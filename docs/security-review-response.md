# Response to MCP Marketplace Security Review

**Project:** MCP Gateway (`io.github.PanosSalt/MCP-Gateway`)
**Review findings:** 6 Low, 2 Info
**Date:** 2026-09-19

Thank you for the review. Every finding was reproduced against source before
being actioned. Four describe controls that were already present — we suspect
the review ran against a partial read of `app/api/oauth.py`, which is 554 lines
and was likely truncated. Evidence is cited below so each can be verified
independently.

We also disclose two issues **not** in the report that our own audit found
while investigating, including one cross-role information disclosure.

## Summary

| # | Finding | Verdict |
|---|---------|---------|
| 1 | Incomplete code in oauth.py | Not reproducible |
| 2 | Broad exception handling in `_sync_entra_role` | **Fixed** |
| 3 | No timeout on LLM SQL generation | Already implemented |
| 4 | No validation of `FILESYSTEM_ALLOWED_DIRS` at startup | **Fixed** |
| 5 | SQL validation via sqlglot may be incomplete | Already implemented; coverage extended |
| 6 | CORS misconfiguration not surfaced | Already implemented; logging added |
| 7 | Missing rate limit on token refresh | Already implemented |
| 8 | Filesystem tools lack per-operation audit granularity | Already implemented; hardened further |
| A | **`GET /tools/` cross-role metadata disclosure** | **Fixed** (self-reported) |
| B | **Unlimited `/oauth/register` and `/oauth/entra-callback`** | **Fixed** (self-reported) |

---

## Finding 1 — Incomplete code in oauth.py

**Not reproducible.** `app/api/oauth.py` is complete at 554 lines, ending with
`root_protected_resource_metadata`. `_login_form_html` is fully defined at
lines 204-231 and escapes all three interpolated values (`error`, `slug`,
`state`) via `html.escape`, so there is no injection path through the login
form.

```
$ wc -l app/api/oauth.py
554 app/api/oauth.py
```

The token endpoint and refresh handling the finding asks about are covered
under findings 2 and 7.

## Finding 2 — Broad exception handling — **Fixed**

Accepted. `_sync_entra_role` caught bare `Exception`, so a programming error
(e.g. `AttributeError`) would be logged as "Azure AD unreachable" and the
user's existing role silently retained.

Narrowed to `RuntimeError`, which is what `app/services/entra.py` normalises
every Graph and transport failure into (entra.py:253-260). Unexpected
exceptions now propagate rather than becoming a silent role extension.

We also fixed an adjacent bug found while making this change: the refresh
token was revoked and committed *before* the role sync ran, so a transient
"Entra config missing" error permanently logged the user out. Revocation now
happens after the sync succeeds.

The finding also suggested retry with backoff. We deliberately did not add it:
the fail-open path is intentional and documented, and retrying inside a token
refresh would extend request latency under exactly the conditions where Graph
is already degraded.

## Finding 3 — No timeout on LLM calls — Already implemented

The Anthropic client has carried a 30-second timeout since before this review:

```python
# app/services/llm.py:77-80
_client = anthropic.AsyncAnthropic(
    api_key=api_key,
    timeout=httpx.Timeout(30.0),
)
```

The scalar applies to connect, read, write and pool. Both `generate_sql` and
`summarize_results` route through `_create_message`, which uses this client,
so neither can hang indefinitely. Timeouts surface as `APITimeoutError`, a
subclass of `APIConnectionError`, mapped to a `RuntimeError` at llm.py:100.

## Finding 4 — No validation of `FILESYSTEM_ALLOWED_DIRS` — **Fixed**

Accepted. Three changes:

- `app/config.py` now rejects at startup any entry that is not absolute or
  that contains a `..` segment. The app refuses to boot rather than starting
  with a misleading sandbox.
- Startup now logs every configured directory, warning individually for
  entries that do not exist or are not directories. Previously these were
  dropped silently, making a typo look like a permission error to the caller.
- The resolved list is cached (`lru_cache`), removing a `stat` per entry on
  every tool listing and every path validation.

On the traversal point specifically: runtime traversal was already prevented.
`_validate_path` resolves through `os.path.realpath` and requires
`real == allowed or real.startswith(allowed + os.sep)` — note the separator,
which correctly rejects a sibling like `/data-evil` against an allowed
`/data`. The new config check is defense-in-depth.

## Finding 5 — SQL validation may be incomplete — Already implemented

The validator was already two-layer and already tested. `assert_safe_select`
(llm.py:118-152) requires every top-level statement to be a `Select` — which
is what blocks `SELECT 1; DROP TABLE x` — and then walks each statement with
`find()` to catch forbidden nodes nested in CTEs or subqueries.

14 tests already covered INSERT, UPDATE, DROP, multi-statement, CTE+DELETE,
CTE+INSERT and the postgres/mysql dialects. `app/tools/sql.py` calls the same
function, so the MCP tool path and the natural-language path share one
validator and one test suite.

We accepted the spirit of the finding and closed the genuine gaps: `CREATE`,
`ALTER TABLE` and `TRUNCATE` were declared forbidden but never exercised;
`Command` nodes (`PRAGMA`, `ATTACH`, `EXEC`) were untested; and the `sqlite`
and `mssql` dialects and the parse-failure path had no coverage. All now
tested.

## Finding 6 — CORS configuration — Already implemented

Wildcards and non-absolute URLs were already rejected:

```python
# app/main.py:282-284
parsed = urlparse(o)
if not parsed.scheme or not parsed.netloc:
    raise ValueError(f"Invalid CORS origin: {o!r} — must be an absolute URL")
```

A `*` is skipped with a warning (main.py:276-281). The finding's
recommendation to "reject invalid origin URLs early" was therefore already
satisfied — a missing scheme raises at import time, not silently.

We agreed with the observability half and added it: the effective origin list
is now logged at INFO on startup. We also fixed a real gap the finding
gestured at — an origin with a trailing slash (`https://x.com/`) passed
`urlparse` validation but could never match a browser `Origin` header, which
is exactly the silent-failure mode described. Such origins are now normalised
with a warning.

## Finding 7 — Missing rate limit on token refresh — Already implemented

`POST /t/{slug}/oauth/token` has been rate limited at 30/minute, and the
decorator covers both grant types — `authorization_code` and `refresh_token`
are branches inside one handler:

```python
# app/api/oauth.py:443-444
@router.post("/oauth/token")
@limiter.limit("30/minute")
async def oauth_token(...):
```

This is also documented in the README's rate-limit table. Note additionally
that refresh tokens are single-use and rotated on every redemption
(oauth.py:508), so a brute-force attempt against a refresh token has no
reusable target.

That said, the finding pointed at a real weakness in the surrounding area —
see disclosure B.

## Finding 8 — Filesystem audit granularity — Already implemented, hardened

The file path was already recorded. `handle` logged all arguments, including
`path`, on every filesystem call (filesystem.py:290-293), so
`GET /audit-logs/?event=fs.` already showed which file was touched.

The underlying concern was sound, though, and we found the audit trail weaker
than it looked in three specific ways, now fixed:

- **Error entries recorded no path at all** — only `{"tool", "error"}`. A
  *blocked* traversal attempt, the most security-relevant event these tools
  produce, did not say which path was attempted. It now does.
- **The raw requested path was logged, not the resolved one.** The trail now
  carries `path_resolved` so it reflects the real target after symlink
  resolution.
- **`fs_write_file` was writing up to 200 characters of file content into the
  audit log.** This is the inverse of the finding's concern — the log was
  recording too much, turning the audit table into a partial copy of sandbox
  contents. Content is now redacted to a length only.

We also added a `fs.{tool}.denied` event so refused calls are auditable, began
recording the client IP on tool events (previously always NULL), and added
`tests/test_filesystem_tools.py` — these 8 tools previously had no test
coverage at all.

---

## Self-reported: not in the review

### A. `GET /tools/` disclosed connections across role boundaries

`SqlToolProvider.get_tool_defaults` built its list from the *unfiltered*
connection query while `get_tools` correctly used the role-filtered one. Since
`GET /tools/` is available to any authenticated user, a **viewer** received the
name, id, database type and operator-written description of every active
connection in the tenant — including admin-only ones — flagged
`accessible: false`.

Scope: tenant-scoped metadata only. No credentials, connection strings or row
data were exposed, and the MCP tool list itself was correctly filtered, so this
never granted access — only knowledge of existence.

Fixed: administrators still receive the full list, which they need to configure
per-tool role overrides, and all other roles receive the filtered list.
Regression tests added in `tests/test_tools_api.py`.

### B. Unlimited endpoints, and rate limits that do not hold across workers

- `POST /t/{slug}/oauth/register` (RFC 7591 dynamic client registration) and
  `GET /t/{slug}/oauth/entra-callback` had **no rate limit**. Registration is
  unauthenticated. Both are now limited (10/min and 20/min).
- The limiter had **no storage backend**, so limits were per-process. Under
  multiple workers every documented limit was effectively multiplied by the
  worker count. An optional `REDIS_URL` now provides shared enforcement, and
  the app warns at startup when running multi-worker without it.
- `get_remote_address` read `request.client.host` with no `X-Forwarded-For`
  handling, so behind a reverse proxy every client shared a single bucket. Now
  configurable via `TRUST_PROXY_HEADERS`, **off by default** — trusting the
  header unconditionally would let any client spoof its own bucket, which is
  worse than the original problem.

---

## Verification

```bash
pip install -r requirements-dev.txt
python -m pytest          # 231 tests, no external services required
python -m ruff check app/ tests/
python -m mypy app/
```
