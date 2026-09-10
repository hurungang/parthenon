# Agent Runtime Monitor — PRD

## Epic Overview

The runtime-control "agent topology" view is a static diagram that lays every running agent at the same delegation depth into a single horizontal row, with no zoom, no pan, and an unreliable scrollbar; agent details and model guardrails live in separate panels at the bottom of the page. For operators watching a live, multi-level agent population, this makes it hard to see delegation relationships, locate a specific agent, tell who triggered whom, trace what tools an agent is calling, or react to an agent that needs attention. This epic replaces the static topology with **Agent Runtime Monitor** — a full-page, interactive, map-style canvas that auto-fits the population and arranges agents in a team-row layout whose columns represent delegation depth, so every delegation chain reads across the map from origin to outcome. A dedicated trigger column shows every person and schedule that set executions in motion, each connected by lines in its own colour, and both agents and trigger entities open dismissible detail cards beside themselves on the map. Schedule-triggered executions are always attributed to the human who created the schedule — never to the schedule itself — so accountability points to people. Hovering or clicking any entity focuses its complete upstream-and-downstream topology without unrelated noise leaking in through shared tool servers. The Communication Hub appears as a full-height fixture with its MCP servers and tool chips, each agent's tool calls drawn as routes through it, agent detail bubbles show guardrail usage against limits with a link to the execution log, any node awaiting human intervention carries an alert, and a filter popover — including a recent-completed window — keeps the view tunable at all times. The map keeps itself current without operator action: it subscribes to a server push channel (with automatic fallback to polling), so executions starting, changing state, or finishing — and trigger or intervention changes — appear within a second or two of happening.

## Business Goals

- **Make delegation relationships legible at a glance** — The team-row layout with delegation-depth columns lets operators read every delegation chain from origin to outcome, so hierarchy questions are answered without manually tracing lines
- **Guarantee human accountability for every execution** — Every execution shows its trigger source, and schedule-triggered executions are attributed to the person who created the schedule — never the schedule name — with unknown creators shown as no name rather than a misleading placeholder
- **Enable whole-chain focus without noise** — Hovering or clicking any entity isolates its complete upstream and downstream topology, excluding unrelated entities that merely share a tool server, so operators can reason about one chain at a time
- **Expose tool activity through the Communication Hub** — A full-height hub fixture with its MCP servers and tool chips, and per-agent tool-call routes, shows what every agent is doing right now
- **Reduce time to detect, inspect, and act** — Alerts on any node awaiting intervention, dismissible detail bubbles (terminate, guardrail usage vs limits, execution-log links), trigger-entity cards with execution lists, and a filter popover with a recent-completed window keep operators in control, while server-push updates (with automatic polling fallback) make every change visible within a second or two — no refresh required

## Users & Personas

- **Platform Operators** — Watch live executions, delegations, tool calls, and intervention requests as they happen on a map that stays current on its own; need to scan the population, focus on a single chain, see who triggered each execution, jump from a person or schedule to the work it caused, and act (terminate, respond to intervention) quickly
- **AI Operations Leads** — Monitor topology health and tune limits; need delegation depth made visible in the layout, guardrail usage shown against limits, and tool-call routes through the hub to spot unhealthy patterns
- **Compliance / Audit Stakeholders** — Verify that every execution is attributable to a responsible person (including schedules being traceable to their human creator), that statuses and execution logs are reachable from the map, and that tool-call history is visible at a glance

## User Stories

- As a platform operator, I want the map to auto-fit the full running population on first load — however many agents are running — and support zoom and drag-to-pan so that I can step back to the whole picture or focus on a busy region without scrolling
- As a platform operator, I want the map to update on its own the moment an execution starts, changes state, or finishes — and whenever trigger or intervention state changes — so that I am always looking at current reality without refreshing or waiting for a poll cycle
- As a platform operator, I want the canvas to look right from the first moment — grid dots covering the whole visible map and the hub bar full-height even before any agents appear — so that the monitor is dependable and legible before I interact with anything
- As a platform operator, I want agents arranged in a team-row layout where each column is a delegation depth so that I can read each delegation chain from its origin to its outcome
- As a platform operator, I want every person and schedule that triggered executions shown in a dedicated trigger column, connected to their executions by lines in that entity's own colour, so that I can see at a glance who and what set the map in motion
- As a platform operator, I want schedule-triggered executions attributed to the person who created the schedule so that accountability always points to a human and never to the schedule itself
- As a platform operator, I want no creator shown at all when a schedule's creator is unknown so that I am never misled by placeholder information
- As a platform operator, I want clicking a person in the trigger column to open a card showing their name, how many executions they triggered directly and via schedules, and the list of those executions with types and statuses, so that I can review a person's footprint without leaving the map
- As a platform operator, I want clicking a schedule in the trigger column to open a card showing its name, its human creator, and the executions it triggered with statuses, so that I can audit the schedule's impact
- As a platform operator, I want selecting an execution in a trigger card to focus and navigate to it on the map so that I can jump straight from a person or schedule to the work it caused
- As a platform operator, I want hovering or clicking any entity to highlight its entire upstream and downstream chain — and nothing else — so that I can reason about one topology without unrelated entities leaking in through shared tool servers
- As a platform operator, I want selecting an agent to show a detail bubble beside it — a terminate action, guardrail usage against its limits, a link to its execution log, and who triggered it — so that I can inspect and act without leaving the map
- As a platform operator, I want the Communication Hub shown as a full-height fixture with its MCP servers and tool chips, and each agent's tool calls drawn as routes through it with the latest call highlighted, so that I can see what each agent is currently doing
- As a platform operator, I want any node awaiting human intervention to carry an alert icon so that I can notice and respond to blocked workflows wherever they occur in the topology
- As a platform operator, I want a filter popover with status and agent-type filters plus a recent-completed window so that I can tune the view to what matters right now
- As a platform operator, I want the filter and legend controls to stay visible and usable even when a filter hides every entity so that I can always restore visibility and am never stranded on an empty map
- As a platform operator, I want to maximise the map to fill the screen so that I can dedicate the whole page to monitoring during an incident

## Acceptance Criteria

### Naming & Page Composition

- The view is presented as **"Agent Runtime Monitor"** throughout the UI (no remaining user-facing "topology" naming for this live runtime view)
- The page is primarily the agent map; the map occupies the main canvas area
- The model guardrail panel is removed from this page entirely — no guardrail panel, section, or tab remains on the Agent Runtime Monitor

### Map Layout & Interaction

- The map auto-fits its content so all visible entities are on screen without scrolling; when many agents are present, the initial view on first load still fits the entire population — the initial fit is not prevented by the interactive zoom limits
- Agents are arranged in a team-row layout in which each column corresponds to a delegation depth, so delegation chains read across the map in order
- The map supports zoom in and zoom out
- The map supports drag-to-pan to move around the canvas
- The map can be maximised to fullscreen and restored to the normal page layout
- The map's grid-dot background covers the entire visible canvas at all times — including when panning or zooming beyond the drawn content and when the map is empty

### Live Updates

- The monitor keeps itself current without the operator refreshing: it receives changes through a server push channel rather than relying on fixed-interval polling
- When an execution starts, changes state, or finishes, the map reflects it within about a second or two — no manual refresh and no waiting for a poll cycle
- When trigger or intervention state changes — such as a node beginning or ceasing to await human intervention — the map reflects it with the same immediacy
- If the push connection drops, the map automatically falls back to periodic polling so the view never silently goes stale, and returns to live push once the connection is restored

### Trigger Entities & Attribution

- A dedicated trigger-entity column shows every person and schedule that triggered executions, each connected by lines to the executions it triggered
- Each trigger entity's lines are drawn in a colour unique to that entity, so its footprint is traceable at a glance
- Wherever a schedule-triggered execution's trigger is displayed — trigger entity cards, agent detail bubbles, and tooltips — the human who created the schedule is shown
- The schedule name identifies the schedule entity itself (its tile in the trigger column and its own detail card) and never appears in place of a human name
- When the schedule's creator is unknown (schedules created before creator tracking existed), no creator is displayed — no placeholder text or generic label is shown
- Directly triggered executions show the triggering user's name; delegated agents show their parent's trigger source

### Trigger Entity Detail Cards

- Clicking a trigger entity opens a detail card beside it; clicking the entity again (or dismissing the card) closes it
- A person's card shows the person's name, the number of executions they triggered (directly and via schedules), and the list of those executions with their types and statuses; the person's own details (email, identity type) are shown when available
- A schedule's card shows the schedule name, its own details (schedule cadence, description, status), its creator (a human), and the executions it triggered with their statuses
- Selecting an execution in either card focuses — and navigates to — that execution on the map
- Trigger cards are dismissible in the same way as the agent detail card, so the operator can return to the plain map view

### Whole-Topology Focus

- Hovering or clicking any entity on the map focuses its complete topology: everything downstream of it and everything upstream of it
- The focus does not leak sideways: entities that merely share an MCP server (or the hub) with the focused chain are not included unless they are genuinely upstream or downstream of the focused entity
- Unrelated entities are visually de-emphasised while a focus is active

### Agent Selection & Detail

- Selecting an agent shows its detail as a bubble next to the agent on the map
- The detail bubble includes a terminate button, guardrail usage shown against the agent's limits, a link to the agent's execution log, and the agent's trigger source
- The trigger source follows the attribution rules above — including the schedule's human creator for schedule-triggered agents
- The detail bubble is dismissible so the operator can return to the plain map view

### Tool-Call Routes (Communication Hub)

- The Communication Hub is shown as a full-height fixture on the map — spanning the full canvas height from the moment the map loads, even when no agents are present yet — with its MCP servers attached and the tools they expose shown as chips
- Each tool call an agent makes is drawn as a route from the agent, through the hub, to the MCP server that served the call
- The most recent call's route is highlighted; older calls render in a light, barely-visible grey; selecting an agent brightens all of its historical routes

### Human-Intervention Alerting

- Any node awaiting human intervention — regardless of its state — is visible on the map by default and carries an alert icon
- Clicking the alert icon opens the existing human-intervention dialog so the operator can respond
- Sleeping agents not awaiting intervention remain hidden by default (they continue to be excluded to avoid dominating the map)

### Filter & Legend Recovery

- The map provides a filter popover with status and agent-type (kind) filters plus a recent-completed window that limits the view to executions completed within a recent time span
- A legend explaining the map's colours and symbols is accessible alongside the filters
- When a filter combination hides every entity, the filter popover and legend remain visible and usable, so the operator can clear or adjust the filter to restore visibility
- There is no "trapped" empty state: an operator can always recover the population without reloading the page

## Out of Scope

- Backend and data-serving design — the runtime map data (including schedule-creator provenance and upstream/downstream chain information) is a required input, and live delivery over a server push channel (with automatic polling fallback) is a required capability, but this epic does not specify how either is implemented
- New business entities for capturing schedule provenance — recording who created a schedule is an addition to the schedule itself, not a new business entity
- Changes to the unrelated Agent Plan Preview "topology" diagram used in agent-type configuration
- Re-adding or relocating the model guardrail panel anywhere else in the product
- Redesigning the terminate flow or the human-intervention dialog themselves (they are reused as-is)
- Editing agent configuration, delegations, or schedules directly from the map (read-only runtime monitor, apart from terminate and intervention response)
- Alert thresholds or notification triggers based on map state
- Mobile-specific responsive design (desktop-first for this epic)

## Dependencies & Constraints

- The monitor depends on reliable live runtime state, delegation (parent/child) relationship signals, execution statuses, and pending-human-intervention information for any node — reaching the map in near real time so each change is visible within about a second or two
- The monitor depends on a server push channel for change delivery, with periodic polling retained only as an automatic fallback when the push connection is unavailable
- The monitor depends on trigger provenance: each execution's trigger source — the user who started it directly, the delegating parent, or the schedule together with the human who created it. Executions triggered by schedules created before creator tracking must be representable without a creator (shown with no creator, never a placeholder)
- Whole-topology focus depends on accurate upstream and downstream chain data; relationships must come from real trigger and delegation chains, not from shared tool-server usage
- The map depends on tool-call routing data from the Communication Hub, including which MCP server served each call and the ordering of calls per agent
- The map reuses the existing terminate action, human-intervention dialog, and agent detail presentation
- Follows existing UI component and internationalisation conventions (documented in `docs/config.yaml`)
- The view remains read-only with respect to agent configuration; permitted actions are terminate and human-intervention response only
