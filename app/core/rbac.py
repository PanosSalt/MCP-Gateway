from __future__ import annotations

from app.models import Role

ROLE_RANK: dict[Role, int] = {
    Role.viewer: 0,
    Role.analyst: 1,
    Role.admin: 2,
}


def has_min_role(user_role: Role, required: Role) -> bool:
    """Return True if user_role meets or exceeds the required role."""
    return ROLE_RANK[user_role] >= ROLE_RANK[required]
