"""add_conversation_intervention_fields

Revision ID: 6d7e345f41b1
Revises: 6beca08c57cf
Create Date: 2026-06-15 14:23:58.770505

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6d7e345f41b1'
down_revision: str | None = '6beca08c57cf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_turn_type_enum = postgresql.ENUM(
    'message', 'intervene_request', 'intervene_response',
    name='turn_type_enum',
)


def upgrade() -> None:
    """Add turn_type and intervene_request_id to conversation_turns,
    and conversation_session_id and delegation_depth to intervene_requests."""
    # Create the enum type explicitly (it may already exist from model import)
    _turn_type_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'conversation_turns',
        sa.Column(
            'turn_type',
            _turn_type_enum,
            nullable=False,
            server_default='message',
        ),
    )
    op.add_column(
        'conversation_turns',
        sa.Column('intervene_request_id', postgresql.UUID(), nullable=True),
    )
    op.create_foreign_key(
        None, 'conversation_turns', 'intervene_requests',
        ['intervene_request_id'], ['id'], ondelete='SET NULL',
    )
    op.add_column(
        'intervene_requests',
        sa.Column('conversation_session_id', postgresql.UUID(), nullable=True),
    )
    op.create_foreign_key(
        None, 'intervene_requests', 'conversation_sessions',
        ['conversation_session_id'], ['id'], ondelete='SET NULL',
    )
    op.add_column(
        'intervene_requests',
        sa.Column('delegation_depth', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Reverse the upgrade — drop new columns, FKs, and enum."""
    # Drop FK on intervene_requests first (reversed from upgrade order)
    op.drop_constraint(None, 'intervene_requests', type_='foreignkey')
    op.drop_column('intervene_requests', 'delegation_depth')
    op.drop_column('intervene_requests', 'conversation_session_id')
    # Drop FK on conversation_turns
    op.drop_constraint(None, 'conversation_turns', type_='foreignkey')
    op.drop_column('conversation_turns', 'intervene_request_id')
    op.drop_column('conversation_turns', 'turn_type')
    # Drop the enum type
    _turn_type_enum.drop(op.get_bind(), checkfirst=True)
