# Implementation Plan: Unify Agent Topology Diagram

## Overview

This change is a replace, not enhance: the low-fidelity conversation-topology rendering inside the agent preview (`AgentTypeDetailsDialog`) is deleted outright and replaced by mounting the management panel's polished, zoom-capable topology canvas (`PanelTopologyCanvas`) directly in its place. The only new code is a thin data-shape adapter that maps the dialog's already-loaded agent type data into the `AgentDraftComposition` shape the existing panel component consumes — no new design, no optional variants, and no work built on top of the old diagram.

## Task Checklist

### Phase 1 — Reuse Panel Canvas As-Is

- [x] 1.1 — Confirm `PanelTopologyCanvas` mounts unchanged inside the preview dialog
- [x] 1.2 — Map the dialog's loaded agent type data into `AgentDraftComposition`

### Phase 2 — Swap the Preview Topology

- [x] 2.1 — Delete the old dialog topology rendering and mount `PanelTopologyCanvas`
- [x] 2.2 — Preserve node-click interactions and permission-error handling in the preview

### Phase 3 — Verify Zoom, i18n & Fit

- [x] 3.1 — Verify zoom in/out and fullscreen work identically in the preview and the panel
- [x] 3.2 — Verify i18n coverage for the unified view

### Phase 4 — Tests & Verification

- [x] 4.1 — Update existing unit tests for the preview topology swap
- [x] 4.2 — Add regression tests for unified rendering and zoom in the preview
- [x] 4.3 — Run full frontend test suite and type check
- [x] 4.4 — Confirm no management-panel regression

## Phase 1 — Reuse Panel Canvas As-Is

### 1.1 — Confirm `PanelTopologyCanvas` mounts unchanged inside the preview dialog

Embed `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` in the preview dialog exactly as the management panel uses it in `frontend/src/pages/agents/AgentManagementPanelPage.tsx` (same props: agent name, draft composition, dirty flag). Do NOT add optional props, variants, or panel-specific behavioral switches unless mounting uncovers a genuine blocker (e.g., controls clipped by the dialog height); if such a blocker appears, make the smallest possible change and record why.

**Done when:** The component renders inside the dialog container with no modifications to its public API; if any adjustment proved unavoidable, it is documented with the reason and `frontend/src/__tests__/PanelTopologyCanvas.test.tsx` still passes unchanged.

### 1.2 — Map the dialog's loaded agent type data into `AgentDraftComposition`

The dialog already loads the agent type plus roles, skills, SOPs, identities, data types, models, MCP servers, and tools. Write a single thin, pure mapping that converts that read-only data into an `AgentDraftComposition` (defined in `frontend/src/types/index.ts`), mirroring how `frontend/src/hooks/useAgentDraftComposition.ts` initializes a draft from a selected agent. This adapter exists only because the existing component expects that shape — it is glue, not design.

**Done when:** A pure mapping function exists (small helper module or local function in the dialog) producing a valid `AgentDraftComposition`, with unit coverage for typed and conversational agent types.

## Phase 2 — Swap the Preview Topology

### 2.1 — Delete the old dialog topology rendering and mount `PanelTopologyCanvas`

Remove the preview's old topology rendering entirely: the `TopologyDiagramRenderer` usage fed by `convTopologyNodes`/`convTopologyEdges`, and the conversation-topology composition `useMemo` (including its direct `withCommunicationHub` usage) in `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` — together with the now-dead `/mcp/tools` dialog query that only the deleted composition consumed (the canvas resolves tool names itself). In the same section, mount `PanelTopologyCanvas` with the mapped draft from task 1.2. The old diagram is deleted — nothing is kept, wrapped, or built on top of it. Do not remove shared modules (`TopologyDiagramRenderer.tsx`, `topologyHub.ts`, `topologyNodeIcons.tsx`, `topologyTextFit.ts`) — they remain in use by `PanelTopologyCanvas`, `AgentPlanContent.tsx`, and `PlanPreviewModal.tsx`.

**Done when:** No trace of the old preview topology remains in `AgentTypeDetailsDialog.tsx`; the preview shows the identical zoned panel topology (Configuration / Capabilities / Tools zones, Communication Hub bar, empty-slot placeholders) in inline and fullscreen modes.

### 2.2 — Preserve node-click interactions and permission-error handling in the preview

Keep the existing `handleNodeClick` behavior (entity view navigation: role/identity/SOP/skill/agent-type dialogs) working with the mounted canvas — extended to resolve the canvas's `type_id`-prefixed node ids (e.g. `sop_x`) and to no-op on the hub and empty-slot placeholders (the zoned canvas has no delegation nodes). Keep the dialog's existing permission-denied handling so users without topology visibility see the graceful permission error instead of a broken or empty diagram.

**Done when:** Clicking topology nodes in the preview triggers the same navigation as before (covered by updated `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx`), and the permission-denied path still renders the standard error alert.

## Phase 3 — Verify Zoom, i18n & Fit

### 3.1 — Verify zoom in/out and fullscreen work identically in the preview and the panel

Because the exact same component is mounted, zoom behavior is inherited for free — verify only that it works within the dialog's constraints: zoom controls reachable (adjust container height/flex only if clipped), 0.5×–3× clamp, auto-fit reset on fullscreen enter/exit, Escape exits fullscreen.

**Done when:** Zoom in/out/fullscreen-reset works in the preview at small dialog sizes and is behaviorally identical to the panel (same component, so only layout fit needs verification).

### 3.2 — Verify i18n coverage for the unified view

All UI text in the unified view comes from the panel canvas's existing `t()`-based labels, so no new strings should be needed. Confirm no hardcoded strings were introduced by the swap or the mapping helper; add keys (in `frontend/src/i18n/locales/`) only if the swap exposed a genuinely missing label.

**Done when:** `grep` finds no hardcoded user-facing strings in the touched files; any added keys exist for all supported locales in `frontend/src/i18n/locales/`; `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` passes.

## Phase 4 — Tests & Verification

### 4.1 — Update existing unit tests for the preview topology swap

Update `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` (and any test asserting the old preview topology DOM, e.g. assertions on hub nodes or the `agents.plan.topology` section) to assert `PanelTopologyCanvas` is rendered in the preview instead.

**Done when:** All updated tests pass and no test references the deleted preview topology composition.

### 4.2 — Add regression tests for unified rendering and zoom in the preview

Add/extend component tests asserting that (a) the preview renders the same zoned graph for the same agent data as `PanelTopologyCanvas` does in the panel, and (b) zoom controls in the preview clamp to the 0.5×–3× range and reset on fullscreen toggle.

**Done when:** New tests exist, pass, and would fail if the preview were reverted to the deleted diagram or lost zoom controls.

### 4.3 — Run full frontend test suite and type check

Run the frontend Vitest suite (using the JSON reporter per project convention) and the TypeScript compiler/lint for `frontend/src`.

**Done when:** Zero failing tests, zero type errors, and no new lint errors attributable to this change.

### 4.4 — Confirm no management-panel regression

Manually smoke-test the agent management panel (`frontend/src/pages/agents/AgentManagementPanelPage.tsx`): topology composition, zoom, fullscreen, editing/dirty state, and node interactions are unchanged from before this change.

**Done when:** Panel behavior matches the pre-change baseline; `AgentManagementPanelPage.test.tsx` and `PanelTopologyCanvas.test.tsx` pass without modification.

## Completion Checklist

- [x] Agent preview renders the identical topology view as the agent management panel (same component, same layout, visuals, interactions, information) — for ALL agent types: typed agents render the unified canvas above their kept plan steps (`AgentPlanContent` with `hideTopology`), while `PlanPreviewModal` keeps its own plan topology
- [x] The old preview-specific topology diagram and its composition code are deleted from the UI and codebase
- [x] `PanelTopologyCanvas` is mounted without new optional props/variants (or any unavoidable deviation is documented) — deviation documented: optional `onNodeClick` prop added (see tech-spec) to preserve preview node-click navigation; default panel behavior unchanged
- [x] The only new logic is the thin `AgentDraftComposition` data-shape adapter
- [x] Zoom in/out (and fullscreen) works in the agent preview with identical behavior to the management panel
- [x] Node-click interactions and permission-denied handling in the preview are preserved
- [x] All UI text uses i18next `t()`; new keys added to all locale files only if genuinely missing (none needed — existing `agents.panel.*` / `agents.plan.*` keys reused)
- [x] Agent management panel behavior is unchanged (no regression)
- [x] All unit tests (existing + new) pass; TypeScript compiles cleanly
- [ ] `docs/master/product/features/agent-management.md` and `docs/master/product/features/agent-types.md` updated per `spec-change.md` instructions (master-doc step of the change lifecycle)
