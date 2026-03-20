"""initial schema

Revision ID: f950cedc43ad
Revises:
Create Date: 2026-03-18 09:55:04.831562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f950cedc43ad'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('oauth_states',
    sa.Column('state', sa.String(length=64), nullable=False),
    sa.Column('tenant_slug', sa.String(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('code_challenge', sa.String(), nullable=True),
    sa.Column('code_challenge_method', sa.String(), nullable=True),
    sa.Column('redirect_uri', sa.String(), nullable=True),
    sa.Column('client_id', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('state')
    )
    op.create_index('ix_oauth_states_expires_at', 'oauth_states', ['expires_at'], unique=False)
    op.create_table('tenants',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('slug', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('db_connections',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('db_type', sa.Enum('postgres', 'mysql', 'sqlite', 'mssql', name='dbtype'), nullable=False),
    sa.Column('encrypted_conn_str', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('min_role', sa.Enum('admin', 'analyst', 'viewer', name='role'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_db_connections_tenant_id'), 'db_connections', ['tenant_id'], unique=False)
    op.create_table('tenant_entra_configs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('entra_tenant_id', sa.String(), nullable=False),
    sa.Column('client_id', sa.String(), nullable=False),
    sa.Column('encrypted_client_secret', sa.Text(), nullable=False),
    sa.Column('admin_group_id', sa.String(), nullable=True),
    sa.Column('analyst_group_id', sa.String(), nullable=True),
    sa.Column('viewer_group_id', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id')
    )
    op.create_table('tool_role_overrides',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('tool_name', sa.String(length=200), nullable=False),
    sa.Column('min_role', sa.Enum('admin', 'analyst', 'viewer', name='role'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tool_overrides_tenant_tool', 'tool_role_overrides', ['tenant_id', 'tool_name'], unique=True)
    op.create_table('users',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('hashed_password', sa.String(), nullable=True),
    sa.Column('role', sa.Enum('admin', 'analyst', 'viewer', name='role'), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('auth_provider', sa.Enum('local', 'entra', name='authprovider'), nullable=False),
    sa.Column('entra_oid', sa.String(), nullable=True),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email_tenant', 'users', ['email', 'tenant_id'], unique=True)
    op.create_index(op.f('ix_users_entra_oid'), 'users', ['entra_oid'], unique=False)
    op.create_index(op.f('ix_users_tenant_id'), 'users', ['tenant_id'], unique=False)
    op.create_table('api_keys',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('prefix', sa.String(length=16), nullable=False),
    sa.Column('hashed_key', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hashed_key')
    )
    op.create_index('ix_api_keys_hashed_key', 'api_keys', ['hashed_key'], unique=False)
    op.create_index('ix_api_keys_user_id', 'api_keys', ['user_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=True),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('event', sa.String(length=50), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute(
        "CREATE INDEX ix_audit_logs_tenant_created_desc "
        "ON audit_logs (tenant_id, created_at DESC)"
    )
    op.create_table('oauth_authorization_codes',
    sa.Column('code', sa.String(length=128), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('redirect_uri', sa.String(), nullable=False),
    sa.Column('code_challenge', sa.String(), nullable=False),
    sa.Column('code_challenge_method', sa.String(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_index('ix_oauth_codes_expires_at', 'oauth_authorization_codes', ['expires_at'], unique=False)
    op.create_table('oauth_refresh_tokens',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('hashed_token', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hashed_token')
    )
    op.create_index('ix_refresh_tokens_hashed', 'oauth_refresh_tokens', ['hashed_token'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_refresh_tokens_hashed', table_name='oauth_refresh_tokens')
    op.drop_table('oauth_refresh_tokens')
    op.drop_index('ix_oauth_codes_expires_at', table_name='oauth_authorization_codes')
    op.drop_table('oauth_authorization_codes')
    op.drop_index('ix_audit_logs_tenant_created_desc', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index('ix_api_keys_user_id', table_name='api_keys')
    op.drop_index('ix_api_keys_hashed_key', table_name='api_keys')
    op.drop_table('api_keys')
    op.drop_index(op.f('ix_users_tenant_id'), table_name='users')
    op.drop_index(op.f('ix_users_entra_oid'), table_name='users')
    op.drop_index('ix_users_email_tenant', table_name='users')
    op.drop_table('users')
    op.drop_index('ix_tool_overrides_tenant_tool', table_name='tool_role_overrides')
    op.drop_table('tool_role_overrides')
    op.drop_table('tenant_entra_configs')
    op.drop_index(op.f('ix_db_connections_tenant_id'), table_name='db_connections')
    op.drop_table('db_connections')
    op.drop_table('tenants')
    op.drop_index('ix_oauth_states_expires_at', table_name='oauth_states')
    op.drop_table('oauth_states')
