"""Live-test runner orchestration (Control Center side).

``turn_resolution.execute_approved_live_test`` is the only place a live test is
started. A live test runs the approved **script** end to end — never an
individual MCP tool call; MCP tools are assumed to work. It:

1. claims the single execution attempt (conditional transition) and commits the
   claim *before* the network hop, so the single-use gate holds even if the
   process dies mid-run;
2. loads the approved saved version's ``python_source`` (+ the reference
   execution's input so the script runs the real scenario) and forwards it to
   ``CC → CH → AR`` verbatim, with the ledger's server-derived subject — no
   operation list crosses the boundary, there is no per-operation execution;
3. persists the **script run record** exactly once (``executed``/``failed``)
   and returns it so the paused tool's resume value carries what actually ran.

A replay/second call returns the stored outcome and never runs anything; a
transport failure is terminal (``failed``) with no retry; a version that was
retired or repointed is never run.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.agents.optimization_live_test_service import (
    OptimizationLiveTestService,
    get_live_test_service,
)
from app.services.conversations import turn_resolution

NOW = datetime.now(timezone.utc)
PERMITTED_TOOL = "crm____searchCustomers"
SECOND_TOOL = "crm____createOrder"
SCRIPT_SOURCE = (
    "def run(context, tools):\n"
    f"    customer = tools.call('{PERMITTED_TOOL}', {{'q': 'ada'}})\n"
    f"    return tools.call('{SECOND_TOOL}', {{'q': 'ada', 'customer': customer}})\n"
)


@pytest.fixture
def permitted_tools(monkeypatch):
    async def _allowed(self, agent_type_id, db):  # noqa: ANN001
        return {PERMITTED_TOOL, SECOND_TOOL}

    monkeypatch.setattr(
        "app.services.agents.permission_manager.AgentPermissionManager."
        "calculate_agent_allowed_tools",
        _allowed,
    )


async def _approved_request(
    db: AsyncSession,
) -> OptimizationLiveTestRequest:
    agent_type = AgentType(
        id=uuid.uuid4(),
        name=f"runner-agent-{uuid.uuid4().hex[:8]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    session = ConversationSession(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        channel="optimization",
        status=ConversationStatus.active,
    )
    db.add(session)
    await db.flush()
    definition = ScriptDefinition(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        name=f"refund-script-{uuid.uuid4().hex[:8]}",
    )
    db.add(definition)
    await db.flush()
    version = ScriptVersion(
        id=uuid.uuid4(),
        script_definition_id=definition.id,
        version_label=f"v{uuid.uuid4().hex[:4]}",
        python_source=SCRIPT_SOURCE,
        sandbox_validation_status=SandboxValidationStatus.passed,
    )
    db.add(version)
    await db.flush()

    service = OptimizationLiveTestService()
    created = await service.create_request(
        db,
        conversation_session_id=session.id,
        script_version_id=version.id,
        reason="need real data",
    )
    assert created.accepted is True, created.reason
    await db.commit()
    row = await db.get(OptimizationLiveTestRequest, created.request_id)
    assert row is not None
    return row


def _script_run_record(status: str = "success", error: str | None = None) -> dict:
    return {
        "kind": "script_run",
        "script_version_id": str(uuid.uuid4()),
        "script_name": "refund-script",
        "script_version_label": "v1",
        "status": status,
        "result_summary": '{"refunded": true}' if status == "success" else None,
        "error": error,
        "duration_ms": 42,
        "tool_calls": [
            {
                "tool_name": PERMITTED_TOOL,
                "status": "success",
                "duration_ms": 5,
                "result_summary": '{"name": "Ada"}',
                "error": None,
            }
        ],
        "telemetry": {"tool_calls": 1, "duration_ms": 42},
    }


def _forward_result(status: str = "executed", records=None, error=None):
    return {
        "status": status,
        "executed_operations": records
        if records is not None
        else [_script_run_record()],
        "started_at": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
        "error": error,
    }


class TestExecuteApprovedLiveTest:
    @pytest.mark.asyncio
    async def test_forwards_the_approved_script_once(
        self, db_session: AsyncSession, permitted_tools
    ):
        row = await _approved_request(db_session)
        forward = AsyncMock(return_value=_forward_result())

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            forward,
        ), patch.object(
            turn_resolution, "push_live_test_result", AsyncMock()
        ):
            payload = await turn_resolution.execute_approved_live_test(
                db_session, row.id
            )

        forward.assert_awaited_once()
        kwargs = forward.await_args.kwargs
        assert kwargs["live_test_request_id"] == str(row.id)
        assert kwargs["conversation_session_id"] == str(row.conversation_session_id)
        # The subject comes from the LEDGER row — the server-derived subject.
        assert kwargs["target_agent_type_id"] == str(row.target_agent_type_id)
        # The SCRIPT is the unit of execution: its source crosses the boundary…
        assert kwargs["script_version_id"] == str(row.script_version_id)
        assert kwargs["python_source"] == SCRIPT_SOURCE
        assert kwargs["script_name"].startswith("refund-script-")
        assert kwargs["script_version_label"].startswith("v")
        # …state context only (the reference input), never credentials.
        assert kwargs["input_context"] == {}
        # …and no operation list is executed tool-by-tool.
        assert "operations" not in kwargs
        assert "requested_operations" not in kwargs

        assert payload["live_test_status"] == "executed"
        assert payload["live_test_request_id"] == str(row.id)
        assert payload["script_version_id"] == str(row.script_version_id)
        assert len(payload["executed_operations"]) == 1
        assert payload["executed_operations"][0]["kind"] == "script_run"
        assert "live_test_error" not in payload

    @pytest.mark.asyncio
    async def test_the_script_run_record_is_persisted_on_the_ledger(
        self, db_session: AsyncSession, permitted_tools
    ):
        row = await _approved_request(db_session)
        record = _script_run_record()

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            AsyncMock(return_value=_forward_result(records=[record])),
        ), patch.object(turn_resolution, "push_live_test_result", AsyncMock()):
            await turn_resolution.execute_approved_live_test(db_session, row.id)

        refreshed = await db_session.get(OptimizationLiveTestRequest, row.id)
        await db_session.refresh(refreshed)
        assert refreshed.status is OptimizationLiveTestStatus.executed
        assert refreshed.execution_started_at is not None
        assert refreshed.execution_finished_at is not None
        # Exactly one record describing the whole run.
        assert refreshed.executed_operations == [record]
        assert refreshed.executed_operations[0]["telemetry"] == {
            "tool_calls": 1,
            "duration_ms": 42,
        }

    @pytest.mark.asyncio
    async def test_the_resume_carries_the_script_run(
        self, db_session: AsyncSession, permitted_tools
    ):
        row = await _approved_request(db_session)
        record = _script_run_record()

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            AsyncMock(return_value=_forward_result(records=[record])),
        ), patch.object(turn_resolution, "push_live_test_result", AsyncMock()):
            payload = await turn_resolution.execute_approved_live_test(
                db_session, row.id
            )

        # The paused tool returns exactly what ran, so the model refines without
        # any further live call.
        assert payload["script_run"] == record
        assert payload["script_run"]["tool_calls"][0]["tool_name"] == PERMITTED_TOOL

    @pytest.mark.asyncio
    async def test_a_failed_run_marks_the_ledger_failed(
        self, db_session: AsyncSession, permitted_tools
    ):
        row = await _approved_request(db_session)
        failed_record = _script_run_record(
            status="error",
            error=(
                "live_test_permission_denied: the script's tool call was denied; "
                "nothing else was attempted"
            ),
        )
        failed_record["tool_calls"][0].update(
            {"status": "error", "result_summary": None, "error": "denied"}
        )

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            AsyncMock(
                return_value=_forward_result(
                    status="failed",
                    records=[failed_record],
                    error="live_test_permission_denied: denied",
                )
            ),
        ), patch.object(turn_resolution, "push_live_test_result", AsyncMock()) as push:
            payload = await turn_resolution.execute_approved_live_test(
                db_session, row.id
            )

        assert payload["live_test_status"] == "failed"
        assert payload["live_test_error"].startswith("live_test_permission_denied")
        assert len(payload["executed_operations"]) == 1
        assert payload["executed_operations"][0]["status"] == "error"

        refreshed = await db_session.get(OptimizationLiveTestRequest, row.id)
        await db_session.refresh(refreshed)
        assert refreshed.status is OptimizationLiveTestStatus.failed
        # The result chunk is pushed before the resumed reply.
        push.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transport_failure_is_terminal_and_never_retried(
        self, db_session: AsyncSession, permitted_tools
    ):
        from app.services.control_center.comm_hub_client import (
            CommunicationHubClientError,
        )

        row = await _approved_request(db_session)
        forward = AsyncMock(side_effect=CommunicationHubClientError("boom"))

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            forward,
        ), patch.object(turn_resolution, "push_live_test_result", AsyncMock()):
            payload = await turn_resolution.execute_approved_live_test(
                db_session, row.id
            )

        assert forward.await_count == 1
        assert payload["live_test_status"] == "failed"
        assert "boom" in payload["live_test_error"]
        # A failed run always leaves one record saying what failed.
        assert len(payload["executed_operations"]) == 1
        assert payload["executed_operations"][0]["kind"] == "script_run"
        assert payload["executed_operations"][0]["status"] == "error"
        refreshed = await db_session.get(OptimizationLiveTestRequest, row.id)
        await db_session.refresh(refreshed)
        assert refreshed.status is OptimizationLiveTestStatus.failed

    @pytest.mark.asyncio
    async def test_a_retired_or_repointed_script_is_never_run(
        self, db_session: AsyncSession, permitted_tools
    ):
        """The source must still belong to the subject: a version repointed to
        another agent type runs nothing (the ledger still records the failure)."""
        row = await _approved_request(db_session)
        other_agent = AgentType(
            id=uuid.uuid4(),
            name=f"repointed-agent-{uuid.uuid4().hex[:8]}",
            input_type=AgentInputType.typed,
            output_type=AgentOutputType.markdown,
            is_active=True,
        )
        db_session.add(other_agent)
        await db_session.flush()
        version = await db_session.get(ScriptVersion, row.script_version_id)
        definition = await db_session.get(
            ScriptDefinition, version.script_definition_id
        )
        definition.agent_type_id = other_agent.id
        await db_session.commit()
        forward = AsyncMock()

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            forward,
        ), patch.object(turn_resolution, "push_live_test_result", AsyncMock()):
            payload = await turn_resolution.execute_approved_live_test(
                db_session, row.id
            )

        forward.assert_not_awaited()
        assert payload["live_test_status"] == "failed"
        assert "source to run" in payload["live_test_error"]
        refreshed = await db_session.get(OptimizationLiveTestRequest, row.id)
        await db_session.refresh(refreshed)
        assert refreshed.status is OptimizationLiveTestStatus.failed

    @pytest.mark.asyncio
    async def test_a_second_execution_returns_the_stored_outcome(
        self, db_session: AsyncSession, permitted_tools
    ):
        row = await _approved_request(db_session)
        forward = AsyncMock(return_value=_forward_result())

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            forward,
        ), patch.object(turn_resolution, "push_live_test_result", AsyncMock()):
            first = await turn_resolution.execute_approved_live_test(
                db_session, row.id
            )
            second = await turn_resolution.execute_approved_live_test(
                db_session, row.id
            )

        # Exactly ONE forward — the replayed approval executes nothing.
        assert forward.await_count == 1
        assert first["live_test_status"] == second["live_test_status"] == "executed"
        assert second["executed_operations"] == first["executed_operations"]
        assert second["script_run"] == first["script_run"]

    @pytest.mark.asyncio
    async def test_a_denied_request_never_forwards(
        self, db_session: AsyncSession, permitted_tools
    ):
        row = await _approved_request(db_session)
        service = OptimizationLiveTestService()
        await service.mark_denied(db_session, row)
        await db_session.commit()
        forward = AsyncMock()

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            forward,
        ), patch.object(turn_resolution, "push_live_test_result", AsyncMock()):
            payload = await turn_resolution.execute_approved_live_test(
                db_session, row.id
            )

        forward.assert_not_awaited()
        assert payload["live_test_status"] == "denied"
        assert "executed_operations" not in payload

    @pytest.mark.asyncio
    async def test_an_expired_request_never_forwards(
        self, db_session: AsyncSession, permitted_tools
    ):
        row = await _approved_request(db_session)
        service = OptimizationLiveTestService()
        await service.mark_expired(db_session, row)
        await db_session.commit()
        forward = AsyncMock()

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            forward,
        ), patch.object(turn_resolution, "push_live_test_result", AsyncMock()):
            payload = await turn_resolution.execute_approved_live_test(
                db_session, row.id
            )

        forward.assert_not_awaited()
        assert payload["live_test_status"] == "expired"

    @pytest.mark.asyncio
    async def test_a_missing_request_is_a_stored_failure(
        self, db_session: AsyncSession, permitted_tools
    ):
        payload = await turn_resolution.execute_approved_live_test(
            db_session, uuid.uuid4()
        )
        assert payload["live_test_status"] == "failed"
        assert payload["live_test_error"] == "not_found"

    @pytest.mark.asyncio
    async def test_tenant_context_is_threaded_into_the_forward(
        self, db_session: AsyncSession, permitted_tools
    ):
        from app.core.tenant_context import TenantContext

        row = await _approved_request(db_session)
        context = TenantContext(
            tenant_id=uuid.uuid4(), slug="t", name="T", is_system_tenant=False
        )
        forward = AsyncMock(return_value=_forward_result())

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "forward_live_test",
            forward,
        ), patch.object(turn_resolution, "push_live_test_result", AsyncMock()):
            await turn_resolution.execute_approved_live_test(
                db_session, row.id, tenant_context=context
            )

        assert forward.await_args.kwargs["tenant_context"] is context

    @pytest.mark.asyncio
    async def test_only_control_center_originates_the_run(self):
        """Structural: the AR/CH run endpoints take an already-authorized script
        and no public/self-service trigger exists."""
        from pathlib import Path

        import app.agent_runtime.api.live_test as ar_live_test
        import app.communication_hub.api.internal.live_test_forwarding as ch_forwarding

        ar_source = Path(ar_live_test.__file__).read_text()
        ch_source = Path(ch_forwarding.__file__).read_text()
        assert "app.services.conversations" not in ar_source
        assert "app.services.conversations" not in ch_source
        assert "optimization_live_test_service" not in ar_source
        assert "optimization_live_test_service" not in ch_source
        assert "/internal/live-test/run" in ar_source
        assert "/internal/live-test/run" in ch_source
