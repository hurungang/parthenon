# Test Plan: passthrough-sessions

**Change**: `passthrough-sessions`
**Date**: 2026-05-12
**Status**: In Progress — `has_db_changes: true`

---

## 1. Test Strategy

This change introduces a new `passthrough` enum value to `McpSessionAuthType`, extends the MCP proxy engine to forward agent JWTs instead of decrypting stored credentials, updates three frontend components (Session Manager, Tool Test Dialog, Role Assignment Dialog), and adds a new `raw_token` surface to the auth middleware. All four test layers must pass before marking this change implemented.

### Test Layers

| Layer | Framework | Location | Purpose |
|-------|-----------|----------|---------|
| Backend unit | pytest | `backend/tests/unit/` | Middleware token storage, proxy auth header logic, runtime dispatcher passthrough path |
| Backend integration | pytest + real PostgreSQL | `backend/tests/integration/` | Session creation lifecycle, tool test endpoint, schema constraint verification |
| Frontend component | Vitest | `frontend/src/__tests__/` | Credential field hiding, passthrough chip, agent identity picker, role dialog badge |
| E2E mocked | Playwright | `e2e/tests/` | Full UI flows with `page.route()` mocks for speed |
| E2E real backend | Playwright | `e2e/tests/` | At least one suite hitting real backend — catches migration issues |

### Database Change Requirements (CRITICAL)

This change has `has_db_changes: true` (new `passthrough` enum value added to `mcp_session_auth_type_enum`). The following rules apply without exception:

- Backend integration test fixture must run `alembic upgrade head` before any test executes
- Integration tests must verify the enum extension took effect by confirming a session with `auth_type = 'passthrough'` can be persisted and retrieved from the real database
- Include negative tests for the credential validation constraint (creating a passthrough session with credentials must be rejected)
- At least one E2E suite must be labeled `Real Backend Integration` and run without `page.route()` mocks
- Pre-run checklist: verify `alembic current` shows the new migration ID before executing any test

---

## 2. Coverage Areas

### Auth Middleware — Raw Token Storage
- `JWTAuthMiddleware.dispatch()` stores the raw bearer token on `request.state.raw_token` immediately after extraction
- `raw_token` is accessible downstream in API endpoints without any re-parsing
- `raw_token` is absent (`None` or unset) when no `Authorization` header is present

### MCP Proxy Engine — Passthrough Auth Header Logic
- `_build_auth_headers()` injects `agent_jwt` as `Authorization: Bearer <jwt>` for passthrough sessions and skips credential decryption entirely
- `_build_auth_headers()` raises `McpProxyError` when `auth_type` is passthrough but `agent_jwt` is `None` or empty
- `_resolve_session()` accepts passthrough sessions that have no `encrypted_credentials` (no validation failure)
- Non-passthrough sessions continue to use the existing credential decryption path unchanged

### Session Management — Passthrough Lifecycle
- Creating a passthrough session with `auth_type: "passthrough"` and no credentials: session is persisted with `is_active = True` immediately
- Creating a passthrough session with credentials supplied: rejected with HTTP 422
- Connection test result for a passthrough session is an immediate success (no live HTTP call to MCP server)
- Passthrough session appears in the session list with correct `auth_type` value returned from the API
- Existing non-passthrough session creation and update flows are unaffected

### Tool Test Endpoint — Passthrough Branch
- Authenticated caller testing a passthrough-type tool: `request.state.raw_token` is extracted and forwarded to `proxy.call_tool()` as `agent_jwt`
- Unauthenticated caller testing a passthrough tool: returns HTTP 400 with clear error message
- Non-passthrough tool test with `session_id` absent: returns HTTP 422 (standard schema validation)
- `agent_subject` field accepted in request body and treated as informational only (not used for auth)

### Agent Runtime Dispatcher — Passthrough Path
- `_load_role_mcp_session_map()` includes passthrough sessions so tool dispatch does not fail with "no session assigned"
- `_execute_mcp_tool()` detects passthrough session, retrieves agent identity JWT from runtime context, passes it to `proxy.call_tool()` as `agent_jwt`
- Runtime error path: when agent identity token is unavailable for a passthrough session, returns a structured error dict instead of crashing the loop

### Frontend — Session Manager
- Passthrough option present in the auth type selector
- When `auth_type === 'passthrough'` is selected: all credential input fields are hidden and an informational alert is rendered
- Submit payload when `auth_type === 'passthrough'`: `credentials` is omitted entirely
- Passthrough sessions displayed with a "Passthrough" chip badge in the session table's auth type column
- Switching from passthrough to another auth type re-shows credential fields without page reload
- Switching from a credential auth type to passthrough hides credential fields without page reload

### Frontend — Tool Test Dialog
- For a server whose active session has `auth_type === 'passthrough'`: session picker is replaced by an agent identity picker
- Agent identity list is populated from the agents API
- Submit payload when passthrough: includes `session_id` of the passthrough session and `agent_subject` of the selected identity
- For a server with a non-passthrough session: existing session picker renders as before

### Frontend — Role Assignment Dialog
- Passthrough sessions displayed with a "Passthrough" chip badge next to their name in the session list
- Passthrough sessions are selectable for role assignment
- The one-session-per-server toggle constraint UI is not shown for passthrough sessions

---

## 3. Critical Scenarios

### Middleware Token Storage
- WHEN a valid JWT bearer token is present in the request → THEN `request.state.raw_token` contains the raw token string
- WHEN no `Authorization` header is present → THEN `request.state.raw_token` is not set (or is `None`)

### Passthrough Auth Header Building
- WHEN `_build_auth_headers()` is called with a passthrough session and a non-empty `agent_jwt` → THEN the returned headers contain `Authorization: Bearer <agent_jwt>` and the credential vault is never accessed
- WHEN `_build_auth_headers()` is called with a passthrough session and `agent_jwt=None` → THEN `McpProxyError` is raised with a descriptive message
- WHEN `_build_auth_headers()` is called with a non-passthrough session → THEN existing credential decryption logic executes unchanged

### Session Creation — Passthrough
- WHEN a passthrough session is created with no credentials → THEN response contains `is_active: true`, `credential_config: null`, and `connection_test.success: true`
- WHEN a passthrough session is created with credentials in the request body → THEN HTTP 422 is returned with a validation error identifying the credentials field

### Session Creation — Schema Verification (Integration)
- WHEN `alembic upgrade head` is applied → THEN inserting a row with `auth_type = 'passthrough'` into `mcp_sessions` succeeds without database error
- WHEN querying `information_schema` for the enum values → THEN `'passthrough'` is present in the `mcp_session_auth_type_enum` type

### Tool Test — Passthrough Branch
- WHEN an authenticated user POSTs to the tool test endpoint with a passthrough session → THEN the proxy receives the caller's JWT as `agent_jwt` and returns the tool result
- WHEN an unauthenticated caller POSTs to the tool test endpoint with a passthrough session → THEN HTTP 400 is returned with `"Passthrough tool test requires an authenticated caller"`

### Runtime Dispatch
- WHEN an agent session is executing and the resolved session has `auth_type == passthrough` → THEN `proxy.call_tool()` is invoked with the agent identity JWT and not with any stored credentials
- WHEN the agent identity token is unavailable at runtime → THEN the tool call returns an error dict and the agent loop continues without crashing

### Frontend Credential Field Hiding
- WHEN the user selects "passthrough" in the session form → THEN credential fields disappear and an informational alert appears in their place
- WHEN the user switches back to a credential-based auth type → THEN credential fields reappear

### Frontend Tool Test Identity Picker
- WHEN the tool test dialog opens for a passthrough server → THEN no session picker is shown; an agent identity picker is shown instead
- WHEN the user selects an agent identity and submits → THEN the request payload contains `session_id` (of the passthrough session) and `agent_subject`

---

## 4. Edge Cases & Risks

| Risk | Scenario | Expected Behaviour |
|------|----------|--------------------|
| Passthrough session in role but no JWT at runtime | Agent identity token expired or unavailable | Structured error returned; agent loop continues |
| MCP server rejects forwarded JWT | Server returns 401/403 on the forwarded JWT | `McpProxyError` raised; tool test reports failure with HTTP status |
| Non-passthrough session with absent `session_id` | Client omits `session_id` for non-passthrough tool test | HTTP 422 from Pydantic schema validation |
| Passthrough session created alongside credential session for same server | Admin creates both types for one server | Both created; role assignment UI shows both; no conflict |
| `agent_subject` field used as auth | Malicious client supplies arbitrary `agent_subject` | Ignored server-side; only `request.state.raw_token` used for auth |
| Migration not applied before running tests | `alembic upgrade head` not run | Passthrough session insert fails with PostgreSQL invalid input value for enum |
| Frontend auth type switch mid-form | User toggles between passthrough and other types | Form state resets cleanly; no stale credential data submitted |
| Passthrough chip missing in session table | Existing sessions loaded before UI update | `auth_type` field present in API response and rendered as chip |

---

## 5. Acceptance Criteria Mapping

| # | PRD Acceptance Criterion | Test Cases |
|---|--------------------------|------------|
| AC-1 | Administrators can configure an MCP server to use a passthrough session type (no explicit session selection required) | Backend integration: passthrough session creation; Frontend component: session form passthrough option and credential hiding |
| AC-2 | When a passthrough session is configured, the Communication Hub automatically forwards the executing agent's identity to the MCP server | Backend unit: `_build_auth_headers()` passthrough branch; Backend integration: tool test passthrough; Runtime dispatcher unit test |
| AC-3 | Tool registry test feature allows selection of agent identity for passthrough-type MCP servers (no session selection shown) | Frontend component: `TestMcpToolDialog` passthrough branch renders identity picker |
| AC-4 | End-to-end flow: agent identity is correctly propagated and recognized by the MCP server | E2E Real Backend Integration test: authenticated passthrough tool test against mcp-demo-app |
| AC-5 | UI clearly distinguishes passthrough session type from traditional session selection | Frontend component: passthrough chip in session table; passthrough badge in role assignment dialog |
| AC-6 | Error handling: clear feedback if passthrough is misconfigured or unsupported | Backend unit: `McpProxyError` on missing JWT; Backend integration: HTTP 400 for unauthenticated tool test; Frontend component: error state rendering |
| AC-7 | No regression in existing session-based workflows | Backend unit/integration: non-passthrough path tests unchanged; E2E: existing session workflow suite passes |

---

## 6. Test Data Requirements

- A registered MCP server (e.g., pointing at mcp-demo-app) with no sessions initially assigned
- A passthrough session created for that server via the API or UI
- An authenticated user with a valid Keycloak JWT (for passthrough tool test scenarios)
- At least one agent identity registered in the system (for tool test identity picker scenarios)
- A role with the passthrough session assigned (for runtime dispatcher tests)
- A credential-based session (e.g., `api_key`) on a separate server to verify non-passthrough regression coverage

**Test data naming**: use `passthrough-test-${timestamp}` prefixes for sessions and server registrations created during tests to allow reliable cleanup in `afterEach` hooks.

---

## 7. Test Environments

| Requirement | Detail |
|-------------|--------|
| Database migration applied | `alembic upgrade head` must be confirmed before running integration or E2E tests; verify with `alembic current` |
| Real PostgreSQL | Backend integration tests must use the real local database, not in-memory mocks |
| mcp-demo-app running | E2E real-backend tests require mcp-demo-app available (JWT-accepting endpoint) |
| Keycloak running | Valid JWTs needed for passthrough tool test and E2E authentication flows |
| Backend API server | Running on `http://localhost:8000` |
| Frontend dev server | Running on `http://localhost:5173` (or configured port) |

---

## 8. Test File References

| Test File | Layer | Covers | Status |
|-----------|-------|--------|--------|
| `backend/tests/unit/test_auth_middleware.py` | Backend unit | `request.state.raw_token` populated after valid JWT; absent without Authorization header | ✅ Implemented |
| `backend/tests/unit/test_mcp_proxy.py` | Backend unit | `_build_auth_headers()` passthrough success; `McpProxyError` on missing JWT; `_resolve_session()` accepts passthrough with no credentials | ✅ Implemented |
| `backend/tests/unit/test_agent_runtime_executor.py` | Backend unit | `_execute_mcp_tool()` passes `agent_jwt` to proxy for passthrough sessions | ✅ Implemented |
| `backend/tests/integration/test_mcp_hub.py` | Backend integration | Passthrough session creation (success + credential rejection); tool test (authenticated success + unauthenticated 400); enum schema verification; PostgreSQL-specific information_schema probe (skipped on SQLite) | ✅ Created (Tasks 4.4, 5.4) |
| `frontend/src/__tests__/McpSessionManager.test.tsx` | Frontend component | Credential fields hidden for passthrough; informational alert rendered; submit payload omits credentials; passthrough chip in table | ✅ Implemented |
| `frontend/src/__tests__/TestMcpToolDialog.test.tsx` | Frontend component | Identity picker rendered for passthrough server; session picker absent; correct payload sent on submit | ✅ Implemented |
| `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx` | Frontend component | Passthrough badge displayed; session selectable; toggle constraint not shown for passthrough | ✅ Implemented |
| `e2e/tests/passthrough-sessions.spec.ts` | E2E (mocked + real backend) | Mocked suite: admin creates passthrough session via UI; chip displayed; tool test dialog shows identity picker; API contract validated. Real Backend Integration suite: backend health check; unauthenticated tool test returns correct status; passthrough+credentials rejected by real backend | ✅ Created |
