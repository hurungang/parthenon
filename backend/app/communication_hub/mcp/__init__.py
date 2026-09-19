"""Communication Hub MCP protocol server package.

Exposes the Communication Hub's permitted tools to external MCP clients
(GitHub Copilot, Claude Desktop, Cursor, custom agents) over the standard
Model Context Protocol (``initialize`` / ``tools/list`` / ``tools/call``).

Architecture notes (see ``docs/changes/add-mcp-protocol-server/architecture.md``):

- The Communication Hub has **no direct database access**. All data is fetched
  from Control Center over mTLS.
- Authentication is performed by the existing ``ApiKeyAuthMiddleware``, which
  validates the client's API key against Control Center and attaches the
  resolved identity token, agent role, and permission set to ``request.state``.
- The resolved identity token is held exclusively on the CH/CC boundary and is
  never serialized into any client-visible response or session object.
"""

from app.communication_hub.mcp.protocol_server import McpProtocolServer
from app.communication_hub.mcp.session_manager import McpSession, McpSessionManager
from app.communication_hub.mcp.tool_registry_bridge import ToolRegistryBridge

__all__ = [
    "McpProtocolServer",
    "McpSession",
    "McpSessionManager",
    "ToolRegistryBridge",
]
