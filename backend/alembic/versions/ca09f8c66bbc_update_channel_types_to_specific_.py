"""update_channel_types_to_specific_providers

Revision ID: ca09f8c66bbc
Revises: 4cd1efec6451
Create Date: 2026-05-14 14:52:30.011891

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'ca09f8c66bbc'
down_revision: str | None = '4cd1efec6451'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Update the channel_type_enum from generic types to specific providers.
    
    Old values: SMTP, EMAIL_API, WEBHOOK, MESSENGER
    New values: SMTP, SENDGRID, RESEND, TEAMS_WEBHOOK, SLACK_WEBHOOK
    """
    # Add new enum values to the existing enum
    op.execute("ALTER TYPE channel_type_enum ADD VALUE IF NOT EXISTS 'SENDGRID'")
    op.execute("ALTER TYPE channel_type_enum ADD VALUE IF NOT EXISTS 'RESEND'")
    op.execute("ALTER TYPE channel_type_enum ADD VALUE IF NOT EXISTS 'TEAMS_WEBHOOK'")
    op.execute("ALTER TYPE channel_type_enum ADD VALUE IF NOT EXISTS 'SLACK_WEBHOOK'")
    
    # Note: We cannot remove old enum values in PostgreSQL without recreating the type.
    # In a real migration with existing data, you would:
    # 1. Update existing rows to use new values
    # 2. Recreate the enum type (create new, alter columns, drop old)
    # 
    # For now, we'll leave the old values in the enum but document that they're deprecated.
    # Since this is a new feature with no production data yet, this is acceptable.


def downgrade() -> None:
    """
    Downgrade is not supported for enum value additions.
    PostgreSQL does not allow removing enum values easily.
    """
    pass
