from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from mcp.types import TextContent, Tool
from sqlalchemy.orm import Session

from app.models import Role, ToolRoleOverride, User


@dataclass
class ToolContext:
    user: User
    db: Session
    # Client IP of the originating MCP connection, recorded on audit entries.
    ip: str | None = None
    # Lazy cache populated by _get_all_connections in sql.py.
    # Avoids re-querying within the same context lifetime.
    conn_cache: list | None = field(default=None, repr=False, compare=False)


@dataclass
class ToolDefault:
    """Metadata about a tool's default role requirement (before overrides)."""
    name: str
    tool_type: str
    description: str
    default_min_role: Role
    connection_id: str | None = None
    connection_name: str | None = None


@runtime_checkable
class ToolProvider(Protocol):
    def get_tools(self, ctx: ToolContext) -> list[Tool]: ...

    async def handle(
        self, name: str, args: dict, ctx: ToolContext
    ) -> list[TextContent] | None:
        """Return a result if this provider owns the tool, or None to pass through."""
        ...

    def get_tool_defaults(self, ctx: ToolContext) -> list[ToolDefault]:
        """Return metadata for all tools this provider can produce."""
        ...


_providers: list[ToolProvider] = []


def register(provider: ToolProvider) -> None:
    _providers.append(provider)


def get_effective_min_role(
    db: Session, tenant_id: str, tool_name: str, default: Role
) -> Role:
    """Check for an admin override, falling back to the provider's default."""
    override = (
        db.query(ToolRoleOverride)
        .filter_by(tenant_id=tenant_id, tool_name=tool_name)
        .first()
    )
    return Role(override.min_role) if override else default


def load_role_overrides(db: Session, tenant_id: str) -> dict[str, Role]:
    """Batch-load all ToolRoleOverride rows for a tenant into a dict keyed by tool_name."""
    rows = db.query(ToolRoleOverride).filter_by(tenant_id=tenant_id).all()
    return {r.tool_name: Role(r.min_role) for r in rows}


def get_tools(ctx: ToolContext) -> list[Tool]:
    return [tool for p in _providers for tool in p.get_tools(ctx)]


def get_all_tool_defaults(ctx: ToolContext) -> list[ToolDefault]:
    """Aggregate tool metadata from all providers (for the REST API)."""
    defaults: list[ToolDefault] = []
    for p in _providers:
        if hasattr(p, "get_tool_defaults"):
            defaults.extend(p.get_tool_defaults(ctx))
    return defaults


async def handle(name: str, args: dict, ctx: ToolContext) -> list[TextContent]:
    for p in _providers:
        result = await p.handle(name, args, ctx)
        if result is not None:
            return result
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# --- Register all tool providers here ---
from app.tools import (  # noqa: E402, F401
    example,
    filesystem,
    sql,
)
