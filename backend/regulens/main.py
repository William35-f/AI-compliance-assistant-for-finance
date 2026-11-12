"""FastAPI application entry point.

Run locally with:  uvicorn regulens.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import psycopg
from fastapi import FastAPI, Response, status
from pydantic import BaseModel

from regulens import __version__, db

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
