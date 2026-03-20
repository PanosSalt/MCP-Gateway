from __future__ import annotations

import html
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import create_access_token
from app.core.dependencies import require_admin
from app.core.limiter import limiter
from app.core.security import encrypt
from app.database import get_db
from app.models import OAuthState, Tenant, TenantEntraConfig, User
from app.schemas import EntraConfigCreate, EntraConfigOut
from app.services import entra as entra_service

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Short-lived SSO code store ────────────────────────────────────────────────
# Maps opaque code -> (gateway_jwt, expires_at).  Single-use; pruned on write.
# In-memory is fine for the admin SSO popup flow: codes are exchanged within
# seconds and a restart simply requires the user to re-authenticate.
_SSO_CODE_TTL_SECONDS = 120
_pending_sso_codes: dict[str, tuple[str, datetime]] = {}
_pending_sso_codes_lock = threading.Lock()


def _issue_sso_code(gateway_token: str) -> str:
    code = secrets.token_urlsafe(32)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=_SSO_CODE_TTL_SECONDS)
    now = datetime.now(tz=timezone.utc)
    with _pending_sso_codes_lock:
        expired = [k for k, (_, exp) in _pending_sso_codes.items() if exp < now]
        for k in expired:
            del _pending_sso_codes[k]
        _pending_sso_codes[code] = (gateway_token, expires_at)
    return code



@router.post("/config", response_model=EntraConfigOut)
def create_entra_config(
    payload: EntraConfigCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TenantEntraConfig:
    existing = (
        db.query(TenantEntraConfig)
        .filter(
            TenantEntraConfig.tenant_id == current_user.tenant_id
        )
        .first()
    )
    if existing:
        existing.entra_tenant_id = payload.entra_tenant_id
        existing.client_id = payload.client_id
        # Only rotate the secret when a new value is explicitly supplied.
        # An empty/omitted secret means "keep the current encrypted value".
        if payload.client_secret:
            existing.encrypted_client_secret = encrypt(payload.client_secret)
        existing.admin_group_id = payload.admin_group_id
        existing.analyst_group_id = payload.analyst_group_id
        existing.viewer_group_id = payload.viewer_group_id
        db.commit()
        db.refresh(existing)
        return existing

    if not payload.client_secret:
        raise HTTPException(
            status_code=422,
            detail="client_secret is required when creating a new SSO configuration",
        )

    config = TenantEntraConfig(
        tenant_id=current_user.tenant_id,
        entra_tenant_id=payload.entra_tenant_id,
        client_id=payload.client_id,
        encrypted_client_secret=encrypt(payload.client_secret),
        admin_group_id=payload.admin_group_id,
        analyst_group_id=payload.analyst_group_id,
        viewer_group_id=payload.viewer_group_id,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.get("/config", response_model=EntraConfigOut)
def get_entra_config(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TenantEntraConfig:
    config = (
        db.query(TenantEntraConfig)
        .filter(
            TenantEntraConfig.tenant_id == current_user.tenant_id
        )
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=404, detail="No Entra ID config found"
        )
    return config


@router.delete("/config")
def delete_entra_config(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    config = (
        db.query(TenantEntraConfig)
        .filter(
            TenantEntraConfig.tenant_id == current_user.tenant_id
        )
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=404, detail="No Entra ID config found"
        )
    db.delete(config)
    db.commit()
    return {"detail": "Entra ID configuration removed"}


@router.get("/login", response_class=RedirectResponse)
@limiter.limit("20/minute")
def entra_login(
    request: Request,
    tenant_slug: str = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    tenant = (
        db.query(Tenant)
        .filter(Tenant.slug == tenant_slug)
        .first()
    )
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_slug}' not found",
        )
    config = (
        db.query(TenantEntraConfig)
        .filter(TenantEntraConfig.tenant_id == tenant.id)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=400,
            detail="Tenant has not configured Entra ID SSO",
        )

    now = datetime.now(tz=timezone.utc)

    # Cleanup expired states on each write (no background task needed)
    db.query(OAuthState).filter(OAuthState.expires_at < now).delete()

    state = secrets.token_urlsafe(32)
    nonce = request.query_params.get("nonce", "")
    expires_at = now + timedelta(minutes=get_settings().oauth_state_ttl_minutes)
    db.add(OAuthState(state=state, tenant_slug=tenant_slug, expires_at=expires_at))
    db.commit()

    entra_state = f"{state}.{nonce}" if nonce else state
    url = entra_service.build_authorization_url(config, entra_state)
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback", response_class=HTMLResponse)
async def entra_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    nonce = ""
    if "." in state:
        state, nonce = state.rsplit(".", 1)

    now = datetime.now(tz=timezone.utc)
    state_row = (
        db.query(OAuthState)
        .filter(OAuthState.state == state, OAuthState.expires_at > now)
        .first()
    )
    if not state_row:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth2 state",
        )
    tenant_slug = state_row.tenant_slug
    db.delete(state_row)
    db.commit()

    tenant = (
        db.query(Tenant)
        .filter(Tenant.slug == tenant_slug)
        .first()
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    config = (
        db.query(TenantEntraConfig)
        .filter(TenantEntraConfig.tenant_id == tenant.id)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=400, detail="Entra ID config missing"
        )

    token_response = await entra_service.exchange_code_for_token(
        config, code
    )
    access_token = token_response.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=502, detail="No access token in Entra response"
        )

    profile = await entra_service.get_entra_profile(access_token)
    group_ids = await entra_service.get_user_group_ids(access_token)

    entra_oid = profile.get("id")
    if not entra_oid:
        logger.error("Entra profile missing 'id' field for tenant %s", tenant_slug)
        raise HTTPException(
            status_code=502, detail="Entra profile missing user identifier"
        )

    email = profile.get("mail") or profile.get(
        "userPrincipalName", ""
    )

    role = entra_service.resolve_role(group_ids, config)
    if not role:
        logger.warning("Entra login denied — user %s not in any role group", entra_oid)
        raise HTTPException(
            status_code=403, detail="Not in any authorised group"
        )

    user = entra_service.jit_provision_user(
        db, tenant.id, entra_oid, email, role
    )
    gateway_token = create_access_token(
        user.id, tenant.id, role.value, email=user.email
    )

    sso_code = _issue_sso_code(gateway_token)
    safe_email = html.escape(email)
    safe_role = html.escape(role.value)
    safe_origin = "*"
    safe_nonce = html.escape(nonce)
    safe_code = html.escape(sso_code)
    logger.info(
        "Entra SSO login: user=%s tenant=%s role=%s",
        user.id, tenant.id, role.value,
    )
    csp_nonce = html.escape(request.scope.get("_csp_nonce", "")) or ""
    script_nonce_attr = f' nonce="{csp_nonce}"' if csp_nonce else ""

    return HTMLResponse(content=(
        "<!DOCTYPE html><html><head><title>MCP Gateway</title>"
        "<style>body{font-family:system-ui;max-width:600px;"
        "margin:60px auto;padding:0 20px}"
        "pre{background:#f1f5f9;padding:16px;border-radius:8px;"
        "word-break:break-all;white-space:pre-wrap}</style>"
        "</head><body>"
        f"<h2>Logged in as {safe_email} ({safe_role})</h2>"
        '<p id="msg">Signing you in\u2026</p>'
        '<div id="fallback" style="display:none">'
        "<p>Your one-time sign-in code (valid 2 minutes):</p>"
        f"<pre>{safe_code}</pre>"
        f"</div><script{script_nonce_attr}>"
        "if(window.opener){"
        "window.opener.postMessage("
        f'{{"type":"sso-code","code":"{safe_code}","nonce":"{safe_nonce}"}}'
        f",'{safe_origin}');"
        "window.close()"
        "}else{"
        'document.getElementById("msg").textContent='
        '"Copy the code below and paste it in the login page.";'
        'document.getElementById("fallback").style.display="block"'
        "}"
        "</script></body></html>"
    ))


@router.get("/exchange")
@limiter.limit("20/minute")
def exchange_sso_code(request: Request, code: str = Query(...)) -> dict:
    """Exchange a short-lived SSO code (from the Entra callback page) for a gateway JWT.

    The code is single-use and expires after 2 minutes.
    """
    now = datetime.now(tz=timezone.utc)
    with _pending_sso_codes_lock:
        entry = _pending_sso_codes.pop(code, None)
    if not entry or entry[1] < now:
        raise HTTPException(status_code=400, detail="Invalid or expired SSO code")
    return {"access_token": entry[0], "token_type": "bearer"}
