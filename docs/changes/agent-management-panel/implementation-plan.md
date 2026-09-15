# Implementation Plan: Agent Management Panel

## Overview

Frontend-only composition change that adds a unified Agent Management Panel at `/agents/panel` where an administrator can fully equip an agent (role, identity, skills, SOPs, input/output data types, model) from one place. The panel reuses the existing module dialogs — extracted into shared components with zero behaviour change — drives a client-side draft composition state, and renders a live topology (including the Communication Hub node) that updates before saving. No backend, schema, or permission-model changes are required.

## Task Checklist

### Phase 1 — Extract shared module dialogs (no behaviour change)

- [x] 1.1 — Relocate `AgentRoleDialog` to shared components
- [x] 1.2 — Relocate `AgentIdentityDialog` to shared components
- [x] 1.3 — Relocate `SkillEditor` to shared components
- [x] 1.4 — Relocate `SopEditor` to shared components
- [x] 1.5 — Relocate `DataTypeFormDialog` to shared components
- [x] 1.6 — Relocate `ModelConfigDialog` to shared components
- [x] 1.7 — Phase 1 regression checkpoint

### Phase 2 — Panel scaffolding (route, agent list, draft state)

- [x] 2.1 — Add panel route and sidebar navigation entry
- [x] 2.2 — Create panel page skeleton with agent list sidebar
- [x] 2.3 — Agent header card: create / edit / delete via reused `AgentTypeForm`
- [x] 2.4 — Draft composition state hook with unsaved-changes guard

### Phase 3 — Equipment slots wiring (assign existing + inline create-and-assign)

- [x] 3.1 — Equipment slots framework (7 slots, permission-gated)
- [x] 3.2 — Shared dialog host with create-and-assign contract
- [x] 3.3 — Role slot (assign existing; inline create via role dialog)
- [x] 3.4 — Identity slot (assign existing; inline OAuth sign-in via identity dialog)
- [x] 3.5 — Skills slot (multi-assign; inline create via skill editor)
- [x] 3.6 — SOPs slot (multi-assign; inline create via SOP editor)
- [x] 3.7 — Input data type slot (assign existing; inline create via data type dialog)
- [x] 3.8 — Output data type slot (assign existing; inline create; conversational lock)
- [x] 3.9 — Model slot (assign existing; inline create via model config dialog)
- [x] 3.10 — Pending changes tray (save / discard)

### Phase 4 — Live topology canvas + Communication Hub node

- [x] 4.1 — Extend `TopologyDiagramRenderer` with the Communication Hub node type
- [x] 4.2 — Panel topology composer (draft state → nodes/edges, empty-slot placeholders)
- [x] 4.3 — Live re-render wiring (draft mutations, agent switch, discard)

### Phase 5 — Existing agent preview topology: Communication Hub node

- [x] 5.1 — Add hub node to conversation agent preview topology
- [x] 5.2 — Add hub node to plan/typed agent preview topology
- [x] 5.3 — Hub legend, i18n, and node-click guard

### Phase 6 — i18n, error handling, polish

- [x] 6.1 — Complete i18n keys for the panel (no hardcoded strings)
- [x] 6.2 — Dialog error-handling standard conformance audit
- [x] 6.3 — Read-only degradation and visual polish pass

### Phase 7 — Tests

- [x] 7.1 — Unit tests: draft composition hook
- [x] 7.2 — Component tests: panel page (list, selection, CRUD)
- [x] 7.3 — Component tests: equipment slots and inline create-and-assign
- [x] 7.4 — Component tests: live topology and Communication Hub node
- [x] 7.5 — Full regression: type-check and vitest suite

---

## Phase 1 — Extract shared module dialogs (no behaviour change)

Goal: move the six module dialogs out of their host pages into shared components under `frontend/src/components/agents/` so both the source pages and the new panel import the same implementation. Fields, validation, and error handling must remain byte-for-byte identical (PRD hard requirement: inline creation must behave identically to the source module).

### 1.1 — Relocate `AgentRoleDialog` to shared components

Move `frontend/src/pages/agents/AgentRoleDialog.tsx` to `frontend/src/components/agents/AgentRoleDialog.tsx`, adjusting only relative import depths. Update `AgentRoleListPage` and the existing dialog test to import from the new location.

- Files touched: `frontend/src/components/agents/AgentRoleDialog.tsx` (moved), `frontend/src/pages/agents/AgentRoleListPage.tsx`, `frontend/src/__tests__/AgentRoleDialog.test.tsx`
- Done when: `npm run type-check` passes; `frontend/src/__tests__/AgentRoleDialog.test.tsx` and `AgentRoleListPage` tests pass; the role create/edit flow on `/agents/roles` is unchanged (dialog opens, saves, invalidates the roles list).

### 1.2 — Relocate `AgentIdentityDialog` to shared components

Move `frontend/src/pages/agents/AgentIdentityDialog.tsx` (OAuth sign-in popup flow) to `frontend/src/components/agents/AgentIdentityDialog.tsx`. Update `AgentIdentityListPage` and its test. The OAuth callback route (`/agents/identities/oauth/callback` → `AgentOAuthCallbackPage`) is untouched.

- Files touched: `frontend/src/components/agents/AgentIdentityDialog.tsx` (moved), `frontend/src/pages/agents/AgentIdentityListPage.tsx`, `frontend/src/__tests__/AgentIdentityDialog.test.tsx`
- Done when: type-check passes; identity dialog tests pass; the sign-in-as-agent popup flow still opens, and success/errors surface in-dialog per the existing pattern.

### 1.3 — Relocate `SkillEditor` to shared components

Move `frontend/src/pages/skills/SkillEditor.tsx` to `frontend/src/components/agents/SkillEditor.tsx`. Update `SkillListPage` and all SkillEditor test files.

- Files touched: `frontend/src/components/agents/SkillEditor.tsx` (moved), `frontend/src/pages/skills/SkillListPage.tsx`, `frontend/src/__tests__/SkillEditor.test.tsx`, `frontend/src/__tests__/SkillEditor.fixes.test.tsx`, `frontend/src/__tests__/SkillEditor.minimal.test.tsx`, `frontend/src/__tests__/SkillEditor.generatedToolReference.test.ts`, `frontend/src/__tests__/SkillEditor.workflow-generation-preview.test.tsx`
- Done when: type-check passes; all SkillEditor and SkillListPage tests pass; skill create/edit/view on `/skills` is unchanged.

### 1.4 — Relocate `SopEditor` to shared components

Move `frontend/src/pages/skills/SopEditor.tsx` to `frontend/src/components/agents/SopEditor.tsx`. Update `SopListPage` and all SopEditor test files.

- Files touched: `frontend/src/components/agents/SopEditor.tsx` (moved), `frontend/src/pages/skills/SopListPage.tsx`, `frontend/src/__tests__/SopEditor.test.tsx`, `frontend/src/__tests__/SopEditor.simple.test.tsx`, `frontend/src/__tests__/SopEditor.workflow-generation-preview.test.tsx`
- Done when: type-check passes; all SopEditor and SopListPage tests pass; SOP create/edit/view on `/sops` is unchanged.

### 1.5 — Relocate `DataTypeFormDialog` to shared components

Move `frontend/src/pages/data-types/DataTypeFormDialog.tsx` to `frontend/src/components/agents/DataTypeFormDialog.tsx`. Update `DataTypesPage` and the dialog/page tests.

- Files touched: `frontend/src/components/agents/DataTypeFormDialog.tsx` (moved), `frontend/src/pages/data-types/DataTypesPage.tsx`, `frontend/src/__tests__/DataTypeFormDialog.test.tsx`, `frontend/src/__tests__/DataTypesPage.test.tsx`
- Done when: type-check passes; data type tests pass; create/edit of data types on `/admin/data-types` is unchanged, including the dynamic field editor.

### 1.6 — Relocate `ModelConfigDialog` to shared components

Move `frontend/src/pages/agents/ModelConfigDialog.tsx` to `frontend/src/components/agents/ModelConfigDialog.tsx`. Update `ModelConfigListPage` and the dialog test.

- Files touched: `frontend/src/components/agents/ModelConfigDialog.tsx` (moved), `frontend/src/pages/agents/ModelConfigListPage.tsx`, `frontend/src/__tests__/ModelConfigDialog.test.tsx`
- Done when: type-check passes; model config tests pass; model config create/edit on `/agents/model-configs` is unchanged, including the fetch-available-models flow.

### 1.7 — Phase 1 regression checkpoint

Run the full verification suite and confirm the extraction introduced no behaviour change: `npm run type-check`, `npm run test` (Vitest; on Windows use the JSON reporter pattern from AGENTS.md). Review the diff to confirm only file moves and import-path updates touched the module pages.

- Files touched: none (verification only)
- Done when: type-check is clean; the full Vitest suite passes with no new failures; `git diff` shows no logic edits inside any relocated dialog or module page.

---

## Phase 2 — Panel scaffolding (route, agent list, draft state)

Goal: a reachable, permission-degrading panel page with the three-region layout from the approved prototype (`docs/changes/agent-management-panel/prototype/index.html`): agent list sidebar, live topology region, equipment region.

### 2.1 — Add panel route and sidebar navigation entry

Register the panel route in `AppRouter` inside the protected `AppShell` branch and add a child item to the Agents group in `AppShell`'s declarative nav data with a new i18n key `nav.agentManagementPanel` in `frontend/src/i18n/locales/en.json`. Follow the existing sidebar pattern (no new permission filtering; content degrades via 403 handling like every other page).

- Files touched: `frontend/src/app/AppRouter.tsx`, `frontend/src/app/AppShell.tsx`, `frontend/src/i18n/locales/en.json`
- Done when: `/agents/panel` renders inside the app shell; the sidebar shows the new entry in the Agents group; deep-linking to `/agents/panel` force-expands the Agents group; the label renders through i18next `t()`.

### 2.2 — Create panel page skeleton with agent list sidebar

Create `frontend/src/pages/agents/AgentManagementPanelPage.tsx` implementing the three-region layout. The agent list sidebar loads agent types through `useAgentTypes`, supports client-side search/filter, and tracks the selected agent id. Loading, empty, and error states render per platform pattern (`CircularProgress`, empty text via `t()`, `PermissionDeniedAlert` on list error). Topology and equipment regions render as labelled placeholders until Phases 3–4 fill them. All visible text via i18next `t()`.

- Files touched: `frontend/src/pages/agents/AgentManagementPanelPage.tsx` (new), `frontend/src/i18n/locales/en.json`
- Done when: the panel lists all accessible agents with correct data; search filters the list; selecting an agent highlights it and stores the selection; a 403 on the agent list shows the permission alert instead of a crash.

### 2.3 — Agent header card: create / edit / delete via reused `AgentTypeForm`

Add the header card above the equipment region: agent name/description plus Create, Edit, and Delete actions. Create/edit open a dialog hosting the existing controlled `AgentTypeForm` (values/onChange contract, `defaultAgentTypeFormValues` for create) with save semantics mirroring `AgentManagementPage` — `POST /agents/types` for create, `PUT /agents/types/{id}` for edit — including slug validation and the bindings-required rule. Delete uses `useDeleteAgentType` behind `ConfirmDialog`. After any successful operation, invalidate the agent types query so the sidebar refreshes immediately without a page reload. Dialog errors follow the standard (`dialogError` state + `PermissionDeniedAlert` first in `DialogContent`).

- Files touched: `frontend/src/pages/agents/AgentManagementPanelPage.tsx`, `frontend/src/pages/agents/AgentTypeForm.tsx` (reused unchanged), `frontend/src/hooks/useAgentTypes.ts` (reused), `frontend/src/components/common/ConfirmDialog.tsx` (reused), `frontend/src/components/permissions/PermissionDeniedAlert.tsx` (reused), `frontend/src/i18n/locales/en.json`
- Done when: creating an agent from the panel makes it appear in the sidebar immediately; editing pre-populates the form and saves successfully; deleting prompts confirmation, removes the agent, and a new agent with the same name can be created afterwards; duplicate/invalid names show clear validation errors; a 403 on save renders inside the dialog.

### 2.4 — Draft composition state hook with unsaved-changes guard

Create `frontend/src/hooks/useAgentDraftComposition.ts` — the core new concept. It holds a strongly typed in-memory draft of the selected agent's equipment (identity, role, skills with binding order, SOPs with binding order, input type/schema, output data type, model) initialised from the fetched `AgentType`, plus: mark-dirty on every mutation, a snapshot for discard, a save action that maps the draft onto the existing agent-type update payload (`PUT /agents/types/{id}`), and integration with `useUnsavedChangesDialog` so switching agents or leaving with unsaved changes prompts confirmation. Define the draft composition and equipment-slot interfaces in `frontend/src/types/index.ts` (TypeScript interfaces; no inferred `any`).

- Files touched: `frontend/src/hooks/useAgentDraftComposition.ts` (new), `frontend/src/types/index.ts`, `frontend/src/hooks/useUnsavedChangesDialog.tsx` (reused), `frontend/src/hooks/useAgentTypes.ts` (reused)
- Done when: selecting an agent populates the draft; every equipment mutation marks the draft dirty without any API call; discard reverts to the last saved snapshot; save issues exactly one `PUT /agents/types/{id}` and clears the dirty flag; switching agents with unsaved changes shows the discard/keep-editing dialog.

---

## Phase 3 — Equipment slots wiring (assign existing + inline create-and-assign)

Goal: seven equipment slots, each able to assign existing resources and create-and-assign new ones inline by mounting the extracted shared dialogs — identical behaviour to the source modules. Every slot mutation touches draft state only until Save.

### 3.1 — Equipment slots framework (7 slots, permission-gated)

Create `frontend/src/components/agents/panel/EquipmentSlots.tsx` plus a slot definition type. Render seven slots — role, identity, skills, SOPs, input data type, output data type, model — each showing current draft value(s) as chips/list items with remove actions, and Assign-existing / Create-new actions. Each slot declares its resource type for gating and explanation text: `agent::management` (agent CRUD), `agent::roles`, `agent::identities`, `agent::skills`, `agent::sops`, `agent::data_types`, `agent::model_configs` (existing manifest entries in `frontend/src/constants/resourceTypes.ts` — no new resource types). When the slot's backing list query fails with 403, disable the slot actions and show an explanatory note via `t()` (graceful read-only degradation; the server remains authoritative). Empty slots render as dashed placeholders.

- Files touched: `frontend/src/components/agents/panel/EquipmentSlots.tsx` (new), `frontend/src/types/index.ts`, `frontend/src/constants/resourceTypes.ts` (reused, unchanged), `frontend/src/i18n/locales/en.json`
- Done when: all seven slots render for the selected agent from draft state; assign/unassign actions mutate only the draft; a user lacking a module permission sees that slot's actions disabled with a clear explanation instead of an error.

### 3.2 — Shared dialog host with create-and-assign contract

Create `frontend/src/components/agents/panel/SharedDialogHost.tsx` — the single mount point for the extracted dialogs inside the panel. Define a create-and-assign contract: the dialog performs its normal create through its existing endpoint and mutations; on success the host receives the created resource (id + display label) and hands it to the slot callback, which assigns it into the draft. The host guarantees the Dialog Error Handling Standard holds for every mounted dialog (errors cleared on open/close; `PermissionDeniedAlert` rendered first in `DialogContent` — the extracted dialogs already implement this).

- Files touched: `frontend/src/components/agents/panel/SharedDialogHost.tsx` (new), `frontend/src/i18n/locales/en.json`
- Done when: each extracted dialog opens from the panel with identical props usage as its source page; a successful inline create flows the new id into draft state; a 403 or API failure inside any dialog is displayed in-dialog, never silently swallowed.

### 3.3 — Role slot (assign existing; inline create via role dialog)

Wire the role slot: assign-existing lists roles via the same roles list query used by `AgentTypeForm`/`AgentManagementPage`; create-new mounts the extracted `AgentRoleDialog` in create mode through the shared host and assigns the created role into the draft on success.

- Files touched: `frontend/src/components/agents/panel/EquipmentSlots.tsx`, `frontend/src/components/agents/panel/SharedDialogHost.tsx`, `frontend/src/components/agents/AgentRoleDialog.tsx` (reused)
- Done when: assigning an existing role updates the draft and (post-Phase 4) the live topology without saving; creating a role inline saves it via the existing roles endpoint, makes it selectable immediately, and assigns it; permission errors surface in-dialog.

### 3.4 — Identity slot (assign existing; inline OAuth sign-in via identity dialog)

Wire the identity slot: assign-existing lists identities via the identities list query; create-new mounts the extracted `AgentIdentityDialog`, reusing the existing OAuth popup flow (`GET /agents/identities/oauth/authorize` + `/agents/identities/oauth/callback` route). On OAuth success the identities list is refreshed and the new identity is assigned into the draft. Provider unavailability surfaces through the dialog's existing error handling.

- Files touched: `frontend/src/components/agents/panel/EquipmentSlots.tsx`, `frontend/src/components/agents/panel/SharedDialogHost.tsx`, `frontend/src/components/agents/AgentIdentityDialog.tsx` (reused)
- Done when: an existing identity can be assigned inline; the sign-in popup flow completes and the new identity is immediately selectable and assigned; if the OIDC provider is unreachable the error is displayed inside the dialog.

### 3.5 — Skills slot (multi-assign; inline create via skill editor)

Wire the skills slot: multi-assign from the skills list fetched exactly as `SkillListPage` does (inline react-query against the existing skills list endpoint); inline create mounts the extracted `SkillEditor` in create mode and assigns the created skill into the draft bindings. Support editing skill binding order in the draft (mirrors `skill_bindings` ordering on the agent type).

- Files touched: `frontend/src/components/agents/panel/EquipmentSlots.tsx`, `frontend/src/components/agents/panel/SharedDialogHost.tsx`, `frontend/src/components/agents/SkillEditor.tsx` (reused)
- Done when: multiple skills can be attached/detached in the draft; a newly created skill is immediately attached; binding order is adjustable and survives save; permission errors surface per the standard.

### 3.6 — SOPs slot (multi-assign; inline create via SOP editor)

Wire the SOPs slot: multi-assign from the SOPs list fetched exactly as `SopListPage` does; inline create mounts the extracted `SopEditor` (create mode) and assigns the created SOP into the draft bindings. Support SOP binding order in the draft (mirrors `sop_bindings` ordering).

- Files touched: `frontend/src/components/agents/panel/EquipmentSlots.tsx`, `frontend/src/components/agents/panel/SharedDialogHost.tsx`, `frontend/src/components/agents/SopEditor.tsx` (reused)
- Done when: multiple SOPs can be attached/detached in the draft; a newly created SOP is immediately attached; binding order is adjustable and survives save; permission errors surface per the standard.

### 3.7 — Input data type slot (assign existing; inline create via data type dialog)

Wire the input data type slot: expose the existing input-type selection (none / typed / conversation) and, for typed input, let the administrator compose the input schema from an existing Agent Data Type in the registry (via `useDataTypes`) or create a new data type inline through the extracted `DataTypeFormDialog`, assigning it into the draft. Validation and field-type rules are the dialog's own — unchanged.

- Files touched: `frontend/src/components/agents/panel/EquipmentSlots.tsx`, `frontend/src/components/agents/panel/SharedDialogHost.tsx`, `frontend/src/components/agents/DataTypeFormDialog.tsx` (reused), `frontend/src/hooks/useDataTypes.ts` (reused)
- Done when: an existing data type can be applied to the typed input in the draft; a newly created data type is immediately applicable; the slot reflects the draft and persists on Save.

### 3.8 — Output data type slot (assign existing; inline create; conversational lock)

Wire the output data type slot: pick the output data type (`output_data_type_id`) from the registry via `useDataTypes`, or create one inline through the extracted `DataTypeFormDialog`. Enforce the existing data-type rule in the UI: conversational agents (`input_type === 'conversation'`) show the slot locked with an explanatory note via `t()` — matching the source modules' behaviour.

- Files touched: `frontend/src/components/agents/panel/EquipmentSlots.tsx`, `frontend/src/components/agents/panel/SharedDialogHost.tsx`, `frontend/src/components/agents/DataTypeFormDialog.tsx` (reused), `frontend/src/hooks/useDataTypes.ts` (reused), `frontend/src/i18n/locales/en.json`
- Done when: an existing output data type can be assigned in the draft; a newly created one is immediately assignable; conversational agents show the locked slot with the explanation; save persists the selection.

### 3.9 — Model slot (assign existing; inline create via model config dialog)

Wire the model slot: pick a model from `useAvailableModels` (the flattened enabled-models union across model configs, matching the `model_id` semantics the agent type stores), or add a new model configuration inline through the extracted `ModelConfigDialog`; after creation, invalidate the model-config queries so the new model is immediately selectable and assign it into the draft.

- Files touched: `frontend/src/components/agents/panel/EquipmentSlots.tsx`, `frontend/src/components/agents/panel/SharedDialogHost.tsx`, `frontend/src/components/agents/ModelConfigDialog.tsx` (reused), `frontend/src/hooks/useAvailableModels.ts` (reused)
- Done when: an existing model can be assigned in the draft; a newly created model config with enabled models appears in the selector immediately and is assignable; save persists `model_id`; permission errors surface in-dialog.

### 3.10 — Pending changes tray (save / discard)

Create `frontend/src/components/agents/panel/PendingChangesTray.tsx`: a summary bar of pending draft changes with Save and Discard. Save delegates to the draft hook's save action (single `PUT /agents/types/{id}`) then invalidates the agent-type queries so the sidebar and saved data refresh; Discard reverts to the snapshot and re-renders. The tray is disabled/hidden while the draft is pristine; save errors render via `PermissionDeniedAlert`; the unsaved-changes dialog guards navigation while dirty.

- Files touched: `frontend/src/components/agents/panel/PendingChangesTray.tsx` (new), `frontend/src/pages/agents/AgentManagementPanelPage.tsx`, `frontend/src/hooks/useAgentDraftComposition.ts`, `frontend/src/i18n/locales/en.json`
- Done when: saving persists all equipment changes and the sidebar/details reflect them immediately without reload; discard restores the last saved state; the tray is inert when there are no changes; a 403 on save shows in the tray area.

---

## Phase 4 — Live topology canvas + Communication Hub node

Goal: the topology region re-renders from draft state on every change — before saving — including a fixed Communication Hub platform node. No runtime calls to the Communication Hub service.

### 4.1 — Extend `TopologyDiagramRenderer` with the Communication Hub node type

Extend the shared renderer with a `communication_hub` node type: a colour entry in its colour map, a column in the layered layout order, and a legend entry localized via the existing legend key pattern (`agents.plan.nodeTypes.communication_hub` in `frontend/src/i18n/locales/en.json`). Fully backwards compatible — graphs without hub nodes render exactly as before.

- Files touched: `frontend/src/components/agents/TopologyDiagramRenderer.tsx`, `frontend/src/i18n/locales/en.json`
- Done when: the renderer draws a hub node with its own colour/column and a localized legend chip; all existing renderer and consumer tests still pass unchanged.

### 4.2 — Panel topology composer (draft state → nodes/edges, empty-slot placeholders)

Create `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` (new) containing the composition builder that maps the draft composition to `TopologyNode[]` / `TopologyEdge[]`: the agent node; identity, role, skill, SOP, input/output data type, and model nodes for equipped items; dashed placeholder nodes for empty slots; and the Communication Hub as a fixed platform node connected to the agent with a dashed platform messaging edge. Node labels resolve through i18next `t()`.

- Files touched: `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` (new), `frontend/src/types/index.ts` (reused types), `frontend/src/i18n/locales/en.json`
- Done when: a fully equipped draft renders all node kinds plus the hub with distinct visuals; an empty/new agent renders the agent node, dashed placeholders, and the hub; output renders correctly through `TopologyDiagramRenderer`.

### 4.3 — Live re-render wiring (draft mutations, agent switch, discard)

Wire the panel: every draft mutation (assign/unassign/inline create-and-assign) re-renders the topology immediately with no API call; selecting a different agent refetches its data, resets the draft, and re-renders that agent's saved topology; Discard re-renders the saved snapshot.

- Files touched: `frontend/src/pages/agents/AgentManagementPanelPage.tsx`, `frontend/src/hooks/useAgentDraftComposition.ts`, `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx`
- Done when: PRD topology acceptance criteria are demonstrable end-to-end — updates appear pre-save, agent switching re-renders the target agent's configuration, discard restores the saved view.

---

## Phase 5 — Existing agent preview topology: Communication Hub node

Goal: the existing Agent Types preview topology also shows the Communication Hub node connected to the agent, for both conversational and typed/plan topologies — client-side only.

### 5.1 — Add hub node to conversation agent preview topology

- [x] Complete — hub node + dashed agent↔hub edge verified in the conversation preview topology; AgentTypeDetailsDialog tests extended and passing.

Extend the client-built conversation topology in `AgentTypeDetailsDialog` (the conversation topology memo) to append the Communication Hub node and the dashed agent↔hub edge.

- Files touched: `frontend/src/components/agents/AgentTypeDetailsDialog.tsx`
- Done when: a conversation agent's preview topology in `/agents` shows the hub connected to the agent; existing `AgentTypeDetailsDialog` tests are updated and pass.

### 5.2 — Add hub node to plan/typed agent preview topology

- [x] Complete — `AgentPlanContent` and `PlanPreviewModal` both append the hub via the idempotent `withCommunicationHub` helper at render time (no backend/plan-schema change); idempotency covered by tests. Note: `PlanPreviewModal` renders its own plan layout (it is not an `AgentPlanContent` consumer), so it required the same helper directly.

For plan-based (typed) topologies whose nodes/edges come from the server-generated plan, append the hub node and dashed edge client-side at render time — via a small shared helper (new) used by `AgentPlanContent` and applied directly by `PlanPreviewModal`, which renders its own plan layout — so no backend/plan-schema change is needed. The helper must be idempotent (never duplicates the hub).

- Files touched: `frontend/src/components/agents/AgentPlanContent.tsx`, `frontend/src/components/agents/topologyHub.ts` (new helper), `frontend/src/components/agents/PlanPreviewModal.tsx` (extended directly — it is not an `AgentPlanContent` consumer)
- Done when: a typed agent's preview topology shows the hub; regenerating a plan does not duplicate the node; no API payload or backend file changes.

### 5.3 — Hub legend, i18n, and node-click guard

- [x] Complete — localized legend chip renders via `agents.plan.nodeTypes.communication_hub` (key present in `en.json`); hub click verified as a safe no-op in `AgentTypeDetailsDialog` tests.

Ensure the hub node renders a localized legend chip, and that clicking the hub node in preview topologies is a safe no-op (the node-click handler must not misparse the hub id as an entity reference).

- Files touched: `frontend/src/components/agents/AgentTypeDetailsDialog.tsx`, `frontend/src/i18n/locales/en.json`
- Done when: the hub appears in the topology legend with localized text; clicking the hub does not open any entity view or throw.

---

## Phase 6 — i18n, error handling, polish

### 6.1 — Complete i18n keys for the panel (no hardcoded strings)

- [x] Complete — scripted audit of all new panel files: every static and dynamic `t()` key resolves in `en.json`; no hardcoded JSX text literals found.

Add all panel keys to `frontend/src/i18n/locales/en.json`: `nav.agentManagementPanel`, the `agents.panel.*` subtree (title, region headings, slot labels/hints, assign/create/remove actions, empty-slot and locked-slot notes, permission notes, tray labels, topology legend), and `agents.plan.nodeTypes.communication_hub`. Audit every new file so all visible text flows through i18next `t()`.

- Files touched: `frontend/src/i18n/locales/en.json`, all new panel components (audit only)
- Done when: a search for hardcoded user-facing strings in the new files finds none; every key referenced by the panel resolves in `en.json`.

### 6.2 — Dialog error-handling standard conformance audit

- [x] Complete — all six relocated dialogs, the panel's agent create/edit dialog, and the tray error surface verified against the standard (dialogError state, try/catch, cleared on open/close, `PermissionDeniedAlert` first in DialogContent). Gaps fixed: `SopEditor` (error now cleared on all three close paths) and `SkillEditor` (title ✕ and Cancel buttons now clear the error).

Audit every dialog the panel can mount (six extracted dialogs, the agent create/edit dialog, pending-changes error surface) against the Dialog Error Handling Standard in `docs/config.yaml`: `dialogError` state, try/catch around async operations, error cleared on open/close, `PermissionDeniedAlert` rendered first in `DialogContent`. Fix any gaps using `useDialogErrorHandler`.

- Files touched: `frontend/src/components/agents/panel/SharedDialogHost.tsx`, `frontend/src/pages/agents/AgentManagementPanelPage.tsx`, `frontend/src/hooks/useDialogErrorHandler.ts` (reused; fixes only if a gap is found)
- Done when: a checklist walkthrough of each dialog confirms a simulated 403 and a generic API failure both render inside the dialog with the permission structure and a Request-Access path where applicable; nothing fails silently.

### 6.3 — Read-only degradation and visual polish pass

- [x] Complete — 403-degradation covered by automated tests (denied slot list → explanatory note + disabled actions; list error → `PermissionDeniedAlert`; panel never surfaces raw errors). Layout compared against the prototype (sidebar search/list + three-region grid, slot head/body/actions/empty/locked states) — no blocking deviations. Polish fixes: input slot's assign picker now uses its own slot label; `PanelTopologyCanvas` reuses `useDataTypes`/`useAvailableModels` instead of duplicated inline queries.

Verify per-slot permission degradation end-to-end with a limited-permission user: disallowed slot actions disabled with explanations, list reads degrade to the permission alert, the panel never shows raw errors. Compare the panel against the approved prototype (`docs/changes/agent-management-panel/prototype/index.html`) for layout, spacing, and interaction states; align MUI usage with the app's established look and feel.

- Files touched: `frontend/src/pages/agents/AgentManagementPanelPage.tsx`, `frontend/src/components/agents/panel/*.tsx` (polish only), `frontend/src/i18n/locales/en.json`
- Done when: manual walkthrough with a read-scoped user shows disabled+explained actions and graceful read degradation; visual review against the prototype finds no deviations worth blocking.

---

## Phase 7 — Tests

### 7.1 — Unit tests: draft composition hook

- [x] Complete — all hook tests pass, including the conversational output-type lock rule.

Cover `useAgentDraftComposition`: initialization from an `AgentType`, dirty tracking on each equipment mutation, discard restoring the snapshot, save mapping to the correct update payload (single `PUT`), and the unsaved-changes guard interaction.

- Files touched: `frontend/src/__tests__/useAgentDraftComposition.test.tsx` (new)
- Done when: all new hook tests pass and cover the scenarios above, including the conversational output-type lock rule.

### 7.2 — Component tests: panel page (list, selection, CRUD)

- [x] Complete — 9 page tests pass: list render, search/filter, selection + regions, 403 list degradation, create (POST + bindings-required rule), slug validation, edit (PUT), in-dialog API failure, delete with confirmation and selection clear.

Cover `AgentManagementPanelPage`: agent list render, search/filter, selection, create/edit/delete flows with post-operation refresh, validation errors, and route/nav entry presence.

- Files touched: `frontend/src/__tests__/AgentManagementPanelPage.test.tsx` (new)
- Done when: all new page tests pass; a created agent appears in the list immediately; deleted agents can be recreated with the same name (true-deletion assertion).

### 7.3 — Component tests: equipment slots and inline create-and-assign

- [x] Complete — 12 slot/tray tests pass: all seven slots render, empty placeholders, role/output/input assign-existing (draft-only, no writes), per-slot create-new dialog request mapping, conversational output lock, 403 slot degradation with explanation, and tray pristine/dirty/saving/error behaviour.

Cover each slot: assign-existing updates the draft; inline create-and-assign flows the created resource id into the draft; conversational output-type slot is locked; 403 on a slot's list query disables actions with the explanation; save/discard tray behaviour.

- Files touched: `frontend/src/__tests__/EquipmentSlots.test.tsx` (new), `frontend/src/__tests__/PendingChangesTray.test.tsx` (new)
- Done when: all slot and tray tests pass for all seven slots, with permission-degradation cases included.

### 7.4 — Component tests: live topology and Communication Hub node

- [x] Complete — `PanelTopologyCanvas` tests (full/empty draft graphs, hub presence, live re-render without new API calls), `TopologyDiagramRenderer` extended (hub colour/column/legend/dashed edge + backwards compat + `withCommunicationHub` idempotency), `AgentTypeDetailsDialog` extended (hub in conversation preview topology, no duplication on recompose, hub click safe no-op), `PlanPreviewModal` extended (hub in plan topology, idempotent on re-render).

Cover: topology re-render on draft change without API calls; agent switch re-render; discard re-render; hub node presence and dashed edge in the panel canvas; hub node added to conversation and plan preview topologies (idempotent helper); renderer support for the hub type.

- Files touched: `frontend/src/__tests__/PanelTopologyCanvas.test.tsx` (new), `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` (extended), `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` (extended)
- Done when: all new/extended topology tests pass, asserting the hub node in panel and preview topologies and pre-save live updates.

### 7.5 — Full regression: type-check and vitest suite

- [x] Complete — `npm run type-check` clean (0 errors, including pre-existing unrelated test-file errors fixed); full Vitest suite 1396 passed / 1414 total, 0 failures (18 pre-existing pending), 0 failed suites. Relocated-dialog module page suites all green.

Run `npm run type-check` and the full `npm run test` suite (Vitest; on Windows use the JSON reporter pattern from AGENTS.md). Confirm no regressions in the module pages whose dialogs were relocated in Phase 1.

- Files touched: none (verification only)
- Done when: type-check is clean; the entire Vitest suite passes including all pre-existing module page, dialog, and topology tests; no skipped or newly failing tests.

---

## Completion Checklist

- [x] All Phase 1–7 tasks checked off above
- [x] `npm run type-check` passes with zero errors
- [x] Full Vitest suite passes with zero new failures
- [x] All six module dialogs live in shared components; module pages import the same shared implementations (zero duplication)
- [x] Panel reachable at `/agents/panel` with sidebar entry in the Agents group
- [x] Agent create/edit/delete works from the panel with immediate list refresh
- [x] All seven equipment slots support assign-existing and inline create-and-assign with identical dialog behaviour to the source modules
- [x] Draft composition state: every equipment change is unsaved until Save; discard and unsaved-changes guard work
- [x] Live topology updates pre-save; agent switching re-renders; Communication Hub node present in panel topology
- [x] Existing agent preview topology (conversation and plan/typed) shows the Communication Hub node
- [x] Permission gating uses existing resource types only (`agent::management`, `agent::roles`, `agent::identities`, `agent::skills`, `agent::sops`, `agent::data_types`, `agent::model_configs`); no backend or manifest changes
- [x] All dialogs follow the Dialog Error Handling Standard (`useDialogErrorHandler` / `PermissionDeniedAlert`)
- [x] All UI text localized via i18next `t()`; no hardcoded strings in new code
- [x] No backend, database, or migration changes (`has_db_changes: false` confirmed in `.change.yaml`)
- [x] Code Reference Map in `tech-spec.md` updated to reflect final file locations
