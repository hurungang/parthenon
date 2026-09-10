# Spec Change: Agent Runtime Monitor

## Affected Spec Areas

- `docs/master/product/features/control-center.md` — "Runtime Control Dashboard" description currently refers to a "topology diagram view" of active agent-to-agent delegation
- `docs/master/product/features/agent-execution.md` — "Runtime Control and Termination Governance" section describes the topology diagram and selectable nodes
- `docs/master/product/features/observability.md` — "Runtime Control Dashboard" entry references delegation topology
- `docs/master/product/features/foundation-platform.md` — sidebar navigation references the "Runtime Control" module (unchanged label, but description wording should reflect the new view)
- `docs/master/product/features/communication-hub.md` — the Communication Hub is surfaced as a full-height fixture on the runtime map, with its MCP servers, tool chips, and agent tool-call routes drawn through it
- `docs/master/product/features/schedule-management.md` — schedules carry creator provenance; schedule-triggered executions are attributed to the schedule's human creator on the runtime map

## New Capabilities

- **Interactive map canvas** — A full-page, map-style view with zoom in/out and drag-to-pan, replacing the static single-row diagram. The canvas auto-fits its content so the full agent population is visible without scrolling; when many agents are present, the initial view on first load still fits the whole population — the initial fit is not prevented by the interactive zoom limits. The grid-dot background covers the entire visible canvas at all times, including when panning or zooming beyond the drawn content and when the map is empty.

- **Live self-updating map** — The monitor keeps itself current without the operator refreshing: it subscribes to a server push channel instead of relying on fixed-interval polling. When an execution starts, changes state, or finishes — and when trigger or intervention state changes — the map reflects the change within about a second or two. Periodic polling remains only as an automatic fallback while the push connection is down, and live push resumes when it recovers.

- **Team-row layout with delegation-depth columns** — Agents are arranged in rows in which each column corresponds to a delegation depth, so every delegation chain reads across the map from origin to outcome. Placement is driven by delegation depth rather than by type grouping; agent type remains visible through filters and the legend.

- **Trigger entity column** — Every person and schedule that triggered executions appears in a dedicated column on the map. Lines connect each trigger entity to the executions it triggered, drawn in a colour unique to that entity so its footprint is traceable at a glance.

- **Schedule creator attribution** — Wherever a schedule-triggered execution's trigger is displayed (trigger entity cards, agent detail bubbles, tooltips), the human who created the schedule is shown. The schedule name identifies the schedule entity itself (its tile in the trigger column and its own detail card) and never appears in place of a human name. When the creator is unknown (schedules created before creator tracking existed), no creator is displayed rather than a placeholder.

- **Trigger entity detail cards** — Clicking a trigger entity toggles a detail card beside it on the map:
  - Person card: the person's name, the number of executions they triggered (directly and via schedules), and the list of those executions with their types and statuses
  - Schedule card: the schedule name, its creator (a human), and the executions it triggered with their statuses
  - Selecting an execution in either card focuses — and navigates to — that execution on the map
  - Cards are dismissible in the same way as the agent detail card

- **Whole-topology focus** — Hovering or clicking any entity on the map highlights its complete topology: everything downstream of it and everything upstream of it. The focus does not leak sideways — entities that merely share an MCP server (or the hub) with the chain are excluded unless they are genuinely upstream or downstream. Unrelated entities are visually de-emphasised while a focus is active.

- **Communication Hub as a full-height fixture** — The hub spans the full height of the map from the moment it loads, even when there are no agents to show yet, with its MCP servers attached and the tools they expose shown as chips. Each agent's tool calls are drawn as routes from the agent, through the hub, to the MCP server that served the call; the most recent call is highlighted, older calls render in light grey, and selecting an agent brightens all of its historical routes.

- **Inline agent detail bubble** — Selecting an agent shows its detail as a bubble beside it on the map, including a terminate button, guardrail usage shown against the agent's limits, a link to the execution log, and the agent's trigger source (attributed per the creator rule above). The bubble is dismissible.

- **Intervention alerts on any awaiting node** — Any node awaiting human intervention, regardless of its state, is visible by default and carries an alert icon; clicking the icon opens the existing human-intervention dialog. Sleeping agents not awaiting intervention remain hidden.

- **Filter popover with recent-completed window** — A filter popover offers status and agent-type (kind) filters plus a recent-completed window that limits the view to executions completed within a recent time span, alongside a legend. When a filter hides every entity, the popover and legend remain visible and usable — no "trapped" empty state.

- **Fullscreen maximise** — The map can be maximised to fill the screen and restored to normal layout.

## Modified Capabilities

- **Runtime map view naming** — Before: the live runtime view was described as a "topology" diagram. After: it is named **Agent Runtime Monitor**, with no user-facing "topology" naming remaining for this live view.

- **Runtime map layout & interaction** — Before: static diagram laying every agent at the same delegation depth into a single horizontal row, with no zoom, no pan, and an unreliable scrollbar. After: interactive map canvas with auto-fit (fitting the whole population on first load even when it is large, not prevented by the interactive zoom limits), a grid-dot background covering the entire visible canvas even when empty or panned beyond the content, zoom in/out, drag-to-pan, live self-updating behaviour via a server push channel with automatic fallback to polling, a team-row layout with delegation-depth columns, and a filter popover (status, agent type, recent-completed window) with a legend that stays usable even when a filter hides every entity.

- **Agent detail presentation** — Before: a separate detail panel at the bottom of the page with a guardrail summary. After: an inline bubble next to the selected agent showing guardrail usage against the agent's limits, a link to the execution log, the terminate action, and the agent's trigger source.

- **Sleeping-agent visibility** — Before: "sleep" conversations are hidden by default because they dominate the diagram. After: any node awaiting human intervention is the exception and is shown by default with an alert indicator, regardless of its state; sleeping agents not awaiting intervention remain hidden.

- **Trigger provenance display** — Before: trigger attribution for schedule-triggered executions was not clearly tied to a responsible person. After: the schedule's human creator is shown as the trigger wherever it is displayed; the schedule name identifies only the schedule entity itself; executions from schedules with no known creator display without attribution rather than a placeholder.

## Removed Capabilities

- **Model guardrail panel on the runtime map page** — The model guardrail panel is removed from this page entirely. (The model-usage guardrail feature itself remains in the product; only its placement on this page is removed.)

## Spec Update Instructions

- Update `docs/master/product/features/control-center.md` — rename the "topology diagram view" / "runtime topology dashboard" references to "Agent Runtime Monitor", and describe the interactive map: team-row layout with delegation-depth columns, the trigger entity column with per-entity coloured lines, whole-topology focus on hover/click of any entity, detail bubbles for agents and trigger entities, intervention alerts on any awaiting node, live self-updating behaviour (server push channel with automatic fallback to polling), and the filter popover with the recent-completed window
- Update `docs/master/product/features/agent-execution.md` — in the "Runtime Control and Termination Governance" section, replace the static topology-diagram description with the Agent Runtime Monitor interactive map and note the default visibility of any node awaiting human intervention and the terminate action in the detail bubble
- Update `docs/master/product/features/observability.md` — replace the "delegation topology" wording for the Runtime Control Dashboard with "Agent Runtime Monitor interactive map"
- Update `docs/master/product/features/foundation-platform.md` — keep the "Runtime Control" module label but update any descriptive wording referencing the topology view to reference the Agent Runtime Monitor
- Create a new feature spec `docs/master/product/features/agent-runtime-monitor.md` describing: the canvas interaction model (auto-fit, zoom, pan, fullscreen), the team-row layout with delegation-depth columns, the trigger entity column with per-entity coloured lines, schedule creator attribution (the creator is shown wherever a schedule-triggered execution's trigger is displayed; the schedule name identifies the schedule entity only; unknown creators display nothing), the trigger entity detail cards (person and schedule variants, execution lists with types and statuses, select-to-focus behaviour, dismissibility), whole-topology focus (upstream and downstream with no sideways leak through shared MCP servers), the Communication Hub as a full-height fixture with MCP servers and tool chips and tool-call routes (spanning the full canvas height on load even when no agents are present), the agent detail bubble (terminate, guardrail usage vs limits, execution-log link, trigger attribution), intervention alerts on any awaiting node, live self-updating behaviour (server push channel with automatic fallback to polling; execution, trigger, and intervention changes visible within about a second or two), canvas presentation details (grid-dot background covering the entire visible canvas, including when empty or panned/zoomed beyond the content, and initial auto-fit of the whole population on first load not prevented by interactive zoom limits), and the filter popover with recent-completed window and empty-state recovery
- Update `docs/master/product/features/communication-hub.md` — note that the Communication Hub appears as a full-height fixture on the Agent Runtime Monitor with its MCP servers and tool chips, with agent tool-call routes drawn through it (agent → Communication Hub → MCP server)
- Update `docs/master/product/features/schedule-management.md` — document schedule creator provenance: the human who created a schedule is recorded and shown as the trigger attribution for schedule-triggered executions on the Agent Runtime Monitor; schedules created before creator tracking have no attributable creator and are displayed without one (never a placeholder); the schedule name identifies the schedule entity itself
- Update `docs/master/product/README.md` — add an "Agent Runtime Monitor" entry to the Feature Index
- Do **not** change the unrelated "topology" diagram in Agent Plan Preview (`agent-plan-mode.md`) — that refers to the static plan topology, not the live runtime map
