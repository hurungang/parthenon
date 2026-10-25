# Tech Spec: Unify Agent Topology Diagram

## Scope

Frontend-only change in `frontend/src`. The agent preview (`AgentTypeDetailsDialog`) stops rendering its own `TopologyDiagramRenderer`-based conversation topology and instead embeds the management panel's `PanelTopologyCanvas`, gaining the zoned composition and zoom in/out (0.5×–3×) behavior. No backend, API, database, or security-boundary changes. This does not affect the top-priority rules in `docs/config.yaml` (no service, data-plane, or credential impact).

## Component Breakdown

### Reused (canonical) components — unchanged or minimally extended

| Component | Role in this change |
|---|---|
| `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` | The canonical topology view. Composes the zoned graph via `buildPanelTopology` (Configuration / Capabilities / Tools zones, Communication Hub bar, empty-slot placeholders), renders it through `TopologyDiagramRenderer`, and owns the fullscreen toggle and zoom controls (`TOPOLOGY_MIN_ZOOM = 0.5`, `TOPOLOGY_MAX_ZOOM = 3`, `TOPOLOGY_ZOOM_STEP = 1.2`, `zoom = 1` = auto-fit; zoom resets on fullscreen enter/exit; Escape exits fullscreen). Gains optional props (e.g., variant/caption, suppress dirty-state affordance) with defaults that keep panel rendering identical. |
| `frontend/src/components/agents/TopologyDiagramRenderer.tsx` | Low-level SVG renderer with viewBox-based zoom/pan transform (view width = world width / zoom, so text fitting and hit targets stay valid at any zoom). Used only via `PanelTopologyCanvas` in this change; also still used by `AgentPlanContent.tsx` and `PlanPreviewModal.tsx` (execution-plan views, out of scope). |
| `frontend/src/components/agents/topologyHub.ts` | `withCommunicationHub` hub helper — used internally by the panel composition. Unchanged. |
| `frontend/src/components/agents/topologyNodeIcons.tsx`, `frontend/src/components/agents/topologyTextFit.ts` | Node icons and viewBox-unit text fitting. Unchanged. |
| `frontend/src/components/agents/AgentDetailBubble.tsx` | Detail bubble shown on node interaction. Behavior preserved in the preview via the canvas. |

### Modified components

| Component | Change |
|---|---|
| `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` | The agent preview. Replaces its topology section: the `TopologyDiagramRenderer` fed by locally composed `convTopologyNodes`/`convTopologyEdges` (built in a `useMemo` for conversational agents) is replaced by `PanelTopologyCanvas`, fed by a new mapping from the dialog's loaded agent type to `AgentDraftComposition`. The conversation-topology composition `useMemo` and its direct `withCommunicationHub` usage are deleted. `handleNodeClick` behavior and the existing permission-denied error alert are preserved. |

### New code

| Unit | Location | Purpose |
|---|---|---|
| Draft mapping helper | Small pure module co-located with the dialog (e.g., `frontend/src/components/agents/agentTypeToDraftComposition.ts`) or a local function in the dialog | Converts the preview's read-only loaded agent type (identity, role, input schema, output data type, model, skills, SOPs, tools) into an `AgentDraftComposition`, mirroring the initialization logic in `frontend/src/hooks/useAgentDraftComposition.ts`. Purely client-side; no new data fetching (the dialog already loads the needed registry data). |

## API Changes

None. No backend endpoints are added, modified, or removed. The preview continues to use the same queries it already issues for the agent type, roles, skills, SOPs, identities, data types, models, MCP servers, and tools; `PanelTopologyCanvas` resolves names/labels from that same registry data internally (including SOP detail steps for composed-skill trees). No frontend API client modules change.

## State Management

- **Preview (React local state)**: `AgentTypeDetailsDialog` already holds the loaded agent type and related registry data in local state/hooks. The new draft mapping is a pure derived value (`useMemo`) over that data — read-only, no editing, `isDirty` is effectively `false`, so the panel canvas's dirty-state affordance is suppressed via the new optional props.
- **Panel canvas internal state (reused as-is)**: `PanelTopologyCanvas` owns `fullscreen` and `zoom` (`useState`), resetting zoom to 1 (auto-fit) on fullscreen enter/exit; `TopologyDiagramRenderer` owns pan center and view transform for the fullscreen viewBox scaling. No global state (Redux/Context) is introduced; zoom state is intentionally local and resets on unmount.
- **No persistence**: zoom/fullscreen state is ephemeral per open of the preview dialog or panel, matching current panel behavior.

## Data Access Patterns

- **No new data access.** The dialog's existing queries provide: agent type (identity/role/model/input/output bindings), roles, skills (with `tool_ids`), SOPs + SOP details (composed-skill steps, order-preserved), agent identities, agent data types (including reverse lookup of the registry data type matching the draft input schema), model configurations, MCP servers (slug grouping) and MCP tools (display names). `PanelTopologyCanvas` consumes these to build `PanelTopologyNames` (role/identity/skill/SOP/data-type names, model labels, tool names + server slugs/colors, `sopComposedSkillIds`).
- **Composition is purely client-side**: `buildPanelTopology` transforms the draft + name tables into `PanelTopologyGraph` (`TopologyNode[]`, `TopologyEdge[]`, zone bands). No topology data comes from the backend for this view.
- **Permission behavior**: unchanged. The dialog's existing permission checks guard the data queries; a denied user still sees the graceful permission error, not an empty diagram.

## Code Reference Map

| Area | File | Action |
|---|---|---|
| Agent preview dialog | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` | Modify — swap topology section to `PanelTopologyCanvas`; delete conversation-topology composition; keep `handleNodeClick` + permission error |
| Canonical topology canvas | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` | Modify minimally — optional embeddability props; zoom/fullscreen logic unchanged |
| Panel topology composition | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` (`buildPanelTopology`, `PanelTopologyGraph`, `PanelTopologyNames`, `PanelTopologyLabels`) | Reuse unchanged |
| SVG renderer (zoom/pan transform) | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` | Reuse unchanged |
| Hub helper | `frontend/src/components/agents/topologyHub.ts` | Reuse unchanged (indirect usage only) |
| Node icons / text fit | `frontend/src/components/agents/topologyNodeIcons.tsx`, `frontend/src/components/agents/topologyTextFit.ts` | Reuse unchanged |
| Node detail bubble | `frontend/src/components/agents/AgentDetailBubble.tsx` | Reuse unchanged |
| Draft composition type | `frontend/src/types/index.ts` (`AgentDraftComposition`, `TopologyNode`, `TopologyEdge`, `TopologyZone`) | Reuse unchanged (type-only) |
| Draft initialization reference | `frontend/src/hooks/useAgentDraftComposition.ts` | Read-only reference for mapping agent type → draft |
| Draft mapping (new) | `frontend/src/components/agents/agentTypeToDraftComposition.ts` (or local to dialog) | Create |
| Management panel page (regression surface) | `frontend/src/pages/agents/AgentManagementPanelPage.tsx` | No code change expected; verify identical behavior |
| Out-of-scope renderer consumers | `frontend/src/components/agents/AgentPlanContent.tsx`, `frontend/src/components/agents/PlanPreviewModal.tsx` | Untouched |
| i18n | `frontend/src/i18n/` (`config.ts`, `locales/`) | Modify — reuse `agents.panel.*` topology keys; add preview-specific keys only if needed, in all locales |
| Tests — updated | `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` | Modify — assert unified canvas in preview |
| Tests — regression guards | `frontend/src/__tests__/PanelTopologyCanvas.test.tsx`, `frontend/src/__tests__/AgentManagementPanelPage.test.tsx` | Extend/keep passing |
| Tests — new coverage | New/extended tests for zoom parity + unified rendering in preview | Create |

## Risks & Mitigations

- **Panel regression**: any prop added to `PanelTopologyCanvas` must default to current behavior; `PanelTopologyCanvas.test.tsx` and `AgentManagementPanelPage.test.tsx` must pass without behavioral edits.
- **Dialog height constraints**: the panel canvas assumes a flexible-height container; the preview dialog may need layout adjustments so zoom controls and the fullscreen view are not clipped.
- **Data completeness**: the preview must load SOP details (composed skills) for the tree rendering; if the dialog does not already fetch SOP details, reuse the same query the panel uses rather than degrading the view.
