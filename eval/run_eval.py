"""Run the evaluation set against the Q&A pipeline and record the results.

Usage (repo root, venv active, Postgres running, index ingested):
    python eval/run_eval.py --name baseline                      # full run (uses Gemini)
    python eval/run_eval.py --name baseline --retrieval-only     # hit@k/MRR only, no LLM
    python eval/run_eval.py --name smoke --limit 20              # first 20 questions

Each run is saved to eval/results/<timestamp>_<name>.json and summarised as one
row in eval/results/summary.md. LLM calls are cached in Postgres, so re-running
an identical configuration is free (and resumes after a quota stop).
"""

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from regulens import db
from regulens.config import get_settings
from regulens.embeddings import get_embedder
from regulens.evaluation import (
    ChunkLocation,
    QuestionResult,
    append_summary_row,
    chunk_locations,
    judge,
    load_questions,
    retrieval_scores,
    safe_name,
    save_run,
    summarise,
)
from regulens.index_configs import INDEX_CONFIGS
from regulens.llm import LLMQuotaExceeded, make_llm
from regulens.qa import QAConfig, answer_question, top_similarity
from regulens.reranker import get_reranker
from regulens.retrieval import RETRIEVAL_MODES, RetrievalConfig, retrieve

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    p = argparse.ArgumentParser(description="Evaluate ReguLens Q&A.")
    p.add_argument("--name", required=True, help="config name used in result file names")
    p.add_argument("--questions", type=Path, default=EVAL_DIR / "questions.jsonl")
    p.add_argument("--index", default=settings.default_index, choices=INDEX_CONFIGS)
    p.add_argument("--mode", default="vector", choices=RETRIEVAL_MODES)
    p.add_argument("--k", type=int, default=settings.retrieval_k)
    p.add_argument("--rerank", action="store_true", help="re-order candidates with a cross-encoder")
    p.add_argument("--candidates", type=int, default=30, help="per-ranker list length (hybrid)")
    p.add_argument("--min-score", type=float, default=settings.min_retrieval_score)
    p.add_argument("--limit", type=int, help="only the first N questions")
    p.add_argument("--category", choices=["factual", "multi-hop", "out_of_scope"])
    p.add_argument("--retrieval-only", action="store_true", help="skip the LLM (hit@k, MRR)")
    p.add_argument("--notes", default="", help="free text for the summary row")
    p.add_argument("--no-summary", action="store_true", help="don't append to summary.md")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    questions = load_questions(args.questions)
    if args.category:
        questions = [q for q in questions if q.category == args.category]
    if args.limit:
        questions = questions[: args.limit]

    retrieval = RetrievalConfig(
        index_name=args.index,
        k=args.k,
        mode=args.mode,
        rerank=args.rerank,
        candidates=args.candidates,
    )
    reranker = get_reranker() if args.rerank else None
    qa_config = QAConfig(retrieval=retrieval, min_retrieval_score=args.min_score)
    embedder = get_embedder()
    answer_llm = judge_llm = None
    if not args.retrieval_only:
        answer_llm = make_llm(settings.gemini_model)
        judge_llm = make_llm(settings.gemini_judge_model)

    print(f"Run '{args.name}': {len(questions)} questions, {retrieval}")
    results: list[QuestionResult] = []
    stopped_early = None
    started = time.perf_counter()

    with db.connect(autocommit=True) as conn:
        for n, q in enumerate(questions, start=1):
            in_scope = q.category != "out_of_scope"
            try:
                if args.retrieval_only:
                    chunks = retrieve(conn, embedder, q.question, retrieval, reranker)
                    retrieved = [
                        ChunkLocation(
                            chunk_id=c.id,
                            source_id=c.source_id,
                            page_start=c.page_start,
                            page_end=c.page_end,
                        )
                        for c in chunks
                    ]
                    hit, rr = retrieval_scores(q, retrieved) if in_scope else (None, None)
                    result = QuestionResult(
                        id=q.id,
                        category=q.category,
                        question=q.question,
                        expected_answer=q.expected_answer,
                        answer="",
                        refused=False,
                        refusal_reason=None,
                        top_score=top_similarity(chunks),
                        retrieved=retrieved,
                        retrieval_hit=hit,
                        reciprocal_rank=rr,
                        correctness=None,
                    )
                else:
                    assert answer_llm is not None and judge_llm is not None
                    response = answer_question(
                        conn,
                        q.question,
                        embedder,
                        answer_llm,
                        qa_config,
                        log_origin="eval",
                        reranker=reranker,
                    )
                    retrieved = chunk_locations(conn, response.retrieved_chunk_ids)
                    hit, rr = retrieval_scores(q, retrieved) if in_scope else (None, None)
                    correctness, reasoning, supported = None, None, 0
                    if in_scope and response.refused:
                        correctness, reasoning = 0.0, "Refused an in-scope question."
                    elif in_scope:
                        ids = [c.chunk_id for c in response.citations]
                        passages = dict(
                            conn.execute(
                                "SELECT id, text FROM chunks WHERE id = ANY(%s)", (ids,)
                            ).fetchall()
                        )
                        verdict = judge(judge_llm, q, response, passages)
                        correctness, reasoning = float(verdict.correctness), verdict.reasoning
                        supported = sum(c.supported for c in verdict.citations)
                    result = QuestionResult(
                        id=q.id,
                        category=q.category,
                        question=q.question,
                        expected_answer=q.expected_answer,
                        answer=response.answer,
                        refused=response.refused,
                        refusal_reason=response.refusal_reason,
                        top_score=response.top_score,
                        retrieved=retrieved,
                        retrieval_hit=hit,
                        reciprocal_rank=rr,
                        correctness=correctness,
                        judge_reasoning=reasoning,
                        citations_total=len(response.citations) if in_scope else 0,
                        citations_supported=supported,
                        unverified_quotes=sum(not c.quote_verified for c in response.citations)
                        if in_scope
                        else 0,
                        latency_ms=response.latency_ms,
                        cost_usd=response.cost_usd,
                        cached=response.cached,
                    )
            except LLMQuotaExceeded as exc:
                stopped_early = str(exc)
                print(f"\nStopped early: {exc}. Results so far are saved; re-run later to resume.")
                break
            results.append(result)
            mark = {True: "hit ", False: "MISS", None: "    "}[result.retrieval_hit]
            score = "" if result.correctness is None else f" correct={result.correctness}"
            refused = " REFUSED" if result.refused else ""
            print(f"  [{n:>3}/{len(questions)}] {q.id:<10} {mark}{score}{refused}", flush=True)

    metrics = summarise(results)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = safe_name(args.name)
    out = RESULTS_DIR / f"{timestamp}_{run_name}.json"
    save_run(
        out,
        {
            "run": run_name,
            "timestamp": timestamp,
            "complete": stopped_early is None,
            "stopped_reason": stopped_early,
            "config": {
                "index": args.index,
                "mode": args.mode,
                "k": args.k,
                "rerank": args.rerank,
                "reranker_model": settings.reranker_model if args.rerank else None,
                "candidates": args.candidates,
                "min_retrieval_score": args.min_score,
                "retrieval_only": args.retrieval_only,
                "answer_model": None if args.retrieval_only else settings.gemini_model,
                "judge_model": None if args.retrieval_only else settings.gemini_judge_model,
                "embedding_model": settings.embedding_model,
                "questions_file": args.questions.name,
            },
            "metrics": metrics,
            "duration_s": round(time.perf_counter() - started, 1),
            "results": [r.model_dump() for r in results],
        },
    )
    if not args.no_summary:
        notes = args.notes + (" (retrieval only)" if args.retrieval_only else "")
        if stopped_early:
            notes += " INCOMPLETE"
        append_summary_row(RESULTS_DIR / "summary.md", f"{timestamp}_{run_name}", metrics, notes)

    print("\nMetrics:")
    for key, value in metrics.items():
        print(f"  {key:<22} {value}")
    print(f"\nSaved {out.relative_to(EVAL_DIR.parent)}")
    return 1 if stopped_early else 0


if __name__ == "__main__":
    sys.exit(main())
