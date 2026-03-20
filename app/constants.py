"""Application-wide constants.

Values that are not operator-tunable belong here.
Operator-tunable values (TTLs, log level, etc.) live in app/config.py.
"""
from __future__ import annotations

# ── API pagination caps ───────────────────────────────────────────────────────

#: Hard upper bound on the number of audit log / query-history rows returned
#: per page. Prevents runaway memory usage on large tenants.
MAX_AUDIT_PAGE_SIZE: int = 200

#: Hard upper bound on user / connection list pages. Larger because these
#: resources are infrequently-changing and tenants rarely exceed hundreds.
MAX_LIST_PAGE_SIZE: int = 500
