"""
Example custom tool — demonstrates how to add a new MCP tool without
touching mcp_sse.py or any other existing file.

To add your own tool:
  1. Copy this file (or create a new one in app/tools/)
  2. Implement a ToolProvider class
  3. Call register(YourProvider()) at the bottom
  4. Add `from app.tools import your_module` in app/tools/__init__.py
"""
from __future__ import annotations

from datetime import datetime, timezone

from mcp.types import TextContent, Tool

from app.core.rbac import has_min_role
from app.models import Role
from app.tools import ToolContext, ToolDefault, get_effective_min_role, register

_GET_TIME_TOOL = Tool(
    name="get_current_time",
    description="Return the current UTC date and time in ISO 8601 format.",
    inputSchema={"type": "object", "properties": {}},
)

_DEFAULT_MIN_ROLE = Role.viewer


class ExampleToolProvider:
    def get_tools(self, ctx: ToolContext) -> list[Tool]:
        effective = get_effective_min_role(
            ctx.db, ctx.user.tenant_id, "get_current_time", _DEFAULT_MIN_ROLE,
        )
        if has_min_role(ctx.user.role, effective):
            return [_GET_TIME_TOOL]
        return []

    def get_tool_defaults(self, ctx: ToolContext) -> list[ToolDefault]:
        return [
            ToolDefault(
                name="get_current_time",
                tool_type="custom",
                description=_GET_TIME_TOOL.description,
                default_min_role=_DEFAULT_MIN_ROLE,
            ),
        ]

    async def handle(
        self, name: str, args: dict, ctx: ToolContext
    ) -> list[TextContent] | None:
        if name == "get_current_time":
            effective = get_effective_min_role(
                ctx.db, ctx.user.tenant_id, "get_current_time", _DEFAULT_MIN_ROLE,
            )
            if not has_min_role(ctx.user.role, effective):
                return [TextContent(type="text", text="Permission denied")]
            now = datetime.now(timezone.utc).isoformat()
            return [TextContent(type="text", text=now)]
        return None


register(ExampleToolProvider())
