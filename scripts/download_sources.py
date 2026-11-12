"""Download every PDF listed in data/sources.csv into data/raw/<id>.pdf.

The PDFs are not committed to git, so this script lets anyone who clones the
repo rebuild data/raw/ in one command.

Usage (from the repo root, with the venv active):
    python scripts/download_sources.py           # download missing files only
    python scripts/download_sources.py --force   # re-download everything
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path

from regulens.config import RAW_DIR, SOURCES_CSV
from regulens.sources import Source, load_sources

# Some sites reject requests without a browser-like User-Agent.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ReguLens-downloader/0.1)"}
TIMEOUT_SECONDS = 120


def download(source: Source, dest: Path) -> int:
    """Download one PDF and return its size in bytes. Raises on failure."""
    request = urllib.request.Request(str(source.url), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        content = response.read()

    # A real PDF starts with "%PDF". Anything else is usually an HTML error page.
    if not content.startswith(b"%PDF"):
        raise ValueError(f"response is not a PDF (starts with {content[:20]!r})")

    # Write to a temp file first so a failed download never leaves a broken PDF behind.
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(content)
    tmp.replace(dest)
    return len(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force", action="store_true", help="re-download existing files"
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for source in load_sources(SOURCES_CSV):
        dest = source.pdf_path(RAW_DIR)
        if dest.exists() and not args.force:
            print(f"  skip  {source.id} (already downloaded)")
            continue
        try:
            size = download(source, dest)
            print(f"  ok    {source.id} ({size / 1_000_000:.1f} MB)")
        # OSError covers network errors and timeouts; ValueError is our "not a PDF" check.
        # Report each failure and keep going with the rest.
        except (OSError, ValueError) as exc:
            failures += 1
            print(f"  FAIL  {source.id}: {exc}")
        time.sleep(1)  # be polite to the servers

    print(f"\nDone with {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
