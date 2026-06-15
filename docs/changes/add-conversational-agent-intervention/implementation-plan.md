# Implementation Plan: Conversational Agent Intervention

## Overview

This plan implements the surfacing of delegated sub-agent intervention requests within the conversation UI. When a delegated sub-agent calls `system____human_intervene`, the request is routed to the parent conversation's WebSocket client, displayed as an inline intervention dialog, and the response is injected back into the sub-agent's execution. This closes the gap where delegated intervention requests were previously invisible in conversational sessions.

## Task Checklist

### Phase 1 — Database Schema Changes
- [ ] 1.1 — Add `turn_type` enum and field to `ConversationTurn` model
- [ ] 1.2 — Add `intervene_request_id` FK to `ConversationTurn` model
- [ ] 1.3 — Add `conversation_session_id` FK and `delegation_depth` to `InterveneRequest` model
- [ ] 1.4 — Generate and verify Alembic migration

### Phase 2 — Backend Schema Updates
- [ ] 2.1 — Update `ConversationTurnRead` Pydantic schema with new fields
- [ ] 2.2 — Update `InterveneRequestCreate` and `InterveneRequestRead` Pydantic schemas

### Phase 3 — Backend Service Layer
- [ ] 3.1 — Extend `ConversationStore.add_turn` to accept `turn_type` and `intervene_request_id`
- [ ] 3.2 — Extend `InterveneRequestStore.create_request` to accept conversation context fields
- [ ] 3.3 — Add `list_pending_for_conversation` query method to `InterveneRequestStore`
- [ ] 3.4 — Extend `InterveneRequestStore.submit_response` to create a paired `intervene_response` conversation turn

### Phase 4 — Backend API Changes
- [ ] 4.1 — Add `POST /api/v1/conversations/{session_id}/interventions/{request_id}/respond` endpoint
- [ ] 4.2 — Add `GET /api/v1/conversations/{session_id}/interventions/pending` endpoint
- [ ] 4.3 — Update `POST /api/v1/conversations/{session_id}/turns` to accept new turn types
- [ ] 4.4 — Update `POST /api/v1/intervene/` create path to accept `conversation_session_id` and `delegation_depth`

### Phase 5 — Communication Hub Intervention Routing
- [ ] 5.1 — Implement Intervention Router module in Communication Hub
- [ ] 5.2 — Implement Intervention Queue (per-conversation-session FIFO)
- [ ] 5.3 — Add WebSocket message types: `intervene_request`, `intervene_response`, `intervene_cancel`, `intervene_status`
- [ ] 5.4 — Route delegated intervention signals to parent conversation WebSocket clients
- [ ] 5.5 — Block chat messages when intervention is pending per session

### Phase 6 — Frontend Type Definitions
- [ ] 6.1 — Add `TurnType` union to TypeScript types and update `ConversationTurn` interface
- [ ] 6.2 — Update `InterveneRequest` interface with new fields
- [ ] 6.3 — Add intervention WebSocket message type interfaces

### Phase 7 — Frontend Hooks and State
- [ ] 7.1 — Extend `useChatSession` to handle intervention WebSocket message types
- [ ] 7.2 — Create `useConversationIntervention` hook for intervention state management
- [ ] 7.3 — Add intervention reconnect logic to `useChatSession`

### Phase 8 — Frontend UI Components
- [ ] 8.1 — Build `InlineInterventionDialog` component (approval/choice/text variants)
- [ ] 8.2 — Build `InterventionPendingIndicator` component (chat flow status)
- [ ] 8.3 — Integrate intervention components into `ConversationDialog`
- [ ] 8.4 — Implement input blocking during pending interventions

### Phase 9 — Dashboard Integration
- [ ] 9.1 — Update `IntervenePage` to display conversational intervention requests
- [ ] 9.2 — Update runtime dashboard to surface in-conversation intervention requests

### Phase 10 — Testing
- [ ] 10.1 — Write unit tests for model/schema changes
- [ ] 10.2 — Write service layer unit tests for new intervention routing logic
- [ ] 10.3 — Write API integration tests for new and changed endpoints
- [ ] 10.4 — Write frontend unit tests for intervevension components
- [ ] 10.5 — Write frontend hook tests for intervention state management
- [ ] 10.6 — Write E2E tests for full conversational intervention flow

---

## Phase 1 — Database Schema Changes

### Task 1.1 — Add `turn_type` enum and field to `ConversationTurn` model

Extend the `ConversationTurn` SQLAlchemy model in `backend/app/db/models/conversations.py` with a new `TurnType` Python enum containing values `message`, `intervene_request`, and `intervene_response`. Add a `turn_type` mapped column to `ConversationTurn` with `message` as the default value. This field distinguishes regular chat messages from intervention events.

**Done when:**
- `TurnType` enum is defined with values `message`, `intervene_request`, `intervene_response`
- `ConversationTurn` has a non-nullable `turn_type` column with `message` as default
- Enum is instantiated with a unique PostgreSQL enum name to avoid collisions

### Task 1.2 — Add `intervene_request_id` FK to `ConversationTurn` model

Add a nullable `intervene_request_id` foreign key column to `ConversationTurn` referencing `intervene_requests.id`. This links intervention-type turns back to their underlying `InterveneRequest` for display and lifecycle tracking. Also add the SQLAlchemy relationship to `InterveneRequest` with lazy loading.

**Done when:**
- `ConversationTurn` has a nullable `intervene_request_id` column with a FK to `intervene_requests.id`
- A relationship is defined on `ConversationTurn` linking to `InterveneRequest`
- The relationship allows the foreign key to be NULL for regular message turns

### Task 1.3 — Add `conversation_session_id` FK and `delegation_depth` to `InterveneRequest` model

Add a nullable `conversation_session_id` foreign key column to `InterveneRequest` referencing `conversation_sessions.id`. This identifies the parent conversation session where the intervention should be surfaced. `NULL` values preserve the existing non-conversational flow. Also add a `delegation_depth` integer column (default `0`) to preserve delegation chain depth directly in the intervention record for audit queries without joins through `AgentJob`.

**Done when:**
- `InterveneRequest` has a nullable `conversation_session_id` column with FK to `conversation_sessions.id`
- `InterveneRequest` has a `delegation_depth` integer column with default `0`
- A relationship is defined on `InterveneRequest` linking to `ConversationSession`
- No existing `NotNull` constraints are violated (both new columns are nullable)

### Task 1.4 — Generate and verify Alembic migration

Run `alembic revision --autogenerate -m "add_conversation_intervention_fields"` in the `backend/` directory. Review the generated migration for correctness: ensure enum types use `create_type=False` for PostgreSQL `ENUM`, confirm the `down_revision` chain is correct, verify all three column additions are present, and the downgrade function is reversible. Apply the migration with `alembic upgrade head`, verify with `alembic current`, and confirm the new columns exist in the database.

**Done when:**
- Migration file is generated at `backend/alembic/versions/`
- Migration uses `postgresql.ENUM(..., create_type=False)` for enum types
- `downgrade()` function reverses all added columns and enum
- `alembic upgrade head` completes without errors
- `alembic current` shows the latest revision
- Database columns are verified with `\d conversation_turns` and `\d intervene_requests` in PostgreSQL

---

## Phase 2 — Backend Schema Updates

### Task 2.1 — Update `ConversationTurnRead` Pydantic schema with new fields

Add `turn_type` and `intervene_request_id` fields to `ConversationTurnRead` in `backend/app/schemas/conversations.py`. The `turn_type` field should be a string with allowed values matching the `TurnType` enum. The `intervene_request_id` should be `UUID | None`. Ensure `from_attributes=True` mode is set for ORM compatibility.

**Done when:**
- `ConversationTurnRead` includes `turn_type: str` and `intervene_request_id: UUID | None`
- Schema validates correctly with test data for all three turn types
- Existing conversation endpoint responses include the new fields (not errors)

### Task 2.2 — Update `InterveneRequestCreate` and `InterveneRequestRead` Pydantic schemas

Add `conversation_session_id` (optional `UUID`) and `delegation_depth` (optional `int`, default `0`) to both `InterveneRequestCreate` and `InterveneRequestRead` in `backend/app/schemas/intervene.py`. The create schema accepts these when intervention originates in a conversation context. The read schema exposes them in API responses.

**Done when:**
- `InterveneRequestCreate` has optional `conversation_session_id: UUID | None` and `delegation_depth: int = 0`
- `InterveneRequestRead` has `conversation_session_id: UUID | None` and `delegation_depth: int`
- Existing tests for intervene endpoints continue to pass (new fields are nullable/defaulted)

---

## Phase 3 — Backend Service Layer

### Task 3.1 — Extend `ConversationStore.add_turn` to accept `turn_type` and `intervene_request_id`

Update the `add_turn` method signature in `backend/app/services/conversations/store.py` to accept optional `turn_type` (default `message`) and `intervene_request_id` (default `None`) parameters. Pass these through to the `ConversationTurn` constructor when creating a new turn. No breaking changes — existing callers receive the same behavior with the new defaults.

**Done when:**
- `add_turn` accepts `turn_type` and `intervene_request_id` as optional keyword arguments
- Default behavior is unchanged (calls without new params create `message` turns with `NULL` FK)
- Turns created with `turn_type="intervene_request"` correctly persist to the database
- Turn count increment on the parent session continues to work for all turn types

### Task 3.2 — Extend `InterveneRequestStore.create_request` to accept conversation context fields

Update `create_request` in `backend/app/services/agents/intervene_service.py` to accept optional `conversation_session_id` and `delegation_depth` parameters. Pass these to the `InterveneRequest` constructor. The existing signature and non-conversational flow are preserved — these parameters default to `None`/`0`.

**Done when:**
- `create_request` accepts optional `conversation_session_id` and `delegation_depth` parameters
- Creating a request with `conversation_session_id` persists both fields correctly
- Creating a request without these parameters produces the same result as before (no regression)

### Task 3.3 — Add `list_pending_for_conversation` query method to `InterveneRequestStore`

Add a new method `list_pending_for_conversation` that queries the `intervene_requests` table for requests where `conversation_session_id` matches the given session ID and `status` is `pending`. Order by `created_at` ascending to support FIFO queue semantics. This is used by the pending intervention endpoint (Task 4.2) and by the Communication Hub for re-delivery on reconnect.

**Done when:**
- Method takes `db` and `conversation_session_id` parameters
- Returns a list of pending `InterveneRequest` objects for the given conversation session
- Results are ordered by `created_at` ascending
- Returns an empty list (not error) when no pending requests exist

### Task 3.4 — Extend `InterveneRequestStore.submit_response` to create a paired `intervene_response` conversation turn

When `submit_response` is called on an `InterveneRequest` that has a `conversation_session_id`, automatically create a `ConversationTurn` of type `intervene_response` in the conversation session. The turn content should summarize the response (approval value, selected choice, or text snippet). This ensures the intervention response is captured as a conversation turn for audit and replay without requiring the API layer to orchestrate it separately.

**Done when:**
- For requests with `conversation_session_id`, a `ConversationTurn` with `turn_type="intervene_response"` is created
- The turn content includes a human-readable summary of the response
- The turn references the `intervene_request_id` FK for traceability
- The non-conversational flow (no `conversation_session_id`) is unchanged — no conversation turn is created
- The AgentJob status transition to `running` still occurs for all requests

---

## Phase 4 — Backend API Changes

### Task 4.1 — Add `POST /api/v1/conversations/{session_id}/interventions/{request_id}/respond` endpoint

Add a new endpoint to `ConversationRouter` that accepts an intervention response for a given intervention request within a conversation session. This endpoint validates the requesting user's permission, calls `InterveneRequestStore.submit_response`, and returns the result. It serves as the REST fallback when the WebSocket respond path is unavailable.

The endpoint must:
- Validate that the conversation session exists and is active
- Validate that the intervention request belongs to the given conversation session
- Delegate to `InterveneRequestStore.submit_response` for persistence and AgentJob resumption
- Return the created `InterveneResponseRead`

**Done when:**
- Endpoint is registered under `ConversationRouter`
- Requires `RT_CONVERSATION` read permission
- Validates session ownership (requesting user matches `triggered_by_user_id`)
- Returns `403` for permission mismatch
- Returns `404` for non-existent session or request
- Returns `400` if request is not pending
- Returns `201` with `InterveneResponseRead` on success
- Creates a `intervene_response` conversation turn via Task 3.4

### Task 4.2 — Add `GET /api/v1/conversations/{session_id}/interventions/pending` endpoint

Add a new endpoint to `ConversationRouter` that returns the currently pending intervention request(s) for a conversation session. Used by the frontend on reconnect to re-surface outstanding interventions. Calls `InterveneRequestStore.list_pending_for_conversation`.

**Done when:**
- Endpoint is registered under `ConversationRouter`
- Requires `RT_CONVERSATION` read permission
- Returns a list of pending `InterveneRequestRead` objects
- Returns an empty list (not error) when no pending requests exist
- Validates session ownership

### Task 4.3 — Update `POST /api/v1/conversations/{session_id}/turns` to accept new turn types

If a turns creation endpoint exists, update it to accept `turn_type` values of `intervene_request` and `intervene_response`. If no dedicated turns POST endpoint exists (turns are created internally via service layer), verify that the existing `GET /conversations/{session_id}` and `POST /conversations/{session_id}/resume` endpoints correctly serialize the new fields without error.

**Done when:**
- Existing conversation read endpoints return `turn_type` and `intervene_request_id` fields
- Serialization does not break for sessions with intervention-type turns
- Session detail responses include intervention turns in correct chronological order

### Task 4.4 — Update `POST /api/v1/intervene/` create path to accept `conversation_session_id` and `delegation_depth`

If the `intervene/` API has an endpoint for creating requests (not just reading/responding), update it to accept the new optional fields. Review the existing `intervene.py` router: currently it only exposes list, get, respond, cancel, and metrics. The creation path is internal (called by Agent Runtime via Communication Hub). Verify that the internal creation call path (likely through the Communication Hub) can pass `conversation_session_id` and `delegation_depth` to `InterveneRequestStore.create_request`.

**Done when:**
- Internal creation flow can pass `conversation_session_id` and `delegation_depth`
- The `list_intervene_requests` endpoint returns the new fields in responses without errors
- The `get_intervene_request` endpoint returns the new fields
- The `get_intervene_metrics` endpoint continues to work without modification

---

## Phase 5 — Communication Hub Intervention Routing

### Task 5.1 — Implement Intervention Router module in Communication Hub

Create a new `InterventionRouter` class/module in the Communication Hub service. Its responsibility: inspect each `human_intervene` suspend signal from Agent Runtime for a `conversation_session_id`. When present, route the intervention request to the connected WebSocket client of the parent conversation session. When absent, fall through to the existing dashboard-based intervention flow (no behavior change for non-conversational interventions).

**Done when:**
- Router intercepts suspend signals from Agent Runtime containing `human_intervene` tool calls
- Router detects the presence of `conversation_session_id` in the signal payload
- Router looks up the active WebSocket connection for the given conversation session
- When a connection is found, pushes an `intervene_request` WebSocket message to that client
- When no `conversation_session_id` is present, the signal flows to the existing dashboard path unchanged
- Router logs routing decisions for observability

### Task 5.2 — Implement Intervention Queue (per-conversation-session FIFO)

Create an `InterventionQueue` class that maintains per-conversation-session FIFO queues. When a delegated sub-agent calls `human_intervene` and another intervention is already pending for the same conversation, the new request is enqueued. When the current intervention is resolved or cancelled, the next request is dequeued and delivered to the UI via WebSocket.

**Done when:**
- Queue is scoped per `conversation_session_id`
- Enqueue and dequeue operations are thread-safe
- Queue persists across WebSocket disconnects (backed by pending requests in the database)
- On reconnect, all pending requests are re-delivered in FIFO order
- Queue state is cleared when the conversation session ends

### Task 5.3 — Add WebSocket message types for intervention

Define and implement the following new WebSocket message types in the Communication Hub:

- `intervene_request` (server → client): Pushed when a delegated sub-agent requests intervention. Payload includes `request_id`, `intervention_type`, `reason`, `choices` (for choice type), `agent_type` (sub-agent type name), and `delegation_depth`.
- `intervene_response` (client → server): Sent when the user submits a response. Payload includes `request_id`, and the response value appropriate to the type.
- `intervene_cancel` (client → server): Sent when the user dismisses/cancels the intervention dialog. Payload includes `request_id`.
- `intervene_status` (server → client): Pushed to update the UI about intervention lifecycle changes. Payload includes `request_id` and `status` (`pending`, `responded`, `cancelled`, `expired`).

Also modify the existing `chat` message type handling to block incoming user messages when an intervention is pending for the conversation session.

**Done when:**
- All four new message types are handled in the WebSocket message loop
- `intervene_request` messages are correctly parsed by the frontend `useChatSession` hook
- `intervene_response` and `intervene_cancel` messages are correctly routed from client to server
- Chat message blocking returns an appropriate error to the client (not silent drop)

### Task 5.4 — Route delegated intervention signals to parent conversation WebSocket clients

Wire the Intervention Router into the Communication Hub's message broker pipeline. When Agent Runtime sends a suspend signal for a `human_intervene` invocation that includes a `conversation_session_id`, the router extracts the intervention details, persists the intervention as a conversation turn via CC, and pushes the `intervene_request` WebSocket message to the connected client.

**Done when:**
- Agent Runtime suspend signals including `conversation_session_id` are intercepted
- The `InterveneRequest` is persisted via CC with `conversation_session_id` and `delegation_depth`
- A `ConversationTurn` of type `intervene_request` is created via CC
- The `intervene_request` WebSocket message is pushed to the correct client
- Non-conversational interventions (no `conversation_session_id`) are not affected

### Task 5.5 — Block chat messages when intervention is pending per session

In the Communication Hub's Conversation Session Manager, track whether a session has an outstanding intervention request. When a session is in the `intervention_pending` state (i.e., has at least one pending `InterveneRequest`), reject new incoming `chat` messages from the WebSocket client with an appropriate error response. This prevents users from sending messages while an intervention dialog is open.

**Done when:**
- Session tracks whether any pending interventions exist
- Incoming chat messages are rejected while intervention is pending
- Error response includes a clear message indicating why input is blocked
- After intervention resolution, normal message flow resumes immediately
- Session termination clears the blocked state

---

## Phase 6 — Frontend Type Definitions

### Task 6.1 — Add `TurnType` union and update `ConversationTurn` interface

In `frontend/src/types/index.ts`, add a `TurnType` union type with values `'message' | 'intervene_request' | 'intervene_response'`. Update the `ConversationTurn` interface to include `turn_type: TurnType` and `intervene_request_id: string | null`.

**Done when:**
- `TurnType` type is exported from `frontend/src/types/index.ts`
- `ConversationTurn` interface includes `turn_type` and `intervene_request_id`
- All existing consumers of `ConversationTurn` compile without errors (new fields are string/optional)

### Task 6.2 — Update `InterveneRequest` interface with new fields

In `frontend/src/types/index.ts`, add `conversation_session_id: string | null` and `delegation_depth: number` to the `InterveneRequest` interface.

**Done when:**
- `InterveneRequest` interface includes `conversation_session_id` and `delegation_depth`
- Existing consumers of `InterveneRequest` compile without errors
- `InterveneRequestFilter` interface (in `interveneApi.ts`) optionally accepts `conversation_session_id`

### Task 6.3 — Add intervention WebSocket message type interfaces

Add TypeScript interfaces for the new WebSocket message payloads: `InterveneRequestMessage`, `InterveneResponseMessage`, `InterveneCancelMessage`, and `InterveneStatusMessage`. These types will be used by the `useChatSession` hook to parse and type-check incoming WebSocket data.

**Done when:**
- Type interfaces are defined in `frontend/src/types/index.ts` or a new `frontend/src/types/intervention.ts`
- Each interface includes the fields documented in Task 5.3
- Types are exported for use in hooks and components

---

## Phase 7 — Frontend Hooks and State

### Task 7.1 — Extend `useChatSession` to handle intervention WebSocket message types

In `frontend/src/hooks/useChatSession.ts`, extend the `ws.onmessage` handler to recognize and process the four new intervention WebSocket message types. When an `intervene_request` message is received, update state to surface the intervention dialog. When an `intervene_status` message is received, update the intervention lifecycle state accordingly.

Add new state to the hook return value: `interventionRequest` (the current pending intervention, or `null`), `interventionQueueLength` (number of pending interventions).

When an intervention is pending, the hook should set `chatStatus` to a distinct `waiting_for_human` kind (add this to the `ChatStatusKind` union) and set `pendingQuestion` to indicate the conversation is in a non-standard waiting state.

**Done when:**
- `useChatSession` parses `intervene_request`, `intervene_status` messages from WebSocket
- Hook exposes `interventionRequest` and `interventionQueueLength` state
- `ChatStatusKind` union includes a value for intervention waiting
- WebSocket `sendInterventionResponse` and `cancelIntervention` functions are exposed
- Existing message handling is not regressed for non-intervention messages

### Task 7.2 — Create `useConversationIntervention` hook

Create a new hook `frontend/src/hooks/useConversationIntervention.ts` that provides intervention-specific logic separate from the chat session. This hook:
- Fetches pending interventions on mount (for reconnect scenarios) via `GET /api/v1/conversations/{session_id}/interventions/pending`
- Provides `respondToIntervention` function that sends response via WebSocket (primary path) with REST fallback via `POST /api/v1/conversations/{session_id}/interventions/{request_id}/respond`
- Provides `cancelIntervention` function
- Tracks submission state and error handling using the standard `useDialogErrorHandler` pattern

**Done when:**
- Hook is created and exported
- Reconnect fetch is performed on mount when `sessionId` is provided
- `respondToIntervention` and `cancelIntervention` functions are exported
- Uses `useDialogErrorHandler` for error state
- Permission errors (403) are surfaced with `PermissionDeniedAlert` pattern

### Task 7.3 — Add intervention reconnect logic to `useChatSession`

Extend the `connect` function in `useChatSession` to fetch any pending intervention requests after WebSocket connection is established but before allowing the user to send messages. If a pending intervention exists, immediately surface it as if it just arrived via WebSocket, so users reconnecting mid-intervention see the dialog automatically.

**Done when:**
- After WebSocket `onopen`, the hook checks for pending interventions
- Pending intervention is surfaced automatically if found
- Input remains blocked until the intervention is resolved
- Message history from the resume endpoint shows intervention turns correctly

---

## Phase 8 — Frontend UI Components

### Task 8.1 — Build `InlineInterventionDialog` component

Create `frontend/src/components/conversations/InlineInterventionDialog.tsx`. This component renders an intervention dialog inline within the chat message flow (not as a MUI Dialog overlay). It closely follows the prototype design at `docs/changes/add-conversational-agent-intervention/prototype/index.html`.

The component must support three intervention types:
- **Approval**: Two buttons ("Approve" with success color, "Deny" with error outlined style)
- **Choice**: Radio button group listing available choices, plus a "Confirm Selection" button that is disabled until a choice is selected
- **Text**: Multiline text input with character limit and "Submit Response" button

The component must also include:
- A header showing which delegated agent requested intervention and delegation depth
- An intervention type badge (approval/choice/text) with appropriate color coding
- A "Dismiss / Cancel" link at the bottom
- Error banner for permission denied using `PermissionDeniedAlert` pattern
- Loading state during submission (LinearProgress)
- All user-facing text via `t()` i18n function

**Done when:**
- Component handles all three intervention types with correct interactive controls
- Visual styling matches prototype colors, spacing, and animations
- Dismiss button triggers cancellation flow
- Error state displays with `PermissionDeniedAlert` when API returns 403
- Loading state shows during submission
- Component is accessible (keyboard navigable, ARIA labels)
- All labels use `t()` for i18n

### Task 8.2 — Build `InterventionPendingIndicator` component

Create `frontend/src/components/conversations/InterventionPendingIndicator.tsx`. This component renders a visual indicator in the chat flow when an intervention is awaiting user input. It replaces the indefinite "thinking" or "waiting" dots with "Waiting for your input" styled text with an amber/orange color treatment.

The indicator should also render in the topbar of the ConversationDialog (replacing the "Connected" badge) and in the context sidebar (updating the session status).

**Done when:**
- Indicator appears in the chat flow when an intervention is pending
- Uses amber/warning colors consistent with the prototype
- Includes animated dots or similar visual cue indicating an active waiting state
- Integrates with the topbar badge and context panel status
- All text uses `t()` i18n function

### Task 8.3 — Integrate intervention components into `ConversationDialog`

In `frontend/src/components/agents/ConversationDialog.tsx`, integrate `InlineInterventionDialog` and `InterventionPendingIndicator`. When `useChatSession` signals an active intervention request, render the inline dialog at the current position in the chat flow (after the most recent message and before the input area). When the intervention is resolved, remove the dialog and add the intervention response as a distinct chat message with intervention response styling.

Also update the topbar badge to show "Waiting for Input" state and the context panel to show the pending queue count.

**Done when:**
- `InlineInterventionDialog` renders inline in the chat flow when `interventionRequest` is non-null
- Intervention resolved messages appear with the distinct styling from the prototype
- Topbar badge transitions between "Connected", "Waiting for Input", and "Input Blocked" states
- Context panel shows intervention queue count and pending intervention details
- Full chat message history (including intervention-type turns) scrolls naturally

### Task 8.4 — Implement input blocking during pending interventions

In `ConversationDialog`, disable the chat message input field and send button when an intervention is pending. The input placeholder text should change to "Waiting for your intervention response..." or similar. Additionally, prevent the user from sending new chat messages while `interventionActive` is true (the hook's `sendMessage` function should be gated or the input should be physically disabled).

**Done when:**
- Chat input and send button are disabled when intervention is pending
- Placeholder text changes to indicate the reason input is blocked
- Input re-enables immediately after intervention is resolved or cancelled
- The blocking mechanism does not interfere with the intervention response submission

---

## Phase 9 — Dashboard Integration

### Task 9.1 — Update `IntervenePage` to display conversational intervention requests

Modify `frontend/src/pages/agents/IntervenePage.tsx` to show a new column or badge indicating whether an intervention request is conversation-scoped (has `conversation_session_id`). Add a "View in Conversation" action that navigates to the relevant conversation dialog. The existing non-conversational intervention display and `InterveneResponseDialog` flow must be preserved unchanged.

**Done when:**
- Intervention request list shows conversation context for requests with `conversation_session_id`
- A navigation action is available to open the relevant conversation
- Existing non-conversational flow continues to work identically
- Filter options may include conversation-scoped vs standalone interventions

### Task 9.2 — Update runtime dashboard to surface in-conversation intervention requests

Extend the runtime control dashboard (if it exists as a separate view) to include intervention requests from conversational sessions. The per-spec description states the dashboard should "surface intervention requests originating from delegated agents in conversational sessions, enabling central monitoring of all pending human interventions regardless of execution context." Verify the current dashboard implementation and add conversation-sourced intervention requests to the display.

**Done when:**
- Dashboard shows conversational intervention requests alongside standalone ones
- Each conversational request is distinguishable by context (conversation session ID or indicator)
- Existing dashboard polling/filtering continues to work
- No regression in standalone intervention dashboard display

---

## Phase 10 — Testing

### Task 10.1 — Write unit tests for model/schema changes

Add tests in `backend/tests/` covering the new model fields and enum types. Verify:
- `ConversationTurn` can be created with `turn_type` values `message`, `intervene_request`, `intervene_response`
- `ConversationTurn` with `intervene_request_id` persists and retrieves correctly
- `InterveneRequest` with `conversation_session_id` and `delegation_depth` persists correctly
- Pydantic schemas serialize/deserialize the new fields correctly
- Default values (`turn_type=message`, `delegation_depth=0`) are applied

**Done when:**
- Tests pass for all new model and schema additions
- Tests cover both valid and edge-case values
- Tests do not break when run against a clean test database

### Task 10.2 — Write service layer unit tests for new intervention routing logic

Add tests in `backend/tests/services/test_intervene_service.py` covering:
- `create_request` with `conversation_session_id` and `delegation_depth`
- `list_pending_for_conversation` returns correct results and empty list
- `submit_response` creates `intervene_response` conversation turn when `conversation_session_id` is present
- `submit_response` does NOT create conversation turn when `conversation_session_id` is `NULL`
- AgentJob status transition still works in both paths

Add tests in `backend/tests/` for ConversationStore:
- `add_turn` with `turn_type="intervene_request"` and `intervene_request_id`
- `add_turn` with `turn_type="intervene_response"` and `intervene_request_id`

**Done when:**
- All service-layer tests pass
- Tests use isolated database sessions (fixtures)
- Both conversational and non-conversational paths are covered

### Task 10.3 — Write API integration tests for new and changed endpoints

Add tests in `backend/tests/api/v1/test_conversations.py` or a new file covering:
- `POST /api/v1/conversations/{session_id}/interventions/{request_id}/respond` — success, session not found (404), request not in session (400), not pending (400), unauthorized (403)
- `GET /api/v1/conversations/{session_id}/interventions/pending` — returns pending, returns empty, session not found
- Existing conversation endpoints return `turn_type` and `intervene_request_id` in response payloads

Add tests in `backend/tests/api/v1/test_intervene.py` covering:
- `POST /api/v1/intervene/` with `conversation_session_id` and `delegation_depth` (if creation endpoint exists)
- `GET /api/v1/intervene/requests` returns new fields in response

**Done when:**
- All API tests pass
- Tests exercise both success and error paths
- Tests use the project's existing test fixtures and auth patterns

### Task 10.4 — Write frontend unit tests for intervention components

Add tests in `frontend/src/__tests__/` for:
- `InlineInterventionDialog` — renders approval, choice, and text variants correctly; submit/dismiss triggers correct callbacks; disabled state on choice until selected; error display; loading state
- `InterventionPendingIndicator` — renders with correct styling and text

Use Vitest with React Testing Library. Follow existing test patterns from `InterveneResponseDialog.test.tsx` and `ConversationDialog.test.tsx`.

**Done when:**
- Component tests pass
- All three intervention types are tested for render and interaction
- Error state rendering is tested
- Submit and dismiss callbacks are verified

### Task 10.5 — Write frontend hook tests for intervention state management

Add tests for `useConversationIntervention` hook covering:
- Fetches pending interventions on mount
- Handles empty pending state
- Submits response via correct path
- Handles API errors with `useDialogErrorHandler` pattern
- Reconnect flow re-surfaces pending interventions

Add tests for `useChatSession` covering intervention message types:
- Parses `intervene_request` WebSocket message and updates state
- Exposes `interventionRequest` and related state
- Blocked state prevents sending messages

**Done when:**
- Hook tests pass
- WebSocket message parsing is tested for all four intervention message types
- Error handling paths are covered

### Task 10.6 — Write E2E tests for full conversational intervention flow

Add E2E tests in `e2e/tests/` covering the end-to-end scenario described in the prototype:
- User starts conversation with Customer Support Agent
- Agent delegates to Fraud Check Agent
- Fraud Check Agent requests approval intervention
- Inline dialog appears in conversation UI
- User approves; intervention response appears as a conversation turn
- Sub-agent continues with the response
- Handles dismiss/cancel flow
- Handles permission error display

Use the project's existing E2E testing framework and patterns. Ensure tests verify WebSocket message flow, database persistence, and UI state transitions.

**Done when:**
- E2E tests pass
- Full approval, choice, text, dismiss, and error scenarios are covered
- Tests verify audit trail (intervention turns in conversation history)
- Reconnect scenario is covered (disconnect during intervention, reconnect, dialog re-surfaces)

---

## Completion Checklist

- [ ] All 10 phases have all tasks marked complete
- [ ] Database migration applied and verified
- [ ] Backend API tests pass (existing + new)
- [ ] Frontend component tests pass
- [ ] Frontend hook tests pass
- [ ] E2E tests pass
- [ ] Non-conversational intervention flow verified (no regression)
- [ ] Service segregation rules verified (AR no DB access, no identity token exposure)
- [ ] Certificate-based auth boundaries verified intact
- [ ] All user-facing text uses i18n `t()` function
- [ ] Code review completed per project conventions
- [ ] Alembic migration includes reversible downgrade
- [ ] Master architecture docs updated per `architecture.md` section 5 instructions
- [ ] Master data model docs updated per `data-model.md` section 6 instructions
- [ ] Master product docs updated per `spec-change.md` spec update instructions
