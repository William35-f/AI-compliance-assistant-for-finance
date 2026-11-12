-- ReguLens database schema.
-- Every statement is idempotent (IF NOT EXISTS), so this file is safe to run
-- on every app start and on a fresh managed Postgres in deployment.
-- Tables are added phase by phase.

-- pgvector: adds the `vector` column type and similarity operators.
CREATE EXTENSION IF NOT EXISTS vector;
