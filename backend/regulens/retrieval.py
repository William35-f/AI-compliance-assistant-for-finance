"""Retrieval: find the chunks most relevant to a question.

Three ways to rank chunks, selected by `RetrievalConfig.mode`:

- "vector": cosine similarity between the question embedding and each chunk
  embedding. Good at meaning ("how fast must we tell the regulator" finds
  "notify MAS ... within one hour"), weaker on exact terms and names.
- "fts": keyword search scored with BM25, computed in SQL from Postgres'
  full-text index. Good at exact terms ("FSM-N06", "SRTO", "multi-factor").
  We compute BM25 ourselves because Postgres' built-in ts_rank has no IDF
  (inverse document frequency): it would weigh "bank" as highly as "SRTO".
- "hybrid": run both and merge the two rankings with Reciprocal Rank Fusion
  (RRF): score = sum over rankers of 1 / (rrf_k + rank). RRF only uses ranks,
  so it needs no tuning to make cosine similarities and BM25 scores comparable.

Optionally a cross-encoder reranker then re-scores the top candidates by
reading question and chunk together (slower, but more precise than comparing
two separately computed embeddings).

Every returned chunk carries its cosine `similarity` to the question whatever
the mode, so the "is anything relevant at all?" guardrail means the same thing
in every configuration.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from regulens.embeddings import Embedder
from regulens.reranker import Reranker

RETRIEVAL_MODES = ("vector", "fts", "hybrid")

# BM25 parameters: k1 controls term-frequency saturation, b length normalisation.
# These are the standard defaults from the information-retrieval literature.
BM25_K1 = 1.2
BM25_B = 0.75


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
    similarity: float  # cosine similarity to the question (always set)
    score: float  # the score this chunk was ranked by (depends on the mode)


@dataclass(frozen=True)
class RetrievalConfig:
    mode: str = "hybrid"
    index_name: str = "heading"
    k: int = 5  # chunks handed to the LLM
    doc_types: tuple[str, ...] = ("regulation",)  # Q&A answers from MAS guidelines only
    candidates: int = 30  # list length per ranker before fusion / reranking
    rrf_k: int = 60  # standard RRF constant: dampens the advantage of top ranks
    rerank: bool = False
    rerank_candidates: int = 20  # how many fused candidates the cross-encoder re-scores

    def __post_init__(self) -> None:
        if self.mode not in RETRIEVAL_MODES:
            raise ValueError(f"mode must be one of {RETRIEVAL_MODES}")


# --------------------------------------------------------------------------- rankers


def vector_ranking(
    conn: psycopg.Connection, query_vec: Vector, config: RetrievalConfig, n: int
) -> list[int]:
    """Chunk ids ordered by cosine distance (exact search, see schema.sql)."""
    rows = conn.execute(
        """
        SELECT c.id
        FROM chunks c JOIN sources s ON s.id = c.source_id
        WHERE c.index_name = %(index)s AND s.doc_type = ANY(%(types)s)
        ORDER BY c.embedding <=> %(q)s
        LIMIT %(n)s
        """,
        {"q": query_vec, "index": config.index_name, "types": list(config.doc_types), "n": n},
    ).fetchall()
    return [r[0] for r in rows]


# BM25 over the chunks in scope, using the generated `tsv` column.
# unnest(tsvector) yields one row per distinct lexeme with its positions,
# so array_length(positions) is the term frequency in that chunk.
_BM25_SQL = """
WITH scope AS (
    SELECT c.id, c.tsv
    FROM chunks c JOIN sources s ON s.id = c.source_id
    WHERE c.index_name = %(index)s AND s.doc_type = ANY(%(types)s)
),
query_terms AS (
    SELECT DISTINCT lexeme FROM unnest(to_tsvector('english', %(q)s))
),
doc_len AS (
    SELECT sc.id, (SELECT coalesce(sum(array_length(u.positions, 1)), 0)
                   FROM unnest(sc.tsv) u) AS len
    FROM scope sc
),
stats AS (
    SELECT count(*)::float AS n_docs, greatest(avg(len), 1)::float AS avg_len FROM doc_len
),
postings AS (
    SELECT sc.id, u.lexeme, coalesce(array_length(u.positions, 1), 1)::float AS tf
    FROM scope sc, unnest(sc.tsv) u
    WHERE u.lexeme IN (SELECT lexeme FROM query_terms)
),
doc_freq AS (
    SELECT lexeme, count(*)::float AS df FROM postings GROUP BY lexeme
)
SELECT p.id,
       sum(
           ln(1 + (st.n_docs - d.df + 0.5) / (d.df + 0.5))               -- IDF
           * p.tf * (%(k1)s + 1)
           / (p.tf + %(k1)s * (1 - %(b)s + %(b)s * dl.len / st.avg_len))  -- saturated TF
       ) AS score
FROM postings p
JOIN doc_freq d USING (lexeme)
JOIN doc_len dl ON dl.id = p.id
CROSS JOIN stats st
GROUP BY p.id
ORDER BY score DESC
LIMIT %(n)s
"""


def bm25_ranking(
    conn: psycopg.Connection, question: str, config: RetrievalConfig, n: int
) -> list[tuple[int, float]]:
    """(chunk id, BM25 score) for chunks sharing at least one term with the question."""
    rows = conn.execute(
        _BM25_SQL,
        {
            "q": question,
            "index": config.index_name,
            "types": list(config.doc_types),
            "n": n,
            "k1": BM25_K1,
            "b": BM25_B,
        },
    ).fetchall()
    return [(r[0], float(r[1])) for r in rows]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], rrf_k: int = 60
) -> list[tuple[int, float]]:
    """Merge rankings: each list contributes 1 / (rrf_k + rank) for every id it contains."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def fetch_chunks(
    conn: psycopg.Connection, scored_ids: Sequence[tuple[int, float]], query_vec: Vector
) -> list[RetrievedChunk]:
    """Load chunk rows (keeping the given order) with their cosine similarity."""
    if not scored_ids:
        return []
    rows = conn.execute(
        """
        SELECT c.id, c.source_id, s.title, s.doc_type, c.page_start, c.page_end, c.heading,
               c.text, 1 - (c.embedding <=> %(q)s) AS similarity
        FROM chunks c JOIN sources s ON s.id = c.source_id
        WHERE c.id = ANY(%(ids)s)
        """,
        {"q": query_vec, "ids": [i for i, _ in scored_ids]},
    ).fetchall()
    by_id = {r[0]: r for r in rows}
    return [
        RetrievedChunk(*by_id[i][:8], similarity=float(by_id[i][8]), score=score)
        for i, score in scored_ids
        if i in by_id
    ]


# --------------------------------------------------------------------------- entry point


def retrieve(
    conn: psycopg.Connection,
    embedder: Embedder,
    question: str,
    config: RetrievalConfig,
    reranker: Reranker | None = None,
) -> list[RetrievedChunk]:
    """Return the top-k chunks for a question. Used by the API and the eval harness."""
    register_vector(conn)
    query_vec = Vector(embedder.embed_query(question))
    pool = max(config.k, config.rerank_candidates if config.rerank else config.k)

    if config.mode == "vector":
        ids = vector_ranking(conn, query_vec, config, pool)
        scored = [(i, 1.0 / rank) for rank, i in enumerate(ids, start=1)]
    elif config.mode == "fts":
        scored = bm25_ranking(conn, question, config, pool)
    else:  # hybrid
        vec_ids = vector_ranking(conn, query_vec, config, config.candidates)
        fts_ids = [i for i, _ in bm25_ranking(conn, question, config, config.candidates)]
        scored = reciprocal_rank_fusion([vec_ids, fts_ids], config.rrf_k)[:pool]

    chunks = fetch_chunks(conn, scored, query_vec)
    if config.mode == "vector":  # for pure vector search, the score IS the similarity
        chunks = [_with_score(c, c.similarity) for c in chunks]

    if config.rerank:
        if reranker is None:
            raise ValueError("config.rerank is set but no reranker was given")
        scores = reranker.score(question, [c.text for c in chunks])
        chunks = [
            _with_score(c, s)
            for c, s in sorted(zip(chunks, scores, strict=True), key=lambda x: x[1], reverse=True)
        ]
    return chunks[: config.k]


def _with_score(chunk: RetrievedChunk, score: float) -> RetrievedChunk:
    return replace(chunk, score=score)
