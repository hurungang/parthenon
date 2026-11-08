"""third-party agent integration clients

Revision ID: e4cbbb651e80
Revises: a1c3e5d70427
Create Date: 2026-11-03 20:18:56.276476

Additive-only migration: creates the ``agent_clients`` and
``agent_client_usage_logs`` tables for third-party agent integration. A client
is an access grant bound to one agent type (input-interface only), distinct from
an ``AgentApiKey`` (identity credential).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e4cbbb651e80'
down_revision: str | None = 'a1c3e5d70427'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'agent_clients',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=200), nullable=False),
        sa.Column('agent_type_id', sa.UUID(), nullable=False),
        sa.Column('key_type', sa.Enum('secret', 'publishable', name='agent_client_key_type_enum'), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('key_prefix', sa.String(length=16), nullable=False),
        sa.Column('status', sa.Enum('active', 'revoked', name='agent_client_status_enum'), nullable=False),
        sa.Column('white_label_theme', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('allowed_origins', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('rate_limit', sa.Integer(), nullable=True),
        sa.Column('rate_limit_window', sa.Enum('per_minute', 'per_hour', 'per_day', name='agent_client_rate_limit_window_enum'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_type_id'], ['agent_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['identities.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_agent_clients_tenant_name'),
        sa.UniqueConstraint('tenant_id', 'slug', name='uq_agent_clients_tenant_slug'),
    )
    op.create_index('ix_agent_clients_agent_type_id', 'agent_clients', ['agent_type_id'], unique=False)
    op.create_index('ix_agent_clients_key_hash', 'agent_clients', ['key_hash'], unique=False)
    op.create_index('ix_agent_clients_tenant_id', 'agent_clients', ['tenant_id'], unique=False)
    op.create_table(
        'agent_client_usage_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('client_id', sa.UUID(), nullable=False),
        sa.Column('action', sa.Enum('conversation_turn', 'submit_request', name='agent_client_action_enum'), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['agent_clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_client_usage_logs_action', 'agent_client_usage_logs', ['action'], unique=False)
    op.create_index('ix_agent_client_usage_logs_client_id', 'agent_client_usage_logs', ['client_id'], unique=False)
    op.create_index('ix_agent_client_usage_logs_timestamp', 'agent_client_usage_logs', ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_agent_client_usage_logs_timestamp', table_name='agent_client_usage_logs')
    op.drop_index('ix_agent_client_usage_logs_client_id', table_name='agent_client_usage_logs')
    op.drop_index('ix_agent_client_usage_logs_action', table_name='agent_client_usage_logs')
    op.drop_table('agent_client_usage_logs')
    op.drop_index('ix_agent_clients_tenant_id', table_name='agent_clients')
    op.drop_index('ix_agent_clients_key_hash', table_name='agent_clients')
    op.drop_index('ix_agent_clients_agent_type_id', table_name='agent_clients')
    op.drop_table('agent_clients')
    op.execute('DROP TYPE IF EXISTS agent_client_action_enum')
    op.execute('DROP TYPE IF EXISTS agent_client_rate_limit_window_enum')
    op.execute('DROP TYPE IF EXISTS agent_client_status_enum')
    op.execute('DROP TYPE IF EXISTS agent_client_key_type_enum')
