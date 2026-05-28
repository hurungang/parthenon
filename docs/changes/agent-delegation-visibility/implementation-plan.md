# Implementation Plan: agent-delegation-visibility

## Overview

This change adds real-time delegation visibility to the Parthenon chat experience by extending `BrokerMessage` with a type discriminator, publishing delegation lifecycle events from `SopOrchestrator`, forwarding those events through the WebSocket endpoint to the browser, and rendering a `DelegationStatusCard` component inline in the chat stream.  All changes flow through the existing Redis pub/sub pipeline — no new channels, services, or API routes are required.

---

## Task Checklist

### Phase 1 — Backend: BrokerMessage extension + SopOrchestrator event publishing

- [ ] 1.1 — Add `message_type` discriminator field to `BrokerMessage`
- [ ] 1.2 — Define `DelegationStage` enum in the agents schema module
- [ ] 1.3 — Define `DelegationEvent` Pydantic schema in the agents schema module
- [ ] 1.4 — Accept optional `MessageBroker` and `session_id` in `SopOrchestrator.__init__`
- [ ] 1.5 — Publish `delegation_started` broker event before A2A call in `_execute_step`
- [ ] 1.6 — Publish `delegation_completed` broker event after successful A2A response in `_execute_step`
- [ ] 1.7 — Publish `delegation_failed` broker event in the A2A exception handler in `_execute_step`
- [ ] 1.8 — Add `_forward_broker_events` coroutine to the WebSocket module
- [ ] 1.9 — Run `_forward_broker_events` concurrently with the main receive loop in `websocket_chat`

### Phase 2 — Frontend: DelegationStatusCard component + useChatSession handling

- [ ] 2.1 — Add `'delegation'` to the `ChatRole` union type
- [ ] 2.2 — Define `DelegationStage` TypeScript enum and `DelegationEvent` interface in the shared types module
- [ ] 2.3 — Extend `ChatMessage` with an optional `delegationEvent` payload field
- [ ] 2.4 — Add delegation event parsing branch in the `useChatSession` `onmessage` handler
- [ ] 2.5 — Create `DelegationStatusCard` component

### Phase 3 — Frontend: ChatPage integration

- [ ] 3.1 — Render `DelegationStatusCard` for delegation messages in `ChatPage`
- [ ] 3.2 — Add i18n translation keys for all delegation status labels

### Phase 4 — Testing

- [ ] 4.1 — Backend pytest: `BrokerMessage` `message_type` serialisation round-trip
- [ ] 4.2 — Backend pytest: `SopOrchestrator._execute_step` delegation event publishing
- [ ] 4.3 — Frontend Vitest: `DelegationStatusCard` renders each delegation stage correctly
- [ ] 4.4 — Frontend Vitest: `useChatSession` delegation event parsing
- [ ] 4.5 — E2E Playwright: delegation visibility in a live multi-agent chat session

---

## Phase 1 — Backend: BrokerMessage extension + SopOrchestrator event publishing

### 1.1 — Add `message_type` discriminator field to `BrokerMessage`

Add a `message_type: str` field to `BrokerMessage.__init__` with a default value of `"chat"`.  Update `to_dict` to include `message_type` in the serialised dict, and update `from_dict` to read it back (defaulting to `"chat"` for backward compatibility with messages that lack the field).  No other existing behaviour changes.

**Done when:** A round-trip through `to_dict` / `from_dict` preserves `message_type` for both a `"chat"` and a `"delegation"` value.

---

### 1.2 — Define `DelegationStage` enum in the agents schema module

Add a `DelegationStage` Python `str` enum to `backend/app/schemas/agents.py` with members: `started`, `in_progress`, `completed`, `failed`.

**Done when:** The enum is importable from `app.schemas.agents` without errors.

---

### 1.3 — Define `DelegationEvent` Pydantic schema in the agents schema module

Add a `DelegationEvent` Pydantic `BaseModel` to `backend/app/schemas/agents.py` with fields: `stage: DelegationStage`, `agent_type_slug: str`, `agent_type_name: str`, `session_link_id: str | None`, and `detail: str | None`.

**Done when:** `DelegationEvent` is importable from `app.schemas.agents` and validates correctly for all four `DelegationStage` values.

---

### 1.4 — Accept optional `MessageBroker` and `session_id` in `SopOrchestrator.__init__`

Extend `SopOrchestrator.__init__` to accept two optional parameters: `broker: MessageBroker | None` and `session_id: str | None`.  Store them as instance attributes.  Existing callers that pass neither continue to work unchanged (broker is `None`, events are silently skipped).

**Done when:** Existing `SopOrchestrator()` construction with no arguments raises no errors and produces no broker calls.

---

### 1.5 — Publish `delegation_started` broker event before A2A call in `_execute_step`

At the top of the `agent_delegation` branch in `_execute_step`, after resolving the target `AgentType` from the database, construct a `BrokerMessage` with `message_type="delegation"` whose `content` field is a JSON-serialised `DelegationEvent(stage=DelegationStage.started, agent_type_slug=..., agent_type_name=...)`.  If `self._broker` and `self._session_id` are both set, call `await self._broker.publish(message)`.

**Done when:** When `SopOrchestrator` is constructed with a broker and session ID, executing a delegation step publishes exactly one `"delegation"` / `started` message before the HTTP call to the A2A endpoint.

---

### 1.6 — Publish `delegation_completed` broker event after successful A2A response in `_execute_step`

Immediately after the successful A2A response, publish a `BrokerMessage` with `message_type="delegation"` carrying a `DelegationEvent(stage=DelegationStage.completed, ...)` serialised to JSON.  Include the `session_link_id` from the A2A response payload if present.

**Done when:** A successful mock A2A response produces exactly one `started` and one `completed` delegation broker message, in that order.

---

### 1.7 — Publish `delegation_failed` broker event in the A2A exception handler in `_execute_step`

In the `except httpx.HTTPError` block, before re-raising `SopOrchestratorError`, publish a `BrokerMessage` with `message_type="delegation"` carrying a `DelegationEvent(stage=DelegationStage.failed, detail=str(exc))`.

**Done when:** When the A2A HTTP call raises `httpx.HTTPError`, a `failed` delegation broker message is published and `SopOrchestratorError` is still raised.

---

### 1.8 — Add `_forward_broker_events` coroutine to the WebSocket module

Add a private `async def _forward_broker_events(websocket, session_id, broker)` coroutine to `backend/app/api/ws/chat.py`.  It subscribes to `broker.subscribe(session_id)` and, for each received `BrokerMessage`, serialises it via `to_dict()` and sends it as JSON over the WebSocket.  The coroutine exits cleanly when the WebSocket closes or the generator is exhausted.

**Done when:** The coroutine, called independently with a mock broker emitting two messages, sends exactly two `websocket.send_json` calls.

---

### 1.9 — Run `_forward_broker_events` concurrently with the main receive loop in `websocket_chat`

In `websocket_chat`, after accepting the connection, use `asyncio.create_task` to launch `_forward_broker_events` alongside the existing `while True` receive loop.  Cancel and await the task on `WebSocketDisconnect` or any other exception exit path.

**Done when:** Delegation events published to the broker channel during an active session are received by the WebSocket client without interrupting normal chat message flow.

---

## Phase 2 — Frontend: DelegationStatusCard component + useChatSession handling

### 2.1 — Add `'delegation'` to the `ChatRole` union type

Extend `ChatRole` in `frontend/src/hooks/useChatSession.ts` to include `'delegation'`.

**Done when:** TypeScript compiles without errors; existing usages of `ChatRole` that only handle `'user' | 'agent' | 'system'` emit no new type errors from this addition alone.

---

### 2.2 — Define `DelegationStage` TypeScript enum and `DelegationEvent` interface in the shared types module

Add a `DelegationStage` const enum (values: `Started`, `InProgress`, `Completed`, `Failed`) and a `DelegationEvent` interface (fields: `stage`, `agentTypeSlug`, `agentTypeName`, `sessionLinkId?`, `detail?`) to `frontend/src/types/index.ts`.

**Done when:** Both are importable from `frontend/src/types/index.ts` with no TypeScript errors.

---

### 2.3 — Extend `ChatMessage` with an optional `delegationEvent` payload field

Add an optional `delegationEvent?: DelegationEvent` field to the `ChatMessage` interface in `frontend/src/hooks/useChatSession.ts`.  All existing `ChatMessage` construction sites are unchanged (field is optional).

**Done when:** TypeScript compiles with no new errors across the codebase.

---

### 2.4 — Add delegation event parsing branch in the `useChatSession` `onmessage` handler

In the `ws.onmessage` handler within `useChatSession`, add a branch that detects `data.message_type === 'delegation'` before the general chat-message path.  Parse `data.content` as JSON, construct a `DelegationEvent` from its fields, and append a `ChatMessage` with `role: 'delegation'` and `delegationEvent` populated.

**Done when:** A mock WebSocket message with `message_type: "delegation"` and a valid JSON `content` adds exactly one `delegation`-role `ChatMessage` to the messages array, and a subsequent `message_type: "chat"` message continues to add a normal agent message.

---

### 2.5 — Create `DelegationStatusCard` component

Create `frontend/src/components/chat/DelegationStatusCard.tsx`.  The component accepts a `message: ChatMessage` prop (where `role === 'delegation'`).  It renders a distinct card showing the delegated agent name, a stage-appropriate icon/colour, and a human-readable status label sourced from `t()`.  Stages: `started` → spinner + "Delegating to [Agent Name]"; `in_progress` → spinner + "Working with [Agent Name]…"; `completed` → check icon + "Completed by [Agent Name]"; `failed` → warning icon + "Delegation to [Agent Name] failed".  All user-visible text uses `t()` with keys added in Phase 3.

**Done when:** The component renders without TypeScript errors and visually represents all four stages when passed a corresponding `ChatMessage`.

---

## Phase 3 — Frontend: ChatPage integration

### 3.1 — Render `DelegationStatusCard` for delegation messages in `ChatPage`

In `ChatPage`, import `DelegationStatusCard` and update the message rendering loop.  When `msg.role === 'delegation'`, render `<DelegationStatusCard message={msg} />` instead of the existing agent bubble.  All other roles render as before.

**Done when:** TypeScript compiles; delegation messages appear as `DelegationStatusCard` elements in the rendered output and do not display as plain text bubbles.

---

### 3.2 — Add i18n translation keys for all delegation status labels

Add the required translation keys to every active locale file (at minimum `en`).  Keys to add: `chat.delegation.started`, `chat.delegation.inProgress`, `chat.delegation.completed`, `chat.delegation.failed`, `chat.delegation.agentLabel` (used as "Delegating to {{name}}").

**Done when:** The `t()` calls in `DelegationStatusCard` resolve to non-empty strings for the `en` locale and produce no missing-key warnings in the browser console.

---

## Phase 4 — Testing

### 4.1 — Backend pytest: `BrokerMessage` `message_type` serialisation round-trip

Write a pytest unit test in `backend/tests/` that constructs a `BrokerMessage` with `message_type="delegation"`, calls `to_dict()`, and verifies the field is present; then calls `from_dict()` on the result and confirms `message_type` round-trips correctly.  Also verify that a legacy dict without the field deserialises with `message_type` defaulting to `"chat"`.

**Done when:** Test passes; no regressions in existing `BrokerMessage` tests.

---

### 4.2 — Backend pytest: `SopOrchestrator._execute_step` delegation event publishing

Write a pytest integration test that constructs `SopOrchestrator` with a mock `MessageBroker` and a `session_id`, stubs the A2A HTTP call, and executes a delegation step.  Assert that the mock broker's `publish` method is called three times in the success path (once each for `started`, a potential `in_progress` signal, and `completed`) and twice in the failure path (`started` then `failed`).  Verify the `message_type` on each published message is `"delegation"` and that `content` deserialises to a `DelegationEvent` with the correct `stage`.

**Done when:** Both success and failure test cases pass; `SopOrchestratorError` is still raised in the failure case.

---

### 4.3 — Frontend Vitest: `DelegationStatusCard` renders each delegation stage correctly

Write Vitest tests in `frontend/src/__tests__/` covering all four `DelegationStage` values.  For each: construct a `ChatMessage` with `role: 'delegation'` and the corresponding `delegationEvent`, render `DelegationStatusCard`, and assert that the expected status text is present in the output.

**Done when:** All four stage tests pass with no TypeScript or rendering errors.

---

### 4.4 — Frontend Vitest: `useChatSession` delegation event parsing

Write a Vitest test that simulates WebSocket messages with `message_type: "delegation"` and verifies that `useChatSession` adds `delegation`-role messages with a populated `delegationEvent` field.  Also verify that a standard agent message following a delegation message adds a normal `agent`-role entry and does not interfere with the delegation entry.

**Done when:** Test passes; no regression in existing `useChatSession` tests.

---

### 4.5 — E2E Playwright: delegation visibility in a live multi-agent chat session

Write a Playwright test in `e2e/tests/` that opens a chat session backed by a SOP with a configured `agent_delegation` step.  Send a user message that triggers delegation, wait for the `DelegationStatusCard` to appear with the `started` state, wait for the `completed` state to appear, and assert that the final agent reply is displayed after completion.  Also test the failure path by stubbing the A2A endpoint to return an error and asserting the `failed` state card is shown.

**Done when:** Both happy-path and failure-path scenarios pass against a running local stack.

---

## Completion Checklist

- [ ] All `BrokerMessage` serialisation tests pass
- [ ] `SopOrchestrator` delegation event publishing tests pass (success and failure paths)
- [ ] `DelegationStatusCard` renders all four stages correctly
- [ ] `useChatSession` correctly parses delegation WebSocket events
- [ ] `ChatPage` renders `DelegationStatusCard` in place of agent bubbles for delegation messages
- [ ] i18n keys present and resolving in the `en` locale
- [ ] E2E tests pass against a running local stack (happy path + failure path)
- [ ] No TypeScript compilation errors introduced
- [ ] No Python linting or type-checking errors introduced
- [ ] All existing unit and integration tests continue to pass
