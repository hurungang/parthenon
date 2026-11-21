# Tech Spec: persistent-agent-activity-state

## Technical Overview

The conversational chat surface currently reconstructs its "processing" indicator from ephemeral, process-local signals: CH's in-memory `ActiveSessionTracker` and `_pending_turn_tasks`, plus status events streamed from AR that are only persisted at the end of a turn. This change introduces a single, authoritative, persisted activity record per conversation session — a new `ConversationActivity` entity owned and written only by Control Center — so the indicator can be reconstructed exactly on reload, restart, and failover, and paused conversational turns can be resumed or resolved to a terminal state.

Status transitions flow AR → CH → CC → DB. Agent Runtime emits activity transitions over the existing NDJSON status channel; Communication Hub forwards each transition to a new CC write endpoint and pushes the normalized status to the live socket; Control Center upserts the single live row and exposes a read endpoint for hydration. On WebSocket (re)connect, CH hydrates the persisted activity from CC and pushes it to the client; the `status_pong` answer reads the persisted state instead of in-memory task state. The frontend accepts the full state model, hydrates on connect, and reconciles the activity bubble so a `waiting_for_human` state renders continuously (no blank gap) and terminal states clear the bubble (no stuck spinner).

## Component Breakdown

- **`ConversationActivity` model + `ActivityState` enum** (CC) — the persisted, tenant-scoped record of a conversation's current activity. Seven states (`thinking`, `using_tool`, `delegating`, `waiting_for_human`, `finished`, `failed`, `timed_out`); the last three are terminal. One live row per session, updated in place on every transition. Carries status-only context (tool name, delegation target, pending intervention id, detail) — never tokens, credentials, or secrets.
- **`ConversationActivityStore`** (CC) — owns atomic upsert, read, and terminal-resolution of the activity row. The only code that writes the row.
- **Activity write/read endpoints** (CC) — internal `PUT`/`GET` on `/internal/data/conversations/{conv_session_id}/activity`, gated by service certificate + signed tenant context, fail-closed without valid headers.
- **`ConversationActivityReaper`** (CC) — background task resolving stale, orphaned, or non-resumable activity to a terminal state, while protecting still-pending interventions on active sessions.
- **Agent Runtime conversational executor** — emits activity transitions (thinking / using_tool / delegating / waiting / waiting_for_human / timeout_or_failed / delegation_resumed) with state-specific context, **only over the CH-bound conversation-turn response stream** (AR originates no outbound call for activity); never writes the DB and never calls CC. Its in-process `conversation_resume` registry remains the pause/resume mechanism but is no longer the UI's source of truth.
- **Communication Hub status pipeline** — forwards each AR transition to the CC activity endpoint and pushes the normalized status to the live socket; hydrates current activity on connect; answers `status_ping` from the persisted state.
- **Frontend `useChatSession` + `ConversationDialog`** — parse the full state model, hydrate on connect, and render the activity bubble with continuous waiting-state visibility and terminal-state clearing.

## API Changes

All new/changed internal routes are under `backend/app/api/v1/internal/session_data.py` (or its module), gated by `require_service_certificate` + `require_internal_tenant_context`.

- **New** `PUT /internal/data/conversations/{conv_session_id}/activity` — upsert the current activity. Body: `state` (ActivityState), optional `current_turn_id`, `tool_name`, `target_agent_type_id`, `pending_intervene_request_id`, `detail`. Returns the persisted activity record.
- **New** `GET /internal/data/conversations/{conv_session_id}/activity` — return the current activity (explicit null when idle). Used by CH hydration.
- **Modified** `POST /internal/data/conversations/{conv_session_id}/prepare-turn` — after persisting the user turn, sets the session activity to `thinking` with the turn as `current_turn_id`.
- **Modified** `POST /internal/data/conversations/{conv_session_id}/append-turn` — after persisting the agent turn, resolves the activity to a terminal state (`finished`, or the terminal status conveyed by the final status event).

WebSocket message changes (CH → client):

- **New** `activity_state` — pushed once on connect, carrying the hydrated persisted activity (`state`, optional `tool_name`, `agent_type`, `pending_intervention`, `timestamp`).
- **Modified** `status_pong` — now returns the persisted `state` (plus context and a `pending_intervention` flag) instead of the `turn_in_flight` / `intervention_pending` booleans derived from in-memory state.

Communication Hub data-client additions (in `backend/app/communication_hub/data_client.py`): `upsert_conversation_activity` and `get_conversation_activity` (the only CH→CC activity calls, using `internal_httpx_client`).

## State Management

- **Backend (CC)** — the `conversation_activity` table is the single source of truth; CH and AR hold no authoritative activity state (CH's in-memory tracker becomes a read-through projection at most).
- **Backend (CH)** — `ActiveSessionTracker` remains for live-socket routing and intervention routing only; `_pending_turn_tasks` remains for cancellation only. Status truth is read from CC on `status_ping` and on connect.
- **Frontend (`useChatSession`)** — `chatStatus` (a `ChatStatus`) is now hydrated from the `activity_state` message on connect and from `status_pong`, and updated live from `chat_status` events. `turnInFlight` is kept open while a non-terminal state is active and closed on a terminal state. `interventionActiveRef` is re-armed when a hydrated `waiting_for_human` is received. `ConversationDialog` computes `showThinking`/standalone status line so `waiting_for_human` renders the pending-intervention indicator and terminal states clear the bubble.

## Data Access Patterns

- **Control Center** — sole DB accessor. Reads/writes `conversation_activity` via `ConversationActivityStore`; the reaper runs a periodic scan over non-terminal rows.
- **Agent Runtime** — no DB access and no CC client for activity (enforced structurally by `backend/tests/agent_runtime/test_ar_activity_persistence_boundaries.py`). AR emits each activity transition only inside the NDJSON response stream it returns to CH's conversation-turn call — it originates **no outbound call** for activity and never calls the CC activity endpoints or the database. (Pre-existing AR→CC data-plane calls for unrelated concerns — session-status PATCH, results, logs — are outside this change; the activity path deliberately neither adds nor reuses them.)
- **Communication Hub** — no DB access. Calls CC over the internal HTTP path (`internal_httpx_client`, auto-attached signed tenant headers) to upsert/hydrate activity.
- **Frontend** — no direct DB access; reads status over the WebSocket and (for history/intervention recovery) the existing REST conversation endpoints. The persisted activity is surfaced exclusively through the WebSocket push and `status_pong`.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ConversationActivity` | model | Persisted current-activity record (one live row per session) | `backend/app/db/models/conversation_activity.py` |
| `ActivityState` | enum | Seven-value activity state (three terminal) | `backend/app/db/models/conversation_activity.py` |
| `ConversationSession` | model | Conversation session; gains `activity` back-reference relationship | `backend/app/db/models/conversations.py` |
| `ConversationTurn` | model | Referenced by `ConversationActivity.current_turn_id` | `backend/app/db/models/conversations.py` |
| `ToolCallRecord` | model | Per-turn tool-call records (unchanged) | `backend/app/db/models/conversations.py` |
| `InterveneRequest` | model | Referenced by `ConversationActivity.pending_intervene_request_id` | `backend/app/db/models/intervene.py` |
| `ConversationActivityStore` | class | Atomic upsert/read/terminal-resolve of the activity row | `backend/app/services/conversations/activity_store.py` |
| `ConversationActivityReaper` | class | Background reaper resolving stale/orphaned activity to terminal | `backend/app/services/conversations/activity_reaper.py` |
| `human_intervene_tool` | endpoint | Creates the intervention request AND persists `waiting_for_human` activity (conversation-scoped) | `backend/app/api/v1/internal/system_tools.py` |
| `_CH_ALLOWLIST` | module var | Internal endpoint allowlist — must include the activity `PUT`/`GET` routes | `backend/app/api/deps.py` |
| `ConversationStore` | class | Persists conversation turns and tool-call records | `backend/app/services/conversations/store.py` |
| `prepare_conversation_turn` | endpoint | Persists user turn; sets activity to `thinking` | `backend/app/api/v1/internal/session_data.py` |
| `append_conversation_turn` | endpoint | Persists agent turn; resolves activity to terminal | `backend/app/api/v1/internal/session_data.py` |
| `upsert_conversation_activity` | endpoint | Internal write endpoint for activity transitions | `backend/app/api/v1/internal/session_data.py` |
| `get_conversation_activity` | endpoint | Internal read endpoint for activity hydration | `backend/app/api/v1/internal/session_data.py` |
| `InternalSessionDataRouter` | router | Internal data API router (service-cert + tenant context) | `backend/app/api/v1/internal/session_data.py` |
| `execute_conversation_turn` | endpoint | AR conversation-turn endpoint with `stream_status_events` | `backend/app/agent_runtime/api/conversation.py` |
| `conversation_router` | router | AR internal conversation routes | `backend/app/agent_runtime/api/conversation.py` |
| `AgentRuntimeExecutor` | class | Executes conversational turns in AR | `backend/app/services/agents/runtime_executor.py` |
| `execute_conversation_turn_from_context` | method | Entry point for one conversational turn | `backend/app/services/agents/runtime_executor.py` |
| `_execute_conversation_turn_from_context_inner` | method | Inner turn body; emits activity transitions | `backend/app/services/agents/runtime_executor.py` |
| `build_langchain_tools_for_ar_path` | function | Wraps tools; emits `using_tool`/`delegating`/`waiting` via callback | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `is_pending` | function | Returns True when a conversational turn is paused on intervention | `backend/app/agent_runtime/conversation_resume.py` |
| `register` | function | Registers a pending conversational intervention future | `backend/app/agent_runtime/conversation_resume.py` |
| `resolve` | function | Resolves a pending intervention with the operator response | `backend/app/agent_runtime/conversation_resume.py` |
| `unregister` | function | Drops a pending intervention registration | `backend/app/agent_runtime/conversation_resume.py` |
| `wait_for_resume` | function | Awaits operator resolution of a pending intervention | `backend/app/agent_runtime/conversation_resume.py` |
| `mark_session_waiting_for_human` | method | AR data-client call for `waiting_for_human` (task-session path) | `backend/app/agent_runtime/data_client.py` |
| `ControlCenterDataClient` (CH) | class | CH→CC internal data client | `backend/app/communication_hub/data_client.py` |
| `prepare_conversation_turn` | method | CH data-client call to prepare a turn | `backend/app/communication_hub/data_client.py` |
| `append_conversation_turn` | method | CH data-client call to append a turn | `backend/app/communication_hub/data_client.py` |
| `upsert_conversation_activity` | method | CH data-client call to persist an activity transition | `backend/app/communication_hub/data_client.py` |
| `get_conversation_activity` | method | CH data-client call to hydrate current activity | `backend/app/communication_hub/data_client.py` |
| `ActiveSessionTracker` | class | Socket map + intervention-active set (routing only) | `backend/app/api/ws/chat.py` |
| `_pending_turn_tasks` | module var | In-flight turn task registry (cancellation only) | `backend/app/api/ws/chat.py` |
| `cancel_pending_conversation_turn` | function | Cancels a pending turn task (end-session) | `backend/app/api/ws/chat.py` |
| `websocket_chat` | function | WS endpoint; adds on-connect activity hydration | `backend/app/api/ws/chat.py` |
| `run_conversation_turn` | function | Runs one turn under the watchdog | `backend/app/api/ws/chat.py` |
| `_process_message` | function | Persists/processes a turn (prepare → LLM → append) | `backend/app/api/ws/chat.py` |
| `_call_llm` | function | Delegates a turn to AR | `backend/app/api/ws/chat.py` |
| `_delegate_conversation_turn_to_agent_runtime` | function | Streams AR status events; forwards transitions to CC | `backend/app/api/ws/chat.py` |
| `_thinking_heartbeat_loop` | function | Keepalive status events while a turn is in flight | `backend/app/api/ws/chat.py` |
| `_build_chat_status_event` | function | Builds a normalized status event payload | `backend/app/api/ws/chat.py` |
| `_send_to_live_socket` | function | Sends over the live socket for a session | `backend/app/api/ws/chat.py` |
| `_persist_and_surface_turn_error` | function | Emits terminal status + persists an error turn | `backend/app/api/ws/chat.py` |
| `_handle_intervention_response` | function | Handles a WS intervention response | `backend/app/api/ws/chat.py` |
| `_handle_intervention_cancel` | function | Handles a WS intervention cancel | `backend/app/api/ws/chat.py` |
| `_signed_tenant_forwarding` | contextmanager | Mints fresh signed tenant headers for a CC call | `backend/app/api/ws/chat.py` |
| `useChatSession` | hook | WS lifecycle, status state, intervention, watchdog | `frontend/src/hooks/useChatSession.ts` |
| `ChatStatus` | type | Normalized chat status shape | `frontend/src/hooks/useChatSession.ts` |
| `ChatStatusKind` | type | Union of status kinds (incl. `waiting_for_human`, terminals) | `frontend/src/hooks/useChatSession.ts` |
| `parseChatStatus` | function | Parses `chat_status` messages into `ChatStatus` | `frontend/src/hooks/useChatSession.ts` |
| `parseActivityState` | function | Parses `activity_state` hydration messages | `frontend/src/hooks/useChatSession.ts` |
| `markTurnInFlight` | function | Opens/closes the in-flight window | `frontend/src/hooks/useChatSession.ts` |
| `isTurnInFlight` | function | True while a non-terminal status is active | `frontend/src/hooks/useChatSession.ts` |
| `ConversationDialog` | component | Chat dialog; renders the activity bubble lifecycle | `frontend/src/components/agents/ConversationDialog.tsx` |
| `ChatInputBar` | component | Chat input; disabled while waiting/in-flight | `frontend/src/components/agents/ConversationDialog.tsx` |
| `InterventionPendingIndicator` | component | "Waiting for your input" indicator | `frontend/src/components/conversations/InterventionPendingIndicator.tsx` |
| `useConversationIntervention` | hook | REST intervention fetch/respond/cancel | `frontend/src/hooks/useConversationIntervention.ts` |
