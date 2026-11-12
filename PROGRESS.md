# ReguLens: progress log

## Phases

- [x] **Phase 0: Setup** (2026-11-12)
- [x] **Phase 1: Ingestion pipeline** (2026-11-12)
- [~] Phase 2: Q&A with citations (built and tested with a fake LLM; live Gemini check waits for the API key)
- [~] Phase 3: Evaluation harness (built; 90 questions; retrieval baseline measured; LLM-judged baseline waits for the API key)
- [x] **Phase 4: Retrieval experiments** (retrieval metrics done; LLM-judged comparison waits for the key)
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

---

## Phase 1: Ingestion pipeline

### Step 1: source documents (2026-11-12)
- `data/sources.csv` has 15 documents: 10 MAS regulations, 5 SGX annual reports.
  `scripts/download_sources.py` fetched all 15 with 0 failures, and `check_sources.py` passes.
- Checked each file with PyMuPDF. All have extractable text (no OCR needed):

| id | PDF pages | Main units found in text |
|---|---|---|
| mas_trm_2021 | 57 | – |
| mas_outsourcing_banks | 25 | – |
| mas_feat_2018 | 15 | – |
| mas_fair_dealing_2024 | 40 | – |
| mas_bcm_2022 | 24 | – |
| mas_iac_2020 | 23 | – |
| mas_erm_banks_2020 | 12 | – |
| mas_aml_626_guidelines | 70 | – |
| mas_cyber_hygiene_fsm_n06 | 4 | – |
| mas_ai_rm_2026 | 30 | – |
| ar_dbs_fy2025 | 107 | $ million |
| ar_ocbc_fy2025 | 276 | $ million |
| ar_singtel_fy2026 | 284 | S$ million |
| ar_keppel_fy2025 | 245 | $'000 (and some $ million) |
| ar_shengsiong_fy2025 | 128 | S$'000 |

### Decisions
| Decision | Why |
|---|---|
| Use MAS Notice **FSM-N06** on Cyber Hygiene, not Notice 655 | Notice 655 was cancelled on 10 May 2024 and replaced by FSM-N06. |
| Use the final **Guidelines on AI Risk Management (7 Oct 2026)**, not the 2024 AI model risk information paper | The final guidelines are current and directly relevant to an AI compliance tool. |
| Annual reports: 2 banks, 1 telco, 1 conglomerate, 1 retailer | A mix of reporting units (`$ million` vs `S$'000`) to test unit handling in Phase 5. |
| Citations use the **PDF page index**, not the printed page number | DBS's PDF puts two printed pages side by side on each PDF page, so printed numbers don't match. The PDF index is what a reader's viewer shows. |
| Added `scripts/download_sources.py` | PDFs are not in git, so anyone cloning the repo can rebuild `data/raw/` in one command. It rejects responses that don't start with `%PDF` (e.g. HTML error pages). |

### Step 2: the pipeline

**Built**
- `pdf_parser.py`: PyMuPDF lines with font size/bold/position become paragraphs tagged with their
  PDF page and nearest heading. Removes running headers/footers (short margin lines repeated on
  >=30% of pages), table-of-contents pages and superscript footnote markers; joins wrapped lines.
- `chunking.py`: section-aware chunker. Packs whole sentences up to `chunk_size` tokens (default
  600) with `overlap` tokens (default 100) of whole sentences; never mixes two headings; merges
  tiny sections forward. Token counts use the embedding model's own tokenizer.
- `embeddings.py`: `Embedder` interface; `FastEmbedEmbedder` runs **nomic-embed-text-v1.5
  (quantised, 768 dims)** locally via ONNX; `HashingEmbedder` for tests.
- `ingestion.py` + `scripts/ingest.py`: parse, chunk, embed, store in `chunks` (pgvector + a
  generated `tsvector` with a GIN index). Chunks are stored per **named index**
  (`index_configs.py`) so variants can coexist for experiments.
- Idempotency: a fingerprint of PDF hash + parser version + chunk settings + embedder is stored per
  (index, document). Same fingerprint: skip. Otherwise delete + insert in one transaction.
  `ingest.py` also prunes documents removed from `sources.csv`.

**Results (measured)**
- Full ingest of 15 documents: 2,360 chunks in 392 s on a laptop CPU (about 4 chunks/s for
  embedding). Re-running skips all 15 documents in under a second.
- Chunk sizes: regulations 366 chunks, median 263 tokens; annual reports 1,994 chunks, median 301.
- `pytest backend`: 58 tests at the end of Phase 1 (parser, chunker, idempotent ingest, pruning).

**Senior-engineer critique and the fixes it led to**

| Problem found (with evidence) | Fix | After |
|---|---|---|
| Annual reports shattered into tiny chunks: median 117 tokens, 1,674 of 3,741 under 100 tokens. KPI call-outs and director names were detected as headings. | Annual reports merge sections under 200 tokens (`REPORT_MIN_SECTION_TOKENS`); MAS guidelines keep strict sections. | 1,994 chunks, median 301, 8 under 100 |
| Footnote markers glued to words ("notification19") in 90 regulation chunks, which breaks full-text search. | Drop superscript digit spans (PyMuPDF flag bit 1); parser version bumped so everything re-ingested automatically. | 0 |
| Table-of-contents pages produced junk headings ("3.2" plus dot leaders). | Drop pages with >=5 dot-leader lines; dot-leader lines never count as headings. | TRM headings now "4.2 Risk Identification" etc. |
| Bold phrases wrapping mid-sentence detected as headings ("policies, and practices across..."). | Headings may not start lowercase or end on a connector word ("the", "of", "and"...). | AI guideline headings clean |
| ONNX Runtime `bad_alloc` during the first full ingest (batch 16 x ~600 tokens, ~2 GB RSS). | Embed in batches of 8. | Full ingest completes |
| Documents removed from sources.csv stayed in the index, and skipped documents kept stale titles. | `prune_index`; metadata upserted on every run. | Tested |

### Decisions

| Decision | Why |
|---|---|
| Local embedding model (nomic-embed-text-v1.5-Q) instead of Gemini embeddings | No API cost or rate limits (the Gemini free tier is tight), and repeatable experiments. It accepts 8,192 tokens, so 600-token chunks are embedded whole; bge-small cuts input at 512. |
| Exact vector search, no HNSW index | About 2.4k chunks: an exact scan takes milliseconds and has perfect recall. HNSW pays off past ~100k rows. |
| `vector` column without a fixed dimension | The model can change without a migration; ingest refuses to mix dimensions within one index. |
| Per-document transactions (autocommit connection + `conn.transaction()`) | A failure on document 10 must not roll back documents 1-9. |
| Chunk size measured in the embedding model's tokens | "600 tokens" means exactly what the model sees. |

---

## Phase 2: Q&A with citations (built; live check pending the Gemini key)

**Built**
- `retrieval.py`: vector search (cosine) over `regulation` chunks of a named index.
- `llm.py`: `LLMClient` interface with `GeminiClient` (structured JSON via `response_json_schema`,
  temperature 0, client-side pacing per model, retries on 429/5xx honouring the server's
  `retryDelay`, daily-quota errors raised immediately), `CachedLLM` (responses stored in Postgres
  `llm_cache`, keyed by a hash of model + prompts + schema) and `FakeLLM` for tests.
- `qa.py`: the prompt labels passages C1..Ck; the LLM returns claims, each citing passage ids with
  a verbatim quote. Code then drops citations to non-existent passages, **verifies every quote
  against the chunk text** (if it is not verbatim, the closest real sentence is shown and the
  citation is marked `quote_verified: false`) and drops claims left without a citation.
- Guardrails: reply "I couldn't find this in the sources." when the best cosine similarity is below
  `MIN_RETRIEVAL_SCORE` (no LLM call), when the model says the passages don't answer it, or when no
  claim keeps a valid citation. Every response carries a not-legal-advice disclaimer.
- `POST /ask` returns `{answer, citations[{marker, source_id, title, page, page_end, quote,
  quote_verified}], refused, refusal_reason, retrieved_chunk_ids, top_score, latency_ms, tokens,
  cost_usd, model, cached, disclaimer}`. Every query is logged to `query_logs`.

**Decisions**

| Decision | Why |
|---|---|
| Gemini (free key) behind a provider-neutral interface | User's choice. The rest of the code only sees `generate_json(system, prompt, schema)`. |
| Claims + per-citation quotes instead of free text with [n] | Lets code verify every citation mechanically, and the UI can show the exact quoted passage. |
| Cache LLM responses in Postgres; a cache hit reports the original latency/tokens | Re-running evals costs nothing on a tight free tier, and statistics stay honest. |
| `cost_usd` is an estimate at the paid-tier list price | On the free tier real cost is $0; the estimate shows what it would cost in production. |

---

## Phase 3: Evaluation harness (built; LLM-judged run pending the Gemini key)

**Built**
- `eval/questions.jsonl`: **90 questions**: 72 factual, 8 multi-hop (each spanning two MAS
  documents), 10 out-of-scope (several deliberately near-domain: SORA rate, Notice 637 capital
  ratios, EU AI Act, DBS profit). Every in-scope question has its expected PDF page(s).
  *Authorship note:* the brief planned for the student to write these. At the user's request they
  were drafted by Claude from the source PDFs, page by page; each expected answer and page was
  checked against the PDF text. A human review of a sample is still recommended.
- `regulens/evaluation.py` + `eval/run_eval.py`: hit@k and MRR (page-range overlap; multi-hop needs
  every source), LLM-judge correctness (0 / 0.5 / 1 rubric), citation accuracy (the judge checks
  each [n] marker against its passage), out-of-scope refusal rate, false-refusal rate, p50/p95
  latency, average cost. `--retrieval-only` scores retrieval with no LLM calls. Each run is saved as
  JSON in `eval/results/` and adds a row to `eval/results/summary.md`.
- `eval/judge_agreement.py`: samples 20 judged answers into a CSV for blind human grading and
  computes judge-human agreement.

**Results (measured)**

| Run | hit@5 | MRR | Notes |
|---|---|---|---|
| baseline-vector-k5 (retrieval only) | 0.800 | 0.669 | 80 in-scope questions |

Misses worth noting: all 5 questions on the 4-page cyber hygiene notice miss. The relevant chunk
packs six different controls together, and the questions use terms ("FSM-N06", "multi-factor
authentication") that keyword search would match but the diluted embedding does not rank highly.
This motivates the hybrid-search and heading-in-embedding experiments in Phase 4.

---

## Phase 4: Retrieval experiments

**Built**
- `retrieval.py`: three rankers (`vector`, `fts` = BM25 computed in SQL from the `tsvector`
  index, `hybrid` = reciprocal rank fusion of both), an optional cross-encoder reranker
  (`reranker.py`, fastembed), and every chunk carries its cosine similarity so the refusal
  guardrail behaves the same in every mode.
- Index variants in `index_configs.py` (`c300_o50`, `c800_o150`, `c600_o0`, `heading`), ingested
  for regulations only (`ingest.py --doc-type regulation`).
- `eval/questions_paraphrased.jsonl` (20 plain-language rewrites) and `eval/compare_runs.py`
  (bootstrap 95% CI + paired wins/losses).

**Results**: see the README "Experiments" section (all rows are in `eval/results/summary.md`).
Chosen: `heading` index + `hybrid`, k = 5, no reranker. hit@5 0.800 to 0.950 (+12/-0),
MRR 0.669 to 0.819; paraphrased set 0.600 to 0.800.

**Decisions**

| Decision | Why |
|---|---|
| BM25 written in SQL instead of `ts_rank` | `ts_rank` has no IDF, so frequent words ("bank", "should") count as much as rare, decisive ones ("SRTO"). |
| Reciprocal rank fusion with k = 60 | Uses ranks only, so cosine and BM25 scores never need to be put on the same scale; 60 is the standard constant. No weight tuning, to avoid overfitting 80 questions. |
| No reranker by default | Did not improve the chosen config and adds ~1.3 s per query on CPU. Still available (`RERANK=true`). |
| Paraphrased question set | Questions written from the text favoured keyword search; the check changed the conclusion (BM25-only dropped from 0.912 to 0.600). |
| Threshold 0.60 | Below the lowest in-scope similarity (0.656) with margin; catches clearly unrelated questions without an LLM call. |

**Critique**
- The eval set is small (80 + 20 questions): differences under ~5 points are within noise, so
  decisions were made on paired wins/losses and confidence intervals, not single numbers.
- The `heading` index holds regulations only (Q&A never searches annual reports). The
  `baseline` index keeps all 15 documents.
- Hybrid search runs the BM25 query over all chunks in scope (no precomputed statistics). At about
  370 regulation chunks this takes about 30 ms; with 100k+ chunks the document-frequency
  statistics should be precomputed into a table.

---

## Open questions / notes
- **Gemini free-tier limits** (reported late 2026, not guaranteed): about 5 RPM / 20 RPD for Flash
  and 15 RPM / 500 RPD for Flash-Lite, per project. A 90-question run needs about 170 calls (answer
  + judge), so the default model is Flash-Lite, requests are paced, and every response is cached.
- Local dev note: port 8000 was already in use on the dev machine, so the API was tested on 8001.
- Starlette prints a deprecation warning about `httpx` in the TestClient. It's harmless; revisit
  when upgrading.
