# Tech Spec: Unify Agent Topology Diagram

## Scope

Frontend-only change in `frontend/src`. This is a direct replacement, not an enhancement: the low-fidelity conversation-topology rendering in the agent preview (`AgentTypeDetailsDialog`) is deleted, and the management panel's polished `PanelTopologyCanvas` is mounted in its place — the same component, as-is, gaining the preview the zoned composition and zoom in/out (0.5×–3×) behavior for free. The only new code is a thin data-shape adapter mapping the dialog's already-loaded agent type data into the `AgentDraftComposition` shape the existing panel component consumes. No backend, API, database, or security-boundary changes; no impact on the top-priority rules in `docs/config.yaml`.

## Component Breakdown

### Reused components — mounted as-is, unchanged

| Component | Role in this change |
|---|---|
| `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` | The canonical topology view, embedded in the preview — same component, same view. Documented deviations: (1) an OPTIONAL `onNodeClick?: (node: TopologyNode) => void` prop was added (forwarded to the renderer in inline and fullscreen modes) because the canvas previously never wired node clicks and the preview must keep its `handleNodeClick` detail navigation. Default (prop omitted, as the panel uses it) is byte-for-byte the previous behavior. (2) Refinement — responsive auto-fit with a capped font size: a new exported constant `TOPOLOGY_MAX_FONT_SCALE` (1.6, alongside `TOPOLOGY_MIN_ZOOM`/`TOPOLOGY_MAX_ZOOM`/`TOPOLOGY_ZOOM_STEP`) is passed to the renderer as the optional `viewFontZoom` cap in fullscreen; zoom controls (0.5×–3×, step 1.2, auto-fit at 1, reset on fullscreen transitions) are unchanged. (3) Refinement — contract-slot labels: `buildPanelTopology` now distinguishes deliberately-set states from unfilled slots, showing the editor dialog's labels ("None" via `agents.panel.noInputType` for input type `none`, "Conversation" via `agents.panel.inputTypeConversation`, "Auto" via `agents.types.outputAuto` for output type `auto`/`markdown`/unset) as solid nodes, while genuinely unfilled slots (typed input without a schema, typed output without a data type) keep the dashed placeholders. |
| `frontend/src/components/agents/TopologyDiagramRenderer.tsx` | Low-level SVG renderer with viewBox-based zoom/pan transform (view width = world width / zoom, so text fitting and hit targets stay valid at any zoom). Refinement — font-scale cap: an OPTIONAL `viewFontZoom?: number` prop (a zoom level at which drawn fonts stop growing) makes the renderer shrink ALL drawn font sizes (node labels/badges/captions, boundary header, zone titles/subtitles, group labels, edge labels, hub bar label) and their width-fitting calls by `cap / zoom` once zoom passes the cap, so on-screen glyph size plateaus while the visible world region keeps expanding — zoom reveals MORE CONTENT (width-fitted labels fit more characters before ellipsis) instead of bigger text. Omitted = uncapped (historical behavior; also the default for out-of-scope consumers `AgentPlanContent.tsx`, `PlanPreviewModal.tsx`). Still consumed via `PanelTopologyCanvas`. |
| `frontend/src/components/agents/topologyHub.ts` | `withCommunicationHub` hub helper — used internally by the panel composition. Untouched. |
| `frontend/src/components/agents/topologyNodeIcons.tsx`, `frontend/src/components/agents/topologyTextFit.ts` | Node icons and viewBox-unit text fitting (estimator-based, no live DOM measuring). Untouched — the font cap reuses the same estimator at a scaled font size. |
| `frontend/src/components/agents/AgentDetailBubble.tsx` | Detail bubble shown on node interaction; behavior inherited in the preview via the canvas. Untouched. |

### Modified components

| Component | Change |
|---|---|
| `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` | The agent preview. Old topology rendering deleted: the `TopologyDiagramRenderer` usage fed by the conversation-topology `convTopologyNodes`/`convTopologyEdges` composition (a `useMemo` with direct `withCommunicationHub` usage) is removed entirely — nothing kept, wrapped, or layered on top. `PanelTopologyCanvas` is mounted in the same section, fed by the new draft mapping. The now-dead `/mcp/tools` dialog query (only consumed by the deleted composition) was removed with it — the canvas resolves tool names/labels from its own shared registry queries. Existing `handleNodeClick` behavior and the existing permission-denied error alert are preserved. `handleNodeClick` additionally resolves the canvas's `type_id`-prefixed node ids (e.g. `sop_x`) and no-ops on empty-slot placeholders. |

### New code (glue only)

| Unit | Location | Purpose |
|---|---|---|
| Draft mapping adapter (new, glue only) | `frontend/src/components/agents/agentTypeToDraftComposition.ts` (`agentTypeToDraftComposition`) | Converts the dialog's already-loaded agent type data (identity, role, input schema, output data type, model, skills, SOPs) into an `AgentDraftComposition` (defined in `frontend/src/types/index.ts`), mirroring the initialization logic in `frontend/src/hooks/useAgentDraftComposition.ts`. This adapter exists solely because the existing component expects that shape — it is unavoidable glue, not new design. Purely client-side; no new data fetching. |

## API Changes

None. No backend endpoints are added, modified, or removed. The preview continues to use the same queries it already issues for the agent type, roles, skills, SOPs, SOP details, identities, data types, and models; `PanelTopologyCanvas` resolves names/labels from that same shared registry data via its own react-query caches (including SOP detail steps for composed-skill trees, tool display names, MCP server slug grouping, and model labels). No frontend API client modules change.

## State Management

- **Preview (React local state)**: `AgentTypeDetailsDialog` already holds the loaded agent type and related registry data in local state/hooks. The draft adapter is a pure derived value (`useMemo`) over that data — read-only, no editing, passed to the canvas with `isDirty={false}`, matching the panel canvas's existing prop contract (the only prop addition is the optional `onNodeClick`).
- **Panel canvas internal state (reused as-is)**: `PanelTopologyCanvas` owns `fullscreen` and `zoom` (`useState`), resetting zoom to 1 (auto-fit) on fullscreen enter/exit; `TopologyDiagramRenderer` owns pan center and view transform for the fullscreen viewBox scaling. No global state (Redux/Context) is introduced; zoom state is intentionally local and resets on unmount.
- **No persistence**: zoom/fullscreen state is ephemeral per open of the preview dialog or panel, matching current panel behavior.

## Data Access Patterns

- **No new data access.** The dialog's existing queries provide: agent type (identity/role/model/input/output bindings), roles, skills, SOPs + SOP details (composed-skill steps, order-preserved), and agent identities. `PanelTopologyCanvas` consumes these plus its own shared registry queries (data types, model configurations, MCP servers and MCP tools) to build `PanelTopologyNames` (role/identity/skill/SOP/data-type names, model labels, tool names + server slugs/colors, `sopComposedSkillIds`).
- **Composition is purely client-side**: `buildPanelTopology` transforms the draft + name tables into `PanelTopologyGraph` (`TopologyNode[]`, `TopologyEdge[]`, zone bands). No topology data comes from the backend for this view.
- **Permission behavior**: unchanged. The dialog's existing permission checks guard the data queries; a denied user still sees the graceful permission error, not an empty diagram.

## Code Reference Map

| Area | File | Action |
|---|---|---|
| Agent preview dialog | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` | Modify — old topology rendering deleted (conversation composition + `TopologyDiagramRenderer` usage removed); `PanelTopologyCanvas` mounted for ALL agent types (typed agents get the canvas above `AgentPlanContent` with `hideTopology`, keeping plan steps, script links, Regenerate plan, and the generation-failed alert); keep `handleNodeClick` + permission error |
| Canonical topology canvas | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` | Modify — optional `onNodeClick` prop (default = previous behavior); refinement: exported `TOPOLOGY_MAX_FONT_SCALE` font cap passed as `viewFontZoom` in fullscreen; refinement: `buildPanelTopology` + `PanelTopologyLabels` label deliberately-set `none`/`conversation` inputs and `auto`-type outputs with the editor dialog's text (unfilled slots stay placeholders); zoom/fullscreen logic unchanged |
| Panel topology composition | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` (`buildPanelTopology`, `PanelTopologyGraph`, `PanelTopologyNames`, `PanelTopologyLabels`) | Modify per the refinements above (new `inputNone`/`inputConversation`/`outputAuto` labels) |
| SVG renderer (zoom/pan transform) | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` | Modify per the refinement above — optional `viewFontZoom` font-scale cap applied to all drawn text and width fitting; uncapped (unchanged) when omitted |
| Hub helper | `frontend/src/components/agents/topologyHub.ts` | Reuse unchanged (indirect usage only) |
| Node icons / text fit | `frontend/src/components/agents/topologyNodeIcons.tsx`, `frontend/src/components/agents/topologyTextFit.ts` | Reuse unchanged |
| Node detail bubble | `frontend/src/components/agents/AgentDetailBubble.tsx` | Reuse unchanged |
| Draft composition type | `frontend/src/types/index.ts` (`AgentDraftComposition`, `TopologyNode`, `TopologyEdge`, `TopologyZone`) | Reuse unchanged (type-only) |
| Draft initialization reference | `frontend/src/hooks/useAgentDraftComposition.ts` | Read-only reference for the adapter's mapping |
| Draft mapping adapter (new, glue only) | `frontend/src/components/agents/agentTypeToDraftComposition.ts` | Create — thin pure agent-type → `AgentDraftComposition` mapping (`agentTypeToDraftComposition`) |
| Management panel page (regression surface) | `frontend/src/pages/agents/AgentManagementPanelPage.tsx` | No code change; verify identical behavior |
| Plan content (typed-agent steps) | `frontend/src/components/agents/AgentPlanContent.tsx` | Modify — minimal optional `hideTopology` prop added to suppress its internal plan-based topology; used only by the preview dialog. `PlanPreviewModal` usage unchanged (keeps its own plan topology) |
| Out-of-scope renderer consumer | `frontend/src/components/agents/PlanPreviewModal.tsx` | Untouched |
| i18n | `frontend/src/i18n/` (`config.ts`, `locales/`) | Verify only — panel canvas's existing `t()` labels carry over; add keys only if a genuinely missing label is exposed |
| Tests — updated | `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` | Modify — assert unified canvas in preview for ALL agent types; typed agents keep plan content with topology suppressed |
| Tests — plan content | `frontend/src/__tests__/AgentPlanContent.test.tsx` | Create — default plan-topology rendering vs. `hideTopology` suppression; PlanPreviewModal path keeps default behavior |
| Tests — adapter | `frontend/src/__tests__/agentTypeToDraftComposition.test.ts` | Create — unit tests for the draft mapping (typed/conversational/minimal agents, guardrail defaults, purity) |
| Tests — regression guards | `frontend/src/__tests__/PanelTopologyCanvas.test.tsx` (extended: optional `onNodeClick` forwarding/default-unchanged, font-cap `viewFontZoom` passthrough, None/Auto vs. placeholder contract-slot labels), `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` (extended: drawn font size capped past `viewFontZoom`, viewBox still expands, omitted cap = historical behavior), `frontend/src/__tests__/AgentManagementPanelPage.test.tsx` (passing, no edits) | Keep passing without behavioral edits |
| E2E — preview/panel parity | `e2e/tests/agent-type-preview-topology.spec.ts` | Create — unified zoned canvas + hub bar in preview, fullscreen zoom parity with panel, node-click entity view, typed-agent unified canvas + plan-steps regression |
| E2E — panel topology | `e2e/tests/agent-management-panel-topology.spec.ts` | Modify — fixed stale expectations and the contract-slot assertions: input type `none` / output type `auto` agents now show "None"/"Auto" instead of dashed empty placeholders |

## Risks & Mitigations

- **Panel regression**: `PanelTopologyCanvas` is reused with the single optional `onNodeClick` prop (default = previous behavior); `PanelTopologyCanvas.test.tsx` and `AgentManagementPanelPage.test.tsx` pass without behavioral edits.
- **Dialog height constraints**: the panel canvas assumes a flexible-height container; only the preview dialog's container layout may need adjusting so zoom controls and the fullscreen view are not clipped — not a component change.
- **Data completeness**: the preview must load SOP details (composed skills) for the tree rendering; if the dialog does not already fetch SOP details, reuse the same query the panel uses rather than degrading the view.
