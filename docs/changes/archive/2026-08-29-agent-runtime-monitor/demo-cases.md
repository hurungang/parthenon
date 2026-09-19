# Demo Cases: agent-runtime-monitor
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/agent-runtime-monitor/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Agent Runtime Monitor > presents the view as "Agent Runtime Monitor" and renders the map canvas
- Agent Runtime Monitor > auto-fits the map and groups each delegation tree into a team container
- Agent Runtime Monitor > renders a delegation connector between parent and child
- Agent Runtime Monitor > surfaces a sleeping agent awaiting intervention and opens the intervention dialog
- Agent Runtime Monitor > selects a node and opens the termination dialog from the detail bubble
- Agent Runtime Monitor > zooms in and out via the toolbar
- Agent Runtime Monitor > pans the canvas via drag
- Agent Runtime Monitor > toggles fullscreen and restores
- Agent Runtime Monitor > shows a cross-type parent/child delegation connector
- Agent Runtime Monitor > recovers from the filtered-empty state via "Reset filters"
- Agent Runtime Monitor > shows trigger provenance as a person entity wired to the execution
- Agent Runtime Monitor > renders the Communication Hub and tool-call routes to MCP servers
- Agent Runtime Monitor > renders the System Tools node and skips unknown-slug and a2a tool calls
- Agent Runtime Monitor > shows schedule creator attribution and no person line for a null-creator schedule

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Page rename & map composition | The runtime view opens as "Agent Runtime Monitor" with the interactive map canvas as the primary view (no residual "topology" naming). | e2e/tests/runtime-control-dashboard.spec.ts | Agent Runtime Monitor > presents the view as "Agent Runtime Monitor" and renders the map canvas |
| 2 | Map auto-fit & team containers | Many agents fit on screen automatically and each delegation tree groups into a labelled team container (`team-container-*`): root at depth 0, delegated children at deeper depth columns, with a count chip. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > auto-fits the map and groups each delegation tree into a team container |
| 3 | Delegation relationship | A parent agent and its delegated child render adjacent with a visible connector line. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > renders a delegation connector between parent and child |
| 4 | Human-intervention alert | A sleeping agent awaiting intervention shows an alert icon; clicking it opens the human-intervention dialog for that session. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > surfaces a sleeping agent awaiting intervention and opens the intervention dialog |
| 5 | Selection & terminate | Selecting a node opens the detail bubble with a terminate action; the termination flow completes with the correct payload. | e2e/tests/runtime-control-dashboard.spec.ts | Agent Runtime Monitor > selects a node and opens the termination dialog from the detail bubble |
| 6 | Zoom in/out | The toolbar zoom controls scale the map canvas up and down. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > zooms in and out via the toolbar |
| 7 | Drag-to-pan | Dragging empty canvas pans the viewport across the map. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > pans the canvas via drag |
| 8 | Fullscreen toggle | Maximising expands the map to fullscreen and toggling again restores the normal layout. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > toggles fullscreen and restores |
| 9 | Cross-type delegation | A parent agent and its delegated child of a different type remain adjacent and joined by a visible connector line. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > shows a cross-type parent/child delegation connector |
| 10 | Filter reset recovery | Hiding every agent-kind node empties the map; the "Reset filters" control restores the population without a page reload. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > recovers from the filtered-empty state via "Reset filters" |
| 11 | Trigger provenance | Person/schedule entities in the leftmost column, wired by trigger lines to the executions they triggered. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > shows trigger provenance as a person entity wired to the execution |
| 12 | Communication Hub & MCP routes | The Communication Hub renders as a full-height vertical bar and tool-call routes run orthogonally to MCP server nodes (per tool slug) with tool chips; selecting an agent highlights its route and involved MCP/tools. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > renders the Communication Hub and tool-call routes to MCP servers |
| 13 | System Tools & excluded calls | System-slug tool calls collapse into the single synthetic "System Tools" node with its tool chip; unknown-slug calls (NULL route_type degrade rows) render no MCP node or chip, and a2a rows (delegations) are excluded outright. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > renders the System Tools node and skips unknown-slug and a2a tool calls |
| 14 | Creator attribution & trigger cards (Phase 13) | Schedule entities render in the trigger column wired to their executions. The schedule card with a known creator shows the creator caption ("by Alice Operator") and its execution list; dismissing closes it. A legacy null-creator schedule shows no creator caption anywhere, and selecting its execution degrades the "Triggered by" line to "Unknown" — the schedule name never appears as a person. | e2e/tests/agent-runtime-monitor.spec.ts | Agent Runtime Monitor > shows schedule creator attribution and no person line for a null-creator schedule |
