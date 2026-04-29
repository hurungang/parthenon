# MCP Hub Test Plan

## What to Test
- MCP server registration
- Slug uniqueness enforcement
- Tool sync and removal
- Session creation and identity binding
- Proxy call routing

## Critical Scenarios
- Admin registers MCP server and tools are synced
- MCP session with identity binding proxies call using bound identity

## Edge Cases
- Duplicate slug registration
- Partial tool sync (server partially responds)
- Tool removed between syncs

## Test File References
- `backend/tests/unit/test_mcp_hub.py`
- `backend/tests/unit/test_mcp_proxy.py`
- `backend/tests/unit/test_mcp_session.py`
- `backend/tests/unit/test_credential_vault.py`
- `e2e/tests/mcp-hub.spec.ts`
