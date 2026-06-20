# Implementation Plan: Agent Delegation Visibility & HITL for Non-Conversational Agents

## Overview

Non-conversational (task) agents already delegate to sub-agents via `agent____<slug>` tool calls, but the execution log provides no delegation visibility and operators cannot respond to sub-agent intervention requests. This plan implements delegation status events, inline intervention dialogs, and 1-level depth enforcement for task agents by extending existing conversational-agent infrastructure to the non-conversational path.

---

## Task Checklist

### Phase 1 — Agent Runtime: Delegation Depth Guard & Status Events
- [x] 1.1 — Add delegation depth guard to task agent execution loop
- [x] 1.2 — Emit delegation status events from task agent act phase
- [x] 1.3 — Wire HITL suspend/resume for task agent delegations
- [x] 1.4 — Inject output type formatting instructions into system prompt

### Phase 2 — Communication Hub: Task Delegation Event Router
- [x] 2.1 — Implement Task Delegation Event Router module
- [x] 2.2 — Route delegation status events to execution log viewers
- [x] 2.3 — Route non-conversational intervention requests to execution log viewers

### Phase 3 — Control Center: New API Endpoints & Event Types
- [x] 3.1 — Add delegation-specific execution log event types (*strings work with existing string-based event_type column*)
- [x] 3.2 — Add pending intervention and delegation status API endpoints
- [x] 3.3 — Extend intervene request store for non-conversational delegation context (*implemented via existing `AgentJob.parent_job_id` FK chain; no new `parent_agent_job_id` column on `InterveneRequest` because `.change.yaml` marks `has_db_changes: false`; the existing `InterveneRequest.agent_session_id` identifies the sub-agent session and the parent is resolved through the FK chain*)

### Phase 4 — Frontend: Execution Log Viewer Updates
- [x] 4.1 — Update LogPresenter to handle delegation event types
- [x] 4.2 — Build delegation status timeline component in execution log
- [x] 4.3 — Build inline task intervention dialog in execution log
- [x] 4.4 — Build persistent "Waiting for Input" banner
- [x] 4.5 — Wire intervention response submission and log resume
- [x] 4.6 — Build output-type-aware Result tab in execution log

### Phase 5 — Integration, Testing & Polish
- [x] 5.1 — Write backend unit tests for each phase 1–3 component
- [x] 5.2 — Write frontend unit tests for each phase 4 component
- [ ] 5.3 — Integration smoke test: full delegating→waiting→resumed flow
- [ ] 5.4 — Integration smoke test: HITL approval/choice/text during delegation
- [ ] 5.5 — Integration smoke test: depth limit blocked, timeout, failure exit conditions
- [ ] 5.6 — Polish: reconnect re-surfaces pending intervention, expired intervention handling

---

## Completion Checklist

- [x] Phase 1 (Agent Runtime) implemented
- [x] Phase 2 (Communication Hub) implemented
- [x] Phase 3 (Control Center API) implemented
- [x] Phase 4 (Frontend) implemented
- [x] Phase 5.1 (Backend unit tests) implemented
- [x] Phase 5.2 (Frontend component tests) implemented
- [ ] Phase 5.3–5.6 (Integration smoke tests & polish) not yet started
- [ ] All unit tests pass (*24 pre-existing failures unrelated to this change*)
- [x] No regressions in conversational agent delegation or HITL (*confirmed*)
- [x] Code Review Map in tech-spec.md verified against actual code
- [ ] `spec-change.md` acceptance criteria satisfied
- [ ] `prd.md` acceptance criteria satisfied

---

## Phase 1 — Agent Runtime: Delegation Depth Guard & Status Events

### 1.1 — Add delegation depth guard to task agent execution loop

**What**: Before the task agent dispatches an `agent____<slug>` delegation tool call in `_act()`, run a pre-dispatch depth check. Non-conversational agents are limited to depth 1 — the parent (depth 0) can delegate to one sub-agent (depth 1), and that sub-agent is blocked from further delegation.

**Where**: `backend/app/services/agents/runtime_executor.py` — `_act()` method (line ~3368 where `_extract_agent_delegation_target` is checked), and `_build_guardrail_state()` for enforcing `max_delegation_depth = 1` for non-conversational agents.

**Changes**:
- In `_build_guardrail_state()`: when the agent type is non-conversational (detected from `job_data` or passed flag), override `max_delegation_depth` to `1` regardless of the policy value (policy may have 3 for conversational).
- In `_act()`: before calling `comm_hub_client.call_a2a_request()`, check `guardrail_state.delegation_depth >= guardrail_state.max_delegation_depth`. If exceeded, emit a `delegation_depth_blocked` log event and skip the A2A call, returning a blocked outcome as the tool result.
- Track the `guardrail_state.delegation_depth` increment after a successful delegation tool call begins.

**Done when**:
- A non-conversational parent agent (depth 0) can delegate to a sub-agent.
- A sub-agent (depth 1) cannot further delegate — the A2A call is blocked.
- A `delegation_depth_blocked` event appears in the execution log when blocked.
- Conversational agents are NOT affected by this limit (they continue using policy-defined `max_delegation_depth`).
- The depth limit is enforced server-side in Agent Runtime — frontend-only bypass is impossible.

### 1.2 — Emit delegation status events from task agent act phase

**What**: When a task agent delegates via the `_act()` method, emit `delegation_started`, `delegation_waiting`, and `delegation_resumed` events through the execution log channel, mirroring the conversational pattern.

**Where**: `backend/app/services/agents/runtime_executor.py` — `_act()` method at the delegation branch (line ~3368–3378), and the `_run_task_loop()` to pass a log-event emitter.

**Changes**:
- Extract or create a log-event emission helper (similar to `emit_status_event` in the conversational loop at line ~2452) usable from the task loop.
- Before `call_a2a_request()`: emit `delegation_started` event via `_log_execution_event()` with event_type `delegation_started`, payload including sub-agent type slug and delegation depth.
- After `call_a2a_request()` (when `wait_for_response=True`): emit `delegation_waiting` event.
- After the `call_a2a_request()` returns (blocking call for task agent): emit `delegation_resumed` with exit condition (success, timeout, or failure from the response).
- Add the new event types to the `_log_execution_event()` call chain.

**Done when**:
- A non-conversational agent that delegates produces `delegation_started`, `delegation_waiting`, and `delegation_resumed` events in the execution log stream.
- Events appear in the live log stream in real time without page refresh.
- Each `delegation_resumed` event includes a distinct exit condition: completed, timeout, or failed.
- Existing non-delegation tool calls continue to produce their normal tool_call events unchanged.
- Conversational agent delegation events continue working unchanged.

### 1.3 — Wire HITL suspend/resume for task agent delegations

**What**: When a delegated sub-agent calls `system____human_intervene`, the task agent's execution must suspend (status → `waiting_for_human`) and the intervention request must be routed back to the parent agent's execution log viewer. The existing HITL suspend mechanism already works for the sub-agent itself but needs the parent task agent to also pause and emit the intervention signal through CH.

**Where**: `backend/app/services/agents/runtime_executor.py` — `_act()` delegation branch and the `call_human_intervene()` path; `backend/app/agent_runtime/comm_hub_client.py` — `call_a2a_request()` and `call_human_intervene()` methods.

**Changes**:
- When `call_a2a_request()` detects that the delegated sub-agent went into `waiting_for_human` status (via the A2A response payload), the task agent's `_act()` should:
  - Set the parent `AgentJob` status to `waiting_for_human`.
  - Emit an `intervention_required` event with the intervention details.
  - Pass the parent `agent_job_id` (not just `conv_session_id`) as context for the intervention routing.
- The `comm_hub_client.call_a2a_request()` response payload must propagate the `waiting_for_human` status and intervention request ID back to the caller.
- The existing `call_human_intervene()` path on the sub-agent side already works — the change is about carrying the parent's `agent_job_id` through so CH knows which execution log viewer to notify.

**Done when**:
- A non-conversational agent delegates to a sub-agent that calls `human_intervene`.
- The parent agent's session status transitions to `waiting_for_human`.
- An `intervention_required` event with the intervention type, reason, and choices is emitted to the parent agent's execution log stream.
- The parent agent's execution log stream emits the `human_intervene` event type (via the existing NDJSON stream mechanism in `stream_session_execution_logs`).
- When the operator responds, the session status transitions back to `running` and the log stream resumes.

### 1.4 — Inject output type formatting instructions into system prompt

**What**: Before the first LLM call, append output format instructions to the system prompt based on the agent type's `output_type` configuration, so the agent respects its configured output type at runtime.

**Where**: `backend/app/services/agents/runtime_executor.py` — `_format_user_prompt()` method (lines ~3676–3727).

**Changes**:
- In `_format_user_prompt()`, after the existing `input_type` handling, add a new block that reads `self.ctx.output_type` and `self.ctx.output_schema`.
- For `output_type == "markdown"`: append "You must produce your final output in markdown format."
- For `output_type == "typed"` with `output_schema`: append "You must produce output as structured JSON matching the following schema: [schema]. Respond with valid JSON only."
- For `output_type == "auto"`: no additional instruction.
- Also update `_handle_save_result_tool_call()` (line ~3404) to derive `content_type` from `output_type` instead of hardcoding `"application/json"`, matching the existing logic in `_content_type_from_output_type()` in `system_tools.py`.

**Done when**:
- A non-conversational agent with `output_type: markdown` receives a markdown formatting instruction in its system prompt.
- A non-conversational agent with `output_type: typed` receives a JSON schema instruction in its system prompt.
- The `save_result` tool call persists with the correct MIME content type derived from `output_type`.
- Agents with `output_type: auto` receive no additional output format instruction.
- Conversational agents are NOT affected by this change.

---

## Phase 2 — Communication Hub: Task Delegation Event Router

### 2.1 — Implement Task Delegation Event Router module

**What**: A new module in Communication Hub that manages delivery of non-conversational delegation status events and intervention requests to execution log viewer clients via the live log stream.

**Where**: New file: `backend/app/communication_hub/services/task_delegation_router.py` (or a new module in `backend/app/communication_hub/routing/`).

**Changes**:
- Create a `TaskDelegationEventRouter` class with:
  - An in-memory registry mapping `agent_job_id` → set of connected log-viewer channels/connections.
  - Methods: `register_viewer(agent_job_id, channel)`, `unregister_viewer(agent_job_id, channel)`, `push_event(agent_job_id, event_payload)`.
  - `push_intervene_request(agent_job_id, intervene_payload)`.
- The router pushes events through the existing live log stream mechanism (NDJSON `StreamingResponse` managed by CC) OR a new internal WebSocket/SSE connection from CH to CC log viewers. The architecture.md implies events flow through the existing live stream channel, so CH needs a way to inject events into CC's log stream. This may mean CH calls a new CC internal endpoint that the log stream poll loop picks up.

**Done when**:
- `TaskDelegationEventRouter` is importable and instantiable.
- It can register and unregister log viewer connections by `agent_job_id`.
- Pushing an event to a registered `agent_job_id` results in the event being delivered through the log stream.

### 2.2 — Route delegation status events to execution log viewers

**What**: When AR emits a delegation status event for a non-conversational agent, CH routes it to the correct execution log viewer's live stream.

**Where**: `backend/app/communication_hub/services/task_delegation_router.py` and integration points in `backend/app/communication_hub/api/a2a.py` or `backend/app/communication_hub/api/internal/tool_routing.py`.

**Changes**:
- In the existing A2A request handler or tool routing path where CH receives delegation status events from AR, detect that the event belongs to a non-conversational agent (context has `agent_job_id` but no `conv_session_id`).
- Forward the event to `TaskDelegationEventRouter.push_event()` instead of (or in addition to) the existing conversational WebSocket path.
- Event types to route: `delegation_started`, `delegation_waiting`, `delegation_resumed`, `delegation_depth_blocked`, `delegation_timeout`, `delegation_failed`.

**Done when**:
- Delegation status events from non-conversational agent executions reach the correct log viewer.
- Events appear in the execution log without interfering with conversational delegation WebSocket events.
- Fallback: if no log viewer is connected, events are still persisted by CC (poll-based fallback).

### 2.3 — Route non-conversational intervention requests to execution log viewers

**What**: When a delegated sub-agent's `human_intervene` call arrives at CH, and the parent context is a non-conversational agent job (identified by `agent_job_id` rather than `conv_session_id`), CH routes the intervention request to the execution log viewer rather than the conversation WebSocket.

**Where**: `backend/app/communication_hub/services/task_delegation_router.py` and the existing intervention routing path in `backend/app/communication_hub/api/internal/tool_routing.py`.

**Changes**:
- In the intervention routing path, check for the presence of a non-conversational `agent_job_id` context (no `conv_session_id`).
- If non-conversational context: call `TaskDelegationEventRouter.push_intervene_request()` instead of `ActiveSessionTracker.send_to_session()`.
- The router pushes a `task_intervene_request` event through the log stream channel.
- On intervention response from the log viewer, CH receives via a new endpoint or existing intervene response endpoint, then signals AR to resume the sub-agent.

**Done when**:
- A delegated sub-agent's intervention request arrives at CH with non-conversational parent context.
- CH routes it to the execution log viewer instead of the conversation WebSocket.
- Operator response from the log viewer is routed back to CH and then to AR.
- Existing conversational intervention routing is preserved unchanged.

---

## Phase 3 — Control Center: New API Endpoints & Event Types

### 3.1 — Add delegation-specific execution log event types

**What**: Extend the execution log event type taxonomy to include delegation lifecycle events, distinct exit conditions, and guardrail outcomes.

**Where**: `backend/app/services/agents/runtime_executor.py` — `_log_execution_event()` call sites; `backend/app/api/v1/internal/session_data.py` — log append endpoint; `backend/app/db/models/session_logs.py` — any event type enums or validation.

**Changes**:
- Define new event type string constants:
  - `delegation_started` — when a non-conversational agent begins delegating.
  - `delegation_waiting` — while the sub-agent is executing.
  - `delegation_resumed` — when the parent resumes after sub-agent completion.
  - `delegation_depth_blocked` — when the depth guard blocks a delegatee further delegation.
  - `delegation_timeout` — when the delegated sub-agent exceeds its time limit.
  - `delegation_failed` — when the delegated sub-agent encounters a runtime error.
- Ensure these event types are accepted by the log append endpoint (no validation rejection).
- Update any event type category mapping used by the LogViewer.

**Done when**:
- All six new event types can be persisted via the CC internal log append endpoint.
- Existing event types (`session_started`, `tool_call`, `llm_call`, etc.) continue working.
- No database schema change required (event_type is a string column).

### 3.2 — Add pending intervention and delegation status API endpoints

**What**: Two new CC REST endpoints for the frontend to query on initial load and reconnect.

**Where**: `backend/app/api/v1/agents.py` — new routes on `AgentJobRouter`.

**Changes**:
- `GET /api/v1/agent-jobs/{session_id}/interventions/pending`:
  - Queries `InterveneRequest` for the given `agent_job_id` with `status == pending`.
  - Returns the pending intervention request details (type, reason, choices, agent).
  - Used by the execution log viewer on reconnect to re-surface outstanding intervention dialogs.
- `GET /api/v1/agent-jobs/{session_id}/delegation/status`:
  - Queries `ExecutionLogEntry` for recent delegation-related entries filtered by event type.
  - Returns current delegation status: active sub-agent types, depths, exit conditions.
  - Used by the execution log viewer to render the delegation status timeline on initial load.

**Done when**:
- `GET .../interventions/pending` returns the currently pending intervention for the session, or empty if none.
- `GET .../delegation/status` returns the current delegation state with sub-agent info.
- Both endpoints require standard `RT_AGENT` read permission.
- Both endpoints return 404 if the session does not exist.

### 3.3 — Extend intervene request store for non-conversational delegation context

**What**: Non-conversational intervention requests need to be scoped to the parent task agent session. Because `.change.yaml` marks `has_db_changes: false`, no new database column was added. Instead, the existing `AgentJob.parent_job_id` FK chain is used: `InterveneRequest.agent_session_id` identifies the sub-agent's session, and the parent's `AgentJob` is reached via `AgentJob.parent_job_id → AgentJob.id` traversal.

**Where**: `backend/app/db/models/intervene.py` — model (no changes); `backend/app/services/agents/intervene_service.py` — `create_request()` (no signature change); `backend/app/api/v1/agents.py` — new `GET .../interventions/pending` endpoint.

**Changes**:
- The `InterveneRequest.agent_session_id` column already references the sub-agent's session — no new column needed.
- The new `GET .../interventions/pending` endpoint accepts a session ID (the parent's `agent_job_id`) and returns pending intervention requests for the session.
- The parent-child relationship is resolved at runtime: CH forwards the intervention request to CC with the sub-agent session ID, and the frontend queries by parent session ID via `GET .../interventions/pending`.
- The `InterveneRequestStore.create_request()` signature is unchanged — the parent context is carried through the event payload, not stored as a separate FK.

**Done when**:
- `GET .../interventions/pending` returns pending interventions for a given session (parent `agent_job_id`) — correctly identifying interventions from delegated sub-agents.
- No new DB migration required (`has_db_changes: false` verified).
- Existing conversational intervention requests continue working using `conversation_session_id`.

---

## Phase 4 — Frontend: Execution Log Viewer Updates

### 4.1 — Update LogPresenter to handle delegation event types

**What**: Extend `presentLog()` to recognize the new delegation event types and render them appropriately in the structured log output.

**Where**: `frontend/src/services/LogPresenter.ts`.

**Changes**:
- Add `delegation_started`, `delegation_waiting`, `delegation_resumed`, `delegation_depth_blocked`, `delegation_timeout`, `delegation_failed` to the event type handlers.
- Map these to appropriate icon types: `delegating` → custom 'delegating' icon, `waiting` → 'waiting' icon, `resumed` → 'success', `blocked`/`timeout`/`failed` → 'error'.
- Add these event types to the span builder so they appear in the correct hierarchical position (under "Agent Actions" → within the iteration where delegation occurred).
- Update `iconTypeFromEntry()` to return appropriate icons for delegation events.
- Update `entryToWorkingStep()` to include sub-agent type and depth in the detail object.

**Done when**:
- Delegation event types appear in the structured log output with correct icons.
- Delegation events are grouped correctly under iterations in the span hierarchy.
- No regressions in existing LLM, tool, system event rendering.

### 4.2 — Build delegation status timeline component in execution log

**What**: A visual timeline within the execution log view that shows delegation lifecycle events (delegating → waiting → resumed) with sub-agent info cards, animated progress bars, and colour-coded statuses matching the prototype.

**Where**: `frontend/src/components/executions/DelegationTimeline.tsx` (new component).

**Changes**:
- Create `DelegationTimeline` component displaying delegation events as a vertical timeline.
- Each delegation event shows:
  - Event timestamp, icon (colour-coded by type), event type label (DELEGATING, WAITING, etc.).
  - Sub-agent inline card with agent name, running/completed/failed state chip.
  - Animated loading bar during `delegating` and `waiting` states (pulsing animation per prototype CSS).
- Colour scheme matches prototype tokens: purple for delegating, amber for waiting, green for resumed, red for blocked/failed.
- Accepts `entries: ExecutionLogEntry[]` as input, filters for delegation event types.
- Integrate into the existing execution log view (the "Execution" tab of `AgentExecutionDetailsDialog`).

**Done when**:
- Delegation events render as a styled timeline with colour-coded icons and sub-agent cards.
- Animated loading bars appear during active delegation/waiting states.
- The timeline updates in real time as new delegation entries arrive from the stream.
- Matches the visual design from `docs/changes/agent-delegation-non-conversational/prototype/index.html`.

### 4.3 — Build inline task intervention dialog in execution log

**What**: When a delegated sub-agent requests human intervention, an inline dialog appears within the execution log timeline (not a separate modal), showing the intervention type, reason, context, and response controls (approve/deny buttons, choice radio group, or text input).

**Where**: `frontend/src/components/executions/TaskInterventionDialog.tsx` (new component).

**Changes**:
- Create `TaskInterventionDialog` as an inline component (not a modal dialog — rendered within the log event list).
- Three response modes:
  - **Approval**: Approve and Deny buttons (green and red, per prototype).
  - **Choice**: Radio-button list with selectable options.
  - **Text**: Textarea with Submit button.
- Shows intervention header with type badge (APPROVAL / CHOICE / TEXT INPUT), requesting sub-agent name, reason, and context.
- After response: shows a "Response submitted" resolved state.
- After expiry (sub-agent timed out): shows an expired overlay with "Request no longer valid" message.
- Accepts `InterveneRequest` data and `onSubmit`, `onDismiss` callbacks.

**Done when**:
- Inline dialog renders within the log event list at the intervention event position.
- Approval mode shows Approve/Deny buttons that work and submit values.
- Choice mode shows selectable options and submits the chosen option.
- Text mode shows textarea and submits the entered text.
- Resolved and expired states render correctly.
- Matches the visual design from the prototype.

### 4.4 — Build persistent "Waiting for Input" banner

**What**: A sticky banner at the top of the execution log that appears when there is a pending intervention request. The banner indicates the session is waiting for human input and provides a "Respond Now" button that scrolls to the inline intervention dialog.

**Where**: `frontend/src/components/executions/InterventionPendingBanner.tsx` (new component).

**Changes**:
- Create `InterventionPendingBanner` component.
- Banner is sticky (position: sticky, top: 0) within the log container.
- Shows: animated spinner, title "Intervention Required — Delegated sub-agent needs input", subtitle with sub-agent name and pending time, and "Respond Now" button.
- "Respond Now" button scrolls to the inline intervention dialog in the timeline.
- Banner visibility is controlled by a `pendingIntervention` state — visible when a pending intervention exists and the inline dialog was dismissed or scrolled out of view.
- Integrate into `AgentExecutionDetailsDialog` or the log tab content area.

**Done when**:
- Banner appears when a pending intervention request exists and the inline dialog is not visible.
- "Respond Now" scrolls to and focuses the inline intervention dialog.
- Banner disappears when there are no pending interventions.
- Banner is styled per the prototype (amber/warning theme, animated spinner).

### 4.5 — Wire intervention response submission and log resume

**What**: Connect the inline intervention dialog response submission to the backend API, handle the response flow, and resume the log stream after submission.

**Where**: `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` — existing intervention dialog wiring; `frontend/src/api/interveneApi.ts` — existing API client; `frontend/src/components/executions/TaskInterventionDialog.tsx`.

**Changes**:
- Reuse the existing `interveneApi.submitInterveneResponse()` function with the intervention request ID and response value.
- After successful submission:
  - The inline dialog transitions to "resolved" state.
  - The log stream resumes automatically (the NDJSON stream endpoint continues yielding new entries after the agent resumes).
  - A `delegation_resumed` event appears in the log timeline.
- Handle submission errors with proper error feedback in the dialog (use `PermissionDeniedAlert` pattern).
- On reconnect: use the new `GET .../interventions/pending` endpoint (Phase 3.2) to check for pending interventions and re-surface the dialog.

**Done when**:
- Operator submits an intervention response and the dialog shows "resolved" state.
- The log stream resumes automatically with new delegation events.
- Submission errors (403, network failure) show proper error messages.
- On page reconnect, pending interventions are fetched and the dialog re-appears.

### 4.6 — Build output-type-aware Result tab in execution log

**What**: Add a Result tab in the execution log details dialog that renders the agent's output formatted according to the agent type's `output_type` definition.

**Where**: `frontend/src/components/executions/OutputTypeResultTab.tsx` (new component); `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` (modified to use new tab).

**Changes**:
- Create `OutputTypeResultTab` component that:
  - Reads `output_type` from the session/agent type metadata.
  - For `markdown`: parses `output_data.markdown` or `output_data.result` as markdown, renders as rich HTML.
  - For `typed`: renders `output_data` as a collapsible JSON tree view, with a "Show Schema" toggle displaying the `output_schema`.
  - For `auto`: renders `output_data` as raw formatted JSON in a `<pre>` block.
- The tab label includes the output type badge (e.g., "Result Markdown", "Result Typed", "Result Auto").
- Tab visibility: shown when session is in terminal status (completed, failed, terminated).
- Replace or extend the existing `AgentJobPage` result section to use `OutputTypeResultTab`.
- Update `AgentExecutionDetailsDialog` tab structure to use the new component.

**Done when**:
- The Result tab renders markdown output as formatted HTML (not raw markdown source).
- The Result tab renders typed JSON output as a structured tree with schema toggle.
- The Result tab renders auto output as raw text/JSON.
- The tab label includes the output type badge.
- The tab only appears when the session is terminal.
- Matches the visual design from the prototype.

---

## Phase 5 — Integration, Testing & Polish

### 5.1 — Write backend unit tests for each phase 1–3 component

**Tests created**:
- `backend/tests/unit/test_delegation_depth_guard.py` — depth limit enforcement for task agents (17 tests).
- `backend/tests/unit/test_task_delegation_status_events.py` — delegation status event emission in task loop (8 tests).
- `backend/tests/unit/test_task_agent_hitl_suspension.py` — HITL suspend/resume in task delegation context (11 tests).
- `backend/tests/unit/test_task_delegation_router.py` — CH router registration, push, routing logic (15 tests).
- `backend/tests/unit/test_output_type_prompt_injection.py` — output type instruction appended to system prompt for each type (15 tests).
- `backend/tests/unit/test_hitl_delegation_status_events.py` — non-conversational HITL delegation status event routing (2 tests).
- `backend/tests/unit/test_a2a_hitl_timeout.py` — A2A HITL timeout handling (4 tests).
- `backend/tests/unit/test_ws_delegation_visibility.py` — stream delegation visibility (1 test).
- `backend/tests/services/test_intervene_service.py` — `InterveneRequest` CRUD, status transitions, respond/cancel/expiry (28 tests).
- `backend/tests/integration/test_intervention_api_integration.py` — API endpoint integration for interventions.
- `backend/tests/integration/test_internal_intervene_respond.py` — Internal intervene respond flow.
- `backend/tests/api/v1/test_intervene.py` — API-level intervene request/response tests.

**Coverage includes**: depth guard blocks, status events emitted, intervention routing, API endpoint responses, output type prompt injection, content type derivation, `InterveneRequest` lifecycle.

### 5.2 — Write frontend unit tests for each phase 4 component

**Tests created**:
- `frontend/src/__tests__/DelegationTimeline.test.tsx` — timeline rendering and live updates (11 tests).
- `frontend/src/__tests__/TaskInterventionDialog.test.tsx` — dialog behaviour for all three intervention types (13 tests).
- `frontend/src/__tests__/InterventionPendingBanner.test.tsx` — banner visibility and Respond Now behaviour (10 tests).
- `frontend/src/__tests__/OutputTypeResultTab.test.tsx` — result rendering for markdown, typed, auto output types (11 tests).
- `frontend/src/__tests__/LogPresenter.test.ts` — delegation event type icon mappings (existing, updated).
- `frontend/src/__tests__/ConversationDelegationVisibility.test.tsx` — delegation visibility in conversation context.

**Done when**: All new frontend tests pass.

### 5.3 — 5.5 : Integration smoke tests
- Start all services via `parthenon.ps1 start -Services backend`, run a non-conversational agent that delegates, verify delegation events appear in the live log stream.
- Run a non-conversational agent where the sub-agent calls `human_intervene`, verify the inline dialog appears, respond, verify the stream resumes.
- Test depth limit blocked, timeout, and failure exit conditions.

**Done when**: All smoke test scenarios pass against a running stack.

### 5.6 — Polish
- Reconnect handling: operator closes and reopens the execution log viewer while an intervention is pending — dialog re-surfaces via `GET .../interventions/pending`.
- Expired intervention: operator tries to respond after the sub-agent has timed out — "Request no longer valid" message appears.
- Guardrail outcomes during delegation: `delegation_depth_blocked` event surfaces correctly.
- Audit trail: all delegation events and intervention decisions are visible in the log timeline post-completion.

**Done when**: All edge cases handled gracefully with clear user feedback.
