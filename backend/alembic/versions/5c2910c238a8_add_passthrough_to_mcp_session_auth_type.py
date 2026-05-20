"""add passthrough to mcp session auth type

Revision ID: 5c2910c238a8
Revises: fcbe5b250e08
Create Date: 2026-05-12 13:49:06.759160

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5c2910c238a8'
down_revision: str | None = 'fcbe5b250e08'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add passthrough to the mcp_session_auth_type_enum
    # Note: ALTER TYPE ADD VALUE cannot be run inside a transaction in PostgreSQL
    # when the new value is used in the same transaction. Since we only add the value
    # here (no column updates), this is safe within a transaction on PostgreSQL 12+.
    op.execute("ALTER TYPE mcp_session_auth_type_enum ADD VALUE IF NOT EXISTS 'passthrough'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    # The 'passthrough' value will remain in the enum type on downgrade.
    pass
