from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet

from app.config import get_settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _make_fernet() -> Fernet:
    """Derive a Fernet key from ENCRYPTION_KEY via BLAKE2b.

    BLAKE2b with digest_size=32 consumes the *full* key material regardless
    of its length, producing exactly 32 bytes of output.  This means:
    - A 32-char key and a 64-char hex key both contribute their full entropy.
    - No bytes are silently discarded.
    - The resulting 32-byte digest is URL-safe base64-encoded to satisfy
      Fernet's key format requirement.
    """
    raw = get_settings().encryption_key.encode()
    derived = hashlib.blake2b(raw, digest_size=32).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = _make_fernet()
    return _fernet


def encrypt(plain_text: str) -> str:
    return _get_fernet().encrypt(plain_text.encode()).decode()


def decrypt(cipher_text: str) -> str:
    return _get_fernet().decrypt(cipher_text.encode()).decode()
