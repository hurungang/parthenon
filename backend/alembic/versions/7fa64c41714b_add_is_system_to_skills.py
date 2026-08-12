"""add_is_system_to_skills

Revision ID: 7fa64c41714b
Revises: c5d6e7f8a9b0
Create Date: 2026-06-05 11:44:00.919340

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7fa64c41714b'
down_revision: str | None = 'c5d6e7f8a9b0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('skills', sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    # Backfill existing skills: mark the default seed skills as system skills
    # Only mark hyphen-format skills as system; old underscore-format skills
    # (save_result, send_notification, get_recipient_group) are NOT system so
    # they can be manually deleted by the user.
    op.execute("UPDATE skills SET is_system = true WHERE name IN ('save-result', 'send-notification', 'get-recipient-group')")
    op.alter_column('skills', 'is_system', server_default=None)


def downgrade() -> None:
    op.drop_column('skills', 'is_system')
