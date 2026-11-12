"""Validate data/sources.csv and check that every PDF is in data/raw/.

Usage (from the repo root, with the venv active):
    python scripts/check_sources.py

Exits with code 1 if anything is wrong, so it can be used in CI later.
"""

import sys
from collections import Counter

from regulens.config import RAW_DIR, SOURCES_CSV
from regulens.sources import SourcesError, check_files, load_sources


def main() -> int:
    try:
        sources = load_sources(SOURCES_CSV)
    except SourcesError as exc:
        print(exc)
        return 1

    counts = Counter(source.doc_type for source in sources)
    print(
        f"{len(sources)} sources in {SOURCES_CSV.name}: "
        f"{counts['regulation']} regulation, {counts['annual_report']} annual_report"
    )
    for source in sources:
        print(f"  [{source.doc_type:<13}] {source.id:<28} {source.title}")

    problems = check_files(sources, RAW_DIR)
    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    if not sources:
        print("\nNo sources yet. Add rows to data/sources.csv and PDFs to data/raw/.")
        return 1

    print("\nAll good: every source has a PDF and every PDF has a source row.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
