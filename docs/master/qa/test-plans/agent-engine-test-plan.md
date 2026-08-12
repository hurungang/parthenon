# Agent Engine Test Plan

## What to Test
- AgentType CRUD operations with rearchitected schema fields (`identity_id`, `role_id`, `model_id`, `system_instruction`, `input_type`, `output_type`)
- Removed fields (`mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `model_config_id`, `model_name`) rejected by API
- Agent instance lifecycle management
- `AgentManagementPage` "Launch" action opens `AgentJobLaunchDialog` with input form driven by `input_type`
- `AgentJobPage`: polls every 3 seconds for `queued`/`running` sessions; stops on terminal status; interval cleared on unmount
- Session result rendered per `output_type` (`typed` → structured view; `markdown` → formatted markdown)
- Conversational agents: `AgentJobPage` shows chat interface with message history and send box
- Permission enforcement on all agent endpoints (`agent:read`, `agent:create`, `agent:update`, `agent:delete`)
- 403 structured error responses with resource type, action, and resource ID
- Permission-denied UI rendering: snackbar with "Request Access" button on 403 from agent endpoints
- All dialogs follow Dialog Error Handling Standard (`dialogError` state, `PermissionDeniedAlert`, cleared on open/close)
- i18n: all new strings use `t()` with keys under `agents.types.*`, `agents.instances.*`, `agents.sessions.*`

### Agent Type Binding Validation (enforce-agent-type-bindings change)
- `validate_bindings()` rejects SOP binding whose `sop_id` is not in the assigned role's permitted SOPs — returns 422 with `{"error": "binding_validation_failed", "messages": [...]}`
- `validate_bindings()` rejects Skill binding whose `skill_id` is not in the assigned role's permitted skills — returns 422 with per-entry message
- `validate_bindings()` rejects duplicate `sop_id` across multiple binding entries — returns 422
- `validate_bindings()` rejects duplicate `skill_id` across multiple binding entries — returns 422
- `validate_bindings()` rejects bindings when `role_id` is null — returns 422
- Backend enforces at-least-one-binding requirement: create/update with empty `sop_bindings` and `skill_bindings` returns 400 "Agent types must specify at least one SOP or Skill binding"
- Binding CASCADE delete: deleting an agent type removes associated binding rows
- Binding data round-trip: POST create returns `sop_bindings[]` and `skill_bindings[]` in response; GET reads them back

### Agent Plan Mode (agent-plan-mode change)
- `PlanGenerationService`: traverses role→SOP→Skill→Tool graph, constructs LLM prompt, invokes LLM, parses structured plan steps; upserts `AgentPlan` row on every save (no duplicate rows)
- `PlanGenerationService`: non-blocking failure — LLM timeouts and parse errors written as `generation_status = failed`; no exception propagates to the API handler
- `PlanGenerationService`: `agent_config_hash` is deterministic for the same `role_id`, `primary_sop_id`, and `system_instruction`; changes when any input changes
- `PlanGenerationService`: no-role path — agent type with no `role_id` produces empty plan steps and empty topology without error
- `TopologyBuilderService`: all four node types (`role`, `sop`, `skill`, `tool`) produce correctly typed node objects with deterministic IDs
- `TopologyBuilderService`: duplicate tools via multiple skill paths produce exactly one node and de-duplicated edges
- `TopologyBuilderService`: empty graph (no role/SOPs/skills/tools) produces empty nodes and edges, not an error
- `POST /api/v1/agents/types` and `PUT /api/v1/agents/types/{type_id}` both include a `plan` field in the response with `plan_steps`, `topology_nodes`, `topology_edges`, `generation_status`, `generation_error`, and `agent_config_hash`
- `agent_plans` table schema: `information_schema` verification that table, columns, nullability, unique constraint on `agent_type_id`, and CASCADE delete rule are all present after migration
- `PlanPreviewModal`: opens automatically after a successful agent type save; renders plan steps as an ordered list with step-type chips; shows `generation_error` when `generation_status = failed`; calls `onClose` callback when close button clicked
- `PlanPreviewModal`: follows Dialog Error Handling Standard (`dialogError` state cleared on open, displayed as `PermissionDeniedAlert` at top of `DialogContent`)
- `TopologyDiagramRenderer`: renders without throwing for valid non-empty payload; differentiates node types visually; renders gracefully for empty nodes/edges
- `AgentManagementPage` plan state: `planData` set to `plan` from save response immediately after successful create/update; `PlanPreviewModal` opened before `setDialogOpen(false)`; plan state cleared when modal dismissed; re-opening create/edit dialog does not re-open the plan modal
- i18n: all plan preview strings use `t()` with keys under `agents.plan.*` namespace; no hardcoded English in `PlanPreviewModal` or `TopologyDiagramRenderer`

### Execution Log Display (user-friendly-agent-logs change)
- `LogPresenter` data transformation: parses identity, role, model, and SOPs/skills from `system_instruction`; classifies entries by `event_type` into working steps (`llm_call`, `tool_call`, and fallback for other types); derives overall result status from the final log entry; builds raw log string from all timestamped entries
- `LogPresenter` graceful handling: empty `entries` array produces empty step list and neutral result status without error; missing or empty `system_instruction` defaults all summary fields without throwing
- `LogSummaryPanel` rendering: displays identity, role, and model fields; SOPs/skills rendered as individual chips; plan progress displayed; result status badge reflects correct visual state for success, failure, and running states
- `WorkingStepsPanel` collapse behaviour: collapsible section closed on first render; header click expands/collapses; individual step detail blocks expand and collapse independently; top-level flat steps always visible regardless of collapsible state
- `RawLogToggle` interaction: toggle reflects `rawMode` prop; `onChange` callback fires on interaction; clipboard copy button visible only when `rawMode` is active; copy button writes full raw log text to clipboard
- `LogViewer` routing: summary panel and working steps panel rendered in friendly mode; monospace raw log block rendered in raw mode; `RawLogToggle` always present in header
- `AgentJobPage` regression: `LogViewer` renders in place of old raw execution log section; "View Execution Logs" button and `SessionExecutionLogsDialog` trigger absent from page; partial log displays without crash when session is still running

### Delegation Visibility and Live Session Stream (agent-delegation-visibility change)
- Conversation-status transport forwards thinking/delegating/waiting/final states in order and preserves terminal timeout/failure signaling
- Delegation target display text is normalized from internal tool naming to user-readable `Delegating to agent <agent_type>`
- Chat surfaces fold delegation snippets by default, retain concise preview context, and preserve expand/collapse interaction state
- Running non-conversation sessions append execution logs live via stream path with deterministic ordering and terminal reconciliation
- Pull fallback remains compatible during stream interruption/reconnect and does not duplicate or lose final status

## Critical Scenarios
- User without `agent:read` receives 403 on `GET /api/v1/agents/types`; UI shows permission-denied snackbar
- User without `agent:create` receives 403 on `POST /api/v1/agents/types`; snackbar pre-filled with resource type and action
- User with correct permission completes full agent CRUD flow without error
- Create agent type: identity selector rendered first; selecting identity clears role when identity changed
- Create agent type without selecting a model → form validation error; save blocked
- Launch task agent: dialog with typed input → 202 → `AgentJobPage` polls → `completed` → result rendered
- Launch conversational agent: dialog with chat input → `AgentJobPage` shows chat interface
- `GET /api/v1/agents/sessions/{id}/result` on in-progress session returns 409
- Stuck agent instances do not hang silently — recovery mechanism or timeout applies

### Execution Log Display (user-friendly-agent-logs change)
- Valid `ExecutionLogRead` with all fields → `LogSummary` contains correct identity, role, model, and ordered list of SOPs/skills
- `entries` mix of `llm_call` and `tool_call` types → each entry classified into correct working step type with appropriate icon and message
- Final entry with success indicator → result status is `success`; final entry with failure indicator → result status is `failure`
- Empty `entries` array → empty working step list; result status neutral; no exception thrown
- Missing `system_instruction` → all summary fields default gracefully; no unguarded property access
- `LogSummaryPanel` with multiple SOPs/skills → each rendered as a separate chip element
- `LogSummaryPanel` result status badge: success state displays correct colour and label; failure state displays correct colour and label; running state shows in-progress indicator
- `WorkingStepsPanel`: collapsed on first render; expands on header click; collapses again on second click; only the clicked step's detail block visible when expanded; other steps remain collapsed
- `RawLogToggle` with `rawMode` false → copy button not visible; toggle to true → copy button visible; click copy → clipboard written with full raw log text
- `LogViewer` mode switching: friendly mode shows summary and working steps; toggle to raw → replaced by monospace log block; toggle back → summary and working steps restored
- `AgentJobPage` with completed session → no "View Execution Logs" button or `SessionExecutionLogsDialog` trigger present on page
- `AgentJobPage` with running session → `LogViewer` renders with partial log data; no crash

### Delegation Visibility and Live Session Stream (agent-delegation-visibility change)
- Conversational run starts without immediate delegation: thinking state is visible in chat before handoff begins
- Delegation starts from internal tool name: chat shows normalized `Delegating to agent <agent_type>` label and transitions to waiting
- Delegation times out or fails: waiting state resolves to a clear terminal timeout/failure status
- Delegation snippets arrive during chat: snippets remain folded by default and can be expanded/collapsed without disturbing message continuity
- Non-conversation running session receives stream updates: new log rows append without manual refresh and terminal completion state is rendered once
- Stream interruption occurs mid-run: fallback path reconciles final status without duplicate terminal rows

## Edge Cases
- Permission revoked mid-session; next request denied
- Session dispatcher race condition: `SKIP LOCKED` prevents double-dispatch under concurrent dispatchers
- `model_id` resolution failure (model disabled after `AgentType` created) → session status `failed` with `ModelResolutionError`

### Agent Plan Mode
- Create agent type with full role/SOP/skill/tool graph → `plan.generation_status = success` → `plan_steps` non-empty → `agent_plans` row upserted (not duplicated on second save)
- Plan generation failure is non-blocking: save returns 201/200; `plan.generation_status = failed` and `generation_error` populated; no 500 or uncaught exception
- Saving agent type with no `role_id` → `plan` field present with empty `plan_steps` and empty `topology`
- `agent_plans` CASCADE delete: delete `AgentType` → associated `AgentPlan` row also deleted
- `agent_config_hash` changes when `system_instruction`, `role_id`, or `primary_sop_id` changes; same inputs → same hash
- If save API call fails (403, 500), `AgentManagementPage` shows error in dialog via Dialog Error Handling Standard; plan modal is NOT opened

### Execution Log Display (user-friendly-agent-logs change)
- Empty `entries` array: summary panel renders; working steps panel shows no step rows; collapsible section renders without crash
- Single entry with no LLM iterations: collapsible section contains one row; no visual breakage
- `system_instruction` absent: summary fields silently default; no unguarded property access exception
- Hundreds of entries: working steps panel renders all rows without UI freeze or memory pressure
- Very long `detail` payload in a step: expandable block handles arbitrary-length content without layout overflow
- Special characters in messages or tool payloads (angle brackets, ampersands, quotes): HTML rendering intact; no XSS risk
- Unicode in SOP/skill names: chips render correctly with any unicode content
- Entry with unrecognised `event_type` (e.g., `token_refresh`): classified into fallback category; not silently dropped without representation
- Run that fails before first LLM call: entries contain only error entries; collapsible section is empty; no misleading label shown
- `AgentJobPage` state cleanup: removal of legacy log state variables leaves no dead references or broken interactions

## Test File References
- `backend/tests/unit/test_agent_gateway.py`
- `backend/tests/unit/test_agent_instance_manager.py`
- `backend/tests/unit/test_agent_session_service.py`
- `backend/tests/unit/test_agent_runtime_executor.py`
- `backend/tests/api/test_agents_api.py`
- `backend/tests/api/test_agents_session_log_stream_api.py`
- `backend/tests/unit/test_ws_delegation_visibility.py`
- `backend/tests/unit/test_fix_support_role_conversation_delegation_tools.py`
- `backend/tests/unit/test_fix_20260521_tool_routing_and_chat_timeout.py`
- `backend/tests/unit/test_fix_20260521_192300_ws_chat_runtime_boundary.py`
- `frontend/src/__tests__/AgentManagementPage.test.tsx`
- `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx`
- `frontend/src/__tests__/AgentSessionPage.test.tsx`
- `frontend/src/__tests__/ConversationDelegationVisibility.test.tsx`
- `frontend/src/__tests__/ConversationDialog.test.tsx`
- `frontend/src/__tests__/SessionExecutionLogsDialog.test.tsx`
- `frontend/src/__tests__/AgentTypeForm.test.tsx`
- `frontend/src/__tests__/AgentInstanceDashboard.test.tsx`
- `frontend/src/__tests__/useChatSession.test.ts`
- `frontend/src/__tests__/useSessionExecutionLogStream.test.ts`
- `e2e/tests/agent-management.spec.ts`
- `e2e/tests/agent-runtime.spec.ts` — Agent Type Configuration, Agent Session Launch, Agent Session Status, Agent Instance Dashboard, Conversation History Display suites
- `e2e/tests/conversation-delegation-visibility.spec.ts` — conversational visibility cues, folded snippets, and terminal waiting resolution
- `e2e/tests/agent-live-logs-stream.spec.ts` — running-session live stream updates and no-refresh progress visibility
- `e2e/tests/auth-required/access-control.spec.ts` — `Permission Denied: Snackbar` and `Permission Denied: Request Access Flow`
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering per page
- `backend/tests/unit/services/test_plan_generation_service.py` — PlanGenerationService unit tests (LLM mocking, upsert, non-blocking failure, hash computation, no-role path)
- `backend/tests/integration/api/test_agent_types_plan.py` — agent_plans schema verification, unique constraint, CASCADE delete, API response shape
- `frontend/src/__tests__/PlanPreviewModal.test.tsx` — modal rendering, step list, error state, topology delegation, i18n, close callback
- `e2e/tests/agent-plan-mode.spec.ts` — Agent Plan Mode — Mocked and Real Backend Integration — Agent Plan Mode suites
- `frontend/src/__tests__/LogPresenter.test.ts` — LogPresenter unit tests (parsing, classification, result status derivation, raw log build, empty/missing field handling)
- `frontend/src/__tests__/LogSummaryPanel.test.tsx` — LogSummaryPanel rendering: identity/role/model display, SOP/skill chips, result status badge states
- `frontend/src/__tests__/WorkingStepsPanel.test.tsx` — WorkingStepsPanel collapse behaviour: default collapsed, expand/collapse, individual step detail blocks, flat steps visibility
- `frontend/src/__tests__/RawLogToggle.test.tsx` — RawLogToggle: controlled props, onChange callback, copy button visibility, clipboard write
- `frontend/src/__tests__/LogViewer.test.tsx` — LogViewer mode routing: friendly vs raw mode rendering, prop delegation, toggle always present
- `e2e/tests/agent-logs.spec.ts` — AgentJobPage LogViewer integration: mode switching, AgentJobPage regression (no old log dialog trigger), partial log on running session

### Model Configurations — Expanded Dispatch Surface

These scenarios cover the engine-level dispatch path exercised by the LangChain observe-reason-act agent loop. See `docs/changes/expand-model-config-providers/prd.md` AC-16 through AC-19 for the runtime dispatch acceptance criteria, and `agent-runtime-test-plan.md` for the per-provider CRUD and unit-level dispatch coverage. The dispatcher resolves a `ModelConfig` from the extended 12-provider registry (`PROVIDER_REGISTRY`) and routes calls to the correct vendor endpoint.

**Per-provider engine dispatch — Gemini (`gemini`):**
- WHEN the LangChain agent loop invokes an LLM call against a model id bound to a Gemini `ModelConfig`, THEN the dispatcher selects the Gemini native REST caller (`_call_gemini`), attaches the decrypted Gemini API key as the vendor-specific credential header, and returns the parsed response; the agent loop receives the completion text, tool calls, and usage in the normalised Parthenon envelope.
- WHEN the Gemini call returns a non-2xx response, THEN `ModelBindingError` is raised with the provider key `gemini` in the message; the agent loop transitions the session to `failed` with the error logged.

**Per-provider engine dispatch — Mistral (`mistral`):**
- WHEN the agent loop calls a model bound to a Mistral config, THEN the dispatcher routes through the OpenAI-compatible family call path to Mistral's base URL; the credential is attached as a bearer token.
- WHEN the Mistral call fails, THEN the session transitions to `failed`; the error log includes the string `mistral`.

**Per-provider engine dispatch — Cohere (`cohere`):**
- WHEN the agent loop calls a model bound to a Cohere config, THEN the dispatcher uses the Cohere native REST caller (`_call_cohere`) with the vendor-specific credential header; the response is extracted from the Cohere envelope and normalised.
- WHEN the Cohere call fails, THEN the session transitions to `failed` with `cohere` in the error log.

**Per-provider engine dispatch — Groq (`groq`):**
- WHEN the agent loop calls a Groq-bound model, THEN the OpenAI-compatible call path is used with Groq's base URL; the bearer token is the decrypted API key.
- WHEN the Groq call fails, THEN the session transitions to `failed`; the log includes `groq`.

**Per-provider engine dispatch — Together AI (`together`):**
- WHEN the agent loop calls a Together-bound model, THEN the dispatcher dispatches through the OpenAI-compatible family to Together's base URL.
- WHEN the Together call fails, THEN the session transitions to `failed`; the log includes `together`.

**Per-provider engine dispatch — Fireworks AI (`fireworks`):**
- WHEN the agent loop calls a Fireworks-bound model, THEN the OpenAI-compatible family path is used with Fireworks' base URL.
- WHEN the Fireworks call fails, THEN the session transitions to `failed`; the log includes `fireworks`.

**Per-provider engine dispatch — Perplexity (`perplexity`):**
- WHEN the agent loop calls a Perplexity-bound model, THEN the OpenAI-compatible family path is used with Perplexity's base URL.
- WHEN the Perplexity call fails, THEN the session transitions to `failed`; the log includes `perplexity`.

**Per-provider engine dispatch — DeepSeek (`deepseek`):**
- WHEN the agent loop calls a DeepSeek-bound model, THEN the OpenAI-compatible family path is used with DeepSeek's base URL.
- WHEN the DeepSeek call fails, THEN the session transitions to `failed`; the log includes `deepseek`.

#### Cross-provider engine-level scenarios
- WHEN the agent runtime call site passes a `provider_type` not in the 12-value `PROVIDER_REGISTRY`, THEN `ModelBindingError` is raised before any HTTP call; the session transitions to `failed`; the log contains the unknown key.
- WHEN the agent loop receives a response from any of the 12 providers, THEN the extractors (`extract_text`, `extract_tool_calls`, `extract_usage`) return the correct shape; usage is `null` for providers that do not report it (preserving the existing `null`-on-unavailable semantics per AC-18).
- WHEN the agent loop makes an inference call through any of the 12 providers, THEN the OpenTelemetry span carries the provider key, model id, config display name, and standard latency/status attributes (per AC-25).
- WHEN a `ModelConfig` is disabled (`is_disabled = true`), THEN the dispatcher skips it during model resolution; the session fails with `ModelResolutionError` if no other config enables the requested model id.

**Test files for the expanded dispatch surface:**
- `backend/tests/unit/test_model_binding.py` — per-provider resolve-and-dispatch, extractor widening, 4xx/5xx log assertion, unknown-provider rejection, observability attribute checks.
- `backend/tests/unit/test_model_config_service.py` — model resolution against the extended 12-provider catalogue.
- `backend/tests/unit/test_agent_runtime_executor.py` — LangChain agent loop integration: dispatch, resolution, and error handling.
- `e2e/tests/agent-runtime.spec.ts` — `Real Backend Integration - Model Configurations` block validates the dispatch path against a live backend.

**Test files for the binding validation surface:**
- `backend/tests/api/test_agent_type_bindings_api.py` — 16 integration tests: binding CRUD (create with SOP+Skill, skill-only, conversation without bindings, none-input without bindings, explicit empty lists, update, clear, GET includes bindings); validation (SOP not in role → 422, skill not in role → 422, duplicate SOP → 422, duplicate skill → 422, bindings without role → 422); at-least-one requirement (400); cascade delete on agent type removal
- `e2e/tests/agent-type-bindings.spec.ts` — Real backend E2E: POST returns binding fields; skips gracefully when backend unavailable
- `e2e/tests/agent-type-bindings-mocked.spec.ts` — Mocked E2E: binding section render, add/remove/reorder, save payload, orphan warning

For agent role, identity, model config, execution log, LangChain execution, token management, and gateway routing coverage, see `agent-runtime-test-plan.md`.
