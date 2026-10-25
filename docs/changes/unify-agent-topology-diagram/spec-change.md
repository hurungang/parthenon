# Spec Change: Unify Agent Topology Diagram

## Affected Spec Areas

- `docs/master/product/features/agent-management.md` — agent management panel topology diagram (becomes the single canonical topology view)
- `docs/master/product/features/agent-types.md` — agent preview view, which currently embeds its own topology diagram
- `docs/master/ux/` — master UI prototype, topology diagram presentation in preview and management contexts

## New Capabilities

- **Unified topology view in agent preview**: the agent preview now presents the identical topology view used by the agent management panel, giving preview users the management panel's richer visuals and interactions.
- **Zoom in/out in agent preview topology**: users can zoom in and out of the topology diagram directly from the agent preview, matching management panel behavior.

## Modified Capabilities

- **Agent preview topology diagram**
  - *Before*: the agent preview rendered its own, lower-fidelity topology diagram with different visuals and no zoom capability.
  - *After*: the agent preview renders the same topology view as the agent management panel — same layout, visuals, interactions, and information — including zoom in/out. The old preview-specific diagram is retired.
- **Agent management panel topology diagram**
  - *Before*: served as the higher-quality implementation, available only within the management panel.
  - *After*: unchanged in behavior; now also serves as the single canonical topology view reused by the agent preview.

## Removed Capabilities

- The standalone preview topology diagram implementation (the divergent lower-fidelity view) is removed from the user experience; users no longer encounter two different topology presentations.

## Spec Update Instructions

- In `docs/master/product/features/agent-management.md`: state that the management panel topology diagram is the single, canonical agent topology view, and that it is also presented in the agent preview, with zoom in/out available in both locations.
- In `docs/master/product/features/agent-types.md`: update the agent preview description to remove references to a separate preview topology diagram and state that the preview shows the unified (management panel) topology view, including zoom capability.
- In `docs/master/ux/`: update the master UI prototype so the agent preview topology representation matches the management panel topology representation (single shared presentation).
- Ensure any feature documentation that references "two topology views" or preview-specific topology behavior is corrected to describe the unified view.
