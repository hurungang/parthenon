"""command prompts table

Revision ID: c41e7a9d2b3f
Revises: b7c1d9e2a4f6
Create Date: 2026-10-24 00:00:00.000000

Adds the ``command_prompts`` table — stored missions for command-driven special
agent executions (e.g. ``optimize-and-verify``). Control-Center-owned.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c41e7a9d2b3f'
down_revision: str | None = 'b7c1d9e2a4f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'command_prompts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('prompt_text', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )


def downgrade() -> None:
    op.drop_table('command_prompts')
