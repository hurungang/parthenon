# Test Plan — Agent Runtime Monitor

## 1. Test Strategy

This change **does modify the database schema** (`has_db_changes: true`): `ScheduledJob` gains a nullable `scheduled_by_user_id` field. The DB-specific test-plan rules therefore apply in full (see "Pre-Test Checklist" and the real-backend E2E variant below). Testing spans **three backend/frontend capability groups** — (1) the pending-intervention signal, (2) trigger provenance, and (3) tool-call history via the Communication Hub — plus the **frontend map-canvas redesign** (including delegation legibility and empty-state filter recovery), across three automated layers plus a short manual pass.

| Layer | Scope | Primary targets |
|-------|-------|-----------------|
| **Unit (backend)** | Controller/serialization logic + scheduling/dispatch logic | `RuntimeTopologyController`, `RuntimeTopologyNodeRead`, `SchedulingEngine._dispatch`, `GatewayLifecycleHandler.launch` |
| **Unit (frontend)** | Component/hook behavior with mocked data | `AgentRuntimeMapCanvas`, `AgentDetailBubble`, `useRuntimeTopology`, page composition |
| **Integration (API/DB)** | Endpoint contract + **schema-change verification** | `get_runtime_topology` handler + `RuntimeTopologyRead`; `scheduled_jobs.scheduled_by_user_id` column properties |
| **E2E** | Full user flows on the live page, mock-first with **one real-backend variant for the schema change** | page rename, map interactions, delegation legibility, filter recovery, trigger provenance, tool-call routes, alert → intervene, terminate |
| **Manual** | Visual/gesture verification impractical to assert in code | zoom/pan feel, auto-fit, fullscreen, grid/grouping legibility, per-agent route colouring |

**Key testing principles for this change:**
- **Contract correctness first**: `needs_intervention` must be `true` for a node with a pending `InterveneRequest` (status `pending`) and `false` otherwise, with `false` as the safe default for backwards compatibility.
- **Trigger provenance is a data-integrity chain, not just a label**: `ScheduledJob.scheduled_by_user_id` → `SchedulingEngine._dispatch` → `GatewayLifecycleHandler.launch` → `AgentJob.triggered_by_user_id` → (delegated child inherits) → `RuntimeTopologyController` resolves a human-readable trigger source. Each hop must be tested independently and end-to-end.
- **Tool-call history is derived, not stored**: the topology endpoint must map namespaced tool names (`server____tool` via `parse_tool_name`) to MCP server slugs, preserving per-node ordering so the frontend can highlight the latest call.
- **Visibility predicate is the critical frontend rule**: a sleeping agent awaiting intervention is shown by default; a sleeping agent *not* awaiting intervention stays hidden.
- **Empty-state recovery is a hard requirement**: the filter/legend toolbar must remain usable when a filter combination hides every node, and "reset filters" must restore visibility without a page reload.
- **Removal is a feature**: verify `VendorModelGuardrailPanel` and the retired `RuntimeTopologyDiagram` no longer render on the page.
- **Reuse is verified, not re-implemented**: terminate and intervene flows are used as-is; tests confirm they still open/complete.

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
- **Resolution**: `RuntimeTopologyController` returns a trigger source per node — a user's display name (direct user trigger or inherited delegation) or the schedule name (schedule trigger).

### Backend — tool-call history via Communication Hub (new)
- Topology node carries a per-node tool-call history list (tool name + MCP server slug + timestamp, ordered).
- Tool calls are read from `ToolCallRecord` (via `ConversationTurn` → `ConversationSession`, and/or `AgentJob.conversation_history`).
- Namespaced tool names are split (`parse_tool_name`) and resolved to `McpServer` slugs so routes can be drawn agent → Communication Hub → MCP server.

### API contract — `GET /agents/runtime/topology`
- Response model `RuntimeTopologyRead` still serializes nodes/edges/roots; each node now includes `needs_intervention`, trigger-provenance fields (trigger source + label), and a tool-call route list.
- No route changes, no query-parameter changes, no removed fields (backwards-compatible additions).

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

### Agent detail bubble (`AgentDetailBubble`)
- Inline bubble beside the selected node: detail + terminate + guardrail summary; dismissible.
- **Trigger provenance (new)**: the bubble shows who triggered the agent (user name or schedule name).

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
- **WHEN** a schedule has no `scheduled_by_user_id` (legacy/NULL) **THEN** the launched `AgentJob` keeps `triggered_by_user_id` NULL and the topology node does not crash resolving provenance.
- **WHEN** an agent delegates to a child agent **THEN** the child `AgentJob.triggered_by_user_id` equals its parent's `triggered_by_user_id`.
- **WHEN** a node was directly user-triggered **THEN** the topology node returns that user's display name as the trigger source.
- **WHEN** a node was schedule-triggered **THEN** the topology node returns the schedule **name** (not the scheduled-by user name) as the trigger source.
- **WHEN** a node was delegated **THEN** the topology node returns the parent's trigger source (the original user's display name).

### Backend — tool-call history
- **WHEN** an agent has recorded tool calls **THEN** the topology node returns a per-node tool-call list with, per call: tool name, MCP server slug, and timestamp, in chronological order.
- **WHEN** a namespaced tool name `server____tool` is resolved **THEN** the tool-call entry carries the tool name (`tool`) and the MCP slug (`server`).
- **WHEN** a tool-call references an MCP slug with no matching `McpServer` **THEN** the entry still returns (slug preserved, no server dropped) and the frontend renders a graceful route.
- **WHEN** an agent has made no tool calls **THEN** the node returns an empty tool-call list (no error, no phantom route).

### Frontend — visibility predicate
- **WHEN** a node is a conversation/instance with runtime status `sleep` and `needs_intervention` is `true` **THEN** it is rendered by default with an alert icon.
- **WHEN** a node is `sleep` and `needs_intervention` is `false` **THEN** it remains hidden by default (excluded from the map).
- **WHEN** a node is active (running/queued) **THEN** it is rendered regardless of `needs_intervention`.

### Frontend — trigger provenance display
- **WHEN** a node is user- or delegation-triggered **THEN** the agent tile and the detail bubble show the triggering user's name.
- **WHEN** a node is schedule-triggered **THEN** the agent tile and the detail bubble show the schedule name.

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
- **Schedule dispatch provenance gaps** — a schedule with `NULL` `scheduled_by_user_id`, or a schedule whose owning identity was deleted, must not crash launch or topology resolution; the trigger source must degrade to an empty/unknown label, not an exception.
- **Delegation chain depth** — a multi-level delegation chain must propagate the original trigger user all the way down (child of child), not just one level; a missing/loop parent must not cause infinite recursion.
- **Delegation vs filter interplay** — filtering out a parent must promote the child to a root; filtering out a child must not hide the parent; filtering both must keep the empty-state toolbar usable.
- **Tool-call ordering & latest-call highlighting** — ordering must be timestamp-stable (no ties flipping the highlighted call); an agent with a single call has that call as "latest"; an agent with zero calls draws no route and no phantom latest-call highlight.
- **MCP slug resolution** — a tool name without a `server____` namespace, an unknown slug, or a slug whose `McpServer` is inactive/deleted must not drop the call or crash the route renderer; the route should still terminate at the hub with a degraded label.
- **i18n completeness** — any hardcoded "topology", trigger-source, or new label bypassing `t()` is a defect; verify no user-facing string is hardcoded.
- **Accessibility** — zoom/pan/fullscreen/alert/dismiss/filter controls must be keyboard- and ARIA-reachable; alert state and latest-call highlighting must be conveyed beyond colour/icon alone (the per-agent colour and grey-vs-bright distinction need a non-colour cue).
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

### Trigger Provenance
- [ ] `ScheduledJob.scheduled_by_user_id` migration applied; column exists (nullable uuid FK → Identity) — **backend integration (schema) + real-backend E2E**
- [ ] Schedule dispatch passes `scheduled_by_user_id` through to the launched `AgentJob.triggered_by_user_id` — **backend unit**
- [ ] Delegated child inherits `triggered_by_user_id` from its parent — **backend unit**
- [ ] Topology node returns trigger source: user name (direct/delegated) or schedule name — **backend unit + API integration**
- [ ] Agent tile and detail bubble show who triggered the agent — **frontend unit + E2E**

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

Test paths follow `docs/config.yaml` → `source.tests`. Entries marked **new** cover the four refinements and the schema change; existing coverage is retained.

### Backend (`backend/tests/`)
- `backend/tests/unit/services/test_runtime_topology_controller.py` — **extended**: existing `needs_intervention` cases remain; trigger-provenance resolution (user name for direct/delegated nodes, schedule name for schedule-triggered nodes); per-node tool-call history derivation (tool name + MCP slug + timestamp, chronological order; empty list when no calls); plus **live-data round**: terminal direct children of included jobs appear with the delegation edge (budget-capped by `max_nodes`, no fetch when the budget is exhausted), `waiting_for_human` backing jobs keep conversations `active`, and chat-spawned linked jobs (`input_data.__conv_session_id`) count as live drivers (terminal linked jobs keep `sleep`).
- `backend/tests/unit/test_scheduling.py` — **extended** (top-level `unit/`, not `unit/services/`): `SchedulingEngine._dispatch` passes `scheduled_by_user_id` into `GatewayLifecycleHandler.launch` (`user_id` argument); a `NULL` scheduled-by does not crash dispatch.
- `backend/tests/unit/test_agent_session_service.py` — **extended**: delegated child inherits `triggered_by_user_id` from its parent (`parent_job_id`), including explicit-user-wins and missing-parent-degradation cases; the launch→enqueue `user_id` forwarding is covered by the pre-existing `test_lifecycle_handler.py::test_launch_passes_user_id_to_session_service`. Four listing/get cases remain skipped (pre-existing, unrelated to this change).
- `backend/tests/integration/api/test_runtime_topology_api.py` — **extended**: retains the `needs_intervention` contract cases; asserts `RuntimeTopologyRead.nodes[*]` carries trigger-provenance fields (`trigger_source`, `trigger_source_label`) and a tool-call route list, with existing node fields unchanged; plus **live-data round**: `waiting_for_human` jobs are returned in the default live view, terminal direct children of an included parent appear with the delegation edge, and a chat-spawned linked job keeps its conversation `active` with a conversation → job edge. Uses module-scoped StaticPool in-memory SQLite.
- `backend/tests/integration/db/test_scheduled_job_schema.py` — **new**: DB-specific schema verification. Creates the schema via `Base.metadata.create_all` on an in-memory SQLite (the declarative model defines the column); asserts `scheduled_jobs.scheduled_by_user_id` exists, is nullable, is a `UUID`, and has an FK to `identities.id` (via SQLAlchemy inspector); inserts a schedule with and without `scheduled_by_user_id` and verifies both persist; existing/legacy rows retain `NULL`.

### Frontend (`frontend/src/__tests__/`) — full suite green
- `frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx` — **updated**: retains "Agent Runtime Monitor" title, absence of `VendorModelGuardrailPanel`, presence of the mocked `AgentRuntimeMapCanvas` as the primary view, no user-facing "topology" label; adds a second describe block asserting the "awaiting intervention" indicator when a node carries `needs_intervention: true` (the Communication Hub visible-node presence is covered by `AgentRuntimeMapCanvas.test.tsx`).
- `frontend/src/__tests__/AgentRuntimeMapCanvas.test.tsx` — **extended**: retains loading/empty states, auto-fit, zoom, pan, grouping, connector, fullscreen, legend; adds cross-type parent/child adjacency, connector persistence when unrelated nodes are filtered out, delegated-child promotion to root when the parent is filtered out, empty-state filter recovery (toolbar/legend usable + "reset filters" restores nodes), Communication Hub node, and tool-call route colouring (latest per-agent colour, older grey, brightened on selection); plus **live-data round**: the intervention alert renders on ANY `needs_intervention` node (a `waiting_for_human` agent-kind node and a sleeping conversation-kind node both flagged; no alert without the flag; alert click invokes the intervention flow with the node), and the tile renders the trigger-source line and the latest-tool-call line (omitted without calls).
- `frontend/src/__tests__/AgentDetailBubble.test.tsx` — **extended**: retains detail + terminate + guardrail summary + dismissible; adds trigger-provenance display (user name / schedule name).
- `frontend/src/__tests__/useRuntimeTopology.test.ts` — **extended**: retains `needs_intervention` and default-visibility predicate; adds trigger-provenance and tool-call-history surfacing onto nodes, and filter state that yields the fully-filtered empty state with a reset path.
- `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx` — **unchanged**: renders `VendorModelGuardrailPanel readonly` directly (panel moved off the monitor page).
- `frontend/src/__tests__/RuntimeTopologyPanel.test.tsx` — **left unchanged**: `RuntimeTopologyPanel` was not repurposed to host the canvas.
- `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` — **left unchanged**: Agent Plan Preview component, unrelated to this change.

### E2E (`e2e/tests/`)
- `e2e/tests/agent-runtime-monitor.spec.ts` — **extended**: retains auto-fit, zoom, pan, fullscreen, grouping, delegation connector, alert → `InterveneResponseDialog`; adds delegation legibility (cross-type adjacency, connector persistence under filter, child promoted to root), empty-state filter recovery ("reset filters"), trigger provenance on tile/bubble, and tool-call routes (Communication Hub node, latest-call per-agent colour, selection brightens history). Mock payloads already carry `needs_intervention`, trigger provenance, and `tool_calls`, so no mock changes were required for the live-data round.
- `e2e/tests/runtime-control-dashboard.spec.ts` — **extended**: retains page rename, map canvas, guardrail-panel absence, detail bubble + terminate (mock-first via `page.route()`); retains the real-backend topology/terminate smoke test.
- `e2e/tests/agent-runtime-monitor.real-backend.spec.ts` — **new**: `test.describe('Real Backend Integration - trigger provenance')`. A no-mock variant that asserts the live `GET /agents/runtime/topology` response carries the trigger-provenance fields (`trigger_source`, `trigger_source_label`) plus the `tool_calls` list and the boolean `needs_intervention` contract — which only works if the `scheduled_by_user_id` migration is applied and the provenance resolution layer is wired through. Skips cleanly when `E2E_REAL_BACKEND_TOKEN` is unset or the backend is unreachable.
- `e2e/tests/conversation-intervention.spec.ts` — **reuse (unchanged)**: confirms the intervention dialog flow still works; the monitor's alert click reaches this same dialog.

---

## Execution Notes

- **Database change** (`has_db_changes: true`): run `python -m alembic current` to confirm the `scheduled_by_user_id` migration is applied; if not, `python -m alembic upgrade head` before any test run (see Pre-Test Checklist). Backend integration fixtures apply migrations in setup.
- Run the full suite via `/test-app` (backend, frontend, E2E) after implementation; all three layers must pass, including the real-backend schema-change E2E variant.
- Reuse patterns from the existing referenced test files (mock topology payloads, `react-i18next` mock, `standardSetup` E2E helper).
- Test data for new fixtures should use identifiable IDs (e.g. `sess-awaiting-intervention`, `sess-sleep-hidden`, `sched-by-user`, `sched-by-null`) so assertions on default visibility and trigger provenance are unambiguous.
