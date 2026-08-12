"""add_recipient_properties_to_group_channel_mappings

Revision ID: aac57a284ad2
Revises: ca09f8c66bbc
Create Date: 2026-05-14 19:17:36.123251

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'aac57a284ad2'
down_revision: str | None = 'ca09f8c66bbc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add recipient_properties JSON column to group_channel_mappings."""
    op.add_column(
        'group_channel_mappings',
        sa.Column('recipient_properties', sa.dialects.postgresql.JSON(astext_type=sa.Text()), nullable=True,
                  comment='Channel-specific recipient data (e.g., email addresses, webhook IDs)')
    )


def downgrade() -> None:
    """Remove recipient_properties column from group_channel_mappings."""
    op.drop_column('group_channel_mappings', 'recipient_properties')
