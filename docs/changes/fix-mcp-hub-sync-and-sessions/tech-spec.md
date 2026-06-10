# Technical Specification: Fix MCP Hub Sync & Sessions

## Technical Overview

This change modifies the MCP Hub subsystem across database, backend API, backend services, and frontend layers. A new `is_default` boolean column is added to `mcp_sessions` to replace the implicit creation-order default session resolution with an explicit flag. The `list_mcp_servers` endpoint is fixed to deduplicate the System server entry. The sync flow in `ToolSyncService` is hardened to tolerate non-fatal initialize-handshake failures and to gate on session existence. The frontend `McpHubPage` and `McpSessionManager` gain conditional sync controls, a distinct System entry presentation, and an interactive default-session selection UI.

## Component Breakdown

### Database Model Layer
- **McpSession model** (`backend/app/db/models/mcp_hub.py`): Gains `is_default` boolean column (`False` default, not nullable). No other model changes; the `McpServer`, `McpTool`, and `ToolPermission` models are unchanged.

### Backend Schema Layer
- **McpSessionRead**, **McpSessionCreate**, **McpSessionUpdate** (`backend/app/schemas/mcp_hub.py`): All gain `is_default` field (required boolean on Read, optional boolean on Create/Update).
- **McpServerRead**: Gains `session_count: int` field to expose session count in the server list without requiring the frontend to make N+1 session queries.
- **SyncResult**: Gains `warnings: list[str]` field to surface non-fatal initialize-handshake warnings alongside tool counts.

### Backend API Layer
- **list_mcp_servers** (`backend/app/api/v1/mcp_hub.py`): Filters the seeded DB copy of the System server from results before prepending the virtual entry. Eager-loads sessions to populate `session_count`.
- **create_mcp_session**: Auto-sets `is_default = True` when the new session is the server's first. Enforces at-most-one-default by clearing `is_default` on sibling sessions when `is_default` is explicitly `True`.
- **update_mcp_session**: Same at-most-one-default enforcement when `is_default` is set to `True`.
- **delete_mcp_session**: Returns 409 if the session being deleted is the default and other sessions exist; allows deletion when it is the last session.
- **sync_mcp_server**: Returns 422 when the server has zero sessions. Resolves the default session by `is_default` flag (with sole-active-session auto-fallback). Returns 200 with warnings on partial success; only raises 502 on complete failure.
- **test_mcp_tool**: Uses `is_default` for session resolution when no explicit `session_id` is provided, extending coverage beyond passthrough-only sessions.

### Backend Service Layer
- **ToolSyncService** (`backend/app/services/mcp/tool_sync.py`): `sync()` method gains warnings capture for non-fatal initialize failures. The `_initialize_mcp_session` helper already catches exceptions gracefully; this change formalizes the warning path so callers can surface warnings to the API response.
- **McpProxyEngine** (`backend/app/services/mcp/proxy.py`): `_resolve_session()` replaces the "first active session" fallback with `is_default`-based resolution.

### Frontend Type Layer
- **McpSession** interface (`frontend/src/types/index.ts`): Gains `is_default: boolean`.
- **McpServer** interface (`frontend/src/types/index.ts`): Gains `session_count: number`.

### Frontend Component Layer
- **McpHubPage** (`frontend/src/pages/mcp/McpHubPage.tsx`): Gains System entry detection with distinct "Built-in" chip and disabled actions; session count column; conditional sync button (disabled with tooltip when `session_count === 0`); contextual info banner for System entry.
- **McpSessionManager** (`frontend/src/pages/mcp/McpSessionManager.tsx`): Gains default session indicator ("Default" chip), radio-button style selection UI for setting default, auto-default info alert for sole sessions, and delete-blocking logic when removing the current default.

### Frontend Hooks Layer
- **useMcpServers** (`frontend/src/hooks/useMcpServers.ts`): No structural changes needed; the hook already returns `McpServer[]` and `useSyncServer` already handles the sync mutation. The new `session_count` field on `McpServerRead` flows through automatically.

## API Changes

### Modified Endpoints

**`GET /mcp/servers`** — Server list with dedup and session count
- Response `McpServerRead` objects now include `session_count: int`
- Exactly one System entry returned when `offset=0` (DB-seeded copy filtered out)
- Eager-loads `sessions` relationship for count computation

**`POST /mcp/servers/{server_id}/sync`** — Resilient sync with session gating
- Returns **422** when server has zero sessions: `{"detail": "This server has no configured sessions. Add a session before syncing."}`
- Resolves default session by `is_default` flag (with sole-active-session auto-fallback)
- Returns **200** with `SyncResult` containing `warnings: [...]` on partial success (initialize issues but tools/list succeeded)
- Returns **502** only on complete failure (tools/list unreachable)

**`POST /mcp/servers/{server_id}/sessions`** — Create session with auto-default
- Request body `McpSessionCreate` gains optional `is_default: bool` field
- Auto-sets `is_default = True` when creating the server's first session
- If `is_default` is explicitly `True`, clears `is_default` on all other sessions for this server

**`PUT /mcp/servers/{server_id}/sessions/{session_id}`** — Update session with default enforcement
- Request body `McpSessionUpdate` gains optional `is_default: bool` field
- If `is_default` is set to `True`, clears `is_default` on all other sessions for this server

**`DELETE /mcp/servers/{server_id}/sessions/{session_id}`** — Default session deletion protection
- Returns **409** when deleting the default session and other sessions exist: `{"detail": "The default session cannot be deleted while other sessions exist. Please designate another session as default first."}`
- Allows deletion when it is the last session (no other sessions to re-assign)

**`POST /mcp/tools/{tool_id}/test`** — Default session resolution
- When `session_id` is not provided, resolves session by `is_default` flag (previously only auto-resolved passthrough sessions; non-passthrough required explicit `session_id`)

### Schema Changes

**`SyncResult`**: New field `warnings: list[str]` (defaults to empty list)

**`McpServerRead`**: New field `session_count: int` (defaults to 0)

**`McpSessionRead`**: New field `is_default: bool`

**`McpSessionCreate`**: New optional field `is_default: bool | None`

**`McpSessionUpdate`**: New optional field `is_default: bool | None`

## State Management

### Server Query Cache Invalidation

- **Set-default mutation**: When a session is marked as default via `PUT /mcp/servers/{serverId}/sessions/{sessionId}`, the sessions query (`['mcp', 'servers', serverId, 'sessions']`) must be invalidated to reflect the new default state in the UI.
- **Delete session**: Existing invalidation for sessions query continues to work; additionally, if the deleted session was the default and the delete is blocked by the backend (409), the frontend must show the error message via `dialogError` state (using existing `PermissionDeniedAlert` pattern).
- **Create session**: Existing invalidation continues to work. The new `is_default` auto-assignment is reflected when sessions are re-fetched.

### UI State for Default Selection

- `McpSessionManager` gains a `useMutation` for setting a session as default. The mutation calls `PUT /mcp/servers/{serverId}/sessions/{sessionId}` with `{ is_default: true }` and invalidates the sessions query on success.
- No new global state or store is needed — session data is managed via React Query cache.

## Data Access Patterns

### Server-Side (Backend)

- **Server list with session count**: Eager-loading `sessions` relationship via `selectinload(McpServer.sessions)` in `list_mcp_servers`. The count is computed from the loaded relationship in Python (not a subquery) to avoid adding SQL complexity. The System virtual entry has `session_count = 0` hardcoded.
- **System server dedup**: The DB-seeded System server (matching `SYSTEM_SERVER_ID`) is excluded from the query results using a `WHERE` clause or by filtering the result list in Python. The virtual entry from `_system_server_read()` is always prepended when `offset == 0`.
- **Default session resolution**: All three call sites (sync endpoint, proxy engine, tool test endpoint) follow the same resolution pattern: query `is_default = True AND is_active = True` first; if not found, check if exactly one active session exists and use it; if multiple active and no default, return an actionable error.
- **At-most-one-default enforcement**: Enforced in application logic (not a DB partial unique index, to keep deployment simple). On create/update, when `is_default` is set to `True`, a separate UPDATE sets all sibling sessions to `is_default = False` within the same transaction.

### Client-Side (Frontend)

- **Session count for sync gating**: Read from `server.session_count` on the `McpServer` object returned by the server list query. No separate session count API call is needed.
- **Session list for default management**: Fetched via `useQuery` with key `['mcp', 'servers', serverId, 'sessions']` inside `McpSessionManager`. The `is_default` field is used to determine which session shows the "Default" chip and which radio button is selected.
- **Set-default mutation**: Uses `useMutation` calling `PUT /mcp/servers/{serverId}/sessions/{sessionId}` with `{ is_default: true }`. The `useQueryClient` is used to invalidate the sessions query on success.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpSession` (SQLAlchemy) | model | ORM model for MCP sessions; gains `is_default` column | `backend/app/db/models/mcp_hub.py` |
| `McpServer` (SQLAlchemy) | model | ORM model for MCP servers; `sessions` relationship used for count | `backend/app/db/models/mcp_hub.py` |
| `McpSessionRead` | schema | Pydantic read schema; gains `is_default: bool` | `backend/app/schemas/mcp_hub.py` |
| `McpSessionCreate` | schema | Pydantic create schema; gains optional `is_default: bool` | `backend/app/schemas/mcp_hub.py` |
| `McpSessionUpdate` | schema | Pydantic update schema; gains optional `is_default: bool` | `backend/app/schemas/mcp_hub.py` |
| `McpServerRead` | schema | Pydantic read schema; gains `session_count: int` | `backend/app/schemas/mcp_hub.py` |
| `SyncResult` | schema | Pydantic sync result schema; gains `warnings: list[str]` | `backend/app/schemas/mcp_hub.py` |
| `list_mcp_servers` | endpoint | Server list API; dedups System entry, adds session count | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_server` | endpoint | Server create; guards reserved "system" slug | `backend/app/api/v1/mcp_hub.py` |
| `sync_mcp_server` | endpoint | Sync API; adds session gating, default resolution, warning capture | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_session` | endpoint | Session create; auto-sets `is_default`, enforces uniqueness | `backend/app/api/v1/mcp_hub.py` |
| `update_mcp_session` | endpoint | Session update; enforces at-most-one-default constraint | `backend/app/api/v1/mcp_hub.py` |
| `delete_mcp_session` | endpoint | Session delete; blocks default deletion when siblings exist | `backend/app/api/v1/mcp_hub.py` |
| `test_mcp_tool` | endpoint | Tool test; resolves default session via `is_default` | `backend/app/api/v1/mcp_hub.py` |
| `_system_server_read` | function | Returns virtual System server entry | `backend/app/api/v1/mcp_hub.py` |
| `_resolve_default_session` | function | Resolves default session by is_default flag | `backend/app/api/v1/mcp_hub.py` |
| `_clear_other_defaults` | function | Clears is_default on sibling sessions (at-most-one-default) | `backend/app/api/v1/mcp_hub.py` |
| `SYSTEM_SERVER_ID` | constant | UUID of the built-in System MCP server | `backend/app/api/v1/mcp_hub.py` |
| `seed_system_tools` | function | Idempotently seeds System server and tools into DB | `backend/app/api/v1/mcp_hub.py` |
| `ToolSyncService` | class | Fetches tool lists from MCP servers, upserts tool records | `backend/app/services/mcp/tool_sync.py` |
| `ToolSyncService.sync` | method | Main sync method; gains warnings capture for non-fatal failures | `backend/app/services/mcp/tool_sync.py` |
| `ToolSyncService._initialize_mcp_session` | method | MCP initialize handshake; returns session ID or None | `backend/app/services/mcp/tool_sync.py` |
| `McpProxyEngine` | class | Routes tool-call invocations to MCP server sessions | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine._resolve_session` | method | Resolves session for a tool call; uses `is_default` when no `session_id` | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine.call_tool` | method | Invokes a tool via JSON-RPC with decrypted credentials | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine._build_auth_headers` | method | Builds auth headers from decrypted session credentials | `backend/app/services/mcp/proxy.py` |
| `McpProxyError` | exception | Raised when an MCP tool call fails | `backend/app/services/mcp/proxy.py` |
| `OAuthRefreshService` | class | Manages OAuth2 token refresh for MCP sessions | `backend/app/services/mcp/oauth_refresh.py` |
| `McpServer` (TypeScript) | interface | Frontend type for MCP server; gains `session_count` | `frontend/src/types/index.ts` |
| `McpSession` (TypeScript) | interface | Frontend type for MCP session; gains `is_default` | `frontend/src/types/index.ts` |
| `McpHubPage` | component | MCP Hub management page with server list and tool browser tabs | `frontend/src/pages/mcp/McpHubPage.tsx` |
| `McpSessionManager` | component | Session management table with create/edit/delete/default- selection | `frontend/src/pages/mcp/McpSessionManager.tsx` |
| `McpToolBrowser` | component | Tool repository browser tab | `frontend/src/pages/mcp/McpToolBrowser.tsx` |
| `TestMcpToolDialog` | component | Dialog for testing tool invocation with session selection | `frontend/src/pages/mcp/TestMcpToolDialog.tsx` |
| `McpServerForm` | component | Create/edit server form dialog | `frontend/src/pages/mcp/McpServerForm.tsx` |
| `useMcpServers` | hook | Fetches paginated MCP server list | `frontend/src/hooks/useMcpServers.ts` |
| `useSyncServer` | hook | Mutation hook for triggering server sync | `frontend/src/hooks/useMcpServers.ts` |
| `useServerSessions` | hook | Fetches sessions for a specific server | `frontend/src/hooks/useMcpServers.ts` |
| `useServerTools` | hook | Fetches tools for a specific server | `frontend/src/hooks/useMcpServers.ts` |
| `test_mcp_session_connection` | function | Tests connectivity to a session's MCP server | `backend/app/services/mcp_session_test.py` |
| Migration file `add_is_default_to_mcp_sessions` | migration | Adds `is_default` column to `mcp_sessions` table | `backend/alembic/versions/6beca08c57cf_add_is_default_to_mcp_sessions.py` |
| `test_mcp_hub_api.py` | test | API integration tests for MCP Hub endpoints | `backend/tests/api/v1/test_mcp_hub_api.py` |
| `test_mcp_hub.py` (unit) | test | Unit tests for MCP Hub services (10 tests: 7 pre-existing + 3 new for sync resilience) | `backend/tests/unit/test_mcp_hub.py` |
| `test_mcp_session.py` | test | Unit tests for MCP session schemas (5 tests: all new for is_default / session_count) | `backend/tests/unit/test_mcp_session.py` |
| `test_mcp_proxy.py` | test | Unit tests for MCP proxy engine (5 tests: 2 session resolution + 3 passthrough auth) | `backend/tests/unit/test_mcp_proxy.py` |
| `test_mcp_hub.py` (integration) | test | Integration tests for MCP Hub business logic (unchanged, passthrough scenarios already neutral) | `backend/tests/integration/test_mcp_hub.py` |
| `mcp-hub.spec.ts` | test | E2E tests for MCP Hub UI | `e2e/tests/mcp-hub.spec.ts` |
| `mcp-tool-validation.spec.ts` | test | E2E tests for MCP tool validation | `e2e/tests/mcp-tool-validation.spec.ts` |
