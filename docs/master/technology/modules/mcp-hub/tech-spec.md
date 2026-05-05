# Module: mcp-hub — Tech Spec

## Overview

The MCP Hub module is the canonical integration boundary between the Parthenon platform and all external MCP (Model Context Protocol) tool servers. It handles registration and configuration of MCP servers, periodic synchronisation of each server's tool catalogue into the platform database under a unique server slug namespace, management of named sessions with encrypted credential storage and per-session identity binding and credential configuration, permission granting at the tool level, proxying of tool-call invocations from agents to the correct external server with automatic credential injection, and a cross-server Tool Repository view with skill association mapping.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `McpServerRouter` | FastAPI router for full CRUD operations on registered MCP servers and the manual tool sync trigger endpoint |
| `McpSessionRouter` | FastAPI router for creating, updating, and deleting named sessions on an MCP server; handles encrypted credential storage via the Credential Vault; persists and returns `identity_binding` and `credential_config` per session |
| `McpToolRouter` | FastAPI router for per-server tool listing and role-based permission grants; also exposes global all-tools listing (`GET /mcp/tools`) and tool-to-skill reverse mapping (`GET /mcp/tools/{id}/skills`) |
| `ToolSyncService` | Service class that connects to a registered MCP server's HTTP endpoint, retrieves its tool manifest, and upserts tool records into the database namespaced under the server's unique slug |
| `McpProxyEngine` | Service class that resolves a tool-call invocation to the correct server session, decrypts and injects the scoped credentials at call time, dispatches the call to the external MCP server, and returns the structured result |
| `McpServer` | SQLAlchemy model for a registered external MCP tool server; holds the server URL, slug, and connection configuration |
| `McpSession` | SQLAlchemy model for a named session on an MCP server; stores the encrypted credential blob, `identity_binding` (JSON), and `credential_config` (JSON); maps the session to an agent identity or role |
| `McpTool` | SQLAlchemy model for a synced tool; namespaced under the owning server's slug; includes the tool schema and metadata from the last sync |
| `ToolPermission` | SQLAlchemy model granting a specific Role access to a specific MCP tool; the permission-grantable unit for agents |

### Frontend

| Component | Description |
|-----------|-------------|
| `useMcpServers` | React Query hook that fetches and caches the MCP server list |
| `useServerSessions` | React Query hook that fetches sessions for a specific MCP server; returns updated `McpSession` type including `identity_binding` and `credential_config` |
| `useAllTools` | React Query hook that fetches all active MCP tools across all servers (`GET /mcp/tools`); cache key `['mcp', 'tools']` |
| `useToolSkills` | React Query hook that fetches skills bound to a specific tool (`GET /mcp/tools/{toolId}/skills`); cache key `['mcp', 'tools', toolId, 'skills']` |
| `McpHubPage` | Tabbed MCP Hub page: Servers tab (server list with status indicators) and Tool Repository tab; hosts per-server Sessions dialog |
| `McpServerForm` | Create and edit form for MCP server registration including URL, slug, and connection settings |
| `McpSessionManager` | Named session CRUD UI; fields include auth type, write-only credentials, `identity_binding`, and `credential_config`; follows Dialog Error Handling Standard |
| `McpToolBrowser` | Tool Repository view: all active tools across all servers grouped by server, with assigned skill chips, search filter, server filter, and active toggle |

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
| `GET` | `/api/v1/mcp/servers/{server_id}/sessions` | List sessions for a server; includes `identity_binding`, `credential_config` |
| `POST` | `/api/v1/mcp/servers/{server_id}/sessions` | Create a named session; accepts `identity_binding`, `credential_config` |
| `PUT` | `/api/v1/mcp/servers/{server_id}/sessions/{session_id}` | Update a session; accepts `identity_binding`, `credential_config` |
| `DELETE` | `/api/v1/mcp/servers/{server_id}/sessions/{session_id}` | Delete a session |
| `GET` | `/api/v1/mcp/tools` | List all active tools across all servers, ordered by server name then tool name |
| `GET` | `/api/v1/mcp/tools/{tool_id}/skills` | List all skills bound to a specific tool via `skill_tool_bindings` |
| `GET` | `/api/v1/mcp/tools/{tool_id}/permissions` | List permissions for a tool |
| `POST` | `/api/v1/mcp/tools/{tool_id}/permissions` | Grant tool access to a role |
| `DELETE` | `/api/v1/mcp/tools/{tool_id}/permissions/{permission_id}` | Revoke tool access |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpServerRouter` | router | CRUD and sync endpoints for MCP servers; all operations guarded by `require_permission(RT_MCP_SERVER, action)` | `backend/app/api/v1/mcp_hub.py` |
| `McpSessionRouter` | router | Session CRUD under `/mcp/servers/{id}/sessions`; persists and returns `identity_binding`, `credential_config`; encrypts credentials via Credential Vault | `backend/app/api/v1/mcp_hub.py` |
| `McpToolRouter` | router | Per-server tool listing and permission grant/revoke; global all-tools listing and tool-to-skill reverse mapping | `backend/app/api/v1/mcp_hub.py` |
| `list_all_tools` | endpoint function | Returns all active `McpTool` records across all servers, ordered by server name then tool name | `backend/app/api/v1/mcp_hub.py` |
| `list_tool_skills` | endpoint function | Returns all `Skill` records bound to a given tool via `skill_tool_bindings` | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_session` | endpoint function | Creates a session; encrypts credentials; stores `identity_binding`, `credential_config` | `backend/app/api/v1/mcp_hub.py` |
| `update_mcp_session` | endpoint function | Updates a session; re-encrypts credentials if provided; stores updated `identity_binding`, `credential_config` | `backend/app/api/v1/mcp_hub.py` |
| `McpSessionCreate` | Pydantic schema | Session creation payload; includes `identity_binding`, `credential_config` fields | `backend/app/schemas/mcp_hub.py` |
| `McpSessionUpdate` | Pydantic schema | Session partial update payload; includes `identity_binding`, `credential_config` fields | `backend/app/schemas/mcp_hub.py` |
| `McpSessionRead` | Pydantic schema | Session response schema; exposes `identity_binding`, `credential_config`; never exposes `encrypted_credentials` | `backend/app/schemas/mcp_hub.py` |
| `ToolSyncService` | class | Fetches tool manifest from a registered MCP server and upserts tools under the server slug namespace | `backend/app/services/mcp/tool_sync.py` |
| `McpProxyEngine` | class | Routes tool-call invocations to the correct server session with credential injection | `backend/app/services/mcp/proxy.py` |
| `McpServer` | model | SQLAlchemy model for a registered external MCP tool server | `backend/app/db/models/mcp_hub.py` |
| `McpSession` | model | SQLAlchemy model for a named MCP session; stores encrypted credentials, `identity_binding` (JSON), and `credential_config` (JSON) | `backend/app/db/models/mcp_hub.py` |
| `McpTool` | model | SQLAlchemy model for a synced tool namespaced under a server slug | `backend/app/db/models/mcp_hub.py` |
| `ToolPermission` | model | SQLAlchemy model granting a role access to a specific tool | `backend/app/db/models/mcp_hub.py` |
| `useMcpServers` | hook | React Query hook for fetching and caching the MCP server list | `frontend/src/hooks/useMcpServers.ts` |
| `useServerSessions` | hook | React Query hook for fetching sessions for a specific MCP server; returns updated `McpSession` type with `identity_binding`, `credential_config` | `frontend/src/hooks/useMcpServers.ts` |
| `useAllTools` | hook | React Query hook fetching all active tools across all servers; cache key `['mcp', 'tools']` | `frontend/src/hooks/useMcpServers.ts` |
| `useToolSkills` | hook | React Query hook fetching skills bound to a specific tool; cache key `['mcp', 'tools', toolId, 'skills']` | `frontend/src/hooks/useMcpServers.ts` |
| `McpHubPage` | component | Tabbed MCP Hub: Servers tab + Tool Repository tab; hosts per-server Sessions dialog | `frontend/src/pages/mcp/McpHubPage.tsx` |
| `McpServerForm` | component | Create/edit form for MCP server registration | `frontend/src/pages/mcp/McpServerForm.tsx` |
| `McpSessionManager` | component | Session CRUD UI with auth type, write-only credentials, `identity_binding`, `credential_config`; follows Dialog Error Handling Standard | `frontend/src/pages/mcp/McpSessionManager.tsx` |
| `McpToolBrowser` | component | Tool Repository: all tools grouped by server with skill chips, search filter, server filter, active toggle | `frontend/src/pages/mcp/McpToolBrowser.tsx` |
