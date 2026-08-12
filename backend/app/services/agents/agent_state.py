"""LangGraph state schemas for task-based and conversational agent graphs."""
from __future__ import annotations

import uuid
from typing import Any, Annotated

try:
    from langgraph.graph import MessagesState
    from langchain_core.messages import BaseMessage
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False


if _LANGGRAPH_AVAILABLE:
    from typing import TypedDict

    class TaskAgentState(TypedDict):
        """State schema for task-based (non-conversational) agent graph execution."""

        session_id: str
        agent_type_id: str
        role_id: str | None
        allowed_tools: list[str]
        input_data: dict[str, Any] | None
        system_instruction: str | None
        output_type: str  # "auto" | "typed" | "markdown"
        output_schema: dict[str, Any] | None
        # Accumulate tool results through graph nodes
        tool_results: list[dict[str, Any]]
        # Final output placed here by the last graph node
        output_data: dict[str, Any] | None
        error_message: str | None
        # LangGraph messages accumulator (used internally by LLM nodes)
        messages: Annotated[list[Any], lambda a, b: a + b]

    class ConversationalAgentState(TypedDict):
        """State schema for conversational (chat) agent graph execution."""

        session_id: str
        agent_type_id: str
        role_id: str | None
        allowed_tools: list[str]
        system_instruction: str | None
        output_type: str
        # Full message history (both user and assistant turns)
        messages: Annotated[list[Any], lambda a, b: a + b]
        # Signals that the session has ended (user closed or agent finished)
        is_complete: bool
        error_message: str | None

else:
    # Fallback plain TypedDicts when LangGraph is not installed
    from typing import TypedDict

    class TaskAgentState(TypedDict):  # type: ignore[no-redef]
        session_id: str
        agent_type_id: str
        role_id: str | None
        allowed_tools: list[str]
        input_data: dict[str, Any] | None
        system_instruction: str | None
        output_type: str
        output_schema: dict[str, Any] | None
        tool_results: list[dict[str, Any]]
        output_data: dict[str, Any] | None
        error_message: str | None
        messages: list[Any]

    class ConversationalAgentState(TypedDict):  # type: ignore[no-redef]
        session_id: str
        agent_type_id: str
        role_id: str | None
        allowed_tools: list[str]
        system_instruction: str | None
        output_type: str
        messages: list[Any]
        is_complete: bool
        error_message: str | None
