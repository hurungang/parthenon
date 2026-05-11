# Test Plan: Agent Runtime with Gateway

**Change**: `implement-agent-runtime-with-gateway`
**Date**: 2026-05-05
**Status**: In Progress — `has_db_changes: true`

---

## 1. Test Strategy

This change introduces a new permission model (AgentRole), a new identity model (AgentIdentity), and an asynchronous session execution system (AgentSession) powered by the **LangChain deep agent framework**. Execution logs now capture the full system instruction and user prompt for every agent run, with UI visibility per instance. All four test layers — backend unit, backend integration, frontend component, and E2E — must pass before marking this change implemented.

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
- Assign identities to role via bulk POST endpoint; assignment persisted in `agent_role_identity` join table
- Remove a specific identity from role via DELETE; assignment record removed
- List identities currently assigned to role via GET; returns identity records with type and status
- Attempt to assign same identity to same role twice → operation is idempotent (no-op) or returns 409 Conflict
- Attempt to remove an identity not assigned to the role → 404 Not Found

### Agent Identity Management
- Create an `AgentIdentity` record via the OAuth sign-in flow (admin signs in to an agent user account in the agent realm; tokens stored on callback)
- Read, update, delete `AgentIdentity` entities
- Identity status transitions: `active`, `suspended`, `deprovisioned`
- Reject deletion when any `AgentType` references the identity (409 Conflict)
- OAuth `authorize` endpoint redirects to the identity provider's configured agent realm (not the user realm)
- OAuth `callback` endpoint stores encrypted access token and refresh token against the new identity record
- Duplicate sign-in for the same agent user (same subject in the agent realm) is rejected or updates the existing identity
- Assign roles to identity via bulk POST; creates `agent_role_identity` records
- Remove role from identity via DELETE; removes `agent_role_identity` record
- List roles currently assigned to identity via GET; returns role records
- Token refresh when access token expired but refresh token still valid → refresh succeeds and new access token stored
- Token refresh when both access token and refresh token expired → returns 401/403 and identity status updated to `suspended`
- Get re-authentication URL for expired identity → returns OAuth authorization URL for agent realm
- Re-authentication flow (OAuth callback) updates stored tokens and restores identity to `active` status

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

### Model Configuration Management
- Create a `ModelConfig` record specifying provider type (OpenAI, Anthropic, LiteLLM proxy, Other), API endpoint, and credentials (encrypted at rest)
- Read: list all model configurations with provider type chip and masked credential indicator
- Update: edit name, endpoint, provider type, and credentials; re-encryption triggered if credentials change
- Delete: remove a model configuration not referenced by any `AgentType`; reject deletion when referenced (409 Conflict)
- Provider type `litellm_proxy` accepts a proxy base URL with no API key required (or optional API key)
- Provider type `openai`, `anthropic`, etc. require API key field; key is stored encrypted and never returned in GET responses
- `GET /api/v1/model-configs/{id}/models` fetches the available model list from the configured provider using the stored credentials
- Available-models endpoint returns a clear error when the provider is unreachable or credentials are invalid (not a 500)
- `ModelConfigDialog` shows a "Fetch Available Models" action that calls the available-models endpoint; the returned list is rendered as checkboxes so the admin can enable or disable individual models
- Enabled models are stored in the `enabled_models` array on the `ModelConfig` record; unchecked models are excluded; a subsequent fetch after save shows the saved selection pre-checked
- `AgentTypeForm` shows a flat list of all enabled models aggregated across every active `ModelConfig` record; no two-level config→model selector; each list entry displays the model identifier and originating provider name for disambiguation
- Selecting a model from the flat list sets the `model_id` string field on `AgentType`; no FK to `ModelConfig` is created

### Agent Type Configuration (Modified)
- Create and update using new schema fields: `identity_id`, `role_id`, `model_id`, `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema`
- `identity_id` dropdown is populated only with identities that were created via the OAuth sign-in flow (agent realm users); identities with status `suspended` or `deprovisioned` are excluded or flagged
- `model_id` is a plain string field on `AgentType`; there is no FK from `AgentType` to `ModelConfig`; the form populates the model selector from the aggregated `enabled_models` list across all active `ModelConfig` records
- Selecting a model from the flat enabled-models list stores the model identifier string in `model_id`; the form does not allow saving without selecting a model
- At runtime, the dispatcher resolves `model_id` → `ModelConfig` by scanning all `ModelConfig.enabled_models` arrays; the first config whose `enabled_models` contains the `model_id` provides the endpoint and credentials for the LLM call
- Removed fields (`mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `model_config_id`, `model_name`) are rejected by the API
- `AgentTypeForm` renders correct fields for each `input_type` and `output_type` combination
- Identity selector rendered first; role selector shows ALL roles (not filtered by identity type)
- Create agent type with identity not assigned to selected role → client-side validation error shown before any API call
- Create agent type with identity assigned to selected role → form submits successfully and backend returns 201
- Changing the selected identity clears the role selection; user must re-select a compatible role

### Agent Instance Dashboard
- Dashboard page shows all agent instances across all agent types, not just types
- Each row displays: instance ID (truncated), agent type name, status chip (running/completed/failed/cancelled), submitted timestamp, and completed timestamp (if applicable)
- Status filter: selecting one or more statuses limits the list to matching instances; clearing filter restores all instances
- Time range filter: selecting a preset (last hour, last 24 h, last 7 days) or custom range limits instances to those submitted within that window
- Status and time filters can be combined
- Filters persist across navigations within the same session (component state or URL params)
- Clicking an instance row navigates to the instance detail page
- Pagination or virtual scroll handles large numbers of instances without UI degradation
- Empty state shown when no instances match the current filters

### Agent Instance Detail View
- Detail page shows: agent type name, status chip, submitted timestamp, completed/failed timestamp, duration, and submitting user
- Input section displays the structured arguments or initial conversation message used to launch the instance
- Output section displays the final result (structured or markdown) when status is `completed`; shows error message when `failed`; shows in-progress indicator when `running` or `queued`
- For conversational agents, a full conversation history section shows the ordered message thread (user messages and agent responses)
- Status chip on the detail page updates in real time while instance is `running` or `queued` (polling or websocket)
- Polling stops automatically when instance reaches a terminal status (`completed`, `failed`, `cancelled`)
- Metadata section shows model config name and model name used for the instance

### Permission Resolution
- `AgentPermissionManager` resolves the full chain: `AgentRole → SOPs → Skills → MCP tools` (via join traversal)
- Direct Skill assignments on a role also contribute their MCP tools
- Merged tool list contains no duplicates
- LRU cache returns consistent results for repeated calls with the same `role_id`
- Cache invalidation removes stale entry after role update or delete

### Runtime Identity-Role Validation
- At session launch, the runtime validates that the agent identity is explicitly assigned to the role via `agent_role_identity`
- Session launch rejected with `PermissionDeniedError` (403) when identity is not assigned to the role
- Session transitions to `failed` immediately on identity-role validation failure; observe-reason-act loop is not initiated
- Session error message contains identity-role assignment mismatch detail when validation fails
- Launch session with identity NOT assigned to role → PermissionDeniedError; session status set to `failed`
- Launch session with identity assigned to role → session proceeds normally (202 response)
- Remove identity-role assignment while session running → next session launch for that agent type fails with PermissionDeniedError

### Bidirectional Identity-Role Assignment
- Admin assigns identity to role from role dialog → identity appears in role's identity list without page reload
- Admin assigns role to identity from identity management view → role appears in identity's role list without page reload
- Both operations create the same `agent_role_identity` record (no duplicates)
- Removing the assignment from the role side removes the record and it no longer appears from the identity side
- Removing the assignment from the identity side removes the record and it no longer appears from the role side

### Token Management UI
- Identity list shows token status chips (`valid`, `expired`, `expiring soon`) per identity row
- Refresh button enabled only when refresh token is valid; disabled when refresh token is expired
- Re-auth button always enabled regardless of token state
- Clicking refresh triggers token refresh flow; on success, status chip updates to `valid` without page reload
- Clicking re-auth opens OAuth popup (or redirect) for agent realm authentication
- OAuth callback from re-auth flow updates stored tokens and closes popup; status chip updates to `valid`

### Communication Hub OAuth Enforcement
- Agent connection without an `Authorization` header returns 401
- Agent connection with an invalid or expired token returns 401
- Agent connection with a valid token but an unrecognized or unauthorized role claim returns 403
- Agent connection with a valid token and a recognized role claim returns 200 with the permitted tool list
- Tool list contains only tools associated with the agent's role (derived from assigned SOPs and Skills)
- Tool entries contain no `description` fields and no `schema` fields — bare `mcp_slug/tool_name` identifiers only
- Agent call to a tool not in the allowed set returns a permission denied error (not a 500 crash)
- Agent call to an allowed tool executes and returns the tool result

### Permission Reference Format
- All tool identifiers returned by `/api/v1/agents/roles/{id}/mcp-tools` use `mcp_slug/tool_name` format (e.g., `supabase/get_project`)
- No tool identifiers use the legacy `server_slug:tool_name` colon format (e.g., `supabase:supabase/get_project`)
- Agent runtime dispatches tool calls using `mcp_slug/tool_name` references throughout the observe-reason-act loop
- `AgentPermissionManager.is_allowed()` lookup resolves correctly for `mcp_slug/tool_name` keys
- Skill tool bindings store and return identifiers in `mcp_slug/tool_name` format only

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
- `AgentRuntimeExecutor` uses the **LangChain deep agent** framework, executing an observe-reason-act loop to orchestrate agent execution
- Each iteration of the observe-reason-act loop: agent observes tool results, reasons about the next step, and acts by calling a tool or producing a final answer
- `AgentRuntimeExecutor` enforces the role's permission boundary — tool calls outside the allowed set are rejected
- Result is written via `save_result` and session status transitions to `completed`
- Unrecoverable errors transition session to `failed` and persist `error_message`

### Execution Log Capture
- For every agent session, an `ExecutionLog` record is created containing the full system instruction and full user prompt as sent to the LLM at the start of execution
- System instruction stored in `execution_logs.system_instruction`; user prompt stored in `execution_logs.user_prompt`; neither field is truncated
- `GET /api/v1/agents/sessions/{id}/execution-logs` returns the execution log record for the given session
- Endpoint returns 404 when no execution log exists for the session (e.g., session still `queued`)
- Endpoint returns 403 when the requesting user does not own the session
- `AgentInstanceDetailPage` renders an "Execution Logs" section that displays system instruction and user prompt from the log record
- Execution log section is only shown when the session has a log record (not shown for `queued` sessions without one)

### Gateway Routing
- `LifecycleHandler` routes incoming launch requests through `AgentSessionService.enqueue` rather than direct executor invocation
- Session ID is returned synchronously from the gateway endpoint
- For conversational agents, gateway maintains bidirectional communication channel

### UI Components
- `AgentRoleListPage`: table renders all roles with SOP count and Skill count; create dialog opens from page header; edit and delete actions per row
- `AgentRoleDialog`: SOP and Skill multi-select; MCP tool preview panel debounced; edit-mode pre-populates existing assignments and loads preview on open
- `AgentIdentityListPage`: table renders all identities with identity_type chip, token status chip (`valid`/`expired`/`expiring soon`), and status chip; create/edit/delete actions; refresh token and re-auth actions per row
- `AgentIdentityDialog`: create/edit form; identity_type dropdown contains all three values; status dropdown; validates required fields
- `AssignIdentitiesToRoleDialog`: dialog opened from role management to assign or remove identities; displays current assignments and allows multi-select add
- `AssignRolesToIdentityDialog`: dialog opened from identity management to assign or remove roles; displays current assignments and allows multi-select add
- `AgentSessionLaunchDialog`: input form renders fields based on `input_type` (`none`, `typed`, `conversation`)
- `AgentJobPage`: result is rendered as structured output or markdown based on `output_type`; conversational agents show chat interface with message send box and message history
- `AgentManagementPage`: "Launch" action appears per agent type row and links to `AgentJobPage`; existing agent management table and actions unaffected
- `AgentTypeForm`: new fields render (`identity_id`, `role_id`, `system_instruction`, `input_type`, `output_type`); removed fields (`mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`) are absent
- All dialogs follow the Dialog Error Handling Standard (`dialogError` state, `PermissionDeniedAlert`, cleared on open/close)

### i18n Coverage
- All new UI strings use `t()` with keys under `agents.roles.*`, `agents.identities.*`, `agents.sessions.*`, `agents.types.*`, `agents.modelConfigs.*`, `agents.instances.*`
- No hardcoded English strings in any new or modified component

### Observability
- All new service operations emit OpenTelemetry traces
- Session status transitions logged with structured fields (session ID, agent type ID, status, timing)
- LangChain agent loop iterations (observe-reason-act cycles) included in trace spans with cycle index and tool call name

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
- WHEN an admin assigns an identity to a role via the role dialog THEN the assignment is persisted and the identity appears in the role's identity list
- WHEN an admin removes an identity from a role THEN the `agent_role_identity` record is removed and the identity no longer appears in the role's identity list
- WHEN an admin attempts to assign the same identity to a role a second time THEN the operation is either idempotent or returns 409 Conflict (no duplicate records created)
- E2E User Journey (assign identity to role): Navigate to Agent Roles → Open role dialog → Open "Assign Identities" → Select identity → Save → Verify identity appears in role's identity list without page reload

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
- WHEN a user opens the `AgentTypeForm` THEN a flat model selector displays all enabled models aggregated across all active `ModelConfig` records
- WHEN a user saves an agent type with a valid `identity_id`, `role_id`, and a selected `model_id` THEN the type is saved with the string model identifier and no FK to `ModelConfig`
- WHEN a user attempts to save an agent type without selecting a model THEN a validation error is shown and save is blocked
- WHEN the runtime dispatches a session THEN it resolves `model_id` by scanning all `ModelConfig.enabled_models` arrays to find the matching config; the matched config supplies endpoint and credentials for the LLM call
- WHEN no `ModelConfig` contains the agent type's `model_id` (e.g., the model was later disabled) THEN the session transitions to `failed` with a `ModelResolutionError` message
- WHEN a user opens `AgentTypeForm` THEN the identity selector is rendered first and the role dropdown shows ALL roles (not filtered by identity type)
- WHEN a user selects an identity and a role where the identity is NOT assigned to that role THEN client-side validation shows a clear error and form submission is blocked before any API call
- WHEN a user selects an identity and a role where the identity IS assigned to that role THEN the form submits successfully and the backend returns 201
- WHEN a user changes the selected identity THEN the role selection is cleared; user must re-select a role
- E2E User Journey (identity-role assignment validation): Open AgentTypeForm → Select identity → Select role where identity is NOT assigned → Verify client-side validation error before API call → Change to role where identity IS assigned → Submit → Verify 201

### Model Configuration Management

- WHEN an admin navigates to Model Configurations THEN the list shows all configs with provider type chip, endpoint, and masked credential indicator
- WHEN an admin creates a model config with provider type `openai` and an API key THEN the API key is stored encrypted and not returned in subsequent GET responses
- WHEN an admin creates a model config with provider type `litellm_proxy` THEN an endpoint URL field is shown and an API key is optional
- WHEN an admin creates a model config with provider type `anthropic` THEN an API key field is required
- WHEN an admin opens the edit dialog for an existing model config THEN the API key field is blank (not pre-populated) and other fields are pre-populated
- WHEN an admin updates credentials in the edit dialog THEN the new credentials are re-encrypted and stored, replacing the previous values
- WHEN the available-models endpoint is called for a valid model config THEN a list of model names is returned from the provider
- WHEN the available-models endpoint is called for a model config with invalid credentials THEN a clear 400/502 error is returned (not 500)
- WHEN `ModelConfigDialog` is opened (create or edit mode) and valid credentials are present THEN a "Fetch Available Models" action calls `GET /api/v1/model-configs/{id}/models` and displays the returned model list as checkboxes
- WHEN the fetch-models call fails (provider unreachable or invalid credentials) THEN the dialog shows an inline error and the checkbox list is not rendered; previously saved `enabled_models` are preserved
- WHEN an admin checks one or more model checkboxes and saves the model config THEN `enabled_models` on the saved record contains exactly the checked model identifiers
- WHEN an admin unchecks a previously enabled model and saves THEN that model identifier is removed from `enabled_models`; any `AgentType` whose `model_id` matches the removed model will fail resolution at runtime
- WHEN an admin attempts to delete a model config referenced by an AgentType THEN the API returns 409 and the UI displays the error
- WHEN an admin deletes an unreferenced model config THEN it is removed from the list without page reload
- WHEN `AgentTypeForm` loads THEN the model selector is populated with the union of `enabled_models` from all active `ModelConfig` records; no two-level config dropdown is shown
- WHEN an admin enables a new model in a `ModelConfig` and then opens `AgentTypeForm` THEN the newly enabled model appears in the flat model selector
- E2E User Journey (create model config — direct LLM): Navigate to Model Configurations → Click "Add Config" → Set provider type to `openai` → Enter name, endpoint, API key → Save → Verify new row appears in list with `openai` chip and masked credential indicator, without page reload
- E2E User Journey (create model config — LiteLLM proxy): Add Config → Set provider type to `litellm_proxy` → Enter name and proxy URL (no API key) → Save → Verify row appears with `litellm_proxy` chip
- E2E User Journey (fetch and enable models): Navigate to Model Configurations → Edit existing config → Click "Fetch Available Models" → Verify model checkboxes appear → Check two models → Save → Verify `enabled_models` in saved record contains exactly those two identifiers
- E2E User Journey (edit credentials): Open edit dialog for existing config → API key field is blank → Enter new key → Save → Verify row still present and credential indicator unchanged (key not exposed)
- E2E User Journey (delete conflict): Click Delete on a model config referenced by an AgentType → Verify 409 error shown in dialog
- E2E User Journey (agent type model selection): Navigate to create Agent Type → Verify flat model list shows all enabled models across all configs → Select a model → Save → Verify agent type saved with correct `model_id` string and no `model_config_id` in payload

### Agent Instance Dashboard

- WHEN a user navigates to the Agent Instances dashboard THEN all instances across all agent types are shown, not just agent types
- WHEN the list renders THEN each row shows agent type name, status chip, submitted timestamp, and (if terminal) completed timestamp
- WHEN a user applies a status filter of `running` THEN only running instances appear; completed/failed/cancelled instances are hidden
- WHEN a user applies multiple status filters (`completed` + `failed`) THEN instances with either status are shown
- WHEN a user clears all status filters THEN all instances are shown again
- WHEN a user selects a time range of "last 24 hours" THEN only instances submitted within that window are shown
- WHEN a user combines a status filter with a time range filter THEN only instances matching both criteria are shown
- WHEN no instances match the current filters THEN an empty state message is shown (not a blank table)
- WHEN a user clicks an instance row THEN they navigate to the instance detail page for that instance
- E2E User Journey (dashboard filters): Navigate to Agent Instances → Verify all instances listed → Apply status filter `completed` → Verify only completed instances visible → Apply time range "last 24 h" → Verify combined filter → Clear filters → Verify all instances restored
- E2E User Journey (navigate to detail): Click on a completed instance row → Verify navigation to detail page → Verify correct instance ID in URL/heading

### Agent Instance Detail View

- WHEN a user views a completed task-based instance THEN the input section shows the arguments provided at launch and the output section shows the final result rendered per `output_type`
- WHEN a user views a failed instance THEN the output section shows the error message and the status chip shows `failed`
- WHEN a user views a running or queued instance THEN the output section shows an in-progress indicator and the status chip updates in real time via polling
- WHEN a running instance reaches `completed` while the detail page is open THEN polling stops, the output section renders the result, and no further API calls are made
- WHEN a user views a conversational agent instance THEN a full conversation history section renders the ordered message thread (user turns and agent turns, in order)
- WHEN the detail page loads for a completed conversational instance THEN the conversation history shows all turns from launch to completion
- WHEN the detail page loads THEN a metadata section shows the model config name and model name used for the execution
- E2E User Journey (task instance detail): Click on a completed task instance → Verify input section, output section, status chip, timestamps, and model metadata are all present and correct
- E2E User Journey (conversational instance detail): Click on a completed conversational instance → Verify conversation history section is present with alternating user/agent messages in correct order
- E2E User Journey (in-progress instance detail): Click on a running instance → Verify in-progress indicator shown → (mock) Status advances to `completed` → Verify result renders and polling stops

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

### Execution Log Capture

- WHEN an agent session begins execution THEN `AgentRuntimeExecutor` creates an `ExecutionLog` record with the exact system instruction and user prompt sent to the LLM before any tool calls occur
- WHEN `GET /api/v1/agents/sessions/{id}/execution-logs` is called for a completed session THEN the response includes `system_instruction` and `user_prompt` fields with their full, untruncated content
- WHEN `GET /api/v1/agents/sessions/{id}/execution-logs` is called for a session that is still `queued` (no log written yet) THEN the endpoint returns 404
- WHEN `GET /api/v1/agents/sessions/{id}/execution-logs` is called by a user who does not own the session THEN the endpoint returns 403
- WHEN the system instruction template has been rendered with agent-specific variables THEN `execution_logs.system_instruction` contains the final rendered string (not the template)
- WHEN a session fails before the executor writes the execution log THEN no `ExecutionLog` record exists and the endpoint returns 404 (not a partially written record)
- WHEN the `AgentInstanceDetailPage` loads for a completed session THEN an "Execution Logs" section is visible and displays both the system instruction and the user prompt
- WHEN the `AgentInstanceDetailPage` loads for a `queued` session THEN the "Execution Logs" section is absent or shows a "Not yet available" state (no 404 errors exposed to the user)
- E2E User Journey (view execution logs): Navigate to Agent Instances → Click a completed instance → Scroll to Execution Logs section → Verify system instruction text and user prompt text are visible → Verify no truncation indicator is present for realistic-length instructions
- E2E User Journey (execution logs API — Real Backend): Launch a task agent session → Wait for `completed` status → Call `GET /api/v1/agents/sessions/{id}/execution-logs` → Verify 200 response with `system_instruction` and `user_prompt` fields populated

### LangChain Deep Agent Execution

- WHEN `AgentRuntimeExecutor` is invoked THEN it initializes a LangChain agent (not a LangGraph state graph) with the bound tools from the role's allowed set
- WHEN the agent's observe-reason-act loop calls a permitted tool THEN the result is fed back to the agent as an observation for the next reasoning step
- WHEN the agent's observe-reason-act loop calls a tool NOT in the role's allowed set THEN `AgentRuntimeExecutor` intercepts the call, logs a permission violation, and returns an error observation to the agent (does not crash the executor)
- WHEN the LangChain agent produces a final answer THEN the executor writes it as the session result and transitions the session to `completed`
- WHEN the LangChain agent exceeds the configured maximum iteration count THEN the executor transitions the session to `failed` with a `MaxIterationsExceeded` error message
- WHEN the agent runtime resolves skills THEN it uses the LangChain tool-binding mechanism (not LangGraph nodes) to expose permitted MCP tools to the agent
- E2E User Journey (observe-reason-act execution): Launch a task agent with a prompt that requires at least one tool call → (mocked) Verify the session transitions `queued → running → completed` → Verify the completed result reflects tool use → Verify execution log is present with the original user prompt

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

### Runtime Identity-Role Validation

- WHEN an `AgentType` has an identity that is NOT assigned to the role THEN launching a session returns 403 (`PermissionDeniedError`) and session status is set to `failed`
- WHEN a session fails identity-role validation THEN the session error message contains the identity-role assignment mismatch detail; the observe-reason-act loop is never initiated
- WHEN `GET /api/v1/agents/sessions/{id}/execution-logs` is called for a session that failed at identity-role validation THEN the endpoint returns 404 (no execution log was written)
- WHEN the identity IS assigned to the role THEN re-launching the session results in 202 and the session proceeds to `completed`
- WHEN an identity-role assignment is removed while a session using that identity-role pair is active THEN the next session launch for that agent type fails with `PermissionDeniedError`
- E2E User Journey (runtime identity-role validation): Create AgentType where identity is NOT assigned to the selected role → Launch session → Verify 403 and session status `failed` with mismatch error → Assign identity to role → Re-launch → Verify 202 and session reaches `completed`

### Communication Hub OAuth Enforcement

- WHEN an agent connects to the hub without an `Authorization` header THEN the hub returns 401
- WHEN an agent connects with an expired or signature-invalid token THEN the hub returns 401
- WHEN an agent connects with a valid token but an unrecognized or unauthorized role claim THEN the hub returns 403
- WHEN an agent connects with a valid token and a recognized role claim THEN the hub returns 200 with the permitted tool list
- WHEN the hub returns a tool list for a role granting access to N tools THEN exactly N tool identifiers are present and no additional tools are exposed
- WHEN the tool list is returned THEN each entry contains only a `mcp_slug/tool_name` identifier; no `description` or `schema` fields are present in any tool entry
- WHEN an agent calls a tool not in its allowed set THEN the hub returns a permission denied error (not 500)
- WHEN an agent calls an allowed tool THEN the hub executes the tool and returns the result successfully
- E2E User Journey (authenticated hub connection — mocked): Agent connects with valid token → Verify 200 and tool list returned → Verify each tool entry has no description or schema field → Call an unlisted tool → Verify permission denied → Call an allowed tool → Verify success
- E2E User Journey (unauthenticated rejection — mocked): Connect without Authorization header → Verify 401 → Connect with invalid token → Verify 401 → Connect with valid token and unrecognized role → Verify 403

### Permission Reference Format

- WHEN a Skill with MCP tool bindings is assigned to an AgentRole and `/api/v1/agents/roles/{id}/mcp-tools` is queried THEN every tool identifier in the response matches the `mcp_slug/tool_name` pattern (e.g., `supabase/get_project`)
- WHEN the response is inspected THEN no identifier uses the colon-delimited `server_slug:tool_name` format (e.g., `supabase:supabase/get_project` must not appear)
- WHEN the agent runtime dispatches a tool call during the observe-reason-act loop THEN it uses `mcp_slug/tool_name` as the lookup key for permission checking
- WHEN `AgentPermissionManager.is_allowed("supabase/get_project")` is called for a permitted tool THEN it returns `True`
- WHEN `AgentPermissionManager.is_allowed("supabase:supabase/get_project")` is called with the legacy colon format THEN it returns `False` (format not recognized)
- E2E User Journey (unified tool format): Assign Skill with MCP tool bindings to an AgentRole → Query `/api/v1/agents/roles/{id}/mcp-tools` → Verify every identifier matches `^[a-z0-9_-]+/[a-z0-9_-]+$` pattern → Launch agent session → Verify session calls tools successfully using `mcp_slug/tool_name` references

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

### Model Configuration
- **Credential exposure in API responses**: the API must never return plaintext API keys in GET responses — tests must assert the credential field is absent or masked in all list and detail responses.
- **Provider type mismatch**: a model config created as `litellm_proxy` used with an `openai`-specific API call path will fail silently at runtime. The available-models fetch must validate provider type compatibility.
- **model_id resolution failure**: if an admin disables a model (removes it from `enabled_models`) after an `AgentType` references it as `model_id`, the next session launch fails with `ModelResolutionError`; the error must surface as a clear session failure (status → `failed`, error_message populated), not a 500 crash.
- **model_id in multiple configs**: if the same model identifier appears in `enabled_models` of two different `ModelConfig` records, resolution must return the first match in a deterministic order (e.g., by config `created_at` ascending); tests must verify the ordering is stable across restarts.
- **Concurrent credential update and session launch**: if an admin updates model config credentials while a session is being dispatched, the executor may hold a reference to the old credentials. Tests should verify the executor fetches credentials at dispatch time, not at type-load time.

### Agent Instance Dashboard & Detail
- **Performance with many instances**: querying all instances without pagination could cause slow page loads. Tests must verify response time is acceptable (< 2 s) with 1000+ instances via an index on `(status, submitted_at)`.
- **Time zone handling**: time range filters must use UTC timestamps consistently. Tests should verify that "last 24 hours" is calculated server-side in UTC, not relying on client local time.
- **Real-time status on detail page**: if the polling interval is not cleared on unmount of the detail page, stale updates could arrive after navigation. Tests must verify interval teardown.
- **Conversation history ordering**: for conversational agents with many turns, the history section must display turns in correct chronological order. A test must assert order when turns are returned unsorted from the API.

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
| 4 | Users can define agent types with identity (OAuth-created), role, model config, system instruction, input/output config | Backend unit: agent type service tests; Frontend: `AgentTypeForm.test.tsx` (identity dropdown, model config selector); E2E: agent type CRUD suite |
| 4a | Admins can create agent identities by signing in to agent user accounts in the agent realm via OAuth; tokens stored securely | Backend unit: `test_agent_identity_service.py` (OAuth flow), `test_token_storage.py`; E2E: `agent-runtime.spec.ts` OAuth sign-in suite |
| 4b | System automatically refreshes agent tokens as needed for agent runtime operations | Backend unit: `test_token_refresh_service.py`; Backend integration: `test_agent_session_lifecycle.py` (expiry scenario); E2E: Real Backend suite (session launch with near-expiry token) |
| 4c | Bootstrap process initializes the agent realm in the identity provider, mirroring user realm setup | Backend unit: `test_realm_manager.py`; Backend integration: realm existence check after bootstrap; E2E: OIDC discovery URL reachable for agent realm |
| 5 | Platform admins can create, edit, and delete model configurations; credentials stored encrypted | Backend unit: `test_model_config_service.py`; Frontend: `ModelConfigListPage.test.tsx`, `ModelConfigDialog.test.tsx`; E2E: model config CRUD suite |
| 6 | System supports both direct LLM provider APIs and LiteLLM proxy as model backends | Backend unit: `test_model_config_service.py` (provider type variants); E2E: model config creation with `openai` and `litellm_proxy` types |
| 7 | Admins can fetch available models from each provider in `ModelConfigDialog` and select which to enable; enabled models aggregate into a flat list in `AgentTypeForm` | Backend unit: `test_model_config_service.py` (available-models endpoint, enabled_models storage/update, error handling); Frontend: `ModelConfigDialog.test.tsx` (fetch models action, checkbox select/deselect, enabled_models in save payload); `AgentTypeForm.test.tsx` (flat model list from all configs); E2E: fetch-and-enable models journey, agent type model selection flow |
| 8 | Agent types store `model_id` as a plain string with no FK to `ModelConfig`; runtime resolves model_id → ModelConfig via `enabled_models` scan | Backend unit: `test_model_binding.py` (model_id stored correctly, runtime resolution, ModelResolutionError when not found); Frontend: `AgentTypeForm.test.tsx` (model_id set on save, model_config_id absent from payload, old fields absent); Backend integration: `test_agent_session_lifecycle.py` (schema: model_id column present, model_config_id column absent) |
| 9 | Users can launch agents, provide required input, and track session status asynchronously | Backend integration: `test_agent_session_lifecycle.py`; Frontend: `AgentSessionLaunchDialog.test.tsx`, `AgentSessionPage.test.tsx`; E2E: session launch and tracking suite (task + conversational) |
| 10 | Agent requests are routed through the communication hub/gateway | Backend unit: `test_lifecycle_handler.py`; E2E: session launch journey verifies 202 + navigation (Real Backend suite) |
| 11 | Agents fetch and use only the SOPs, Skills, and MCP tools permitted by their assigned role | Backend unit: `test_permission_manager.py`, `test_agent_runtime_executor.py`; executor boundary enforcement tests |
| 12 | All agent actions, session statuses, and results are auditable and observable | Backend integration: `test_agent_session_lifecycle.py` verifies `AgentSession` records persist status, timing, output, and error fields; OTEL span emission verified |
| 13 | Agent instance dashboard shows all instances with status filtering, time filtering, and key metadata | Frontend: `AgentInstanceDashboard.test.tsx`; E2E: `agent-runtime.spec.ts` instance dashboard filter suite |
| 14 | Users can drill into an agent instance to view full execution history including input, output, and conversation | Frontend: `AgentInstanceDetailPage.test.tsx`; E2E: instance detail view suite (task + conversational variants) |
| 15 | Error handling and permission enforcement are consistent across all dialogs | Frontend component: `AgentRoleDialog.test.tsx`, `AgentIdentityDialog.test.tsx`, `AgentSessionLaunchDialog.test.tsx`, `ModelConfigDialog.test.tsx` — all verify `dialogError` state and `PermissionDeniedAlert` rendering |
| 16 | Out-of-scope actions (direct DB access, gateway bypass) are not possible | Backend unit: `test_agent_runtime_executor.py` permission boundary rejection; backend integration: verify no executor-bypass path exists |
| 17 | For conversational agents, the UI opens a chat interface for interactive communication | Frontend component: `AgentSessionPage.test.tsx` chat interface rendering; E2E: conversational agent launch journey |
| 18 | Execution logs for every agent run must include the full system instruction and user prompt as sent to the LLM, and these must be visible in the UI for each agent instance | Backend unit: `test_execution_log_service.py` (log creation, field completeness, 404 for queued, 403 for non-owner); Backend integration: `test_agent_session_lifecycle.py` (execution_logs table exists, log persisted on completed session, system_instruction and user_prompt populated); Frontend: `AgentInstanceDetailPage.test.tsx` (execution logs section present, fields rendered, absent for queued session); E2E: `agent-runtime.spec.ts` execution logs suite (mocked + real backend) |
| 19 | The agent runtime must use the LangChain deep agent framework, supporting skill-based execution and advanced SOP/Skill orchestration; LangGraph is not used | Backend unit: `test_agent_runtime_executor.py` (LangChain executor instantiates a LangChain agent, observe-reason-act loop verified, no LangGraph import); E2E: `agent-runtime.spec.ts` execution flow (tool call observed in log, session reaches `completed`) |
| 20 | Permission references use unified `mcp_slug/tool_name` format (not `server_slug:tool_name`) | Backend unit: `test_permission_manager.py` (`is_allowed()` returns True for `/`-format, False for colon format); Backend integration: `test_agent_session_lifecycle.py` (role mcp-tools endpoint returns identifiers in `/`-format only); E2E: `agent-runtime.spec.ts` unified tool format suite |
| 21 | Identity-role assignments are managed explicitly via many-to-many join; bidirectional UI from role and identity views | Backend unit: `test_agent_role_identity_assignments.py` (assign, remove, list, idempotent, 404 on missing); Backend integration: `test_agent_session_lifecycle.py` (`agent_role_identity` table exists with correct FK constraints); Frontend: `AssignIdentitiesToRoleDialog.test.tsx`, `AssignRolesToIdentityDialog.test.tsx`; E2E: `agent-runtime.spec.ts` bidirectional assignment suite |
| 22 | Identity selector shown first in `AgentTypeForm`; role selector shows ALL roles; client-side validation prevents saving when identity is not assigned to selected role | Frontend: `AgentTypeForm.test.tsx` (identity selector rendered first, all roles shown in dropdown, validation error when identity not assigned to role, success when assigned, role cleared on identity change); E2E: `agent-runtime.spec.ts` identity-role assignment validation journey |
| 23 | Runtime validation: agent identity must be explicitly assigned to the role; unassigned identity-role pair → PermissionDeniedError | Backend unit: `test_agent_runtime_executor.py` (unassigned identity → session `failed` with PermissionDeniedError, no executor loop initiated); Backend unit: `test_agent_role_identity_assignments.py` (assignment lookup logic); Backend integration: `test_agent_session_lifecycle.py` (real launch with unassigned identity returns 403); E2E: `agent-runtime.spec.ts` runtime identity-role validation suite |
| 24 | Communication hub requires agent identity OAuth token; validates role authorization | Backend unit: `test_communication_hub.py` (no token → 401, invalid token → 401, valid token wrong role → 403, valid token correct role → 200); E2E: `agent-runtime.spec.ts` hub OAuth enforcement suite (mocked) |
| 25 | Communication hub exposes only role-permitted tools; no descriptions or schemas in tool list | Backend unit: `test_communication_hub.py` (tool count matches role, no description field, no schema field per entry, disallowed call → permission denied, allowed call → success); E2E: `agent-runtime.spec.ts` role-based tool exposure suite (mocked) |
| 26 | Token refresh restores expired agent access token when refresh token is still valid; identity suspended when both tokens expired | Backend unit: `test_token_refresh.py` (success path with valid refresh token, both-expired → `suspended` status, concurrent refresh safety); Backend integration: `test_agent_session_lifecycle.py` (expiry scenario with real token state); E2E: Real Backend suite (session launch with near-expiry token) |
| 27 | Token management UI shows token status chips per identity and provides refresh/re-auth actions | Frontend: `AgentIdentityListPage.test.tsx` (token status chip rendered, refresh button enabled/disabled per state, re-auth button always enabled); Frontend: `AgentIdentityDialog.test.tsx` (re-auth URL displayed); E2E: `agent-runtime.spec.ts` token management UI suite (mocked) |

---

## 6. Test File References

All paths below are relative to the workspace root, as defined in `docs/config.yaml` under `source.tests`.

### Backend Unit Tests (`backend/tests/unit/`)

| File | Tests | Coverage |
|------|-------|----------|
| `backend/tests/unit/test_agent_role_service.py` | 14 | `AgentRoleService` CRUD (create, list, read-by-id, update, delete), cache invalidation, SOP/Skill assignment replacement; identity assignment list returns correct records; removal of non-existent identity assignment returns 404 |
| `backend/tests/unit/test_agent_role_identity_assignments.py` | 7 | Bulk assign identities to role persists `agent_role_identity` records; remove identity from role deletes record; list identities assigned to role returns correct set; assign same identity twice is idempotent or returns 409; remove identity not assigned to role returns 404; assignment lookup used by runtime validator returns correct boolean; assignment record absent after removal confirms true deletion |
| `backend/tests/unit/test_agent_identity_service.py` | 14 | Identity CRUD (new realm_name/realm_username model), OAuth sign-in flow (authorize redirect targets agent realm, callback token storage with encryption, not-found guard), status transitions, conflict detection |
| `backend/tests/unit/test_realm_manager.py` | 7 | `RealmManager` skips external/unconfigured providers, resolves realm name from explicit arg → yaml → default `ai_agents`, `keycloak_auth_failed` on unreachable Keycloak, `realm_creation_failed` on conflict, `realm_exists` returns True/False without raising |
| `backend/tests/unit/test_token_refresh_service.py` | 8 | Proactive refresh within expiry window, new encrypted tokens stored after refresh, refresh token rotated, expired refresh token → identity `suspended` + `TokenRefreshError`, missing refresh token raises, missing identity raises, `refresh_expiring_soon` returns count / skips failed and continues / returns 0 when none due |
| `backend/tests/unit/test_token_refresh.py` | 5 | Token refresh when access token expired but refresh token valid → success and new tokens stored; token refresh when both access and refresh tokens expired → 401/403 and identity set to `suspended`; get re-auth URL for expired identity → returns OAuth authorization URL for agent realm; re-authentication flow (OAuth callback) updates tokens and restores identity to `active`; concurrent refresh for same identity does not duplicate update |
| `backend/tests/unit/test_model_config_service.py` | 16 | `ModelConfigService` CRUD; credential encryption on create and re-encryption on update; GET responses do not include plaintext credentials; `get_available_models` for each provider type (`openai`, `anthropic`, `litellm_proxy`); `get_available_models` returns structured error on provider unreachable or invalid credentials; delete blocked when referenced by AgentType (409 — using enabled_models scan, not FK); `enabled_models` stored on create; `enabled_models` updated on update; `fetch_available_models` returns enabled_models list when non-empty; `fetch_available_models` falls back to live provider query when enabled_models is empty; provider type `litellm_proxy` allows optional API key |
| `backend/tests/unit/test_model_binding.py` | 9 | `AgentType.model_id` string field stored correctly; no `model_config_id` FK on AgentType ORM; runtime `ModelBindingLayer.resolve_model_config(model_id)` scans all `ModelConfig.enabled_models` and returns matching config; raises `ModelBindingError` when no config contains the model_id; raises `ModelBindingError` when no configs exist; `litellm_proxy` config resolved correctly via enabled_models; `enabled_models` saved and updated correctly on `ModelConfig`; disabled model removed from `enabled_models` causes resolution failure; resolution succeeds after re-enabling a previously disabled model; resolution returns first matching config when model_id appears in multiple configs (deterministic order) |
| `backend/tests/unit/test_agent_session_service.py` | 11 | Enqueue, state transitions (`queued→running→completed`, `queued→running→failed`), list filtering |
| `backend/tests/unit/test_agent_runtime_executor.py` | 16 | LangChain agent instantiation (no LangGraph state graph); observe-reason-act loop iteration with permitted tool call; permitted tool call result returned as observation; disallowed tool call intercepted and permission violation logged; executor produces final answer → session `completed`; executor exception → session `failed`; max iteration limit exceeded → `MaxIterationsExceeded` session `failed`; permission denied at session start → `failed`; success → `completed`; execution log written before first tool call; execution log `system_instruction` matches rendered instruction; execution log `user_prompt` matches session input; identity NOT assigned to role at launch → session `failed` with `PermissionDeniedError`; observe-reason-act loop not initiated when identity-role assignment validation fails |
| `backend/tests/unit/test_execution_log_service.py` | 8 | `ExecutionLogService.create_log` persists `system_instruction` and `user_prompt` untruncated; GET returns log for session owner; GET returns 403 for non-owner; GET returns 404 when no log exists (queued session); log fields are full strings (not templates or placeholders); no log created when session fails before executor start; log created exactly once per session (no duplicates on retry); system_instruction field contains rendered instruction (not template string) |
| `backend/tests/unit/test_agent_instance_manager.py` | 5 | `AgentInstanceManager` lifecycle |
| `backend/tests/unit/test_agent_gateway.py` | 3 | Agent Gateway routing |
| `backend/tests/unit/test_communication_hub.py` | 8 | Hub OAuth token validation (no token → 401, invalid token → 401, wrong role → 403, correct role → 200); tool list restricted to role-permitted tools only; tool entries have no description or schema field; disallowed tool call → permission denied; allowed tool call → success |
| `backend/tests/unit/test_permission_manager.py` | 9 | Full role-to-tool chain resolution (SOPs → Skills → MCP tools); direct Skill assignment contributes tools; merged list has no duplicates; circular SOP dependency resolved without recursion; cache hit returns consistent result; cache invalidated on role write; `is_allowed()` returns True for `mcp_slug/tool_name` format; `is_allowed()` returns False for legacy `server_slug:tool_name` colon format; `/mcp-tools` endpoint returns identifiers in `/`-format only |

### Backend Integration Tests (`backend/tests/integration/`)

| File | Tests | Coverage |
|------|-------|----------|
| `backend/tests/integration/test_agent_session_lifecycle.py` | 40 | All new tables exist (agent_roles, agent_identities, agent_jobs, agent_role_sops, agent_role_skills, **agent_role_identity**, model_configs, **execution_logs**); `agent_role_identity` table has `agent_role_id` and `agent_identity_id` columns with correct FK constraints; `model_configs` has provider_type, api_base_url, encrypted_api_key, **enabled_models** columns; `execution_logs` table has `session_id`, `system_instruction`, `user_prompt` columns; agent_types has `model_id` column (plain string); agent_types does NOT have `model_config_id` or `model_name` columns (verified via PRAGMA table_info); agent_types has new columns (identity_id, role_id, input_type, output_type); removed old columns absent; full CRUD lifecycle for roles/identities/model_configs; `enabled_models` persisted on create and updated correctly; runtime `ModelBindingLayer.resolve_model_config(model_id)` returns correct ModelConfig from real DB; `ModelBindingError` raised against real DB when no config contains model_id; delete ModelConfig blocked when AgentType.model_id matches enabled_models entry (409); session state machine with real DB; encrypted credential storage verified; execution log created for a completed session against real DB; `execution_logs.system_instruction` and `execution_logs.user_prompt` are populated and untruncated; no execution log record exists for a `queued` session; session launch with identity NOT assigned to role returns 403 and sets status to `failed` |
| `backend/tests/integration/test_realm_bootstrap.py` | 5 | Bootstrap skips for external provider; creates agent realm for keycloak_bundled with configured name; registers OIDC client; idempotency surfaces `realm_creation_failed`; structured error code present |

### Frontend Component Tests (`frontend/src/__tests__/`)

| File | Tests | Coverage |
|------|-------|----------|
| `frontend/src/__tests__/AgentRoleListPage.test.tsx` | 6 | Table renders all roles; SOP count chip; Add/Edit/Delete actions |
| `frontend/src/__tests__/AgentRoleDialog.test.tsx` | 9 | Create/edit dialog; required field validation; PermissionDeniedAlert; error cleared on close; rerender without double-wrap; identity assignment count chip rendered; assign identities button opens `AssignIdentitiesToRoleDialog`; removing identity from assignment list removes record; save reflects current assignments |
| `frontend/src/__tests__/AssignIdentitiesToRoleDialog.test.tsx` | 6 | Dialog opens from role management; current assigned identities listed; selecting identity adds to assignment; removing identity from list removes assignment; save persists changes via bulk POST and DELETE; PermissionDeniedAlert on 403 |
| `frontend/src/__tests__/AssignRolesToIdentityDialog.test.tsx` | 6 | Dialog opens from identity management; current assigned roles listed; selecting role adds to assignment; removing role from list removes assignment; save persists changes via bulk POST and DELETE; PermissionDeniedAlert on 403 |
| `frontend/src/__tests__/AgentIdentityListPage.test.tsx` | 11 | Table renders realm_name and realm_username columns; token active chip when token_expires_at is future; no-token indicator when null; status chips; OAuth section column header; Add Identity button opens dialog |
| `frontend/src/__tests__/AgentIdentityDialog.test.tsx` | 12 | Create mode: realm_name/realm_username fields present, no OAuth button; Edit mode: pre-populates all three fields, OAuth sign-in button present, authorize endpoint called, error shown on failure; Save enabled only when all three required fields filled; error cleared on reopen |
| `frontend/src/__tests__/AgentOAuthCallbackPage.test.tsx` | 5 | Loading spinner while processing; AGENT_OAUTH_SUCCESS posted to opener on success; AGENT_OAUTH_ERROR on IdP error param; AGENT_OAUTH_ERROR on missing code/state; AGENT_OAUTH_ERROR on backend API failure |
| `frontend/src/__tests__/ModelConfigListPage.test.tsx` | 8 | Table renders all configs with provider type chip; masked credential indicator present (API key not shown in text); Add/Edit/Delete action buttons; empty state when no configs exist; provider type chip variant for `litellm_proxy` vs. `openai` vs. `anthropic` |
| `frontend/src/__tests__/ModelConfigDialog.test.tsx` | 16 | Create mode: provider type selector renders all types; API key field required for `openai`/`anthropic`; API key optional for `litellm_proxy`; endpoint URL field present; Save blocked when required fields missing; "Fetch Available Models" button visible in edit mode and NOT in create mode; button calls available-models API and renders model checkboxes; checking models includes identifiers in enabled_models payload; fetch failure shows inline error (no checkboxes rendered, existing enabled_models preserved); edit mode renders enabled_models count hint; save payload always includes enabled_models array; PermissionDeniedAlert on 403; error cleared on reopen; 409 conflict error shown on delete |
| `frontend/src/__tests__/AgentTypeForm.test.tsx` | 23 | New fields present (identity_id, role_id, model_id, system_instruction, input_type, output_type); flat model selector present (aggregates enabled_models across all ModelConfigs); model_id set correctly on AgentType payload on save; no model_config_id field or two-level config selector rendered; no model_name sub-selector; old fields absent (mode, max_instances, sop_id); flat list populated from all-enabled-models API call on render; empty state shown when no models are enabled across any config; input schema shown/hidden per input_type; enabled models from multiple configs appear together in a single flat list; identity selector rendered before role selector; role dropdown shows ALL roles (not filtered by identity type); client-side validation error when selected identity is not assigned to selected role; form submission blocked when identity not assigned to role; role selection cleared when identity changes |
| `frontend/src/__tests__/AgentManagementPage.test.tsx` | 9 | Launch button opens dialog; Edit action; aria-label on IconButtons |
| `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx` | 6 | Info Alert for none input_type; submit flow; PermissionDeniedAlert |
| `frontend/src/__tests__/AgentSessionPage.test.tsx` | 9 | Queued/completed/failed status rendering; status text in chip + Paper; scrollIntoView mock; chat interface renders for conversational session; message history displayed in chat view |
| `frontend/src/__tests__/AgentInstanceDashboard.test.tsx` | 10 | All instances rendered across agent types; status chip per row; submitted timestamp and completed timestamp columns; status filter single selection; status filter multi-selection; time range filter "last 24 h"; combined status + time filters; empty state when no results match; clicking row navigates to detail; pagination/virtual scroll renders without overflow |
| `frontend/src/__tests__/AgentInstanceDetailPage.test.tsx` | 14 | Input section renders arguments or initial message; output section renders structured result for `typed` output; output section renders markdown for `markdown` output; failed instance shows error message in output section; running instance shows in-progress indicator; status chip updates on poll; polling stops on terminal status; conversation history section renders for conversational agent (ordered turns); metadata section shows model config name and model name; polling interval cleared on unmount; execution logs section visible for completed session; `system_instruction` text rendered in execution logs section; `user_prompt` text rendered in execution logs section; execution logs section absent (or shows unavailable state) for `queued` session |

### E2E Tests (`e2e/tests/`)

| File | Tests | Backend | Coverage |
|------|-------|---------|----------|
| `e2e/tests/agent-management.spec.ts` | 6 pass | Mocked | Agent management page renders; agent type list; input_type chip; create dialog opens |
| `e2e/tests/agent-runtime.spec.ts` | 42+ pass, 4 skip | Mocked (real-backend tests skip when backend not running) | Agent role management (CRUD, **bidirectional identity assignment suite**), OAuth identity sign-in flow (realm_name/realm_username columns, token active chip, OAuth button in edit dialog — mocked authorize endpoint), **token management UI suite** (token status chips rendered, refresh button enabled/disabled per token state, re-auth button always enabled, refresh updates chip — mocked), agent type configuration (model_id field used in mock data, no model_config_id or model_name, flat model selector shows enabled_models across all configs, **identity-role assignment validation** — role dropdown shows all roles, client-side error when identity not assigned to selected role, success when assigned), model config CRUD (create with openai provider, create with litellm_proxy provider, enabled_models in mock data, Fetch Models button in edit dialog, edit without exposing key, delete conflict, real-backend model-configs table with enabled_models column), agent instance dashboard (all instances listed, status chips, filter status, filter time, empty state, navigate to detail), conversation history display (chat interface for conversational session, metadata for completed session), session launch dialog, session status pages (queued/completed/failed), **execution logs suite** (mocked: detail page shows execution logs section with system instruction and user prompt for completed session; execution logs section absent for queued session; real-backend: GET /agents/sessions/{id}/execution-logs returns 200 with system_instruction and user_prompt after session completes), **LangChain execution flow** (mocked observe-reason-act: session completes after tool call step; execution log present; no LangGraph references in network responses), **runtime identity-role validation suite** (identity NOT assigned to role → 403 + failed status; assign identity to role → session succeeds; remove assignment → next session fails), **bidirectional assignment suite** (assign identity to role from role dialog → appears in role's list; assign role to identity from identity view → appears in identity's list; remove from either side removes record), **hub OAuth enforcement suite** (no token → 401; invalid token → 401; wrong role → 403; correct role → 200 + tool list with no descriptions/schemas; unlisted tool call → permission denied), **unified tool format suite** (role mcp-tools endpoint returns `mcp_slug/tool_name` format only; session calls tools successfully with `/`-format), real-backend integration variants |
| `e2e/tests/agent-bootstrap.spec.ts` | 5 pass, 1 skip | Mocked + Real Keycloak (skipped when Keycloak not running on port 8082) | Health endpoint reports identity provider status; identities page loads with realm name column when realm initialized (mocked); configured agent realm name displayed; agent realm OIDC discovery endpoint reachable; user realm unaffected; backend health reports agent_realm_initialized |
| `e2e/tests/agent-bootstrap.spec.ts` | 3 pass, skipped when Keycloak not running | Real Keycloak | Realm OIDC discovery endpoint reachable; agent realm distinct from user realm; bootstrap idempotency (run twice, no error) |

The 4 skipped tests in `agent-runtime.spec.ts` are the "Real Backend Integration" suite — they run only when the backend is reachable at `http://localhost:8000` and validate that the DB migration has been applied (including `model_configs`, `execution_logs` tables and new `agent_types` columns). One of the four is dedicated to the `GET /agents/sessions/{id}/execution-logs` endpoint against the real backend.

---

## 7. Pre-Test Checklist

Before executing any test suite for this change:

- [ ] Run `alembic upgrade head` and verify output shows new migration applied
- [ ] Run `alembic current` and confirm the revision matches the migration created for this change
- [ ] Confirm new tables exist: `agent_roles`, `agent_role_sops`, `agent_role_skills`, `agent_identities`, `agent_jobs`, `model_configs`
- [ ] Confirm `model_configs` table includes `provider_type`, `endpoint`, `credentials_enc`, and `enabled_models` columns
- [ ] Confirm removed columns are absent on `agent_types`: `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `model_config_id`, `model_name`
- [ ] Confirm new column present on `agent_types`: `model_id` (string, no FK constraint to model_configs)
- [ ] Confirm `AgentSkillAssignment` table is dropped
- [ ] Confirm `agent_identities` table includes `access_token_enc` and `refresh_token_enc` columns (encrypted token storage)
- [ ] Start all services via `.\parthenon.ps1 start` and verify health checks pass
- [ ] Confirm backend responds at `http://localhost:8000/health`
- [ ] Confirm frontend serves at `http://localhost:5173`
- [ ] Confirm Keycloak agent realm is initialized: `http://localhost:8082/realms/<agent_realm>/.well-known/openid-configuration` returns 200
- [ ] Confirm agent realm name in `config/identity.yaml` (or equivalent bootstrap config) matches the realm initialized in Keycloak
- [ ] Confirm `execution_logs` table exists with columns: `id`, `session_id`, `system_instruction`, `user_prompt`, `created_at`
- [ ] Verify `GET /api/v1/agents/sessions/{id}/execution-logs` returns 200 for a completed session and 404 for a queued session
- [ ] Confirm no LangGraph packages are imported in `backend/app/services/agent_runtime_executor.py` (LangChain deep agent framework only)
- [ ] Confirm `agent_role_identity` join table exists with columns: `agent_role_id`, `agent_identity_id` (composite PK or unique constraint enforced)
- [ ] Confirm `agent_roles` table does NOT include `allowed_identity_types` column (architectural correction applied)
- [ ] Spot-check `GET /api/v1/agents/roles/{id}/mcp-tools` for a role with known tool bindings and verify every identifier matches `mcp_slug/tool_name` format (no colon-delimited identifiers)
- [ ] Confirm communication hub endpoint is accessible at the configured port (check `config/identity.yaml` or environment variables for hub host/port)
