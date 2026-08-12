"""Guardrail Callback — enforces execution limits via LangChain event hooks.

AsyncCallbackHandler that checks iteration limits, token budgets, and
delegation depth at LLM call boundaries to prevent runaway agents.

Complements the inline guardrail checks already present in runtime_executor.py
(those remain as the primary enforcement path; this callback provides an
additional LangChain-native enforcement point for future integration).

Raises:
    GuardrailStop: When any guardrail limit is exceeded. Propagates up
        through the LangChain chain and can be caught by the agent loop.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Union

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


class GuardrailStop(Exception):
    """Raised by GuardrailCallback when an execution limit is exceeded."""

    def __init__(self, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


class GuardrailCallback(AsyncCallbackHandler):
    """LangChain AsyncCallbackHandler that enforces Parthenon execution guardrails.

    Checks the following on each LLM call:
    - Iteration limit (max_iterations): Stops if iteration_count > max_iterations
    - Token budget (token_budget): Stops if cumulative tokens > token_budget
    - Delegation depth (max_delegation_depth): Stops if delegation_depth > max_delegation_depth
    - Wall-clock timeout (timeout_seconds): Stops if elapsed time >= timeout_seconds

    Designed to work alongside the existing inline guardrail checks in
    runtime_executor.py — not to replace them.

    Usage:
        state = GuardrailState(
            max_iterations=10,
            max_tokens_total=100_000,
            timeout_seconds=300,
        )
        callback = GuardrailCallback(
            guardrail_state=state,
            session_id="sess-123",
        )
        response = await llm.ainvoke(messages, config={"callbacks": [callback]})
    """

    def __init__(
        self,
        guardrail_state: Any,
        session_id: str,
        data_client: Any = None,
        execution_mode: str = "task",
    ) -> None:
        """Initialise the guardrail callback.

        Args:
            guardrail_state: An object with attributes:
                - iteration_count (int): Current iteration number
                - max_iterations (int | None): Max allowed iterations (None = no limit)
                - tokens_used (int): Cumulative tokens consumed so far
                - max_tokens_total (int | None): Token budget (None = no limit)
                - started_at (float | None): Epoch time when the loop started
                - timeout_seconds (float | None): Max wall-clock seconds (None = no limit)
            session_id: The current agent session ID (for logging).
            data_client: Optional data client for logging guardrail events.
            execution_mode: "task" or "conversation" — affects log messages.
        """
        super().__init__()
        self.guardrail_state = guardrail_state
        self.session_id = session_id
        self.data_client = data_client
        self.execution_mode = execution_mode

    @property
    def raise_error(self) -> bool:
        return True

    # ── LangChain callback hooks ──────────────────────────────────────────────

    async def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        **kwargs: Any,
    ) -> None:
        """Check iteration limit and timeout before each LLM call."""
        if hasattr(self.guardrail_state, "cumulative_iterations"):
            self.guardrail_state.cumulative_iterations += 1
        self._check_iteration_limit()
        self._check_timeout()
        await self._emit_guardrail_snapshot()

    async def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        """Check iteration limit and timeout before each chat model call."""
        if hasattr(self.guardrail_state, "cumulative_iterations"):
            self.guardrail_state.cumulative_iterations += 1
        self._check_iteration_limit()
        self._check_timeout()
        await self._emit_guardrail_snapshot()

    async def on_llm_end(
        self,
        response: LLMResult,
        **kwargs: Any,
    ) -> None:
        """Update token counter and check budget after each LLM call completes."""
        tokens_used = 0
        # Primary path: llm_output dict (OpenAI-style)
        if response.llm_output:
            token_usage = response.llm_output.get("token_usage") or {}
            tokens_used = token_usage.get("total_tokens", 0) or 0
        # Fallback: usage_metadata on generation messages (LangChain chat models)
        if not tokens_used and response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    if hasattr(gen, "message") and hasattr(gen.message, "usage_metadata"):
                        meta = gen.message.usage_metadata or {}
                        tokens_used = meta.get("total_tokens", 0) or 0
                        if tokens_used:
                            break
                if tokens_used:
                    break
        if tokens_used > 0 and hasattr(self.guardrail_state, "token_usage_current_session"):
            self.guardrail_state.token_usage_current_session += tokens_used
        self._check_token_budget()

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Check delegation depth before tool execution."""
        self._check_delegation_depth()

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _emit_guardrail_snapshot(self) -> None:
        """Emit a guardrail.runtime.snapshot event with current counters and limits.

        Allows the frontend LogSummaryPanel to display live guardrail usage
        during execution (not just after task_loop_completed).
        """
        if self.data_client is None:
            return
        gs = self.guardrail_state
        try:
            iteration = getattr(gs, "cumulative_iterations", 0)
            await self.data_client.log_execution_event(
                session_id=self.session_id,
                event_type="guardrail.runtime.snapshot",
                message=f"Guardrail state — iteration {iteration}",
                data={
                    "policy_snapshot_id": str(getattr(gs, "policy_snapshot_id", "unknown")),
                    "current_value": {
                        "cumulative_iterations": iteration,
                        "delegated_steps": getattr(gs, "delegated_steps", 0),
                        "delegation_depth": getattr(gs, "delegation_depth", 0),
                        "elapsed_seconds": gs.elapsed_seconds() if callable(getattr(gs, "elapsed_seconds", None)) else 0.0,
                        "token_usage_current_session": getattr(gs, "token_usage_current_session", 0),
                    },
                    "threshold_value": {
                        "max_iterations": getattr(gs, "max_iterations", None),
                        "max_delegation_depth": getattr(gs, "max_delegation_depth", None),
                        "max_delegated_steps": getattr(gs, "max_delegated_steps", None),
                        "token_budget": getattr(gs, "token_budget", None),
                        "execution_timeout_seconds": getattr(gs, "execution_timeout_seconds", None),
                    },
                },
            )
        except Exception:  # noqa: BLE001 — snapshot is non-critical; never block execution
            pass

    # ── Private guard checks ──────────────────────────────────────────────────

    def _check_iteration_limit(self) -> None:
        """Raise GuardrailStop if iteration limit exceeded."""
        max_iter = getattr(self.guardrail_state, "max_iterations", None)
        if max_iter is None:
            return
        current_iter = getattr(
            self.guardrail_state,
            "cumulative_iterations",
            getattr(self.guardrail_state, "iteration_count", 0),
        )
        if current_iter > max_iter:
            msg = (
                f"Iteration limit reached: {current_iter}/{max_iter} "
                f"(session={self.session_id})"
            )
            logger.warning("GuardrailCallback: %s", msg)
            raise GuardrailStop(
                reason="iteration_limit",
                details={
                    "iteration_count": current_iter,
                    "max_iterations": max_iter,
                    "session_id": self.session_id,
                },
            )

    def _check_token_budget(self) -> None:
        """Raise GuardrailStop if token budget exceeded."""
        max_tokens = getattr(self.guardrail_state, "token_budget", None) or getattr(self.guardrail_state, "max_tokens_total", None)
        if max_tokens is None:
            return
        tokens_used = getattr(self.guardrail_state, "token_usage_current_session", None)
        if tokens_used is None:
            tokens_used = getattr(self.guardrail_state, "tokens_used", 0)
        if tokens_used > max_tokens:
            msg = (
                f"Token budget exceeded: {tokens_used}/{max_tokens} "
                f"(session={self.session_id})"
            )
            logger.warning("GuardrailCallback: %s", msg)
            raise GuardrailStop(
                reason="token_budget",
                details={
                    "tokens_used": tokens_used,
                    "max_tokens_total": max_tokens,
                    "session_id": self.session_id,
                },
            )

    def _check_timeout(self) -> None:
        """Raise GuardrailStop if wall-clock timeout exceeded."""
        timeout = getattr(self.guardrail_state, "timeout_seconds", None)
        started_at = getattr(self.guardrail_state, "started_at", None)
        if timeout is None or started_at is None:
            return
        elapsed = time.monotonic() - started_at
        if elapsed >= timeout:
            msg = (
                f"Execution timeout: {elapsed:.1f}s >= {timeout}s "
                f"(session={self.session_id})"
            )
            logger.warning("GuardrailCallback: %s", msg)
            raise GuardrailStop(
                reason="timeout",
                details={
                    "elapsed_seconds": elapsed,
                    "timeout_seconds": timeout,
                    "session_id": self.session_id,
                },
            )

    def _check_delegation_depth(self) -> None:
        """Raise GuardrailStop if delegation depth limit exceeded."""
        max_depth = getattr(self.guardrail_state, "max_delegation_depth", None)
        if max_depth is None:
            return
        current_depth = getattr(self.guardrail_state, "delegation_depth", 0)
        if current_depth > max_depth:
            msg = (
                f"Delegation depth limit reached: {current_depth}/{max_depth} "
                f"(session={self.session_id})"
            )
            logger.warning("GuardrailCallback: %s", msg)
            raise GuardrailStop(
                reason="delegation_depth",
                details={
                    "delegation_depth": current_depth,
                    "max_delegation_depth": max_depth,
                    "session_id": self.session_id,
                },
            )
