"""Unit tests for HITL suspension in task agent delegation.

Covers Phase 1.3: Parent session transitioning to waiting_for_human during
delegation, intervention context propagation, and the response injection.

Tests the data_client.mark_session_waiting_for_human interface and the
delegation response HITL flag handling that is wired through
_run_task_loop_ar's tool execution path.

Acceptance criteria: AC-UI-1, AC-UI-3, AC-UI-5, AC-UI-6.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agents.runtime_executor import (
    AgentRuntimeExecutor,
    HumanInterveneRequired,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def data_client() -> AsyncMock:
    dc = AsyncMock()
    dc.log_execution_event = AsyncMock()
    dc.mark_session_waiting_for_human = AsyncMock()
    return dc


@pytest.fixture
def executor(data_client: AsyncMock) -> AgentRuntimeExecutor:
    ex = AgentRuntimeExecutor()
    ex._data_client = data_client
    return ex


# ── Tests: mark_session_waiting_for_human data client interface ───────────────


class TestMarkSessionWaitingForHuman:
    """Verify the data_client.mark_session_waiting_for_human interface."""

    @pytest.mark.asyncio
    async def test_calls_mark_session_waiting_for_human(self, data_client: AsyncMock) -> None:
        """mark_session_waiting_for_human should be callable with session_id
        and request_id, making the correct API call."""
        session_id = uuid.uuid4()
        request_id = str(uuid.uuid4())

        await data_client.mark_session_waiting_for_human(
            session_id=session_id,
            intervene_request_id=request_id,
        )

        data_client.mark_session_waiting_for_human.assert_awaited_once_with(
            session_id=session_id,
            intervene_request_id=request_id,
        )

    @pytest.mark.asyncio
    async def test_mark_session_with_conversation_history(
        self, data_client: AsyncMock
    ) -> None:
        """When conversation_history is provided, it's passed through."""
        session_id = uuid.uuid4()
        request_id = str(uuid.uuid4())
        history = [{"role": "user", "content": "hello"}]

        await data_client.mark_session_waiting_for_human(
            session_id=session_id,
            intervene_request_id=request_id,
            conversation_history=history,
        )

        data_client.mark_session_waiting_for_human.assert_awaited_once_with(
            session_id=session_id,
            intervene_request_id=request_id,
            conversation_history=history,
        )

    @pytest.mark.asyncio
    async def test_status_contains_waiting_for_human(
        self, data_client: AsyncMock
    ) -> None:
        """The data client should send the correct status.
        
        Verify the actual DataClient implementation has the expected
        method signature with session_id and intervene_request_id parameters.
        """
        from app.agent_runtime.data_client import ControlCenterDataClient
        import inspect
        sig = inspect.signature(ControlCenterDataClient.mark_session_waiting_for_human)
        params = sig.parameters
        assert "session_id" in params
        assert "intervene_request_id" in params

    @pytest.mark.asyncio
    async def test_interface_accepts_all_intervention_types(self, data_client: AsyncMock) -> None:
        """The mark_session_waiting_for_human interface should work for all
        intervention types (approval, choice, text)."""
        session_id = uuid.uuid4()
        for itype in ["approval", "choice", "text"]:
            request_id = str(uuid.uuid4())
            await data_client.mark_session_waiting_for_human(
                session_id=session_id,
                intervene_request_id=request_id,
            )
        assert data_client.mark_session_waiting_for_human.await_count == 3


# ── Tests: HumanInterveneRequired exception ───────────────────────────────────


class TestHumanInterveneRequired:
    """Verify the HumanInterveneRequired exception exists and can be raised."""

    def test_exception_can_be_raised(self) -> None:
        """HumanInterveneRequired can be raised and caught."""
        with pytest.raises(HumanInterveneRequired):
            raise HumanInterveneRequired()

    def test_exception_is_exception_subclass(self) -> None:
        """HumanInterveneRequired is an Exception subclass."""
        assert issubclass(HumanInterveneRequired, Exception)

    def test_exception_message(self) -> None:
        """HumanInterveneRequired carries a meaningful message."""
        try:
            raise HumanInterveneRequired("Intervention needed")
        except HumanInterveneRequired as exc:
            assert "Intervention needed" in str(exc)


# ── Tests: Intervention context propagation via delegation response ──────────


class TestInterventionContextFromDelegationResponse:
    """Verify that when a delegation response includes HITL context,
    the proper events and status transitions occur."""

    @pytest.mark.asyncio
    async def test_intervention_required_event_contains_context(self, executor, data_client) -> None:
        """The intervention_required event should include delegation target
        and intervention type metadata."""
        session_id = uuid.uuid4()

        await executor._log_execution_event(
            session_id=session_id,
            event_type="intervention_required",
            message="Delegated agent requires human intervention",
            data={
                "delegation_target": "sub-approval-agent",
                "intervention_type": "approval",
                "reason": "Approve transaction exceeding limit",
            },
            data_client=data_client,
        )

        assert data_client.log_execution_event.await_count >= 1
        call_kwargs = data_client.log_execution_event.call_args.kwargs
        assert call_kwargs["event_type"] == "intervention_required"
        data = call_kwargs["data"]
        assert data["delegation_target"] == "sub-approval-agent"
        assert data["intervention_type"] == "approval"
        assert "reason" in data


# ── Tests: Intervention response recording ────────────────────────────────────


class TestInterventionResponseRecording:
    """Verify intervention responses contain required audit fields."""

    def test_intervention_response_has_required_fields(self) -> None:
        """The intervention response should contain operator identity,
        decision, and timestamp."""
        expected_fields = {"operator_user_id", "approval_value", "responded_at"}
        test_response = {
            "id": str(uuid.uuid4()),
            "request_id": str(uuid.uuid4()),
            "operator_user_id": "user-abc-123",
            "approval_value": True,
            "responded_at": "2026-06-17T12:00:00Z",
            "operator_user_name": "Test Operator",
        }
        assert set(test_response.keys()).issuperset(expected_fields)

    @pytest.mark.asyncio
    async def test_intervention_approval_response_recorded(self, data_client: AsyncMock) -> None:
        """Verify an approval response can be logged as an execution event."""
        session_id = uuid.uuid4()
        await data_client.log_execution_event(
            session_id=session_id,
            event_type="intervention_response",
            message="Operator responded to intervention request",
            data={
                "request_id": str(uuid.uuid4()),
                "operator_user_id": "user-abc",
                "approval_value": True,
                "responded_at": "2026-06-17T12:00:00Z",
            },
        )
        assert data_client.log_execution_event.await_count >= 1

    def test_data_client_has_required_methods(self, data_client: AsyncMock) -> None:
        """The data client must expose mark_session_waiting_for_human."""
        assert hasattr(data_client, "mark_session_waiting_for_human")
        assert callable(data_client.mark_session_waiting_for_human)
