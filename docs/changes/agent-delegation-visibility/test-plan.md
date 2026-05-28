# Test Plan: Agent Delegation Visibility

## 1. Test Strategy

This change touches three distinct layers that must all be validated independently and together:

- **Backend unit tests (pytest)** — verify `SopOrchestrator` emits the correct `BrokerMessage` at each delegation lifecycle stage, and that `BrokerMessage` serialises/deserialises `message_type` with proper backward-compatible defaulting.
- **Frontend component/unit tests (Vitest)** — verify `DelegationStatusCard` renders the correct visual state for each `DelegationStage`, and that `useChatSession` correctly parses delegation WebSocket events into `ChatMessage` entries with `role: 'delegation'`.
- **End-to-end tests (Playwright)** — verify the complete flow from the browser perspective: user sends a message, delegation events appear inline in the chat stream with correct stage transitions, and existing chat messages are unaffected.

All three layers must pass before the change is considered complete. A passing frontend test suite alone does not confirm backend event publishing works, and passing backend tests alone do not confirm the UI renders correctly.

---

## 2. Coverage Areas

| Area | Why It Is Critical |
|---|---|
| `BrokerMessage.message_type` serialisation and backward compatibility | Old messages without the field must not break client parsing or existing chat rendering. This is the highest-risk change in the entire feature. |
| `SopOrchestrator` delegation event publishing | If events are not published, the entire feature is silently missing — no error, just nothing shown to the user. |
| `useChatSession` delegation event parsing | If parsing fails, delegation messages are silently dropped or cause unhandled errors. |
| `DelegationStatusCard` stage rendering | Each stage (`started`, `in_progress`, `completed`, `failed`) must show the correct icon, colour, and human-readable text. |
| `ChatPage` delegation vs. chat rendering split | Messages with `role: 'delegation'` must render `DelegationStatusCard`; messages with `role: 'user'` or `role: 'agent'` must continue using existing renderers. |
| WebSocket forwarding (`_forward_broker_events`) | Events must be forwarded to the WebSocket client concurrently with normal agent replies and must not block or delay chat messages. |
| Task lifecycle (creation and cancellation) | The asyncio task must be cancelled and awaited on every WebSocket exit path to prevent resource leaks. |

---

## 3. Critical Scenarios

### 3.1 Delegation Started Event Received by Frontend

**WHEN** a primary agent begins delegating to a sub-agent and the backend publishes a `delegation / started` `BrokerMessage` to the session channel,  
**THEN** the frontend WebSocket handler receives the event, `useChatSession` appends a `ChatMessage` with `role: 'delegation'` and `stage: Started` to the messages array, and `ChatPage` renders a `DelegationStatusCard` inline in the message stream showing a spinner and the delegated agent's name without any page reload.

---

### 3.2 Progress Events Appear in Real Time

**WHEN** the sub-agent emits one or more `in_progress` delegation events during its execution,  
**THEN** each event is forwarded over the WebSocket concurrently with any normal agent chat messages, the messages array grows with additional `role: 'delegation'` entries, and the user sees the in-progress state update in the chat stream without waiting for the sub-agent to finish.

---

### 3.3 Delegation Completion Updates the Card

**WHEN** the sub-agent finishes successfully and the backend publishes a `delegation / completed` `BrokerMessage`,  
**THEN** the frontend renders a `DelegationStatusCard` with `stage: Completed`, displaying a check-mark icon and a clear completion label that includes the agent name, replacing the in-progress visual state for that delegation.

---

### 3.4 Delegation Failure Shows Error State

**WHEN** sub-agent execution raises an exception and the backend publishes a `delegation / failed` `BrokerMessage` (before re-raising the error),  
**THEN** the frontend renders a `DelegationStatusCard` with `stage: Failed`, displaying a warning icon and a user-readable failure message, so the user never sees an indefinite spinner.

---

### 3.5 Backward Compatibility — Existing Chat Messages Still Render Correctly

**WHEN** the WebSocket receives a message that was produced before this change and therefore lacks the `message_type` field,  
**THEN** `useChatSession` treats the message as `message_type: "chat"` (the default), does not attempt to parse `content` as a delegation event, and renders the message through the existing chat message path without error or visual regression.

> **Risk note:** This scenario is the single highest-risk compatibility gap. `BrokerMessage.from_dict` must default `message_type` to `"chat"` when the key is absent. Both the backend unit tests and a dedicated frontend Vitest test must cover this case explicitly before the change ships.

---

### 3.6 Multiple Concurrent Delegations

**WHEN** a session triggers two or more delegation steps in rapid succession (e.g., a multi-step SOP that delegates to Agent A then Agent B),  
**THEN** each delegation produces its own independent sequence of `ChatMessage` entries in the messages array, the cards for both delegations are visible in the chat stream in chronological order, and the state of one delegation does not interfere with the display state of another.

---

### 3.7 WebSocket Reconnection During Active Delegation

**WHEN** the user's WebSocket connection drops while a delegation is in the `started` or `in_progress` state and then reconnects,  
**THEN** the `started` card that was already rendered remains visible in the message history (it was already appended), the asyncio task for the previous connection is cancelled cleanly without a resource leak, and any events published after reconnection are forwarded correctly over the new connection.

---

## 4. Edge Cases & Risks

### BrokerMessage Backward Compatibility (Highest Risk)

Messages stored in Redis or arriving from older backend instances will not contain a `message_type` key. If `from_dict` does not default the field, the deserialization will raise a validation error and break the WebSocket handler for all sessions on that pod. The backend unit test for `BrokerMessage` must include an explicit test with a dict that has no `message_type` key and assert the resulting object has `message_type == "chat"`.

### WebSocket Task Lifecycle

The `_forward_broker_events` task must be cancelled on every WebSocket exit path: clean disconnect, protocol error, and unhandled exception. If cancellation is not awaited, the task continues holding a Redis subscription, leaking memory and connection slots. The backend unit test for `websocket_chat` must verify the task is cancelled after the connection closes, including in error paths.

### Sub-Agent Failure with No Progress Events

If the A2A HTTP call to the sub-agent raises immediately (e.g., network timeout before any response), there will be a `started` event but no `in_progress` events before the `failed` event. The `DelegationStatusCard` must handle the transition from `started` directly to `failed` without requiring an intermediate `in_progress` entry.

### Rapid-Succession Delegations

If a SOP delegates to multiple agents in a tight loop, the Redis pub/sub channel may receive interleaved events for different delegation stages. Because each event carries `agent_type_slug` and `stage`, the frontend must not assume events arrive strictly sequenced. Each event is an independent immutable message in the array; the card for each message renders only its own event's stage without shared mutable state.

### `DelegationStatusCard` Rendered with Missing `delegationEvent`

If a `ChatMessage` with `role: 'delegation'` is received but `delegationEvent` is `undefined` (e.g., malformed content that failed JSON parse), `DelegationStatusCard` must not crash the chat view. It should render a safe fallback or nothing rather than an unhandled exception that blanks the conversation.

### i18n Coverage

All human-readable strings rendered by `DelegationStatusCard` must use `t()` keys. Hard-coded English strings are a convention violation. The Vitest test must render the component in at least one locale to confirm no missing translation keys cause runtime errors.

---

## 5. Acceptance Criteria Checklist

These map directly to the PRD acceptance criteria and are expressed as observable user outcomes.

- [ ] A delegation status indicator appears in the chat stream immediately when delegation starts — before the delegated agent has finished any work.
- [ ] The delegation status card explicitly shows the delegated agent's name in all three stages (started, in-progress, completed).
- [ ] While the sub-agent is running, the card shows a visually distinct in-progress state (spinner or similar) so users know the task is still active.
- [ ] When the sub-agent finishes, the card changes to a clear completion state (check-mark or similar), confirming that delegation has ended.
- [ ] All three delegation states (started, in-progress, completed) are understandable to a non-technical user reading them in the chat view without requiring external logs or a separate dashboard.
- [ ] Delegation cards appear in the same conversation view that shows the primary agent's messages — no separate panel or navigation required.
- [ ] Key delegated activities (in-progress steps) are surfaced as visible chat entries, not buried in a separate log, but do not disrupt reading the primary conversation.
- [ ] If the sub-agent fails, the card shows a clear failure state instead of leaving the user with an indefinite spinner.
- [ ] Existing user and agent chat messages are unaffected by the change — they render identically to pre-change behaviour.

---

## 6. Test File References

Test implementation should be distributed across all three test layers defined in `docs/config.yaml` under `source.tests`.

### Backend — `backend/tests/` (pytest)

- Unit tests for `BrokerMessage`:
  - Serialises `message_type` correctly in `to_dict`.
  - Deserialises `message_type` correctly in `from_dict`.
  - **Backward compatibility**: `from_dict` with a dict lacking `message_type` produces `message_type == "chat"`.
- Unit tests for `DelegationStage` and `DelegationEvent`:
  - Each enum member serialises to the expected string value.
  - `DelegationEvent` round-trips through JSON without data loss.
- Unit tests for `SopOrchestrator._execute_step` (agent_delegation branch):
  - With a mock broker supplied: asserts `publish` is called three times (started, completed, failed paths) with the correct `message_type`, `stage`, `agent_type_slug`, and `agent_type_name`.
  - With no broker supplied: asserts no publish calls are made and existing callers are unaffected.
- Integration/functional tests for `_forward_broker_events` and `websocket_chat`:
  - Task is created when the WebSocket connects and cancelled when it disconnects.
  - A delegation event published to the session channel is received by the WebSocket client.

### Frontend — `frontend/src/__tests__/` (Vitest)

- `DelegationStatusCard` component tests:
  - Renders a spinner-style icon for `stage: Started` and `stage: InProgress`.
  - Renders a check-mark icon for `stage: Completed`.
  - Renders a warning icon for `stage: Failed`.
  - Includes the agent name from `agentTypeName` in the rendered text for all stages.
  - Does not crash when `delegationEvent` is `undefined`.
  - Uses `t()` for all visible strings (no hard-coded English).
- `useChatSession` hook tests:
  - A WebSocket message with `message_type: "delegation"` appends a `ChatMessage` with `role: 'delegation'` and a correctly parsed `delegationEvent`.
  - A WebSocket message **without** `message_type` (backward-compatibility case) is treated as a normal chat message and does not produce a `role: 'delegation'` entry.
  - A WebSocket message with `message_type: "chat"` continues to produce the existing `ChatMessage` format unchanged.
- `ChatPage` rendering tests:
  - A `messages` array containing a mix of `role: 'user'`, `role: 'agent'`, and `role: 'delegation'` entries renders `DelegationStatusCard` only for delegation entries.
  - Existing chat message renderers are not invoked for delegation entries.

### E2E — `e2e/tests/` (Playwright)

- Full delegation visibility flow:
  - User sends a message that triggers an agent delegation.
  - The chat stream shows a `DelegationStatusCard` with the sub-agent's name in the `started` state without a page reload.
  - The card transitions to `completed` after the sub-agent finishes.
  - Existing user and agent messages above the delegation card remain visually unchanged.
- Delegation failure flow (if a controllable failure scenario is available in the test environment):
  - A failed delegation shows the failure state card rather than a spinner.
- Backward-compatibility regression:
  - A session that receives only chat messages (no delegation events) renders the conversation identically to pre-change behaviour with no visual artifacts.
