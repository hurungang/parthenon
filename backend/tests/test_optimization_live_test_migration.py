"""Migration + persistence for the optimization live-test ledger.

The change is additive and reversible, in two revisions:

* ``3d7c2a5940bc`` — one new table ``optimization_live_tests``
  (``OptimizationLiveTestRequest``) whose creation owns the new
  ``optimization_live_test_status_enum``, plus one nullable
  ``runtime_tool_calls.optimization_live_test_request_id`` FK
  (``ON DELETE SET NULL``) marking approved live calls;
* ``7b1e4c2d9f03`` (child) — one nullable
  ``optimization_live_tests.script_version_id`` FK to ``script_versions.id``
  (``ON DELETE SET NULL``): a live test runs the **saved script** end-to-end,
  so the ledger must name the approved version;
* **no** ``conversation_sessions`` change — ``channel`` is already a free-form
  string, so ``channel="optimization"`` needs no schema change.

Pinned here: the ORM round-trip (including the script version), both revisions'
single-parent chain and additive/reversible shape (no parameterised DDL, the
column dropped before the table), pre-existing rows keeping a ``NULL`` pointer,
and the ``optimization`` channel being writable today.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models.agents import AgentInputType, AgentOutputType, AgentType
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.optimization_live_test import (
    OptimizationLiveTestRequest,
    OptimizationLiveTestStatus,
)
from app.db.models.script_registry import (
    SandboxValidationStatus,
    ScriptDefinition,
    ScriptVersion,
)
from app.db.models.tool_calls import (
    RuntimeToolCall,
    RuntimeToolCallRouteType,
    RuntimeToolCallSessionKind,
    RuntimeToolCallStatus,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION = "3d7c2a5940bc"
PARENT_REVISION = "992bbc77bf6a"
MIGRATION_FILE = (
    BACKEND_ROOT / "alembic" / "versions" / f"{REVISION}_optimization_live_test_requests.py"
)
SCRIPT_VERSION_REVISION = "7b1e4c2d9f03"
SCRIPT_VERSION_MIGRATION_FILE = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / f"{SCRIPT_VERSION_REVISION}_optimization_live_test_script_version.py"
)


# ── Entity / enum ────────────────────────────────────────────────────────────


class TestOptimizationLiveTestEntity:
    def test_status_enum_members(self):
        assert {member.value for member in OptimizationLiveTestStatus} == {
            "pending",
            "approved",
            "executed",
            "failed",
            "denied",
            "expired",
            "cancelled",
        }
        assert OptimizationLiveTestStatus("denied") is OptimizationLiveTestStatus.denied

    def test_table_columns_and_indexes(self):
        table = OptimizationLiveTestRequest.__table__
        expected = {
            "id",
            "tenant_id",
            "conversation_session_id",
            "target_agent_type_id",
            "request_turn_id",
            "intervene_request_id",
            "resume_id",
            "script_version_id",
            "status",
            "requested_operations",
            "executed_operations",
            "expires_at",
            "execution_started_at",
            "execution_finished_at",
            "created_at",
            "updated_at",
        }
        assert expected <= set(table.columns.keys())
        assert table.name == "optimization_live_tests"
        index_names = {index.name for index in table.indexes}
        assert "ix_optimization_live_tests_tenant_session" in index_names
        assert "ix_optimization_live_tests_status_expires_at" in index_names

    def test_the_script_version_pointer_is_nullable_and_set_null(self):
        """A live test names the approved SAVED script version; script retention
        must never destroy the ledger row, so the FK is ``SET NULL``."""
        column = OptimizationLiveTestRequest.__table__.columns["script_version_id"]
        assert column.nullable is True
        foreign_keys = list(column.foreign_keys)
        assert len(foreign_keys) == 1
        fk = foreign_keys[0]
        assert fk.target_fullname == "script_versions.id"
        assert fk.ondelete == "SET NULL"

    @pytest.mark.asyncio
    async def test_full_orm_round_trip(self, db_session):
        agent_type = AgentType(
            name=f"migration-agent-{uuid.uuid4().hex[:8]}",
            input_type=AgentInputType.typed,
            output_type=AgentOutputType.markdown,
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.flush()
        session = ConversationSession(
            agent_type_id=agent_type.id,
            channel="optimization",
            status=ConversationStatus.active,
        )
        db_session.add(session)
        await db_session.flush()

        definition = ScriptDefinition(
            agent_type_id=agent_type.id,
            name=f"migration-script-{uuid.uuid4().hex[:8]}",
        )
        db_session.add(definition)
        await db_session.flush()
        version = ScriptVersion(
            script_definition_id=definition.id,
            version_label=f"v{uuid.uuid4().hex[:4]}",
            python_source=(
                "def run(context, tools):\n"
                "    return tools.call('crm____searchCustomers', {'q': 'ada'})\n"
            ),
            sandbox_validation_status=SandboxValidationStatus.passed,
        )
        db_session.add(version)
        await db_session.flush()

        row = OptimizationLiveTestRequest(
            conversation_session_id=session.id,
            target_agent_type_id=agent_type.id,
            script_version_id=version.id,
            status=OptimizationLiveTestStatus.executed,
            requested_operations=[
                {
                    "tool_name": "crm____searchCustomers",
                    "arguments": {},
                    "purpose": "called by the script",
                }
            ],
            executed_operations=[
                {
                    "kind": "script_run",
                    "script_version_id": str(version.id),
                    "script_name": definition.name,
                    "status": "success",
                    "result_summary": '{"name": "Ada"}',
                    "error": None,
                    "duration_ms": 12,
                    "tool_calls": [
                        {
                            "tool_name": "crm____searchCustomers",
                            "status": "success",
                            "duration_ms": 5,
                            "result_summary": '{"name": "Ada"}',
                            "error": None,
                        }
                    ],
                    "telemetry": {"tool_call_count": 1},
                }
            ],
            expires_at=datetime.now(timezone.utc),
            execution_started_at=datetime.now(timezone.utc),
            execution_finished_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        await db_session.flush()
        row_id = row.id
        agent_type_id = agent_type.id
        version_id = version.id
        db_session.expire_all()

        reloaded = await db_session.get(OptimizationLiveTestRequest, row_id)
        assert reloaded is not None
        await db_session.refresh(reloaded)
        assert reloaded.status is OptimizationLiveTestStatus.executed
        assert reloaded.target_agent_type_id == agent_type_id
        # The approved SAVED script version round-trips.
        assert reloaded.script_version_id == version_id
        assert reloaded.requested_operations[0]["tool_name"] == "crm____searchCustomers"
        assert reloaded.executed_operations[0]["kind"] == "script_run"
        assert reloaded.executed_operations[0]["status"] == "success"
        assert reloaded.executed_operations[0]["script_version_id"] == str(version_id)
        assert reloaded.executed_operations[0]["tool_calls"][0]["status"] == "success"
        assert reloaded.expires_at is not None
        assert reloaded.execution_started_at is not None
        assert reloaded.execution_finished_at is not None
        assert reloaded.created_at is not None
        assert reloaded.updated_at is not None

    @pytest.mark.asyncio
    async def test_existing_tool_call_rows_keep_a_null_pointer(self, db_session):
        agent_type = AgentType(
            name=f"migration-tool-agent-{uuid.uuid4().hex[:8]}",
            input_type=AgentInputType.conversation,
            output_type=AgentOutputType.auto,
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.flush()
        session = ConversationSession(
            agent_type_id=agent_type.id,
            channel="web",
            status=ConversationStatus.active,
        )
        db_session.add(session)
        await db_session.flush()
        call = RuntimeToolCall(
            session_id=session.id,
            session_kind=RuntimeToolCallSessionKind.conversation,
            tool_name="system____save_data",
            route_type=RuntimeToolCallRouteType.system,
            status=RuntimeToolCallStatus.success,
        )
        db_session.add(call)
        await db_session.flush()

        assert call.optimization_live_test_request_id is None

    @pytest.mark.asyncio
    async def test_the_optimization_channel_needs_no_schema_change(self, db_session):
        """``channel`` is a free-form string — writing ``optimization`` works
        without any migration and business values are unaffected."""
        agent_type = AgentType(
            name=f"migration-channel-{uuid.uuid4().hex[:8]}",
            input_type=AgentInputType.typed,
            output_type=AgentOutputType.markdown,
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.flush()
        optimization = ConversationSession(
            agent_type_id=agent_type.id,
            channel="optimization",
            status=ConversationStatus.active,
        )
        web = ConversationSession(
            agent_type_id=agent_type.id,
            channel="web",
            status=ConversationStatus.active,
        )
        integration = ConversationSession(
            agent_type_id=agent_type.id,
            channel="integration",
            status=ConversationStatus.active,
        )
        db_session.add_all([optimization, web, integration])
        await db_session.flush()

        channels = {
            row.channel
            for row in (
                await db_session.execute(
                    select(ConversationSession).where(
                        ConversationSession.agent_type_id == agent_type.id
                    )
                )
            ).scalars().all()
        }
        assert channels == {"optimization", "web", "integration"}

    def test_no_conversation_scope_column_was_added(self):
        """The avatar model has no scope column: the session's own agent type is
        the subject, so ``conversation_sessions`` carries no subject pointer."""
        columns = set(ConversationSession.__table__.columns.keys())
        assert not any("scope" in name for name in columns)


# ── Alembic revision ────────────────────────────────────────────────────────


class TestOptimizationLiveTestMigration:
    def test_migration_file_exists(self):
        assert MIGRATION_FILE.is_file(), f"missing migration: {MIGRATION_FILE}"

    def test_revision_is_the_single_child_of_the_previous_head(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)

        revision = script.get_revision(REVISION)
        assert revision is not None, "live-test migration missing from the script dir"
        assert revision.down_revision == PARENT_REVISION

        children = [
            rev.revision
            for rev in script.walk_revisions()
            if rev.down_revision == PARENT_REVISION
        ]
        # Single child: no competing migration branches off the same parent.
        assert children == [REVISION]

    def test_upgrade_creates_the_table_and_one_nullable_column(self):
        source = MIGRATION_FILE.read_text()
        upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        code = "\n".join(line.split("#", 1)[0] for line in upgrade_body.splitlines())

        assert "op.create_table(" in code
        assert "'optimization_live_tests'" in code
        assert "op.add_column(" in code
        assert "'runtime_tool_calls'" in code
        assert "'optimization_live_test_request_id'" in code
        # The pointer is nullable — existing rows must stay valid.
        assert "nullable=True" in code
        assert "op.create_foreign_key(" in code
        # No conversation-table change (channel is already free-form text).
        assert "'conversation_sessions'" not in code
        # No parameterised DDL (PostgreSQL cannot bind DDL params).
        assert "bindparams" not in code
        # The enum is created by the table itself (no standalone CREATE TYPE).
        assert "op.execute" not in code

    def test_downgrade_drops_the_column_before_the_table(self):
        source = MIGRATION_FILE.read_text()
        downgrade_body = source.split("def downgrade()", 1)[1]
        code = "\n".join(line.split("#", 1)[0] for line in downgrade_body.splitlines())

        column_pos = code.index("op.drop_column('runtime_tool_calls'")
        table_pos = code.index("op.drop_table('optimization_live_tests')")
        assert column_pos < table_pos, (
            "downgrade must drop the FK/column before dropping the table"
        )
        assert "op.drop_constraint(" in code

    def test_no_data_seed_or_agent_type_change(self):
        source = MIGRATION_FILE.read_text()
        upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        code = "\n".join(line.split("#", 1)[0] for line in upgrade_body.splitlines())
        assert "'agent_types'" not in code
        assert "insert" not in code.lower()

    def test_revision_is_the_script_directory_head(self):
        """This change's revision must be reachable from a head (later,
        unrelated migrations may extend the chain)."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)
        heads = set(script.get_heads())
        ancestors = {rev.revision for rev in script.iterate_revisions(heads, "base")}
        assert REVISION in ancestors


class TestScriptVersionMigration:
    """``7b1e4c2d9f03`` — the SAVED script version a live test runs."""

    def test_migration_file_exists(self):
        assert SCRIPT_VERSION_MIGRATION_FILE.is_file(), (
            f"missing migration: {SCRIPT_VERSION_MIGRATION_FILE}"
        )

    def test_revision_is_the_single_child_of_the_ledger_revision(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)

        revision = script.get_revision(SCRIPT_VERSION_REVISION)
        assert revision is not None, "script-version migration missing"
        assert revision.down_revision == REVISION

        children = [
            rev.revision
            for rev in script.walk_revisions()
            if rev.down_revision == REVISION
        ]
        assert children == [SCRIPT_VERSION_REVISION]

    def test_upgrade_adds_one_nullable_set_null_foreign_key(self):
        source = SCRIPT_VERSION_MIGRATION_FILE.read_text()
        upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        code = "\n".join(line.split("#", 1)[0] for line in upgrade_body.splitlines())

        assert "op.add_column(" in code
        assert "'optimization_live_tests'" in code
        assert "'script_version_id'" in code
        # Nullable: historical ledger rows simply have no approved version.
        assert "nullable=True" in code
        assert "op.create_foreign_key(" in code
        assert "'script_versions'" in code
        assert "ondelete='SET NULL'" in code
        # No backfill, no parameterised DDL, no other table touched.
        assert "bindparams" not in code
        assert "insert" not in code.lower()
        assert "op.create_table(" not in code
        assert "op.drop_column(" not in code

    def test_downgrade_drops_the_constraint_then_the_column(self):
        source = SCRIPT_VERSION_MIGRATION_FILE.read_text()
        downgrade_body = source.split("def downgrade()", 1)[1]
        code = "\n".join(line.split("#", 1)[0] for line in downgrade_body.splitlines())

        constraint_pos = code.index("op.drop_constraint(")
        column_pos = code.index("op.drop_column('optimization_live_tests'")
        assert constraint_pos < column_pos, (
            "downgrade must drop the FK before dropping the column"
        )
        assert "type_='foreignkey'" in code

    def test_the_chain_head_includes_the_script_version_revision(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)
        heads = set(script.get_heads())
        ancestors = {rev.revision for rev in script.iterate_revisions(heads, "base")}
        assert SCRIPT_VERSION_REVISION in ancestors
        # The ledger revision is its parent (no branch off the same parent).
        assert REVISION in ancestors
