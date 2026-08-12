# Implementation Plan: passthrough-sessions

## Overview

Extend the MCP Hub with a `passthrough` session auth type that forwards the executing agent's JWT directly to the MCP server instead of decrypting stored credentials. Changes touch the backend model layer, proxy engine, session and tool-test endpoints, agent runtime dispatcher, and the session manager, tool test dialog, and role assignment UI in the frontend.

---

## Task Checklist

- [x] 1.1 — Add `passthrough` to `McpSessionAuthType` enum
- [x] 1.2 — Generate Alembic migration for passthrough enum value
- [x] 1.3 — Verify migration runs cleanly
- [x] 2.1 — Store raw token on `request.state.raw_token` in middleware
- [x] 2.2 — Unit test for raw token storage
- [x] 3.1 — Add `agent_jwt` parameter to `McpProxyEngine.call_tool()`
- [x] 3.2 — Add passthrough branch to `_build_auth_headers()`
- [x] 3.3 — Raise error if passthrough session has no JWT
- [x] 3.4 — Update `_resolve_session()` for passthrough sessions
- [x] 3.5 — Unit tests for passthrough auth header building
- [x] 4.1 — Update `McpSessionCreate` schema validation
- [x] 4.2 — Skip credential encryption for passthrough sessions
- [x] 4.3 — Skip connection test for passthrough sessions
- [x] 4.4 — Integration tests for passthrough session creation
- [x] 5.1 — Make `session_id` optional in `TestToolRequest` schema
- [x] 5.2 — Update `test_mcp_tool` endpoint for passthrough
- [x] 5.3 — Add validation for passthrough tool test
- [x] 5.4 — Integration tests for tool test passthrough mode
- [x] 6.1 — Include passthrough sessions in role session map
- [x] 6.2 — Update `_execute_mcp_tool()` for passthrough
- [x] 6.3 — Unit test for runtime executor passthrough path
- [x] 7.1 — Add `'passthrough'` to frontend `McpSessionAuthType` type
- [x] 8.1 — Add `'passthrough'` to `AUTH_TYPES` constant
- [x] 8.2 — Note credential fields unused for passthrough
- [x] 8.3 — Hide credential fields when passthrough selected
- [x] 8.4 — Omit credentials in submit for passthrough
- [x] 8.5 — Display passthrough chip in session table
- [x] 8.6 — Unit tests for passthrough form state
- [x] 9.1 — Extend `McpSession` interface with `auth_type`
- [x] 9.2 — Derive `isPassthrough` boolean in tool test dialog
- [x] 9.3 — Add agent identity fetch for passthrough
- [x] 9.4 — Branch session selection UI for passthrough
- [x] 9.5 — Update `handleTest` for passthrough payload
- [x] 9.6 — Unit tests for tool test passthrough branch
- [x] 10.1 — Extend `McpSessionInfo` interface with `auth_type`
- [x] 10.2 — Display passthrough chip in role assignment dialog
- [x] 10.3 — Unit test for role assignment passthrough badge

---

## Implementation Phases

### Phase 1: Backend — Data Model & Migration

**Tasks:**
- [x] Task 1.1: Add `passthrough = "passthrough"` to `McpSessionAuthType` enum (file: `backend/app/db/models/mcp_hub.py`)
- [x] Task 1.2: Generate Alembic migration that runs `ALTER TYPE mcp_session_auth_type_enum ADD VALUE IF NOT EXISTS 'passthrough'` outside a transaction (file: `backend/alembic/versions/<revision>_add_passthrough_to_mcp_session_auth_type.py`)
- [x] Task 1.3: Verify migration runs cleanly with `alembic upgrade head` and confirm `alembic current` reflects the new revision

### Phase 2: Backend — Auth Middleware (Raw Token Access)

**Tasks:**
- [x] Task 2.1: In `JWTAuthMiddleware.dispatch()`, store the extracted bearer token string on `request.state.raw_token` immediately after extraction, before claims validation (file: `backend/app/middleware/auth.py`)
- [x] Task 2.2: Write unit test confirming `request.state.raw_token` is populated after middleware processes a valid JWT (file: `backend/tests/unit/test_auth_middleware.py`)

### Phase 3: Backend — MCP Proxy Engine

**Tasks:**
- [x] Task 3.1: Add optional `agent_jwt: str | None = None` parameter to `McpProxyEngine.call_tool()` signature (file: `backend/app/services/mcp/proxy.py`)
- [x] Task 3.2: Add `passthrough` branch to `_build_auth_headers()`: when `session.auth_type == McpSessionAuthType.passthrough`, inject `agent_jwt` as `Authorization: Bearer <jwt>` and skip credential decryption entirely (file: `backend/app/services/mcp/proxy.py`)
- [x] Task 3.3: Raise `McpProxyError` in `_build_auth_headers()` if `auth_type` is passthrough but `agent_jwt` is `None` or empty (file: `backend/app/services/mcp/proxy.py`)
- [x] Task 3.4: Update `_resolve_session()` so it does not require `encrypted_credentials` to be present for passthrough sessions (passthrough sessions are valid even with no stored credentials) (file: `backend/app/services/mcp/proxy.py`)
- [x] Task 3.5: Write unit tests for passthrough auth header building — success case, and missing JWT error case (file: `backend/tests/unit/test_mcp_proxy.py`)

### Phase 4: Backend — Session Management (Create / Update)

**Tasks:**
- [x] Task 4.1: Update `McpSessionCreate` Pydantic schema — add validation that `credentials` must be `None` when `auth_type == passthrough` (file: `backend/app/schemas/mcp_hub.py`)
- [x] Task 4.2: Update `create_mcp_session` endpoint — for passthrough auth type: skip credential encryption, skip connection test, and set `is_active = True` directly (file: `backend/app/api/v1/mcp_hub.py`)
- [x] Task 4.3: Update `mcp_session_test.py` `test_mcp_session_connection()` — return an immediate success result for passthrough sessions without attempting an authenticated HTTP call (file: `backend/app/services/mcp_session_test.py`)
- [x] Task 4.4: Write integration tests for passthrough session creation: verify session is created with `is_active=True`, no encrypted_credentials stored, and response includes a passing connection test (file: `backend/tests/integration/test_mcp_hub.py`)

### Phase 5: Backend — Tool Test Endpoint (Passthrough Branch)

**Tasks:**
- [x] Task 5.1: Update `TestToolRequest` schema — make `session_id` optional (`uuid.UUID | None = None`), add `agent_subject: str | None = None` field for passthrough identity selection (file: `backend/app/schemas/mcp_hub.py`)
- [x] Task 5.2: Update `test_mcp_tool` endpoint — detect passthrough session type from the resolved session; extract `request.state.raw_token` and pass as `agent_jwt` to `proxy.call_tool()`; require `session_id` for non-passthrough calls (file: `backend/app/api/v1/mcp_hub.py`)
- [x] Task 5.3: Add validation in `test_mcp_tool`: return HTTP 400 if `session_id` is absent and the resolved session is not passthrough type; return HTTP 400 if passthrough session requires a JWT but caller is unauthenticated (file: `backend/app/api/v1/mcp_hub.py`)
- [x] Task 5.4: Write integration tests for the tool test endpoint in passthrough mode: authenticated call succeeds; unauthenticated call returns 400 (file: `backend/tests/integration/test_mcp_hub.py`)

### Phase 6: Backend — Agent Runtime Dispatcher

**Tasks:**
- [x] Task 6.1: Update `_load_role_mcp_session_map()` in `AgentRuntimeExecutor` — passthrough sessions must be included in the map so tool dispatch does not fail on "no session assigned" (file: `backend/app/services/agents/runtime_executor.py`)
- [x] Task 6.2: Update `_execute_mcp_tool()` — detect when the resolved session has `auth_type == passthrough`; retrieve the agent's current identity JWT from the runtime context (e.g., `AgentJob.identity_token` or via OIDC token refresh); pass it as `agent_jwt` to `proxy.call_tool()` (file: `backend/app/services/agents/runtime_executor.py`)
- [x] Task 6.3: Write unit test for `_execute_mcp_tool()` passthrough path: verify proxy is called with `agent_jwt` and `session_id` when session is passthrough (file: `backend/tests/unit/test_agent_runtime_executor.py`)

### Phase 7: Frontend — Types

**Tasks:**
- [x] Task 7.1: Add `'passthrough'` to the `McpSessionAuthType` union type (file: `frontend/src/types/index.ts`)

### Phase 8: Frontend — Session Manager UI

**Tasks:**
- [x] Task 8.1: Add `'passthrough'` to the `AUTH_TYPES` constant array (file: `frontend/src/pages/mcp/McpSessionManager.tsx`)
- [x] Task 8.2: Update `SessionForm` interface — no new fields needed; credential fields are already optional; note them as unused when `auth_type === 'passthrough'` (file: `frontend/src/pages/mcp/McpSessionManager.tsx`)
- [x] Task 8.3: Update credential form render: when `auth_type === 'passthrough'`, hide all credential input fields and render an informational alert ("Passthrough sessions forward the agent's identity automatically — no credentials are stored.") (file: `frontend/src/pages/mcp/McpSessionManager.tsx`)
- [x] Task 8.4: Update create/edit submit handler: omit `credentials` payload entirely when `auth_type === 'passthrough'` (file: `frontend/src/pages/mcp/McpSessionManager.tsx`)
- [x] Task 8.5: Update session table: display a "Passthrough" `Chip` badge in the auth type column for passthrough sessions (file: `frontend/src/pages/mcp/McpSessionManager.tsx`)
- [x] Task 8.6: Write unit tests for passthrough form state: credential fields hidden, submit omits credentials (file: `frontend/src/__tests__/McpSessionManager.test.tsx`)

### Phase 9: Frontend — Tool Test Dialog

**Tasks:**
- [x] Task 9.1: Extend the local `McpSession` interface in `TestMcpToolDialog` to include `auth_type: McpSessionAuthType` (file: `frontend/src/pages/mcp/TestMcpToolDialog.tsx`)
- [x] Task 9.2: Derive a `isPassthrough` boolean from the fetched sessions list: `true` when the server's only active session has `auth_type === 'passthrough'` (file: `frontend/src/pages/mcp/TestMcpToolDialog.tsx`)
- [x] Task 9.3: Add agent identity fetch: when `isPassthrough`, query `/agents/identities` to populate the agent identity picker (file: `frontend/src/pages/mcp/TestMcpToolDialog.tsx`)
- [x] Task 9.4: Branch the session selection UI: when `isPassthrough`, replace the session `Select` with an agent identity `Select` labeled "Execute as agent identity"; otherwise show the existing session picker (file: `frontend/src/pages/mcp/TestMcpToolDialog.tsx`)
- [x] Task 9.5: Update `handleTest`: when `isPassthrough`, post `{ session_id: passthroughSession.id, agent_subject: selectedAgentSubject, tool_input: inputData }` instead of requiring a manually selected session (file: `frontend/src/pages/mcp/TestMcpToolDialog.tsx`)
- [x] Task 9.6: Write unit tests for passthrough branch: identity picker rendered, correct payload sent (file: `frontend/src/__tests__/TestMcpToolDialog.test.tsx`)

### Phase 10: Frontend — Role Assignment Dialog

**Tasks:**
- [x] Task 10.1: Extend the `McpSessionInfo` interface in `AssignMcpSessionsToRoleDialog` to include `auth_type: string` (file: `frontend/src/pages/agents/AssignMcpSessionsToRoleDialog.tsx`)
- [x] Task 10.2: Update session list rendering: display a "Passthrough" `Chip` next to passthrough session names and remove the "one-session-per-server" toggle constraint UI for passthrough sessions (passthrough sessions can coexist with credential sessions per server) (file: `frontend/src/pages/agents/AssignMcpSessionsToRoleDialog.tsx`)
- [x] Task 10.3: Write unit test for role assignment dialog showing passthrough badge and correct selection behavior (file: `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx`)
