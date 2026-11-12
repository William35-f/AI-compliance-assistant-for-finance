"""Ingest the PDFs listed in data/sources.csv into a named chunk index.

Usage (repo root, venv active, `docker compose up -d` running):
    python scripts/ingest.py                         # all documents into "baseline"
    python scripts/ingest.py --index baseline --source mas_trm_2021
    python scripts/ingest.py --force                 # re-ingest even if unchanged

Re-running is safe: unchanged documents are skipped, changed ones replaced.
"""

import argparse
import sys
import time

from regulens import db
from regulens.config import RAW_DIR, SOURCES_CSV, get_settings
from regulens.embeddings import get_embedder
from regulens.index_configs import INDEX_CONFIGS, get_index_config
from regulens.ingestion import ingest_source, prune_index
from regulens.sources import load_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest source PDFs into pgvector.")
    parser.add_argument("--index", default=get_settings().default_index, choices=INDEX_CONFIGS)
    parser.add_argument("--source", action="append", help="only this source id (repeatable)")
    parser.add_argument(
        "--doc-type", choices=["regulation", "annual_report"], help="only this document type"
    )
    parser.add_argument("--force", action="store_true", help="re-ingest unchanged documents")
    args = parser.parse_args()

    config = get_index_config(args.index)
    sources = load_sources(SOURCES_CSV)
    if args.source:
        unknown = set(args.source) - {s.id for s in sources}
        if unknown:
            print(f"Unknown source id(s): {sorted(unknown)}")
            return 1
        sources = [s for s in sources if s.id in args.source]
    if args.doc_type:
        sources = [s for s in sources if s.doc_type == args.doc_type]

    print(f"Index '{config.name}': {config}")
    print("Loading embedding model...")
    embedder = get_embedder()
    print(f"Embedder: {embedder.name} ({embedder.dim} dims)\n")

    db.init_db()
    total_chunks = 0
    started = time.perf_counter()
    with db.connect(autocommit=True) as conn:
        for source in sources:
            t0 = time.perf_counter()
            result = ingest_source(
                conn,
                source,
                source.pdf_path(RAW_DIR),
                config,
                embedder,
                force=args.force,
            )
            total_chunks += result.chunk_count
            print(
                f"  {result.status:<8} {source.id:<28} {result.page_count:>4} pages "
                f"{result.chunk_count:>5} chunks  {time.perf_counter() - t0:6.1f}s"
            )
        if not args.source and not args.doc_type:  # full run: drop docs that left sources.csv
            for removed in prune_index(conn, config.name, {s.id for s in sources}):
                print(f"  pruned   {removed} (no longer in sources.csv)")
    print(
        f"\n{len(sources)} documents, {total_chunks} chunks in index '{config.name}' "
        f"({time.perf_counter() - started:.0f}s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
