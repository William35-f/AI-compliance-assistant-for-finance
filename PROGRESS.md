# ReguLens: progress log

## Phases

- [x] **Phase 0: Setup** (2026-11-12)
- [ ] Phase 1: Ingestion pipeline
- [ ] Phase 2: Q&A with citations
- [ ] Phase 3: Evaluation harness
- [ ] Phase 4: Retrieval experiments
- [ ] Phase 5: Report extraction and risk agent
- [ ] Phase 6: Frontend, CI and deployment

---

## Phase 0: Setup

### Built
- Repo layout: `backend/`, `frontend/`, `eval/`, `data/`, `scripts/`.
- `docker-compose.yml` running `pgvector/pgvector:pg16` with a health check and a named volume.
- Backend package `regulens` (installed with `pip install -e "backend[dev]"`):
  - `config.py`: settings from `.env` via pydantic-settings; API keys stored as `SecretStr`.
  - `db.py` + `schema.sql`: psycopg 3 connection helper; idempotent schema applied at startup.
  - `main.py`: FastAPI app with `GET /health` (200 when Postgres + pgvector work, otherwise 503).
  - `sources.py`: strict loader and validator for `data/sources.csv`.
- `scripts/check_sources.py`: checks that every row has `data/raw/<id>.pdf` and every PDF has a row.
- `.env.example`, `.gitignore` (PDFs and `.env` are never committed), `.gitattributes`.

### Results (measured 2026-11-12)
- `pytest backend`: 15 passed (3 health unit tests, 1 health integration test against real
  Postgres, 11 sources.csv tests). `ruff check`: clean.
- `/health` checked by hand: 200 with `pgvector_version: 0.8.7` while the DB was up, 503
  `unreachable` after `docker compose stop db`, and 200 again after restarting it.

### Decisions
| Decision | Why |
|---|---|
| Backend is an installable package (`backend/regulens`) | `scripts/` and `eval/` can `import regulens` without `sys.path` hacks. |
| Only Postgres runs in Docker for now; the API runs locally with `uvicorn --reload` | Faster edit-run loop while learning. A backend Dockerfile comes in Phase 6. |
| Schema lives in `schema.sql`, applied idempotently at app startup | Docker init scripts only run on an empty volume and don't exist on managed Postgres. One idempotent file works locally, in CI and in deployment. |
| psycopg 3 + plain SQL, no ORM | Vector search, full-text search and rank fusion are SQL-heavy. Plain SQL keeps them visible and easy to explain. |
| `/health` returns 503 (not 200) when the DB is down | Deployment platforms use the status code to decide if the app is healthy. The app still starts without a DB so it can report this. |
| PDFs are named `data/raw/<id>.pdf`, with `sources.csv` as the single registry | One naming rule means ingestion and eval never need a separate filename column. |
| `sources.csv` read as `utf-8-sig`, dates must be `YYYY-MM-DD` | The CSV will likely be edited in Excel on Windows, which adds a BOM and may reformat dates. Validation catches this early. |
| Postgres host port is configurable (`POSTGRES_PORT`) | Avoids clashes with other local Postgres installs. |

### Open questions for later phases
- **Embeddings (Phase 1):** Anthropic has no embeddings API. If the LLM provider is Anthropic,
  embeddings need OpenAI or a local model (e.g. a small sentence-transformers model). To be decided
  in Phase 1, keeping the embedder swappable like the LLM.
- Local dev note: port 8000 was already in use on the dev machine, so the API was tested on 8001.
- Starlette prints a deprecation warning about `httpx` in the TestClient. It's harmless; revisit when upgrading.
