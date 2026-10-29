"""token expiry alerting

Revision ID: 6f2c9bce0cc6
Revises: c2d3e4f5a6b7
Create Date: 2026-10-27 10:30:24.135985

Reviewed and trimmed: unrelated autogenerate drift (super_admin_credentials
drop, tenant_id nullability churn, uq_agent_role_* constraints, IPC comments,
tenant_invitations index change) was removed — those are pre-existing model/DB
divergence handled elsewhere.

Enum handling: ``token_refresh_outcome_enum`` already exists (created for
token_refresh_logs.outcome) and is reused with create_type=False. The three
new enums are created explicitly so columns can reference them with
create_type=False.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6f2c9bce0cc6'
down_revision: str | None = 'c2d3e4f5a6b7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# New enum types created by this migration
_NEW_ENUMS = (
    ('token_health_state_enum', ('healthy', 'expiring', 'expired', 'unknown')),
    ('token_check_outcome_enum', ('passed', 'blocked')),
    ('token_health_target_kind_enum', ('agent_identity', 'mcp_session')),
)

# Pre-existing enum reused with create_type=False
_REFRESH_OUTCOME = postgresql.ENUM(
    'success', 'failure', name='token_refresh_outcome_enum', create_type=False
)
_HEALTH_STATE = postgresql.ENUM(
    'healthy', 'expiring', 'expired', 'unknown', name='token_health_state_enum', create_type=False
)
_CHECK_OUTCOME = postgresql.ENUM(
    'passed', 'blocked', name='token_check_outcome_enum', create_type=False
)
_TARGET_KIND = postgresql.ENUM(
    'agent_identity', 'mcp_session', name='token_health_target_kind_enum', create_type=False
)


def upgrade() -> None:
    for enum_name, values in _NEW_ENUMS:
        op.execute(
            "CREATE TYPE %s AS ENUM (%s)" % (enum_name, ", ".join("'%s'" % v for v in values))
        )

    op.create_table('token_health_checks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('agent_type_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('target_kind', _TARGET_KIND, nullable=False),
    sa.Column('target_id', sa.UUID(), nullable=False),
    sa.Column('health_state', _HEALTH_STATE, nullable=False),
    sa.Column('check_outcome', _CHECK_OUTCOME, nullable=False),
    sa.Column('message', sa.String(length=1000), nullable=False),
    sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_type_id'], ['agent_types.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['agent_jobs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_token_health_checks_checked_at', 'token_health_checks', ['checked_at'], unique=False)
    op.create_index('ix_token_health_checks_target', 'token_health_checks', ['target_kind', 'target_id'], unique=False)
    op.create_index('ix_token_health_checks_tenant_id', 'token_health_checks', ['tenant_id'], unique=False)

    op.add_column('agent_identities', sa.Column('refresh_token_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('agent_identities', sa.Column('last_token_refresh_outcome', _REFRESH_OUTCOME, nullable=True))
    op.add_column('agent_identities', sa.Column('token_health_state', _HEALTH_STATE, nullable=True))

    op.add_column('mcp_sessions', sa.Column('last_token_refresh_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mcp_sessions', sa.Column('last_token_refresh_outcome', _REFRESH_OUTCOME, nullable=True))
    op.add_column('mcp_sessions', sa.Column('token_health_state', _HEALTH_STATE, nullable=True))

    op.add_column('token_refresh_logs', sa.Column('mcp_session_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_token_refresh_logs_mcp_session_id',
        'token_refresh_logs', 'mcp_sessions', ['mcp_session_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_token_refresh_logs_mcp_session_id', 'token_refresh_logs', type_='foreignkey'
    )
    op.drop_column('token_refresh_logs', 'mcp_session_id')

    op.drop_column('mcp_sessions', 'token_health_state')
    op.drop_column('mcp_sessions', 'last_token_refresh_outcome')
    op.drop_column('mcp_sessions', 'last_token_refresh_at')

    op.drop_column('agent_identities', 'token_health_state')
    op.drop_column('agent_identities', 'last_token_refresh_outcome')
    op.drop_column('agent_identities', 'refresh_token_expires_at')

    op.drop_index('ix_token_health_checks_tenant_id', table_name='token_health_checks')
    op.drop_index('ix_token_health_checks_target', table_name='token_health_checks')
    op.drop_index('ix_token_health_checks_checked_at', table_name='token_health_checks')
    op.drop_table('token_health_checks')

    for enum_name, _values in reversed(_NEW_ENUMS):
        op.execute('DROP TYPE %s' % enum_name)
