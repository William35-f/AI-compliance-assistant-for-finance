"""Tests for question answering: quote checks, answer assembly, guardrails, logging."""

import pytest
from pydantic import BaseModel

from regulens import db
from regulens.embeddings import HashingEmbedder
from regulens.llm import FakeLLM
from regulens.qa import (
    REFUSAL_TEXT,
    LLMAnswer,
    LLMCitation,
    LLMClaim,
    QAConfig,
    answer_question,
    assemble_answer,
    build_prompt,
    checked_summary,
    verify_quote,
)
from regulens.retrieval import RetrievedChunk
from tests.conftest import QA_RETRIEVAL, requires_db

CHUNK_TEXT = (
    "A bank should notify MAS within one hour of discovering a severe incident. "
    "The notification should be followed by a root-cause report."
)


def chunk(id_: int = 1, text: str = CHUNK_TEXT) -> RetrievedChunk:
    return RetrievedChunk(
        id_, "doc", "Doc Title", "regulation", 3, 4, "1 Notification", text, 0.8, 0.8
    )


def claim(text: str, *cites: tuple[str, str]) -> LLMClaim:
    return LLMClaim(text=text, citations=[LLMCitation(chunk_id=c, quote=q) for c, q in cites])


# --------------------------------------------------------------------------- unit


def test_verify_quote_accepts_verbatim_with_different_quotes_and_spacing() -> None:
    quote = "notify  MAS within one hour"
    assert verify_quote(quote, CHUNK_TEXT) == (quote, True)
    assert verify_quote("“root-cause report.”", CHUNK_TEXT)[1] is True


def test_verify_quote_replaces_paraphrase_with_real_sentence() -> None:
    shown, verified = verify_quote("banks must tell MAS in one hour", CHUNK_TEXT)
    assert verified is False
    assert shown.startswith("A bank should notify MAS")  # real source text is displayed


def test_assemble_answer_numbers_citations_and_drops_bad_ones() -> None:
    llm_answer = LLMAnswer(
        answerable=True,
        claims=[
            claim("Banks must notify MAS within an hour.", ("C1", "notify MAS within one hour")),
            claim("A report follows.", ("c1", "root-cause report"), ("C9", "made up")),
            claim("Unsupported claim.", ("C7", "nothing")),  # cites a passage that doesn't exist
        ],
    )
    text, citations = assemble_answer(llm_answer, [chunk()])
    assert text == "Banks must notify MAS within an hour. [1] A report follows. [2]"
    assert [c.marker for c in citations] == [1, 2]
    assert all(c.quote_verified for c in citations)
    assert citations[0].page == 3 and citations[0].page_end == 4


def test_same_quote_reuses_marker() -> None:
    same = ("C1", "notify MAS within one hour")
    text, citations = assemble_answer(
        LLMAnswer(answerable=True, claims=[claim("First.", same), claim("Second.", same)]),
        [chunk()],
    )
    assert text == "First. [1] Second. [1]"
    assert len(citations) == 1


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("Notify MAS within  1 hour.", "Notify MAS within 1 hour."),  # whitespace tidied
        ("Notify MAS within 2 hours.", None),  # a number the claims don't contain
        ("", None),
        ("x" * 200, None),  # too long for a heading
    ],
)
def test_checked_summary_keeps_only_numbers_the_claims_support(
    summary: str, expected: str | None
) -> None:
    answer = "Banks must notify MAS within 1 hour. [1] A report follows within 14 days. [2]"
    assert checked_summary(summary, answer) == expected


def test_checked_summary_ignores_citation_markers() -> None:
    # "[2]" is a marker, not a fact, so it can't vouch for a "2" in the summary.
    assert checked_summary("Report within 2 days.", "Report within 14 days. [2]") is None


def test_build_prompt_labels_passages_with_title_and_pages() -> None:
    prompt = build_prompt("When?", [chunk(), chunk(2)])
    assert '<passage id="C1">' in prompt and '<passage id="C2">' in prompt
    assert "[Doc Title | pages 3-4 | section: 1 Notification]" in prompt
    assert prompt.rstrip().endswith("Question: When?")


# --------------------------------------------------------------------------- integration


def answering_llm() -> FakeLLM:
    """Fake LLM that answers from passage C1 with a verbatim quote."""

    def respond(system: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        return LLMAnswer(
            answerable=True,
            claims=[claim("Notify MAS within one hour.", ("C1", "notify MAS within one hour"))],
            summary="Notify MAS within one hour.",
        )

    return FakeLLM(respond)


@requires_db
def test_answers_with_citation_and_logs(qa_index: None, embedder: HashingEmbedder) -> None:
    llm = answering_llm()
    config = QAConfig(retrieval=QA_RETRIEVAL, min_retrieval_score=0.1)
    with db.connect() as conn:
        result = answer_question(
            conn, "How fast must a bank notify MAS?", embedder, llm, config, "test"
        )
        logged = conn.execute(
            "SELECT refused, retrieved_chunk_ids, input_tokens FROM query_logs "
            "WHERE origin = 'test' AND index_name = %s",
            (QA_RETRIEVAL.index_name,),
        ).fetchone()

    assert not result.refused
    assert result.answer == "Notify MAS within one hour. [1]"
    assert result.summary == "Notify MAS within one hour."
    assert result.citations[0].source_id == "test_qa_doc"
    assert result.citations[0].page == 1
    assert result.citations[0].quote_verified
    assert result.tokens.input == 100 and result.cost_usd > 0
    assert "notify MAS within one hour" in llm.calls[0]  # retrieved text reached the prompt
    assert logged == (False, result.retrieved_chunk_ids, 100)


@requires_db
def test_low_retrieval_score_refuses_without_calling_llm(
    qa_index: None, embedder: HashingEmbedder
) -> None:
    llm = answering_llm()
    config = QAConfig(retrieval=QA_RETRIEVAL, min_retrieval_score=0.99)
    with db.connect() as conn:
        result = answer_question(
            conn, "What is the capital of France?", embedder, llm, config, None
        )
    assert result.refused and result.refusal_reason == "low_retrieval_score"
    assert result.answer == REFUSAL_TEXT
    assert llm.calls == []  # no tokens spent
    assert result.disclaimer


@pytest.mark.parametrize(
    ("llm_answer", "reason"),
    [
        (LLMAnswer(answerable=False, claims=[]), "model_declined"),
        (LLMAnswer(answerable=True, claims=[claim("Uncited.", ("C9", "x"))]), "no_valid_citations"),
    ],
)
@requires_db
def test_refuses_when_model_declines_or_cites_nothing(
    qa_index: None, embedder: HashingEmbedder, llm_answer: LLMAnswer, reason: str
) -> None:
    llm = FakeLLM(lambda *_: llm_answer)
    config = QAConfig(retrieval=QA_RETRIEVAL, min_retrieval_score=0.0)
    with db.connect() as conn:
        result = answer_question(
            conn, "How fast must a bank notify MAS?", embedder, llm, config, None
        )
    assert result.refused and result.refusal_reason == reason
    assert result.citations == []
    assert result.retrieved_chunk_ids  # still reported, useful for debugging
