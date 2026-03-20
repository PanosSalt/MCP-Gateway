"""Tests for app.main — router registration and database wiring."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_get_db_yields_session(db_session: Session) -> None:
    assert isinstance(db_session, Session)
    # Confirm session is active (not closed)
    assert db_session.is_active


def test_openapi_schema_loads(client: TestClient):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    paths = schema["paths"]
    assert "/auth/login" in paths
    assert "/tenants/" in paths
    assert "/connections/" in paths
    assert "/query/" in paths
    assert "/auth/entra/config" in paths
    assert "/auth/entra/login" in paths
    assert "/auth/entra/callback" in paths
    assert "/mcp/sse" in paths
