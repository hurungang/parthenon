# Test Plan — Conversational Agent Intervention

## 1. Test Strategy

This test plan validates the inline intervention flow for conversational agent sessions — when a delegated sub-agent calls `human_intervene`, the intervention surfaces in the conversation UI via WebSocket instead of the operator dashboard. This is distinct from the non-conversational `human_intervene` flow (covered by `human-intervene-test-plan.md`).

| Layer | Framework | Scope |
|---|---|---|
| **Backend Unit** | pytest + SQLite | `TurnType` enum values; `ConversationTurn` with `turn_type`/`intervene_request_id`; `InterveneRequest` with `conversation_session_id`/`delegation_depth`; store operations; HITL timeout and delegation status events |
| **Backend Integration** | pytest + PostgreSQL (`parthenon_test`) | Schema migration verification (`information_schema`); API endpoint integration (pending list, respond, real backend); non-conversational flow regression |
| **Frontend Component** | Vitest + React Testing Library | `InlineInterventionDialog` (approval/choice/text); `InterventionPendingIndicator`; `useConversationIntervention` hook; `useChatSession` WebSocket intervention handling |
| **E2E (Mocked)** | Playwright + `page.route()` | Conversation UI intervention flow with mocked API/WebSocket; audit turn visibility |
| **E2E (Real Backend)** | Playwright (no mocks) | Full intervention lifecycle against live backend; schema migration validation; real WebSocket delivery |
| **Manual / Exploratory** | Manual | Multi-SOP workflow delegation; operator dashboard unchanged; cross-service boundary edge cases |

## 2. Coverage Areas

| Area | Why Critical |
|---|---|
| Database schema changes | New fields on `ConversationTurn` (`turn_type` enum, `intervene_request_id` FK) and `InterveneRequest` (`conversation_session_id`, `delegation_depth`) with NOT NULL constraints and default values — missing or misconfigured constraints silently corrupt intervention linkage |
| Core intervention surfacing in conversations | Delegated sub-agent `human_intervene` calls MUST surface inline in conversation UI via WebSocket, replacing the prior broken indefinite-waiting state — this is the primary user-facing change |
| Conversation pause & resume | Message input must be blocked while intervention is pending; cancellation and termination must correctly cascade to sub-agents |
| Intervention queue (concurrent requests) | Multiple delegated sub-agents each calling `human_intervene` in parallel must be serialized FIFO in the UI to prevent overlapping dialogs |
| Audit & traceability | `intervene_request` and `intervene_response` turns must be persisted in conversation history with type, prompt, options, operator identity, response value, timestamp, and delegation chain metadata |
| Non-conversational flow preservation | Existing non-conversational intervention flow (operator dashboard, `running → waiting_for_human → running` state transitions) must work unchanged — regression here is a showstopper |
| Service boundary enforcement | Agent Runtime must never connect to database; agent-instance certs blocked from `/internal/*`; all intervention persistence through CC API |
| Error handling & edge cases | Reconnection re-surfaces pending intervention; sub-agent timeout shows timeout message; permission errors surfaced clearly; race conditions handled idempotently |

## 3. Critical Scenarios

### Scenario 1: Full Intervention Lifecycle — Approval Type

- **WHEN** a user sends a chat message that causes a delegated sub-agent to call `human_intervene(type=approval, prompt="Approve this action?")`
- **THEN** an inline intervention dialog appears in the conversation with Yes/No options
- **THEN** the message input field is disabled with a "Waiting for your input" indicator
- **THEN** an `intervene_request` conversation turn is persisted with the approval prompt visible
- **WHEN** the user clicks Yes and submits
- **THEN** the dialog closes, an `intervene_response` turn appears in the conversation showing the approval response
- **THEN** the sub-agent resumes execution and the conversation continues normally

### Scenario 2: Choice-Type Intervention

- **WHEN** a delegated sub-agent calls `human_intervene(type=choice, choices=["Option A", "Option B", "Option C"])`
- **THEN** the dialog renders select-list with all three options; submit disabled until selection made
- **WHEN** a selection is made and submitted
- **THEN** the selected choice value is persisted in the response turn and passed to the sub-agent

### Scenario 3: Text-Type Intervention

- **WHEN** a sub-agent calls `human_intervene(type=text, prompt="Describe the desired output format")`
- **THEN** a free-text input field appears in the dialog; submit disabled when field is empty
- **WHEN** text is entered and submitted
- **THEN** the text value is persisted and injected into the sub-agent

### Scenario 4: Intervention Cancellation

- **WHEN** an intervention dialog is open and the user clicks Cancel/Dismiss
- **THEN** a cancellation signal is sent to the sub-agent; `InterveneRequest` status updates to `cancelled`; message input re-enabled; conversation shows cancellation notice as a turn

### Scenario 5: Parent Session Termination During Pending Intervention

- **WHEN** an intervention is pending in a conversation and the parent session is terminated
- **THEN** the pending intervention request is set to `cancelled` (or `expired`); conversation shows the termination outcome

### Scenario 6: Concurrent Intervention Queuing

- **WHEN** Sub-Agent A calls `human_intervene` (request R1) and before R1 is resolved, Sub-Agent B also calls `human_intervene` (request R2)
- **THEN** R1 appears in the UI first; R2 is queued and does NOT appear until R1 is resolved or cancelled
- **WHEN** R1 is resolved
- **THEN** R2 is delivered to the UI immediately

### Scenario 7: Reconnection with Pending Intervention

- **WHEN** an intervention dialog is open and the user disconnects (page close, network drop)
- **THEN** the `InterveneRequest` remains in `pending` status
- **WHEN** the user reconnects to the conversation
- **THEN** the UI calls `GET /api/v1/conversations/{session_id}/interventions/pending` and the intervention dialog is re-surfaced with original prompt and options intact

### Scenario 8: Sub-Agent Timeout While Waiting

- **WHEN** a sub-agent is waiting for intervention response and the request timeout is reached
- **THEN** the request status changes to `expired`; a timeout message appears in the conversation; message input is re-enabled

### Scenario 9: Permission-Denied Intervention Response

- **WHEN** a user attempts to respond to an intervention without sufficient permissions
- **THEN** the response is rejected with a 403; a clear permission error message appears in the dialog (not a silent failure); dialog stays open

### Scenario 10: Non-Conversational Flow — No Regression

- **WHEN** a non-conversational agent session calls `human_intervene` (no `conversation_session_id` on the agent job)
- **THEN** the intervention request appears in the operator dashboard (existing flow); no WebSocket message sent to any conversation UI; session states transition `running → waiting_for_human → running` unchanged; `InterveneRequest` record has NULL `conversation_session_id` and `delegation_depth = 0`

## 4. Edge Cases & Risks

| Edge Case | Risk Level | Mitigation |
|---|---|---|
| `conversation_session_id` is NULL on non-conversational `InterveneRequest` | **High** | Backend integration test MUST verify NULL is accepted; existing dashboard flow MUST still work |
| Intervention Router receives `session_id` for conversation with no active WebSocket | Medium | Router must hold pending and deliver on reconnect; verified via reconnection scenario |
| CH routes intervention to wrong conversation session (cross-session leak) | **High** | Test with two simultaneous conversations; verify each gets only its own intervention requests |
| `human_intervene` tool contract change accidentally breaks existing tool invocations | **High** | Contract must be unchanged — only routing layer changes; verify tool input/output schema unchanged |
| Race condition: user submits response and cancels simultaneously | Medium | Idempotent status transitions; second operation rejected gracefully |
| Multiple browser tabs on same conversation | Medium | All tabs connected via WebSocket should receive; response from any should resolve |
| `turn_type` defaults to `message` for existing rows | Low | No data migration needed; verify default constraint works |
| `delegation_depth` negative values | Low | Verify DB constraint CHECK >= 0 or Pydantic validation Field(ge=0) |
| Very large intervention prompt or choices payload exceeds WebSocket frame | Low | Validate with max-size payload; truncation or pagination if needed |

### Project-Level Risks

- **Service segregation**: AR must never touch DB or receive identity tokens. Any new endpoint or data path that bypasses CC is a blocker.
- **Certificate auth boundary**: The Intervention Router runs in CH. CH must continue authenticating to CC with service cert. Any change that grants agent-instance certs access to internal CC endpoints is a blocker.
- **Migration ordering**: New fields on `ConversationTurn` and `InterveneRequest` must be applied before new API endpoints are deployed; verify migration revision chain is clean.

## 5. Acceptance Criteria Checklist

### Core Intervention Flow in Conversations
- [ ] AC-1: Delegated sub-agent `human_intervene` call surfaces inline intervention dialog in conversation UI
- [ ] AC-2: Conversation shows "Waiting for your input" indicator replacing indefinite waiting state
- [ ] AC-3: Dialog supports all three intervention types: Approval (Yes/No), Choice (select from options), Text (free-form)
- [ ] AC-4: After user responds, dialog closes, sub-agent resumes, conversation continues
- [ ] AC-5: User response appears as intervention response turn in conversation

### Conversation Pause and Resume
- [ ] AC-6: "Waiting for human input" status visible while sub-agent awaits intervention
- [ ] AC-7: No new user messages can be sent while intervention is outstanding
- [ ] AC-8: Dialog dismiss/cancel → sub-agent receives cancellation signal → conversation resumes
- [ ] AC-9: Parent session termination → pending intervention cancelled → termination outcome shown

### Audit and Traceability
- [ ] AC-10: Every intervention request persisted as `intervene_request` turn with type, context, and options
- [ ] AC-11: Every intervention response persisted as `intervene_response` turn with operator identity, response value, timestamp
- [ ] AC-12: Intervention turns visible in conversation history, audit views, and replay
- [ ] AC-13: Delegation chain (sub-agent, depth) preserved in intervention records

### Non-Conversational Flow Preservation
- [ ] AC-14: Existing non-conversational intervention flow works unchanged
- [ ] AC-15: Non-conversational intervention requests continue to appear in operator dashboard
- [ ] AC-16: Session state transitions preserved (`running → waiting_for_human → running`)

### Error Handling and Edge Cases
- [ ] AC-17: Disconnected user → pending intervention re-surfaced on reconnect
- [ ] AC-18: Multiple parallel intervention requests → queued and presented sequentially
- [ ] AC-19: Sub-agent timeout → clear timeout message in conversation
- [ ] AC-20: Permission errors → surfaced with clear error message in dialog (not silent)

## 6. Database Migration Requirements

This change has `has_db_changes: true`. Backend integration tests must verify schema changes against a real PostgreSQL database with `alembic upgrade head` applied.

### Schema Changes to Verify
- `ConversationTurn.turn_type` — enum with values `message`, `intervene_request`, `intervene_response`; default `message`; NOT NULL
- `ConversationTurn.intervene_request_id` — nullable FK to `intervene_requests.id`
- `InterveneRequest.conversation_session_id` — nullable FK to `conversation_sessions.id`; must accept NULL (non-conversational flow)
- `InterveneRequest.delegation_depth` — integer; default 0; NOT NULL; minimum 0

### Pre-Test Checklist
- [ ] Verify migration applied: `python -m alembic current` shows expected revision ID
- [ ] All three services running (CC on 8000, AR on 8001, CH on 8002)
- [ ] CC health endpoint returns 200
- [ ] Test operator user has intervention response permissions

## 7. Test File References

### Backend Tests — `backend/tests/`

| Test File | Covers |
|---|---|
| `backend/tests/unit/test_conversation_intervention_turns.py` | `TurnType` enum values; `ConversationTurn` with `turn_type`/`intervene_request_id`; `InterveneRequest` with `conversation_session_id`/`delegation_depth`; store operations for add_turn, create_request, list_pending, submit_response; service boundary enforcement (26 tests) |
| `backend/tests/integration/test_intervention_schema_migration.py` | Database schema verification: column existence checks for `turn_type`, `intervene_request_id`, `conversation_session_id`, `delegation_depth`; `TurnType` enum value completeness; NULL acceptance for FK columns; FK constraint verification (11 tests) |
| `backend/tests/integration/test_intervention_api_integration.py` | Full API integration: `GET /conversations/{id}/interventions/pending`; `POST /conversations/{id}/interventions/{req_id}/respond` (approval/choice/text); existing endpoints return `turn_type` and `intervene_request_id` (13 tests) |
| `backend/tests/integration/test_non_conversational_regression.py` | Non-conversational flow preservation: create/respond/cancel without `conversation_session_id`; AgentJob status transition; dashboard visibility; metrics; mixed conv/non-conv coexistence (8 tests) |
| `backend/tests/unit/test_a2a_hitl_timeout.py` | HITL timeout handling: `_wait_for_receiver_result` deadline extension; terminal status deferred expiry; `Request` parameter injection fix (4 tests) |
| `backend/tests/unit/test_hitl_delegation_status_events.py` | HITL delegation status events: `waiting_for_human` and `delegation_resumed` event emission; correct event sequence ordering (2 tests) |

### Frontend Tests — `frontend/src/__tests__/`

| Test File | Covers |
|---|---|
| `frontend/src/__tests__/InlineInterventionDialog.test.tsx` | Inline dialog component: approval/choice/text rendering; submit/dismiss callbacks; disabled submit until choice/text entered; error display; loading state; badge rendering (19 tests) |
| `frontend/src/__tests__/InterventionPendingIndicator.test.tsx` | "Waiting for your input" indicator; inline/non-inline variants; CircularProgress spinner; warning color treatment (5 tests) |
| `frontend/src/__tests__/ConversationDialog.intervention.test.tsx` | Hook-level integration: `useChatSession` exposes `interventionRequest`, `interventionQueueLength`, `sendInterventionResponse`, `cancelIntervention` (3 tests) |
| `frontend/src/__tests__/useConversationIntervention.test.ts` | Hook tests: fetch pending on mount; null sessionId handling; empty state; WebSocket primary + REST fallback for respond/cancel; error handling (9 tests) |
| `frontend/src/__tests__/useChatSession.intervention.test.ts` | WebSocket message parsing: `intervene_request` (approval/choice/text); `intervene_status` (responded/cancelled clears state); chat message blocking; sendInterventionResponse/cancelIntervention WebSocket sends (9 tests) |

### E2E Tests — `e2e/tests/`

| Test File | Covers |
|---|---|
| `e2e/tests/conversation-intervention.spec.ts` | Mocked variant: intervention page loads; conversation history page loads; intervene request mock data renders; no redirect to login. Real Backend Integration variant: `GET /conversations`, `GET /intervene/requests`, `GET /intervene/metrics`, `GET /health`, pending interventions for unknown session (404), respond endpoint rejects invalid request (10 tests) |
| `e2e/tests/intervene.spec.ts` | Human Intervene approval response flow: submitting approval response sends API call |
| `e2e/tests/conversation-delegation-visibility.spec.ts` | Conversation delegation status and waiting UI: thinking → delegating → waiting transitions; collapsible snippet UI; fold/expand/collapse interaction |

## 8. Out of Scope for Testing

- Mobile or push-notification intervention response
- Custom intervention types beyond Approval/Choice/Text
- Batch/parallel intervention resolution
- A2A intervention outside user-facing conversations
- Changes to the `human_intervene` tool contract itself
- Operator dashboard UI changes (verified via regression only)

## 9. Related Test Plans

- **[Human Intervene Test Plan](human-intervene-test-plan.md)** — Non-conversational intervention flow (operator dashboard, session state machine)
- **[Conversation Sessions Test Plan](conversation-sessions-test-plan.md)** — Session lifecycle, ownership, resume, and WebSocket title updates
- **[Agent Runtime Test Plan](agent-runtime-test-plan.md)** — Agent execution, tool calling, and HITL tool integration
- **[Communication Hub Test Plan](communication-hub-test-plan.md)** — WebSocket routing, intervention relay, and cross-session isolation
