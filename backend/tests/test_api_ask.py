"""API tests for POST /ask, with the embedder and LLM replaced by fakes."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from regulens import main
from regulens.embeddings import HashingEmbedder, get_embedder
from regulens.qa import QAConfig
from tests.conftest import QA_RETRIEVAL, requires_db
from tests.test_qa import answering_llm


@pytest.fixture
def client() -> Iterator[TestClient]:
    main.app.dependency_overrides = {
        get_embedder: HashingEmbedder,
        main.get_llm: answering_llm,
        main.get_qa_config: lambda: QAConfig(retrieval=QA_RETRIEVAL, min_retrieval_score=0.1),
    }
    yield TestClient(main.app)
    main.app.dependency_overrides = {}


def test_rejects_too_short_question(client: TestClient) -> None:
    assert client.post("/ask", json={"question": "a"}).status_code == 422


def test_missing_api_key_gives_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from regulens.llm import LLMError

    def no_key() -> None:
        raise LLMError("GEMINI_API_KEY is not set")

    main.app.dependency_overrides[main.get_llm] = main.get_llm  # use the real provider...
    monkeypatch.setattr(main, "make_llm", no_key)  # ...whose factory fails
    response = client.post("/ask", json={"question": "How fast must a bank notify MAS?"})
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


@requires_db
def test_ask_returns_answer_with_citations(client: TestClient, qa_index: None) -> None:
    response = client.post("/ask", json={"question": "How fast must a bank notify MAS?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Notify MAS within one hour. [1]"
    assert body["citations"][0]["source_id"] == "test_qa_doc"
    assert body["citations"][0]["quote"] == "notify MAS within one hour"
    assert body["refused"] is False
    assert body["disclaimer"]
    assert {"retrieved_chunk_ids", "latency_ms", "tokens", "cost_usd"} <= body.keys()
