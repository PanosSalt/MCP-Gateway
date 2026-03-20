from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Role(str, enum.Enum):
    admin = "admin"
    analyst = "analyst"
    viewer = "viewer"


class DBType(str, enum.Enum):
    postgres = "postgres"
    mysql = "mysql"
    sqlite = "sqlite"
    mssql = "mssql"


class AuthProvider(str, enum.Enum):
    local = "local"
    entra = "entra"


class Tenant(Base):
    __tablename__ = "tenants"
    __allow_unmapped__ = True

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(tz=timezone.utc)
    )

    users = relationship(
        "User", back_populates="tenant", cascade="all, delete"
    )
    connections = relationship(
        "DBConnection", back_populates="tenant", cascade="all, delete"
    )
    entra_config = relationship(
        "TenantEntraConfig",
        back_populates="tenant",
        cascade="all, delete",
        uselist=False,
    )


class TenantEntraConfig(Base):
    __tablename__ = "tenant_entra_configs"
    __allow_unmapped__ = True

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String, ForeignKey("tenants.id"), nullable=False, unique=True
    )
    entra_tenant_id = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    encrypted_client_secret = Column(Text, nullable=False)
    admin_group_id = Column(String, nullable=True)
    analyst_group_id = Column(String, nullable=True)
    viewer_group_id = Column(String, nullable=True)

    tenant = relationship("Tenant", back_populates="entra_config")


class User(Base):
    __tablename__ = "users"
    __allow_unmapped__ = True

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, nullable=False)
    hashed_password = Column(String, nullable=True)
    role = Column(Enum(Role), default=Role.viewer)
    is_active = Column(Boolean, default=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(tz=timezone.utc)
    )
    auth_provider = Column(
        Enum(AuthProvider), default=AuthProvider.local, nullable=False
    )
    entra_oid = Column(String, nullable=True, index=True)

    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    tenant = relationship("Tenant", back_populates="users")
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete")

    __table_args__ = (
        Index("ix_users_email_tenant", "email", "tenant_id", unique=True),
    )


class DBConnection(Base):
    __tablename__ = "db_connections"
    __allow_unmapped__ = True

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    db_type = Column(Enum(DBType), nullable=False)
    encrypted_conn_str = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    min_role = Column(Enum(Role), nullable=False, default=Role.viewer)
    created_at = Column(
        DateTime, default=lambda: datetime.now(tz=timezone.utc)
    )

    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    tenant = relationship("Tenant", back_populates="connections")


class APIKey(Base):
    __tablename__ = "api_keys"
    __allow_unmapped__ = True

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id    = Column(String, ForeignKey("tenants.id"), nullable=False)
    user_id      = Column(String, ForeignKey("users.id"), nullable=False)
    name         = Column(String(100), nullable=False)
    prefix       = Column(String(16), nullable=False)
    hashed_key   = Column(String(64), nullable=False, unique=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(tz=timezone.utc))
    last_used_at = Column(DateTime, nullable=True)
    revoked_at   = Column(DateTime, nullable=True)
    expires_at   = Column(DateTime, nullable=True)

    user   = relationship("User", back_populates="api_keys")
    tenant = relationship("Tenant")

    __table_args__ = (
        Index("ix_api_keys_hashed_key", "hashed_key"),
        Index("ix_api_keys_user_id", "user_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __allow_unmapped__ = True

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id  = Column(String, ForeignKey("tenants.id"), nullable=True)
    user_id    = Column(String, ForeignKey("users.id"), nullable=True)
    event      = Column(String(50), nullable=False)
    ip_address = Column(String(45), nullable=True)
    metadata_  = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(tz=timezone.utc))

    __table_args__ = (
        # Descending index — matches the ORDER BY created_at DESC in list queries.
        # Managed via raw SQL in migration e2c4a7f93b16; postgresql_ops documents intent.
        Index(
            "ix_audit_logs_tenant_created_desc",
            "tenant_id", "created_at",
            postgresql_ops={"created_at": "DESC"},
        ),
    )


class OAuthState(Base):
    __tablename__ = "oauth_states"
    __allow_unmapped__ = True

    state       = Column(String(64), primary_key=True)
    tenant_slug = Column(String, nullable=False)
    expires_at  = Column(DateTime, nullable=False)

    code_challenge        = Column(String, nullable=True)
    code_challenge_method = Column(String, nullable=True)
    redirect_uri          = Column(String, nullable=True)
    client_id             = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_oauth_states_expires_at", "expires_at"),
    )


class OAuthAuthorizationCode(Base):
    __tablename__ = "oauth_authorization_codes"
    __allow_unmapped__ = True

    code                  = Column(String(128), primary_key=True)
    tenant_id             = Column(String, ForeignKey("tenants.id"), nullable=False)
    user_id               = Column(String, ForeignKey("users.id"), nullable=False)
    redirect_uri          = Column(String, nullable=False)
    code_challenge        = Column(String, nullable=False)
    code_challenge_method = Column(String, default="S256")
    expires_at            = Column(DateTime, nullable=False)
    used                  = Column(Boolean, default=False)

    __table_args__ = (
        Index("ix_oauth_codes_expires_at", "expires_at"),
    )


class OAuthRefreshToken(Base):
    __tablename__ = "oauth_refresh_tokens"
    __allow_unmapped__ = True

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id    = Column(String, ForeignKey("tenants.id"), nullable=False)
    user_id      = Column(String, ForeignKey("users.id"), nullable=False)
    hashed_token = Column(String(64), nullable=False, unique=True)
    expires_at   = Column(DateTime, nullable=False)
    revoked_at   = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(tz=timezone.utc))

    __table_args__ = (
        Index("ix_refresh_tokens_hashed", "hashed_token"),
    )


class ToolRoleOverride(Base):
    __tablename__ = "tool_role_overrides"
    __allow_unmapped__ = True

    id        = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    tool_name = Column(String(200), nullable=False)
    min_role  = Column(Enum(Role), nullable=False)

    tenant = relationship("Tenant")

    __table_args__ = (
        Index("ix_tool_overrides_tenant_tool", "tenant_id", "tool_name", unique=True),
    )
