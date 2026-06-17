# Test Plan: Conversational Agent Intervention

## 1. Test Strategy

| Layer | Framework | Scope | Approach |
|---|---|---|---|
| **Backend Unit** | pytest + SQLite in-memory | Schema changes on `ConversationTurn` and `InterveneRequest`; intervention routing logic; API endpoint handlers; Communication Hub message routing | Async test functions with mocked DB sessions and service dependencies |
| **Backend Integration** | pytest + real PostgreSQL (`parthenon_test`) | Database migration verification; schema constraints; endpoint integration (request → response → DB state); service-boundary enforcement | Real DB connections via `async_sessionmaker`; verify `information_schema` for new columns and enums; test FK and nullable constraints |
| **Frontend Component** | Vitest + React Testing Library | Intervention Dialog component; ConversationDialog intervention integration; pending indicator component; WebSocket message handling hooks | Mocked API, WebSocket, and service hooks; assert rendering of approval/choice/text types; verify message-blocking and status indicators |
| **E2E (Mocked)** | Playwright + page.route() | Conversation UI intervention flow with mocked API/WebSocket; UI state transitions; dialog interactions; audit turn visibility | Quick, isolated UI behavior validation without real backend |
| **E2E (Real Backend)** | Playwright (no mocks) | Full intervention lifecycle against live backend; schema migration validation; real WebSocket delivery; audit trail persistence | `test.describe('Real Backend Integration - Conversational Agent Intervention')` — direct HTTP/WS calls to running services |
| **Manual / Exploratory** | Manual | Non-conversational flow regression; multi-SOP workflow delegation; operator dashboard unchanged | Checklist-based smoke testing; cross-service boundary edge cases |

---

## 2. Coverage Areas

### 2.1 Database Schema Changes (has_db_changes: true)

**Critical**: These new fields and constraints must be verified at the schema level.

- `ConversationTurn.turn_type` — enum with values `message`, `intervene_request`, `intervene_response`; default `message`; NOT NULL
- `ConversationTurn.intervene_request_id` — nullable FK to `intervene_requests.id`; ON DELETE SET NULL or RESTRICT (verify)
- `InterveneRequest.conversation_session_id` — nullable FK to `conversation_sessions.id`; must accept NULL (non-conversational flow preserved)
- `InterveneRequest.delegation_depth` — integer; default 0; NOT NULL; minimum 0

**Why critical**: Missing or misconfigured constraints silently corrupt intervention linkage. A non-nullable `conversation_session_id` would break all existing non-conversational interventions. Missing `turn_type` enum values would prevent turn classification.

### 2.2 Core Intervention Flow in Conversations

- Surfacing delegated sub-agent `human_intervene` calls in conversation UI via WebSocket
- Blocking new user messages while an intervention is pending
- Inline intervention dialog rendering (approval / choice / text types)
- User response sent via WebSocket → CC persist → AR resume
- Conversation resumption after intervention resolution
- "Waiting for your input" indicator during pending state

**Why critical**: This is the primary user-facing change. Without it, the existing broken state (silent hang) persists.

### 2.3 Conversation Pause & Resume

- `chat` message blocking when `intervention_pending` state is active
- Cancellation signal on dialog dismiss → sub-agent receives cancel → conversation resumes
- Parent session termination → pending intervention cancelled → termination outcome displayed

**Why critical**: Users must not be able to race ahead of an outstanding intervention. Termination cascading prevents orphaned intervention requests.

### 2.4 Intervention Queue (Concurrent Requests)

- Multiple delegated sub-agents each call `human_intervene` in parallel
- Requests delivered to UI one at a time (FIFO)
- Each resolved/cancelled before the next appears

**Why critical**: Without queuing, UI state corruption could surface multiple overlapping dialogs.

### 2.5 Audit & Traceability

- `intervene_request` turn persisted in conversation with type, prompt, options, delegation chain
- `intervene_response` turn persisted with operator identity, response value, timestamp
- Turns visible in conversation history and audit views
- Delegation chain metadata preserved (sub-agent, depth) on the `InterveneRequest` record

**Why critical**: Compliance auditors must see complete decision trails. Missing turns = audit gap.

### 2.6 Non-Conversational Flow Preservation (Regression)

- Non-conversational intervention requests still appear in operator dashboard
- Session state transitions (`running` → `waiting_for_human` → `running`) unchanged
- Existing `InterveneRequest` records without `conversation_session_id` still function normally
- Dashboard polling continues to work

**Why critical**: Breaking the existing intervention flow for non-conversational agents is a showstopper regression.

### 2.7 Service Boundary Enforcement

- Agent Runtime never connects to database (CC is sole DB accessor)
- Agent Runtime never receives user identity tokens
- Certificate-based authentication preserved: agent-instance certs blocked from `/internal/*`
- All intervention persistence goes through CC API

**Why critical**: Top-priority architecture rule violations are unacceptable.

### 2.8 Error Handling & Edge Cases

- Reconnection: pending intervention re-surfaced on UI reconnect via `GET /interventions/pending`
- Timeout: sub-agent timeout → expired status → timeout message in conversation
- Permission errors: user lacks permission → clear error in dialog (not silent)
- Multiple parallel requests: queued sequentially, not dropped

**Why critical**: These are the PRD-explicit edge cases that must work for production readiness.

---

## 3. Critical Scenarios

### Scenario 1: Full Intervention Lifecycle — Approval Type

- WHEN a user sends a chat message that causes a delegated sub-agent to call `human_intervene(type=approval, prompt="Approve this action?")`
- THEN an inline intervention dialog appears in the conversation with Yes/No options
- THEN the message input field is disabled with a "Waiting for your input" indicator
- THEN an `intervene_request` conversation turn is persisted with the approval prompt visible
- WHEN the user clicks Yes and submits
- THEN the dialog closes, an `intervene_response` turn appears in the conversation showing the approval response
- THEN the sub-agent resumes execution and the conversation continues normally

### Scenario 2: Choice-Type Intervention

- WHEN a delegated sub-agent calls `human_intervene(type=choice, choices=["Option A", "Option B", "Option C"])`
- THEN the dialog renders radio-button or select-list with all three options
- THEN the user must select one before submitting (submit button disabled until selection made)
- WHEN a selection is made and submitted
- THEN the selected choice value is persisted in the response turn and passed to the sub-agent

### Scenario 3: Text-Type Intervention

- WHEN a sub-agent calls `human_intervene(type=text, prompt="Describe the desired output format")`
- THEN a free-text input field appears in the dialog
- THEN submit is disabled when the field is empty
- WHEN text is entered and submitted
- THEN the text value is persisted and injected into the sub-agent

### Scenario 4: Intervention Cancellation

- WHEN an intervention dialog is open in the conversation
- AND the user clicks Cancel/Dismiss
- THEN a cancellation signal is sent to the sub-agent
- THEN the `InterveneRequest` status updates to `cancelled`
- THEN the message input field is re-enabled
- THEN the conversation shows a cancellation notice as a turn

### Scenario 5: Parent Session Termination During Pending Intervention

- WHEN an intervention is pending in a conversation
- AND the parent session is terminated (via runtime dashboard or timeout)
- THEN the pending intervention request is set to `cancelled` (or `expired`)
- THEN the conversation shows the termination outcome

### Scenario 6: Concurrent Intervention Queuing

- WHEN a conversation has Sub-Agent A call `human_intervene` (request R1)
- AND before R1 is resolved, Sub-Agent B also calls `human_intervene` (request R2)
- THEN R1 appears in the UI first
- THEN R2 is queued and does NOT appear until R1 is resolved or cancelled
- WHEN R1 is resolved
- THEN R2 is delivered to the UI immediately

### Scenario 7: Reconnection with Pending Intervention

- WHEN an intervention dialog is open
- AND the user disconnects (page close, network drop)
- THEN the `InterveneRequest` remains in `pending` status
- WHEN the user reconnects to the conversation
- THEN the UI calls `GET /api/v1/conversations/{session_id}/interventions/pending`
- THEN the intervention dialog is re-surfaced with the original prompt and options intact

### Scenario 8: Sub-Agent Timeout While Waiting

- WHEN a sub-agent is waiting for intervention response
- AND the intervention request timeout is reached
- THEN the request status changes to `expired`
- THEN a timeout message appears in the conversation
- THEN the message input is re-enabled

### Scenario 9: Permission-Denied Intervention Response

- WHEN a user attempts to respond to an intervention without sufficient permissions
- THEN the response is rejected with a 403
- THEN a clear permission error message appears in the dialog (not a silent failure)
- THEN the dialog stays open so the user can retry or a higher-privilege operator can take over

### Scenario 10: Non-Conversational Flow — No Regression

- WHEN a non-conversational agent session calls `human_intervene` (no `conversation_session_id` on the agent job)
- THEN the intervention request appears in the operator dashboard (existing flow)
- THEN no WebSocket message is sent to any conversation UI
- THEN session states transition `running` → `waiting_for_human` → `running` unchanged
- THEN the `InterveneRequest` record has NULL `conversation_session_id` and `delegation_depth = 0`

---

## 4. Edge Cases & Risks

### 4.1 Edge Cases

| Edge Case | Risk Level | Mitigation |
|---|---|---|
| `turn_type` defaults to `message` for existing rows — no data migration needed | Low | Verify default constraint works; existing turns unaffected |
| `intervene_request_id` is NULL for regular message turns | Low | Verify nullable FK constraint; test that regular turns don't require an intervene_request_id |
| `conversation_session_id` is NULL on non-conversational InterveneRequest | **High** | Backend integration test MUST verify NULL is accepted; existing dashboard flow MUST still work |
| `delegation_depth` negative values | Low | Verify DB constraint (CHECK >= 0) or Pydantic validation (Field(ge=0)) |
| Intervention Router receives a `session_id` for a conversation that has no active WebSocket | Medium | Router must hold pending and deliver on reconnect; verify via reconnection scenario |
| CH routes intervention to wrong conversation session (cross-session leak) | **High** | Test with two simultaneous conversations; verify each gets only its own intervention requests |
| `human_intervene` tool contract change accidentally breaks existing tool invocations | **High** | Contract must be unchanged — only routing layer changes; verify tool input/output schema unchanged |
| Race condition: user submits response and cancels simultaneously | Medium | Idempotent status transitions; second operation should be rejected gracefully (already `responded` or `cancelled`) |
| Very large intervention prompt or choices payload exceeds WebSocket frame | Low | Truncation or pagination; validate with max-size payload |
| Multiple browser tabs open on same conversation — which gets the intervene_request? | Medium | All tabs connected via WebSocket should receive; response from any should resolve |

### 4.2 Project-Level Risks

- **Service segregation**: AR must never touch DB or receive identity tokens. Any new endpoint or data path that bypasses CC is a blocker.
- **Certificate auth boundary**: The Intervention Router runs in CH. CH must continue authenticating to CC with service cert. Any change that grants agent-instance certs access to internal CC endpoints is a blocker.
- **Migration ordering**: New fields on `ConversationTurn` and `InterveneRequest` must be applied before new API endpoints are deployed; verify migration revision chain is clean.

---

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
- [ ] AC-16: Session state transitions preserved (`running` → `waiting_for_human` → `running`)

### Error Handling and Edge Cases

- [ ] AC-17: Disconnected user → pending intervention re-surfaced on reconnect
- [ ] AC-18: Multiple parallel intervention requests → queued and presented sequentially
- [ ] AC-19: Sub-agent timeout → clear timeout message in conversation
- [ ] AC-20: Permission errors → surfaced with clear error message in dialog (not silent)

---

## 6. Test File References

### 6.1 Backend Tests — `backend/tests/`

| Test File | Covers |
|---|---|
| `backend/tests/unit/test_conversation_intervention_turns.py` | **Combined unit tests**: `TurnType` enum values; `ConversationTurn` with `turn_type` and `intervene_request_id`; `InterveneRequest` with `conversation_session_id` and `delegation_depth`; `ConversationStore.add_turn` with intervention params; `InterveneRequestStore.create_request` with conversation context; `list_pending_for_conversation` query; `submit_response` creates paired `intervene_response` turn; service boundary enforcement (AR never touches DB) **(26 tests)** |
| `backend/tests/integration/test_intervention_schema_migration.py` | **Database schema verification**: column existence checks for `turn_type`, `intervene_request_id`, `conversation_session_id`, `delegation_depth`; `TurnType` enum value completeness; NULL acceptance for FK columns; FK constraint verification **(11 tests)** |
| `backend/tests/integration/test_intervention_api_integration.py` | **Full API integration**: `GET /conversations/{id}/interventions/pending` (empty, with data, 404); `POST /conversations/{id}/interventions/{req_id}/respond` (approval/choice/text success, 404, 422); existing endpoints return `turn_type` and `intervene_request_id` **(13 tests)** |
| `backend/tests/integration/test_non_conversational_regression.py` | **Non-conversational flow preservation**: create/respond/cancel without `conversation_session_id`; AgentJob status transition; dashboard visibility; metrics endpoint; mixed conv/non-conv coexistence **(8 tests)** |
| `backend/tests/unit/test_a2a_hitl_timeout.py` | **HITL timeout handling**: `_wait_for_receiver_result` deadline extension after HITL resume; terminal status deferred expiry; `Request` parameter injection fix; receiver result received after HITL **(4 tests)** |
| `backend/tests/unit/test_hitl_delegation_status_events.py` | **HITL delegation status events**: `waiting_for_human` and `delegation_resumed` status event emission during conversational delegation; correct event sequence ordering **(2 tests)** |

**Total Backend: 64 tests | Passed: 63 | Failed: 1 (pre-existing: test_ws_delegation_visibility.py)**

### 6.2 Frontend Tests — `frontend/src/__tests__/`

| Test File | Covers |
|---|---|
| `frontend/src/__tests__/InlineInterventionDialog.test.tsx` | Inline dialog component: approval/choice/text rendering; submit/dismiss callbacks; disabled submit until choice/text entered; error display; loading state; badge rendering **(19 tests)** |
| `frontend/src/__tests__/InterventionPendingIndicator.test.tsx` | "Waiting for your input" indicator; inline/non-inline variants; CircularProgress spinner; warning color treatment **(5 tests)** |
| `frontend/src/__tests__/ConversationDialog.intervention.test.tsx` | Hook-level integration: `useChatSession` exposes `interventionRequest`, `interventionQueueLength`, `sendInterventionResponse`, `cancelIntervention`; `useConversationIntervention` interface verification **(3 tests)** |
| `frontend/src/__tests__/useConversationIntervention.test.ts` | Hook tests: fetch pending on mount; null sessionId handling; empty state; WebSocket primary + REST fallback for respond/cancel; error handling via `useDialogErrorHandler` **(9 tests)** |
| `frontend/src/__tests__/useChatSession.intervention.test.ts` | WebSocket message parsing: `intervene_request` (approval/choice/text); `intervene_status` (responded/cancelled clears state); chat message blocking; `sendInterventionResponse`/`cancelIntervention` WebSocket sends; initial null state **(9 tests)** |

**Total Frontend: 45 tests | Passed: 45 | Failed: 0**

### 6.3 E2E Tests — `e2e/tests/`

| Test File | Covers |
|---|---|
| `e2e/tests/conversation-intervention.spec.ts` | **Mocked variant** (4 tests): Intervention page loads; conversation history page loads; intervene request mock data renders; no redirect to login. **Real Backend Integration variant** (6 tests): `GET /conversations`, `GET /intervene/requests`, `GET /intervene/metrics`, `GET /health`, pending interventions for unknown session (404), respond endpoint rejects invalid request (401/403/404/422) |

**Total E2E: 10 tests | Passed: 10 | Failed: 0**

### 6.4 Pre-Test Checklist (Real Backend Integration)

Before running the Real Backend Integration suite, verify:
- [x] Database migrations applied: `python -m alembic current` shows latest revision (`6d7e345f41b1`)
- [x] All three services running (CC on 8000, AR on 8001, CH on 8002): `.\parthenon.ps1 status`
- [x] CC health endpoint returns 200
- [x] Test operator user has permissions to respond to interventions

---

## 7. Test Data Requirements

- Conversation agent type configured with a delegation-capable SOP (sub-agent calls `human_intervene`)
- Test operator identity with intervention response permissions
- Non-conversational agent type for regression testing
- Multiple sub-agent configurations to test queuing with parallel intervention calls
- WebSocket connection context tied to test conversation session

---

## 8. Out of Scope for Testing

- Mobile or push-notification intervention response
- Custom intervention types beyond Approval/Choice/Text
- Batch/parallel intervention resolution (out of scope per PRD)
- A2A intervention outside user-facing conversations
- Changes to the `human_intervene` tool contract itself
- Operator dashboard UI changes (verified via regression only)
