# Test Plan — Agent Runtime Monitor

## 1. Test Strategy

This test plan validates the replacement of the static "agent topology" diagram with **Agent Runtime Monitor** — a full-page, interactive, map-style canvas for watching the live, multi-level agent population. It covers the frontend map-canvas redesign (zoom/pan/auto-fit, team-container grouping by delegation depth, delegation connectors, trigger provenance, tool-call routes through the Communication Hub, trigger-entity detail cards, empty-state filter recovery), the backend contract and live-data fixes (pending-intervention signal, trigger provenance with **creator-only attribution**, per-node tool-call history, live-set completeness), and the **real-time live stream** (server-sent events with automatic polling fallback).

This change **does modify the database schema** (`has_db_changes: true`): `ScheduledJob` gains a nullable `scheduled_by_user_id` field. The DB-specific test-plan rules apply in full (see Section 6).

| Layer | Framework | Scope |
|---|---|---|
| **Backend Unit** | pytest + SQLite | `RuntimeTopologyController` pending-intervention resolution; trigger-provenance resolution (creator-only, `NULL` when unknown); per-node tool-call history derivation; live-set completeness (terminal children budget-capped by `max_nodes`, `waiting_for_human` as live status, chat-spawned linked jobs); projection content-hash change detection; `SchedulingEngine._dispatch` → `launch` user-id forwarding; delegated-child trigger inheritance |
| **Backend Integration** | pytest + PostgreSQL / in-memory SQLite (`StaticPool`) | `GET /agents/runtime/topology` contract (additive fields); **scheduled_by_user_id schema verification**; **SSE stream endpoint** (query-param JWT auth, permission parity, hash-gated emission, heartbeats, clean disconnect) |
| **Frontend Component** | Vitest + React Testing Library | `AgentRuntimeMapCanvas` (canvas, grouping, connectors, tool-call routes, trigger-entity cards, empty-state recovery, canvas polish); `AgentDetailBubble` (creator-only provenance); `useRuntimeTopology` hook (visibility predicate, cache integration, real-time stream consumption, polling fallback); page composition |
| **E2E (Mocked)** | Playwright + `page.route()` | Page rename, map interactions, delegation legibility, filter recovery, trigger provenance, trigger-entity detail cards, tool-call routes, alert → intervene, terminate, **mocked-stream live update (tile appears without polling)** |
| **E2E (Real Backend)** | Playwright (no mocks) | `GET /agents/runtime/topology` live contract (trigger provenance fields + tool_calls + needs_intervention) — validates the `scheduled_by_user_id` migration; optional SSE stream smoke |
| **Manual / Exploratory** | Manual | Zoom/pan feel, auto-fit, fullscreen, grid/grouping legibility, per-agent route colouring, grid-dot coverage while panning/zooming, full-height hub, first-load fit of a large population |

**Key testing principles for this change:**
- **Contract correctness first**: `needs_intervention` must be `true` only for a node with a pending `InterveneRequest` (status `pending`), with `false` as the safe default for backwards compatibility.
- **Trigger provenance is a data-integrity chain, not just a label**: `ScheduledJob.scheduled_by_user_id` → `SchedulingEngine._dispatch` → `GatewayLifecycleHandler.launch` → `AgentJob.triggered_by_user_id` → (delegated child inherits) → `RuntimeTopologyController` resolves a human-readable trigger source. Each hop is tested independently and end-to-end.
- **Attribution is human-centric (creator-only)**: for schedule-triggered nodes, the trigger label resolves to the schedule creator's identity name, or is `NULL` when the creator is unknown — the old schedule-name fallback is removed and its absence asserted. The schedule name identifies the schedule entity only; it must never appear in place of a person anywhere (tiles, bubbles, tooltips, cards).
- **Push, don't poll — polling is only a safety net**: the stream endpoint authenticates the `EventSource` connection via the query-param token (no `Authorization` header is available to `EventSource`), emits the projection only when it actually changed (content-hash comparison), keeps the connection alive with heartbeats, and enforces the **same agent-read permission** as the REST topology endpoint. On the frontend, stream payloads land in the query cache immediately (a new execution appears without any polling request), polling activates only while the stream is down, and the client returns to push on recovery.
- **Canvas presentation is contract, not decoration**: grid dots must cover the entire visible canvas (empty map and when panning/zooming beyond drawn content), the Communication Hub must span the full canvas height from first load even with zero agents, and the initial fit of a large population must not be clamped by the interactive min-zoom limit (the clamp governs user zoom steps, not the initial auto-fit).
- **Visibility predicate**: a sleeping agent awaiting intervention is shown by default; a sleeping agent not awaiting intervention stays hidden.
- **Empty-state recovery is a hard requirement**: the filter/legend toolbar must remain usable when a filter combination hides every node, and "reset filters" must restore visibility without a page reload.
- **Reuse is verified, not re-implemented**: terminate and intervene flows are used as-is; tests confirm they still open and complete.

## 2. Coverage Areas

| Area | Why Critical |
|---|---|
| Backend — pending-intervention resolution (`RuntimeTopologyController`) | Per-node resolution of pending `InterveneRequest` rows keyed by session (agent vs conversation), attached to the projection without new entities; correct safe default `false`; the signal must flow through projection, schema, and endpoint without being dropped or mis-typed |
| Backend — live-set completeness | Terminal direct children of included jobs appear so delegation edges render (budget-capped by `max_nodes`); `waiting_for_human` is a live status; an open conversation computes `active` when its backing job or any chat-spawned linked job (`input_data.__conv_session_id`) is live, with a conversation → linked-job edge |
| Backend — trigger provenance | Migration/schema (`scheduled_by_user_id` nullable uuid FK); schedule dispatch → launch stamping onto `AgentJob.triggered_by_user_id`; delegation inheritance; controller resolution to a human-readable trigger source (creator identity name for schedule-triggered nodes, `NULL` when unknown, schedule-name fallback removed) |
| Backend — tool-call history via Communication Hub | Per-node tool-call history list (tool name + MCP server slug + timestamp, ordered), read from `ToolCallRecord`, namespaced names split via `parse_tool_name` and resolved to `McpServer` slugs |
| API contract — `GET /agents/runtime/topology` | `RuntimeTopologyRead` serializes nodes/edges/roots with additive per-node fields (`needs_intervention`, trigger provenance, tool-call routes); no route, query-parameter, or field removals — backwards-compatible additions |
| Backend — live topology stream (SSE) | Query-param token auth (reject before any event); same agent-read permission as REST (no bypass); hash-gated emission (identicial projections → heartbeats only); heartbeats on a fixed keepalive interval; payload matches `RuntimeTopologyRead` shape; clean cancellation on client disconnect |
| Frontend — real-time stream consumption | Immediate cache push (new execution appears with no polling request); fallback to periodic polling on stream error/reconnect storms; recovery resyncs cache; hook exposes active transport (push vs polling); cleanup closes `EventSource` and stops the fallback poller on unmount |
| Frontend data model & naming | `RuntimeTopologyNode` mirrors `needs_intervention`, trigger provenance, and tool-call history; all user-facing "topology" strings replaced by "Agent Runtime Monitor" via `t()` |
| Map canvas (`AgentRuntimeMapCanvas`) | Zoom in/out, drag-to-pan, auto-fit on mount/resize; grid-aligned layout with same-type grouping into visible containers; delegation connectors from `parent_session_id`; cross-type adjacency and connector persistence under filter; child promoted to root when parent filtered out; empty-state filter recovery; tool-call routes agent → hub → MCP server with latest-call highlight; fullscreen toggle with re-fit; grid-dot background covers entire visible canvas; full-height hub fixture with zero agents; first-load fit not clamped by interactive min-zoom |
| Agent detail bubble (`AgentDetailBubble`) | Inline bubble beside the selected node: detail + terminate + guardrail summary + trigger source; dismissible; creator-only trigger provenance (never schedule name as person; no placeholder when creator unknown) |
| Trigger entity detail cards | Person card (name, triggered-execution count, execution list rows with type/status); schedule card (name, executions, creator caption only when a creator exists); open on entity click, close on second click/dismiss; row-click selects that execution on the map; filter-scoped execution lists and counts |
| Human-intervention alerting | Default visibility of sleep + `needs_intervention` nodes; alert icon on ANY node flagged `needs_intervention` (including agent jobs paused in `waiting_for_human`, not just sleeping conversations); alert click opens the existing `InterveneResponseDialog` |
| Page composition (`RuntimeControlDashboardPage`) | Map is the primary canvas; guardrail panel absent; no residual user-facing "topology" naming; empty/loading/error states handled; accessibility |

## 3. Critical Scenarios

### Scenario 1: Live-Set Completeness

- **WHEN** an included job has a terminal direct child (e.g. failed delegated attempt) **THEN** the child appears in the projection with its own status and the parent → child delegation edge is present (child depth = parent depth + 1, child not a root).
- **WHEN** the active set approaches `max_nodes` **THEN** the terminal-children fetch is capped by the remaining budget (no fetch when the budget is exhausted).
- **WHEN** a job is paused in `waiting_for_human` **THEN** it is visible in the default live topology with status `waiting_for_human`, and a conversation it drives computes runtime status `active` (not `sleep`).
- **WHEN** a chat-spawned job linked via `input_data.__conv_session_id` is live **THEN** its source conversation computes `active` and an edge conversation → job is returned; **WHEN** the only linked job is terminal **THEN** the conversation stays `sleep`.

### Scenario 2: Pending-Intervention Contract

- **WHEN** a node's session has a pending `InterveneRequest` (status `pending`) **THEN** that node's `needs_intervention` is `true`.
- **WHEN** a node's session has no pending intervention request (or only non-pending statuses — responded/cancelled/expired) **THEN** `needs_intervention` is `false`.
- **WHEN** `GET /agents/runtime/topology` is called **THEN** every node in `RuntimeTopologyRead.nodes` carries a boolean `needs_intervention` and existing fields are unchanged.

### Scenario 3: Trigger Provenance — Schema & Dispatch Chain

- **WHEN** the migration is applied **THEN** `scheduled_jobs.scheduled_by_user_id` exists, is nullable, is a `uuid`, and carries an FK to `identities`.
- **WHEN** the migration is applied **THEN** pre-existing `ScheduledJob` rows retain `NULL` (no backfill errors, no data loss).
- **WHEN** a schedule with a `scheduled_by_user_id` fires **THEN** the launched `AgentJob.triggered_by_user_id` equals the schedule's `scheduled_by_user_id`.
- **WHEN** an agent delegates to a child agent **THEN** the child `AgentJob.triggered_by_user_id` equals its parent's `triggered_by_user_id`.
- **WHEN** a schedule has no `scheduled_by_user_id` (legacy/NULL) **THEN** the launched `AgentJob` keeps `triggered_by_user_id` NULL and the topology node resolves `trigger_user_label` as `NULL` — no crash, no schedule-name fallback.

### Scenario 4: Trigger Provenance — Creator-Only Attribution

- **WHEN** a node was directly user-triggered (or delegated) **THEN** the topology node returns that user's display name as the trigger label.
- **WHEN** a node was schedule-triggered and the schedule has a known creator **THEN** `trigger_user_label` is the creator's **identity name** — never the schedule name.
- **WHEN** a node was schedule-triggered and the schedule creator is unknown (legacy `NULL`) **THEN** `trigger_user_label` is `NULL`/absent — no schedule-name fallback and no placeholder string anywhere (agent tile, detail bubble, tooltips).
- **WHEN** a node was delegated **THEN** the topology node returns the parent's trigger label (the original user's display name).

### Scenario 5: Tool-Call History

- **WHEN** an agent has recorded tool calls **THEN** the topology node returns a per-node tool-call list with, per call: tool name, MCP server slug, and timestamp, in chronological order.
- **WHEN** a namespaced tool name `server____tool` is resolved **THEN** the entry carries the tool name (`tool`) and the MCP slug (`server`).
- **WHEN** a tool-call references an MCP slug with no matching `McpServer` **THEN** the entry still returns (slug preserved) and the frontend renders a graceful route.
- **WHEN** an agent has made no tool calls **THEN** the node returns an empty tool-call list (no error, no phantom route).

### Scenario 6: Live Topology Stream (SSE)

- **WHEN** a client opens the stream endpoint with a **valid** JWT passed as a query parameter **THEN** the connection is accepted (`text/event-stream`) and an initial projection payload is emitted.
- **WHEN** a client opens the stream endpoint with a **missing, expired, or invalid** query-param token **THEN** the connection is rejected before any event is emitted — never an open unauthenticated stream.
- **WHEN** a principal **lacks** the agent-read permission required by `GET /agents/runtime/topology` **THEN** the stream endpoint rejects them with the same failure mode (permission parity — the stream is not a permission bypass).
- **WHEN** the projection is unchanged between change-detection passes **THEN** no data event is emitted (hash equal) — only the keepalive heartbeat flows on the fixed interval.
- **WHEN** the projection changes (execution starts/changes state/finishes, trigger or intervention state changes) **THEN** a data event carrying the updated projection is emitted promptly (hash differs → emit).
- **WHEN** two consecutive projections have identical content but different object identity **THEN** the hash comparison treats them as equal (content-derived, canonical).
- **WHEN** the client disconnects **THEN** the server-side generator/task for that subscriber is cancelled and cleaned up (no leaked connections, no continued DB polling).
- **WHEN** a data event is emitted **THEN** its payload deserialises to the same `RuntimeTopologyRead` shape as the REST endpoint (no field drift between push and pull).

### Scenario 7: Real-Time Stream Consumption (Frontend)

- **WHEN** a stream payload arrives **THEN** the hook writes it into the shared query cache immediately — a newly started execution renders with **no** polling request and **no** manual refetch (assert: no additional `GET /agents/runtime/topology` call).
- **WHEN** an execution changes state or finishes, or trigger/intervention state changes **THEN** the map reflects the change from the pushed payload with push immediacy (no poll-cycle wait).
- **WHEN** the stream errors or the connection drops **THEN** the hook activates periodic polling automatically (fallback within the poll interval, never silently stale).
- **WHEN** the stream reconnects **THEN** polling stops, push resumes, and the first post-recovery payload resyncs the cache (no state gap from the polling window).
- **WHEN** the stream is healthy **THEN** polling remains inactive (no redundant requests while push is live).
- **WHEN** the monitor unmounts **THEN** the `EventSource` is closed and the fallback poller is stopped — no orphan connections or timers remain.

### Scenario 8: Canvas Presentation Polish

- **WHEN** the map is empty (zero agents) **THEN** grid dots cover the entire visible canvas (no blank region inside the viewport).
- **WHEN** the operator pans the viewport beyond the drawn content (or zooms out past the content bounds) **THEN** grid dots still cover every visible pixel — no white/unpainted margins at any edge.
- **WHEN** the map loads with zero agents **THEN** the Communication Hub fixture spans the full canvas height from the first render.
- **WHEN** the map first loads with a large population (more agents than fit at the interactive min-zoom scale) **THEN** the initial view still fits the entire population on screen — the initial auto-fit scale is not clamped by the interactive min-zoom limit.
- **WHEN** the operator zooms out after the initial fit **THEN** the interactive min-zoom clamp engages from that point.

### Scenario 9: Map Interaction, Layout & Delegation Legibility

- **WHEN** the monitor opens with many nodes **THEN** all visible agents are on screen without scrolling (auto-fit).
- **WHEN** the operator zooms in/out or drags the empty canvas **THEN** the canvas scale changes/anchors and the viewport pans.
- **WHEN** the maximize control is toggled **THEN** the map expands to fullscreen and restores to the normal layout, re-fitting content each time.
- **WHEN** multiple agents share the same agent type **THEN** they render inside one labelled virtual container, aligned to a grid; parent and delegated children are laid out adjacent and joined by a visible connector line.
- **WHEN** a parent and its delegated child are **different agent types** **THEN** they remain adjacent and joined by a connector line (delegation adjacency overrides type grouping).
- **WHEN** a filter hides nodes that are **not** part of a parent/child pair **THEN** the parent→child connector line remains visible.
- **WHEN** a parent is filtered out **THEN** its delegated child is promoted to a root (still rendered, not orphaned/hidden with the parent).

### Scenario 10: Visibility Predicate & Empty-State Filter Recovery

- **WHEN** a node is a conversation/instance with runtime status `sleep` and `needs_intervention` is `true` **THEN** it is rendered by default with an alert icon.
- **WHEN** a node is `sleep` and `needs_intervention` is `false` **THEN** it remains hidden by default (excluded from the map).
- **WHEN** a node is active (running/queued) **THEN** it is rendered regardless of `needs_intervention`.
- **WHEN** a filter combination hides every node **THEN** the legend and status/kind filter controls and the toolbar remain visible and usable.
- **WHEN** the operator activates "reset filters" on an empty map **THEN** the full agent population is restored without a page reload.

### Scenario 11: Tool-Call Route Rendering

- **WHEN** the map renders **THEN** the Communication Hub is shown as a visible node.
- **WHEN** an agent has tool calls **THEN** each call is drawn as a route from the agent, through the hub, to the MCP server that served it; the latest call's route is highlighted in a unique colour per agent and older calls render in light grey.
- **WHEN** an agent is selected **THEN** that agent's historical routes are brightened so all its calls become visible.

### Scenario 12: Selection & Detail + Human-Intervention Alert

- **WHEN** a node is selected **THEN** a detail bubble appears beside it showing agent detail, a terminate action, a guardrail summary, and the trigger source; dismiss restores the plain map.
- **WHEN** the terminate action is used **THEN** the existing termination flow completes and the topology reflects the result.
- **WHEN** the alert icon is clicked on a node awaiting intervention **THEN** the existing `InterveneResponseDialog` opens for that session and the response flow completes without change.

### Scenario 13: Trigger Entity Detail Cards

- **WHEN** a person entity in the trigger column is clicked **THEN** a detail card opens showing the person's name, the count of executions they triggered (direct + via schedules), and the execution list with each row's type and status.
- **WHEN** a schedule entity is clicked **THEN** its card shows the schedule name, its executions with statuses, and the creator caption **only when a creator exists** (null-creator legacy schedules show no caption and no placeholder).
- **WHEN** the same entity is clicked again — or the card is dismissed **THEN** the card closes and the plain map view is restored.
- **WHEN** an execution row is clicked in either card **THEN** that execution becomes selected on the map — focused and navigated to.
- **WHEN** a status/kind filter or recent-completed window is active **THEN** each card's execution list (and its count) contains only executions reachable in the current filter; no executions reachable renders an empty list without error.

### Scenario 14: Page Composition

- **WHEN** the Agent Runtime Monitor page is rendered **THEN** no guardrail panel/section/tab is present and the map canvas is the primary view.
- **WHEN** the page is rendered **THEN** no user-facing "topology" label remains for this live runtime view (all strings resolve to "Agent Runtime Monitor").

## 4. Edge Cases & Risks

| Edge Case | Risk Level | Mitigation |
|---|---|---|
| Backwards-compatibility of new fields (`needs_intervention`, trigger provenance, tool-call history) | **High** | All additions have safe defaults (`false`, `null`/empty list); schema remains additive; existing tests and older mocks that omit the fields must still serialize/parse |
| Sleep-node status ambiguity across `kind` values (`agent`/`conversation`/`instance`) | **High** | The "sleep + awaiting intervention" rule must apply only to the correct kind(s); predicate must not resurrect completed/failed/terminated nodes |
| Multi-request / multi-session mapping | High | The join key (`agent_session_id` vs `conversation_session_id`) must be tested for both agent-kind and conversation-kind nodes to avoid false positives/negatives |
| Race / stale topology between poll and render | Medium | An answered intervention must not leave a phantom alert; dialog and refetch must behave consistently |
| Empty topology | Medium | Zero nodes/edges render a clean empty state — no crash, no broken auto-fit math |
| Large / deeply-nested populations | Medium | Auto-fit and grouping must not overflow into a single row or reintroduce a broken scrollbar; pan/zoom stay usable at high node counts |
| Zoom/pan vs selection | Medium | Clicking a node must not be swallowed by drag-to-pan; dragging on a node must not open the detail bubble |
| Fullscreen re-fit & cleanup | Medium | Repeated fullscreen toggling must re-fit content and not leak portal/DOM state; dismissal must not strand the bubble |
| Migration safety (`scheduled_by_user_id`) | **High** | Nullable and additive: legacy rows load with `NULL`; FK created without breaking legacy rows; `alembic downgrade` drops the column cleanly; enum handling avoids duplicate-type errors |
| Schedule dispatch provenance gaps (NULL creator, deleted owning identity) | **High** | Must not crash launch or topology resolution; label degrades to `NULL`; schedule-name fallback has been **removed** — no fallback string or placeholder may render anywhere |
| Schedule name never renders as a person | **High** | Regression guard: tiles, bubbles, tooltips must never fall back to the schedule name; mock payloads that predate the creator-only fix must be updated or explicitly asserted against |
| Trigger-card list vs filter interplay | High | Card list and count stay consistent with the active filter; changing the filter while a card is open refreshes the list (no stale rows, no count/list mismatch); row-click never targets an execution hidden by the filter |
| Trigger-card dismissal state | Medium | Opening person/schedule cards and the agent bubble in sequence must not strand multiple cards; dismissal and re-open survive zoom/pan/fullscreen transitions |
| Delegation chain depth | High | A multi-level chain propagates the original trigger user all the way down (child of child); a missing/loop parent must not cause infinite recursion |
| Delegation vs filter interplay | Medium | Filtering out a parent promotes the child to a root; filtering out a child must not hide the parent; filtering both keeps the empty-state toolbar usable |
| Tool-call ordering & latest-call highlighting | Medium | Ordering is timestamp-stable (no ties flipping the highlighted call); an agent with a single call has that call as "latest"; zero calls draws no route and no phantom highlight |
| MCP slug resolution | Medium | A tool name without a `server____` namespace, an unknown slug, or an inactive/deleted `McpServer` must not drop the call or crash the route renderer; route terminates at the hub with a degraded label |
| i18n completeness | Medium | Any hardcoded "topology", trigger-source, or new label bypassing `t()` is a defect |
| Accessibility | Medium | Zoom/pan/fullscreen/alert/dismiss/filter controls must be keyboard- and ARIA-reachable; alert state and latest-call highlighting need a non-colour cue |
| Multiple tabs / concurrent streams | Medium | Each subscriber gets an independent stream with correct events; no collapse, corruption, or cross-delivery between subscribers; burst of concurrent connections must not exhaust connection/DB-polling resources (per-connection registry, cleaned up on disconnect) |
| Stream reconnect storms (flapping network / backend restart) | **High** | Client backs off reconnect attempts (jittered, bounded), must not stack multiple pollers or `EventSource`s; server survives a wave of simultaneous reconnects; auth failures are terminal, not retryable |
| Hash-comparison cost at large populations | Medium | Canonical serialisation, no per-subscriber duplicate computation where a shared projection is feasible; heartbeat interval must not silently degrade under load |
| Stale cache across transport switches | **High** | State changed during the polling-fallback window is reconciled by the first post-recovery push payload; a recovery that re-opens the stream without resyncing can leave ghost nodes |
| Heartbeat vs proxy timeouts | Medium | Heartbeat interval short enough to keep NAT/proxy tables warm; client treats a dropped connection as fallback-triggering, not as healthy silence |
| Min-zoom clamp vs initial fit regression | Medium | A test asserting first-load fit of an over-large population is the regression guard; re-fit after resize/fullscreen uses the same unclamped-fit path while user zoom remains clamped |
| Grid-dot painter at extremes | Medium | Deep zoom in/out must not make the dot pattern alias into moiré, vanish, or tank render performance (viewport-space tiling) |
| Full-height hub vs maximise | Medium | Toggling fullscreen and viewport resize must keep the hub spanning the new full canvas height (no stale pixel height) |
| Removal side-effects | Medium | Removing `VendorModelGuardrailPanel` must not orphan imports, tests, or route-level references; the retired `RuntimeTopologyDiagram` is fully removed, not just unused |

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
- [ ] Initial view on first load fits the entire population whatever the agent count — initial fit not blocked by the interactive zoom limits (clamp applies to user zoom steps only) — **frontend unit + E2E**

### Live Updates (server push + polling fallback)
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
- [ ] Topology node returns trigger label: user name (direct/delegated) or schedule **creator identity name**; `NULL` when the creator is unknown — schedule-name fallback removed — **backend unit + API integration**
- [ ] Agent tile and detail bubble show the human for schedule-triggered runs (never the schedule name as a person); unknown creator renders no person line, no placeholder — **frontend unit + E2E**
- [ ] The schedule entity card shows the creator caption only when a creator exists; legacy null-creator schedules show no creator caption anywhere — **frontend unit + E2E**

### Trigger Entity Detail Cards
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

### Backend / API Contract (supporting requirement)
- [ ] `GET /agents/runtime/topology` returns `needs_intervention` per node — **backend unit + API integration**
- [ ] `needs_intervention` is `true` for pending-intervention nodes, `false` otherwise — **backend unit**
- [ ] No new database entities introduced (one added field on `ScheduledJob` only) — **backend unit + integration (regression)**
- [ ] Terminal direct children of included jobs appear in the live topology with the delegation edge rendered, budget-capped by `max_nodes` — **backend unit + API integration**
- [ ] `waiting_for_human` jobs are included in the default (live) status list and count as a live status for conversations they drive — **backend unit + API integration**
- [ ] Conversations count chat-spawned linked jobs (`input_data.__conv_session_id`) as live drivers (`active` not `sleep`) with a conversation → job edge — **backend unit + API integration**
- [ ] Alert icon renders on ANY node with `needs_intervention` (agent jobs paused in `waiting_for_human` included, not just sleeping conversations) — **frontend unit**
- [ ] Agent tiles render the trigger-source line and the latest-tool-call line — **frontend unit**

## 6. Database Migration Requirements

This change has `has_db_changes: true`. Backend integration tests must verify schema changes against a real PostgreSQL database with `alembic upgrade head` applied.

### Schema Changes to Verify
- `ScheduledJob.scheduled_by_user_id` — nullable `uuid` FK → `identities.id`; existing/legacy rows retain `NULL` (additive, no data loss)

### Pre-Test Checklist
- [ ] Verify migration applied: `python -m alembic current` shows the new revision that adds `scheduled_by_user_id`; if not, run `python -m alembic upgrade head` before any test run.
- [ ] Backend integration fixture applies migrations in setup so the test database matches production (`alembic upgrade head`).
- [ ] Integration test asserts the new column exists, is nullable, is a `uuid`, and has an FK to `identities` (via `information_schema` / SQLAlchemy inspector) — not just service logic.
- [ ] Include at least one real-backend E2E variant for the schema change (no `page.route()` mocks) to catch migration issues that mocked tests miss.

## 7. Test File References

### Backend — `backend/tests/`

| Test File | Covers |
|---|---|
| `backend/tests/unit/services/test_runtime_topology_controller.py` | **Extended**: existing `needs_intervention` cases remain; trigger-provenance resolution (user name for direct/delegated nodes; **creator identity name for schedule-triggered nodes and `NULL` when unknown — the schedule-name fallback is removed and asserted absent**, including schedules whose owning identity was deleted); per-node tool-call history derivation (tool name + MCP slug + timestamp, chronological order; empty list when no calls); live-data round (terminal direct children budget-capped by `max_nodes`, `waiting_for_human` keeps conversations `active`, chat-spawned linked jobs count as live drivers); stream round (projection content-hash helper — identical projections hash equal, any state change changes the hash) |
| `backend/tests/unit/test_scheduling.py` | **Extended**: `SchedulingEngine._dispatch` passes `scheduled_by_user_id` into `GatewayLifecycleHandler.launch` (`user_id` argument); a `NULL` scheduled-by does not crash dispatch |
| `backend/tests/unit/test_agent_session_service.py` | **Extended**: delegated child inherits `triggered_by_user_id` from its parent (`parent_job_id`), including explicit-user-wins and missing-parent-degradation cases; launch→enqueue `user_id` forwarding is covered by the pre-existing `test_lifecycle_handler.py::test_launch_passes_user_id_to_session_service` |
| `backend/tests/integration/api/test_runtime_topology_api.py` | **Extended**: retains the `needs_intervention` contract cases; asserts `RuntimeTopologyRead.nodes[*]` carries trigger-provenance fields (`trigger_source`, `trigger_source_label`) and a tool-call route list, with existing node fields unchanged; adds the creator-only attribution contract (schedule-triggered label is the creator name; legacy null-creator resolves `NULL`/absent — never the schedule name); live-data round (`waiting_for_human` in default live view, terminal children with delegation edge, chat-spawned linked job keeps conversation `active`). Uses module-scoped `StaticPool` in-memory SQLite |
| `backend/tests/integration/db/test_scheduled_job_schema.py` | **New**: DB-specific schema verification — creates the schema via `Base.metadata.create_all` on in-memory SQLite; asserts `scheduled_jobs.scheduled_by_user_id` exists, is nullable, is a `UUID`, and has an FK to `identities.id` (SQLAlchemy inspector); inserts schedules with and without the field and verifies both persist; legacy rows retain `NULL` |
| `backend/tests/integration/api/test_runtime_topology_stream.py` | **New**: SSE stream endpoint tests (FastAPI `TestClient` streaming / httpx stream) — valid query-param JWT opens the stream and yields an initial projection event; missing/expired/garbage token rejected before any event; principal without agent-read permission rejected (permission parity); identical projections emit **no** data events (hash-gated) while heartbeats continue on the keepalive interval; a projection change emits a data event promptly whose payload deserialises to `RuntimeTopologyRead`; client disconnect cancels the server-side generator cleanly (no leaked subscribers) |

### Frontend — `frontend/src/__tests__/` (full suite green)

| Test File | Covers |
|---|---|
| `frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx` | **Updated**: "Agent Runtime Monitor" title, absence of `VendorModelGuardrailPanel`, mocked `AgentRuntimeMapCanvas` as the primary view, no user-facing "topology" label; "awaiting intervention" indicator when a node carries `needs_intervention: true` (hub visible-node presence covered by `AgentRuntimeMapCanvas.test.tsx`) |
| `frontend/src/__tests__/AgentRuntimeMapCanvas.test.tsx` | **Extended**: loading/empty states, auto-fit, zoom, pan, grouping, connector, fullscreen, legend; cross-type parent/child adjacency, connector persistence under filter, delegated-child promotion to root, empty-state filter recovery; Communication Hub node and tool-call route colouring; **trigger-entity detail cards** (person card with name/count/list, schedule card with creator caption only when a creator exists, open/close/dismiss, filter-scoped lists, empty list without error); live-data round (alert on ANY `needs_intervention` node, trigger-source and latest-tool-call lines); canvas-polish round (grid dots cover the viewport in empty state and after panning/zooming beyond content, hub spans full canvas height with zero agents, initial fit of an over-large population not clamped by interactive min-zoom) |
| `frontend/src/__tests__/AgentDetailBubble.test.tsx` | **Extended**: detail + terminate + guardrail summary + dismissible; creator-only trigger provenance — schedule-triggered run shows the schedule creator's human name, never the schedule name in place of a person; unknown creator renders no person/trigger line |
| `frontend/src/__tests__/useRuntimeTopology.test.ts` | **Extended**: `needs_intervention` and default-visibility predicate; trigger-provenance and tool-call-history surfacing; fully-filtered empty state with a reset path; **real-time round** — pushed stream payload lands in the query cache immediately (new node renders with no polling request, no extra `GET /agents/runtime/topology` while the stream is healthy), stream error activates the polling fallback, recovery stops polling and resyncs the cache, unmount closes the `EventSource` and stops the fallback poller. (The stream transport is covered here; a sibling `useRuntimeTopologyStream.test.ts` was the conditional alternative and is skipped.) |
| `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx` | **Unchanged**: renders `VendorModelGuardrailPanel` readonly directly (panel moved off the monitor page) |
| `frontend/src/__tests__/RuntimeTopologyPanel.test.tsx` | **Left unchanged**: `RuntimeTopologyPanel` was not repurposed to host the canvas |
| `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` | **Left unchanged**: Agent Plan Preview component, unrelated to this change |

### E2E — `e2e/tests/`

| Test File | Covers |
|---|---|
| `e2e/tests/agent-runtime-monitor.spec.ts` | **Extended**: auto-fit, zoom, pan, fullscreen, grouping, delegation connector, alert → `InterveneResponseDialog`; delegation legibility (cross-type adjacency, connector persistence under filter, child promoted to root); empty-state filter recovery ("reset filters"); creator-only trigger provenance on tile/bubble; **trigger-entity describe block** (person card name/count/list, schedule card with creator caption only when a creator exists — mock payload includes a null-creator legacy schedule, row-click selects the execution, filter-scoped lists, dismiss/second-click closes); tool-call routes (hub node, latest-call per-agent colour, selection brightens history); **mocked-stream live-update block** (intercept the SSE endpoint via `page.route()`, emit one more execution, assert the new tile appears with no polling/refetch — count `GET /agents/runtime/topology` via the route handler; fallback variant: abort stream → topology GETs resume; recovery variant: stream unblocked → polling stops, pushed update lands); **canvas-polish assertions** (hub full-height on load with zero agents, grid dots across the viewport when panned beyond content, initial fit of a large mock population) |
| `e2e/tests/runtime-control-dashboard.spec.ts` | **Extended**: page rename to "Agent Runtime Monitor", map canvas, guardrail-panel absence, detail bubble + terminate (mock-first via `page.route()`); retains the real-backend topology/terminate smoke test |
| `e2e/tests/agent-runtime-monitor.real-backend.spec.ts` | **New**: `test.describe('Real Backend Integration - trigger provenance')` — no-mock variant asserting the live `GET /agents/runtime/topology` response carries trigger-provenance fields (`trigger_source`, `trigger_source_label`), the `tool_calls` list, and the boolean `needs_intervention` contract; only works when the `scheduled_by_user_id` migration is applied and provenance resolution is wired through; skips cleanly when `E2E_REAL_BACKEND_TOKEN` is unset or the backend is unreachable. Optional stream smoke (same skip contract): open the live SSE endpoint with the real token as a query param and assert an initial event arrives within the heartbeat window |
| `e2e/tests/conversation-intervention.spec.ts` | **Reuse (unchanged)**: confirms the intervention dialog flow still works; the monitor's alert click reaches this same dialog |

## 8. Out of Scope for Testing

- Visual/gesture aesthetics beyond the asserted contract points (zoom/pan feel, exact grid spacing) — covered by manual pass
- Changes to the `human_intervene` or terminate contracts themselves (reused as-is, verified via regression)
- The non-map runtime control dashboard features (recursion validation, guardrail hierarchy) — covered by `runtime-control-dashboard` coverage in [Agent Runtime Test Plan](agent-runtime-test-plan.md)
- Mobile/touch-optimised map gestures
- Multi-operator collaborative editing of the live map

## 9. Related Test Plans

- **[Agent Runtime Test Plan](agent-runtime-test-plan.md)** — Agent execution, sessions, roles/identities, model configs, guardrails, runtime control dashboard; the monitor page builds on this runtime stack
- **[Conversational Agent Intervention Test Plan](conversation-intervention-test-plan.md)** — The `InterveneResponseDialog` flow reused by the monitor's alert click
- **[Human Intervene Test Plan](human-intervene-test-plan.md)** — Non-conversational intervention state machine and the `needs_intervention` signal source
- **[Schedule Management Test Plan](scheduling-test-plan.md)** — `ScheduledJob` model and the `scheduled_by_user_id` provenance migration
- **[Frontend Test Plan](frontend-test-plan.md)** — Component test infrastructure conventions (React Query + MSW, `*.simple.test.tsx` workarounds)