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
