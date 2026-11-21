# Module: conversations — Tech Spec

> Part of the [technology documentation](../../README.md).

## Overview

The conversations module provides complete and durable persistence of every interaction that passes through the platform. Each conversation session groups a bounded set of turns; each turn captures a single message from a participant (user, agent, system, or tool); each tool call within a turn is separately recorded. This three-level structure ensures full audit trails and supports session replay for debugging and compliance purposes.

For **conversation-type agents**, the module provides persistent, user-named sessions with automatic title generation, session lifecycle management (active → closed → archived), and full turn history preservation. Users can start, resume, end, and archive conversation sessions through a dedicated Sessions tab in the agent type view.

Two later capabilities extend the same substrate without changing that model:

- **Persisted activity state** — one authoritative `ConversationActivity` row per session carries the current processing state (thinking / using tool / delegating / waiting for human / terminal). It is written only by Control Center, so the chat indicator survives reload, restart and failover.
- **Durable paused turns** — a paused conversational turn is backed by a queryable resume index (`ConversationTurnResume`) plus an opaque, versioned checkpoint payload (`ConversationTurnCheckpoint`). The turn can be resumed on *any* Agent Runtime instance, exactly once.

The module also hosts the **optimization-channel** conversation: an ordinary session whose `channel` is `"optimization"` and whose `agent_type_id` is the subject agent type. Session semantics (subject, availability, live-test ledger) are documented here; the optimization mode itself belongs to the [agents plans & optimization page](../agents/plans-optimization.md).

All writes are Control Center-only. Agent Runtime emits status/activity transitions inside the NDJSON stream it returns to Communication Hub and never touches the database; Communication Hub relays.

---

## Key Components

### Backend — persistence and lifecycle

| Component | Description |
|-----------|-------------|
| `ConversationStore` | Data-access class for conversation persistence; writes sessions, turns and tool call records; `update_title`, `archive_session`, user-scoped `list_sessions`, and the paginated `list_sessions_page` query (status semantics, explicit date range overrides the default window, ordered `updated_at` DESC, resume projection join) |
| `ConversationSessionManager` | Owns session lifecycle and ownership validation; `create()` keeps the business `input_type == conversation` guard; `create_optimization()` accepts typed **and** conversational subjects for the optimization channel; no update path exposes `agent_type_id` or `channel` |
| `SessionAutoNamer` | Background-task title generation; falls back to a truncated first message |
| `ConversationRouter` | Conversation REST surface: listing, detail, create/resume/end/archive, intervention pending/respond, paginated sessions listing, and the optimization-channel endpoints |
| `ConversationSession` / `ConversationTurn` / `ToolCallRecord` | Session, turn and per-turn tool-call models (turn type: `message` / `intervene_request` / `intervene_response`) |
| `terminate_in_flight_conversation_execution` | Best-effort termination of an in-flight execution bound to a session through the CC → CH → AR terminate chain (logged, never fails the end call) |

### Backend — activity state

| Component | Description |
|-----------|-------------|
| `ConversationActivity` + `ActivityState` | One live row per session; seven states (`thinking`, `using_tool`, `delegating`, `waiting_for_human`, `finished`, `failed`, `timed_out`), the last three terminal. Carries status-only context (tool name, delegation/delegation target, pending intervention id, detail, `active_resume_id`) — never tokens or credentials |
| `ConversationActivityStore` | The only writer of the activity row: atomic upsert, read, heartbeat `touch` (working rows only), and terminal resolution (optionally carrying a terminal reason) |
| `ConversationActivityReaper` | Background sweep that resolves stale/orphaned activity to a terminal state; extended into the **Terminal Resolver** that consults the linked resume record and writes record + activity together. A stale working row (`thinking` / `using_tool` / `delegating`) resolves to `failed` with the `unexpectedly_terminated` reason; a live `waiting_for_human` pause is protected |

### Backend — resume index and checkpoint store

| Component | Description |
|-----------|-------------|
| `ConversationTurnResume` | Queryable lifecycle record for one paused turn: state (`waiting_for_human` / `resuming` / `resolved` / `unresumable`), outcome, validity window, claim fields (`claimed_by_instance_id`, `claim_expires_at`), unique idempotency key, applied markers, terminal reason code, single outcome turn |
| `ConversationTurnCheckpoint` | 1:1 opaque LangGraph payload with schema version, byte size and consumption flag; never interpreted by CC, size-capped, purged after resolution/retention |
| `ConversationTurnResumeStore` | Single writer of resume transitions: create-or-reuse (supersedes any other live record), claim arbitration (the holder may renew its own live lease; another instance gets `already_held`), release, resuming, resolve, resolve-unresumable. Illegal transitions raise |
| `ConversationTurnCheckpointStore` | Payload upsert / load / consume / purge |
| `turn_resolution` | Answer path: advances the resume record in the same transaction as the stored answer, expires the linked pending intervention when a record goes unresumable, dispatches exactly once, and executes an approved live test before dispatching the resume |
| `InternalSessionDataRouter` | Internal data plane used by Communications Hub: activity read/write/touch, resume read/write, checkpoint read/write, claim/release and the single-transaction `complete` closer |

### Frontend

| Component | Description |
|-----------|-------------|
| `ConversationSessionsTab` | Sessions list with start/resume/end/archive actions and resume-state badges projected from the API |
| `ConversationDialog` | Conversation surface: status chip/bubble lifecycle, inline interventions, terminal cards, recovery vocabulary (waiting / resumed / resolved / no longer resumable) and input re-enable on terminal states |
| `ResumeTerminalCard` | Reason-keyed terminal card (expired / resumed elsewhere / checkpoint lost / unexpectedly terminated) with next step and dismiss; "Ask again" re-sends the last user request |
| `useChatSession` | WebSocket lifecycle and status model: parses `chat_status`, `activity_state` hydration, `intervene_request`/`live_test` payloads and structured `chat_error`; exposes `chatStatus`, `resumeState`, `activeResumeId`, `terminalReason`, `pendingIntervention`, `liveTestResults` |
| `useConversationSessions` / `useConversationSessionsPage` | Sessions listing queries (legacy and paginated) |
| `useConversationIntervention` | REST intervention fetch/respond/cancel used to re-surface a pending decision on reconnect |

---

## API Endpoints

### Sessions and turns

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/conversations` | List sessions (filterable by agent type, user, status, date), ordered `updated_at DESC` |
| `GET` | `/api/v1/conversations/sessions` | Paginated, tenant-scoped listing: `status` (`active` / `ended` / `all`), explicit or default date window, `page` / `page_size`; response envelope carries `total`, paging and `default_window_days`. Adds the resume projection (`resume_state`, `resume_outcome`, `resume_expires_at`) per item |
| `GET` | `/api/v1/conversations/{session_id}` | Session detail with all turns and embedded tool call records |
| `POST` | `/api/v1/conversations` | Create a business conversation session (requires `input_type == conversation`) |
| `POST` | `/api/v1/conversations/{session_id}/resume` | Full session context (metadata + turns) with ownership validation |
| `POST` | `/api/v1/conversations/{session_id}/end` | Close the session; best-effort terminate any in-flight execution |
| `POST` | `/api/v1/conversations/{session_id}/archive` | Archive the session |
| `GET` | `/api/v1/conversations/{session_id}/interventions/pending` | Pending intervention requests (re-surfaced on reconnect); optimization-aware for live-test approvals |
| `POST` | `/api/v1/conversations/{session_id}/interventions/{request_id}/respond` | Submit an intervention answer; advances the resume record transactionally and dispatches once. A second answer returns the stored outcome |

### Optimization channel

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/conversations/optimization` | Open an optimization conversation on a subject agent type (`{agent_type_id}` only). `404` unknown subject, `403` without `agent::read`. Typed and conversational subjects accepted; one session row is written and availability is computed, never stored |
| `GET` | `/api/v1/conversations/{session_id}/optimization` | Subject + availability + replay-vs-live audit for an optimization conversation (`422 not_optimization_conversation` for other channels) |
| `GET` | `/api/v1/conversations/{session_id}/live-test-requests` | The session's live-test ledger, newest first (status, script version, derived tool-call preview, script run record, timings, decision attribution) |

### Internal data plane (Control Center, service certificate + signed tenant context)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/internal/data/conversations/{id}/prepare-turn` | Persist the user turn; set activity `thinking` with the turn as `current_turn_id`; refuses a new message while a decision is pending; reports the optimization guidance block |
| `POST` | `/internal/data/conversations/{id}/append-turn` | Persist the agent turn; resolve activity to terminal |
| `PUT` / `GET` | `/internal/data/conversations/{id}/activity` | Upsert / read current activity (read returns explicit null when idle); the write refuses `waiting_for_human` without a live resume record |
| `POST` | `/internal/data/conversations/{id}/activity/touch` | Refresh a live working row's `last_updated_at` from the hub heartbeat (no state change; no-op for paused/terminal rows) |
| `PUT` / `GET` | `/internal/data/conversations/{id}/resume` | Create-or-reuse / read the live resume record |
| `PUT` / `GET` | `/internal/data/conversations/{id}/resume/checkpoint` | Upsert / load the opaque checkpoint payload |
| `POST` | `/internal/data/conversations/{id}/resume/claim` | Acquire/renew the turn claim (`acquired` / `already_held` / `terminal` / `not_found`) |
| `POST` | `/internal/data/conversations/{id}/resume/release` | Release the claim (best effort) |
| `POST` | `/internal/data/conversations/{id}/resume/complete` | Single-transaction closer: append the outcome turn once, set terminal state/outcome, consume the checkpoint, resolve activity |
| `POST` | `/internal/data/intervene/respond` | Hub-facing intervention answer; advances the resume record and threads the verified tenant context into the resume dispatch |

Public intervention responses also exist at `POST /api/v1/intervene/requests/{request_id}/respond` (job-session path and the conversation-scoped branch).

---

## State Management

Backend state is authoritative in Control Center: `conversation_activity` is the single source of truth for "what is happening", and the resume index is the single source of truth for "can this paused turn be answered". Communication Hub's `ActiveSessionTracker` remains only for live-socket routing and intervention routing; `_pending_turn_tasks` remains only for cancellation.

Frontend state stays inside `useChatSession`. `ChatStatus` carries `kind`, `detail`, server `message`, `resumeState`, `activeResumeId` and `terminalReason`; terminal detection is unchanged. Hydration on connect (`activity_state`) preserves the server message and resume fields so a reconnect renders the same outcome as the live socket. The waiting indicator is gated on a live resume id — "waiting for your input" is never shown for activity that has no answerable turn. Because the resume runs out of band, the dialog treats post-pause `thinking`/`using_tool` as "resumed and continuing" and any terminal status as the end.

---

## Data Access Patterns

- **Control Center is the only DB accessor.** Sessions, turns, tool calls, activity and resume/checkpoint rows are all CC-owned; every read/write happens in a CC request handler or the reaper's own session.
- **Agent Runtime is a courier.** It emits activity transitions only inside the NDJSON response stream to CH; checkpoint/resume state is read and written exclusively through `CheckpointTransportClient` → CH → CC. No SQLAlchemy import, connection string or credential in AR. (Structural test: `backend/tests/agent_runtime/test_ar_activity_persistence_boundaries.py`.)
- **Communication Hub is transport.** It relays with the signed tenant header set it verified, never mints headers, never persists and never inspects payload content beyond the size guard. It calls CC through `internal_httpx_client`.
- **Activity write path** — AR transition → CH → `PUT …/activity` (or `touch` on each ~15s heartbeat) → CC upsert → live socket push. `human_intervene` persists `waiting_for_human` with the pending intervention id; `prepare-turn` sets `thinking`; `append-turn` resolves terminal; the reaper resolves dead rows.
- **Resume write path** — the pause writes resume state + checkpoint through AR → CH → CC; the operator's answer advances the record and dispatches once; AR claims the turn, loads the checkpoint and continues; `complete` appends the single outcome turn. Claim arbitration is a conditional update; expiry only frees the turn for failover and never changes lifecycle state.
- **Exactly-once** — the management-tool write and its applied marker commit together, keyed by the resume record's unique idempotency key; the outcome turn and terminal transition likewise commit together, guarded by `outcome_turn_id`. Duplicate answers return the stored outcome.
- **Payload hygiene** — payloads are size-capped, versioned, consumed once and purged after resolution or retention; the index row survives purge so audit and outcome remain intact. No payload body is loaded for status rendering.
- **Tenant scoping** — enforced by the signed internal tenant context at CC; the resume record carries `tenant_id`; a resumed turn can never cross tenants.
- **Optimization channel** — creation writes exactly one session row; availability and the optimizer model are derived at read time and never persisted on the session.

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ConversationSession` | model | Session model (`title`, `triggered_by_user_id`, `agent_job_id`, `channel`, `updated_at`, resume back-reference) | `backend/app/db/models/conversations.py` |
| `ConversationStatus` | enum | `active`, `closed`, `archived`, `error` | `backend/app/db/models/conversations.py` |
| `TurnType` | enum | `message`, `intervene_request`, `intervene_response` | `backend/app/db/models/conversations.py` |
| `ConversationTurn` | model | Single message in a session; `turn_type`, `intervene_request_id` (also referenced as the paused/outcome turn) | `backend/app/db/models/conversations.py` |
| `ToolCallRecord` | model | Per-turn tool invocation record | `backend/app/db/models/conversations.py` |
| `ConversationActivity` | model | Persisted per-session activity row (one live row per session; gains `active_resume_id`) | `backend/app/db/models/conversation_activity.py` |
| `ActivityState` | enum | Seven-state activity vocabulary with three terminal states | `backend/app/db/models/conversation_activity.py` |
| `TERMINAL_ACTIVITY_STATES` | constant | Terminal state set used by the store and reaper | `backend/app/db/models/conversation_activity.py` |
| `ConversationTurnResume` | model | Authoritative resume index for one paused conversational turn | `backend/app/db/models/conversation_turn_resume.py` |
| `ConversationTurnCheckpoint` | model | Opaque, versioned paused-turn payload (1:1 with the resume record) | `backend/app/db/models/conversation_turn_resume.py` |
| `ResumeState` | enum | `waiting_for_human`, `resuming`, `resolved`, `unresumable` | `backend/app/db/models/conversation_turn_resume.py` |
| `ResumeOutcome` | enum | `approved_applied`, `denied`, `cancelled`, `expired`, `superseded`, `resume_failed` | `backend/app/db/models/conversation_turn_resume.py` |
| `CheckpointPayloadKind` | enum | `agent_turn_state`, `conversation_state` | `backend/app/db/models/conversation_turn_resume.py` |
| `InterveneRequest` / `InterveneRequestStatus` | model / enum | Pending confirmation referenced by activity; owns the validity window (`pending` / `responded` / `cancelled` / `expired`) | `backend/app/db/models/intervene.py` |
| `ConversationActivityStore` | service | Atomic upsert / read / heartbeat touch / terminal resolve of the activity row | `backend/app/services/conversations/activity_store.py` |
| `ConversationActivityReaper` | service | Background sweep + Terminal Resolver (stale working rows, orphaned pauses, dead confirmations) | `backend/app/services/conversations/activity_reaper.py` |
| `get_activity_reaper` | function | Process-wide reaper singleton accessor | `backend/app/services/conversations/activity_reaper.py` |
| `ConversationActivityReaper._resolve_waiting_for_human` | method | Resume-record-aware decision for a paused row | `backend/app/services/conversations/activity_reaper.py` |
| `ConversationTurnResumeStore` | service | Single writer of resume lifecycle: create/supersede, claim, release, resolve | `backend/app/services/conversations/turn_resume_store.py` |
| `ConversationTurnCheckpointStore` | service | Checkpoint upsert / load / consume / purge with byte cap | `backend/app/services/conversations/turn_checkpoint_store.py` |
| `turn_resolution` | module | Answer path: advance-answer transaction, dispatch-once, unresumable handling, approved live-test execution, outcome delivery | `backend/app/services/conversations/turn_resolution.py` |
| `dispatch_answered_conversation_turn` | function | Conversation-scoped resume dispatch (tenant context threaded explicitly) | `backend/app/services/conversations/turn_resolution.py` |
| `expire_linked_intervention` | function | Expires a still-pending confirmation when its resume record goes unresumable | `backend/app/services/conversations/turn_resolution.py` |
| `execute_approved_live_test` | function | Runs the approved script once before dispatching the resume | `backend/app/services/conversations/turn_resolution.py` |
| `ConversationStore` | service | Conversation persistence; `update_title`, `archive_session`, `list_sessions`, `list_sessions_page`, `add_turn(turn_type, intervene_request_id)` | `backend/app/services/conversations/store.py` |
| `ConversationSessionManager` | service | Business session lifecycle (`create`) + optimization-channel creation (`create_optimization`) | `backend/app/services/conversations/manager.py` |
| `SessionAutoNamer` | service | LLM session title generation with truncated-message fallback | `backend/app/services/conversations/auto_namer.py` |
| `LiveTestExpirySweeper` / `sweep_expired_live_tests` | service | Startup + periodic sweep closing overdue live-test approvals and settling their pauses | `backend/app/services/conversations/live_test_expiry.py` |
| `terminate_in_flight_conversation_execution` | function | Best-effort in-flight execution termination on session end | `backend/app/services/conversations/termination.py` |
| `InterveneRequestStore` | service | Intervention create/respond/cancel persistence (pause path stamps the tenant resume TTL) | `backend/app/services/agents/intervene_service.py` |
| `ConversationSessionCreate` / `ConversationSessionRead` / `ConversationTurnRead` / `ConversationSessionDetailRead` | schemas | Session create/read contracts; `guardrail_usage`; resume projection on the session read | `backend/app/schemas/conversations.py` |
| `ConversationSessionPageRead` | schema | Paginated listing envelope (`items`, `total`, `page`, `page_size`, `default_window_days`) | `backend/app/schemas/conversations.py` |
| `ConversationRouter` | router | Conversation REST surface (sessions, interventions, optimization channel) | `backend/app/api/v1/conversations.py` |
| `list_conversation_sessions_paged` | endpoint | `GET /conversations/sessions` with resume projection | `backend/app/api/v1/conversations.py` |
| `create_optimization_conversation` | endpoint | `POST /conversations/optimization` | `backend/app/api/v1/conversations.py` |
| `get_optimization_conversation` | endpoint | `GET /conversations/{id}/optimization` (subject + availability + audit) | `backend/app/api/v1/conversations.py` |
| `list_live_test_requests` | endpoint | `GET /conversations/{id}/live-test-requests` | `backend/app/api/v1/conversations.py` |
| `terminate_in_flight_conversation_execution` (route) | endpoint behaviour | `POST /conversations/{id}/end` best-effort termination | `backend/app/api/v1/conversations.py` |
| `InternalSessionDataRouter` | router | Internal data-plane router hosting activity/resume/checkpoint endpoints | `backend/app/api/v1/internal/session_data.py` |
| `prepare_conversation_turn` | endpoint | Persist user turn; set activity `thinking`; decision-pending refusal | `backend/app/api/v1/internal/session_data.py` |
| `append_conversation_turn` | endpoint | Persist agent turn; resolve activity terminal | `backend/app/api/v1/internal/session_data.py` |
| `upsert_conversation_activity` / `get_conversation_activity` | endpoints | Activity write / hydration read | `backend/app/api/v1/internal/session_data.py` |
| `touch_conversation_activity` | endpoint | Activity heartbeat refresh | `backend/app/api/v1/internal/session_data.py` |
| `ConversationActivityUpsertRequest` / `ConversationActivityResponse` / `_activity_response` | schemas / function | Activity write body and read model (includes `active_resume_id`, terminal reason/message) | `backend/app/api/v1/internal/session_data.py` |
| `save_conversation_turn_resume` / `get_conversation_turn_resume` | endpoints | Resume record write/read | `backend/app/api/v1/internal/session_data.py` |
| `save_conversation_turn_checkpoint` / `get_conversation_turn_checkpoint` | endpoints | Checkpoint payload write/read | `backend/app/api/v1/internal/session_data.py` |
| `claim_conversation_turn_resume` / `release_conversation_turn_resume` | endpoints | Turn claim acquire/renew/release | `backend/app/api/v1/internal/session_data.py` |
| `complete_conversation_turn_resume` | endpoint | Single-transaction outcome closer | `backend/app/api/v1/internal/session_data.py` |
| `internal_intervene_respond` | endpoint | Hub-facing answer path (threads verified tenant context) | `backend/app/api/v1/internal/session_data.py` |
| `RuntimeToolCallRecord.optimization_live_test_request_id` | ingest field | Ledger pointer stamped on live-test tool calls | `backend/app/api/v1/internal/session_data.py` |
| `human_intervene_tool` | endpoint | Persists the intervention and the `waiting_for_human` activity for a pause | `backend/app/api/v1/internal/system_tools.py` |
| `respond_to_intervene_request` | endpoint | Dialog-facing answer; transactional resume advance | `backend/app/api/v1/intervene.py` |
| `_resume_agent_session` | function | Dispatches one resume through CH | `backend/app/api/v1/intervene.py` |
| `_deliver_interruption_notice` / `_INTERRUPTION_NOTICE` | function / constant | Legacy single terminal notice (superseded by reason-keyed outcomes) | `backend/app/api/v1/conversations.py` |
| `require_service_certificate` / `_CH_ALLOWLIST` | dependency / constant | Internal guards; allowlist includes activity, resume and checkpoint routes | `backend/app/api/deps.py` |
| `AgentRuntimeClient.resume_session` | method | CC → CH resume dispatch | `backend/app/services/control_center/agent_runtime_client.py` |
| `ControlCenterDataClient` (CH) | class | CH → CC internal-data client for turns, activity, resume and checkpoints | `backend/app/communication_hub/data_client.py` |
| `ControlCenterDataClient.touch_conversation_activity` | method | Heartbeat touch relay | `backend/app/communication_hub/data_client.py` |
| `ControlCenterDataClient.save_conversation_turn_resume` / `save_conversation_turn_checkpoint` / `claim_conversation_turn_resume` / `complete_conversation_turn_resume` | methods | Resume/checkpoint/claim/complete relays | `backend/app/communication_hub/data_client.py` |
| `_activity_state_message` | function | Connect-hydration payload builder (activity + resume fields + message) | `backend/app/api/ws/chat.py` |
| `_persist_activity_transition` | function | Persists a status transition to CC | `backend/app/api/ws/chat.py` |
| `ConversationDialog` | component | Chat dialog: status bubble, inline interventions, terminal card, recovery vocabulary | `frontend/src/components/agents/ConversationDialog.tsx` |
| `ConversationSessionsTab` | component | Sessions list with resume-state badges | `frontend/src/components/agents/ConversationSessionsTab.tsx` |
| `SessionSwitcherList` | component block | Sessions-tab UI: ended switch, date window, pagination, ended chip, resume for active only | `frontend/src/components/agents/ConversationDialog.tsx` |
| `ResumeTerminalCard` | component | Reason-keyed terminal card with "Ask again" and dismiss | `frontend/src/components/conversations/ResumeTerminalCard.tsx` |
| `InterventionPendingIndicator` | component | "Waiting for your input" indicator | `frontend/src/components/conversations/InterventionPendingIndicator.tsx` |
| `InlineInterventionDialog` | component | Inline approval/choice/text dialog (markdown preview via `ContentRenderer`) | `frontend/src/components/conversations/InlineInterventionDialog.tsx` |
| `useChatSession` | hook | WS lifecycle, status/activity parsing, resume vocabulary, intervention and live-test state | `frontend/src/hooks/useChatSession.ts` |
| `ChatStatus` / `ChatStatusKind` / `TERMINAL_CHAT_STATUS_KINDS` / `isTerminalChatStatusKind` | types / constant / function | Normalized status model, kind union and terminal detection | `frontend/src/hooks/useChatSession.ts` |
| `parseActivityState` / `activityStateFromPayload` / `parseChatStatus` | functions | Activity hydration and live status parsing | `frontend/src/hooks/useChatSession.ts` |
| `markTurnInFlight` / `isTurnInFlight` | functions | In-flight window open/close | `frontend/src/hooks/useChatSession.ts` |
| `useConversationSessions` / `useConversationSessionsPage` | hooks | Legacy and paginated sessions queries | `frontend/src/hooks/useConversationSessions.ts` |
| `useConversationIntervention` | hook | REST intervention fetch/respond/cancel | `frontend/src/hooks/useConversationIntervention.ts` |
| `ConversationSession` / `ConversationSessionDetail` / `ConversationTurn` / `TurnType` | types | Frontend session/turn types (incl. `channel`, `turn_count`, resume projection) | `frontend/src/types/index.ts` |
| `InterveneRequestMessage` / `InterveneResponseMessage` / `InterveneCancelMessage` / `InterveneStatusMessage` / `ChatBlockedMessage` / `InterventionWsMessage` | types | WebSocket intervention contract | `frontend/src/types/index.ts` |
| `conversations.sessions.*` / `chat.resume.*` / `intervention.*` | i18n namespaces | Session labels, live status copy, recovery and closed-intervention strings | `frontend/src/i18n/locales/en.json` |
| `test_conversation_turn_resume_store` | test module | Resume store lifecycle and claim contention | `backend/tests/unit/conversations/test_conversation_turn_resume_store.py` |
| `test_resume_terminal_resolver` | test module | Terminal Resolver branches (incl. dead-confirmation expiry) | `backend/tests/unit/conversations/test_resume_terminal_resolver.py` |
| `test_activity_touch_and_heartbeat` | test module | Heartbeat touch, stale bounds, dead working rows → failed | `backend/tests/unit/conversations/test_activity_touch_and_heartbeat.py` |
| `test_turn_checkpoint_endpoints` | test module | Internal endpoints, allowlist, cross-tenant denial | `backend/tests/unit/test_turn_checkpoint_endpoints.py` |
| `test_conversation_pause_resume_flow` | integration test | Pause → answer → resume end-to-end | `backend/tests/integration/test_conversation_pause_resume_flow.py` |
| `ConversationDialog.resumeRecovery.test.tsx` | test file | Four-state rendering, terminal card, Ask again, input re-enable | `frontend/src/__tests__/ConversationDialog.resumeRecovery.test.tsx` |
