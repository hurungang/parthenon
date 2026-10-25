# Implementation Plan: Unify Agent Topology Diagram

## Overview

This change replaces the simple topology diagram currently rendered inside the agent preview (`AgentTypeDetailsDialog`) with the polished, zoom-capable topology canvas used by the agent management panel (`PanelTopologyCanvas`), so both locations render one identical, canonical topology view. The work is frontend-only: adapt the preview's loaded agent data into the panel's draft composition, embed the shared canvas, retire the preview-specific topology composition, and verify with updated unit tests and i18n coverage.

## Task Checklist

### Phase 1 — Preparation & Component Adaptation

- [ ] 1.1 — Audit `PanelTopologyCanvas` dependencies and props for reuse outside the panel
- [ ] 1.2 — Make `PanelTopologyCanvas` embeddable in the agent preview context (no behavioral change in the panel)

### Phase 2 — Wire the Unified Topology into the Agent Preview

- [ ] 2.1 — Build an `AgentDraftComposition` from the agent preview's loaded agent type data
- [ ] 2.2 — Replace the preview's `TopologyDiagramRenderer` usage with `PanelTopologyCanvas`
- [ ] 2.3 — Retire the preview-specific conversation topology composition
- [ ] 2.4 — Preserve node-click interactions and permission-error handling in the preview

### Phase 3 — Zoom Parity, i18n & Polish

- [ ] 3.1 — Verify zoom in/out and fullscreen behave identically in the preview and the panel
- [ ] 3.2 — Audit and extend i18n keys for the unified view

### Phase 4 — Cleanup, Tests & Verification

- [ ] 4.1 — Update existing unit tests for the preview topology change
- [ ] 4.2 — Add regression tests for zoom and unified rendering in the preview
- [ ] 4.3 — Run full frontend test suite and type check
- [ ] 4.4 — Confirm no management-panel regression

## Phase 1 — Preparation & Component Adaptation

### 1.1 — Audit `PanelTopologyCanvas` dependencies and props for reuse outside the panel

Review `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` end to end: its props (`agentName`, `draft: AgentDraftComposition`, `isDirty`), its internal name/label resolution (registry data loaded via hooks), zoom controls (`TOPOLOGY_MIN_ZOOM`/`TOPOLOGY_MAX_ZOOM`/`TOPOLOGY_ZOOM_STEP`), and fullscreen toggle. Identify any panel-only assumptions (e.g., dirty-state indicators, panel-specific labels keyed as `agents.panel.*`) that would look wrong in the preview context.

**Done when:** A written list of panel-only assumptions exists in this document's Phase notes (or the PR's description) and each item has a decision: adapt, parameterize, or leave as-is.

### 1.2 — Make `PanelTopologyCanvas` embeddable in the agent preview context (no behavioral change in the panel)

Introduce whatever minimal prop surface is needed (e.g., optional caption/variant or hiding the dirty-state affordance) so the component renders correctly when embedded in a dialog-sized container. The panel usage in `frontend/src/pages/agents/AgentManagementPanelPage.tsx` must remain pixel- and behavior-identical.

**Done when:** `PanelTopologyCanvas` accepts the new optional props with defaults that preserve current panel rendering; `frontend/src/__tests__/PanelTopologyCanvas.test.tsx` and `frontend/src/__tests__/AgentManagementPanelPage.test.tsx` still pass unchanged.

## Phase 2 — Wire the Unified Topology into the Agent Preview

### 2.1 — Build an `AgentDraftComposition` from the agent preview's loaded agent type data

The preview (`frontend/src/components/agents/AgentTypeDetailsDialog.tsx`) already loads the agent type plus its roles, skills, SOPs, identities, data types, and tools. Construct an `AgentDraftComposition` (defined in `frontend/src/types/index.ts`) from that read-only data — mirroring how `frontend/src/hooks/useAgentDraftComposition.ts` initializes a draft from a selected agent in the panel — so `buildPanelTopology` can compose the same zoned graph.

**Done when:** A pure mapping function exists (in the dialog or a small helper module) that converts the preview's loaded agent type into a valid `AgentDraftComposition`, with unit coverage for typed and conversational agent types.

### 2.2 — Replace the preview's `TopologyDiagramRenderer` usage with `PanelTopologyCanvas`

In the preview's topology section (currently rendering `TopologyDiagramRenderer` with `convTopologyNodes`/`convTopologyEdges`), render `PanelTopologyCanvas` instead, passing the agent name and the mapped draft. The rendered result must be visually and interactively identical to the management panel's topology.

**Done when:** The agent preview shows the zoned panel topology (Configuration / Capabilities / Tools zones, Communication Hub bar, placeholders for empty slots) in both inline and fullscreen modes, and no direct `TopologyDiagramRenderer` usage remains in `AgentTypeDetailsDialog.tsx` for this section.

### 2.3 — Retire the preview-specific conversation topology composition

Remove the `convTopologyNodes`/`convTopologyEdges` `useMemo` composition (and the `withCommunicationHub` usage specific to it) from `AgentTypeDetailsDialog.tsx`, since the panel canvas composes the hub and zones itself. Do not remove `TopologyDiagramRenderer`, `topologyHub.ts`, or `topologyNodeIcons.tsx` — they remain in use by `PanelTopologyCanvas`, `AgentPlanContent.tsx`, and `PlanPreviewModal.tsx`.

**Done when:** No dead preview-topology code remains in `AgentTypeDetailsDialog.tsx`; shared topology modules used elsewhere are untouched; TypeScript compile reports no unused-symbol errors in the touched files.

### 2.4 — Preserve node-click interactions and permission-error handling in the preview

Keep the existing `handleNodeClick` behavior (delegation/identity detail navigation) working with the new canvas, and keep the dialog's existing permission-denied handling so users without topology visibility see the graceful permission error instead of a broken or empty diagram.

**Done when:** Clicking topology nodes in the preview triggers the same navigation as before (covered by updated `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx`), and the permission-denied path still renders the standard error alert.

## Phase 3 — Zoom Parity, i18n & Polish

### 3.1 — Verify zoom in/out and fullscreen behave identically in the preview and the panel

Confirm the preview's embedded canvas supports zoom in/out (0.5×–3×, ~20% per click, auto-fit reset on fullscreen enter/exit) exactly as in the panel, and that zoom controls are reachable within the dialog's constrained height (adjust container height/flex layout if the controls are clipped).

**Done when:** Zoom in/out/fullscreen-reset works in the preview at small dialog sizes; Escape exits fullscreen in the preview; manual verification (or component test) confirms the same clamps and step as the panel.

### 3.2 — Audit and extend i18n keys for the unified view

All UI text in the unified view must come from `t()` per project convention. Reuse existing `agents.panel.*` topology keys where the wording fits both contexts; add new keys (in `frontend/src/i18n/locales/`) only where preview-specific wording is required. No hardcoded strings may be introduced anywhere, including the new mapping code.

**Done when:** `grep` finds no hardcoded user-facing strings in the touched files; new/changed keys exist for all supported locales in `frontend/src/i18n/locales/`; `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` passes with the updated keys.

## Phase 4 — Cleanup, Tests & Verification

### 4.1 — Update existing unit tests for the preview topology change

Update `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` (and any test asserting the old preview topology DOM, e.g. assertions on hub nodes or `agents.plan.topology` section) to assert the panel canvas is rendered in the preview instead.

**Done when:** All updated tests pass and no test references the removed preview topology composition.

### 4.2 — Add regression tests for zoom and unified rendering in the preview

Add/extend component tests asserting that (a) the preview renders the same zoned graph for the same agent data as `PanelTopologyCanvas` does in the panel, and (b) zoom controls in the preview clamp to the 0.5×–3× range and reset on fullscreen toggle.

**Done when:** New tests exist, pass, and would fail if the preview were reverted to the old diagram or lost zoom controls.

### 4.3 — Run full frontend test suite and type check

Run the frontend Vitest suite (using the JSON reporter per project convention) and the TypeScript compiler/lint for `frontend/src`.

**Done when:** Zero failing tests, zero type errors, and no new lint errors attributable to this change.

### 4.4 — Confirm no management-panel regression

Manually smoke-test the agent management panel (`frontend/src/pages/agents/AgentManagementPanelPage.tsx`): topology composition, zoom, fullscreen, editing/dirty state, and node interactions are unchanged from before this change.

**Done when:** Panel behavior matches the pre-change baseline; `AgentManagementPanelPage.test.tsx` and `PanelTopologyCanvas.test.tsx` pass without modification (beyond any new optional-prop coverage).

## Completion Checklist

- [ ] Agent preview renders the identical topology view as the agent management panel (layout, visuals, interactions, information)
- [ ] The old preview-specific topology diagram is removed from the UI and its composition code is deleted
- [ ] Zoom in/out (and fullscreen) works in the agent preview with identical behavior to the management panel
- [ ] Topology content in the preview remains accurate for the selected agent (typed and conversational types)
- [ ] Node-click interactions and permission-denied handling in the preview are preserved
- [ ] All UI text uses i18next `t()`; new keys added to all locale files
- [ ] Agent management panel behavior is unchanged (no regression)
- [ ] All unit tests (existing + new) pass; TypeScript compiles cleanly
- [ ] `docs/master/product/features/agent-management.md` and `docs/master/product/features/agent-types.md` updated per `spec-change.md` instructions (master-doc step of the change lifecycle)
