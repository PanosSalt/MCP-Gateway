"""Tests for app.api.tools — tool listing and per-tool role overrides."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token, hash_password
from app.models import DBConnection, DBType, Role, Tenant, ToolRoleOverride, User

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant_and_admin(db_session):
    tenant = Tenant(name="Tools Corp", slug="tools-corp")
    db_session.add(tenant)
    db_session.flush()
    admin = User(
        email="admin@tools.com",
        hashed_password=hash_password("pw"),
        role=Role.admin,
        tenant_id=tenant.id,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(tenant)
    db_session.refresh(admin)
    return tenant, admin


@pytest.fixture
def admin_header(tenant_and_admin):
    _, admin = tenant_and_admin
    token = create_access_token(admin.id, admin.tenant_id, admin.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def viewer(db_session, tenant_and_admin):
    tenant, _ = tenant_and_admin
    v = User(
        email="viewer@tools.com",
        hashed_password=hash_password("pw"),
        role=Role.viewer,
        tenant_id=tenant.id,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


@pytest.fixture
def viewer_header(viewer):
    token = create_access_token(viewer.id, viewer.tenant_id, viewer.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def analyst(db_session, tenant_and_admin):
    tenant, _ = tenant_and_admin
    a = User(
        email="analyst@tools.com",
        hashed_password=hash_password("pw"),
        role=Role.analyst,
        tenant_id=tenant.id,
    )
    db_session.add(a)
    db_session.commit()
    db_session.refresh(a)
    return a


@pytest.fixture
def analyst_header(analyst):
    token = create_access_token(analyst.id, analyst.tenant_id, analyst.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def connection(db_session, tenant_and_admin):
    tenant, _ = tenant_and_admin
    conn = DBConnection(
        name="Test DB",
        db_type=DBType.postgres,
        encrypted_conn_str="enc",
        tenant_id=tenant.id,
        min_role=Role.viewer,
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn


# ── GET /tools/ ──────────────────────────────────────────────────────────────


def test_list_tools_returns_custom_tools(client: TestClient, tenant_and_admin, admin_header):
    """Even without connections, the custom get_current_time tool appears."""
    resp = client.get("/tools/", headers=admin_header)
    assert resp.status_code == 200
    tools = resp.json()
    names = [t["tool_name"] for t in tools]
    assert "get_current_time" in names
    time_tool = next(t for t in tools if t["tool_name"] == "get_current_time")
    assert time_tool["tool_type"] == "custom"
    assert time_tool["default_min_role"] == "viewer"
    assert time_tool["accessible"] is True


def test_list_tools_returns_connection_tools(
    client: TestClient, tenant_and_admin, admin_header, connection,
):
    resp = client.get("/tools/", headers=admin_header)
    assert resp.status_code == 200
    tools = resp.json()
    names = [t["tool_name"] for t in tools]
    assert any(n.startswith("get_schema_") for n in names)
    assert any(n.startswith("execute_sql_") for n in names)
    assert "list_connections" in names

    schema_tool = next(t for t in tools if t["tool_name"].startswith("get_schema_"))
    assert schema_tool["connection_id"] == connection.id
    assert schema_tool["connection_name"] == "Test DB"
    assert schema_tool["tool_type"] == "schema"
    assert schema_tool["default_min_role"] == "viewer"


def test_list_tools_viewer_sees_correct_accessibility(
    client: TestClient, connection, viewer_header,
):
    """Viewer sees schema tools as accessible, execute tools as inaccessible (default analyst)."""
    resp = client.get("/tools/", headers=viewer_header)
    assert resp.status_code == 200
    tools = resp.json()

    schema_tool = next(
        (t for t in tools if t["tool_name"].startswith("get_schema_")), None
    )
    execute_tool = next(
        (t for t in tools if t["tool_name"].startswith("execute_sql_")), None
    )

    assert schema_tool is not None
    assert schema_tool["accessible"] is True

    assert execute_tool is not None
    assert execute_tool["accessible"] is False
    assert execute_tool["default_min_role"] == "analyst"


def test_list_tools_requires_auth(client: TestClient):
    resp = client.get("/tools/")
    assert resp.status_code in (401, 403)


@pytest.fixture
def admin_only_connection(db_session, tenant_and_admin):
    tenant, _ = tenant_and_admin
    conn = DBConnection(
        name="Payroll DB",
        db_type=DBType.postgres,
        encrypted_conn_str="enc",
        tenant_id=tenant.id,
        min_role=Role.admin,
        description="Contains salary data",
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn


def test_list_tools_hides_inaccessible_connections_from_viewer(
    client: TestClient, admin_only_connection, viewer_header,
):
    """A viewer must not learn that an admin-only connection exists.

    Regression test: get_tool_defaults previously used the unfiltered
    connection query, leaking connection name, id and description to
    every authenticated user regardless of role.
    """
    resp = client.get("/tools/", headers=viewer_header)
    assert resp.status_code == 200
    body = resp.text
    tools = resp.json()

    assert not any(
        t["connection_id"] == admin_only_connection.id for t in tools
    )
    assert "Payroll DB" not in body
    assert "Contains salary data" not in body


def test_list_tools_shows_all_connections_to_admin(
    client: TestClient, admin_only_connection, admin_header,
):
    """Admins keep the full list — they need it to configure role overrides."""
    resp = client.get("/tools/", headers=admin_header)
    assert resp.status_code == 200
    tools = resp.json()
    assert any(t["connection_id"] == admin_only_connection.id for t in tools)


def test_list_tools_cross_tenant_isolation(
    client: TestClient, db_session, tenant_and_admin, admin_header,
):
    other = Tenant(name="Other", slug="other-tools")
    db_session.add(other)
    db_session.flush()
    db_session.add(DBConnection(
        name="OtherDB", db_type=DBType.sqlite,
        encrypted_conn_str="enc", tenant_id=other.id,
    ))
    db_session.commit()

    resp = client.get("/tools/", headers=admin_header)
    tools = resp.json()
    conn_names = [t["connection_name"] for t in tools if t["connection_name"]]
    assert "OtherDB" not in conn_names


# ── PATCH /tools/{tool_name} ─────────────────────────────────────────────────


def test_update_tool_role_creates_override(
    client: TestClient, tenant_and_admin, admin_header, connection,
):
    resp = client.get("/tools/", headers=admin_header)
    schema_tool = next(t for t in resp.json() if t["tool_name"].startswith("get_schema_"))
    tool_name = schema_tool["tool_name"]

    resp = client.patch(
        f"/tools/{tool_name}",
        json={"min_role": "admin"},
        headers=admin_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool_name"] == tool_name
    assert body["min_role"] == "admin"
    assert body["reset"] is False

    resp = client.get("/tools/", headers=admin_header)
    updated = next(t for t in resp.json() if t["tool_name"] == tool_name)
    assert updated["effective_min_role"] == "admin"
    assert updated["default_min_role"] == "viewer"


def test_update_tool_role_reset_to_default(
    client: TestClient, db_session, tenant_and_admin, admin_header, connection,
):
    tenant, _ = tenant_and_admin
    resp = client.get("/tools/", headers=admin_header)
    schema_tool = next(t for t in resp.json() if t["tool_name"].startswith("get_schema_"))
    tool_name = schema_tool["tool_name"]

    db_session.add(ToolRoleOverride(
        tenant_id=tenant.id, tool_name=tool_name, min_role=Role.admin,
    ))
    db_session.commit()

    resp = client.patch(
        f"/tools/{tool_name}",
        json={"min_role": None},
        headers=admin_header,
    )
    assert resp.status_code == 200
    assert resp.json()["reset"] is True

    resp = client.get("/tools/", headers=admin_header)
    updated = next(t for t in resp.json() if t["tool_name"] == tool_name)
    assert updated["effective_min_role"] == updated["default_min_role"]


def test_update_tool_role_requires_admin(
    client: TestClient, connection, viewer_header,
):
    resp = client.patch(
        "/tools/get_current_time",
        json={"min_role": "admin"},
        headers=viewer_header,
    )
    assert resp.status_code == 403


def test_update_tool_role_unknown_tool(
    client: TestClient, tenant_and_admin, admin_header,
):
    resp = client.patch(
        "/tools/nonexistent_tool",
        json={"min_role": "admin"},
        headers=admin_header,
    )
    assert resp.status_code == 404


def test_update_custom_tool_role(
    client: TestClient, tenant_and_admin, admin_header,
):
    """Override role for the custom get_current_time tool."""
    resp = client.patch(
        "/tools/get_current_time",
        json={"min_role": "analyst"},
        headers=admin_header,
    )
    assert resp.status_code == 200

    resp = client.get("/tools/", headers=admin_header)
    time_tool = next(t for t in resp.json() if t["tool_name"] == "get_current_time")
    assert time_tool["effective_min_role"] == "analyst"
    assert time_tool["default_min_role"] == "viewer"


# ── Override affects MCP tool visibility ──────────────────────────────────────


def test_override_affects_tool_visibility(
    client: TestClient, db_session, tenant_and_admin, viewer_header, connection,
):
    """After overriding a schema tool to admin, a viewer can no longer access it."""
    tenant, _ = tenant_and_admin

    resp = client.get("/tools/", headers=viewer_header)
    schema_tool = next(t for t in resp.json() if t["tool_name"].startswith("get_schema_"))
    assert schema_tool["accessible"] is True
    tool_name = schema_tool["tool_name"]

    db_session.add(ToolRoleOverride(
        tenant_id=tenant.id, tool_name=tool_name, min_role=Role.admin,
    ))
    db_session.commit()

    resp = client.get("/tools/", headers=viewer_header)
    schema_tool = next(t for t in resp.json() if t["tool_name"] == tool_name)
    assert schema_tool["accessible"] is False
    assert schema_tool["effective_min_role"] == "admin"


def test_override_affects_analyst_visibility(
    client: TestClient, db_session, tenant_and_admin, analyst_header, connection,
):
    """Lowering execute tool min_role to viewer makes it accessible to analysts still."""
    tenant, _ = tenant_and_admin

    resp = client.get("/tools/", headers=analyst_header)
    exec_tool = next(t for t in resp.json() if t["tool_name"].startswith("execute_sql_"))
    assert exec_tool["accessible"] is True
    tool_name = exec_tool["tool_name"]

    db_session.add(ToolRoleOverride(
        tenant_id=tenant.id, tool_name=tool_name, min_role=Role.viewer,
    ))
    db_session.commit()

    resp = client.get("/tools/", headers=analyst_header)
    exec_tool = next(t for t in resp.json() if t["tool_name"] == tool_name)
    assert exec_tool["accessible"] is True
    assert exec_tool["effective_min_role"] == "viewer"
