import json as _json
import logging
import logging.config
import os
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.datastructures import MutableHeaders
from starlette.responses import PlainTextResponse

from alembic.config import Config as _AlembicConfig
from alembic.runtime.migration import MigrationContext as _MigrationContext
from alembic.script import ScriptDirectory as _ScriptDirectory
from app.api import api_keys, audit_logs, auth, auth_entra, connections, mcp_sse, oauth, query, tenants, tools
from app.config import get_settings
from app.core.limiter import limiter
from app.core.log_filter import install_filters
from app.database import get_engine, get_session
from app.services.audit import backfill_audit_emails


class _JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects for log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            payload["exc"] = self.formatException(record.exc_info)
        return _json.dumps(payload, default=str)


def _configure_logging() -> None:
    settings = get_settings()
    level = settings.log_level.upper()
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": lambda: _JSONFormatter()},
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": level,
            "handlers": ["default"],
        },
        "loggers": {
            # Alembic emits INFO on every MigrationContext.configure() call,
            # which happens on every /health probe. Suppress to WARNING.
            "alembic.runtime.migration": {"level": "WARNING", "propagate": True},
        },
    })


_scanner_logger = logging.getLogger("app.scanner_guard")
_cors_logger = logging.getLogger("app.cors")


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware that adds security headers to every HTTP response.

    Uses raw ASGI send-wrapping instead of BaseHTTPMiddleware to avoid the
    ``body_stream`` assertion error that BaseHTTPMiddleware triggers when an
    SSE endpoint sends a streaming response via ``request._send`` and FastAPI
    then auto-generates a second response for the ``None`` return value.

    A duplicate-response guard silently drops any second ``http.response.start``
    (and everything after it), which prevents uvicorn from raising RuntimeError.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        csp_nonce = None
        if path == "/auth/entra/callback":
            csp_nonce = secrets.token_urlsafe(16)
            scope["_csp_nonce"] = csp_nonce

        response_started = False
        suppressing = False

        async def send_wrapper(message):
            nonlocal response_started, suppressing
            if suppressing:
                return
            if message["type"] == "http.response.start":
                if response_started:
                    suppressing = True
                    return
                response_started = True
                headers = MutableHeaders(raw=list(message.get("headers", [])))
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )
                script_src = "'self'"
                if csp_nonce:
                    script_src += f" 'nonce-{csp_nonce}'"
                headers["Content-Security-Policy"] = (
                    f"default-src 'self'; script-src {script_src}; "
                    "style-src 'self' 'unsafe-inline'; "
                    "frame-ancestors 'none'"
                )
                if path.startswith("/auth"):
                    headers["Cache-Control"] = "no-store"
                message = {**message, "headers": headers.raw}
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Patterns used by vulnerability scanners that have no legitimate reason to
# reach a Python/FastAPI service.  Matched against the raw URL path.
_MALICIOUS_PATH_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"/cgi-bin/"
    r"|/struts2"
    r"|/webtools/"
    r"|/broker/"
    r"|/JSPWiki/"
    r"|/wp-admin"
    r"|/wp-login"
    r"|/wp-content"
    r"|/\.env"
    r"|/actuator"
    r"|/manager/html"
    r"|/solr/"
    r"|/console/"
    r"|/invoker/"
    r"|/jmx-console"
    r")"
)

_MALICIOUS_QUERY_RE = re.compile(
    r"\$\{jndi:", re.IGNORECASE
)


_SCANNER_SAFE_PREFIXES = ("/health", "/admin", "/t/")


class ScannerGuardMiddleware:
    """Pure-ASGI middleware — early rejection of exploit-scanner requests.

    Returns 403 immediately so these requests never reach routers, reducing
    noise and protecting the async event loop from unnecessary work.

    Uses raw ASGI instead of BaseHTTPMiddleware to avoid streaming assertion
    errors with SSE connections.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        if not any(path.startswith(p) for p in _SCANNER_SAFE_PREFIXES):
            query = (scope.get("query_string", b"") or b"").decode(
                "utf-8", errors="replace"
            )
            if _MALICIOUS_PATH_RE.search(path) or _MALICIOUS_QUERY_RE.search(query):
                client_host = (
                    scope["client"][0] if scope.get("client") else "unknown"
                )
                _scanner_logger.warning(
                    "Blocked scanner probe: client=%s path=%s", client_host, path,
                )
                response = PlainTextResponse("Forbidden", status_code=403)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def _cleanup_expired_oauth(db) -> None:
    """Delete expired OAuth states, authorization codes, and refresh tokens."""
    from app.models import OAuthAuthorizationCode, OAuthRefreshToken, OAuthState

    now = datetime.now(tz=timezone.utc)
    deleted_states = db.query(OAuthState).filter(OAuthState.expires_at < now).delete()
    deleted_codes = db.query(OAuthAuthorizationCode).filter(OAuthAuthorizationCode.expires_at < now).delete()
    deleted_tokens = db.query(OAuthRefreshToken).filter(OAuthRefreshToken.expires_at < now).delete()
    if deleted_states or deleted_codes or deleted_tokens:
        db.commit()
        logging.getLogger(__name__).info(
            "OAuth cleanup: %d states, %d codes, %d refresh tokens expired",
            deleted_states, deleted_codes, deleted_tokens,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _log = logging.getLogger(__name__)
    db = get_session()
    try:
        backfill_audit_emails(db)
        _cleanup_expired_oauth(db)
    except Exception:
        _log.exception("Lifespan startup tasks failed")
    finally:
        db.close()

    yield

    # Shutdown — uvicorn has already stopped accepting new connections and
    # waited up to --timeout-graceful-shutdown seconds for in-flight requests
    # to complete before reaching here.
    _log.info("MCP Gateway shutting down — disposing engine pool")


app = FastAPI(
    title="MCP Gateway",
    description="Multi-tenant MCP server with authentication and RBAC",
    version="1.0.0",
    lifespan=lifespan,
)

_configure_logging()

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ScannerGuardMiddleware)

install_filters()


def _get_cors_origins() -> list[str]:
    settings = get_settings()
    raw = (settings.cors_origins or settings.base_url).strip()
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    validated = []
    for o in origins:
        if o == "*":
            _cors_logger.warning(
                "Wildcard CORS origin ('*') is not permitted; skipping. "
                "Set CORS_ORIGINS to explicit origins."
            )
            continue
        parsed = urlparse(o)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid CORS origin: {o!r} — must be an absolute URL")
        validated.append(o)
    return validated or [settings.base_url.rstrip("/")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── API v1 — versioned admin/management endpoints ────────────────────────────
# Protocol-defined routes (OAuth /t/{slug}/..., MCP /t/{slug}/..., /.well-known/)
# and infrastructure routes (/health, /admin) are intentionally unversioned.
_v1 = APIRouter(prefix="/api/v1")
_v1.include_router(auth.router, prefix="/auth", tags=["v1"])
_v1.include_router(auth_entra.router, prefix="/auth/entra", tags=["v1"])
_v1.include_router(tenants.router, prefix="/tenants", tags=["v1"])
_v1.include_router(connections.router, prefix="/connections", tags=["v1"])
_v1.include_router(query.router, prefix="/query", tags=["v1"])
_v1.include_router(api_keys.router, prefix="/api-keys", tags=["v1"])
_v1.include_router(audit_logs.router, prefix="/audit-logs", tags=["v1"])
_v1.include_router(tools.router, prefix="/tools", tags=["v1"])
app.include_router(_v1)

# Unversioned aliases kept for backward compatibility with the current frontend.
# Migrate clients to /api/v1/... and remove these in a future release.
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(tenants.router, prefix="/tenants", tags=["tenants"])
app.include_router(
    connections.router, prefix="/connections", tags=["connections"]
)
app.include_router(query.router, prefix="/query", tags=["query"])
app.include_router(
    auth_entra.router, prefix="/auth/entra", tags=["entra"]
)
app.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
app.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit-logs"])
app.include_router(tools.router, prefix="/tools", tags=["tools"])
app.include_router(mcp_sse.legacy_router, prefix="/mcp", tags=["mcp-legacy"])

# Root-level well-known routes (RFC 8414 §3.1 compliant URL structure)
app.include_router(oauth.well_known_router, tags=["oauth-discovery"])

# Tenant-scoped routes — OAuth + MCP endpoints under /t/{slug}
app.include_router(oauth.router, prefix="/t/{slug}", tags=["oauth"])
app.include_router(mcp_sse.router, prefix="/t/{slug}", tags=["mcp"])


_ALEMBIC_INI = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
_health_log = logging.getLogger(__name__ + ".health")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness + readiness probe. Checks database connectivity and migration state."""
    db = get_session()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")
    finally:
        db.close()

    try:
        cfg = _AlembicConfig(_ALEMBIC_INI)
        script = _ScriptDirectory.from_config(cfg)
        with get_engine().connect() as conn:
            ctx = _MigrationContext.configure(conn)
            current = set(ctx.get_current_heads())
        expected = set(script.get_heads())
        if current != expected:
            raise HTTPException(
                status_code=503,
                detail=f"Pending migrations: at {current or 'none'}, expected {expected}",
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Treat alembic introspection errors as non-fatal — DB connectivity
        # (checked above) is the primary liveness concern.
        _health_log.warning("Migration state check failed: %s", exc)

    return {"status": "ok"}


# ── Admin UI (built frontend) ─────────────────────────────────────────────────
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_ASSETS_DIR = os.path.join(_STATIC_DIR, "assets")

if os.path.isdir(_ASSETS_DIR):
    app.mount("/admin/assets", StaticFiles(directory=_ASSETS_DIR), name="admin-assets")

@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def admin_ui() -> FileResponse:
    index = os.path.join(_STATIC_DIR, "index.html")
    if not os.path.isfile(index):
        raise HTTPException(status_code=503, detail="Admin UI not built")
    return FileResponse(index)
