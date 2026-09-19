# API Keys

API keys provide long-lived programmatic access to MCP Gateway without requiring a browser-based OAuth flow. They are useful for CI/CD pipelines, scripts, and non-interactive integrations.

---

## How They Work

1. An authenticated user creates an API key via the REST API or admin UI
2. The gateway returns the raw key **once** — it is never stored or retrievable again
3. The key is HMAC-SHA-256 hashed (keyed with `SECRET_KEY`) and stored in the database alongside a short prefix
4. Subsequent requests include the raw key as a query parameter
5. The gateway hashes the provided key, looks up the prefix, and validates the hash

---

## Key Format

Keys follow the format `mgw_{first8}_{random}`, where `random` is a 43-character
`secrets.token_urlsafe(32)` value and `first8` is its first 8 characters:

- `mgw_` — fixed namespace prefix
- `mgw_{first8}` — the **stored prefix** (12 characters), kept in plaintext for
  lookup and display
- The full 43-character random value follows. Note it *repeats* the 8 characters
  already shown in the prefix — they are not disjoint halves

Only the full key is accepted for authentication, and only its HMAC-SHA-256
digest is stored. A full key is 56 characters.

Example shape: `mgw_hPR2Rod3_hPR2Rod3<35 more characters>`

---

## API Endpoints

### Create a Key

**POST** `/api-keys`

**Authentication:** Any authenticated user (JWT or existing API key)

**Rate limit:** 10/minute

Request:
```json
{
  "name": "CI pipeline",
  "expires_at": "2027-01-01T00:00:00Z"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Human-readable label (1-100 characters) |
| `expires_at` | datetime | No | Optional expiry time (ISO 8601). Null means no expiry |

Response (201):
```json
{
  "id": "abc-123-def",
  "name": "CI pipeline",
  "prefix": "mgw_a1b2c3d4",
  "raw_key": "mgw_a1b2c3d4_e5f6g7h8i9j0k1l2m3n4o5p6",
  "created_at": "2026-03-18T12:00:00Z"
}
```

The `raw_key` field is only included in the create response. Store it immediately.

**Error cases:**
- `409 Conflict` — An **active** key with this name already exists for the user

> If a **revoked** key with the same name exists, it is automatically deleted when the new key is created. This keeps the key list clean after rotation.

### List Keys

**GET** `/api-keys`

**Authentication:** Any authenticated user

Returns all keys belonging to the current user. The raw key value is never returned.

Response:
```json
[
  {
    "id": "abc-123-def",
    "name": "CI pipeline",
    "prefix": "mgw_a1b2c3d4",
    "created_at": "2026-03-18T12:00:00Z",
    "last_used_at": "2026-03-18T14:30:00Z",
    "revoked_at": null,
    "expires_at": "2027-01-01T00:00:00Z"
  }
]
```

### Revoke a Key

**DELETE** `/api-keys/{key_id}`

**Authentication:** Any authenticated user (must own the key)

Sets the `revoked_at` timestamp. The key immediately stops working. Revocation is permanent.

Response: **`204 No Content`** with an empty body.

---

## Usage

Pass the raw key as a query parameter on any authenticated endpoint:

```bash
# List connections
curl "http://localhost:8000/connections/?api_key=mgw_a1b2c3d4_e5f6..."

# MCP SSE endpoint (tenant-scoped, recommended)
curl "http://localhost:8000/t/my-org/mcp/sse?api_key=mgw_a1b2c3d4_e5f6..."

# MCP SSE endpoint (legacy, deprecated — sunset 2027-03-01)
curl "http://localhost:8000/mcp/sse?api_key=mgw_a1b2c3d4_e5f6..."
```

The key inherits the role and tenant of the user who created it.

### MCP clients (Claude Desktop, Cursor)

API keys work with `mcp-remote` on the tenant-scoped endpoint. Pass the key in the URL:

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

This skips the OAuth browser login entirely — no browser window opens. The key is validated on the SSE connection, and subsequent MCP message POSTs are authenticated via the session ID.

---

## Security Model

| Aspect | Detail |
|--------|--------|
| **Storage** | HMAC-SHA-256 keyed with `SECRET_KEY`; raw key never stored. A database breach alone is insufficient to recover keys — `SECRET_KEY` is also required |
| **Lookup** | Prefix-based (O(1) lookup, then hash comparison) |
| **Transport** | Query parameter — ensure HTTPS in production to prevent interception |
| **Scope** | Same role and tenant as the creating user |
| **Revocation** | Immediate and permanent via `DELETE /api-keys/{id}` |
| **Expiry** | Optional; expired keys are rejected at validation time |
| **Last used** | `last_used_at` is updated on each successful authentication |

### API Keys vs. OAuth Tokens

| | API Key | OAuth Access Token |
|---|---------|-------------------|
| **Lifetime** | Long-lived (optional expiry) | Short-lived (15 minutes default) |
| **Use case** | Scripts, CI/CD, automation, MCP clients | Browser-based clients, MCP desktop apps |
| **Revocation** | Explicit via API | Implicit (expires, or rotate `SECRET_KEY`) |
| **Refresh** | N/A — key is permanent until revoked | Via refresh token grant |
| **Transport** | Query parameter `?api_key=...` | `Authorization: Bearer` header |

---

## Admin UI

The **API Keys** tab in the admin UI allows users to:

- Create new keys with optional names and expiry dates
- View all keys with prefix, creation date, and last-used timestamp
- Revoke keys with a single click
- See which keys have expired

---

## Audit Trail

| Event | When |
|-------|------|
| `key.created` | New key generated (metadata: `key_name`, `key_prefix`) |
| `key.revoked` | Key revoked (metadata: `key_prefix` only — no name) |
