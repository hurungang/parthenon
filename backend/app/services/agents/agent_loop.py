"""LangChain deep agent loop definitions for task and conversational agents.

Replaces the previous LangGraph state-schema approach with plain Python dataclasses
that carry the observe-reason-act execution context through each loop iteration.

These classes are consumed by AgentRuntimeExecutor to track state without any
LangGraph dependency.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Maximum iterations before the executor stops to prevent infinite loops
DEFAULT_MAX_ITERATIONS: int = 10


@dataclass
class AgentLoopContext:
    """Base execution context shared by both task and conversational loops.

    Carried through each observe → reason → act iteration by AgentRuntimeExecutor.
    """

    session_id: str
    agent_type_id: str
    role_id: str | None
    allowed_tools: list[str]
    system_instruction: str | None
    output_type: str  # "auto" | "typed" | "markdown"
    output_schema: dict[str, Any] | None
    # Accumulated LLM message thread (role + content dicts)
    messages: list[dict[str, Any]] = field(default_factory=list)
    # Results returned by tool calls in the current session
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    # Tool definitions (OpenAI-format) available for the LLM in this session
    tool_definitions: list[dict[str, Any]] = field(default_factory=list)
    # Final structured output placed here by the last iteration
    output_data: dict[str, Any] | None = None
    error_message: str | None = None
    # True when the agent has signalled completion
    is_complete: bool = False
    iteration: int = 0
    max_iterations: int = DEFAULT_MAX_ITERATIONS

    @property
    def user_prompt(self) -> str | None:
        """Return the first user message from the message thread, if any."""
        for msg in self.messages:
            if msg.get("role") == "user":
                return str(msg.get("content", ""))
        return None

    def append_user_message(self, content: str) -> None:
        """Add a user-role message to the thread."""
        self.messages.append({"role": "user", "content": content})

    def append_assistant_message(self, content: str) -> None:
        """Add an assistant-role message to the thread."""
        self.messages.append({"role": "assistant", "content": content})

    def append_tool_result(self, tool_call_id: str, tool_name: str, result: Any) -> None:
        """Record a tool call result in both the thread and the tool_results list.
        
        Args:
            tool_call_id: The ID of the tool call this result corresponds to
            tool_name: Name of the tool that was called
            result: The result returned by the tool
        """
        result_dict = {"tool": tool_name, "result": result}
        self.tool_results.append(result_dict)
        self.messages.append({
            "role": "tool",
            "content": str(result),
            "tool_call_id": tool_call_id,
        })

    def should_continue(self) -> bool:
        """Return True if the loop should proceed to the next iteration."""
        return not self.is_complete and self.iteration < self.max_iterations


@dataclass
class TaskAgentLoop(AgentLoopContext):
    """Execution context for task-based (non-conversational) agent runs.

    The agent processes ``input_data`` once and produces ``output_data``.
    The loop terminates when the agent signals completion or max iterations are reached.
    """

    input_data: dict[str, Any] | None = None


@dataclass
class ConversationalAgentLoop(AgentLoopContext):
    """Execution context for conversational (multi-turn) agent sessions.

    Message history is maintained across turns.  The session stays open until
    the user or agent explicitly ends the conversation.
    """
    # No additional fields beyond AgentLoopContext — messages[] holds the full thread
