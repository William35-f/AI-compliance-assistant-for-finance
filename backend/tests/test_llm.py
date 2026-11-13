"""Tests for the LLM layer: retry-delay parsing, pacing and the Postgres cache."""

import time

from pydantic import BaseModel

from regulens import db
from regulens.llm import CachedLLM, FakeLLM, _Pacer, _retry_delay_seconds
from tests.conftest import requires_db


class Echo(BaseModel):
    value: str


def test_retry_delay_uses_server_hint() -> None:
    error = Exception("429 RESOURCE_EXHAUSTED {'retryDelay': '37s'}")
    assert _retry_delay_seconds(error, attempt=0) == 38.0


def test_retry_delay_falls_back_to_exponential_backoff() -> None:
    assert _retry_delay_seconds(Exception("503"), attempt=0) == 2.0
    assert _retry_delay_seconds(Exception("503"), attempt=2) == 8.0
    assert _retry_delay_seconds(Exception("503"), attempt=10) == 60.0  # capped


def test_pacer_spaces_requests() -> None:
    pacer = _Pacer(requests_per_minute=600)  # one request per 0.1 s
    started = time.monotonic()
    for _ in range(3):
        pacer.wait()
    assert time.monotonic() - started >= 0.19


@requires_db
def test_cache_returns_stored_response_without_calling_model() -> None:
    db.init_db()
    fake = FakeLLM(lambda system, prompt, schema: Echo(value=prompt.upper()))
    fake.model = f"fake-cache-test-{time.time_ns()}"  # unique key per test run
    cached = CachedLLM(fake)
    try:
        first, usage1 = cached.generate_json(system="s", prompt="hello", schema=Echo)
        second, usage2 = cached.generate_json(system="s", prompt="hello", schema=Echo)
        assert first == second == Echo(value="HELLO")
        assert len(fake.calls) == 1  # second answer came from Postgres
        assert not usage1.cached and usage2.cached
        assert usage2.input_tokens == usage1.input_tokens  # original usage is kept

        cached.generate_json(system="s", prompt="different", schema=Echo)
        assert len(fake.calls) == 2  # a different prompt is a cache miss
    finally:
        with db.connect() as conn:
            conn.execute("DELETE FROM llm_cache WHERE model = %s", (fake.model,))


def test_gemini_client_retries_network_errors(monkeypatch) -> None:
    """A dropped connection (e.g. DNS failure) is retried instead of ending an eval run."""
    from types import SimpleNamespace

    from regulens import llm

    error_cls = llm._network_errors()[0]
    calls = {"n": 0}

    def flaky_generate_content(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise error_cls("getaddrinfo failed")
        return SimpleNamespace(text='{"value": "ok"}', usage_metadata=None)

    client = llm.GeminiClient.__new__(llm.GeminiClient)
    client.model = "test-model"
    client._max_retries = 2
    client._thinking_level = None
    client._pacer = _Pacer(requests_per_minute=0)
    client._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=flaky_generate_content)
    )
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    parsed, _usage = client.generate_json(system="s", prompt="p", schema=Echo)
    assert parsed.value == "ok"
    assert calls["n"] == 2
