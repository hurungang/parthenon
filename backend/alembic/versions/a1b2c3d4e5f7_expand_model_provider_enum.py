"""expand_model_provider_enum

Phase 3.x (change: expand-model-config-providers): extend
``model_provider_enum`` with eight additional API-key-based LLM
provider keys — ``gemini``, ``mistral``, ``cohere``, ``groq``,
``together``, ``fireworks``, ``perplexity``, ``deepseek`` — so the
runtime dispatcher and the model configurations UI can recognise the
twelve-provider catalogue end-to-end. The change is purely additive
at the enum level; no ``ModelConfig`` row is rewritten.

Revision ID: a1b2c3d4e5f7
Revises: f4a5b6c7d8e9
Create Date: 2026-06-03 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: str | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_PROVIDER_VALUES = (
    "gemini",
    "mistral",
    "cohere",
    "groq",
    "together",
    "fireworks",
    "perplexity",
    "deepseek",
)


def upgrade() -> None:
    # Postgres-style ALTER TYPE for ``model_provider_enum``.
    # Each new value is added additively and idempotently; the test
    # suite (which uses SQLite) tolerates the no-op. Per
    # ``AGENTS.md`` migration guidance, the statement is not
    # parameterised and each ``ADD VALUE`` runs in its own
    # ``op.execute()`` call (Postgres ``ALTER TYPE ... ADD VALUE``
    # cannot run inside an explicit transaction block on older PG
    # versions).
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        for value in _NEW_PROVIDER_VALUES:
            op.execute(
                sa.text(
                    f"ALTER TYPE model_provider_enum "
                    f"ADD VALUE IF NOT EXISTS '{value}'"
                )
            )
    else:
        # SQLite stores enums as plain strings — nothing to alter.
        pass


def downgrade() -> None:
    # Postgres cannot drop enum values in use without a table rewrite.
    # For an additive change we leave the values in place on downgrade;
    # a future cleanup migration can drop them after verifying no rows
    # reference them.
    pass
