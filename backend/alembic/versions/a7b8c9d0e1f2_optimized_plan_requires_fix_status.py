"""optimized_plan_status_enum gains 'requires_fix'.

Revision ID: a7b8c9d0e1f2
Revises: 7127b840ae80
Create Date: 2026-11-11

Separates optimization from execution: a plan that was produced by an
optimization run (``ready``) can later fail in real execution and fall back to
the model-driven path. That state is now recorded on the SAME plan row as
``requires_fix`` (execution-side), distinct from ``needs_feedback``
(authoring-side: verification could not complete).

Additive enum change only. The failed-execution attribution is a read-only
traversal (FallbackEvent -> ScriptExecutionRecord -> ScriptVersion ->
ScriptDefinition.source_optimized_plan_id) and the evidence lives in the
existing ``feedback_comments`` JSON, so no column/table/FK is added.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: str | None = '7127b840ae80'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The enum type already exists (created by the model import), so this is a
    # plain string-formatted DDL statement — no bound parameters, no sa.Enum.
    # PostgreSQL 12+ permits ADD VALUE inside a transaction as long as the new
    # value is not used in the same transaction (it is not here).
    op.execute(
        "ALTER TYPE optimized_plan_status_enum "
        "ADD VALUE IF NOT EXISTS 'requires_fix'"
    )


def downgrade() -> None:
    # PostgreSQL cannot remove a single enum value without recreating the type
    # (and rewriting every dependent column). The value is additive and inert
    # when unused, so downgrade is intentionally a documented no-op.
    pass
