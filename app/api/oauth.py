"""OAuth 2.0 endpoints for MCP browser-based authentication.

All routes are mounted under /t/{slug}/ in main.py.
"""
from __future__ import annotations

import base64
import hashlib
import html
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from app.core.limiter import limiter
from app.database import get_db
from app.models import (
    AuthProvider,
    OAuthAuthorizationCode,
    OAuthRefreshToken,
    OAuthState,
    Tenant,
    TenantEntraConfig,
    User,
)
from app.services import entra as entra_service
from app.services.audit import write_audit_log

logger = logging.getLogger(__name__)

router = APIRouter()
well_known_router = APIRouter()

# TTL values come from app/config.py (oauth_code_ttl_minutes / oauth_state_ttl_minutes)
# so operators can tune them without code changes.


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_loopback_uri(uri: str) -> bool:
    """Accept only http://localhost[/...] and http://127.0.0.1[/...].

    Uses urlparse so that http://localhost.evil.com is correctly rejected
    (startswith("http://localhost") would have passed it).
    """
    try:
        parsed = urlparse(uri)
        return parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    except Exception:
        return False


def _get_tenant_or_404(slug: str, db: Session) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{slug}' not found")
    return tenant


def _get_valid_state(state: str, db: Session) -> OAuthState:
    now = datetime.now(tz=timezone.utc)
    row = (
        db.query(OAuthState)
        .filter(OAuthState.state == state, OAuthState.expires_at > now)
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth2 state")
    return row


def _get_entra_config_or_400(
    tenant: Tenant, db: Session
) -> TenantEntraConfig:
    config = (
        db.query(TenantEntraConfig)
        .filter(TenantEntraConfig.tenant_id == tenant.id)
        .first()
    )
    if not config:
        raise HTTPException(status_code=400, detail="Entra ID config missing")
    return config


def _issue_code_and_redirect(
    user: User, state_row: OAuthState, db: Session
) -> RedirectResponse:
    code = secrets.token_urlsafe(32)
    db.add(OAuthAuthorizationCode(
        code=code,
        tenant_id=user.tenant_id,
        user_id=user.id,
        redirect_uri=state_row.redirect_uri,
        code_challenge=state_row.code_challenge,
        code_challenge_method=state_row.code_challenge_method,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=get_settings().oauth_code_ttl_minutes),
    ))
    db.delete(state_row)
    db.commit()

    redirect = f"{state_row.redirect_uri}?code={code}&state={state_row.state}"
    return RedirectResponse(redirect, status_code=302)


def _issue_token_response(user: User, db: Session) -> dict:
    settings = get_settings()
    access_token = create_access_token(user.id, user.tenant_id, user.role.value, email=user.email)
    raw_refresh, hashed_refresh = create_refresh_token()
    db.add(OAuthRefreshToken(
        tenant_id=user.tenant_id,
        user_id=user.id,
        hashed_token=hashed_refresh,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    ))
    db.commit()
    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


async def _sync_entra_role(user: User, db: Session) -> None:
    """Re-resolve an Entra user's role from Azure AD during token refresh.

    Uses client credentials (app-only) to query Microsoft Graph for current
    group memberships.  If the Entra config has been removed or Azure AD is
    unreachable, the behaviour depends on the failure mode:

    * **Config missing** — the user's refresh is rejected (raises 403).
    * **Graph unreachable** (``RuntimeError``) — logged as a warning; existing
      DB role is kept.  A user removed from all groups will retain their role
      until Graph recovers.
    * **Anything else** — propagates.  An unexpected exception is a bug, and
      swallowing it would silently extend the caller's current role.

    Called before the refresh token is revoked, so raising here leaves the
    caller's existing token usable.
    """
    config = (
        db.query(TenantEntraConfig)
        .filter(TenantEntraConfig.tenant_id == user.tenant_id)
        .first()
    )
    if not config:
        logger.warning(
            "Entra config missing for tenant %s during refresh for user %s — revoking",
            user.tenant_id, user.id,
        )
        raise HTTPException(
            status_code=403,
            detail="Entra ID configuration removed — please re-authenticate",
        )

    try:
        group_ids = await entra_service.get_user_group_ids_by_oid(
            config, user.entra_oid,
        )
    except RuntimeError:
        # entra_service normalises every Graph/transport failure to
        # RuntimeError.  Anything else is a bug and must not be swallowed
        # into a silent role extension.
        logger.warning(
            "Could not reach Azure AD to re-resolve role for user %s; "
            "proceeding with existing role (%s)",
            user.id, user.role.value,
            exc_info=True,
        )
        return

    new_role = entra_service.resolve_role(group_ids, config)
    if new_role is None:
        logger.warning(
            "Entra user %s no longer in any role group — deactivating and revoking refresh token",
            user.id,
        )
        user.is_active = False
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="User is no longer a member of any authorised group",
        )

    if new_role != user.role:
        logger.info(
            "Entra role changed for user %s: %s -> %s",
            user.id, user.role.value, new_role.value,
        )
        user.role = new_role
        db.commit()
        db.refresh(user)


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    digest = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return digest == code_challenge


def _login_form_html(slug: str, state: str, error: str = "") -> str:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html>
<head>
  <title>MCP Gateway Login</title>
  <style>
    body {{ font-family: system-ui; max-width: 400px; margin: 80px auto; padding: 0 20px; }}
    input {{ width: 100%; padding: 10px; margin: 8px 0; border: 1px solid #ccc;
             border-radius: 6px; box-sizing: border-box; font-size: 16px; }}
    button {{ width: 100%; padding: 12px; background: #2563eb; color: white;
              border: none; border-radius: 6px; font-size: 16px; cursor: pointer; }}
    button:hover {{ background: #1d4ed8; }}
    .error {{ color: #dc2626; font-size: 14px; }}
    h2 {{ margin-bottom: 24px; }}
  </style>
</head>
<body>
  <h2>Sign in to MCP Gateway</h2>
  {error_html}
  <form method="post" action="/t/{html.escape(slug)}/oauth/login">
    <input type="hidden" name="state" value="{html.escape(state)}">
    <input type="email" name="email" placeholder="Email" required autofocus>
    <input type="password" name="password" placeholder="Password" required>
    <button type="submit">Sign in</button>
  </form>
</body>
</html>"""


# ── Discovery ─────────────────────────────────────────────────────────────────


@router.get("/.well-known/oauth-authorization-server")
def oauth_discovery(slug: str, request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    prefix = f"{base}/t/{slug}"
    return {
        "issuer": prefix,
        "authorization_endpoint": f"{prefix}/oauth/authorize",
        "token_endpoint": f"{prefix}/oauth/token",
        "registration_endpoint": f"{prefix}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
    }


# ── Protected Resource Metadata (RFC 9728) ────────────────────────────────────


@router.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata(slug: str, request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {
        "resource": f"{base}/t/{slug}/mcp/sse",
        "authorization_servers": [f"{base}/t/{slug}"],
    }


# ── Dynamic Client Registration (RFC 7591) ───────────────────────────────────


@router.post("/oauth/register")
@limiter.limit("10/minute")
async def oauth_register(slug: str, request: Request) -> dict:
    body = await request.json()
    redirect_uris = body.get("redirect_uris", [])
    client_name = body.get("client_name", "mcp-client")
    now = int(datetime.now(tz=timezone.utc).timestamp())
    return {
        "client_id": f"{client_name}-{slug}",
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "client_id_issued_at": now,
    }


# ── Authorization ─────────────────────────────────────────────────────────────


@router.get("/oauth/authorize", response_model=None)
@limiter.limit("30/minute")
def oauth_authorize(
    slug: str,
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    db: Session = Depends(get_db),
) -> HTMLResponse | RedirectResponse:
    tenant = _get_tenant_or_404(slug, db)

    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only response_type=code is supported")

    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="Only S256 code challenge method is supported")

    if not _is_loopback_uri(redirect_uri):
        raise HTTPException(status_code=400, detail="redirect_uri must be a localhost URI")

    now = datetime.now(tz=timezone.utc)
    db.query(OAuthState).filter(OAuthState.expires_at < now).delete()

    existing = db.query(OAuthState).filter(OAuthState.state == state).first()
    if existing:
        existing.tenant_slug = slug
        existing.expires_at = now + timedelta(minutes=get_settings().oauth_state_ttl_minutes)
        existing.code_challenge = code_challenge
        existing.code_challenge_method = code_challenge_method
        existing.redirect_uri = redirect_uri
        existing.client_id = client_id
    else:
        db.add(OAuthState(
            state=state,
            tenant_slug=slug,
            expires_at=now + timedelta(minutes=get_settings().oauth_state_ttl_minutes),
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            redirect_uri=redirect_uri,
            client_id=client_id,
        ))
    db.commit()

    entra_config = (
        db.query(TenantEntraConfig)
        .filter(TenantEntraConfig.tenant_id == tenant.id)
        .first()
    )

    if entra_config:
        entra_url = entra_service.build_authorization_url(
            entra_config, state, tenant_slug=slug,
        )
        return RedirectResponse(entra_url, status_code=302)

    return HTMLResponse(_login_form_html(slug, state))


# ── Local Login ───────────────────────────────────────────────────────────────


@router.post("/oauth/login", response_model=None)
@limiter.limit("10/minute")
async def oauth_login_submit(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    form = await request.form()
    email = str(form.get("email", ""))
    password = str(form.get("password", ""))
    state = str(form.get("state", ""))

    state_row = _get_valid_state(state, db)
    tenant = _get_tenant_or_404(slug, db)
    user = (
        db.query(User)
        .filter(User.email == email, User.tenant_id == tenant.id)
        .first()
    )

    if not user or not user.hashed_password or not verify_password(password, user.hashed_password):
        return HTMLResponse(_login_form_html(slug, state, error="Invalid email or password"))

    if not user.is_active:
        return HTMLResponse(_login_form_html(slug, state, error="Account disabled"))

    ip = request.client.host if request.client else None
    write_audit_log(db, "oauth.login", user=user, ip=ip)
    return _issue_code_and_redirect(user, state_row, db)


# ── Entra SSO Callback ───────────────────────────────────────────────────────


@router.get("/oauth/entra-callback")
@limiter.limit("20/minute")
async def oauth_entra_callback(
    request: Request,
    slug: str,
    code: str,
    state: str,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    state_row = _get_valid_state(state, db)
    tenant = _get_tenant_or_404(slug, db)
    config = _get_entra_config_or_400(tenant, db)

    token_response = await entra_service.exchange_code_for_token(
        config, code, tenant_slug=slug,
    )
    access_token = token_response.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access token in Entra response")

    profile = await entra_service.get_entra_profile(access_token)
    group_ids = await entra_service.get_user_group_ids(access_token)

    entra_oid = profile.get("id")
    if not entra_oid:
        logger.error("Entra profile missing 'id' field for tenant %s", slug)
        raise HTTPException(status_code=502, detail="Entra profile missing user identifier")

    email = profile.get("mail") or profile.get("userPrincipalName", "")
    role = entra_service.resolve_role(group_ids, config)
    if not role:
        logger.warning("Entra login denied — user %s not in any role group", entra_oid)
        existing_user = (
            db.query(User)
            .filter(User.entra_oid == entra_oid, User.tenant_id == tenant.id)
            .first()
        )
        if existing_user and existing_user.is_active:
            existing_user.is_active = False
            logger.info("Deactivated user %s — no longer in any role group", existing_user.id)
        db.delete(state_row)
        db.commit()
        error_params = urlencode({
            "error": "access_denied",
            "error_description": "Not in any authorised group",
            "state": state_row.state,
        })
        return RedirectResponse(
            f"{state_row.redirect_uri}?{error_params}", status_code=302
        )

    user = entra_service.jit_provision_user(db, tenant.id, entra_oid, email, role)
    write_audit_log(db, "oauth.entra_login", user=user)
    return _issue_code_and_redirect(user, state_row, db)


# ── Token Exchange ────────────────────────────────────────────────────────────


@router.post("/oauth/token")
@limiter.limit("30/minute")
async def oauth_token(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    form = await request.form()
    grant_type = form.get("grant_type")

    if grant_type == "authorization_code":
        code_val = str(form.get("code", ""))
        code_verifier = str(form.get("code_verifier", ""))
        redirect_uri = str(form.get("redirect_uri", ""))

        now = datetime.now(tz=timezone.utc)
        auth_code = (
            db.query(OAuthAuthorizationCode)
            .filter(
                OAuthAuthorizationCode.code == code_val,
                OAuthAuthorizationCode.used.is_(False),
                OAuthAuthorizationCode.expires_at > now,
            )
            .first()
        )
        if not auth_code:
            raise HTTPException(status_code=400, detail="Invalid or expired authorization code")

        if not _verify_pkce(code_verifier, auth_code.code_challenge):
            raise HTTPException(status_code=400, detail="PKCE verification failed")

        if auth_code.redirect_uri != redirect_uri:
            raise HTTPException(status_code=400, detail="redirect_uri mismatch")

        # Delete the code immediately (single-use guarantee; avoids table bloat).
        user_id = auth_code.user_id
        db.delete(auth_code)
        db.commit()

        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            # The code was valid but the user is gone — server-side invariant
            # violation, not a client error.
            logger.error("Valid auth code redeemed but user %s not found/inactive", user_id)
            raise HTTPException(status_code=500, detail="Authentication error")

        write_audit_log(db, "oauth.token_issued", user=user)
        return _issue_token_response(user, db)

    elif grant_type == "refresh_token":
        raw_refresh = str(form.get("refresh_token", ""))
        hashed = hashlib.sha256(raw_refresh.encode()).hexdigest()
        now = datetime.now(tz=timezone.utc)
        token_row = (
            db.query(OAuthRefreshToken)
            .filter(
                OAuthRefreshToken.hashed_token == hashed,
                OAuthRefreshToken.revoked_at.is_(None),
                OAuthRefreshToken.expires_at > now,
            )
            .first()
        )
        if not token_row:
            raise HTTPException(status_code=400, detail="Invalid or expired refresh token")

        user = db.query(User).filter(User.id == token_row.user_id).first()
        if not user or not user.is_active:
            logger.error("Valid refresh token redeemed but user %s not found/inactive", token_row.user_id)
            raise HTTPException(status_code=500, detail="Authentication error")

        # Re-resolve the role *before* revoking.  A transient Entra failure
        # that raises here must not consume the caller's only refresh token —
        # otherwise an admin misconfiguration logs every user out permanently.
        if user.auth_provider == AuthProvider.entra and user.entra_oid:
            await _sync_entra_role(user, db)

        token_row.revoked_at = now
        db.commit()

        write_audit_log(db, "oauth.token_refreshed", user=user)
        return _issue_token_response(user, db)

    raise HTTPException(status_code=400, detail="Unsupported grant_type")


# ── Root-level well-known routes (RFC 8414 §3.1 compliant paths) ─────────────
# RFC 8414 constructs the metadata URL by inserting /.well-known/... between
# the host and the path component of the issuer.  For issuer
# http://host/t/demo-corp the URL is:
#   http://host/.well-known/oauth-authorization-server/t/demo-corp
# These routes are mounted at root in main.py via well_known_router.


@well_known_router.get("/.well-known/oauth-authorization-server/t/{slug}")
def root_oauth_discovery(slug: str, request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    prefix = f"{base}/t/{slug}"
    return {
        "issuer": prefix,
        "authorization_endpoint": f"{prefix}/oauth/authorize",
        "token_endpoint": f"{prefix}/oauth/token",
        "registration_endpoint": f"{prefix}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
    }


@well_known_router.get("/.well-known/oauth-protected-resource/t/{slug}/mcp/sse")
def root_protected_resource_metadata(slug: str, request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {
        "resource": f"{base}/t/{slug}/mcp/sse",
        "authorization_servers": [f"{base}/t/{slug}"],
    }
