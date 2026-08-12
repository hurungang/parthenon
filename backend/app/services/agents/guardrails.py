"""Guardrail policy and runtime enforcement helpers for agent execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any


class GuardrailStopReason:
    """Canonical guardrail stop reason taxonomy."""

    CYCLE_DETECTED = "cycle_detected"
    ITERATION_LIMIT_EXCEEDED = "iteration_limit_exceeded"
    DELEGATION_DEPTH_EXCEEDED = "delegation_depth_exceeded"
    DELEGATED_STEPS_EXCEEDED = "delegated_steps_exceeded"
    EXECUTION_TIMEOUT_EXCEEDED = "execution_timeout_exceeded"
    TOKEN_BUDGET_EXCEEDED_NON_CONVERSATIONAL = "token_budget_exceeded_non_conversational"
    TOKEN_GUARDRAIL_FALLBACK_APPLIED = "token_guardrail_fallback_applied"


class GuardrailInfoReason:
    """Non-terminal informational guardrail event reason taxonomy."""

    CONVERSATIONAL_TOKEN_THRESHOLD_OBSERVED = "conversational_token_threshold_observed"
    TOKEN_THRESHOLD_OBSERVED = "token_budget_threshold_reached_observe_mode"


class GuardrailStop(Exception):
    """Exception raised for terminal guardrail enforcement decisions."""

    def __init__(self, reason: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.details = details or {}


class ModelAvailabilityBlockedError(RuntimeError):
    """Raised when the pre-execution availability check denies dispatch.

    The pre-execution check is performed by Agent Runtime before any
    model action; on deny, dispatch is blocked and the run is recorded
    with the appropriate ``AgentJob.termination_category`` and an
    execution log entry tagged with the matching ``event_category``
    (model_disabled or vendor_disabled).
    """

    def __init__(
        self,
        *,
        message: str,
        blocked_by: str,
        disabled_reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.blocked_by = blocked_by
        self.disabled_reason = disabled_reason
        self.details = details or {}


@dataclass(slots=True)
class RuntimeGuardrailState:
    """Mutable runtime counters used by execution loops and delegation accounting."""

    max_iterations: int
    max_delegation_depth: int
    max_delegated_steps: int
    execution_timeout_seconds: int
    token_budget: int | None
    token_enforcement_mode: str
    token_fallback_mode: str
    conversational_token_visibility_mode: str
    conversational_continuation_policy: str
    policy_snapshot_id: str
    start_monotonic_seconds: float = field(default_factory=monotonic)
    cumulative_iterations: int = 0
    delegated_steps: int = 0
    delegation_depth: int = 0
    tree_depth: int = 0
    token_usage_current_session: int = 0
    token_threshold_reached: bool = False
    token_enforcement_applied: bool = False

    def elapsed_seconds(self) -> float:
        return max(0.0, monotonic() - self.start_monotonic_seconds)


def detect_cycle_path(
    adjacency: dict[str, list[str]],
    root_node: str,
    *,
    max_nodes: int = 2048,
) -> list[str] | None:
    """Detect a delegation cycle and return an ordered cycle path if one exists."""
    visited: set[str] = set()
    stack: set[str] = set()
    parent: dict[str, str | None] = {}

    if len(adjacency) > max_nodes:
        raise ValueError(f"Delegation graph exceeds traversal limit ({max_nodes})")

    def _dfs(node: str) -> list[str] | None:
        visited.add(node)
        stack.add(node)

        for target in adjacency.get(node, []):
            if target not in visited:
                parent[target] = node
                found = _dfs(target)
                if found:
                    return found
            elif target in stack:
                # Reconstruct cycle path target -> ... -> node -> target.
                cycle_backtrack = [node]
                cursor = node
                while cursor != target:
                    prev = parent.get(cursor)
                    if prev is None:
                        break
                    cursor = prev
                    cycle_backtrack.append(cursor)
                cycle_backtrack.reverse()
                cycle_backtrack.append(target)
                return cycle_backtrack

        stack.remove(node)
        return None

    parent[root_node] = None
    found_cycle = _dfs(root_node)
    if found_cycle:
        return found_cycle

    # Graph may contain disconnected components; scan them too.
    for node in adjacency:
        if node not in visited:
            parent[node] = None
            found_cycle = _dfs(node)
            if found_cycle:
                return found_cycle

    return None


def extract_total_tokens_from_usage(usage: dict[str, Any] | None) -> int:
    """Extract total token usage from provider-normalized usage dict."""
    if not usage:
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, int):
        return max(0, total)
    return 0
