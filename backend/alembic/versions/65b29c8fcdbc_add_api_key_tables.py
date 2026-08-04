"""add_api_key_tables

Revision ID: 65b29c8fcdbc
Revises: 7b5fe61d84d5
Create Date: 2026-07-30 22:49:24.106010

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '65b29c8fcdbc'
down_revision: str | None = '7b5fe61d84d5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('agent_api_keys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('agent_identity_id', sa.UUID(), nullable=False),
    sa.Column('agent_role_id', sa.UUID(), nullable=False),
    sa.Column('status', postgresql.ENUM('active', 'revoked', name='api_key_status_enum', create_type=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['agent_identity_id'], ['agent_identities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['agent_role_id'], ['agent_roles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['identities.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_identity_id', 'agent_role_id', name='uq_agent_api_keys_identity_role')
    )
    op.create_index('ix_agent_api_keys_key_hash', 'agent_api_keys', ['key_hash'], unique=False)
    op.create_index('ix_agent_api_keys_status', 'agent_api_keys', ['status'], unique=False)
    op.create_table('api_key_usage_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('api_key_id', sa.UUID(), nullable=False),
    sa.Column('action', postgresql.ENUM('validate', 'load_skills', 'tool_call', name='api_key_usage_action_enum', create_type=True), nullable=False),
    sa.Column('tool_name', sa.String(length=256), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['api_key_id'], ['agent_api_keys.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_api_key_usage_logs_action', 'api_key_usage_logs', ['action'], unique=False)
    op.create_index('ix_api_key_usage_logs_api_key_id', 'api_key_usage_logs', ['api_key_id'], unique=False)
    op.create_index('ix_api_key_usage_logs_timestamp', 'api_key_usage_logs', ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_api_key_usage_logs_timestamp', table_name='api_key_usage_logs')
    op.drop_index('ix_api_key_usage_logs_api_key_id', table_name='api_key_usage_logs')
    op.drop_index('ix_api_key_usage_logs_action', table_name='api_key_usage_logs')
    op.drop_table('api_key_usage_logs')
    op.drop_index('ix_agent_api_keys_status', table_name='agent_api_keys')
    op.drop_index('ix_agent_api_keys_key_hash', table_name='agent_api_keys')
    op.drop_table('agent_api_keys')
