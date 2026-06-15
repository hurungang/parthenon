from __future__ import annotations

from typing import Any, Callable


def hello_world_tool(agent_identity: dict[str, Any]) -> dict[str, Any]:
    """Return a greeting that surfaces the caller's agent identity."""
    return {
        "message": "Hello from MCP Demo App!",
        "agent_sub": agent_identity.get("sub"),
        "agent_claims": agent_identity,
    }


def hello_agent_tool(agent_identity: dict[str, Any]) -> dict[str, Any]:
    """Greets the calling agent identity. Requires mcp_role 'demo_agent'."""
    mcp_role = agent_identity.get("mcp_role")
    if mcp_role != "demo_agent":
        return {"access_denied": True, "reason": "Agent identity lacks required mcp_role: demo_agent"}
    return {
        "message": "Hello Agent!",
        "agent_sub": agent_identity.get("sub"),
        "agent_realm": agent_identity.get("iss"),
        "agent_mcp_role": agent_identity.get("mcp_role"),
        "agent_claims": agent_identity,
    }


def hello_user_tool(user_identity: dict[str, Any]) -> dict[str, Any]:
    """Greets the calling user identity. Requires mcp_role 'demo_user'."""
    mcp_role = user_identity.get("mcp_role")
    if mcp_role != "demo_user":
        return {"access_denied": True, "reason": "User identity lacks required mcp_role: demo_user"}
    return {
        "message": "Hello User!",
        "user_sub": user_identity.get("sub"),
        "user_realm": user_identity.get("iss"),
        "user_mcp_role": user_identity.get("mcp_role"),
        "user_claims": user_identity,
    }


tool_registry: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "helloWorld": hello_world_tool,
    "helloAgent": hello_agent_tool,
    "helloUser": hello_user_tool,
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
    },
    {
        "name": "helloAgent",
        "description": (
            "Greets the calling agent identity. "
            "Requires the agent to have mcp_role 'demo_agent'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "helloUser",
        "description": (
            "Greets the calling user identity. "
            "Requires the user to have mcp_role 'demo_user'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
