"""Compare saved eval runs with confidence intervals and paired wins/losses.

With ~80 questions, one question moves hit@5 by 1.25 points, so small
differences can be noise. This script shows, for each run:
- hit@k and MRR,
- a 95% bootstrap confidence interval for hit@k (resample questions 2,000 times),
- versus the FIRST run: how many questions it newly gets right ("+") and how
  many it newly gets wrong ("-"). A change that is +9/-1 is convincing;
  +3/-2 is not.

Usage:
    python eval/compare_runs.py baseline-vector-k5 exp-hybrid-k5 exp-heading-hybrid-k5
(names match the end of the file name in eval/results/; the latest file wins)
"""

import json
import random
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def load(name: str) -> dict:
    matches = sorted(RESULTS.glob(f"*_{name}.json"))
    if not matches:
        raise SystemExit(f"No run named {name!r} in {RESULTS}")
    return json.loads(matches[-1].read_text(encoding="utf-8"))


def hits(run: dict) -> dict[str, bool]:
    return {
        r["id"]: bool(r["retrieval_hit"]) for r in run["results"] if r["category"] != "out_of_scope"
    }


def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def main(names: list[str]) -> int:
    runs = [load(n) for n in names]
    base = hits(runs[0])
    print(f"{'run':<40} {'n':>3} {'hit@k':>6} {'95% CI':>13} {'MRR':>6} {'vs first':>9}")
    for name, run in zip(names, runs, strict=True):
        h = hits(run)
        values = [float(v) for v in h.values()]
        lo, hi = bootstrap_ci(values)
        m = run["metrics"]
        gained = sum(h[i] and not base.get(i, False) for i in h)
        lost = sum(base.get(i, False) and not h[i] for i in h)
        print(
            f"{name:<40} {len(values):>3} {m['retrieval_hit_rate']:>6.3f} "
            f"[{lo:.3f},{hi:.3f}] {m['mrr']:>6.3f} {f'+{gained}/-{lost}':>9}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
