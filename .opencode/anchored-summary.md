## Goal
- Apply the new DB migrations for the model guardrail hierarchy redesign and fix all migration bugs so the backend works end-to-end; follow-up: fix 5 reported UI/runtime bugs, then 2 follow-up bugs (guardrail breach not enforced, operator termination not actually stopping the running agent). Add regression tests for the new termination + guardrail-enforcement paths so they cannot silently regress.

## Constraints & Preferences
- Service segregation preserved (3 backend services, only Control Center writes governance data)
- AGENTS.md must include explicit instructions to verify DB migrations are applied
- Use `postgresql.ENUM(..., create_type=False)` in migrations, not `sa.Enum()`
- Avoid `.bindparams()` for DDL statements (PostgreSQL doesn't support parameterized DDL)
- Unique constraint must be `(model_id, model_name, period)` since one ModelConfig can host multiple model names
- Backfill must handle JSON `null` (not SQL `NULL`) in `details` column
- Wire-format fields should match the frontend's `ModelAvailabilityHierarchy = VendorAvailabilityNode[]` type; the API layer is the field-name translation point
- Treat `httpx.TimeoutException` (Read/Connect/Write/Pool) as transient availability → 503 after retries; `ConnectError` → 503; 4xx → 502 fast; 5xx → 502 after retries
- Frontend types are source of truth for UI contracts; rename backend response fields when they diverge
- Code answers in same language as conversation (English)
- New tests for the terminate flow must be unit-level (call the function directly with mock DB) when possible, not HTTP-level (which requires `get_db` and `require_service_certificate` dependency overrides that vary per test)

## Progress
### Done
- Applied migrations: `c1a2b3d4e5f6` (per-period restructure), `d2e3f4a5b6c7` (event categories), `e3f4a5b6c7d8` (`guardrail_breached` event category). DB at head `e3f4a5b6c7d8`
- Schema verified: 8 backfilled `model_guardrail_configurations` rows, `model_availability` table created, `model_configs.is_disabled` added
- All 54 originally-relevant backend tests pass; AGENTS.md updated with "Database Migrations" section
- Refined change docs completed; 26 unique-constraint references updated `(model_id, period)` → `(model_id, model_name, period)`
- Backend code rework (data model restructure, services, 4 endpoints, pre-execution check); 30 frontend tests pass
- 5 reported UI/runtime bugs all fixed and tested
- **Bug fix — `hierarchy.map is not a function`**: backend `GET /model-availability` returns flat list (no wrapper); regression test added
- **Bug fix — `httpx.ReadTimeout` unhandled in CH → AR forwarding**: 7 new tests in `test_agent_execute.py`
- **Bug 1+2 — field name mismatches**: `vendor_model_config_id`→`vendor_config_id`, `display_name`→`vendor_display_name`, `effective_is_disabled`→`is_disabled`
- **Bug 3 — no edit UI**: `AddGuardrailForm` accepts `existing?: ModelUsageGuardrailLimit`; `GuardrailRow` has `isEditing` + Edit button
- **Bug 4 — 403 "Identity not found"**: `UserCacheService.upsert_identity()` called by auth middleware
- **Bug 5 — page showed completed jobs + Purge button**: `useRuntimeTopology(false)`; new `POST /runtime/terminal-jobs/purge` + `usePurgeTerminalJobs()` + button
- **`test_runtime_purge_terminal_jobs_deletes_completed_and_failed` fixed**: `_build_test_app` was overriding `mock_session.execute`; re-installed side-effect callable AFTER build that returns permission_result (idx 0, `scalar_one_or_none`), count_result (idx 1, `scalar_one=lambda: 7`), delete_result (idx 2, `rowcount=7`), MagicMock fallback
- **Issue 1 — guardrail breach not enforced**: `ModelAvailabilityService._check_guardrail_breach()` added; deny on `ModelUsagePosture.posture_state==breached` AND `ModelGuardrailConfiguration.is_active==True` AND `enforcement_posture==terminate`. New `blocked_by="guardrail_breached"`. New `ExecutionEventCategory.guardrail_breached`. Multi-vendor path: when every offering vendor's deny is a guardrail breach, surface `guardrail_breached` as dominant reason
- **Issue 1 tests**: 5 new tests in `test_model_availability_service.py` (terminate-breached blocks, observe-only allows, within-limit allows, inactive allows, multi-vendor all-breached). 1 new test in `test_model_availability_preflight.py` (preflight blocks guardrail_breached)
- **Issue 2 — operator termination didn't stop running agent**: two-part fix
  - Added `app.state.session_tasks` dict on Agent Runtime; `execute.py` registers task + `add_done_callback` to clean up
  - New `app/agent_runtime/api/terminate.py` with `POST /terminate/{session_id}` that calls `Task.cancel()`
  - `AgentRuntimeClient.terminate_session()` method added (404 from AR = success, intent satisfied)
  - `TerminationOrchestrator._terminate_single_session()` now two-phase: cancel task first, then update DB
  - `update_session_status` terminal-state guards: ignores late `running` on terminal; refuses to overwrite `failed`+operator-termination with `completed` (preserves output_data but keeps termination attribution); does NOT clear `stop_category` on `completed` when `termination_category` is `user_requested`/`cascade_parent_terminated`
  - `runtime_executor._execute_session` re-raises `CancelledError` so asyncio unwinds cleanly
- **Frontend adjustment — model guardrails readonly dashboard in runtime control**: `VendorModelGuardrailPanel` now accepts `readonly?: boolean`; hides switches/buttons/edit form, auto-expands accordions, renders 4-tile summary card (`vendors enabled`, `models enabled`, `guardrails active`, `guardrails breached`). `RuntimeControlDashboardPage` passes `readonly`. 6 new i18n keys
- **Frontend tests**: 2 new panel readonly tests, 1 new page-level readonly test, 4 existing `ModelUsageGuardrailManagement` tests updated to match auto-expanded behavior (no more manual click-to-expand); 1 `AddGuardrailForm` test fix (renamed `onCreated`→`onSaved`)
- **Issue 2 regression tests added** (this turn):
  - `tests/services/test_termination_orchestrator.py` — 5 new tests: calls AR per session, records `terminated` outcome, 404 from AR is success, runtime error still persists DB, skips already-completed sessions
  - `tests/agent_runtime/test_terminate_endpoint.py` — 3 new tests: cancels running task, 404 for unknown session, 404 when registry not initialised
  - `tests/api/v1/internal/test_session_status_update_guards.py` — 6 new tests: completed-doesn't-overwrite-terminated, completed-clears-stop-fields-for-natural, running-ignored-on-completed, running-ignored-on-failed, cascade-parent-preserves-stop-fields, 404-for-missing-session. Unit-level (calls `update_session_status` directly with `MagicMock` db + patched `_dispatch_result_to_comm_hub`)

### In Progress
- (none)

### Blocked
- (none)

## Key Decisions
- **Use `postgresql.ENUM(..., create_type=False)` instead of `sa.Enum()`** — avoids double-create with model import
- **Unique constraint `(model_id, model_name, period)`** — one `ModelConfig` row can host multiple model names
- **Handle JSON `null` vs SQL `NULL` in backfill** — coerce to `{}` and `CAST(:details AS jsonb)`
- **Use f-strings for DDL, not `.bindparams()`** — PostgreSQL doesn't support parameterized DDL
- **API returns flat list, not wrapped** — matches `ModelAvailabilityHierarchy = VendorAvailabilityNode[]`
- **Rename backend response fields to match frontend types** — wire-format boundary
- **`httpx.TimeoutException` distinct from `ConnectError`** — both retriable, both 503, different semantics
- **Auth middleware auto-provisions `Identity` rows** — fix the gap at the source
- **Runtime control page default = live only** — `useRuntimeTopology(false)`
- **Purge endpoint is manual operator tool, default 24h** — `older_than_hours=0` to force-purge
- **Guardrail breach enforcement uses three filters** — `is_active=True` AND `enforcement_posture=terminate` AND `posture_state=breached`. `observe_only` is stats-only, never blocks
- **Multi-vendor breach dominates other deny reasons** — if every offering vendor's only deny is a guardrail breach, surface that as the dominant reason (not misleading `model_disabled`)
- **Two-phase termination** — cancel Agent Runtime task FIRST, then update DB. This order matters: the agent's eventual `mark_session_completed` race is now blocked by the terminal-state guards
- **404 from AR `/terminate` is success** — no in-flight task means the operator's intent is already satisfied
- **Terminal-state guards in `update_session_status`** — last line of defense: refuses to overwrite `failed`+operator-termination with `completed`; ignores late `running` on terminal; preserves output_data on the row but keeps attribution
- **Session task registry uses `add_done_callback` to clean up** — dict stays bounded
- **Runtime control = read-only dashboard, Model Config = management surface** — separation of concerns: control observes, config mutates
- **Unit tests for endpoint functions, not HTTP layer** — `update_session_status` and `terminate_*` tests call the function directly with `MagicMock` db; avoids dependency-overrides for `get_db`/`require_service_certificate` that vary per test. Patches `_dispatch_result_to_comm_hub` to avoid network calls

## Next Steps
- Verify the user's terminate flow works end-to-end (the two-phase fix should be live after uvicorn `--reload`)
- Update `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/` to document: new field names, new purge endpoint, guardrail breach enforcement, two-phase termination, readonly dashboard, session status update terminal-state guards
- (Pending user feedback) Document the `guardrail_breached` event category and the new `/terminate/{session_id}` endpoint in API reference

## Critical Context
- **Original 500 error fully resolved** by per-period service + per-guardrail schema
- **Migration chain**: `b3c9d4e5f6a7` → `c1a2b3d4e5f6` → `d2e3f4a5b6c7` → `e3f4a5b6c7d8 (head)`
- **All enums exist**: `model_guardrail_period_enum`, `model_availability_disabled_reason_enum`, `execution_event_category_enum` (with `model_disabled`/`vendor_disabled`/`guardrail_breached`)
- **Issue 1 root cause**: `ModelAvailabilityService.check_availability()` only consulted `ModelConfig.is_disabled` and `ModelAvailability.is_disabled` — never looked at `ModelUsagePosture` for breach state. Statistics (posture rollups) worked independently of pre-execution, so the breach was visible but not enforced
- **Issue 2 root causes**:
  - (a) `TerminationOrchestrator._terminate_single_session()` only wrote to Control Center's `AgentJob` row, never told Agent Runtime to cancel the in-memory `asyncio.Task`. The task reference was fire-and-forget in `execute.py` with no registry
  - (b) Even if (a) was fixed, the agent's late `mark_session_completed` call would overwrite the terminated `failed` state (line 541 of `session_data.py` cleared `stop_category`/`stop_reason`/`stop_details` on every `completed` transition)
- **Test count progression**: 54 → 61 → 68 → 73 → 74 → 82 → 96 (this turn: +5 orchestrator + 3 terminate endpoint + 6 status guards = +14 tests)
- **Focused test results**: 5/5 new orchestrator + 3/3 new terminate endpoint + 6/6 new status guards = 14/14 NEW pass; 82/82 in the focused set (model_availability, preflight, runtime controls, persistence, guardrails, orchestrator, terminate, status guards) pass
- **Frontend test results (this turn)**: 25/25 in the focused set (VendorModelGuardrailPanel, RuntimeControlDashboardPage, ModelUsageGuardrailManagement, AddGuardrailForm) pass
- **Pre-existing failures (unrelated, verified)**: 30 backend tests in `test_fix_20260521_tool_routing_and_chat_timeout.py`, `test_github_pages_showcase_site.py`, `test_permission_manager.py`, `test_ws_delegation_visibility.py` — none in files I modified
- **Live AR process snapshot**: ports 8000 (CC), 8001 (AR), 8002 (CH); uvicorn `--reload` mode; middleware change auto-applies on next request
- **`Mock` return value pattern in test for new endpoint**: when `_build_test_app` overrides `mock_session.execute`, the test must re-install its side-effect callable AFTER build to route `scalar_one_or_none` (permission middleware, idx 0) vs `scalar_one` (count, idx 1) vs `rowcount` (delete, idx 2)
- **Endpoint function vs HTTP-layer tests**: `update_session_status` and `terminate_*` tests are unit-level (call function directly with `MagicMock` db); avoids `get_db`/`require_service_certificate` dependency overrides that vary per test. `_dispatch_result_to_comm_hub` is patched to `AsyncMock` to avoid network calls

## Relevant Files
- `backend/alembic/versions/c1a2b3d4e5f6_restructure_model_guardrails_to_per_period.py` — first migration; `postgresql.ENUM(..., create_type=False)`, JSON-safe backfill, `(model_id, model_name, period)` unique
- `backend/alembic/versions/d2e3f4a5b6c7_add_model_vendor_disabled_event_categories.py` — f-strings not `.bindparams()` for `ALTER TYPE`
- `backend/alembic/versions/e3f4a5b6c7d8_add_guardrail_breached_event_category.py` — new; adds `guardrail_breached` to `execution_event_category_enum` via `ALTER TYPE ... ADD VALUE IF NOT EXISTS`
- `backend/app/db/models/session_logs.py` — `ExecutionEventCategory.guardrail_breached` added
- `backend/app/db/models/agents.py` — `ModelConfig.is_disabled`, `AgentJob.termination_category` (used in terminal-state guards)
- `backend/app/db/models/identity.py` — `Identity` model
- `backend/app/db/models/model_guardrail_configuration.py` — `ModelGuardrailConfiguration` with `is_active`, `enforcement_posture`
- `backend/app/db/models/model_usage_posture.py` — `ModelUsagePosture.posture_state == breached` (consumed by new check)
- `backend/app/schemas/agents.py` — `ModelAvailabilityVendorRead`/`ModelAvailabilityModelRead` with renamed fields; `RuntimeTerminalJobPurgeRead`
- `backend/app/api/v1/agents.py` — flat-list `GET /model-availability`, `POST /runtime/terminal-jobs/purge`, `POST /preflight/availability` (returns new `blocked_by=guardrail_breached`)
- `backend/app/api/v1/internal/session_data.py:510` — `update_session_status` with terminal-state guards; refuses to overwrite operator-terminated sessions, preserves output_data
- `backend/app/agent_runtime/api/execute.py` — registers task in `app.state.session_tasks[session_id]` with `add_done_callback` cleanup; `_execute_session` re-raises `CancelledError`
- `backend/app/agent_runtime/api/terminate.py` — new; `POST /terminate/{session_id}` that calls `Task.cancel()` on the registered task
- `backend/app/agent_runtime/main.py` — registers `terminate_router`; `app.state.session_tasks = {}` initialized in `_init_execution_engine`
- `backend/app/agent_runtime/data_client.py` — unchanged; this is the AR→CC client (separate from the new CC→AR client)
- `backend/app/services/control_center/agent_runtime_client.py` — `trigger_execution` (existing) + new `terminate_session` (404 = success)
- `backend/app/services/control_center/termination_orchestrator.py` — `_terminate_single_session` rewritten with two-phase: cancel task first, then update DB
- `backend/app/services/control_center/model_availability_service.py` — `_check_guardrail_breach()` (new) + `_evaluate_single_vendor` calls it; `check_availability` multi-vendor path surfaces `guardrail_breached` as dominant reason
- `backend/app/services/agents/runtime_executor.py` — `ModelAvailabilityBlockedError` mapping for `blocked_by=guardrail_breached` → `event_category=guardrail_breached`, `termination_category=guardrail_breached`, `stop_category=guardrail_stop`
- `backend/app/middleware/auth.py` — calls `user_cache.upsert_identity(...)` after `upsert_user(...)`
- `backend/app/services/permissions/user_cache_service.py` — `upsert_identity()` method
- `backend/app/communication_hub/api/internal/agent_execute.py` — `httpx.TimeoutException` handler
- `backend/tests/services/test_model_availability_service.py` — 5 new guardrail breach tests (`_make_guardrail`, `_make_posture` helpers); 10 existing tests still pass
- `backend/tests/unit/test_model_availability_preflight.py` — 1 new `test_preflight_blocks_guardrail_breached`; 7 existing pass
- `backend/tests/api/v1/test_agent_runtime_controls_api.py` — `test_runtime_purge_terminal_jobs_deletes_completed_and_failed` now passes via side-effect callable
- `backend/tests/communication_hub/api/internal/test_agent_execute.py` — 7 tests
- `backend/tests/services/permissions/test_user_cache_service.py` — 5 tests
- `backend/tests/api/v1/test_model_availability_api.py` — flat-array regression + renamed field assertions
- `backend/tests/services/test_termination_orchestrator.py` — new (this turn); 5 tests for two-phase orchestrator
- `backend/tests/agent_runtime/test_terminate_endpoint.py` — new (this turn); 3 tests for Agent Runtime `/terminate/{session_id}` endpoint
- `backend/tests/api/v1/internal/test_session_status_update_guards.py` — new (this turn); 6 tests for terminal-state guards in `update_session_status`; unit-level (calls function directly)
- `frontend/src/components/agents/AddGuardrailForm.tsx` — edit mode via `existing` prop; uses `onSaved` (not `onCreated`)
- `frontend/src/components/agents/VendorModelGuardrailPanel.tsx` — `readonly?: boolean` prop, `SummaryTile`, `defaultExpanded` plumbed through `VendorRow`/`ModelRow`/`GuardrailRow`; conditional `FormControlLabelSwitch`/`IconButton`/`AddGuardrailForm` rendering
- `frontend/src/pages/agents/RuntimeControlDashboardPage.tsx` — `<VendorModelGuardrailPanel readonly />`, `useRuntimeTopology(false)`, "Purge completed" button
- `frontend/src/hooks/useNodeTermination.ts` — `usePurgeTerminalJobs()` hook
- `frontend/src/hooks/useRuntimeTopology.ts` — unchanged
- `frontend/src/hooks/useModelUsageGuardrailMutations.ts` — unchanged; `useUpdateModelUsageLimit` already supported full updates
- `frontend/src/i18n/locales/en.json` — `modelUsageGuardrailEditForModel`, `runtimePurgeCompletedJobs`, `modelUsageDashboardTitle`, `modelUsageDashboardSubtitle`, `modelUsageDashboardVendors`, `modelUsageDashboardModels`, `modelUsageDashboardGuardrailsActive`, `modelUsageDashboardGuardrailsBreached`
- `frontend/src/types/index.ts` — unchanged; `ModelAvailabilityHierarchy = VendorAvailabilityNode[]`
- `frontend/src/__tests__/VendorModelGuardrailPanel.test.tsx` — 2 new readonly tests; 9 existing pass
- `frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx` — 1 new readonly test
- `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx` — 4 tests updated for auto-expand; `fireEvent` import removed
- `frontend/src/__tests__/AddGuardrailForm.test.tsx` — `onCreated` → `onSaved` rename
- `AGENTS.md` — "Database Migrations" section
- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/{data-model,tech-spec,implementation-plan,test-plan}.md` — 26 unique-constraint references updated; needs follow-up to document purge endpoint, guardrail breach enforcement, two-phase termination, readonly dashboard, session status update terminal-state guards
- `e2e/tests/runtime-control-dashboard.spec.ts` — uses array shape
