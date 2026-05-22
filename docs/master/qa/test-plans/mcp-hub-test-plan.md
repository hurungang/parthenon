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
- Partial tool sync (server partially responds)
- Tool removed between syncs
- Permission revoked between tool sync and proxy call
- Tool with no skill bindings returns empty `skills` array (not 404)
- Search term in McpToolBrowser matches display name and slug formats
- Passthrough session created alongside credential session for same server — both persisted; role assignment UI shows both; no conflict
- Frontend auth type toggle mid-form — form state resets cleanly; no stale credential data submitted for passthrough
- Passthrough chip absent from session table for legacy sessions loaded before UI update — `auth_type` field in API response drives rendering
- MCP server rejects forwarded JWT (401/403) — `McpProxyError` raised; tool test reports failure with status code

## Known Limitations
- Full Vitest component tests for McpSessionManager and McpToolBrowser are implemented; McpHubPage tab navigation is also covered.

## Test File References

### Backend
- `backend/tests/unit/test_mcp_hub.py` — server registration, slug uniqueness, tool sync
- `backend/tests/unit/test_mcp_proxy.py` — proxy call routing, identity binding, passthrough `_build_auth_headers()` success and `McpProxyError` on missing JWT, `_resolve_session()` accepts passthrough with no credentials
- `backend/tests/unit/test_mcp_session.py` — session unit logic
- `backend/tests/unit/test_credential_vault.py` — credential encryption/decryption
- `backend/tests/unit/test_auth_middleware.py` — `request.state.raw_token` populated after valid JWT; absent without `Authorization` header
- `backend/tests/api/v1/test_mcp_hub_api.py` — `GET /mcp/tools`, `GET /mcp/tools/{id}/skills`, session create/update/read with `identity_binding` and `credential_config`, credential exclusion from responses
- `backend/tests/integration/test_enhance_mcp_hub_skills_sops_db.py` — schema migration verification (`identity_binding`, `credential_config` columns exist), credential-not-returned integration path, real-database constraint enforcement
- `backend/tests/integration/test_mcp_hub.py` — passthrough session creation (success + credential rejection); tool test (authenticated success + unauthenticated 400); `mcp_session_auth_type_enum` schema verification via `information_schema`; requires `alembic upgrade head` before execution

### Frontend
- `frontend/src/__tests__/McpHubPage.test.tsx` — tab navigation (Servers / Tool Repository), session dialog trigger from server row
- `frontend/src/__tests__/McpSessionManager.test.tsx` — session CRUD rendering, `identity_binding` and `credential_config` inputs, write-only credential field, dialog error display, passthrough credential field hiding, passthrough informational alert, passthrough chip in table, submit payload omits credentials for passthrough
- `frontend/src/__tests__/McpToolBrowser.test.tsx` — tool list grouped by server, search filtering, server filter dropdown, skill chips
- `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx` — passthrough badge displayed next to session name; passthrough session selectable; one-session-per-server toggle not shown for passthrough

### E2E
- `e2e/tests/mcp-hub.spec.ts` — full McpSessionManager CRUD flow (mocked), Tool Repository tab with tool grouping and search (mocked), parent table refresh after session operations; `test.describe('Real Backend Integration - MCP Sessions')` — real session creation, verifies `identity_binding`/`credential_config` returned, confirms `encrypted_credentials` absent
- `e2e/tests/agent-a2a-communication.spec.ts` — MCP server slug validation coverage (`mcp server registration blocks invalid slug values`)
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering per page
- `e2e/tests/passthrough-sessions.spec.ts` — mocked suite: admin creates passthrough session via UI, chip displayed, tool test dialog shows identity picker, API contract validated; `test.describe('Real Backend Integration')` suite: backend health check, unauthenticated tool test returns correct status, passthrough+credentials rejected by real backend
