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
| 4. Retrieval experiments | ✅ Done (retrieval metrics) |
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

### Phase 4: Retrieval experiments

- [x] BM25 keyword search in SQL, hybrid search with reciprocal rank fusion, optional cross-encoder reranker
- [x] Chunk size / overlap variants and heading-in-embedding variant, one change at a time
- [x] Paraphrased question set to check for lexical bias in the eval
- [x] Confidence intervals and paired wins/losses (`eval/compare_runs.py`)
- [x] Winner: heading embedding + hybrid (hit@5 0.800 to 0.950); reranker and chunk-size changes did not help
- [ ] Full LLM-judged comparison of baseline vs chosen config (needs the Gemini key)

## Experiments (Phase 4)

All numbers come from `eval/run_eval.py --retrieval-only` on the 80 in-scope questions
(hit@5 = the expected document *and* page is among the 5 retrieved chunks). "+/-" counts
questions gained/lost versus the baseline, and the 95% interval comes from bootstrap
resampling (`eval/compare_runs.py`). One question is worth 1.25 points, so small gaps are noise.

| Change (one at a time) | hit@5 | 95% CI | MRR | vs baseline |
|---|---|---|---|---|
| Baseline: vector search, 600-token chunks, 100 overlap | 0.800 | 0.713-0.887 | 0.669 | |
| BM25 keyword search only | 0.912 | 0.850-0.963 | 0.779 | +11/-2 |
| Hybrid (vector + BM25, reciprocal rank fusion) | 0.850 | 0.762-0.925 | 0.729 | +5/-1 |
| Hybrid + cross-encoder reranker (MiniLM-L6) | 0.900 | 0.825-0.963 | 0.741 | +9/-1 |
| Hybrid + cross-encoder reranker (jina-turbo) | 0.912 | 0.850-0.963 | 0.769 | +9/-0 |
| Chunks 300 / overlap 50 (vector) | 0.825 | 0.738-0.900 | 0.592 | +4/-2 |
| Chunks 800 / overlap 150 (vector) | 0.863 | 0.787-0.938 | 0.672 | +7/-2 |
| Chunks 600 / no overlap (vector) | 0.825 | 0.738-0.900 | 0.638 | +4/-2 |
| Title + heading added to chunk text before embedding (vector) | 0.925 | 0.863-0.975 | 0.732 | +10/-0 |
| **Heading embedding + hybrid (chosen)** | **0.950** | **0.900-0.988** | **0.819** | **+12/-0** |
| Heading embedding + hybrid + jina reranker | 0.938 | 0.875-0.988 | 0.779 | +11/-0 |

**Robustness check with paraphrased questions.** The eval questions were written while reading
the PDFs, so they reuse the documents' wording, which flatters keyword search. A second set of 20
questions with the same answers asks them in plain language ("how long can a vendor wait before
telling the bank it brought in another company?" instead of "sub-contractor notification").

| Config (paraphrased set, n = 20) | hit@5 | MRR |
|---|---|---|
| Vector (baseline) | 0.600 | 0.447 |
| BM25 only | 0.600 | 0.371 |
| Hybrid | 0.700 | 0.471 |
| Heading embedding + vector | 0.700 | 0.554 |
| **Heading embedding + hybrid (chosen)** | **0.800** | 0.550 |

**What each change did, and why**
- **Heading in the embedding: the biggest win (+10/-0 on its own).** Chunks deep inside a section
  ("4.6 ... multi-factor authentication") don't mention the document or section they belong to.
  Prepending "MAS Notice FSM-N06 on Cyber Hygiene | Cyber Hygiene Practices" gives the vector
  the context that users put in their questions. All 5 cyber hygiene questions went from miss to hit.
- **BM25 alone looked best on the original questions, but it was a measurement artefact.** On
  paraphrased questions it fell to 0.600, the same as plain vector search. Questions that
  echo the source text favour exact-word matching; real users don't talk like regulations.
- **Hybrid search is the robust choice.** On its own it underperformed BM25 (equal-weight
  fusion let vector's weaker ranking push good BM25 hits out of the top 5). Combined with heading
  embeddings, it is best on both question sets: vector handles paraphrase, BM25 handles exact
  terms like "SRTO" and "FSM-N06".
- **Did NOT help: the cross-encoder reranker.** It rescued plain hybrid (+9/-1), but on top of
  heading + hybrid it made things slightly worse (MRR 0.819 to 0.779 with jina, 0.748 with MiniLM),
  and it costs about 1.3 s per query (median retrieval: vector 19 ms, hybrid 50 ms, hybrid +
  reranker 1,335 ms). MiniLM also reads only the first 512 tokens of a 600-token chunk.
- **Did NOT help: changing chunk size or overlap.** 300-token chunks lowered MRR (0.669 to 0.592):
  small chunks split facts from their context. 800-token chunks and removing overlap changed
  results by 2-5 questions, within noise. The 600/100 default stays.
- **Refusal threshold** (`MIN_RETRIEVAL_SCORE = 0.60`) was set from the data: the lowest in-scope
  best-match similarity was 0.656 (paraphrased) and 0.706 (original), while clearly unrelated
  questions scored 0.52-0.58. Near-domain out-of-scope questions (EU AI Act 0.737, Notice 637
  0.712) can't be separated by similarity, so the LLM's "not answerable" signal handles them.

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
| Heading embedding + hybrid, k = 5 (chosen) | 0.950 | 0.819 | pending Gemini key | pending | pending |
