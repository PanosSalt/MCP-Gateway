"""
Filesystem tool provider — exposes read/write file operations through MCP.

Allowed directories are configured via FILESYSTEM_ALLOWED_DIRS env var.
When empty, no filesystem tools are registered.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import os
from datetime import datetime, timezone

from mcp.types import TextContent, Tool

from app.config import get_settings
from app.core.rbac import has_min_role
from app.models import Role
from app.services.audit import write_audit_log
from app.tools import ToolContext, ToolDefault, get_effective_min_role, register

logger = logging.getLogger(__name__)

_READ_ROLE = Role.analyst
_WRITE_ROLE = Role.admin


def _allowed_dirs() -> list[str]:
    raw = get_settings().filesystem_allowed_dirs.strip()
    if not raw:
        return []
    dirs = [os.path.realpath(d.strip()) for d in raw.split(",") if d.strip()]
    return [d for d in dirs if os.path.isdir(d)]


def _validate_path(path: str) -> str:
    """Resolve path and verify it falls within an allowed directory."""
    real = os.path.realpath(os.path.expanduser(path))
    for allowed in _allowed_dirs():
        if real == allowed or real.startswith(allowed + os.sep):
            return real
    raise PermissionError(f"Path is outside allowed directories: {path}")


# ── Tool definitions ─────────────────────────────────────────────────────────

_TOOLS: dict[str, tuple[Tool, Role]] = {}


def _def(name: str, description: str, schema: dict, role: Role) -> None:
    _TOOLS[name] = (
        Tool(name=name, description=description, inputSchema=schema),
        role,
    )


_def("fs_read_file", "Read file contents as UTF-8 text.", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute path to the file"},
    },
    "required": ["path"],
}, _READ_ROLE)

_def("fs_list_directory", "List directory contents with [FILE] or [DIR] prefixes.", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute path to the directory"},
    },
    "required": ["path"],
}, _READ_ROLE)

_def("fs_directory_tree", "Get recursive JSON tree of a directory.", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Starting directory"},
        "max_depth": {"type": "integer", "description": "Max recursion depth (default 5)", "default": 5},
    },
    "required": ["path"],
}, _READ_ROLE)

_def("fs_search_files", "Recursively search for files matching a glob pattern.", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Starting directory"},
        "pattern": {"type": "string", "description": "Glob pattern to match (e.g. *.py, **/*.json)"},
    },
    "required": ["path", "pattern"],
}, _READ_ROLE)

_def("fs_get_file_info", "Get file or directory metadata (size, timestamps, type).", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute path to file or directory"},
    },
    "required": ["path"],
}, _READ_ROLE)

_def("fs_write_file", "Create or overwrite a file with the given content.", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute path for the file"},
        "content": {"type": "string", "description": "File content to write"},
    },
    "required": ["path", "content"],
}, _WRITE_ROLE)

_def("fs_create_directory", "Create a directory (including parents if needed).", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute path for the directory"},
    },
    "required": ["path"],
}, _WRITE_ROLE)

_def("fs_move_file", "Move or rename a file or directory.", {
    "type": "object",
    "properties": {
        "source": {"type": "string", "description": "Current path"},
        "destination": {"type": "string", "description": "New path"},
    },
    "required": ["source", "destination"],
}, _WRITE_ROLE)


# ── Handlers ─────────────────────────────────────────────────────────────────

_MAX_READ_BYTES = 10 * 1024 * 1024  # 10 MB


async def _read_file(args: dict) -> str:
    path = _validate_path(args["path"])
    size = os.path.getsize(path)
    if size > _MAX_READ_BYTES:
        raise ValueError(f"File too large ({size:,} bytes). Maximum is 10 MB.")
    with open(path, encoding="utf-8") as f:
        return f.read()


async def _list_directory(args: dict) -> str:
    path = _validate_path(args["path"])
    entries = sorted(os.listdir(path))
    lines = []
    for name in entries:
        full = os.path.join(path, name)
        prefix = "[DIR]" if os.path.isdir(full) else "[FILE]"
        lines.append(f"{prefix} {name}")
    return "\n".join(lines) if lines else "(empty directory)"


def _build_tree(path: str, depth: int, max_depth: int) -> list[dict]:
    if depth >= max_depth:
        return []
    result = []
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return []
    for name in entries:
        full = os.path.join(path, name)
        if os.path.isdir(full):
            result.append({
                "name": name,
                "type": "directory",
                "children": _build_tree(full, depth + 1, max_depth),
            })
        else:
            result.append({"name": name, "type": "file"})
    return result


async def _directory_tree(args: dict) -> str:
    path = _validate_path(args["path"])
    max_depth = min(int(args.get("max_depth", 5)), 10)
    tree = _build_tree(path, 0, max_depth)
    return json.dumps(tree, indent=2)


async def _search_files(args: dict) -> str:
    root = _validate_path(args["path"])
    pattern = args["pattern"]
    matches: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames + dirnames:
            if fnmatch.fnmatch(name, pattern):
                matches.append(os.path.join(dirpath, name))
        if len(matches) >= 1000:
            break
    return "\n".join(matches) if matches else "No matches found."


async def _get_file_info(args: dict) -> str:
    path = _validate_path(args["path"])
    stat = os.stat(path)
    info = {
        "path": path,
        "type": "directory" if os.path.isdir(path) else "file",
        "size_bytes": stat.st_size,
        "created": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "accessed": datetime.fromtimestamp(stat.st_atime, tz=timezone.utc).isoformat(),
        "permissions": oct(stat.st_mode),
    }
    return json.dumps(info, indent=2)


async def _write_file(args: dict) -> str:
    path = _validate_path(args["path"])
    content = args["content"]
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Written {len(content)} bytes to {path}"


async def _create_directory(args: dict) -> str:
    path = _validate_path(args["path"])
    os.makedirs(path, exist_ok=True)
    return f"Directory created: {path}"


async def _move_file(args: dict) -> str:
    source = _validate_path(args["source"])
    destination = _validate_path(args["destination"])
    if os.path.exists(destination):
        raise FileExistsError(f"Destination already exists: {destination}")
    os.rename(source, destination)
    return f"Moved {source} -> {destination}"


_HANDLERS: dict[str, object] = {
    "fs_read_file": _read_file,
    "fs_list_directory": _list_directory,
    "fs_directory_tree": _directory_tree,
    "fs_search_files": _search_files,
    "fs_get_file_info": _get_file_info,
    "fs_write_file": _write_file,
    "fs_create_directory": _create_directory,
    "fs_move_file": _move_file,
}


# ── Provider ─────────────────────────────────────────────────────────────────

class FilesystemToolProvider:
    def get_tools(self, ctx: ToolContext) -> list[Tool]:
        if not _allowed_dirs():
            return []
        tools: list[Tool] = []
        for name, (tool, default_role) in _TOOLS.items():
            effective = get_effective_min_role(
                ctx.db, ctx.user.tenant_id, name, default_role,
            )
            if has_min_role(ctx.user.role, effective):
                tools.append(tool)
        return tools

    def get_tool_defaults(self, ctx: ToolContext) -> list[ToolDefault]:
        if not _allowed_dirs():
            return []
        return [
            ToolDefault(
                name=name,
                tool_type="filesystem",
                description=tool.description or "",
                default_min_role=role,
            )
            for name, (tool, role) in _TOOLS.items()
        ]

    async def handle(
        self, name: str, args: dict, ctx: ToolContext
    ) -> list[TextContent] | None:
        handler = _HANDLERS.get(name)
        if handler is None:
            return None

        default_role = _TOOLS[name][1]
        effective = get_effective_min_role(
            ctx.db, ctx.user.tenant_id, name, default_role,
        )
        if not has_min_role(ctx.user.role, effective):
            return [TextContent(type="text", text="Permission denied")]

        try:
            result = await handler(args)  # type: ignore[operator]
            write_audit_log(ctx.db, f"fs.{name}", user=ctx.user, metadata={
                "tool": name,
                "args": {k: (v[:200] if isinstance(v, str) else v) for k, v in args.items()},
            })
            return [TextContent(type="text", text=result)]
        except (PermissionError, FileNotFoundError, FileExistsError, IsADirectoryError) as exc:
            write_audit_log(ctx.db, f"fs.{name}.error", user=ctx.user, metadata={
                "tool": name, "error": str(exc),
            })
            return [TextContent(type="text", text=f"Error: {exc}")]
        except Exception as exc:
            logger.error("Filesystem tool %s failed: %s", name, exc, exc_info=True)
            write_audit_log(ctx.db, f"fs.{name}.error", user=ctx.user, metadata={
                "tool": name, "error": str(exc),
            })
            return [TextContent(type="text", text=f"Error: {exc}")]


register(FilesystemToolProvider())
