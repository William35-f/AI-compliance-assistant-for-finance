"""Tests for GET /health.

The unit tests replace the database functions with fakes, so they run without
Docker. The integration test talks to the real Postgres and is skipped when
it is not running.
"""

import psycopg
import pytest
from fastapi.testclient import TestClient

from regulens import db, main


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Skip the real schema setup that runs at startup.
    monkeypatch.setattr(db, "init_db", lambda: None)
    return TestClient(main.app)


def test_health_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "pgvector_version", lambda: "0.8.0")
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["pgvector_version"] == "0.8.0"


def test_health_database_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable() -> str:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(db, "pgvector_version", unreachable)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


def test_health_pgvector_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "pgvector_version", lambda: None)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "pgvector_missing"


def _database_is_up() -> bool:
    try:
        with db.connect():
            return True
    except psycopg.OperationalError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _database_is_up(), reason="Postgres is not running")
def test_health_against_real_database() -> None:
    with TestClient(main.app) as real_client:  # `with` runs the startup hook (init_db)
        response = real_client.get("/health")
    assert response.status_code == 200
    assert response.json()["pgvector_version"]
