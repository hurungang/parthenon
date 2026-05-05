# Test Plan: Agent Runtime with Gateway

**Change**: `implement-agent-runtime-with-gateway`
**Date**: 2026-05-01
**Status**: In Progress — `has_db_changes: true`

---

## 1. Test Strategy

This change introduces a new permission model (AgentRole), a new identity model (AgentIdentity), and an asynchronous session execution system (AgentSession) powered by **LangGraph**. All three layers — backend unit, backend integration, frontend component, and E2E — must pass before marking this change implemented.

### Test Layers

| Layer | Framework | Location | Purpose |
|-------|-----------|----------|---------|
| Backend unit | pytest | `backend/tests/unit/` | Service logic, permission resolution, state machine |
| Backend integration | pytest + real PostgreSQL | `backend/tests/integration/` | Schema constraints, session lifecycle, multi-service flows |
| Frontend component | Vitest | `frontend/src/__tests__/` | Component rendering, state transitions, dialog error handling |
| E2E mocked | Playwright | `e2e/tests/agent-runtime.spec.ts` | Full user flows with `page.route()` mocks for speed |
| E2E real backend | Playwright | `e2e/tests/agent-runtime.spec.ts` | One suite variant hitting real backend — catches migration issues |

### Database Change Requirements (CRITICAL)

This change has `has_db_changes: true`. The following rules apply without exception:

- Backend integration test fixture must run `alembic upgrade head` before any test
- Integration tests must verify actual schema properties via `information_schema` (not just service-level happy paths)
- Integration tests must include negative tests for constraint violations (e.g., deleting a role referenced by an AgentType must return 409)
- At least one E2E suite must be labeled `Real Backend Integration` and run without `page.route()` mocks
- Pre-run checklist: verify `alembic current` shows the new migration ID before executing any test

---

## 2. Coverage Areas

### Agent Role CRUD
- Create, read, update, delete `AgentRole` entities
- Assign SOP IDs and Skill IDs atomically in a single transaction
- Replace (not append) SOP/Skill assignments on update
- Reject deletion when any `AgentType` references the role (409 Conflict)
- Permission cache invalidation triggered on every write

### Agent Identity Management
- Create an `AgentIdentity` record via the OAuth sign-in flow (admin signs in to an agent user account in the agent realm; tokens stored on callback)
- Read, update, delete `AgentIdentity` entities
- Identity status transitions: `active`, `suspended`, `deprovisioned`
- Reject deletion when any `AgentType` references the identity (409 Conflict)
- OAuth `authorize` endpoint redirects to the identity provider's configured agent realm (not the user realm)
- OAuth `callback` endpoint stores encrypted access token and refresh token against the new identity record
- Duplicate sign-in for the same agent user (same subject in the agent realm) is rejected or updates the existing identity

### Realm Initialization (Bootstrap)
- `RealmManager` initializes a dedicated agent realm (e.g., `ai_agents`) in the identity provider using configuration from the bootstrap config file
- Agent realm initialization mirrors the user realm setup (client registration, default roles, redirect URIs)
- Agent realm name is configurable; tests exercise both a custom name and the default
- Bootstrap is idempotent: running it twice against an already-initialized realm does not error or duplicate resources
- If the identity provider is unavailable during bootstrap, a clear error is surfaced (not a silent failure)

### Agent Token Storage and Refresh
- Access tokens and refresh tokens are stored encrypted at rest against the `AgentIdentity` record
- `TokenRefreshService` refreshes an agent's access token before it expires (proactive refresh)
- `TokenRefreshService` handles an already-expired access token using the stored refresh token
- Refresh token rotation: after a successful refresh, the new refresh token replaces the old one in storage
- If the refresh token is also expired, the identity status is updated to `suspended` and an error is logged
- Token refresh is triggered automatically before agent session execution when the token is within the configurable expiry window

### Agent Type Configuration (Modified)
- Create and update using new schema fields: `identity_id`, `role_id`, `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema`
- `identity_id` dropdown is populated only with identities that were created via the OAuth sign-in flow (agent realm users); identities with status `suspended` or `deprovisioned` are excluded or flagged
- Removed fields (`mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`) are rejected by the API
- `AgentTypeForm` renders correct fields for each `input_type` and `output_type` combination

### Permission Resolution
- `AgentPermissionManager` resolves the full chain: `AgentRole → SOPs → Skills → MCP tools` (via join traversal)
- Direct Skill assignments on a role also contribute their MCP tools
- Merged tool list contains no duplicates
- LRU cache returns consistent results for repeated calls with the same `role_id`
- Cache invalidation removes stale entry after role update or delete

### Real-Time MCP Tool Preview
- Selecting or deselecting SOPs/Skills in `AgentRoleDialog` triggers a re-fetch of the preview tool list
- Preview fetch is debounced (300 ms)
- Preview panel shows the resolved tool list immediately on first open if role already has assignments
- Preview panel shows empty state when no SOPs or Skills are selected

### Agent Session Lifecycle
- Enqueue: `POST /api/v1/agents/sessions` returns 202 with a session ID synchronously
- List: `GET /api/v1/agents/sessions` returns only sessions belonging to the authenticated user
- Status transitions: `queued → running → completed` (happy path) and `queued → running → failed` (error path)
- `GET /api/v1/agents/sessions/{id}/result` returns 409 when session is not yet in a terminal status
- `AgentJobPage` polls every 3 seconds and stops polling on `completed` or `failed` for task-based agents
- For conversational agents, `AgentJobPage` opens a chat interface with message history; user can send messages and receive agent responses in real time
- Polling interval is cleared on component unmount

### Session Dispatch and Execution
- `SessionDispatcher` selects `queued` sessions with `SKIP LOCKED` to avoid double-dispatch
- `AgentRuntimeExecutor` uses **LangGraph** state graphs to orchestrate agent execution
- `AgentRuntimeExecutor` enforces the role's permission boundary — tool calls outside the allowed set are rejected
- Result is written via `save_result` and session status transitions to `completed`
- Unrecoverable errors transition session to `failed` and persist `error_message`

### Gateway Routing
- `LifecycleHandler` routes incoming launch requests through `AgentSessionService.enqueue` rather than direct executor invocation
- Session ID is returned synchronously from the gateway endpoint
- For conversational agents, gateway maintains bidirectional communication channel

### UI Components
- `AgentRoleListPage`: table renders all roles with SOP count and Skill count; create dialog opens from page header; edit and delete actions per row
- `AgentRoleDialog`: SOP and Skill multi-select; MCP tool preview panel debounced; edit-mode pre-populates existing assignments and loads preview on open
- `AgentIdentityListPage`: table renders all identities with identity_type chip and status chip; create/edit/delete actions
- `AgentIdentityDialog`: create/edit form; identity_type dropdown contains all three values; status dropdown; validates required fields
- `AgentSessionLaunchDialog`: input form renders fields based on `input_type` (`none`, `typed`, `conversation`)
- `AgentJobPage`: result is rendered as structured output or markdown based on `output_type`; conversational agents show chat interface with message send box and message history
- `AgentManagementPage`: "Launch" action appears per agent type row and links to `AgentJobPage`; existing agent management table and actions unaffected
- `AgentTypeForm`: new fields render (`identity_id`, `role_id`, `system_instruction`, `input_type`, `output_type`); removed fields (`mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`) are absent
- All dialogs follow the Dialog Error Handling Standard (`dialogError` state, `PermissionDeniedAlert`, cleared on open/close)

### i18n Coverage
- All new UI strings use `t()` with keys under `agents.roles.*`, `agents.identities.*`, `agents.sessions.*`, `agents.types.*`
- No hardcoded English strings in any new or modified component

### Observability
- All new service operations emit OpenTelemetry traces
- Session status transitions logged with structured fields (session ID, agent type ID, status, timing)
- LangGraph node transitions included in trace spans

---

## 3. Critical Scenarios

### Agent Role Management

- WHEN a user creates a role with no SOPs and no Skills THEN the role is saved and the MCP tool preview shows an empty list
- WHEN a user assigns two SOPs to a role THEN the MCP tool preview shows the union of all tools from those SOPs' Skills without duplicates
- WHEN a user assigns one SOP and one direct Skill THEN the preview shows tools from the SOP chain plus the direct Skill's tools, deduplicated
- WHEN a user removes all SOPs/Skills from an existing role THEN the preview clears and the save updates join records atomically
- WHEN a user attempts to delete a role that is assigned to an AgentType THEN the API returns 409 and the UI displays the error in the dialog
- WHEN a role is updated THEN the permission cache entry for that role is invalidated and the next resolution performs a fresh query
- WHEN `AgentRoleDialog` opens for an existing role (edit mode) THEN the assigned SOPs and Skills are pre-checked and the MCP tool preview loads immediately without requiring the user to change a selection
- WHEN the MCP tool preview fetch fails in `AgentRoleDialog` THEN the preview panel shows an inline error state and the Save button remains enabled (user can still save the role)
- E2E User Journey (happy path — create): Navigate to Agent Roles page → Click "Add Role" → Enter name → Check two SOPs → Verify preview tools list updates (debounced) → Click Save → Verify new role row appears in table with correct SOP count chip, without page reload
- E2E User Journey (edit with existing assignments): Click Edit on an existing role → Verify SOPs/Skills pre-checked and preview populated → Uncheck one SOP → Verify preview updates → Save → Verify table row SOP count chip updated, without page reload
- E2E User Journey (delete conflict): Click Delete on a role assigned to an AgentType → Verify dialog shows 409 error message (not silent failure)

### Agent Identity Management

- WHEN an admin initiates the OAuth sign-in flow for a new agent identity THEN the backend `authorize` endpoint redirects to the identity provider's agent realm login page (not the user realm)
- WHEN the identity provider returns a successful OAuth callback THEN the backend stores encrypted access and refresh tokens and creates the `AgentIdentity` record with status `active`
- WHEN the OAuth callback contains an error parameter THEN the backend surfaces a clear error and no `AgentIdentity` record is created
- WHEN the same agent user (same subject in the agent realm) signs in a second time THEN the system either updates the existing identity's tokens or rejects the duplicate (defined behavior is consistent)
- WHEN a user updates an identity's status to `suspended` THEN the status chip in the list reflects the change without page reload
- WHEN a user attempts to delete an identity that is referenced by an AgentType THEN the API returns 409 and the UI displays the error
- WHEN `AgentIdentityListPage` loads THEN the table shows identities created via the OAuth flow with their status chips
- WHEN `AgentIdentityDialog` opens for edit THEN the agent realm subject, auth_provider, and status are pre-populated; tokens are not displayed (masked)
- E2E User Journey (happy path — OAuth sign-in): Navigate to Agent Identities page → Click "Add Identity (Sign In)" → Browser redirects to agent realm login → (mocked callback) Callback returns code → Verify new row appears in table with `active` status chip, without page reload
- E2E User Journey (status update): Click Edit on existing identity → Change status to `suspended` → Save → Verify status chip in table updates to `suspended` without page reload
- E2E User Journey (delete conflict): Click Delete on an identity referenced by an AgentType → Verify dialog shows 409 error (not a silent failure)

### Realm Bootstrap

- WHEN bootstrap runs against an unconfigured identity provider THEN `RealmManager` creates the agent realm with the name from the bootstrap config
- WHEN the agent realm name in the bootstrap config is `ai_agents` THEN the initialized realm is named `ai_agents` in the identity provider
- WHEN bootstrap runs against an identity provider where the agent realm already exists THEN `RealmManager` completes without error and does not duplicate realm resources
- WHEN the identity provider is unreachable during bootstrap THEN `RealmManager` raises a structured error (not an unhandled exception) with the realm name and provider URL
- WHEN bootstrap completes successfully THEN both the user realm and the agent realm are present in the identity provider
- E2E / Integration: After bootstrap, verify a `/realms/<agent_realm>/.well-known/openid-configuration` endpoint is reachable on the identity provider (Keycloak)

### Agent Token Refresh

- WHEN an agent identity's access token is within the configurable expiry window at session launch time THEN `TokenRefreshService` proactively refreshes it before the session starts
- WHEN an agent identity's access token is already expired at session launch time THEN `TokenRefreshService` uses the stored refresh token to obtain a new access token
- WHEN a token refresh succeeds THEN the new access token and rotated refresh token are stored encrypted, replacing the previous values
- WHEN the refresh token is expired or invalid THEN `TokenRefreshService` marks the identity as `suspended`, logs a structured error, and the session does not start (returns a clear error to the caller)
- WHEN token refresh is triggered concurrently for the same identity (e.g., two sessions launching simultaneously) THEN only one refresh is performed (no duplicate refresh race)
- WHEN `AgentRuntimeExecutor` performs a mid-session tool call and the current access token has expired THEN the executor calls `TokenRefreshService` inline before retrying the tool call

### Agent Type Configuration

- WHEN a user creates an agent type with `input_type = none` THEN no input schema fields are rendered
- WHEN a user creates an agent type with `input_type = typed` THEN input schema builder fields are rendered
- WHEN a user creates an agent type with `input_type = conversation` THEN a conversation mode indicator is shown
- WHEN a user saves an agent type with a valid `identity_id` and `role_id` THEN the type is linked to the identity and role records

### Agent Session Launch and Tracking

- WHEN a user clicks "Launch" on an AgentType row in `AgentManagementPage` THEN `AgentJobLaunchDialog` opens with the correct input form for that agent's `input_type`
- WHEN `input_type` is `none` THEN the launch dialog shows no input fields and only a Confirm/Launch button
- WHEN `input_type` is `typed` THEN the launch dialog renders input fields driven by `input_schema`
- WHEN `input_type` is `conversation` THEN the launch dialog opens a chat input (not a structured form)
- WHEN a user submits the launch dialog with valid input THEN the backend returns 202 with a session ID and the UI navigates to `AgentJobPage` for that session ID
- WHEN the session status is `queued` THEN `AgentJobPage` shows a pending indicator and polls every 3 seconds
- WHEN the session transitions to `running` THEN the polling continues and status updates without page reload
- WHEN the session reaches `completed` THEN polling stops, result is fetched, and output is rendered per `output_type`
- WHEN `output_type` is `typed` THEN result is rendered as a structured JSON/table view
- WHEN `output_type` is `markdown` THEN result is rendered as formatted markdown text
- WHEN the session reaches `failed` THEN polling stops and the error message is displayed
- WHEN the `AgentJobPage` component unmounts before session completes THEN the polling interval is cleared and no further requests are made
- WHEN `GET /api/v1/agents/sessions/{id}/result` is called on an in-progress session THEN the API returns 409
- WHEN a conversational agent session is launched THEN `AgentJobPage` displays a chat interface (not a result panel); user can type a message and submit it; agent response appears in the thread
- E2E User Journey (task agent, happy path): Navigate to Agent Management → Click Launch on a task agent → Launch dialog opens with typed input form → Fill in fields → Submit → Navigate to AgentJobPage → See `queued` status → (mock) Status advances to `completed` → Result rendered per output_type → Verify polling has stopped
- E2E User Journey (conversational agent): Navigate to Agent Management → Click Launch on a conversational agent → Launch dialog opens with chat input → Submit initial message → Navigate to AgentJobPage chat view → Verify chat interface rendered with message history

### Gateway Routing

- WHEN a launch request arrives at the gateway endpoint THEN `LifecycleHandler` calls `AgentSessionService.enqueue` (not the executor directly) and returns the session ID synchronously
- WHEN a conversational agent is launched via the gateway THEN `LifecycleHandler` establishes a bidirectional WebSocket channel for the session
- WHEN the gateway receives a launch request for a non-existent AgentType ID THEN it returns 404 (not 500)
- WHEN the gateway receives a launch request from a user without permission THEN it returns 403

### Permission Enforcement

- WHEN an agent attempts a tool call not in its role's allowed tool set THEN `AgentRuntimeExecutor` rejects the call and logs a violation
- WHEN a role has no SOPs and no direct Skills THEN the allowed tool set is empty and all tool calls are rejected
- WHEN the permission cache is populated for a role and then the role is updated THEN the next resolution bypasses the cache and recomputes
- WHEN a role has a circular SOP dependency (SOP A → SOP B → SOP A) THEN `AgentPermissionManager` detects the cycle and resolves a finite tool set without infinite recursion

### Error Handling

- WHEN any dialog API call fails with 403 THEN `PermissionDeniedAlert` is displayed as the first child of `DialogContent`
- WHEN any dialog is closed and reopened THEN `dialogError` is cleared and no stale error is shown
- WHEN the `AgentRoleDialog` MCP preview fetch fails THEN the preview shows an error state and the save action remains enabled

---

## 4. Edge Cases & Risks

### Permission Calculation
- **Circular SOP dependencies**: if SOP A depends on SOP B which depends on SOP A, the join traversal could loop. The `AgentPermissionManager` must detect and break cycles.
- **Large tool sets**: a role assigned many SOPs could resolve hundreds of tools. Verify the cache serialization and the API response remain performant.
- **Stale cache after delete**: if a role is deleted and recreated with the same ID (unlikely but possible via restore), the LRU cache must be invalidated correctly.

### Session Queue
- **Stuck sessions**: a `running` session whose executor crashes never transitions to `failed`. A recovery mechanism or timeout check is needed; tests should verify this does not silently hang.
- **Double dispatch**: `SKIP LOCKED` prevents this in the steady state, but tests must verify a session is only dispatched once even under concurrent dispatcher instances.
- **Queue overflow**: if session submission rate exceeds dispatch capacity, `queued` sessions accumulate. Tests should verify the system degrades gracefully (no data loss, no 500 errors on enqueue).

### OAuth / Identity
- **Realm misconfiguration**: if the agent realm name in bootstrap config does not match the identity provider's configured realm, OAuth callbacks will fail with an unknown issuer. Tests must verify `RealmManager` validates the realm is reachable before completing bootstrap.
- **OAuth state parameter replay**: the `authorize` → `callback` flow must use a one-time CSRF state token. A replayed or missing state must be rejected with 400, not silently accepted.
- **OAuth token expiry during session execution**: the executor must refresh the agent's token mid-session. Test that an expired token triggers `TokenRefreshService` inline rather than a failed tool call.
- **Refresh token expiry with concurrent sessions**: if the refresh token expires while multiple sessions are queued, all sessions for that identity should fail gracefully with a consistent error, and the identity status should be set to `suspended` exactly once (no duplicate updates).
- **Agent realm vs. user realm confusion**: the `authorize` endpoint for agent identity sign-in must target the agent realm, not the user realm. A misconfigured redirect that points to the user realm must be detectable in tests (realm name in the OIDC discovery URL should match config).

### Database Migrations
- **Migration not applied**: if `alembic upgrade head` is not run, new tables (`agent_roles`, `agent_identities`, `agent_sessions`) are missing and all role/identity/session endpoints return 500 instead of 404/201. Integration tests must catch this by running against a real DB after migrations.
- **Removed fields on AgentType**: the old `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances` columns must be dropped. Tests must verify these columns are absent in `information_schema.columns`.
- **Removed models**: `AgentSkillAssignment` and `AgentMode` must be fully removed. Any remaining FK references would cause startup errors.
- **Enum value constraints**: `AgentSessionStatus`, `AgentIdentityType`, `AgentIdentityStatus`, `AgentInputType`, `AgentOutputType` are PostgreSQL enums. Tests must verify valid values are accepted and invalid values are rejected at the DB level.

### Frontend State
- **Polling memory leak**: if `AgentJobPage` is navigated away from before session completion, the `setInterval` must be cleared. A missing `clearInterval` on unmount would cause state updates on unmounted components.
- **Preview race condition**: rapid SOP/Skill selection changes could produce out-of-order preview responses. The debounce (300 ms) mitigates this, but tests should verify only the latest result is displayed.

---

## 5. Acceptance Criteria Checklist

| # | PRD Acceptance Criterion | Test Coverage |
|---|--------------------------|---------------|
| 1 | Users can create, edit, and delete agent roles, assigning SOP and Skill permissions | Backend unit: `test_agent_role_service.py`; Frontend: `AgentRoleListPage.test.tsx`, `AgentRoleDialog.test.tsx`; E2E: `agent-runtime.spec.ts` role CRUD suite |
| 2 | When a role is granted SOP access, all underlying Skills and MCP tools are automatically included | Backend unit: `test_permission_manager.py`; E2E: role dialog preview suite |
| 3 | UI provides a real-time preview of allowed MCP tools based on selected SOPs and Skills | Frontend component: `AgentRoleDialog.test.tsx` (debounce, empty state, edit-mode pre-population); E2E: role dialog preview suite |
| 4 | Users can define agent types with identity (OAuth-created), role, system instruction, input/output config | Backend unit: agent type service tests; Frontend: `AgentTypeForm.test.tsx` (identity dropdown shows OAuth identities); E2E: agent type CRUD suite |
| 4a | Admins can create agent identities by signing in to agent user accounts in the agent realm via OAuth; tokens stored securely | Backend unit: `test_agent_identity_service.py` (OAuth flow), `test_token_storage.py`; E2E: `agent-runtime.spec.ts` OAuth sign-in suite |
| 4b | System automatically refreshes agent tokens as needed for agent runtime operations | Backend unit: `test_token_refresh_service.py`; Backend integration: `test_agent_session_lifecycle.py` (expiry scenario); E2E: Real Backend suite (session launch with near-expiry token) |
| 4c | Bootstrap process initializes the agent realm in the identity provider, mirroring user realm setup | Backend unit: `test_realm_manager.py`; Backend integration: realm existence check after bootstrap; E2E: OIDC discovery URL reachable for agent realm |
| 5 | Users can launch agents, provide required input, and track session status asynchronously | Backend integration: `test_agent_session_lifecycle.py`; Frontend: `AgentSessionLaunchDialog.test.tsx`, `AgentSessionPage.test.tsx`; E2E: session launch and tracking suite (task + conversational) |
| 6 | Agent requests are routed through the communication hub/gateway | Backend unit: `test_lifecycle_handler.py`; E2E: session launch journey verifies 202 + navigation (Real Backend suite) |
| 7 | Agents fetch and use only the SOPs, Skills, and MCP tools permitted by their assigned role | Backend unit: `test_permission_manager.py`, `test_agent_runtime_executor.py`; executor boundary enforcement tests |
| 8 | All agent actions, session statuses, and results are auditable and observable | Backend integration: `test_agent_session_lifecycle.py` verifies `AgentSession` records persist status, timing, output, and error fields; OTEL span emission verified |
| 9 | Error handling and permission enforcement are consistent across all dialogs | Frontend component: `AgentRoleDialog.test.tsx`, `AgentIdentityDialog.test.tsx`, `AgentSessionLaunchDialog.test.tsx` — all verify `dialogError` state and `PermissionDeniedAlert` rendering |
| 10 | Out-of-scope actions (direct DB access, gateway bypass) are not possible | Backend unit: `test_agent_runtime_executor.py` permission boundary rejection; backend integration: verify no executor-bypass path exists |
| 11 | For conversational agents, the UI opens a chat interface for interactive communication | Frontend component: `AgentSessionPage.test.tsx` chat interface rendering; E2E: conversational agent launch journey |

---

## 6. Test File References

All paths below are relative to the workspace root, as defined in `docs/config.yaml` under `source.tests`.

### Backend Unit Tests (`backend/tests/unit/`)

| File | Tests | Coverage |
|------|-------|----------|
| `backend/tests/unit/test_agent_role_service.py` | 12 | `AgentRoleService` CRUD (create, list, read-by-id, update, delete), cache invalidation, assignment replacement |
| `backend/tests/unit/test_agent_identity_service.py` | 14 | Identity CRUD (new realm_name/realm_username model), OAuth sign-in flow (authorize redirect targets agent realm, callback token storage with encryption, not-found guard), status transitions, conflict detection |
| `backend/tests/unit/test_realm_manager.py` | 7 | `RealmManager` skips external/unconfigured providers, resolves realm name from explicit arg → yaml → default `ai_agents`, `keycloak_auth_failed` on unreachable Keycloak, `realm_creation_failed` on conflict, `realm_exists` returns True/False without raising |
| `backend/tests/unit/test_token_refresh_service.py` | 8 | Proactive refresh within expiry window, new encrypted tokens stored after refresh, refresh token rotated, expired refresh token → identity `suspended` + `TokenRefreshError`, missing refresh token raises, missing identity raises, `refresh_expiring_soon` returns count / skips failed and continues / returns 0 when none due |
| `backend/tests/unit/test_agent_session_service.py` | 11 | Enqueue, state transitions (`queued→running→completed`, `queued→running→failed`), list filtering |
| `backend/tests/unit/test_agent_runtime_executor.py` | 9 | Executor instantiation/required methods, permission denied → failed, generic exception → failed, success → completed |
| `backend/tests/unit/test_agent_instance_manager.py` | 5 | `AgentInstanceManager` lifecycle |
| `backend/tests/unit/test_agent_gateway.py` | 3 | Agent Gateway routing |

### Backend Integration Tests (`backend/tests/integration/`)

| File | Tests | Coverage |
|------|-------|----------|
| `backend/tests/integration/test_agent_session_lifecycle.py` | 26 | All new tables exist (agent_roles, agent_identities, agent_jobs, agent_role_sops, agent_role_skills); agent_identities has realm_name, realm_username, access_token, refresh_token, token_expires_at columns; agent_types has new columns (identity_id, role_id, input_type, output_type); removed old columns absent; full CRUD lifecycle for roles/identities; session state machine with real DB; schema column verification via information_schema |
| `backend/tests/integration/test_realm_bootstrap.py` | 5 | Bootstrap skips for external provider; creates agent realm for keycloak_bundled with configured name; registers OIDC client; idempotency surfaces `realm_creation_failed`; structured error code present |

### Frontend Component Tests (`frontend/src/__tests__/`)

| File | Tests | Coverage |
|------|-------|----------|
| `frontend/src/__tests__/AgentRoleListPage.test.tsx` | 6 | Table renders all roles; SOP count chip; Add/Edit/Delete actions |
| `frontend/src/__tests__/AgentRoleDialog.test.tsx` | 7 | Create/edit dialog; required field validation; PermissionDeniedAlert; error cleared on close; rerender without double-wrap |
| `frontend/src/__tests__/AgentIdentityListPage.test.tsx` | 11 | Table renders realm_name and realm_username columns; token active chip when token_expires_at is future; no-token indicator when null; status chips; OAuth section column header; Add Identity button opens dialog |
| `frontend/src/__tests__/AgentIdentityDialog.test.tsx` | 12 | Create mode: realm_name/realm_username fields present, no OAuth button; Edit mode: pre-populates all three fields, OAuth sign-in button present, authorize endpoint called, error shown on failure; Save enabled only when all three required fields filled; error cleared on reopen |
| `frontend/src/__tests__/AgentOAuthCallbackPage.test.tsx` | 5 | Loading spinner while processing; AGENT_OAUTH_SUCCESS posted to opener on success; AGENT_OAUTH_ERROR on IdP error param; AGENT_OAUTH_ERROR on missing code/state; AGENT_OAUTH_ERROR on backend API failure |
| `frontend/src/__tests__/AgentTypeForm.test.tsx` | 11 | New fields present (identity_id, role_id, system_instruction, input_type, output_type); MUI label selector fixes |
| `frontend/src/__tests__/AgentManagementPage.test.tsx` | 9 | Launch button opens dialog; Edit action; aria-label on IconButtons |
| `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx` | 6 | Info Alert for none input_type; submit flow; PermissionDeniedAlert |
| `frontend/src/__tests__/AgentSessionPage.test.tsx` | 8 | Queued/completed/failed status rendering; status text in chip + Paper; scrollIntoView mock |

### E2E Tests (`e2e/tests/`)

| File | Tests | Backend | Coverage |
|------|-------|---------|----------|
| `e2e/tests/agent-management.spec.ts` | 6 pass | Mocked | Agent management page renders; agent type list; input_type chip; create dialog opens |
| `e2e/tests/agent-runtime.spec.ts` | 20 pass, 3 skip | Mocked (real-backend tests skip when backend not running) | Agent role management, OAuth identity sign-in flow (realm_name/realm_username columns, token active chip, OAuth button in edit dialog — mocked authorize endpoint), agent type configuration (new fields, identity dropdown, no old fields), session launch dialog, session status pages (queued/completed/failed), real-backend integration variants |
| `e2e/tests/agent-bootstrap.spec.ts` | 5 pass, 1 skip | Mocked + Real Keycloak (skipped when Keycloak not running on port 8082) | Health endpoint reports identity provider status; identities page loads with realm name column when realm initialized (mocked); configured agent realm name displayed; agent realm OIDC discovery endpoint reachable; user realm unaffected; backend health reports agent_realm_initialized |
| `e2e/tests/agent-bootstrap.spec.ts` | 3 pass, skipped when Keycloak not running | Real Keycloak | Realm OIDC discovery endpoint reachable; agent realm distinct from user realm; bootstrap idempotency (run twice, no error) |

The 2 skipped tests in `agent-runtime.spec.ts` are the "Real Backend Integration" suite — they run only when the backend is reachable at `http://localhost:8000` and validate that the DB migration has been applied.

---

## 7. Pre-Test Checklist

Before executing any test suite for this change:

- [ ] Run `alembic upgrade head` and verify output shows new migration applied
- [ ] Run `alembic current` and confirm the revision matches the migration created for this change
- [ ] Confirm new tables exist: `agent_roles`, `agent_role_sops`, `agent_role_skills`, `agent_identities`, `agent_jobs`
- [ ] Confirm removed columns are absent on `agent_types`: `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`
- [ ] Confirm `AgentSkillAssignment` table is dropped
- [ ] Confirm `agent_identities` table includes `access_token_enc` and `refresh_token_enc` columns (encrypted token storage)
- [ ] Start all services via `.\parthenon.ps1 start` and verify health checks pass
- [ ] Confirm backend responds at `http://localhost:8000/health`
- [ ] Confirm frontend serves at `http://localhost:5173`
- [ ] Confirm Keycloak agent realm is initialized: `http://localhost:8082/realms/<agent_realm>/.well-known/openid-configuration` returns 200
- [ ] Confirm agent realm name in `config/identity.yaml` (or equivalent bootstrap config) matches the realm initialized in Keycloak
