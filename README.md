# ReguLens

**An AI assistant for Singapore financial compliance.** ReguLens answers questions about
MAS (Monetary Authority of Singapore) guidelines using only retrieved passages, with a
document-and-page citation for every claim. It extracts key figures (revenue, net profit,
total debt, risk disclosures) from SGX-listed companies' annual reports into validated JSON,
and flags risk disclosures that may need checking against MAS guidelines, for a human to review.

> Status: **Phase 0 (setup) complete.** See [PROGRESS.md](PROGRESS.md) for the build log,
> design decisions and (once measured) evaluation results.

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
