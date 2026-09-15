# Test Plan — Agent Runtime Monitor

## 1. Test Strategy

This change **does modify the database schema** (`has_db_changes: true`): `ScheduledJob` gains a nullable `scheduled_by_user_id` field. The DB-specific test-plan rules therefore apply in full (see "Pre-Test Checklist" and the real-backend E2E variant below). Testing spans **four backend/frontend capability groups** — (1) the pending-intervention signal, (2) trigger provenance with **creator-only attribution** (the schedule-name fallback for `trigger_user_label` is removed), (3) tool-call history via the Communication Hub, and (4) the **real-time live stream** (server-sent events with automatic polling fallback) — plus the **frontend map-canvas redesign** (including delegation legibility, **trigger-entity detail cards**, empty-state filter recovery, and the **canvas polish round**: whole-canvas grid-dot background, full-height hub fixture on load, and initial fit unblocked by the interactive zoom clamp), across three automated layers plus a short manual pass.

| Layer | Scope | Primary targets |
|-------|-------|-----------------|
| **Unit (backend)** | Controller/serialization logic + scheduling/dispatch logic + **projection hash/change-detection** | `RuntimeTopologyController`, `RuntimeTopologyNodeRead`, `SchedulingEngine._dispatch`, `GatewayLifecycleHandler.launch`, stream payload builder |
| **Unit (frontend)** | Component/hook behavior with mocked data | `AgentRuntimeMapCanvas`, `AgentDetailBubble`, `useRuntimeTopology` (+ stream hook), page composition |
| **Integration (API/DB)** | Endpoint contract + **schema-change verification** + **SSE stream endpoint** (auth, heartbeats, hash-gated emission, permission parity) | `get_runtime_topology` handler + `RuntimeTopologyRead`; the SSE topology-stream endpoint; `scheduled_jobs.scheduled_by_user_id` column properties |
| **E2E** | Full user flows on the live page, mock-first with **one real-backend variant for the schema change** | page rename, map interactions, delegation legibility, filter recovery, trigger provenance, trigger-entity detail cards, tool-call routes, alert → intervene, terminate, **mocked-stream live update (tile appears without polling)** |
| **Manual** | Visual/gesture verification impractical to assert in code | zoom/pan feel, auto-fit, fullscreen, grid/grouping legibility, per-agent route colouring, **grid-dot coverage while panning/zooming, full-height hub, first-load fit of a large population** |

**Key testing principles for this change:**
- **Contract correctness first**: `needs_intervention` must be `true` for a node with a pending `InterveneRequest` (status `pending`) and `false` otherwise, with `false` as the safe default for backwards compatibility.
- **Trigger provenance is a data-integrity chain, not just a label**: `ScheduledJob.scheduled_by_user_id` → `SchedulingEngine._dispatch` → `GatewayLifecycleHandler.launch` → `AgentJob.triggered_by_user_id` → (delegated child inherits) → `RuntimeTopologyController` resolves a human-readable trigger source. Each hop must be tested independently and end-to-end.
- **Attribution is human-centric (creator-only)**: for schedule-triggered nodes, `trigger_user_label` resolves to the schedule creator's identity name, or is `NULL` when the creator is unknown — the old schedule-name fallback is removed. The schedule name identifies the schedule entity only (its trigger-column tile and its own detail card); it must never appear in place of a person anywhere (tiles, bubbles, tooltips, cards).
- **Trigger-entity cards are filter-scoped**: a person/schedule card's execution list (and its count) contains only executions reachable under the currently active filter, and clicking a row selects that execution on the map.
- **Tool-call history is derived, not stored**: the topology endpoint must map namespaced tool names (`server____tool` via `parse_tool_name`) to MCP server slugs, preserving per-node ordering so the frontend can highlight the latest call.
- **Visibility predicate is the critical frontend rule**: a sleeping agent awaiting intervention is shown by default; a sleeping agent *not* awaiting intervention stays hidden.
- **Empty-state recovery is a hard requirement**: the filter/legend toolbar must remain usable when a filter combination hides every node, and "reset filters" must restore visibility without a page reload.
- **Removal is a feature**: verify `VendorModelGuardrailPanel` and the retired `RuntimeTopologyDiagram` no longer render on the page.
- **Reuse is verified, not re-implemented**: terminate and intervene flows are used as-is; tests confirm they still open/complete.
- **Push, don't poll — polling is only a safety net (new)**: the stream endpoint must authenticate the `EventSource` connection via the query-param token (no Authorization header is available to `EventSource`), emit the projection **only when it actually changed** (content hash comparison — identical payloads are not re-sent), keep the connection alive with heartbeats, and enforce the **same agent-read permission** as `GET /agents/runtime/topology`. On the frontend, stream payloads land in the query cache immediately (a new execution appears without any polling request), polling activates only while the stream is down, and the client returns to push on recovery.
- **Canvas presentation is contract, not decoration (new)**: grid dots must cover the *entire visible canvas* (empty map, and panning/zooming beyond drawn content), the Communication Hub must span the full canvas height from first load even with zero agents, and the initial fit of a large population on first load must not be clamped by the interactive min-zoom limit.

### Pre-Test Checklist (database change)

- **Verify the migration was applied**: `python -m alembic current` shows the new revision that adds `scheduled_by_user_id`; if not, run `python -m alembic upgrade head` before any test run.
- **Backend integration fixture must apply migrations**: the test database is brought to `head` in setup so the schema matches production.
- **Integration test verifies the new column**, not just service logic: assert `scheduled_jobs.scheduled_by_user_id` exists, is nullable, is a `uuid`, and has an FK to `identities`, via `information_schema`/constraint introspection.
- **Include at least one real-backend E2E variant** for the schema change (no `page.route()` mocks) to catch migration issues that mocked tests miss.

---

## 2. Coverage Areas

### Backend — pending-intervention resolution (`RuntimeTopologyController`)
- Per-node resolution of pending `InterveneRequest` rows keyed by session (agent vs conversation), attached to the projection without new entities.
- Correct default (`false`) when no pending request exists, and correct `true` when one does.
- The signal flows through the projection dataclass, the response schema, and the endpoint handler without being dropped or mis-typed.

### Backend — live-set completeness (live-data verification round)
- **Terminal direct children are included**: the topology also returns terminal (e.g. failed) direct children of included jobs so delegation edges render — budget-capped by `max_nodes` (children fetch consumes the remaining node budget; skipped when the budget is exhausted).
- **`waiting_for_human` is a live status**: the endpoint includes it in the default (live) and terminal status lists, and the controller's live-status set counts a HITL-paused job as engaged.
- **Conversation live drivers**: an open conversation computes runtime status `active` (not `sleep`) when either its backing job OR any chat-spawned linked job (`input_data.__conv_session_id`) is in a live state; a conversation → linked-job edge is emitted so the spawned run renders under the conversation.

### Backend — trigger provenance (new)
- **Migration/schema**: `ScheduledJob.scheduled_by_user_id` is added as a nullable `uuid` FK → `Identity`, with existing schedules retaining `NULL` and no data loss.
- **Schedule dispatch**: `SchedulingEngine._dispatch` passes `scheduled_by_user_id` into `GatewayLifecycleHandler.launch`, which stamps it onto the created `AgentJob.triggered_by_user_id`.
- **Delegation inheritance**: a delegated child `AgentJob` inherits `triggered_by_user_id` from its parent (via `parent_job_id`).
- **Resolution**: `RuntimeTopologyController` returns a trigger source per node — a user's display name (direct user trigger or inherited delegation), or the schedule **creator's identity name** for schedule-triggered nodes. When the creator is unknown (legacy `NULL` `scheduled_by_user_id`), `trigger_user_label` is `NULL` — the schedule-name fallback is removed.
- **Attribution invariant**: the schedule name never appears in place of a human name anywhere (agent tiles, detail bubbles, tooltips); it identifies only the schedule entity's tile in the trigger column and its own detail card.

### Backend — tool-call history via Communication Hub (new)
- Topology node carries a per-node tool-call history list (tool name + MCP server slug + timestamp, ordered).
- Tool calls are read from `ToolCallRecord` (via `ConversationTurn` → `ConversationSession`, and/or `AgentJob.conversation_history`).
- Namespaced tool names are split (`parse_tool_name`) and resolved to `McpServer` slugs so routes can be drawn agent → Communication Hub → MCP server.

### API contract — `GET /agents/runtime/topology`
- Response model `RuntimeTopologyRead` still serializes nodes/edges/roots; each node now includes `needs_intervention`, trigger-provenance fields (trigger source + label), and a tool-call route list.
- No route changes, no query-parameter changes, no removed fields (backwards-compatible additions).

### Backend — live topology stream (SSE) (new)
- **Query-param token auth**: the stream endpoint authenticates via the JWT passed as a query parameter (browser `EventSource` cannot set an `Authorization` header); a missing, expired, or invalid token is rejected before any event is sent (401/connection refused, never an open unauthenticated stream).
- **Permission parity**: the stream applies the **same agent-read permission** check as `GET /agents/runtime/topology` — a principal who cannot read the topology endpoint cannot open the stream, and a permitted principal gets the same population scope.
- **Hash-gated emission**: the endpoint computes a content hash of the projection and emits an SSE payload **only when the hash changes** — unchanged projections produce no data events (only heartbeats), so the client cache is not churned by identical state.
- **Heartbeats**: keepalive comment/ping events are sent on a fixed interval so proxies and browsers do not time out an idle-but-unchanged connection.
- **Payload contract**: each data event carries the same `RuntimeTopologyRead` shape as the REST endpoint (same serializer, no field drift), plus whatever change-type metadata the frontend needs (or none — full-projection replacement is acceptable and simpler to test).
- **Lifecycle**: the stream terminates cleanly on client disconnect (no leaked generator/tasks, no further DB polling for that client).

### Frontend — real-time stream consumption (new)
- **Immediate cache push**: the stream hook routes each incoming projection into the shared query cache synchronously — a newly started execution appears on the map without any polling request or manual refetch, and state/intervention changes land with the same immediacy (PRD: within about a second or two).
- **Fallback on stream error**: when the stream connection errors or drops, the hook automatically falls back to periodic polling (the existing topology query) so the view never silently goes stale.
- **Recovery to push**: when the stream reconnects, polling stops and live push resumes; the first payload after recovery replaces/resyncs the cache so no state gap remains from the polling period.
- **Connection state surfacing**: the hook exposes the active transport (push vs polling) so tests (and the UI, if desired) can assert which mode is live at any moment.
- **Cleanup**: closing/unmounting the monitor (or page hide, if implemented) closes the `EventSource` and stops the fallback poller — no orphan connections or timers.

### Frontend data model & naming
- `RuntimeTopologyNode` type mirrors `needs_intervention`, trigger provenance, and tool-call history; `AgentJobStatus` already carries `waiting_for_human`.
- All user-facing "topology" strings for this live view replaced by "Agent Runtime Monitor" via `t()`.

### Map canvas (`AgentRuntimeMapCanvas`)
- Zoom in/out, drag-to-pan, and auto-fit on mount/resize.
- Grid-aligned layout (not single row) with same-type grouping into visible containers.
- Delegation connectors render parent → child adjacency from `parent_session_id`.
- **Delegation legibility (new)**: cross-type parent/child adjacency and connector persistence when *other* nodes are filtered out; a delegated child is promoted to a root when its parent is filtered out (so it never disappears with its parent).
- **Empty-state filter recovery (new)**: status/kind filters + legend stay visible and usable when a filter hides every node; "reset filters" restores the population without reload.
- **Tool-call routes (new)**: the Communication Hub is rendered as a visible node; per-agent routes are drawn agent → Communication Hub → MCP server, with the latest call highlighted in a per-agent colour, older calls in light grey, and history brightened on selection.
- Fullscreen/maximize toggle and restore, re-fitting content on transition.
- **Canvas polish (new)**: the grid-dot background paints the *entire visible canvas* — including the empty state and whenever panning/zooming moves the viewport beyond the drawn content (no blank/white regions at the edges); the Communication Hub fixture spans the full canvas height from the moment the map loads, even with zero agents; the initial view on first load fits a large population entirely on screen — the initial fit scale is not blocked by the interactive min-zoom clamp (the clamp governs user zoom steps, not the initial auto-fit).

### Agent detail bubble (`AgentDetailBubble`)
- Inline bubble beside the selected node: detail + terminate + guardrail summary; dismissible.
- **Trigger provenance (new, creator-only)**: the bubble shows the human who triggered the agent — the triggering user, the inherited delegation source, or the schedule **creator** for schedule-triggered runs. Never the schedule name as a person; when the creator is unknown, no person/trigger line renders (no placeholder).

### Trigger entity detail cards (`AgentRuntimeMapCanvas`) (new)
- Clicking a person or schedule entity tile in the trigger column opens a dismissible detail card beside it; clicking the entity again (or dismissing) closes it — same dismissal pattern as the agent detail bubble.
- **Person card**: the person's name, the count of executions they triggered (directly and via schedules), and the execution list with each row's type and status; clicking a row selects (focuses and navigates to) that execution on the map.
- **Schedule card**: the schedule name, the executions it triggered with their statuses, and a creator caption rendered **only when a creator exists** (null-creator legacy schedules show no caption and no placeholder).
- **Filter scoping**: each card's execution list and count include only executions reachable under the currently active status/kind filter and recent-completed window.

### Human-intervention alerting
- Default visibility of sleep + `needs_intervention` nodes; **alert icon on ANY node flagged `needs_intervention`** — including agent jobs paused in `waiting_for_human`, not just sleeping conversations.
- Agent tiles also render the trigger-source line and (when calls exist) the latest-tool-call line.
- Alert click opens the existing `InterveneResponseDialog` for that session.

### Page composition (`RuntimeControlDashboardPage`)
- Map is the primary canvas; guardrail panel absent; empty/loading/error states handled; accessibility.

---

## 3. Critical Scenarios

> WHEN/THEN format only — implementation lives in the test files, not here.

### Backend — live-set completeness (live-data verification round)
- **WHEN** an included job has a terminal direct child (e.g. failed delegated attempt) **THEN** the child appears in the projection with its own status and the parent → child delegation edge is present (child depth = parent depth + 1, child not a root).
- **WHEN** the active set approaches `max_nodes` **THEN** the terminal-children fetch is capped by the remaining budget (no fetch when the budget is exhausted).
- **WHEN** a job is paused in `waiting_for_human` **THEN** it is visible in the default live topology with status `waiting_for_human`, and a conversation it drives computes runtime status `active` (not `sleep`).
- **WHEN** a chat-spawned job linked via `input_data.__conv_session_id` is live **THEN** its source conversation computes `active` and an edge conversation → job is returned; **WHEN** the only linked job is terminal **THEN** the conversation stays `sleep`.

### Backend — pending-intervention contract
- **WHEN** a node's session has a pending `InterveneRequest` (status `pending`) **THEN** that node's `needs_intervention` is `true`.
- **WHEN** a node's session has no pending intervention request **THEN** `needs_intervention` is `false`.
- **WHEN** an intervention request is in a non-pending status (responded/cancelled/expired) **THEN** the node is **not** flagged as needing intervention.
- **WHEN** `GET /agents/runtime/topology` is called **THEN** every node in `RuntimeTopologyRead.nodes` carries a boolean `needs_intervention` and existing fields (session_id, status, kind, title, parent_session_id, etc.) are unchanged.

### Backend — trigger provenance schema & dispatch
- **WHEN** the migration is applied **THEN** the `scheduled_jobs.scheduled_by_user_id` column exists, is nullable, is a `uuid`, and carries an FK to `identities`.
- **WHEN** the migration is applied **THEN** pre-existing `ScheduledJob` rows retain `NULL` in `scheduled_by_user_id` (no backfill errors, no data loss).
- **WHEN** a schedule with a `scheduled_by_user_id` fires **THEN** the launched `AgentJob.triggered_by_user_id` equals the schedule's `scheduled_by_user_id`.
- **WHEN** a schedule has no `scheduled_by_user_id` (legacy/NULL) **THEN** the launched `AgentJob` keeps `triggered_by_user_id` NULL and the topology node does not crash resolving provenance — it resolves with `trigger_user_label` NULL (no schedule-name fallback).
- **WHEN** an agent delegates to a child agent **THEN** the child `AgentJob.triggered_by_user_id` equals its parent's `triggered_by_user_id`.
- **WHEN** a node was directly user-triggered **THEN** the topology node returns that user's display name as the trigger label.
- **WHEN** a node was schedule-triggered and the schedule has a known creator **THEN** `trigger_user_label` is the creator's **identity name** — never the schedule name.
- **WHEN** a node was schedule-triggered and the schedule creator is unknown (legacy `NULL`) **THEN** `trigger_user_label` is `NULL`/absent — no schedule-name fallback and no placeholder string.
- **WHEN** a node was delegated **THEN** the topology node returns the parent's trigger label (the original user's display name).

### Backend — tool-call history
- **WHEN** an agent has recorded tool calls **THEN** the topology node returns a per-node tool-call list with, per call: tool name, MCP server slug, and timestamp, in chronological order.
- **WHEN** a namespaced tool name `server____tool` is resolved **THEN** the tool-call entry carries the tool name (`tool`) and the MCP slug (`server`).
- **WHEN** a tool-call references an MCP slug with no matching `McpServer` **THEN** the entry still returns (slug preserved, no server dropped) and the frontend renders a graceful route.
- **WHEN** an agent has made no tool calls **THEN** the node returns an empty tool-call list (no error, no phantom route).

### Backend — live topology stream (SSE) (new)
- **WHEN** a client opens the stream endpoint with a **valid** JWT passed as a query parameter **THEN** the connection is accepted (200, `text/event-stream`) and an initial projection payload is emitted.
- **WHEN** a client opens the stream endpoint with a **missing, expired, or invalid** query-param token **THEN** the connection is rejected before any event is emitted (auth error / 401) — never an open unauthenticated stream and never a 200 followed by an error event.
- **WHEN** a principal **lacks** the agent-read permission required by `GET /agents/runtime/topology` **THEN** the stream endpoint rejects them with the same failure mode (permission parity — the stream is not a permission bypass).
- **WHEN** a permitted principal with restricted scope opens the stream **THEN** the streamed population matches what the REST endpoint would return for the same principal (same filtering, same fields).
- **WHEN** the projection is unchanged between change-detection passes **THEN** no data event is emitted (the hash is equal) — only the keepalive heartbeat flows.
- **WHEN** the projection changes (execution starts/changes state/finishes, trigger or intervention state changes) **THEN** a data event carrying the updated projection is emitted promptly (the hash differs → emit).
- **WHEN** a heartbeat interval elapses with no projection change **THEN** a heartbeat/keepalive event is sent on the stream so proxies and browsers do not time out the connection.
- **WHEN** two consecutive projections have identical content but different object identity **THEN** the hash comparison treats them as equal (hash is content-derived, not reference/serialisation-order sensitive beyond canonicalisation).
- **WHEN** the client disconnects **THEN** the server-side generator/task for that subscriber is cancelled and cleaned up (no leaked connections, no continued DB polling for the disconnected client).
- **WHEN** a data event is emitted **THEN** its payload deserialises to the same `RuntimeTopologyRead` shape as the REST endpoint (no field drift between push and pull paths).

### Frontend — real-time stream consumption (new)
- **WHEN** a stream payload arrives **THEN** the hook writes it into the shared query cache immediately — a newly started execution renders on the map with **no** polling request and **no** manual refetch (assert: no additional `GET /agents/runtime/topology` call is made).
- **WHEN** an execution changes state or finishes, or trigger/intervention state changes **THEN** the map reflects the change from the pushed payload with push immediacy (no poll-cycle wait).
- **WHEN** the stream errors or the connection drops **THEN** the hook activates periodic polling automatically so the view continues to receive updates (fallback within the poll interval, never silently stale).
- **WHEN** the stream reconnects after a failure **THEN** polling stops, push resumes, and the first post-recovery payload resyncs the cache (no state gap from the polling window).
- **WHEN** the stream is healthy **THEN** polling remains inactive (no redundant requests while push is live).
- **WHEN** the monitor unmounts (or the connection is otherwise torn down) **THEN** the `EventSource` is closed and the fallback poller is stopped — no orphan connections or timers remain.

### Canvas presentation polish (new)
- **WHEN** the map is empty (zero agents) **THEN** grid dots cover the entire visible canvas (no blank region inside the viewport).
- **WHEN** the operator pans the viewport beyond the drawn content (or zooms out past the content bounds) **THEN** grid dots still cover every visible pixel — no white/unpainted margins appear at any edge.
- **WHEN** the map loads with zero agents **THEN** the Communication Hub fixture spans the full canvas height from the first render (not sized to content, not collapsed).
- **WHEN** the map first loads with a large population (more agents than fit at the interactive min-zoom scale) **THEN** the initial view still fits the entire population on screen — the initial auto-fit scale is not clamped by the interactive min-zoom limit (clamping applies only to subsequent user zoom steps).
- **WHEN** the operator zooms out after the initial fit **THEN** the interactive min-zoom clamp engages from that point (the clamp still works as a user-facing limit; only the initial fit bypasses it).

### Frontend — visibility predicate
- **WHEN** a node is a conversation/instance with runtime status `sleep` and `needs_intervention` is `true` **THEN** it is rendered by default with an alert icon.
- **WHEN** a node is `sleep` and `needs_intervention` is `false` **THEN** it remains hidden by default (excluded from the map).
- **WHEN** a node is active (running/queued) **THEN** it is rendered regardless of `needs_intervention`.

### Frontend — trigger provenance display (creator-only)
- **WHEN** a node is user- or delegation-triggered **THEN** the agent tile and the detail bubble show the triggering user's name.
- **WHEN** a node is schedule-triggered with a known creator **THEN** the agent tile and the detail bubble show the creator's human name — never the schedule name in place of a person.
- **WHEN** a node is schedule-triggered with an unknown creator **THEN** no person/trigger line is rendered (no placeholder), and the schedule name does not appear as the trigger.

### Trigger entity detail cards (new)
- **WHEN** a person entity in the trigger column is clicked **THEN** a detail card opens beside it showing the person's name, the count of executions they triggered (direct + via schedules), and the execution list with each row's type and status.
- **WHEN** the same entity is clicked again — or the card is dismissed **THEN** the card closes and the plain map view is restored.
- **WHEN** a schedule entity is clicked **THEN** its card shows the schedule name, its executions with statuses, and the creator caption **only when a creator exists**.
- **WHEN** a schedule has a null/unknown creator **THEN** no creator caption appears anywhere on its card (no placeholder or generic label).
- **WHEN** an execution row is clicked in either card **THEN** that execution becomes selected on the map — focused and navigated to.
- **WHEN** a status/kind filter or recent-completed window is active **THEN** each card's execution list (and its count) contains only executions reachable in the current filter.
- **WHEN** no executions are reachable under the active filter **THEN** the card renders an empty list without error.

### Map interaction
- **WHEN** the monitor opens with many nodes **THEN** all visible agents are on screen without scrolling (auto-fit).
- **WHEN** the operator zooms in/out **THEN** the canvas scale changes and content remains anchored under the cursor/center.
- **WHEN** the operator drags the empty canvas **THEN** the viewport pans.
- **WHEN** the maximize control is toggled **THEN** the map expands to fullscreen and restores to the normal layout, re-fitting content each time.

### Layout & grouping
- **WHEN** multiple agents share the same agent type **THEN** they render inside one labelled virtual container, aligned to a grid.
- **WHEN** a parent agent has delegated child agents **THEN** parent and children are laid out adjacent and joined by a visible connector line.

### Delegation legibility (new)
- **WHEN** a parent and its delegated child are **different agent types** **THEN** they remain adjacent and joined by a connector line (delegation adjacency overrides type grouping).
- **WHEN** a filter hides nodes that are **not** part of a parent/child pair **THEN** the parent→child connector line remains visible (delegation is not lost).
- **WHEN** a parent is filtered out **THEN** its delegated child is promoted to a root (still rendered, not orphaned/hidden with the parent).

### Empty-state filter recovery (new)
- **WHEN** a filter combination hides every node **THEN** the legend and status/kind filter controls and the toolbar remain visible and usable.
- **WHEN** the operator activates "reset filters" on an empty map **THEN** the full agent population is restored without a page reload.

### Tool-call route rendering (new)
- **WHEN** the map renders **THEN** the Communication Hub is shown as a visible node.
- **WHEN** an agent has tool calls **THEN** each call is drawn as a route from the agent, through the Communication Hub, to the MCP server that served it.
- **WHEN** an agent has multiple tool calls **THEN** the latest call's route is highlighted in a unique colour per agent and older calls render in light grey.
- **WHEN** an agent is selected **THEN** that agent's historical routes are brightened so all its calls become visible.

### Selection & detail
- **WHEN** a node is selected **THEN** a detail bubble appears beside it showing agent detail, a terminate action, a guardrail summary, and the trigger source.
- **WHEN** the terminate action is used **THEN** the existing termination flow completes and the topology reflects the result.
- **WHEN** the bubble is dismissed **THEN** the plain map view is restored.

### Human-intervention alert
- **WHEN** the alert icon is clicked on a sleeping agent awaiting intervention **THEN** the existing `InterveneResponseDialog` opens for that agent's session, and the response flow completes without change.

### Page composition
- **WHEN** the Agent Runtime Monitor page is rendered **THEN** no guardrail panel/section/tab is present and the map canvas is the primary view.
- **WHEN** the page is rendered **THEN** no user-facing "topology" label remains for this live runtime view (all strings resolve to "Agent Runtime Monitor").

---

## 4. Edge Cases & Risks

- **Backwards-compatibility of new fields** — clients/consumers that predate `needs_intervention`, trigger provenance, and tool-call history must not break; all additions must have safe defaults (`false`, `null`/empty list) and the schema must remain additive. Verify existing tests and older mocks that omit the fields still serialize/parse.
- **Sleep-node status ambiguity** — `kind` values (`agent`/`conversation`/`instance`) carry different status semantics; the "sleep + awaiting intervention" rule must apply only to the correct kind(s). Ensure the predicate does not resurrect completed/failed/terminated nodes.
- **Multi-request / multi-session mapping** — a session with multiple intervention requests (or a request keyed by a different session field) must not produce false positives/negatives; the join key (`agent_session_id` vs `conversation_session_id`) must be tested for both agent-kind and conversation-kind nodes.
- **Race / stale topology** — an intervention request answered between topology poll and render should not leave a phantom alert; confirm the dialog and refetch behave consistently.
- **Empty topology** — zero nodes/edges must render a clean empty state (no crash, no broken auto-fit math).
- **Large / deeply-nested populations** — auto-fit and grouping must not overflow into a single row or reintroduce a broken scrollbar; pan/zoom must remain usable at high node counts.
- **Zoom/pan vs selection** — clicking a node must not be swallowed by drag-to-pan; dragging on a node must not accidentally open the detail bubble.
- **Fullscreen re-fit & cleanup** — toggling fullscreen repeatedly must re-fit content and not leak portal/DOM state; dismissing on exit must not strand the bubble.
- **Migration safety** — `scheduled_by_user_id` is nullable and additive: verify existing `ScheduledJob` rows load with `NULL`, the FK is created without breaking legacy rows, and `alembic upgrade head` is reversible (`downgrade()` drops the column cleanly). Enum-type handling (if any) must avoid duplicate-type errors.
- **Schedule dispatch provenance gaps** — a schedule with `NULL` `scheduled_by_user_id`, or a schedule whose owning identity was deleted, must not crash launch or topology resolution; the trigger label must degrade to `NULL` — the schedule-name fallback has been **removed**, so no fallback string and no placeholder may render anywhere (schedule card, agent tile, detail bubble, tooltips).
- **Schedule name never renders as a person** — regression guard: agent tiles, detail bubbles, and tooltips must never fall back to the schedule name for schedule-triggered runs, with or without a creator; only the schedule entity's tile/card carry the schedule name. Mock payloads that predate the creator-only fix (labels set to schedule names) must be updated or explicitly asserted against.
- **Trigger-card list vs filter interplay** — a card's execution list and count must stay consistent with the active filter; changing the filter while a card is open must refresh the list (no stale rows, no count/list mismatch); clicking a row must never target an execution hidden by the filter (rows are scoped to reachable executions).
- **Trigger-card dismissal state** — opening person/schedule cards and the agent bubble in sequence must not strand multiple cards; dismissal and re-open survive zoom/pan/fullscreen transitions the same way the agent bubble does.
- **Delegation chain depth** — a multi-level delegation chain must propagate the original trigger user all the way down (child of child), not just one level; a missing/loop parent must not cause infinite recursion.
- **Delegation vs filter interplay** — filtering out a parent must promote the child to a root; filtering out a child must not hide the parent; filtering both must keep the empty-state toolbar usable.
- **Tool-call ordering & latest-call highlighting** — ordering must be timestamp-stable (no ties flipping the highlighted call); an agent with a single call has that call as "latest"; an agent with zero calls draws no route and no phantom latest-call highlight.
- **MCP slug resolution** — a tool name without a `server____` namespace, an unknown slug, or a slug whose `McpServer` is inactive/deleted must not drop the call or crash the route renderer; the route should still terminate at the hub with a degraded label.
- **i18n completeness** — any hardcoded "topology", trigger-source, or new label bypassing `t()` is a defect; verify no user-facing string is hardcoded.
- **Accessibility** — zoom/pan/fullscreen/alert/dismiss/filter controls must be keyboard- and ARIA-reachable; alert state and latest-call highlighting must be conveyed beyond colour/icon alone (the per-agent colour and grey-vs-bright distinction need a non-colour cue).
- **Multiple tabs / concurrent streams (new)** — the same operator opening the monitor in several tabs (or several subscribers on one backend instance) must each get an independent stream with correct events; the backend must not collapse, corrupt, or cross-deliver between subscribers, and a burst of concurrent connections must not exhaust connection/DB-polling resources (subscriber registry is per-connection and cleaned up on disconnect).
- **Stream reconnect storms (new)** — a flapping network (or backend restart) can cause rapid error→retry→error loops: the client must back off reconnect attempts (jittered, bounded) instead of hammering the endpoint, must not stack multiple pollers or `EventSource`s from overlapping retries, and the server must survive a wave of simultaneous reconnects without dropping permitted subscribers it can serve. Auth failures must **not** trigger endless reconnects (a rejected token is terminal, not retryable, at the transport level).
- **Hash-comparison cost (new)** — computing the projection hash requires serialising the full projection every change-detection pass; with a large population this must stay cheap enough not to starve the endpoint or the DB (canonical serialisation, no per-subscriber duplicate computation where a shared projection is feasible). A silently-degrading heartbeat interval under load is a defect, not a tuning detail.
- **Stale cache across transport switches (new)** — state that changed *during* the polling-fallback window must be reconciled by the first post-recovery push payload; a recovery that merely re-opens the stream without resyncing the cache can leave ghost nodes (e.g. a terminated execution still on the map).
- **Heartbeat vs proxy timeouts (new)** — corporate proxies/idle-timeout gateways may kill "idle" SSE connections; the heartbeat interval must be short enough to keep NAT/proxy tables warm (and the client must treat a dropped connection as fallback-triggering, not as healthy silence).
- **Min-zoom clamp vs initial fit regression (new)** — a later change to the clamp must not silently re-block the initial fit: the test asserting first-load fit of an over-large population is the regression guard; also verify the fit survives resize/fullscreen transitions (re-fit after those events must use the same unclamped-fit path, while user zoom remains clamped).
- **Grid-dot painter at extremes (new)** — deep zoom-in/out must not make the dot pattern alias into moiré, vanish, or tank render performance (dots are viewport-space, not content-space, or equivalently tiled to the viewport — the "covers everything" property must hold at extreme zoom levels too).
- **Full-height hub vs maximise (new)** — toggling fullscreen (and viewport resize) must keep the hub spanning the new full canvas height; the hub must not retain a stale pixel height from the pre-maximise layout.
- **Removal side-effects** — removing `VendorModelGuardrailPanel` must not orphan imports, tests, or route-level references; the retired `RuntimeTopologyDiagram` must be fully removed, not just unused.

---

## 5. Acceptance Criteria Checklist

Maps 1:1 to the PRD acceptance criteria. Each item is verified by the indicated layer.

### Renaming & Page Composition
- [ ] View presented as "Agent Runtime Monitor" throughout the UI, no residual "topology" naming for this live view — **frontend unit + E2E**
- [ ] Page is primarily the agent map; map occupies the main canvas — **frontend unit + E2E**
- [ ] Model guardrail panel removed from the page entirely (no panel/section/tab) — **frontend unit + E2E**

### Map Interaction
- [ ] Map auto-fits content so all visible agents are on screen without scrolling — **frontend unit + manual**
- [ ] Map supports zoom in and zoom out — **frontend unit + manual**
- [ ] Map supports drag-to-pan — **frontend unit + manual**
- [ ] Map can be maximised to fullscreen and restored — **frontend unit + E2E + manual**
- [ ] Grid-dot background covers the entire visible canvas at all times — empty map, and when panning/zooming beyond the drawn content — **frontend unit + manual**
- [ ] Communication Hub spans the full canvas height from the moment the map loads, even with zero agents — **frontend unit + E2E**
- [ ] Initial view on first load fits the entire population however many agents are running — initial fit not blocked by the interactive zoom limits (clamp applies to user zoom steps only) — **frontend unit + E2E**

### Live Updates (server push + polling fallback) (new)
- [ ] Monitor receives changes through the server push channel (server-sent events) rather than relying on fixed-interval polling — **backend integration (stream) + frontend unit (hook) + E2E**
- [ ] Stream endpoint authenticates via the query-param token; missing/expired/invalid tokens are rejected before any event — **backend integration (stream)**
- [ ] Stream applies the same agent-read permission as `GET /agents/runtime/topology` (permission parity, no bypass) — **backend integration (stream)**
- [ ] Projection emitted only when changed (content-hash comparison); unchanged state emits heartbeats only — **backend unit (hash) + backend integration (stream)**
- [ ] Heartbeats keep the connection alive during idle-but-unchanged periods — **backend integration (stream)**
- [ ] Stream payloads match the REST `RuntimeTopologyRead` shape (no push/pull field drift) — **backend integration (stream)**
- [ ] Stream payloads land in the query cache immediately: a new execution appears on the map with no polling request and no refetch — **frontend unit (hook) + E2E (mocked stream)**
- [ ] Execution start/state-change/finish and trigger/intervention changes appear within about a second or two via push — **frontend unit + E2E**
- [ ] When the push connection drops, the client automatically falls back to periodic polling (view never silently stale) — **frontend unit + E2E**
- [ ] When the connection is restored, the client returns to push and resyncs the cache (no state gap) — **frontend unit + E2E**

### Layout & Grouping
- [ ] Agents aligned to a grid rather than a single row — **frontend unit + manual**
- [ ] Same-type agents grouped in a visible virtual container — **frontend unit + manual**
- [ ] Auto-distribution fits screen ratio (no single-row overflow, no broken scrollbar) — **frontend unit + manual**

### Delegation Relationships
- [ ] Agent and delegated child(ren) displayed next to each other — **frontend unit + manual**
- [ ] Connecting line shows parent → child relationship — **frontend unit + manual**
- [ ] Parent/child adjacency and connector preserved when parent and child are different agent types — **frontend unit + E2E**
- [ ] Parent→child connector remains visible when other (unrelated) nodes are filtered out — **frontend unit + E2E**
- [ ] Delegated child promoted to a root when its parent is filtered out — **frontend unit + E2E**

### Agent Selection & Detail
- [ ] Selecting an agent shows a detail bubble next to it on the map — **frontend unit + E2E**
- [ ] Bubble reuses existing detail component; includes terminate + guardrail summary — **frontend unit + E2E**
- [ ] Bubble is dismissible — **frontend unit**
- [ ] Bubble shows the agent's trigger source (who or what triggered it) — **frontend unit + E2E**

### Human-Intervention Alerting
- [ ] Sleeping agent awaiting intervention shown by default (not hidden) — **frontend unit (hook + component) + E2E**
- [ ] Alert icon appears on that agent's tile — **frontend unit + E2E**
- [ ] Clicking alert icon opens the existing human-intervention dialog — **frontend unit + E2E**
- [ ] Sleeping agents not awaiting intervention remain hidden by default — **frontend unit**

### Trigger Provenance (creator-only attribution)
- [ ] `ScheduledJob.scheduled_by_user_id` migration applied; column exists (nullable uuid FK → Identity) — **backend integration (schema) + real-backend E2E**
- [ ] Schedule dispatch passes `scheduled_by_user_id` through to the launched `AgentJob.triggered_by_user_id` — **backend unit**
- [ ] Delegated child inherits `triggered_by_user_id` from its parent — **backend unit**
- [ ] Topology node returns `trigger_user_label`: user name (direct/delegated) or schedule **creator identity name**; `NULL` when the creator is unknown — schedule-name fallback removed — **backend unit + API integration**
- [ ] Agent tile and detail bubble show the human for schedule-triggered runs (never the schedule name as a person); unknown creator renders no person line, no placeholder — **frontend unit + E2E**
- [ ] The schedule entity card shows the creator caption only when a creator exists; legacy null-creator schedules show no creator caption anywhere — **frontend unit + E2E**

### Trigger Entity Detail Cards (new)
- [ ] Clicking a person entity opens a detail card beside it: person name + triggered-execution count (direct + via schedules) + list with type/status per row — **frontend unit (canvas) + E2E**
- [ ] Clicking a schedule entity opens a detail card: schedule name + creator (only when a creator exists) + its executions with statuses — **frontend unit (canvas) + E2E**
- [ ] Clicking the entity again (or dismissing) closes the card; dismissal matches the agent detail bubble pattern — **frontend unit + E2E**
- [ ] Clicking an execution row in either card selects — focuses and navigates to — that execution on the map — **frontend unit + E2E**
- [ ] Card execution lists and counts include only executions reachable under the current filter; no executions reachable renders an empty list without error — **frontend unit + E2E**

### Tool-Call History (Communication Hub)
- [ ] Communication Hub shown as a visible component on the map — **frontend unit + E2E**
- [ ] Each tool call drawn as a route agent → Communication Hub → MCP server — **frontend unit + E2E**
- [ ] Topology node returns per-node tool-call history (tool name + MCP slug + timestamp, ordered) — **backend unit + API integration**
- [ ] Latest call's route highlighted in a unique per-agent colour; older calls grey — **frontend unit + manual**
- [ ] Selecting an agent brightens its historical routes — **frontend unit + E2E**

### Filter & Legend Recovery
- [ ] Status/kind filters + legend accessible from a toolbar that stays on screen — **frontend unit + E2E**
- [ ] When a filter hides every agent, the filter/legend controls and toolbar remain visible and usable — **frontend unit + E2E**
- [ ] "Reset filters" restores the population without a page reload (no trapped empty state) — **frontend unit + E2E**

### Backend / API contract (supporting requirement)
- [ ] `GET /agents/runtime/topology` returns `needs_intervention` per node — **backend unit + API integration**
- [ ] `needs_intervention` is `true` for pending-intervention nodes, `false` otherwise — **backend unit**
- [ ] No new database entities introduced (one added field on `ScheduledJob` only) — **backend unit + integration (regression)**

### Live-Data Corrections (verification round)
- [ ] Terminal direct children of included jobs appear in the live topology with the delegation edge rendered, budget-capped by `max_nodes` — **backend unit + API integration**
- [ ] `waiting_for_human` jobs are included in the default (live) status list and count as a live status for conversations they drive — **backend unit + API integration**
- [ ] Conversations count chat-spawned linked jobs (`input_data.__conv_session_id`) as live drivers (`active` not `sleep`) with a conversation → job edge — **backend unit + API integration**
- [ ] Alert icon renders on ANY node with `needs_intervention` (agent jobs paused in `waiting_for_human` included, not just sleeping conversations) — **frontend unit**
- [ ] Agent tiles render the trigger-source line and the latest-tool-call line — **frontend unit**

---

## 6. Test File References

Test paths follow `docs/config.yaml` → `source.tests`. Entries marked **new**/**extended** cover the prior refinements, the schema change, the two latest refinements (the **creator-attribution fix** and the **trigger-entity detail cards**), and the **real-time + canvas-polish refinement**: the SSE stream endpoint (backend integration), the stream-consuming hook (`useRuntimeTopology` vitest), canvas polish (canvas vitest + e2e), and the mocked-stream live-update E2E. Existing coverage is retained.

### Backend (`backend/tests/`)
- `backend/tests/unit/services/test_runtime_topology_controller.py` — **extended**: existing `needs_intervention` cases remain; trigger-provenance resolution (user name for direct/delegated nodes; **creator identity name for schedule-triggered nodes and `NULL` when unknown — the schedule-name fallback is removed and asserted absent**, including schedules whose owning identity was deleted); per-node tool-call history derivation (tool name + MCP slug + timestamp, chronological order; empty list when no calls); plus **live-data round**: terminal direct children of included jobs appear with the delegation edge (budget-capped by `max_nodes`, no fetch when the budget is exhausted), `waiting_for_human` backing jobs keep conversations `active`, and chat-spawned linked jobs (`input_data.__conv_session_id`) count as live drivers (terminal linked jobs keep `sleep`); plus the **stream round**: the projection content-hash helper — identical projections hash equal (content-derived, canonical serialisation, stable across object identity/field order) and any state change (node added/status flipped/intervention toggled) changes the hash.
- `backend/tests/unit/test_scheduling.py` — **extended** (top-level `unit/`, not `unit/services/`): `SchedulingEngine._dispatch` passes `scheduled_by_user_id` into `GatewayLifecycleHandler.launch` (`user_id` argument); a `NULL` scheduled-by does not crash dispatch.
- `backend/tests/unit/test_agent_session_service.py` — **extended**: delegated child inherits `triggered_by_user_id` from its parent (`parent_job_id`), including explicit-user-wins and missing-parent-degradation cases; the launch→enqueue `user_id` forwarding is covered by the pre-existing `test_lifecycle_handler.py::test_launch_passes_user_id_to_session_service`. Four listing/get cases remain skipped (pre-existing, unrelated to this change).
- `backend/tests/integration/api/test_runtime_topology_api.py` — **extended**: retains the `needs_intervention` contract cases; asserts `RuntimeTopologyRead.nodes[*]` carries trigger-provenance fields (`trigger_source`, `trigger_source_label`) and a tool-call route list, with existing node fields unchanged; adds the creator-only attribution contract — a schedule-triggered node's label is the creator name, and a legacy null-creator schedule resolves with a `NULL`/absent label (never the schedule name); plus **live-data round**: `waiting_for_human` jobs are returned in the default live view, terminal direct children of an included parent appear with the delegation edge, and a chat-spawned linked job keeps its conversation `active` with a conversation → job edge. Uses module-scoped StaticPool in-memory SQLite.
- `backend/tests/integration/db/test_scheduled_job_schema.py` — **new**: DB-specific schema verification. Creates the schema via `Base.metadata.create_all` on an in-memory SQLite (the declarative model defines the column); asserts `scheduled_jobs.scheduled_by_user_id` exists, is nullable, is a `UUID`, and has an FK to `identities.id` (via SQLAlchemy inspector); inserts a schedule with and without `scheduled_by_user_id` and verifies both persist; existing/legacy rows retain `NULL`.
- `backend/tests/integration/api/test_runtime_topology_stream.py` — **new**: SSE stream endpoint tests (FastAPI `TestClient` streaming / httpx stream). Covers: valid query-param JWT opens the stream and yields an initial projection event; missing/expired/garbage token is rejected before any event; a principal without agent-read permission is rejected (permission parity with `GET /agents/runtime/topology`); identical projection passes emit **no** data events (hash-gated) while heartbeats continue on the keepalive interval; a projection change emits a data event promptly whose payload deserialises to the `RuntimeTopologyRead` shape; client disconnect cancels the server-side generator cleanly (no leaked subscribers).

### Frontend (`frontend/src/__tests__/`) — full suite green
- `frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx` — **updated**: retains "Agent Runtime Monitor" title, absence of `VendorModelGuardrailPanel`, presence of the mocked `AgentRuntimeMapCanvas` as the primary view, no user-facing "topology" label; adds a second describe block asserting the "awaiting intervention" indicator when a node carries `needs_intervention: true` (the Communication Hub visible-node presence is covered by `AgentRuntimeMapCanvas.test.tsx`).
- `frontend/src/__tests__/AgentRuntimeMapCanvas.test.tsx` — **extended**: retains loading/empty states, auto-fit, zoom, pan, grouping, connector, fullscreen, legend; adds cross-type parent/child adjacency, connector persistence when unrelated nodes are filtered out, delegated-child promotion to root when the parent is filtered out, empty-state filter recovery (toolbar/legend usable + "reset filters" restores nodes), Communication Hub node, and tool-call route colouring (latest per-agent colour, older grey, brightened on selection); adds **trigger-entity detail cards**: person card (name + triggered-execution count + list rows with type/status, row-click selects the execution on the map), schedule card (name + creator caption rendered only when a creator exists + executions with statuses), open on entity click / close on second click or dismiss, filter-scoped execution lists and counts (empty list without error when nothing is reachable); plus **live-data round**: the intervention alert renders on ANY `needs_intervention` node (a `waiting_for_human` agent-kind node and a sleeping conversation-kind node both flagged; no alert without the flag; alert click invokes the intervention flow with the node), and the tile renders the trigger-source line and the latest-tool-call line (omitted without calls); plus the **canvas-polish round**: grid dots cover the whole viewport in the empty state and after panning/zooming beyond the content bounds (assert the background layer spans the viewport, not the content bounding box), the Communication Hub fixture spans the full canvas height on first render with zero agents, and the initial fit of an over-large population is not clamped by the interactive min-zoom (initial scale below the clamp on first load; user zoom steps afterwards still respect the clamp).
- `frontend/src/__tests__/AgentDetailBubble.test.tsx` — **extended**: retains detail + terminate + guardrail summary + dismissible; adds creator-only trigger provenance — a schedule-triggered run shows the schedule creator's human name, never the schedule name in place of a person, and an unknown creator renders no person/trigger line (no placeholder).
- `frontend/src/__tests__/useRuntimeTopology.test.ts` — **extended**: retains `needs_intervention` and default-visibility predicate; adds trigger-provenance and tool-call-history surfacing onto nodes, and filter state that yields the fully-filtered empty state with a reset path; adds the **real-time round**: a pushed stream payload lands in the query cache immediately (new node renders with no polling request — assert no extra `GET /agents/runtime/topology` while the stream is healthy); a stream error activates the polling fallback; recovery stops polling and resyncs the cache from the first post-recovery payload; unmount closes the `EventSource` and stops the fallback poller. If the stream logic ships as a separate hook (mirroring the `useSessionExecutionLogStream` precedent), cover it in a sibling `useRuntimeTopologyStream.test.ts` and keep this file focused on cache-integration and the visibility predicate.
- `frontend/src/__tests__/useRuntimeTopologyStream.test.ts` — **new (conditional)**: stream-transport unit tests with a mocked `EventSource` — message → cache push, `onerror` → fallback mode flag, reopen → back to push mode, cleanup on unmount. Skip if the transport is covered inside `useRuntimeTopology.test.ts` instead.
- `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx` — **unchanged**: renders `VendorModelGuardrailPanel readonly` directly (panel moved off the monitor page).
- `frontend/src/__tests__/RuntimeTopologyPanel.test.tsx` — **left unchanged**: `RuntimeTopologyPanel` was not repurposed to host the canvas.
- `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` — **left unchanged**: Agent Plan Preview component, unrelated to this change.

### E2E (`e2e/tests/`)
- `e2e/tests/agent-runtime-monitor.spec.ts` — **extended**: retains auto-fit, zoom, pan, fullscreen, grouping, delegation connector, alert → `InterveneResponseDialog`; adds delegation legibility (cross-type adjacency, connector persistence under filter, child promoted to root), empty-state filter recovery ("reset filters"), creator-only trigger provenance on tile/bubble, a **trigger-entity describe block** (the e2e trigger-entity spec target): open the person card (name, count, list rows with type/status), open the schedule card (name, executions, creator caption only when a creator exists — mock payload includes a null-creator legacy schedule), row-click selects/navigates to the execution on the map, filter-scoped lists, dismiss/second-click closes; tool-call routes (Communication Hub node, latest-call per-agent colour, selection brightens history); the **mocked-stream live-update block**: intercept the SSE stream endpoint via `page.route()` (or a Playwright raw-response mock), load the map with the initial population, emit a stream event carrying one additional execution, and assert the new tile appears **without any polling/refetch action** (track `GET /agents/runtime/topology` requests and assert the count does not increase; assert no test-triggered reload) — plus the fallback variant (abort the stream → topology GETs resume) and the recovery variant (stream unblocked → polling stops, pushed update still lands); and the **canvas-polish assertions**: hub fixture full-height on load with zero agents, grid dots present across the viewport when panned beyond content (empty-state dot coverage is covered by the canvas vitest), initial fit shows the whole large mock population on first load. Mock payloads already carry `needs_intervention`, trigger provenance, and `tool_calls`, so no mock changes were required for the live-data round.
- `e2e/tests/runtime-control-dashboard.spec.ts` — **extended**: retains page rename, map canvas, guardrail-panel absence, detail bubble + terminate (mock-first via `page.route()`); retains the real-backend topology/terminate smoke test.
- `e2e/tests/agent-runtime-monitor.real-backend.spec.ts` — **new**: `test.describe('Real Backend Integration - trigger provenance')`. A no-mock variant that asserts the live `GET /agents/runtime/topology` response carries the trigger-provenance fields (`trigger_source`, `trigger_source_label`) plus the `tool_calls` list and the boolean `needs_intervention` contract — which only works if the `scheduled_by_user_id` migration is applied and the provenance resolution layer is wired through. Skips cleanly when `E2E_REAL_BACKEND_TOKEN` is unset or the backend is unreachable. **Stream smoke (optional, same skip contract)**: open the live SSE endpoint with the real token as a query param and assert an initial event arrives within the heartbeat window — a live smoke that the query-param auth and stream wiring work end-to-end (deep stream behaviour stays in the backend integration tests).
- `e2e/tests/conversation-intervention.spec.ts` — **reuse (unchanged)**: confirms the intervention dialog flow still works; the monitor's alert click reaches this same dialog.

---

## Execution Notes

- **Database change** (`has_db_changes: true`): run `python -m alembic current` to confirm the `scheduled_by_user_id` migration is applied; if not, `python -m alembic upgrade head` before any test run (see Pre-Test Checklist). Backend integration fixtures apply migrations in setup.
- Run the full suite via `/test-app` (backend, frontend, E2E) after implementation; all three layers must pass, including the real-backend schema-change E2E variant.
- Reuse patterns from the existing referenced test files (mock topology payloads, `react-i18next` mock, `standardSetup` E2E helper).
- Test data for new fixtures should use identifiable IDs (e.g. `sess-awaiting-intervention`, `sess-sleep-hidden`, `sched-by-user`, `sched-by-null`) so assertions on default visibility and trigger provenance are unambiguous. For the creator-attribution fix, pair a schedule with a known creator identity (e.g. `creator-alice`) with a legacy null-creator schedule so creator-caption presence vs absence — and the absence of any schedule-name-as-person fallback — is asserted without ambiguity.
- **Stream testing (new)**: backend stream tests drive the projection through the controller twice (unchanged → changed) rather than sleeping on real intervals — inject or patch the change-detection/heartbeat clock. E2E mocks the stream endpoint with `page.route()` and emits an event mid-test; assert "no polling" by counting `GET /agents/runtime/topology` requests via the route handler, not by absence-of-visibility timing alone. Give the mocked stream a distinctive test execution ID (e.g. `sess-stream-live-<ts>`) so the "new tile appears" assertion is unambiguous.


### Phase 14 — Trigger-entity own details (verification scenarios)

- **WHEN** a schedule entity's detail card is opened **THEN** the schedule's own cadence (cron, humanised), description and status appear — sourced from `GET /schedules/{id}` with the topology payload as fallback.
- **WHEN** a person entity's detail card is opened **THEN** the user's email and identity type appear — sourced from `GET /identities/{id}`.
- **WHEN** either fetch fails (e.g. 403) **THEN** the detail rows are hidden silently and the rest of the card (executions, creator) still renders.
