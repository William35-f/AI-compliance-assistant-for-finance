"""FastAPI application entry point.

Run locally with:  uvicorn regulens.main:app --reload
"""

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field

from regulens import __version__, db
from regulens.config import get_settings
from regulens.embeddings import Embedder, get_embedder
from regulens.llm import LLMClient, LLMError, LLMQuotaExceeded, make_llm
from regulens.qa import AskResponse, QAConfig, answer_question
from regulens.reranker import Reranker, get_reranker
from regulens.retrieval import RetrievalConfig

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
