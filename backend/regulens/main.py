"""FastAPI application entry point.

Run locally with:  uvicorn regulens.main:app --reload
"""

import logging
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from regulens import __version__, db
from regulens.config import RAW_DIR, SOURCES_CSV, get_settings
from regulens.embeddings import Embedder, get_embedder
from regulens.extraction import ExtractionResult, KeyRisk, extract_report
from regulens.llm import LLMClient, LLMError, LLMQuotaExceeded, make_llm
from regulens.qa import AskResponse, QAConfig, answer_question
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


@app.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    conn: Annotated[psycopg.Connection, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    llm: Annotated[LLMClient, Depends(get_llm)],
    config: Annotated[QAConfig, Depends(get_qa_config)],
    reranker: Annotated[Reranker | None, Depends(get_optional_reranker)],
) -> AskResponse:
    """Answer a question about MAS guidelines, with a citation for every claim."""
    try:
        return answer_question(
            conn, request.question.strip(), embedder, llm, config, reranker=reranker
        )
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
    except LLMQuotaExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except LLMError as exc:
        logger.exception("LLM failure during extraction")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The language model failed") from exc


@app.post("/extract", response_model=ExtractionResult)
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


@app.post("/risk-check", response_model=RiskCheckResult)
def risk_check(
    request: RiskCheckRequest,
    conn: Annotated[psycopg.Connection, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
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
