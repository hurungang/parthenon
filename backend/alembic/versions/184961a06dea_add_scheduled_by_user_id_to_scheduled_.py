"""add scheduled_by_user_id to scheduled_jobs

Revision ID: 184961a06dea
Revises: b5403591994f
Create Date: 2026-09-02 09:15:21.010605

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '184961a06dea'
down_revision: str | None = 'b5403591994f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'scheduled_jobs',
        sa.Column('scheduled_by_user_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_scheduled_jobs_scheduled_by_user_id_identities',
        'scheduled_jobs',
        'identities',
        ['scheduled_by_user_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_scheduled_jobs_scheduled_by_user_id_identities',
        'scheduled_jobs',
        type_='foreignkey',
    )
    op.drop_column('scheduled_jobs', 'scheduled_by_user_id')
