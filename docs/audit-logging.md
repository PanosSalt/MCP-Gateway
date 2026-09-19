# Audit Logging

MCP Gateway writes a structured audit log entry for every significant action. All events are stored in the `audit_logs` database table and can be queried via the REST API or the admin UI.

---

## API Endpoint

### `GET /audit-logs/`

**Authentication:** Admin only

**Rate limit:** 60/minute

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | integer | `0` | Number of entries to skip (pagination offset) |
| `limit` | integer | `50` | Number of entries to return (max 200) |
| `event_prefix` | string | — | Comma-separated event prefixes to filter by |

**Examples:**

```bash
# All events, first page
curl "http://localhost:8000/audit-logs/" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Query and tool events only
curl "http://localhost:8000/audit-logs/?event_prefix=query,tool" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Auth events, page 2
curl "http://localhost:8000/audit-logs/?event_prefix=login,oauth&skip=50&limit=50" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Response Schema

Each entry in the response array:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique audit log ID |
| `user_id` | string | ID of the acting user (null for unauthenticated actions) |
| `user_email` | string | Email of the acting user (resolved by joining the `users` table at read time) |
| `event` | string | Event identifier (e.g. `login.success`, `tool.execute_sql`) |
| `ip_address` | string | Client IP address |
| `metadata` | object | Event-specific data (see below) |
| `created_at` | datetime | ISO 8601 timestamp |

---

## Event Catalog

Every entry carries `user_id`, `ip_address` and `created_at` as **columns**, plus
an auto-injected `user_email` in metadata (the *acting* user's address). The
tables below list only the event-specific metadata keys beyond those.

> Entries that record an action taken *on* another user (`user.deleted`,
> `user.role_updated`) identify the target by `target_user_id`. The
> `user_email` on those entries is the **administrator who acted**, not the
> affected user. This is easy to misread during an investigation.

### Authentication

| Event | Trigger | Metadata |
|-------|---------|----------|
| `login.success` | Successful password login | *(none)* |
| `login.failure` | Failed password login | `reason`, plus `email` when no user matched |

`reason` is one of `unknown_tenant`, `unknown_user_or_no_password`,
`wrong_password`, `account_disabled`.

### OAuth

| Event | Trigger | Metadata |
|-------|---------|----------|
| `oauth.login` | Successful local login via OAuth flow | *(none)* |
| `oauth.entra_login` | Successful Entra SSO via OAuth flow | *(none)* |
| `oauth.token_issued` | Authorization code exchanged for tokens | *(none)* |
| `oauth.token_refreshed` | Refresh token used to issue new tokens | *(none)* |

The acting user is on the `user_id` column; these events carry no extra metadata.

### Natural Language Queries

| Event | Trigger | Metadata |
|-------|---------|----------|
| `query.success` | REST `/query/` returned results | `connection_id`, `question` (≤200 chars), `sql_generated` |
| `query.failure` | REST `/query/` failed | `connection_id`, `question` (≤200 chars), `error` |

### MCP SQL Tools

| Event | Trigger | Metadata |
|-------|---------|----------|
| `tool.execute_sql` | SQL executed via MCP tool | `tool`, `connection_id`, `sql_preview` (≤200 chars), `row_count` |
| `tool.execute_sql.rejected` | SQL rejected by the safety validator | `tool`, `connection_id`, `reason` |
| `tool.execute_sql.error` | SQL execution failed | `tool`, `connection_id`, `error` |

Only the *successful* event records the SQL, and only a 200-character preview
(`sql_preview`). Rejected and failed statements are **not** recorded verbatim —
`reason` / `error` describe why.

### Filesystem Tools

All filesystem events share one metadata shape: `tool`, plus an `args` object
holding the call arguments.

| Event | Trigger |
|-------|---------|
| `fs.{tool_name}` | Tool executed successfully |
| `fs.{tool_name}.denied` | Caller's role was below the tool's minimum |
| `fs.{tool_name}.error` | Tool raised — adds an `error` key alongside `args` |

Inside `args`:

- Path arguments (`path`, `source`, `destination`) appear both as supplied and
  resolved, e.g. `path` and `path_resolved`. The resolved form reflects the real
  target after `~` expansion and symlink resolution, and is the one to trust.
- `content` (for `fs_write_file`) is **never** recorded. Only its length is,
  as `"<N chars>"`.
- All other string values are truncated to 200 characters.

Error entries include the attempted path, so a blocked traversal is visible in
the trail.

### Connections

| Event | Trigger | Metadata |
|-------|---------|----------|
| `connection.created` | New database connection added | `connection_id`, `name`, `db_type` |
| `connection.updated` | Connection settings modified | `connection_id`, `fields_changed` (list of field names) |
| `connection.deleted` | Connection soft-deleted | `connection_id` |

`fields_changed` records which fields were supplied, not their values —
connection strings never reach the audit log.

### Tenants and Users

| Event | Trigger | Metadata |
|-------|---------|----------|
| `tenant.created` | New tenant registered | `tenant_id`, `slug` |
| `user.deleted` | User removed from tenant | `target_user_id` |
| `user.role_updated` | User's role changed | `target_user_id`, `new_role` |

### API Keys

| Event | Trigger | Metadata |
|-------|---------|----------|
| `key.created` | New API key generated | `key_prefix`, `key_name` |
| `key.revoked` | API key revoked | `key_prefix` |

---

## Filtering by Event Prefix

The `event_prefix` query parameter accepts a comma-separated list of prefixes. An entry matches if its `event` field starts with any of the prefixes.

| Filter | Matches |
|--------|---------|
| `login` | `login.success`, `login.failure` |
| `oauth` | `oauth.login`, `oauth.entra_login`, `oauth.token_issued`, `oauth.token_refreshed` |
| `query` | `query.success`, `query.failure` |
| `tool` | `tool.execute_sql`, `tool.execute_sql.rejected`, `tool.execute_sql.error` |
| `fs` | All filesystem events |
| `connection` | `connection.created`, `connection.updated`, `connection.deleted` |
| `user` | `user.deleted`, `user.role_updated` |
| `key` | `key.created`, `key.revoked` |
| `query,tool` | All query and MCP tool events |

---

## Admin UI

The **Audit Log** tab in the admin UI provides a filterable, paginated view of all events with:

- **Category filters:** All Events, Queries, MCP Tools, Auth, Connections, Users, API Keys
- **Expandable rows:** Click any row to see full metadata
- **Event badges:** Color-coded by type (success, error, admin action)
- **Metadata summaries:** Key fields like `question`, `sql_generated`, `error`, `email`, `new_role` shown inline
- **Load more:** Pagination with 50 events per page
