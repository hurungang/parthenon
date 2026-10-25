"""fully_scripted flags on agent plans and script definitions

Revision ID: 38b5903c0c22
Revises: 7d0fe5f1308d
Create Date: 2026-10-20 22:15:19.037120

Adds the execution-semantics flags for the script-as-tool product decision:
- ``agent_plans.fully_scripted`` — plan-generation LLM marks plans that a
  SINGLE end-to-end script can serve with zero LLM.
- ``script_definitions.fully_scripted`` — only such definitions are served
  directly by the dispatcher; all other scripts are invocable virtual tools
  (``script____<name>``).

NOTE: reviewed by hand — unrelated autogenerate drift (tenant_id nullability,
legacy constraints) intentionally excluded.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '38b5903c0c22'
down_revision: str | None = '7d0fe5f1308d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('agent_plans', sa.Column('fully_scripted', sa.Boolean(), nullable=True))
    op.add_column(
        'script_definitions',
        sa.Column('fully_scripted', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('script_definitions', 'fully_scripted')
    op.drop_column('agent_plans', 'fully_scripted')
