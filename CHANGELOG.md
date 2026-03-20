# Changelog

This file is automatically updated by [python-semantic-release](https://python-semantic-release.readthedocs.io/)
on every merge to `main`. Do not edit it by hand — write [conventional commits](CONTRIBUTING.md#commit-messages) instead.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2025-03-18

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
