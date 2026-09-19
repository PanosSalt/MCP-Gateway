# Contributing to MCP Gateway

Thanks for your interest in contributing. This document covers how to submit bug reports, propose features, and get PRs merged.

## Before you start

- Check the [existing issues](../../issues) to avoid duplicates
- For large changes, open an issue first to discuss the approach before writing code

## Development setup

```bash
git clone <repo-url>
cd MCP-Gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env — DATABASE_URL is required and has no default; point it at a local Postgres
# instance (e.g. postgresql://user:pass@localhost:5432/mcpgw). The app will not start
# without it. Tests are separate and configure their own in-memory SQLite.
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Run the test suite. The tests configure their own in-memory SQLite, so no database or
other external service needs to be running:

```bash
python -m pytest tests/ -v
```

All tests must pass before submitting a PR.

## Submitting a pull request

1. Fork the repo and create a branch from `main`
2. Write tests for any new behaviour
3. Make sure `pytest` passes
4. Keep commits focused — one logical change per commit
5. Open a PR against `main` with a clear description of what and why

## Adding a custom tool

Tools are supplied by **provider classes**, not decorated functions. A provider
implements three methods — `get_tools`, `get_tool_defaults` and `handle` — and
registers itself with `register()`.

Create a file in `app/tools/`:

```python
# app/tools/my_tool.py
from __future__ import annotations

from mcp.types import TextContent, Tool

from app.core.rbac import has_min_role
from app.models import Role
from app.tools import ToolContext, ToolDefault, get_effective_min_role, register

_MY_TOOL = Tool(
    name="my_tool",
    description="What this tool does.",
    inputSchema={
        "type": "object",
        "properties": {"input": {"type": "string"}},
        "required": ["input"],
    },
)

_DEFAULT_MIN_ROLE = Role.analyst


class MyToolProvider:
    def get_tools(self, ctx: ToolContext) -> list[Tool]:
        """Tools this user may see. Return [] to hide them."""
        effective = get_effective_min_role(
            ctx.db, ctx.user.tenant_id, "my_tool", _DEFAULT_MIN_ROLE,
        )
        return [_MY_TOOL] if has_min_role(ctx.user.role, effective) else []

    def get_tool_defaults(self, ctx: ToolContext) -> list[ToolDefault]:
        """Metadata for the admin UI's role-override screen."""
        return [
            ToolDefault(
                name="my_tool",
                tool_type="custom",
                description=_MY_TOOL.description,
                default_min_role=_DEFAULT_MIN_ROLE,
            ),
        ]

    async def handle(
        self, name: str, args: dict, ctx: ToolContext
    ) -> list[TextContent] | None:
        """Return None for tools you don't own so the next provider sees them."""
        if name != "my_tool":
            return None
        effective = get_effective_min_role(
            ctx.db, ctx.user.tenant_id, "my_tool", _DEFAULT_MIN_ROLE,
        )
        if not has_min_role(ctx.user.role, effective):
            return [TextContent(type="text", text="Permission denied")]
        return [TextContent(type="text", text=do_something(args["input"]))]


register(MyToolProvider())
```

Then add the import at the bottom of `app/tools/__init__.py` so the module is
loaded — registration happens at import time, and there is no auto-discovery:

```python
from app.tools import example, filesystem, my_tool, sql  # noqa: E402,F401
```

Re-check the role inside `handle`. `get_tools` only controls visibility; a
client can still call a tool it was never shown.

`app/tools/example.py` is a working minimal provider to copy from.

## Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/) and [python-semantic-release](https://python-semantic-release.readthedocs.io/) to automate versioning and changelog generation. Every commit merged to `main` is analysed — the type prefix determines whether a release is triggered and what version is bumped.

| Prefix | What it means | Version bump |
|--------|--------------|-------------|
| `feat:` | New feature or behaviour | Minor (`0.x.0`) |
| `fix:` | Bug fix | Patch (`0.0.x`) |
| `perf:` | Performance improvement | Patch |
| `feat!:` or `BREAKING CHANGE:` footer | Breaking API change | Major (`x.0.0`) |
| `docs:` `chore:` `ci:` `test:` `style:` `refactor:` | Everything else | No release |

**Examples:**

```
feat: add Slack notification tool
fix: prevent duplicate audit entries on token refresh
perf: cache schema introspection results for 60 seconds
feat!: rename execute_sql min_role field to min_required_role

BREAKING CHANGE: existing tool role overrides stored in the database
use the old field name and must be migrated.
```

Commits that don't follow this format are ignored by the release process but are still valid — they just won't appear in the changelog.

## Code style

- Python: `ruff` and `mypy` both run in CI and will block a PR. Run them locally
  before pushing:
  ```bash
  python -m ruff check app/ tests/
  python -m mypy app/
  ```
- Keep functions small and focused
- Prefer explicit over clever

## Reporting security issues

Do **not** open a public GitHub issue for security vulnerabilities. Email the maintainers directly. We aim to respond within 48 hours.

## Licence

By contributing you agree that your contributions will be licensed under the MIT License.
