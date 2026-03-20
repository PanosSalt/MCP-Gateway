from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import AuthProvider, DBType, Role


def _validate_email_format(v: str) -> str:
    """Lightweight email format check — requires an @ with a dotted domain."""
    parts = v.split("@")
    if len(parts) != 2 or not parts[0] or "." not in parts[1] or not parts[1].split(".")[-1]:
        raise ValueError("Invalid email address format")
    return v.lower().strip()


# ── Auth ─────────────────────────────────────────────────────────────

class UserLogin(BaseModel):
    email: str
    password: str
    # Optional: when provided the login is scoped to that tenant, preventing
    # cross-tenant email ambiguity in multi-tenant deployments.
    tenant_slug: str | None = None

    _check_email = field_validator("email")(_validate_email_format)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: str
    tenant_id: str
    role: Role


# ── Tenants ──────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)
    admin_email: str
    admin_password: str = Field(..., min_length=12)

    _check_admin_email = field_validator("admin_email")(_validate_email_format)


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime


# ── Users ────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str
    password: str = Field(..., min_length=12)
    role: Role = Role.viewer

    _check_email = field_validator("email")(_validate_email_format)


class UserRoleUpdate(BaseModel):
    role: Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: Role
    is_active: bool
    auth_provider: AuthProvider


# ── Connections ──────────────────────────────────────────────────────

class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    db_type: DBType
    connection_string: str = Field(..., max_length=2000)
    description: str | None = Field(None, max_length=1000)
    min_role: Role = Role.viewer


class ConnectionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    db_type: DBType | None = None
    connection_string: str | None = Field(None, max_length=2000)
    description: str | None = Field(None, max_length=1000)
    min_role: Role | None = None


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    db_type: DBType
    description: str | None
    is_active: bool
    created_at: datetime
    min_role: Role


# ── Query ────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    connection_id: str
    question: str = Field(..., min_length=1, max_length=2000)


class QueryResponse(BaseModel):
    question: str
    sql_generated: str | None
    result: list[dict]
    summary: str


# ── Entra ID ─────────────────────────────────────────────────────────

class EntraConfigCreate(BaseModel):
    entra_tenant_id: str
    client_id: str
    # None means "keep the existing secret" — only meaningful on update.
    # A new configuration must provide a non-empty secret (enforced in the endpoint).
    client_secret: str | None = None
    admin_group_id: str | None = None
    analyst_group_id: str | None = None
    viewer_group_id: str | None = None


class EntraConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entra_tenant_id: str
    client_id: str
    admin_group_id: str | None
    analyst_group_id: str | None
    viewer_group_id: str | None


class EntraLoginResponse(BaseModel):
    authorization_url: str


# ── API Keys ──────────────────────────────────────────────────────────

class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    expires_at: datetime | None = None


class APIKeyCreatedResponse(BaseModel):
    id: str
    name: str
    prefix: str
    raw_key: str  # returned ONCE only — not stored
    created_at: datetime


class APIKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None


# ── OAuth ─────────────────────────────────────────────────────────────

class OAuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class OAuthDiscovery(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    response_types_supported: list[str] = ["code"]
    grant_types_supported: list[str] = ["authorization_code", "refresh_token"]
    code_challenge_methods_supported: list[str] = ["S256"]


# ── Tools ─────────────────────────────────────────────────────────────

class ToolInfo(BaseModel):
    tool_name: str
    tool_type: str
    description: str
    connection_id: str | None
    connection_name: str | None
    default_min_role: Role
    effective_min_role: Role
    accessible: bool


class ToolRoleUpdate(BaseModel):
    min_role: Role | None = None


# ── Audit Log ────────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None
    user_email: str | None = None
    event: str
    ip_address: str | None
    metadata: dict | None = Field(None, validation_alias="metadata_")
    created_at: datetime

# Backward-compat alias for the old /query/history endpoint
QueryHistoryEntry = AuditLogEntry
