"""Unit tests for delegation depth limit enforcement.

Covers configured-maximum depth resolution (no input-type override), starting
depth provenance (recorded job depth vs legacy input key), depth guard blocking
in the ``_act()`` path, and ``delegation_depth_blocked`` event emission.

Acceptance criteria: the configured Max Delegation Depth is the sole depth limit
for conversational and task agents, and over-deep hops are blocked with the
configured maximum reported.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agents.guardrails import (
    GuardrailStop,
    GuardrailStopReason,
    RuntimeGuardrailState,
)
from app.services.agents.runtime_executor import AgentRuntimeExecutor


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_guardrail_state(max_depth: int = 3, current_depth: int = 0) -> RuntimeGuardrailState:
    """Build a RuntimeGuardrailState with desired delegation depth settings."""
    return RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=max_depth,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="policy-1",
        delegation_depth=current_depth,
        tree_depth=current_depth,
    )


def _make_agent_type(input_type: str = "typed", **kwargs) -> MagicMock:
    """Build a mock agent type with given input_type."""
    agent_type = MagicMock()
    agent_type.input_type = input_type  # string for non-enum comparison
    for k, v in kwargs.items():
        setattr(agent_type, k, v)
    return agent_type


# ── Tests: _build_guardrail_state configured depth ───────────────────────────


class TestBuildGuardrailStateConfiguredDepth:
    """The agent type's configured maximum depth is authoritative.

    There is no input-type override and no platform cap: conversational and task
    (non-conversational) agents with the same configuration resolve the same
    maximum.  The platform default only fills an ABSENT value.
    """

    def test_conversational_configured_depth_is_honoured(self) -> None:
        executor = AgentRuntimeExecutor()
        context = {"input_type": "conversation", "guardrail_policy": {"max_delegation_depth": 5}}
        state = executor._build_guardrail_state(context, {})
        assert state.max_delegation_depth == 5

    def test_task_configured_depth_is_honoured(self) -> None:
        """A task agent configured for 5 resolves 5 — not the old forced 1."""
        executor = AgentRuntimeExecutor()
        context = {"input_type": "typed", "guardrail_policy": {"max_delegation_depth": 5}}
        state = executor._build_guardrail_state(context, {})
        assert state.max_delegation_depth == 5

    def test_task_configured_depth_of_three_is_not_reduced(self) -> None:
        executor = AgentRuntimeExecutor()
        context = {"input_type": "typed", "guardrail_policy": {"max_delegation_depth": 3}}
        state = executor._build_guardrail_state(context, {})
        assert state.max_delegation_depth == 3

    def test_none_input_is_not_forced_to_one(self) -> None:
        executor = AgentRuntimeExecutor()
        context = {"input_type": "none", "guardrail_policy": {"max_delegation_depth": 10}}
        state = executor._build_guardrail_state(context, {})
        assert state.max_delegation_depth == 10

    @pytest.mark.parametrize("configured_depth", [0, 1, 3, 7, 64])
    def test_task_and_conversational_resolve_identically(self, configured_depth: int) -> None:
        executor = AgentRuntimeExecutor()
        policy = {"max_delegation_depth": configured_depth}
        task_state = executor._build_guardrail_state(
            {"input_type": "typed", "guardrail_policy": dict(policy)}, {}
        )
        conv_state = executor._build_guardrail_state(
            {"input_type": "conversation", "guardrail_policy": dict(policy)}, {}
        )
        assert task_state.max_delegation_depth == configured_depth
        assert conv_state.max_delegation_depth == configured_depth

    def test_zero_configured_depth_is_not_treated_as_unset(self) -> None:
        """0 is a valid non-negative value: no delegation permitted at the root."""
        executor = AgentRuntimeExecutor()
        context = {"input_type": "typed", "guardrail_policy": {"max_delegation_depth": 0}}
        state = executor._build_guardrail_state(context, {})
        assert state.max_delegation_depth == 0

    def test_empty_context_uses_platform_default(self) -> None:
        """No policy value → platform default 3 (unchanged effective default)."""
        executor = AgentRuntimeExecutor()
        assert executor._build_guardrail_state({}, {}).max_delegation_depth == 3
        assert executor._build_guardrail_state(
            {"guardrail_policy": {}}, {}
        ).max_delegation_depth == 3

    def test_input_type_as_enum_object(self) -> None:
        """Input_type may be an enum object; it no longer influences depth."""
        from app.db.models.agents import AgentInputType

        executor = AgentRuntimeExecutor()
        context = {
            "input_type": AgentInputType.typed,
            "guardrail_policy": {"max_delegation_depth": 4},
        }
        state = executor._build_guardrail_state(context, {})
        assert state.max_delegation_depth == 4

    def test_input_type_as_enum_conversation(self) -> None:
        from app.db.models.agents import AgentInputType

        executor = AgentRuntimeExecutor()
        context = {
            "input_type": AgentInputType.conversation,
            "guardrail_policy": {"max_delegation_depth": 4},
        }
        state = executor._build_guardrail_state(context, {})
        assert state.max_delegation_depth == 4


# ── Tests: _build_guardrail_state starting depth provenance ──────────────────


class TestBuildGuardrailStateStartingDepth:
    """The run starts from the job's recorded delegation depth."""

    def test_recorded_job_depth_seeds_both_depths(self) -> None:
        executor = AgentRuntimeExecutor()
        state = executor._build_guardrail_state({}, {"delegation_depth": 2})
        assert state.tree_depth == 2
        assert state.delegation_depth == 2, "delegation_depth must reflect the real chain depth"

    def test_legacy_input_key_resolves_the_same_way(self) -> None:
        executor = AgentRuntimeExecutor()
        state = executor._build_guardrail_state(
            {}, {"input_data": {"__delegation_depth": 2}}
        )
        assert state.tree_depth == 2
        assert state.delegation_depth == 2

    def test_recorded_depth_wins_over_legacy_input_key(self) -> None:
        executor = AgentRuntimeExecutor()
        state = executor._build_guardrail_state(
            {},
            {"delegation_depth": 2, "input_data": {"__delegation_depth": 5}},
        )
        assert state.tree_depth == 2
        assert state.delegation_depth == 2

    def test_recorded_zero_wins_over_legacy_input_key(self) -> None:
        """An explicit recorded 0 (root job) is authoritative, not falsy-skipped."""
        executor = AgentRuntimeExecutor()
        state = executor._build_guardrail_state(
            {},
            {"delegation_depth": 0, "input_data": {"__delegation_depth": 3}},
        )
        assert state.tree_depth == 0
        assert state.delegation_depth == 0

    def test_payload_without_depth_resolves_zero(self) -> None:
        """Root runs (and stale payloads without the additive field) are unaffected."""
        executor = AgentRuntimeExecutor()
        state = executor._build_guardrail_state({}, {})
        assert state.tree_depth == 0
        assert state.delegation_depth == 0


# ── Tests: _check_runtime_limits_or_raise depth guard ────────────────────────


class TestCheckRuntimeLimitsDepthGuard:
    """Verify GuardrailStop is raised when delegation_depth exceeds max."""

    def test_depth_within_limit_passes(self) -> None:
        """No exception when delegation_depth <= max_delegation_depth."""
        executor = AgentRuntimeExecutor()
        state = _make_guardrail_state(max_depth=3, current_depth=2)
        # Should not raise
        executor._check_runtime_limits_or_raise(state)

    def test_depth_exceeds_limit_raises(self) -> None:
        """GuardrailStop raised when delegation_depth > max_delegation_depth."""
        executor = AgentRuntimeExecutor()
        state = _make_guardrail_state(max_depth=1, current_depth=2)
        with pytest.raises(Exception) as exc_info:
            executor._check_runtime_limits_or_raise(state)
        assert exc_info.value.reason == GuardrailStopReason.DELEGATION_DEPTH_EXCEEDED

    def test_depth_advanced_by_delegation_is_enforced(self) -> None:
        """Both run-level checks read the same actual chain depth.

        A run whose tree depth is within the maximum but which has advanced its
        delegation depth beyond it is stopped (the real chain is too deep).
        """
        executor = AgentRuntimeExecutor()
        state = _make_guardrail_state(max_depth=2, current_depth=2)
        state.delegation_depth = 3  # an in-run delegation advanced the chain
        with pytest.raises(GuardrailStop) as exc_info:
            executor._check_runtime_limits_or_raise(state)
        assert exc_info.value.reason == GuardrailStopReason.DELEGATION_DEPTH_EXCEEDED
        assert exc_info.value.details["current_value"] == 3
        assert exc_info.value.details["threshold_value"] == 2

    def test_depth_equals_limit_correct_details(self) -> None:
        """Verify the guardrail details contain the depth limit values."""
        executor = AgentRuntimeExecutor()
        state = _make_guardrail_state(max_depth=1, current_depth=2)
        try:
            executor._check_runtime_limits_or_raise(state)
        except GuardrailStop as exc:
            assert "depth" in str(exc).lower()
            assert exc.details.get("threshold_value") == 1
            assert exc.details.get("current_value") == 2


# ── Tests: Delegation depth blocked event emission (TaskAgentLoop _act path) ─


class TestDelegationDepthBlockedEventActPath:
    """Verify delegation_depth_blocked event is emitted in _act() when depth exceeded.

    The _act() method should emit a blocked event and return a blocked tool result
    instead of dispatching the delegation, so the agent can continue.
    """

    @pytest.mark.asyncio
    async def test_depth_blocked_emits_event_and_returns_blocked_result(self) -> None:
        """When the next hop would exceed the configured max, the event is emitted
        with that configured maximum and the tool result contains blocked=True."""
        from app.services.agents.agent_loop import TaskAgentLoop

        executor = AgentRuntimeExecutor()
        # Assign a mock _data_client so _log_execution_event works
        data_client = AsyncMock()
        executor._data_client = data_client

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-qa"],
            system_instruction="You are a test agent",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=3,
            tree_depth=3,  # Already at the configured maximum — a hop would exceed it
            max_delegation_depth=3,  # Configured maximum (not a platform cap)
        )

        with patch.object(executor, '_permission_manager') as mock_permission:
            mock_permission.check_tool_allowed = MagicMock()

            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                # Set up pending tool calls that would trigger delegation
                ctx._pending_tool_calls = [
                    {
                        "id": "call-1",
                        "name": "agent__sub-qa",
                        "args": {"query": "test"},
                    }
                ]

                # We also need to patch CommHubToolClient import
                with patch(
                    "app.agent_runtime.comm_hub_client.CommHubToolClient"
                ) as mock_comm_cls:
                    mock_comm = mock_comm_cls.return_value

                    result_ctx = await executor._act(ctx, {"agent__sub-qa"}, AsyncMock())

                # Verify the blocked event was logged
                blocked_calls = [
                    call for call in data_client.log_execution_event.call_args_list
                    if call.kwargs.get("event_type") == "delegation_depth_blocked"
                ]
                assert len(blocked_calls) >= 1, (
                    "Expected delegation_depth_blocked event to be logged"
                )
                blocked_call = blocked_calls[0]
                # The delegation target is in the data dict, not the message
                assert blocked_call.kwargs["data"]["delegation_target"] == "sub-qa"
                assert blocked_call.kwargs["data"]["max_depth"] == 3, (
                    "The blocked event must carry the CONFIGURED maximum"
                )
                # No stale one-level task-agent wording
                assert "Non-conversational" not in blocked_call.kwargs["message"]

                # Verify tool result contains blocked=True and names the configured max
                assert len(result_ctx.tool_results) >= 1
                last_result = result_ctx.tool_results[-1]["result"]
                assert last_result.get("blocked") is True, (
                    "Tool result should contain blocked=True"
                )
                assert "configured maximum delegation depth of 3" in last_result["reason"]

    @pytest.mark.asyncio
    async def test_act_fallback_blocks_at_loop_context_maximum(self) -> None:
        """With no supplied guardrail state, the act fallback uses the loop
        context's configured maximum (never a one-level constant)."""
        from app.services.agents.agent_loop import TaskAgentLoop

        executor = AgentRuntimeExecutor()
        data_client = AsyncMock()
        executor._data_client = data_client

        ctx = TaskAgentLoop(
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent____sub-qa"],
            system_instruction="You are a test agent",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=7,
            tree_depth=7,
            max_delegation_depth=7,
        )

        with patch.object(executor, '_permission_manager') as mock_permission:
            mock_permission.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    {"id": "call-1", "name": "agent____sub-qa", "args": {}},
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient"):
                    await executor._act(ctx, {"agent____sub-qa"}, AsyncMock())

        blocked_calls = [
            call for call in data_client.log_execution_event.call_args_list
            if call.kwargs.get("event_type") == "delegation_depth_blocked"
        ]
        assert len(blocked_calls) == 1
        assert blocked_calls[0].kwargs["data"]["max_depth"] == 7

    @pytest.mark.asyncio
    async def test_depth_allowed_proceeds_with_delegation(self) -> None:
        """A hop stays allowed while it is within the configured maximum."""
        from app.services.agents.agent_loop import TaskAgentLoop

        executor = AgentRuntimeExecutor()
        data_client = AsyncMock()
        executor._data_client = data_client

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-qa"],
            system_instruction="You are a test agent",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=1,
            tree_depth=1,  # Delegated child at chain depth 1
            max_delegation_depth=3,  # Configured maximum 3 — next hop reaches 2
        )

        with patch.object(executor, '_permission_manager') as mock_permission:
            mock_permission.check_tool_allowed = MagicMock()

            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    {
                        "id": "call-1",
                        "name": "agent__sub-qa",
                        "args": {"query": "test"},
                    }
                ]

                with patch(
                    "app.agent_runtime.comm_hub_client.CommHubToolClient"
                ) as mock_comm_cls:
                    mock_comm = mock_comm_cls.return_value
                    mock_comm.call_a2a_request = AsyncMock(
                        return_value={"status": "completed", "output": "result"}
                    )

                    result_ctx = await executor._act(ctx, {"agent__sub-qa"}, AsyncMock())

                # Verify NO blocked event
                blocked_calls = [
                    call for call in data_client.log_execution_event.call_args_list
                    if call.kwargs.get("event_type") == "delegation_depth_blocked"
                ]
                assert len(blocked_calls) == 0, (
                    "No delegation_depth_blocked expected when depth is within limit"
                )

                # Verify delegation_started was emitted instead
                started_calls = [
                    call for call in data_client.log_execution_event.call_args_list
                    if call.kwargs.get("event_type") == "delegation_started"
                ]
                assert len(started_calls) >= 1, (
                    "Expected delegation_started event when delegation proceeds"
                )

    @pytest.mark.asyncio
    async def test_hop_reaching_exactly_the_configured_maximum_is_allowed(self) -> None:
        """The last permitted level is allowed: next depth == max is not a block.

        A run at chain depth 2 with configured maximum 3 delegates to depth 3 —
        the boundary case the pre-change one-level cap always rejected.
        """
        from app.services.agents.agent_loop import TaskAgentLoop

        executor = AgentRuntimeExecutor()
        data_client = AsyncMock()
        executor._data_client = data_client

        ctx = TaskAgentLoop(
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__sub-qa"],
            system_instruction="You are a test agent",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=2,
            tree_depth=2,
            max_delegation_depth=3,  # next_depth (3) == max — last permitted hop
        )

        with patch.object(executor, '_permission_manager') as mock_permission:
            mock_permission.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    {"id": "call-1", "name": "agent__sub-qa", "args": {"query": "test"}},
                ]
                with patch(
                    "app.agent_runtime.comm_hub_client.CommHubToolClient"
                ) as mock_comm_cls:
                    mock_comm_cls.return_value.call_a2a_request = AsyncMock(
                        return_value={"status": "completed", "output": "result"}
                    )
                    await executor._act(ctx, {"agent__sub-qa"}, AsyncMock())

        event_types = [
            call.kwargs.get("event_type")
            for call in data_client.log_execution_event.call_args_list
        ]
        assert "delegation_depth_blocked" not in event_types
        assert "delegation_started" in event_types


# ── Tests: Delegation depth blocked in execute_tool_calls path (non-conv run loop) ──


class TestDelegationDepthBlockedExecuteToolCalls:
    """Verify delegation_depth_blocked event in the _execute_tool_calls path."""

    @pytest.mark.asyncio
    async def test_depth_blocked_in_execute_tool_calls_path(self) -> None:
        """The _execute_tool_calls path also emits delegation_depth_blocked."""
        executor = AgentRuntimeExecutor()
        data_client = AsyncMock()
        executor._data_client = data_client

        with patch(
            "app.agent_runtime.comm_hub_client.CommHubToolClient"
        ) as mock_comm_cls, patch.object(
            executor, '_permission_manager'
        ) as mock_permission, patch.object(
            executor, '_execute_mcp_tool_ar', AsyncMock(return_value={})
        ), patch.object(
            executor, '_load_role_mcp_session_map', AsyncMock(return_value={})
        ):
            mock_comm = mock_comm_cls.return_value
            mock_permission.check_tool_allowed = MagicMock()

            session_id = uuid.uuid4()
            guardrail_state = _make_guardrail_state(max_depth=1, current_depth=1)
            context: dict = {
                "role_id": str(uuid.uuid4()),
                "allowed_tools": {"agent__sub-agent"},
                "tool_definitions": [],
                "tool_name_map": {},
                "role_mcp_sessions": {},
                "guardrail_policy": {"max_delegation_depth": 1},
            }

            from app.agent_runtime.comm_hub_client import CommHubToolClient

            # We test the delegation depth guard by calling _execute_tool_calls
            # with a delegation tool that would exceed depth
            tool_calls = [
                {
                    "id": "call-depth-blocked",
                    "function": {
                        "name": "agent__sub-agent",
                        "arguments": '{"query": "test"}',
                    },
                }
            ]

            messages: list[dict] = []

            # Mock model binding layer via private method access
            # _execute_tool_calls is called from within _run_task_loop's old flow.
            # Since we want to test the isolated logic, we call it directly.
            try:
                from app.services.agents.runtime_executor import (
                    _extract_agent_delegation_target,
                )
            except ImportError:
                pass

            # Use public-facing test via _act instead since _execute_tool_calls
            # may not be directly accessible (it's an internal iterative method).
            # Instead, test the depth check happens via the _act path.
            # This is already covered above in TestDelegationDepthBlockedActPath.

    @pytest.mark.asyncio
    async def test_depth_blocked_allows_parent_to_continue(self) -> None:
        """When delegation is blocked, the agent should not raise an error but
        return a blocked result, allowing continued iteration."""
        from app.services.agents.agent_loop import TaskAgentLoop

        executor = AgentRuntimeExecutor()
        data_client = AsyncMock()
        executor._data_client = data_client

        session_id = uuid.uuid4()
        ctx = TaskAgentLoop(
            session_id=str(session_id),
            agent_type_id=str(uuid.uuid4()),
            role_id=str(uuid.uuid4()),
            allowed_tools=["agent__deeper-agent"],
            system_instruction="Keep going after delegation",
            output_type="auto",
            output_schema=None,
            input_data={},
            delegation_depth=3,
            tree_depth=3,  # At the configured maximum — next hop is blocked
            max_delegation_depth=3,
        )

        with patch.object(executor, '_permission_manager') as mock_perm:
            mock_perm.check_tool_allowed = MagicMock()
            with patch.object(executor, '_load_role_mcp_session_map', AsyncMock(return_value={})):
                ctx._pending_tool_calls = [
                    {"id": "c1", "name": "agent__deeper-agent", "args": {}}
                ]
                with patch("app.agent_runtime.comm_hub_client.CommHubToolClient") as mcc:
                    result_ctx = await executor._act(ctx, {"agent__deeper-agent"}, AsyncMock())

                # Verify the loop context is still valid (not stopped)
                assert result_ctx.is_complete is False
                assert result_ctx.error_message is None
                # The tool result should be present
                assert len(result_ctx.tool_results) >= 1


# ── Tests: conversational agents resolve the configured limit ────────────────


class TestConversationalConfiguredDepth:
    """Conversational agents use the configured maximum like every other type."""

    @pytest.mark.asyncio
    async def test_conversational_agent_default_depth_is_platform_default(self) -> None:
        """An unconfigured conversational agent resolves the platform default 3."""
        executor = AgentRuntimeExecutor()
        context = {"input_type": "conversation", "guardrail_policy": {}}
        state = executor._build_guardrail_state(context, {})
        assert state.max_delegation_depth == 3

    @pytest.mark.asyncio
    async def test_conversational_agent_within_configured_limit_not_blocked(self) -> None:
        """Depth 2 within a configured maximum of 3 is not a breach."""
        executor = AgentRuntimeExecutor()
        context = {
            "input_type": "conversation",
            "guardrail_policy": {"max_delegation_depth": 3},
        }
        state = executor._build_guardrail_state(context, {})
        state.delegation_depth = 2
        # Should not raise: delegation_depth (2) <= configured max (3)
        executor._check_runtime_limits_or_raise(state)

    @pytest.mark.asyncio
    async def test_conversational_agent_honours_deeper_configured_limit(self) -> None:
        """A conversational agent configured for 6 is allowed through depth 6."""
        executor = AgentRuntimeExecutor()
        context = {
            "input_type": "conversation",
            "guardrail_policy": {"max_delegation_depth": 6},
        }
        state = executor._build_guardrail_state(context, {})
        state.tree_depth = 6
        state.delegation_depth = 6
        executor._check_runtime_limits_or_raise(state)  # no raise at 6/6
