from __future__ import annotations

import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings

_INSECURE_DEFAULTS = {
    "change-this-in-production",
    "change-this-32-byte-key-in-prod!!",
}


class Settings(BaseSettings):
    database_url: str
    secret_key: str = "change-this-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens_sql: int = 1024
    llm_max_tokens_summary: int = 500
    encryption_key: str = "change-this-32-byte-key-in-prod!!"
    base_url: str = "http://localhost:8000"
    # Comma-separated list of allowed CORS origins.  Defaults to base_url.
    # Example: "https://admin.example.com,https://gateway.example.com"
    cors_origins: str = ""
    oauth_state_ttl_minutes: int = 10
    oauth_code_ttl_minutes: int = 5
    entra_authority_url: str = "https://login.microsoftonline.com"
    entra_graph_url: str = "https://graph.microsoft.com/v1.0"
    # Comma-separated list of directories the filesystem tools may access.
    # When empty, no filesystem tools are exposed.
    filesystem_allowed_dirs: str = ""
    log_level: str = "INFO"
    # Shared storage for the rate limiter.  Empty means in-memory, which is
    # per-process and therefore does not hold across multiple workers.
    redis_url: str = ""
    # Number of uvicorn workers; mirrors WEB_CONCURRENCY in entrypoint.sh.
    # Only used to warn when rate limits cannot be enforced globally.
    web_concurrency: int = 1
    # Honour X-Forwarded-For when deriving the rate-limit key.  Enable only
    # when a trusted reverse proxy sets the header, otherwise clients can
    # spoof it to bypass rate limits.
    trust_proxy_headers: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def reject_insecure_defaults_in_production(self) -> "Settings":
        if self.secret_key in _INSECURE_DEFAULTS:
            raise ValueError(
                "SECRET_KEY must be changed from the default before running in production."
            )
        if self.encryption_key in _INSECURE_DEFAULTS:
            raise ValueError(
                "ENCRYPTION_KEY must be changed from the default before running in production."
            )
        if len(self.encryption_key) < 32:
            raise ValueError(
                "ENCRYPTION_KEY must be at least 32 characters. "
                "The full key is consumed via BLAKE2b derivation, so longer keys "
                "(e.g. a 64-char hex string) provide proportionally more entropy."
            )
        for entry in self.filesystem_allowed_dirs.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if not os.path.isabs(entry):
                raise ValueError(
                    f"FILESYSTEM_ALLOWED_DIRS entry {entry!r} must be an "
                    "absolute path."
                )
            if ".." in entry.split(os.sep):
                raise ValueError(
                    f"FILESYSTEM_ALLOWED_DIRS entry {entry!r} must not contain "
                    "'..' path segments."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
