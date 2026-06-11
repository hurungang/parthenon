# MCP Hub Test Plan

## What to Test

### MCP Server Management
- MCP server registration
- Slug uniqueness enforcement
- Slug format enforcement (lowercase letters, numbers, hyphens) on MCP server naming fields
- Tool sync and removal
- Proxy call routing
- Permission enforcement on all MCP server endpoints (`mcp_server:read`, `mcp_server:create`, `mcp_server:update`, `mcp_server:delete`)
- 403 structured error responses with resource type, action, and resource ID
- Permission-denied UI rendering: snackbar on 403 from MCP server delete includes resource ID context

### System Entry Deduplication
- MCP server list returns zero or one System entry, never duplicates
- System entry is visually distinct from user-registered servers (Built-in/platform label)
- System entry is immutable: no sync, edit, or delete actions available
- Creating or deleting real MCP servers does not affect the System entry count
- System entry appears only at offset 0 in paginated listing; excluded at offset > 0
- System entry has `session_count: 0` and uses a reserved slug

### Sync Resilience
- Sync succeeds when `tools/list` works even if `initialize` handshake fails or returns unexpected response
- Sync failure when both `initialize` and `tools/list` fail returns specific, actionable error messages (not generic)
- Sync updates `last_synced_at` timestamp on success
- Sync does NOT update `last_synced_at` on failure
- Sync error messages differ by failure mode (no network vs. auth failure vs. protocol error)

### Sync Visibility & Session Dependency
- Server with one or more sessions: sync button/action is visible and enabled
- Server with zero sessions: sync button/action is hidden or disabled with explanatory tooltip ("no configured sessions")
- After creating a session via dialog, sync button becomes visible/enabled in the parent server row (parent table refreshes without page reload)
- After deleting all sessions, sync button becomes hidden/disabled (parent table refreshes)
- System entry never shows sync action regardless of state
- Attempting to sync a server with zero sessions returns HTTP 422 with actionable detail message

### Default Session
- `is_default` BOOLEAN column exists on `mcp_sessions` table, NOT NULL, default `false`
- Pydantic schemas: `McpSessionCreate`/`McpSessionUpdate` accept optional `is_default`; `McpSessionRead` includes `is_default` (but never `encrypted_credentials`)
- **Single Session**: First session on a server auto-defaults to `is_default = true`; sole session is visibly marked as default regardless of flag
- **Multiple Sessions**: Admin can set exactly one session as default per server; setting a new default auto-unsets the previous; at most one default per server
- **Delete Default**: Deleting the default session with other sessions remaining prompts admin to select a new default (or delete is rejected)
- **Sync/Tool Routing**: Sync and tool calls use the default session when no specific session is specified; if no default and multiple sessions exist, sync fails with clear error
- **Passthrough Compat**: Passthrough sessions are eligible as default and function correctly for sync and tool calls
- **Backward Compat**: Existing sessions without `is_default` display as `false` and function without errors; migration defaults all existing sessions to `false`

### Parent Table Refresh (Cross-cutting)
- After creating a session via dialog → server row in parent table updates without page reload
- After editing a session (setting `is_default`) → session list refreshes, default badge updates
- After deleting a session → parent table and session list refresh
- Session count changes reflect in UI immediately after create/delete

### MCP Sessions
- Session CRUD lifecycle: create, read, update, delete per MCP server
- Session `identity_binding` and `credential_config` fields accepted and persisted
- Session credentials (`encrypted_credentials`) never returned in any API response or UI field
- Credential field is write-only in edit form — existing value is not pre-populated
- Dialog error handling: 403, 422, and 500 errors displayed inside session dialog
- Session list (McpSessionManager) refreshes after create/edit/delete without page reload
- Credential preserved on update when credential field is omitted from request

### Passthrough Sessions
- `auth_type = "passthrough"` accepted on session create; session persisted with `is_active = True` and no credential data
- Creating a passthrough session with credentials in the body returns HTTP 422
- `mcp_session_auth_type_enum` database enum includes the `passthrough` value (verified via `information_schema`)
- Connection test result for a passthrough session reports immediate success (no live HTTP call)
- `_build_auth_headers()` injects the caller's JWT as `Authorization: Bearer <jwt>` for passthrough sessions; credential vault never accessed
- `_build_auth_headers()` raises `McpProxyError` when called with a passthrough session but no `agent_jwt` supplied
- Tool test endpoint: authenticated caller with a passthrough session → caller's JWT forwarded to proxy
- Tool test endpoint: unauthenticated caller with a passthrough session → HTTP 400 with descriptive error
- Auth middleware stores raw bearer token on `request.state.raw_token` immediately after extraction; absent when no `Authorization` header
- McpSessionManager: passthrough option present in auth type selector; credential fields hidden when selected; informational alert shown
- McpSessionManager: switching between passthrough and credential auth types toggles fields without page reload
- McpSessionManager: passthrough sessions display a "Passthrough" chip in the session table auth type column
- Submit payload for passthrough session creation omits `credentials` field entirely
- Role Assignment Dialog: passthrough sessions display a "Passthrough" badge; remain selectable; one-session-per-server toggle UI not shown for passthrough sessions

### Tool Repository
- `GET /mcp/tools` returns all active tools across all servers, ordered by server name then tool name
- `GET /mcp/tools` returns empty list when no active tools exist
- `GET /mcp/tools/{tool_id}/skills` returns all skills bound to a tool
- `GET /mcp/tools/{tool_id}/skills` returns empty list (not 404) for tools with no skill bindings
- Both endpoints require authentication; unauthenticated requests rejected (401/403)
- McpToolBrowser: tools grouped by server, search filters by name (client-side), server filter dropdown works
- Each tool shows skill chips for assigned skills

## Critical Scenarios

### System Entry & Deduplication
- MCP server list displays exactly one System entry, visually distinct (Built-in chip) from real servers — no duplicates
- System entry remains unchanged when real servers are created or deleted
- System entry has no sync, edit, or delete actions
- System entry appears only at offset 0; excluded from paginated results at offset > 0

### Sync Resilience
- Sync with `tools/list` succeeding but `initialize` failing completes with tools discovered and a warning
- Sync with both `initialize` and `tools/list` failing returns actionable error (connection refused vs. auth error vs. protocol mismatch)
- Sync success updates `last_synced_at`; sync failure does NOT update it

### Sync Visibility & Session Dependency
- Sync button visible/enabled when server has sessions; hidden/disabled with tooltip when server has zero sessions
- Sync button state updates automatically after session create/delete (parent table refresh, no manual page reload)
- Attempting sync on a server with zero sessions returns HTTP 422

### Default Session — Single Session
- First session created on a server auto-sets `is_default = true` on the backend
- Sole session is visibly marked as default regardless of the `is_default` column value
- API response for a sole session includes `is_default: true`

### Default Session — Multiple Sessions
- Admin sets a session as default; previous default is auto-unset (at most one per server)
- Default session is visually distinguished in sessions list (badge, chip, or icon)
- Deleting the default session with other sessions remaining requires explicit admin action (prompt or reject)
- Non-default session deletion does not affect the default
- Creating a new session does not auto-override existing default

### Default Session — Sync & Tool Routing
- Sync uses the default session when no session is specified
- Sync fails clearly when multiple sessions exist but none is marked default

### Passthrough & Backward Compatibility
- Passthrough sessions are eligible as default and work for sync and tool calls
- Existing sessions (pre-migration) display `is_default: false` and function without errors
- Encrypted credentials never appear in `is_default` response fields (security invariant)

### Core MCP Hub
- Admin registers MCP server and tools are synced
- MCP session with identity binding proxies call using bound identity
- Session created with credential — `encrypted_credentials` absent from all subsequent read responses
- Session updated with new credential — old credential replaced; new credential never returned
- Session updated without providing credential field — existing encrypted credential is preserved
- `GET /mcp/tools` returns tools from multiple servers in correct sort order
- McpSessionManager dialog shows 403 error inline — not silent failure
- McpHubPage tabs (Servers / Tool Repository) switchable without runtime errors
- Parent MCP server list unchanged after session operations (sessions are sub-resource)
- User without `mcp_server:read` receives 403 on `GET /api/v1/mcp/servers`; UI shows permission-denied snackbar
- User without `mcp_server:create` receives 403 on `POST /api/v1/mcp/servers`; snackbar pre-filled with resource type and action
- 403 on MCP server delete includes resource ID in snackbar context
- User with correct permissions completes full MCP server CRUD flow
- MCP server registration with non-slug values is rejected with inline validation and blocked save action
- Passthrough session created with no credentials → `is_active: true`, no credential data stored, connection test reports success
- Passthrough session created with credentials → HTTP 422 returned; no session persisted
- Authenticated user POSTs to tool test endpoint with passthrough session → proxy receives caller's JWT; tool result returned
- Unauthenticated caller POSTs to tool test endpoint with passthrough session → HTTP 400 with descriptive error
- `request.state.raw_token` populated when valid JWT present; absent when no `Authorization` header

## Edge Cases
- Duplicate slug registration
- System entry slug collision — reserved slug that normal registration rejects
- Partial tool sync (server partially responds)
- Tool removed between syncs
- Permission revoked between tool sync and proxy call
- Tool with no skill bindings returns empty `skills` array (not 404)
- Search term in McpToolBrowser matches display name and slug formats
- Passthrough session created alongside credential session for same server — both persisted; role assignment UI shows both; no conflict
- Frontend auth type toggle mid-form — form state resets cleanly; no stale credential data submitted for passthrough
- Passthrough chip absent from session table for legacy sessions loaded before UI update — `auth_type` field in API response drives rendering
- MCP server rejects forwarded JWT (401/403) — `McpProxyError` raised; tool test reports failure with status code
- Server with single inactive session — still indicated as default but sync may fail gracefully
- Server with one passthrough session as sole/default — sync without caller token returns clear missing-identity error
- Rapid toggle of `is_default` between two sessions (race condition) — last-write-wins consistency
- Session with `is_default = true` deactivated (`is_active = false`) — sync uses active default; if default is inactive, sync fails with clear message
- Sync with no sessions but stale session-count cache — session count always queried fresh from DB before sync button visibility decision
- Deleting the last session (which was default) — server transitions to zero-session state; sync button disappears, no stale default indicators
- Migration on database with existing sessions — `is_default` defaults to `false` for all; admin must explicitly configure
- `is_default` column non-nullable enforcement — inserting session without `is_default` succeeds (defaults to `false`); NULL inserts rejected
- Concurrent session creation — two sessions created simultaneously both potentially get `is_default = true`; server-side uniqueness enforcement

## Known Limitations
- Full Vitest component tests for McpSessionManager and McpToolBrowser are implemented; McpHubPage tab navigation is also covered.
- Default session display (badge/chip) and deletion-blocking tests in the frontend Vitest suite validate `is_default` UI rendering and user interaction.

## Test File References

### Backend
- `backend/tests/unit/test_mcp_hub.py` — server registration, slug uniqueness, tool sync, sync resilience (initialize fails but tools/list succeeds; both fail; `last_synced_at` timestamp update)
- `backend/tests/unit/test_mcp_session.py` — session unit logic, `is_default` schema validation (read/create/update schemas), model defaults
- `backend/tests/unit/test_mcp_proxy.py` — proxy call routing, identity binding, passthrough `_build_auth_headers()` success and `McpProxyError` on missing JWT, `_resolve_session()` accepts passthrough with no credentials
- `backend/tests/unit/test_credential_vault.py` — credential encryption/decryption
- `backend/tests/unit/test_auth_middleware.py` — `request.state.raw_token` populated after valid JWT; absent without `Authorization` header
- `backend/tests/api/v1/test_mcp_hub_api.py` — `GET /mcp/tools`, `GET /mcp/tools/{id}/skills`, session create/update/read with `identity_binding` and `credential_config`, credential exclusion from responses, System entry dedup (offset 0 vs. non-zero), sync session gating (422), `session_count` in server response, `is_default` in session response, default session resolution by `is_default` flag
- `backend/tests/integration/test_enhance_mcp_hub_skills_sops_db.py` — schema migration verification (`identity_binding`, `credential_config` columns exist), credential-not-returned integration path, real-database constraint enforcement
- `backend/tests/integration/test_mcp_hub.py` — passthrough session creation (success + credential rejection); tool test (authenticated success + unauthenticated 400); `mcp_session_auth_type_enum` schema verification via `information_schema`; requires `alembic upgrade head` before execution; existing passthrough tests compatible with `is_default` (defaults to false)

### Frontend
- `frontend/src/__tests__/McpHubPage.test.tsx` — tab navigation (Servers / Tool Repository), session dialog trigger from server row, System entry deduplication (Built-in chip, disabled actions, platform slug), sync button visibility based on `session_count` (disabled when 0, enabled when > 0)
- `frontend/src/__tests__/McpSessionManager.test.tsx` — session CRUD rendering, `identity_binding` and `credential_config` inputs, write-only credential field, dialog error display, passthrough credential field hiding, passthrough informational alert, passthrough chip in table, submit payload omits credentials for passthrough, default session display (Default chip, radio buttons, auto-default alert, sole session indicator), default session deletion blocking (delete prompt)
- `frontend/src/__tests__/McpToolBrowser.test.tsx` — tool list grouped by server, search filtering, server filter dropdown, skill chips
- `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx` — passthrough badge displayed next to session name; passthrough session selectable; one-session-per-server toggle not shown for passthrough

### E2E
- `e2e/tests/mcp-hub.spec.ts` — full McpSessionManager CRUD flow (mocked), Tool Repository tab with tool grouping and search (mocked), parent table refresh after session operations; System Entry desk block (Built-in chip, disabled sync), sync button visibility (enabled with sessions, disabled without); `test.describe('Real Backend Integration - MCP Default Session')` — real System entry verification (one System entry, correct slug/name), real 422 on sync without sessions, real server creation/deletion with cleanup
- `e2e/tests/agent-a2a-communication.spec.ts` — MCP server slug validation coverage (`mcp server registration blocks invalid slug values`)
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering per page
- `e2e/tests/passthrough-sessions.spec.ts` — mocked suite: admin creates passthrough session via UI, chip displayed, tool test dialog shows identity picker, API contract validated; `test.describe('Real Backend Integration')` suite: backend health check, unauthenticated tool test returns correct status, passthrough+credentials rejected by real backend
