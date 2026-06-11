# Module: mcp-hub — Tech Spec

## Overview

The MCP Hub module is the canonical integration boundary between the Parthenon platform and all external MCP (Model Context Protocol) tool servers. It handles registration and configuration of MCP servers, periodic synchronisation of each server's tool catalogue into the platform database under a unique server slug namespace, management of named sessions with encrypted credential storage and per-session identity binding and credential configuration (including an explicit `is_default` flag for default session resolution), permission granting at the tool level, proxying of tool-call invocations from agents to the correct external server with automatic credential injection, and a cross-server Tool Repository view with skill association mapping.

A built-in **System** MCP server (reserved slug `system`) is seeded in the database at startup and surfaced as a virtual entry in the server list. The System server provides platform-native tools such as `save_result`. The server list deduplicates the DB-seeded System entry so that exactly one System entry appears.

Synchronisation (`POST /mcp/servers/{id}/sync`) is hardened: non-fatal initialise-handshake failures are captured as warnings (partial success returns 200 with warnings), session-gating returns 422 when a server has zero sessions, and complete failure returns 502 only when tools/list is unreachable. Default session resolution uses the explicit `is_default` flag (with sole-active-session auto-fallback) across sync, tool test, and proxy call paths.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `McpServerRouter` | FastAPI router for full CRUD operations on registered MCP servers (excluding the reserved `system` slug) and the manual tool sync trigger endpoint |
| `McpSessionRouter` | FastAPI router for creating, updating, and deleting named sessions on an MCP server; handles encrypted credential storage via the Credential Vault; persists and returns `identity_binding`, `credential_config`, and `is_default` |
| `McpToolRouter` | FastAPI router for per-server tool listing and role-based permission grants; also exposes global all-tools listing (`GET /mcp/tools`), tool-to-skill reverse mapping (`GET /mcp/tools/{id}/skills`), and tool test endpoint with default-session resolution |
| `ToolSyncService` | Service class that connects to a registered MCP server's HTTP endpoint, retrieves its tool manifest, and upserts tool records into the database namespaced under the server's unique slug; captures non-fatal initialise warnings for surfacing in API responses |
| `McpProxyEngine` | Service class that resolves a tool-call invocation to the correct server session (using `is_default` when no explicit `session_id` is provided), decrypts and injects the scoped credentials at call time (or forwards the caller's agent JWT for passthrough sessions), dispatches the call to the external MCP server, and returns the structured result |
| `OAuthRefreshService` | Service class that manages OAuth2 token refresh lifecycle for MCP sessions with `oauth2` auth type; checks token expiry and performs refresh callbacks |
| `McpServerRead` | Pydantic read schema for MCP server responses; includes `session_count: int` for sync-gating UI without N+1 session queries |
| `SyncResult` | Pydantic schema returned by the sync endpoint; includes `warnings: list[str]` to surface non-fatal initialise-handshake warnings alongside tool counts |
| `McpServer` | SQLAlchemy model for a registered external MCP tool server; holds the server URL, slug, and connection configuration; the reserved `system` slug server is seeded at startup |
| `McpSession` | SQLAlchemy model for a named session on an MCP server; stores the encrypted credential blob, `identity_binding` (JSON), `credential_config` (JSON), and `is_default` boolean flag for explicit default session resolution; maps the session to an agent identity or role |
| `McpTool` | SQLAlchemy model for a synced tool; namespaced under the owning server's slug; includes the tool schema and metadata from the last sync |
| `ToolPermission` | SQLAlchemy model granting a specific Role access to a specific MCP tool; the permission-grantable unit for agents |

### Frontend

| Component | Description |
|-----------|-------------|
| `useMcpServers` | React Query hook that fetches and caches the MCP server list |
| `useServerSessions` | React Query hook that fetches sessions for a specific MCP server; returns updated `McpSession` type including `identity_binding`, `credential_config`, and `is_default` |
| `useAllTools` | React Query hook that fetches all active MCP tools across all servers (`GET /mcp/tools`); cache key `['mcp', 'tools']` |
| `useToolSkills` | React Query hook that fetches skills bound to a specific tool (`GET /mcp/tools/{toolId}/skills`); cache key `['mcp', 'tools', toolId, 'skills']` |
| `useServerTools` | React Query hook that fetches tools for a specific server (`GET /mcp/servers/{id}/tools`) |
| `useSyncServer` | Mutation hook for triggering manual tool sync for a server (`POST /mcp/servers/{id}/sync`) |
| `McpHubPage` | Tabbed MCP Hub page: Servers tab (server list with status indicators) and Tool Repository tab; detects System entry with distinct "Built-in" chip and disabled actions; shows session count column; conditional sync button (disabled with tooltip when `session_count === 0`); hosts per-server Sessions dialog |
| `McpServerForm` | Create and edit form for MCP server registration including URL, slug, and connection settings; guards against reserved `system` slug |
| `McpSessionManager` | Named session CRUD UI; fields include auth type, write-only credentials, `identity_binding`, and `credential_config`; displays default session indicator ("Default" chip), radio-button style selection UI for setting default, auto-default info alert for sole sessions, and delete-blocking logic when removing the current default; follows Dialog Error Handling Standard |
| `McpToolBrowser` | Tool Repository view: all active tools across all servers grouped by server, with assigned skill chips, search filter, server filter, and active toggle |
| `TestMcpToolDialog` | Dialog for testing tool invocation; shows session selection (or agent identity picker for passthrough sessions); uses `is_default` for default session resolution when no explicit `session_id` is provided |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/mcp/servers` | List all registered MCP servers; deduplicates System entry (filters DB copy, prepends virtual entry when `offset=0`); eager-loads sessions to compute `session_count` |
| `POST` | `/api/v1/mcp/servers` | Register a new MCP server; guards against reserved `system` slug |
| `GET` | `/api/v1/mcp/servers/{server_id}` | Get MCP server detail |
| `PUT` | `/api/v1/mcp/servers/{server_id}` | Update MCP server configuration |
| `DELETE` | `/api/v1/mcp/servers/{server_id}` | Delete an MCP server |
| `POST` | `/api/v1/mcp/servers/{server_id}/sync` | Trigger manual tool sync; returns **422** when server has zero sessions; resolves default session by `is_default` flag (with sole-active-session auto-fallback); returns **200** with `SyncResult` containing `warnings: [...]` on partial success; returns **502** only on complete failure |
| `GET` | `/api/v1/mcp/servers/{server_id}/tools` | List synced tools for a server |
| `GET` | `/api/v1/mcp/servers/{server_id}/sessions` | List sessions for a server; includes `identity_binding`, `credential_config`, `is_default` |
| `POST` | `/api/v1/mcp/servers/{server_id}/sessions` | Create a named session; auto-sets `is_default = True` for the server's first session; if `is_default` is explicitly `True`, clears `is_default` on all sibling sessions (at-most-one-default); accepts `identity_binding`, `credential_config`; passthrough auth type skips credential encryption and live test, activates immediately |
| `PUT` | `/api/v1/mcp/servers/{server_id}/sessions/{session_id}` | Update a session; enforces at-most-one-default constraint when `is_default` is set to `True`; accepts `identity_binding`, `credential_config` |
| `DELETE` | `/api/v1/mcp/servers/{server_id}/sessions/{session_id}` | Delete a session; returns **409** if the session is the default and other sessions exist; allows deletion when it is the last session |
| `GET` | `/api/v1/mcp/tools` | List all active tools across all servers, ordered by server name then tool name |
| `GET` | `/api/v1/mcp/tools/{tool_id}/skills` | List all skills bound to a specific tool via `skill_tool_bindings` |
| `GET` | `/api/v1/mcp/tools/{tool_id}/permissions` | List permissions for a tool |
| `POST` | `/api/v1/mcp/tools/{tool_id}/permissions` | Grant tool access to a role |
| `DELETE` | `/api/v1/mcp/tools/{tool_id}/permissions/{permission_id}` | Revoke tool access |
| `POST` | `/api/v1/mcp/tools/{tool_id}/test` | Test a tool call; resolves default session by `is_default` when no explicit `session_id` is provided (supports both passthrough and non-passthrough sessions); `agent_subject` field for passthrough identity resolution (UUID or realm_username); returns `TestToolResponse` with success/error |

---

## Code Reference Map

### Backend — API Layer

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SYSTEM_SERVER_ID` | constant | UUID of the built-in System MCP server (`00000000-0000-0000-0000-000000000001`) | `backend/app/api/v1/mcp_hub.py` |
| `seed_system_tools` | function | Idempotently seeds System server and platform-native tools into DB at startup | `backend/app/api/v1/mcp_hub.py` |
| `_system_server_read` | function | Returns virtual System server entry (hardcoded `session_count = 0`) | `backend/app/api/v1/mcp_hub.py` |
| `_resolve_default_session` | function | Resolves default session for a server by `is_default` flag (with sole-active-session auto-fallback) | `backend/app/api/v1/mcp_hub.py` |
| `_clear_other_defaults` | function | Clears `is_default` on all sibling sessions for at-most-one-default enforcement | `backend/app/api/v1/mcp_hub.py` |
| `list_mcp_servers` | endpoint | Server list API; filters DB-seeded System entry, prepends virtual entry at `offset=0`, eager-loads sessions for `session_count` | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_server` | endpoint | Server create endpoint; guards against reserved `system` slug | `backend/app/api/v1/mcp_hub.py` |
| `sync_mcp_server` | endpoint | Sync trigger; session-gating (422), default-session resolution, warning capture on partial success (200), 502 on complete failure | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_session` | endpoint | Session create; auto-sets `is_default` for first session; enforces at-most-one-default; accepts `identity_binding`, `credential_config` | `backend/app/api/v1/mcp_hub.py` |
| `update_mcp_session` | endpoint | Session update; enforces at-most-one-default; accepts `identity_binding`, `credential_config`, `is_default` | `backend/app/api/v1/mcp_hub.py` |
| `delete_mcp_session` | endpoint | Session delete; returns 409 when deleting default session with siblings; allows last-session deletion | `backend/app/api/v1/mcp_hub.py` |
| `test_mcp_tool` | endpoint | Tool test; resolves default session via `is_default` when no `session_id`; detects passthrough sessions; extracts `request.state.raw_token` for passthrough JWT forwarding; accepts `agent_subject` for passthrough identity resolution | `backend/app/api/v1/mcp_hub.py` |
| `list_all_tools` | endpoint function | Returns all active `McpTool` records across all servers, ordered by server name then tool name | `backend/app/api/v1/mcp_hub.py` |
| `list_tool_skills` | endpoint function | Returns all `Skill` records bound to a given tool via `skill_tool_bindings` | `backend/app/api/v1/mcp_hub.py` |

### Backend — Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpServerRead` | Pydantic schema | Server response schema; includes `session_count: int` for sync-gating UI | `backend/app/schemas/mcp_hub.py` |
| `McpSessionRead` | Pydantic schema | Session response schema; exposes `identity_binding`, `credential_config`, `is_default: bool`; never exposes `encrypted_credentials` | `backend/app/schemas/mcp_hub.py` |
| `McpSessionCreate` | Pydantic schema | Session creation payload; includes `identity_binding`, `credential_config`; optional `is_default: bool`; `@model_validator` rejects credentials when `auth_type` is `passthrough` | `backend/app/schemas/mcp_hub.py` |
| `McpSessionUpdate` | Pydantic schema | Session partial update payload; includes `identity_binding`, `credential_config`; optional `is_default: bool` | `backend/app/schemas/mcp_hub.py` |
| `SyncResult` | Pydantic schema | Sync result response; includes `warnings: list[str]` for non-fatal initialise-handshake warnings | `backend/app/schemas/mcp_hub.py` |
| `TestToolRequest` | Pydantic schema | Tool test request; `session_id` optional (resolved via `is_default` when omitted); `agent_subject` field for passthrough identity resolution (UUID or realm_username) | `backend/app/schemas/mcp_hub.py` |

### Backend — Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ToolSyncService` | class | Fetches tool manifest from a registered MCP server and upserts tools under the server slug namespace | `backend/app/services/mcp/tool_sync.py` |
| `ToolSyncService.sync` | method | Main sync method; captures non-fatal initialise warnings for surfacing in API responses | `backend/app/services/mcp/tool_sync.py` |
| `ToolSyncService._initialize_mcp_session` | method | MCP initialise handshake; returns session ID or `None` on failure | `backend/app/services/mcp/tool_sync.py` |
| `McpProxyEngine` | class | Routes tool-call invocations to the correct server session with credential injection; passthrough branch forwards caller JWT instead of decrypting stored credentials | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine._resolve_session` | method | Resolves session for a tool call; uses `is_default` when no explicit `session_id` is provided | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine.call_tool` | method | Invokes a tool via JSON-RPC with decrypted credentials; accepts optional `agent_jwt` parameter; raises `McpProxyError` if passthrough session selected but no JWT available | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine._build_auth_headers` | method | Builds auth headers from decrypted session credentials; passthrough branch injects `agent_jwt` as `Authorization: Bearer` header | `backend/app/services/mcp/proxy.py` |
| `McpProxyError` | exception | Raised when an MCP tool call fails (e.g. missing JWT for passthrough, unreachable server) | `backend/app/services/mcp/proxy.py` |
| `OAuthRefreshService` | class | Manages OAuth2 token refresh lifecycle for MCP sessions; checks token expiry and performs refresh callbacks | `backend/app/services/mcp/oauth_refresh.py` |
| `test_mcp_session_connection` | function | Tests connectivity to a session's MCP server; returns immediate success for passthrough auth type without performing a live connection test | `backend/app/services/mcp_session_test.py` |

### Backend — Models & Migrations

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpServer` | model | SQLAlchemy model for a registered external MCP tool server; `sessions` relationship used for server list session count | `backend/app/db/models/mcp_hub.py` |
| `McpSession` | model | SQLAlchemy model for a named MCP session; stores encrypted credentials, `identity_binding` (JSON), `credential_config` (JSON), and `is_default` boolean flag for explicit default session resolution | `backend/app/db/models/mcp_hub.py` |
| `McpSessionAuthType` | enum | `str` enum — `api_key`, `bearer_token`, `basic_auth`, `oauth2`, `none`, `passthrough` | `backend/app/db/models/mcp_hub.py` |
| `McpTool` | model | SQLAlchemy model for a synced tool namespaced under a server slug | `backend/app/db/models/mcp_hub.py` |
| `ToolPermission` | model | SQLAlchemy model granting a role access to a specific tool | `backend/app/db/models/mcp_hub.py` |
| `add_passthrough_to_mcp_session_auth_type` | migration | Adds `passthrough` to `mcp_session_auth_type_enum`; downgrade is no-op | `backend/alembic/versions/5c2910c238a8_add_passthrough_to_mcp_session_auth_type.py` |
| `add_is_default_to_mcp_sessions` | migration | Adds `is_default` boolean column to `mcp_sessions` table | `backend/alembic/versions/6beca08c57cf_add_is_default_to_mcp_sessions.py` |

### Frontend — Types

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpServer` (TypeScript) | interface | Frontend type for MCP server; includes `session_count: number` for sync gating | `frontend/src/types/index.ts` |
| `McpSession` (TypeScript) | interface | Frontend type for MCP session; includes `is_default: boolean`, `identity_binding`, `credential_config` | `frontend/src/types/index.ts` |

### Frontend — Hooks

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useMcpServers` | hook | React Query hook for fetching and caching the paginated MCP server list | `frontend/src/hooks/useMcpServers.ts` |
| `useSyncServer` | hook | Mutation hook for triggering manual tool sync for a server | `frontend/src/hooks/useMcpServers.ts` |
| `useServerSessions` | hook | React Query hook for fetching sessions for a specific MCP server; includes `is_default`, `identity_binding`, `credential_config` | `frontend/src/hooks/useMcpServers.ts` |
| `useServerTools` | hook | React Query hook for fetching synced tools for a specific server | `frontend/src/hooks/useMcpServers.ts` |
| `useAllTools` | hook | React Query hook fetching all active tools across all servers; cache key `['mcp', 'tools']` | `frontend/src/hooks/useMcpServers.ts` |
| `useToolSkills` | hook | React Query hook fetching skills bound to a specific tool; cache key `['mcp', 'tools', toolId, 'skills']` | `frontend/src/hooks/useMcpServers.ts` |

### Frontend — Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpHubPage` | component | Tabbed MCP Hub: Servers tab + Tool Repository tab; System entry detection with "Built-in" chip and disabled actions; session count column; conditional sync button (disabled with tooltip when `session_count === 0`); hosts per-server Sessions dialog | `frontend/src/pages/mcp/McpHubPage.tsx` |
| `McpServerForm` | component | Create/edit form for MCP server registration; guards against reserved `system` slug | `frontend/src/pages/mcp/McpServerForm.tsx` |
| `McpSessionManager` | component | Session CRUD UI with auth type, write-only credentials, `identity_binding`, `credential_config`; default session indicator ("Default" chip), radio-button selection UI for setting default, auto-default info alert for sole sessions, delete-blocking when removing current default; passthrough: credential fields hidden, info Alert shown, Passthrough chip in table; follows Dialog Error Handling Standard | `frontend/src/pages/mcp/McpSessionManager.tsx` |
| `TestMcpToolDialog` | component | Tool test dialog; shows session selection resolved via `is_default`; shows agent identity picker instead of session picker for passthrough sessions; sends `agent_subject` in payload for passthrough; agent identities fetched from `/agents/identities` | `frontend/src/pages/mcp/TestMcpToolDialog.tsx` |
| `McpToolBrowser` | component | Tool Repository: all tools grouped by server with skill chips, search filter, server filter, active toggle | `frontend/src/pages/mcp/McpToolBrowser.tsx` |

### Test Files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_mcp_hub_api.py` | test module | API integration tests for MCP Hub endpoints | `backend/tests/api/v1/test_mcp_hub_api.py` |
| `test_mcp_hub.py` (unit) | test module | Unit tests for MCP Hub services including sync resilience scenarios | `backend/tests/unit/test_mcp_hub.py` |
| `test_mcp_session.py` | test module | Unit tests for MCP session schemas (`is_default`, `session_count` validation) | `backend/tests/unit/test_mcp_session.py` |
| `test_mcp_proxy.py` | test module | Unit tests for `McpProxyEngine`; includes session resolution and passthrough auth scenarios | `backend/tests/unit/test_mcp_proxy.py` |
| `test_mcp_hub.py` (integration) | test module | Integration tests for MCP Hub business logic | `backend/tests/integration/test_mcp_hub.py` |
| `McpSessionManager.test` | test module | Component tests for `McpSessionManager`; includes passthrough UI and default session selection | `frontend/src/__tests__/McpSessionManager.test.tsx` |
| `TestMcpToolDialog.test` | test module | Component tests for `TestMcpToolDialog`; includes identity picker for passthrough, session picker for standard sessions | `frontend/src/__tests__/TestMcpToolDialog.test.tsx` |
| `mcp-hub.spec.ts` | test module | E2E tests for MCP Hub UI flows | `e2e/tests/mcp-hub.spec.ts` |
| `mcp-tool-validation.spec.ts` | test module | E2E tests for MCP tool validation | `e2e/tests/mcp-tool-validation.spec.ts` |

### i18n

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `mcp.sessions.passthrough` | i18n key | Display label for passthrough auth type chip in session table | `frontend/src/i18n/locales/en.json` |
| `mcp.sessions.passthroughInfo` | i18n key | Informational Alert text shown when passthrough auth type is selected | `frontend/src/i18n/locales/en.json` |
