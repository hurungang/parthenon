"""
Failing tests that reproduce Issue 1: Tool Sync 404 — Wrong Endpoint.

Root cause:
  tool_sync.py calls  GET {base_url}/tools
  MCP protocol requires  POST {base_url}/mcp  (or /mcp/stream)
                          body: {"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}

Expected fix:
  Replace the simple GET /tools call with a JSON-RPC 2.0 POST to /mcp.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.mcp.tool_sync import ToolSyncService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_server(base_url: str = "https://mcp.supabase.com"):
    server = MagicMock()
    server.id = uuid4()
    server.slug = "supabase-mcp"
    server.base_url = base_url
    server.status = None
    server.last_synced_at = None
    return server


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None, scalars=lambda: MagicMock(all=lambda: [])))
    db.add = MagicMock()
    return db


def _http_response(status_code: int, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or (json.dumps(json_data) if json_data is not None else "")
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("no JSON"))
    resp.raise_for_status = MagicMock(
        side_effect=Exception(f"HTTP {status_code}") if status_code >= 400 else None
    )
    return resp


def _make_client(get_response=None, post_response=None):
    # Default GET to 404 — simulates what real MCP servers return for GET /tools
    if get_response is None:
        get_response = _http_response(404, text="Not Found")
    client = AsyncMock()
    client.get = AsyncMock(return_value=get_response)
    client.post = AsyncMock(return_value=post_response)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


# ── Issue-reproducing tests (these FAIL with current implementation) ──────────

@pytest.mark.asyncio
async def test_sync_does_NOT_call_GET_slash_tools():
    """
    FAILING TEST — Reproduces Issue 1.

    Current code calls:  GET https://mcp.supabase.com/tools  → 404
    Correct protocol:    POST https://mcp.supabase.com/mcp
                         body: {"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}

    This test verifies that the sync implementation does NOT issue a bare GET /tools
    request, which the MCP protocol spec does not define.
    """
    server = _mock_server("https://mcp.supabase.com")
    db = _mock_db()

    # Simulate what the real server returns: 404 for GET /tools
    not_found_response = _http_response(404, text="Not Found")

    mock_http_client = _make_client(get_response=not_found_response)

    with patch("httpx.AsyncClient", return_value=mock_http_client):
        service = ToolSyncService()
        # After fix: POST /mcp is called but post_response is None → AttributeError,
        # which propagates as a generic Exception, confirming the old GET /tools is gone.
        with pytest.raises(Exception):
            await service.sync(server, db)

    # Assert: the implementation called GET (wrong) instead of POST (correct MCP protocol)
    http_client_instance = await mock_http_client.__aenter__()
    called_get = http_client_instance.get.called
    called_post = http_client_instance.post.called

    # After fix: implementation must use POST /mcp, NOT GET /tools
    assert not called_get, (
        "sync() must NOT issue a bare GET /tools request after the JSON-RPC fix."
    )
    assert called_post, (
        "sync() must POST to the MCP JSON-RPC endpoint instead of GET /tools."
    )


@pytest.mark.asyncio
async def test_sync_calls_correct_jsonrpc_endpoint():
    """
    FAILING TEST — Defines the correct behaviour after the fix.

    After the fix, sync() must:
    1. POST to {base_url}/mcp  (Streamable HTTP MCP endpoint)
    2. Send JSON-RPC 2.0 payload with method "tools/list"
    3. Parse result from data["result"]["tools"]
    """
    server = _mock_server("https://mcp.supabase.com")
    db = _mock_db()

    # Correct MCP JSON-RPC 2.0 response
    jsonrpc_response = _http_response(
        200,
        json_data={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "list_tables", "description": "List all tables", "inputSchema": {"type": "object"}},
                    {"name": "execute_sql", "description": "Run SQL query", "inputSchema": {"type": "object"}},
                ]
            },
        },
    )

    mock_http_client = _make_client(post_response=jsonrpc_response)

    with patch("httpx.AsyncClient", return_value=mock_http_client):
        service = ToolSyncService()
        # This will FAIL with current implementation because it does GET not POST
        result = await service.sync(server, db)

    http_client_instance = await mock_http_client.__aenter__()

    # Verify POST was called (not GET)
    assert http_client_instance.post.called, (
        "sync() must POST to the MCP JSON-RPC endpoint, not GET /tools"
    )
    assert not http_client_instance.get.called, (
        "sync() must NOT issue a bare GET /tools request"
    )

    # Verify the request goes to /mcp endpoint
    post_call_args = http_client_instance.post.call_args
    called_url = post_call_args[0][0] if post_call_args[0] else post_call_args.kwargs.get("url", "")
    assert "/mcp" in called_url, (
        f"Expected POST to .../mcp but got: {called_url}"
    )

    # Verify JSON-RPC payload
    posted_json = post_call_args.kwargs.get("json") or (post_call_args[1].get("json") if len(post_call_args) > 1 else None)
    assert posted_json is not None, "POST must include a JSON body"
    assert posted_json.get("jsonrpc") == "2.0", "Must use JSON-RPC 2.0"
    assert posted_json.get("method") == "tools/list", "Must call tools/list method"

    # Verify tool count returned
    assert result["added"] == 2, f"Expected 2 tools added, got: {result}"


@pytest.mark.asyncio
async def test_sync_handles_jsonrpc_error_response():
    """
    FAILING TEST — After fix, sync() must handle JSON-RPC error objects gracefully.
    """
    server = _mock_server("https://mcp.supabase.com")
    db = _mock_db()

    error_response = _http_response(
        200,
        json_data={
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        },
    )

    mock_http_client = _make_client(post_response=error_response)

    with patch("httpx.AsyncClient", return_value=mock_http_client):
        service = ToolSyncService()
        # After fix: should raise RuntimeError with the JSON-RPC error message
        with pytest.raises(RuntimeError, match="tools/list"):
            await service.sync(server, db)
