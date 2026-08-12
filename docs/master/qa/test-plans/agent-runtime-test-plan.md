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

### Runtime SOP Selection and Fallback Injection (ai-assisted-workflow-authoring-for-sop-and-skill)
- `PlanGenerationService._resolve_graph` filters `sop_data_list` to SOPs referenced in `system_instruction` when names are present
- If no SOP names are referenced and `primary_sop_id` is set, `_resolve_graph` falls back to the default SOP only
- If no SOP names are referenced and no default SOP is configured, `_resolve_graph` keeps all role SOPs
- `get_agent_context` skips default SOP content injection when `system_instruction` already references SOP names
- `get_agent_context` injects default SOP content when `system_instruction` references no SOP names
- SOP name matching is case-insensitive in both planning and runtime context assembly paths

### A2A Communication and Slug Enforcement
- A2A routing uses target agent type slug and preserves requester/receiver session continuity.
- Runtime fallback creates dynamic receiver on target miss, then links conversation state for continued turns.
- Disconnect flow removes dynamic receiver and clears A2A session-link state.
- A2A allow/deny decision accepts only target slugs derived from SOP `agent_delegation` steps.
- Slug-only validation rejects non-slug agent type and agent names before/at API validation boundaries.

### Unified Tool Naming and Routing
- `parse_tool_name(name)` correctly splits `server____tool` into `(server, tool)` for valid names
- `build_tool_name(server, tool)` produces canonical `server____tool` string
- `is_system_tool(name)` returns `True` only for `system____*` names
- Legacy bare tool names parsed without error (backward compatibility)
- Names with more or fewer than 4 underscores rejected as malformed
- Server segment containing `____` rejected (reserved separator)
- `system` as MCP server name rejected at registration time
- Agent executor code contains no branching on system vs MCP tool type — all tool calls forwarded uniformly to Communication Hub

### Explicit Result Saving
- Agent that calls `system____save_result` → `ResultRecord` created with correct payload, title, and source
- Agent that completes without calling `system____save_result` → no `ResultRecord` created
- Both scenarios verified via `result_records` table query and `GET /api/v1/results` endpoint

### Service Trust Boundaries
- Agent Runtime attempts direct PostgreSQL connection → connection refused (no `DATABASE_URL` configured)
- Agent Runtime fetches all context (plan, skills, model config) via Control Center data APIs only
- Agent Runtime bootstrap: certificate issued by Control Center; subsequent requests use mTLS with service cert
- Certificate renewal: AR renews before expiry; old cert remains active until new cert is validated
- Agent Runtime calling Communication-Hub-only internal endpoints is denied by Control Center caller-scope policy
- Agent Runtime calls to non-allowlisted internal endpoints are denied by default with auditable deny reason fields

## Critical Scenarios


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
- Passthrough session dispatch: `_load_role_mcp_session_map()` includes passthrough sessions so dispatch does not fail with "no session assigned"
- Passthrough session dispatch: `_execute_mcp_tool()` detects `auth_type == passthrough`, retrieves agent identity JWT from runtime context, passes it to `proxy.call_tool()` as `agent_jwt`; stored credentials never accessed
- Passthrough session dispatch: when agent identity token is unavailable at runtime, tool call returns a structured error dict and the agent loop continues without crashing

### A2A Runtime Lifecycle
- Request with available target slug routes directly and returns in same session.
- Request with unavailable target slug triggers dynamic receiver creation and link activation.
- Request with disallowed target slug is denied before runtime provisioning.
- Disconnect tears down dynamic receiver and removes session-link record.

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

### Certificate Lifecycle (Security Segregation)
- CA initialization: root CA cert generated on first Control Center startup; idempotent on subsequent startups
- Certificate issuance: `POST /certificates/issue` creates record in `agent_instance_certificate` with status `active`; CN format `agent-type:instance-id`; serial number globally unique
- Certificate validation: valid certificate accepted; expired certificate returns 401 with outcome `expired` logged; revoked certificate returns 403 with outcome `revoked` logged; all outcomes recorded in `certificate_validation_log`
- Certificate revocation: `POST /certificates/revoke` marks certificate `revoked`, inserts entry into `certificate_revocation_entry`; subsequent use of revoked cert immediately rejected
- Certificate renewal: Agent Runtime auto-renews at 80% of lifetime (19 h); new cert atomically replaces old cert with no downtime; renewal logged with new serial and expiration
- Graceful shutdown: if certificate expires and renewal fails (Control Center unreachable or permission denied), Agent Runtime logs critical error and shuts down; no tool calls accepted with expired cert

### Agent Runtime Security Guarantees
- Metadata response (`GET /agent/metadata`) does NOT contain `identity_token`, `access_token`, or `refresh_token` fields — zero-trust requirement
- Agent Runtime authenticates using client certificate only; JWT tokens are never held by Agent Runtime
- Certificate loaded from filesystem on startup; absence or corruption causes startup failure with clear error
- Security assertion: Agent Runtime validates metadata response structure and rejects responses containing identity tokens

### Execution Guardrails (add-agent-execution-guardrails)
- Pre-execution delegation graph validation blocks direct and indirect recursion before first model or tool action
- Runtime enforces cumulative execution ceilings for iterations, delegation depth, delegated steps, and timeout with deterministic stop reasons
- Guardrail stop reasons remain distinct from functional runtime failures in persisted session state and logs
- Conversational sessions surface current-session token usage and continuation hints without token-budget-only hard stop
- Non-conversational sessions enforce token budget behavior consistently with configured fallback visibility
- Guardrail counters and stop outcomes remain visible in execution summaries used by operators

## Test File References

### Backend — Unit Tests
- `backend/tests/unit/test_agent_identity_service.py` — identity CRUD, status transitions, token storage
- `backend/tests/unit/test_agent_role_service.py` — role CRUD, SOP/skill assignment, permission cache invalidation
- `backend/tests/unit/test_agent_runtime_executor.py` — LangChain executor, role permission boundary enforcement
- `backend/tests/unit/test_agent_session_service.py` — session lifecycle, dispatch, result writing
- `backend/tests/unit/test_agent_gateway.py` — gateway authorization checks
- `backend/tests/unit/test_agent_instance_manager.py` — instance tracking and status
- `backend/tests/unit/test_token_refresh_service.py` — token refresh logic, retry/backoff, rate-limit handling

### Backend — Integration Tests
- `backend/tests/integration/test_certificate_lifecycle.py` — certificate issuance, validation, revocation, renewal against real database
- `backend/tests/integration/test_authorization_flow.py` — full authorization flow: certificate validation + permission resolution + token refresh
- `backend/tests/integration/test_token_refresh_security.py` — token refresh with mocked OAuth provider; retry logic; `token_refresh_log` population
- `backend/tests/integration/test_agent_session_lifecycle.py` — session dispatch, execution, completion, failure transitions
- `backend/tests/integration/test_agent_role_constraints.py` — role constraint enforcement

### E2E Tests
- `e2e/tests/agent-runtime.spec.ts` — Agent Runtime UI flows and session submission
- `e2e/tests/agent-management.spec.ts` — agent type and identity management CRUD
- `e2e/tests/agent-bootstrap.spec.ts` — realm initialization and first-run setup
- `e2e/tests/agent-security-segregation.spec.ts` — **Real Backend Integration**: certificate authentication, metadata security assertion (no identity tokens), tool authorization with certificate, certificate revocation
- `e2e/tests/agent-identity-token-refresh.spec.ts` — token refresh endpoint wiring, identity management UI with mocked backend

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

### Model Configurations — Expanded Provider Catalogue

See `docs/changes/expand-model-config-providers/prd.md` AC-1 through AC-30 for the full acceptance criteria. All 12 provider keys (`openai`, `anthropic`, `litellm_proxy`, `azure_openai` plus the eight new below) are covered by the test files listed at the end of this section. For database-migration verification, see the pre-test checklist in `docs/changes/expand-model-config-providers/test-plan.md` and the real-backend E2E assertion that `GET /agents/model-configs` returns a 2xx response only when the migration has been applied.

**Per-provider scenarios — Gemini (`gemini`):**
- WHEN a Platform Administrator creates a `ModelConfig` with `provider_type = "gemini"` through the REST API, THEN the backend encrypts the API key with the AES-256 vault and persists the row; the `ModelConfigRead` response contains `has_credentials: true` and no raw key or encrypted blob; the new row is returned by the list endpoint with the correct `provider_type`.
- WHEN an agent invokes a model bound to a Gemini `ModelConfig`, THEN the dispatcher routes the call through the Gemini native REST endpoint, attaches the correct credential header, and normalises the response through the extractor; usage data is extracted or set to `null` when unavailable.
- WHEN a Gemini API call returns 4xx or 5xx, THEN the error log contains the string `gemini` and the underlying vendor error body; a `ModelBindingError` is raised.
- WHEN the administrator clicks "Fetch Models" on a Gemini config, THEN the endpoint returns a non-empty, sorted curated list; on network failure, it returns `[]` and logs an error.

**Per-provider scenarios — Mistral (`mistral`):**
- WHEN a Platform Administrator creates a `ModelConfig` with `provider_type = "mistral"`, THEN the API key is AES-256-encrypted; the row appears in the list with the mistral provider chip; the `has_credentials` flag is the only credential-derived field.
- WHEN the dispatcher resolves a model id against a Mistral config, THEN the call is dispatched through the OpenAI-compatible call path to Mistral's base URL; the credential is attached as a bearer token.
- WHEN a Mistral API call fails, THEN the error log contains the string `mistral`.
- WHEN "Fetch Models" is invoked, THEN the shared OpenAI-compatible listing endpoint returns models from Mistral's `/models` endpoint; on failure, the list is empty.

**Per-provider scenarios — Cohere (`cohere`):**
- WHEN a `ModelConfig` is created with `provider_type = "cohere"`, THEN the API key is encrypted and the row round-trips through list/get/update/delete correctly; the Cohere-specific credential header is never exposed.
- WHEN the dispatcher routes a call against a Cohere config, THEN it uses the Cohere native REST endpoint with the vendor-specific credential header; the response text, tool-calls, and usage are extracted from the Cohere response envelope.
- WHEN a Cohere API call returns a 4xx or 5xx error, THEN the error log includes the string `cohere`.
- WHEN "Fetch Models" is invoked for a Cohere config, THEN the curated static list is returned; even an empty-credential config returns the curated list.

**Per-provider scenarios — Groq (`groq`):**
- WHEN a `ModelConfig` with `provider_type = "groq"` is persisted, THEN the encryption, read, update, and delete paths function identically to the OpenAI-compatible family; the Groq base URL is used for all dispatch.
- WHEN the dispatcher calls Groq, THEN it uses the OpenAI-compatible call path; the bearer token is the decrypted API key.
- WHEN a Groq API call fails, THEN the error log contains the string `groq`.

**Per-provider scenarios — Together AI (`together`):**
- WHEN a `ModelConfig` with `provider_type = "together"` is created, THEN all CRUD operations and credential encryption work as expected; the Together base URL is used.
- WHEN the dispatcher calls Together AI, THEN it dispatches through the OpenAI-compatible path; the bearer token is the decrypted API key.
- WHEN a Together API call fails, THEN the error log contains the string `together`.

**Per-provider scenarios — Fireworks AI (`fireworks`):**
- WHEN a `ModelConfig` with `provider_type = "fireworks"` is created, THEN the row round-trips correctly; the Fireworks base URL is the dispatch target.
- WHEN the dispatcher routes a call against Fireworks, THEN it goes through the OpenAI-compatible path; the credential is a bearer token.
- WHEN a Fireworks API call fails, THEN the error log contains the string `fireworks`.

**Per-provider scenarios — Perplexity (`perplexity`):**
- WHEN a `ModelConfig` with `provider_type = "perplexity"` is created, THEN all CRUD and encryption guarantees hold; the Perplexity base URL is used.
- WHEN the dispatcher calls Perplexity, THEN it uses the OpenAI-compatible call path.
- WHEN a Perplexity API call fails, THEN the error log contains the string `perplexity`.

**Per-provider scenarios — DeepSeek (`deepseek`):**
- WHEN a `ModelConfig` with `provider_type = "deepseek"` is created, THEN the row round-trips correctly through all CRUD endpoints; the DeepSeek base URL is the dispatch target.
- WHEN the dispatcher routes a DeepSeek call, THEN it goes through the OpenAI-compatible path.
- WHEN a DeepSeek API call fails, THEN the error log contains the string `deepseek`.

#### Cross-provider scenarios
- WHEN the dispatcher receives a `provider_type` not in the 12-value registry, THEN `ModelBindingError` is raised and the unknown key is logged.
- WHEN an admin updates a config's `provider_type` from one new provider to another (e.g. `gemini` → `mistral`), THEN the change is persisted and the new provider key is returned by the list endpoint.
- WHEN the "Fetch Models" call fails for any provider (network error, invalid key), THEN the endpoint returns 200 with `[]`, the log includes the provider key, and the admin is never blocked from saving.
- WHEN an admin attempts to delete a config whose `enabled_models` includes a model id referenced by an `AgentType`, THEN the delete returns 409 for every provider.
- WHEN the existing list endpoint returns configs for all 12 provider types, THEN each response entry contains the correct `provider_type` string literal byte-for-byte.
- WHEN an inference call is made through any of the 12 providers, THEN the OpenTelemetry span and structured log carry the provider key, model id, config display name, and standard latency/status attributes.

#### Database migration verification
- WHEN `alembic current` is run after the migration, THEN the new revision id (chained from `f4a5b6c7d8e9`) is reported.
- WHEN the Postgres `model_provider_enum` metadata is queried, THEN exactly 12 values are present in append-only order.
- WHEN the `(id, provider_type)` of every pre-existing `model_configs` row is snapshotted before and after the migration, THEN the two snapshots are byte-for-byte equal.
- WHEN the migration is applied a second time, THEN it is a no-op (idempotent).

**Test files for the expanded provider catalogue:**
- `backend/tests/unit/test_model_config_service.py` — per-provider CRUD lifecycle with AES-256 vault, list-models per provider family, failure-path coverage.
- `backend/tests/unit/test_model_binding.py` — per-provider resolve and dispatch, extractor widening for Gemini and Cohere, 4xx/5xx log assertion across all 12 providers, unknown-provider rejection, observability attributes.
- `backend/tests/api/test_model_configs_api.py` — round-trip over the full 12-provider catalogue, provider-type change on update, delete safety guard (409), list-models endpoint per provider, permission rules.
- `backend/tests/db/test_model_provider_enum_migration.py` — enum row count, column type preservation, type-not-recreated check, pre-existing row preservation, migration idempotency.
- `e2e/tests/agent-runtime.spec.ts` — `Real Backend Integration - Model Configurations` block (no `page.route()` mocks, validates migration applied) and `Model Config CRUD` block.

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

### System-Instruction-Aware SOP Behavior
- `system_instruction` explicitly names a SOP available on the role → plan generation and runtime context include that SOP path only
- `system_instruction` omits SOP names and `primary_sop_id` is configured → default SOP is used as fallback for both plan context and runtime SOP content
- `system_instruction` omits SOP names and no default SOP is configured → all role SOPs remain available to planning path and runtime avoids forced default injection

### Token Refresh During Execution
- Access token expires mid-session → executor calls `TokenRefreshService` inline → tool call retried with new token
- Refresh token expired → identity status → `suspended` → session fails gracefully

### Credential Security
- API key never returned in plaintext from GET responses — assert credential field absent or masked in all list and detail responses

### Passthrough Runtime Dispatch (Critical Path)
- Agent session executing with a passthrough-type MCP session assigned to its role → `proxy.call_tool()` invoked with agent identity JWT; no credential decryption occurs
- Agent identity token unavailable at runtime (expired or absent) → tool call returns structured error dict; agent observe-reason-act loop continues without crashing

### Execution Guardrails (add-agent-execution-guardrails)
- Direct and indirect delegation cycles are rejected in pre-check with deterministic cycle stop classification
- Runtime enforces bounded execution for iteration, delegation depth, delegated steps, and timeout without ambiguous terminal states
- Guardrail stop reasons are preserved through status updates and execution logs for operator triage
- Conversational token usage is visible in execution summary surfaces without forcing token-budget-only termination

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
- `backend/tests/unit/test_agent_guardrails.py`
- `backend/tests/unit/test_agent_role_service.py`
- `backend/tests/unit/test_agent_identity_service.py`
- `backend/tests/unit/test_agent_runtime_executor.py` — includes passthrough session dispatch: `_execute_mcp_tool()` passes `agent_jwt` to proxy; structured error returned when agent JWT unavailable
- `backend/tests/unit/test_agent_session_service.py`
- `backend/tests/unit/test_agent_instance_manager.py`
- `backend/tests/unit/test_model_config_service.py`
- `backend/tests/unit/test_model_binding.py`
- `backend/tests/unit/test_permission_manager.py`
- `backend/tests/unit/services/test_plan_generation_service.py`
- `backend/tests/unit/test_a2a_core_flow.py`
- `backend/tests/unit/test_a2a_communication.py`
- `backend/tests/unit/test_token_refresh_service.py`
- `backend/tests/unit/test_realm_manager.py`
- `backend/tests/unit/test_lifecycle_handler.py`
- `backend/tests/unit/test_execution_log.py`
- `backend/tests/unit/test_communication_hub.py`
- `backend/tests/unit/test_agent_data_sop_injection.py`

### Backend Integration Tests
- `backend/tests/integration/test_agent_session_lifecycle.py`
- `backend/tests/integration/test_agent_execution_with_logs.py`
- `backend/tests/integration/test_agent_role_constraints.py`
- `backend/tests/integration/test_realm_bootstrap.py`
- `backend/tests/integration/test_identity_setup_flow.py`
- `backend/tests/integration/test_communication_hub.py`
- `backend/tests/integration/test_websocket_communication_hub.py`
- `backend/tests/integration/test_internal_allowlist_partitioning.py`
- `backend/tests/integration/test_internal_deny_audit_events.py`
- `backend/tests/integration/test_internal_revocation_fail_closed.py`

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
- `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx`
- `frontend/src/__tests__/ConversationDialog.test.tsx`
- `frontend/src/__tests__/LogPresenter.test.ts`
- `frontend/src/__tests__/LogSummaryPanel.test.tsx`
- `frontend/src/__tests__/ModelConfigListPage.test.tsx`
- `frontend/src/__tests__/ModelConfigDialog.test.tsx`

### E2E Tests
- `e2e/tests/agent-runtime.spec.ts` — Agent Role Management, Agent Identity Management, Agent Type Configuration, Agent Session Launch, Agent Session Status, Model Config CRUD, Agent Instance Dashboard, Conversation History Display, Agent Role Identity Constraints, Identity-First Role Selection, Real Backend Integration suites
- `e2e/tests/agent-management.spec.ts` — guardrail editor fields and token-enforcement controls in create/edit flows
- `e2e/tests/agent-navigation.spec.ts` — agent details dialog guardrail rendering and k-token display coverage
- `e2e/tests/agent-logs.spec.ts` — execution summary visibility path for guardrail usage presentation
- `e2e/tests/agent-bootstrap.spec.ts` — Agent Realm Bootstrap (Mocked and Real Keycloak Integration suites)
- `e2e/tests/agent-a2a-communication.spec.ts` — slug validation and delegation preview coverage for A2A-related UI flows
- `e2e/tests/comm-hub-websocket.spec.ts` — Communication Hub websocket flow coverage
- `e2e/tests/websocket-communication-hub.spec.ts` — websocket routing and delivery checks
- `e2e/tests/service-segregation-security-audit.spec.ts` — Real backend deny-path checks for internal authorize/system-tools endpoints and revocation contract endpoint wiring
- `backend/tests/unit/services/test_plan_generation_service.py` — AgentRuntimeLoader plan injection unit tests (loaded via agent-plan-mode change)
- `backend/tests/integration/api/test_agent_types_plan.py` — plan injection integration coverage
