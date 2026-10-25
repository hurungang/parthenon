"""Structural tests for the drop-``ExecutionModeConfiguration`` migration.

Revision ``b2c3d4e5f6a7`` implements the Software 3.0 refinement
(data-model.md §1.6/§1.7): execution modes are removed. This test asserts:

- ``upgrade()`` drops the ``execution_mode_configurations`` table and the
  ``execution_mode`` column on ``script_execution_records``
- ``upgrade()`` adds the ``repair_attempts`` table and ``repaired_from_id``
  lineage on ``script_versions``
- ``downgrade()`` fully restores the prior schema (reversible)
- No parameterized DDL (PostgreSQL rule, AGENTS.md)
- ENUMs use ``postgresql.ENUM(..., create_type=False)``

The full alembic up/down round-trip remains CI/PostgreSQL work per AGENTS.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ALEMBIC_VERSIONS = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions"
)
MIGRATION_NAME = "b2c3d4e5f6a7_drop_execution_mode_configuration.py"


@pytest.fixture(scope="module")
def migration_source() -> str:
    path = ALEMBIC_VERSIONS / MIGRATION_NAME
    assert path.exists(), f"drop-execution-mode migration not found: {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def upgrade_body(migration_source: str) -> str:
    return migration_source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]


@pytest.fixture(scope="module")
def downgrade_body(migration_source: str) -> str:
    return migration_source.split("def downgrade()", 1)[1]


class TestRevisionIdentity:
    def test_revision_chain(self, migration_source: str):
        assert 'revision: str = "b2c3d4e5f6a7"' in migration_source
        assert "down_revision" in migration_source


class TestUpgradeDropsModes:
    def test_upgrade_drops_execution_mode_configurations(self, upgrade_body: str):
        assert 'op.drop_table("execution_mode_configurations")' in upgrade_body

    def test_upgrade_drops_execution_mode_column(self, upgrade_body: str):
        assert (
            'op.drop_column("script_execution_records", "execution_mode")'
            in upgrade_body
        )

    def test_upgrade_adds_repair_attempts_table(self, upgrade_body: str):
        assert 'op.create_table(\n        "repair_attempts"' in upgrade_body
        # RepairAttempt evidence columns (E10)
        assert '"defect_diagnosis"' in upgrade_body
        assert '"diff_applied"' in upgrade_body
        assert '"retry_outcome"' in upgrade_body

    def test_upgrade_adds_repaired_from_lineage(self, upgrade_body: str):
        assert '"repaired_from_id"' in upgrade_body

    def test_upgrade_adds_identity_parity_evidence(self, upgrade_body: str):
        assert '"identity_parity_confirmed"' in upgrade_body


class TestDowngradeRestores:
    def test_downgrade_recreates_execution_mode_configurations(
        self, downgrade_body: str
    ):
        assert 'op.create_table(\n        "execution_mode_configurations"' in downgrade_body

    def test_downgrade_drops_repair_structures(self, downgrade_body: str):
        assert 'op.drop_table("repair_attempts")' in downgrade_body
        assert 'op.drop_column("script_versions", "repaired_from_id")' in downgrade_body
        assert (
            'op.drop_column("script_execution_records", "identity_parity_confirmed")'
            in downgrade_body
        )
        assert '"execution_mode",\n            script_execution_mode' in downgrade_body

    def test_downgrade_drops_repair_retry_enum(self, downgrade_body: str):
        assert "DROP TYPE IF EXISTS repair_retry_outcome_enum" in downgrade_body


class TestMigrationRules:
    def test_enums_use_create_type_false(self, migration_source: str):
        """AGENTS.md: enums are created by model import, never re-created."""
        assert "create_type=False" in migration_source
        assert "sa.ENUM(" not in migration_source

    def test_no_parameterized_ddl(self, migration_source: str):
        """PostgreSQL does not support parameterized DDL — no bindparams()."""
        assert "bindparams" not in migration_source

    def test_upgrade_downgrade_are_symmetric_on_tables(
        self, upgrade_body: str, downgrade_body: str
    ):
        assert 'op.create_table(\n        "repair_attempts"' in upgrade_body
        assert 'op.drop_table("repair_attempts")' in downgrade_body
        assert 'op.drop_table("execution_mode_configurations")' in upgrade_body
        assert (
            'op.create_table(\n        "execution_mode_configurations"' in downgrade_body
        )
