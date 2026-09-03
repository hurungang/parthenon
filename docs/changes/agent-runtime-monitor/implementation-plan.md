# Implementation Plan: agent-runtime-monitor

## Overview

This plan turns the runtime-control "agent topology" view into the **Agent Runtime Monitor**: a full-page, interactive, map-style canvas with zoom/pan/auto-fit, grid-aligned grouping by agent type, delegation adjacency precedence over grouping, an inline detail bubble, default-visible alerting for sleeping agents awaiting human intervention, trigger provenance (user / delegated parent / schedule), and per-agent tool-call routes through the Communication Hub to MCP servers. It also enhances the backend topology API to expose per-node pending-intervention state, trigger provenance, and tool-call history, and records the schedule "scheduled by" user so schedule-triggered agents carry a trigger source.

## Task Checklist

### Phase 1 — Backend: pending-intervention contract
- [x] 1.1 — Resolve pending intervention state per node in `RuntimeTopologyController`
- [x] 1.2 — Extend projection dataclasses with pending-intervention fields
- [x] 1.3 — Update `RuntimeTopologyNodeRead` response schema
- [x] 1.4 — Serialize the new field in the topology endpoint handler
- [x] 1.5 — Update backend unit tests for the topology controller

### Phase 2 — Backend: trigger provenance (scheduling + delegation)
- [x] 2.1 — Add `ScheduledJob.scheduled_by_user_id` field + Alembic migration
- [x] 2.2 — Pass `scheduled_by_user_id` through `SchedulingEngine._dispatch` → `launch`
- [x] 2.3 — Stamp `triggered_by_user_id` on launched `AgentJob` via `GatewayLifecycleHandler.launch`
- [x] 2.4 — Delegation inheritance: child `AgentJob` inherits parent `triggered_by_user_id`
- [x] 2.5 — Backend unit tests for scheduler pass-through + delegation inheritance

### Phase 3 — Backend: topology controller provenance + tool-call history
- [x] 3.1 — Resolve per-node trigger provenance (user | delegated parent | schedule name)
- [x] 3.2 — Read tool-call history + derive per-node MCP server routes
- [x] 3.3 — Extend `RuntimeTopologyNodeRead` + add `ToolCallRouteRead` schema
- [x] 3.4 — Serialize provenance + tool-call routes in the endpoint handler
- [x] 3.5 — Backend unit tests for provenance + tool-call routes

### Phase 4 — Frontend data model & naming
- [x] 4.1 — Mirror new fields in frontend `RuntimeTopologyNode` type
- [x] 4.2 — Mirror trigger-provenance + tool-call-route types in frontend
- [x] 4.3 — Expose pending-intervention state and default visibility in `useRuntimeTopology`
- [x] 4.4 — Rebrand "topology" → "Agent Runtime Monitor" (i18n + page title)

### Phase 5 — Map canvas component
- [x] 5.1 — Create the map canvas component with zoom / pan / auto-fit
- [x] 5.2 — Implement grid layout, agent-type grouping, and auto-distribution
- [x] 5.3 — Render delegation connectors (parent → child)
- [x] 5.4 — Integrate the canvas into the page and remove the guardrail panel
- [x] 5.5 — Add fullscreen / maximize toggle
- [x] 5.6 — Rework delegation adjacency precedence over type grouping (cross-type)
- [x] 5.7 — Render Communication Hub node + per-agent tool-call routes

### Phase 6 — Agent detail bubble
- [x] 6.1 — Create the inline detail bubble component
- [x] 6.2 — Wire selection → bubble positioning and dismissal
- [x] 6.3 — Add trigger-provenance row to the detail bubble

### Phase 7 — Human-intervention alerting
- [x] 7.1 — Render alert icon on default-visible sleeping nodes awaiting intervention
- [x] 7.2 — Wire alert click → `InterveneResponseDialog`

### Phase 8 — Polish & test coverage
- [x] 8.1 — Add frontend unit tests
- [x] 8.2 — Handle empty / loading / error states and accessibility
- [x] 8.3 — Final review, i18n coverage, and cleanup
- [x] 8.4 — Add frontend tests for delegation adjacency, tool-call routes, provenance, empty-state recovery
- [x] 8.5 — Rework empty-state handling for filter/legend recovery (no trapped empty map)

### Phase 9 — Monitor live-data corrections
- [x] 9.1 — Topology edges derived from `AgentJob.parent_job_id` (union + dedupe with `AgentRunRelationship`), `depth_from_root` by walking parent chains
- [x] 9.2 — `AgentSessionService.enqueue`: delegated child `delegation_depth` = parent depth + 1 (verify inherited `triggered_by_user_id`)
- [x] 9.3 — Add `waiting_for_human` to topology default + non-terminal status lists
- [x] 9.4 — Conversation ↔ job linkage: attach jobs as children of conversation nodes via `input_data.__conv_session_id`
- [x] 9.5 — New `RuntimeToolCall` model (`runtime_tool_calls`) + Alembic migration
- [x] 9.6 — CC internal endpoint `POST /internal/data/tool-calls` + AR allowlist registration
- [x] 9.7 — AR records every tool execution (`record_tool_call` on the data client; executor task loop, raw conversation loop, LangChain wrapper, `human_intervene`)
- [x] 9.8 — Controller tool-call union (`RuntimeToolCall` + `ToolCallRecord`, drop `chat_status`, latest-first, cap 20)
- [x] 9.9 — Scheduling API writes `scheduled_by_user_id` on create/update
- [x] 9.10 — A2A enqueue resolves the chat user from the source conversation
- [x] 9.11 — Controller provenance: conversation nodes use their own user; delegated jobs keep inherited user
- [x] 9.12 — Frontend: alert icon + warning border for ANY node with `needs_intervention` (incl. `waiting_for_human` jobs)
- [x] 9.13 — Frontend elegance: "Triggered by …" on every tile, latest-tool badge, CH/MCP node styling polish, i18n keys
- [x] 9.14 — Compile/type verification (`compileall`, `tsc --noEmit`) and fixture alignment for the new job fields

### Phase 10 — Map layout: team rows, hub firewall, orthogonal tool routing
- [x] 10.1 — Replace the type-grouped grid with delegation-tree containers: one tree per container row, columns = delegation depth (root col 0, 1st-level delegation col 1, …), BFS depth with cycle guard, filtered-out parents promote children to roots, newest root first
- [x] 10.2 — Communication Hub as a vertical firewall bar spanning the full container-stack height at a fixed X right of the widest container (`INTER_REGION_GAP`), always visible
- [x] 10.3 — MCP column right of the hub: slugs used by visible agents + ONE synthetic "System Tools" node (never "unknown"); even vertical distribution along the hub height
- [x] 10.4 — Tool chips column right of each MCP: distinct bare tool names (`server____tool` → `tool`), stacked vertically centred on the MCP node
- [x] 10.5 — Orthogonal multi-segment tool routes: agent → column gutter → container bottom channel → hub left edge (horizontal run), hub right edge → MCP → tool chip; no diagonal hub join
- [x] 10.6 — Selection highlighting: selected agent's routes thickened/brightened (`data-highlighted`), involved MCP + tool nodes outlined in the agent colour, unrelated MCP/tool nodes dimmed
- [x] 10.7 — i18n key `runtimeMonitorSystemTools`; update canvas unit tests (team/row/deep-column semantics, System Tools instead of "unknown", hub/MCP/tool nodes, route highlighting)

---

## Phase 1 — Backend: pending-intervention contract

### 1.1 — Resolve pending intervention state per node in `RuntimeTopologyController`
Enhance `RuntimeTopologyController.get_active_topology()` in `backend/app/services/control_center/runtime_topology_controller.py` so that, after building the node set, it queries pending `InterveneRequest` rows (status `pending`) via the existing `InterveneRequestStore` data path, keyed by `agent_session_id` / `conversation_session_id`, and computes a boolean `needs_intervention` signal per node.

**Done when:** every node that has a pending `InterveneRequest` for its session resolves `needs_intervention=True`, all others `False`, with no new database entities and no schema migration.

### 1.2 — Extend projection dataclasses with pending-intervention fields
Add the pending-intervention attribute(s) to the `TopologyNode` dataclass (and carry it through `RuntimeTopologyProjection`) so the controller can attach the resolved signal to each node before returning.

**Done when:** `TopologyNode` exposes a `needs_intervention` field (default `False`) and `get_active_topology()` populates it for every returned node.

### 1.3 — Update `RuntimeTopologyNodeRead` response schema
Add the `needs_intervention` field to `RuntimeTopologyNodeRead` in `backend/app/schemas/agents.py` (Pydantic, strongly typed, default `False`). Do not change `RuntimeTopologyRead` or `RuntimeTopologyEdgeRead` beyond carrying the node field through.

**Done when:** `RuntimeTopologyNodeRead` includes a typed `needs_intervention: bool` field and the schema still imports/serializes cleanly.

### 1.4 — Serialize the new field in the topology endpoint handler
Update `get_runtime_topology` in `backend/app/api/v1/agents.py` (`GET /agents/runtime/topology`) to pass `node.needs_intervention` into each `RuntimeTopologyNodeRead` instance in the response mapping.

**Done when:** `GET /agents/runtime/topology` returns the `needs_intervention` value on each node, verified by an API-level smoke call.

### 1.5 — Update backend unit tests for the topology controller
Extend `backend/tests/unit/services/test_runtime_topology_controller.py` to cover the new signal: a node with a pending intervention request returns `needs_intervention=True`, a node without one returns `False`.

**Done when:** new unit tests pass and existing topology controller tests remain green.

---

## Phase 2 — Backend: trigger provenance (scheduling + delegation)

### 2.1 — Add `ScheduledJob.scheduled_by_user_id` field + Alembic migration
Add `scheduled_by_user_id` (uuid, nullable, FK → `identities.id`) to the `ScheduledJob` model in `backend/app/db/models/scheduling.py`. Generate the migration with `python -m alembic revision --autogenerate -m "add scheduled_by_user_id to scheduled_jobs"`, review it (nullable FK, no enum type changes, reversible `downgrade()`), and apply it with `python -m alembic upgrade head`.

**Done when:** `ScheduledJob` exposes `scheduled_by_user_id`, the migration is generated and applied (`alembic current` shows the new revision), and the field persists/reads cleanly.

### 2.2 — Pass `scheduled_by_user_id` through `SchedulingEngine._dispatch` → `launch`
Update `_dispatch` in `backend/app/services/scheduling/scheduler.py` so the agent-target branch calls `handler.launch(...)` with `user_id=job.scheduled_by_user_id` instead of `user_id=None`.

**Done when:** a schedule-triggered launch forwards the schedule's `scheduled_by_user_id` into `launch`, so the resulting `AgentJob` carries that user as its trigger source.

### 2.3 — Stamp `triggered_by_user_id` on launched `AgentJob` via `GatewayLifecycleHandler.launch`
Confirm/update `GatewayLifecycleHandler.launch` in `backend/app/services/gateway/lifecycle_handler.py` so the `user_id` it receives flows into `AgentSessionService.enqueue(...)` (which already stamps `triggered_by_user_id=user_id`). No signature change required beyond ensuring the value is forwarded.

**Done when:** `launch(..., user_id=<scheduled_by>)` produces an `AgentJob` with `triggered_by_user_id == <scheduled_by>`.

### 2.4 — Delegation inheritance: child `AgentJob` inherits parent `triggered_by_user_id`
In the delegation creation path — `AgentSessionService.enqueue` (`backend/app/services/agents/session_service.py`), called from the A2A data handler `backend/app/api/v1/internal/session_data.py` with `parent_job_id` set and `user_id=None` — resolve the parent `AgentJob` and copy its `triggered_by_user_id` onto the child when `user_id` is `None`.

**Done when:** a delegated child job's `triggered_by_user_id` equals its parent's, so the map shows a parent-delegated trigger source for delegated agents.

### 2.5 — Backend unit tests for scheduler pass-through + delegation inheritance
Add backend unit tests under `backend/tests/unit/services/` covering: (a) `_dispatch` passes `scheduled_by_user_id` through to `launch`, and (b) a delegated child created with `parent_job_id` inherits the parent's `triggered_by_user_id`.

**Done when:** new tests pass and existing scheduling/session tests remain green.

---

## Phase 3 — Backend: topology controller provenance + tool-call history

### 3.1 — Resolve per-node trigger provenance (user | delegated parent | schedule name)
In `RuntimeTopologyController.get_active_topology()` (`backend/app/services/control_center/runtime_topology_controller.py`), derive each node's trigger source: read `AgentJob.triggered_by_user_id` → `Identity.display_name` for user/delegated sources, detect `parent_job_id` for delegated children (which inherit the trigger), and resolve the schedule name for schedule-triggered jobs; attach `trigger_source` and a human-readable `trigger_source_label` to each `TopologyNode`.

**Done when:** every node carries `trigger_source` (`user` | `delegated_parent` | `schedule` | `unknown`) and a label (user display name or schedule name).

### 3.2 — Read tool-call history + derive per-node MCP server routes
Read tool-call history from `ToolCallRecord` via `ConversationTurn` → `ConversationSession` (and/or `AgentJob.conversation_history`); map each namespaced tool name via `parse_tool_name` (`server____tool`) to its `McpServer` (slug → name); attach an ordered (latest-first) per-node route list to `TopologyNode`.

**Done when:** each node carries ordered tool-call routes (tool name → MCP server slug/name/id) used by the frontend to draw agent → Communication Hub → MCP server routes.

### 3.3 — Extend `RuntimeTopologyNodeRead` + add `ToolCallRouteRead` schema
Add trigger-provenance fields (`trigger_source`, `trigger_source_label`) and a `tool_calls` list to `RuntimeTopologyNodeRead` in `backend/app/schemas/agents.py`; introduce a `ToolCallRouteRead` sub-schema (`tool_name`, `server_slug`, `server_name`, `server_id`, `created_at`).

**Done when:** `RuntimeTopologyNodeRead` serializes provenance and tool-call routes cleanly and the schema imports without error.

### 3.4 — Serialize provenance + tool-call routes in the endpoint handler
Update `get_runtime_topology` in `backend/app/api/v1/agents.py` to map each `TopologyNode`'s provenance fields and tool-call routes into `RuntimeTopologyNodeRead` (including the `ToolCallRouteRead` list).

**Done when:** `GET /agents/runtime/topology` returns trigger provenance + tool-call routes per node, verified by an API-level smoke call.

### 3.5 — Backend unit tests for provenance + tool-call routes
Extend `backend/tests/unit/services/test_runtime_topology_controller.py` to cover user / delegated / schedule provenance resolution and tool-call-route derivation (tool name → MCP server).

**Done when:** new tests pass and existing topology controller tests remain green.

---

## Phase 4 — Frontend data model & naming

### 4.1 — Mirror new fields in frontend `RuntimeTopologyNode` type
Add `needs_intervention: boolean` to the `RuntimeTopologyNode` interface in `frontend/src/types/index.ts` so the frontend type matches the backend response.

**Done when:** `RuntimeTopologyNode` mirrors the backend field and TypeScript compiles without type errors.

### 4.2 — Mirror trigger-provenance + tool-call-route types in frontend
Add `trigger_source`, `trigger_source_label`, and `tool_calls` (with a new `ToolCallRoute` interface) to `RuntimeTopologyNode` in `frontend/src/types/index.ts`.

**Done when:** frontend types mirror the backend provenance + tool-call fields and TypeScript compiles without type errors.

### 4.3 — Expose pending-intervention state and default visibility in `useRuntimeTopology`
Update `useRuntimeTopology` in `frontend/src/hooks/useRuntimeTopology.ts` to surface `needs_intervention` on each node and export an `isNodeVisibleByDefault` predicate: active (non-`sleep`) nodes are visible by default, plus any `sleep` node where `needs_intervention` is `true`; sleeping nodes not awaiting intervention remain hidden.

**Done when:** the hook returns nodes with `needs_intervention` and exports an `isNodeVisibleByDefault` predicate that includes "sleep + awaiting intervention" by default.

### 4.4 — Rebrand "topology" → "Agent Runtime Monitor" (i18n + page title)
Rename the page title and all user-facing "topology" strings for this live view to "Agent Runtime Monitor" in `frontend/src/i18n/locales/en.json` (all via `t()`), and update the page header/route labels in `RuntimeControlDashboardPage.tsx`.

**Done when:** no user-facing "topology" string remains for this live runtime view; all new/updated strings resolve through `t()`.

---

## Phase 5 — Map canvas component

### 5.1 — Create the map canvas component with zoom / pan / auto-fit
Create `AgentRuntimeMapCanvas` (new file under `frontend/src/components/agents/`) with viewport state for zoom level and pan offset, wheel/pinch zoom, drag-to-pan on empty canvas, and an auto-fit ("fit to screen") behavior on mount and resize.

**Done when:** the canvas zooms in/out, drags to pan, and auto-fits its content so all visible nodes are on screen without scroll.

### 5.2 — Implement grid layout, agent-type grouping, and auto-distribution
Implement the layout engine: align agent tiles to a grid (not a single row), group agents of the same agent type into a visible virtual container, and auto-distribute groups to fit the screen ratio with no single-row overflow or broken scrollbar.

**Done when:** same-type agents render inside a labelled container, arranged on a grid, and the whole population fits the screen ratio automatically.

> **Rework note:** the layout must give delegation adjacency precedence over type grouping (see 5.6) — a delegated child of a different type is placed beside its parent rather than scattered into its own type group.

### 5.3 — Render delegation connectors (parent → child)
Render a connecting line (with direction) from each parent node to its delegated child node(s), using `parent_session_id` from the topology data, positioned adjacent to their tiles.

**Done when:** parent → child delegation relationships are visually connected, and parents/children are laid out adjacent to each other.

> **Rework note:** connectors must persist across agent-type boundaries and remain visible when other (non-delegated) agents are filtered out (see 5.6).

### 5.4 — Integrate the canvas into the page and remove the guardrail panel
Replace the `RuntimeTopologyDiagram` usage in `RuntimeControlDashboardPage.tsx` with `AgentRuntimeMapCanvas`, and remove `VendorModelGuardrailPanel` from the page entirely.

**Done when:** the page renders the map canvas as the primary view and no guardrail panel, section, or tab remains on the page.

### 5.5 — Add fullscreen / maximize toggle
Add a maximize control that expands the map to fullscreen and restores it to the normal page layout, re-fitting the content on toggle.

**Done when:** the map can be maximized to fill the screen and restored, with content re-fit on each transition.

### 5.6 — Rework delegation adjacency precedence over type grouping (cross-type)
Adjust the layout engine so delegation adjacency takes precedence over agent-type grouping: a delegated child is placed beside its parent (and connected by a line) even when the two are different agent types, rather than being scattered into separate type groups; the parent-to-child connector remains visible when other agents are filtered out.

**Done when:** cross-type parent/child adjacency and the connecting line are preserved even with differing agent types and active filters.

### 5.7 — Render Communication Hub node + per-agent tool-call routes
Add a visible Communication Hub node to the canvas, and draw each agent's tool calls as routes agent → Communication Hub → MCP server (from the node's `tool_calls` list): the most recent call uses a per-agent colour, older calls render in light grey, and selecting an agent brightens that agent's historical routes.

**Done when:** tool-call routes render with latest-call per-agent colour, grey history, and selection brightening semantics, with the Communication Hub as a visible hop.

---

## Phase 6 — Agent detail bubble

### 6.1 — Create the inline detail bubble component
Create `AgentDetailBubble` (new file under `frontend/src/components/agents/`) that reuses the existing agent detail information, embeds the terminate action (via `NodeTerminationDialog`), and shows a guardrail summary, matching the prototype.

**Done when:** the bubble displays agent detail, a terminate button, and a guardrail summary using the existing detail/terminate data.

> **Rework note:** the bubble must additionally surface the agent's trigger source (see 6.3).

### 6.2 — Wire selection → bubble positioning and dismissal
On selecting a node, position the bubble adjacent to the selected tile (reflowing to stay on screen under zoom/pan), and support dismissal to return to the plain map.

**Done when:** selecting an agent opens the bubble next to it, the bubble tracks/positions correctly, and it is dismissible.

### 6.3 — Add trigger-provenance row to the detail bubble
Render the selected node's trigger source in `AgentDetailBubble` from the `trigger_source` / `trigger_source_label` fields: user- or delegation-triggered agents show the triggering user's name, and schedule-triggered agents show the schedule name.

**Done when:** the bubble shows who (or what) triggered the agent using the trigger-provenance fields.

---

## Phase 7 — Human-intervention alerting

### 7.1 — Render alert icon on default-visible sleeping nodes awaiting intervention
Render an alert indicator on the tile of every default-visible `sleep` node where `needs_intervention` is `True`, matching the prototype's alert styling.

**Done when:** sleeping agents awaiting intervention appear by default with a visible alert icon; sleeping agents not awaiting intervention remain hidden.

### 7.2 — Wire alert click → `InterveneResponseDialog`
Wire the alert-icon click to fetch the pending intervention request at click time via the new `getPendingInterventionForNode` helper (added to `frontend/src/api/interveneApi.ts`), then open the existing `InterveneResponseDialog` (unchanged) with that request.

**Done when:** clicking the alert icon resolves the node's pending request and opens the existing human-intervention dialog for that agent, reusing the current response flow.

---

## Phase 8 — Polish & test coverage

### 8.1 — Add frontend unit tests
Add new frontend tests under `frontend/src/__tests__/` (`AgentRuntimeMapCanvas.test.tsx`, `AgentDetailBubble.test.tsx`, `useRuntimeTopology.test.ts`) covering the map canvas (zoom/pan/auto-fit), agent-type grouping, delegation connectors, detail bubble, intervention alert visibility, and the renamed page; update `RuntimeControlDashboardPage.test.tsx` and repoint `ModelUsageGuardrailManagement.test.tsx` to render `VendorModelGuardrailPanel readonly` directly. `RuntimeTopologyPanel.test.tsx` and `TopologyDiagramRenderer.test.tsx` are left unchanged.

**Done when:** new tests pass and existing frontend tests for the page/diagram/terminate/intervene components remain green.

### 8.2 — Handle empty / loading / error states and accessibility
Add empty-state, loading, and error handling for the topology query, and ensure controls (zoom, pan, fullscreen, alert, bubble) are keyboard/ARIA accessible and all text is i18n-driven.

**Done when:** empty/loading/error states render cleanly, controls are accessible, and no hardcoded UI strings remain.

> **Rework note:** the empty state must distinguish "no agents at all" from "filters hid every agent", and keep the filter/legend toolbar usable in the latter case (see 8.5).

### 8.3 — Final review, i18n coverage, and cleanup
Delete the now-unused `RuntimeTopologyDiagram` component (the guardrail panel `VendorModelGuardrailPanel` is retained and only removed from this page), verify i18n coverage, and run the full frontend/backend test suites plus a syntax/type check.

**Done when:** dead code is removed, all tests pass, and the build/type-check completes without errors.

### 8.4 — Add frontend tests for delegation adjacency, tool-call routes, provenance, empty-state recovery
Add frontend tests covering the four refinements: cross-type delegation adjacency, Communication Hub tool-call routes (per-agent colour / grey history / selection brighten), the detail-bubble trigger-provenance row, and empty-state filter recovery (controls remain usable when a filter hides every agent).

**Done when:** new tests pass and existing frontend tests remain green.

### 8.5 — Rework empty-state handling for filter/legend recovery (no trapped empty map)
Rework the empty-state rendering so that, when a status/kind filter combination hides every agent, the filter/legend controls and toolbar remain visible and usable (distinct from the true "no agents" or loading/error states), allowing the operator to clear or adjust filters to restore visibility without reloading the page.

**Done when:** a fully-filtered map never traps the operator — the toolbar/filter/legend stay on screen and can always restore the population.

---

## Phase 9 — Monitor live-data corrections

Live-data defects verified against the running DB/logs: delegation edges were
empty (`agent_run_relationships` has 0 rows while `agent_jobs.parent_job_id`
is populated), `waiting_for_human` jobs were invisible, conversation turns
had no link to the jobs they spawned, real tool calls were never persisted,
and trigger provenance was NULL everywhere. Fixes below restore live data
flow through the Agent Runtime Monitor.

### 9.1 — Topology edges from `AgentJob.parent_job_id`
`RuntimeTopologyController.get_active_topology` now builds the delegation
edge set from `AgentJob.parent_job_id` for every included job, unions it
with any `AgentRunRelationship` rows (deduped by child, relationship rows
taking precedence), and computes `depth_from_root` by walking parent chains
(including non-active ancestors, fetched level by level with a 20-hop cap;
cycle-safe with memoisation).
**Done when:** delegated parent→child connectors render on the live map even
when `agent_run_relationships` is empty.

### 9.2 — `AgentSessionService.enqueue` delegation depth
Child jobs created with `parent_job_id` get `delegation_depth = parent.delegation_depth + 1`
(previously always 0); the existing `triggered_by_user_id` inheritance from
the parent is preserved and verified for the A2A path.
**Done when:** delegated children in the DB carry a non-zero depth and the
original triggering user.

### 9.3 — `waiting_for_human` visible in the topology
`get_runtime_topology` (`backend/app/api/v1/agents.py`) includes
`AgentJobStatus.waiting_for_human` in both the default and non-terminal
status lists (terminal statuses remain behind `include_terminal`).
**Done when:** jobs paused for human intervention appear on the monitor with
their pending-intervention alert.

### 9.4 — Conversation ↔ job linkage
The controller parses `input_data.__conv_session_id` (JSON-safe) from
included jobs and attaches them as children of the matching conversation
node (edges conv → job), so chat-spawned delegations form a connected tree.
**Done when:** conversation nodes on the monitor connect to the jobs they
triggered instead of floating disconnected.

### 9.5 — `RuntimeToolCall` model + migration
New model `RuntimeToolCall` (table `runtime_tool_calls`) in
`backend/app/db/models/tool_calls.py` (registered in
`app/db/models/__init__.py`): polymorphic `session_id` (agent job OR
conversation id, no FK, indexed), `session_kind`, `tool_name`, `route_type`,
`mcp_slug`, `status`, `duration_ms`, `error`, `created_at`. Migration
`a8344bd0b4ac` ("add runtime_tool_calls") generated, reviewed (additive
only), applied.
**Done when:** `alembic current` shows `a8344bd0b4ac (head)`.

### 9.6 — CC internal ingest endpoint
`POST /internal/data/tool-calls` in
`backend/app/api/v1/internal/session_data.py` (service-certificate auth)
accepts a single record or a batch (`records[]`), validated by
`RuntimeToolCallRecord`; the path is registered in the Agent Runtime
internal allowlist (`app/api/deps.py`).
**Done when:** Agent Runtime can persist tool executions through the data
API without any direct DB access.

### 9.7 — AR records every tool execution
`record_tool_call(...)` added to `ControlCenterDataClient`
(fire-and-forget — failures are logged and swallowed). Recording is wired
into: `_execute_mcp_tool_ar` (raw conversation loop; records
session_kind/route_type/mcp_slug/duration/error and resolves a working data
client even when the call site passes `data_client=None`),
`build_langchain_tools_for_ar_path` (generic CommHub tools + A2A delegation
tools via an optional `tool_call_recorder` callback), and
`LangChainHumanInterveneTool`. The executor passes recorders for task-agent
(`agent`) and conversation-turn (`conversation`) sessions.
**Done when:** MCP, system, and A2A tool calls from task agents AND chat
turns land in `runtime_tool_calls`.

### 9.8 — Controller tool-call union
Node `tool_calls` union `RuntimeToolCall` rows (by session_id) with the
legacy `ToolCallRecord` path, drop the `chat_status` pseudo-events, sort
most-recent-first, and cap at 20 entries per node.
**Done when:** the monitor renders real tool history per node without chat
noise.

### 9.9 — Scheduling API provenance
`create_schedule` / `update_schedule` (`backend/app/api/v1/scheduling.py`)
set `scheduled_by_user_id` from the requesting user's identity (the
`platform_user_id` claim, same pattern as the agent-launch endpoints).
**Done when:** schedule-triggered agents resolve their schedule + user
provenance instead of NULL.

### 9.10 — A2A enqueue trigger user
`prepare_a2a_request` resolves the source conversation
(`body.conv_session_id` → `ConversationSession.triggered_by_user_id`) and
passes it as `user_id` to `session_service.enqueue`, so chat-originated
delegations carry the chat user.
**Done when:** conversation-spawned jobs show the requesting human as the
trigger source.

### 9.11 — Controller provenance refinements
Conversation nodes resolve provenance from their own
`ConversationSession.triggered_by_user_id` (never marked "delegated" from a
backing job); delegated jobs prefer the inherited user with
`trigger_source='delegated'`; schedule-name resolution unchanged.
**Done when:** every node carries an accurate trigger source + label.

### 9.12 — Frontend alert coverage
`AgentRuntimeMapCanvas` shows the intervention alert icon and a warning
tile border/background for ANY node with `needs_intervention === true`
—including `waiting_for_human` agent jobs, not only sleeping conversations.
**Done when:** every intervention-awaiting node alerts by default.

### 9.13 — Frontend elegance pass
Every tile renders a "Triggered by …" line (label or typed source via
i18n); tiles with tool history show the latest call (`tool_calls[0]`) as a
compact badge with tooltip; Communication Hub and MCP server nodes restyled
to match agent-tile typography/iconography; zoom/pan/fit/fullscreen and
legend-filter behaviours unchanged; new strings via `t()` in `en.json`.
**Done when:** the map reads consistently with live trigger + tool data.

### 9.14 — Verification
Backend `python -m compileall app` clean; frontend `npx tsc --noEmit` clean
for production code (pre-existing `src/__tests__/*` errors unchanged); all
34 controller unit tests green after aligning the shared job fixture with
the newly consumed fields (`parent_job_id`, `input_data`, `delegation_depth`);
805 backend unit tests pass; monitor-related frontend suites (60 tests)
pass.
**Done when:** no compile/type errors and no test regressions.

---

## Phase 10 — Map layout: team rows, hub firewall, orthogonal tool routing

Direct user feedback on the live monitor: straight tool lines overlapped
tiles/lines; same-type agents were scattered into type groups; the
Communication Hub floated as a small box; system tool calls surfaced as an
"unknown" box; and selecting an agent did not make its full tool path
obvious. The layout engine in `AgentRuntimeMapCanvas.tsx` is replaced
(pure layout refactor — no API, hook, or terminate/intervene changes).

### 10.1 — Delegation-tree team containers
`layoutNodes` (type-grouped grid) is replaced by `layoutTrees`: trees are
built from the topology edges among VISIBLE nodes (parent → child); roots
are visible nodes with no visible parent edge (a filtered-out parent
promotes its child to a root), ordered by root `created_at` desc. Each tree
gets BFS depths (cycle-guarded via the depth map) and renders as ONE dashed
container occupying ONE row; containers stack vertically (`ROW_GAP`).
Container width = `(maxDepth+1)` columns; label = root's
`agent_type_name`; tile size/typography, trigger line, latest-tool badge,
status dot, and alert icon are unchanged. Tiles expose `data-container`
and `data-depth` for tests.
**Done when:** one container per delegation tree per row; root in column 0,
1st-level delegation in column 1, 3rd/4th level in columns 2/3, … .

### 10.2 — Communication Hub firewall
The hub is a vertical rounded bar (`HUB_W` × full container-stack height,
min `HUB_MIN_H`) placed at the widest container's right edge +
`INTER_REGION_GAP`, so every tool route can reach it with a clean
horizontal run; the label is rotated vertically inside the bar. It renders
always (even on a fully-filtered map).
**Done when:** the hub spans the top of the first container to the bottom
of the last and is never missing.

### 10.3 — MCP column (even distribution)
MCP keys are collected from visible agents' `tool_calls` via
`classifyMcpKey`: the reserved `system` slug (or an empty slug) collapses
into ONE synthetic "System Tools" node (i18n `runtimeMonitorSystemTools`);
the `unknown` fallback slug — the backend degrade path for unparseable
names, in practice A2A delegation calls, which are already shown as
delegation edges — is skipped entirely so an "unknown" node is never
rendered. (The topology API does not expose `route_type`, so the A2A skip
is approximated client-side by the slug.) Nodes are distributed evenly
along the hub height: `y_i = hubTop + hubHeight·(i+1)/(n+1)`, System Tools
first, then slugs alphabetically.
**Done when:** involved MCPs + one System Tools node sit on the hub's
right, evenly spaced, with no "unknown" node.

### 10.4 — Tool chips column
Per MCP, the distinct bare tool names used by visible agents (part after
`____`, full name as fallback) render as small chips stacked vertically and
vertically centred on their MCP node, `TOOL_GAP_X` to its right.
**Done when:** each MCP lists exactly the distinct tools agents used via it.

### 10.5 — Orthogonal multi-segment tool routes
Per tool call: (1) agent tile right edge → right into the tile-free gutter
at its column's right edge (`COLUMN_GAP`/2, clamped inside the container);
(2) down the gutter to the container's tile-free bottom channel
(`CONTAINER_BOTTOM_CHANNEL` reserved below the deepest tile row); (3)
horizontal along the channel Y out of the container and through the
`INTER_REGION_GAP` to the hub's left edge (never crosses other containers —
they occupy disjoint Y ranges); (4) hub right edge at the MCP's Y → MCP
left edge; (5) MCP right edge → orthogonal elbow → tool chip. Halves 1–3
and 4–5 join visually AT the hub (no diagonal). Delegation connectors
become clean gutters elbows (parent right → gutter → child left) with the
old bezier kept only for degenerate same-column edges. Styling keeps the
per-agent colour for the latest call, grey for older calls, and
brightening on selection, now with non-color cues (`data-highlighted`,
`data-dimmed`, thicker stroke, opacity steps).
**Done when:** no tool line crosses an agent tile; selecting an agent makes
the full path agent → hub → MCP → tool obvious (colour + thickness +
outlined MCP/tool nodes, unrelated ones dimmed).

### 10.6 — i18n + tests
New key `agents.sessions.runtimeMonitorSystemTools` ("System Tools") in
`en.json`. Canvas tests reworked: type-grouping test replaced by
team/row/deep-column semantics (one container per tree via
`team-container-<rootId>`, `data-depth` 0/1, unrelated same-type agents in
separate containers); new assertions for the System Tools node, the
"unknown"-never-rendered rule, tool chips, and the selection highlight
(`data-highlighted` on routes + involved MCP/tool nodes, `data-dimmed` on
unrelated ones). `npx tsc --noEmit` stays clean for production code; the
canvas suite (33 tests) and the related monitor suites pass.
**Done when:** all strings resolve via `t()` and the canvas test suite is
green.

---

## Phase 11 — Monitor refinements: recent terminal jobs, hub fixture, execution log, guardrail usage

### 11.1 — Recent terminal jobs in the live set (backend)
`get_active_topology` gains a `recent_minutes` window (default 30): jobs in a
terminal state (completed/failed/terminated) whose completion time —
`completed_at`, falling back to `created_at` (`AgentJob` has no `updated_at`
column, so the chain collapses) — is within the window join the live node set
alongside queued/running/waiting_for_human, ordered by `created_at desc` with
live statuses first and respecting the `max_nodes` budget. The existing
"terminal direct children of included jobs" logic then pulls their children
in. `GET /agents/runtime/topology` exposes
`recent_minutes: int = Query(30, ge=0, le=10080)` (0 = disabled) and passes it
through; `include_terminal` keeps its "all terminal, no window" meaning (the
recent window is skipped when terminal statuses are already included). Fixes
recently-finished trees being invisible on the live map (e.g. a completed
delegation root whose children recorded `supabase` tool calls in
`runtime_tool_calls` — recording worked, the live-set was the problem).
**Done when:** a just-finished session tree stays visible with its tool
routes; backend topology unit + integration suites pass.

### 11.2 — Communication Hub as a full-height stage fixture (frontend)
The world is at least stage-sized (`worldW = max(naturalWorldW,
viewportSize.width)`, `worldH = max(naturalWorldH, viewportSize.height)`); the
hub spans the full world height (`HUB_MIN_H` removed) and pins to
`max(containersRight + INTER_REGION_GAP, viewportSize.width - HUB_W - 24)`.
At fit-to-screen the hub is a full-height fixture on the right — including the
filter-driven empty state (overlay message + reset filters stay; MCP/tool
columns only render when tool data exists). Fit/zoom/pan verified (world ≥
stage, hub right edge always inside the stage).
**Done when:** the hub never shrinks or drifts left; canvas suite green
(ResizeObserver stubbed in tests so the mocked stage size feeds
`viewportSize`).

### 11.3 — Execution log link in the detail bubble (frontend)
Agent-kind nodes get an "Execution log" action
(`agents.sessions.runtimeMonitorExecutionLog`) that opens the existing
`AgentExecutionDetailsDialog` for `node.session_id` (rendered from the
bubble; MUI dialog portals; local open state). Conversations and instances
have no execution log and show no link.
**Done when:** the dialog opens for agent tiles only; bubble suite green.

### 11.4 — Guardrail usage in the detail bubble (frontend)
The guardrail box now shows USAGE vs LIMITS for the same four metrics as
`LogSummaryPanel` (tokens / iterations / delegated steps / delegation depth)
as compact `current / limit` rows with the same near (≥80%) / over colour
semantics (plus a non-colour `data-state` cue), reusing the
`agents.sessions.logViewer.summary.*` labels. Data sources: agent-kind reads
`AgentJob.output_data.guardrail_usage` via `GET /agents/sessions/{id}`
(react-query, lazily when the bubble mounts, staleTime 30s); conversation-kind
reads `ConversationSession.guardrail_usage` via the existing conversation
hook. Limits merge: the usage dict's own `max_*` first, then the agent-type
configuration. Missing usage renders "—"; null `output_data` is handled.
**Done when:** usage rows render for both node kinds; bubble suite green.

### Task Checklist

- [x] 11.1 — Backend: `recent_minutes` window in `get_active_topology` + `GET /agents/runtime/topology` param (0 disables; `include_terminal` unchanged)
- [x] 11.2 — Canvas: stage-sized world, full-height hub pinned right, `HUB_MIN_H` removed
- [x] 11.3 — Bubble: execution-log link (agent-kind only) opening `AgentExecutionDetailsDialog`
- [x] 11.4 — Bubble: guardrail usage vs limits (4 metrics, near/over colours, agent + conversation sources)
- [x] i18n key `agents.sessions.runtimeMonitorExecutionLog` added; all strings via `t()`
- [x] Tests updated (`AgentDetailBubble.test.tsx`, `AgentRuntimeMapCanvas.test.tsx`); both suites green
- [x] `npx tsc --noEmit` — no new production errors; `python -m compileall app` clean

---

## Phase 12 — MCP slug resolution, filter popover, recent window, precise highlights

### 12.1 — External MCP calls resolve to the right slug (backend)
Verified live: node tool_calls showed `('supabase__get_project', 'unknown')`.
Root cause: the AR recorder stored the SANITISED tool name (the OpenAI
sanitiser converts the canonical `server____tool` 4-underscore separator to
`__`), but `_resolve_mcp_slug` → `parse_tool_name` only splits the canonical
form → ValueError → "unknown". Two-sided fix:
- Controller fallback (read time — repairs EXISTING rows): when the canonical
  split fails, split the sanitised form on the FIRST `__`; empty parts
  degrade to `unknown`; bare legacy system names stay `system` (unchanged
  `parse_tool_name` contract — the fallback lives only in the controller).
- Recorder canonical name (new rows): `build_langchain_tools_for_ar_path`
  records the CANONICAL name (restored via `tool_name_map`, same mapping the
  CommHub dispatch uses) instead of the sanitised definition name; delegation
  tools record `agent____<slug>`.
**Done when:** `supabase__get_project` → `supabase` for stored rows; new
rows carry canonical names; controller unit tests cover both + the guards.

### 12.2 — A2A rows excluded from node tool calls (backend + schema)
`RuntimeToolCall` rows with `route_type='a2a'` are delegations, not tool
executions — the topology history query filters them out (`route_type !=
'a2a'`), so delegation calls never render as MCP routes. `ToolCallRoute`
(dataclass) and `ToolCallRouteRead` (schema) expose the additive
`route_type` field (nullable; `None` for legacy chat-sourced rows) so the
frontend can distinguish if needed.
**Done when:** the history query carries the a2a exclusion (statement-level
test) and `route_type` flows to the API response.

### 12.3 — Filter/legend popover redesign (frontend)
The bottom-centre collapsible legend bar is replaced by a floating circular
filter button at the RIGHT-BOTTOM corner (collapsed by default, primary
filled, `FilterList` icon) with a badge showing the count of ACTIVE
restrictions (hidden statuses + hidden kinds + recent-completed hidden).
Hover or click opens a compact panel (white surface, border, shadow,
rounded) anchored above-left containing the status chips, kind chips, and
the new recently-completed controls. Auto-fold: 1.2s after the pointer
leaves the button/panel area, immediately on click-outside (document-level
listener while open) and on Escape. ARIA: `aria-expanded`, focusable button,
keyboard toggle. All chips keep their toggle-to-filter behaviour (off-chips
dimmed).
**Done when:** collapsed by default, hover/click opens, click-outside /
Escape / pointer-leave fold; canvas suite covers each.

### 12.4 — "Recently completed" toggle + time window (frontend)
New panel row "Recently completed agents" (ON by default). When OFF,
recently-finished terminal nodes are hidden. Next to it a compact time
window: numeric input (clamped ≥ 1) + minutes/hours unit select, default
30 minutes ("Window" label). Wiring: `useRuntimeTopology(includeTerminal,
recentMinutes)` puts `recent_minutes` in the query key + URL; the PAGE owns
`recentEnabled` + `recentMinutes` state, passes `recentEnabled ?
recentMinutes : 0` into the hook, and passes both + callbacks down to the
canvas. Changing the window refetches (React Query key change) with the
page debouncing commits ~500ms to avoid refetch storms.
**Done when:** the hook test pins the URL/key per value (30 default, custom,
0 = disabled, change refetches); toggle + window controls render and clamp.

### 12.5 — Per-agent tool highlight precision (frontend)
Verified bug: selecting an agent that used ONE system tool highlighted ALL
chips under the System Tools node. The selection-highlight computation now
derives the exact set of `(mcp_slug, bare_tool_name)` pairs from the
selected node's `tool_calls` (bare = after `____`, else after the first
`__`, else the full name; `system` rows keep the synthetic System Tools
node). ONLY MCP nodes whose slug the agent actually called are outlined
(only the agent's used chips are highlighted — uninvolved chips stay dimmed
while an agent is selected), and route segments draw only for the agent's
actual calls (latest-call colour vs grey semantics unchanged). `route_type`
`a2a` rows are additionally excluded client-side from routes/highlights
(belt-and-braces with 12.2).
**Done when:** highlight test pins used-chips-only + dimmed-unused; A2A
rows produce no MCP node/chip/route.

### Task Checklist

- [x] 12.1 — Controller `_resolve_mcp_slug` sanitised-name fallback (first `__` split; empty → unknown; bare system names → system) + recorder writes canonical names (`tool_name_map` restore)
- [x] 12.2 — Backend excludes `route_type='a2a'` rows from `node.tool_calls`; `route_type` added to `ToolCallRoute`/`ToolCallRouteRead`/frontend `ToolCallRoute`
- [x] 12.3 — Canvas: floating right-bottom filter button (collapsed default, badge = active restriction count) + hover/click panel with auto-fold (1.2s pointer-leave, click-outside, Escape) + ARIA
- [x] 12.4 — "Recently completed agents" toggle (default ON) + numeric window input (clamp ≥ 1) + minutes/hours unit; `useRuntimeTopology(recentMinutes)` query key/URL; page owns debounced (500ms) state
- [x] 12.5 — Precise per-agent highlights: only used `(slug, bare tool)` pairs; uninvolved chips dimmed; A2A excluded client-side from routes/highlights
- [x] i18n keys `runtimeMonitorFilterButton`, `runtimeMonitorRecentToggle`, `runtimeMonitorWindowLabel`, `runtimeMonitorWindowUnitMinutes`, `runtimeMonitorWindowUnitHours` added; all strings via `t()`
- [x] Tests updated (`AgentRuntimeMapCanvas.test.tsx`, `useRuntimeTopology.test.ts`, `test_runtime_topology_controller.py`); suites green
- [x] `npx tsc --noEmit` — no new production errors; `python -m compileall app` clean

---

## Completion Checklist

- [x] Backend topology endpoint returns `needs_intervention` per node (no DB schema change)
- [x] Backend topology controller unit tests pass
- [x] Frontend types mirror the backend field
- [x] `useRuntimeTopology` drives default visibility of sleep + awaiting-intervention nodes
- [x] Page is rebranded "Agent Runtime Monitor" (all strings via `t()`)
- [x] Map canvas supports zoom in/out, drag-to-pan, and auto-fit
- [x] Grid layout groups agents by type in visible containers and fits screen ratio
- [x] Delegation connectors show parent → child adjacency
- [x] `VendorModelGuardrailPanel` is removed from the page
- [x] Fullscreen/maximize toggle works and re-fits content
- [x] Inline detail bubble shows detail + terminate + guardrail summary and is dismissible
- [x] Alert icon appears on sleeping agents awaiting intervention (visible by default)
- [x] Alert click opens `InterveneResponseDialog`
- [x] Empty/loading/error states and accessibility handled
- [x] Frontend and backend test suites pass; build/type-check clean
- [x] `ScheduledJob.scheduled_by_user_id` migration generated and applied
- [x] Scheduler passes `scheduled_by_user_id` through to `launch`
- [x] Delegated child `AgentJob` inherits parent `triggered_by_user_id`
- [x] Topology endpoint returns trigger provenance (source + label) per node
- [x] Topology endpoint returns tool-call routes (tool → MCP server) per node
- [x] Frontend types mirror trigger-provenance + tool-call-route fields
- [x] Canvas gives delegation adjacency precedence over type grouping (cross-type, survives filtering)
- [x] Communication Hub node + tool-call routes render (per-agent colour / grey history / selection brighten)
- [x] Detail bubble shows trigger provenance (user name or schedule name)
- [x] Empty-state filter/legend recovery (no trapped empty map)
- [x] Backend + frontend tests cover the new refinements
- [x] Map layout: one delegation-tree container per row (columns = delegation depth)
- [x] Communication Hub firewall bar + evenly distributed MCP nodes + tool chips
- [x] System Tools node instead of "unknown"; orthogonal multi-segment tool routes
- [x] Selection highlights the full agent → hub → MCP → tool path (colour + non-color cues)
