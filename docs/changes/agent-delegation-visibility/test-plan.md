# Test Plan: Agent Delegation Visibility

## 1. Test Strategy

This change is a UX visibility adjustment only. Testing must validate user-visible status behavior while explicitly avoiding assumptions about core runtime logic rewrites.

- Backend tests confirm that existing conversation/delegation pathways still emit or forward the status signals needed by the UI and honor timeout boundaries.
- Frontend tests validate rendering and text behavior for three user-visible states in conversational flow: thinking, delegating, waiting (plus clear terminal status on timeout/failure).
- E2E tests validate end-user visibility in the real conversation surface, including non-regression for normal chat messages.
- Manual verification is required for animation clarity (thinking/waiting indicators), because visual pacing and perceived responsiveness are not fully captured by unit assertions.

Definition of done for this change:
- Backend, frontend, and e2e suites covering this scope all pass.
- Every PRD acceptance criterion is mapped to at least one scenario and verified by at least one test layer.
- No behavior change is required for delegation decisioning, orchestration, identity, or authorization logic.

---

## 2. Coverage Areas

| Area | Why It Is Critical |
|---|---|
| Conversational thinking indicator visibility | Users must see immediate activity feedback while the conversational agent is processing before delegation starts. |
| Delegation start label format | UX requires exact wording: `Delegating to agent <agent_type>` for clear handoff context. |
| Delegation target derivation from tool name | Internal delegation naming may use `agent____<slug>` (with model/tool alias `agent__<agent_type>`), but the displayed label must be normalized to the user-readable target format. |
| Waiting indicator during delegated execution | Users need continuous feedback until delegated response or timeout to prevent perceived hangs. |
| Timeout/failure terminal state | Waiting must always resolve to a clear end state; no indefinite loading indicators are acceptable. |
| Visibility consistency in conversational views | Status messaging must appear where users converse, not in separate technical panels. |
| Non-regression of existing chat UX | User/agent chat messages and send flow must remain unchanged by this visibility-focused update. |

---

## 3. Critical Scenarios

### S1. Thinking Indicator Before Delegation

**WHEN** a user sends a conversational prompt and the primary agent is processing before any delegation starts,  
**THEN** the chat view displays a visible thinking animation until either delegation begins or a direct response is produced.

### S2. Delegation Start Label Uses Required Format

**WHEN** delegation begins for an internal target identified as `agent____<slug>` (or surfaced alias `agent__<agent_type>`),  
**THEN** the chat status text is shown exactly as `Delegating to agent <agent_type>` in the conversational stream.

### S3. Waiting Indicator Persists Until Resolution

**WHEN** the delegation start state is shown,  
**THEN** a waiting animation remains visible until a delegated response arrives or a timeout is reached.

### S4. Timeout Produces Final Visible State

**WHEN** delegated execution exceeds timeout,  
**THEN** the UI transitions from waiting to a clear final timeout/failure status and does not remain in indefinite waiting.

### S5. Delegation Failure Produces Final Visible State

**WHEN** delegated execution fails before completion,  
**THEN** the user sees a clear final failure status in the same conversational view.

### S6. Non-Technical Readability

**WHEN** users view thinking/delegating/waiting/final states,  
**THEN** labels are concise and understandable without technical terminology or log inspection.

### S7. Visibility in All Conversational Surfaces Where Delegation Occurs

**WHEN** delegation is triggered from supported conversational UI surfaces,  
**THEN** the same status experience (thinking, delegation label, waiting, terminal outcome) is visible consistently in those surfaces.

### S8. Regression Guard for Core Chat Experience

**WHEN** standard non-delegated chat messages are sent and received,  
**THEN** existing message rendering, input behavior, and conversation flow remain unchanged.

---

## 4. Edge Cases & Risks

- Rapid delegation completion: delegation may complete quickly after start; UI must still render a readable handoff transition instead of flickering or skipping directly with no visibility.
- Consecutive delegations in one conversation: each delegation must show its own start/wait/final progression without state bleed between turns.
- Timeout and response race: if a response arrives near timeout boundary, terminal state resolution must be deterministic and user-visible.
- Agent type formatting risk: deriving display text from `agent____<slug>` and/or alias `agent__<agent_type>` must not leak raw internal tokens or malformed labels to users; normalization/mapping must still show `Delegating to agent <agent_type>`.
- Reconnect/reload during waiting: conversation should not return to an ambiguous loading state with no terminal outcome indicator.
- i18n consistency risk: status text should remain readable and consistent through translation keys used in conversational UI components.

---

## 5. Acceptance Criteria Checklist

| PRD Acceptance Criterion | Scenario Coverage | Primary Test Layers |
|---|---|---|
| While the primary conversational agent is processing, the front chatbox shows a visible thinking indicator. | S1 | Frontend, E2E |
| When delegation starts, the chat displays the label exactly in the format: `Delegating to agent <agent_type>` after any internal naming normalization/mapping. | S2 | Frontend, E2E |
| After delegation begins, the chat shows a waiting indicator until a delegated response is received or a timeout occurs. | S3, S4 | Frontend, E2E, Backend timeout boundary regression |
| If delegated execution times out or fails, users see a clear final status state and are not left in an indefinite waiting state. | S4, S5 | Frontend, E2E, Backend timeout/failure pathway regression |
| Delegation-related status messages are understandable to non-technical users and consistently visible in conversational views where delegation occurs. | S6, S7 | Frontend, E2E, Manual UX validation |
| The required user experience is limited to simple conversational status visibility and does not require altering core delegation or runtime business logic. | S8 (plus scope guard in strategy and regression) | Backend regression, Frontend regression, E2E regression |

Checklist:
- [x] AC1 verified by at least one frontend and one e2e scenario.
- [x] AC2 verified with exact string assertion for delegation label format after internal-name normalization/mapping.
- [x] AC3 verified for both success path and timeout boundary.
- [x] AC4 verified for timeout and explicit failure path.
- [x] AC5 verified for readability and cross-surface consistency.
- [x] AC6 verified by regression coverage confirming no core runtime behavior rewrite assumptions.

---

## 6. Test File References

The following files are in scope for implementing and validating this narrowed UX adjustment.

### Backend (pytest)

- `backend/tests/unit/test_fix_support_role_conversation_delegation_tools.py`
  - Existing delegation wait behavior and delegated response timing regression anchor.
- `backend/tests/unit/test_fix_20260521_tool_routing_and_chat_timeout.py`
  - Existing timeout boundary coverage relevant to waiting-until-timeout UX expectations.
- `backend/tests/unit/test_fix_20260521_192300_ws_chat_runtime_boundary.py`
  - Existing runtime-boundary regression guard to ensure no core runtime logic shift in chat path.
- `backend/tests/unit/test_ws_delegation_visibility.py` (new)
  - Add focused coverage for conversation-channel status event forwarding required by thinking/delegating/waiting/final UI states.

### Frontend (Vitest)

- `frontend/src/__tests__/ConversationDialog.test.tsx`
  - Existing conversational UI behavior tests; extend with status visibility assertions.
- `frontend/src/__tests__/useChatSession.test.ts`
  - Existing chat-session hook test anchor; extend for delegation status event handling.
- `frontend/src/__tests__/AgentSessionPage.test.tsx`
  - Regression coverage for mixed message rendering around conversational status updates.
- `frontend/src/__tests__/ConversationDelegationVisibility.test.tsx` (new)
  - Add explicit assertions for: thinking animation visibility, exact `Delegating to agent <agent_type>` label, waiting animation lifecycle, and terminal timeout/failure visibility.

### E2E (Playwright)

- `e2e/tests/chat.spec.ts`
  - Existing baseline chat rendering and send-flow regression anchor.
- `e2e/tests/conversations.spec.ts`
  - Existing conversation-view regression anchor for message history stability.
- `e2e/tests/agent-a2a-communication.spec.ts`
  - Existing delegation-related flow anchor; extend to conversational visibility assertions where applicable.
- `e2e/tests/conversation-delegation-visibility.spec.ts` (new)
  - Add end-user scenarios for S1-S7 with success and timeout/failure outcomes in conversational UI.
