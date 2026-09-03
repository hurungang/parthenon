# Agent Runtime Monitor — PRD

## Epic Overview

The runtime-control "agent topology" view is a static diagram that lays every running agent at the same delegation depth into a single horizontal row, with no zoom, no pan, and an unreliable scrollbar; agent details and model guardrails live in separate panels at the bottom of the page. For operators watching a live, multi-level agent population, this makes it hard to see delegation relationships, locate a specific agent, tell who triggered whom, trace what tools an agent is calling, or react to an agent that needs attention. This epic replaces the static topology with **Agent Runtime Monitor** — a full-page, interactive, map-style canvas that auto-fits and auto-distributes agents onto a grid, groups agents of the same type, connects parents to their children regardless of agent type, shows who triggered every agent, draws each agent's tool calls as routes through the Communication Hub to its MCP servers, surfaces sleeping agents awaiting human intervention by default, and shows agent detail (with terminate, guardrail summary, and trigger provenance) directly next to the selected agent.

## Business Goals

- **Rebrand the view clearly** — Retire the ambiguous "topology" name and establish "Agent Runtime Monitor" as the product term for the live runtime map
- **Make delegation relationships legible at a glance** — Parents and their delegated children appear side by side and are connected by a clear line regardless of agent type, so operators instantly understand who delegated to whom
- **Show who triggered every agent** — Each agent surfaces its trigger source (a user, a delegated parent, or a schedule), so operators can trace accountability at a glance
- **Trace tool calls through the Communication Hub** — Each agent's tool calls are drawn as routes through the Communication Hub to its MCP servers, with the latest call highlighted, so operators can see what each agent is currently doing
- **Reduce time to locate, act, and recover** — A zoomable, pannable map shows agent detail (terminate action, guardrail summary, and trigger provenance) beside the selected agent, surfaces sleeping agents awaiting intervention by default, and keeps filter/legend controls usable even when a filter hides every agent

## Users & Personas

- **Platform Operators** — Watch live agent executions, delegations, tool calls, and human-intervention requests; need to scan the full population, zoom to areas of interest, see who triggered each agent, and act (terminate, respond to intervention) quickly
- **AI Operations Leads** — Monitor running topology and tune limits; need a clear, legible picture of delegation depth, grouping by agent type, and tool-call routes through the Communication Hub to spot unhealthy patterns
- **Compliance / Audit Stakeholders** — Verify that running execution, trigger provenance (who triggered each agent), and tool-call history are visible and traceable at a glance

## User Stories

- As a platform operator, I want to open the Agent Runtime Monitor and see the full running agent population auto-fitted to the screen so that I do not have to scroll through a single crowded row
- As a platform operator, I want to zoom in and out and drag-to-pan across the map so that I can focus on a busy region or step back to the whole picture
- As a platform operator, I want agents of the same type grouped together in a clear container so that I can recognise related agents at a glance
- As a platform operator, I want an agent and its delegated child agents displayed next to each other and joined by a clear connecting line — even when they are different agent types or other agents are filtered out — so that I can see the delegation relationship immediately
- As a platform operator, I want selecting an agent to show a detail bubble beside it — including a terminate button, a guardrail summary, and who triggered the agent — so that I can inspect and act on an agent without leaving the map
- As a platform operator, I want every agent to show who triggered it — a user, its delegated parent, or a schedule — so that I can trace accountability without leaving the map
- As a platform operator, I want to see an agent's tool calls drawn as routes through the Communication Hub to its MCP servers, with the latest call highlighted, so that I can see what each agent is currently doing
- As a platform operator, I want the filter and legend controls to stay visible and usable even when a filter hides every agent so that I can always restore visibility and am never stranded on an empty map
- As a platform operator, I want sleeping agents that are waiting for human intervention to be visible by default with an alert icon so that I can notice and respond to blocked workflows
- As a platform operator, I want to maximise the map to fill the screen so that I can dedicate the whole page to monitoring during an incident

## Acceptance Criteria

### Renaming & Page Composition

- The view is presented as **"Agent Runtime Monitor"** throughout the UI (no remaining user-facing "topology" naming for this live runtime view)
- The page is primarily the agent map; the map occupies the main canvas area
- The model guardrail panel is removed from this page entirely — no guardrail panel, section, or tab remains on the Agent Runtime Monitor

### Map Interaction

- The map auto-fits its content so all visible agents are on screen without scrolling
- The map supports zoom in and zoom out
- The map supports drag-to-pan to move around the canvas
- The map can be maximised to fullscreen and restored to the normal page layout

### Layout & Grouping

- Agents are aligned to a grid rather than a single row
- Agents of the same type are grouped together in a visible virtual container
- Delegation adjacency takes precedence over type grouping: a delegated child is placed beside its parent (connected by a line) even when the two are different agent types, rather than being scattered into separate type groups
- All agents are automatically distributed and attempt to fit the screen ratio (no single-row overflow, no broken scrollbar)

### Delegation Relationships

- An agent and its delegated child agent(s) are displayed next to each other
- A clear connecting line visually shows the delegation relationship from parent to child
- Parent-to-child adjacency and the connecting line are preserved even when the parent and child are different agent types
- The connecting line between a parent and child remains visible when other agents are filtered out, so delegation is not lost when the operator narrows the view

### Agent Selection & Detail

- Selecting an agent shows its detail as a bubble next to the agent on the map
- The detail bubble reuses the existing agent detail component and includes a terminate button, a guardrail summary, and the agent's trigger source (who or what triggered it)
- The detail bubble is dismissible so the operator can return to the plain map view

### Human-Intervention Alerting

- A sleeping agent that is waiting for human intervention is shown on the map by default (not hidden)
- An alert icon appears on that agent's tile to indicate it needs attention
- Clicking the alert icon opens the existing human-intervention dialog so the operator can respond
- Agents that are asleep and not waiting for intervention remain hidden by default (they continue to be excluded to avoid dominating the map)

### Trigger Provenance

- Every agent shows who triggered it — a user, a delegated parent, or a schedule
- A delegated agent inherits the trigger user of its parent agent, and the map shows that parent-delegated trigger source
- A scheduled agent carries the schedule's "scheduled by" user, passed through when the schedule triggers, and the map shows the schedule name as the trigger source
- The trigger source is visible on the agent tile and/or in the detail bubble: user- or delegation-triggered agents show the triggering user's name, and schedule-triggered agents show the schedule name

### Tool-Call History (Communication Hub)

- The Communication Hub is shown as a visible component on the map
- Each tool call an agent makes is drawn as a route from the agent, through the Communication Hub, to the MCP server that served the call
- The most recent call's route is highlighted in a unique colour per agent, so the operator can see each agent's latest activity at a glance
- Older calls render in a light, barely-visible grey
- Selecting an agent brightens that agent's historical routes so all of its calls become visible

### Filter & Legend Recovery

- The map provides status and agent-type (kind) filters plus a legend, all accessible from a toolbar that stays on screen
- When a filter combination hides every agent, the filter and legend controls and the toolbar remain visible and usable, so the operator can clear or adjust the filter to restore visibility
- There is no "trapped" empty state: an operator can always recover the agent population without reloading the page

## Out of Scope

- Backend API design or implementation details — the enhanced runtime map data is a required input, but this epic does not specify how the data is served
- New database entities (the schedule "scheduled by" user is an added field, not a new entity; no other schema additions)
- Changes to the unrelated Agent Plan Preview "topology" diagram used in agent-type configuration
- Re-adding or relocating the model guardrail panel anywhere else in the product
- Redesigning the terminate flow or the human-intervention dialog themselves (they are reused as-is)
- Editing agent configuration, delegations, or schedules directly from the map (read-only runtime monitor, apart from terminate and intervention response)
- Alert thresholds or notification triggers based on map state
- Mobile-specific responsive design (desktop-first for this epic)

## Dependencies & Constraints

- The monitor depends on reliable live runtime state, delegation (parent/child) relationship signals, agent type grouping, status information — including whether a sleeping agent is waiting for human intervention — and trigger provenance (who or what triggered each agent)
- The runtime map data must expose pending-human-intervention information for sleeping agents; this is a product requirement, not an implementation detail, and does not require new database entities
- The map depends on trigger provenance data: each agent's trigger source (user, delegated parent, or schedule), which requires a "scheduled by" user to be recorded on schedules and passed through when a schedule triggers
- The map depends on tool-call routing data from the Communication Hub, including which MCP server served each call and the ordering of calls per agent
- The map reuses the existing agent detail component, terminate action, and human-intervention dialog
- Follows existing UI component and internationalisation conventions (documented in `docs/config.yaml`)
- The view remains read-only with respect to agent configuration; permitted actions are terminate and human-intervention response only
