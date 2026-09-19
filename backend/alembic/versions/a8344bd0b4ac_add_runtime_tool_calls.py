"""add runtime_tool_calls

Revision ID: a8344bd0b4ac
Revises: 184961a06dea
Create Date: 2026-09-02 17:58:59.858312

Additive-only migration: creates the ``runtime_tool_calls`` table used by
Agent Runtime to record every tool execution (MCP / system / A2A) for the
Agent Runtime Monitor.  ``session_id`` is polymorphic (agent job id OR
conversation id) and intentionally has no foreign key.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a8344bd0b4ac'
down_revision: str | None = '184961a06dea'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'runtime_tool_calls',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column(
            'session_kind',
            sa.Enum('agent', 'conversation', name='runtime_tool_call_session_kind_enum'),
            nullable=False,
        ),
        sa.Column('tool_name', sa.String(length=400), nullable=False),
        sa.Column(
            'route_type',
            sa.Enum('system', 'mcp', 'a2a', name='runtime_tool_call_route_type_enum'),
            nullable=False,
        ),
        sa.Column('mcp_slug', sa.String(length=100), nullable=True),
        sa.Column(
            'status',
            sa.Enum('success', 'error', name='runtime_tool_call_status_enum'),
            nullable=False,
        ),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_runtime_tool_calls_session', 'runtime_tool_calls', ['session_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_runtime_tool_calls_session', table_name='runtime_tool_calls')
    op.drop_table('runtime_tool_calls')
    op.execute('DROP TYPE IF EXISTS runtime_tool_call_session_kind_enum')
    op.execute('DROP TYPE IF EXISTS runtime_tool_call_route_type_enum')
    op.execute('DROP TYPE IF EXISTS runtime_tool_call_status_enum')
