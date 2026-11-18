"""Optimization live-test ledger — script validation, state machine, expiry, audit.

The conversational optimizer is replay-only by default. A live test is **one
end-to-end run of a saved script** — never an individual MCP tool call: MCP
tools are assumed to work, and what the operator consents to is that script
running once, as the agent.

This suite proves the ledger's guarantees server-side:

* **script validation matrix** — the subject is derived from the session (never
  supplied), the requested ``script_version_id`` must exist in the
  conversation's tenant, carry ``python_source`` and belong to that subject; the
  script must contain at least one literal ``tools.call``; one pending request
  per conversation; the per-session approved-live cap; every refusal writes
  nothing.
* **tool-call preview derivation** — ``requested_operations`` is built
  server-side from the approved version's own source (ordered, de-duplicated,
  bounded with a ``+N more`` marker), never supplied by the caller, and
  immutable after creation.
* **state machine** — only the documented transitions are admitted
  (``pending → approved → executed|failed``; ``pending → denied|expired|
  cancelled``); denied/expired rows are retained with empty
  ``executed_operations``.
* **script run record** — one ``{kind: "script_run", …}`` entry (result summary,
  per-``tools.call`` outcomes, telemetry, duration) written once.
* **single shot** — ``begin_execution`` is one conditional transition: exactly
  one caller claims the run; a replayed approval returns the stored outcome.
* **expiry / denial** — the sweep closes overdue ``pending`` rows only, keeps
  the session replay-only, and never retries.
* **audit** — replay (``execute_script``) and live (ledger pointer) calls are
  counted distinctly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInputType, AgentOutputType, AgentType
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterventionType,
)
from app.db.models.optimization_live_test import (
    OptimizationLiveTestRequest,
    OptimizationLiveTestStatus,
)
from app.db.models.script_registry import (
    ScriptDefinition,
    SandboxValidationStatus,
    ScriptVersion,
)
from app.db.models.tenant import Tenant, TenantStatus
from app.db.models.tool_calls import (
    RuntimeToolCall,
    RuntimeToolCallRouteType,
    RuntimeToolCallSessionKind,
    RuntimeToolCallStatus,
)
from app.services.agents.optimization_live_test_service import (
    MAX_LIVE_TEST_PREVIEW_TOOLS,
    REFUSAL_ALREADY_PENDING,
    REFUSAL_INVALID_SCRIPT_VERSION,
    REFUSAL_NOT_PERMITTED,
    REFUSAL_NO_TOOL_CALLS,
    REFUSAL_OUT_OF_SCOPE,
    REFUSAL_QUOTA,
    REFUSAL_SCRIPT_VERSION_NOT_FOUND,
    OptimizationLiveTestService,
    get_live_test_service,
    outcome_of,
    render_script_live_test_reason,
)

NOW = datetime.now(timezone.utc)
PERMITTED_TOOL = "crm____searchCustomers"
OTHER_PERMITTED_TOOL = "crm____createOrder"

SCRIPT_SOURCE = (
    "def run(context, tools):\n"
    f"    matches = tools.call('{PERMITTED_TOOL}', {{'q': 'ada'}})\n"
    f"    return tools.call('{OTHER_PERMITTED_TOOL}', {{'q': 'ada'}})\n"
)


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _tenant(db: AsyncSession) -> Tenant:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(
        id=uuid.uuid4(),
        slug=f"ledger-ws-{suffix}",
        name=f"Ledger Workspace {suffix}",
        status=TenantStatus.active,
    )
    db.add(tenant)
    await db.flush()
    return tenant


async def _subject(db: AsyncSession, *, tenant_id: uuid.UUID | None = None) -> AgentType:
    agent_type = AgentType(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"ledger-agent-{uuid.uuid4().hex[:8]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _conversation(
    db: AsyncSession,
    agent_type: AgentType,
    *,
    channel: str = "optimization",
    tenant_id: uuid.UUID | None = None,
) -> ConversationSession:
    session = ConversationSession(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_type_id=agent_type.id,
        channel=channel,
        status=ConversationStatus.active,
    )
    db.add(session)
    await db.flush()
    return session


async def _script(
    db: AsyncSession,
    agent_type: AgentType,
    *,
    source: str | None = SCRIPT_SOURCE,
    tenant_id: uuid.UUID | None = None,
    definition: ScriptDefinition | None = None,
    version_label: str | None = None,
) -> tuple[ScriptDefinition, ScriptVersion]:
    """Seed one saved script version owned by ``agent_type``."""
    if definition is None:
        definition = ScriptDefinition(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            agent_type_id=agent_type.id,
            name=f"live-test-script-{uuid.uuid4().hex[:8]}",
        )
        db.add(definition)
        await db.flush()
    version = ScriptVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        script_definition_id=definition.id,
        version_label=version_label or f"v{uuid.uuid4().hex[:6]}",
        python_source=source,
        sandbox_validation_status=SandboxValidationStatus.passed,
    )
    db.add(version)
    await db.flush()
    return definition, version


@pytest.fixture
def permitted_tools(monkeypatch):
    """The subject's own grants: two MCP tools."""
    async def _allowed(self, agent_type_id, db):  # noqa: ANN001
        return {PERMITTED_TOOL, OTHER_PERMITTED_TOOL}

    monkeypatch.setattr(
        "app.services.agents.permission_manager.AgentPermissionManager."
        "calculate_agent_allowed_tools",
        _allowed,
    )
    return {PERMITTED_TOOL, OTHER_PERMITTED_TOOL}


async def _rows(
    db: AsyncSession, *, agent_type_id: uuid.UUID | None = None
) -> list[OptimizationLiveTestRequest]:
    stmt = select(OptimizationLiveTestRequest)
    if agent_type_id is not None:
        stmt = stmt.where(
            OptimizationLiveTestRequest.target_agent_type_id == agent_type_id
        )
    return list((await db.execute(stmt)).scalars().all())


# ── Script validation matrix ────────────────────────────────────────────────


class TestScriptValidation:
    @pytest.mark.asyncio
    async def test_a_valid_script_version_is_recorded_pending(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
            reason="need real data",
        )

        assert result.accepted is True
        assert result.request_id is not None
        assert result.expires_at is not None
        # The resolved target names the script the operator approved.
        assert result.script is not None
        assert result.script.script_version_id == version.id
        assert result.script.python_source.strip() == SCRIPT_SOURCE.strip()

        row = await db_session.get(OptimizationLiveTestRequest, result.request_id)
        assert row is not None
        assert row.status is OptimizationLiveTestStatus.pending
        # The subject is derived from the SESSION — never from the caller.
        assert row.target_agent_type_id == agent_type.id
        # The script the operator approved is recorded on the row.
        assert row.script_version_id == version.id
        # The preview is evidence of what the script will call.
        assert [entry["tool_name"] for entry in row.requested_operations] == [
            PERMITTED_TOOL,
            OTHER_PERMITTED_TOOL,
        ]
        assert row.executed_operations is None
        assert row.execution_started_at is None

    @pytest.mark.asyncio
    async def test_unknown_conversation_is_out_of_scope(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        _definition, version = await _script(db_session, agent_type)

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=uuid.uuid4(),
            script_version_id=version.id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_OUT_OF_SCOPE
        assert await _rows(db_session, agent_type_id=agent_type.id) == []

    @pytest.mark.asyncio
    async def test_business_conversation_is_out_of_scope(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        business = await _conversation(db_session, agent_type, channel="web")
        _definition, version = await _script(db_session, agent_type)

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=business.id,
            script_version_id=version.id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_OUT_OF_SCOPE
        assert await _rows(db_session, agent_type_id=agent_type.id) == []

    @pytest.mark.asyncio
    async def test_conversation_without_a_subject_is_out_of_scope(
        self, db_session: AsyncSession, permitted_tools
    ):
        session = ConversationSession(
            id=uuid.uuid4(),
            agent_type_id=None,
            channel="optimization",
            status=ConversationStatus.active,
        )
        db_session.add(session)
        await db_session.flush()

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=uuid.uuid4(),
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_OUT_OF_SCOPE

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_version_id", [None, "", "not-a-uuid", 12345])
    async def test_a_missing_or_malformed_script_version_is_refused(
        self, db_session: AsyncSession, permitted_tools, bad_version_id
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=bad_version_id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_INVALID_SCRIPT_VERSION
        assert await _rows(db_session, agent_type_id=agent_type.id) == []

    @pytest.mark.asyncio
    async def test_an_unknown_script_version_is_refused(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=uuid.uuid4(),
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_SCRIPT_VERSION_NOT_FOUND
        assert await _rows(db_session, agent_type_id=agent_type.id) == []

    @pytest.mark.asyncio
    async def test_a_version_without_source_is_refused(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type, source=None)
        version.python_source = "   \n"
        await db_session.flush()

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_SCRIPT_VERSION_NOT_FOUND
        assert await _rows(db_session, agent_type_id=agent_type.id) == []

    @pytest.mark.asyncio
    async def test_a_script_owned_by_another_agent_type_is_out_of_scope(
        self, db_session: AsyncSession, permitted_tools
    ):
        """The approved script must belong to the conversation's subject — an
        approval can never run another agent's script."""
        agent_type = await _subject(db_session)
        other = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, other_version = await _script(db_session, other)

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=other_version.id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_OUT_OF_SCOPE
        assert await _rows(db_session, agent_type_id=agent_type.id) == []

    @pytest.mark.asyncio
    async def test_a_script_from_another_tenant_is_not_found(
        self, db_session: AsyncSession, permitted_tools
    ):
        tenant_a = await _tenant(db_session)
        tenant_b = await _tenant(db_session)
        agent_type = await _subject(db_session, tenant_id=tenant_a.id)
        session = await _conversation(
            db_session, agent_type, tenant_id=tenant_a.id
        )
        _definition, foreign_version = await _script(
            db_session, agent_type, tenant_id=tenant_b.id
        )

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=foreign_version.id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_SCRIPT_VERSION_NOT_FOUND
        assert await _rows(db_session, agent_type_id=agent_type.id) == []

    @pytest.mark.asyncio
    async def test_a_script_without_literal_tool_calls_is_refused(
        self, db_session: AsyncSession, permitted_tools
    ):
        """A script that calls nothing proves nothing: MCP tools are assumed to
        work, so a live run of a no-egress script would prove nothing."""
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(
            db_session,
            agent_type,
            source="def run(context, tools):\n    return {'ok': True}\n",
        )

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_NO_TOOL_CALLS
        assert await _rows(db_session, agent_type_id=agent_type.id) == []

    @pytest.mark.asyncio
    async def test_a_script_naming_a_tool_outside_the_subjects_grants_is_refused(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(
            db_session,
            agent_type,
            source=(
                "def run(context, tools):\n"
                "    return tools.call('other-server____deleteEverything', {})\n"
            ),
        )

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_NOT_PERMITTED
        assert "other-server____deleteEverything" in (result.reason or "")
        assert await _rows(db_session, agent_type_id=agent_type.id) == []

    @pytest.mark.asyncio
    async def test_a_dynamic_tool_name_is_not_previewable_and_is_ignored(
        self, db_session: AsyncSession, permitted_tools
    ):
        """Only literal names can be previewed; a purely dynamic script has no
        previewable call, so the ledger refuses it with ``no_tool_calls``."""
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(
            db_session,
            agent_type,
            source=(
                "def run(context, tools):\n"
                "    name = context.get('tool')\n"
                "    return tools.call(name, {})\n"
            ),
        )

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_NO_TOOL_CALLS

    @pytest.mark.asyncio
    async def test_second_pending_request_is_refused(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()

        first = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        assert first.accepted is True

        second = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        assert second.accepted is False
        assert second.reason_code == REFUSAL_ALREADY_PENDING
        assert len(await _rows(db_session, agent_type_id=agent_type.id)) == 1

    @pytest.mark.asyncio
    async def test_per_session_approved_cap_is_enforced(
        self, db_session: AsyncSession, permitted_tools,
    ):
        from app.core.config import get_settings

        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        cap = max(1, int(get_settings().optimizer_live_test_approved_cap))

        # Consume the whole cap with executed script runs.
        for index in range(cap):
            db_session.add(
                OptimizationLiveTestRequest(
                    id=uuid.uuid4(),
                    conversation_session_id=session.id,
                    target_agent_type_id=agent_type.id,
                    script_version_id=version.id,
                    status=OptimizationLiveTestStatus.executed,
                    requested_operations=[{"tool_name": PERMITTED_TOOL}],
                    executed_operations=[
                        {"kind": "script_run", "status": "success"}
                    ],
                    expires_at=NOW,
                )
            )
        await db_session.flush()

        result = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        assert result.accepted is False
        assert result.reason_code == REFUSAL_QUOTA

    @pytest.mark.asyncio
    async def test_denied_rows_do_not_consume_the_cap(
        self, db_session: AsyncSession, permitted_tools
    ):
        from app.core.config import get_settings

        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        cap = max(1, int(get_settings().optimizer_live_test_approved_cap))
        for _index in range(cap + 1):
            db_session.add(
                OptimizationLiveTestRequest(
                    id=uuid.uuid4(),
                    conversation_session_id=session.id,
                    target_agent_type_id=agent_type.id,
                    script_version_id=version.id,
                    status=OptimizationLiveTestStatus.denied,
                    requested_operations=[{"tool_name": PERMITTED_TOOL}],
                    expires_at=NOW,
                )
            )
        await db_session.flush()

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        assert result.accepted is True


# ── Tool-call preview derivation ────────────────────────────────────────────


class TestPreviewDerivation:
    @pytest.mark.asyncio
    async def test_preview_is_ordered_and_de_duplicated(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(
            db_session,
            agent_type,
            source=(
                "def run(context, tools):\n"
                f"    a = tools.call('{OTHER_PERMITTED_TOOL}', {{}})\n"
                f"    b = tools.call('{PERMITTED_TOOL}', {{}})\n"
                f"    return tools.call('{OTHER_PERMITTED_TOOL}', {{}})\n"
            ),
        )

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )

        row = await db_session.get(OptimizationLiveTestRequest, result.request_id)
        assert [entry["tool_name"] for entry in row.requested_operations] == [
            OTHER_PERMITTED_TOOL,
            PERMITTED_TOOL,
        ]
        for entry in row.requested_operations:
            assert entry["arguments"] == {}
            assert entry["purpose"]

    @pytest.mark.asyncio
    async def test_preview_is_bounded_with_a_remaining_marker(
        self, db_session: AsyncSession, permitted_tools, monkeypatch
    ):
        """The card is bounded, but the operator still sees the true total."""
        names = [f"crm____tool{i}" for i in range(MAX_LIVE_TEST_PREVIEW_TOOLS + 3)]

        async def _all_permitted(self, agent_type_id, db):  # noqa: ANN001
            return set(names)

        monkeypatch.setattr(
            "app.services.agents.permission_manager.AgentPermissionManager."
            "calculate_agent_allowed_tools",
            _all_permitted,
        )
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        body = "\n".join(
            f"    tools.call('{name}', {{}})" for name in names
        )
        _definition, version = await _script(
            db_session, agent_type, source=f"def run(context, tools):\n{body}\n"
        )

        result = await OptimizationLiveTestService().create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )

        row = await db_session.get(OptimizationLiveTestRequest, result.request_id)
        entries = row.requested_operations
        assert len(entries) == MAX_LIVE_TEST_PREVIEW_TOOLS + 1
        assert entries[-1]["tool_name"] == "+3 more"

    @pytest.mark.asyncio
    async def test_the_caller_never_supplies_the_preview(
        self, db_session: AsyncSession, permitted_tools
    ):
        """``create_request`` has no operation-list parameter: the preview is
        always derived from the approved version's own source."""
        import inspect

        signature = inspect.signature(
            OptimizationLiveTestService.create_request
        )
        assert "requested_operations" not in signature.parameters
        assert "operations" not in signature.parameters
        assert "script_version_id" in signature.parameters

    def test_the_approval_card_names_the_script_and_its_preview(self):
        text = render_script_live_test_reason(
            script_name="daily-refunds",
            script_version_label="v3",
            tool_preview=[PERMITTED_TOOL, OTHER_PERMITTED_TOOL],
            reason="Replay could not prove the totals step.",
            expires_at=NOW,
        )

        assert "**Run this script live**" in text
        assert "`daily-refunds`" in text
        assert "`v3`" in text
        assert "Replay could not prove the totals step." in text
        assert f"`{PERMITTED_TOOL}`" in text
        assert f"`{OTHER_PERMITTED_TOOL}`" in text
        assert "ONCE" in text
        assert "MCP tools are assumed to work" in text
        assert "Single use" in text
        assert NOW.isoformat() in text

    def test_the_approval_card_marks_the_true_total_when_bounded(self):
        preview = [f"crm____tool{i}" for i in range(MAX_LIVE_TEST_PREVIEW_TOOLS + 2)]
        text = render_script_live_test_reason(
            script_name="big-script",
            script_version_label="v1",
            tool_preview=preview,
            reason=None,
            expires_at=None,
        )
        assert "and 2 more" in text
        # No literal calls → the card says so instead of inventing a preview.
        assert "No literal `tools.call(...)`" in render_script_live_test_reason(
            script_name=None,
            script_version_label=None,
            tool_preview=[],
            reason=None,
            expires_at=None,
        )


# ── State machine ───────────────────────────────────────────────────────────


class TestStateMachine:
    @pytest.mark.asyncio
    async def test_approve_then_execute_then_complete(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        row = await db_session.get(OptimizationLiveTestRequest, created.request_id)

        await service.mark_approved(db_session, row)
        assert row.status is OptimizationLiveTestStatus.approved
        # approved is consent only — no evidence, no timings.
        assert row.executed_operations is None
        assert row.execution_started_at is None

        claimed = await service.begin_execution(db_session, row.id)
        assert claimed is True

        run_record = service.build_script_run_record(
            script_version_id=version.id,
            script_name="live-test-script",
            script_version_label="v1",
            status="success",
            result_summary='{"total": 42}',
            tool_calls=[
                {"tool_name": PERMITTED_TOOL, "status": "success", "duration_ms": 5}
            ],
            telemetry={"tool_calls": 1, "duration_ms": 12},
            duration_ms=12,
            error=None,
        )
        await service.complete_execution(
            db_session,
            row.id,
            executed_operations=[run_record],
            failed=False,
            started_at=NOW,
            finished_at=NOW,
        )
        refreshed = await db_session.get(OptimizationLiveTestRequest, row.id)
        await db_session.refresh(refreshed)
        assert refreshed.status is OptimizationLiveTestStatus.executed
        assert refreshed.executed_operations == [run_record]
        assert refreshed.executed_operations[0]["kind"] == "script_run"
        assert refreshed.executed_operations[0]["script_version_id"] == str(
            version.id
        )
        assert refreshed.execution_started_at is not None
        assert refreshed.execution_finished_at is not None

        outcome = outcome_of(refreshed)
        assert outcome.script_run is not None
        assert outcome.script_run["kind"] == "script_run"
        assert outcome.script_run["status"] == "success"
        assert outcome.script_run["tool_calls"][0]["tool_name"] == PERMITTED_TOOL

    @pytest.mark.asyncio
    async def test_denied_is_terminal_and_retains_no_evidence(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        row = await db_session.get(OptimizationLiveTestRequest, created.request_id)

        await service.mark_denied(db_session, row)
        assert row.status is OptimizationLiveTestStatus.denied
        assert row.executed_operations is None
        assert row.execution_started_at is None

        # Denied can never be approved/executed afterwards.
        await service.mark_approved(db_session, row)
        assert row.status is OptimizationLiveTestStatus.denied
        assert await service.begin_execution(db_session, row.id) is False

    @pytest.mark.asyncio
    async def test_approved_cannot_be_denied(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        row = await db_session.get(OptimizationLiveTestRequest, created.request_id)
        await service.mark_approved(db_session, row)

        await service.mark_denied(db_session, row)
        assert row.status is OptimizationLiveTestStatus.approved

    @pytest.mark.asyncio
    async def test_a_failed_script_run_records_the_failure(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        await service.begin_execution(db_session, created.request_id)
        run_record = service.build_script_run_record(
            script_version_id=version.id,
            script_name="live-test-script",
            script_version_label="v1",
            status="error",
            result_summary=None,
            tool_calls=[
                {
                    "tool_name": PERMITTED_TOOL,
                    "status": "error",
                    "error": "live_test_permission_denied",
                }
            ],
            telemetry=None,
            duration_ms=3,
            error="live_test_permission_denied: the script's tool call was denied",
        )
        await service.complete_execution(
            db_session,
            created.request_id,
            executed_operations=[run_record],
            failed=True,
            started_at=NOW,
            finished_at=NOW,
        )
        refreshed = await db_session.get(
            OptimizationLiveTestRequest, created.request_id
        )
        await db_session.refresh(refreshed)
        assert refreshed.status is OptimizationLiveTestStatus.failed
        # One run record says what failed; the remaining calls are not attempted.
        assert len(refreshed.executed_operations) == 1
        assert refreshed.executed_operations[0]["status"] == "error"
        assert refreshed.executed_operations[0]["tool_calls"] == [
            {
                "tool_name": PERMITTED_TOOL,
                "status": "error",
                "error": "live_test_permission_denied",
            }
        ]

    @pytest.mark.asyncio
    async def test_requested_operations_are_immutable_after_creation(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        expected = [
            {"tool_name": PERMITTED_TOOL, "arguments": {}, "purpose": "called by the script"},
            {
                "tool_name": OTHER_PERMITTED_TOOL,
                "arguments": {},
                "purpose": "called by the script",
            },
        ]
        await service.begin_execution(db_session, created.request_id)
        await service.complete_execution(
            db_session,
            created.request_id,
            executed_operations=[{"kind": "script_run", "status": "success"}],
            failed=False,
            started_at=NOW,
            finished_at=NOW,
        )
        refreshed = await db_session.get(
            OptimizationLiveTestRequest, created.request_id
        )
        await db_session.refresh(refreshed)
        assert refreshed.requested_operations == expected
        assert refreshed.script_version_id == version.id


# ── Single shot / idempotency ───────────────────────────────────────────────


class TestSingleShot:
    @pytest.mark.asyncio
    async def test_only_one_caller_claims_the_execution(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )

        first = await service.begin_execution(db_session, created.request_id)
        second = await service.begin_execution(db_session, created.request_id)

        assert first is True
        assert second is False

    @pytest.mark.asyncio
    async def test_a_terminal_row_can_never_be_reclaimed(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        await service.begin_execution(db_session, created.request_id)
        await service.complete_execution(
            db_session,
            created.request_id,
            executed_operations=[{"kind": "script_run", "status": "success"}],
            failed=False,
            started_at=NOW,
            finished_at=NOW,
        )

        assert await service.begin_execution(db_session, created.request_id) is False

    @pytest.mark.asyncio
    async def test_replayed_request_finds_the_row_for_the_same_script_version(
        self, db_session: AsyncSession, permitted_tools
    ):
        """AR re-executes the interrupted tool task on resume: the same script
        version must return the stored row (never a second request/approval)."""
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        definition, version = await _script(db_session, agent_type)
        _definition2, other_version = await _script(
            db_session, agent_type, definition=None
        )
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        assert definition.id == version.script_definition_id

        replay = await service.find_replay(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        other = await service.find_replay(
            db_session,
            conversation_session_id=session.id,
            script_version_id=other_version.id,
        )
        malformed = await service.find_replay(
            db_session,
            conversation_session_id=session.id,
            script_version_id="not-a-uuid",
        )

        assert replay is not None and replay.id == created.request_id
        assert other is None
        assert malformed is None


# ── Denial / expiry stays replay-only ──────────────────────────────────────


class TestExpiry:
    @pytest.mark.asyncio
    async def test_sweep_closes_only_overdue_pending_rows(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        overdue = OptimizationLiveTestRequest(
            id=uuid.uuid4(),
            conversation_session_id=session.id,
            target_agent_type_id=agent_type.id,
            script_version_id=version.id,
            status=OptimizationLiveTestStatus.pending,
            requested_operations=[{"tool_name": PERMITTED_TOOL}],
            expires_at=NOW - timedelta(minutes=1),
        )
        future = OptimizationLiveTestRequest(
            id=uuid.uuid4(),
            conversation_session_id=session.id,
            target_agent_type_id=agent_type.id,
            script_version_id=version.id,
            status=OptimizationLiveTestStatus.pending,
            requested_operations=[{"tool_name": OTHER_PERMITTED_TOOL}],
            expires_at=NOW + timedelta(minutes=30),
        )
        approved = OptimizationLiveTestRequest(
            id=uuid.uuid4(),
            conversation_session_id=session.id,
            target_agent_type_id=agent_type.id,
            script_version_id=version.id,
            status=OptimizationLiveTestStatus.approved,
            requested_operations=[{"tool_name": PERMITTED_TOOL}],
            expires_at=NOW - timedelta(minutes=1),
            execution_started_at=NOW,
        )
        db_session.add_all([overdue, future, approved])
        await db_session.flush()

        expired = await OptimizationLiveTestService().expire_overdue(
            db_session, conversation_session_id=session.id, now=NOW
        )

        assert expired == 1
        refreshed = {
            row.id: row
            for row in (await db_session.execute(
                select(OptimizationLiveTestRequest)
            )).scalars().all()
        }
        assert refreshed[overdue.id].status is OptimizationLiveTestStatus.expired
        # Expiry leaves no execution evidence and stays replay-only.
        assert refreshed[overdue.id].executed_operations is None
        assert refreshed[future.id].status is OptimizationLiveTestStatus.pending
        # An in-flight execution is never torn down by the sweep.
        assert refreshed[approved.id].status is OptimizationLiveTestStatus.approved

    @pytest.mark.asyncio
    async def test_lazy_check_reports_overdue_without_transitioning(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        row = OptimizationLiveTestRequest(
            id=uuid.uuid4(),
            conversation_session_id=session.id,
            target_agent_type_id=agent_type.id,
            script_version_id=version.id,
            status=OptimizationLiveTestStatus.pending,
            requested_operations=[{"tool_name": PERMITTED_TOOL}],
            expires_at=NOW - timedelta(seconds=1),
        )
        db_session.add(row)
        await db_session.flush()
        service = OptimizationLiveTestService()

        assert service.is_overdue(row, now=NOW) is True
        assert row.status is OptimizationLiveTestStatus.pending

    @pytest.mark.asyncio
    async def test_sweep_closes_the_linked_intervention(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        intervene = InterveneRequest(
            id=uuid.uuid4(),
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="Run this script live",
            conversation_session_id=session.id,
        )
        db_session.add(intervene)
        await db_session.flush()
        row = OptimizationLiveTestRequest(
            id=uuid.uuid4(),
            conversation_session_id=session.id,
            target_agent_type_id=agent_type.id,
            script_version_id=version.id,
            intervene_request_id=intervene.id,
            status=OptimizationLiveTestStatus.pending,
            requested_operations=[{"tool_name": PERMITTED_TOOL}],
            expires_at=NOW - timedelta(minutes=1),
        )
        db_session.add(row)
        await db_session.flush()

        await OptimizationLiveTestService().expire_overdue(
            db_session, conversation_session_id=session.id, now=NOW
        )

        refreshed = await db_session.get(InterveneRequest, intervene.id)
        await db_session.refresh(refreshed)
        assert refreshed.status is InterveneRequestStatus.expired
        assert refreshed.responded_at is not None

    @pytest.mark.asyncio
    async def test_cancel_for_session_closes_only_pending_rows(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        pending = OptimizationLiveTestRequest(
            id=uuid.uuid4(),
            conversation_session_id=session.id,
            target_agent_type_id=agent_type.id,
            script_version_id=version.id,
            status=OptimizationLiveTestStatus.pending,
            requested_operations=[{"tool_name": PERMITTED_TOOL}],
            expires_at=NOW + timedelta(minutes=10),
        )
        executed = OptimizationLiveTestRequest(
            id=uuid.uuid4(),
            conversation_session_id=session.id,
            target_agent_type_id=agent_type.id,
            script_version_id=version.id,
            status=OptimizationLiveTestStatus.executed,
            requested_operations=[{"tool_name": OTHER_PERMITTED_TOOL}],
            executed_operations=[{"kind": "script_run", "status": "success"}],
            expires_at=NOW,
        )
        db_session.add_all([pending, executed])
        await db_session.flush()

        cancelled = await OptimizationLiveTestService().cancel_for_session(
            db_session, session.id
        )

        assert cancelled == 1
        assert pending.status is OptimizationLiveTestStatus.cancelled
        assert pending.executed_operations is None
        assert executed.status is OptimizationLiveTestStatus.executed


# ── Audit: replay vs live ──────────────────────────────────────────────────


class TestSessionAudit:
    @pytest.mark.asyncio
    async def test_replay_and_live_calls_are_counted_distinctly(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )

        def _call(tool_name: str, live_id=None, created_at=None):
            return RuntimeToolCall(
                id=uuid.uuid4(),
                session_id=session.id,
                session_kind=RuntimeToolCallSessionKind.conversation,
                tool_name=tool_name,
                route_type=RuntimeToolCallRouteType.system,
                status=RuntimeToolCallStatus.success,
                optimization_live_test_request_id=live_id,
                created_at=created_at or NOW,
            )

        db_session.add_all(
            [
                _call("system____execute_script"),
                _call("system____execute_script"),
                # Live calls the approved script made (ledger pointer set).
                _call(f"crm____searchCustomers", live_id=created.request_id),
                _call(f"crm____createOrder", live_id=created.request_id),
                # An ordinary conversation tool call is neither replay nor live.
                _call("system____save_data"),
            ]
        )
        await db_session.flush()

        audit = await service.session_audit(db_session, session.id)

        assert audit["replay_verifications"] == 2
        assert audit["live_operations"] == 2
        assert audit["replay_only"] is False
        assert audit["last_live_at"] is not None

    @pytest.mark.asyncio
    async def test_no_live_call_means_replay_only(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)

        audit = await OptimizationLiveTestService().session_audit(
            db_session, session.id
        )

        assert audit == {
            "replay_verifications": 0,
            "live_operations": 0,
            "last_live_at": None,
            "replay_only": True,
        }

    @pytest.mark.asyncio
    async def test_resume_payload_for_a_denied_request_is_status_only(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        row = await db_session.get(OptimizationLiveTestRequest, created.request_id)
        await service.mark_denied(db_session, row)

        payload = outcome_of(row).resume_payload()

        assert payload["live_test_status"] == "denied"
        assert payload["live_test_request_id"] == str(row.id)
        assert payload["script_version_id"] == str(version.id)
        assert "executed_operations" not in payload
        assert "script_run" not in payload

    @pytest.mark.asyncio
    async def test_resume_payload_for_an_executed_run_carries_the_run_record(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        _definition, version = await _script(db_session, agent_type)
        service = OptimizationLiveTestService()
        created = await service.create_request(
            db_session,
            conversation_session_id=session.id,
            script_version_id=version.id,
        )
        run_record = service.build_script_run_record(
            script_version_id=version.id,
            script_name="live-test-script",
            script_version_label="v1",
            status="success",
            result_summary='{"ok": true}',
            tool_calls=[{"tool_name": PERMITTED_TOOL, "status": "success"}],
            telemetry={"tool_calls": 1},
            duration_ms=9,
            error=None,
        )
        await service.begin_execution(db_session, created.request_id)
        await service.complete_execution(
            db_session,
            created.request_id,
            executed_operations=[run_record],
            failed=False,
            started_at=NOW,
            finished_at=NOW,
        )
        row = await db_session.get(OptimizationLiveTestRequest, created.request_id)

        payload = outcome_of(row).resume_payload()

        assert payload["live_test_status"] == "executed"
        assert payload["script_version_id"] == str(version.id)
        assert payload["executed_operations"] == [run_record]
        assert payload["script_run"] == run_record

    @pytest.mark.asyncio
    async def test_pending_summaries_expose_the_script_and_its_preview(
        self, db_session: AsyncSession, permitted_tools
    ):
        agent_type = await _subject(db_session)
        session = await _conversation(db_session, agent_type)
        definition, version = await _script(db_session, agent_type)
        intervene = InterveneRequest(
            id=uuid.uuid4(),
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="Run this script live",
            conversation_session_id=session.id,
        )
        db_session.add(intervene)
        await db_session.flush()
        row = OptimizationLiveTestRequest(
            id=uuid.uuid4(),
            conversation_session_id=session.id,
            target_agent_type_id=agent_type.id,
            intervene_request_id=intervene.id,
            script_version_id=version.id,
            status=OptimizationLiveTestStatus.pending,
            requested_operations=[{"tool_name": PERMITTED_TOOL}],
            expires_at=NOW + timedelta(minutes=10),
        )
        db_session.add(row)
        await db_session.flush()

        summaries = await OptimizationLiveTestService().pending_intervention_summaries(
            db_session, [intervene.id]
        )

        summary = summaries[intervene.id]
        assert summary["live_test_request_id"] == row.id
        assert summary["status"] == "pending"
        assert summary["script_version_id"] == version.id
        assert summary["script_name"] == definition.name
        assert summary["script_version_label"] == version.version_label
        assert summary["operations"] == [{"tool_name": PERMITTED_TOOL}]
        assert summary["executed_operations"] is None
        assert summary["target_agent_type_id"] == agent_type.id

    @pytest.mark.asyncio
    async def test_service_is_a_singleton(self):
        assert get_live_test_service() is get_live_test_service()
