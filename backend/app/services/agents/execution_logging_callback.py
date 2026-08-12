"""Execution Logging Callback — emits Parthenon execution events via LangChain hooks.

AsyncCallbackHandler that records LLM calls, tool dispatches, and token usage
as structured execution log events during agent runs.

Integrates with Parthenon's existing execution log infrastructure by calling
data_client.log_execution_event() at each LLM/tool boundary, enabling the
LogViewer / WorkingStepsPanel UI to display hierarchical execution timelines.

Event types emitted:
- "llm_request"    — on_chat_model_start / on_llm_start
- "llm_response"   — on_llm_end (includes token usage when available)
- "tool_call"      — on_tool_start
- "tool_response"  — on_tool_end
- "tool_error"     — on_tool_error
- "llm_error"      — on_llm_error / on_chain_error
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Union

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


class ExecutionLoggingCallback(AsyncCallbackHandler):
    """LangChain AsyncCallbackHandler that emits Parthenon execution log events.

    Calls data_client.log_execution_event() for each LLM call, tool dispatch,
    and response to provide real-time visibility into agent execution.

    Complements the existing inline logging in runtime_executor.py.

    Usage:
        callback = ExecutionLoggingCallback(
            session_id="sess-123",
            data_client=data_client,
            iteration_ref=[0],  # mutable ref to track current iteration
        )
        response = await llm.ainvoke(messages, config={"callbacks": [callback]})
    """

    def __init__(
        self,
        session_id: str,
        data_client: Any,
        iteration_ref: Optional[list[int]] = None,
    ) -> None:
        """Initialise the logging callback.

        Args:
            session_id: The current agent session ID.
            data_client: Data client with log_execution_event() method.
            iteration_ref: Optional mutable list[int] where [0] is the
                current iteration counter. Passed by reference so the
                callback always sees the live iteration number.
        """
        super().__init__()
        self.session_id = session_id
        self.data_client = data_client
        self.iteration_ref: list[int] = iteration_ref if iteration_ref is not None else [0]
        self._llm_start_time: float = 0.0
        self._tool_start_times: dict[str, float] = {}

    @property
    def raise_error(self) -> bool:
        return False  # Logging failures should not stop execution

    # ── LangChain callback hooks ──────────────────────────────────────────────

    async def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        **kwargs: Any,
    ) -> None:
        """Emit llm_request event when an LLM call begins."""
        self._llm_start_time = time.monotonic()
        await self._safe_log(
            event_type="llm_request",
            message=f"[iter={self._current_iter()}] LLM call started",
            data={
                "model": serialized.get("kwargs", {}).get("model_name", "unknown"),
                "iteration": self._current_iter(),
                "prompt_count": len(prompts),
            },
        )

    async def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        """Emit llm_request event when a chat model call begins."""
        self._llm_start_time = time.monotonic()
        self.iteration_ref[0] += 1  # Each model call = one iteration
        model_name = (
            serialized.get("kwargs", {}).get("model_name")
            or serialized.get("name", "unknown")
        )
        msg_count = sum(len(batch) for batch in messages)
        await self._safe_log(
            event_type="llm_request",
            message=f"[iter={self._current_iter()}] Chat model call: {model_name}",
            data={
                "model": model_name,
                "iteration": self._current_iter(),
                "message_count": msg_count,
            },
        )

    async def on_llm_end(
        self,
        response: LLMResult,
        **kwargs: Any,
    ) -> None:
        """Emit llm_response event when an LLM call completes, with token usage."""
        elapsed = time.monotonic() - self._llm_start_time if self._llm_start_time else 0.0
        usage: dict[str, Any] = {}
        if response.llm_output:
            raw_usage = response.llm_output.get("token_usage") or {}
            if raw_usage:
                usage = {
                    "prompt_tokens": raw_usage.get("prompt_tokens", 0),
                    "completion_tokens": raw_usage.get("completion_tokens", 0),
                    "total_tokens": raw_usage.get("total_tokens", 0),
                }

        # Also check usage_metadata on the generation
        if not usage and response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    if hasattr(gen, "message") and hasattr(gen.message, "usage_metadata"):
                        meta = gen.message.usage_metadata
                        if meta:
                            usage = {
                                "prompt_tokens": meta.get("input_tokens", 0),
                                "completion_tokens": meta.get("output_tokens", 0),
                                "total_tokens": meta.get("total_tokens", 0),
                            }
                            break

        await self._safe_log(
            event_type="llm_response",
            message=(
                f"[iter={self._current_iter()}] LLM response received "
                f"({elapsed:.2f}s)"
                + (f" — {usage.get('total_tokens', 0)} tokens" if usage else "")
            ),
            data={
                "iteration": self._current_iter(),
                "elapsed_seconds": round(elapsed, 3),
                "usage": usage,
            },
        )

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Emit tool_call event when a tool is about to be executed."""
        tool_name = serialized.get("name", "unknown_tool")
        run_id = str(kwargs.get("run_id", ""))
        self._tool_start_times[run_id] = time.monotonic()

        # Truncate large inputs in logs
        logged_input = input_str[:500] if len(input_str) > 500 else input_str

        await self._safe_log(
            event_type="tool_call",
            message=f"[iter={self._current_iter()}] Tool call: {tool_name}",
            data={
                "tool": tool_name,
                "input": logged_input,
                "iteration": self._current_iter(),
                "run_id": run_id,
            },
        )

    async def on_tool_end(
        self,
        output: Any,
        **kwargs: Any,
    ) -> None:
        """Emit tool_response event when a tool call completes."""
        run_id = str(kwargs.get("run_id", ""))
        elapsed = 0.0
        if run_id in self._tool_start_times:
            elapsed = time.monotonic() - self._tool_start_times.pop(run_id)

        # LangChain may pass a ToolMessage object or a plain string
        output_str = output.content if hasattr(output, "content") else str(output)
        logged_output = output_str[:500] if len(output_str) > 500 else output_str

        await self._safe_log(
            event_type="tool_response",
            message=f"[iter={self._current_iter()}] Tool response ({elapsed:.2f}s)",
            data={
                "output": logged_output,
                "elapsed_seconds": round(elapsed, 3),
                "iteration": self._current_iter(),
            },
        )

    async def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        **kwargs: Any,
    ) -> None:
        """Emit tool_error event when a tool call fails."""
        await self._safe_log(
            event_type="tool_error",
            message=f"[iter={self._current_iter()}] Tool error: {error}",
            data={
                "error": str(error),
                "iteration": self._current_iter(),
            },
        )

    async def on_llm_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        **kwargs: Any,
    ) -> None:
        """Emit llm_error event when an LLM call fails."""
        await self._safe_log(
            event_type="llm_error",
            message=f"[iter={self._current_iter()}] LLM error: {error}",
            data={
                "error": str(error),
                "iteration": self._current_iter(),
            },
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _current_iter(self) -> int:
        """Return the current iteration number from the mutable ref."""
        return self.iteration_ref[0] if self.iteration_ref else 0

    async def _safe_log(
        self,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Log an execution event, swallowing any logging failures."""
        if self.data_client is None:
            return
        try:
            await self.data_client.log_execution_event(
                session_id=self.session_id,
                event_type=event_type,
                message=message,
                data=data or {},
            )
        except Exception as exc:
            logger.debug(
                "ExecutionLoggingCallback: failed to log %s event for session %s: %s",
                event_type,
                self.session_id,
                exc,
            )
