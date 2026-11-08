"""add inactive to agent_client_status_enum

Revision ID: f1a2b3c4d5e6
Revises: e4cbbb651e80
Create Date: 2026-11-03 22:40:00.000000

Additive enum value: a client can be temporarily deactivated (``inactive``,
reversible) in addition to ``active`` and ``revoked`` (permanent).
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: str | None = 'e4cbbb651e80'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL 12+ permits ADD VALUE inside a transaction as long as the new
    # value is not used in the same transaction (it is not here).
    op.execute("ALTER TYPE agent_client_status_enum ADD VALUE IF NOT EXISTS 'inactive'")


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value; leave it in place.
    pass
