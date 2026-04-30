# MCP Hub Test Plan

## What to Test
- MCP server registration
- Slug uniqueness enforcement
- Tool sync and removal
- Session creation and identity binding
- Proxy call routing
- Permission enforcement on all MCP server endpoints (`mcp_server:read`, `mcp_server:create`, `mcp_server:update`, `mcp_server:delete`)
- 403 structured error responses with resource type, action, and resource ID
- Permission-denied UI rendering: snackbar on 403 from MCP server delete includes resource ID context

## Critical Scenarios
- Admin registers MCP server and tools are synced
- MCP session with identity binding proxies call using bound identity
- User without `mcp_server:read` receives 403 on `GET /api/v1/mcp/servers`; UI shows permission-denied snackbar
- User without `mcp_server:create` receives 403 on `POST /api/v1/mcp/servers`; snackbar pre-filled with resource type and action
- 403 on MCP server delete includes resource ID in snackbar context
- User with correct permissions completes full MCP server CRUD flow

## Edge Cases
- Duplicate slug registration
- Partial tool sync (server partially responds)
- Tool removed between syncs
- Permission revoked between tool sync and proxy call

## Test File References
- `backend/tests/unit/test_mcp_hub.py`
- `backend/tests/unit/test_mcp_proxy.py`
- `backend/tests/unit/test_mcp_session.py`
- `backend/tests/unit/test_credential_vault.py`
- `frontend/src/__tests__/McpHubPage.test.tsx`
- `e2e/tests/mcp-hub.spec.ts`
- `e2e/tests/access-control.spec.ts` — `403 on MCP server delete triggers snackbar with resource ID context`
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering per page
