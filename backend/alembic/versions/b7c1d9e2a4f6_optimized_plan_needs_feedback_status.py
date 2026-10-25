"""optimized_plan_status_enum gains 'needs_feedback'.

Revision ID: b7c1d9e2a4f6
Revises: 93d25e577411
Create Date: 2026-10-23

Adds the ``needs_feedback`` value to ``optimized_plan_status_enum``: when the
Optimize & Verify refinement loop exhausts its attempts without a passing
composition, the plan lands in an explicit needs-feedback state (with the
failure recorded in ``verification_log`` / ``error``) so the user can steer
the next regeneration via feedback — instead of a silent ``failed``.
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c1d9e2a4f6"
down_revision: str | None = "93d25e577411"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot be rolled back inside a transaction on
    # some PostgreSQL versions; guarded with IF NOT EXISTS for idempotency.
    op.execute(
        "ALTER TYPE optimized_plan_status_enum "
        "ADD VALUE IF NOT EXISTS 'needs_feedback'"
    )


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value; downgrade is a no-op. Existing
    # 'needs_feedback' rows remain valid for the VARCHAR-backed enum.
    pass
