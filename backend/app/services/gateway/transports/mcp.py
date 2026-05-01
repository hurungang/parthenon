"""MCP Gateway Transport — exposes lifecycle operations as MCP tools."""

import logging
from typing import Any

from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler

logger = logging.getLogger(__name__)


class McpGatewayTransport:
    """
    Exposes the four gateway lifecycle operations as MCP tools:
    agent_init, agent_request, agent_answer, agent_close.

    These tools are registered in the MCP Hub so external systems
    can interact with agents via the MCP protocol.
    """

    MCP_TOOLS = [
        {
            "name": "agent_init",
            "description": "Initialize a new agent instance for the given agent type.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent_type_id": {"type": "string", "description": "UUID of the agent type"},
                    "initiator_subject": {
                        "type": "string",
                        "description": "Optional initiator identifier",
                    },
                },
                "required": ["agent_type_id"],
            },
        },
        {
            "name": "agent_request",
            "description": "Send a user prompt to an active agent instance.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_handle": {"type": "string", "description": "Session handle from init"},
                    "prompt": {"type": "string", "description": "User prompt"},
                    "context": {"type": "object", "description": "Optional context dict"},
                },
                "required": ["session_handle", "prompt"],
            },
        },
        {
            "name": "agent_answer",
            "description": "Provide an answer to a pending agent question.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_handle": {"type": "string"},
                    "answer": {"type": "string", "description": "Answer to the agent's question"},
                },
                "required": ["session_handle", "answer"],
            },
        },
        {
            "name": "agent_close",
            "description": "Close an agent instance and end the session.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_handle": {"type": "string"},
                },
                "required": ["session_handle"],
            },
        },
    ]

    def __init__(self) -> None:
        self._handler = GatewayLifecycleHandler()

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return the MCP tool definitions for gateway lifecycle operations."""
        return self.MCP_TOOLS

    async def dispatch(self, tool_name: str, arguments: dict[str, Any], db: Any) -> dict[str, Any]:
        """Dispatch an MCP tool call to the appropriate lifecycle handler method."""
        if tool_name == "agent_init":
            return await self._handler.init(
                agent_type_id=arguments["agent_type_id"],
                initiator_subject=arguments.get("initiator_subject"),
                db=db,
            )
        elif tool_name == "agent_request":
            return await self._handler.request(
                session_handle=arguments["session_handle"],
                prompt=arguments["prompt"],
                context=arguments.get("context"),
                db=db,
            )
        elif tool_name == "agent_answer":
            return await self._handler.answer(
                session_handle=arguments["session_handle"],
                answer_text=arguments["answer"],
            )
        elif tool_name == "agent_close":
            return await self._handler.close(
                session_handle=arguments["session_handle"],
                db=db,
            )
        else:
            raise ValueError(f"Unknown gateway tool: {tool_name}")
