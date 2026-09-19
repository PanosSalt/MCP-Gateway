from __future__ import annotations

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import get_settings

logger = logging.getLogger(__name__)


def _client_key(request: Request) -> str:
    """Rate-limit key: the client IP, honouring X-Forwarded-For when trusted.

    Behind a reverse proxy ``request.client.host`` is the proxy's address, so
    every caller collapses into a single bucket.  X-Forwarded-For fixes that,
    but only when the proxy is trusted — otherwise any client can spoof the
    header and mint itself an unlimited number of buckets.  Hence opt-in.
    """
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Left-most entry is the original client; the rest are proxies.
            return forwarded.split(",")[0].strip()
    return get_remote_address(request)


def _storage_uri() -> str | None:
    """Shared limiter storage, or None for slowapi's in-memory default."""
    return get_settings().redis_url or None


limiter = Limiter(key_func=_client_key, storage_uri=_storage_uri())


def warn_if_unshared_storage() -> None:
    """Log a warning when limits cannot hold across workers.

    In-memory storage is per-process, so with N workers every documented
    limit is effectively N times higher.
    """
    settings = get_settings()
    if settings.redis_url:
        return
    if settings.web_concurrency > 1:
        logger.warning(
            "Rate limiter is using in-memory storage with WEB_CONCURRENCY=%d. "
            "Limits apply per worker, so effective limits are ~%dx the "
            "configured values. Set REDIS_URL for shared enforcement.",
            settings.web_concurrency, settings.web_concurrency,
        )
