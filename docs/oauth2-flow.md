# OAuth 2.1 + PKCE Flow

MCP Gateway implements OAuth 2.1 with PKCE (Proof Key for Code Exchange) for browser-based MCP clients like `mcp-remote`. The implementation follows RFC 8414 (discovery), RFC 7591 (dynamic client registration), RFC 6749 (authorization code), and RFC 8252 (native apps / loopback redirect).

All OAuth endpoints are tenant-scoped under `/t/{slug}/oauth/`.

---

## Flow Overview

> **Shortcut:** If the client provides an `?api_key=` query parameter on `GET /t/{slug}/mcp/sse`, the endpoint authenticates immediately and skips the entire OAuth flow below. See [API Keys](api-keys.md) for details.

```
mcp-remote                        MCP Gateway                       Browser
    │                                  │                               │
    │ 1. GET /t/{slug}/mcp/sse         │                               │
    │ ────────────────────────────────► │                               │
    │ ◄──── 401 + WWW-Authenticate     │                               │
    │                                  │                               │
    │ 2. GET /.well-known/oauth-       │                               │
    │    authorization-server/t/{slug} │                               │
    │ ────────────────────────────────► │                               │
    │ ◄──── Discovery JSON             │                               │
    │                                  │                               │
    │ 3. POST /t/{slug}/oauth/register │                               │
    │ ────────────────────────────────► │                               │
    │ ◄──── client_id                  │                               │
    │                                  │                               │
    │ 4. Open browser ──────────────────────────────────────────────── ►│
    │    /t/{slug}/oauth/authorize     │                               │
    │    ?response_type=code           │                               │
    │    &client_id=...                │                               │
    │    &redirect_uri=http://localhost │                               │
    │    &state=...                    │                               │
    │    &code_challenge=...           │        5. Login form           │
    │    &code_challenge_method=S256   │ ◄──────────────────────────── │
    │                                  │        6. POST credentials     │
    │                                  │ ◄──────────────────────────── │
    │                                  │        7. 302 → redirect_uri   │
    │                                  │            ?code=...&state=... │
    │ ◄─── callback on localhost ──────────────────────────────────────│
    │                                  │                               │
    │ 8. POST /t/{slug}/oauth/token    │                               │
    │    grant_type=authorization_code │                               │
    │    code=...                      │                               │
    │    code_verifier=...             │                               │
    │ ────────────────────────────────► │                               │
    │ ◄──── access_token + refresh     │                               │
    │                                  │                               │
    │ 9. GET /t/{slug}/mcp/sse         │                               │
    │    Authorization: Bearer ...     │                               │
    │ ────────────────────────────────► │                               │
    │ ◄──── SSE stream (MCP tools)     │                               │
```

---

## Endpoints

### Discovery

**GET** `/.well-known/oauth-authorization-server/t/{slug}`

Returns OAuth server metadata per RFC 8414.

Response:
```json
{
  "issuer": "https://gateway.example.com/t/my-org",
  "authorization_endpoint": "https://gateway.example.com/t/my-org/oauth/authorize",
  "token_endpoint": "https://gateway.example.com/t/my-org/oauth/token",
  "registration_endpoint": "https://gateway.example.com/t/my-org/oauth/register",
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"],
  "token_endpoint_auth_methods_supported": ["none"]
}
```

### Protected Resource Metadata

**GET** `/.well-known/oauth-protected-resource/t/{slug}/mcp/sse`

Returns metadata per RFC 9728, including a pointer to the authorization server.

### Dynamic Client Registration

**POST** `/t/{slug}/oauth/register`

Clients register themselves before starting the authorization flow. No authentication required.

Request:
```json
{
  "redirect_uris": ["http://localhost:3000/callback"],
  "client_name": "My MCP Client"
}
```

Response:
```json
{
  "client_id": "my-org_a1b2c3d4e5f6",
  "client_name": "My MCP Client",
  "redirect_uris": ["http://localhost:3000/callback"],
  "token_endpoint_auth_method": "none"
}
```

The `client_id` is namespaced to the tenant (`{slug}_{random}`). `client_name` defaults to `"MCP Client"` if omitted.

### Authorization

**GET** `/t/{slug}/oauth/authorize`

| Parameter | Required | Description |
|-----------|----------|-------------|
| `response_type` | Yes | Must be `code` |
| `client_id` | Yes | From registration |
| `redirect_uri` | Yes | Must be loopback (`localhost`, `127.0.0.1`, or `::1`) |
| `state` | Yes | Opaque value for CSRF protection |
| `code_challenge` | Yes | Base64url-encoded SHA-256 of the code verifier |
| `code_challenge_method` | Yes | Must be `S256` |

If the tenant has Entra SSO configured, the user is redirected to Microsoft for login. Otherwise, the gateway shows its own login form.

### Entra SSO Callback

**GET** `/t/{slug}/oauth/entra-callback`

After Microsoft authentication, the gateway:
1. Exchanges the Entra code for a Microsoft access token
2. Fetches the user's profile and group memberships from Microsoft Graph
3. Maps groups to a gateway role (admin > analyst > viewer)
4. JIT-provisions the user if they don't exist
5. Issues an authorization code and redirects back to the client's `redirect_uri`

### Local Login

**POST** `/t/{slug}/oauth/login`

When Entra is not configured, the authorization endpoint renders a login form. The form submits to this endpoint.

| Field | Description |
|-------|-------------|
| `email` | User's email |
| `password` | User's password |
| `state` | The OAuth state from the authorize request |

On success, redirects to the `redirect_uri` with `?code=...&state=...`.

### Token Exchange

**POST** `/t/{slug}/oauth/token`

Content-Type: `application/x-www-form-urlencoded`

#### Authorization code grant

| Parameter | Value |
|-----------|-------|
| `grant_type` | `authorization_code` |
| `code` | Authorization code from callback |
| `code_verifier` | The original PKCE code verifier (plain text) |
| `redirect_uri` | Must match the one used in the authorize request |

#### Refresh token grant

| Parameter | Value |
|-----------|-------|
| `grant_type` | `refresh_token` |
| `refresh_token` | A valid, non-revoked refresh token |

Response (both grants):
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900,
  "refresh_token": "mgw_rt_..."
}
```

---

## PKCE (S256)

PKCE prevents authorization code interception attacks. The flow:

1. Client generates a random `code_verifier` (43-128 characters, URL-safe)
2. Client computes `code_challenge = base64url(sha256(code_verifier))`
3. Client sends `code_challenge` + `code_challenge_method=S256` in the authorize request
4. Gateway stores the challenge with the OAuth state
5. Client sends the original `code_verifier` in the token exchange
6. Gateway verifies: `base64url(sha256(code_verifier)) == stored code_challenge`

Only `S256` is supported. Plain PKCE is not accepted.

---

## Token Lifecycle

| Token | Lifetime | Storage |
|-------|----------|---------|
| Authorization code | 5 minutes | Database (single-use, deleted after exchange) |
| OAuth state | 10 minutes | Database (deleted after use or on expiry) |
| Access token (JWT) | 15 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`) | Not stored — stateless, validated by signature |
| Refresh token | 30 days (configurable via `REFRESH_TOKEN_EXPIRE_DAYS`) | Database (SHA-256 hash only) |

### Refresh token rotation

Each refresh token is **single-use**. When a client refreshes:

1. The old refresh token is revoked
2. **For Entra users**: the gateway re-queries Azure AD for current group memberships and updates the user's role if it changed (see [Entra role sync on refresh](#entra-role-sync-on-refresh) below)
3. A new access token + refresh token pair is issued
4. The new refresh token is stored (hashed)

If the same refresh token is used twice (replay attack), the second attempt fails with 401.

---

## Redirect URI Restrictions

Only loopback redirect URIs are accepted, per RFC 8252:

- `http://localhost` (any port)
- `http://127.0.0.1` (any port)
- `http://[::1]` (any port)

HTTPS redirect URIs and non-loopback hosts are rejected. This ensures tokens are only delivered to locally-running clients, not remote servers.

---

## Entra Role Sync on Refresh

When an Entra SSO user refreshes their token, the gateway re-resolves their role from Azure AD in real time using the **client credentials flow** (app-only permissions). This ensures that group membership changes in Azure AD are reflected without requiring a full re-login.

### How it works

1. User presents a refresh token with `grant_type=refresh_token`
2. Gateway detects the user is an Entra user (`auth_provider=entra`)
3. Gateway acquires an app-only token via client credentials grant
4. Gateway queries `GET /users/{oid}/transitiveMemberOf` on Microsoft Graph
5. Gateway maps group memberships to a role using the tenant's Entra config
6. If the role changed, the user record is updated in the database
7. The new access token is issued with the updated role

### Edge cases

| Scenario | Behaviour |
|----------|-----------|
| User promoted (e.g. analyst → admin) | Role updated in DB, new token reflects new role |
| User removed from all groups | User deactivated in DB; refresh rejected with 403; re-login also denied until re-added to a group |
| Entra config deleted for the tenant | Refresh rejected with 403; user must re-authenticate |
| Azure AD / Graph API unreachable | Warning logged; refresh proceeds with existing DB role |

**Known limitation**: If Azure AD is unreachable during a token refresh, a user who was removed from all groups will retain their old role until Graph API recovers. This trade-off prioritises availability over immediate revocation.

### MCP tool calls

In addition to role sync on refresh, the gateway re-reads the user's role from the database on **every MCP tool call**. This means that if a role is updated (either via Entra sync, admin UI, or API), the change takes effect on the next tool invocation — even within an active SSE session.

---

## Entra SSO Integration

When a tenant has Entra ID configured (via `POST /auth/entra/config`), the OAuth authorize endpoint automatically redirects to Microsoft instead of showing the local login form. The flow is:

1. User hits `/t/{slug}/oauth/authorize`
2. Gateway detects Entra config exists for this tenant
3. Gateway redirects to `login.microsoftonline.com/{entra_tenant_id}/oauth2/v2.0/authorize`
4. User authenticates with Microsoft
5. Microsoft redirects back to `/t/{slug}/oauth/entra-callback`
6. Gateway fetches profile + groups, maps to role, provisions user
7. Gateway issues its own authorization code and redirects to the MCP client

The MCP client only ever sees the gateway's OAuth flow. Microsoft's tokens stay server-side.

### Required Azure AD App Registration

The Entra app registration must have:

- **Redirect URIs** (Web platform):
  - `http://<gateway-url>/auth/entra/callback` (admin UI SSO)
  - `http://<gateway-url>/t/<slug>/oauth/entra-callback` (MCP OAuth flow)
- **API permissions** (Microsoft Graph):
  - **Delegated**: `openid`, `profile`, `email`, `User.Read`, `GroupMember.Read.All`
  - **Application**: `Directory.Read.All` (used for role sync during token refresh via client credentials flow)
- **Admin consent** granted for the delegated `GroupMember.Read.All` and the application `Directory.Read.All`

The delegated scopes are used during interactive login. The application permission is a **separate grant** — it allows the gateway to query a user's group memberships server-to-server during token refresh, without a user-delegated token.

> **Note:** `Directory.Read.All` is required (not `GroupMember.Read.All`) because the gateway uses `GET /users/{oid}/transitiveMemberOf` with an app-only token, which requires directory-level read access.

To add the Application permission in Azure portal:
1. Go to **App registrations** → your app → **API permissions**
2. Click **Add a permission** → **Microsoft Graph** → **Application permissions**
3. Search for `Directory.Read.All` and select it
4. Click **Grant admin consent** for the new permission
