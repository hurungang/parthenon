import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.agents.guardrails import (
    GuardrailStop,
    GuardrailStopReason,
    RuntimeGuardrailState,
    detect_cycle_path,
)
from app.services.agents.runtime_executor import AgentRuntimeExecutor


def test_detect_cycle_path_self_loop():
    adjacency = {"a": ["a"]}
    cycle = detect_cycle_path(adjacency, "a")
    assert cycle == ["a", "a"]


def test_detect_cycle_path_indirect_cycle():
    adjacency = {
        "a": ["b"],
        "b": ["c"],
        "c": ["a"],
    }
    cycle = detect_cycle_path(adjacency, "a")
    assert cycle is not None
    assert cycle[0] == "a"
    assert cycle[-1] == "a"


def test_detect_cycle_path_acyclic_graph():
    adjacency = {
        "a": ["b"],
        "b": ["c"],
        "c": [],
    }
    cycle = detect_cycle_path(adjacency, "a")
    assert cycle is None


def test_detect_cycle_path_traversal_limit():
    adjacency = {f"n{i}": [] for i in range(5)}
    with pytest.raises(ValueError, match="traversal limit"):
        detect_cycle_path(adjacency, "n0", max_nodes=2)


@pytest.mark.asyncio
async def test_precheck_blocks_when_cycle_detected():
    executor = AgentRuntimeExecutor()
    data_client = AsyncMock()

    state = RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="policy-1",
    )

    with pytest.raises(GuardrailStop) as exc_info:
        await executor._precheck_delegation_graph(
            session_id=uuid.uuid4(),
            agent_type_slug="root-agent",
            context={
                "delegation_graph": {
                    "root-agent": ["child-agent"],
                    "child-agent": ["root-agent"],
                }
            },
            data_client=data_client,
            guardrail_state=state,
        )

    err = exc_info.value
    assert getattr(err, "reason", None) == GuardrailStopReason.CYCLE_DETECTED
    assert data_client.log_execution_event.await_count >= 1


@pytest.mark.asyncio
async def test_precheck_blocks_when_graph_errors_present():
    executor = AgentRuntimeExecutor()
    data_client = AsyncMock()

    state = RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="policy-1",
    )

    with pytest.raises(GuardrailStop) as exc_info:
        await executor._precheck_delegation_graph(
            session_id=uuid.uuid4(),
            agent_type_slug="root-agent",
            context={
                "delegation_graph": {"root-agent": []},
                "delegation_graph_errors": ["Inactive delegated target 'x'"]
            },
            data_client=data_client,
            guardrail_state=state,
        )

    err = exc_info.value
    assert getattr(err, "reason", None) == GuardrailStopReason.CYCLE_DETECTED


@pytest.mark.asyncio
async def test_precheck_passes_when_allowed_agent_types_excludes_self():
    """allowed_agent_types that does NOT contain the root slug should pass."""
    executor = AgentRuntimeExecutor()
    data_client = AsyncMock()

    state = RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="policy-1",
    )

    await executor._precheck_delegation_graph(
        session_id=uuid.uuid4(),
        agent_type_slug="supabase-get-roles",
        context={
            "allowed_agent_types": ["supabase-query", "data-analyzer"],
        },
        data_client=data_client,
        guardrail_state=state,
    )

    assert data_client.log_execution_event.await_count >= 1
    call_kwargs = data_client.log_execution_event.call_args.kwargs
    assert call_kwargs["event_type"] == "guardrail.precheck.allowed"


@pytest.mark.asyncio
async def test_precheck_passes_when_allowed_agent_types_includes_self():
    """allowed_agent_types containing the root slug should NOT trigger a false self-loop.

    Regression test: the precheck must filter out the root agent from its own
    target list to avoid false "A → A" cycle detection.
    """
    executor = AgentRuntimeExecutor()
    data_client = AsyncMock()

    state = RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="policy-1",
    )

    await executor._precheck_delegation_graph(
        session_id=uuid.uuid4(),
        agent_type_slug="supabase-get-roles",
        context={
            "allowed_agent_types": ["supabase-get-roles", "supabase-query"],
        },
        data_client=data_client,
        guardrail_state=state,
    )

    assert data_client.log_execution_event.await_count >= 1
    call_kwargs = data_client.log_execution_event.call_args.kwargs
    assert call_kwargs["event_type"] == "guardrail.precheck.allowed"
