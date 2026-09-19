"""MCP protocol server — bridges JSON-RPC methods to the tool registry bridge.

Implements the standard MCP JSON-RPC surface:

- ``initialize``            → capability negotiation (no auth required).
- ``notifications/initialized`` → client ack (no response).
- ``tools/list``            → permission-filtered tool catalog.
- ``tools/call``            → authorized tool dispatch.

The JSON-RPC request/response shapes follow the Model Context Protocol
specification (protocol version ``2024-11-05``). The official ``mcp`` Python SDK
is the intended long-term implementation; this module is intentionally a thin,
dependency-optional bridge so the Communication Hub remains importable even
before the SDK is installed (see ``backend/pyproject.toml``).
"""
from __future__ import annotations

import logging
from typing import Any

from app.communication_hub.mcp.session_manager import MCP_PROTOCOL_VERSION
from app.communication_hub.mcp.tool_registry_bridge import ToolRegistryBridge

logger = logging.getLogger(__name__)

JSONRPC = "2.0"

#: JSON-RPC error codes used by the MCP protocol.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

SERVER_INFO = {"name": "parthenon-communication-hub", "version": "0.1.0"}


class McpProtocolServer:
    """Stateless JSON-RPC → tool-registry bridge.

    Sessions carry the authenticated identity/role/permissions context; this
    class only interprets JSON-RPC methods and delegates tool work to
    :class:`ToolRegistryBridge`.
    """

    def __init__(self) -> None:
        self._bridge = ToolRegistryBridge()

    async def handle(
        self, request: Any, message: dict[str, Any], session: Any
    ) -> dict[str, Any] | None:
        """Handle a single JSON-RPC message, returning a response dict (or None for notifications).

        ``session`` may be ``None`` for ``initialize`` (the only method allowed
        before a session is established). All other methods require an
        authenticated session. ``request`` is the FastAPI request, used to reach
        Control Center over mTLS during tool dispatch.
        """
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        # Notifications (no ``id``) get no response.
        if method == "notifications/initialized":
            return None

        try:
            if method == "initialize":
                if session is not None:
                    session.initialized = True
                    session.protocol_version = (
                        params.get("protocolVersion") or session.protocol_version
                    )
                return self._ok(request_id, self._handle_initialize(params))
            if method == "ping":
                return self._ok(request_id, {})
            if session is None:
                return self._error(request_id, INVALID_REQUEST, "Session not initialized")
            if method == "tools/list":
                return self._ok(request_id, {"tools": self._bridge.build_catalog(session)})
            if method == "tools/call":
                return await self._handle_tools_call(request, request_id, session, params)
            return self._error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        except PermissionError as exc:
            return self._error(request_id, INVALID_PARAMS, str(exc))
        except Exception as exc:  # noqa: BLE001 — always return a JSON-RPC error
            logger.exception("MCP method %s failed", method)
            return self._error(request_id, INTERNAL_ERROR, str(exc))

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        # Store negotiated client details on the session at the transport layer;
        # here we only advertise server capabilities.
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }

    async def _handle_tools_call(
        self, request: Any, request_id: Any, session: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not tool_name:
            return self._error(request_id, INVALID_PARAMS, "Missing tool name")
        if not isinstance(arguments, dict):
            arguments = {}

        logger.info(
            "MCP tool call: tool=%s session=%s key=%s",
            tool_name,
            session.session_id,
            session.api_key_name,
        )
        result = await self._bridge.dispatch(request, session, tool_name, arguments)
        return self._ok(request_id, result)

    @staticmethod
    def _ok(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": JSONRPC, "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": JSONRPC, "id": request_id, "error": {"code": code, "message": message}}
