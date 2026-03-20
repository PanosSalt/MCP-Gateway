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
| `user_email` | string | Email of the acting user (extracted from metadata) |
| `event` | string | Event identifier (e.g. `login.success`, `tool.execute_sql`) |
| `ip_address` | string | Client IP address |
| `metadata` | object | Event-specific data (see below) |
| `created_at` | datetime | ISO 8601 timestamp |

---

## Event Catalog

### Authentication

| Event | Trigger | Metadata |
|-------|---------|----------|
| `login.success` | Successful password login | `email`, `tenant_slug` |
| `login.failure` | Failed password login | `email`, `reason` |

### OAuth

| Event | Trigger | Metadata |
|-------|---------|----------|
| `oauth.login` | Successful local login via OAuth flow | `email` |
| `oauth.entra_login` | Successful Entra SSO via OAuth flow | `email`, `entra_oid` |
| `oauth.token_issued` | Authorization code exchanged for tokens | `user_id` |
| `oauth.token_refreshed` | Refresh token used to issue new tokens | `user_id` |

### Natural Language Queries

| Event | Trigger | Metadata |
|-------|---------|----------|
| `query.success` | REST `/query/` endpoint returned results | `connection_id`, `question`, `sql_generated` |
| `query.failure` | REST `/query/` endpoint failed | `connection_id`, `question`, `error` |

### MCP SQL Tools

| Event | Trigger | Metadata |
|-------|---------|----------|
| `tool.execute_sql` | SQL executed via MCP tool | `connection_id`, `sql` |
| `tool.execute_sql.rejected` | SQL rejected (non-SELECT, role check) | `connection_id`, `sql`, `reason` |
| `tool.execute_sql.error` | SQL execution failed | `connection_id`, `sql`, `error` |

### Filesystem Tools

| Event | Trigger | Metadata |
|-------|---------|----------|
| `fs.fs_read_file` | File read via MCP tool | `path` |
| `fs.fs_write_file` | File written via MCP tool | `path` |
| `fs.fs_list_directory` | Directory listed | `path` |
| `fs.fs_directory_tree` | Directory tree generated | `path` |
| `fs.fs_search_files` | File search executed | `path`, `pattern` |
| `fs.fs_get_file_info` | File info retrieved | `path` |
| `fs.fs_create_directory` | Directory created | `path` |
| `fs.fs_move_file` | File moved | `source`, `destination` |
| `fs.{tool_name}.error` | Any filesystem tool error | `path`, `error` |

### Connections

| Event | Trigger | Metadata |
|-------|---------|----------|
| `connection.created` | New database connection added | `name`, `db_type` |
| `connection.updated` | Connection settings modified | `connection_id`, changed fields |
| `connection.deleted` | Connection soft-deleted | `connection_id`, `name` |

### Tenants and Users

| Event | Trigger | Metadata |
|-------|---------|----------|
| `tenant.created` | New tenant registered | `slug`, `name` |
| `user.deleted` | User removed from tenant | `email` |
| `user.role_updated` | User's role changed | `email`, `new_role` |

### API Keys

| Event | Trigger | Metadata |
|-------|---------|----------|
| `key.created` | New API key generated | `name`, `prefix` |
| `key.revoked` | API key revoked | `name`, `prefix` |

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
