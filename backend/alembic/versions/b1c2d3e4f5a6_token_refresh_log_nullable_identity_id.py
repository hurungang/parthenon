"""Relax TokenRefreshLog.agent_identity_id to nullable (token-expiry-alerting).

Session-targeted refresh audit rows carry ``mcp_session_id`` set and
``agent_identity_id`` NULL; the exactly-one-target check constraint now
enforces precisely one of the two per row.

Revision ID: b1c2d3e4f5a6
Revises: 6f2c9bce0cc6
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = '6f2c9bce0cc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the legacy OR-constraint if present (older environments may not
    # have it — autogenerate skipped name-bearing constraints there).
    op.execute(
        'ALTER TABLE token_refresh_logs DROP CONSTRAINT IF EXISTS ck_token_refresh_logs_has_target'
    )
    op.alter_column(
        'token_refresh_logs', 'agent_identity_id', existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_check_constraint(
        'ck_token_refresh_logs_has_target',
        'token_refresh_logs',
        "(CASE WHEN agent_identity_id IS NOT NULL THEN 1 ELSE 0 END + "
        "CASE WHEN mcp_session_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE token_refresh_logs DROP CONSTRAINT IF EXISTS ck_token_refresh_logs_has_target'
    )
    # Only re-apply NOT NULL when no session-targeted rows exist.
    op.execute(
        "UPDATE token_refresh_logs SET agent_identity_id = "
        "'00000000-0000-0000-0000-000000000000'::uuid "
        "WHERE agent_identity_id IS NULL"
    )
    op.alter_column(
        'token_refresh_logs', 'agent_identity_id', existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_check_constraint(
        'ck_token_refresh_logs_has_target',
        'token_refresh_logs',
        'agent_identity_id IS NOT NULL OR mcp_session_id IS NOT NULL',
    )
