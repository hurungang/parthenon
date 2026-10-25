# PRD: Unify Agent Topology Diagram

## Epic Overview

The Parthenon web UI currently presents two different agent topology diagram views: one inside the agent preview view, and a higher-quality, more polished version in the agent management panel. Having two divergent views of the same information confuses users, doubles the maintenance surface, and delivers an inconsistent experience depending on where a user happens to be. This change unifies the experience: the agent preview will present the exact same topology view used in the agent management panel — including its superior visuals and zoom in/out capability — so users always see one consistent, high-quality topology diagram everywhere.

## Business Goals

- Deliver a single, consistent topology experience — 100% identical view in agent preview and agent management panel
- Improve usability of topology inspection by providing zoom in/out in both locations
- Reduce duplicated UI maintenance and the risk of the two views drifting apart
- Improve user perception of quality by retiring the lower-fidelity preview diagram
- Reduce support/UX confusion reported around inconsistent topology views (target: zero related complaints after release)

## Users & Personas

- **Platform Administrators** — configure and inspect agent types; need to understand agent topology (roles, skills, tools, connections) quickly and consistently from any screen
- **Agent Designers / Operators** — review agent configurations before deployment; need the richer management-panel view, including zoom, when examining complex topologies in the preview context
- **Tenant Users** — view agents they are permitted to see; benefit from one familiar topology experience instead of two

## User Stories

- As a platform administrator, I want the agent preview to show the same topology diagram as the agent management panel, so that I don't have to relearn a different view depending on where I am.
- As an agent designer, I want to zoom in and out of the topology diagram in the agent preview, so that I can inspect large or complex topologies comfortably.
- As an operator, I want a single canonical topology view, so that any documentation, training, or troubleshooting guidance applies everywhere.
- As a tenant user, I want topology diagrams to look and behave identically across the UI, so that the product feels coherent and trustworthy.

## Acceptance Criteria

- The agent preview displays the same topology diagram view as the agent management panel, with identical layout, visuals, interactions, and information shown
- The previous, divergent preview topology diagram is no longer shown anywhere in the UI
- Users can zoom in and zoom out of the topology diagram in the agent preview
- Zoom in/out in the agent preview behaves the same as in the agent management panel
- All agent preview topology content (nodes, relationships, labels) remains accurate and reflects the selected agent, as before
- All UI text in the unified view continues to use the localized text mechanism (no hardcoded strings) in both locations
- Users without permission to view a given agent's topology see a graceful permission error rather than a broken or empty diagram
- The agent management panel topology behavior is unchanged — no regression for existing management-panel users

## Out of Scope

- Any changes to the topology data itself (what entities/relationships exist in an agent topology)
- Redesigning or visually enhancing the management panel topology diagram — it is already the reference implementation
- New topology features beyond zoom parity (e.g., drag-and-drop editing, export, filtering)
- Backend/API changes
- Other diagram or visualization views in the product (e.g., SOP composition views)

## Dependencies & Constraints

- Depends on the existing agent management panel topology view remaining available and stable during the transition
- All UI text must go through the localization mechanism per project conventions
- UI-only change: must not affect backend services, security boundaries, or the top-priority architecture rules
- Reuse must preserve existing permission checks so that users only see topologies they are authorized to view
