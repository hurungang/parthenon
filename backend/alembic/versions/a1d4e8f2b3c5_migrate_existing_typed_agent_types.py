"""migrate existing typed agent types to AgentDataType

Revision ID: a1d4e8f2b3c5
Revises: 3131c85e74e0
Create Date: 2026-06-20 18:45:00.000000

Data migration:
  Finds agent types where output_type = 'typed' and output_schema is non-null,
  creates AgentDataType entries from unique schemas, and links agent types
  via output_data_type_id.
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import json
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision: str = "a1d4e8f2b3c5"
down_revision: str | None = "3131c85e74e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _make_slug(name: str) -> str:
    """Generate a URL-friendly slug from a name."""
    slug = name.lower().replace(" ", "-").replace("_", "-")
    # Remove non-alphanumeric chars except hyphens
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    # Collapse multiple hyphens
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "unnamed-schema"


VALID_FIELD_TYPES = frozenset({"string", "number", "boolean", "date", "enum"})


def _schema_fingerprint(schema: dict) -> str:
    """Generate a stable fingerprint for a schema dict for deduplication."""
    normalized = json.dumps(schema, sort_keys=True, default=str)
    return str(hash(normalized))


def upgrade() -> None:
    """Create AgentDataType entries from existing typed agent types and link them."""
    connection = op.get_bind()

    # Step 1: Find all agent types with output_type='typed' and non-null output_schema
    rows = connection.execute(
        text(
            "SELECT id, name, output_schema FROM agent_types "
            "WHERE output_type = 'typed' AND output_schema IS NOT NULL"
        )
    ).fetchall()

    if not rows:
        op.execute("SELECT 1 WHERE FALSE")  # No-op; no typed agent types to migrate
        return

    # Step 2: Deduplicate by schema fingerprint
    schema_map: dict[str, dict] = {}  # fingerprint -> schema dict
    agent_type_map: dict[str, list[dict]] = {}  # fingerprint -> list of {id, name}

    for row in rows:
        agent_id, agent_name, output_schema = row
        schema = output_schema if isinstance(output_schema, dict) else {}

        if not schema:
            continue

        fp = _schema_fingerprint(schema)
        if fp not in schema_map:
            schema_map[fp] = schema
            agent_type_map[fp] = []
        agent_type_map[fp].append({"id": str(agent_id), "name": str(agent_name)})

    # Step 3: Create AgentDataType entries for unique schemas
    for fp, schema in schema_map.items():
        # Derive a data type name from the first agent type name
        first_agent = agent_type_map[fp][0]
        dt_name = first_agent["name"]
        dt_slug = _make_slug(dt_name)

        # Ensure unique slug by appending short UUID fragment
        short_id = uuid.uuid4().hex[:8]
        dt_slug = f"{dt_slug}-{short_id}"

        # Extract field definitions from the output_schema
        fields = []
        schema_properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        schema_required = schema.get("required", []) if isinstance(schema, dict) else []

        for field_name, field_def in schema_properties.items():
            if not isinstance(field_def, dict):
                continue
            field_type = field_def.get("type", "string")
            if field_type not in VALID_FIELD_TYPES:
                continue  # Skip unsupported JSON Schema types (array, object, etc.)
            field_entry: dict = {
                "name": field_name,
                "type": field_type,
                "required": field_name in schema_required if isinstance(schema_required, list) else False,
            }
            if field_type == "enum" and "enum" in field_def:
                field_entry["enum_values"] = field_def["enum"]
            if "default" in field_def:
                field_entry["default"] = field_def["default"]
            fields.append(field_entry)

        if not fields:
            # Fallback: create a single "value" field
            fields = [{"name": "value", "type": "string", "required": True}]

        now = datetime.now(timezone.utc)
        dt_id = uuid.uuid4()

        # Insert the AgentDataType row
        connection.execute(
            text(
                "INSERT INTO agent_data_types (id, name, slug, description, fields, created_at, updated_at) "
                "VALUES (:id, :name, :slug, :description, :fields, :created_at, :updated_at)"
            ),
            {
                "id": dt_id,
                "name": dt_name,
                "slug": dt_slug,
                "description": f"Auto-migrated from agent type '{first_agent['name']}'",
                "fields": json.dumps(fields),
                "created_at": now,
                "updated_at": now,
            },
        )

        # Step 4: Link agent types to the new data type
        for agent_info in agent_type_map[fp]:
            connection.execute(
                text(
                    "UPDATE agent_types SET output_data_type_id = :data_type_id "
                    "WHERE id = :agent_id"
                ),
                {
                    "data_type_id": dt_id,
                    "agent_id": agent_info["id"],
                },
            )


def downgrade() -> None:
    """Revert the data migration — unset output_data_type_id and remove created data types."""
    connection = op.get_bind()

    # Find all auto-migrated data types (description starts with "Auto-migrated")
    rows = connection.execute(
        text(
            "SELECT id FROM agent_data_types "
            "WHERE description LIKE 'Auto-migrated from agent type%'"
        )
    ).fetchall()

    for row in rows:
        dt_id = row[0]
        # Unlink agent types
        connection.execute(
            text(
                "UPDATE agent_types SET output_data_type_id = NULL "
                "WHERE output_data_type_id = :dt_id"
            ),
            {"dt_id": dt_id},
        )
        # Delete the data type
        connection.execute(
            text("DELETE FROM agent_data_types WHERE id = :dt_id"),
            {"dt_id": dt_id},
        )
