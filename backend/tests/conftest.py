"""Shared test fixtures: a small test index built from a synthetic PDF."""

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
from regulens.retrieval import RetrievalConfig
from regulens.sources import Source
from tests.pdf_factory import TextItem, make_pdf


def database_is_up() -> bool:
    try:
        with db.connect():
            return True
    except psycopg.OperationalError:
        return False


requires_db = pytest.mark.skipif(not database_is_up(), reason="Postgres is not running")

QA_SOURCE = Source(
    id="test_qa_doc",
    title="Test Outsourcing Guidelines",
    publisher="Test",
    url="https://example.com/qa.pdf",
    date_downloaded=date(2026, 1, 1),
    doc_type="regulation",
)
QA_INDEX = IndexConfig("test_qa_index", ChunkConfig(chunk_size=60, overlap=0, min_section_tokens=1))
QA_RETRIEVAL = RetrievalConfig(index_name=QA_INDEX.name, k=3)


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


@pytest.fixture
def qa_index(tmp_path: Path, embedder: HashingEmbedder) -> Iterator[None]:
    """Ingest a 2-section synthetic guideline into a test-only index."""
    pdf = make_pdf(
        tmp_path / "qa.pdf",
        pages=[
            [
                TextItem("1 Notification", size=18),
                TextItem(
                    "A bank should notify MAS within one hour of discovering\n"
                    "a severe outsourcing incident."
                ),
            ],
            [
                TextItem("2 Board oversight", size=18),
                TextItem("The board should approve the outsourcing risk management\nframework."),
            ],
        ],
    )
    db.init_db()
    with db.connect(autocommit=True) as conn:
        ingest_source(conn, QA_SOURCE, pdf, QA_INDEX, embedder)
    yield
    with db.connect(autocommit=True) as conn:
        conn.execute("DELETE FROM sources WHERE id = %s", (QA_SOURCE.id,))
        conn.execute("DELETE FROM query_logs WHERE index_name = %s", (QA_INDEX.name,))
