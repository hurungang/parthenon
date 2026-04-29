# Module: mcp-hub — Tech Spec

## Overview

The MCP Hub module is the canonical integration boundary between the Parthenon platform and all external MCP (Model Context Protocol) tool servers. It handles registration and configuration of MCP servers, periodic synchronisation of each server's tool catalogue into the platform database under a unique server slug namespace, management of named sessions with encrypted credential storage, permission granting at the tool level, and proxying of tool-call invocations from agents to the correct external server with automatic credential injection.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `McpServerRouter` | FastAPI router for full CRUD operations on registered MCP servers and the manual tool sync trigger endpoint |
| `McpSessionRouter` | FastAPI router for creating, updating, and deleting named sessions on an MCP server; handles encrypted credential field storage via the Credential Vault |
| `McpToolRouter` | FastAPI router for listing synced tools for a server and managing role-based permission grants on individual tools |
| `ToolSyncService` | Service class that connects to a registered MCP server's HTTP endpoint, retrieves its tool manifest, and upserts tool records into the database namespaced under the server's unique slug |
| `McpProxyEngine` | Service class that resolves a tool-call invocation to the correct server session, decrypts and injects the scoped credentials at call time, dispatches the call to the external MCP server, and returns the structured result |
| `McpServer` | SQLAlchemy model for a registered external MCP tool server; holds the server URL, slug, and connection configuration |
| `McpSession` | SQLAlchemy model for a named session on an MCP server; stores the encrypted credential blob and maps the session to an agent identity or role |
| `McpTool` | SQLAlchemy model for a synced tool; namespaced under the owning server's slug; includes the tool schema and metadata from the last sync |
| `ToolPermission` | SQLAlchemy model granting a specific Role access to a specific MCP tool; the permission-grantable unit for agents |

### Frontend

| Component | Description |
|-----------|-------------|
| `useMcpServers` | React Query hook that fetches and caches the MCP server list from the Platform API |
| `McpHubPage` | MCP server list page with online/offline status indicators and action toolbar for registration, sync, and deletion |
| `McpServerForm` | Create and edit form for MCP server registration including URL, slug, and connection settings |
| `McpSessionManager` | Named session CRUD interface with per-session credential field configuration per MCP server |
| `McpToolBrowser` | Synced tool browser with inline permission grant and revoke controls per role |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/mcp/servers` | List all registered MCP servers |
| `POST` | `/api/v1/mcp/servers` | Register a new MCP server |
| `GET` | `/api/v1/mcp/servers/{server_id}` | Get MCP server detail |
| `PUT` | `/api/v1/mcp/servers/{server_id}` | Update MCP server configuration |
| `DELETE` | `/api/v1/mcp/servers/{server_id}` | Delete an MCP server |
| `POST` | `/api/v1/mcp/servers/{server_id}/sync` | Trigger manual tool sync from the server |
| `GET` | `/api/v1/mcp/servers/{server_id}/tools` | List synced tools for a server |
| `GET` | `/api/v1/mcp/servers/{server_id}/sessions` | List sessions for a server |
| `POST` | `/api/v1/mcp/servers/{server_id}/sessions` | Create a named session |
| `PUT` | `/api/v1/mcp/servers/{server_id}/sessions/{session_id}` | Update a session |
| `DELETE` | `/api/v1/mcp/servers/{server_id}/sessions/{session_id}` | Delete a session |
| `GET` | `/api/v1/mcp/tools/{tool_id}/permissions` | List permissions for a tool |
| `POST` | `/api/v1/mcp/tools/{tool_id}/permissions` | Grant tool access to a role |
| `DELETE` | `/api/v1/mcp/tools/{tool_id}/permissions/{permission_id}` | Revoke tool access |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpServerRouter` | router | CRUD and sync endpoints for MCP servers | `backend/app/api/v1/mcp_hub.py` |
| `McpSessionRouter` | router | CRUD endpoints for MCP sessions with encrypted credential storage | `backend/app/api/v1/mcp_hub.py` |
| `McpToolRouter` | router | Tool listing and permission grant/revoke endpoints | `backend/app/api/v1/mcp_hub.py` |
| `ToolSyncService` | class | Fetches tool manifest from a registered MCP server and upserts under the server slug namespace | `backend/app/services/mcp/tool_sync.py` |
| `McpProxyEngine` | class | Routes tool-call invocations to the correct server session with credential injection | `backend/app/services/mcp/proxy.py` |
| `McpServer` | model | SQLAlchemy model for a registered external MCP tool server | `backend/app/db/models/mcp_hub.py` |
| `McpSession` | model | SQLAlchemy model for a named session on an MCP server with encrypted credentials | `backend/app/db/models/mcp_hub.py` |
| `McpTool` | model | SQLAlchemy model for a synced tool namespaced under a server slug | `backend/app/db/models/mcp_hub.py` |
| `ToolPermission` | model | SQLAlchemy model granting a role access to a specific tool | `backend/app/db/models/mcp_hub.py` |
| `useMcpServers` | hook | React Query hook for fetching and caching the MCP server list | `frontend/src/hooks/useMcpServers.ts` |
| `McpHubPage` | component | MCP server list with status indicators and action toolbar | `frontend/src/pages/mcp/McpHubPage.tsx` |
| `McpServerForm` | component | Create/edit form for MCP server registration | `frontend/src/pages/mcp/McpServerForm.tsx` |
| `McpSessionManager` | component | Named session CRUD with credential field configuration per MCP server | `frontend/src/pages/mcp/McpSessionManager.tsx` |
| `McpToolBrowser` | component | Synced tool list with inline permission grant/revoke per role | `frontend/src/pages/mcp/McpToolBrowser.tsx` |
