# ReguLens

**An AI assistant for Singapore financial compliance.** ReguLens answers questions about
MAS (Monetary Authority of Singapore) guidelines using only retrieved passages, with a
document-and-page citation for every claim. It extracts key figures (revenue, net profit,
total debt, risk disclosures) from SGX-listed companies' annual reports into validated JSON,
and flags risk disclosures that may need checking against MAS guidelines, for a human to review.

> Status: **Phase 0 (setup) complete, Phase 1 in progress.** See [PROGRESS.md](PROGRESS.md)
> for the detailed build log, design decisions and (once measured) evaluation results.

## Progress

| Phase | Status |
|---|---|
| 0. Setup (Docker, Postgres + pgvector, FastAPI `/health`, sources registry) | ✅ Done |
| 1. Ingestion pipeline | 🟡 In progress |
| 2. Q&A with citations | ⬜ Not started |
| 3. Evaluation harness | ⬜ Not started |
| 4. Retrieval experiments | ⬜ Not started |
| 5. Report extraction and risk agent | ⬜ Not started |
| 6. Frontend, CI and deployment | ⬜ Not started |

### Phase 1: Ingestion pipeline

**Step 1: collect the source documents (my task)**

- [ ] Download ~10 MAS guideline PDFs into `data/raw/<id>.pdf` (0 / 10)
- [ ] Download 5 SGX annual reports into `data/raw/<id>.pdf` (0 / 5)
- [ ] Add one row per document to `data/sources.csv`
- [ ] `python scripts/check_sources.py` prints "All good"
- [ ] Decide the LLM provider (Anthropic or OpenAI) and the embedding option (local model or OpenAI)

**Step 2: build the pipeline (with Claude)**

- [ ] Parse PDFs with PyMuPDF, keeping the page number and nearest section heading
- [ ] Section-aware chunker (~500–800 tokens, with overlap, configurable size)
- [ ] Unit tests for the chunker
- [ ] Swappable embedder (same small-interface idea as the LLM)
- [ ] `chunks` table in pgvector with metadata (source_id, page, heading, text) + full-text index
- [ ] `scripts/ingest.py` is idempotent (re-running creates no duplicates)
- [ ] Ingest all documents and record chunk counts in PROGRESS.md

## Tech stack

Python 3.11+ · FastAPI · Pydantic v2 · Postgres 16 + pgvector (Docker Compose) · PyMuPDF ·
hybrid retrieval (full-text + vector, reciprocal rank fusion, optional cross-encoder reranker) ·
OpenAI or Anthropic LLM behind one small interface · React (Vite + TypeScript) · pytest ·
GitHub Actions

## Run it locally

Prerequisites: Python 3.11+, Docker Desktop, Git.

```powershell
# 1. Configuration: copy the example and fill in API keys later (Phase 2)
copy .env.example .env

# 2. Start Postgres + pgvector
docker compose up -d --wait

# 3. Create a virtual environment and install the backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e "backend[dev]"

# 4. Run the API (use --port 8001 if port 8000 is already taken)
uvicorn regulens.main:app --reload
# then open http://127.0.0.1:8000/health or http://127.0.0.1:8000/docs

# 5. Run the tests and the linter
pytest backend
ruff check backend scripts
```

If PowerShell refuses to run `activate`, either run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or call the tools directly,
for example `.venv\Scripts\python -m pytest backend`.

## Source documents

PDFs are **not** committed (they are copyrighted). The registry of documents is
[data/sources.csv](data/sources.csv); each row's PDF must be saved as `data/raw/<id>.pdf`.
Check the registry with:

```powershell
python scripts/check_sources.py
```

## Repository layout

```
backend/     FastAPI app (package `regulens`) and its tests
frontend/    React app (Phase 6)
eval/        evaluation questions, scripts and results (Phase 3)
data/        sources.csv (committed) and raw/ PDFs (git-ignored)
scripts/     command-line tools (source checks, ingestion)
```

## Evaluation results

Nothing measured yet. Only numbers produced by `eval/run_eval.py` will appear here.
