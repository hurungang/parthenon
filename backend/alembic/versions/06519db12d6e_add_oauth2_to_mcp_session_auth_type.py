"""add_oauth2_to_mcp_session_auth_type

Revision ID: 06519db12d6e
Revises: 10703a671de6
Create Date: 2026-05-04 14:07:22.445591

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '06519db12d6e'
down_revision: str | None = '10703a671de6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add oauth2 to the mcp_session_auth_type_enum
    # Note: ALTER TYPE ADD VALUE cannot be run inside a transaction in PostgreSQL
    op.execute("ALTER TYPE mcp_session_auth_type_enum ADD VALUE IF NOT EXISTS 'oauth2'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values
    # This would require recreating the enum and updating all dependent objects
    # For safety, we leave the oauth2 value in place even on downgrade
    pass
