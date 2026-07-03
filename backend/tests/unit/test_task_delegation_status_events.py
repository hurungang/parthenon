"""Unit tests for delegation lifecycle event emission in the task agent path.

Covers Phase 1.2: delegation_started, delegation_waiting, delegation_resumed,
delegation_timeout, delegation_failed events emitted during task agent
delegation via _act().

Acceptance criteria: AC-DS-1 through AC-DS-5, AC-EC-1 through AC-EC-3.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agents.runtime_executor import AgentRuntimeExecutor


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def data_client() -> AsyncMock:
    dc = AsyncMock()
    return dc


@pytest.fixture
def executor(data_client: AsyncMock) -> AgentRuntimeExecutor:
    ex = AgentRuntimeExecutor()
    ex._data_client = data_client
    return ex


def _make_tool_call(
    call_id: str,
    tool_name: str = "agent__sub-agent",
    args: dict | None = None,
) -> dict:
    return {
        "id": call_id,
        "name": tool_name,
        "args": args or {"query": "test"},
    }


# ── Tests: Successful delegation lifecycle ────────────────────────────────────


class TestSuccessfulDelegationLifecycle:
    """Verify events emitted for a successful delegation (started→waiting→resumed)."""

    @pytest.mark.asyncio
    async def test_successful_delegation_emits_all_events(self, executor, data_client) -> None:
        """A successful delegation emits delegation_started, delegation_resumed
        with exit condition 'completed'."""
        from app.services.agents.agent_loop import TaskAgentLoop

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-agent"],
            system_instruction="Delegate and return",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=0,
            max_delegation_depth=1,
        )

        with patch.object(executor, '_permission_manager') as mock_perm:
            mock_perm.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    _make_tool_call("call-1", "agent__sub-agent", {"query": "analyze"})
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient") as mcc:
                    mock_comm = mcc.return_value
                    mock_comm.call_a2a_request = AsyncMock(
                        return_value={"receiver_session_id": "rcv-1", "status": "accepted"}
                    )
                    mock_comm.wait_for_a2a_response = AsyncMock(
                        return_value={"status": "completed", "output": "analysis result"}
                    )

                    await executor._act(ctx, {"agent__sub-agent"}, AsyncMock())

        # Extract event types from log_execution_event calls
        event_types: list[str] = [
            c.kwargs["event_type"]
            for c in data_client.log_execution_event.call_args_list
        ]

        # Verify key delegation events in order
        assert "delegation_started" in event_types, (
            "Expected delegation_started event"
        )
        assert "delegation_resumed" in event_types, (
            "Expected delegation_resumed event"
        )

        # Check delegation_started has correct metadata
        started_calls = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_started"
        ]
        assert len(started_calls) >= 1
        assert "sub-agent" in started_calls[0].kwargs.get("message", "")

        # Check delegation_resumed has exit condition "completed"
        resumed_calls = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_resumed"
        ]
        assert len(resumed_calls) >= 1
        assert resumed_calls[0].kwargs["data"].get("exit_condition") == "completed"

        # Verify delegation_started appears before delegation_resumed
        def first_index(events: list[str], target: str) -> int:
            for i, e in enumerate(events):
                if e == target:
                    return i
            return -1

        started_idx = first_index(event_types, "delegation_started")
        resumed_idx = first_index(event_types, "delegation_resumed")
        assert 0 <= started_idx < resumed_idx, (
            "delegation_started must appear before delegation_resumed"
        )

    @pytest.mark.asyncio
    async def test_delegation_emits_delegation_started_before_a2a(self, executor, data_client) -> None:
        """delegation_started is emitted before call_a2a_request is dispatched."""
        from app.services.agents.agent_loop import TaskAgentLoop

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-agent"],
            system_instruction="Test",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=0,
            max_delegation_depth=1,
        )

        started_before_a2a = False

        # Track order of calls
        call_order: list[str] = []

        original_log = executor._log_execution_event

        async def tracking_log(session_id, event_type, message, data, **kwargs):
            call_order.append(f"log:{event_type}")
            await original_log(session_id, event_type, message, data, **kwargs)

        executor._log_execution_event = tracking_log  # type: ignore[assignment]

        with patch.object(executor, '_permission_manager') as mock_perm:
            mock_perm.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    _make_tool_call("call-1", "agent__sub-agent")
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient") as mcc:
                    mock_comm = mcc.return_value

                    # Track when A2A is called
                    async def a2a_call(*args, **kwargs):
                        call_order.append("a2a:call_a2a_request")
                        return {"status": "completed", "output": "ok"}

                    mock_comm.call_a2a_request = AsyncMock(side_effect=a2a_call)

                    await executor._act(ctx, {"agent__sub-agent"}, AsyncMock())

        # Find positions
        started_idx = next(
            (i for i, v in enumerate(call_order) if v == "log:delegation_started"), -1
        )
        a2a_idx = next(
            (i for i, v in enumerate(call_order) if v == "a2a:call_a2a_request"), -1
        )
        assert started_idx >= 0, "delegation_started must be logged"
        assert a2a_idx >= 0, "call_a2a_request must be called"
        assert started_idx < a2a_idx, (
            "delegation_started must be emitted before call_a2a_request"
        )


# ── Tests: Delegation timeout ─────────────────────────────────────────────────


class TestDelegationTimeout:
    """Verify delegation_timeout event is emitted distinctly from failed."""

    @pytest.mark.asyncio
    async def test_delegation_timeout_on_a2a_exception(self, executor, data_client) -> None:
        """When call_a2a_request raises an exception with 'timeout' in the message,
        delegation_timeout event is emitted (distinct from delegation_failed).
        
        NOTE: The code checks for "timeout" in the error message string to
        distinguish timeout from other failures. We use a regular Exception
        with "timeout" in the message to test this branch."""
        from app.services.agents.agent_loop import TaskAgentLoop

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-agent"],
            system_instruction="Test",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=0,
            max_delegation_depth=1,
        )

        with patch.object(executor, '_permission_manager') as mock_perm:
            mock_perm.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    _make_tool_call("call-1", "agent__sub-agent")
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient") as mcc:
                    mock_comm = mcc.return_value
                    # Raise an exception with "timeout" in the message
                    mock_comm.call_a2a_request = AsyncMock(
                        side_effect=Exception("timeout: A2A request timed out")
                    )

                    await executor._act(ctx, {"agent__sub-agent"}, AsyncMock())

        timeout_events = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_timeout"
        ]
        assert len(timeout_events) >= 1, (
            "Expected delegation_timeout event for timeout exception"
        )
        assert "timed out" in timeout_events[0].kwargs.get("message", "").lower(), (
            "Timeout message should reference timeout"
        )

        # Verify NO delegation_failed was emitted for this error
        # (delegation_failed events may exist from other paths but not for this error)
        failed_events_with_timeout = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_failed"
            and "timed out" in c.kwargs.get("message", "")
        ]
        assert len(failed_events_with_timeout) == 0, (
            "Timeout should not emit delegation_failed — delegation_timeout is distinct"
        )

    @pytest.mark.asyncio
    async def test_delegation_timeout_from_response_status(self, executor, data_client) -> None:
        """When A2A response contains status 'timeout', delegation_timeout is emitted."""
        from app.services.agents.agent_loop import TaskAgentLoop

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-agent"],
            system_instruction="Test",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=0,
            max_delegation_depth=1,
        )

        with patch.object(executor, '_permission_manager') as mock_perm:
            mock_perm.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    _make_tool_call("call-1", "agent__sub-agent")
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient") as mcc:
                    mock_comm = mcc.return_value
                    mock_comm.call_a2a_request = AsyncMock(
                        return_value={"receiver_session_id": "rcv-1", "status": "accepted"}
                    )
                    mock_comm.wait_for_a2a_response = AsyncMock(
                        return_value={"status": "timeout", "error": "timed out"}
                    )

                    await executor._act(ctx, {"agent__sub-agent"}, AsyncMock())

        timeout_events = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_timeout"
        ]
        assert len(timeout_events) >= 1

        # delegation_resumed should still be emitted with exit_condition=timeout
        resumed_events = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_resumed"
        ]
        assert len(resumed_events) >= 1
        assert resumed_events[0].kwargs["data"].get("exit_condition") == "timeout"


# ── Tests: Delegation failed ──────────────────────────────────────────────────


class TestDelegationFailed:
    """Verify delegation_failed event is emitted distinctly from timeout."""

    @pytest.mark.asyncio
    async def test_delegation_failed_on_runtime_error(self, executor, data_client) -> None:
        """When call_a2a_request raises a non-timeout exception,
        delegation_failed event is emitted."""
        from app.services.agents.agent_loop import TaskAgentLoop

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-agent"],
            system_instruction="Test",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=0,
            max_delegation_depth=1,
        )

        with patch.object(executor, '_permission_manager') as mock_perm:
            mock_perm.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    _make_tool_call("call-1", "agent__sub-agent")
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient") as mcc:
                    mock_comm = mcc.return_value
                    mock_comm.call_a2a_request = AsyncMock(
                        side_effect=RuntimeError("Sub-agent crashed")
                    )

                    await executor._act(ctx, {"agent__sub-agent"}, AsyncMock())

        failed_events = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_failed"
        ]
        assert len(failed_events) >= 1, (
            "Expected delegation_failed event for runtime error"
        )
        assert "failed" in failed_events[0].kwargs.get("message", "").lower()

        # Verify NO delegation_timeout was emitted for this runtime error
        timeout_events = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_timeout"
        ]
        # There might be some from other flows, but check the error-specific one
        error_timeout = [
            c for c in timeout_events
            if "crashed" in c.kwargs.get("message", "")
        ]
        assert len(error_timeout) == 0, (
            "Runtime error should not emit delegation_timeout"
        )

    @pytest.mark.asyncio
    async def test_delegation_failed_from_response_status(self, executor, data_client) -> None:
        """When A2A response contains status 'failed', delegation_failed is emitted."""
        from app.services.agents.agent_loop import TaskAgentLoop

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-agent"],
            system_instruction="Test",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=0,
            max_delegation_depth=1,
        )

        with patch.object(executor, '_permission_manager') as mock_perm:
            mock_perm.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    _make_tool_call("call-1", "agent__sub-agent")
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient") as mcc:
                    mock_comm = mcc.return_value
                    mock_comm.call_a2a_request = AsyncMock(
                        return_value={"status": "failed", "error": "processing error"}
                    )

                    await executor._act(ctx, {"agent__sub-agent"}, AsyncMock())

        failed_events = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_failed"
        ]
        assert len(failed_events) >= 1

        resumed_events = [
            c for c in data_client.log_execution_event.call_args_list
            if c.kwargs.get("event_type") == "delegation_resumed"
        ]
        assert len(resumed_events) >= 1
        assert resumed_events[0].kwargs["data"].get("exit_condition") == "failed"


# ── Tests: Delegation events order verification ──────────────────────────────


class TestDelegationEventOrder:
    """Verify the relative ordering of delegation events."""

    @pytest.mark.asyncio
    async def test_delegation_events_appear_in_correct_order(self, executor, data_client) -> None:
        """Events should appear in this order:
        1. delegation_started
        2. delegation_timeout/delegation_failed (if error)
        3. delegation_resumed
        """
        from app.services.agents.agent_loop import TaskAgentLoop

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-agent"],
            system_instruction="Test",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=0,
            max_delegation_depth=1,
        )

        with patch.object(executor, '_permission_manager') as mock_perm:
            mock_perm.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    _make_tool_call("call-1", "agent__sub-agent")
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient") as mcc:
                    mock_comm = mcc.return_value
                    mock_comm.call_a2a_request = AsyncMock(
                        return_value={"status": "completed", "output": "ok"}
                    )

                    await executor._act(ctx, {"agent__sub-agent"}, AsyncMock())

        event_types: list[str] = [
            c.kwargs["event_type"]
            for c in data_client.log_execution_event.call_args_list
        ]

        # Filter to only delegation events
        delegation_events = [
            e for e in event_types
            if e.startswith("delegation_")
        ]

        # Must have at least started and resumed
        assert "delegation_started" in delegation_events
        assert "delegation_resumed" in delegation_events

        # Verify order: started before resumed
        started_pos = delegation_events.index("delegation_started")
        resumed_pos = delegation_events.index("delegation_resumed")
        assert started_pos < resumed_pos, (
            "delegation_started must be before delegation_resumed"
        )

    @pytest.mark.asyncio
    async def test_events_persisted_via_data_client(self, executor, data_client) -> None:
        """All delegation events are persisted via data_client.log_execution_event."""
        from app.services.agents.agent_loop import TaskAgentLoop

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-agent"],
            system_instruction="Test",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=0,
            max_delegation_depth=1,
        )

        with patch.object(executor, '_permission_manager') as mock_perm:
            mock_perm.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    _make_tool_call("call-1", "agent__sub-agent")
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient") as mcc:
                    mock_comm = mcc.return_value
                    mock_comm.call_a2a_request = AsyncMock(
                        return_value={"status": "completed", "output": "ok"}
                    )

                    await executor._act(ctx, {"agent__sub-agent"}, AsyncMock())

        assert data_client.log_execution_event.await_count >= 3, (
            "Expected at least 3 log events (tool_call, delegation_started, "
            "delegation_resumed, iteration_complete, etc.)"
        )

        # Verify each delegation event has required metadata
        for call in data_client.log_execution_event.call_args_list:
            kwargs = call.kwargs
            if kwargs.get("event_type", "").startswith("delegation_"):
                assert "session_id" in kwargs
                assert "message" in kwargs
                assert isinstance(kwargs.get("data"), dict), (
                    f"Event {kwargs['event_type']} must have data dict"
                )
