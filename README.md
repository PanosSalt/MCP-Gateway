# MCP Gateway

![Tests](https://github.com/PanosSalt/MCP-Gateway/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)

The production platform for MCP tools.

Claude Desktop can connect to your internal tools — databases, filesystems, APIs, anything — through a single authenticated endpoint. You control who can use which tools, every action is logged, and no raw credentials ever leave your server.

Built-in tools: SQL query (Postgres, MySQL, SQLite, MSSQL), filesystem access.
Custom tools: plug in anything that implements the MCP tool interface.

> **[See it in action](docs/media/local_demo.mp4)** — short demo of Claude Desktop querying a database through MCP Gateway.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [API Reference](#api-reference)
- [MCP Integration](#mcp-integration)
- [Role-Based Access Control](#role-based-access-control)
- [Entra ID / SSO](#entra-id--sso)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [Additional Documentation](#additional-documentation)

---

## Overview

MCP Gateway sits between AI assistants and your databases. It:

1. Authenticates users via password login, Microsoft Entra ID (Azure AD), or API keys
2. Enforces role-based access control (viewer / analyst / admin)
3. Exposes databases as MCP tools that AI assistants can discover and call
4. Translates natural language questions into SQL via Claude, executes queries, and summarizes results
5. Logs all activity to a structured audit trail

```
Claude Desktop / mcp-remote
        │
        │ MCP over SSE (OAuth 2.1 + PKCE)
        ▼
┌─────────────────────────────────────────────────────────┐
│                      MCP Gateway                        │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐ │
│  │ Auth /   │  │  Admin   │  │   MCP SSE Endpoint    │ │
│  │ OAuth    │  │   UI     │  │  /t/{slug}/mcp/sse    │ │
│  └──────────┘  └──────────┘  └───────────────────────┘ │
│                                          │              │
│  ┌──────────────────────────────────────┐│              │
│  │         Tool Providers               ││              │
│  │  sql.py → get_schema / execute_sql   ││              │
│  └──────────────────────────────────────┘│              │
└─────────────────────────────────────────┼───────────────┘
                                          │ Decrypted DSN
                    ┌─────────────────────┼────────────────┐
                    │   Your Databases    │                │
                    │  Postgres  MySQL  MSSQL  SQLite      │
                    └────────────────────────────────────  ┘
```

---

## What you get out of the box

**For your organisation**
- One URL for Claude Desktop — users authenticate once, access everything they're allowed
- Microsoft Entra ID SSO — roles assigned automatically from Azure AD groups
- Full audit trail — every tool call, every query, every login, who did what and when

**For your tools**
- Drop any MCP tool into the gateway and it inherits auth, RBAC, and logging automatically
- Per-tool role overrides — restrict SQL execution to analysts, filesystem writes to admins
- Bundled: SQL tools (4 databases), filesystem tools (read, write, search, tree)

**For your security team**
- No credentials on employee machines
- Tenant isolation — org A cannot see org B's tools or data
- API keys for CI/CD, OAuth 2.1 + PKCE for human users

### Supported Databases
| Database | Driver | DSN Format |
|----------|--------|------------|
| PostgreSQL | psycopg2 | `postgresql://user:pass@host/db` |
| MySQL / MariaDB | PyMySQL | `mysql+pymysql://user:pass@host/db` |
| Microsoft SQL Server | pymssql | `mssql+pymssql://user:pass@host/db` |
| SQLite | Built-in | `sqlite:///path/to/file.db` |

### Filesystem Tools
- Sandboxed file read/write/search exposed as MCP tools
- Enabled via `FILESYSTEM_ALLOWED_DIRS` environment variable
- Read operations (analyst+): `fs_read_file`, `fs_list_directory`, `fs_directory_tree`, `fs_search_files`, `fs_get_file_info`
- Write operations (admin): `fs_write_file`, `fs_create_directory`, `fs_move_file`

### Admin UI
- Web interface served at `/admin/`
- Manage connections, users, SSO config, API keys, and tool roles
- View audit logs, generated SQL, and query results

---

## Architecture

### Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| API Framework | FastAPI | 0.131.0 |
| ASGI Server | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy | 2.0.30 |
| Migrations | Alembic | 1.13.1 |
| Auth / JWT | PyJWT + bcrypt | 2.12.0 / 4.0.1 |
| Encryption | cryptography (Fernet) | 46.0.5 |
| LLM | Anthropic SDK | 0.42.0 |
| MCP Protocol | mcp | 1.23.0 |
| SQL Validation | sqlglot | 25.1.0 |
| Rate Limiting | slowapi | 0.1.9 |
| Frontend | React 18 + TypeScript + Vite | — |

### Project Structure

```
app/
├── main.py               # FastAPI app setup, middleware, routing
├── config.py             # Environment config (Pydantic Settings)
├── database.py           # SQLAlchemy engine + session factory
├── api/
│   ├── auth.py           # POST /auth/login
│   ├── auth_entra.py     # Entra SSO (legacy admin UI paths)
│   ├── oauth.py          # OAuth 2.1 endpoints (/t/{slug}/oauth/*)
│   ├── connections.py    # DB connection CRUD
│   ├── query.py          # Natural language query endpoint
│   ├── tenants.py        # Tenant + user management
│   ├── tools.py          # Tool listing + role overrides
│   ├── mcp_sse.py        # MCP SSE transport
│   ├── api_keys.py       # API key management
│   └── audit_logs.py     # GET /audit-logs/ (admin)
├── core/
│   ├── auth.py           # JWT creation/validation, password hashing
│   ├── dependencies.py   # FastAPI dependency injection
│   ├── rbac.py           # Role hierarchy helpers
│   ├── security.py       # Fernet encrypt/decrypt
│   ├── api_keys.py       # API key generation + hashing
│   ├── limiter.py        # slowapi rate limiter setup
│   └── log_filter.py     # Health-check log noise filter
├── constants.py          # Non-tunable application-wide constants (pagination caps, etc.)
├── models/__init__.py    # All SQLAlchemy ORM models
├── schemas/__init__.py   # All Pydantic request/response schemas
├── services/
│   ├── entra.py          # Microsoft Graph API client
│   ├── llm.py            # Anthropic API (SQL gen + summarization)
│   ├── mcp_client.py     # Direct SQLAlchemy schema introspection + query execution
│   └── audit.py          # Audit log writer
└── tools/
    ├── __init__.py       # Tool provider framework + registry
    ├── sql.py            # DB schema + execute_sql tools
    ├── example.py        # Example custom tools
    └── filesystem.py     # Sandboxed file read/write/search tools

frontend/src/
├── App.tsx               # Root component, auth context, tab routing
├── api.ts                # API client, token management
├── types.ts              # TypeScript types (mirrors Pydantic schemas)
├── constants.ts          # Frontend constants (timeouts, retry config)
└── components/
    ├── Login.tsx          # Sign-in form
    ├── Setup.tsx          # Tenant registration
    ├── Dashboard.tsx      # Tenant info + role display
    ├── Connections.tsx    # DB connection management
    ├── Query.tsx          # Natural language query UI
    ├── Users.tsx          # User management (admin)
    ├── SsoConfig.tsx      # Entra ID configuration (admin)
    ├── Tools.tsx          # Tool browser + role overrides
    ├── ApiKeys.tsx        # API key management
    └── AuditLog.tsx       # Filterable audit log viewer (admin)
```

### Database Schema

```
Tenants ─┬─► Users ──────► APIKeys
         ├─► DBConnections
         ├─► TenantEntraConfig
         ├─► AuditLogs
         ├─► OAuthStates
         ├─► OAuthAuthorizationCodes
         ├─► OAuthRefreshTokens
         └─► ToolRoleOverrides
```

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- An Anthropic API key (for the `/query/` endpoint; not needed for raw MCP tool access)

### 1. Clone and configure

```bash
git clone <repo-url>
cd MCP-Gateway
cp .env.example .env
```

Edit `.env`:

```bash
# Required — generate unique values
SECRET_KEY=<random 64-char string>
ENCRYPTION_KEY=<random string, min 32 chars — longer is better>
POSTGRES_PASSWORD=<strong password>

# Required for natural language query
ANTHROPIC_API_KEY=sk-ant-...

# Update to your server's public URL in production
BASE_URL=http://localhost:8000
```

Generate secure random values:

```bash
# SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"

# ENCRYPTION_KEY (min 32 chars; full key consumed via BLAKE2b derivation)
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Start the stack

```bash
docker compose up -d
```

Services started:
- `api` on port **8000** (FastAPI + admin UI)
- `db` on port 5432 (PostgreSQL, internal only)

### 3. Register your first tenant

```bash
curl -s -X POST http://localhost:8000/tenants/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Organization",
    "slug": "my-org",
    "admin_email": "admin@example.com",
    "admin_password": "SuperSecret123!"
  }' | jq
```

The `slug` becomes part of your MCP URL: `http://localhost:8000/t/my-org/mcp/sse`

### 4. Open the admin UI

Navigate to **http://localhost:8000/admin/** and sign in with your admin credentials.

### 5. Add a database connection

In the admin UI → **Connections** → **Create connection**, or via API:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"SuperSecret123!"}' \
  | jq -r .access_token)

curl -s -X POST http://localhost:8000/connections/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production DB",
    "db_type": "postgres",
    "connection_string": "postgresql://user:pass@host/mydb",
    "min_role": "viewer"
  }' | jq
```

### 6. Connect Claude Desktop

Add to your Claude Desktop MCP config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "my-org-gateway": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://localhost:8000/t/my-org/mcp/sse"
      ]
    }
  }
}
```

Restart Claude Desktop. It will open a browser window for OAuth login. After authenticating, Claude can use your database tools.

---

## Configuration

All configuration is via environment variables. See `.env.example` for a template.

### Required

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | JWT signing secret — use a random 64-char string |
| `ENCRYPTION_KEY` | Fernet AES key for DB credentials — minimum 32 characters; full key consumed via BLAKE2b |
| `POSTGRES_PASSWORD` | PostgreSQL password — used by docker-compose for both the `db` service and `DATABASE_URL` |
| `DATABASE_URL` | PostgreSQL DSN — set automatically by docker-compose; only needed for local (non-Docker) dev |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required for `/query/` NL query endpoint |
| `BASE_URL` | `http://localhost:8000` | Public-facing URL (used in OAuth callbacks) |
| `CORS_ORIGINS` | `BASE_URL` | Comma-separated allowed origins for CORS. Must be absolute URLs — wildcards (`*`) are rejected |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | JWT access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | OAuth refresh token lifetime |
| `OAUTH_STATE_TTL_MINUTES` | `10` | OAuth PKCE state validity window — increase for high-latency SSO providers |
| `OAUTH_CODE_TTL_MINUTES` | `5` | OAuth authorization code validity window |
| `LLM_MODEL` | `claude-sonnet-4-6` | Anthropic model for SQL generation |
| `LLM_MAX_TOKENS_SQL` | `1024` | Max tokens for SQL generation |
| `LLM_MAX_TOKENS_SUMMARY` | `500` | Max tokens for result summarization |
| `FILESYSTEM_ALLOWED_DIRS` | — | Comma-separated directories the MCP filesystem tools may access. When empty, no filesystem tools are exposed |

### Entra ID

| Variable | Default | Description |
|----------|---------|-------------|
| `ENTRA_AUTHORITY_URL` | `https://login.microsoftonline.com` | Microsoft identity platform base URL |
| `ENTRA_GRAPH_URL` | `https://graph.microsoft.com/v1.0` | Microsoft Graph API base URL |

---

## Authentication

### Local login

```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SuperSecret123!",
  "tenant_slug": "my-org"   // optional, disambiguates if same email is in multiple tenants
}
```

Response:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

Include the token in subsequent requests:
```
Authorization: Bearer eyJ...
```

Access tokens expire after 15 minutes by default. Use the OAuth token endpoint with a refresh token to get a new pair.

### API keys

Generate a key (requires authentication):

```bash
curl -s -X POST http://localhost:8000/api-keys/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "CI pipeline"}' | jq
```

The `raw_key` in the response is shown **once only** — store it immediately:
```json
{
  "id": "...",
  "name": "CI pipeline",
  "prefix": "mgw_abcd1234",
  "raw_key": "mgw_abcd1234...",
  "created_at": "..."
}
```

Use via query parameter:
```bash
curl "http://localhost:8000/connections/?api_key=mgw_abcd1234..."
```

### OAuth 2.1 (MCP browser clients)

The gateway implements RFC 8414 OAuth discovery. MCP clients follow this flow automatically:

1. Client connects to `/t/{slug}/mcp/sse` — receives 401 + `WWW-Authenticate` header pointing to the OAuth discovery URL
2. Client fetches `/.well-known/oauth-authorization-server/t/{slug}`
3. Client registers dynamically via `POST /t/{slug}/oauth/register`
4. Client opens browser → user logs in at `/t/{slug}/oauth/authorize`
5. Client exchanges code + PKCE verifier for tokens via `POST /t/{slug}/oauth/token`
6. Client reconnects with Bearer token

No manual configuration needed — just point mcp-remote at your tenant's SSE URL.

### API key auth (MCP non-interactive clients)

For CI/CD, scripts, or when you want to skip the browser login, pass an API key in the URL:

```json
{
  "mcpServers": {
    "gateway": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/t/my-org/mcp/sse?api_key=mgw_..."]
    }
  }
}
```

The SSE endpoint validates the key and establishes the session directly — no OAuth flow, no browser window. See [API Keys](docs/api-keys.md) for details.

---

## API Reference

All management endpoints are available at both their canonical paths (e.g. `/tenants/`) and the versioned prefix `/api/v1/` (e.g. `/api/v1/tenants/`). The unversioned paths are kept for backward compatibility with the current frontend; new integrations should use `/api/v1/`. Protocol-defined routes (OAuth `/t/{slug}/…`, MCP `/t/{slug}/…`, `/.well-known/`) and infrastructure routes (`/health`, `/admin`) are intentionally unversioned.

### Tenants & Users

| Method | Path | Role | Description |
|--------|------|------|-------------|
| `POST` | `/tenants/` | Public | Register new tenant + admin user |
| `GET` | `/tenants/me` | Any | Get your tenant details |
| `GET` | `/tenants/users` | Admin | List all users in your tenant |
| `POST` | `/tenants/users` | Admin | Create a local user |
| `PATCH` | `/tenants/users/{id}` | Admin | Update user role |

**Register tenant:**
```bash
curl -X POST http://localhost:8000/tenants/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corp",
    "slug": "acme",
    "admin_email": "admin@acme.com",
    "admin_password": "SuperSecret123!"
  }'
```

**Create user:**
```bash
curl -X POST http://localhost:8000/tenants/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "analyst@acme.com",
    "password": "AnotherSecret456!",
    "role": "analyst"
  }'
```

Roles: `viewer` (default), `analyst`, `admin`. Passwords must be at least 12 characters.

---

### Connections

| Method | Path | Role | Description |
|--------|------|------|-------------|
| `POST` | `/connections/` | Admin | Add a database connection |
| `GET` | `/connections/` | Viewer+ | List accessible connections |
| `PATCH` | `/connections/{id}` | Admin | Update connection |
| `DELETE` | `/connections/{id}` | Admin | Soft-delete connection |

**Add connection:**
```bash
curl -X POST http://localhost:8000/connections/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sales DB",
    "db_type": "postgres",
    "connection_string": "postgresql://user:pass@db-host/sales",
    "description": "Production sales database",
    "min_role": "analyst"
  }'
```

`min_role` controls who can query this connection. Users below this role cannot see or use it.

---

### Natural Language Query

| Method | Path | Role | Rate Limit | Description |
|--------|------|------|-----------|-------------|
| `POST` | `/query/` | Analyst+ | 30/min | Execute NL query |
| `GET` | `/query/history` | Admin | 60/min | Paginated query audit history |

**Query:**
```bash
curl -X POST http://localhost:8000/query/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": "...",
    "question": "What are the top 5 customers by total revenue this quarter?"
  }'
```

Response:
```json
{
  "sql_generated": "SELECT customer_name, SUM(amount) AS total FROM orders ...",
  "result": [
    {"customer_name": "Acme Corp", "total": 125000}
  ],
  "summary": "The top customer this quarter is Acme Corp with $125,000 in revenue."
}
```

The query pipeline:
1. Fetches schema from the database
2. Sends schema + question to Claude → generates SQL
3. Validates SQL is a `SELECT` statement (blocks all writes)
4. Executes SQL (30-second timeout)
5. Sends question + results to Claude → generates summary

---

### Tools

| Method | Path | Role | Description |
|--------|------|------|-------------|
| `GET` | `/tools/` | Any | List MCP tools with role metadata |
| `PATCH` | `/tools/{tool_name}` | Admin | Set or reset role override |

**List tools:**
```bash
curl http://localhost:8000/tools/ \
  -H "Authorization: Bearer $TOKEN"
```

Response:
```json
[
  {
    "tool_name": "execute_sql_sales-db_abcd1234",
    "description": "Execute SQL on Sales DB",
    "connection_id": "...",
    "default_min_role": "analyst",
    "effective_min_role": "admin",
    "accessible": false
  }
]
```

**Override tool role:**
```bash
# Restrict to admin only
curl -X PATCH "http://localhost:8000/tools/execute_sql_sales-db_abcd1234" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"min_role": "admin"}'

# Reset to connection default
curl -X PATCH "http://localhost:8000/tools/execute_sql_sales-db_abcd1234" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"min_role": null}'
```

---

### API Keys

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api-keys/` | Generate a new key |
| `GET` | `/api-keys/` | List your keys |
| `DELETE` | `/api-keys/{id}` | Revoke a key |

```bash
# Generate (expires_at is optional)
curl -X POST http://localhost:8000/api-keys/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "CI pipeline", "expires_at": "2027-01-01T00:00:00Z"}'

# List
curl http://localhost:8000/api-keys/ \
  -H "Authorization: Bearer $TOKEN"

# Revoke
curl -X DELETE "http://localhost:8000/api-keys/{id}" \
  -H "Authorization: Bearer $TOKEN"
```

---

### Audit Logs

| Method | Path | Role | Rate Limit | Description |
|--------|------|------|-----------|-------------|
| `GET` | `/audit-logs/` | Admin | 60/min | List audit events (filterable) |

```bash
# All events (paginated)
curl "http://localhost:8000/audit-logs/?limit=50" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Filter by event type (comma-separated prefixes)
curl "http://localhost:8000/audit-logs/?event_prefix=query,tool&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Query parameters: `skip` (offset, default 0), `limit` (max 200, default 50), `event_prefix` (comma-separated, e.g. `query`, `login`, `fs`).

---

### Health Check

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

Returns `503` if the database is unreachable. Suitable for Kubernetes liveness and readiness probes.

---

## MCP Integration

### Connecting Claude Desktop

Install mcp-remote:
```bash
npm install -g mcp-remote
```

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "gateway": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8000/t/my-org/mcp/sse"]
    }
  }
}
```

On first connection, a browser window opens for OAuth login. After authenticating, mcp-remote caches the tokens and reconnects automatically. Tokens refresh silently in the background.

### Available MCP Tools

For each active database connection the user can access, the gateway exposes two tools:

**`get_schema_{connection-name}_{id}`**
Returns the full database schema (tables, columns, types, constraints, indexes). Claude calls this first to understand the data structure before generating SQL.

**`execute_sql_{connection-name}_{id}`**
Executes a `SELECT` statement and returns rows as JSON. Any non-SELECT statement is rejected (INSERT, UPDATE, DELETE, DROP, etc.). Execution timeout: 30 seconds.

**`list_connections`**
Returns all database connections the user can access with their names and types.

**`get_current_time`**
Returns the current UTC time in ISO 8601 format. Available to all roles.

**Filesystem tools** (only when `FILESYSTEM_ALLOWED_DIRS` is configured):

| Tool | Role | Description |
|------|------|-------------|
| `fs_read_file` | Analyst+ | Read a file as UTF-8 text |
| `fs_list_directory` | Analyst+ | List directory contents |
| `fs_directory_tree` | Analyst+ | Recursive directory tree (JSON) |
| `fs_search_files` | Analyst+ | Glob pattern search |
| `fs_get_file_info` | Analyst+ | File metadata (size, timestamps) |
| `fs_write_file` | Admin | Create or overwrite a file |
| `fs_create_directory` | Admin | Create a directory (with parents) |
| `fs_move_file` | Admin | Move or rename a file |

### SSE Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /t/{slug}/mcp/sse` | Bearer JWT or `?api_key=` | Tenant-scoped SSE (recommended) |
| `POST /t/{slug}/mcp/messages` | Bearer JWT, `?api_key=`, or session ID | Tenant-scoped message handler |
| `GET /mcp/sse` | `?api_key=` or `?token=` | Legacy SSE (deprecated, sunset 2026-06-01) |
| `POST /mcp/messages` | Bearer JWT, `?api_key=`, or `?token=` | Legacy message handler (deprecated) |

### OAuth Discovery Endpoints

| Endpoint | RFC | Description |
|----------|-----|-------------|
| `GET /.well-known/oauth-authorization-server/t/{slug}` | RFC 8414 | Authorization server metadata |
| `GET /.well-known/oauth-protected-resource/t/{slug}/mcp/sse` | RFC 9728 | Protected resource metadata |
| `POST /t/{slug}/oauth/register` | RFC 7591 | Dynamic client registration |
| `GET /t/{slug}/oauth/authorize` | RFC 6749 | Authorization endpoint (PKCE S256) |
| `POST /t/{slug}/oauth/token` | RFC 6749 | Token endpoint (code + refresh_token) |

---

## Build your own tools

Any Python function becomes an authenticated, audited MCP tool:

```python
# app/tools/my_tool.py
from app.tools import register_tool, ToolContext
from mcp.types import TextContent

@register_tool(name="my_custom_tool", min_role="analyst")
async def my_tool(arguments: dict, ctx: ToolContext) -> list[TextContent]:
    # ctx.user gives you the authenticated user + their role
    # ctx.db gives you the database session
    result = do_something(arguments["input"])
    return [TextContent(type="text", text=result)]
```

Restart the gateway. The tool appears in Claude Desktop automatically, with auth and audit logging included.

---

## Role-Based Access Control

Three roles in ascending order of permission: `viewer` → `analyst` → `admin`

### Default permissions

| Action | Viewer | Analyst | Admin |
|--------|:------:|:-------:|:-----:|
| View connections | ✓ | ✓ | ✓ |
| Run NL queries | — | ✓ | ✓ |
| Use filesystem tools (read) | — | ✓ | ✓ |
| Use filesystem tools (write) | — | — | ✓ |
| View audit logs | — | — | ✓ |
| View query history | — | — | ✓ |
| Manage connections | — | — | ✓ |
| Manage users | — | — | ✓ |
| Configure SSO | — | — | ✓ |
| Manage API keys | ✓ | ✓ | ✓ |
| Override tool roles | — | — | ✓ |

### Per-connection roles

Each connection has a `min_role`. Users below this role cannot see or use that connection, or the MCP tools it generates.

Example: A sensitive production database with `min_role: admin` is invisible to analysts and viewers entirely — it won't appear in `/connections/` or `/tools/`, and its MCP tools won't be listed.

### Per-tool overrides

Admins can override the effective minimum role for any MCP tool independently of the connection's `min_role`:

```bash
# Lock down SQL execution on prod, but keep schema browsing open
PATCH /tools/execute_sql_prod-db_abcd1234  {"min_role": "admin"}
PATCH /tools/get_schema_prod-db_abcd1234   {"min_role": "analyst"}

# Reset to connection default
PATCH /tools/execute_sql_prod-db_abcd1234  {"min_role": null}
```

---

## Entra ID / SSO

### Setup in Azure AD

1. Register an application in Azure Active Directory (App registrations → New registration)
2. Add redirect URIs:
   - `http://<gateway-url>/auth/entra/callback` (admin UI SSO)
   - `http://<gateway-url>/t/<slug>/oauth/entra-callback` (MCP OAuth flow)
3. Under **API permissions**, add:
   - **Delegated** (Microsoft Graph): `openid`, `profile`, `email`, `User.Read`, `GroupMember.Read.All`
   - **Application** (Microsoft Graph): `Directory.Read.All` (required for role sync during token refresh)
   - Grant **admin consent** for the delegated `GroupMember.Read.All` and the application `Directory.Read.All`
4. Create a **Client secret** (Certificates & secrets → New client secret)
5. Note your Azure tenant ID, app client ID, and the client secret value

### Configure in MCP Gateway

Via admin UI: **SSO Config** tab, or via API:

```bash
curl -X POST http://localhost:8000/auth/entra/config \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "entra_tenant_id": "your-azure-tenant-uuid",
    "client_id": "your-app-client-id",
    "client_secret": "your-client-secret",
    "admin_group_id": "azure-group-uuid-for-admins",
    "analyst_group_id": "azure-group-uuid-for-analysts",
    "viewer_group_id": "azure-group-uuid-for-viewers"
  }'
```

Group IDs are optional — configure only what you need. Users in multiple mapped groups get the highest role.

### Login flow

Direct users to: `http://<gateway>/auth/entra/login?tenant_slug=<slug>`

The gateway redirects to Microsoft. After authentication it:
1. Fetches the user's profile from Microsoft Graph (`/me`)
2. Fetches transitive group memberships (`/me/transitiveMemberOf`)
3. Maps groups to roles (highest wins: admin > analyst > viewer)
4. Creates the user if they don't exist (just-in-time provisioning)
5. Returns a JWT

---

## Development

### Local setup (without Docker)

```bash
# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env: set DATABASE_URL to a local Postgres instance (or use SQLite for quick testing)

# Run migrations
alembic upgrade head

# Start API (with auto-reload)
uvicorn app.main:app --reload --port 8000
```

### Frontend development

```bash
cd frontend
npm install
npm run dev   # Vite dev server on port 5173 with API proxy
```

The Vite dev server proxies all API paths to `http://localhost:8000`, so the frontend and API can run independently during development.

### Sample databases

```bash
docker compose --profile dev up -d
```

Starts pre-seeded sample databases:
- `sample_postgres` on port **5433** → `postgresql://sampleuser:samplepass@localhost:5433/sampledb`
- `sample_mysql` on port **3307** → `mysql+pymysql://sampleuser:samplepass@localhost:3307/sampledb`

Add these as connections in the admin UI to explore the natural language query feature.

### Running tests

```bash
# All 198 tests (no external services required — uses SQLite in-memory)
.venv/bin/python -m pytest

# Verbose output
.venv/bin/python -m pytest -v

# Single test file
.venv/bin/python -m pytest tests/test_connections_api.py -v

# Single test
.venv/bin/python -m pytest tests/test_oauth.py::test_token_endpoint_code_exchange -v
```

### Database migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration after changing models/__init__.py
alembic revision --autogenerate -m "describe your change"

# Roll back one step
alembic downgrade -1

# Show history
alembic history --verbose
```

### Building for production

```bash
# Build frontend static files
cd frontend && npm run build && cd ..

# The Dockerfile builds both in a multi-stage build:
docker build -t mcp-gateway .
docker compose up -d
```

---

## Troubleshooting

### "SECRET_KEY must be set" / "ENCRYPTION_KEY must be set"

docker-compose uses `${VAR:?error message}` syntax — it fails fast if these are not set. Generate them:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"           # SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"           # ENCRYPTION_KEY
```

Add to your `.env` file before running `docker compose up`.

### API returns 503 on health check

The database is not reachable. Check:
```bash
docker compose ps        # are all containers running?
docker compose logs db   # any Postgres startup errors?
docker compose restart api  # restart API if db was slow to start
```

### Claude Desktop doesn't open a browser for login

Ensure mcp-remote is installed: `npm install -g mcp-remote`. Check that `BASE_URL` in `.env` matches the URL you put in `claude_desktop_config.json`. A mismatch causes the OAuth callback to fail silently.

### Query returns `"INVALID_QUERY"`

The LLM could not generate a valid `SELECT` for your question, or it generated a non-SELECT statement (which is blocked). Try:
- Be more specific in your question
- Ensure your database has descriptive column and table names
- Check that `ANTHROPIC_API_KEY` is set and valid

### Entra login returns 400 "Entra ID not configured for this tenant"

The tenant doesn't have an Entra ID configuration. Add one via **Admin UI → SSO Config** or `POST /auth/entra/config`.

### Entra callback returns 403 "Not a member of any authorized group"

The Azure AD user is not in any of the three groups configured for the tenant. Either:
- Add the user to one of the mapped groups in Azure AD
- Update the group IDs in the gateway config to match the user's actual groups (`POST /auth/entra/config`)

### Refresh token rejected as "Invalid or expired"

Refresh tokens are **single-use** — each use issues a new pair and revokes the old one. If two requests attempt to use the same refresh token simultaneously, the second fails. Re-authenticate to get a fresh pair.

### Rate limit 429 responses

| Endpoint | Limit |
|----------|-------|
| `POST /tenants/` | 5/min |
| `POST /auth/login` | 10/min |
| `POST /t/{slug}/oauth/login` | 10/min |
| `POST /api-keys/` | 10/min |
| `GET /auth/entra/login` | 20/min |
| `GET /t/{slug}/oauth/authorize` | 30/min |
| `POST /t/{slug}/oauth/token` | 30/min |
| `POST /query/` | 30/min |
| `GET /audit-logs/` | 60/min |
| `GET /query/history` | 60/min |

Wait 60 seconds for the limit window to reset.

---

## Security

### Credentials at rest

| Data | Storage |
|------|---------|
| Passwords | bcrypt (never stored plain) |
| JWT signing | `SECRET_KEY` (HS256) |
| DB connection strings | Fernet AES-256 encrypted |
| Entra client secrets | Fernet AES-256 encrypted |
| API keys | HMAC-SHA-256 keyed with `SECRET_KEY` (raw key returned once, never stored) |
| Refresh tokens | SHA-256 hash |

### HTTP security headers

All responses include:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Strict-Transport-Security: max-age=31536000`
- `Cache-Control: no-store` on auth endpoints

### OAuth protections

- **PKCE S256** — prevents authorization code interception attacks
- **Single-use authorization codes** — codes expire after 5 minutes and are deleted on first use
- **Rotating refresh tokens** — each refresh revokes the previous token (prevents replay)
- **Loopback-only redirect URIs** — only `localhost`, `127.0.0.1`, and `::1` are accepted as redirect targets (per RFC 8252)

### SQL safety

The `execute_sql` MCP tool rejects all non-SELECT statements via sqlglot AST parsing before any query reaches the database. INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, and EXEC are all blocked regardless of how they are formatted.

### Tenant isolation

All database queries are scoped to `current_user.tenant_id`. Foreign key constraints enforce isolation at the schema level — there is no code path that allows data from one tenant to appear in another tenant's responses.

### Rotating secrets

**Rotating `SECRET_KEY`:** All existing JWTs immediately become invalid. Users must re-authenticate. Refresh tokens (hashed separately) are also invalidated. **API keys are also invalidated** — they are HMAC-keyed with `SECRET_KEY`, so existing keys must be revoked and re-issued after rotation.

**Rotating `ENCRYPTION_KEY`:** Requires re-encrypting all stored connection strings and Entra client secrets with the new key before the old key is removed. Plan this as a maintenance window — the gateway cannot serve connections during the rotation.

### Audit log

All significant events are written to the `audit_logs` table:

| Event | When |
|-------|------|
| `login.success` / `login.failure` | Every login attempt |
| `oauth.login` / `oauth.entra_login` | OAuth authorization |
| `oauth.token_issued` / `oauth.token_refreshed` | Token exchange and refresh |
| `query.success` / `query.failure` | Every NL query |
| `tool.execute_sql` / `tool.execute_sql.rejected` / `tool.execute_sql.error` | MCP SQL tool usage |
| `fs.*` (e.g. `fs.fs_read_file`, `fs.fs_write_file.error`) | Filesystem tool usage |
| `connection.created` / `connection.updated` / `connection.deleted` | Connection changes |
| `tenant.created` | Tenant registration |
| `user.deleted` / `user.role_updated` | User management |
| `key.created` / `key.revoked` | API key lifecycle |

Query the audit log:
```bash
curl "http://localhost:8000/audit-logs/?limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
```

---

## Additional Documentation

| Guide | Description |
|-------|-------------|
| [Testing with Claude Desktop](docs/testing-with-claude-desktop.md) | End-to-end walkthrough: local users + Entra SSO |
| [Deployment Guide](docs/deployment.md) | Railway, Render, and generic Docker/VPS deployment |
| [OAuth 2.1 Flow](docs/oauth2-flow.md) | Full PKCE flow, endpoints, token lifecycle |
| [Filesystem Tools](docs/filesystem-tools.md) | Sandboxed file access via MCP |
| [Audit Logging](docs/audit-logging.md) | Event catalog, API, and metadata reference |
| [API Keys](docs/api-keys.md) | Key lifecycle, security model, usage |
| [Tool Role Overrides](docs/tool-role-overrides.md) | Per-tool RBAC configuration |

## What's Coming — SaltMine AI

MCP Gateway is the open source foundation. A managed platform called **SaltMine AI** 
is currently in development, built on top of this project, following the same security principles and aimed at business teams 
who want to query their data without any infrastructure to manage.

Planned features include:

- Multi-datasource queries across databases, data lakes, and APIs in a single question
- Business-user chat interface with visualisations — no SQL knowledge required
- Data privacy controls with field-level masking and query-level audit trails
- Zero Vendor Lock-in on AI
- Understands Your Business Language

If you're interested in learning more, have a use case you'd like to discuss, 
or just want to follow the progress:

- 📧 [salterisp@gmail.com](mailto:salterisp@gmail.com)
- 💼 [linkedin.com/in/panagiotissalteris](https://www.linkedin.com/in/panagiotissalteris)