from __future__ import annotations

import json
import logging
import re

from mcp.types import TextContent, Tool

from app.core.rbac import has_min_role
from app.core.security import decrypt
from app.models import DBConnection, Role
from app.services import mcp_client
from app.services.audit import write_audit_log
from app.services.llm import assert_safe_select, json_default
from app.tools import ToolContext, ToolDefault, load_role_overrides, register

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^a-z0-9]+")


def _conn_slug(conn: DBConnection) -> str:
    return _SAFE_NAME_RE.sub("_", conn.name.lower()).strip("_")


def _schema_tool_name(conn: DBConnection) -> str:
    return f"get_schema_{_conn_slug(conn)}_{conn.id[:8]}"


def _execute_tool_name(conn: DBConnection) -> str:
    return f"execute_sql_{_conn_slug(conn)}_{conn.id[:8]}"


def _schema_description(conn: DBConnection) -> str:
    return (
        f"Return the full schema of '{conn.name}' "
        f"({conn.db_type.value}) so you can write accurate SQL. "
        + (conn.description or "")
    )


def _execute_description(conn: DBConnection) -> str:
    return (
        f"Execute a SELECT SQL query against '{conn.name}' "
        f"({conn.db_type.value}) and return the raw rows. "
        "Only SELECT statements are allowed."
    )


def _build_schema_tool(conn: DBConnection) -> Tool:
    return Tool(
        name=_schema_tool_name(conn),
        description=_schema_description(conn),
        inputSchema={"type": "object", "properties": {}},
    )


def _build_execute_tool(conn: DBConnection) -> Tool:
    return Tool(
        name=_execute_tool_name(conn),
        description=_execute_description(conn),
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A SELECT SQL statement to execute",
                }
            },
            "required": ["sql"],
        },
    )


_LIST_CONNECTIONS_TOOL = Tool(
    name="list_connections",
    description="List all database connections available to you.",
    inputSchema={"type": "object", "properties": {}},
)


def _get_all_connections(ctx: ToolContext) -> list[DBConnection]:
    """Return all active connections for the user's tenant, caching on ctx."""
    if ctx.conn_cache is None:
        ctx.conn_cache = (
            ctx.db.query(DBConnection)
            .filter(
                DBConnection.tenant_id == ctx.user.tenant_id,
                DBConnection.is_active.is_(True),
            )
            .all()
        )
    return ctx.conn_cache


def _get_visible_connections(ctx: ToolContext) -> list[DBConnection]:
    """Return connections the user's role is allowed to see."""
    return [c for c in _get_all_connections(ctx) if has_min_role(ctx.user.role, c.min_role)]


class SqlToolProvider:
    def get_tools(self, ctx: ToolContext) -> list[Tool]:
        connections = _get_visible_connections(ctx)
        overrides = load_role_overrides(ctx.db, ctx.user.tenant_id)
        tools: list[Tool] = [_LIST_CONNECTIONS_TOOL]
        for c in connections:
            schema_name = _schema_tool_name(c)
            schema_role = overrides.get(schema_name, c.min_role)
            if has_min_role(ctx.user.role, schema_role):
                tools.append(_build_schema_tool(c))

            exec_name = _execute_tool_name(c)
            exec_role = overrides.get(exec_name, Role.analyst)
            if has_min_role(ctx.user.role, exec_role):
                tools.append(_build_execute_tool(c))
        return tools

    def get_tool_defaults(self, ctx: ToolContext) -> list[ToolDefault]:
        connections = _get_all_connections(ctx)
        defaults: list[ToolDefault] = [
            ToolDefault(
                name="list_connections",
                tool_type="utility",
                description=_LIST_CONNECTIONS_TOOL.description,
                default_min_role=Role.viewer,
            ),
        ]
        for c in connections:
            defaults.append(ToolDefault(
                name=_schema_tool_name(c),
                tool_type="schema",
                description=_schema_description(c),
                default_min_role=c.min_role,
                connection_id=c.id,
                connection_name=c.name,
            ))
            defaults.append(ToolDefault(
                name=_execute_tool_name(c),
                tool_type="execute",
                description=_execute_description(c),
                default_min_role=Role.analyst,
                connection_id=c.id,
                connection_name=c.name,
            ))
        return defaults

    async def handle(
        self, name: str, args: dict, ctx: ToolContext
    ) -> list[TextContent] | None:
        connections = _get_visible_connections(ctx)
        schema_map = {_schema_tool_name(c): c for c in connections}
        execute_map = {_execute_tool_name(c): c for c in connections}

        if name == "list_connections":
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        [
                            {
                                "id": c.id,
                                "name": c.name,
                                "type": c.db_type.value,
                                "description": c.description,
                                "schema_tool": _schema_tool_name(c),
                                "execute_tool": _execute_tool_name(c),
                            }
                            for c in connections
                        ],
                        indent=2,
                    ),
                )
            ]

        overrides = load_role_overrides(ctx.db, ctx.user.tenant_id)

        if name in schema_map:
            conn = schema_map[name]
            schema_role = overrides.get(name, conn.min_role)
            if not has_min_role(ctx.user.role, schema_role):
                return [TextContent(type="text", text="Permission denied")]
            try:
                conn_str = decrypt(conn.encrypted_conn_str)
                schema = await mcp_client.get_schema(conn.db_type, conn_str)
                return [TextContent(type="text", text=schema)]
            except Exception as exc:
                logger.error("Schema tool %s failed: %s", name, exc, exc_info=True)
                return [TextContent(type="text", text=f"Error: {exc}")]

        if name in execute_map:
            conn = execute_map[name]
            exec_role = overrides.get(name, Role.analyst)
            if not has_min_role(ctx.user.role, exec_role):
                return [TextContent(type="text", text="Permission denied: insufficient role to execute queries")]
            sql = (args.get("sql") or "").strip()
            try:
                assert_safe_select(sql, conn.db_type.value)
            except ValueError as exc:
                write_audit_log(ctx.db, "tool.execute_sql.rejected", user=ctx.user, metadata={
                    "tool": name, "connection_id": conn.id, "reason": str(exc),
                })
                return [TextContent(type="text", text=f"SQL rejected: {exc}")]
            try:
                conn_str = decrypt(conn.encrypted_conn_str)
                rows = await mcp_client.run_query(conn.db_type, conn_str, sql)
                write_audit_log(ctx.db, "tool.execute_sql", user=ctx.user, metadata={
                    "tool": name, "connection_id": conn.id, "sql_preview": sql[:200],
                    "row_count": len(rows),
                })
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"row_count": len(rows), "rows": rows},
                            indent=2,
                            default=json_default,
                        ),
                    )
                ]
            except Exception as exc:
                logger.error("Execute tool %s failed: %s", name, exc, exc_info=True)
                write_audit_log(ctx.db, "tool.execute_sql.error", user=ctx.user, metadata={
                    "tool": name, "connection_id": conn.id, "error": str(exc),
                })
                return [TextContent(type="text", text=f"Error: {exc}")]

        return None


register(SqlToolProvider())
