# Agent Runtime Test Plan

## What to Test

### Agent Role CRUD
- Create, read, update, delete `AgentRole` entities
- Assign SOP IDs and Skill IDs atomically; replace (not append) on update
- Reject deletion when an `AgentType` references the role (409 Conflict)
- Permission cache invalidated on every write
- Assign identities to role via bulk POST; persisted in `agent_role_identity` join table
- Remove identity from role via DELETE; idempotent assign (no-op or 409 on duplicate)
- List identities assigned to role via GET
- `allowed_identity_types` constraint persisted and enforced on assignment

### Agent Identity Management
- Create `AgentIdentity` via OAuth sign-in flow (admin signs in to agent realm)
- Read, update, delete `AgentIdentity` entities
- Status transitions: `active`, `suspended`, `deprovisioned`
- Reject deletion when any `AgentType` references the identity (409 Conflict)
- `authorize` endpoint redirects to agent realm (not user realm)
- `callback` endpoint stores encrypted access and refresh tokens; creates identity with status `active`
- Duplicate sign-in for same agent user updates existing identity or rejects consistently
- Assign roles to identity via bulk POST; remove via DELETE; list via GET

### Realm Initialization (Bootstrap)
- `RealmManager` creates dedicated agent realm from bootstrap config
- Realm name is configurable; default is `ai_agents`
- Bootstrap is idempotent (no error or duplicate resources on second run)
- Clear error surfaced when identity provider is unavailable during bootstrap

### Agent Token Storage and Refresh
- Access tokens and refresh tokens stored encrypted against `AgentIdentity`
- `TokenRefreshService` proactively refreshes before expiry window; handles already-expired token via refresh token
- Refresh token rotation on successful refresh
- Identity status set to `suspended` when refresh token is expired; session blocked
- Token refresh triggered inline mid-session when current access token expires

### Model Configuration Management
- Create, read, update, delete `ModelConfig` entities (provider types: `openai`, `anthropic`, `litellm_proxy`, `other`)
- API key stored encrypted; never returned in GET responses (masked indicator only)
- `litellm_proxy` type: endpoint URL required, API key optional
- `GET /api/v1/model-configs/{id}/models` fetches available models from provider using stored credentials
- Available-models endpoint returns structured error when provider unreachable or credentials invalid (not 500)
- `enabled_models` array updated on save; unchecked models removed; subsequent fetch shows saved selection
- `AgentTypeForm` shows flat union of `enabled_models` across all active `ModelConfig` records; no two-level selector
- Selecting a model sets `model_id` string on `AgentType`; no FK to `ModelConfig` created
- Reject deletion when referenced by an `AgentType` (409 Conflict)

### Agent Type Configuration
- New schema fields: `identity_id`, `role_id`, `model_id`, `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema`
- Removed fields (`mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `model_config_id`, `model_name`) rejected by API
- Identity selector populated with active OAuth-signed-in identities only
- Model selector populated from aggregated `enabled_models` across all active `ModelConfig` records
- Identity and role with no assignment link → client-side validation error before API call
- Changing identity clears role selection
- Save blocked unless a model is selected

### Runtime Identity-Role Validation
- At session launch: validates identity is assigned to role via `agent_role_identity`
- Session rejected with 403 (`PermissionDeniedError`) if identity not assigned to role
- Session transitions immediately to `failed`; observe-reason-act loop not initiated
- Error message contains identity-role assignment mismatch detail
- No `ExecutionLog` written for sessions failing at identity-role validation

### Agent Session Lifecycle
- Enqueue: `POST /api/v1/agents/sessions` returns 202 with session ID synchronously
- List: `GET /api/v1/agents/sessions` returns only sessions belonging to authenticated user
- Status transitions: `queued → running → completed` and `queued → running → failed`
- `GET /api/v1/agents/sessions/{id}/result` returns 409 when session not in terminal status
- Polling: `AgentJobPage` polls every 3 seconds; stops on `completed` or `failed`; interval cleared on unmount

### Session Dispatch and Execution (LangChain)
- `SessionDispatcher` uses `SKIP LOCKED` to prevent double-dispatch
- `AgentRuntimeExecutor` uses the **LangChain deep agent** framework (not LangGraph state graph) — observe-reason-act loop
- Executor enforces role permission boundary; tool calls outside allowed set rejected and logged
- Result written via `save_result`; session transitions to `completed`
- `MaxIterationsExceeded` transitions session to `failed` with error message
- Model resolved at dispatch time by scanning all `ModelConfig.enabled_models` arrays
- Missing `model_id` resolution → `ModelResolutionError`; session status → `failed`

### Execution Log Capture
- `ExecutionLog` record created for every session containing full, untruncated system instruction and user prompt
- `GET /api/v1/agents/sessions/{id}/execution-logs` returns log for completed session
- Returns 404 for sessions still `queued` or sessions that failed before log was written
- Returns 403 when requesting user does not own the session
- `AgentInstanceDetailPage` renders "Execution Logs" section for completed sessions; absent for `queued` sessions

### Agent Instance Dashboard
- Shows all agent instances across all agent types
- Each row: instance ID (truncated), agent type name, status chip, submitted timestamp, completed timestamp
- Status filter and time range filter; both combinable; persist across navigations
- Empty state shown when no instances match current filters
- Clicking a row navigates to instance detail page
- Performance: acceptable response time with 1000+ instances

### Agent Instance Detail View
- Input section, output section, status chip, timestamps, duration, submitting user, model metadata
- Conversational agents: full ordered conversation history section
- Real-time status updates via polling while `running` or `queued`; polling stops at terminal status
- `failed` sessions show error message; `running` sessions show in-progress indicator

### Permission Resolution
- `AgentPermissionManager` resolves: `AgentRole → SOPs → Skills → MCP tools` via join traversal
- Direct Skill assignments also contribute tools; merged set has no duplicates
- LRU cache returns consistent results for same `role_id`; invalidated on role update or delete
- Circular SOP dependency detected; finite tool set resolved without infinite recursion

### Bidirectional Identity-Role Assignment
- Assign from role side and assign from identity side both create the same `agent_role_identity` record (no duplicates)
- Removing from either side removes the record and propagates to the other view without page reload

### Token Management UI
- Identity list shows token status chips (`valid`, `expired`, `expiring soon`)
- Refresh button enabled only when refresh token is valid
- Re-auth button always enabled
- OAuth callback from re-auth flow updates tokens; status chip updates to `valid` without page reload

### Communication Hub OAuth Enforcement
- Agent connection without `Authorization` header → 401
- Expired or signature-invalid token → 401
- Valid token with unrecognized or unauthorized role claim → 403
- Valid token with recognized role → 200 with permitted tool list
- Tool list entries contain only `mcp_slug/tool_name` identifiers; no `description` or `schema` fields
- Agent call to unlisted tool returns permission denied (not 500)

### AgentRuntimeLoader — Plan Injection (agent-plan-mode change)
- When an agent session is started for an agent type with `generation_status = success`, the plan is loaded from `agent_plans` and injected into the agent's system context (LLM system prompt) as a structured text block
- The injected plan includes instructions directing the agent to follow the pre-approved steps
- When no `AgentPlan` row exists for the agent type, the session starts without plan injection (graceful degradation; no errors)
- When the agent type's plan has `generation_status = failed`, the session proceeds without plan injection
- Runtime logs record whether a plan was loaded and injected (for observability)

### Permission Reference Format
- All tool identifiers returned by `/api/v1/agents/roles/{id}/mcp-tools` use `mcp_slug/tool_name` format
- No colon-delimited `server_slug:tool_name` format in any response
- `AgentPermissionManager.is_allowed()` resolves correctly for `mcp_slug/tool_name` keys

### Real-Time MCP Tool Preview
- Selecting/deselecting SOPs/Skills in `AgentRoleDialog` triggers debounced (300 ms) re-fetch of preview tool list
- Preview populates immediately on open when role already has assignments
- Preview shows empty state when no SOPs or Skills are selected
- Preview fetch failure shows inline error; Save remains enabled

### Gateway Routing
- Launch request routed through `AgentSessionService.enqueue`; session ID returned synchronously
- Conversational agents: bidirectional WebSocket channel established by `LifecycleHandler`
- Non-existent AgentType ID → 404; unauthorized launch → 403

## Critical Scenarios

### Database Change Requirements
This module has `has_db_changes: true`. Before running any tests:
1. Verify `alembic current` shows the agent-runtime migration ID
2. Backend integration test fixture must run `alembic upgrade head` before any test
3. Integration tests must verify schema via `information_schema` queries
4. At least one E2E suite must be labeled `Real Backend Integration` and run without `page.route()` mocks

### Identity-Role Validation (Critical Path)
- Create `AgentType` where identity is NOT assigned to role → launch → 403 → session status `failed` → assign identity to role → re-launch → 202 → session reaches `completed`

### Permission Boundary Enforcement
- Role with no SOPs and no Skills → empty allowed tool set → all tool calls rejected
- Role assigned two SOPs → preview shows union of tools without duplicates → save → cache invalidated

### Token Refresh During Execution
- Access token expires mid-session → executor calls `TokenRefreshService` inline → tool call retried with new token
- Refresh token expired → identity status → `suspended` → session fails gracefully

### Credential Security
- API key never returned in plaintext from GET responses — assert credential field absent or masked in all list and detail responses

## Edge Cases
- Circular SOP dependencies resolved without infinite recursion
- Double-dispatch prevented via `SKIP LOCKED`; verify session dispatched only once under concurrent dispatchers
- `model_id` appears in `enabled_models` of two `ModelConfig` records → resolution uses first match by deterministic ordering
- Concurrent credential update and session launch → executor fetches credentials at dispatch time
- Refresh token expiry with concurrent sessions → all sessions fail gracefully; identity status set to `suspended` exactly once
- OAuth state parameter replay → rejected with 400 (not silently accepted)
- Stuck running sessions (executor crash) → recovery mechanism or timeout; does not silently hang

## Test File References

### Backend Unit Tests
- `backend/tests/unit/test_agent_role_service.py`
- `backend/tests/unit/test_agent_identity_service.py`
- `backend/tests/unit/test_agent_runtime_executor.py`
- `backend/tests/unit/test_agent_session_service.py`
- `backend/tests/unit/test_agent_instance_manager.py`
- `backend/tests/unit/test_model_config_service.py`
- `backend/tests/unit/test_model_binding.py`
- `backend/tests/unit/test_permission_manager.py`
- `backend/tests/unit/test_token_refresh_service.py`
- `backend/tests/unit/test_realm_manager.py`
- `backend/tests/unit/test_lifecycle_handler.py`
- `backend/tests/unit/test_execution_log.py`
- `backend/tests/unit/test_communication_hub.py`

### Backend Integration Tests
- `backend/tests/integration/test_agent_session_lifecycle.py`
- `backend/tests/integration/test_agent_execution_with_logs.py`
- `backend/tests/integration/test_agent_role_constraints.py`
- `backend/tests/integration/test_realm_bootstrap.py`
- `backend/tests/integration/test_identity_setup_flow.py`
- `backend/tests/integration/test_communication_hub.py`

### Backend API Tests
- `backend/tests/api/test_agents_api.py`
- `backend/tests/api/test_model_configs_api.py`

### Frontend Component Tests
- `frontend/src/__tests__/AgentRoleListPage.test.tsx`
- `frontend/src/__tests__/AgentRoleDialog.test.tsx`
- `frontend/src/__tests__/AgentIdentityListPage.test.tsx`
- `frontend/src/__tests__/AgentIdentityDialog.test.tsx`
- `frontend/src/__tests__/AgentOAuthCallbackPage.test.tsx`
- `frontend/src/__tests__/AgentInstanceDashboard.test.tsx`
- `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx`
- `frontend/src/__tests__/AgentSessionPage.test.tsx`
- `frontend/src/__tests__/AgentTypeForm.test.tsx`
- `frontend/src/__tests__/ModelConfigListPage.test.tsx`
- `frontend/src/__tests__/ModelConfigDialog.test.tsx`

### E2E Tests
- `e2e/tests/agent-runtime.spec.ts` — Agent Role Management, Agent Identity Management, Agent Type Configuration, Agent Session Launch, Agent Session Status, Model Config CRUD, Agent Instance Dashboard, Conversation History Display, Agent Role Identity Constraints, Identity-First Role Selection, Real Backend Integration suites
- `e2e/tests/agent-bootstrap.spec.ts` — Agent Realm Bootstrap (Mocked and Real Keycloak Integration suites)
- `e2e/tests/communication-hub-auth.spec.ts` — Communication Hub OAuth enforcement
- `backend/tests/unit/services/test_plan_generation_service.py` — AgentRuntimeLoader plan injection unit tests (loaded via agent-plan-mode change)
- `backend/tests/integration/api/test_agent_types_plan.py` — plan injection integration coverage
