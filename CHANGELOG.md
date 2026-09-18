# Changelog

This file is automatically updated by [python-semantic-release](https://python-semantic-release.readthedocs.io/)
on every merge to `main`. Do not edit it by hand — write [conventional commits](CONTRIBUTING.md#commit-messages) instead.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

<!-- version list -->

## v1.0.2 (2026-09-18)

### Bug Fixes

- **changelog**: Add insertion marker and backfill v1.0.0/v1.0.1 entries
  ([#3](https://github.com/PanosSalt/MCP-Gateway/pull/3),
  [`1dcfb9a`](https://github.com/PanosSalt/MCP-Gateway/commit/1dcfb9aa1f4f68c6d649b0a6dd61731900efff6b))


## v1.0.1 (2026-09-18)

### Bug Fixes

- **ci**: Authenticate release workflow as GitHub App instead of GITHUB_TOKEN
  ([#2](https://github.com/PanosSalt/MCP-Gateway/pull/2),
  [`5a80ae1`](https://github.com/PanosSalt/MCP-Gateway/commit/5a80ae121efd2e9704d93e9093f19324c3370ef7))

- **deps**: Patch npm advisories and bump frontend build to Node 22
  ([#1](https://github.com/PanosSalt/MCP-Gateway/pull/1),
  [`5135c77`](https://github.com/PanosSalt/MCP-Gateway/commit/5135c776167b0fba772895cd5f6bb6f4cdcdc1e9))

- **deps**: Upgrade dependencies to patch all known security advisories
  ([#1](https://github.com/PanosSalt/MCP-Gateway/pull/1),
  [`5135c77`](https://github.com/PanosSalt/MCP-Gateway/commit/5135c776167b0fba772895cd5f6bb6f4cdcdc1e9))


## [1.0.0] - 2026-03-20

### Added

**Core gateway**
- Multi-tenant architecture — complete isolation between organisations at the schema level
- MCP SSE transport (`/t/{slug}/mcp/sse`) with OAuth 2.1 + PKCE authentication
- Tool provider framework with `@register_tool` decorator for custom tools
- Structured audit log — every login, query, and tool call recorded

**Authentication**
- Local email/password login with bcrypt + JWT (15-min access tokens, 30-day refresh tokens)
- Microsoft Entra ID (Azure AD) SSO with automatic role assignment from group membership
- API keys with optional expiry (SHA-256 hashed, raw key shown once)
- Full OAuth 2.1 + PKCE flow (RFC 8414 discovery, RFC 7591 dynamic registration)

**Built-in tools**
- SQL tools: `get_schema` and `execute_sql` for PostgreSQL, MySQL, MSSQL, and SQLite
- `execute_sql` rejects all non-SELECT statements via sqlglot AST parsing
- Filesystem tools: read, write, search, directory tree — sandboxed to configured directories
- `list_connections` and `get_current_time` utility tools

**Access control**
- Three-role hierarchy: `viewer` → `analyst` → `admin`
- Per-connection `min_role` — users below the threshold cannot see the connection or its tools
- Per-tool role overrides — admins can tighten or loosen individual tool access independently

**Admin UI**
- React + TypeScript single-page app served from `/admin/`
- Manage connections, users, SSO config, API keys, and tool role overrides
- Filterable audit log viewer

**Infrastructure**
- Docker Compose setup with Postgres, optional sample databases for development
- Alembic migrations
- GitHub Actions CI (pytest on every PR)
- Rate limiting on all sensitive endpoints
