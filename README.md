# ReguLens

[![CI](https://github.com/William35-f/AI-compliance-assistant-for-finance/actions/workflows/ci.yml/badge.svg)](https://github.com/William35-f/AI-compliance-assistant-for-finance/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/version-1.0.0-0F5E66)
![Python](https://img.shields.io/badge/python-3.11%2B-18222E)
![React](https://img.shields.io/badge/react-18-18222E)

**An AI assistant for Singapore financial compliance, where every answer sits next to its
evidence.** Ask a question about MAS (Monetary Authority of Singapore) rules and ReguLens answers
only from the official documents: each point cites a document, page and verbatim quote that the
code checks against the source, and the cited page opens beside the answer with the paragraph
highlighted. If the documents don't cover the question, it says so instead of guessing.

It also extracts revenue, net profit, total debt and key risks from SGX-listed companies' annual
reports (each number verified on its statement page), and links those risks to the MAS guidelines
that cover them.

![ReguLens answering a question about incident notification, with the cited MAS paragraph highlighted beside the answer](docs/images/ask-light.png)

**v1.0.0 at a glance** (90-question evaluation): answer correctness **0.89** · citation accuracy
**0.99** · out-of-scope questions refused **100%** · retrieval hit@5 **0.80 → 0.95** · median
answer **6 s** · about **$0.0003** per question.

**Live demo:** _not deployed yet_ (see [DEPLOY.md](DEPLOY.md)) · [Changelog](CHANGELOG.md) ·
[Build log and decisions](PROGRESS.md) · [Demo test report](docs/demo-test/TEST_LOG.md)

> ReguLens is a research and portfolio project. It is not legal or regulatory advice; always
> check the cited source documents.

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Documents covered](#documents-covered)
- [Tech stack](#tech-stack)
- [Evaluation results](#evaluation-results)
- [Demo test in the real UI](#demo-test-in-the-real-ui)
- [Retrieval experiments](#retrieval-experiments)
- [Run it locally](#run-it-locally)
- [Configuration](#configuration)
- [API](#api)
- [Project structure](#project-structure)
- [Limitations](#limitations)
- [Future work](#future-work)
- [Progress](#progress)

## What it does

| Page | What you can do |
|---|---|
| **Ask** | Ask about MAS guidelines and notices. The answer is a one-line summary plus numbered points, each with citation chips. The right-hand panel shows the cited page with the document's own paragraph numbers and the cited paragraph highlighted; click any chip or source to switch. Shows sources cited, response time and cost per question. |
| **Extract** | Pick one of 5 SGX annual reports (or upload a PDF) and get revenue, net profit and total debt in full amounts, each with the number as printed, its page, and whether it was verified on that page, plus the key risk disclosures. |
| **Risk check** | For a report's top risks, or a risk you describe, find the MAS guideline passages that cover it and flag the ones a person should review. |
| **Stats and evals** | Live usage (questions, response times, cost, refusals, cache hits) and the latest evaluation scores. |

Light and dark themes, a phone layout with a bottom navigation bar, visible keyboard focus,
44 px touch targets and WCAG AA contrast throughout.

| Dark theme | Phone |
|---|---|
| ![Ask page in the dark theme](docs/images/ask-dark.png) | ![Ask page on a phone](docs/images/ask-mobile.png) |

| Extract from a report | Stats and evals |
|---|---|
| ![Extraction of DBS figures, each verified on its page](docs/images/extract.png) | ![Stats page with the v1 evaluation scores](docs/images/stats.png) |

## How it works

```mermaid
flowchart LR
    subgraph Offline["Offline ingestion (scripts/ingest.py)"]
        PDF["MAS + SGX PDFs"] --> PARSE["PyMuPDF parser<br/>page + nearest heading"]
        PARSE --> CHUNK["Section-aware chunker<br/>600 tokens, 100 overlap"]
        CHUNK --> EMB["nomic-embed-text v1.5<br/>local ONNX, title+heading prepended"]
    end
    EMB --> DB[("Postgres 16 + pgvector<br/>vectors + tsvector index")]

    UI["React app<br/>Ask / Extract / Risk check / Stats"] --> API["FastAPI<br/>rate limits + caches"]

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

**The LLM reads; code checks.** The model only writes language. Everything that can be checked is
checked in Python before it reaches the screen:

| Check | What it prevents |
|---|---|
| Cited passage ids must exist; claims without a valid citation are dropped | Answers built on nothing |
| Every quote is matched word for word against its passage; if it isn't found, the closest real sentence is shown and flagged "closest match" | Made-up quotes |
| The one-line summary heading is rejected if it contains a number the cited points don't | Invented time limits or figures in the heading |
| "Must" becomes "should" when the cited guideline says "should" | Overstating how binding a guideline is |
| Two-stage refusal: a similarity threshold, then the model's own "not answerable" flag | Guessing outside the documents |
| Extracted numbers: units converted and totals summed in code, each number verified on its page | Misread units and arithmetic slips |

Other key ideas:
- **The LLM reads; code checks.** Citations, quotes, units and arithmetic are verified in Python,
  so a hallucinated quote or a misread unit is caught instead of shown as fact.
- **Two-stage refusal.** A similarity threshold refuses clearly unrelated questions without an
  LLM call; the model's own "not answerable" flag handles near-domain ones.
- **Everything measured.** An eval harness with 90 hand-checked questions, an LLM judge, a
  judge-vs-human agreement check, confidence intervals and a CI quality gate.

## Documents covered

Answers come only from these 10 MAS publications (the PDFs are downloaded by a script, not stored
in git; see `data/sources.csv`):

| MAS publication |
|---|
| Technology Risk Management Guidelines (January 2021) |
| MAS Notice FSM-N06 on Cyber Hygiene (Banks) |
| Guidelines on Business Continuity Management (June 2022) |
| Guidelines on Outsourcing (Banks) |
| Guidelines to MAS Notice 626 on Prevention of Money Laundering and Countering the Financing of Terrorism (Banks) |
| Guidelines on Individual Accountability and Conduct (September 2020) |
| Guidelines on Fair Dealing: Board and Senior Management Responsibilities (May 2024) |
| Guidelines on Environmental Risk Management for Banks (December 2020) |
| Principles to Promote Fairness, Ethics, Accountability and Transparency (FEAT) in the Use of AI and Data Analytics (2018) |
| Guidelines on Artificial Intelligence Risk Management (October 2026) |

Annual reports for extraction: DBS Group Holdings 2025, OCBC 2025, Singtel 2026 (FY to 31 March),
Keppel 2025 and Sheng Siong Group 2025.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic, psycopg 3 |
| Database and search | PostgreSQL 16 + pgvector (vectors) and Postgres full-text search (BM25-style), fused with reciprocal rank fusion |
| Embeddings | nomic-embed-text v1.5, run locally (ONNX via fastembed) |
| LLM | Google Gemini (`gemini-3.5-flash-lite`) through a swappable client with a response cache |
| PDF parsing | PyMuPDF |
| Frontend | React 18, TypeScript, Vite |
| Quality | pytest (162 tests), ruff, GitHub Actions with a 20-question smoke eval gate |
| Packaging | Docker Compose for local Postgres; one Docker image for API + frontend + embedding model |

## Evaluation results

Only numbers produced by the scripts appear here (full log: [eval/results/summary.md](eval/results/summary.md)).

| Config | hit@5 | MRR | Answer correctness | Citation accuracy | Out-of-scope refusal | p50 / p95 latency |
|---|---|---|---|---|---|---|
| Baseline: vector, k = 5 | 0.800 | 0.669 | not run yet | – | – | – |
| **Chosen: heading embedding + hybrid, k = 5 (v1.0.0)** | **0.950** | **0.819** | **0.887** | **0.987** | **1.000** | 6.3 s / 7.2 s |

v1.0.0 in more detail (run `20261113T081952Z`, `gemini-3.5-flash-lite` answering and judging):
factual 0.896, multi-hop 0.813; false refusals 3 of 80 in-scope questions (0.04); 3% of quotes
not verbatim (shown as "closest match"); estimated cost $0.0003 per question at paid-tier prices.
Answer correctness is 71 of 80 with a 95% interval of about ±0.06, so it matches the previous full
run (0.900, run `20261112T154112Z`) within noise: 8 questions moved by half a point, 5 down and 3
up, mostly answers that kept the main point but dropped a secondary detail.

What changed in v1 and how it was checked: answers now carry a one-line summary heading (its
numbers must appear in the cited claims), and "must" is rewritten to "should" when the cited
source says "should", because MAS guidelines are expectations, not legal requirements. A
[32-question demo test](docs/demo-test/TEST_LOG.md) in the real UI found that 10 of 26 answers
had hardened "should" into "must"; in the v1 eval, "must" appears 22 times across the answers
instead of 41.

Extraction on the 5 annual reports (`eval/run_extraction_eval.py`): revenue, net profit and total
debt **15 of 15 correct**, each on the right page and verified on it; fiscal year, currency and
key risks 5 of 5; company name 4 of 5 (the model wrote OCBC as "Overseas-Chinese" instead of
"Oversea-Chinese").

## Demo test in the real UI

32 common bank compliance questions (AML and customer due diligence, incident reporting,
technology and cyber risk, outsourcing, AI governance, conduct), worded the way a compliance
officer would ask, were typed into the Ask page in Chrome, and every answer was checked by hand
against its highlighted source.

| | Result |
|---|---|
| Answered or refused correctly | **32 of 32** (26 answered, 6 out-of-scope refused, including a request to ignore the sources) |
| Answers factually correct | 24 of 26, 2 partly, 0 wrong |
| Typical response time | 2.4 s |

Full log with every answer and screenshot: [docs/demo-test/TEST_LOG.md](docs/demo-test/TEST_LOG.md)
(also as a [Word report](docs/demo-test/ReguLens-demo-test-report.docx)); blank template for new
rounds: [TEMPLATE.md](docs/demo-test/TEMPLATE.md). The test found that answers tended to turn
"should" into "must", which v1 fixes in code.

## Retrieval experiments

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

**Quick start** (after the one-time setup below): start Docker Desktop, then

```powershell
docker compose up -d --wait                              # Postgres + pgvector
.venv\Scripts\activate
uvicorn regulens.main:app --port 8001                     # open http://127.0.0.1:8001
```

The API serves the built frontend (`frontend/dist`) on the same port, so the whole app is at
<http://127.0.0.1:8001> and the API docs at <http://127.0.0.1:8001/docs>. Run
`cd frontend; npm install; npm run build` once first, or use `npm run dev` (port 5173) while
working on the frontend.

**One-time setup**

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
pytest backend                               # 160 tests; live Gemini tests run with -m live
ruff check backend scripts eval
python eval/run_eval.py --name my-run --retrieval-only   # free, no LLM calls
python eval/run_eval.py --name my-run                    # full run, uses Gemini
python eval/run_extraction_eval.py
```

If PowerShell refuses to run `activate`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
once, or call tools directly, for example `.venv\Scripts\python -m pytest backend`.

Or run everything in one container: `docker build -t regulens .` then
`docker run -p 8000:8000 --env-file .env -e DATABASE_URL=postgresql://regulens:regulens@host.docker.internal:5432/regulens regulens`.

## Configuration

Settings are read from `.env` in the repo root (copy `.env.example`). The main ones:

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | (required) | Free key from <https://aistudio.google.com/apikey> |
| `DATABASE_URL` | `postgresql://regulens:regulens@localhost:5432/regulens` | Postgres connection |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model that answers questions |
| `GEMINI_JUDGE_MODEL` | `gemini-3.5-flash-lite` | Model that grades answers in evals |
| `GEMINI_REQUESTS_PER_MINUTE` | `10` | Client-side pacing for the free tier |
| `GEMINI_MAX_RETRIES` | `4` | Retries on 429/5xx and network errors (use 8 for long eval runs) |
| `RETRIEVAL_MODE` / `RETRIEVAL_K` | `hybrid` / `5` | Search mode (`vector`, `fts`, `hybrid`) and passages per question |
| `MIN_RETRIEVAL_SCORE` | `0.60` | Below this best-match similarity, refuse without calling the LLM |
| `RATE_LIMIT_ASK_PER_MINUTE` | `10` | Questions allowed per minute |
| `RATE_LIMIT_HEAVY_PER_HOUR` | `6` | `/extract` and `/risk-check` calls allowed per hour |

## API

| Endpoint | What it does |
|---|---|
| `POST /ask` `{question}` | Answer + citations `[{source_id, title, page, quote, quote_verified}]`, retrieved chunk ids, latency, tokens, estimated cost, disclaimer |
| `POST /extract` (PDF upload or `source_id`) | Company, fiscal year, currency, revenue, net profit, total debt (with components), key risks; each with page + verification flag |
| `POST /risk-check` `{risks}` or `{source_id}` | Per risk: related MAS guideline passages with quotes, assessment, `needs_human_review` |
| `GET /stats` | Query count, p50/p95 latency, average cost, refusals, cache hits, latest eval scores |
| `GET /sources/{id}/pages/{page}?quote=` | One page as paragraphs (with the document's own paragraph numbers), the paragraph holding the quote flagged; powers the source panel |
| `GET /sources`, `GET /health` | Document registry; liveness/readiness (503 if the database is down) |

## Project structure

```
backend/         FastAPI app (package `regulens`) and 162 tests
  regulens/      qa.py (answers + checks), retrieval.py, extraction.py, risk_agent.py,
                 page_view.py (source panel), llm.py (Gemini client + cache), main.py (API)
frontend/        React + TypeScript app: Ask, Extract, Risk check, Stats and evals
eval/            questions, extraction truth, eval scripts and saved results
docs/demo-test/  32-question demo test: log, Word report, screenshots, template
docs/images/     README screenshots
data/            sources.csv (committed); raw/ PDFs (git-ignored, see scripts/download_sources.py)
scripts/         download_sources, check_sources, ingest
Dockerfile       one image: API + built frontend + embedding model
DEPLOY.md        step-by-step deployment to Render + Neon
CHANGELOG.md     release notes
PROGRESS.md      build log: what was built, measured and decided, phase by phase
```

## Limitations

- **Small, self-written eval set.** 90 + 20 questions, drafted with AI assistance from the PDFs and
  checked against the source pages; differences under ~5 points are noise,
  and an independent human review of the questions is still worth doing.
- **LLM judge bias.** The judge is a Gemini model grading Gemini answers; `eval/judge_agreement.py`
  measures agreement with a human on a sample to keep it honest.
- **Free-tier constraints.** Gemini's free quota allows a few hundred requests a day, which limits
  how many full evals and demo queries can run, and free-tier models are often overloaded (503),
  which makes latency unpredictable. Costs shown are estimates at paid list prices; the real cost
  on the free tier is $0.
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

## Progress

| Phase | Status |
|---|---|
| 0. Setup (Docker, Postgres + pgvector, FastAPI `/health`, sources registry) | ✅ Done |
| 1. Ingestion pipeline | ✅ Done |
| 2. Q&A with citations | ✅ Done (live on Gemini) |
| 3. Evaluation harness | ✅ Done; v1.0.0: correctness 0.89, citation accuracy 0.99, out-of-scope refusal 1.00 |
| 4. Retrieval experiments | ✅ Done (retrieval metrics) |
| 5. Report extraction and risk agent | ✅ Done; extraction 15/15 numbers correct |
| 6. Frontend, CI and deployment | 🟡 Built; public deployment planned (see [DEPLOY.md](DEPLOY.md)) |

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
- [x] Live check against Gemini

### Phase 3: Evaluation harness
- [x] 90 eval questions (72 factual, 8 multi-hop, 10 out-of-scope) with expected pages
- [x] `eval/run_eval.py`: hit@k, MRR, judged correctness, citation accuracy, refusals, latency, cost
- [x] `eval/judge_agreement.py` for checking the LLM judge against a human
- [x] Retrieval baseline: hit@5 = 0.800, MRR = 0.669
- [x] Full LLM-judged run of the chosen config (correctness 0.900), repeated for v1.0.0 (0.887, same within noise)
- [ ] Judge-human agreement on 20 sampled answers

### Phase 4: Retrieval experiments
- [x] BM25 in SQL, hybrid search with reciprocal rank fusion, optional cross-encoder reranker
- [x] Chunk size / overlap variants and heading-in-embedding variant, one change at a time
- [x] Paraphrased question set to check for lexical bias in the eval
- [x] Confidence intervals and paired wins/losses (`eval/compare_runs.py`)
- [x] Winner: heading embedding + hybrid (hit@5 0.800 to 0.950); reranker and chunk-size changes did not help
- [ ] Full LLM-judged comparison of baseline vs chosen config (~170 more free-tier calls)

### Phase 5: Report extraction and risk agent
- [x] Ground truth for the 5 reports, read from their audited statements (`eval/extraction_truth.jsonl`)
- [x] Page selection finds the right statement page for 15/15 fields
- [x] `POST /extract`: LLM copies numbers + unit labels; code converts units, sums debt, verifies on page
- [x] `POST /risk-check`: plain-Python agent loop (max 3 steps) with a guideline search tool
- [x] Prompt-injection defences tested (an injected number can never pass verification)
- [x] Extraction accuracy run (15/15 numbers) and live injection test (passed)

### Phase 6: Frontend, CI and deployment
- [x] React app: Ask (clickable citations), Extract (table + risk check), Risk check, Stats
- [x] Ask redesign: answer beside the cited page, cited paragraph highlighted (located for 147/147 eval citations)
- [x] Summary heading checked against the claims; "must" softened to "should" when the source says "should"
- [x] Risk check page, light/dark themes, 44 px touch targets, WCAG AA contrast
- [x] [32-question demo test](docs/demo-test/TEST_LOG.md) in the real UI: 32/32 answered or refused correctly
- [x] Rate limiting; caches for repeated questions and query embeddings
- [x] GitHub Actions: lint, tests with pgvector, frontend build, 20-question smoke eval gate
- [x] Dockerfile (one image: API + frontend + embedding model) and [DEPLOY.md](DEPLOY.md)
- [ ] Deploy to Render + Neon and add the live demo link
- [ ] Add the `GEMINI_API_KEY` repository secret so the CI smoke eval runs

</details>

## Author

Built by [William35-f](https://github.com/William35-f).
