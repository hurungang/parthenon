# Test Plan: Unify Agent Topology Diagram

## Test Strategy

This is a **frontend-only** change (React 19 + TypeScript + MUI) that replaces the agent preview's bespoke conversation topology rendering with the canonical `PanelTopologyCanvas` used by the agent management panel, gaining zoned composition and zoom in/out (0.5×–3×). No backend, API, database, or security-boundary changes, so **backend and API test layers are not required** for this change.

Testing focuses on two axes:

1. **Unification** — the agent preview (`AgentTypeDetailsDialog`) renders the identical topology view as the management panel: same canvas component, same zoned layout (Configuration / Capabilities / Tools zones, Communication Hub bar, empty-slot placeholders), same visuals and interactions, with data correctly mapped from the read-only loaded agent type into `AgentDraftComposition`.
2. **Regression** — the management panel topology behavior is unchanged (new props on `PanelTopologyCanvas` must default to current behavior), and out-of-scope `TopologyDiagramRenderer` consumers (`AgentPlanContent`, `PlanPreviewModal`) are untouched.

Layers exercised:

- **Frontend component tests (Vitest + Testing Library)** — primary layer: preview rendering, draft mapping helper, zoom/fullscreen behavior, permission-denied handling, localization of all visible text.
- **E2E (as available)** — sanity pass over preview vs. panel consistency for a representative agent type.

Test data uses identifiable fixtures (agent types with roles, skills, SOPs, composed skills, tools, models) so node/edge content can be asserted accurately, not just for presence.

## Coverage Areas

1. **Preview unified canvas rendering** — `AgentTypeDetailsDialog` renders `PanelTopologyCanvas` (zoned graph, hub bar, placeholders) instead of the old conversation-topology renderer.
2. **Draft mapping helper** — pure mapping from loaded agent type (identity, role, input schema, output data type, model, skills, SOPs, tools) to `AgentDraftComposition`, mirroring `useAgentDraftComposition` initialization.
3. **Data accuracy in preview** — nodes, relationships, and labels (role/identity/skill/SOP/data-type names, model labels, tool names + server slugs) reflect the selected agent, including composed-SOP skill trees (requires SOP details to be loaded).
4. **Zoom parity** — zoom in/out works in the preview with the same limits/step as the panel (min 0.5, max 3, step 1.2); auto-fit at zoom = 1; text fitting and hit targets stay valid at extreme zooms.
5. **Fullscreen behavior** — toggle available, zoom resets to auto-fit on fullscreen enter/exit, Escape exits fullscreen, nothing clipped within dialog height constraints.
6. **Dirty-state suppression** — the read-only preview passes `isDirty={false}` so the panel canvas's dirty-state affordance renders neutral; the only optional prop added to `PanelTopologyCanvas` is `onNodeClick` (omitted by the panel, keeping panel behavior intact).
7. **Node interaction** — `handleNodeClick` (extended to resolve the canvas's `type_id`-prefixed node ids) opens the entity view dialogs (role/identity/SOP/skill) in the preview; hub and empty-slot placeholder clicks are safe no-ops.
8. **Localization** — all visible text in the unified view uses i18n keys (`agents.panel.*` reuse plus any new preview keys present in **all** locales); no hardcoded strings.
9. **Permission handling** — a user without permission sees the existing graceful permission error alert, not an empty diagram or crash.
10. **Management panel regression** — `PanelTopologyCanvas` and `AgentManagementPanelPage` behavior identical to before the change.
11. **Out-of-scope consumers** — `AgentPlanContent` and `PlanPreviewModal` rendering unaffected.

## Critical Scenarios (WHEN/THEN)

1. **WHEN** an authorized user opens the agent preview for a fully configured agent type (role, skills, SOPs incl. composed skills, tools, model), **THEN** the topology renders through the panel canvas with the same zoned composition, Communication Hub bar, and node/edge content as the management panel shows for the equivalent configuration.
2. **WHEN** the user clicks zoom in / zoom out in the preview, **THEN** zoom steps between 0.5× and 3× (step factor 1.2), labels remain readable and nodes remain clickable at both extremes, matching panel behavior exactly.
3. **WHEN** the user toggles fullscreen in the preview (and presses Escape), **THEN** fullscreen enters/exits, zoom resets to auto-fit on each transition, and no control or diagram content is clipped by the dialog.
4. **WHEN** the user clicks a topology node in the preview, **THEN** the matching entity view dialog opens (role/identity/SOP/skill); clicks on the Communication Hub bar and empty-slot placeholders do nothing.
5. **WHEN** the loaded agent type changes (user opens preview for a different agent), **THEN** the diagram re-derives via the pure draft mapping (`useMemo`) and shows the new agent's topology accurately — no stale nodes from the previous agent.
6. **WHEN** a user lacking permission opens the preview, **THEN** the graceful permission error alert is shown and no topology diagram (empty or broken) is rendered.
7. **WHEN** the management panel is opened after the change, **THEN** topology rendering, zoom, fullscreen, and dirty-state affordance are identical to pre-change behavior.
8. **WHEN** the preview renders any text (zone labels, captions, zoom control aria-labels), **THEN** every string resolves through the localization mechanism in all supported locales.

## Edge Cases

- **Minimal agent type** — agent with no skills/SOPs/tools: zoned graph renders with empty-slot placeholders and Communication Hub bar; no crash, no empty canvas.
- **Large/complex topology** — agent with many skills, composed SOPs, and tools: auto-fit produces a readable initial view; zoom makes large graphs inspectable; text fitting stays valid at 0.5× and 3×.
- **Composed SOP with missing SOP details** — if SOP detail steps are not loaded, the view must not degrade silently; the same query the panel uses must be reused (per tech spec risk note).
- **Agents with/without conversational configuration** — the old conversation-topology path (including the deleted `convTopologyNodes`/`convTopologyEdges` `useMemo` and direct `withCommunicationHub` usage) is fully removed; no dead code path renders a divergent diagram anywhere in the UI.
- **Repeated open/close** — zoom and fullscreen state are ephemeral per dialog open; reopening the preview resets zoom to auto-fit.
- **Unknown registry references** — agent type referencing a tool/skill/data type not resolvable in the loaded registry data: canvas renders with graceful fallback labels rather than crashing.
- **Input schema / output data type reverse lookup** — draft input schema that does not match any registry data type, and the happy-path match, both handled without errors.
- **Localization fallback** — a locale missing a new preview key must not render a raw key or hardcoded string in the default locale's place (all locales updated together).
- **Dialog layout constraints** — very small viewport / long agent names: zoom controls and fullscreen view remain accessible and not clipped.
- **Out-of-scope renderer consumers** — `AgentPlanContent` and `PlanPreviewModal` still render correctly after the shared renderer is exercised through the new path.

## Acceptance Criteria Checklist

- [ ] Agent preview displays the same topology diagram view as the agent management panel — identical layout, visuals, interactions, and information (Critical Scenarios 1–4)
- [ ] The previous, divergent preview topology diagram is no longer shown anywhere in the UI (Edge Case: removed conversation-topology path)
- [ ] Zoom in/out works in the agent preview (Scenario 2)
- [ ] Zoom behavior in the preview is identical to the management panel (limits 0.5×–3×, step 1.2, auto-fit at 1, reset on fullscreen transitions) (Scenarios 2–3, 7)
- [ ] Preview topology content (nodes, relationships, labels) remains accurate for the selected agent, including composed skills (Scenarios 1, 5)
- [ ] All UI text in the unified view is localized (no hardcoded strings) in both locations, across all locales (Scenario 8)
- [ ] Users without permission see a graceful permission error, not a broken/empty diagram (Scenario 6)
- [ ] Management panel topology behavior is unchanged — panel tests pass without behavioral edits (Scenario 7)
- [ ] No backend/API/DB changes; preview uses only its existing queries (verified by absence of API-layer changes and passing frontend suites)

## Test File References

Frontend component tests under `frontend/src/__tests__/` (per `docs/config.yaml` `source.tests`):

| File | Purpose |
|---|---|
| `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` | **Updated** — asserts the preview renders the unified `PanelTopologyCanvas`; data accuracy for the selected agent; draft re-mapping on agent switch; `handleNodeClick` entity views (identity/role) and hub/placeholder no-ops; typed-agent plan branch untouched; permission-denied alert; dirty-state affordance suppressed |
| `frontend/src/__tests__/agentTypeToDraftComposition.test.ts` | **New** — unit tests for the draft mapping helper (pure mapping, composed SOPs/bindings ordering, guardrail defaults, minimal agent type, input purity) |
| `frontend/src/__tests__/PanelTopologyCanvas.test.tsx` | **Extended** — regression guards: new optional `onNodeClick` prop forwarded when provided and absent by default (panel behavior unchanged); zoom/fullscreen/Escape logic unchanged |
| `frontend/src/__tests__/AgentManagementPanelPage.test.tsx` | Management panel regression surface |
| `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` | Zoom/pan viewBox scaling, text fitting at extreme zoom, hub edge semantics |

E2E (Playwright) under `e2e/tests/`:

| File | Purpose |
|---|---|
| `e2e/tests/agent-type-preview-topology.spec.ts` | **New** — preview shows the unified zoned panel canvas (hub bar, composed skill tree, ③ TOOLS zone, placeholders, no old "platform messaging" edge); zoom controls + fullscreen auto-fit parity in the preview; node click opens the entity view dialog; typed-agent `AgentPlanContent` branch regression |
| `e2e/tests/agent-management-panel-topology.spec.ts` | **Updated** — panel topology regression (live topology, zoom/fullscreen, zero-request draft mutations, agent switching) plus the preview-dialog tests updated to assert the unified canvas |

Execution: run the frontend Vitest suite (JSON reporter per project convention) plus the E2E topology flows (`npx playwright test tests/agent-type-preview-topology.spec.ts tests/agent-management-panel-topology.spec.ts` from `e2e/`); all layers must pass 100% before the change is considered complete.
