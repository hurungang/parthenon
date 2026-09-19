# Test Plan: Agent Management Panel

## Test Strategy

- **Frontend-heavy composition change**: no API, schema, or inter-service changes (`has_db_changes: false` in `.change.yaml`) — **no backend tests, migration tests, or database verification needed**; the backend remains a consumer of existing endpoints exactly as today.
- **Unit/Component tests (Vitest, `frontend/src/__tests__/`)** — highest-weight layer for this change:
  - Pure-function tests for the topology builder and the Communication Hub helper (idempotence, node/edge shape, placeholder handling).
  - Hook tests for the draft composition state: initialization from a fetched agent, dirty tracking, snapshot/discard, save-payload mapping, unsaved-changes guard integration.
  - Component tests for each new panel component: sidebar, equipment slots, shared dialog host, pending-changes tray, topology canvas, page shell.
  - Regression guard around the Phase 1 dialog extraction: all existing dialog test files must pass unchanged after the relocation, and module pages must import the shared implementations.
  - Extended-component tests: renderer `communication_hub` node type + legend, agent preview topology hub node, router route, shell nav entry.
  - i18n coverage test for the new locale keys (platform rule: no hardcoded UI text). Run with the JSON reporter per project convention.
- **Integration/E2E (Playwright, `e2e/tests/`)** — full lifecycle validation against the running stack:
  - Complete agent CRUD lifecycle through the panel (create → read → edit → delete → recreate with same name), verifying UI + persisted state.
  - Inline create-and-assign per slot type using realistic, timestamped test data with cleanup.
  - Parent-refresh assertions after every dialog close (no manual reload).
  - Live-topology behaviors can use route mocks for speed; include at least one real-backend CRUD flow (skill guidance: one unmocked variant catches wiring issues mocks miss).
- **Manual testing** — flows that cannot be automated reliably: inline identity OAuth popup sign-in (real Keycloak/EntraID), identity provider unavailable behavior, visual QA of topology layout/legend, localization spot-checks, cross-browser rendering.
- **Explicitly out of scope for testing**: Agent Runtime / Communication Hub runtime behavior (untouched), permission-resolution logic (untouched — panel reuses existing `agent::*` manifest entries), module-page standalone functionality beyond regression.

## Coverage Areas

- **Dialog extraction regression (Phase 1)** — the six relocated dialogs (`AgentRoleDialog`, `AgentIdentityDialog`, `SkillEditor`, `SopEditor`, `DataTypeFormDialog`, `ModelConfigDialog`) must behave identically after the move: same fields, validation, error handling in both their source module pages and the panel. Divergence violates the PRD hard requirement of zero duplication with identical behavior.
- **Panel CRUD flows (agent lifecycle)** — create, read, edit, delete of agents from the header card: values displayed accurately in sidebar and header, edit form pre-populated, delete confirmation, related counts update, recreation with the same name proves true deletion (not a soft-hide). Parent panel/sidebar must refresh automatically after every dialog close (parent-table-refresh rule).
- **Equipment slots (all seven)** — role, identity, skills, SOPs, input data type, output data type, model: each slot supports assign-existing, create-inline, and unassign; slot rendering reflects the draft exactly; empty slots show dashed placeholders.
- **Live topology updates without saving** — the topology is composed purely client-side from the draft: every assign/change/remove re-renders immediately with no API call fired; this is the PRD's "see exactly what I am about to persist" guarantee and cannot be validated by save-time assertions alone.
- **Agent switching re-render** — selecting a different agent refetches its configuration, resets the draft, and re-renders the topology for that agent's current saved state; unsaved changes are guarded.
- **Communication Hub node in BOTH topologies** — the panel live topology AND the existing agent preview topology (`AgentTypeDetailsDialog`, `AgentPlanContent`, `PlanPreviewModal`) must show the hub node with its dashed platform-messaging edge and localized legend chip; the helper must be idempotent (no duplicate nodes on repeated application).
- **Unsaved-changes indicator + discard** — dirty state drives the pending-changes tray (inert while pristine); Save issues exactly one agent-type update call; Discard reverts to the last snapshot; the guard fires on agent switch and route navigation.
- **Permission gating / degradation** — per-slot gating against existing `agent::*` resource types: 403 on a slot's list query disables that slot's actions with a localized explanation (not an error surface); structured 403s render via the in-dialog `PermissionDeniedAlert` per the **Dialog Error Handling Standard**; read-only users can browse compositions; sidebar entry respects nav visibility.
- **i18n completeness** — every visible panel string (slot labels, hints, permission notes, tray, topology legend, nav entry) resolves through `t()` and exists in the English locale file; no hardcoded strings anywhere in new components.
- **Conversational-agent output-type lock** — conversational agents show a locked/unavailable output-type slot (data-type rule applied as-is); non-conversational agents can set typed outputs; data types referenced by agent types cannot be deleted from any reachable path.

## Critical Scenarios

- WHEN an administrator creates an agent from the panel with name, system instruction, and equipment; THEN the agent appears in the sidebar immediately with all values correctly displayed and no page reload occurred.
- WHEN an administrator edits an existing agent; THEN the form opens pre-populated with current values, and after saving the updated values are visible immediately in sidebar, header, and topology.
- WHEN any create/edit dialog is closed; THEN the parent panel and agent list refresh automatically showing updated data without a manual page reload.
- WHEN an administrator deletes an agent with confirmation; THEN it disappears from the list immediately, related counts update, and a new agent with the same name can be created afterwards.
- WHEN invalid input is submitted in the agent form (missing required field, duplicate name); THEN a clear validation or duplicate-name error is shown and nothing is saved.
- WHEN an inline dialog's API call fails (e.g., 403); THEN the error renders inside the dialog via the standard permission alert per the Dialog Error Handling Standard — never a silent failure.
- WHEN an administrator creates a role inline from the role slot; THEN the role is persisted via its normal endpoint and becomes available/assigned in the role selector and draft immediately, without leaving the panel.
- WHEN an administrator provisions an identity inline; THEN the OAuth sign-in popup flow completes and the new identity is immediately selectable for the agent.
- WHEN new skills, SOPs, data types, or model configs are created inline; THEN each is immediately attached/settable on the agent's draft and visible in the slot and topology.
- WHEN any relocated dialog is compared with its source module dialog; THEN fields, validation behavior, and error handling are identical (create, edit, and view modes).
- WHEN the panel's live topology is displayed; THEN it shows distinct nodes for each equipped role, identity, skill, SOP, input/output type, model, plus the fixed Communication Hub node.
- WHEN equipment is assigned, changed, or removed in a slot; THEN the topology updates visually immediately — with no network request issued.
- WHEN the administrator switches to a different agent; THEN the topology re-renders for that agent's current configuration and the draft resets from fetched data.
- WHEN the administrator attempts to switch agents or navigate away with unsaved draft changes; THEN the unsaved-changes confirmation appears, and Discard reverts to the last saved snapshot while Keep Editing preserves the draft.
- WHEN the administrator saves pending changes; THEN exactly one agent-type update call is issued and the sidebar/agent caches refresh so saved state is reflected immediately.
- WHEN the agent preview topology is opened in the Agent Types view (details dialog, plan content, plan preview); THEN the Communication Hub node appears connected to the agent in both conversational and typed/plan topologies, with a clickable-node guard preventing hub interactions.
- WHEN the Communication Hub helper is applied to a topology that already contains the hub node; THEN no duplicate node or edge is added.
- WHEN a user lacking a resource-domain permission (e.g., roles) opens the panel; THEN that slot's actions are disabled/hidden with a clear localized explanation, and read access degrades gracefully instead of showing errors.
- WHEN a read-only user browses the panel; THEN compositions are viewable and all write actions are disabled with explanations.
- WHEN a conversational agent is selected; THEN the output data type slot is locked with an explanatory state, while the input slot remains configurable.
- WHEN any panel text is rendered; THEN it is produced by the localization function with keys present in the English locale (verified by the i18n coverage test).

## Edge Cases & Risks

- **Create-inline then immediately assign** — the resource is persisted server-side before the agent draft is saved; navigating away or refreshing mid-flow keeps the resource but loses the draft. Verify the resource survives, the draft loss is guarded by the unsaved-changes dialog, and no orphaned draft assignment renders.
- **Empty states** — brand-new agent with zero equipment (all seven slots dashed, topology = placeholders + hub only); empty resource lists per slot; empty sidebar (no agents, or agent list denied); search/filter with no matches.
- **Concurrent edits** — the same agent edited in the panel and in the Agent Types module (or another tab): last-write-wins on save; verify the panel refetches on selection and does not silently merge stale drafts.
- **Large collections** — sidebar client-side filter over many agents; role/skill/SOP/data-type/model selectors with long lists; binding-order handling for large skills/SOPs sets; check selector usability and render performance.
- **OAuth identity provisioning failure mid-flow** — popup blocked, user cancels consent, provider unreachable, or callback error: dialog must surface the failure via the standard error handling with no partial draft assignment.
- **Save failure mid-save** — network error or 403 on the single update call: tray remains dirty, error surfaced via the permission alert, no partial equipment write occurred.
- **Duplicate/casing names** — agent names differing only by case or surrounding whitespace are rejected consistently with the module's behavior.
- **Dialog host exclusivity** — only one dialog mounted at a time; closing via Escape/backdrop clears error state per the standard; reopening shows a clean form.
- **Topology extremes** — all slots empty vs. all slots filled: layout must remain stable and legible; hub node never overlaps or disappears; legend chip always localized.
- **Helper idempotence** — repeated application of the hub helper (e.g., panel + plan content in one view) must not duplicate the node/edge.
- **Data type delete guard** — data types referenced by agent types cannot be deleted from any path reachable through the panel context.
- **Session expiry mid-panel** — 401 during a slot list fetch or save triggers the standard auth redirect without corrupting panel state.
- **Delete with dirty draft** — deleting the currently selected agent while the draft has unsaved changes: confirm the guard/confirmation ordering and that selection resets cleanly.
- **Risk note** — the highest-risk regression surface is the Phase 1 dialog extraction (six components moved); all existing dialog and page tests must be re-run with zero behavioral assertion changes.

## Acceptance Criteria Checklist

### Agent Configuration Lifecycle

- [ ] New agent created from the panel with required fields appears in the agent list immediately with all values correctly displayed
- [ ] Agent list shows all accessible agents with configuration fields and attached equipment accurately; filtering and search work correctly
- [ ] Editing an existing agent opens the form pre-populated; changes save and are visible immediately
- [ ] Closing any create/edit dialog auto-refreshes the parent panel and agent list without a manual page reload
- [ ] Deleting an agent with confirmation removes it from the list immediately, updates related counts, and the same name can be recreated afterwards (true deletion)
- [ ] Validation errors shown for invalid input; duplicate agent names rejected with a clear message; required fields enforced; permission errors surfaced gracefully inside dialogs

### Inline Resource Creation

- [ ] Existing role assignable or new role creatable inline; new role immediately available in the selector without leaving the panel
- [ ] Existing identity assignable or new identity sign-in/provisioned inline; new identity immediately selectable
- [ ] Existing Skills/SOPs attachable or new ones creatable inline; newly created Skills/SOPs immediately associated with the agent
- [ ] Existing input/output types pickable or new Agent Data Type creatable inline; new data type immediately settable
- [ ] Existing model selectable or new model configuration addable inline; new model immediately selectable
- [ ] Every inline creation dialog behaves identically (same fields, validation, error handling) to its source-module dialog — no reduced or divergent variant

### Topology Visualization

- [ ] Panel topology shows distinct icons for each equipped role, identity, skill, SOP, input/output data type, model, and the Communication Hub
- [ ] Assigning, changing, or removing equipment updates the topology immediately — without saving
- [ ] Switching agents re-renders the topology for that agent's current configuration
- [ ] The existing agent preview topology in the Agent Types view also displays the Communication Hub node, connected to the agent

### Permissions

- [ ] Panel capabilities respect existing per-module permissions: actions for domains the user lacks are disabled/hidden with a clear explanation
- [ ] Read access degrades gracefully (no error surfaces) for users with read-only or partial access

## Test File References

Paths follow `docs/config.yaml` `source.tests` conventions (`frontend/src/__tests__/`, `e2e/tests/`). No backend test files are required for this change.

### Implemented — frontend unit/component tests (Vitest)

Implemented flat in `frontend/src/__tests__/` (NOT in the originally proposed `agents/panel/` subfolder — the project keeps panel component tests flat alongside existing `__tests__` files):

- `frontend/src/__tests__/useAgentDraftComposition.test.tsx` — draft init from fetched agent, dirty tracking, per-slot mutations, snapshot/discard, save-payload mapping (single PUT), guard integration (18 tests)
- `frontend/src/__tests__/AgentManagementPanelPage.test.tsx` — three-region layout, selection state, header CRUD wiring, dialog error display (9 tests)
- `frontend/src/__tests__/EquipmentSlots.test.tsx` — seven slots: assign/unassign/inline-create contract, gating, conversational output lock (8 tests)
- `frontend/src/__tests__/PendingChangesTray.test.tsx` — inert-while-pristine, save, discard, error surfacing (4 tests)
- `frontend/src/__tests__/PanelTopologyCanvas.test.tsx` — live re-render on draft mutation, no API calls, hub node present; includes the `buildPanelTopology` pure-builder coverage originally proposed as a separate file (6 tests, 3 of them builder-level)
- `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` — extended: `communication_hub` node type + legend + hub-helper idempotence (covers the originally proposed `withCommunicationHub.test.ts`; +7 tests — 5 for the hub node type, 2 for the helper)
- `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` — extended: hub node in the agent preview topology (+3 tests)
- `frontend/src/__tests__/PlanPreviewModal.test.tsx` — extended: hub node in the plan preview topology (+2 tests)
- `frontend/src/__tests__/AppShell.test.tsx` — extended: `/agents/panel` nav entry

Consolidated — planned as separate files but covered inside the files above (no standalone file was created):

- `buildPanelTopology.test.ts` → covered in `PanelTopologyCanvas.test.tsx`
- `withCommunicationHub.test.ts` → covered in `TopologyDiagramRenderer.test.tsx`
- `AgentListSidebar.test.tsx` → sidebar search/selection/empty/error states covered in `AgentManagementPanelPage.test.tsx`
- `SharedDialogHost.test.tsx` → the create-and-assign contract is covered by `AgentManagementPanelPage.test.tsx` (host mocked at the contract level) and — at the real-component level — by the E2E slot specs below; the relocated dialogs themselves keep their existing unchanged test files (regression set)
- `panel-i18n-coverage.test.ts` → no dedicated file; the platform i18n rule is enforced by review and covered indirectly (all panel strings render through `t()` in the component tests and E2E specs assert localized English copy)

### Implemented — E2E tests (Playwright, `e2e/tests/`)

All mocked (mock-first convention: `mockApiCatchAllProxyAware` + `standardSetup` + a per-suite world of stateful route handlers in `_agent_panel_world.ts`, with a request-observer route enabling "zero network requests" assertions):

- `e2e/tests/_agent_panel_world.ts` — shared mock world: stateful agents/roles/skills/SOPs/data-types/model-configs endpoints, MUI-select locators (`muiCombobox`/`selectMuiOption`), request observer
- `e2e/tests/agent-management-panel.spec.ts` — full agent CRUD lifecycle through the panel (create → read → edit → delete → recreate same name), parent auto-refresh assertions (no-reload marker), unsaved-changes guard (Keep Editing/Discard), single-PUT save tray, sidebar search, empty-slot placeholders; plus the gated real-backend (unmocked) CRUD flow variant that probes `http://localhost:8000` at runtime and skips cleanly when the stack or the test user's permissions are unavailable
- `e2e/tests/agent-management-panel-slots.spec.ts` — inline create-and-assign per equipment slot (role, identity, skills, SOPs, input/output data types, model) with timestamped test data (per-test mocked world = self-cleaning); identical-dialog equivalence checks (real shared dialogs, same titles/fields/validation as source modules); assign-existing + unassign round-trip; conversational output lock. The OAuth identity popup sign-in remains manual-only per plan — the identity spec asserts the inline dialog opens and surfaces a mocked provider 403 via the Dialog Error Handling Standard, then covers assign-existing
- `e2e/tests/agent-management-panel-topology.spec.ts` — live topology updates without saving (zero API requests via route observer), agent-switch re-render with guard, Communication Hub node + dashed "platform messaging" edge in the panel topology AND in the existing agent preview topology (`AgentTypeDetailsDialog` → Agent Preview tab, both the conversational branch and the typed/plan branch via `AgentPlanContent`)
- `e2e/tests/agent-management-panel-permissions.spec.ts` — dedicated panel-permissions spec (instead of extending `permissions.spec.ts`, to keep that large file untouched): slot degradation on structured 403 via `page.route` mocking, sidebar 403 graceful degradation without auth-redirect, read-only browsing with zero write actions, 403 on save surfaced in the pending-changes tray with the draft kept dirty

Note on `e2e/tests/auth-required/access-control.spec.ts`: not extended — the dedicated panel-permissions spec above covers the plan's permission scenarios with mocked 403s; the auth-required suite needs the live stack and is unaffected by this change.

### Existing tests that must keep passing after dialog relocation (regression set)

- `frontend/src/__tests__/AgentRoleDialog.test.tsx`, `frontend/src/__tests__/AgentRoleListPage.test.tsx`
- `frontend/src/__tests__/AgentIdentityDialog.test.tsx`, `frontend/src/__tests__/AgentIdentityListPage.test.tsx`, `frontend/src/__tests__/AgentOAuthCallbackPage.test.tsx`
- `frontend/src/__tests__/SkillEditor.minimal.test.tsx` (plus other `SkillEditor.*` tests), `frontend/src/__tests__/SopEditor.simple.test.tsx`
- `frontend/src/__tests__/DataTypesPage.test.tsx`, `frontend/src/__tests__/ModelConfigDialog.test.tsx`, `frontend/src/__tests__/ModelConfigListPage.test.tsx`
- `frontend/src/__tests__/AgentTypeForm.test.tsx`, `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx`, `frontend/src/__tests__/PlanPreviewModal.test.tsx`
- `frontend/src/__tests__/AppShell.test.tsx` — extended for the new `/agents/panel` sidebar nav entry; `frontend/src/__tests__/app/AppRouter.test.tsx` — unchanged regression set (the route itself is covered by the panel page/permission specs)

### Not applicable

- `backend/tests/` — no backend changes in this change (`has_db_changes: false`, no new/modified endpoints); no migration or schema verification required
- `mcp-demo-app/tests/` — unrelated to this change
