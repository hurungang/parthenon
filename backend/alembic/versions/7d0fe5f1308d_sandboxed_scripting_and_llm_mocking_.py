"""sandboxed scripting and llm mocking schema

Revision ID: 7d0fe5f1308d
Revises: c3d4e5f6a7b8
Create Date: 2026-10-20 10:29:12.438304

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7d0fe5f1308d'
down_revision: str | None = 'c3d4e5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enums carried on columns with create_type=False — types are created
# explicitly below (project convention: AGENTS.md enum rule).
sandbox_validation_status = postgresql.ENUM(
    'pending', 'passed', 'failed',
    name='sandbox_validation_status_enum', create_type=False,
)
mock_interaction_kind = postgresql.ENUM(
    'agent_loop', 'semantic_bridge', 'decision_step',
    name='mock_interaction_kind_enum', create_type=False,
)

_ENUM_DEFS = {
    'sandbox_validation_status_enum': "('pending', 'passed', 'failed')",
    'mock_interaction_kind_enum': "('agent_loop', 'semantic_bridge', 'decision_step')",
}


def _create_enum_types() -> None:
    for name, values in _ENUM_DEFS.items():
        op.execute(
            f"DO $$ BEGIN\n"
            f"    CREATE TYPE {name} AS ENUM {values};\n"
            f"EXCEPTION\n"
            f"    WHEN duplicate_object THEN NULL;\n"
            f"END $$;"
        )


def _drop_enum_types() -> None:
    for name in _ENUM_DEFS:
        op.execute(f"DROP TYPE IF EXISTS {name}")


def _extend_fallback_trigger_reason() -> None:
    # Parameterized DDL is unsupported for ALTER TYPE — string-format the
    # identifiers/values (no bound params).
    op.execute("ALTER TYPE fallback_trigger_reason_enum ADD VALUE IF NOT EXISTS 'sandbox_violation'")
    op.execute("ALTER TYPE fallback_trigger_reason_enum ADD VALUE IF NOT EXISTS 'resource_limit_exceeded'")


def _rebuild_fallback_trigger_reason_without_new_values() -> None:
    """PostgreSQL cannot DROP VALUE — rebuild the enum with the original set.

    Documented enum-rebuild pattern: create new type, migrate the column,
    drop the old type, rename the new one.
    """
    op.execute("CREATE TYPE fallback_trigger_reason_enum_new AS ENUM ('execution_error', 'tool_schema_mismatch', 'output_validation_failure')")
    op.execute("ALTER TABLE fallback_events ALTER COLUMN trigger_reason TYPE fallback_trigger_reason_enum_new USING trigger_reason::text::fallback_trigger_reason_enum_new")
    op.execute("DROP TYPE fallback_trigger_reason_enum")
    op.execute("ALTER TYPE fallback_trigger_reason_enum_new RENAME TO fallback_trigger_reason_enum")


def upgrade() -> None:
    _create_enum_types()
    _extend_fallback_trigger_reason()

    # script_versions — sandboxed Python source + per-version resource caps
    op.add_column('script_versions', sa.Column('python_source', sa.Text(), nullable=True))
    op.add_column('script_versions', sa.Column('cpu_limit_seconds', sa.Integer(), nullable=True))
    op.add_column('script_versions', sa.Column('memory_limit_mb', sa.Integer(), nullable=True))
    op.add_column('script_versions', sa.Column('wall_time_limit_seconds', sa.Integer(), nullable=True))
    op.add_column('script_versions', sa.Column('sandbox_validation_status', sandbox_validation_status, server_default='pending', nullable=False))
    op.add_column('script_versions', sa.Column('sandbox_validation_reason', sa.Text(), nullable=True))

    # verification_runs — sandbox-compliance evidence
    op.add_column('verification_runs', sa.Column('sandbox_check_passed', sa.Boolean(), nullable=True))

    # script_execution_records — accurate token accounting + sandbox failure provenance
    op.add_column('script_execution_records', sa.Column('tokens_saved_actual', sa.Integer(), nullable=True))
    op.add_column('script_execution_records', sa.Column('sandbox_termination', sa.Boolean(), nullable=True))
    op.add_column('script_execution_records', sa.Column('sandbox_violation_detail', sa.Text(), nullable=True))

    # llm_mock_recordings — new tenant-scoped LLM mock recordings table
    op.create_table('llm_mock_recordings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=True),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('recording_key', sa.String(length=200), nullable=False),
    sa.Column('model_identifier', sa.String(length=200), nullable=False),
    sa.Column('interaction_kind', mock_interaction_kind, nullable=False),
    sa.Column('request_payload', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('response_payload', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('usage_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('recorded_by', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['agent_jobs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'recording_key', 'model_identifier', name='uq_llm_mock_recordings_tenant_key_model')
    )
    op.create_index('ix_llm_mock_recordings_tenant_id', 'llm_mock_recordings', ['tenant_id'])
    op.create_index('ix_llm_mock_recordings_session_id', 'llm_mock_recordings', ['session_id'])
    op.create_index('ix_llm_mock_recordings_recording_key', 'llm_mock_recordings', ['recording_key'])


def downgrade() -> None:
    op.drop_index('ix_llm_mock_recordings_recording_key', table_name='llm_mock_recordings')
    op.drop_index('ix_llm_mock_recordings_session_id', table_name='llm_mock_recordings')
    op.drop_index('ix_llm_mock_recordings_tenant_id', table_name='llm_mock_recordings')
    op.drop_table('llm_mock_recordings')

    op.drop_column('script_execution_records', 'sandbox_violation_detail')
    op.drop_column('script_execution_records', 'sandbox_termination')
    op.drop_column('script_execution_records', 'tokens_saved_actual')

    op.drop_column('verification_runs', 'sandbox_check_passed')

    op.drop_column('script_versions', 'sandbox_validation_reason')
    op.drop_column('script_versions', 'sandbox_validation_status')
    op.drop_column('script_versions', 'wall_time_limit_seconds')
    op.drop_column('script_versions', 'memory_limit_mb')
    op.drop_column('script_versions', 'cpu_limit_seconds')
    op.drop_column('script_versions', 'python_source')

    # Remove enum values via the documented enum-rebuild pattern
    # (PostgreSQL cannot DROP VALUE).
    _rebuild_fallback_trigger_reason_without_new_values()
    _drop_enum_types()
