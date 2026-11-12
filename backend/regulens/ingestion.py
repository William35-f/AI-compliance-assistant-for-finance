"""Ingestion: PDF -> paragraphs -> chunks -> embeddings -> Postgres.

Idempotency: each (index, document) pair stores a fingerprint of everything
that affects its chunks. Re-running with the same inputs is a no-op. If
anything changed, the document's old chunks are deleted and the new ones
inserted in ONE transaction, so a crash half-way never leaves duplicates
or a half-ingested document behind.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from regulens.chunking import Chunk, chunk_paragraphs
from regulens.embeddings import Embedder
from regulens.index_configs import IndexConfig
from regulens.pdf_parser import PARSER_VERSION, parse_pdf
from regulens.sources import Source


@dataclass(frozen=True)
class IngestResult:
    source_id: str
    status: Literal["ingested", "skipped"]
    chunk_count: int
    page_count: int


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(source: Source, pdf_sha: str, config: IndexConfig, embedder_name: str) -> str:
    """Hash of every input that changes the stored chunks."""
    payload = {
        "pdf": pdf_sha,
        "parser": PARSER_VERSION,
        "chunk": asdict(config.chunk_for(source.doc_type)),
        "heading_in_embedding": config.heading_in_embedding,
        "embedder": embedder_name,
        # The title is embedded when heading_in_embedding is on.
        "title": source.title if config.heading_in_embedding else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def embedding_text(chunk: Chunk, title: str, config: IndexConfig) -> str:
    """The exact string we embed for a chunk."""
    if not config.heading_in_embedding:
        return chunk.text
    context = f"{title} | {chunk.heading}" if chunk.heading else title
    return f"{context}\n{chunk.text}"


def upsert_source(
    conn: psycopg.Connection, source: Source, page_count: int | None = None, sha: str | None = None
) -> None:
    """Insert or refresh a document's metadata from sources.csv.

    page_count/sha are only known after parsing; when omitted, existing values are kept.
    """
    conn.execute(
        """
        INSERT INTO sources (id, title, publisher, url, doc_type, date_downloaded,
                             page_count, file_sha256)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title, publisher = EXCLUDED.publisher, url = EXCLUDED.url,
            doc_type = EXCLUDED.doc_type, date_downloaded = EXCLUDED.date_downloaded,
            page_count = COALESCE(EXCLUDED.page_count, sources.page_count),
            file_sha256 = COALESCE(EXCLUDED.file_sha256, sources.file_sha256)
        """,
        (
            source.id,
            source.title,
            source.publisher,
            str(source.url),
            source.doc_type,
            source.date_downloaded,
            page_count,
            sha,
        ),
    )


def _check_same_model(conn: psycopg.Connection, index_name: str, dim: int) -> None:
    """All vectors in one index must come from the same model (same dimension)."""
    row = conn.execute(
        "SELECT vector_dims(embedding) FROM chunks WHERE index_name = %s LIMIT 1", (index_name,)
    ).fetchone()
    if row and row[0] != dim:
        raise ValueError(
            f"Index '{index_name}' holds {row[0]}-dim vectors but the embedder makes {dim}-dim "
            "vectors. Use a new index name for a different embedding model."
        )


def ingest_source(
    conn: psycopg.Connection,
    source: Source,
    pdf_path: Path,
    config: IndexConfig,
    embedder: Embedder,
    force: bool = False,
) -> IngestResult:
    """Ingest one document into one index. Safe to call repeatedly.

    `conn` must be in autocommit mode, so that `conn.transaction()` below is a
    real transaction that commits this document on its own.
    """
    if not conn.autocommit:
        raise ValueError("ingest_source needs db.connect(autocommit=True)")
    register_vector(conn)
    _check_same_model(conn, config.name, embedder.dim)  # fail fast, before slow work
    upsert_source(conn, source)  # keep title/url etc. in sync with sources.csv
    sha = file_sha256(pdf_path)
    fp = fingerprint(source, sha, config, embedder.name)

    existing = conn.execute(
        "SELECT fingerprint, chunk_count FROM ingested_documents "
        "WHERE index_name = %s AND source_id = %s",
        (config.name, source.id),
    ).fetchone()
    if existing and existing[0] == fp and not force:
        page_count_row = conn.execute(
            "SELECT page_count FROM sources WHERE id = %s", (source.id,)
        ).fetchone()
        return IngestResult(source.id, "skipped", existing[1], page_count_row[0] or 0)

    # The slow part (parsing + embedding) happens before we open the write transaction.
    paragraphs, page_count = parse_pdf(pdf_path)
    chunk_config = config.chunk_for(source.doc_type)
    chunks = chunk_paragraphs(paragraphs, chunk_config, count_tokens=embedder.count_tokens)
    vectors = embedder.embed_documents([embedding_text(c, source.title, config) for c in chunks])

    with conn.transaction():
        upsert_source(conn, source, page_count, sha)
        conn.execute(
            "DELETE FROM chunks WHERE index_name = %s AND source_id = %s",
            (config.name, source.id),
        )
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks (index_name, source_id, chunk_index, page_start, page_end,
                                    heading, text, token_count, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        config.name,
                        source.id,
                        c.index,
                        c.page_start,
                        c.page_end,
                        c.heading,
                        c.text,
                        c.token_count,
                        Vector(v),
                    )
                    for c, v in zip(chunks, vectors, strict=True)
                ],
            )
        conn.execute(
            """
            INSERT INTO ingested_documents (index_name, source_id, fingerprint, chunk_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (index_name, source_id) DO UPDATE SET
                fingerprint = EXCLUDED.fingerprint, chunk_count = EXCLUDED.chunk_count,
                ingested_at = now()
            """,
            (config.name, source.id, fp, len(chunks)),
        )
    return IngestResult(source.id, "ingested", len(chunks), page_count)


def prune_index(conn: psycopg.Connection, index_name: str, keep_source_ids: set[str]) -> list[str]:
    """Delete chunks of documents that are no longer in sources.csv. Returns removed ids."""
    rows = conn.execute(
        "SELECT source_id FROM ingested_documents WHERE index_name = %s", (index_name,)
    ).fetchall()
    removed = sorted({r[0] for r in rows} - keep_source_ids)
    with conn.transaction():
        for source_id in removed:
            for table in ("chunks", "ingested_documents"):
                conn.execute(
                    f"DELETE FROM {table} WHERE index_name = %s AND source_id = %s",
                    (index_name, source_id),
                )
    return removed
