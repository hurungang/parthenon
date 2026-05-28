# Technical Specification: agent-delegation-visibility

## 1. Technical Overview

Delegation visibility is delivered by extending the existing Redis pub/sub pipeline to carry typed `delegation` events alongside chat messages.  `SopOrchestrator` publishes a `BrokerMessage` with `message_type="delegation"` at each lifecycle stage of a sub-agent invocation (started, completed, failed).  The `websocket_chat` endpoint subscribes to the session channel concurrently with its main receive loop and forwards all broker messages — including delegation events — directly to the WebSocket client as JSON.  On the frontend, `useChatSession` detects `message_type === "delegation"` events and injects `delegation`-role `ChatMessage` entries into the message queue; `ChatPage` renders these using the new `DelegationStatusCard` component.  No new REST endpoints, services, database tables, or pub/sub channels are required.

---

## 2. Component Breakdown

### BrokerMessage (extended)

**File:** `backend/app/services/comm_hub/broker.py`

Gains a `message_type` string field (default `"chat"`) that acts as a discriminator for the WebSocket client.  The `to_dict` and `from_dict` methods include this field; `from_dict` defaults to `"chat"` for backward compatibility with messages that pre-date this field.  No other behaviour changes.

---

### DelegationStage (new — Python)

**File:** `backend/app/schemas/agents.py`

A `str` Python enum with four members: `started`, `in_progress`, `completed`, `failed`.  Used as the `stage` field of `DelegationEvent` and serialised into the `content` of the delegation `BrokerMessage`.

---

### DelegationEvent (new — Pydantic schema)

**File:** `backend/app/schemas/agents.py`

A Pydantic `BaseModel` that is serialised to JSON and carried as the `content` string of a delegation `BrokerMessage`.  Fields: `stage` (`DelegationStage`), `agent_type_slug` (string), `agent_type_name` (string), `session_link_id` (optional string from the A2A response), `detail` (optional string for failure messages).

---

### SopOrchestrator (extended)

**File:** `backend/app/services/skills/sop_orchestrator.py`

Extended to accept an optional `MessageBroker` instance and `session_id` at construction time.  The `_execute_step` method, in its `agent_delegation` branch, publishes three delegation `BrokerMessage` instances: one before the A2A HTTP call (`started`), one on successful response (`completed`), and one in the exception handler before re-raising (`failed`).  When no broker is supplied, the three publish calls are skipped silently; all existing callers continue to work unchanged.

---

### _forward_broker_events (new — backend function)

**File:** `backend/app/api/ws/chat.py`

A private `async` coroutine that subscribes to a session's `MessageBroker` channel and streams each received `BrokerMessage` to the caller's WebSocket connection via `send_json`.  It runs concurrently with the main message-receive loop inside `websocket_chat`, launched as an `asyncio.Task`.  The task is cancelled and awaited on every exit path from the WebSocket handler (disconnect, error, or normal close).

---

### websocket_chat (extended)

**File:** `backend/app/api/ws/chat.py`

After accepting the connection, creates an `asyncio.Task` wrapping `_forward_broker_events` so that delegation events published to the session channel reach the client in real time alongside normal agent replies.  Task lifecycle is tied to the WebSocket connection lifetime.

---

### DelegationStage (new — TypeScript)

**File:** `frontend/src/types/index.ts`

A TypeScript const enum mirroring the backend `DelegationStage` values: `Started`, `InProgress`, `Completed`, `Failed`.  Used by `DelegationEvent` and `DelegationStatusCard`.

---

### DelegationEvent (new — TypeScript interface)

**File:** `frontend/src/types/index.ts`

TypeScript interface with fields: `stage: DelegationStage`, `agentTypeSlug: string`, `agentTypeName: string`, `sessionLinkId?: string`, `detail?: string`.  Populated by `useChatSession` when parsing a `delegation`-type WebSocket event.

---

### ChatRole (extended)

**File:** `frontend/src/hooks/useChatSession.ts`

The `ChatRole` union type gains a `'delegation'` member.  No other change.

---

### ChatMessage (extended)

**File:** `frontend/src/hooks/useChatSession.ts`

Gains an optional `delegationEvent?: DelegationEvent` field.  This field is populated only when `role === 'delegation'`; all other message types leave it `undefined`.

---

### useChatSession (extended)

**File:** `frontend/src/hooks/useChatSession.ts`

The `ws.onmessage` handler gains a new branch before the general message path: when `data.message_type === 'delegation'`, it parses `data.content` as JSON, constructs a `DelegationEvent`, and appends a `ChatMessage` with `role: 'delegation'` and the parsed event in `delegationEvent`.  All other existing branches are unchanged.

---

### DelegationStatusCard (new — React component)

**File:** `frontend/src/components/chat/DelegationStatusCard.tsx`

A React component rendered inline in the chat message list for messages with `role === 'delegation'`.  Accepts a single `message: ChatMessage` prop.  Reads `message.delegationEvent` to determine the current `DelegationStage` and renders a MUI `Card` with a stage-appropriate icon (spinner for `started`/`in_progress`, check mark for `completed`, warning icon for `failed`), a colour-coded status indicator, and a human-readable label from `t()` that includes the delegated agent's name.  Does not manage any state of its own.

---

### ChatPage (extended)

**File:** `frontend/src/pages/chat/ChatPage.tsx`

The message-rendering loop is updated to detect `msg.role === 'delegation'` and render `<DelegationStatusCard message={msg} />` for those entries.  All other roles continue to use existing rendering logic.

---

## 3. API Changes

This change introduces no new REST endpoints and no changes to existing REST endpoint contracts.

### WebSocket message schema change (existing channel)

The existing WebSocket channel at `/ws/sessions/{session_id}` will now emit two distinct message shapes from server to client:

**Chat message** (unchanged shape):
- `sender_role` — one of `"user"`, `"agent"`, `"system"` — identifies the speaker
- `content` — text of the message
- `timestamp` — ISO-8601 string

**Delegation event** (new shape):
- `message_type` — `"delegation"` — discriminates this message from a chat message
- `sender_role` — `"agent"` — for consistency with existing client parsing
- `content` — JSON string that deserialises to a `DelegationEvent` object (`stage`, `agent_type_slug`, `agent_type_name`, `session_link_id?`, `detail?`)
- `timestamp` — ISO-8601 string

Existing chat messages gain the `message_type: "chat"` field as an additive, backward-compatible change.  Clients that do not read the field continue to function normally.

---

## 4. State Management

### `useChatSession` — messages array

The `messages: ChatMessage[]` state array already drives all message rendering.  No new top-level state variables are needed.  The only change is that the array now also contains entries with `role: 'delegation'` and a populated `delegationEvent` field.

There is no separate "delegation state" slice.  Each delegation event is an immutable entry in the shared `messages` array, making the state model consistent with existing chat messages.  The lifecycle of a delegation appears as a sequence of discrete messages in the array (e.g., `started` followed later by `completed`), so the UI can render each stage as it arrives without special reconciliation logic.

### `ChatPage` — no new state

`ChatPage` does not introduce any new `useState` or `useRef` values for delegation.  It reads from the existing `messages` array provided by `useChatSession` and delegates all rendering to `DelegationStatusCard`.

---

## 5. Data Access Patterns

### Delegation event flow (backend → frontend)

1. `SopOrchestrator._execute_step` resolves the target `AgentType` from the database (existing query, no change to data access pattern).
2. `SopOrchestrator._execute_step` calls `MessageBroker.publish` with a delegation `BrokerMessage` — a Redis `PUBLISH` to the session channel.
3. `_forward_broker_events` (running in a concurrent task in `websocket_chat`) receives the message via `MessageBroker.subscribe` — a Redis `SUBSCRIBE` on the same channel.
4. `_forward_broker_events` serialises the `BrokerMessage` via `to_dict()` and calls `websocket.send_json` — no database access.
5. `useChatSession.onmessage` receives the JSON payload over the WebSocket, detects `message_type === 'delegation'`, parses `content` as `DelegationEvent`, and appends to `messages`.
6. `ChatPage` re-renders with the updated `messages` array; `DelegationStatusCard` reads the static `delegationEvent` from the message prop.

No new database tables, migrations, or Supabase direct-access patterns are involved.  All delegation data is transient — persisted only in Redis until the subscriber receives it.

### Agent name resolution

The delegated agent's human-readable name (`agent_type_name`) is resolved from the database by `SopOrchestrator._execute_step` before the first delegation event is published (the existing `AgentType` query already executes at that point).  No additional data access is needed on the frontend; the name is carried inside the `DelegationEvent` payload.

---

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `BrokerMessage` | class | Typed message struct for Redis pub/sub; gains `message_type` discriminator | `backend/app/services/comm_hub/broker.py` |
| `MessageBroker` | class | Redis pub/sub broker with per-session channels | `backend/app/services/comm_hub/broker.py` |
| `publish` | method | Publishes a `BrokerMessage` to the session's Redis channel | `backend/app/services/comm_hub/broker.py` |
| `subscribe` | method | Returns async generator of `BrokerMessage` for a session channel | `backend/app/services/comm_hub/broker.py` |
| `to_dict` | method | Serialises `BrokerMessage` to a plain dict (includes `message_type`) | `backend/app/services/comm_hub/broker.py` |
| `from_dict` | method | Deserialises a plain dict to `BrokerMessage` (defaults `message_type` to `"chat"`) | `backend/app/services/comm_hub/broker.py` |
| `DelegationStage` | enum | Python str enum — `started`, `in_progress`, `completed`, `failed` | `backend/app/schemas/agents.py` |
| `DelegationEvent` | class | Pydantic schema for delegation lifecycle event payload | `backend/app/schemas/agents.py` |
| `A2ARequest` | class | Pydantic schema for outbound A2A delegation request (existing) | `backend/app/schemas/agents.py` |
| `A2AResponse` | class | Pydantic schema for inbound A2A delegation response (existing) | `backend/app/schemas/agents.py` |
| `SopOrchestrator` | class | Executes ordered SOP steps; extended to publish delegation events | `backend/app/services/skills/sop_orchestrator.py` |
| `SopOrchestratorError` | class | Raised when SOP orchestration fails (unchanged) | `backend/app/services/skills/sop_orchestrator.py` |
| `execute` | method | Top-level SOP execution loop (unchanged) | `backend/app/services/skills/sop_orchestrator.py` |
| `_execute_step` | method | Handles individual SOP step; publishes delegation events in `agent_delegation` branch | `backend/app/services/skills/sop_orchestrator.py` |
| `SopStepType` | enum | Step type discriminator; `agent_delegation` value triggers event publishing | `backend/app/db/models/skills.py` |
| `AgentRouter` | class | Routes messages between agent instances via broker (unchanged — forwards events transparently) | `backend/app/services/comm_hub/agent_router.py` |
| `route` | method | Publishes a `BrokerMessage` to a target session channel (unchanged) | `backend/app/services/comm_hub/agent_router.py` |
| `websocket_chat` | function | WebSocket endpoint; extended to launch `_forward_broker_events` as a concurrent task | `backend/app/api/ws/chat.py` |
| `WebSocketServer` | class | Authenticates WebSocket connections (unchanged) | `backend/app/api/ws/chat.py` |
| `authenticate` | method | Validates the token query param and returns claims (unchanged) | `backend/app/api/ws/chat.py` |
| `_process_message` | function | Persists turns and calls LLM for chat messages (unchanged) | `backend/app/api/ws/chat.py` |
| `_forward_broker_events` | function | New coroutine; subscribes to session broker channel and streams events to WebSocket client | `backend/app/api/ws/chat.py` |
| `ChatRole` | type | Union type for message sender role; gains `'delegation'` member | `frontend/src/hooks/useChatSession.ts` |
| `ChatMessage` | interface | Message entry in the chat stream; gains optional `delegationEvent` field | `frontend/src/hooks/useChatSession.ts` |
| `useChatSession` | hook | Manages WebSocket lifecycle and message queue; extended to parse delegation events | `frontend/src/hooks/useChatSession.ts` |
| `ConversationalGuardrailUsage` | interface | Guardrail usage data parsed from WebSocket (unchanged) | `frontend/src/hooks/useChatSession.ts` |
| `DelegationStage` | enum | TypeScript const enum mirroring backend stages | `frontend/src/types/index.ts` |
| `DelegationEvent` | interface | TypeScript shape of the parsed delegation event payload | `frontend/src/types/index.ts` |
| `GatewayInitResponse` | interface | Type for gateway init response (unchanged) | `frontend/src/types/index.ts` |
| `DelegationStatusCard` | component | Renders a delegation lifecycle event inline in the chat stream | `frontend/src/components/chat/DelegationStatusCard.tsx` |
| `ChatPage` | component | Chat session page; extended to render `DelegationStatusCard` for delegation messages | `frontend/src/pages/chat/ChatPage.tsx` |
