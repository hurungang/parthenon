from __future__ import annotations

from typing import Any, Callable


def hello_world_tool(agent_identity: dict[str, Any]) -> dict[str, Any]:
    """Return a greeting that surfaces the caller's agent identity."""
    return {
        "message": "Hello from MCP Demo App!",
        "agent_sub": agent_identity.get("sub"),
        "agent_claims": agent_identity,
    }


tool_registry: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "helloWorld": hello_world_tool,
}

TOOL_MANIFEST: list[dict[str, Any]] = [
    {
        "name": "helloWorld",
        "description": (
            "Returns a greeting message that includes the calling agent's "
            "identity (sub claim) from the forwarded JWT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }
]
