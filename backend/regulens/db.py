"""Database helpers.

We use psycopg 3 with plain SQL instead of an ORM. Most of the interesting
queries in this project (vector search, full-text search, rank fusion) are
SQL-heavy anyway, and plain SQL keeps them visible and easy to explain.
"""

from pathlib import Path

import psycopg

from regulens.config import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(autocommit: bool = False) -> psycopg.Connection:
    """Open a new connection. Use it as a context manager: `with connect() as conn:`.

    Default: everything inside the `with` block is one transaction, committed
    on exit (or rolled back on error). With autocommit=True each statement
    commits immediately, and `with conn.transaction():` marks explicit
    transactions. Ingestion uses this so each document commits on its own.
    """
    return psycopg.connect(get_settings().database_url, connect_timeout=3, autocommit=autocommit)


def init_db() -> None:
    """Create the extension and tables if they do not exist yet."""
    with connect() as conn:
        # Without query parameters, psycopg can run several statements in one call.
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def pgvector_version() -> str | None:
    """Return the installed pgvector version, or None if the extension is missing.

    Raises psycopg.OperationalError if the database is unreachable.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    return row[0] if row else None
