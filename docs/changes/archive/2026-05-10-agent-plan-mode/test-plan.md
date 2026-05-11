# Test Plan: Agent Plan Mode

**Change**: `agent-plan-mode`
**Date**: 2026-05-09
**Status**: Ready for Implementation — `has_db_changes: true`

---

## 1. Test Strategy

This change extends the Agent Type save flow to invoke an LLM to generate a human-readable implementation plan and visual topology diagram for each agent. It introduces a new `agent_plans` table, two new backend services (`PlanGenerationService` with LLM integration, `TopologyBuilderService`), extended API response shapes on `POST /agents/types` and `PUT /agents/types/{type_id}`, runtime plan loading in `AgentRuntimeLoader`, and two new frontend components (`PlanPreviewModal`, `TopologyDiagramRenderer`). All five test layers — backend unit, backend integration, frontend component, E2E mocked, and E2E real backend — must pass before marking this change implemented.

### Test Layers

| Layer | Framework | Location | Purpose |
|-------|-----------|----------|---------|
| Backend unit | pytest | `backend/tests/unit/` | Service logic, topology serialization, plan step assembly, hash computation, non-blocking error handling |
| Backend integration | pytest + real PostgreSQL | `backend/tests/integration/` | Schema constraints on `agent_plans`, cascade delete, unique FK, save-response shape, upsert behaviour |
| Frontend component | Vitest | `frontend/src/__tests__/` | Modal rendering, step list, diagram renderer, error state, i18n keys, close callback, dialog error handling |
| E2E mocked | Playwright | `e2e/tests/agent-plan-mode.spec.ts` | Full create/update save flows with `page.route()` mocks for speed |
| E2E real backend | Playwright | `e2e/tests/agent-plan-mode.spec.ts` | One suite hitting the real backend — catches migration issues that mocked tests miss |

### Database Change Requirements (CRITICAL)

This change has `has_db_changes: true`. The following rules apply without exception:

- Backend integration test fixture must run `alembic upgrade head` before any test
- Integration tests must verify the `agent_plans` table was created and has the correct columns via `information_schema`
- Integration tests must verify the unique constraint on `agent_type_id` by attempting two inserts for the same agent type
- Integration tests must verify CASCADE delete: deleting an `AgentType` must also remove the associated `AgentPlan` row
- Integration tests must verify non-nullable columns are enforced (`id`, `agent_type_id`, `generation_status`, `generated_at`)
- At least one E2E suite must be labeled `Real Backend Integration - Agent Plan Mode` and run without `page.route()` mocks
- Pre-run checklist: verify `alembic current` shows the new `add_agent_plans` migration ID before executing any test

---

## 2. Coverage Areas

### `agent_plans` Table Schema

The new table must be created with the correct column types, nullability constraints, unique FK to `agent_types`, and CASCADE delete rule. Schema verification tests inspect `information_schema.columns` and `information_schema.table_constraints` directly — not just service-level happy paths — to ensure the migration was actually applied.

### PlanGenerationService

Orchestrates LLM-based plan generation on agent type save. Key behaviours to cover:
- Happy path: traverses the role→SOP→Skill→Tool graph, constructs an LLM prompt with agent context (instructions, role, SOPs, skills, tools), invokes the configured LLM, parses the response, and produces a structured `plan_steps` list
- LLM mocking: unit tests should mock the LLM client to return predictable plan responses (success case and various response formats)
- Upsert: on the first save, an `AgentPlan` row is created; on subsequent saves, the existing row is updated (not duplicated)
- Non-blocking failure: if the LLM invocation or parsing throws an exception, the `AgentPlan` row is written with `generation_status = failed` and the `generation_error` field populated; no exception propagates to the caller
- Hash computation: `agent_config_hash` reflects the combination of `role_id`, `primary_sop_id`, and `system_instruction`; the same inputs produce the same hash on repeated calls
- No role assigned: when the agent type has no `role_id`, the service handles the missing graph gracefully (empty plan steps, status recorded)
- LLM timeout/errors: verify that LLM client timeouts or API errors are caught and recorded as failed generation, not unhandled exceptions

### TopologyBuilderService

Converts the resolved graph to a `nodes`/`edges` payload. Key behaviours:
- All four node types (`role`, `sop`, `skill`, `tool`) produce correctly typed node objects
- Edges correctly encode the source-to-target relationships in the graph
- Node IDs are deterministic: the same graph produces the same node ID values on every call
- Empty graph (no role, no SOPs, no skills, no tools) produces an empty nodes and empty edges list — not an error
- Duplicate tools appearing via multiple skill paths produce exactly one node and correctly de-duplicated edges

### API Response Extension

Both `POST /api/v1/agents/types` and `PUT /api/v1/agents/types/{type_id}` must include the `plan` field in their response. Key coverage:
- Successful generation: response body contains `plan` with `generation_status = success`, a non-empty `plan_steps` array (LLM-generated content), and a non-empty `topology` with `nodes` and `edges`
- Failed generation: response body contains `plan` with `generation_status = failed` and a `generation_error` string (e.g., "LLM timeout" or "LLM parsing error"); the agent type record is still saved (201/200 status code)
- No role: `plan` field is present but has an empty `plan_steps` and empty `topology`
- Schema shape: `plan` contains `plan_steps` (array of `{order, type, name, description}`), `topology_nodes` (array of `{id, type, label, meta}`), `topology_edges` (array of `{source, target, label}`), `generation_status`, `generation_error`, and `agent_config_hash`
- LLM integration: verify that plan generation service invoked the LLM client (check via mocked LLM call counts or logs)

### PlanPreviewModal

MUI Dialog component opened automatically after a successful agent type save. Key coverage:
- Renders plan steps as an ordered list when `generation_status = success`
- Renders step-type chips with appropriate labels for each step type
- Delegates topology rendering to `TopologyDiagramRenderer`
- Shows error state (error message visible) when `generation_status = failed`
- Calls the `onClose` callback when the close button is clicked
- Is not rendered (or is hidden) before a save is performed
- `dialogError` state follows the Dialog Error Handling Standard: cleared on open, displayed as `PermissionDeniedAlert` at the top of `DialogContent`
- All visible strings use `t()` from i18next (no hardcoded English)

### TopologyDiagramRenderer

Receives the nodes/edges payload and renders a visual diagram. Key coverage:
- Renders without throwing when given a valid non-empty payload
- Differentiates node types by colour, icon, or visual style (verified via rendered output or snapshot)
- Renders empty state gracefully when both `nodes` and `edges` are empty arrays
- Does not throw when `nodes` or `edges` contain unexpected or extra fields

### AgentManagementPage State Management

The page now manages `planData` and `planModalOpen` state after a save. Key coverage:
- `planData` is set to the `plan` field from the save response immediately after a successful create/update call
- `PlanPreviewModal` is opened (`planModalOpen = true`) after the successful save, before `setDialogOpen(false)`
- `planData` is cleared and `planModalOpen` is set to false when the user dismisses the modal
- Re-opening the agent type create/edit dialog after dismissing the modal does not re-open the plan modal

### i18n Coverage

All new UI strings for the plan preview feature must be defined in `frontend/src/i18n/locales/en.json` under the `agents.plan.*` namespace. No hardcoded English strings may appear in `PlanPreviewModal` or `TopologyDiagramRenderer`.

### AgentRuntimeLoader Plan Injection

The agent runtime must load the saved plan and inject it into the agent's execution context. Key coverage:
- When an agent session is started with an agent type that has a saved plan (`generation_status = success`), the plan is loaded from the `agent_plans` table
- The plan is formatted as a structured text block and injected into the agent's system context (LLM system prompt)
- The injected plan includes clear instructions for the agent to follow the pre-approved steps
- If no plan exists for the agent type, the agent session starts without plan injection (graceful degradation, no errors)
- If the plan has `generation_status = failed`, the agent session proceeds without plan injection
- Runtime logs record whether a plan was loaded and injected for observability

### Error Handling

- Plan generation failure is non-blocking: the agent type save returns 201/200 even when generation fails (including LLM timeouts or errors)
- The frontend `PlanPreviewModal` displays the `generation_error` message when status is `failed`
- If the save API call itself fails (network error, 403, 500), `AgentManagementPage` follows the Dialog Error Handling Standard and does not open the plan modal

---

## 3. Critical Scenarios

### Database Schema Verification

- WHEN the `add_agent_plans` Alembic migration is applied THEN `information_schema.tables` shows an `agent_plans` table in the public schema
- WHEN `information_schema.columns` is queried for `agent_plans` THEN columns `id`, `agent_type_id`, `plan_steps`, `topology`, `generation_status`, `generated_at`, `created_at`, `updated_at` are all present
- WHEN `information_schema.columns` is queried for `agent_plans.generation_error` THEN `is_nullable = 'YES'`
- WHEN `information_schema.columns` is queried for `agent_plans.agent_type_id` THEN `is_nullable = 'NO'`
- WHEN `information_schema.table_constraints` is queried for `agent_plans` THEN a UNIQUE constraint exists on `agent_type_id`
- WHEN two `AgentPlan` rows are inserted for the same `agent_type_id` THEN the second insert raises a unique violation (the upsert path must be used, not plain insert)
- WHEN an `AgentType` row is deleted from the database THEN the corresponding `AgentPlan` row is also deleted (CASCADE constraint in effect)
- WHEN an `AgentType` row with no plan record is deleted THEN the delete succeeds without error (no orphan FK violation)

### Plan Generation — Happy Path

- WHEN an agent type with a role, primary SOP, associated skills, and tools is saved THEN `PlanGenerationService` produces a non-empty `plan_steps` list with each step containing `order`, `type`, `name`, and `description`
- WHEN plan generation succeeds THEN the `AgentPlan` row has `generation_status = success` and `generation_error = null`
- WHEN the same agent type is updated a second time THEN the existing `AgentPlan` row is updated in place (upserted); no second row is created
- WHEN the agent type's `system_instruction` is changed and the type is re-saved THEN `agent_config_hash` on the updated plan record differs from the previous hash

### Plan Generation — No Role Assigned

- WHEN an agent type has no `role_id` THEN `PlanGenerationService` completes without raising an exception
- WHEN an agent type has no `role_id` THEN the resulting `AgentPlan` has an empty `plan_steps` array and an empty `topology`

### Plan Generation — Non-Blocking Failure

- WHEN `PlanGenerationService.generate_plan()` raises an internal exception THEN the exception is caught, an `AgentPlan` row with `generation_status = failed` is written, and the exception does not propagate to the API handler
- WHEN the LLM client times out or returns an error THEN plan generation catches the error, writes `generation_status = failed` with error details, and does not propagate the exception
- WHEN the LLM response cannot be parsed into structured plan steps THEN plan generation fails gracefully with `generation_status = failed` and a descriptive error message
- WHEN plan generation fails THEN `generation_error` on the saved row contains a non-empty human-readable error message
- WHEN plan generation fails THEN the agent type record is still saved and the API returns 201 (create) or 200 (update) — not 500

### Topology Building

- WHEN a graph with one role, two SOPs, three skills, and five tools is provided THEN the nodes list contains one role node, two sop nodes, three skill nodes, and five tool nodes (no duplicates)
- WHEN the same graph is serialized twice THEN all node IDs are identical across both calls (deterministic)
- WHEN a tool appears in two different skills THEN the tool has exactly one node and both skills have an edge pointing to it
- WHEN an empty graph is provided (no role) THEN `TopologyBuilderService` returns `{ nodes: [], edges: [] }` without raising

### API Save Response

- WHEN `POST /api/v1/agents/types` is called with valid payload THEN the response body contains a top-level `plan` field with `generation_status`, `plan_steps`, `topology_nodes`, `topology_edges`, `agent_config_hash`, and `generated_at`
- WHEN `PUT /api/v1/agents/types/{type_id}` is called THEN the response also includes the regenerated `plan` field
- WHEN plan generation fails internally THEN `POST /api/v1/agents/types` still returns 201 and the `plan.generation_status` is `failed`
- WHEN `GET /api/v1/agents/types` (list) is called THEN the `plan` field is absent from each list item (plan only in create/update responses)

### PlanPreviewModal Rendering

- WHEN `PlanPreviewModal` receives a plan with `generation_status = success` THEN an ordered list of plan steps is rendered with the correct count
- WHEN `PlanPreviewModal` receives a plan with `generation_status = failed` THEN an error state is visible showing the `generation_error` text
- WHEN `PlanPreviewModal` is closed via the close button THEN the `onClose` callback is invoked
- WHEN `PlanPreviewModal` is not yet opened (`planModalOpen = false`) THEN the dialog is not mounted or is hidden
- WHEN `PlanPreviewModal` mounts with a `failed` plan THEN the error is shown as the first visible element within `DialogContent` (Dialog Error Handling Standard)

### TopologyDiagramRenderer

- WHEN `TopologyDiagramRenderer` receives nodes of types `role`, `sop`, `skill`, `tool` THEN all nodes are present in the rendered output
- WHEN `TopologyDiagramRenderer` receives an empty nodes and edges array THEN it renders an empty-state indicator without throwing
- WHEN `TopologyDiagramRenderer` receives a payload with unknown extra fields on nodes THEN it renders without throwing

### AgentManagementPage Integration

- WHEN a user saves a new agent type and the server returns a plan THEN `PlanPreviewModal` opens automatically without requiring a second user action
- WHEN a user dismisses `PlanPreviewModal` THEN `planData` is cleared and the modal is not shown again unless another save occurs
- WHEN a user saves an updated agent type THEN `PlanPreviewModal` opens with the regenerated plan from the update response
- E2E User Journey (create with plan — mocked): Navigate to Agent Management → Click "Add Agent Type" → Fill in required fields → Save → Verify `PlanPreviewModal` opens with step list and diagram → Dismiss modal → Verify agent type row appears in table without page reload
- E2E User Journey (update with plan — mocked): Edit existing agent type → Modify system instruction → Save → Verify `PlanPreviewModal` opens with updated plan → Dismiss → Verify table row reflects updated name/config
- E2E User Journey (failed plan — mocked): Save agent type where mocked plan response has `generation_status = failed` → Verify modal opens → Verify error message from `generation_error` visible → Dismiss → Verify agent type row saved correctly
- E2E User Journey (Real Backend Integration — create): Create real agent type via `POST /api/v1/agents/types` with no `page.route()` mock → Verify response includes `plan` field → Verify `AgentPlan` row exists in database with correct `agent_type_id` → Verify `generation_status` is either `success` or `failed` (not absent) → Delete agent type → Verify `AgentPlan` row is also deleted (CASCADE verified)

### i18n

- WHEN `PlanPreviewModal` renders all visible text THEN every string is produced by `t()` from i18next (no hardcoded English strings in the component)
- WHEN `TopologyDiagramRenderer` renders node type labels THEN label strings are produced via `t()` under the `agents.plan.*` namespace
- WHEN the `en.json` locale file is inspected THEN keys `agents.plan.title`, `agents.plan.close`, `agents.plan.errorTitle`, `agents.plan.stepTypes.*`, and `agents.plan.nodeTypes.*` are all present

### Agent Runtime Plan Loading

- WHEN an agent session is started with an agent type that has a saved plan (`generation_status = success`) THEN the `AgentRuntimeLoader` queries the `agent_plans` table and loads the plan
- WHEN the plan is loaded THEN the plan steps are formatted as structured text and injected into the agent's system context (LLM prompt)
- WHEN the agent's system context is inspected THEN it contains clear instructions to follow the pre-approved plan
- WHEN an agent session is started with an agent type that has no saved plan THEN the session starts successfully without plan injection (graceful degradation)
- WHEN an agent session is started with an agent type that has `generation_status = failed` THEN the session starts successfully without plan injection
- WHEN plan loading and injection occurs THEN runtime logs record the plan loading event for observability

---

## 4. Edge Cases & Risks

### Plan Generation During Concurrent Saves

If an agent type is saved simultaneously from two clients, two `PlanGenerationService` calls may race to upsert the same `AgentPlan` row. The upsert must use an `ON CONFLICT DO UPDATE` strategy or equivalent to avoid unique violation errors. Tests should verify the happy path is correct; the concurrent race is a deployment-level risk that does not require a full concurrency test in the unit suite.

### Large Permission Graphs

An agent type whose role grants access to many SOPs with deeply nested skill chains could produce hundreds of plan steps and hundreds of topology nodes. Verify that `TopologyBuilderService` serializes large graphs without hitting Python recursion limits and that the resulting JSON payload does not exceed the API response size limit used by the MUI Dialog renderer.

### Missing or Incomplete Master Data

If the role, SOPs, or skills in the database have been partially deleted or are in an inconsistent state at plan-generation time, `PlanGenerationService` must not crash the save request. The non-blocking error path must write a `failed` status with a descriptive error and allow the save to complete.

### LLM Timeout and Rate Limiting

If the configured LLM provider times out or returns a rate limit error (429), `PlanGenerationService` must catch the error, record `generation_status = failed` with details, and not propagate the exception. Tests should mock LLM client timeout and rate limit responses to verify graceful handling.

### LLM Response Parsing Failures

If the LLM returns a response that cannot be parsed into the expected plan structure (malformed JSON, missing fields, unexpected format), the parsing error must be caught, and `generation_status = failed` must be recorded. Unit tests should provide various malformed LLM responses to verify error handling.

### LLM Returns Empty or Invalid Plan

If the LLM returns an empty plan (no steps) or a plan with invalid step types, the service should either record the plan as-is with a warning or fail gracefully depending on validation rules. Tests should verify that an empty LLM response does not crash the service.

### Hash Stability Across Deployments

The `agent_config_hash` is computed from `role_id`, `primary_sop_id`, and `system_instruction`. Tests should verify the hash function produces consistent output across Python restarts (i.e., does not use `hash()` which is not stable across processes). This matters for future staleness detection features.

### Plan Staleness on Read

The plan preview is only surfaced on save responses. If a user navigates away and returns to the agent type list, the plan is not re-displayed. Tests should confirm the `useAgentTypes` list query does not include the `plan` field, both to avoid payload bloat and to avoid showing a potentially stale plan without the user re-saving.

### Modal Not Re-Opening Without Save

The `PlanPreviewModal` must not open when the user opens the agent type edit dialog (without saving). State management tests must confirm `planModalOpen` remains `false` when the edit dialog is opened and then closed without saving.

### Diagram Renderer Empty State

`TopologyDiagramRenderer` must display a meaningful empty state when the topology payload is empty (e.g., agent type with no role). A blank white box with no indicator would confuse users. The empty state message must be i18n-covered.

### Dialog Error Handling Standard Compliance

`PlanPreviewModal` must follow the project's Dialog Error Handling Standard: `dialogError` state cleared on open, `PermissionDeniedAlert` rendered as the first child of `DialogContent`. If the modal is repurposed to make future API calls, this standard must remain enforced.

### Migration Not Applied

If `alembic upgrade head` is not run before tests, `agent_plans` table is missing and all plan-related service calls fail with `UndefinedTableError`. Integration tests must catch this by running against a real DB after applying migrations. The pre-run checklist (`alembic current` shows new migration ID) must be completed before any integration or E2E test run.

### Frontend Plan Field Optional

The frontend must treat `plan` as always-optional in the `AgentTypeRead` response. If a future backend version or an older API client omits the field, `AgentManagementPage` must not throw and must not open the plan modal. Component tests must assert graceful handling of a save response with `plan: null` or `plan` absent.

---

## 5. Acceptance Criteria Checklist

| # | PRD Acceptance Criterion | Test Coverage |
|---|--------------------------|---------------|
| 1 | When a user saves an Agent Type, the system automatically generates a clear, step-by-step implementation plan based on the agent's instruction, role SOPs, and skills | Backend unit: `test_plan_generation_service.py` (happy path, role-SOP-Skill-Tool graph traversal); Backend integration: `test_agent_types_plan.py` (plan field in POST response against real DB) |
| 2 | The generated plan is displayed in a human-readable format, outlining each action the agent will take | Frontend component: `PlanPreviewModal.test.tsx` (step list rendered with correct count and step-type chips); E2E mocked: create journey with plan modal step list |
| 3 | A topology diagram visually shows the Agent Role, SOPs, Skills, and Tools that will be used, with clear relationships | Frontend component: `TopologyDiagramRenderer.test.tsx` (all four node types rendered, edges present); E2E mocked: diagram visible in modal after save |
| 4 | Users can preview the full plan and diagram before executing or deploying the agent | Frontend component: `PlanPreviewModal.test.tsx` (modal opens after save); `AgentManagementPage.test.tsx` (planModalOpen set after successful save); E2E: plan modal opens on create and update journeys |
| 5 | The plan and diagram update automatically if the agent's configuration, role, SOPs, or skills change | Backend unit: `test_plan_generation_service.py` (upsert on re-save, hash changes on config change); Backend integration: `test_agent_types_plan.py` (update response includes regenerated plan); E2E: update journey verifies modal opens with new plan |
| 6 | All UI text is internationalized via i18next | Frontend component: `PlanPreviewModal.test.tsx` and `TopologyDiagramRenderer.test.tsx` verify `t()` calls; `en.json` key presence verification |
| 7 | The feature is accessible and usable on both desktop and tablet devices | E2E mocked: viewport assertions in plan modal test (1280px desktop, 768px tablet) |
| 8 | Error handling: If plan generation fails, users receive a clear, actionable error message | Backend unit: `test_plan_generation_service.py` (exception → `failed` status, `generation_error` populated, save returns 201); Frontend: `PlanPreviewModal.test.tsx` (failed-status error state rendered); E2E mocked: failed-plan journey |
| 9 | No direct database access occurs from the frontend; all data flows through the backend API | Frontend architecture: `PlanPreviewModal` receives plan as prop from save response, no Supabase or direct DB calls; verified by code review and absence of any direct DB import in frontend plan components |

---

## 6. Test File References

All paths are relative to the workspace root as defined in `docs/config.yaml` under `source.tests`.

### Backend Unit Tests (`backend/tests/unit/`)

| File | Coverage |
|------|----------|
| `backend/tests/unit/services/test_plan_generation_service.py` | `PlanGenerationService`: happy path (role→SOP→Skill→Tool graph traversal produces ordered plan_steps); upsert on re-save (existing row updated, no second row created); non-blocking failure (exception caught, `failed` status written, exception not propagated); `generation_error` populated on failure; `generation_status = success` with non-empty plan_steps on success; no-role case (empty plan_steps, no crash); hash computed from `role_id` + `primary_sop_id` + `system_instruction`; hash is deterministic across repeated calls with identical inputs; hash changes when any input changes |
| `backend/tests/unit/services/test_topology_builder_service.py` | `TopologyBuilderService`: all four node types (role, sop, skill, tool) produce correctly typed node objects; edges encode correct source-to-target relationships; node IDs are deterministic (same graph → same IDs); empty graph produces `{nodes: [], edges: []}` without error; duplicate tools across skill paths produce exactly one node; large graph (many SOPs, many tools) serializes without recursion error; node objects include required fields (`id`, `type`, `label`, `meta`) |

### Backend Integration Tests (`backend/tests/integration/`)

| File | Coverage |
|------|----------|
| `backend/tests/integration/api/test_agent_types_plan.py` | Schema verification via `information_schema`: `agent_plans` table exists; all required columns present; `agent_type_id` is NOT NULL; `generation_error` is nullable; unique constraint on `agent_type_id` enforced (second insert raises violation); CASCADE delete: deleting an `AgentType` also removes its `AgentPlan` row; `POST /api/v1/agents/types` response includes `plan` field with `generation_status`, `plan_steps`, `topology_nodes`, `topology_edges`, `agent_config_hash`; `PUT /api/v1/agents/types/{type_id}` response also includes regenerated `plan`; plan row upserted (not duplicated) on second save; plan field absent from `GET /api/v1/agents/types` list response; failed generation path: plan row written with `generation_status = failed` and non-null `generation_error`; agent type save returns 201/200 even when generation status is `failed` |

### Frontend Component Tests (`frontend/src/__tests__/`)

| File | Coverage |
|------|----------|
| `frontend/src/__tests__/PlanPreviewModal.test.tsx` | Renders plan steps as ordered list when `generation_status = success`; correct step count matches `plan_steps` array length; step-type chips rendered with translated labels; `TopologyDiagramRenderer` mounted inside modal; error state shown when `generation_status = failed` with `generation_error` text; error element is first child of `DialogContent` (Dialog Error Handling Standard); `onClose` callback invoked on close button click; modal not rendered (or hidden) when `open = false`; `dialogError` cleared when modal closed and reopened; all text produced via `t()` (no hardcoded English strings) |
| `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` | Renders without throwing given valid nodes and edges payload; nodes of types `role`, `sop`, `skill`, `tool` all present in output; empty nodes and edges arrays produce an empty-state indicator without throwing; unknown extra fields on node objects do not throw; snapshot test for known payload (verifies visual differentiation exists) |
| `frontend/src/__tests__/AgentManagementPage.test.tsx` | `planModalOpen` set to `true` after successful create save; `planData` set to plan from save response; `PlanPreviewModal` not mounted before first save; `planData` cleared and `planModalOpen` set to `false` after modal close; save response with `plan: null` does not open modal (graceful handling); save response with `plan` absent does not throw; re-opening edit dialog without saving does not re-open plan modal |

### E2E Tests (`e2e/tests/`)

| File | Coverage |
|------|----------|
| `e2e/tests/agent-plan-mode.spec.ts` | **Mocked suite** — `page.route()` for `/api/v1/agents/types` POST and PUT: create journey (fill form → save → modal opens → step list visible → diagram rendered → dismiss → table row present); update journey (edit type → save → modal opens with plan → dismiss → table updated without reload); failed plan journey (mock returns `generation_status = failed` → modal opens → error message visible → dismiss → agent type saved correctly); viewport tests (desktop 1280×800, tablet 768×1024 — modal usable); i18n key smoke test (no raw key strings visible in rendered modal text); **Real Backend Integration - Agent Plan Mode** (no `page.route()` mock): create an agent type via real API → verify response body contains `plan` field with valid `generation_status` → verify `PlanPreviewModal` opens → dismiss → delete agent type → verify no orphan `agent_plans` row remains in DB (via a backend health check or separate DB assertion query) |
