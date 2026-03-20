from __future__ import annotations

import hashlib
import hmac
import secrets

from app.config import get_settings

KEY_PREFIX = "mgw"
KEY_ENTROPY_BYTES = 32


def hash_api_key(raw_key: str) -> str:
    """HMAC-SHA-256 of the raw key using SECRET_KEY as the server-side secret.

    Binding the hash to a server secret means a database breach alone is not
    sufficient to reverse-engineer API keys — the attacker also needs SECRET_KEY.
    """
    secret = get_settings().secret_key.encode()
    return hmac.new(secret, raw_key.encode(), hashlib.sha256).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """
    Returns (raw_key, prefix, hashed_key).
    raw_key is returned to the user ONCE and never stored.
    prefix is stored plaintext for display.
    hashed_key (HMAC-SHA-256 hex) is stored in DB for verification.
    """
    raw    = secrets.token_urlsafe(KEY_ENTROPY_BYTES)
    prefix = f"{KEY_PREFIX}_{raw[:8]}"
    full   = f"{prefix}_{raw}"
    hashed = hash_api_key(full)
    return full, prefix, hashed
