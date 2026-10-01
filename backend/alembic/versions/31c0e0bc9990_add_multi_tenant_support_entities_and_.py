"""add multi-tenant support entities and tenant scoping

Additive-only multi-tenant support migration:

- New enum types: tenant_status_enum, tenant_role_enum,
  tenant_membership_status_enum, tenant_invitation_status_enum,
  tenant_audit_event_type_enum, tenant_audit_actor_type_enum,
  platform_setting_category_enum
- New tables: tenants, tenant_user_memberships, tenant_invitations,
  tenant_audit_events, platform_settings
- New nullable ``tenant_id`` column (FK -> tenants.id ON DELETE SET NULL,
  indexed) on every direct tenant-scoped business entity. While multi-tenancy
  is disabled the references stay NULL and behavior is unchanged.

No drops, no non-nullable additions. Multi-tenancy is opt-in and disabled by
default; existing data is adopted into the implicit system tenant by the
application-level adoption process.

Revision ID: 31c0e0bc9990
Revises: a8344bd0b4ac
Create Date: 2026-09-20 15:34:27.101711

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '31c0e0bc9990'
down_revision: str | None = 'a8344bd0b4ac'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── New enum types ────────────────────────────────────────────────────────────
# Created explicitly in upgrade() (checkfirst) and dropped in downgrade().
# Table DDL references them with create_type=False per project convention
# (postgresql.ENUM(..., create_type=False)) — required in particular because
# tenant_role_enum is shared by three of the new tables.

_TENANT_ROLE = postgresql.ENUM(
    'platform_admin', 'tenant_admin', 'member',
    name='tenant_role_enum', create_type=False,
)
_TENANT_STATUS = postgresql.ENUM(
    'active', 'suspended', 'deleted',
    name='tenant_status_enum', create_type=False,
)
_TENANT_MEMBERSHIP_STATUS = postgresql.ENUM(
    'active', 'suspended', 'removed',
    name='tenant_membership_status_enum', create_type=False,
)
_TENANT_INVITATION_STATUS = postgresql.ENUM(
    'pending', 'accepted', 'expired', 'revoked',
    name='tenant_invitation_status_enum', create_type=False,
)
_TENANT_AUDIT_EVENT_TYPE = postgresql.ENUM(
    'tenant_created', 'tenant_updated', 'tenant_suspended', 'tenant_resumed',
    'tenant_deleted', 'cross_tenant_access_denied', 'tenant_boundary_violation',
    name='tenant_audit_event_type_enum', create_type=False,
)
_TENANT_AUDIT_ACTOR_TYPE = postgresql.ENUM(
    'platform_admin', 'tenant_admin', 'tenant_user', 'tenant_agent',
    'api_key', 'system',
    name='tenant_audit_actor_type_enum', create_type=False,
)
_PLATFORM_SETTING_CATEGORY = postgresql.ENUM(
    'tenancy', 'platform',
    name='platform_setting_category_enum', create_type=False,
)

_NEW_ENUM_TYPES = (
    _TENANT_ROLE,
    _TENANT_STATUS,
    _TENANT_MEMBERSHIP_STATUS,
    _TENANT_INVITATION_STATUS,
    _TENANT_AUDIT_EVENT_TYPE,
    _TENANT_AUDIT_ACTOR_TYPE,
    _PLATFORM_SETTING_CATEGORY,
)

# ── Direct tenant-scoped tables ──────────────────────────────────────────────
# Each gains: nullable tenant_id column + ix_<table>_tenant_id index +
# fk_<table>_tenant_id FK to tenants.id ON DELETE SET NULL. Join/child tables
# intentionally inherit scope via their parents and are not listed here.

_SCOPED_TABLES = (
    'access_request_batches',
    'access_requests',
    'agent_a2a_sessions',
    'agent_api_keys',
    'agent_data',
    'agent_data_types',
    'agent_identities',
    'agent_instances',
    'agent_jobs',
    'agent_outputs',
    'agent_roles',
    'agent_run_relationships',
    'agent_types',
    'conversation_sessions',
    'execution_log_entries',
    'groups',
    'guardrail_threshold_events',
    'identities',
    'identity_provider_config_audits',
    'identity_provider_configs',
    'intervene_requests',
    'mcp_servers',
    'model_availability',
    'model_configs',
    'model_guardrail_configurations',
    'model_guardrail_evaluations',
    'model_usage_postures',
    'notification_channels',
    'notification_events',
    'notification_logs',
    'policy_actions',
    'policy_resources',
    'policy_statements',
    'recipient_groups',
    'result_records',
    'roles',
    'runtime_tool_calls',
    'scheduled_jobs',
    'skills',
    'sops',
    'tag_definitions',
    'termination_requests',
)


def upgrade() -> None:
    # 1. New enum types
    for enum_type in _NEW_ENUM_TYPES:
        enum_type.create(op.get_bind(), checkfirst=True)

    # 2. New tenancy tables
    op.create_table('tenants',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('status', _TENANT_STATUS, nullable=False),
        sa.Column('admin_contact_role', _TENANT_ROLE, nullable=False),
        sa.Column('is_system_tenant', sa.Boolean(), nullable=False),
        sa.Column('is_onboarded', sa.Boolean(), nullable=False),
        sa.Column('admin_contact_name', sa.String(length=200), nullable=True),
        sa.Column('admin_contact_email', sa.String(length=320), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug')
    )
    # Exactly one implicit system tenant may adopt pre-existing data
    op.create_index(
        'uq_tenants_single_system_tenant', 'tenants', ['id'],
        unique=True, postgresql_where=sa.text('is_system_tenant = true'),
    )
    op.create_table('tenant_user_memberships',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('tenant_role', _TENANT_ROLE, nullable=False),
        sa.Column('status', _TENANT_MEMBERSHIP_STATUS, nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['platform_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'user_id', name='uq_tenant_membership_tenant_user')
    )
    op.create_index('ix_tenant_user_memberships_tenant_id', 'tenant_user_memberships', ['tenant_id'], unique=False)
    op.create_index('ix_tenant_user_memberships_user_id', 'tenant_user_memberships', ['user_id'], unique=False)
    op.create_table('tenant_invitations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('invited_by_id', sa.UUID(), nullable=True),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('tenant_role', _TENANT_ROLE, nullable=False),
        sa.Column('status', _TENANT_INVITATION_STATUS, nullable=False),
        sa.Column('is_single_use', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['invited_by_id'], ['tenant_user_memberships.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tenant_invitations_email', 'tenant_invitations', ['email'], unique=False)
    op.create_index('ix_tenant_invitations_tenant_id', 'tenant_invitations', ['tenant_id'], unique=False)
    op.create_table('tenant_audit_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('event_type', _TENANT_AUDIT_EVENT_TYPE, nullable=False),
        sa.Column('actor_type', _TENANT_AUDIT_ACTOR_TYPE, nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=True),
        sa.Column('actor_ip', sa.String(length=45), nullable=True),
        sa.Column('target_resource', sa.String(length=500), nullable=True),
        sa.Column('detail', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('is_security_relevant', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tenant_audit_events_created_at', 'tenant_audit_events', ['created_at'], unique=False)
    op.create_index('ix_tenant_audit_events_tenant_id', 'tenant_audit_events', ['tenant_id'], unique=False)
    op.create_table('platform_settings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('key', sa.String(length=200), nullable=False),
        sa.Column('value', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', _PLATFORM_SETTING_CATEGORY, nullable=False),
        sa.Column('is_tenant_agnostic', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key')
    )

    # 3. Nullable tenant scoping on every direct tenant-scoped entity.
    # All additions are nullable with no default — while multi-tenancy is
    # disabled the column stays NULL and platform behavior is unchanged.
    for table_name in _SCOPED_TABLES:
        op.add_column(table_name, sa.Column('tenant_id', sa.UUID(), nullable=True))
        op.create_index(f'ix_{table_name}_tenant_id', table_name, ['tenant_id'], unique=False)
        op.create_foreign_key(
            f'fk_{table_name}_tenant_id', table_name, 'tenants',
            ['tenant_id'], ['id'], ondelete='SET NULL',
        )


def downgrade() -> None:
    # 1. Remove tenant scoping columns (FK and index dropped explicitly by name)
    for table_name in _SCOPED_TABLES:
        op.drop_constraint(f'fk_{table_name}_tenant_id', table_name, type_='foreignkey')
        op.drop_index(f'ix_{table_name}_tenant_id', table_name=table_name)
        op.drop_column(table_name, 'tenant_id')

    # 2. Drop the new tenancy tables (children before parents)
    op.drop_table('platform_settings')
    op.drop_index('ix_tenant_audit_events_tenant_id', table_name='tenant_audit_events')
    op.drop_index('ix_tenant_audit_events_created_at', table_name='tenant_audit_events')
    op.drop_table('tenant_audit_events')
    op.drop_index('ix_tenant_invitations_tenant_id', table_name='tenant_invitations')
    op.drop_index('ix_tenant_invitations_email', table_name='tenant_invitations')
    op.drop_table('tenant_invitations')
    op.drop_index('ix_tenant_user_memberships_user_id', table_name='tenant_user_memberships')
    op.drop_index('ix_tenant_user_memberships_tenant_id', table_name='tenant_user_memberships')
    op.drop_table('tenant_user_memberships')
    op.drop_index('uq_tenants_single_system_tenant', table_name='tenants', postgresql_where=sa.text('is_system_tenant = true'))
    op.drop_table('tenants')

    # 3. Drop the new enum types
    for enum_type in reversed(_NEW_ENUM_TYPES):
        enum_type.drop(op.get_bind(), checkfirst=True)
