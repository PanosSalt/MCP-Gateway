from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from sqlalchemy.orm import Session
from starlette.responses import Response

from app import tools
from app.core.auth import decode_token
from app.core.dependencies import _user_from_api_key, _user_from_jwt
from app.database import get_session
from app.models import Tenant, User
from app.tools import ToolContext

logger = logging.getLogger(__name__)


def _authenticate_request(request: Request, db: Session) -> User | None:
    """Try Bearer JWT, then api_key query param.  Return the user or None."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return _user_from_jwt(auth_header[7:], db)
    api_key = request.query_params.get("api_key")
    if api_key:
        return _user_from_api_key(api_key, db)
    return None


class _AlreadySentResponse(Response):
    """No-op ASGI response for endpoints that already wrote via ``request._send``.

    Returning this instead of ``None`` prevents FastAPI from auto-generating a
    second ``http.response.start`` message, which would crash any
    ``BaseHTTPMiddleware`` in the stack (e.g. SlowAPIMiddleware).
    """

    async def __call__(self, scope, receive, send):
        pass

router = APIRouter()
legacy_router = APIRouter()

_tenant_transports: dict[str, SseServerTransport] = {}
_legacy_transport = SseServerTransport("/mcp/messages")


def _get_transport(slug: str) -> SseServerTransport:
    if slug not in _tenant_transports:
        _tenant_transports[slug] = SseServerTransport(f"/t/{slug}/mcp/messages")
    return _tenant_transports[slug]


def build_mcp_server(user_id: str, db: Session) -> Server:
    server = Server("mcp-gateway")

    def _fresh_ctx() -> ToolContext:
        user = db.query(User).filter(User.id == user_id).first()
        return ToolContext(user=user, db=db)

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return tools.get_tools(_fresh_ctx())

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict
    ) -> list[TextContent]:
        return await tools.handle(name, arguments, _fresh_ctx())

    return server


@router.get("/mcp/sse")
async def mcp_sse(
    slug: str,
    request: Request,
):
    """Tenant-scoped MCP SSE endpoint.

    Accepts ``Authorization: Bearer <JWT>`` or ``?api_key=<key>``.
    When neither is provided, returns 401 with WWW-Authenticate so
    mcp-remote can initiate the OAuth browser flow.
    """
    db = get_session()
    try:
        user = _authenticate_request(request, db)
        if user is None:
            base = str(request.base_url).rstrip("/")
            www_auth = (
                f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/t/{slug}/mcp/sse"'
            )
            raise HTTPException(
                status_code=401,
                headers={"WWW-Authenticate": www_auth},
                detail="Authentication required",
            )

        tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
        if not tenant or user.tenant_id != tenant.id:
            raise HTTPException(status_code=403, detail="Token not valid for this tenant")

        sse_transport = _get_transport(slug)
        mcp_server = build_mcp_server(user.id, db)

        client_ip = request.client.host if request.client else "unknown"
        logger.info(
            "SSE connect: tenant=%s user=%s (%s) client=%s",
            slug, user.email, user.id, client_ip,
        )
        t0 = time.monotonic()
        disconnect_reason = "clean"
        try:
            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await mcp_server.run(
                    streams[0],
                    streams[1],
                    mcp_server.create_initialization_options(),
                )
        except Exception as exc:
            disconnect_reason = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            elapsed = time.monotonic() - t0
            logger.info(
                "SSE disconnect: tenant=%s user=%s (%s) duration=%.1fs reason=%s",
                slug, user.email, user.id, elapsed, disconnect_reason,
            )
        return _AlreadySentResponse()
    except HTTPException:
        raise
    finally:
        db.close()


@router.post("/mcp/messages", include_in_schema=False)
async def mcp_messages(slug: str, request: Request):
    # Verify credentials when present; otherwise fall through to
    # SseServerTransport which validates the session_id.  This allows
    # api_key-authenticated SSE sessions (where mcp-remote does not
    # re-send credentials on POST) while still rejecting bad tokens.
    db = get_session()
    try:
        _authenticate_request(request, db)
    finally:
        db.close()

    sse_transport = _get_transport(slug)

    captured_status = 202
    captured_body = b""

    async def capturing_send(message):
        nonlocal captured_status, captured_body
        if message["type"] == "http.response.start":
            captured_status = message["status"]
        elif message["type"] == "http.response.body":
            captured_body += message.get("body", b"")

    await sse_transport.handle_post_message(
        request.scope, request.receive, capturing_send
    )
    return Response(content=captured_body, status_code=captured_status)


# ── Legacy /mcp/sse endpoint (API-key auth, deprecated) ──────────────────────


@legacy_router.get("/sse")
async def legacy_mcp_sse(request: Request, api_key: str | None = None, token: str | None = None):
    """Legacy MCP SSE endpoint. Accepts api_key or token query param.

    Deprecated — migrate to /t/{slug}/mcp/sse with OAuth Bearer auth.
    """
    db = get_session()
    try:
        if api_key:
            logger.warning("Legacy SSE auth via query param 'api_key' — migrate to OAuth Bearer auth")
            user = _user_from_api_key(api_key, db)
        elif token:
            logger.warning("Legacy SSE auth via query param 'token' — migrate to OAuth Bearer auth")
            user = _user_from_jwt(token, db)
        else:
            raise HTTPException(status_code=401, detail="api_key or token query param required")

        sse_transport = _legacy_transport
        mcp_server = build_mcp_server(user.id, db)

        async def send_with_deprecation(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"deprecation", b"true"))
                headers.append((b"sunset", b"2026-06-01"))
                message = {**message, "headers": headers}
            await request._send(message)

        client_ip = request.client.host if request.client else "unknown"
        logger.info(
            "SSE connect (legacy): user=%s (%s) client=%s",
            user.email, user.id, client_ip,
        )
        t0 = time.monotonic()
        disconnect_reason = "clean"
        try:
            async with sse_transport.connect_sse(
                request.scope, request.receive, send_with_deprecation
            ) as streams:
                await mcp_server.run(
                    streams[0],
                    streams[1],
                    mcp_server.create_initialization_options(),
                )
        except Exception as exc:
            disconnect_reason = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            elapsed = time.monotonic() - t0
            logger.info(
                "SSE disconnect (legacy): user=%s (%s) duration=%.1fs reason=%s",
                user.email, user.id, elapsed, disconnect_reason,
            )
        return _AlreadySentResponse()
    except HTTPException:
        raise
    finally:
        db.close()


@legacy_router.post("/messages", include_in_schema=False)
async def legacy_mcp_messages(request: Request):
    # Require a valid token even on the legacy endpoint (defence-in-depth).
    auth_header = request.headers.get("Authorization", "")
    api_key_param = request.query_params.get("api_key")
    token_param = request.query_params.get("token")

    authenticated = False
    if auth_header.startswith("Bearer ") and decode_token(auth_header[7:]):
        authenticated = True
    elif token_param and decode_token(token_param):
        authenticated = True
    elif api_key_param:
        _db = get_session()
        try:
            _user_from_api_key(api_key_param, _db)
            authenticated = True
        except HTTPException:
            pass
        finally:
            _db.close()

    if not authenticated:
        raise HTTPException(status_code=401, detail="Authentication required")

    sse_transport = _legacy_transport

    captured_status = 202
    captured_body = b""

    async def capturing_send(message):
        nonlocal captured_status, captured_body
        if message["type"] == "http.response.start":
            captured_status = message["status"]
        elif message["type"] == "http.response.body":
            captured_body += message.get("body", b"")

    await sse_transport.handle_post_message(
        request.scope, request.receive, capturing_send
    )
    return Response(content=captured_body, status_code=captured_status)
