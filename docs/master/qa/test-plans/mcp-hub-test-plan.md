# MCP Hub Test Plan

## What to Test

### MCP Server Management
- MCP server registration
- Slug uniqueness enforcement
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

## Edge Cases
- Duplicate slug registration
- Partial tool sync (server partially responds)
- Tool removed between syncs
- Permission revoked between tool sync and proxy call
- Tool with no skill bindings returns empty `skills` array (not 404)
- Search term in McpToolBrowser matches display name and slug formats

## Known Limitations
- Full Vitest component tests for McpSessionManager and McpToolBrowser are implemented; McpHubPage tab navigation is also covered.

## Test File References

### Backend
- `backend/tests/unit/test_mcp_hub.py` — server registration, slug uniqueness, tool sync
- `backend/tests/unit/test_mcp_proxy.py` — proxy call routing and identity binding
- `backend/tests/unit/test_mcp_session.py` — session unit logic
- `backend/tests/unit/test_credential_vault.py` — credential encryption/decryption
- `backend/tests/api/v1/test_mcp_hub_api.py` — `GET /mcp/tools`, `GET /mcp/tools/{id}/skills`, session create/update/read with `identity_binding` and `credential_config`, credential exclusion from responses
- `backend/tests/integration/test_enhance_mcp_hub_skills_sops_db.py` — schema migration verification (`identity_binding`, `credential_config` columns exist), credential-not-returned integration path, real-database constraint enforcement

### Frontend
- `frontend/src/__tests__/McpHubPage.test.tsx` — tab navigation (Servers / Tool Repository), session dialog trigger from server row
- `frontend/src/__tests__/McpSessionManager.test.tsx` — session CRUD rendering, `identity_binding` and `credential_config` inputs, write-only credential field, dialog error display
- `frontend/src/__tests__/McpToolBrowser.test.tsx` — tool list grouped by server, search filtering, server filter dropdown, skill chips

### E2E
- `e2e/tests/mcp-hub.spec.ts` — full McpSessionManager CRUD flow (mocked), Tool Repository tab with tool grouping and search (mocked), parent table refresh after session operations; `test.describe('Real Backend Integration - MCP Sessions')` — real session creation, verifies `identity_binding`/`credential_config` returned, confirms `encrypted_credentials` absent
- `e2e/tests/access-control.spec.ts` — `403 on MCP server delete triggers snackbar with resource ID context`
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering per page
