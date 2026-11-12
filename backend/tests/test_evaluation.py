"""Tests for the evaluation harness (scoring logic only, no LLM or DB)."""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from regulens.evaluation import (
    ChunkLocation,
    CitationJudgement,
    EvalQuestion,
    Judgement,
    QuestionResult,
    append_summary_row,
    judge,
    load_questions,
    percentile,
    retrieval_scores,
    summarise,
)
from regulens.llm import FakeLLM
from regulens.qa import AskResponse, Citation, TokenUsage


def question(**overrides) -> EvalQuestion:
    data = {
        "id": "q1",
        "question": "How soon must a bank notify MAS?",
        "expected_answer": "Within one hour.",
        "expected_source_id": "mas_bcm_2022",
        "expected_pages": [19],
        "category": "factual",
    } | overrides
    return EvalQuestion(**data)


def loc(source: str, start: int, end: int | None = None, cid: int = 0) -> ChunkLocation:
    return ChunkLocation(chunk_id=cid, source_id=source, page_start=start, page_end=end or start)


# --------------------------------------------------------------------------- questions


def test_load_questions_skips_comments_and_rejects_duplicates(tmp_path: Path) -> None:
    line = question().model_dump_json()
    path = tmp_path / "q.jsonl"
    path.write_text(f"// a comment\n{line}\n\n", encoding="utf-8")
    assert [q.id for q in load_questions(path)] == ["q1"]

    path.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_questions(path)


def test_out_of_scope_must_have_no_source() -> None:
    with pytest.raises(ValueError):
        question(category="out_of_scope")
    oos = question(category="out_of_scope", expected_source_id=None, expected_pages=[])
    assert oos.expected_locations() == {}


def test_multi_source_needs_page_dict() -> None:
    with pytest.raises(ValueError):
        question(category="multi-hop", expected_source_id=["a", "b"], expected_pages=[1])


# --------------------------------------------------------------------------- retrieval


def test_hit_when_page_inside_chunk_range() -> None:
    q = question(expected_pages=[19])
    retrieved = [loc("other", 19), loc("mas_bcm_2022", 18, 20)]
    assert retrieval_scores(q, retrieved) == (True, 0.5)


def test_miss_when_right_document_wrong_page() -> None:
    assert retrieval_scores(question(), [loc("mas_bcm_2022", 3)]) == (False, 0.0)


def test_multi_hop_needs_every_source() -> None:
    q = question(
        category="multi-hop",
        expected_source_id=["a", "b"],
        expected_pages={"a": [1], "b": [5]},
    )
    assert retrieval_scores(q, [loc("a", 1), loc("x", 2), loc("b", 5)]) == (
        True,
        pytest.approx(1 / 3),
    )
    assert retrieval_scores(q, [loc("a", 1)]) == (False, 0.0)


# --------------------------------------------------------------------------- judge


def response_with_markers(*markers: int) -> AskResponse:
    citations = [
        Citation(
            marker=m,
            chunk_id=m,
            source_id="s",
            title="T",
            page=1,
            page_end=1,
            heading=None,
            quote="q",
            quote_verified=True,
        )
        for m in markers
    ]
    return AskResponse(
        answer="x",
        citations=citations,
        refused=False,
        retrieved_chunk_ids=[],
        top_score=0.9,
        latency_ms=1,
        tokens=TokenUsage(input=1, output=1),
        cost_usd=0.0,
        model="m",
    )


def test_judge_counts_missing_or_unknown_markers_as_unsupported() -> None:
    def respond(system: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        assert "Reference answer:\nWithin one hour." in prompt
        return Judgement(
            reasoning="ok",
            correctness=1,
            citations=[
                CitationJudgement(marker=1, supported=True),
                CitationJudgement(marker=9, supported=True),  # no such marker: ignored
            ],
        )

    verdict = judge(FakeLLM(respond), question(), response_with_markers(1, 2), {1: "p1", 2: "p2"})
    assert [(c.marker, c.supported) for c in verdict.citations] == [(1, True), (2, False)]


# --------------------------------------------------------------------------- metrics


def result(**overrides) -> QuestionResult:
    data = {
        "id": "q",
        "category": "factual",
        "question": "?",
        "expected_answer": "!",
        "answer": "a",
        "refused": False,
        "refusal_reason": None,
        "top_score": 0.8,
        "retrieved": [],
        "retrieval_hit": True,
        "reciprocal_rank": 1.0,
        "correctness": 1.0,
        "citations_total": 2,
        "citations_supported": 2,
        "latency_ms": 100,
        "cost_usd": 0.001,
    } | overrides
    return QuestionResult(**data)


def test_percentile_nearest_rank() -> None:
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile([], 50) is None


def test_summarise_combines_categories() -> None:
    metrics = summarise(
        [
            result(id="a"),
            result(
                id="b",
                correctness=0.0,
                refused=True,
                retrieval_hit=False,
                reciprocal_rank=0.0,
                citations_total=0,
                citations_supported=0,
            ),
            result(id="c", category="multi-hop", correctness=0.5, citations_supported=1),
            result(
                id="d",
                category="out_of_scope",
                refused=True,
                retrieval_hit=None,
                correctness=None,
                citations_total=0,
                citations_supported=0,
            ),
        ]
    )
    assert metrics["retrieval_hit_rate"] == pytest.approx(2 / 3)
    assert metrics["answer_correctness"] == pytest.approx(1.5 / 3)
    assert metrics["correctness_multi_hop"] == 0.5
    assert metrics["citation_accuracy"] == pytest.approx(3 / 4)
    assert metrics["oos_refusal_rate"] == 1.0
    assert metrics["false_refusal_rate"] == pytest.approx(1 / 3)


def test_summary_row_appended(tmp_path: Path) -> None:
    path = tmp_path / "summary.md"
    append_summary_row(path, "run1", {"retrieval_hit_rate": 0.8, "avg_cost_usd": 0.0001}, "first")
    append_summary_row(path, "run2", {"retrieval_hit_rate": 0.9}, "second")
    text = path.read_text(encoding="utf-8")
    assert text.count("| run") == 3  # header + 2 rows
    assert "| run1 | – | 0.800 |" in text
    assert "0.000100" in text


def test_example_questions_file_is_valid() -> None:
    path = Path(__file__).resolve().parents[2] / "eval" / "questions.jsonl"
    if path.exists():
        questions = load_questions(path)
        assert questions
        assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])
