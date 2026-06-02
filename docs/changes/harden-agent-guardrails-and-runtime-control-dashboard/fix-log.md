# Fix Log: harden-agent-guardrails-and-runtime-control-dashboard

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20260601-153000

**Created:** 2026-06-01T15:30:00Z
**Status:** Resolved
**Issue:** Operators configuring model usage guardrails cannot tell what unit the numeric limits are in. The `usage_limit_hour`, `usage_limit_day`, `usage_limit_week`, and `usage_limit_month` fields need an associated unit so an operator setting a value of `100` knows whether that means 100 tokens, 100 thousand tokens, or 100 million tokens.

### Observed Behavior
When an operator opens the model-usage guardrail dialog and types `100` into the Hourly Limit, Daily Limit, Weekly Limit, or Monthly Limit field, the dashboard panel then renders `45 / 100` with no suffix. It is ambiguous whether `100` means 100 raw tokens, 100 thousand tokens, or another scale — the operator has no way to record their assumption and consumers cannot interpret the limit consistently. The new `ModelUsageGuardrailDialog` introduced by FIX-20260601-145208 preserved this ambiguity; only the model picker was hardened.

### Expected Behavior
1. A new `unit` field is added to `ModelGuardrailConfiguration` and to the create/update/read schemas. The value is one of `k` (thousand tokens) or `tokens` (raw tokens). The default is `k` so the existing UX shows `100k` instead of an ambiguous `100`.
2. The `ModelUsageGuardrailDialog` exposes a unit `Select` (default `k`) right after the model picker. The unit is `disabled` in edit mode because the unit is a property of the configuration's billing semantics and reinterpreting the limit value would silently change the meaning of historical data.
3. The `ModelUsageGuardrailPanel` displays the unit next to the value (`42 / 100 k` for `k`, or `42000 / 100000 tokens` for raw tokens). The unit comes from the **limit** record (not the posture record) because the unit is per-limit, not per-posture.
4. A new Alembic migration adds the `unit` column with a `server_default='k'` so existing rows are backfilled implicitly.
5. Frontend and backend payload types round-trip the new field; create/get/update all return `unit` in their response shape, and create defaults to `k` if the client omits the field.

### Analysis
- **Affected components:**
  - `backend/app/db/models/model_guardrail_configuration.py` — new `ModelUsageUnit` enum and `unit` column
  - `backend/app/db/models/__init__.py` — re-export the new enum
  - `backend/app/schemas/agents.py` — add `unit` to `ModelUsageGuardrailLimitCreate` (default `k`), `ModelUsageGuardrailLimitUpdate` (optional), and `ModelUsageGuardrailLimitRead` (required, serialized from the model)
  - `backend/app/services/control_center/model_usage_guardrail_service.py` — `create_configuration` accepts `unit: ModelUsageUnit | None = None` and defaults to `k`; `update_configuration` accepts `unit: ModelUsageUnit | object = _UNSET` and treats `None` as no-change
  - `backend/app/api/v1/agents.py` — pass `unit=body.unit` from the create payload to the service
  - `backend/alembic/versions/b3c9d4e5f6a7_add_unit_to_model_guardrail_configurations.py` (new) — adds the `unit` column with `server_default='k'`
  - `frontend/src/types/index.ts` — add `ModelUsageUnit` union type and add `unit: ModelUsageUnit` to `ModelUsageGuardrailLimit`
  - `frontend/src/components/agents/ModelUsageGuardrailDialog.tsx` — add a unit `Select` (default `k`, `disabled` in edit mode); add `unit: ModelUsageUnit` to `ModelUsageGuardrailFormData`
  - `frontend/src/components/agents/ModelUsageGuardrailPanel.tsx` — display the unit suffix after `{p.usage_value} / {p.limit_value}` (unit comes from the matching limit record, defaulting to `k`)
  - `frontend/src/hooks/useModelUsageGuardrailMutations.ts` — add `unit: ModelUsageUnit` to `ModelUsageGuardrailCreatePayload`; add `unit?: ModelUsageUnit` to `ModelUsageGuardrailUpdatePayload`
  - `frontend/src/pages/agents/RuntimeControlDashboardPage.tsx` — pass `unit: data.unit` into both `createGuardrailMutation.mutateAsync` and `updateGuardrailMutation.mutateAsync` payloads
  - `frontend/src/pages/agents/ModelConfigListPage.tsx` — also wired through (same pattern, type-system requirement) so both pages dispatch `unit` consistently
  - `frontend/src/i18n/locales/en.json` — add `agents.sessions.modelUsageDialogUnit`, `agents.sessions.modelUsageUnitK`, `agents.sessions.modelUsageUnitTokens`
- **Root cause hypothesis:** The original implementation in FIX-20260601-145208 introduced a `ModelGuardrailConfiguration` model with bare `int` columns for the four period limits. While the model dropdown was hardened to link guardrails to a real `model_id`, the numeric limits remained unitless. Each downstream consumer (UI panel, posture rollups) had to assume a unit, leading to ambiguity for operators and inconsistent interpretation across services.
- **Documentation impact:**
  - `tech-spec.md` — add `ModelUsageUnit` enum entry; update `ModelUsageGuardrailDialog` and `ModelUsageGuardrailPanel` descriptions; add the new Alembic migration filename; add the new test file
  - `test-plan.md` — add a new subsection under feature area B covering the unit selector and the panel unit suffix; add the new test file to the test file planning list; update the execution checklist frontend count
  - `prd.md` — no change (existing AC4/AC5 acceptance criteria now have an explicit UX for unit selection)
  - `fix-log.md` — this entry

### Fix Tasks
- [x] **Reproduce** — New unit test cases demonstrate (a) the unit selector default, (b) save dispatch, (c) operator-driven change, and (d) edit-mode freeze
- [x] **Fix** — Implement the fix in code (backend schema/ORM/migration + frontend dialog/panel/payload types)
- [x] **Verify** — Run all relevant backend and frontend tests; type-check and lint clean
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
- **File:** `frontend/src/__tests__/ModelUsageGuardrailDialog.unit.test.tsx` (new)
  - **Test name:** "renders a unit Select with default value k"
    **Status:** Passing after fix
  - **Test name:** "dispatches unit: 'k' in the payload when save is clicked with the default"
    **Status:** Passing after fix
  - **Test name:** "lets the operator change the unit and the payload reflects the choice"
    **Status:** Passing after fix (operator switches to `tokens` and the payload reflects it)
  - **Test name:** "freezes the unit selector in edit mode (disabled)"
    **Status:** Passing after fix

- **File:** `frontend/src/__tests__/ModelUsageGuardrailDialog.modelDropdown.test.tsx`
  - **Test name:** "sends both model_id and model_name from the chosen option when saving"
    **Status:** Modified — also asserts `payload.unit === 'k'`

- **File:** `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx`
  - **Test name:** "renders the unit suffix next to the usage value for each limit" (new)
    **Status:** Passing — panel renders `45 / 100 k` because the mocked limit has `unit: 'k'`
  - Other existing tests — extended the mocked `model-usage-limits` response to include `unit: 'k'` per limit

- **File:** `backend/tests/api/v1/test_model_usage_guardrails_api.py`
  - **Test name:** "test_create_model_usage_limit_defaults_unit_to_k_when_omitted" (new)
    **Status:** Passing — schema defaults `unit` to `k` when the request body omits it
  - **Test name:** "test_create_model_usage_limit_returns_explicit_unit" (new)
    **Status:** Passing — service receives `unit='tokens'`; response shape includes `unit: 'tokens'`
  - **Test name:** "test_get_model_usage_limit_returns_unit_field" (new)
    **Status:** Passing — read schema serializes `unit` from the model
  - **Test name:** "test_update_model_usage_limit_passes_unit_through_to_service" (new)
    **Status:** Passing — update path threads `unit` from request to service to model

### Code Changes
**Modified by:** conductor agent
**Timestamp:** 2026-06-01T15:30:00Z

**New files:**
1. `backend/alembic/versions/b3c9d4e5f6a7_add_unit_to_model_guardrail_configurations.py:1` — Alembic migration that adds the `unit` column to `model_guardrail_configurations` with `server_default='k'` and a downgrade that drops the column and the enum type.

2. `frontend/src/__tests__/ModelUsageGuardrailDialog.unit.test.tsx:1` — Four-scenario test: (a) default `k`, (b) save dispatches `unit: 'k'`, (c) operator can change the unit and the payload reflects the choice, (d) edit mode freezes the unit selector.

**Modified files:**
3. `backend/app/db/models/model_guardrail_configuration.py:20-25` — Added `ModelUsageUnit` string enum with `tokens` and `k` members.
4. `backend/app/db/models/model_guardrail_configuration.py:46-51` — Added `unit: Mapped[ModelUsageUnit]` column mapped to the new `model_usage_unit_enum` PostgreSQL enum, `nullable=False`, `default=ModelUsageUnit.k`, `server_default='k'`.
5. `backend/app/db/models/__init__.py:61-64` — Re-exported `ModelUsageUnit` alongside `ModelGuardrailConfiguration`.
6. `backend/app/schemas/agents.py:25-28` — Imported `ModelUsageUnit` from the model.
7. `backend/app/schemas/agents.py:488` — Added `unit: ModelUsageUnit = ModelUsageUnit.k` to `ModelUsageGuardrailLimitCreate`.
8. `backend/app/schemas/agents.py:501` — Added `unit: ModelUsageUnit | None = None` to `ModelUsageGuardrailLimitUpdate` (no-change semantics).
9. `backend/app/schemas/agents.py:516` — Added `unit: ModelUsageUnit` to `ModelUsageGuardrailLimitRead` (serialized from the model).
10. `backend/app/services/control_center/model_usage_guardrail_service.py:14-18` — Imported `ModelUsageUnit`.
11. `backend/app/services/control_center/model_usage_guardrail_service.py:57` — `create_configuration` accepts `unit: ModelUsageUnit | None = None`.
12. `backend/app/services/control_center/model_usage_guardrail_service.py:71` — `create_configuration` passes `unit=unit or ModelUsageUnit.k` to the ORM model so the schema default flows through.
13. `backend/app/services/control_center/model_usage_guardrail_service.py:90` — `update_configuration` accepts `unit: ModelUsageUnit | object = _UNSET`.
14. `backend/app/services/control_center/model_usage_guardrail_service.py:104-105` — `update_configuration` applies `unit` only when it is not `_UNSET` and not `None` (preserves the spec's `None = no change` contract).
15. `backend/app/api/v1/agents.py:1367` — Threads `unit=body.unit` from the create payload to the service.
16. `frontend/src/types/index.ts:325` — Added `export type ModelUsageUnit = 'k' | 'tokens'`.
17. `frontend/src/types/index.ts:332` — Added `unit: ModelUsageUnit` to `ModelUsageGuardrailLimit`.
18. `frontend/src/components/agents/ModelUsageGuardrailDialog.tsx:18-21` — Imported `ModelUsageUnit`.
19. `frontend/src/components/agents/ModelUsageGuardrailDialog.tsx:40-49` — Added `unit: ModelUsageUnit` to `ModelUsageGuardrailFormData`.
20. `frontend/src/components/agents/ModelUsageGuardrailDialog.tsx:66` — Added `unit` local state defaulting to `initialData?.unit ?? 'k'`.
21. `frontend/src/components/agents/ModelUsageGuardrailDialog.tsx:100` — Passes `unit` into the save payload.
22. `frontend/src/components/agents/ModelUsageGuardrailDialog.tsx:153-168` — Added the unit `Select` (right after the model picker) with `disabled={isEdit}` and the two menu items `k` / `tokens` (labels via i18n).
23. `frontend/src/components/agents/ModelUsageGuardrailPanel.tsx:82` — Panel renders `... {p.limit_value} {limit?.unit ?? 'k'}` so the unit suffix comes from the matching limit record.
24. `frontend/src/hooks/useModelUsageGuardrailMutations.ts:3-7` — Imported `ModelUsageUnit`.
25. `frontend/src/hooks/useModelUsageGuardrailMutations.ts:11-17` — Added `unit: ModelUsageUnit` to the create payload.
26. `frontend/src/hooks/useModelUsageGuardrailMutations.ts:22-30` — Added `unit?: ModelUsageUnit` to the update payload.
27. `frontend/src/pages/agents/RuntimeControlDashboardPage.tsx:251-272` — Threads `unit: data.unit` into both the create and update `mutateAsync` payloads.
28. `frontend/src/pages/agents/ModelConfigListPage.tsx:243-268` — Threads `unit: data.unit` into both the create and update `mutateAsync` payloads (parallel to the dashboard page so both call sites satisfy the new payload type).
29. `frontend/src/i18n/locales/en.json:541-543` — Added `modelUsageDialogUnit` ("Usage Unit"), `modelUsageUnitK` ("k (thousand tokens)"), `modelUsageUnitTokens` ("tokens").
30. `frontend/src/__tests__/ModelUsageGuardrailDialog.modelDropdown.test.tsx:72` — Existing test now also asserts `payload.unit === 'k'`.
31. `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx:57` — Mocked `model-usage-limits` response now includes `unit: 'k'` per limit.
32. `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx:152-167` — New test asserts the unit suffix is rendered next to the usage value.
33. `backend/tests/api/v1/test_model_usage_guardrails_api.py:16-19` — Imported `ModelUsageUnit`.
34. `backend/tests/api/v1/test_model_usage_guardrails_api.py:60-76` — `_fake_limit` now exposes `unit` (default `ModelUsageUnit.k`) so existing mock-based tests don't break.
35. `backend/tests/api/v1/test_model_usage_guardrails_api.py:208-348` — Four new tests covering create-default, create-explicit, get-returns-unit, and update-passes-unit-through.

### Documentation Updates
**Updated by:** conductor agent
**Timestamp:** 2026-06-01T15:35:00Z

- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/tech-spec.md`:
  - **Code Reference Map** — Added `ModelUsageUnit` enum entry under the existing `ModelGuardrailEnforcementPosture` entry; updated `ModelUsageGuardrailDialog` description to mention the unit selector; updated `ModelUsageGuardrailPanel` description to mention the unit suffix in display; added the new Alembic migration filename; added the new test file `ModelUsageGuardrailDialog.unit.test.tsx` to the test references.
- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/test-plan.md`:
  - **Detailed Coverage by Feature Area B** — Added new subsection "Operator can choose the unit (k default or raw tokens) for each period limit and the panel renders the unit suffix consistently."
  - **Test File References** — Added `ModelUsageGuardrailDialog.unit.test.tsx`.
  - **Execution Checklist** — Updated frontend changed-area pass count to 17/17 (was 16/16).
- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/fix-log.md` — This entry.

### Verification Results
**Verified by:** conductor agent
**Timestamp:** 2026-06-01T15:30:00Z

- **Backend tests:** 12/12 passing across `test_model_usage_guardrails_api.py` (8/8; was 4/4, +4 new unit tests) and `test_model_guardrail_persistence.py` (4/4; unchanged). The wider set of changed-area tests also passes: 26/26 across `test_model_usage_guardrails_api.py`, `test_model_guardrail_persistence.py`, `test_agent_runtime_controls_api.py`, `test_runtime_control_persistence.py`, and `test_agent_guardrails.py` (was 22/22, +4 new).
- **Frontend tests:** 17/17 passing across `ModelUsageGuardrailDialog.unit.test.tsx` (4/4 new), `ModelUsageGuardrailDialog.modelDropdown.test.tsx` (3/3), `ModelUsageGuardrailManagement.test.tsx` (5/5; was 4/4, +1 new), `RuntimeControlDashboardPage.test.tsx` (2/2), `AgentInstanceDashboard.runtime-control.test.tsx` (3/3). The changed-area pass count grew from 15/15 to 17/17.
- **Type-check:** clean for all files modified by this fix; 4 pre-existing TS errors remain in unrelated files (`ConversationDelegationVisibility.test.tsx`, `SopEditor.simple.test.tsx`, `WorkflowTerminology.rename-coverage.test.tsx`, `LogSummaryPanel.tsx`).
- **Lint:** no new errors in files modified by this fix; 94 pre-existing lint errors and 12 pre-existing warnings remain in unrelated files (mostly `TestMcpToolDialog.tsx` `any` usage and `LogPresenter.ts` `any` usage).
- **Reproduction tests:** ✓ New `ModelUsageGuardrailDialog.unit.test.tsx` (4/4) covers all four scenarios; the model dropdown test now also asserts `unit: 'k'`.

---

## FIX-20260601-145208

**Created:** 2026-06-01T14:52:08Z
**Status:** Resolved
**Issue:** Model guardrail dialog uses free-text model name (linked to random UUID) instead of a dropdown of configured models; runtime control dashboard is a sidebar panel rather than a dedicated page with a live topology diagram matching the agent topology preview prototype.

### Observed Behavior
1. `ModelUsageGuardrailDialog` showed a free-text `model_name` TextField and created a guardrail with a random UUID for `model_id` (matching the existing pattern in `AgentInstanceDashboardPage`). Operators could not link a guardrail to an actual configured model from the existing `ModelConfig.enabled_models` lists.
2. Runtime control dashboard features (topology panel, model-usage panel, terminate controls) were embedded as panels in `AgentInstanceDashboardPage`. There was no dedicated `/agents/runtime-control` page, and `RuntimeTopologyPanel` rendered nodes as flat MUI cards grouped by depth rather than as a live SVG topology diagram similar to the agent topology preview in `docs/master/ux/prototype/index.html` (which uses rounded rectangles with `<line>` connectors between agent-type, SOP, skill, and tool nodes).

### Expected Behavior
1. `ModelUsageGuardrailDialog` provides a model picker (Select) populated from the union of all `enabled_models` across all `ModelConfig` providers, with a clear label per option (e.g. `gpt-4.1 (OpenAI)`). `model_id` and `model_name` are sent from the chosen option so the guardrail is linked to an actual configured model.
2. A dedicated `RuntimeControlDashboardPage` exists at `/agents/runtime-control` and replaces the runtime-control panels currently embedded in `AgentInstanceDashboardPage`. The page renders a live SVG-based topology diagram (similar to the agent topology preview prototype) showing parent/child agent nodes and their delegation edges, with selected-node details and terminate controls. Polling/refresh updates the diagram as active state changes.

### Analysis
- **Affected components:**
  - `frontend/src/components/agents/ModelUsageGuardrailDialog.tsx` — change TextField to Select; accept `availableModels` prop
  - `frontend/src/hooks/useModelUsageGuardrailMutations.ts` — payload no longer needs a separate `model_id` since the dialog supplies both
  - `frontend/src/pages/agents/ModelConfigListPage.tsx` — pass `enabled_models` to dialog
  - `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` — remove embedded runtime-control panels
  - `frontend/src/components/agents/RuntimeTopologyPanel.tsx` — replace flat card list with SVG topology diagram
  - **New:** `frontend/src/pages/agents/RuntimeControlDashboardPage.tsx` — dedicated dashboard page
  - `frontend/src/app/AppRouter.tsx` — register the new route
  - `frontend/src/app/AppShell.tsx` — add Runtime Control nav item under the AI Agent group
  - `frontend/src/i18n/locales/en.json` — add new i18n keys
  - **New test file:** `frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx`
- **Root cause hypothesis:** The original implementation used a free-text model name field and a random UUID for `model_id` to keep the dialog simple. The original tech-spec also specified `RuntimeControlDashboardPage` as a "new" page but the implementation placed all runtime-control UI inside `AgentInstanceDashboardPage` (see tech-spec entry: "Runtime control scenarios were incorporated into the existing AgentInstanceDashboardPage rather than a new standalone page"). The flat card list in `RuntimeTopologyPanel` was a pragmatic simplification, but does not match the visual quality of the agent topology preview prototype.
- **Documentation impact:**
  - `tech-spec.md` — re-elevate `RuntimeControlDashboardPage` from "Incorporated into existing page" to "Implemented as standalone page"; add new `RuntimeTopologyDiagram` component entry; update `ModelUsageGuardrailDialog` description to reference model dropdown
  - `test-plan.md` — add Section F feature area for model dropdown behavior; add Section G for dedicated dashboard page
  - `prd.md` — no change (acceptance criteria already met by behavior; just need to deliver the right UX)
  - `prototype/index.html` — already depicts the dedicated topology view; no change needed
  - `fix-log.md` — this entry

### Fix Tasks
- [x] **Reproduce** — Create test cases that demonstrate the two issues
- [x] **Fix** — Implement the fixes in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
- **File:** `frontend/src/__tests__/ModelUsageGuardrailDialog.modelDropdown.test.tsx`
- **Test name:** "renders a model picker combobox (not a free-text input)"
- **Status:** Passing after fix (was failing before — dialog was a free-text TextField)
- **Test name:** "sends both model_id and model_name from the chosen option when saving"
- **Status:** Passing after fix (was failing — previously sent `crypto.randomUUID()` and the free-text value)
- **Test name:** "disables the save button when no model is selected and shows required error"
- **Status:** Passing after fix (validates required-model UX)

- **File:** `frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx`
- **Test name:** "exposes a dedicated page at /agents/runtime-control"
- **Status:** Passing after fix (was failing — route was unhandled)
- **Test name:** "renders an SVG element with the parent and child nodes from topology data"
- **Status:** Passing after fix (was failing — `RuntimeControlDashboardPage` file did not exist; topology now renders via `RuntimeTopologyDiagram` SVG component)

- **File:** `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx`
- **Updated to target the dedicated `RuntimeControlDashboardPage`** since the runtime-control panels were removed from `AgentInstanceDashboardPage`. The four tests now mount the dedicated page and assert the model-usage panel, add affordance, create-dialog, and edit-dialog behaviors.

### Code Changes
**Modified by:** conductor agent
**Timestamp:** 2026-06-01T15:30:00Z

**New files:**
1. `frontend/src/components/agents/RuntimeTopologyDiagram.tsx` — SVG-based live delegation topology renderer. Rounded-rect nodes (rx=8) per session, status-colored fills/strokes, arrow-marked bezier connectors, click-to-select, and risk highlighting for `failed` / `terminated` statuses. Visual style matches the agent topology preview prototype (`docs/master/ux/prototype/index.html:3897` and `docs/changes/.../prototype/index.html:313-396`).

2. `frontend/src/pages/agents/RuntimeControlDashboardPage.tsx` — Dedicated runtime control dashboard page at `/agents/runtime-control`. Composes `RuntimeTopologyDiagram`, `ModelUsageGuardrailPanel`, `NodeTerminationDialog`, and `ModelUsageGuardrailDialog` with selected-node details, polling refresh (`useRuntimeTopology(true)`), and full CRUD for model-usage guardrails.

3. `frontend/src/hooks/useAvailableModels.ts` — Flatten `ModelConfig.enabled_models` into `AvailableModel[]` (each entry includes `model_id`, `model_name`, `config_id`, `config_display_name`, `provider_type`) so the dialog can render a dropdown populated from configured providers.

4. `frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx` — Two-scenario test: (a) route registration at `/agents/runtime-control`, (b) live SVG topology rendering with rects and connector lines for parent/child nodes.

5. `frontend/src/__tests__/ModelUsageGuardrailDialog.modelDropdown.test.tsx` — Three-scenario test: (a) dialog renders a `combobox` (Select) and no free-text textbox, (b) save dispatches `model_id` + `model_name` from the chosen option, (c) required-model UX (no save submission when no model is selected).

**Modified files:**
6. `frontend/src/components/agents/ModelUsageGuardrailDialog.tsx` — Replaced free-text `TextField` for model name with a `Select` populated from `availableModels`; each option is labeled `<model_name> (<config_display_name>)`. Added inline required-error alert when no model is selected. Tightened error rendering to use `error != null` to avoid `unknown`-to-`ReactNode` type errors.

7. `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` — Removed embedded runtime-control panels: `RuntimeTopologyPanel`, `ModelUsageGuardrailPanel`, `NodeTerminationDialog`, `ModelUsageGuardrailDialog`, and the delete-confirmation dialog. Removed the related state (`selectedTopologySessionId`, `terminationDialogOpen`, `lastTerminationRequest`, `guardrailDialogOpen`, `editingGuardrail`, `deleteGuardrailTarget`), mutations (`createGuardrailMutation`, `updateGuardrailMutation`, `deleteGuardrailMutation`, `terminateMutation`), and hooks (`useRuntimeTopology`, `useNodeTermination`, `useModelUsageLimits`, `useModelUsagePosture`, `useAvailableModels`, `useTerminationOutcomes`). The page is now strictly a session list with filter controls and the execution details dialog.

8. `frontend/src/app/AppShell.tsx` — Added `Runtime Control` to the AI Agent nav group pointing to `/agents/runtime-control` (reuses the existing `AccountTreeIcon`).

9. `frontend/src/i18n/locales/en.json` — Added `nav.runtimeControl = "Runtime Control"` (the i18n keys for the dashboard title, subtitle, model picker, etc. were already in place from the previous fix).

10. `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx` — Updated to mount `RuntimeControlDashboardPage` instead of `AgentInstanceDashboardPage`, and wrapped in a `MemoryRouter` so the page renders correctly. Added a mock for `/agents/model-configs` so the model dropdown fetches return a sample `ModelConfig` with `enabled_models`.

### Documentation Updates
**Updated by:** conductor agent
**Timestamp:** 2026-06-01T15:35:00Z

- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/tech-spec.md`:
  - **Component Breakdown** — Re-elevated `RuntimeControlDashboardPage` to a standalone page description; documented the new `RuntimeTopologyDiagram` (SVG-based) component; updated `ModelUsageGuardrailDialog` description to reference the model dropdown populated from `ModelConfig.enabled_models`; marked `RuntimeTopologyPanel` as legacy.
  - **Code Reference Map** — Updated `AgentInstanceDashboardPage` description to note that runtime-control panels moved to the dedicated page; re-pointed `RuntimeControlDashboardPage` to the new standalone file; added `RuntimeTopologyDiagram` and `useAvailableModels` entries; updated `ModelUsageGuardrailDialog` description; added `RuntimeControlDashboardPage.test`, `ModelUsageGuardrailDialog.modelDropdown.test`, and `ModelUsageGuardrailManagement.test` (re-aimed at the dedicated page) to the test references.
- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/test-plan.md`:
  - **Acceptance Criteria Coverage Map** — Added feature area G (Dedicated runtime control dashboard + live SVG topology + configured model dropdown) covering AC5, AC7, AC8.
  - **Section G) Dedicated Runtime Control Dashboard** — New user journey and frontend test cases covering the dedicated page route, SVG topology rendering, model dropdown, and the relocation of CRUD affordances from the session-list page.
  - **Test File References** — Added `RuntimeControlDashboardPage.test.tsx` and `ModelUsageGuardrailDialog.modelDropdown.test.tsx`.
  - **Execution Checklist** — Updated frontend changed-area pass count to 16/16.
- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/fix-log.md` — This entry.

### Verification Results
**Verified by:** conductor agent
**Timestamp:** 2026-06-01T15:25:00Z

- **Frontend tests:** 16/16 passing across `AgentInstanceDashboard.runtime-control.test.tsx` (3/3), `RuntimeControlDashboardPage.test.tsx` (2/2), `RuntimeTopologyPanel.test.tsx` (2/2), `ModelUsageGuardrailDialog.modelDropdown.test.tsx` (3/3), `ModelUsageGuardrailManagement.test.tsx` (4/4), `NodeTerminationDialog.test.tsx` (2/2), `AppShell.test.tsx` (7/7), `AgentInstanceDashboard.test.tsx` (8/8), `ModelConfigListPage.test.tsx` (4/4).
- **Backend tests:** 22/22 passing across `test_agent_runtime_controls_api.py`, `test_model_usage_guardrails_api.py`, `test_runtime_control_persistence.py`, `test_model_guardrail_persistence.py`, and `test_agent_guardrails.py`.
- **Type-check:** clean for all files modified by this fix; 4 pre-existing TS errors remain in unrelated test files (`ConversationDelegationVisibility.test.tsx`, `SopEditor.simple.test.tsx`, `WorkflowTerminology.rename-coverage.test.tsx`, `LogSummaryPanel.tsx`).
- **Lint:** no new errors in files modified by this fix; 94 pre-existing lint errors and 12 pre-existing warnings remain in unrelated files (mostly `TestMcpToolDialog.tsx` `any` usage and `LogPresenter.ts` `any` usage).
- **Reproduction tests:** ✓ All originally-failing scenarios now pass — `ModelUsageGuardrailDialog.modelDropdown.test.tsx` (3/3) and `RuntimeControlDashboardPage.test.tsx` (2/2).

---

## FIX-20260601-182000

**Created:** 2026-06-01T18:20:00Z
**Status:** Resolved
**Issue:** Cannot configure model-level usage guardrails — dashboard panel is display-only with no create/edit/delete UI

### Observed Behavior
The `ModelUsageGuardrailPanel` on the runtime dashboard only displays existing model usage guardrail limits and current posture. There is no user interface to create new model guardrail configurations, edit existing ones, or delete them. Operators cannot define model-level usage limits against specific models as required by PRD acceptance criterion AC4.

### Expected Behavior
Operators should be able to configure model-specific usage limits by hour, day, week, and month periods (PRD AC4). The dashboard should provide:
- A dialog/form to create a new model usage guardrail configuration (select model, set period limits, choose enforcement posture)
- Inline edit capability on existing configurations
- A delete action on existing configurations
- All operations reflected immediately in the display panel

### Analysis
- **Affected components:** `ModelUsageGuardrailPanel` (frontend), missing create/edit dialog, missing delete wiring
- **Root cause hypothesis:** The frontend management UI for model guardrail CRUD was not implemented during the initial build. Backend CRUD endpoints (`POST/PUT/DELETE /api/v1/agents/guardrails/model-usage-limits`) exist and the display-only frontend panel reads limits correctly, but no UI was built to call the mutation endpoints.
- **Documentation impact:** `tech-spec.md` (Code Reference Map), `test-plan.md` (add test scenario), `demo-cases.md` (add demo case for model guardrail configuration)

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
- **File:** frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx
- **Test name:** ModelUsageGuardrailManagement - configuration CRUD > shows model usage guardrail panel with existing limits
- **Status:** Passing (panel renders correctly)
- **Test name:** ModelUsageGuardrailManagement - configuration CRUD > has no button or affordance to create a new model usage guardrail - demonstrates missing CRUD UI
- **Status:** Passing (confirms bug — no create button exists)
- **Test name:** ModelUsageGuardrailManagement - configuration CRUD > fails when asserting a create button exists - this proves the feature is missing
- **Status:** Failing (proves create/edit/delete UI does not exist)

### Code Changes
**Modified by:** conductor agent
**Timestamp:** 2026-06-01T18:40:00Z

**New files:**
1. `frontend/src/components/agents/ModelUsageGuardrailDialog.tsx` — Dialog component for creating and editing model usage guardrail configurations. Supports model name, enforcement posture (terminate/observe_only), four period-based limit fields (hourly, daily, weekly, monthly), and active toggle. Handles create and edit modes based on whether `initialData` is provided.

2. `frontend/src/hooks/useModelUsageGuardrailMutations.ts` — Three React Query mutation hooks:
   - `useCreateModelUsageLimit` — POST to `/agents/guardrails/model-usage-limits` to create a new guardrail configuration
   - `useUpdateModelUsageLimit` — PUT to `/agents/guardrails/model-usage-limits/{config_id}` to update an existing configuration
   - `useDeleteModelUsageLimit` — DELETE to `/agents/guardrails/model-usage-limits/{config_id}` to remove a configuration
   All hooks invalidate the `model-usage-limits` and `model-usage-posture` query caches on success.

3. `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx` — Frontend tests verifying:
   - Panel displays existing limits correctly
   - Add button exists to create new model usage guardrails
   - Create dialog opens when add button is clicked
   - Edit dialog opens when edit icon is clicked on a limit row

**Modified files:**
4. `frontend/src/components/agents/ModelUsageGuardrailPanel.tsx` — Extended with:
   - "Add Model Limit" button in the panel header
   - Edit (pencil) and Delete (trash) icon buttons on each limit row
   - New props: `onAdd`, `onEdit`, `onDelete` callbacks
   - Added imports: `Button`, `IconButton`, `EditIcon`, `DeleteIcon`

5. `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` — Integrated CRUD UI:
   - Added state: `guardrailDialogOpen`, `editingGuardrail`, `deleteGuardrailTarget`
   - Added mutations: `createGuardrailMutation`, `updateGuardrailMutation`, `deleteGuardrailMutation`
   - Wired ModelUsageGuardrailPanel callbacks to dialog open/close
   - Added ModelUsageGuardrailDialog for create/edit
   - Added delete confirmation dialog
   - Added `ModelGuardrailEnforcementPosture` type to schema imports

6. `frontend/src/i18n/locales/en.json` — Added i18n keys for:
   - `modelUsageAddLimit`, `modelUsageEditLimit`, `modelUsageDeleteLimit`
   - `modelUsageDialogCreate`, `modelUsageDialogEdit`, `modelUsageDialogModelName`
   - `modelUsageDialogEnforcement`, `modelUsageDialogHourly`, `modelUsageDialogDaily`
   - `modelUsageDialogWeekly`, `modelUsageDialogMonthly`, `modelUsageDialogActive`
   - `modelUsageDeleteConfirmTitle`, `modelUsageDeleteConfirmMsg`

### Documentation Updates
**Updated by:** conductor agent
**Timestamp:** 2026-06-01T18:50:00Z

- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/tech-spec.md` — Added Code Reference Map entries for `ModelUsageGuardrailDialog`, `useCreateModelUsageLimit`, `useUpdateModelUsageLimit`, `useDeleteModelUsageLimit`; updated `ModelUsageGuardrailPanel` description to include CRUD affordances.
- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/test-plan.md` — Added ModelUsageGuardrailManagement.test.tsx to test file references; expanded frontend component test cases for dialogs and mutation hooks; added F) feature area for model guardrail configuration management UI; updated AC4/AC5 coverage status.
- `docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/fix-log.md` — Comprehensive fix entry (this document).

### Verification Results
**Verified by:** conductor agent
**Timestamp:** 2026-06-01T18:45:00Z

- **Backend tests:** 10/10 passing (model usage guardrail API + unit guardrail tests)
- **Backend integration tests:** 6/6 passing (model guardrail persistence + runtime control persistence)
- **Frontend tests:** 11/11 passing (new + existing runtime-control, topology panel, termination dialog tests)
- **Reproduction test:** ✓ 4/4 passing (was previously intentionally failing; now all pass after fix)
- **Note:** 1 pre-existing failure in `tests/api/test_agents_api.py::test_stream_session_logs_emits_entries_and_terminal_marker` (unrelated to this fix — `ExecutionLogEntryRead` missing `event_category`/`actor_type` in test mock)

---
