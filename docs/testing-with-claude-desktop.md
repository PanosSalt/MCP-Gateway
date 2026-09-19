# Testing MCP Gateway with Claude Desktop

This guide covers two authentication paths for testing the gateway end-to-end:

- **Path A — Local users**: create users in the Admin UI and assign roles manually
- **Path B — Entra SSO**: users authenticate via Azure AD and receive roles automatically from group membership

Both paths use the same OAuth 2.1 + PKCE flow with Claude Desktop — no API keys or manual token pasting required.

> **Admin UI** is available at `http://localhost:8000/admin` once the gateway is running.

---

## Prerequisites

| Tool | Notes |
|---|---|
| Docker + Docker Compose | To run the gateway and sample databases |
| Node.js ≥ 20 + npx | Client-side only — Claude Desktop runs `mcp-remote` via `npx`. The gateway itself connects to databases directly over SQLAlchemy and spawns no subprocesses. |
| Claude Desktop | Download from [claude.ai/download](https://claude.ai/download) |
| A modern browser | For the Admin UI and OAuth login |

---

## 1. Start the Gateway

### 1a. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
SECRET_KEY=your-random-secret-here
ENCRYPTION_KEY=<paste the generated value below — do not use a placeholder>
BASE_URL=http://localhost:8000
POSTGRES_PASSWORD=mcppass
```

Generate secure values:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"          # SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"          # ENCRYPTION_KEY
```

### 1b. Start the stack

```bash
docker compose --profile dev up --build -d
```

Wait until healthy:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

The `dev` profile includes `sample_postgres` (port `5433`) and `sample_mysql` (port `3307`) with seed data pre-loaded.

---

## 2. Create a Tenant

Open **http://localhost:8000/admin** and click **Create a new tenant**:

| Field | Value |
|---|---|
| **Organisation name** | `Local Test Corp` |
| **Slug** | `local-test-corp` |
| **Admin email** | `admin@demo.com` |
| **Admin password** | `supersecret123` |

Click **Create tenant**, then sign in with those credentials.

<details>
<summary>Alternative: curl</summary>

```bash
curl -s -X POST http://localhost:8000/tenants/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Local Test Corp",
    "slug": "local-test-corp",
    "admin_email": "admin@demo.com",
    "admin_password": "supersecret123"
  }' | python3 -m json.tool

TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@demo.com", "password": "supersecret123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

</details>

---

## 3. Register Database Connections

In the Admin UI go to the **Connections** tab and click **+ Add connection**.

### Postgres

| Field | Value |
|---|---|
| **Name** | `Products DB` |
| **Type** | `postgres` |
| **Connection string** | `postgresql://sampleuser:samplepass@sample_postgres:5432/sampledb` |

### MySQL

| Field | Value |
|---|---|
| **Name** | `HR Database` |
| **Type** | `mysql` |
| **Connection string** | `mysql://sampleuser:samplepass@sample_mysql:3306/sampledb` |

> Use the Docker service names (`sample_postgres`, `sample_mysql`) as hostnames — the gateway runs inside Docker and cannot reach `localhost`.

<details>
<summary>Alternative: curl</summary>

```bash
curl -s -X POST http://localhost:8000/connections/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Products DB",
    "db_type": "postgres",
    "connection_string": "postgresql://sampleuser:samplepass@sample_postgres:5432/sampledb"
  }' | python3 -m json.tool

curl -s -X POST http://localhost:8000/connections/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "HR Database",
    "db_type": "mysql",
    "connection_string": "mysql://sampleuser:samplepass@sample_mysql:3306/sampledb"
  }' | python3 -m json.tool
```

</details>

---

## Path A — Local Users with Manual Role Assignment

Users are created directly in the gateway with a role (`admin`, `analyst`, or `viewer`). They sign in with email + password via the gateway's own login form.

### A1. Create additional users

In the Admin UI go to the **Users** tab and click **+ Add user**:

| Email | Password | Role |
|---|---|---|
| `analyst@demo.com` | `analyst-pass-123` | `analyst` |
| `viewer@demo.com` | `viewer-pass-456` | `viewer` |

<details>
<summary>Alternative: curl</summary>

```bash
curl -s -X POST http://localhost:8000/tenants/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "analyst@demo.com", "password": "analyst-pass-123", "role": "analyst"}' \
  | python3 -m json.tool

curl -s -X POST http://localhost:8000/tenants/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "viewer@demo.com", "password": "viewer-pass-456", "role": "viewer"}' \
  | python3 -m json.tool
```

</details>

### A2. Change or remove a user

In the **Users** tab:
- **Change role**: use the role dropdown next to any local user
- **Remove user**: click the **Remove** button (not available for your own account)

<details>
<summary>Alternative: curl</summary>

```bash
# List users to find IDs
curl -s http://localhost:8000/tenants/users \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Change role
curl -s -X PATCH http://localhost:8000/tenants/users/<user-id> \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "analyst"}' | python3 -m json.tool

# Remove user
curl -s -X DELETE http://localhost:8000/tenants/users/<user-id> \
  -H "Authorization: Bearer $TOKEN"
```

</details>

### A3. Configure Claude Desktop

| OS | Config path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "mcp-gateway": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/t/local-test-corp/mcp/sse"]
    }
  }
}
```

Fully restart Claude Desktop. On first connection a browser window opens showing the gateway's login form — sign in with any of the users you created. The session is cached automatically.

### Alternative: API key auth (no browser login)

If you want to skip the OAuth browser flow entirely (useful for Cursor, CI/CD, or headless environments), create an API key and pass it in the URL:

1. In the Admin UI go to **API Keys** and click **+ New key** (or use `POST /api-keys`)
2. Copy the raw key (shown once only)
3. Use this config:

```json
{
  "mcpServers": {
    "mcp-gateway": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/t/local-test-corp/mcp/sse?api_key=mgw_..."]
    }
  }
}
```

No browser window opens — the connection authenticates immediately via the API key.

---

## Path B — Entra SSO with Automatic Role Assignment

Users authenticate via Azure AD. The gateway maps Azure AD group membership to gateway roles automatically — no manual user creation needed. Users are provisioned on first login (JIT provisioning).

### B1. Gather Azure AD details

You need from your Azure AD app registration:

| Value | Where to find it |
|---|---|
| **Tenant ID** | Azure portal → Azure Active Directory → Overview |
| **Client ID** | App registration → Overview |
| **Client secret** | App registration → Certificates & secrets |
| **Admin group object ID** | Azure AD → Groups → your admin group → Object ID |
| **Analyst group object ID** | same |
| **Viewer group object ID** | same |

The app registration must have:
- Redirect URI: `http://localhost:8000/t/local-test-corp/oauth/entra-callback`
- API permissions (Microsoft Graph):
  - **Delegated**: `openid`, `profile`, `email`, `User.Read`, `GroupMember.Read.All`
  - **Application**: `GroupMember.Read.All` (required for role sync during token refresh)
  - Grant **admin consent** for both the delegated and the application `GroupMember.Read.All`

### B2. Configure Entra on the tenant

In the Admin UI go to the **SSO Config** tab and fill in:

| Field | Value |
|---|---|
| **Entra Tenant ID** | your Azure AD tenant ID |
| **Client ID** | your app registration client ID |
| **Client Secret** | your app registration secret |
| **Admin Group ID** | object ID of the group whose members become `admin` |
| **Analyst Group ID** | object ID of the group whose members become `analyst` |
| **Viewer Group ID** | object ID of the group whose members become `viewer` |

Click **Save**.

<details>
<summary>Alternative: curl</summary>

```bash
curl -s -X POST http://localhost:8000/auth/entra/config \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "entra_tenant_id": "<azure-tenant-id>",
    "client_id": "<app-client-id>",
    "client_secret": "<app-client-secret>",
    "admin_group_id": "<admin-group-object-id>",
    "analyst_group_id": "<analyst-group-object-id>",
    "viewer_group_id": "<viewer-group-object-id>"
  }' | python3 -m json.tool
```

</details>

### B3. Configure Claude Desktop

Same config as Path A — the slug URL is identical:

```json
{
  "mcpServers": {
    "mcp-gateway": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/t/local-test-corp/mcp/sse"]
    }
  }
}
```

Fully restart Claude Desktop. On first connection a browser window opens and — because Entra is configured on the tenant — **redirects directly to the Microsoft login page**. After signing in, the gateway checks the user's group membership and assigns the matching role automatically.

### B4. How role resolution works

| Azure AD group membership | Assigned gateway role |
|---|---|
| Member of Admin Group ID | `admin` |
| Member of Analyst Group ID | `analyst` |
| Member of Viewer Group ID | `viewer` |
| Not in any configured group | Login denied — a **302** back to the client's `redirect_uri` with `error=access_denied`, not a 403. An existing user record is deactivated |

Role is re-evaluated on every token refresh and login. Removing a user from all Azure AD groups deactivates their gateway account and blocks further access. Re-adding them to a group re-activates the account automatically on their next successful login. Entra-provisioned users appear in the **Users** tab with provider `ENTRA` and can be removed from there if needed.

---

## 4. Test Queries in Claude Desktop

Once connected, Claude Desktop can see these MCP tools:

| Tool | Description |
|---|---|
| `list_connections` | Lists databases available to your role |
| `get_schema_<name>_<id>` | Returns the full schema for a database |
| `execute_sql_<name>_<id>` | Executes a SELECT query and returns rows |

Try asking:

- "What products do we have in stock and what are their prices?"
- "Show me the top 3 most expensive products"
- "List all employees in the Engineering department"
- "What is the average salary by department?"

Claude will call `list_connections`, then `get_schema_...`, generate SQL, call `execute_sql_...`, and answer in plain English.

---

## 5. Test via Admin UI Query Tab

The **Query** tab in the Admin UI lets you run natural language queries from the browser (requires `ANTHROPIC_API_KEY` in `.env`).

1. Go to the **Query** tab.
2. Select **Products DB**.
3. Ask: `What are the top 3 best-selling products by total quantity ordered?`
4. Click **Run query**.

---

## Troubleshooting

### Claude Desktop doesn't show the MCP Gateway tools

1. Check the gateway: `curl http://localhost:8000/health`
2. Check the SSE endpoint responds:
   ```bash
   curl -i http://localhost:8000/t/local-test-corp/mcp/sse
   ```
   Expect **`401 Unauthorized`** with a `WWW-Authenticate: Bearer resource_metadata=...`
   header. That is the correct unauthenticated response and is what triggers
   `mcp-remote`'s browser login — a `404` means the tenant slug is wrong.
3. Fully quit and reopen Claude Desktop (not just close the window)
4. Check Claude Desktop logs:
   - macOS: `~/Library/Logs/Claude/`
   - Windows: `%APPDATA%\Claude\logs\`

### OAuth login window doesn't appear

- Verify the tenant slug in the config URL matches the one you created
- Verify `BASE_URL=http://localhost:8000` is set in `.env`

### Entra login: "Not in any authorised group"

The signed-in user is not a member of any of the three group IDs configured in B2. Add the user to an Azure AD group, or update the group IDs in the SSO Config to match the user's actual groups.

### Entra login: token exchange fails (502)

- Check the client secret hasn't expired in Azure AD
- Verify the redirect URI `http://localhost:8000/t/local-test-corp/oauth/entra-callback` is registered in the app registration

### "Connection refused" when querying

The gateway connects to databases directly via SQLAlchemy. Ensure:
- The connection string uses Docker service names (`sample_postgres`, `sample_mysql`), not `localhost`, when running inside Docker
- The database port is reachable from the gateway container

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | None | Liveness check |
| `GET` | `/admin` | None | Admin UI (browser) |
| `POST` | `/tenants/` | None | Register tenant + admin user |
| `POST` | `/auth/login` | None | Get JWT (local users) |
| `GET` | `/tenants/me` | Any role | Get your tenant info |
| `GET` | `/tenants/users` | Admin | List tenant users |
| `POST` | `/tenants/users` | Admin | Add a local user |
| `PATCH` | `/tenants/users/{id}` | Admin | Update a user's role |
| `DELETE` | `/tenants/users/{id}` | Admin | Remove a user |
| `POST` | `/auth/entra/config` | Admin | Configure Entra SSO |
| `GET` | `/auth/entra/config` | Admin | Get current Entra config |
| `DELETE` | `/auth/entra/config` | Admin | Remove Entra config |
| `POST` | `/connections/` | Admin | Register a DB connection |
| `GET` | `/connections/` | Any role | List active connections |
| `PATCH` | `/connections/{id}` | Admin | Update a connection |
| `DELETE` | `/connections/{id}` | Admin | Soft-delete a connection |
| `POST` | `/query/` | Analyst+ | Natural language query (REST) |
| `GET` | `/tools/` | Any role | List MCP tools |
| `PATCH` | `/tools/{name}` | Admin | Override tool min_role |
| `GET` | `/t/{slug}/mcp/sse` | OAuth or API key | MCP SSE endpoint (Claude Desktop, Cursor) |
| `GET` | `/docs` | None | Interactive Swagger UI |
