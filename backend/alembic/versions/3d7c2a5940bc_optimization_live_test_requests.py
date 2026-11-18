"""optimization live test requests

Revision ID: 3d7c2a5940bc
Revises: 992bbc77bf6a
Create Date: 2026-11-15 14:19:54.651337

Additive, reversible persistence for the conversational optimizer's live-test
ledger:

* new ``optimization_live_tests`` table (``OptimizationLiveTestRequest``) and
  its ``optimization_live_test_status_enum``;
* one nullable ``runtime_tool_calls.optimization_live_test_request_id`` FK
  (``ON DELETE SET NULL``) marking the raw tool calls of an operator-approved,
  single-use live test.

Notes:
- The enum type is new, so the table creation owns it: ``sa.Enum`` is declared
  inline on the ``status`` column (no standalone/parameterised ``CREATE TYPE``
  or ``ALTER TYPE`` DDL). ``downgrade()`` drops the type defensively (guarded)
  after the table is gone, so ``downgrade -1`` / ``upgrade head`` round-trips.
- No ``conversation_sessions`` change (``channel`` is an existing free-form
  string; ``agent_type_id`` is the subject), no backfill, no column drop.
- Autogenerate also reported unrelated pre-existing drift (tenant_id
  nullability, ``super_admin_credentials``, identity-provider comments,
  ``tenant_invitations`` index uniqueness, role unique constraints); this
  revision was hand-reviewed and limited to the two objects above.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3d7c2a5940bc'
down_revision: str | None = '992bbc77bf6a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STATUS_ENUM_NAME = 'optimization_live_test_status_enum'
_TOOL_CALL_FK_NAME = 'runtime_tool_calls_optimization_live_test_request_id_fkey'


def upgrade() -> None:
    op.create_table(
        'optimization_live_tests',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('conversation_session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('target_agent_type_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('request_turn_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('intervene_request_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('resume_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.Enum(
            'pending', 'approved', 'executed', 'failed', 'denied', 'expired', 'cancelled',
            name=_STATUS_ENUM_NAME,
        ), nullable=False),
        sa.Column('requested_operations', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('executed_operations', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('execution_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('execution_finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_session_id'], ['conversation_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['intervene_request_id'], ['intervene_requests.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['request_turn_id'], ['conversation_turns.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['resume_id'], ['conversation_turn_resumes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['target_agent_type_id'], ['agent_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_optimization_live_tests_status_expires_at',
        'optimization_live_tests', ['status', 'expires_at'], unique=False,
    )
    op.create_index(
        'ix_optimization_live_tests_tenant_session',
        'optimization_live_tests', ['tenant_id', 'conversation_session_id'], unique=False,
    )

    op.add_column(
        'runtime_tool_calls',
        sa.Column('optimization_live_test_request_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        _TOOL_CALL_FK_NAME, 'runtime_tool_calls', 'optimization_live_tests',
        ['optimization_live_test_request_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(_TOOL_CALL_FK_NAME, 'runtime_tool_calls', type_='foreignkey')
    op.drop_column('runtime_tool_calls', 'optimization_live_test_request_id')

    op.drop_index('ix_optimization_live_tests_tenant_session', table_name='optimization_live_tests')
    op.drop_index('ix_optimization_live_tests_status_expires_at', table_name='optimization_live_tests')
    op.drop_table('optimization_live_tests')

    # The type was created with the table; drop it defensively so the revision
    # can be re-applied (downgrade -1 / upgrade head round-trip).
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{_STATUS_ENUM_NAME}') "
        f"THEN DROP TYPE {_STATUS_ENUM_NAME}; END IF; END $$;"
    )
