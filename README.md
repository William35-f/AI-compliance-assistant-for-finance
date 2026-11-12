# ReguLens

**An AI assistant for Singapore financial compliance.** ReguLens answers questions about
MAS (Monetary Authority of Singapore) guidelines using only retrieved passages, with a
document-and-page citation for every claim. It extracts key figures (revenue, net profit,
total debt, risk disclosures) from SGX-listed companies' annual reports into validated JSON,
and flags risk disclosures that may need checking against MAS guidelines, for a human to review.

> Status: **Phases 0-1 complete; Phases 2-3 built, waiting for a Gemini API key for live runs.** See [PROGRESS.md](PROGRESS.md)
> for the detailed build log, design decisions and (once measured) evaluation results.

## Progress

| Phase | Status |
|---|---|
| 0. Setup (Docker, Postgres + pgvector, FastAPI `/health`, sources registry) | ✅ Done |
| 1. Ingestion pipeline | ✅ Done |
| 2. Q&A with citations | 🟡 Built, needs Gemini key for a live check |
| 3. Evaluation harness | 🟡 Built, retrieval baseline measured |
| 4. Retrieval experiments | ⬜ Not started |
| 5. Report extraction and risk agent | ⬜ Not started |
| 6. Frontend, CI and deployment | ⬜ Not started |

### Phase 1: Ingestion pipeline

**Step 1: collect the source documents**

- [x] Download 10 MAS guideline PDFs into `data/raw/<id>.pdf` (10 / 10)
- [x] Download 5 SGX annual reports into `data/raw/<id>.pdf` (5 / 5: DBS, OCBC, Singtel, Keppel, Sheng Siong)
- [x] Add one row per document to `data/sources.csv`
- [x] `python scripts/check_sources.py` prints "All good"
- [x] `scripts/download_sources.py` re-downloads all PDFs from `sources.csv` in one command
- [x] Decide the LLM provider (Gemini, free key) and the embedding option (local nomic-embed-text-v1.5)

**Step 2: build the pipeline (with Claude)**

- [x] Parse PDFs with PyMuPDF, keeping the page number and nearest section heading
- [x] Section-aware chunker (~500–800 tokens, with overlap, configurable size)
- [x] Unit tests for the chunker
- [x] Swappable embedder (same small-interface idea as the LLM)
- [x] `chunks` table in pgvector with metadata (source_id, page, heading, text) + full-text index
- [x] `scripts/ingest.py` is idempotent (re-running creates no duplicates)
- [x] Ingest all documents and record chunk counts in PROGRESS.md (15 docs, 2,360 chunks)

### Phase 2: Q&A with citations

- [x] `POST /ask` with vector retrieval (k = 5) and Gemini behind a swappable interface
- [x] Answers as claims with chunk citations + verbatim quotes, validated by Pydantic
- [x] Quotes verified against the source text; refusal guardrails; not-legal-advice disclaimer
- [x] Every query logged to `query_logs`
- [ ] Live check against Gemini (needs `GEMINI_API_KEY` in `.env`)

### Phase 3: Evaluation harness

- [x] 90 eval questions (72 factual, 8 multi-hop, 10 out-of-scope) with expected pages
- [x] `eval/run_eval.py`: hit@k, MRR, judged correctness, citation accuracy, refusals, latency, cost
- [x] `eval/judge_agreement.py` for checking the LLM judge against a human
- [x] Retrieval baseline: hit@5 = 0.800, MRR = 0.669
- [ ] Full LLM-judged baseline (needs the Gemini key)
- [ ] Judge-human agreement on 20 sampled answers

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
[data/sources.csv](data/sources.csv) (10 MAS guidelines + 5 SGX annual reports); each row's
PDF is saved as `data/raw/<id>.pdf`. Download them all and check the registry with:

```powershell
python scripts/download_sources.py   # fetches any missing PDFs from the URLs in sources.csv
python scripts/check_sources.py      # every row has a PDF and every PDF has a row
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

Only numbers produced by `eval/run_eval.py` appear here (full log: [eval/results/summary.md](eval/results/summary.md)).

| Config | hit@5 | MRR | Answer correctness | Citation accuracy | OOS refusal |
|---|---|---|---|---|---|
| Vector only, k = 5 (baseline) | 0.800 | 0.669 | pending Gemini key | pending | pending |
