-- ReguLens database schema.
-- Every statement is idempotent (IF NOT EXISTS), so this file is safe to run
-- on every app start and on a fresh managed Postgres in deployment.

-- pgvector: adds the `vector` column type and similarity operators.
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per document in data/sources.csv.
CREATE TABLE IF NOT EXISTS sources (
    id              text PRIMARY KEY,
    title           text NOT NULL,
    publisher       text NOT NULL,
    url             text NOT NULL,
    doc_type        text NOT NULL CHECK (doc_type IN ('regulation', 'annual_report')),
    date_downloaded date NOT NULL,
    page_count      integer,
    file_sha256     text
);

-- Which documents have been ingested into which index, and with what inputs.
-- `fingerprint` hashes the PDF bytes + parser version + chunk settings + embedding
-- model. If it is unchanged, ingest.py skips the document (idempotency).
CREATE TABLE IF NOT EXISTS ingested_documents (
    index_name   text NOT NULL,
    source_id    text NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    fingerprint  text NOT NULL,
    chunk_count  integer NOT NULL,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (index_name, source_id)
);

-- The retrieval units. Several indexes (chunking variants) can coexist.
CREATE TABLE IF NOT EXISTS chunks (
    id           bigserial PRIMARY KEY,
    index_name   text NOT NULL,
    source_id    text NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    chunk_index  integer NOT NULL,
    page_start   integer NOT NULL,
    page_end     integer NOT NULL,
    heading      text,
    text         text NOT NULL,
    token_count  integer NOT NULL,
    -- No fixed dimension, so the embedding model can change without a migration.
    -- All rows in one index share a model (enforced by ingest.py).
    embedding    vector NOT NULL,
    -- Full-text search vector, maintained by Postgres automatically.
    tsv          tsvector GENERATED ALWAYS AS (
                     to_tsvector('english', coalesce(heading, '') || ' ' || text)
                 ) STORED,
    UNIQUE (index_name, source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_index_source_idx ON chunks (index_name, source_id);
-- No approximate (HNSW) vector index on purpose: with a few thousand chunks an
-- exact scan takes milliseconds and has perfect recall. Add HNSW past ~100k rows.

-- LLM responses keyed by a hash of (model, system prompt, prompt, schema).
-- Identical requests (e.g. re-running an eval) are answered from here for free.
CREATE TABLE IF NOT EXISTS llm_cache (
    key            text PRIMARY KEY,
    model          text NOT NULL,
    response       jsonb NOT NULL,
    input_tokens   integer NOT NULL,
    output_tokens  integer NOT NULL,
    latency_ms     integer NOT NULL,  -- latency of the original (uncached) call
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- One row per answered question (API traffic and eval runs, told apart by `origin`).
CREATE TABLE IF NOT EXISTS query_logs (
    id                  bigserial PRIMARY KEY,
    created_at          timestamptz NOT NULL DEFAULT now(),
    question            text NOT NULL,
    answer              text NOT NULL,
    refused             boolean NOT NULL,
    refusal_reason      text,
    retrieved_chunk_ids bigint[] NOT NULL,
    top_score           real,
    latency_ms          integer NOT NULL,
    input_tokens        integer NOT NULL,
    output_tokens       integer NOT NULL,
    cost_usd            numeric(12, 6) NOT NULL,
    model               text,
    index_name          text NOT NULL,
    origin              text NOT NULL,  -- 'api' or 'eval'
    cached              boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS query_logs_created_idx ON query_logs (created_at);
