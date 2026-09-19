# Test Plan — Agent Management Panel

## 1. Test Strategy

This test plan validates the **Agent Management Panel** — a full-page, three-region composition surface (`/agents/panel`) where administrators create, edit, and equip agents without visiting the individual module pages. It covers the agent CRUD lifecycle through the panel, inline create-and-assign for all seven equipment slots, live client-side topology composition, the Communication Hub node in both the panel and existing preview topologies, the unsaved-changes tray, and permission degradation.

This change is **frontend-only composition** (`has_db_changes: false`): no API, schema, or inter-service changes. The backend remains a consumer of existing endpoints exactly as today — **no backend tests, migration tests, or database verification are required**. Because everything above the existing endpoints moved, the testing weight shifts to the frontend component layer, with E2E validating the full lifecycle against the running stack.

| Layer | Framework | Scope |
|---|---|---|
| **Frontend Component (primary)** | Vitest + React Testing Library | Draft composition hook (init from fetched agent, dirty tracking, per-slot mutations, snapshot/discard, single-PUT save payload, guard integration); panel page shell (three-region layout, selection, header CRUD, dialog error display); equipment slots (assign/unassign/inline-create contract, gating, conversational output lock); pending-changes tray; live topology canvas (re-render on draft mutation, zero API calls, hub node, pure builder); shared resource picker dialog (search, pagination, single/multi modes, slot apply semantics, 403 degradation); extended renderer/preview/shell coverage (`communication_hub` node type, legend, helper idempotence, preview topology hub node, `/agents/panel` nav entry) |
| **E2E (Mocked-first)** | Playwright + `page.route()` | Full agent CRUD lifecycle through the panel with parent auto-refresh (no-reload) assertions; inline create-and-assign per slot with identical-dialog equivalence; live topology with zero-network-request assertions via a request-observer route; agent-switch re-render with unsaved-changes guard; hub node in existing preview topologies; slot-level 403 degradation, sidebar 403, read-only browsing, 403-on-save tray behavior |
| **E2E (Real Backend)** | Playwright (no mocks) | One gated CRUD-lifecycle variant through the panel against the live stack — probes the backend at runtime and **skips cleanly** when the stack or the test user's permissions are unavailable (no DB changes to validate; the unmocked variant catches wiring issues mocks miss) |
| **Manual / Exploratory** | Manual | Inline identity OAuth popup sign-in against a real provider (Keycloak/EntraID), identity provider unavailable behavior, visual QA of topology layout/legend at slot extremes, localization spot-checks, cross-browser rendering |

**Key testing principles for this change:**

- **Live topology is client-side contract, not decoration**: the topology is composed purely from the draft — every assign/change/remove re-renders immediately with **no network request** (asserted via a request-observer route, not absence-of-visibility timing). This is the PRD's "see exactly what I am about to persist" guarantee and cannot be validated by save-time assertions alone.
- **Zero duplication with identical behavior**: the six relocated dialogs (`AgentRoleDialog`, `AgentIdentityDialog`, `SkillEditor`, `SopEditor`, `DataTypeFormDialog`, `ModelConfigDialog`) are the real shared implementations — tests compare dialog titles, fields, validation, and error handling in the panel against the source module pages; all existing dialog tests must pass unchanged (regression set).
- **True deletion, not soft-hide**: deleting an agent must allow recreating the same name afterwards; every dialog close refreshes the parent panel and sidebar **without a manual page reload**.
- **Permission degradation over error surfaces**: a 403 on a slot's list query disables only that slot's actions with a localized explanation; structured 403s render via the in-dialog `PermissionDeniedAlert` per the **Dialog Error Handling Standard** — never a silent failure.
- **i18n completeness**: every visible panel string renders through `t()` (platform rule: no hardcoded UI text); E2E specs assert localized English copy.

## 2. Coverage Areas

| Area | Why Critical |
|---|---|
| Dialog extraction regression (Phase 1) | Six dialogs relocated to shared implementations; divergence between panel and source module behavior violates the PRD hard requirement of zero duplication with identical behavior |
| Panel agent CRUD lifecycle | Create/read/edit/delete from the header card with accurate values in sidebar + header, pre-populated edit form, delete confirmation, count updates, and recreation with the same name; parent refresh after every dialog close without reload |
| Equipment slots (all seven) | Role, identity, skills, SOPs, input data type, output data type, model — each supports assign-existing, create-inline, and unassign; slot rendering reflects the draft exactly; empty slots show dashed placeholders |
| Resource picker dialog | Shared picker for slot assign-existing: client-side debounced search, pagination, single (replace) vs multi (reconcile) selection semantics, create-new flow with pre-selection of the created row, 403 degradation, long-name tooltip handling |
| Live topology without saving | Composed purely client-side from the draft; mutations re-render immediately with zero API calls; distinct nodes per equipped item plus the fixed Communication Hub node; agent switching re-renders for the newly selected agent |
| Communication Hub node in both topologies | The hub node (dashed "platform messaging" edge, localized legend chip) must appear in the panel live topology AND the existing agent preview topology (details dialog conversational branch, typed/plan branch via plan preview); the hub helper is idempotent — no duplicate node/edge on repeated application |
| Draft state & unsaved-changes tray | Dirty tracking drives the tray (inert while pristine); Save issues exactly one agent-type update; Discard reverts to the last snapshot; the guard fires on agent switch and route navigation |
| Permission gating / degradation | Per-slot gating against existing `agent::*` resource types; slot 403 disables only that slot with a localized explanation; sidebar 403 degrades gracefully without auth-redirect; read-only users browse compositions; 403 on save keeps the draft dirty and surfaces the error in the tray |
| Conversational-agent output-type lock | Conversational agents show a locked output-type slot while the input slot stays configurable; non-conversational agents can set typed outputs |
| i18n & shell integration | All panel strings localize through `t()`; `/agents/panel` route and sidebar nav entry present; app router regression unchanged |

## 3. Critical Scenarios

### Scenario 1: Agent CRUD Lifecycle Through the Panel

- **WHEN** an administrator creates an agent with name, system instruction, and equipment **THEN** the agent appears in the sidebar immediately with all values correctly displayed and the header count updated — no page reload occurred.
- **WHEN** an administrator edits an existing agent **THEN** the form opens pre-populated and, after saving, updated values are visible immediately in sidebar, header, and topology.
- **WHEN** any create/edit dialog is closed **THEN** the parent panel and agent list refresh automatically without a manual reload.
- **WHEN** an administrator deletes an agent with confirmation **THEN** it disappears immediately, related counts update, and a new agent with the same name can be created afterwards (true deletion).
- **WHEN** invalid input is submitted (missing required field, duplicate/casing name) **THEN** a clear validation error is shown and nothing is saved.
- **WHEN** an inline dialog's API call fails (e.g. 403) **THEN** the error renders inside the dialog via the standard permission alert — never a silent failure.

### Scenario 2: Inline Create-and-Assign (Equipment Slots)

- **WHEN** a role is created inline from the role slot **THEN** it persists via its normal endpoint, mounts the **real** Agent Role dialog (same title/fields/validation as the source module), and lands on the draft immediately without leaving the panel.
- **WHEN** an identity is provisioned inline **THEN** the dialog opens and surfaces provider failures through the standard error handling; assign-existing selects the identity immediately (the OAuth popup flow itself remains manual-only).
- **WHEN** skills, SOPs, data types, or model configs are created inline **THEN** each is immediately attached/settable on the draft and visible in the slot and topology, through the real shared dialogs.
- **WHEN** assign-existing and unassign round-trips are performed **THEN** the draft stays consistent (single-slot replace for role/model; order-preserving reconcile for skills/SOPs).

### Scenario 3: Live Topology Without Saving

- **WHEN** equipment is assigned, changed, or removed in a slot **THEN** the topology updates visually immediately with **zero network requests** (request-observer assertion).
- **WHEN** the panel topology is displayed **THEN** it shows distinct nodes for each equipped role, identity, skill, SOP, input/output type, and model, plus the fixed Communication Hub node.
- **WHEN** the administrator switches to a different agent **THEN** the topology re-renders for that agent's saved configuration and the draft resets from fetched data; unsaved changes are guarded (Keep Editing preserves, Discard switches).
- **WHEN** draft changes are discarded **THEN** no state leaks when switching agents and back.

### Scenario 4: Communication Hub in Preview Topologies

- **WHEN** the Agent Types details dialog preview topology is opened (conversational branch and typed/plan branch) **THEN** the Communication Hub node appears connected to the agent with its dashed platform-messaging edge and localized legend chip — exactly once.
- **WHEN** the hub helper is applied to a topology that already contains the hub node **THEN** no duplicate node or edge is added.

### Scenario 5: Unsaved-Changes Tray & Single-PUT Save

- **WHEN** a draft mutation occurs **THEN** the tray lists the pending change with zero write calls issued.
- **WHEN** the administrator saves pending changes **THEN** exactly one agent-type update call is issued and the sidebar/agent caches refresh so saved state is reflected immediately.
- **WHEN** Discard is used **THEN** the draft reverts to the last saved snapshot.
- **WHEN** navigation or agent switching happens with unsaved changes **THEN** the confirmation guard appears.

### Scenario 6: Permission Degradation

- **WHEN** the roles list returns 403 **THEN** only the role slot is disabled with a localized explanation while every other slot keeps working and no error alert appears.
- **WHEN** the agent list returns 403 **THEN** the sidebar degrades gracefully and the session is kept (no auth redirect).
- **WHEN** a read-only user browses the panel **THEN** compositions are viewable and all write actions are disabled with explanations.
- **WHEN** save returns 403 **THEN** the error surfaces in the pending-changes tray and the draft stays dirty.

## 4. Edge Cases & Risks

| Edge Case | Risk | Mitigation |
|---|---|---|
| Create-inline then immediately assign; navigating away mid-flow | Medium | Resource survives server-side; draft loss guarded by the unsaved-changes dialog; no orphaned draft assignment renders |
| Empty states (fresh agent, empty resource lists, empty sidebar, no search matches) | Medium | All seven slots dashed; topology = placeholders + hub; graceful empty notes |
| Concurrent edits (panel vs module page / another tab) | Medium | Last-write-wins on save; panel refetches on selection and never silently merges stale drafts |
| Large collections (many agents, long selector lists, big skill/SOP sets) | Medium | Client-side sidebar filter, paginated picker, binding-order handling; selector usability and render performance |
| OAuth identity provisioning failure mid-flow (popup blocked, consent cancelled, provider unreachable) | Medium | Failure surfaced via the standard error handling; no partial draft assignment |
| Save failure mid-save (network error or 403 on the single update) | High | Tray stays dirty, error surfaced, no partial equipment write |
| Duplicate/casing/whitespace agent names | Low | Rejected consistently with module behavior |
| Dialog host exclusivity & error-state hygiene | Medium | One dialog mounted at a time; Escape/backdrop clears error state; reopening shows a clean form |
| Topology extremes (all slots empty vs all filled) | Medium | Layout stays stable and legible; hub node never overlaps or disappears; legend chip always localized |
| Helper idempotence (panel + plan content in one view) | Medium | Repeated application never duplicates node/edge |
| Data type delete guard | Medium | Data types referenced by agent types cannot be deleted from any panel-reachable path |
| Session expiry mid-panel (401 on slot fetch or save) | Medium | Standard auth redirect without corrupting panel state |
| Delete with dirty draft | Medium | Guard/confirmation ordering verified; selection resets cleanly |
| Highest regression risk: Phase 1 dialog extraction | **High** | All existing dialog and page tests re-run with zero behavioral assertion changes (regression set below) |

## 5. Acceptance Criteria Checklist

Maps 1:1 to the PRD acceptance criteria. Each item is verified by the indicated layer.

### Agent Configuration Lifecycle
- [ ] New agent created from the panel appears in the agent list immediately with all values correctly displayed — **E2E + frontend component**
- [ ] Agent list shows all accessible agents with configuration fields and attached equipment accurately; filtering and search work — **E2E + frontend component**
- [ ] Editing opens the form pre-populated; changes save and are visible immediately — **E2E**
- [ ] Closing any create/edit dialog auto-refreshes the parent panel and agent list without a manual reload — **E2E (no-reload assertion)**
- [ ] Deleting with confirmation removes the agent immediately, updates counts, and the same name can be recreated (true deletion) — **E2E (mocked + real-backend variant)**
- [ ] Validation errors shown for invalid input; duplicate names rejected; required fields enforced; permission errors surfaced gracefully inside dialogs — **E2E + frontend component**

### Inline Resource Creation
- [ ] Existing role assignable or new role creatable inline; immediately available without leaving the panel — **E2E + frontend component**
- [ ] Existing identity assignable or new identity provisioned inline; immediately selectable — **E2E (+ manual OAuth popup)**
- [ ] Existing Skills/SOPs attachable or new ones creatable inline; immediately associated — **E2E**
- [ ] Existing input/output types pickable or new data type creatable inline; immediately settable — **E2E + frontend component**
- [ ] Existing model selectable or new model configuration addable inline; immediately selectable — **E2E**
- [ ] Every inline creation dialog behaves identically (fields, validation, error handling) to its source-module dialog — **E2E (equivalence checks) + regression set**

### Topology Visualization
- [ ] Panel topology shows distinct icons for each equipped item plus the Communication Hub — **E2E + frontend component**
- [ ] Assigning, changing, or removing equipment updates the topology immediately — without saving, and with no network request — **E2E (request observer) + frontend component**
- [ ] Switching agents re-renders the topology for that agent's current configuration — **E2E + frontend component**
- [ ] The existing agent preview topology in the Agent Types view also displays the Communication Hub node connected to the agent — **E2E + frontend component (renderer, details dialog, plan preview)**

### Permissions
- [ ] Panel capabilities respect existing per-module permissions; disabled/hidden actions for unpermitted domains carry a clear localized explanation — **E2E + frontend component**
- [ ] Read access degrades gracefully (no error surfaces) for read-only or partial access — **E2E**

## 6. Test File References

Paths follow `docs/config.yaml` `source.tests` (`frontend/src/__tests__/`, `e2e/tests/`). No backend test files are required (`has_db_changes: false`).

### Frontend component tests (Vitest) — primary layer

| Test File | Covers |
|---|---|
| `frontend/src/__tests__/useAgentDraftComposition.test.tsx` | Draft init from fetched agent, dirty tracking, per-slot mutations, snapshot/discard, save-payload mapping (single PUT), guard integration |
| `frontend/src/__tests__/AgentManagementPanelPage.test.tsx` | Three-region layout, selection state, header CRUD wiring, dialog error display; sidebar search/selection/empty/error states |
| `frontend/src/__tests__/EquipmentSlots.test.tsx` | Seven slots: assign/unassign/inline-create contract, gating, conversational output lock |
| `frontend/src/__tests__/PendingChangesTray.test.tsx` | Inert-while-pristine, save, discard, error surfacing |
| `frontend/src/__tests__/PanelTopologyCanvas.test.tsx` | Live re-render on draft mutation, no API calls, hub node present; `buildPanelTopology` pure-builder coverage (idempotence, node/edge shape, placeholder handling) |
| `frontend/src/__tests__/ResourcePickerDialog.test.tsx` | Shared picker: label/sublabel rows, debounced client-side search, empty state, pagination, single-replace vs multi-reconcile selection, create-new pre-selection, 403 degradation via permission alert, long-name tooltip; slot picker configs (role replace semantics, skill order-preserving reconcile, typed input schema composition/resolution, typed output switch, model selection mapping) |
| `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` | **Extended**: `communication_hub` node type + localized legend + hub-helper idempotence |
| `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` | **Extended**: hub node in the agent preview topology |
| `frontend/src/__tests__/PlanPreviewModal.test.tsx` | **Extended**: hub node in the plan preview topology |
| `frontend/src/__tests__/AppShell.test.tsx` | **Extended**: `/agents/panel` sidebar nav entry |

### E2E tests (Playwright, mocked-first)

All mocked via the shared per-change mock world (`mockApiCatchAllProxyAware` + `standardSetup` + stateful route handlers, MUI-select locators, request-observer route for zero-network assertions):

| Test File | Covers |
|---|---|
| `e2e/tests/_agent_panel_world.ts` | Shared mock world: stateful agents/roles/skills/SOPs/data-types/model-configs endpoints, MUI-select locators, request observer |
| `e2e/tests/agent-management-panel.spec.ts` | Full CRUD lifecycle (create → read → edit → delete → recreate same name), parent auto-refresh (no-reload), unsaved-changes guard, single-PUT save tray, sidebar search, empty-slot placeholders; **gated real-backend (unmocked) CRUD variant** that skips cleanly when the stack is unavailable |
| `e2e/tests/agent-management-panel-slots.spec.ts` | Inline create-and-assign per slot with timestamped data (per-test mocked world = self-cleaning); identical-dialog equivalence; assign-existing + unassign round-trip; conversational output lock; identity 403 surfaced via the Dialog Error Handling Standard |
| `e2e/tests/agent-management-panel-topology.spec.ts` | Live topology updates with zero API requests (route observer), agent-switch re-render with guard, discard-no-leak, hub node + dashed edge in panel topology AND existing preview topologies (conversational + typed/plan branches) |
| `e2e/tests/agent-management-panel-permissions.spec.ts` | Slot degradation on structured 403, sidebar 403 without auth-redirect, read-only browsing with zero write actions, 403 on save kept in the tray with draft dirty |

### Regression set (must keep passing after dialog relocation)

Existing dialog/page tests unchanged: `AgentRoleDialog`, `AgentRoleListPage`, `AgentIdentityDialog`, `AgentIdentityListPage`, `AgentOAuthCallbackPage`, `SkillEditor.*` (incl. `SkillEditor.minimal`), `SopEditor.simple`, `DataTypesPage`, `ModelConfigDialog`, `ModelConfigListPage`, `AgentTypeForm`, `TopologyDiagramRenderer`, `PlanPreviewModal`, `AppShell`, and `app/AppRouter` in `frontend/src/__tests__/`.

## 7. Out of Scope for Testing

- Agent Runtime / Communication Hub runtime behavior (untouched by this change)
- Permission-resolution logic (untouched — the panel reuses existing `agent::*` manifest entries)
- Module-page standalone functionality beyond the dialog-relocation regression set
- `backend/tests/` and `mcp-demo-app/tests/` — no backend changes; unrelated to this change

## 8. Related Test Plans

- **[Agents UI Test Plan](agents-ui-test-plan.md)** — the module pages whose dialogs the panel reuses; source-side behavior baseline
- **[Agent Runtime Test Plan](agent-runtime-test-plan.md)** — agent types, roles, identities, model configs backend contracts consumed by the panel
- **[Agent Data Types & Typed Outputs Test Plan](agent-data-types-test-plan.md)** — data type registry rules (conversational output lock, delete guard) applied as-is by the panel
- **[Frontend Test Plan](frontend-test-plan.md)** — component test infrastructure conventions (React Query + MSW, `*.simple.test.tsx` workarounds)
