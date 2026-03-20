# Tool Role Overrides

MCP Gateway uses a two-level role system for MCP tools: **connection-level defaults** and **per-tool overrides**. This allows admins to fine-tune which roles can access specific tools without changing the connection configuration.

---

## Role Hierarchy

Three roles in ascending order of permission:

```
viewer (0) → analyst (1) → admin (2)
```

A user can access a tool if their role rank is greater than or equal to the tool's effective minimum role. For example, an analyst can use a tool with `min_role: analyst` or `min_role: viewer`, but not `min_role: admin`.

---

## Connection-Level Defaults

Each database connection has a `min_role` field (set when creating or updating the connection):

```bash
curl -X POST http://localhost:8000/connections/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production DB",
    "db_type": "postgres",
    "connection_string": "postgresql://...",
    "min_role": "analyst"
  }'
```

This `min_role` determines:
- Who can **see** the connection in `GET /connections/`
- The **default minimum role** for the connection's generated MCP tools (`get_schema_*`, `execute_sql_*`)
- Who can **see** the tools in `GET /tools/` and in the MCP tool list

Users below the connection's `min_role` cannot see the connection or any of its tools at all.

---

## Tool Defaults

Each tool type has its own default minimum role, which may differ from the connection's `min_role`:

| Tool | Default `min_role` | Notes |
|------|-------------------|-------|
| `list_connections` | `viewer` | Always available to all roles |
| `get_schema_{name}_{id}` | Connection's `min_role` | Inherits from the connection |
| `execute_sql_{name}_{id}` | `analyst` | Higher default because it runs queries |
| `get_current_time` | `viewer` | Utility tool, no data access |
| `fs_read_file` | `analyst` | Filesystem read access |
| `fs_write_file` | `admin` | Filesystem write access |

The effective minimum role for a tool is the **higher** of the connection's `min_role` and the tool's own default. For example, if a connection has `min_role: admin`, then `get_schema` also requires `admin` even though its default is the connection's `min_role`.

---

## Per-Tool Overrides

Admins can override the effective minimum role for any individual tool using `PATCH /tools/{tool_name}`.

### Set an override

```bash
# Restrict execute_sql to admin only
curl -X PATCH "http://localhost:8000/tools/execute_sql_prod-db_abcd1234" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"min_role": "admin"}'
```

### Remove an override

```bash
# Reset to the connection/tool default
curl -X PATCH "http://localhost:8000/tools/execute_sql_prod-db_abcd1234" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"min_role": null}'
```

Overrides are stored in the `tool_role_overrides` database table, scoped per tenant.

---

## How Effective Role Is Computed

When determining whether a user can access a tool, the gateway checks:

1. **Override exists?** Use the override's `min_role`
2. **No override?** Use the tool's default `min_role`
3. Compare the user's role rank against the effective `min_role` rank

```
effective_min_role = override.min_role  if override exists
                   else tool.default_min_role
accessible = user.role_rank >= effective_min_role_rank
```

---

## Practical Examples

### Lock down SQL execution while keeping schema open

Allow analysts to browse schemas but restrict query execution to admins:

```bash
PATCH /tools/execute_sql_prod-db_abcd1234  {"min_role": "admin"}
PATCH /tools/get_schema_prod-db_abcd1234   {"min_role": "analyst"}
```

Result:
- Analysts see the schema tool and can explore table structures
- Only admins can run SQL against the production database

### Open a connection to viewers for schema browsing

A connection with `min_role: analyst` hides everything from viewers. To let viewers browse the schema:

```bash
PATCH /tools/get_schema_staging-db_efgh5678  {"min_role": "viewer"}
```

Result:
- Viewers can see and use the schema tool
- SQL execution still requires `analyst` (the default)

### Restrict filesystem write tools further

Filesystem write tools default to `admin`, but you could also override read tools:

```bash
PATCH /tools/fs_read_file     {"min_role": "admin"}
PATCH /tools/fs_write_file    {"min_role": "admin"}
```

---

## Viewing Tool Roles

### REST API

```bash
curl http://localhost:8000/tools/ \
  -H "Authorization: Bearer $TOKEN"
```

Response:
```json
[
  {
    "tool_name": "execute_sql_prod-db_abcd1234",
    "tool_type": "execute",
    "description": "Execute SQL on Production DB",
    "connection_id": "abcd1234-...",
    "connection_name": "Production DB",
    "default_min_role": "analyst",
    "effective_min_role": "admin",
    "accessible": false
  },
  {
    "tool_name": "get_schema_prod-db_abcd1234",
    "tool_type": "schema",
    "description": "Get schema for Production DB",
    "connection_id": "abcd1234-...",
    "connection_name": "Production DB",
    "default_min_role": "analyst",
    "effective_min_role": "analyst",
    "accessible": true
  }
]
```

Fields:
- `default_min_role` — the tool's built-in default
- `effective_min_role` — the actual role after applying any override
- `accessible` — whether the current user can use this tool

### Admin UI

The **Tools** tab shows all tools grouped by connection:
- **Default Role** column shows the built-in default
- **Override Role** column shows a dropdown (for admins) to select an override. After changing the dropdown, click the **Update** button that appears to save the change. Select "Default" to remove an override.
- **Accessible** column indicates whether the current user can use the tool
- A green success banner confirms when an override is saved
