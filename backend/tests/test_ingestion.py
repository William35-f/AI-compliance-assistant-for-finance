"""Integration tests for ingestion against the real Postgres (skipped if it is down).

They use the tiny HashingEmbedder, so no model download is needed, and they
write only rows for test-only source ids / index names, cleaned up afterwards.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest

from regulens import db
from regulens.chunking import ChunkConfig
from regulens.embeddings import HashingEmbedder
from regulens.index_configs import IndexConfig
from regulens.ingestion import ingest_source
from regulens.sources import Source
from tests.pdf_factory import TextItem, make_pdf


def _database_is_up() -> bool:
    try:
        with db.connect():
            return True
    except psycopg.OperationalError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _database_is_up(), reason="Postgres is not running"),
]

SOURCE = Source(
    id="test_ingest_doc",
    title="Test Guidelines",
    publisher="Test",
    url="https://example.com/test.pdf",
    date_downloaded=date(2026, 1, 1),
    doc_type="regulation",
)
CONFIG = IndexConfig("test_index_a", ChunkConfig(chunk_size=40, overlap=10, min_section_tokens=1))


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    db.init_db()
    with db.connect(autocommit=True) as connection:
        yield connection
        connection.execute("DELETE FROM sources WHERE id = %s", (SOURCE.id,))  # cascades


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    # One sentence per line: text running past the page edge would not be extracted.
    body = "\n".join(f"Outsourcing control number {i} must be reviewed." for i in range(20))
    return make_pdf(
        tmp_path / "doc.pdf",
        pages=[[TextItem("1 Outsourcing", size=18), TextItem(body)], [TextItem("More text here.")]],
    )


def chunk_count(conn: psycopg.Connection, index: str) -> int:
    row = conn.execute(
        "SELECT count(*) FROM chunks WHERE index_name = %s AND source_id = %s", (index, SOURCE.id)
    ).fetchone()
    return row[0]


def test_reingest_is_idempotent(conn: psycopg.Connection, pdf: Path) -> None:
    embedder = HashingEmbedder()
    first = ingest_source(conn, SOURCE, pdf, CONFIG, embedder)
    assert first.status == "ingested"
    assert first.chunk_count > 1
    assert chunk_count(conn, CONFIG.name) == first.chunk_count

    second = ingest_source(conn, SOURCE, pdf, CONFIG, embedder)
    assert second.status == "skipped"
    assert chunk_count(conn, CONFIG.name) == first.chunk_count  # no duplicates

    forced = ingest_source(conn, SOURCE, pdf, CONFIG, embedder, force=True)
    assert forced.status == "ingested"
    assert chunk_count(conn, CONFIG.name) == first.chunk_count  # replaced, not appended


def test_changed_settings_replace_chunks(conn: psycopg.Connection, pdf: Path) -> None:
    embedder = HashingEmbedder()
    ingest_source(conn, SOURCE, pdf, CONFIG, embedder)
    bigger = IndexConfig(CONFIG.name, ChunkConfig(chunk_size=400, overlap=0))
    result = ingest_source(conn, SOURCE, pdf, bigger, embedder)
    assert result.status == "ingested"  # fingerprint changed, so it re-ran
    assert chunk_count(conn, CONFIG.name) == result.chunk_count


def test_indexes_are_independent(conn: psycopg.Connection, pdf: Path) -> None:
    embedder = HashingEmbedder()
    other = IndexConfig("test_index_b", ChunkConfig(chunk_size=400, overlap=0))
    a = ingest_source(conn, SOURCE, pdf, CONFIG, embedder)
    b = ingest_source(conn, SOURCE, pdf, other, embedder)
    assert chunk_count(conn, CONFIG.name) == a.chunk_count
    assert chunk_count(conn, other.name) == b.chunk_count


def test_stores_metadata_and_full_text_index(conn: psycopg.Connection, pdf: Path) -> None:
    ingest_source(conn, SOURCE, pdf, CONFIG, HashingEmbedder())
    row = conn.execute(
        """
        SELECT heading, page_start, vector_dims(embedding)
        FROM chunks
        WHERE index_name = %s AND source_id = %s
          AND tsv @@ websearch_to_tsquery('english', 'outsourcing reviewed')
        ORDER BY chunk_index LIMIT 1
        """,
        (CONFIG.name, SOURCE.id),
    ).fetchone()
    assert row == ("1 Outsourcing", 1, 64)


def test_rejects_mixing_embedding_models(conn: psycopg.Connection, pdf: Path) -> None:
    ingest_source(conn, SOURCE, pdf, CONFIG, HashingEmbedder(dim=64))
    with pytest.raises(ValueError, match="dim"):
        ingest_source(conn, SOURCE, pdf, CONFIG, HashingEmbedder(dim=32))


def test_requires_autocommit_connection(pdf: Path) -> None:
    with db.connect() as plain, pytest.raises(ValueError, match="autocommit"):
        ingest_source(plain, SOURCE, pdf, CONFIG, HashingEmbedder())
