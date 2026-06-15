# Tech Spec: Conversational Agent Intervention

## 1. Technical Overview

This change bridges the gap between delegated agent intervention requests and the conversation UI by routing `human_intervene` tool invocations from sub-agents to the parent conversation's WebSocket connection. The implementation preserves all service segregation rules — Agent Runtime never directly accesses the database or holds user identity tokens. The Communication Hub acts as the intervention router, detecting conversation-scoped intervention signals and pushing them to connected WebSocket clients. Control Center persists intervention turns in the conversation store with delegation chain metadata for audit traceability.

**Key technical decisions:**
- Intervention routing uses the existing WebSocket infrastructure (no new transport layer)
- Turn type discrimination uses a new `turn_type` enum on `ConversationTurn` rather than overloading the `role` field
- Intervention lifecycle (`pending` → `responded`/`cancelled`/`expired`) on `InterveneRequest` is unchanged — the change is in how requests are surfaced, not how they are managed
- Queuing is per-conversation-session FIFO, backed by database state for resilience across disconnects

---

## 2. Component Breakdown

### 2.1 Communication Hub — Intervention Router (New)

**File:** New module within Communication Hub service directory

**Responsibility:** Inspects suspend signals from Agent Runtime for `human_intervene` invocations containing a `conversation_session_id`. When detected, routes the intervention request to the connected WebSocket client of the parent conversation. When `conversation_session_id` is absent, passes through to the existing dashboard-based intervention flow unchanged.

**Key behaviors:**
- Detects conversation context from the suspend signal payload
- Looks up active WebSocket connections for the parent conversation session
- Pushes `intervene_request` WebSocket message to the connected client
- Handles disconnected clients by holding the request in the database for re-delivery on reconnect (queried via `GET /api/v1/conversations/{session_id}/interventions/pending`)

### 2.2 Communication Hub — Intervention Queue (New)

**File:** New module within Communication Hub service directory

**Responsibility:** Maintains per-conversation-session FIFO queues of pending intervention requests. When a delegated sub-agent requests intervention and another intervention is already pending for the same conversation session, the new request is enqueued. Delivered to the UI in order as prior interventions are resolved or cancelled.

**Key behaviors:**
- Queue scope: one queue per `conversation_session_id`
- Persistence: backed by database (InterveneRequest records with `status=pending`), survives service restart
- Delivery: pops from queue when current intervention transitions to non-pending status
- Cleanup: queue cleared when conversation session ends or is terminated

### 2.3 Communication Hub — WebSocket Message Types (Changed)

**File:** Existing WebSocket message handler in Communication Hub

**Responsibility:** Handle four new intervention message types and modify chat message handling to block input during pending interventions.

**New message types:**
- `intervene_request` (server → client): intervention prompt with type, reason, options, delegation context
- `intervene_response` (client → server): user's response with request_id and response value
- `intervene_cancel` (client → server): user's dismissal with request_id
- `intervene_status` (server → client): lifecycle updates with request_id and status

**Changed behavior:**
- `chat` messages from client are rejected with error when session has pending intervention

### 2.4 Control Center — Conversation Turn Store (Changed)

**File:** `backend/app/services/conversations/store.py`

**Responsibility:** Extended to persist `intervene_request` and `intervene_response` turn types in conversation sessions. Handles the new `turn_type` enum field and `intervene_request_id` foreign key on `ConversationTurn`.

**Key behaviors:**
- `add_turn` accepts optional `turn_type` (default `message`) and `intervene_request_id`
- Turn count increment on parent session works for all turn types
- Query methods return turns in chronological order with intervention turns interleaved

### 2.5 Control Center — Intervene Request Store (Changed)

**File:** `backend/app/services/agents/intervene_service.py`

**Responsibility:** Extended to accept and persist conversation context fields on `InterveneRequest`. Provides query methods for conversation-scoped pending interventions. Automatically creates paired `intervene_response` conversation turns when responses are submitted to conversation-scoped requests.

**Key behaviors:**
- `create_request` accepts optional `conversation_session_id` and `delegation_depth`
- `list_pending_for_conversation` returns pending requests filtered by conversation session
- `submit_response` auto-creates `ConversationTurn` of type `intervene_response` when `conversation_session_id` is present
- Non-conversational flow (no `conversation_session_id`) is unchanged

### 2.6 Control Center — Conversation Intervention API (New)

**File:** `backend/app/api/v1/conversations.py`

**Responsibility:** Two new endpoints for intervention response and pending intervention query within the conversation scope. These serve as REST fallbacks when the WebSocket path is unavailable and handle reconnect scenarios.

### 2.7 Agent Runtime — Agent Engine (Changed)

**File:** Existing Agent Runtime engine code

**Responsibility:** Carries the parent conversation session ID through delegation. When a delegated sub-agent calls `human_intervene`, the engine includes the conversation session ID in the suspend signal sent to the Communication Hub.

**Key behaviors:**
- Conversation session ID is propagated through delegation context
- Suspend signal includes `conversation_session_id` and `delegation_depth`
- `human_intervene` tool contract is unchanged
- No database access, no identity token access

### 2.8 Frontend — `InlineInterventionDialog` (New)

**File:** `frontend/src/components/conversations/InlineInterventionDialog.tsx`

**Responsibility:** Renders the inline intervention dialog within the chat message flow. Supports the three intervention types (approval, choice, text) with appropriate interactive controls, matching the prototype design.

**Key behaviors:**
- Renders approval buttons (Approve/Deny), choice radio group, or text input based on `intervention_type`
- Handles submission, dismissal/cancellation, and error display
- Follows Dialog Error Handling Standard with `useDialogErrorHandler`
- All labels internationalized via `t()`

### 2.9 Frontend — `InterventionPendingIndicator` (New)

**File:** `frontend/src/components/conversations/InterventionPendingIndicator.tsx`

**Responsibility:** Visual status indicator in the chat flow showing "Waiting for your input" during pending interventions. Replaces the indefinite thinking/waiting dots state.

### 2.10 Frontend — `useConversationIntervention` Hook (New)

**File:** `frontend/src/hooks/useConversationIntervention.ts`

**Responsibility:** Manages intervention lifecycle state for a conversation session. Fetches pending interventions on mount (reconnect handling), provides response submission and cancellation functions with error handling.

### 2.11 Frontend — `useChatSession` Hook (Changed)

**File:** `frontend/src/hooks/useChatSession.ts`

**Responsibility:** Extended to parse and handle the four new intervention WebSocket message types. Exposes intervention state (`interventionRequest`, `interventionQueueLength`) and intervention action functions.

### 2.12 Frontend — `ConversationDialog` (Changed)

**File:** `frontend/src/components/agents/ConversationDialog.tsx`

**Responsibility:** Integrates `InlineInterventionDialog` and `InterventionPendingIndicator` into the chat flow. Manages input blocking during pending interventions. Updates topbar badge and context panel for intervention state visibility.

---

## 3. API Changes

### New Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/v1/conversations/{session_id}/interventions/{request_id}/respond` | Submit a response to an intervention request within a conversation session. Returns `InterveneResponseRead`. REST fallback when WebSocket respond is unavailable. |
| `GET` | `/api/v1/conversations/{session_id}/interventions/pending` | Return currently pending intervention requests for a conversation session. Used on reconnect to re-surface outstanding interventions. |

### Changed Endpoints

| Method | Route | Change |
|--------|-------|--------|
| `POST` | `/api/v1/conversations/{session_id}/turns` | If a turns creation endpoint exists, extended to accept `turn_type` values `intervene_request` and `intervene_response`. |
| `GET` | `/api/v1/conversations/{session_id}` | Response now includes `turn_type` and `intervene_request_id` on each turn object. |
| `POST` | `/api/v1/conversations/{session_id}/resume` | Response now includes `turn_type` and `intervene_request_id` on each turn object. |
| `GET` | `/api/v1/intervene/requests` | Response now includes `conversation_session_id` and `delegation_depth` fields on each request where present. |
| `GET` | `/api/v1/intervene/requests/{request_id}` | Response now includes `conversation_session_id` and `delegation_depth` fields. |
| `POST` | `/api/v1/intervene/requests/{request_id}/respond` | If the request has a `conversation_session_id`, an `intervene_response` conversation turn is automatically created. |

### Internal Communication (No REST Endpoints)

| Source | Destination | Change |
|--------|-------------|--------|
| Agent Runtime | Communication Hub | Suspend signal for `human_intervene` now carries `conversation_session_id` and `delegation_depth` |
| Communication Hub | Control Center | Intervention router requests turn creation for `intervene_request` turns and queries pending interventions per conversation |
| Communication Hub | Conversation UI | New WebSocket message types for intervention lifecycle (see Section 3.1 of architecture.md) |

---

## 4. State Management

### Frontend State Changes

**`useChatSession` hook — new state:**
- `interventionRequest: InterveneRequest | null` — the currently active (or next queued) intervention requiring user response
- `interventionQueueLength: number` — count of remaining pending interventions in the queue

**`useChatSession` hook — changed state:**
- `chatStatus.kind` union extended with a value for intervention waiting (`waiting_for_human`)
- `pendingQuestion` may be set to indicate the conversation is blocked on intervention (distinct from agent question state)

**`useConversationIntervention` hook — state:**
- `pendingInterventions: InterveneRequest[]` — all pending interventions for the session (fetched on mount)
- `currentIntervention: InterveneRequest | null` — the intervention currently being displayed
- `isSubmitting: boolean` — submission in progress
- `dialogError: unknown` — error state following `useDialogErrorHandler` pattern

**`ConversationDialog` component — derived state:**
- `interventionActive: boolean` — derived from `interventionRequest !== null`
- Input disabled state derived from `interventionActive`
- Topbar badge state derived from intervention/connected status
- Context panel queue display derived from `interventionQueueLength`

### Communication Hub State

- Per-session intervention-pending flag (boolean, in-memory)
- Per-session intervention queue (list of `request_id`s, backed by database)
- Active WebSocket connection tracking for conversation sessions (existing)

---

## 5. Data Access Patterns

### Reads

| Data | Accessor | Pattern |
|------|----------|---------|
| Pending interventions for conversation session | CC → `InterveneRequestStore.list_pending_for_conversation` | Query by `conversation_session_id` + `status=pending`, ordered by `created_at ASC` |
| Full conversation session with intervention turns | CC → `ConversationStore.get_session_with_turns` | Eager-loaded turns with `turn_type` and `intervene_request_id` |
| Intervention request with response | CC → `InterveneRequestStore.get_request` | Eager-loaded `response` relationship |
| Active WebSocket connection for conversation session | CH → in-memory connection registry | Map of `session_id` → WebSocket client |

### Writes

| Data | Accessor | Pattern |
|------|----------|---------|
| Intervention request creation (conversation-scoped) | CH → CC → `InterveneRequestStore.create_request` | CH calls internal endpoint; CC persists with `conversation_session_id` + `delegation_depth` |
| `intervene_request` turn creation | CH → CC → `ConversationStore.add_turn` | CH calls internal endpoint; turn has `turn_type=intervene_request` + `intervene_request_id` FK |
| `intervene_response` turn creation | CC → `ConversationStore.add_turn` (in `submit_response`) | Auto-created when responding to conversation-scoped request |
| Intervention response submission | Frontend → CH (WebSocket primary) or Frontend → CC (REST fallback) | Dual-path: WS preferred for latency, REST for reliability |
| Chat message blocking | CH → rejects client message | Checks pending-intervention flag before routing message to AR |

### Service Boundaries

- **Agent Runtime** never reads from or writes to the database — all `InterveneRequest` persistence is via Communication Hub → Control Center
- **Agent Runtime** never receives user identity tokens — intervention responses are stripped of caller identity before injection as tool return values
- **Communication Hub** does not directly manipulate database records — it calls Control Center internal endpoints for all persistence
- **Frontend** calls backend REST APIs for data, WebSocket for real-time messaging — no direct database access

---

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TurnType` | Enum (Python) | Turn type enum: `message`, `intervene_request`, `intervene_response` | `backend/app/db/models/conversations.py` |
| `ConversationTurn.turn_type` | Column | New `turn_type` field on turns table | `backend/app/db/models/conversations.py` |
| `ConversationTurn.intervene_request_id` | Column | FK to `intervene_requests.id`, nullable | `backend/app/db/models/conversations.py` |
| `ConversationTurn.intervene_request` | Relationship | ORM relationship to `InterveneRequest` | `backend/app/db/models/conversations.py` |
| `InterveneRequest.conversation_session_id` | Column | FK to `conversation_sessions.id`, nullable | `backend/app/db/models/intervene.py` |
| `InterveneRequest.delegation_depth` | Column | Integer, default 0, denormalized delegation depth | `backend/app/db/models/intervene.py` |
| `InterveneRequest.conversation_session` | Relationship | ORM relationship to `ConversationSession` | `backend/app/db/models/intervene.py` |
| `ConversationTurnRead` | Pydantic Schema | Read schema for conversation turns, includes `turn_type` and `intervene_request_id` | `backend/app/schemas/conversations.py` |
| `InterveneRequestCreate` | Pydantic Schema | Create schema, includes optional `conversation_session_id` and `delegation_depth` | `backend/app/schemas/intervene.py` |
| `InterveneRequestRead` | Pydantic Schema | Read schema, includes `conversation_session_id` and `delegation_depth` | `backend/app/schemas/intervene.py` |
| `ConversationStore.add_turn` | Method | Extended to accept `turn_type` and `intervene_request_id` params | `backend/app/services/conversations/store.py` |
| `InterveneRequestStore.create_request` | Method | Extended with `conversation_session_id` and `delegation_depth` params | `backend/app/services/agents/intervene_service.py` |
| `InterveneRequestStore.list_pending_for_conversation` | Method | New query method for conversation-scoped pending interventions | `backend/app/services/agents/intervene_service.py` |
| `InterveneRequestStore.submit_response` | Method | Extended to auto-create `intervene_response` conversation turn when conversation-scoped | `backend/app/services/agents/intervene_service.py` |
| `POST /conversations/{id}/interventions/{req_id}/respond` | API Endpoint | Respond to intervention within conversation session | `backend/app/api/v1/conversations.py` |
| `GET /conversations/{id}/interventions/pending` | API Endpoint | List pending interventions for conversation session | `backend/app/api/v1/conversations.py` |
| `InterventionRouter` | Class | Routes conversation-scoped intervention signals to WebSocket clients | New file in Communication Hub |
| `InterventionQueue` | Class | Per-session FIFO queue for intervention requests | New file in Communication Hub |
| `TurnType` | TypeScript Type | Union type: `'message' \| 'intervene_request' \| 'intervene_response'` | `frontend/src/types/index.ts` |
| `ConversationTurn` (updated) | TypeScript Interface | Extended with `turn_type` and `intervene_request_id` | `frontend/src/types/index.ts` |
| `InterveneRequest` (updated) | TypeScript Interface | Extended with `conversation_session_id` and `delegation_depth` | `frontend/src/types/index.ts` |
| `InterveneRequestMessage` | TypeScript Interface | WebSocket `intervene_request` message payload | `frontend/src/types/index.ts` |
| `InterveneResponseMessage` | TypeScript Interface | WebSocket `intervene_response` message payload | `frontend/src/types/index.ts` |
| `InterveneCancelMessage` | TypeScript Interface | WebSocket `intervene_cancel` message payload | `frontend/src/types/index.ts` |
| `InterveneStatusMessage` | TypeScript Interface | WebSocket `intervene_status` message payload | `frontend/src/types/index.ts` |
| `useChatSession` (extended) | Hook | Extended to handle intervention messages, expose intervention state | `frontend/src/hooks/useChatSession.ts` |
| `useConversationIntervention` | Hook | New hook for intervention lifecycle management | `frontend/src/hooks/useConversationIntervention.ts` |
| `InlineInterventionDialog` | Component | Inline intervention dialog for approval/choice/text types | `frontend/src/components/conversations/InlineInterventionDialog.tsx` |
| `InterventionPendingIndicator` | Component | Visual waiting indicator in chat flow | `frontend/src/components/conversations/InterventionPendingIndicator.tsx` |
| `ConversationDialog` (updated) | Component | Integrates intervention components, input blocking, state transitions | `frontend/src/components/agents/ConversationDialog.tsx` |
| `IntervenePage` (updated) | Page | Shows conversation context for intervention requests | `frontend/src/pages/agents/IntervenePage.tsx` |
| `InterveneRequestList` | Component | Existing intervention request list, may show conversation context | `frontend/src/components/agents/InterveneRequestList.tsx` |
| `InterveneResponseDialog` | Component | Existing standalone intervention dialog, preserved unchanged | `frontend/src/components/agents/InterveneResponseDialog.tsx` |
| `useInterveneRequests` | Hook | Existing hook for dashboard intervention polling, preserved unchanged | `frontend/src/hooks/useInterveneRequests.ts` |
| `interveneApi` | Module | Existing API module, unchanged (new endpoints are on conversations router) | `frontend/src/api/interveneApi.ts` |
| `ChatStatusKind` (extended) | TypeScript Type | Extended with intervention waiting status value | `frontend/src/hooks/useChatSession.ts` |
| `useDialogErrorHandler` | Hook | Existing error handler hook, reused in `useConversationIntervention` | `frontend/src/hooks/useDialogErrorHandler.ts` |
| `PermissionDeniedAlert` | Component | Existing error alert component, reused in `InlineInterventionDialog` | `frontend/src/components/permissions/PermissionDeniedAlert.tsx` |
