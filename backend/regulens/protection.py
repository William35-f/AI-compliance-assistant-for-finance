"""Protection for a public demo API: rate limiting and caching.

Rate limiting: a sliding window per client IP and endpoint. The public demo
runs on a free Gemini key with a small daily quota, so a single visitor (or
bot) must not be able to burn it. In-memory state is fine for one server
process; with several replicas this would move to Redis.

Caching happens in three layers, cheapest first:
1. `AnswerCache`: identical question + same config -> the previous full answer
   (skips embedding, retrieval and the LLM). Short TTL so changes show up.
2. `CachedQueryEmbedder`: identical question text -> the previous embedding
   (embedding a query costs ~15 ms of CPU).
3. `CachedLLM` (llm.py, in Postgres): identical prompt -> the previous LLM
   response, which survives restarts and is shared with the eval harness.
"""

import re
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Sequence

from fastapi import HTTPException, Request, status

from regulens.embeddings import Embedder

# --------------------------------------------------------------------------- rate limiting


class SlidingWindowLimiter:
    """Allow at most `limit` calls per `window_s` seconds for each key."""

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._calls: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    MAX_KEYS = 10_000  # forget idle clients beyond this, so memory can't grow forever

    def _prune(self, now: float) -> None:
        idle = [
            k for k, calls in self._calls.items() if not calls or now - calls[-1] >= self.window_s
        ]
        for key in idle:
            del self._calls[key]

    def check(self, key: str) -> float | None:
        """Record a call. Returns None if allowed, else seconds until the next free slot."""
        now = self._clock()
        with self._lock:
            if len(self._calls) >= self.MAX_KEYS:
                self._prune(now)
            calls = self._calls.setdefault(key, deque())
            while calls and now - calls[0] >= self.window_s:
                calls.popleft()
            if len(calls) >= self.limit:
                return self.window_s - (now - calls[0])
            calls.append(now)
            return None


def client_key(request: Request) -> str:
    """Client IP for rate limiting.

    Behind a hosting proxy (Render, Fly) the socket address is the proxy, and the
    proxy APPENDS the real client IP to X-Forwarded-For. We take the LAST entry:
    earlier entries are whatever the client sent, so trusting the first one would
    let anyone dodge the limit by sending a fake header.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(limiter: SlidingWindowLimiter) -> Callable[[Request], None]:
    """FastAPI dependency: raise 429 with Retry-After when the client is over the limit."""

    def dependency(request: Request) -> None:
        wait = limiter.check(client_key(request))
        if wait is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Rate limit: {limiter.limit} requests per {int(limiter.window_s)} s. "
                f"Try again in {int(wait) + 1} s.",
                headers={"Retry-After": str(int(wait) + 1)},
            )

    return dependency


# --------------------------------------------------------------------------- caching


def normalise_question(question: str) -> str:
    """'  What is an SRTO? ' and 'what is an srto' share a cache entry."""
    return re.sub(r"[\s?.!]+$", "", re.sub(r"\s+", " ", question.strip().lower()))


class TTLCache:
    """Small thread-safe LRU cache whose entries expire after `ttl_s` seconds."""

    def __init__(self, max_items: int, ttl_s: float, clock: Callable[[], float] = time.monotonic):
        self.max_items = max_items
        self.ttl_s = ttl_s
        self._clock = clock
        self._data: OrderedDict[object, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: object) -> object | None:
        with self._lock:
            item = self._data.get(key)
            if item is None or self._clock() - item[0] > self.ttl_s:
                self._data.pop(key, None)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return item[1]

    def put(self, key: object, value: object) -> None:
        with self._lock:
            self._data[key] = (self._clock(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)


class CachedQueryEmbedder:
    """Wraps an Embedder; query embeddings are cached (documents are not)."""

    def __init__(self, inner: Embedder, max_items: int = 2048):
        self.inner = inner
        self.name = inner.name
        self.dim = inner.dim
        self._cache = TTLCache(max_items, ttl_s=float("inf"))

    def count_tokens(self, text: str) -> int:
        return self.inner.count_tokens(text)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached  # type: ignore[return-value]
        vector = self.inner.embed_query(text)
        self._cache.put(text, vector)
        return vector
