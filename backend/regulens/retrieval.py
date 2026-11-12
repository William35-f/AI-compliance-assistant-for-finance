"""Retrieval: find the chunks most relevant to a question.

Phase 2 baseline: vector search only. Cosine similarity between the question
embedding and every chunk embedding in the index, highest first.
(pgvector's `<=>` operator returns cosine *distance* = 1 - similarity.)
"""

from collections.abc import Sequence
from dataclasses import dataclass

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from regulens.embeddings import Embedder


@dataclass(frozen=True)
class RetrievedChunk:
    id: int
    source_id: str
    title: str
    doc_type: str
    page_start: int
    page_end: int
    heading: str | None
    text: str
    score: float  # cosine similarity for vector search (higher = more similar)


RETRIEVAL_MODES = ("vector",)


@dataclass(frozen=True)
class RetrievalConfig:
    mode: str = "vector"
    index_name: str = "baseline"
    k: int = 5  # chunks handed to the LLM
    doc_types: tuple[str, ...] = ("regulation",)  # Q&A answers from MAS guidelines only


_COLUMNS = """
    c.id, c.source_id, s.title, s.doc_type, c.page_start, c.page_end, c.heading, c.text
"""


def vector_search(
    conn: psycopg.Connection,
    query_embedding: Sequence[float],
    k: int,
    index_name: str,
    doc_types: Sequence[str],
) -> list[RetrievedChunk]:
    """Top-k chunks by cosine similarity (exact search, see schema.sql)."""
    register_vector(conn)
    rows = conn.execute(
        f"""
        SELECT {_COLUMNS}, 1 - (c.embedding <=> %(q)s) AS score
        FROM chunks c JOIN sources s ON s.id = c.source_id
        WHERE c.index_name = %(index)s AND s.doc_type = ANY(%(types)s)
        ORDER BY c.embedding <=> %(q)s
        LIMIT %(k)s
        """,
        {"q": Vector(list(query_embedding)), "index": index_name, "types": list(doc_types), "k": k},
    ).fetchall()
    return [RetrievedChunk(*row[:8], score=float(row[8])) for row in rows]


def retrieve(
    conn: psycopg.Connection, embedder: Embedder, question: str, config: RetrievalConfig
) -> list[RetrievedChunk]:
    """Entry point used by the API and the eval harness."""
    query_embedding = embedder.embed_query(question)
    return vector_search(conn, query_embedding, config.k, config.index_name, config.doc_types)
