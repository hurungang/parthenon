# Test Plan: Agent Delegation Visibility & HITL for Non-Conversational Agents

## 1. Test Strategy

### Overall Approach

This feature is inherently **multi-service** (Control Center, Communication Hub, Agent Runtime) and **multi-layer** (backend logic, frontend UI, live streaming). Testing must span all three service boundaries and all three test layers. The strategy is:

- **Backend Unit Tests** — Validate the core business logic in isolation: delegation depth guard enforcement, delegation status event emission, output-type prompt injection, and the new `InterveneRequest.parent_agent_job_id` column. Mock outbound service calls (CH client, CC data APIs) to test decision logic in `runtime_executor.py`, `guardrails.py`, and `intervene_service.py` without requiring live services.
- **Backend Integration Tests** — Verify that `InterveneRequest.parent_agent_job_id` persists correctly through the SQLAlchemy model layer. Validate that the new `TaskDelegationEventRouter` in CH correctly routes events between AR and log viewers. Confirm that new delegation event types are accepted by the CC internal log endpoint.
- **Frontend Component Tests** — Use Vitest + React Testing Library to test each new/updated frontend component in isolation with mocked API responses and mocked NDJSON streams. Validate rendering logic for `DelegationTimeline`, `TaskInterventionDialog`, `InterventionPendingBanner`, `OutputTypeResultTab`, and the updated `LogPresenter` mappings.
- **E2E Tests** — Use Playwright to execute full user journeys against the real backend stack (all three services running). These tests validate real-time event delivery, intervention request/response round-trips, and UI state transitions without mocking backend endpoints or WebSocket/stream connections.

### Test Layer Responsibilities

| Layer | Scope | Tooling | Mocking Strategy |
|-------|-------|---------|-----------------|
| Backend Unit | Single function/class logic | pytest + unittest.mock | Mock CH client, CC data API, DB session |
| Backend Integration | DB schema + CH routing + API endpoint acceptance | pytest + test DB or mock DB | Real SQLAlchemy models, real CH router |
| Frontend Component | UI rendering, state, user interaction | Vitest + RTL + MSW | Mock API calls, mock `useSessionExecutionLogStream` |
| E2E | Full user journeys against live stack | Playwright | Real backend, real DB, real NDJSON stream |

### Manual Testing (Where Automation Is Impractical)

- **Live NDJSON stream reconnection** with actual socket disconnect/reconnect (network-layer simulation is fragile in automated tests)
- **Visual regression** of delegation timeline colour-coding and animation states (defer to future visual snapshot tests)
- **Browser tab switching** during pending intervention (cross-tab state recovery is difficult to automate)

---

## 2. Coverage Areas

### Area 1: Delegation Depth Limit Enforcement *(Critical — Safety Boundary)*

**Why critical**: This is the mechanism that prevents unbounded delegation chains in automated workflows. A bypass here creates a silent infinite-delegation risk that could exhaust resources with no operator visibility.

**What must be tested**:
- Depth 0 (parent) delegates → allowed
- Depth 1 (sub-agent from non-conversational parent) delegates → blocked
- Depth 1 (sub-agent from conversational parent, depth 3 limit) delegates → allowed (conversational path unchanged)
- Blocked delegation emits `delegation_depth_blocked` event with clear message
- Depth guard is enforced server-side in Agent Runtime (not frontend-only)
- `max_delegation_depth` override in `_build_guardrail_state()` is correctly applied only for non-conversational agents

### Area 2: Delegation Status Event Emission *(Core Visibility)*

**Why critical**: Without these events, the entire "visibility" goal of this change is unmet — operators see a black box during delegation.

**What must be tested**:
- `delegation_started` emitted before `call_a2a_request()` with `wait_for_response=True`
- `delegation_waiting` emitted after A2A request dispatched, sub-agent is executing
- `delegation_resumed` emitted when A2A request returns (includes exit condition)
- `delegation_timeout` emitted when sub-agent times out (distinct from generic failure)
- `delegation_failed` emitted when sub-agent encounters runtime error (distinct from timeout)
- Events appear in NDJSON stream in real time without manual refresh
- Events are persisted and replayed on stream reconnect
- Conversational agent delegation event emission is NOT broken by these changes

### Area 3: Human-in-the-Loop During Task Delegation *(Critical User Flow)*

**Why critical**: This is the marquee interaction — operator sees an intervention, responds inline, and execution resumes. Every step in this chain must work, including error states like expired requests and stream disconnects.

**What must be tested**:
- Sub-agent calls `system____human_intervene` → parent `AgentJob.status` → `waiting_for_human`
- Inline intervention popup appears with correct intervention type (approval/choice/text)
- Operator responds from inline popup → log stream resumes automatically
- Operator dismisses popup or navigates away → `InterventionPendingBanner` appears
- Returning to execution log → pending intervention re-surfaces via `GET .../interventions/pending`
- Intervention response (operator identity, decision, timestamp) recorded in execution timeline
- Expired intervention shows "Request no longer valid" and blocks response
- Non-conversational intervention routing uses `parent_agent_job_id` (not `conv_session_id`)
- Conversational intervention routing is NOT broken (still uses `conv_session_id`)

### Area 4: Output Type Prompt Injection *(System Prompt Integrity)*

**Why critical**: Downstream processes rely on formatted output. If the prompt injection is wrong, agents produce malformed results that break automation chains.

**What must be tested**:
- `output_type == "markdown"` → system prompt includes markdown formatting instruction
- `output_type == "typed"` with `output_schema` → system prompt includes schema + structured JSON instruction
- `output_type == "auto"` → no additional format instruction appended
- Injection happens in `_format_user_prompt()` before first LLM call
- Conversational agent system prompts are NOT modified

### Area 5: Output-Type-Aware Result Tab *(Frontend Display)*

**Why critical**: Operators need to see results in their intended format. Raw markdown or unformatted JSON harms usability.

**What must be tested**:
- Markdown output rendered as rich HTML (not raw markdown source)
- Typed JSON output displayed as structured expandable/collapsible tree
- Auto output displayed as raw formatted text in `<pre>` block
- Result tab only visible when session is in terminal state
- Tab label includes output type badge (e.g., "Result [Markdown]")
- Tab integrates into `AgentExecutionDetailsDialog` alongside Execution and History tabs

### Area 6: Delegation Timeline Rendering *(Frontend Display)*

**Why critical**: This is the primary UI surface for delegation visibility — events must map correctly to visual states.

**What must be tested**:
- `DelegationTimeline` filters entries by delegation event types
- Correct colour-coded icons per event type (purple=delegating, amber=waiting, green=resumed, red=blocked/error)
- Sub-agent inline card shows agent name, state chip, animated loading bar during active delegation
- Timeline updates in real time as stream entries arrive
- Previously persisted delegation events visible on initial page load

### Area 7: LogPresenter Event Type Mappings *(Frontend Logic)*

**Why critical**: The LogPresenter transforms raw log entries into the structured log view. Wrong mappings mean delegation events appear in wrong sections or with wrong icons.

**What must be tested**:
- All six delegation event types have correct `iconTypeFromEntry()` mappings
- Delegation events classified under "Agent Actions" span (not preparation or completion)
- Delegation events NOT in `PREPARATION_EVENT_TYPES` or `COMPLETION_EVENT_TYPES`

### Area 8: API and Data Model Changes *(Backend Integration)*

**Why critical**: New endpoints and event types must be correct at the data layer.

**What must be tested**:
- `GET /api/v1/agent-jobs/{session_id}/interventions/pending` returns correct pending request for a session
- `GET /api/v1/agent-jobs/{session_id}/delegation/status` returns delegation event summary
- New delegation event types accepted by `POST .../internal/data/sessions/{session_id}/log`
- A2A response payload includes `waiting_for_human` flag and intervention request ID
- Existing `InterveneRequest.agent_session_id` correctly identifies sub-agent session; parent context resolved via `AgentJob.parent_job_id` FK chain (no new DB column needed, verified per `has_db_changes: false`)

### Area 9: Service Boundaries and Architecture Compliance *(Security/Architecture)*

**Why critical**: Must not violate `top_priority_rules` from `docs/config.yaml`.

**What must be tested**:
- Agent Runtime never accesses database directly for delegation or intervention state
- Delegation and intervention state persisted via CC internal endpoints only
- Agent Runtime never receives user identity tokens
- Agent Runtime certificate validation unchanged
- Communication Hub routes delegation events and interventions (AR → CH → CC)
- Conversational delegation path fully preserved (no regression)

### Area 10: Exit Conditions and Cleanup

**Why critical**: Delegation can end in multiple ways — each must be handled distinctly and correctly.

**What must be tested**:
- Successful completion: `delegation_resumed` with successful outcome, parent continues
- Timeout: `delegation_timeout` event with distinct timeout message (not generic failure)
- Runtime error: `delegation_failed` event with distinct failure message
- Operator termination of parent: all active sub-agents terminated, log reflects terminated outcome
- Guardrail outcomes (termination, observe-only) during delegation surfaced with clear labelling

---

## 3. Critical Scenarios

### Scenario 1: Full Delegation Lifecycle with Successful Completion

**WHEN** a non-conversational agent configured with delegation permission executes a task that delegates to a sub-agent
**AND** the sub-agent completes successfully
**THEN** the execution log displays `delegating to <sub-agent>`, a `waiting` indicator with animated progress, and a `delegation_resumed` event with successful outcome
**AND** all events appear in the execution log in real time without manual refresh
**AND** the delegation timeline shows colour-coded entries for each lifecycle stage
**AND** the parent agent continues execution after delegation resumes

### Scenario 2: Non-Conversational Agent Requests Human Input During Delegation (Approval Type)

**WHEN** a sub-agent delegated by a non-conversational agent calls `system____human_intervene` with type `approval`
**THEN** the parent execution log pauses and displays an inline intervention popup with Approve/Deny buttons
**AND** the parent `AgentJob.status` transitions to `waiting_for_human`
**AND** the live log stream emits a `human_intervene` event with intervention context
**WHEN** the operator clicks Approve
**THEN** the popup resolves to "Response submitted" state
**AND** the log stream resumes automatically
**AND** the intervention response (operator identity, decision, timestamp) is recorded in the execution timeline

### Scenario 3: Operator Dismisses Intervention Popup and Returns Later

**WHEN** a pending intervention request is active (sub-agent waiting for human input)
**AND** the operator dismisses the inline popup or navigates away
**THEN** a persistent `InterventionPendingBanner` appears at the top of the execution log with animated spinner, sub-agent name, intervention type, and "Respond Now" button
**WHEN** the operator clicks "Respond Now" or navigates back to the execution log
**THEN** the pending intervention is re-surfaced
**AND** the inline dialog is scrolled into view and focused
**WHEN** the operator responds
**THEN** the banner automatically hides

### Scenario 4: Delegation Depth Limit Enforced

**WHEN** a non-conversational agent (depth 0) delegates to a sub-agent (depth 1)
**THEN** delegation proceeds normally
**WHEN** the depth-1 sub-agent attempts to delegate further via `agent____<slug>`
**THEN** the delegation is blocked at the Agent Runtime level
**AND** a `delegation_depth_blocked` event is emitted with a clear message
**AND** the blocked sub-agent receives the blocked outcome as its tool result

### Scenario 5: Conversational Agent Delegation Depth Unchanged

**WHEN** a conversational agent delegates to a sub-agent
**AND** the sub-agent (depth 1) delegates further (depth 2, within conversational limit of 3)
**THEN** delegation proceeds normally (conversational path unchanged)
**AND** no depth-related blocking occurs for depths ≤ default conversational limit

### Scenario 6: Markdown Output Type — System Prompt Injection and Result Display

**WHEN** a non-conversational agent is configured with `output_type: markdown`
**AND** the agent executes a task and produces markdown output
**THEN** the agent's system prompt includes an explicit markdown formatting instruction (injected by `_format_user_prompt()`)
**THEN** the execution log viewer's Result tab renders the output as rich formatted HTML (not raw markdown)
**AND** the Result tab header displays an "Output Type: Markdown" badge

### Scenario 7: Typed JSON Output Type — System Prompt Injection and Result Display

**WHEN** a non-conversational agent is configured with `output_type: typed` and a JSON output schema
**AND** the agent executes a task and produces structured JSON output
**THEN** the agent's system prompt includes the output schema and a structured JSON instruction
**THEN** the execution log viewer's Result tab renders the output as an expandable/collapsible JSON tree
**AND** a "Schema" toggle is available to display the output schema alongside the result

### Scenario 8: Delegation Timeout — Distinct Visual Feedback

**WHEN** a non-conversational agent delegates to a sub-agent that exceeds the timeout
**THEN** a `delegation_timeout` event is emitted (not a generic failure)
**AND** the execution log displays a clear delegation-timeout status distinct from delegation-failed
**AND** the delegation timeline shows the timeout event with distinct error styling

### Scenario 9: Operator Terminates Parent During Active Delegation

**WHEN** a non-conversational agent is waiting on a delegated sub-agent (`waiting` status)
**AND** the operator terminates the parent session
**THEN** the parent session transitions to `terminated` status
**AND** all active delegated sub-agents are terminated
**AND** the execution log reflects the terminated outcome

### Scenario 10: Reconnect Recovery — Delegation Events and Pending Interventions

**WHEN** the live log stream connection is interrupted (browser tab sleep, network blip)
**AND** delegation status events were emitted during the disconnect
**THEN** on reconnect, all previously emitted delegation events are visible in the log timeline from `GET .../logs`
**WHEN** an intervention request became pending during the disconnect
**AND** the operator reconnects and opens the execution log
**THEN** `GET .../interventions/pending` returns the pending intervention
**AND** the intervention is re-surfaced inline in the log viewer

### Scenario 11: Intervention Request Expires Before Operator Responds

**WHEN** an intervention request is pending for a non-conversational delegation
**AND** the sub-agent times out before the operator responds
**THEN** the intervention request status transitions to `expired`
**AND** the inline dialog shows "Request no longer valid" with all controls disabled
**AND** a clear message indicates the request is no longer valid

### Scenario 12: Output Type "Auto" — No Prompt Injection, Raw Display

**WHEN** a non-conversational agent is configured with `output_type: auto`
**AND** the agent executes a task
**THEN** no additional output format instruction is added to the system prompt
**THEN** the execution log viewer's Result tab renders the output as raw formatted text in a `<pre>` block
**AND** the Result tab header displays an "Output Type: Auto" badge

---

## 4. Edge Cases & Risks

### Edge Cases

| # | Edge Case | Risk Level | Mitigation |
|---|-----------|------------|------------|
| E1 | Concurrent delegation to multiple sub-agents from one parent | Medium | Test that each sub-agent gets its own delegation lifecycle events and the log correctly interleaves them |
| E2 | Self-delegation (agent delegates to its own agent type) | Medium | Verify depth guard still applies (self-delegation counts as depth increment); test that self-delegation doesn't cause infinite loop |
| E3 | Sub-agent with `output_type` different from parent | Low | Verify each agent respects its own output type; the result tab reads from the parent agent's metadata, not the sub-agent's |
| E4 | Output type `typed` but `output_schema` is null or empty | Medium | Verify `_format_user_prompt()` handles missing schema gracefully (log warning, fall back to auto behaviour) |
| E5 | Very long markdown output (> 10K characters) | Low | Verify Result tab rendering doesn't freeze or overflow; test with realistic large markdown payloads |
| E6 | NDJSON stream delivers events out of order | Low | Delegation timeline sorts by timestamp regardless of arrival order |
| E7 | `TaskDelegationEventRouter` map cleared on CH restart | Medium | Verify that persisted events in CC log store are replayed on viewer reconnect; no events are permanently lost |
| E8 | Intervention response submitted simultaneously from two browser tabs | Low | CC intervention endpoint enforces idempotency (responded requests reject duplicate responses with appropriate error) |
| E9 | Agent type has `output_type` changed mid-execution | Low | Output type is read once at session start from snapshot — mid-execution changes don't affect running sessions |
| E10 | Non-conversational agent delegates to a conversational sub-agent | Medium | The sub-agent executes normally (conversational loop); the parent task agent waits for completion and emits delegation events as expected |

### Architectural Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| AR directly accesses DB for `parent_agent_job_id` | Violates `top_priority_rules` (only CC can access DB) | Code review gate: verify all intervention persistence goes through CC endpoints. Integration test asserts no DB models imported in AR. |
| Delegation depth enum change breaks conversational agents | Regression in existing conversational delegation | Dedicated conversational delegation regression test suite; depth limit override only in `_build_guardrail_state()` for non-conv agents |
| `TaskDelegationEventRouter` memory leak from unregistered viewers | CH memory growth under load | Unit test for register/unregister lifecycle; integration test simulates viewer disconnect without explicit unregister and verifies cleanup |
| Frontend `InterveneResponseDialog` modal conflicts with inline `TaskInterventionDialog` | Duplicate intervention UI shown simultaneously | Component test verifies only one dialog renders at a time per intervention event; E2E test confirms no double-popup |
| Stream reconnection during active intervention causes duplicate `humanInterveneEvent` | Double-dialog rendering | `useSessionExecutionLogStream` deduplicates by `request_id`; test verifies this |

---

## 5. Acceptance Criteria Checklist

Maps each PRD acceptance criterion to the test layer(s) that validate it.

### Delegation Status Visibility in Execution Log

| PRD AC | Description | Backend Unit | Backend Integration | Frontend Component | E2E |
|--------|-------------|:---:|:---:|:---:|:---:|
| AC-DS-1 | `delegating to <agent_type>` event appears in real time | ✅ | ✅ | — | ✅ |
| AC-DS-2 | `waiting` status with visible indicator during delegation | ✅ | ✅ | ✅ | ✅ |
| AC-DS-3 | `delegation_resumed` event when sub-agent completes | ✅ | ✅ | — | ✅ |
| AC-DS-4 | All delegation events appear without manual page refresh | — | — | ✅ | ✅ |
| AC-DS-5 | Live log stream shows work in progress (not stuck/idle) | — | — | ✅ | ✅ |

### User Intervention During Delegation

| PRD AC | Description | Backend Unit | Backend Integration | Frontend Component | E2E |
|--------|-------------|:---:|:---:|:---:|:---:|
| AC-UI-1 | Inline intervention popup with type and context during delegation | ✅ | ✅ | ✅ | ✅ |
| AC-UI-2 | Operator can approve/reject, choose, or enter text inline | — | — | ✅ | ✅ |
| AC-UI-3 | Log stream resumes automatically after response | ✅ | — | ✅ | ✅ |
| AC-UI-4 | Persistent pending banner when dialog dismissed/navigated away | — | — | ✅ | ✅ |
| AC-UI-5 | Pending intervention re-surfaced on return to execution log | ✅ | ✅ | ✅ | ✅ |
| AC-UI-6 | Intervention response captured in execution timeline for audit | ✅ | ✅ | ✅ | ✅ |

### Delegation Depth Enforcement

| PRD AC | Description | Backend Unit | Backend Integration | Frontend Component | E2E |
|--------|-------------|:---:|:---:|:---:|:---:|
| AC-DD-1 | Non-conv parent (depth 0) can delegate to one or more sub-agents | ✅ | — | — | ✅ |
| AC-DD-2 | Sub-agent delegated by non-conv cannot delegate further | ✅ | — | — | ✅ |
| AC-DD-3 | Depth limit blocked → clear outcome message in execution log | ✅ | ✅ | ✅ | ✅ |
| AC-DD-4 | Depth limit enforced server-side (AR level, not frontend) | ✅ | — | — | ✅ |

### Exit Conditions for Delegation

| PRD AC | Description | Backend Unit | Backend Integration | Frontend Component | E2E |
|--------|-------------|:---:|:---:|:---:|:---:|
| AC-EC-1 | Successful completion → `delegation_resumed` with successful outcome | ✅ | ✅ | ✅ | ✅ |
| AC-EC-2 | Timeout → distinct delegation-timeout status (not generic failure) | ✅ | ✅ | ✅ | ✅ |
| AC-EC-3 | Runtime error → distinct delegation-failure status | ✅ | ✅ | ✅ | ✅ |
| AC-EC-4 | Operator terminates parent → all sub-agents terminated, log reflects terminated outcome | ✅ | — | ✅ | ✅ |

### Output Type Respect & Result Display

| PRD AC | Description | Backend Unit | Backend Integration | Frontend Component | E2E |
|--------|-------------|:---:|:---:|:---:|:---:|
| AC-OT-1 | `output_type: markdown` → system prompt includes markdown instruction | ✅ | — | — | ✅ |
| AC-OT-2 | `output_type: typed` → system prompt includes schema + JSON instruction | ✅ | — | — | ✅ |
| AC-OT-3 | `output_type: auto` → no additional format instruction | ✅ | — | — | — |
| AC-OT-4 | Result tab renders markdown as rich HTML | — | — | ✅ | ✅ |
| AC-OT-5 | Result tab renders typed JSON as structured tree | — | — | ✅ | ✅ |
| AC-OT-6 | Result tab renders auto as raw text | — | — | ✅ | ✅ |
| AC-OT-7 | Result tab visible immediately when session completes | — | — | ✅ | ✅ |
| AC-OT-8 | Output type labelled in Result tab header | — | — | ✅ | ✅ |

### Error Handling & Edge Cases

| PRD AC | Description | Backend Unit | Backend Integration | Frontend Component | E2E |
|--------|-------------|:---:|:---:|:---:|:---:|
| AC-EH-1 | Reconnect → previously emitted delegation events visible | — | ✅ | ✅ | ✅ |
| AC-EH-2 | Late intervention response → "request no longer valid" shown | ✅ | ✅ | ✅ | ✅ |
| AC-EH-3 | Guardrail outcomes during delegation → clear labelling in log | ✅ | ✅ | ✅ | ✅ |

---

## 6. Test File References

### Backend Tests — `backend/tests/`

| Test File | Scope | Covers | Status | Tests |
|-----------|-------|--------|--------|-------|
| `backend/tests/unit/test_delegation_depth_guard.py` | Unit | AC-DD-1 through AC-DD-4: Delegation depth limit enforcement, `max_delegation_depth` override, `delegation_depth_blocked` emission, conversational path unchanged | ✅ Created | 17 tests |
| `backend/tests/unit/test_task_delegation_status_events.py` | Unit | AC-DS-1 through AC-DS-5: Delegation lifecycle event emission in `_act()`, event types, real-time event sequence | ✅ Created | 8 tests |
| `backend/tests/unit/test_task_agent_hitl_suspension.py` | Unit | AC-UI-1 through AC-UI-6: Parent status transition to `waiting_for_human`, HITL propagation through `call_a2a_request()`, response injection, intervention recording | ✅ Created | 11 tests |
| `backend/tests/unit/test_output_type_prompt_injection.py` | Unit | AC-OT-1 through AC-OT-3: `_format_user_prompt()` output type instruction injection, schema injection, auto no-op, conversational agent non-interference | ✅ Created | 15 tests |
| `backend/tests/unit/test_task_delegation_router.py` | Unit | N/A (infrastructure): `TaskDelegationEventRouter` register/unregister, push event, push intervene request, viewer connection tracking, fallback when no viewer connected | ✅ Created | 15 tests |
| `backend/tests/unit/test_hitl_delegation_status_events.py` | Unit | AC-UI-1 through AC-UI-6: Non-conversational HITL delegation status event routing | ✅ Created | 2 tests |
| `backend/tests/unit/test_a2a_hitl_timeout.py` | Unit | AC-EC-2, AC-EH-2: A2A HITL timeout handling in delegation context | ✅ Created | 4 tests |
| `backend/tests/unit/test_ws_delegation_visibility.py` | Unit | AC-DS-1 through AC-DS-5: Delegation event visibility through WebSocket/stream | ✅ Created | 1 test |
| `backend/tests/services/test_intervene_service.py` | Integration | AC-UI-5, AC-UI-6, AC-EH-2: `InterveneRequest` CRUD, status transitions, response submission, expiration, cancellation, metrics | ✅ Created | 28 tests |
| `backend/tests/integration/test_intervention_api_integration.py` | Integration | API endpoint correctness: `POST /interventions/`, `POST /interventions/{id}/respond`, delegation depth tracking | ✅ Created | — |
| `backend/tests/integration/test_internal_intervene_respond.py` | Integration | Internal intervene respond flow through CH → CC | ✅ Created | — |
| `backend/tests/integration/test_intervention_schema_migration.py` | Integration | DB schema migration handling for intervention-related changes (no `parent_agent_job_id` column added — verifies existing schema sufficiency) | ✅ Created | — |
| `backend/tests/api/v1/test_intervene.py` | Integration | API-level intervene request and response endpoint tests | ✅ Created | — |

### Frontend Tests — `frontend/src/__tests__/`

| Test File | Scope | Covers | Status | Tests |
|-----------|-------|--------|--------|-------|
| `frontend/src/__tests__/DelegationTimeline.test.tsx` | Component | AC-DS-1 through AC-DS-5: Event filtering, colour-coded icons per event type | ✅ Created | 11 tests |
| `frontend/src/__tests__/TaskInterventionDialog.test.tsx` | Component | AC-UI-1, AC-UI-2, AC-EH-2: Approval/choice/text modes, resolved/expired states | ✅ Created | 13 tests |
| `frontend/src/__tests__/InterventionPendingBanner.test.tsx` | Component | AC-UI-4: Pending/not-pending visibility, type labels, Respond Now callback | ✅ Created | 10 tests |
| `frontend/src/__tests__/OutputTypeResultTab.test.tsx` | Component | AC-OT-4 through AC-OT-8: Markdown/Typed/Auto badge rendering, null data handling | ✅ Created | 11 tests |
| `frontend/src/__tests__/LogPresenter.test.ts` | Component (existing) | N/A: Delegation event type `iconTypeFromEntry()` mappings | ✅ Created | — |
| `frontend/src/__tests__/ConversationDelegationVisibility.test.tsx` | Component (new) | AC-DS-1 through AC-DS-5: Delegation visibility in conversation context | ✅ Created | — |
| `frontend/src/__tests__/AgentExecutionDetailsDialog.test.tsx` | Component (existing) | AC-UI-1 through AC-UI-4, AC-OT-7 | ⬜ Planned | — |
| `frontend/src/__tests__/useSessionExecutionLogStream.test.ts` | Hook (existing) | AC-UI-1, AC-UI-5, AC-EH-1 | ⬜ Planned | — |
| `frontend/src/__tests__/AgentSessionPage.test.tsx` | Component (existing) | AC-OT-4 through AC-OT-8 | ⬜ Planned | — |

### E2E Tests — `e2e/tests/`

| Test File | Scope | Covers | Status | Tests |
|-----------|-------|--------|--------|-------|
| `e2e/tests/delegation-lifecycle-visibility.spec.ts` | E2E (new, mocked) | Delegation lifecycle events rendering: started, resumed, depth_blocked, timeout, failed, multi-event view, no-delegation hidden | ✅ Created | 7 tests |
| `e2e/tests/task-agent-delegation-hitl.spec.ts` | E2E (new, live) | Full HITL round-trip — sub-agent intervention, popup response, banner, expired | ⬜ Planned | — |
| `e2e/tests/task-agent-delegation-depth-limit.spec.ts` | E2E (new, live) | Depth limit enforcement E2E | ⬜ Planned | — |
| `e2e/tests/task-agent-output-type-result.spec.ts` | E2E (new, live) | Output type E2E — markdown/typed/auto Result tab | ⬜ Planned | — |
| `e2e/tests/conversation-delegation-visibility.spec.ts` | E2E (existing) | Regression: conversational delegation unchanged | 🔄 Existing | — |
| `e2e/tests/conversation-intervention.spec.ts` | E2E (existing) | Regression: conversational intervention unchanged | 🔄 Existing | — |
| `e2e/tests/intervene.spec.ts` | E2E (existing) | Regression: conversational HITL unchanged | 🔄 Existing | — |

---

## 7. Test Execution Order

For developers implementing these tests, the recommended build order is:

1. **Backend unit tests first** (depth guard, status events, output type injection, task delegation router) — these validate core logic with no service dependencies
2. **Backend integration tests** (intervene `parent_agent_job_id`, new API endpoints, log event type acceptance) — these validate the data and API layers
3. **Frontend component tests** (DelegationTimeline, TaskInterventionDialog, OutputTypeResultTab, LogPresenter, InterventionPendingBanner) — these validate UI rendering and state
4. **Updated component/hook tests** (AgentExecutionDetailsDialog, useSessionExecutionLogStream) — these validate integration of new components into existing views
5. **E2E tests** — these validate the full stack end-to-end; requires all services running with the implemented changes

---

## 8. Test Data Conventions

All test data MUST follow these conventions to avoid collisions and ensure clean teardown:

- **Prefix**: `e2e-test-` for E2E, `unit-test-` for unit, `itest-` for integration
- **Timestamp suffix**: Append `-${Date.now()}` or `_${uuid4().hex[:8]}` for uniqueness
- **Cleanup**: All tests clean up created resources in `afterEach`/`teardown` (delete test agent types, test jobs, test intervention requests)
- **Distinct names**: Test agent types use descriptive names like `Task Agent — Delegation E2E — Markdown Output` to aid debugging in database/log inspection

## 9. Success Metrics

All tests across all layers must pass with:

- **Backend unit tests**: 0 failures, covering all new and modified code paths in `runtime_executor.py`, `guardrails.py`, `intervene_service.py`, `task_delegation_router.py`
- **Backend integration tests**: 0 failures, confirming new API endpoint correctness and event type acceptance (no schema changes required)
- **Frontend component tests**: 0 failures, all new components rendering correctly in all states (loading, active, resolved, expired, error)
- **E2E tests**: 0 failures against the live backend stack, validating real-time streaming, intervention round-trips, and full delegation lifecycles
- **No regressions**: All existing conversational delegation, HITL, and execution log tests continue to pass unchanged
