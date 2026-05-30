# Test Plan: Agent Delegation Visibility

## 1. Test Strategy

This refinement remains a UX visibility adjustment and transport-behavior refinement only. Testing validates user-visible progress behavior in both conversation and non-conversation flows without changing core delegation/runtime business logic.

- Backend tests validate status and log-stream event forwarding, append ordering, timeout/failure terminal signaling, and pull-fallback compatibility.
- Frontend tests validate conversational status rendering (thinking/delegating/waiting/final), folded delegation snippet behavior, and live non-conversation log append behavior without manual refresh.
- E2E tests validate full user-observable behavior in real surfaces: conversational delegation cues and non-conversation live session progress.
- Manual verification validates readability and motion clarity (thinking/waiting indicators, folded snippet previews, expand/collapse affordances).

Definition of done for this change:
- Backend, frontend, and e2e suites covering this scope all pass.
- Every PRD acceptance criterion is mapped to at least one scenario and verified by at least one test layer.
- No behavior change is introduced for delegation decisioning, orchestration, identity, authorization, or runtime access controls.

---

## 2. Coverage Areas

| Area | Why It Is Critical |
|---|---|
| Conversational thinking indicator visibility | Users must see immediate activity feedback while the conversational agent is processing before delegation starts. |
| Delegation start label format | UX requires exact wording: `Delegating to agent <agent_type>` for clear handoff context. |
| Delegation target derivation from tool name | Internal delegation naming may use `agent____<slug>` (with model/tool alias `agent__<agent_type>`), but the displayed label must be normalized to the user-readable target format. |
| Waiting indicator during delegated execution | Users need continuous feedback until delegated response or timeout to prevent perceived hangs. |
| Folded chat delegation snippets (default collapsed) | Delegation execution details must be visible in compact form by default to preserve readability while still signaling progress. |
| Expand/collapse delegation snippets on demand | Users must be able to inspect details when needed without forcing full verbosity in the main chat stream. |
| Folded snippet context quality | Collapsed snippet preview must provide enough context-at-a-glance to confirm work is progressing. |
| Non-conversation live execution-log stream | Active session progress must append live without manual refresh, reducing ambiguity and stale screens. |
| Non-conversation stream fallback and terminal completion | Reconnect/fallback behavior must preserve correctness and terminal visibility for run completion/failure. |
| Timeout/failure terminal state | Waiting must always resolve to a clear end state; no indefinite loading indicators are acceptable. |
| Visibility consistency in conversational views | Status messaging must appear where users converse, not in separate technical panels. |
| Visibility consistency in non-conversation execution views | Session-focused monitoring views must show live updates consistently across pages/dialogs that expose run progress. |
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
**THEN** a waiting animation remains visible until a delegated response arrives or a timeout is reached, including the anchorless case where no agent reply has rendered yet (conversation currently contains only user messages).

### S4. Delegation Snippets Are Folded by Default in Chat

**WHEN** delegation-related execution snippet lines are received in a conversation,  
**THEN** snippet content is shown in a folded/collapsed state by default.

### S5. Folded Snippets Can Be Expanded and Collapsed On Demand

**WHEN** a user interacts with snippet expand/collapse controls,  
**THEN** the snippet panel expands to show details and can be collapsed again without losing conversation continuity.

### S6. Folded Snippet Preview Gives At-a-Glance Progress Context

**WHEN** snippets remain collapsed during ongoing delegation,  
**THEN** preview text provides enough concise context to confirm that delegated work is progressing.

### S7. Non-Conversation Active Sessions Stream Logs Live

**WHEN** a non-conversation agent session is in running state,  
**THEN** new execution log entries appear in session monitoring views live without manual page refresh.

### S8. Non-Conversation Live Stream Handles Recovery and Terminal Completion

**WHEN** stream interruptions or terminal session transitions occur,  
**THEN** the UI reconciles using fallback/pull behavior and shows correct terminal completion/failure status without duplicate or missing final state.

### S9. Timeout Produces Final Visible State

**WHEN** delegated execution exceeds timeout,  
**THEN** the UI transitions from waiting to a clear final timeout/failure status and does not remain in indefinite waiting.

### S10. Delegation Failure Produces Final Visible State

**WHEN** delegated execution fails before completion,  
**THEN** the user sees a clear final failure status in the same conversational view.

### S11. Non-Technical Readability Across Visibility Cues

**WHEN** users view thinking/delegating/waiting/final states,  
**THEN** labels and snippet previews are concise and understandable without technical terminology or log inspection.

### S12. Visibility in All Conversational Surfaces Where Delegation Occurs

**WHEN** delegation is triggered from supported conversational UI surfaces,  
**THEN** the same status experience (thinking, delegation label, waiting, terminal outcome) is visible consistently in those surfaces.

### S13. Regression Guard for Core Chat Experience

**WHEN** standard non-delegated chat messages are sent and received,  
**THEN** existing message rendering, input behavior, and conversation flow remain unchanged.

### S14. Scope Guard for Runtime and Security Behavior

**WHEN** visibility cues and non-conversation stream updates are enabled,  
**THEN** delegation decisioning, authorization boundaries, identity handling, and core runtime business logic remain unchanged.

---

## 4. Edge Cases & Risks

- Rapid delegation completion: delegation may complete quickly after start; UI must still render a readable handoff transition instead of flickering or skipping directly with no visibility.
- Consecutive delegations in one conversation: each delegation must show its own start/wait/final progression without state bleed between turns.
- Timeout and response race: if a response arrives near timeout boundary, terminal state resolution must be deterministic and user-visible.
- No-agent-anchor rendering risk: delegation intro/progress visibility can be skipped when the current conversation has only user turns and the first agent reply has not rendered yet.
- Agent type formatting risk: deriving display text from `agent____<slug>` and/or alias `agent__<agent_type>` must not leak raw internal tokens or malformed labels to users; normalization/mapping must still show `Delegating to agent <agent_type>`.
- Folded snippet overload risk: collapsed preview may become too verbose and reduce readability if summarization boundaries are not stable.
- Expand/collapse state continuity risk: user toggles should not break message order, status indicator visibility, or snippet grouping.
- Non-conversation stream ordering risk: out-of-order append events could misrepresent progress if ordering/reconciliation is not deterministic.
- Non-conversation reconnect risk: temporary disconnects may cause duplicate, skipped, or stale entries if fallback merge rules are weak.
- Reconnect/reload during waiting: conversation should not return to an ambiguous loading state with no terminal outcome indicator.
- i18n consistency risk: status text should remain readable and consistent through translation keys used in conversational UI components.

---

## 5. Acceptance Criteria Checklist

| PRD Acceptance Criterion | Scenario Coverage | Primary Test Layers |
|---|---|---|
| AC1. While the primary conversational agent is processing, the front chatbox shows a visible thinking indicator. | S1 | Frontend, E2E |
| AC2. When delegation starts, the chat displays the label exactly in the format: `Delegating to agent <agent_type>`. | S2 | Frontend, E2E |
| AC3. After delegation begins, the chat shows a waiting indicator until a delegated response is received or a timeout occurs. | S3, S9 | Frontend, E2E, Backend timeout pathway regression |
| AC4. During non-conversation agent runs, users can observe live execution progress updates without manually refreshing. | S7, S8 | Backend API, Frontend integration, E2E |
| AC5. In chat, delegation execution log snippets are presented folded by default and can be expanded on demand. | S4, S5 | Frontend, E2E |
| AC6. Folded delegation snippets in chat provide enough context to confirm progress at a glance while keeping conversation readable. | S6, S11 | Frontend, Manual UX validation, E2E |
| AC7. If delegated execution times out or fails, users see a clear final status state and are not left in an indefinite waiting state. | S9, S10 | Frontend, E2E, Backend regression |
| AC8. Delegation-related status messages and execution visibility cues are understandable to non-technical users and consistently visible where relevant. | S11, S12 | Frontend, E2E, Manual UX validation |
| AC9. Required UX scope is limited to execution visibility and user-facing progress communication; no core delegation/runtime business-logic change is required. | S13, S14 | Backend regression, Frontend regression, E2E regression |

Checklist:
- [x] AC1 through AC9 each map to at least one scenario.
- [x] Conversational visibility scenarios cover thinking, delegating label, waiting, timeout, and failure.
- [x] Non-conversation visibility scenarios cover live stream updates and reconnect/terminal reconciliation.
- [x] Folded snippet scenarios cover default collapsed state, expand/collapse behavior, and at-a-glance context quality.
- [x] Scope/regression scenarios confirm no core delegation/runtime behavior change.

---

## 6. Test File References

The following files are likely affected for implementing and validating this refinement.

### Backend (pytest)

- `backend/tests/unit/test_fix_support_role_conversation_delegation_tools.py`
  - Delegation naming normalization and delegated response timing regression anchor.
- `backend/tests/unit/test_fix_20260521_tool_routing_and_chat_timeout.py`
  - Timeout boundary coverage for waiting-to-terminal-state behavior.
- `backend/tests/unit/test_fix_20260521_192300_ws_chat_runtime_boundary.py`
  - Runtime boundary regression guard for chat visibility transport.
- `backend/tests/unit/test_ws_delegation_visibility.py`
  - Conversation-channel status forwarding for thinking/delegating/waiting/final states and snippet source payloads.
- `backend/tests/api/test_agents_api.py`
  - Session log API contract and non-conversation progress retrieval fallback coverage.
- `backend/tests/api/test_agents_session_log_stream_api.py`
  - Live non-conversation execution-log stream append/ordering/terminal-marker behavior.

### Frontend (Vitest)

- `frontend/src/__tests__/ConversationDialog.test.tsx`
  - Conversational UI status and folded snippet rendering in dialog surface.
- `frontend/src/__tests__/useChatSession.test.ts`
  - Chat status parsing plus folded snippet aggregation and expand/collapse state behavior.
- `frontend/src/__tests__/AgentSessionPage.test.tsx`
  - Non-conversation live progress rendering and no-refresh append behavior in session page.
- `frontend/src/__tests__/ConversationDelegationVisibility.test.tsx`
  - Thinking visibility, exact delegation label format, waiting lifecycle, folded snippet UX, and terminal timeout/failure states.
- `frontend/src/__tests__/SessionExecutionLogsDialog.test.tsx`
  - Non-conversation live stream updates and fallback reconciliation in log dialog surface.
- `frontend/src/__tests__/AgentSessionPage.test.tsx`
  - Running-session stream-state hint visibility and non-conversation session regression coverage.
- `frontend/src/__tests__/useSessionExecutionLogStream.test.ts`
  - NDJSON stream parsing, terminal marker handling, and fallback transition behavior in the live-stream hook.

### E2E (Playwright)

- `e2e/tests/chat.spec.ts`
  - Baseline chat rendering and non-delegation regression anchor.
- `e2e/tests/conversations.spec.ts`
  - Conversation-view consistency anchor for status and folded snippet visibility.
- `e2e/tests/conversation-delegation-visibility.spec.ts`
  - End-user scenarios for conversational visibility cues, folded snippets, expand/collapse, success and timeout/failure outcomes.
- `e2e/tests/agent-logs.spec.ts`
  - Non-conversation execution log UI coverage anchor; extend for live stream behavior during active runs.
- `e2e/tests/agent-a2a-communication.spec.ts`
  - Delegation-flow integration anchor to ensure visibility cues align with real delegation lifecycle.
- `e2e/tests/agent-live-logs-stream.spec.ts`
  - Dedicated non-conversation live stream scenarios for append updates without manual refresh and terminal reconciliation.
