"""Tests for rate limiting, caches and the /stats endpoint."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from regulens import main
from regulens.embeddings import HashingEmbedder
from regulens.protection import (
    CachedQueryEmbedder,
    SlidingWindowLimiter,
    TTLCache,
    normalise_question,
)
from regulens.qa import QAConfig
from tests.conftest import QA_RETRIEVAL, requires_db
from tests.test_qa import answering_llm


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_blocks_after_limit_and_recovers() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window_s=60, clock=clock)
    assert limiter.check("a") is None
    assert limiter.check("a") is None
    wait = limiter.check("a")
    assert wait == pytest.approx(60)
    assert limiter.check("b") is None  # other clients are unaffected
    clock.now += 61
    assert limiter.check("a") is None  # window slid past the old calls


def test_ttl_cache_expires_and_evicts() -> None:
    clock = FakeClock()
    cache = TTLCache(max_items=2, ttl_s=10, clock=clock)
    cache.put("x", 1)
    cache.put("y", 2)
    cache.put("z", 3)  # evicts the least recently used ("x")
    assert cache.get("x") is None and cache.get("z") == 3
    clock.now += 11
    assert cache.get("z") is None  # expired
    assert cache.hits == 1 and cache.misses == 2


def test_normalise_question() -> None:
    assert normalise_question("  What is an SRTO?? ") == normalise_question("what is an  srto")


def test_query_embedder_cache() -> None:
    inner = HashingEmbedder()
    calls = []
    original = inner.embed_query
    inner.embed_query = lambda text: calls.append(text) or original(text)  # type: ignore[method-assign]
    cached = CachedQueryEmbedder(inner)
    assert cached.embed_query("hello") == cached.embed_query("hello")
    assert calls == ["hello"]
    assert cached.dim == inner.dim


@pytest.fixture
def client() -> Iterator[TestClient]:
    main.ANSWER_CACHE._data.clear()
    main.app.dependency_overrides = {
        main.get_api_embedder: HashingEmbedder,
        main.get_llm: answering_llm,
        main.get_qa_config: lambda: QAConfig(retrieval=QA_RETRIEVAL, min_retrieval_score=0.1),
    }
    yield TestClient(main.app)
    main.app.dependency_overrides = {}


@requires_db
def test_repeated_question_served_from_answer_cache(client: TestClient, qa_index: None) -> None:
    first = client.post("/ask", json={"question": "How fast must a bank notify MAS?"}).json()
    second = client.post("/ask", json={"question": "how fast must a bank notify MAS"}).json()
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["answer"] == first["answer"]


@requires_db
def test_ask_rate_limit_returns_429(
    client: TestClient, qa_index: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main.ASK_LIMIT, "limit", 1)
    monkeypatch.setattr(main.ASK_LIMIT, "_calls", {})
    assert client.post("/ask", json={"question": "Who approves the framework?"}).status_code == 200
    blocked = client.post("/ask", json={"question": "Who approves the framework?"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


@requires_db
def test_stats_reports_usage_and_eval(client: TestClient) -> None:
    body = client.get("/stats").json()
    assert {"queries", "latency_p50_ms", "avg_cost_usd"} <= body["usage"].keys()
    assert "ask" in body["rate_limits"]
    if body["latest_retrieval_eval"]:
        assert "retrieval_hit_rate" in body["latest_retrieval_eval"]["metrics"]


def test_sources_endpoint_lists_annual_reports(client: TestClient) -> None:
    body = client.get("/sources", params={"doc_type": "annual_report"}).json()
    assert all(item["doc_type"] == "annual_report" for item in body)


def test_client_key_uses_the_proxy_appended_ip() -> None:
    from starlette.requests import Request

    from regulens.protection import client_key

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")],  # spoofed, then real
        "client": ("10.0.0.1", 1234),
    }
    assert client_key(Request(scope)) == "203.0.113.9"


def test_limiter_forgets_idle_clients() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=5, window_s=60, clock=clock)
    limiter.MAX_KEYS = 3
    for ip in ["a", "b", "c"]:
        limiter.check(ip)
    clock.now += 61
    limiter.check("d")  # table is full: idle a/b/c are pruned first
    assert set(limiter._calls) == {"d"}
