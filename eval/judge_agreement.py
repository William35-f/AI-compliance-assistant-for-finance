"""Check that the LLM judge agrees with a human reviewer.

An LLM judge is only useful if it grades like a person would. This script
samples judged answers from a run so a human can grade them blind, then
measures how often the two agree.

Usage:
    python eval/judge_agreement.py sample --run eval/results/<run>.json --n 20
        -> writes eval/judge_review.csv; fill in the `human_score` column (0, 0.5 or 1)
           WITHOUT looking at `judge_score` first (hide that column while grading).
    python eval/judge_agreement.py score
        -> prints and saves agreement to eval/results/judge_agreement.json
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REVIEW_CSV = EVAL_DIR / "judge_review.csv"
FIELDS = [
    "id",
    "question",
    "expected_answer",
    "answer",
    "human_score",
    "judge_score",
    "judge_reasoning",
    "reviewer",
    "run",
]


def sample(run_path: Path, n: int, seed: int) -> int:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    judged = [
        r
        for r in run["results"]
        if r["correctness"] is not None and not r["refused"]  # refusals are scored by rule
    ]
    picked = random.Random(seed).sample(judged, min(n, len(judged)))
    with REVIEW_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in sorted(picked, key=lambda r: r["id"]):
            writer.writerow(
                {
                    "id": r["id"],
                    "question": r["question"],
                    "expected_answer": r["expected_answer"],
                    "answer": r["answer"],
                    "human_score": "",
                    "judge_score": r["correctness"],
                    "judge_reasoning": r["judge_reasoning"],
                    "reviewer": "",
                    "run": run["run"],
                }
            )
    print(f"Wrote {len(picked)} rows to {REVIEW_CSV.name}. Fill in human_score (0/0.5/1).")
    return 0


def score() -> int:
    with REVIEW_CSV.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["human_score"].strip()]
    if not rows:
        print("No human_score values filled in yet.")
        return 1
    pairs = [(float(r["human_score"]), float(r["judge_score"])) for r in rows]
    exact = sum(h == j for h, j in pairs) / len(pairs)
    within_half = sum(abs(h - j) <= 0.5 for h, j in pairs) / len(pairs)
    disagreements = [
        {"id": r["id"], "human": float(r["human_score"]), "judge": float(r["judge_score"])}
        for r in rows
        if float(r["human_score"]) != float(r["judge_score"])
    ]
    result = {
        "run": rows[0]["run"],
        "reviewer": sorted({r["reviewer"] for r in rows}),
        "n": len(pairs),
        "exact_agreement": round(exact, 3),
        "agreement_within_0.5": round(within_half, 3),
        "mean_human": round(sum(h for h, _ in pairs) / len(pairs), 3),
        "mean_judge": round(sum(j for _, j in pairs) / len(pairs), 3),
        "disagreements": disagreements,
    }
    out = EVAL_DIR / "results" / "judge_agreement.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--run", type=Path, required=True)
    s.add_argument("--n", type=int, default=20)
    s.add_argument("--seed", type=int, default=7)
    sub.add_parser("score")
    args = parser.parse_args()
    return sample(args.run, args.n, args.seed) if args.command == "sample" else score()


if __name__ == "__main__":
    sys.exit(main())
