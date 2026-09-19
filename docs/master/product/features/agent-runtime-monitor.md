# Agent Runtime Monitor

## Overview

The Agent Runtime Monitor replaces the runtime control dashboard's static "agent topology" diagram — a single horizontal row with no zoom, no pan, and an unreliable scrollbar — with a full-page, interactive, map-style canvas for watching the live, multi-level agent population. The map auto-fits the running population on first load and arranges agents in a team-row layout whose columns represent delegation depth, so every delegation chain reads across the map from origin to outcome. A dedicated trigger column shows every person and schedule that set executions in motion, each connected by lines in its own colour, and both agents and trigger entities open dismissible detail cards beside themselves on the map. Schedule-triggered executions are always attributed to the human who created the schedule — never to the schedule itself — so accountability points to people. Hovering or clicking any entity focuses its complete upstream-and-downstream chain without unrelated noise leaking in through shared tool servers. The Communication Hub appears as a full-height fixture with its MCP servers and tool chips, and each agent's tool calls are drawn as routes through it. Agent detail bubbles show guardrail usage against limits with a link to the execution log, any node awaiting human intervention carries an alert, and a filter popover — including a recent-completed window — keeps the view tunable at all times. The map keeps itself current without operator action: it receives changes through a live server push channel (with automatic fallback to periodic polling), so executions starting, changing state, or finishing — and trigger or intervention changes — appear within a second or two of happening.

## Who Uses It

- **Platform Operators** — Watch live executions, delegations, tool calls, and intervention requests as they happen on a map that stays current on its own; scan the population, focus on a single chain, see who triggered each execution, jump from a person or schedule to the work it caused, and act (terminate, respond to intervention) quickly
- **AI Operations Leads** — Monitor execution health and tune limits; need delegation depth made visible in the layout, guardrail usage shown against limits, and tool-call routes through the hub to spot unhealthy patterns
- **Compliance / Audit Stakeholders** — Verify that every execution is attributable to a responsible person (including schedules being traceable to their human creator), that statuses and execution logs are reachable from the map, and that tool-call history is visible at a glance

## What It Does

- Presents the runtime view as **"Agent Runtime Monitor"** throughout the UI — no remaining user-facing "topology" naming for this live runtime view
- Renders a **live self-updating map** of the running agent population — execution trees, delegations, the Communication Hub, and MCP servers with their tools — that keeps itself current without the operator refreshing
- **Auto-fits the full population** on first load, however many agents are running, and supports zoom in/out, drag-to-pan, and fullscreen maximise
- Arranges agents in a **team-row layout** in which each column is a delegation depth, so every delegation chain reads across the map in order
- Shows a dedicated **trigger entity column** — every person and schedule that triggered executions — connected to their executions by lines in that entity's own colour
- **Attributes schedule-triggered executions to the human who created the schedule**, never to the schedule itself; when the schedule's creator is unknown, no creator is shown rather than a misleading placeholder
- Opens **dismissible detail cards beside each trigger entity** — person cards and schedule cards with execution lists, types, and statuses — with select-to-focus behaviour that navigates to the execution on the map
- Provides **whole-chain focus**: hovering or clicking any entity highlights everything upstream and downstream of it — and nothing else — excluding entities that merely share a tool server with the chain
- Shows the **Communication Hub as a full-height fixture** with its MCP servers attached and the tools they expose shown as chips; each agent's tool calls are drawn as routes from the agent, through the hub, to the MCP server that served the call, with the most recent call highlighted and earlier calls rendered in light grey
- Shows an **inline agent detail bubble** next to the selected agent — a terminate action, guardrail usage against the agent's limits, a link to the execution log, and the agent's trigger source — dismissible without leaving the map
- Marks **any node awaiting human intervention with an alert icon**, regardless of its state, opening the existing human-intervention dialog for response; sleeping agents not awaiting intervention remain hidden by default
- Provides a **filter popover** (status filters, agent-type filters, and a recent-completed window) alongside a legend, and keeps both usable even when a filter hides every entity — no "trapped" empty state
- Guarantees **canvas presentation** from the first moment: a grid-dot background covering the entire visible canvas, the map rendering properly even when empty, an initial auto-fit that fits large populations on first load, a loading indicator while the running population is being fetched, and the latest delegation an agent initiates displayed in the same way as its latest tool call

## Key Concepts

- **Agent Runtime Monitor**: The live, full-page, interactive map of the running agent population. The map occupies the main canvas area of the page; the model guardrail panel is removed from this page entirely.
- **Team-Row Layout with Delegation Depth Columns**: Agents are arranged in rows in which each column corresponds to a delegation depth, so delegation chains read across the map from origin to outcome. Placement is driven by delegation depth rather than by agent type.
- **Auto-Fit Canvas**: The map fits all visible entities on screen without scrolling. When many agents are present, the initial view on first load still fits the entire population — the initial fit is not prevented by the interactive zoom limits, which govern user zoom steps only.
- **Trigger Entity Column**: A dedicated column showing every person and schedule that triggered executions, each connected to its executions by lines in a colour unique to that entity.
- **Schedule Creator Attribution**: Wherever a schedule-triggered execution's trigger is displayed, the human who created the schedule is shown. The schedule name identifies the schedule entity only; schedules with no known creator display no attribution — never a placeholder.
- **Trigger Entity Detail Cards**: Dismissible cards opened beside a trigger entity. A person's card shows their name, the number of executions they triggered (directly and via schedules), and the list of those executions with types and statuses; a schedule's card shows the schedule name, its creator, and the executions it triggered. Selecting an execution in a card focuses and navigates to it on the map.
- **Whole-Chain Focus**: Hovering or clicking any entity highlights its complete upstream and downstream chain. The focus does not leak sideways: entities that merely share an MCP server or the hub with the chain are excluded unless they are genuinely upstream or downstream of it. Unrelated entities are visually de-emphasised while a focus is active.
- **Communication Hub Fixture**: The hub spans the full height of the map from the moment it loads, even when no agents are present yet, with its MCP servers attached and the tools they expose shown as chips. Each agent's tool calls are drawn as routes from the agent, through the hub, to the MCP server that served the call; the most recent call's route is highlighted, older calls render in a light barely-visible grey, and selecting an agent brightens all of its historical routes.
- **Agent Detail Bubble**: An inline, dismissible bubble beside a selected agent containing a terminate button, guardrail usage shown against the agent's limits, a link to the agent's execution log, and the agent's trigger source (attributed per the schedule-creator rule).
- **Intervention Alerts**: Any node awaiting human intervention — regardless of its state — is visible on the map by default and carries an alert icon that opens the existing human-intervention dialog.
- **Filter Popover with Recent-Completed Window**: Status and agent-type filters plus a recent-completed window that limits the view to executions completed within a recent time span, alongside a legend. When a filter combination hides every entity, the popover and legend remain visible and usable so the operator can always restore visibility without reloading the page.
- **Live Self-Updating Map**: The monitor receives changes through a server push channel rather than relying on fixed-interval polling, so executions starting, changing state, or finishing — and trigger or intervention changes — appear within about a second or two. If the push connection drops, the map automatically falls back to periodic polling so the view never silently goes stale, and returns to live push once the connection is restored.
- **Canvas Presentation Guarantees**: Presentation details that hold in every state — a grid-dot background covering the entire visible canvas (including when panning or zooming beyond drawn content and when the map is empty), a map that renders correctly when empty, an initial auto-fit of the whole population on first load, a loading indicator shown while the running population is being fetched, and the latest delegation shown in the same way as the latest tool call.

## Acceptance Criteria

### Naming & Page Composition
- The view is presented as **"Agent Runtime Monitor"** throughout the UI — no remaining user-facing "topology" naming for this live runtime view
- The page is primarily the agent map; the map occupies the main canvas area
- The model guardrail panel is removed from this page entirely — no guardrail panel, section, or tab remains on the Agent Runtime Monitor

### Map Layout & Interaction
- The map auto-fits its content so all visible entities are on screen without scrolling; when many agents are present, the initial view on first load still fits the entire population — the initial fit is not prevented by the interactive zoom limits
- Agents are arranged in a team-row layout in which each column corresponds to a delegation depth, so delegation chains read across the map in order
- The map supports zoom in and zoom out
- The map supports drag-to-pan to move around the canvas
- The map can be maximised to fullscreen and restored to the normal page layout
- The map's grid-dot background covers the entire visible canvas at all times — including when panning or zooming beyond the drawn content and when the map is empty
- A loading indicator is shown while the running agent population is being fetched, so a loading map is never mistaken for an empty platform
- The most recent delegation an agent initiates is displayed in the same way as its latest tool call, so the agent's current action — delegating or calling a tool — is visible at a glance

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

### Whole-Chain Focus
- Hovering or clicking any entity on the map focuses its complete chain: everything downstream of it and everything upstream of it
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

- Backend and data-serving design — the runtime map data (including schedule-creator provenance and upstream/downstream chain information) is a required input, and live delivery over a server push channel (with automatic polling fallback) is a required capability, but this feature does not specify how either is implemented
- New business entities for capturing schedule provenance — recording who created a schedule is an addition to the schedule itself, not a new business entity
- Changes to the unrelated Agent Plan Preview diagram used in agent-type configuration
- Re-adding or relocating the model guardrail panel anywhere else in the product
- Redesigning the terminate flow or the human-intervention dialog themselves (they are reused as-is)
- Editing agent configuration, delegations, or schedules directly from the map (read-only runtime monitor, apart from terminate and intervention response)
- Alert thresholds or notification triggers based on map state
- Mobile-specific responsive design (desktop-first for this feature)

## Dependencies & Constraints

- The monitor depends on reliable live runtime state, delegation (parent/child) relationship signals, execution statuses, and pending-human-intervention information for any node — reaching the map in near real time so each change is visible within about a second or two
- The monitor depends on a server push channel for change delivery, with periodic polling retained only as an automatic fallback when the push connection is unavailable
- The monitor depends on trigger provenance: each execution's trigger source — the user who started it directly, the delegating parent, or the schedule together with the human who created it. Executions triggered by schedules created before creator tracking must be representable without a creator (shown with no creator, never a placeholder)
- Whole-chain focus depends on accurate upstream and downstream chain data; relationships must come from real trigger and delegation chains, not from shared tool-server usage
- The map depends on tool-call routing data from the Communication Hub, including which MCP server served each call and the ordering of calls per agent
- The map reuses the existing terminate action, human-intervention dialog, and agent detail presentation
- Follows existing UI component and internationalisation conventions
- The view remains read-only with respect to agent configuration; permitted actions are terminate and human-intervention response only