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
- `frontend/src/__tests__/AgentManagementPage.test.tsx`
- `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx`
- `frontend/src/__tests__/AgentSessionPage.test.tsx`
- `frontend/src/__tests__/AgentTypeForm.test.tsx`
- `frontend/src/__tests__/AgentInstanceDashboard.test.tsx`
- `e2e/tests/agent-management.spec.ts`
- `e2e/tests/agent-runtime.spec.ts` — Agent Type Configuration, Agent Session Launch, Agent Session Status, Agent Instance Dashboard, Conversation History Display suites
- `e2e/tests/access-control.spec.ts` — `Permission Denied: Snackbar` and `Permission Denied: Request Access Flow`
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

For agent role, identity, model config, execution log, LangChain execution, token management, and gateway routing coverage, see `agent-runtime-test-plan.md`.
