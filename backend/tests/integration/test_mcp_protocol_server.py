"""Integration test for the MCP protocol server.

Exercises the full ``initialize`` → ``tools/list`` → ``tools/call`` flow through
the real ``McpProtocolServer`` + ``McpSessionManager`` + ``ToolRegistryBridge``,
with only the Control Center transport (``_post_cc``) stubbed — no database and
no running Control Center required.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.communication_hub.mcp.protocol_server import McpProtocolServer
from app.communication_hub.mcp.session_manager import McpSessionManager
from app.communication_hub.mcp.tool_registry_bridge import ToolRegistryBridge


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> ToolRegistryBridge:
    monkeypatch.setenv("CONTROL_CENTER_URL", "http://control-center")
    bridge = ToolRegistryBridge()

    async def _post_cc(
        request: Any, cc_base: str, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if path.endswith("/system-tools/skills/resolve"):
            return {
                "skills": [
                    {
                        "name": "github-skill",
                        "tools": [
                            {
                                "name": "github____list_prs",
                                "description": "List pull requests",
                                "input_schema": {"type": "object", "properties": {}},
                            }
                        ],
                    }
                ]
            }
        if path.endswith("/system-tools/save-data"):
            return {"result": {"saved": True}}
        if path.endswith("/internal/mcp/proxy-tool"):
            return {"result": {"prs": [{"number": 42}]}}
        return {"result": {}}

    monkeypatch.setattr(bridge, "_post_cc", _post_cc)
    return bridge


async def test_full_initialize_list_call_flow(bridge: ToolRegistryBridge) -> None:
    manager = McpSessionManager()
    server = McpProtocolServer()
    server._bridge = bridge

    # 1. initialize — no session required.
    init = await server.handle(
        None, {"id": 1, "method": "initialize", "params": {}}, None
    )
    assert init["result"]["protocolVersion"] == "2024-11-05"
    assert init["result"]["capabilities"] == {"tools": {}}
    assert init["result"]["serverInfo"]["name"] == "parthenon-communication-hub"

    # 2. establish an authenticated session.
    session = manager.create_session(
        agent_role_id="role-1",
        agent_identity_id="identity-1",
        permissions=["system____save_data", "github____list_prs"],
        skills=[
            {
                "name": "github-skill",
                "tools": [
                    {
                        "name": "github____list_prs",
                        "description": "List pull requests",
                        "input_schema": {"type": "object", "properties": {}},
                    }
                ],
            }
        ],
    )

    # 3. tools/list — permission-filtered catalog.
    listed = await server.handle(
        None, {"id": 2, "method": "tools/list"}, session
    )
    names = [t["name"] for t in listed["result"]["tools"]]
    assert "load_skills" in names
    assert "system____save_data" in names
    assert "github____list_prs" in names

    # 4. tools/call load_skills — result wrapped in MCP text content.
    load_skills = await server.handle(
        None,
        {"id": 3, "method": "tools/call", "params": {"name": "load_skills", "arguments": {}}},
        session,
    )
    assert load_skills["result"]["content"][0]["type"] == "text"
    assert "github-skill" in load_skills["result"]["content"][0]["text"]

    # 5. tools/call system tool.
    system_call = await server.handle(
        None,
        {
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "system____save_data",
                "arguments": {"data_name": "x", "data_value": {}},
            },
        },
        session,
    )
    assert system_call["result"]["content"][0]["type"] == "text"

    # 6. tools/call proxied MCP tool.
    proxy_call = await server.handle(
        None,
        {
            "id": 5,
            "method": "tools/call",
            "params": {"name": "github____list_prs", "arguments": {"state": "open"}},
        },
        session,
    )
    assert proxy_call["result"]["content"][0]["type"] == "text"
    assert "42" in proxy_call["result"]["content"][0]["text"]

    # 7. unauthorized call rejected.
    denied = await server.handle(
        None,
        {
            "id": 6,
            "method": "tools/call",
            "params": {"name": "system____get_data", "arguments": {}},
        },
        session,
    )
    assert denied["error"]["code"] == -32602
