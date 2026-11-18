"""Enum + migration coverage for the ``requires_fix`` optimized-plan status.

The change is one additive PostgreSQL enum value on
``optimized_plan_status_enum``. These tests pin:

- the model-level enum member (``requires_fix`` exists, is distinct from the
  authoring-side ``needs_feedback``, and survives an ORM round-trip),
- the Alembic revision file (additive ``ADD VALUE IF NOT EXISTS`` DDL, no
  ``sa.Enum`` / parameterized DDL, documented no-op ``downgrade``),
- the revision being an applied-chain head in the script directory.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.db.models.agents import (
    AgentInputType,
    AgentOutputType,
    AgentPlan,
    AgentPlanStatus,
    AgentType,
)
from app.db.models.optimized_plan import (
    OptimizedImplementationPlan,
    OptimizedPlanStatus,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_FILE = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "a7b8c9d0e1f2_optimized_plan_requires_fix_status.py"
)


# ── Enum ──────────────────────────────────────────────────────────────────────


class TestOptimizedPlanStatusEnum:
    def test_requires_fix_member_exists_with_value(self):
        assert OptimizedPlanStatus.requires_fix.value == "requires_fix"
        assert "requires_fix" in {s.value for s in OptimizedPlanStatus}

    def test_requires_fix_is_distinct_from_authoring_states(self):
        """``requires_fix`` is execution-side; authoring must never emit it."""
        authoring_states = {
            OptimizedPlanStatus.generating,
            OptimizedPlanStatus.ready,
            OptimizedPlanStatus.failed,
            OptimizedPlanStatus.needs_feedback,
        }
        assert OptimizedPlanStatus.requires_fix not in authoring_states
        assert OptimizedPlanStatus.requires_fix != OptimizedPlanStatus.needs_feedback

    def test_string_lookup_round_trip(self):
        """The value can be resolved from its wire string (API/tool input)."""
        assert OptimizedPlanStatus("requires_fix") is OptimizedPlanStatus.requires_fix

    async def test_status_survives_orm_round_trip(self, db_session):
        agent_type = AgentType(
            name=f"requires-fix-{uuid.uuid4().hex[:8]}",
            input_type=AgentInputType.none,
            output_type=AgentOutputType.markdown,
        )
        db_session.add(agent_type)
        await db_session.flush()
        base_plan = AgentPlan(
            agent_type_id=agent_type.id,
            generation_status=AgentPlanStatus.success,
            plan_steps=[{"order": 1, "type": "tool_call", "name": "s"}],
        )
        db_session.add(base_plan)
        await db_session.flush()

        plan = OptimizedImplementationPlan(
            agent_type_id=agent_type.id,
            agent_plan_id=base_plan.id,
            plan_steps=[],
            fully_scripted=False,
            status=OptimizedPlanStatus.requires_fix,
        )
        db_session.add(plan)
        await db_session.flush()
        plan_id = plan.id

        db_session.expire_all()
        reloaded = await db_session.get(OptimizedImplementationPlan, plan_id)
        assert reloaded is not None
        assert reloaded.status is OptimizedPlanStatus.requires_fix


# ── Alembic migration ─────────────────────────────────────────────────────────


class TestRequiresFixMigration:
    def test_migration_file_exists(self):
        assert MIGRATION_FILE.is_file(), (
            f"missing migration for requires_fix: {MIGRATION_FILE}"
        )

    def test_upgrade_is_additive_enum_add_value(self):
        source = MIGRATION_FILE.read_text()
        upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        normalized = " ".join(upgrade_body.split())
        assert "ALTER TYPE optimized_plan_status_enum" in normalized
        assert "ADD VALUE IF NOT EXISTS 'requires_fix'" in normalized
        # PostgreSQL cannot ALTER an enum with bound parameters; and the enum
        # type already exists via model import (no sa.Enum / CREATE TYPE).
        # Compare against code lines only (comments mention sa.Enum).
        code = "\n".join(
            line.split("#", 1)[0] for line in upgrade_body.splitlines()
        )
        assert "sa.Enum" not in code
        assert "CREATE TYPE" not in code
        assert "bindparams" not in code

    def test_downgrade_is_documented_noop(self):
        """PostgreSQL cannot drop a single enum value; downgrade must be a
        documented no-op (never parameterized DDL, never a broken recreation)."""
        source = MIGRATION_FILE.read_text()
        downgrade_body = source.split("def downgrade()", 1)[1]
        code = "\n".join(
            line.split("#", 1)[0] for line in downgrade_body.splitlines()
        )
        # Only a docstring + ``pass`` — no DDL executed.
        assert "pass" in code
        assert "op.execute" not in code
        assert "ALTER TYPE" not in code

    def test_revision_is_on_the_script_directory_head_chain(self):
        """The requires_fix revision must be part of the migration chain that
        reaches a head (later, unrelated migrations may extend the chain —
        that must not make this migration look missing)."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        # ``script_location`` is relative to alembic.ini; running the tests from
        # another cwd must not break resolution.
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)

        heads = set(script.get_heads())
        revision = script.get_revision("a7b8c9d0e1f2")
        assert revision is not None, "requires_fix revision missing from script dir"
        ancestor_revisions = {
            rev.revision for rev in script.iterate_revisions(heads, "base")
        }
        assert revision.revision in ancestor_revisions, (
            "requires_fix migration is not on a head chain "
            f"(heads={sorted(heads)})"
        )
        # Additive migration: it revises an existing revision.
        assert revision.down_revision == "7127b840ae80"

    def test_only_one_requires_fix_enum_migration(self):
        """Guard against duplicate migrations of the same enum value."""
        versions = (BACKEND_ROOT / "alembic" / "versions").glob("*.py")
        matches = [
            p
            for p in versions
            if "ADD VALUE IF NOT EXISTS 'requires_fix'" in p.read_text()
        ]
        assert len(matches) == 1, (
            "expected exactly one migration adding requires_fix, got "
            f"{[p.name for p in matches]}"
        )
        # Idempotent DDL (safe on re-run / partially-migrated databases).
        assert "IF NOT EXISTS" in matches[0].read_text()
