"""Tests for retrieval: RRF maths, BM25 keyword ranking, hybrid mode and reranking."""

import pytest

from regulens import db
from regulens.embeddings import HashingEmbedder
from regulens.reranker import KeywordOverlapReranker
from regulens.retrieval import RetrievalConfig, bm25_ranking, reciprocal_rank_fusion, retrieve
from tests.conftest import QA_INDEX, requires_db


def test_rrf_rewards_agreement_between_rankers() -> None:
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]], rrf_k=60)
    order = [chunk_id for chunk_id, _ in fused]
    assert order[:2] == [1, 3]  # in both lists near the top
    assert set(order) == {1, 2, 3, 4}
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_rrf_single_list_keeps_order() -> None:
    assert [i for i, _ in reciprocal_rank_fusion([[7, 8, 9]])] == [7, 8, 9]


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError):
        RetrievalConfig(mode="magic")


def config(mode: str, **kw) -> RetrievalConfig:
    return RetrievalConfig(mode=mode, index_name=QA_INDEX.name, k=2, **kw)


@requires_db
def test_bm25_finds_exact_terms(qa_index: None) -> None:
    with db.connect() as conn:
        ranked = bm25_ranking(conn, "board approve framework", config("fts"), n=5)
        text = conn.execute("SELECT text FROM chunks WHERE id = %s", (ranked[0][0],)).fetchone()[0]
    assert "board should approve" in text
    assert ranked[0][1] > 0


@requires_db
def test_bm25_returns_nothing_for_unrelated_words(qa_index: None) -> None:
    with db.connect() as conn:
        assert bm25_ranking(conn, "football bananas", config("fts"), n=5) == []


@requires_db
@pytest.mark.parametrize("mode", ["vector", "fts", "hybrid"])
def test_every_mode_returns_scored_chunks_with_similarity(qa_index: None, mode: str) -> None:
    with db.connect() as conn:
        chunks = retrieve(conn, HashingEmbedder(), "Who must approve the framework?", config(mode))
    assert 1 <= len(chunks) <= 2
    assert all(-1.0 <= c.similarity <= 1.0 for c in chunks)
    assert chunks[0].source_id == "test_qa_doc"


@requires_db
def test_reranker_reorders_candidates(qa_index: None) -> None:
    question = "notify MAS within one hour severe incident"
    with db.connect() as conn:
        chunks = retrieve(
            conn,
            HashingEmbedder(),
            question,
            config("hybrid", rerank=True, rerank_candidates=5),
            KeywordOverlapReranker(),
        )
    assert "notify MAS within one hour" in chunks[0].text
    assert chunks[0].score >= chunks[-1].score


@requires_db
def test_rerank_without_reranker_is_an_error(qa_index: None) -> None:
    with db.connect() as conn, pytest.raises(ValueError, match="reranker"):
        retrieve(conn, HashingEmbedder(), "q?", config("vector", rerank=True))
