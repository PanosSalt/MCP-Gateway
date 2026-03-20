"""Tests for app.api.mcp_sse — MCP SSE endpoint helpers."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from app.api.mcp_sse import build_mcp_server
from app.core.auth import create_access_token, hash_password
from app.core.security import encrypt
from app.models import DBConnection, DBType, Role, Tenant, User
from app.tools.sql import (
    _LIST_CONNECTIONS_TOOL as LIST_CONNECTIONS_TOOL,
)
from app.tools.sql import (
    _build_execute_tool,
    _build_schema_tool,
)
from app.tools.sql import (
    _execute_tool_name as _build_execute_tool_name,
)
from app.tools.sql import (
    _schema_tool_name as _build_schema_tool_name,
)


@pytest.fixture
def setup_data(db_session):
    tenant = Tenant(name="MCP Corp", slug="mcp-corp")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        email="mcp@test.com",
        hashed_password=hash_password("pw"),
        role=Role.analyst,
        tenant_id=tenant.id,
    )
    db_session.add(user)
    db_session.flush()
    conn = DBConnection(
        name="Main DB",
        db_type=DBType.postgres,
        encrypted_conn_str=encrypt("postgresql://u:p@host/db"),
        description="Primary database",
        tenant_id=tenant.id,
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(tenant)
    db_session.refresh(user)
    db_session.refresh(conn)
    return tenant, user, conn


# ── _build_schema_tool_name / _build_execute_tool_name ───────────────


class TestBuildToolNames:
    def test_schema_tool_name(self, setup_data):
        _, _, conn = setup_data
        name = _build_schema_tool_name(conn)
        assert name.startswith("get_schema_main_db_")
        assert conn.id[:8] in name

    def test_execute_tool_name(self, setup_data):
        _, _, conn = setup_data
        name = _build_execute_tool_name(conn)
        assert name.startswith("execute_sql_main_db_")
        assert conn.id[:8] in name

    def test_special_chars(self, db_session, setup_data):
        tenant, _, _ = setup_data
        conn = DBConnection(
            name="My DB!@#$%",
            db_type=DBType.mysql,
            encrypted_conn_str=encrypt("mysql://x"),
            tenant_id=tenant.id,
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)
        schema_name = _build_schema_tool_name(conn)
        assert schema_name.startswith("get_schema_my_db_")
        assert "!" not in schema_name
        assert "@" not in schema_name

    def test_uniqueness(self, db_session, setup_data):
        """Two connections with similar names produce different tool names."""
        tenant, _, _ = setup_data
        c1 = DBConnection(
            name="Sales",
            db_type=DBType.postgres,
            encrypted_conn_str=encrypt("x"),
            tenant_id=tenant.id,
        )
        c2 = DBConnection(
            name="Sales",
            db_type=DBType.postgres,
            encrypted_conn_str=encrypt("y"),
            tenant_id=tenant.id,
        )
        db_session.add_all([c1, c2])
        db_session.commit()
        db_session.refresh(c1)
        db_session.refresh(c2)
        assert _build_schema_tool_name(c1) != _build_schema_tool_name(c2)
        assert _build_execute_tool_name(c1) != _build_execute_tool_name(c2)


# ── _build_schema_tool / _build_execute_tool ─────────────────────────


def test_build_schema_tool(setup_data):
    _, _, conn = setup_data
    tool = _build_schema_tool(conn)
    assert tool.name == _build_schema_tool_name(conn)
    assert "Main DB" in tool.description
    assert "postgres" in tool.description


def test_build_execute_tool(setup_data):
    _, _, conn = setup_data
    tool = _build_execute_tool(conn)
    assert tool.name == _build_execute_tool_name(conn)
    assert "Main DB" in tool.description
    assert "sql" in tool.inputSchema["properties"]
    assert "sql" in tool.inputSchema["required"]


# ── build_mcp_server ─────────────────────────────────────────────────


def test_build_mcp_server_returns_server(db_session, setup_data):
    _, user, _ = setup_data
    server = build_mcp_server(user.id, db_session)
    assert server is not None


# ── list_connections tool ────────────────────────────────────────────


def test_list_connections_tool_schema():
    assert LIST_CONNECTIONS_TOOL.name == "list_connections"
    assert LIST_CONNECTIONS_TOOL.inputSchema["type"] == "object"


# ── SSE endpoint auth (tenant-scoped) ────────────────────────────────


def test_mcp_sse_no_auth_returns_401(client, setup_data):
    """Unauthenticated request returns 401 with WWW-Authenticate pointing to PRM."""
    tenant, _, _ = setup_data
    resp = client.get(f"/t/{tenant.slug}/mcp/sse")
    assert resp.status_code == 401
    www_auth = resp.headers["WWW-Authenticate"]
    assert "Bearer" in www_auth
    assert "oauth-protected-resource" in www_auth
    assert tenant.slug in www_auth


def test_mcp_sse_invalid_bearer_returns_401(client, setup_data):
    tenant, _, _ = setup_data
    from tests.conftest import TestSessionLocal
    with patch("app.api.mcp_sse.get_session", new=lambda: TestSessionLocal()):
        resp = client.get(
            f"/t/{tenant.slug}/mcp/sse",
            headers={"Authorization": "Bearer bad-token"},
        )
    assert resp.status_code == 401


def test_mcp_sse_wrong_tenant_returns_403(client, db_session, setup_data):
    tenant, user, _ = setup_data
    other = Tenant(name="Other Corp", slug="other-corp")
    db_session.add(other)
    db_session.commit()
    token = create_access_token(user.id, user.tenant_id, user.role.value)
    from tests.conftest import TestSessionLocal
    with patch("app.api.mcp_sse.get_session", new=lambda: TestSessionLocal()):
        resp = client.get(
            f"/t/{other.slug}/mcp/sse",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403


# ── handle_list_tools ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_list_tools_returns_all(db_session, setup_data):
    """handle_list_tools returns list_connections + schema tool + execute tool per connection."""
    _, user, conn = setup_data
    server = build_mcp_server(user.id, db_session)

    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list", params=None))

    tools = result.root.tools
    names = [t.name for t in tools]
    assert "list_connections" in names
    assert _build_schema_tool_name(conn) in names
    assert _build_execute_tool_name(conn) in names


# ── handle_call_tool: list_connections ───────────────────────────────


@pytest.mark.asyncio
async def test_handle_call_tool_list_connections(db_session, setup_data):
    """list_connections tool returns JSON with tenant's active connections."""
    _, user, conn = setup_data
    server = build_mcp_server(user.id, db_session)

    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="list_connections", arguments={}),
        )
    )

    content = result.root.content
    assert len(content) == 1
    data = json.loads(content[0].text)
    assert isinstance(data, list)
    assert any(c["id"] == conn.id for c in data)
    assert any(c["name"] == "Main DB" for c in data)
    # Each entry should include the tool names for convenience
    entry = next(c for c in data if c["id"] == conn.id)
    assert "schema_tool" in entry
    assert "execute_tool" in entry


# ── handle_call_tool: get_schema ─────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_call_tool_get_schema_success(db_session, setup_data):
    """get_schema tool returns the DB schema text."""
    _, user, conn = setup_data
    schema_tool_name = _build_schema_tool_name(conn)

    with patch(
        "app.tools.sql.mcp_client.get_schema",
        new=AsyncMock(return_value="CREATE TABLE users (id INT);"),
    ):
        server = build_mcp_server(user.id, db_session)
        handler = server.request_handlers[CallToolRequest]
        result = await handler(
            CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(name=schema_tool_name, arguments={}),
            )
        )

    text = result.root.content[0].text
    assert "CREATE TABLE" in text


# ── handle_call_tool: execute_sql success ────────────────────────────


@pytest.mark.asyncio
async def test_handle_call_tool_execute_sql_success(db_session, setup_data):
    """execute_sql tool runs a valid SELECT and returns rows as JSON."""
    _, user, conn = setup_data
    execute_tool_name = _build_execute_tool_name(conn)

    with patch(
        "app.tools.sql.mcp_client.run_query",
        new=AsyncMock(return_value=[{"id": 1, "name": "Alice"}]),
    ):
        server = build_mcp_server(user.id, db_session)
        handler = server.request_handlers[CallToolRequest]
        result = await handler(
            CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(
                    name=execute_tool_name,
                    arguments={"sql": "SELECT id, name FROM users"},
                ),
            )
        )

    data = json.loads(result.root.content[0].text)
    assert data["row_count"] == 1
    assert data["rows"][0]["name"] == "Alice"


# ── handle_call_tool: execute_sql SQL safety rejection ───────────────


@pytest.mark.asyncio
async def test_handle_call_tool_execute_sql_rejects_dml(db_session, setup_data):
    """execute_sql tool rejects non-SELECT statements."""
    _, user, conn = setup_data
    execute_tool_name = _build_execute_tool_name(conn)

    server = build_mcp_server(user.id, db_session)
    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name=execute_tool_name,
                arguments={"sql": "DELETE FROM users"},
            ),
        )
    )

    text = result.root.content[0].text
    assert "rejected" in text.lower() or "sql rejected" in text.lower()


# ── handle_call_tool: unknown tool ───────────────────────────────────


@pytest.mark.asyncio
async def test_handle_call_tool_unknown_tool(db_session, setup_data):
    """Calling an unregistered tool name returns 'Unknown tool' message."""
    _, user, _ = setup_data
    server = build_mcp_server(user.id, db_session)

    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="nonexistent_tool", arguments={}),
        )
    )

    text = result.root.content[0].text
    assert "Unknown tool" in text
