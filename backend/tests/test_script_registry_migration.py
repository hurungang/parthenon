"""Migration checks for the script registry & execution tables.

Per AGENTS.md, schema changes ship as Alembic migrations. The full
upgrade/downgrade round-trip runs in CI against PostgreSQL; these tests
assert the structural invariants that must hold in the migration source:

- The migration creates all six script tables
- ENUMs use ``postgresql.ENUM(..., create_type=False)`` (AGENTS.md rule:
  enums are created by model import, not by the migration)
- The migration is reversible (a downgrade() body exists)
"""
from __future__ import annotations

from pathlib import Path

import pytest

ALEMBIC_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

EXPECTED_TABLES = (
    "script_definitions",
    "script_versions",
    "verification_runs",
    "fallback_events",
    "script_execution_records",
)

# The refinement removed execution modes — the drop migration must remove the
# table from the base migration's schema and add repair structures.
DROPPED_TABLES = ("execution_mode_configurations",)
FOLLOW_UP_TABLES = ("repair_attempts",)


def _migration_source() -> str:
    matches = [
        p
        for p in ALEMBIC_VERSIONS.glob("*.py")
        if "script_registry_and_execution" in p.name
    ]
    assert matches, "script registry migration file not found"
    return matches[0].read_text(encoding="utf-8")


def _drop_migration_source() -> str:
    matches = [
        p
        for p in ALEMBIC_VERSIONS.glob("*.py")
        if "drop_execution_mode_configuration" in p.name
    ]
    assert matches, "drop-execution-mode migration file not found"
    return matches[0].read_text(encoding="utf-8")


class TestScriptRegistryMigration:
    def test_migration_file_exists(self):
        matches = list(ALEMBIC_VERSIONS.glob("*script_registry_and_execution*.py"))
        assert matches

    @pytest.mark.parametrize("table", EXPECTED_TABLES)
    def test_migration_creates_all_script_tables(self, table: str):
        source = _migration_source()
        assert f"'{table}'" in source or f'"{table}"' in source

    def test_enums_created_via_model_import_not_migration(self):
        """AGENTS.md rule: use ``postgresql.ENUM(..., create_type=False)``."""
        source = _migration_source()
        assert "create_type=False" in source

    def test_migration_is_reversible(self):
        """A downgrade() body with table drops must exist."""
        source = _migration_source()
        assert "def downgrade()" in source
        assert "drop_table" in source


class TestDropExecutionModeMigration:
    """The refinement removed execution modes: the follow-up migration
    ``b2c3d4e5f6a7`` drops ``execution_mode_configurations`` and adds the
    ``repair_attempts`` table + ``repaired_from_id`` lineage (E10)."""

    def test_follow_up_migration_file_exists(self):
        assert list(
            ALEMBIC_VERSIONS.glob("*drop_execution_mode_configuration*.py")
        )

    @pytest.mark.parametrize("table", DROPPED_TABLES)
    def test_mode_table_dropped_in_upgrade(self, table: str):
        source = _drop_migration_source()
        assert f'op.drop_table("{table}")' in source

    @pytest.mark.parametrize("table", FOLLOW_UP_TABLES)
    def test_repair_table_created_in_upgrade(self, table: str):
        source = _drop_migration_source()
        assert f'"{table}"' in source

    def test_repair_lineage_column_added(self):
        source = _drop_migration_source()
        assert '"repaired_from_id"' in source

    def test_mode_table_restored_in_downgrade(self):
        source = _drop_migration_source()
        downgrade = source.split("def downgrade()", 1)[1]
        assert 'op.create_table(\n        "execution_mode_configurations"' in downgrade
