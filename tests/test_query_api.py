"""Tests for app.api.query — natural language query endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token, hash_password
from app.core.security import encrypt
from app.models import AuditLog, DBConnection, DBType, Role, Tenant, User


@pytest.fixture
def tenant_and_user(db_session):
    tenant = Tenant(name="Test Corp", slug="test-corp")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        email="analyst@test.com",
        hashed_password=hash_password("pw"),
        role=Role.analyst,
        tenant_id=tenant.id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(tenant)
    db_session.refresh(user)
    return tenant, user


@pytest.fixture
def connection(db_session, tenant_and_user):
    tenant, _ = tenant_and_user
    conn = DBConnection(
        name="TestDB",
        db_type=DBType.postgres,
        encrypted_conn_str=encrypt("postgresql://u:p@host/db"),
        description="test database",
        tenant_id=tenant.id,
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn


@pytest.fixture
def auth_header(tenant_and_user):
    _, user = tenant_and_user
    token = create_access_token(user.id, user.tenant_id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


def test_query_success(client: TestClient, connection, auth_header):
    with (
        patch(
            "app.services.mcp_client.get_schema",
            new_callable=AsyncMock,
            return_value="CREATE TABLE t (id INT);",
        ),
        patch(
            "app.services.llm.generate_sql",
            new_callable=AsyncMock,
            return_value="SELECT * FROM t",
        ),
        patch(
            "app.services.mcp_client.run_query",
            new_callable=AsyncMock,
            return_value=[{"id": 1}],
        ),
        patch(
            "app.services.llm.summarize_results",
            new_callable=AsyncMock,
            return_value="Found one row.",
        ),
    ):
        resp = client.post(
            "/query/",
            json={
                "connection_id": connection.id,
                "question": "show me everything",
            },
            headers=auth_header,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sql_generated"] == "SELECT * FROM t"
    assert body["summary"] == "Found one row."
    assert body["result"] == [{"id": 1}]


def test_query_connection_not_found(client: TestClient, auth_header, tenant_and_user):
    resp = client.post(
        "/query/",
        json={
            "connection_id": "nonexistent-id",
            "question": "hello",
        },
        headers=auth_header,
    )
    assert resp.status_code == 404
    assert "Connection not found" in resp.json()["detail"]


def test_query_invalid_query_returns_400(
    client: TestClient, connection, auth_header
):
    with (
        patch(
            "app.services.mcp_client.get_schema",
            new_callable=AsyncMock,
            return_value="CREATE TABLE t (id INT);",
        ),
        patch(
            "app.services.llm.generate_sql",
            new_callable=AsyncMock,
            return_value="INVALID_QUERY",
        ),
    ):
        resp = client.post(
            "/query/",
            json={
                "connection_id": connection.id,
                "question": "nonsense",
            },
            headers=auth_header,
        )
    assert resp.status_code == 400
    assert "Could not generate" in resp.json()["detail"]


def test_query_schema_retrieval_failure(
    client: TestClient, connection, auth_header
):
    with patch(
        "app.services.mcp_client.get_schema",
        new_callable=AsyncMock,
        side_effect=RuntimeError("connection refused"),
    ):
        resp = client.post(
            "/query/",
            json={
                "connection_id": connection.id,
                "question": "show tables",
            },
            headers=auth_header,
        )
    assert resp.status_code == 500
    assert "Failed to connect" in resp.json()["detail"]


def test_query_llm_sql_generation_failure(
    client: TestClient, connection, auth_header
):
    with (
        patch(
            "app.services.mcp_client.get_schema",
            new_callable=AsyncMock,
            return_value="CREATE TABLE t (id INT);",
        ),
        patch(
            "app.services.llm.generate_sql",
            new_callable=AsyncMock,
            side_effect=RuntimeError("rate limit"),
        ),
    ):
        resp = client.post(
            "/query/",
            json={
                "connection_id": connection.id,
                "question": "show me data",
            },
            headers=auth_header,
        )
    assert resp.status_code == 502
    assert "AI service" in resp.json()["detail"]


def test_query_sql_validation_failure(
    client: TestClient, connection, auth_header
):
    with (
        patch(
            "app.services.mcp_client.get_schema",
            new_callable=AsyncMock,
            return_value="CREATE TABLE t (id INT);",
        ),
        patch(
            "app.services.llm.generate_sql",
            new_callable=AsyncMock,
            side_effect=ValueError("Non-SELECT statement"),
        ),
    ):
        resp = client.post(
            "/query/",
            json={
                "connection_id": connection.id,
                "question": "delete everything",
            },
            headers=auth_header,
        )
    assert resp.status_code == 400
    assert "Non-SELECT" in resp.json()["detail"]


def test_query_execution_failure(
    client: TestClient, connection, auth_header
):
    with (
        patch(
            "app.services.mcp_client.get_schema",
            new_callable=AsyncMock,
            return_value="CREATE TABLE t (id INT);",
        ),
        patch(
            "app.services.llm.generate_sql",
            new_callable=AsyncMock,
            return_value="SELECT 1",
        ),
        patch(
            "app.services.mcp_client.run_query",
            new_callable=AsyncMock,
            side_effect=RuntimeError("query timeout"),
        ),
    ):
        resp = client.post(
            "/query/",
            json={
                "connection_id": connection.id,
                "question": "count rows",
            },
            headers=auth_header,
        )
    assert resp.status_code == 500
    assert "Query execution failed" in resp.json()["detail"]


def test_query_summarization_failure_returns_fallback(
    client: TestClient, connection, auth_header
):
    with (
        patch(
            "app.services.mcp_client.get_schema",
            new_callable=AsyncMock,
            return_value="CREATE TABLE t (id INT);",
        ),
        patch(
            "app.services.llm.generate_sql",
            new_callable=AsyncMock,
            return_value="SELECT 1",
        ),
        patch(
            "app.services.mcp_client.run_query",
            new_callable=AsyncMock,
            return_value=[{"1": 1}],
        ),
        patch(
            "app.services.llm.summarize_results",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM down"),
        ),
    ):
        resp = client.post(
            "/query/",
            json={
                "connection_id": connection.id,
                "question": "anything",
            },
            headers=auth_header,
        )
    assert resp.status_code == 200
    assert resp.json()["summary"] == "Could not generate summary."


def test_query_requires_auth(client: TestClient):
    resp = client.post(
        "/query/",
        json={"connection_id": "x", "question": "y"},
    )
    assert resp.status_code in (401, 403)


def test_query_cross_tenant_isolation(client: TestClient, db_session):
    """A user cannot query a connection belonging to another tenant."""
    tenant_a = Tenant(name="A", slug="a")
    tenant_b = Tenant(name="B", slug="b")
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()

    user_a = User(
        email="a@a.com",
        hashed_password=hash_password("pw"),
        role=Role.admin,
        tenant_id=tenant_a.id,
    )
    conn_b = DBConnection(
        name="BConn",
        db_type=DBType.postgres,
        encrypted_conn_str=encrypt("postgresql://x"),
        tenant_id=tenant_b.id,
    )
    db_session.add_all([user_a, conn_b])
    db_session.commit()
    db_session.refresh(user_a)
    db_session.refresh(conn_b)

    token = create_access_token(
        user_a.id, tenant_a.id, user_a.role.value
    )
    resp = client.post(
        "/query/",
        json={
            "connection_id": conn_b.id,
            "question": "show data",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── Query History Tests ────────────────────────────────────────────────────────

@pytest.fixture
def admin_and_tenant(db_session):
    tenant = Tenant(name="History Corp", slug="history-corp")
    db_session.add(tenant)
    db_session.flush()
    admin = User(
        email="admin@history.com",
        hashed_password=hash_password("pw"),
        role=Role.admin,
        tenant_id=tenant.id,
    )
    viewer = User(
        email="viewer@history.com",
        hashed_password=hash_password("pw"),
        role=Role.viewer,
        tenant_id=tenant.id,
    )
    db_session.add_all([admin, viewer])
    db_session.commit()
    db_session.refresh(tenant)
    db_session.refresh(admin)
    db_session.refresh(viewer)
    return tenant, admin, viewer


def test_query_history_admin_sees_events(client: TestClient, db_session, admin_and_tenant):
    tenant, admin, _ = admin_and_tenant
    db_session.add_all([
        AuditLog(tenant_id=tenant.id, user_id=admin.id, event="query.success",
                 metadata_={"question": "q1"}),
        AuditLog(tenant_id=tenant.id, user_id=admin.id, event="query.failure",
                 metadata_={"question": "q2"}),
        AuditLog(tenant_id=tenant.id, user_id=admin.id, event="login.success",
                 metadata_={}),
    ])
    db_session.commit()

    token = create_access_token(admin.id, tenant.id, admin.role.value)
    resp = client.get(
        "/query/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    events = [e["event"] for e in resp.json()]
    assert "query.success" in events
    assert "query.failure" in events
    assert "login.success" not in events


def test_query_history_viewer_forbidden(client: TestClient, admin_and_tenant):
    _, _, viewer = admin_and_tenant
    token = create_access_token(viewer.id, viewer.tenant_id, viewer.role.value)
    resp = client.get(
        "/query/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_query_history_pagination(client: TestClient, db_session, admin_and_tenant):
    tenant, admin, _ = admin_and_tenant
    for i in range(10):
        db_session.add(
            AuditLog(tenant_id=tenant.id, user_id=admin.id, event="query.success",
                     metadata_={"i": i})
        )
    db_session.commit()

    token = create_access_token(admin.id, tenant.id, admin.role.value)
    resp = client.get(
        "/query/history?skip=0&limit=5",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 5
