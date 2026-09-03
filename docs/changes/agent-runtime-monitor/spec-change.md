# Spec Change: Agent Runtime Monitor

## Affected Spec Areas

- `docs/master/product/features/control-center.md` — "Runtime Control Dashboard" description currently refers to a "topology diagram view" of active agent-to-agent delegation
- `docs/master/product/features/agent-execution.md` — "Runtime Control and Termination Governance" section describes the topology diagram and selectable nodes
- `docs/master/product/features/observability.md` — "Runtime Control Dashboard" entry references delegation topology
- `docs/master/product/features/foundation-platform.md` — sidebar navigation references the "Runtime Control" module (unchanged label, but description wording should reflect the new view)
- `docs/master/product/features/communication-hub.md` — the Communication Hub is surfaced as a visible component on the runtime map, with agent tool-call routes drawn through it
- `docs/master/product/features/schedule-management.md` — schedules carry a "scheduled by" user, surfaced as the trigger source for schedule-triggered agents

## New Capabilities

- **Interactive map canvas** — A full-page, map-style view with zoom in/out and drag-to-pan, replacing the static single-row diagram. The canvas auto-fits its content so the full agent population is visible without scrolling.

- **Grid alignment with type grouping** — Agents are laid out on a grid rather than one row, and agents of the same type are grouped into a visible virtual container. Delegation adjacency takes precedence over grouping: a delegated child is placed beside its parent even across types, rather than being scattered into a separate type group. All agents are automatically distributed to fit the screen ratio.

- **Delegation adjacency with connectors** — An agent and its delegated child agent(s) are displayed next to each other, joined by a clear connecting line that shows the parent → child delegation relationship — even when the parent and child are different agent types, and the connector remains visible when other agents are filtered out.

- **Inline agent detail bubble** — Selecting an agent shows its detail (reusing the existing detail component) as a bubble beside the agent on the map, including a terminate button, a guardrail summary, and the agent's trigger source.

- **Trigger provenance** — Every agent shows who triggered it: a user, its delegated parent, or a schedule. Delegated agents inherit the trigger user of their parent; scheduled agents carry the schedule's "scheduled by" user, passed through when the schedule triggers. The map (tile and/or detail bubble) shows the triggering user's name or the schedule name.

- **Tool-call route visualisation (Communication Hub)** — The Communication Hub is shown as a visible component on the map. Tool calls an agent makes are drawn as routes from the agent, through the Communication Hub, to the MCP server that served the call. The latest call's route is highlighted in a unique colour per agent; older calls render in a light grey; selecting an agent brightens all of its historical routes.

- **Filter & legend with empty-state recovery** — The map offers status and agent-type (kind) filters plus a legend in a persistent toolbar. When a filter hides every agent, the filter/legend controls and toolbar remain visible and usable, so the operator can always restore visibility — no "trapped" empty state.

- **Fullscreen maximise** — The map can be maximised to fill the screen and restored to normal layout.

- **Default human-intervention alerting** — Sleeping agents that are waiting for human intervention are shown by default with an alert icon on their tile; clicking the icon opens the existing human-intervention dialog.

## Modified Capabilities

- **Runtime map view naming** — Before: the live runtime view was described as a "topology" diagram. After: it is named **Agent Runtime Monitor**, with no user-facing "topology" naming remaining for this live view.

- **Runtime map layout & interaction** — Before: static diagram laying every agent at the same delegation depth into a single horizontal row, with no zoom, no pan, and an unreliable scrollbar. After: interactive map canvas with auto-fit, zoom in/out, drag-to-pan, grid alignment, automatic distribution to the screen ratio, and status/agent-type filtering with a legend that stays usable even when a filter hides every agent.

- **Agent detail presentation** — Before: a separate detail panel at the bottom of the page. After: an inline bubble next to the selected agent, containing the same detail information (terminate action + guardrail summary) plus the agent's trigger source (who triggered it).

- **Sleeping-agent visibility** — Before: "sleep" conversations are hidden by default because they dominate the diagram. After: sleeping agents that are waiting for human intervention are the exception and are shown by default with an alert indicator; sleeping agents not awaiting intervention remain hidden.

## Removed Capabilities

- **Model guardrail panel on the runtime map page** — The model guardrail panel is removed from this page entirely. (The model-usage guardrail feature itself remains in the product; only its placement on this page is removed.)

## Spec Update Instructions

- Update `docs/master/product/features/control-center.md` — rename the "topology diagram view" / "runtime topology dashboard" references to "Agent Runtime Monitor", and describe the interactive map (zoom, pan, auto-fit, grid, type grouping) and the inline detail bubble
- Update `docs/master/product/features/agent-execution.md` — in the "Runtime Control and Termination Governance" section, replace the static topology-diagram description with the Agent Runtime Monitor interactive map and note the default visibility of sleeping agents awaiting human intervention
- Update `docs/master/product/features/observability.md` — replace the "delegation topology" wording for the Runtime Control Dashboard with "Agent Runtime Monitor interactive map"
- Update `docs/master/product/features/foundation-platform.md` — keep the "Runtime Control" module label but update any descriptive wording referencing the topology view to reference the Agent Runtime Monitor
- Create a new feature spec `docs/master/product/features/agent-runtime-monitor.md` describing the map canvas interaction model, grid/type grouping, cross-type delegation connectors, inline detail bubble (with trigger provenance), fullscreen behaviour, trigger-provenance display, tool-call route visualisation through the Communication Hub, filter/legend empty-state recovery, and the human-intervention alerting rule
- Update `docs/master/product/features/communication-hub.md` — note that the Communication Hub appears as a visible component on the Agent Runtime Monitor, with agent tool-call routes drawn through it (agent → Communication Hub → MCP server)
- Update `docs/master/product/features/schedule-management.md` — document the schedule "scheduled by" user and that it is passed through as the trigger source for schedule-triggered agents shown on the runtime map
- Update `docs/master/product/README.md` — add an "Agent Runtime Monitor" entry to the Feature Index
- Do **not** change the unrelated "topology" diagram in Agent Plan Preview (`agent-plan-mode.md`) — that refers to the static plan topology, not the live runtime map
