import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.rbac import ROLE_RANK as _RANK
from app.core.security import decrypt
from app.models import AuthProvider, Role, TenantEntraConfig, User

logger = logging.getLogger(__name__)

_SCOPES = "openid profile email User.Read GroupMember.Read.All"

HTTP_TIMEOUT = httpx.Timeout(10.0)
MAX_GROUP_PAGES = 20


@asynccontextmanager
async def _http_client(
    http: httpx.AsyncClient | None,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Yield a shared client if provided, otherwise create and close one.

    Allows callers to pass a single client across multiple Graph calls
    (connection reuse), while still working correctly when called standalone.
    """
    if http is not None:
        yield http
    else:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            yield client


def _redirect_uri(tenant_slug: str | None = None) -> str:
    settings = get_settings()
    if tenant_slug:
        return f"{settings.base_url}/t/{tenant_slug}/oauth/entra-callback"
    return f"{settings.base_url}/auth/entra/callback"


def build_authorization_url(
    config: TenantEntraConfig,
    state: str,
    tenant_slug: str | None = None,
) -> str:
    """Build the Entra ID OAuth2 authorization URL.

    When *tenant_slug* is provided the redirect goes through the MCP OAuth
    callback path ``/t/{slug}/oauth/entra-callback``.  Without it the legacy
    admin-UI callback ``/auth/entra/callback`` is used.
    """
    settings = get_settings()
    redirect_uri = _redirect_uri(tenant_slug)
    params = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": _SCOPES,
        "state": state,
    }
    base = (
        f"{settings.entra_authority_url}/{config.entra_tenant_id}/oauth2/v2.0/authorize"
    )
    return f"{base}?{urlencode(params)}"


async def exchange_code_for_token(
    config: TenantEntraConfig,
    code: str,
    http: httpx.AsyncClient | None = None,
    tenant_slug: str | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for an access token."""
    settings = get_settings()
    redirect_uri = _redirect_uri(tenant_slug)
    client_secret = decrypt(config.encrypted_client_secret)
    token_url = (
        f"{settings.entra_authority_url}/{config.entra_tenant_id}"
        f"/oauth2/v2.0/token"
    )
    try:
        async with _http_client(http) as client:
            r = await client.post(
                token_url,
                data={
                    "client_id": config.client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "scope": _SCOPES,
                },
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Token exchange failed: HTTP {exc.response.status_code}"
        ) from None
    except httpx.TransportError as exc:
        raise RuntimeError(
            f"Could not reach Microsoft identity service: {type(exc).__name__}"
        ) from None
    finally:
        del client_secret  # removes name binding; not a cryptographic memory wipe


async def get_entra_profile(
    access_token: str,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Fetch the authenticated user's profile from Microsoft Graph."""
    graph_base = get_settings().entra_graph_url
    try:
        async with _http_client(http) as client:
            r = await client.get(
                f"{graph_base}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Profile fetch failed: HTTP {exc.response.status_code}"
        ) from None
    except httpx.TransportError as exc:
        raise RuntimeError(
            f"Could not reach Microsoft Graph: {type(exc).__name__}"
        ) from None


async def get_user_group_ids(
    access_token: str,
    http: httpx.AsyncClient | None = None,
) -> list[str]:
    """Retrieve all transitive group memberships for the user."""
    graph_base = get_settings().entra_graph_url
    ids: list[str] = []
    url: str | None = (
        f"{graph_base}/me/transitiveMemberOf"
        f"/microsoft.graph.group?$select=id"
    )
    page = 0
    try:
        async with _http_client(http) as client:
            while url and page < MAX_GROUP_PAGES:
                r = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                r.raise_for_status()
                data = r.json()
                ids.extend(g["id"] for g in data.get("value", []))
                url = data.get("@odata.nextLink")
                page += 1
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Group fetch failed: HTTP {exc.response.status_code}"
        ) from None
    except httpx.TransportError as exc:
        raise RuntimeError(
            f"Could not reach Microsoft Graph: {type(exc).__name__}"
        ) from None

    # Warn after the loop so a TransportError above doesn't suppress it
    if page >= MAX_GROUP_PAGES:
        logger.warning(
            "Hit group pagination cap (%d pages); some groups may be missing",
            MAX_GROUP_PAGES,
        )

    return ids


async def get_app_token(
    config: TenantEntraConfig,
    http: httpx.AsyncClient | None = None,
) -> str:
    """Acquire an app-only token via client credentials grant.

    Requires ``GroupMember.Read.All`` as an **Application** permission
    (with admin consent) in the Azure AD app registration.
    """
    settings = get_settings()
    client_secret = decrypt(config.encrypted_client_secret)
    token_url = (
        f"{settings.entra_authority_url}/{config.entra_tenant_id}"
        f"/oauth2/v2.0/token"
    )
    try:
        async with _http_client(http) as client:
            r = await client.post(
                token_url,
                data={
                    "client_id": config.client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
            r.raise_for_status()
            return r.json()["access_token"]
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Client credentials token failed: HTTP {exc.response.status_code}"
        ) from None
    except httpx.TransportError as exc:
        raise RuntimeError(
            f"Could not reach Microsoft identity service: {type(exc).__name__}"
        ) from None
    finally:
        del client_secret


async def get_user_group_ids_by_oid(
    config: TenantEntraConfig,
    entra_oid: str,
    http: httpx.AsyncClient | None = None,
) -> list[str]:
    """Retrieve group memberships for a user by OID using app-only permissions.

    Uses ``GET /users/{oid}/transitiveMemberOf/microsoft.graph.group`` with
    ``GroupMember.Read.All`` Application permission (with admin consent).
    Returns a flat list of group IDs the user is a transitive member of.
    """
    app_token = await get_app_token(config, http)
    graph_base = get_settings().entra_graph_url
    url: str | None = (
        f"{graph_base}/users/{entra_oid}/transitiveMemberOf"
        f"/microsoft.graph.group?$select=id"
    )
    ids: list[str] = []
    page = 0
    try:
        async with _http_client(http) as client:
            while url and page < MAX_GROUP_PAGES:
                r = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {app_token}"},
                )
                r.raise_for_status()
                data = r.json()
                ids.extend(g["id"] for g in data.get("value", []))
                url = data.get("@odata.nextLink")
                page += 1
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Group fetch (app-only) failed: HTTP {exc.response.status_code}"
        ) from None
    except httpx.TransportError as exc:
        raise RuntimeError(
            f"Could not reach Microsoft Graph: {type(exc).__name__}"
        ) from None

    if page >= MAX_GROUP_PAGES:
        logger.warning(
            "Hit group pagination cap (%d pages) for user %s; some groups may be missing",
            MAX_GROUP_PAGES, entra_oid,
        )

    return ids


def resolve_role(
    group_ids: list[str], config: TenantEntraConfig
) -> Role | None:
    """Map Entra group memberships to the highest matching gateway role.

    Logs when a user qualifies for multiple roles so the grant is auditable.
    """
    matched: list[tuple[Role, str]] = []
    if config.admin_group_id and config.admin_group_id in group_ids:
        matched.append((Role.admin, config.admin_group_id))
    if config.analyst_group_id and config.analyst_group_id in group_ids:
        matched.append((Role.analyst, config.analyst_group_id))
    if config.viewer_group_id and config.viewer_group_id in group_ids:
        matched.append((Role.viewer, config.viewer_group_id))

    if not matched:
        return None

    # Sort by role rank descending so the highest role is always first,
    # regardless of the order the if-blocks were evaluated above.
    matched.sort(key=lambda x: _RANK[x[0]], reverse=True)

    if len(matched) > 1:
        logger.info(
            "User matched %d role groups; granting highest: %s",
            len(matched),
            matched[0][0].value,
        )

    return matched[0][0]


def jit_provision_user(
    db: Session,
    tenant_id: str,
    entra_oid: str,
    email: str,
    role: Role,
) -> User:
    """Create or update a user record from Entra ID profile data.

    Handles concurrent provision race via IntegrityError retry.
    """
    user = (
        db.query(User)
        .filter(User.entra_oid == entra_oid, User.tenant_id == tenant_id)
        .first()
    )
    if user:
        user.email = email
        user.role = role
        user.is_active = True
        db.commit()
        db.refresh(user)
        return user

    new_user = User(
        email=email,
        hashed_password=None,
        role=role,
        auth_provider=AuthProvider.entra,
        entra_oid=entra_oid,
        tenant_id=tenant_id,
    )
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user
    except IntegrityError as exc:
        if not exc.orig or "entra_oid" not in str(exc.orig):
            raise
        db.rollback()
        # Another request provisioned this user between our query and insert.
        # Re-fetch and update to ensure email and role are current.
        existing = (
            db.query(User)
            .filter(User.entra_oid == entra_oid, User.tenant_id == tenant_id)
            .first()
        )
        if not existing:
            raise
        existing.email = email
        existing.role = role
        db.commit()
        db.refresh(existing)
        return existing
