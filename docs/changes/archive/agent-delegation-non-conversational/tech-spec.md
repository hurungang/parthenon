# Tech Spec: Agent Delegation Visibility & HITL for Non-Conversational Agents

## Technical Overview

Non-conversational (task) agents in Parthenon already delegate to sub-agents using the `agent____<slug>` tool call routed through `backend/app/agent_runtime/comm_hub_client.py` → Communication Hub → Control Center → Agent Runtime. However, the task agent execution loop in `backend/app/services/agents/runtime_executor.py` does not emit delegation status events (`delegating`, `waiting`, `delegation_resumed`) that the conversational loop already emits, and Human-in-the-Loop intervention requests from delegated sub-agents are not surfaced in the task agent's execution log. This change adds status event emission to the task loop, enforces a 1-level delegation depth limit via a new guard, routes non-conversational delegation events and intervention requests through a new CH Task Delegation Event Router, and extends the frontend execution log viewer to render delegation timelines and inline intervention dialogs. Conversational agent delegation and HITL paths are preserved unchanged — all changes are additive.

**Key design decisions**:
- Reuse existing delegation status event infrastructure from `_run_conversational_loop()` — the task agent `_act()` method is extended to call the same event emission pattern.
- Enforce depth limit at the Agent Runtime level using existing `RuntimeGuardrailState.delegation_depth` and `max_delegation_depth` fields — override `max_delegation_depth` to 1 for non-conversational agents in `_build_guardrail_state()`.
- Route non-conversational events through CC's existing live log stream NDJSON endpoint (`GET /api/v1/agent-jobs/{session_id}/logs/stream`) — CH writes events to CC's execution log store, and the stream poll loop picks them up.
- Frontend inline intervention dialog reuses the existing `InterveneResponseDialog` component pattern but renders inline within the log timeline instead of as a separate modal.
- Inject output type formatting instructions into the system prompt during `_format_user_prompt()` so the LLM respects the agent's configured `output_type` at runtime, rather than leaving it as passive metadata.

---

## Component Breakdown

### Backend Components

#### 1. Delegation Depth Guard (Agent Runtime — modified)

**Responsibility**: Reject delegation tool calls from non-conversational agents when the current delegation depth is at or exceeds the limit (1 level).

**Location**: `backend/app/services/agents/runtime_executor.py`
- `_build_guardrail_state()` — override `max_delegation_depth` to 1 for non-conversational agents.
- `_act()` (task agent path, ~line 3368) — pre-dispatch depth check before `call_a2a_request()`.

**Behaviour**:
- Parent agent (depth 0) delegates → allowed.
- Sub-agent (depth 1) attempts to delegate → blocked; `delegation_depth_blocked` log event emitted; tool result returns blocked outcome.
- Conversational agents continue using policy-defined `max_delegation_depth` (default 3).
- Checked server-side in Agent Runtime — cannot be bypassed from frontend.

#### 2. Task Agent Delegation Status Emitter (Agent Runtime — modified)

**Responsibility**: Emit delegation lifecycle events from the non-conversational agent execution loop.

**Location**: `backend/app/services/agents/runtime_executor.py`
- `_act()` — delegation branch at the `_extract_agent_delegation_target()` check.
- `_log_execution_event()` — used for persisting new delegation event types.

**Event types emitted**:
- `delegation_started` — before `call_a2a_request()` with `wait_for_response=True`.
- `delegation_waiting` — after A2A request is dispatched, sub-agent is executing.
- `delegation_resumed` — after A2A request returns (includes exit condition: completed/timeout/failed).
- `delegation_depth_blocked` — when depth guard blocks a delegation attempt.
- `delegation_timeout` — when `call_a2a_request()` returns a timeout response.
- `delegation_failed` — when `call_a2a_request()` returns an error response.
- `intervention_required` — when a delegated sub-agent enters `waiting_for_human` status and the parent must pause.

#### 3. Task Agent HITL Suspender (Agent Runtime — modified)

**Responsibility**: Suspend the parent task agent execution when a delegated sub-agent calls `system____human_intervene`, and propagate the intervention context back through CH to the execution log viewer.

**Location**: `backend/app/services/agents/runtime_executor.py` — `_act()` delegation branch; `backend/app/agent_runtime/comm_hub_client.py` — `call_a2a_request()` return value inspection.

**Behaviour**:
- When `call_a2a_request()` detects sub-agent entered `waiting_for_human` status:
  - Parent `AgentJob.status` → `waiting_for_human` (via CC session status update).
  - An `intervention_required` event with intervention context (type, reason, choices, sub-agent name, parent `agent_job_id`) is emitted to the execution log.
- When operator responds, parent resumes and sub-agent receives the response as tool return value.

#### 4. Task Delegation Event Router (Communication Hub — new)

**Responsibility**: Route non-conversational delegation status events and intervention requests to execution log viewer clients.

**Location**: `backend/app/communication_hub/services/task_delegation_router.py` (new file).

**Public interface**:
- `register_viewer(agent_job_id: str, channel_identifier: str) -> None`
- `unregister_viewer(agent_job_id: str, channel_identifier: str) -> None`
- `push_event(agent_job_id: str, event: dict) -> None` — for delegation status events.
- `push_intervene_request(agent_job_id: str, payload: dict) -> None` — for intervention requests.
- `is_viewer_connected(agent_job_id: str) -> bool`

**Behaviour**:
- Maintains in-memory map of `agent_job_id` → set of active viewer channel IDs.
- Events are injected into CC's execution log store (via `ControlCenterDataClient`), so the existing NDJSON stream poll loop (`stream_session_execution_logs`) delivers them.
- Falls back to poll-based delivery when no live viewer is connected (events are persisted and picked up on next poll).

#### 5. Intervention Router — Non-Conversational Path Extension (Communication Hub — modified)

**Responsibility**: Detect non-conversational context in intervention requests and fall through to the dashboard flow instead of routing to the conversational WebSocket.

**Location**: `backend/app/communication_hub/intervention_router.py` — `route_intervention_signal()` method; `backend/app/communication_hub/api/internal/tool_routing.py` — `human_intervene` handler.

**Behaviour**:
- CH's `InterventionRouter.route_intervention_signal()` inspects each `human_intervene` signal for `conversation_session_id`.
- When `conversation_session_id` is absent (non-conversational delegation context): returns `False`, causing the request to fall through to CC's existing dashboard flow where an `InterveneRequest` is created. The live log stream then picks up the `human_intervene` event and delivers it to execution log viewers.
- When `conversation_session_id` is present (conversational context): routes via `ActiveSessionTracker.send_to_session()` to the WebSocket client (unchanged).
- The `TaskDelegationEventRouter.push_intervene_request()` directly persists `human_intervene` log events to CC's execution log store for delivery via the NDJSON stream.

#### 6. Intervention Request Persistence — Non-Conversational Context (Control Center — unchanged)

**Responsibility**: Persist and query intervention requests from non-conversational delegation context using existing schema relationships.

**Location**: `backend/app/services/agents/intervene_service.py` — `create_request()`; `backend/app/db/models/intervene.py` — `InterveneRequest` model.

**Behaviour**:
- No database schema changes were required (`has_db_changes: false` in `.change.yaml`).
- `InterveneRequest.agent_session_id` already identifies the sub-agent's session. The parent task agent's session is found via `AgentJob.parent_job_id` FK chain (`InterveneRequest → agent_session_id → AgentJob → parent_job_id → parent AgentJob`).
- `create_request()` continues using the same signature — the parent context is carried through the runtime event flow (not persisted as a separate column).
- Pending intervention querying for non-conversational context uses the existing `interveneApi.getInterveneRequest()` + the new `GET .../interventions/pending` endpoint which returns outstanding requests by `agent_job_id` (the parent session).

#### 7. Output Type Prompt Injector (Agent Runtime — modified)

**Responsibility**: Inject output format instructions into the system prompt for non-conversational agents based on the agent type's `output_type` configuration.

**Location**: `backend/app/services/agents/runtime_executor.py` — `_format_user_prompt()` (lines ~3676–3727).

**Behaviour**:
- When `output_type == "markdown"`: append an instruction to produce output in markdown format.
- When `output_type == "typed"` and `output_schema` is present: append an instruction to produce structured JSON matching the schema, including the schema itself as context.
- When `output_type == "auto"`: no additional output format instruction added.
- The injected instruction is appended to the existing system prompt before the first LLM call.
- Does not affect conversational agents (existing behaviour preserved).

---

### Frontend Components

#### 7. Delegation Timeline (Execution Log — new)

**Responsibility**: Render a colour-coded vertical timeline of delegation lifecycle events within the execution log view.

**Location**: `frontend/src/components/executions/DelegationTimeline.tsx` (new file).

**Props**: `entries: ExecutionLogEntry[]` — the full log entry list; the component filters for delegation event types internally.

**Visual design reference**: `docs/changes/agent-delegation-non-conversational/prototype/index.html` — `.log-event.ev-delegating`, `.ev-waiting`, `.ev-resumed`, `.ev-blocked` CSS classes and the `.delegation-card` sub-agent inline card.

**Behaviour**:
- Filters entries by event types: `delegation_started`, `delegation_waiting`, `delegation_resumed`, `delegation_depth_blocked`, `delegation_timeout`, `delegation_failed`.
- Each event renders with: timestamp, colour-coded icon (purple=delegating, amber=waiting, green=resumed, red=blocked/error), event type label, message, extra metadata.
- Sub-agent inline card during active delegation: shows agent name, running/completed/failed state chip, animated loading bar during delegating/waiting.
- Updates in real time as new entries arrive from the live stream.

#### 8. Task Intervention Dialog (Execution Log — new)

**Responsibility**: Render an inline intervention response UI within the execution log event stream (not a separate modal).

**Location**: `frontend/src/components/executions/TaskInterventionDialog.tsx` (new file).

**Props**: `request: InterveneRequest`, `onSubmit: (value) => Promise<void>`, `onDismiss: () => void`, `expired?: boolean`.

**Visual design reference**: `docs/changes/agent-delegation-non-conversational/prototype/index.html` — `.intervene-inline` with header, body (approval buttons / choice radio / text textarea), and footer.

**Behaviour**:
- Three response modes based on `request.intervention_type`:
  - **approval**: Approve (green full-width) and Deny (red outlined) buttons.
  - **choice**: Radio-button list with selectable options, Submit button.
  - **text**: Textarea with Submit button.
- Resolved state: shows "Response submitted" with greyed-out disabled UI.
- Expired state: shows "Request no longer valid" overlay, all controls disabled.

#### 9. Intervention Pending Banner (Execution Log — new)

**Responsibility**: Persistent sticky banner at the top of the execution log when an intervention request is pending but not visible (dialog dismissed or scrolled out of view).

**Location**: `frontend/src/components/executions/InterventionPendingBanner.tsx` (new file).

**Props**: `pending: boolean`, `subAgentName: string`, `interventionType: string`, `pendingSince: string`, `onRespond: () => void`.

**Visual design reference**: `docs/changes/agent-delegation-non-conversational/prototype/index.html` — `.iv-pending-banner` with animated spinner, banner title, subtitle, and "Respond Now" button.

**Behaviour**:
- Visible when `pending` is true and the inline dialog is not visible.
- "Respond Now" button calls `onRespond` which scrolls to and focuses the inline dialog in the timeline.
- Automatically hides when `pending` becomes false (intervention responded or expired).

#### 10. Updated LogPresenter (Frontend — modified)

**Responsibility**: Recognize and correctly map the new delegation event types in the structured log output.

**Location**: `frontend/src/services/LogPresenter.ts`.

**Changes**:
- `iconTypeFromEntry()` — add mappings for `delegation_started` → 'delegating', `delegation_waiting` → 'waiting', `delegation_resumed` → 'success', `delegation_depth_blocked` → 'error', `delegation_timeout` → 'error', `delegation_failed` → 'error'.
- `buildSpans()` — classify delegation events to appear within the "Agent Actions" span, grouped under the iteration where they occur.
- New event types are NOT added to `PREPARATION_EVENT_TYPES` or `COMPLETION_EVENT_TYPES` — they belong in the agent-actions iteration span.

#### 11. Updated AgentExecutionDetailsDialog (Frontend — modified)

**Responsibility**: Integrate the new DelegationTimeline, TaskInterventionDialog, and InterventionPendingBanner into the execution log tab.

**Location**: `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx`.

**Changes**:
- Render `DelegationTimeline` below or alongside `LogViewer` in the execution tab.
- When `humanInterveneEvent` fires from `useSessionExecutionLogStream`, show `TaskInterventionDialog` inline at the intervention event position instead of (or in addition to) the existing modal `InterveneResponseDialog`.
- Show `InterventionPendingBanner` when an intervention is pending and the inline dialog is dismissed/scrolled away.
- On dialog open and reconnect: query `GET .../interventions/pending` to re-surface outstanding dialogs.

#### 12. Output-Type Result Tab (Execution Log — new)

**Responsibility**: Render the agent's execution output formatted according to the agent type's `output_type` definition in a dedicated Result tab within the execution log details dialog.

**Location**: `frontend/src/components/executions/OutputTypeResultTab.tsx` (new file).

**Visual design reference**: `docs/changes/agent-delegation-non-conversational/prototype/index.html` — the "Result" tab section showing formatted output.

**Behaviour**:
- Reads `output_type` from the session's agent type metadata (available via existing `GET /agents/sessions/{id}` response).
- Three rendering modes based on `output_type`:
  - **markdown**: Parses `output_data.markdown` or `output_data.result` as markdown and renders as rich formatted HTML. Uses the existing markdown rendering approach from `AgentJobPage` (parse markdown, render with `dangerouslySetInnerHTML`).
  - **typed**: Renders `output_data` as a structured JSON tree view with expandable/collapsible nodes. Shows a "Schema" toggle to display the `output_schema` alongside the result for validation comparison.
  - **auto**: Renders `output_data` as raw formatted JSON in a `<pre>` block.
- Tab label includes an output type badge (e.g., "Result [Markdown]", "Result [Typed]", "Result [Auto]").
- The tab is only visible when the session is in a terminal state (completed, failed, terminated) — same condition as the existing Result tab.
- Integrates into `AgentExecutionDetailsDialog` alongside the existing Execution and History tabs.

---

## API Changes

### New Endpoints (Control Center)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/agent-jobs/{session_id}/interventions/pending` | Return the currently pending intervention request for a task agent session, if any. Returns `InterveneRequest` with type, reason, choices, requesting sub-agent. Used by frontend on reconnect to re-surface intervention dialogs. |
| `GET` | `/api/v1/agent-jobs/{session_id}/delegation/status` | Return current delegation status: active sub-agent types, depths, exit conditions. Queries recent delegation-related `ExecutionLogEntry` entries. Used by frontend to render the delegation timeline on initial load. |

### Changed Endpoints

| Method | Path | Change Description |
|--------|------|--------------------|
| `GET` | `/api/v1/agent-jobs/{session_id}/logs/stream` | Now emits delegation-related `ExecutionLogEntry` events with event types: `delegation_started`, `delegation_waiting`, `delegation_resumed`, `delegation_depth_blocked`, `delegation_timeout`, `delegation_failed`, `intervention_required`. The existing `human_intervene` event type already works but will now also trigger from non-conversational delegation context. |
| `POST` | `/api/v1/internal/data/sessions/{session_id}/log` | Accepts the six new delegation event types in addition to existing event types. |
| `POST` | `/api/v1/interventions/` | Accepts requests from non-conversational delegation context (using existing `agent_session_id` field — no new schema changes). |
| `POST` | `/api/v1/internal/a2a/request` | A2A response payload now includes delegation status context (`waiting_for_human` flag, intervention request ID, sub-agent session ID) for non-conversational callers. |

### New Internal Events (Agent Runtime → Communication Hub)

| Event Type | Direction | Payload |
|------------|-----------|---------|
| `delegation_status` | AR → CH | `{status: "started"|"waiting"|"resumed"|"blocked"|"timeout"|"failed", agent_type: string, depth: int, session_id: string, parent_agent_job_id?: string}` |
| `human_intervene` (delegation context) | CH → Log Viewer (via NDJSON stream) | `{event_type: "human_intervene", request_id: string, intervention_type: string, reason: string, choices?: string[], sub_agent_type: string, agent_job_id: string}` — the existing stream event type, now also triggered by non-conversational delegation context. Non-conversational interventions fall through CH's `InterventionRouter` (no `conversation_session_id`) to CC's existing intervention creation flow, and the NDJSON stream emits the `human_intervene` event. |
| `intervention_required` | AR → Execution Log | `{event_type: "intervention_required", request_id: string, intervention_type: string, reason: string, choices?: string[], sub_agent_type: string}` — emitted by `runtime_executor.py` when a delegated sub-agent enters `waiting_for_human` status. Persisted as an execution log event. |

---

## State Management

### Backend State

- **Delegation depth tracking**: `RuntimeGuardrailState.delegation_depth` (existing field, now enforced at max 1 for non-conversational agents). Incremented in `_act()` when a delegation tool call proceeds.
- **Session status for HITL**: `AgentJob.status` transitions to `waiting_for_human` when a delegated sub-agent requests intervention. Transitioned back to `running` by the existing intervention response handling in CC.
- **Intervention pending state**: `InterveneRequest.status` (`pending` → `responded`/`expired`). Existing lifecycle unchanged — pending interventions for non-conversational context are queried via the new `GET .../interventions/pending` endpoint by parent `agent_job_id`.
- **Task Delegation Event Router connections**: In-memory map `dict[str, set[str]]` mapping `agent_job_id` → viewer channel IDs. Ephemeral — cleared on CH restart, viewers reconnect.

### Frontend State

- **Execution log entries**: `logEntries: ExecutionLogEntry[]` in `AgentExecutionDetailsDialog` — merged from initial fetch + streamed entries via `useSessionExecutionLogStream`. Existing pattern, now includes delegation event types.
- **Stream connection state**: `ExecutionLogStreamConnectionState` in `useSessionExecutionLogStream` — `'idle' | 'connecting' | 'connected' | 'reconnecting' | 'fallback'`. Existing pattern, unchanged.
- **Human intervene event**: `humanInterveneEvent: HumanInterveneEvent | null` in `useSessionExecutionLogStream`. Existing pattern — now also fires for non-conversational delegation interventions (already supported by stream endpoint when `AgentJobStatus.waiting_for_human` is detected).
- **Intervention dialog state**: `autoDialogOpen: boolean`, `autoDialogRequest: InterveneRequest | null` in `AgentExecutionDetailsDialog`. Existing pattern — now supplemented by inline `TaskInterventionDialog` state.
- **Pending banner visibility**: `pendingBannerVisible: boolean` derived from intervention event presence and dialog dismissal. New state — managed locally in the execution log tab.
- **Delegation timeline data**: Derived from `logEntries` filtered by delegation event types. No separate fetch — computed from existing log entry list.

---

## Data Access Patterns

### Server-Side (Control Center — sole database accessor)

- **Execution log events**: Written by AR via `POST /api/v1/internal/data/sessions/{session_id}/log` (CC internal endpoint). Read by frontend via `GET /api/v1/agent-jobs/{session_id}/logs` and the NDJSON stream `GET .../logs/stream`. All delegation events follow this pattern — AR never writes to DB directly.
- **Intervention requests**: Written by CC's `InterveneRequestStore.create_request()` (called by CH on behalf of AR). Read by frontend via `interveneApi.getInterveneRequest()` (existing) and the new `GET .../interventions/pending` endpoint. AR never touches the intervene table.
- **Delegation status query**: New `GET .../delegation/status` endpoint queries `ExecutionLogEntry` filtered by delegation event types, ordered by timestamp. Read-only, uses existing session log model. No new DB columns required — the parent-child relationship is resolved via `AgentJob.parent_job_id` FK.

### Client-Side (Frontend — REST + NDJSON Stream)

- **Initial load**: `GET /api/v1/agent-jobs/{session_id}/logs` fetches all log entries (including previously persisted delegation events).
- **Live stream**: `useSessionExecutionLogStream` hook connects to NDJSON `GET .../logs/stream`, receiving `log_entry`, `human_intervene`, and `stream_completed` event types. Delegation events arrive as `log_entry` type entries with the new event_types.
- **Intervention response**: `POST /api/v1/interventions/{request_id}/respond` (existing endpoint) — submits operator response. Works for both conversational and non-conversational intervention requests.
- **Reconnect recovery**: `GET .../interventions/pending` (new endpoint) on dialog open/reconnect to check for outstanding interventions.

### Inter-Service (Agent Runtime → Communication Hub → Control Center)

- **Delegation tool calls**: AR → CH via `CommHubToolClient.call_a2a_request()` (HTTPS with mTLS). CH resolves receiver, spawns sub-agent via CC, waits for result via Redis pub/sub.
- **Delegation status events**: AR → CH via internal log event write to CC's execution log store. CH's `TaskDelegationEventRouter` detects non-conversational context and ensures events reach the correct log viewer stream.
- **Intervention requests**: AR (sub-agent) → CH via `CommHubToolClient.call_human_intervene()`. CH → CC via `InterveneRequestStore.create_request()`. CC → frontend via NDJSON stream `human_intervene` event. For non-conversational context, CH's `InterventionRouter` detects no `conversation_session_id` and falls through to the dashboard flow (existing `InterveneRequest` creation); the parent session's NDJSON stream picks up the event.
- **Intervention responses**: Frontend → CC via `POST /interventions/{id}/respond`. CC → CH via signal to resume sub-agent. CH → AR via response injection into sub-agent's tool return value.

### Service Boundaries Preserved

- AR never accesses the database directly — all delegation state persistence via CC internal endpoints.
- AR never receives user identity tokens — intervention responses are injected as tool return values.
- AR certificate validation unchanged — only `service:communication-hub` mTLS on internal endpoints.
- Conversational delegation path unchanged — new non-conversational path is additive.

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRuntimeExecutor` | class | Orchestrates agent execution via LangChain observe-reason-act loop for both task and conversational agents | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._act()` | method | Dispatch pending tool calls with permission enforcement; delegation branch emits status events | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._run_task_loop()` | method | Execute a task agent via the LangChain observe-reason-act loop; creates `TaskAgentLoop` context | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._run_conversational_loop()` | method | Execute a conversational agent loop via WebSocket; existing delegation status event emitter | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._execute_job()` | method | Orchestrate execution by loading agent type, resolving permissions, and dispatching to task or conversational loop | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._build_guardrail_state()` | method | Build `RuntimeGuardrailState` from resolved context policy snapshot; overrides `max_delegation_depth` for non-conversational agents | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._log_execution_event()` | method | Persist an execution log event via CC internal data API | `backend/app/services/agents/runtime_executor.py` |
| `_extract_agent_delegation_target()` | function | Extract delegated target slug when tool_name is `agent____<slug>` | `backend/app/services/agents/runtime_executor.py` |
| `_build_delegation_request_payload()` | function | Build A2A request payload from dynamic agent tool args | `backend/app/services/agents/runtime_executor.py` |
| `HumanInterveneRequired` | exception | Raised when the agent calls `human_intervene`, signalling execution should pause | `backend/app/services/agents/runtime_executor.py` |
| `TaskAgentLoop` | class | Execution context for task-based (non-conversational) agent runs | `backend/app/services/agents/agent_loop.py` |
| `ConversationalAgentLoop` | class | Execution context for conversational (multi-turn) agent sessions | `backend/app/services/agents/agent_loop.py` |
| `AgentLoopContext` | class | Base execution context shared by both task and conversational loops | `backend/app/services/agents/agent_loop.py` |
| `RuntimeGuardrailState` | class | Mutable runtime counters for execution loops: iterations, delegation depth, delegated steps, token usage | `backend/app/services/agents/guardrails.py` |
| `GuardrailStop` | exception | Exception for terminal guardrail enforcement decisions (depth exceeded, timeout, etc.) | `backend/app/services/agents/guardrails.py` |
| `GuardrailStopReason` | class | Canonical guardrail stop reason taxonomy (CYCLE_DETECTED, DELEGATION_DEPTH_EXCEEDED, etc.) | `backend/app/services/agents/guardrails.py` |
| `GuardrailInfoReason` | class | Non-terminal informational guardrail event reason taxonomy | `backend/app/services/agents/guardrails.py` |
| `CommHubToolClient` | class | Client for calling tools and A2A requests through Communication Hub with mTLS | `backend/app/agent_runtime/comm_hub_client.py` |
| `CommHubToolClient.call_a2a_request()` | method | Initiate an A2A delegation request through CH; returns response or propagates HITL status | `backend/app/agent_runtime/comm_hub_client.py` |
| `CommHubToolClient.call_human_intervene()` | method | Request human intervention through CH; forwards to CC for persistence | `backend/app/agent_runtime/comm_hub_client.py` |
| `CommHubToolClient.wait_for_a2a_response()` | method | Wait for a delegated sub-agent result via Redis pub/sub with HITL-aware deadline extension | `backend/app/agent_runtime/comm_hub_client.py` |
| `InterveneRequestStore` | class | Persistence layer for intervene request lifecycle — create, query, respond, cancel | `backend/app/services/agents/intervene_service.py` |
| `InterveneRequestStore.create_request()` | method | Create a new intervene request; unchanged signature — parent context resolved via `AgentJob.parent_job_id` FK chain | `backend/app/services/agents/intervene_service.py` |
| `InterveneRequestStore.get_request()` | method | Fetch an intervene request with response eagerly loaded | `backend/app/services/agents/intervene_service.py` |
| `InterveneRequest` | model | SQLAlchemy model for human-intervene requests; uses existing `agent_session_id` column (no new `parent_agent_job_id` column added) | `backend/app/db/models/intervene.py` |
| `InterveneResponse` | model | SQLAlchemy model for human-intervene responses | `backend/app/db/models/intervene.py` |
| `InterveneRequestStatus` | enum | Status enum: pending, responded, expired, cancelled | `backend/app/db/models/intervene.py` |
| `InterventionType` | enum | Type enum: approval, choice, text | `backend/app/db/models/intervene.py` |
| `ExecutionLogEntry` | model | SQLAlchemy model for structured execution log entries per session | `backend/app/db/models/session_logs.py` |
| `AgentJob` | model | SQLAlchemy model representing an agent execution session | `backend/app/db/models/agents.py` |
| `AgentJobStatus` | enum | Status enum: queued, running, waiting_for_human, completed, failed, terminated | `backend/app/db/models/agents.py` |
| `AgentInputType` | enum | Input type enum: none, typed, conversation | `backend/app/db/models/agents.py` |
| `TaskDelegationEventRouter` | class | In-memory router in CH that manages delegation status event and intervention delivery to log viewers | `backend/app/communication_hub/services/task_delegation_router.py` |
| `ActiveSessionTracker` | class | Tracks active WebSocket connections for conversational intervention routing (unchanged) | `backend/app/api/ws/chat.py:25` |
| `InterventionRouter` | class | Routes conversation-scoped `human_intervene` signals to WebSocket clients; non-conversational interventions fall through to dashboard flow | `backend/app/communication_hub/intervention_router.py` |
| `InterventionQueue` | class | Per-session FIFO queue for intervention request ordering in CH | `backend/app/communication_hub/intervention_queue.py` |
| `MessageBroker` | class | Redis pub/sub message broker used for A2A result waiting | `backend/app/services/comm_hub/broker.py` |
| `ControlCenterDataClient` | class | CH client for calling CC internal data APIs (session, log, intervene) | `backend/app/communication_hub/data_client.py` |
| `stream_session_execution_logs()` | function | NDJSON streaming endpoint for session execution logs; detects `waiting_for_human` and emits `human_intervene` events | `backend/app/api/v1/agents.py` |
| `get_session_execution_logs()` | function | REST endpoint returning all execution log entries for a session | `backend/app/api/v1/agents.py` |
| `InternalSessionDataRouter` | router | Internal data API router (APIRouter instance, not a class) for CC: session metadata, log append, status transitions | `backend/app/api/v1/internal/session_data.py` |
| `AgentPermissionManager` | class | Resolves allowed tools and enforces permission boundaries on every tool call | `backend/app/services/agents/permission_manager.py` |
| `AgentExecutionDetailsDialog` | component | Dialog showing agent execution details: execution log, results, conversation history with auto-popup intervene dialog | `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` |
| `InterveneResponseDialog` | component | Modal dialog for responding to human-intervene requests (approval/choice/text) | `frontend/src/components/agents/InterveneResponseDialog.tsx` |
| `InterveneRequestList` | component | Table listing pending intervene requests with respond/cancel actions | `frontend/src/components/agents/InterveneRequestList.tsx` |
| `LogViewer` | component | Execution log viewer: summary panel, working steps spans, raw log toggle | `frontend/src/components/executions/LogViewer.tsx` |
| `DelegationTimeline` | component | Colour-coded vertical timeline of delegation lifecycle events within execution log | `frontend/src/components/executions/DelegationTimeline.tsx` |
| `TaskInterventionDialog` | component | Inline intervention response UI rendered within the execution log event stream | `frontend/src/components/executions/TaskInterventionDialog.tsx` |
| `InterventionPendingBanner` | component | Sticky banner at top of execution log indicating pending intervention with "Respond Now" action | `frontend/src/components/executions/InterventionPendingBanner.tsx` |
| `useSessionExecutionLogStream` | hook | Connects to NDJSON log stream endpoint; emits entries, connection state, and humanInterveneEvent | `frontend/src/hooks/useSessionExecutionLogStream.ts` |
| `useExecutionLogs` | hook | Fetches execution logs (system instruction + user prompt) for a session | `frontend/src/hooks/useExecutionLogs.ts` |
| `presentLog()` | function | Pure transformation: converts raw logs and entries into structured log with summary, spans, and raw text | `frontend/src/services/LogPresenter.ts` |
| `interveneApi` | module | API client for intervene request CRUD: get, list, submit response, cancel | `frontend/src/api/interveneApi.ts` |
| `ExecutionLogEntry` (type) | type | TypeScript interface for structured log entry with id, session_id, event_type, message, data, timestamp, log_level | `frontend/src/types/index.ts` |
| `InterveneRequest` (type) | type | TypeScript interface for intervention request with id, status, intervention_type, reason, choices | `frontend/src/types/index.ts` |
| `AgentJobStatus` (type) | type | TypeScript union type for session status: queued, running, waiting_for_human, completed, failed, terminated | `frontend/src/types/index.ts` |
| `HumanInterveneEvent` (type) | type | TypeScript interface for stream `human_intervene` events with request_id, session_id, reason, intervention_type | `frontend/src/hooks/useSessionExecutionLogStream.ts` |
| `AgentOutputType` | enum | Output type enum: auto, typed, markdown | `backend/app/db/models/agents.py` |
| `AgentType.output_type` | column | SQLAlchemy column storing agent output type | `backend/app/db/models/agents.py` |
| `AgentType.output_schema` | column | JSON schema used when output_type is typed | `backend/app/db/models/agents.py` |
| `AgentRuntimeExecutor._format_user_prompt()` | method | Assembles system prompt with input/output type context; now appends output type formatting instruction | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._handle_save_result_tool_call()` | method | Persists save_result call as ResultRecord; now derives content_type from output_type via `_resolve_content_type()` | `backend/app/services/agents/runtime_executor.py` |
| `OutputTypeResultTab` | component | Renders agent output formatted per output_type: markdown as HTML, typed as JSON tree, auto as raw | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `AgentJobPage` (result section) | component | Existing page that renders task agent result directly (structured JSON/markdown); the new `OutputTypeResultTab` is used within `AgentExecutionDetailsDialog` instead | `frontend/src/pages/agents/AgentJobPage.tsx` |
| `AgentTypeForm` (output type field) | component | Agent type creation/edit form with output_type dropdown and output_schema editor | `frontend/src/pages/agents/AgentTypeForm.tsx` |
