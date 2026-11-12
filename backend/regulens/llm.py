"""LLM access behind one small interface: `generate_json(system, prompt, schema)`.

Everything else in ReguLens calls only this interface, so the provider can be
swapped (Gemini today; a FakeLLM in tests) without touching the Q&A logic.

Implementations:
- GeminiClient: Google Gemini with structured JSON output, client-side request
  pacing (the free tier allows only a few requests per minute) and retries on
  temporary errors.
- CachedLLM: wraps any client and stores responses in Postgres, keyed by a hash
  of (model, system prompt, prompt, schema). Re-running an eval costs nothing.
- FakeLLM: returns canned responses, for tests.
"""

import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from regulens import db
from regulens.config import get_settings

logger = logging.getLogger("regulens.llm")
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMUsage:
    model: str
    input_tokens: int
    output_tokens: int  # includes "thinking" tokens, which are billed as output
    latency_ms: int
    cached: bool = False


class LLMError(RuntimeError):
    """The LLM call failed (after retries) or returned invalid output."""


class LLMQuotaExceeded(LLMError):
    """The daily free-tier quota is used up; retrying today will not help."""


class LLMClient(Protocol):
    model: str

    def generate_json(self, *, system: str, prompt: str, schema: type[T]) -> tuple[T, LLMUsage]:
        """Return the model's answer parsed into `schema`, plus token usage."""
        ...


# --------------------------------------------------------------------------- Gemini


class _Pacer:
    """Spaces out requests to stay under a requests-per-minute limit (thread-safe)."""

    def __init__(self, requests_per_minute: float):
        self._interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._lock = threading.Lock()
        self._next_time = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next_time - now
            self._next_time = max(now, self._next_time) + self._interval
        if delay > 0:
            time.sleep(delay)


_pacers: dict[str, _Pacer] = {}  # one per model: free-tier limits are per model


def _retry_delay_seconds(error: Exception, attempt: int) -> float:
    """Use the server's suggested retry delay if present, else exponential backoff."""
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", str(error))
    if match:
        return float(match.group(1)) + 1.0
    return min(60.0, 2.0 ** (attempt + 1))


class GeminiClient:
    def __init__(
        self,
        model: str,
        api_key: str,
        requests_per_minute: float,
        max_retries: int = 4,
        thinking_level: str | None = None,
    ):
        from google import genai  # imported here so tests don't need network setup

        self.model = model
        self._client = genai.Client(api_key=api_key)
        self._max_retries = max_retries
        self._thinking_level = thinking_level
        self._pacer = _pacers.setdefault(model, _Pacer(requests_per_minute))

    def generate_json(self, *, system: str, prompt: str, schema: type[T]) -> tuple[T, LLMUsage]:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.0,  # as deterministic as possible: answers and evals are repeatable
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            thinking_config=(
                types.ThinkingConfig(thinking_level=self._thinking_level)
                if self._thinking_level
                else None
            ),
        )
        for attempt in range(self._max_retries + 1):
            self._pacer.wait()
            started = time.perf_counter()
            try:
                response = self._client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                break
            except (errors.ClientError, errors.ServerError) as exc:
                code = getattr(exc, "code", None)
                if code == 429 and "PerDay" in str(exc):
                    raise LLMQuotaExceeded(
                        f"Daily Gemini quota exhausted for {self.model}"
                    ) from exc
                retryable = code in (429, 500, 503, 504)
                if not retryable or attempt == self._max_retries:
                    raise LLMError(f"Gemini call failed ({code}): {exc}") from exc
                delay = _retry_delay_seconds(exc, attempt)
                logger.warning(
                    "Gemini %s, retrying in %.0fs (attempt %d)", code, delay, attempt + 1
                )
                time.sleep(delay)
        latency_ms = int((time.perf_counter() - started) * 1000)

        text = response.text or ""
        try:
            parsed = schema.model_validate_json(text)
        except ValueError as exc:
            raise LLMError(
                f"Model returned invalid JSON for {schema.__name__}: {text[:300]}"
            ) from exc

        meta = response.usage_metadata
        usage = LLMUsage(
            model=self.model,
            input_tokens=(meta.prompt_token_count or 0) if meta else 0,
            output_tokens=((meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0))
            if meta
            else 0,
            latency_ms=latency_ms,
        )
        return parsed, usage


# --------------------------------------------------------------------------- Cache


class CachedLLM:
    """Wraps a client; identical requests are answered from the `llm_cache` table.

    A cache hit returns the ORIGINAL usage and latency (flagged cached=True), so
    eval statistics stay those of the real call.
    """

    def __init__(self, inner: LLMClient):
        self.inner = inner
        self.model = inner.model

    @staticmethod
    def cache_key(model: str, system: str, prompt: str, schema: type[BaseModel]) -> str:
        payload = json.dumps(
            [model, system, prompt, schema.model_json_schema()], sort_keys=True
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def generate_json(self, *, system: str, prompt: str, schema: type[T]) -> tuple[T, LLMUsage]:
        key = self.cache_key(self.model, system, prompt, schema)
        with db.connect() as conn:
            row = conn.execute(
                "SELECT response, input_tokens, output_tokens, latency_ms "
                "FROM llm_cache WHERE key = %s",
                (key,),
            ).fetchone()
        if row:
            usage = LLMUsage(self.model, row[1], row[2], row[3], cached=True)
            return schema.model_validate(row[0]), usage

        parsed, usage = self.inner.generate_json(system=system, prompt=prompt, schema=schema)
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_cache
                    (key, model, response, input_tokens, output_tokens, latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (key) DO NOTHING
                """,
                (
                    key,
                    self.model,
                    parsed.model_dump_json(),
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.latency_ms,
                ),
            )
        return parsed, usage


# --------------------------------------------------------------------------- Fake


class FakeLLM:
    """Test double: `respond(system, prompt, schema)` builds the answer."""

    def __init__(self, respond: Callable[[str, str, type[BaseModel]], BaseModel]):
        self.model = "fake-llm"
        self._respond = respond
        self.calls: list[str] = []

    def generate_json(self, *, system: str, prompt: str, schema: type[T]) -> tuple[T, LLMUsage]:
        self.calls.append(prompt)
        result = self._respond(system, prompt, schema)
        return schema.model_validate(result.model_dump()), LLMUsage(self.model, 100, 20, 5)


# --------------------------------------------------------------------------- Factory


def make_llm(model: str | None = None, cache: bool = True) -> LLMClient:
    """Build the configured LLM client (the answer model unless `model` is given)."""
    settings = get_settings()
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
        raise LLMError("GEMINI_API_KEY is not set. Add it to .env (see .env.example).")
    client: LLMClient = GeminiClient(
        model=model or settings.gemini_model,
        api_key=settings.gemini_api_key.get_secret_value(),
        requests_per_minute=settings.gemini_requests_per_minute,
        thinking_level=settings.gemini_thinking_level,
    )
    return CachedLLM(client) if cache else client


def estimate_cost_usd(usage: LLMUsage) -> float:
    """Cost at the paid-tier list price set in settings (free-tier calls cost $0)."""
    settings = get_settings()
    return round(
        usage.input_tokens / 1e6 * settings.price_input_per_mtok
        + usage.output_tokens / 1e6 * settings.price_output_per_mtok,
        6,
    )


__all__ = [
    "CachedLLM",
    "FakeLLM",
    "GeminiClient",
    "LLMClient",
    "LLMError",
    "LLMQuotaExceeded",
    "LLMUsage",
    "estimate_cost_usd",
    "make_llm",
]
