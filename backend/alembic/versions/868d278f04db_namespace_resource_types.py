"""namespace_resource_types

Revision ID: 868d278f04db
Revises: 9d7152156e11
Create Date: 2026-07-03 23:53:50.460945

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '868d278f04db'
down_revision: str | None = '9d7152156e11'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mapping of legacy flat values to namespace replacements.
_LEGACY_MAP: dict[str, str] = {
    "*": "*::*",
    "agent": "agent::management",
    "role": "agent::roles",
    "skill": "agent::skills",
    "intervene": "agent::human_intervention",
    "scheduling": "agent::schedules",
    "mcp_server": "integration::mcp_hub",
    "notification": "integration::notifications",
    "data_type": "agent::data_types",
    "conversation": "agent::trails",
    "result": "agent::trails",
    "permissions": "system::permissions",
    "group": "system::permissions",
    "user": "system::permissions",
    "tag": "system::permissions",
    "access_request": "system::permissions",
}

# Reverse mapping for downgrade (many:1 consolidations are lossy).
_REVERSE_MAP: dict[str, str] = {
    "*::*": "*",
    "agent::management": "agent",
    "agent::roles": "role",
    "agent::skills": "skill",
    "agent::human_intervention": "intervene",
    "agent::schedules": "scheduling",
    "integration::mcp_hub": "mcp_server",
    "integration::notifications": "notification",
    "agent::data_types": "data_type",
    "agent::trails": "conversation",
    "system::permissions": "permissions",
}


def _data_upgrade() -> None:
    conn = op.get_bind()
    for old_val, new_val in _LEGACY_MAP.items():
        conn.execute(
            sa.text(
                "UPDATE policy_statements SET module = :new_val "
                "WHERE module = :old_val AND module NOT LIKE '%::%'"
            ),
            {"old_val": old_val, "new_val": new_val},
        )
        conn.execute(
            sa.text(
                "UPDATE policy_resources SET resource_type = :new_val "
                "WHERE resource_type = :old_val AND resource_type NOT LIKE '%::%'"
            ),
            {"old_val": old_val, "new_val": new_val},
        )


def _data_downgrade() -> None:
    conn = op.get_bind()
    for old_val, new_val in _REVERSE_MAP.items():
        conn.execute(
            sa.text(
                "UPDATE policy_statements SET module = :new_val "
                "WHERE module = :old_val AND module LIKE '%::%'"
            ),
            {"old_val": old_val, "new_val": new_val},
        )
        conn.execute(
            sa.text(
                "UPDATE policy_resources SET resource_type = :new_val "
                "WHERE resource_type = :old_val AND resource_type LIKE '%::%'"
            ),
            {"old_val": old_val, "new_val": new_val},
        )


def upgrade() -> None:
    _data_upgrade()


def downgrade() -> None:
    _data_downgrade()
