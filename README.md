# ReguLens

**An AI assistant for Singapore financial compliance.** ReguLens answers questions about MAS
(Monetary Authority of Singapore) guidelines using only retrieved passages, and backs every claim
with a document, page and verbatim quote that the code checks against the source. It extracts
revenue, net profit, total debt and key risk disclosures from SGX-listed companies' annual reports,
converting units and verifying each number on the cited financial-statement page. A small agent
then links each disclosed risk to the relevant MAS guideline sections and flags possible gaps for
a human to review. Retrieval quality was improved with measured, one-change-at-a-time experiments
(hit@5 **0.80 → 0.95** on 80 questions).

**Live demo:** _not deployed yet_ (see [DEPLOY.md](DEPLOY.md)) · **Build log and decisions:** [PROGRESS.md](PROGRESS.md)

## Architecture

```mermaid
flowchart LR
    subgraph Offline["Offline ingestion (scripts/ingest.py)"]
        PDF["MAS + SGX PDFs"] --> PARSE["PyMuPDF parser<br/>page + nearest heading"]
        PARSE --> CHUNK["Section-aware chunker<br/>600 tokens, 100 overlap"]
        CHUNK --> EMB["nomic-embed-text v1.5<br/>local ONNX, title+heading prepended"]
    end
    EMB --> DB[("Postgres 16 + pgvector<br/>vectors + tsvector index")]

    UI["React app<br/>Ask / Extract / Stats"] --> API["FastAPI<br/>rate limits + caches"]

    API -- "/ask" --> RET["Hybrid retrieval<br/>vector + BM25 (SQL), RRF"]
    RET --> DB
    RET --> GATE{"best similarity<br/>at least 0.60?"}
    GATE -- no --> REFUSE["Refuse: not in sources"]
    GATE -- yes --> LLM["Gemini: JSON claims<br/>with passage ids + quotes"]
    LLM --> CHECK["Code checks: cited ids exist,<br/>quotes verbatim, drop uncited claims"]

    API -- "/extract" --> PAGES["Page selector<br/>statements + risk pages"]
    PAGES --> LLM2["Gemini: numbers as printed,<br/>unit labels, pages"]
    LLM2 --> VERIFY["Code: units to full amounts,<br/>sum debt, verify on page"]

    API -- "/risk-check" --> AGENT["Agent loop, max 3 steps<br/>tool: search_guidelines"]
    AGENT --> RET
```

Key ideas:
- **The LLM reads; code checks.** Citations, quotes, units and arithmetic are verified in Python,
  so a hallucinated quote or a misread unit is caught instead of shown as fact.
- **Two-stage refusal.** A similarity threshold refuses clearly unrelated questions without an
  LLM call; the model's own "not answerable" flag handles near-domain ones.
- **Everything measured.** An eval harness with 90 hand-checked questions, an LLM judge, a
  judge-vs-human agreement check, confidence intervals and a CI quality gate.

## Evaluation results

Only numbers produced by the scripts appear here (full log: [eval/results/summary.md](eval/results/summary.md)).

| Config | hit@5 | MRR | Answer correctness | Citation accuracy | Out-of-scope refusal | p50 / p95 latency |
|---|---|---|---|---|---|---|
| Baseline: vector, k = 5 | 0.800 | 0.669 | pending Gemini run | pending | pending | pending |
| **Chosen: heading embedding + hybrid, k = 5** | **0.950** | **0.819** | pending Gemini run | pending | pending | pending |

Extraction accuracy on the 5 annual reports (`eval/run_extraction_eval.py`): pending Gemini run.
Page selection already finds the correct statement page for **15 of 15** fields (tested).

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

## Run it locally

Prerequisites: Python 3.11+, Node 20+, Docker Desktop, a free Gemini API key
(<https://aistudio.google.com/apikey>).

```powershell
# 1. Configuration: copy the example and put your key in GEMINI_API_KEY
copy .env.example .env

# 2. Postgres + pgvector
docker compose up -d --wait

# 3. Backend
python -m venv .venv
.venv\Scripts\activate                       # macOS/Linux: source .venv/bin/activate
pip install -e "backend[dev]"

# 4. Documents and index (PDFs are not in git; ~5 minutes the first time)
python scripts/download_sources.py           # 10 MAS documents + 5 annual reports
python scripts/check_sources.py
python scripts/ingest.py --index heading --doc-type regulation   # what /ask searches

# 5. API (use another port if 8001 is taken)
uvicorn regulens.main:app --reload --port 8001   # docs at http://127.0.0.1:8001/docs

# 6. Frontend, in a second terminal
cd frontend; npm install; npm run dev        # http://localhost:5173

# 7. Tests, lint, evals
pytest backend                               # 125 tests; live Gemini tests run with -m live
ruff check backend scripts eval
python eval/run_eval.py --name my-run --retrieval-only   # free, no LLM calls
python eval/run_eval.py --name my-run                    # full run, uses Gemini
python eval/run_extraction_eval.py
```

If PowerShell refuses to run `activate`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
once, or call tools directly, for example `.venv\Scripts\python -m pytest backend`.

Or run everything in one container: `docker build -t regulens .` then
`docker run -p 8000:8000 --env-file .env -e DATABASE_URL=postgresql://regulens:regulens@host.docker.internal:5432/regulens regulens`.

## API

| Endpoint | What it does |
|---|---|
| `POST /ask` `{question}` | Answer + citations `[{source_id, title, page, quote, quote_verified}]`, retrieved chunk ids, latency, tokens, estimated cost, disclaimer |
| `POST /extract` (PDF upload or `source_id`) | Company, fiscal year, currency, revenue, net profit, total debt (with components), key risks; each with page + verification flag |
| `POST /risk-check` `{risks}` or `{source_id}` | Per risk: related MAS guideline passages with quotes, assessment, `needs_human_review` |
| `GET /stats` | Query count, p50/p95 latency, average cost, refusals, cache hits, latest eval scores |
| `GET /sources`, `GET /health` | Document registry; liveness/readiness (503 if the database is down) |

## Limitations

- **Small, self-written eval set.** 90 + 20 questions, drafted from the PDFs by the assistant that
  built the system and checked against the source pages; differences under ~5 points are noise,
  and an independent human review of the questions is still worth doing.
- **LLM judge bias.** The judge is a Gemini model grading Gemini answers; `eval/judge_agreement.py`
  measures agreement with a human on a sample to keep it honest.
- **Free-tier constraints.** Gemini's free quota allows a few hundred requests a day, which limits
  how many full evals and demo queries can run; costs shown are estimates at paid list prices.
- **PDF heuristics.** Heading detection and statement-page selection are rules tuned on these
  documents. Scanned PDFs (no text layer) are not supported, and complex tables can be misread;
  every extracted number is therefore verified on its page and flagged when it can't be.
- **Definitions are choices.** "Total debt" means borrowings + debt securities issued, excluding
  leases and deposits (for banks, debt securities only). Other definitions would give other numbers.
- **Single process.** Rate limits and in-memory caches are per process; multiple replicas would
  need Redis.

## Future work

- OCR fallback for scanned reports and a table-aware parser for financial statements.
- Larger, human-written eval set, including real user questions from `query_logs`.
- Track document versions (MAS revises guidelines) and re-ingest on change.
- Weighted fusion or a fine-tuned reranker, evaluated on paraphrased questions.
- Streaming answers in the UI; per-user auth and quotas.

## Repository layout

```
backend/     FastAPI app (package `regulens`) and 125 tests
frontend/    React + TypeScript app (Ask, Extract, Stats)
eval/        questions, extraction truth, eval scripts and saved results
data/        sources.csv (committed); raw/ PDFs (git-ignored, see scripts/download_sources.py)
scripts/     download_sources, check_sources, ingest
Dockerfile   one image: API + built frontend + embedding model
DEPLOY.md    step-by-step deployment to Render + Neon
```

## Progress

| Phase | Status |
|---|---|
| 0. Setup (Docker, Postgres + pgvector, FastAPI `/health`, sources registry) | ✅ Done |
| 1. Ingestion pipeline | ✅ Done |
| 2. Q&A with citations | 🟡 Built and tested with a fake LLM; live Gemini check pending the API key |
| 3. Evaluation harness | 🟡 Built; retrieval baseline measured; LLM-judged runs pending the API key |
| 4. Retrieval experiments | ✅ Done (retrieval metrics) |
| 5. Report extraction and risk agent | 🟡 Built and tested; accuracy run pending the API key |
| 6. Frontend, CI and deployment | 🟡 Built; deployment needs your Render/Neon accounts |

<details>
<summary>Checklist by phase</summary>

### Phase 1: Ingestion pipeline
- [x] 10 MAS guideline PDFs and 5 SGX annual reports in `data/raw/`, registered in `sources.csv`
- [x] `scripts/download_sources.py` and `scripts/check_sources.py`
- [x] LLM provider: Gemini (free key); embeddings: local nomic-embed-text-v1.5
- [x] PyMuPDF parsing with page numbers and nearest headings
- [x] Section-aware chunker (configurable size and overlap) with unit tests
- [x] Swappable embedder; `chunks` table with pgvector + full-text index
- [x] Idempotent `scripts/ingest.py` (15 docs, 2,360 chunks)

### Phase 2: Q&A with citations
- [x] `POST /ask` with retrieval + Gemini behind a swappable interface
- [x] Claims with chunk citations + verbatim quotes, validated by Pydantic and checked in code
- [x] Refusal guardrails; not-legal-advice disclaimer; every query logged to `query_logs`
- [ ] Live check against Gemini (needs `GEMINI_API_KEY` in `.env`)

### Phase 3: Evaluation harness
- [x] 90 eval questions (72 factual, 8 multi-hop, 10 out-of-scope) with expected pages
- [x] `eval/run_eval.py`: hit@k, MRR, judged correctness, citation accuracy, refusals, latency, cost
- [x] `eval/judge_agreement.py` for checking the LLM judge against a human
- [x] Retrieval baseline: hit@5 = 0.800, MRR = 0.669
- [ ] Full LLM-judged baseline (needs the Gemini key)
- [ ] Judge-human agreement on 20 sampled answers

### Phase 4: Retrieval experiments
- [x] BM25 in SQL, hybrid search with reciprocal rank fusion, optional cross-encoder reranker
- [x] Chunk size / overlap variants and heading-in-embedding variant, one change at a time
- [x] Paraphrased question set to check for lexical bias in the eval
- [x] Confidence intervals and paired wins/losses (`eval/compare_runs.py`)
- [x] Winner: heading embedding + hybrid (hit@5 0.800 to 0.950); reranker and chunk-size changes did not help
- [ ] Full LLM-judged comparison of baseline vs chosen config (needs the Gemini key)

### Phase 5: Report extraction and risk agent
- [x] Ground truth for the 5 reports, read from their audited statements (`eval/extraction_truth.jsonl`)
- [x] Page selection finds the right statement page for 15/15 fields
- [x] `POST /extract`: LLM copies numbers + unit labels; code converts units, sums debt, verifies on page
- [x] `POST /risk-check`: plain-Python agent loop (max 3 steps) with a guideline search tool
- [x] Prompt-injection defences tested (an injected number can never pass verification)
- [ ] Extraction accuracy run and live injection test (need the Gemini key)

### Phase 6: Frontend, CI and deployment
- [x] React app: Ask (clickable citations), Extract (table + risk check), Stats
- [x] Rate limiting; caches for repeated questions and query embeddings
- [x] GitHub Actions: lint, tests with pgvector, frontend build, 20-question smoke eval gate
- [x] Dockerfile (one image: API + frontend + embedding model) and [DEPLOY.md](DEPLOY.md)
- [ ] Deploy to Render + Neon (needs your accounts) and add the live demo link
- [ ] Add the `GEMINI_API_KEY` repository secret so the CI smoke eval runs

</details>
