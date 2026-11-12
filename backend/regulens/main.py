"""FastAPI application entry point.

Run locally with:  uvicorn regulens.main:app --reload
"""

import json
import logging
import tempfile
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from regulens import __version__, db
from regulens.config import RAW_DIR, REPO_ROOT, SOURCES_CSV, get_settings
from regulens.embeddings import Embedder, get_embedder
from regulens.extraction import ExtractionResult, KeyRisk, extract_report
from regulens.llm import LLMClient, LLMError, LLMQuotaExceeded, make_llm
from regulens.protection import (
    CachedQueryEmbedder,
    SlidingWindowLimiter,
    TTLCache,
    normalise_question,
    rate_limit,
)
from regulens.qa import AskResponse, QAConfig, answer_question, log_query
from regulens.report_pages import ReportTooLarge
from regulens.reranker import Reranker, get_reranker
from regulens.retrieval import RetrievalConfig
from regulens.risk_agent import RiskCheckResult, check_risks
from regulens.sources import load_sources

logger = logging.getLogger("regulens")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs once at startup: make sure the schema exists.

    If the database is down we still start, so /health can report the problem
    instead of the whole app crashing.
    """
    try:
        db.init_db()
        logger.info("Database schema is ready")
    except psycopg.OperationalError as exc:
        logger.warning("Database unreachable at startup, continuing anyway: %s", exc)
    yield


app = FastAPI(title="ReguLens", version=__version__, lifespan=lifespan)


# --------------------------------------------------------------------------- dependencies
# Tests replace these with fakes via app.dependency_overrides.


def get_db() -> Iterator[psycopg.Connection]:
    try:
        conn = db.connect()
    except psycopg.OperationalError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from exc
    with conn:
        yield conn


def get_llm() -> LLMClient:
    try:
        return make_llm()
    except LLMError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def get_qa_config() -> QAConfig:
    settings = get_settings()
    return QAConfig(
        retrieval=RetrievalConfig(
            mode=settings.retrieval_mode,
            index_name=settings.default_index,
            k=settings.retrieval_k,
            rerank=settings.rerank,
        ),
        min_retrieval_score=settings.min_retrieval_score,
    )


def get_optional_reranker() -> Reranker | None:
    """Load the cross-encoder only when reranking is switched on."""
    return get_reranker() if get_settings().rerank else None


_query_embedder: CachedQueryEmbedder | None = None


def get_api_embedder() -> Embedder:
    """The shared embedder, with an in-memory cache for repeated questions."""
    global _query_embedder
    if _query_embedder is None:
        _query_embedder = CachedQueryEmbedder(get_embedder())
    return _query_embedder


# Per-client limits. Each /ask costs 1 LLM call, /extract 1 big call, /risk-check up to 10.
ASK_LIMIT = SlidingWindowLimiter(limit=get_settings().rate_limit_ask_per_minute, window_s=60)
EXTRACT_LIMIT = SlidingWindowLimiter(limit=get_settings().rate_limit_heavy_per_hour, window_s=3600)
RISK_LIMIT = SlidingWindowLimiter(limit=get_settings().rate_limit_heavy_per_hour, window_s=3600)

ANSWER_CACHE = TTLCache(max_items=500, ttl_s=3600)


# --------------------------------------------------------------------------- endpoints


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unreachable", "pgvector_missing"]
    pgvector_version: str | None = None
    version: str = __version__


@app.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    """Liveness + readiness check.

    Returns 200 when the API, Postgres and pgvector all work, otherwise 503.
    Deployment hosts call this endpoint to decide whether the app is healthy.
    """
    try:
        version = db.pgvector_version()
    except psycopg.OperationalError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", database="unreachable")

    if version is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", database="pgvector_missing")

    return HealthResponse(status="ok", database="ok", pgvector_version=version)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(rate_limit(ASK_LIMIT))])
def ask(
    request: AskRequest,
    conn: Annotated[psycopg.Connection, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_api_embedder)],
    llm: Annotated[LLMClient, Depends(get_llm)],
    config: Annotated[QAConfig, Depends(get_qa_config)],
    reranker: Annotated[Reranker | None, Depends(get_optional_reranker)],
) -> AskResponse:
    """Answer a question about MAS guidelines, with a citation for every claim."""
    started = time.perf_counter()
    question = request.question.strip()
    cache_key = (normalise_question(question), config, llm.model)
    cached = ANSWER_CACHE.get(cache_key)
    if isinstance(cached, AskResponse):
        response = cached.model_copy(
            update={"cached": True, "latency_ms": int((time.perf_counter() - started) * 1000)}
        )
        log_query(conn, question, response, config, "api")
        return response
    try:
        response = answer_question(conn, question, embedder, llm, config, reranker=reranker)
        ANSWER_CACHE.put(cache_key, response)
        return response
    except LLMQuotaExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except LLMError as exc:
        logger.exception("LLM failure")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The language model failed") from exc


# --------------------------------------------------------------------------- reports

MAX_UPLOAD_BYTES = 40 * 1024 * 1024  # annual reports in our corpus are up to ~17 MB


def _report_path(source_id: str) -> Path:
    """Resolve a source id from sources.csv to its downloaded annual report PDF."""
    sources = {s.id: s for s in load_sources(SOURCES_CSV)}
    source = sources.get(source_id)
    if source is None or source.doc_type != "annual_report":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No annual report with id '{source_id}'")
    path = source.pdf_path(RAW_DIR)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"PDF for '{source_id}' is not downloaded")
    return path


def _run_extraction(path: Path, llm: LLMClient, source_id: str | None) -> ExtractionResult:
    try:
        return extract_report(path, llm, source_id=source_id)
    except ReportTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    except LLMQuotaExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except LLMError as exc:
        logger.exception("LLM failure during extraction")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The language model failed") from exc


@app.post(
    "/extract", response_model=ExtractionResult, dependencies=[Depends(rate_limit(EXTRACT_LIMIT))]
)
async def extract(
    llm: Annotated[LLMClient, Depends(get_llm)],
    file: Annotated[UploadFile | None, File(description="Annual report PDF")] = None,
    source_id: Annotated[str | None, Form(description="Or: id of a report in sources.csv")] = None,
) -> ExtractionResult:
    """Extract revenue, net profit, total debt and key risks, each with a page reference."""
    if (file is None) == (source_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Send either a file or a source_id"
        )
    if source_id is not None:
        return await run_in_threadpool(_run_extraction, _report_path(source_id), llm, source_id)

    assert file is not None
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "PDF is larger than 40 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File is not a PDF")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(data)
        return await run_in_threadpool(_run_extraction, path, llm, None)


class RiskCheckRequest(BaseModel):
    source_id: str | None = Field(
        default=None, description="Annual report id to extract risks from"
    )
    risks: list[KeyRisk] | None = Field(
        default=None, description="Or: risks from a previous /extract"
    )
    max_risks: int = Field(default=3, ge=1, le=6, description="Each risk costs up to 3 LLM calls")


@app.post(
    "/risk-check", response_model=RiskCheckResult, dependencies=[Depends(rate_limit(RISK_LIMIT))]
)
def risk_check(
    request: RiskCheckRequest,
    conn: Annotated[psycopg.Connection, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_api_embedder)],
    llm: Annotated[LLMClient, Depends(get_llm)],
    config: Annotated[QAConfig, Depends(get_qa_config)],
) -> RiskCheckResult:
    """For each disclosed risk, find related MAS guidelines and flag possible gaps."""
    if (request.risks is None) == (request.source_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Send either risks or a source_id"
        )
    risks = request.risks
    if risks is None:
        assert request.source_id is not None
        risks = _run_extraction(_report_path(request.source_id), llm, request.source_id).key_risks
    try:
        return check_risks(conn, risks[: request.max_risks], embedder, llm, config.retrieval)
    except LLMQuotaExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except LLMError as exc:
        logger.exception("LLM failure during risk check")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The language model failed") from exc


# --------------------------------------------------------------------------- sources


class SourceInfo(BaseModel):
    id: str
    title: str
    publisher: str
    doc_type: str
    url: str
    downloaded: bool


@app.get("/sources", response_model=list[SourceInfo])
def list_sources(
    doc_type: Literal["regulation", "annual_report"] | None = None,
) -> list[SourceInfo]:
    """Documents in data/sources.csv (used by the frontend's report picker)."""
    return [
        SourceInfo(
            id=s.id,
            title=s.title,
            publisher=s.publisher,
            doc_type=s.doc_type,
            url=str(s.url),
            downloaded=s.pdf_path(RAW_DIR).is_file(),
        )
        for s in load_sources(SOURCES_CSV)
        if doc_type is None or s.doc_type == doc_type
    ]


# --------------------------------------------------------------------------- stats

EVAL_RESULTS_DIR = REPO_ROOT / "eval" / "results"


class UsageStats(BaseModel):
    queries: int
    refused: int
    cached: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    avg_cost_usd: float | None
    first_query_at: str | None


class EvalSnapshot(BaseModel):
    run: str
    timestamp: str
    config: dict
    metrics: dict


class StatsResponse(BaseModel):
    usage: UsageStats
    latest_eval: EvalSnapshot | None  # latest full (LLM-judged) run on the main question set
    latest_retrieval_eval: EvalSnapshot | None  # latest retrieval-only run of the live config
    rate_limits: dict[str, str]


def _latest_eval(full: bool) -> EvalSnapshot | None:
    """Most recent saved eval run of the configuration the API is serving."""
    settings = get_settings()
    for path in sorted(EVAL_RESULTS_DIR.glob("*.json"), reverse=True):
        if "extraction" in path.name or path.name.startswith("judge"):
            continue
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cfg = run.get("config", {})
        if cfg.get("questions_file") != "questions.jsonl" or cfg.get("retrieval_only") == full:
            continue
        if not full and (
            cfg.get("index") != settings.default_index
            or cfg.get("mode") != settings.retrieval_mode
            or cfg.get("rerank", False) != settings.rerank
        ):
            continue
        return EvalSnapshot(
            run=run["run"], timestamp=run["timestamp"], config=cfg, metrics=run["metrics"]
        )
    return None


@app.get("/stats", response_model=StatsResponse)
def stats(conn: Annotated[psycopg.Connection, Depends(get_db)]) -> StatsResponse:
    """Usage of the public API (eval traffic excluded) and the latest eval scores."""
    row = conn.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE refused), count(*) FILTER (WHERE cached),
               percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms),
               percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms),
               avg(cost_usd), min(created_at)
        FROM query_logs WHERE origin = 'api'
        """
    ).fetchone()
    assert row is not None
    settings = get_settings()
    return StatsResponse(
        usage=UsageStats(
            queries=row[0],
            refused=row[1],
            cached=row[2],
            latency_p50_ms=row[3],
            latency_p95_ms=row[4],
            avg_cost_usd=float(row[5]) if row[5] is not None else None,
            first_query_at=row[6].isoformat() if row[6] else None,
        ),
        latest_eval=_latest_eval(full=True),
        latest_retrieval_eval=_latest_eval(full=False),
        rate_limits={
            "ask": f"{settings.rate_limit_ask_per_minute} per minute",
            "extract": f"{settings.rate_limit_heavy_per_hour} per hour",
            "risk-check": f"{settings.rate_limit_heavy_per_hour} per hour",
        },
    )


# --------------------------------------------------------------------------- frontend

# In production the built React app (frontend/dist) is served by this same process,
# so the demo is one service with one URL. Registered last: API routes win.
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
