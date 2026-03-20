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
# Edit .env — set DATABASE_URL to a local Postgres instance or leave for SQLite fallback
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Run the test suite (no external services required — uses SQLite in-memory):

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

Drop a file in `app/tools/` and use the `@register_tool` decorator:

```python
from app.tools import register_tool, ToolContext
from mcp.types import TextContent

@register_tool(name="my_tool", min_role="analyst")
async def my_tool(arguments: dict, ctx: ToolContext) -> list[TextContent]:
    result = do_something(arguments["input"])
    return [TextContent(type="text", text=result)]
```

The tool is auto-discovered on startup. No other wiring needed.

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

- Python: follow the existing style (no strict linter enforced yet)
- Keep functions small and focused
- Prefer explicit over clever

## Reporting security issues

Do **not** open a public GitHub issue for security vulnerabilities. Email the maintainers directly. We aim to respond within 48 hours.

## Licence

By contributing you agree that your contributions will be licensed under the MIT License.
