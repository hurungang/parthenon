"""add_unit_to_model_guardrail_configurations

Revision ID: b3c9d4e5f6a7
Revises: aad0f4a3b3bc
Create Date: 2026-06-01 15:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3c9d4e5f6a7'
down_revision: str | None = 'aad0f4a3b3bc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE model_usage_unit_enum AS ENUM ('tokens', 'k')")
    op.add_column(
        'model_guardrail_configurations',
        sa.Column(
            'unit',
            sa.Enum('tokens', 'k', name='model_usage_unit_enum', create_type=False),
            nullable=False,
            server_default='k',
        ),
    )


def downgrade() -> None:
    op.drop_column('model_guardrail_configurations', 'unit')
    op.execute('DROP TYPE IF EXISTS model_usage_unit_enum')
