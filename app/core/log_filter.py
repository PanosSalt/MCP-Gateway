"""Custom logging filters for uvicorn access logs."""

from __future__ import annotations

import logging
import re


class HealthCheckFilter(logging.Filter):
    """Suppress uvicorn access-log lines for the /health endpoint.

    Docker HEALTHCHECK hits this every ~30s and creates excessive noise.
    """

    _health_re = re.compile(r'"[A-Z]+ /health[\s?]')

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not self._health_re.search(msg)


class SensitiveQueryParamFilter(logging.Filter):
    """Redact sensitive query-parameter values from uvicorn access-log lines.

    OAuth authorization codes, API keys, and JWT tokens appear as query
    parameters on callback/SSE URLs.  Logging these in plaintext creates a
    credential-leak vector (log aggregation, SIEM export, shared terminals).
    """

    _SENSITIVE_PARAMS = {"code", "api_key", "token", "session_state"}
    _param_re = re.compile(
        r"([?&])(" + "|".join(re.escape(p) for p in _SENSITIVE_PARAMS) + r")=([^&\s]+)"
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(
                self._redact(a) if isinstance(a, str) else a
                for a in record.args
            )
        elif isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        return True

    @classmethod
    def _redact(cls, value: str) -> str:
        return cls._param_re.sub(r"\1\2=[REDACTED]", value)


def install_filters() -> None:
    """Attach filters to uvicorn's access logger.

    Safe to call multiple times — guards against duplicate installation.
    """
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, HealthCheckFilter) for f in access_logger.filters):
        access_logger.addFilter(HealthCheckFilter())
    if not any(isinstance(f, SensitiveQueryParamFilter) for f in access_logger.filters):
        access_logger.addFilter(SensitiveQueryParamFilter())
