# Tech Spec: Resumable Agent Turn Persistence

## Technical Overview

A paused conversational turn stops being process-local state. Control Center (CC) becomes the owner of two new records: an authoritative **resume index** (`ConversationTurnResume`) and an opaque **checkpoint payload** (`ConversationTurnCheckpoint`), with `ConversationActivity.active_resume_id` making "shown as waiting" structurally equal to "actually answerable". Agent Runtime (AR) keeps executing agents but swaps its per-turn `MemorySaver` for a durable checkpointer that persists LangGraph state to CC through Communication Hub (CH) and never holds a datastore connection. The conversational `human_intervene` tool goes back to LangGraph `interrupt()`/`Command(resume=…)` semantics, so a pause returns immediately and a later resume rebuilds the graph from the durable payload on *any* AR instance.

Resume is initiated by the operator's answer: CC records the response and dispatches once, CH forwards it to the configured AR service endpoint and consumes the resumed turn's event stream, and AR arbitrates with a short-lived turn claim before continuing. The confirmed write is applied exactly once because the management-tool dispatch commits its applied marker in the same transaction as the write, keyed by the resume record's idempotency key. When a turn genuinely cannot continue, the existing activity reaper is extended into a Terminal Resolver that writes one reason-code-keyed terminal outcome, which the frontend renders instead of the legacy generic timeout message.

## Component Breakdown

### Control Center — resume index, payload store, terminal resolution

- **Schema** — `ConversationTurnResume` is the queryable lifecycle record (state, outcome, validity window, claim fields, idempotency key, applied markers, terminal reason, single outcome turn). `ConversationTurnCheckpoint` is the 1:1 opaque payload with a schema version, byte size, and consumption flag. `ConversationActivity` gains `active_resume_id`.
- **`ConversationTurnResumeStore`** — the only writer of resume lifecycle transitions. Owns create-or-reuse (supersede previous live record), claim arbitration (acquire when unclaimed or the lease expired), release, resuming transition, resolve (success/denial/cancel) and resolve-unresumable. Illegal transitions raise.
- **`ConversationTurnCheckpointStore`** — payload upsert/load/consume/purge. Never interprets payload content; enforces the configured byte cap.
- **`InternalSessionDataRouter`** — internal data-plane surface used by CH: resume read/write, checkpoint read/write, claim/release, complete (the single-transaction closer that appends the outcome turn and resolves activity).
- **`ConversationActivityStore`** — extended to carry `active_resume_id` and to clear it on terminal resolution.
- **`ConversationActivityReaper`** — extended into the Terminal Resolver: a waiting row consults its resume record (protected while valid, resolved when expired/superseded/cancelled/checkpoint-lost/claim-abandoned), writing record and activity together.
- **`respond_to_intervene_request` / `internal_intervene_respond`** — advance the resume record in the same transaction that stores the operator's answer, then dispatch exactly once.
- **`execute_management_tool`** — the confirmed-write chokepoint: honours the turn idempotency key, returns the stored effect summary on replay, and commits the applied marker with the write.
- **`list_conversation_sessions_paged`** — projects the live resume state for the sessions list badges.

### Agent Runtime — durable checkpointing and instance-independent resume

- **`DurableCheckpointSaver`** — LangGraph checkpointer implementation backed by the transport client; coalesces intermediate super-step writes to the latest checkpoint, provides an explicit flush, and maps load/deserialisation failures to a typed unavailable error.
- **`CheckpointTransportClient`** — AR's only path to pause state: save/load checkpoint, save resume index, claim, release, complete, all issued to CH through `internal_httpx_client` with the AR certificate. Courier only.
- **`AgentRuntimeExecutor`** — the conversational turn now builds the agent with the durable checkpointer, registers the resume index when a pause is detected, flushes before reporting waiting, and returns a pause result instead of awaiting a future.
- **`resume_conversation_turn`** — new AR endpoint: claim, load checkpoint, rebuild the agent, emit `thinking`, resume with the operator's value, stream status events and a final chunk (or a new `paused` chunk when the resumed turn pauses again).
- **`resume_session`** — legacy resume endpoint keeps the job path and delegates conversation-scoped resumes to the new handler; the in-process registry (`conversation_resume`) is retired from production paths.
- **`LangChainHumanInterveneTool`** — conversational path returns to `interrupt()` with an idempotent registration key so a replayed tool task reuses the pending request.

### Communication Hub — transport, relay, single dispatch

- **Checkpoint relay** — AR-facing save/load routes forwarding to CC inside the signed-tenant forwarding scope; transport only, no inspection beyond the size guard, no persistence, no signing.
- **`forward_resume_session`** — resume router: job path preserved; conversation-scoped resumes start a supervised background dispatch that streams the AR resume, forwards/persists status transitions, persists one outcome via CC, and pushes one reply to the live socket.
- **Dispatch de-duplication** — per-conversation in-flight guard plus stored-outcome short-circuit; combined with the AR claim this yields one resume and one outcome per answered intervention.
- **Terminal notification** — the terminal `chat_status` is emitted only for durably unresumable turns, carrying CC's reason code and message.
- **`_activity_state_message`** — hydration payload extended with `active_resume_id`, resume state, terminal reason, and message.

### Frontend — recovery messaging

- **`useChatSession`** — status model extended with resume state, active resume id, and terminal reason; activity hydration now preserves the server-provided message.
- **`ConversationDialog`** — renders waiting / resumed / resolved / no-longer-resumable vocabulary, the unresumable terminal card with next step and dismiss, and re-enables input on terminal states.
- **`ConversationSessionsTab`** — badges sessions from the API resume projection.

## API Changes

### Control Center internal data plane (service-certificate auth, CH-only allowlist)

| Route | Purpose |
|---|---|
| `PUT /api/v1/internal/data/conversations/{conv_session_id}/resume` | Create or reuse the live resume record for a pause; supersedes any other live record for the session |
| `GET /api/v1/internal/data/conversations/{conv_session_id}/resume` | Return the live resume record (explicit null when idle) |
| `PUT /api/v1/internal/data/conversations/{conv_session_id}/resume/checkpoint` | Upsert the opaque checkpoint payload for the live record |
| `GET /api/v1/internal/data/conversations/{conv_session_id}/resume/checkpoint` | Load the opaque checkpoint payload |
| `POST /api/v1/internal/data/conversations/{conv_session_id}/resume/claim` | Acquire/renew the turn claim; distinguishes acquired / already-held / terminal / not-found |
| `POST /api/v1/internal/data/conversations/{conv_session_id}/resume/release` | Release the claim best-effort |
| `POST /api/v1/internal/data/conversations/{conv_session_id}/resume/complete` | Single-transaction closer: append the outcome turn once, set terminal state/outcome, consume checkpoint, resolve activity to finished |
| `PUT /api/v1/internal/data/conversations/{conv_session_id}/activity` | Existing; now also carries `active_resume_id` and refuses waiting without a live resume record |
| `GET /api/v1/internal/data/conversations/{conv_session_id}/activity` | Existing; now also returns `active_resume_id` and terminal reason/message |
| `POST /api/v1/internal/data/conversations/{conv_session_id}/activity/touch` | Refreshes a live working row's `last_updated_at` (no state change) from the CH heartbeat; no-op for terminal/paused rows |

### Communication Hub internal routes

| Route | Purpose |
|---|---|
| `PUT /internal/checkpoint/{conv_session_id}` | AR-facing checkpoint save, relayed to CC |
| `GET /internal/checkpoint/{conv_session_id}` | AR-facing checkpoint load, relayed from CC |
| `POST /internal/agent/resume/{session_id}` | Existing route; conversation-scoped dispatches now instance-independent, de-duplicated, and outcome-persisting; returns a resume status enum instead of an orphan marker |

### Agent Runtime internal routes

| Route | Purpose |
|---|---|
| `POST /internal/conversation/resume` | Resume a paused conversational turn from its durable checkpoint: claim, load, `Command(resume=…)`, stream status events + final (or paused) |
| `POST /internal/resume` | Existing; conversation-scoped ids delegate to the conversational resume handler |
| `POST /internal/conversation/turn` | Unchanged contract; the stream can now terminate with a `paused` chunk instead of a reply |

### Control Center user-facing changes

| Route | Change |
|---|---|
| `GET /api/v1/conversations/sessions` | Adds resume projection (`resume_state`, `resume_outcome`, `resume_expires_at`) to each session read |
| `POST /api/v1/intervene/requests/{request_id}/respond` | Advances the resume record transactionally; duplicate answers return the stored outcome without re-dispatch |

### Management tool dispatch

`POST /api/v1/internal/management-tools/{tool_name}` accepts the turn idempotency key as a request header. When the key resolves to a resume record whose write is already applied, the stored effect summary is returned without executing the handler. Otherwise the handler result and the applied marker commit together.

## State Management

Frontend state stays inside `useChatSession`; no new store is introduced.

- `ChatStatus` gains `resumeState` (waiting / resuming / resolved / unresumable), `activeResumeId`, and `terminalReason`, keeping the existing kind union and terminal detection unchanged.
- Activity hydration must preserve `message`, the live resume id, and the terminal reason so a reconnect renders the same outcome as the live socket push.
- The waiting indicator is gated on the presence of a live resume id — the dialog must never show "waiting for your input" for activity that has no answerable turn.
- On a terminal state (`finished`, `failed`, `timed_out`, or the legacy `timeout_or_failed`), the dialog clears the activity bubble, renders the terminal message or card, and re-enables input.
- Because the resume happens out-of-band, the dialog treats a resume event like any other status stream: `thinking`/`using_tool` after a pause means "resumed and continuing"; a terminal status ends it.

## Data Access Patterns

- **CC is the only database accessor.** Both new entities are CC-owned; every read/write happens inside CC request handlers or the reaper's own session.
- **AR is a courier.** It reads and writes checkpoint/resume state exclusively through `CheckpointTransportClient` → CH → CC. No SQLAlchemy import, no connection string, no datastore endpoint, no credential in AR.
- **CH is transport.** It relays payloads with the signed tenant header set it verified, never mints headers, never persists, and never inspects payload content beyond the size guard.
- **Tenant scoping** is enforced by the signed internal tenant context at CC; the resume record carries `tenant_id` and a resumed turn can never cross tenants. The conversation session id remains the resume key.
- **Exactly-once** relies on a single transaction boundary in CC: the management-tool write and its applied marker commit together, keyed by the resume record's unique idempotency key; the outcome turn and the terminal lifecycle transition likewise commit together, guarded by `outcome_turn_id`.
- **Claim arbitration** is a conditional update in CC (`claimed_by_instance_id`, `claim_expires_at`); expiry only frees the turn for failover and never changes the lifecycle state.
- **Payload hygiene** — payloads are size-capped, versioned, consumed once, purged after resolution or the retention horizon; the index row survives purge so audit and outcome remain intact.
- **Read paths that must stay cheap** — the activity hydration read and the sessions listing use single joined lookups; no payload body is ever loaded for status rendering.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ConversationTurnResume` | model | Authoritative resume index for one paused conversational turn | `backend/app/db/models/conversation_turn_resume.py` |
| `ConversationTurnCheckpoint` | model | Opaque, versioned paused-turn payload (1:1 with the resume record) | `backend/app/db/models/conversation_turn_resume.py` |
| `ResumeState` | enum | `waiting_for_human \| resuming \| resolved \| unresumable` | `backend/app/db/models/conversation_turn_resume.py` |
| `ResumeOutcome` | enum | `approved_applied \| denied \| cancelled \| expired \| superseded \| resume_failed` | `backend/app/db/models/conversation_turn_resume.py` |
| `CheckpointPayloadKind` | enum | `agent_turn_state \| conversation_state` | `backend/app/db/models/conversation_turn_resume.py` |
| `ConversationActivity` | model | Persisted per-session activity record; gains `active_resume_id` | `backend/app/db/models/conversation_activity.py` |
| `ActivityState` | enum | Activity state vocabulary (`thinking`, `using_tool`, `delegating`, `waiting_for_human`, terminal states) | `backend/app/db/models/conversation_activity.py` |
| `TERMINAL_ACTIVITY_STATES` | constant | Terminal activity state set used by the store and reaper | `backend/app/db/models/conversation_activity.py` |
| `ConversationSession` | model | Conversation session; gains the resume back-reference | `backend/app/db/models/conversations.py` |
| `ConversationTurn` | model | Conversation turn row; referenced as paused turn and as outcome turn | `backend/app/db/models/conversations.py` |
| `InterveneRequest` | model | Pending confirmation; unchanged lifecycle, owns the validity window | `backend/app/db/models/intervene.py` |
| `InterveneRequestStatus` | enum | `pending \| responded \| cancelled \| expired` | `backend/app/db/models/intervene.py` |
| `ConversationTurnResumeStore` | service | Single writer of resume lifecycle: create/supersede, claim, release, resolve | `backend/app/services/conversations/turn_resume_store.py` |
| `ConversationTurnCheckpointStore` | service | Checkpoint payload upsert/load/consume/purge with byte cap | `backend/app/services/conversations/turn_checkpoint_store.py` |
| `ConversationActivityStore` | service | Activity upsert / terminal resolve; carries `active_resume_id` | `backend/app/services/conversations/activity_store.py` |
| `ConversationActivityReaper` | service | Background sweep extended into the Terminal Resolver | `backend/app/services/conversations/activity_reaper.py` |
| `get_activity_reaper` | function | Process-wide reaper singleton accessor | `backend/app/services/conversations/activity_reaper.py` |
| `ConversationActivityReaper._resolve_waiting_for_human` | method | Per-row paused-turn resolution decision, now resume-record aware | `backend/app/services/conversations/activity_reaper.py` |
| `ConversationStore.list_sessions_page` | method | Sessions listing query; gains the resume projection join | `backend/app/services/conversations/store.py` |
| `InterveneRequestStore` | service | Intervention create/respond/cancel persistence | `backend/app/services/agents/intervene_service.py` |
| `InternalSessionDataRouter` | router | CC internal data-plane router hosting the new resume endpoints | `backend/app/api/v1/internal/session_data.py` |
| `ConversationActivityUpsertRequest` | schema | Activity upsert body; gains `active_resume_id` | `backend/app/api/v1/internal/session_data.py` |
| `ConversationActivityResponse` | schema | Activity read model; gains `active_resume_id` and terminal reason/message | `backend/app/api/v1/internal/session_data.py` |
| `_activity_response` | function | Builds the activity read model | `backend/app/api/v1/internal/session_data.py` |
| `upsert_conversation_activity` | endpoint | `PUT /conversations/{id}/activity` | `backend/app/api/v1/internal/session_data.py` |
| `get_conversation_activity` | endpoint | `GET /conversations/{id}/activity` | `backend/app/api/v1/internal/session_data.py` |
| `save_conversation_turn_resume` | endpoint | `PUT /conversations/{id}/resume` | `backend/app/api/v1/internal/session_data.py` |
| `get_conversation_turn_resume` | endpoint | `GET /conversations/{id}/resume` | `backend/app/api/v1/internal/session_data.py` |
| `save_conversation_turn_checkpoint` | endpoint | `PUT /conversations/{id}/resume/checkpoint` | `backend/app/api/v1/internal/session_data.py` |
| `get_conversation_turn_checkpoint` | endpoint | `GET /conversations/{id}/resume/checkpoint` | `backend/app/api/v1/internal/session_data.py` |
| `claim_conversation_turn_resume` | endpoint | `POST /conversations/{id}/resume/claim` | `backend/app/api/v1/internal/session_data.py` |
| `release_conversation_turn_resume` | endpoint | `POST /conversations/{id}/resume/release` | `backend/app/api/v1/internal/session_data.py` |
| `complete_conversation_turn_resume` | endpoint | `POST /conversations/{id}/resume/complete` (outcome + state + activity, one transaction) | `backend/app/api/v1/internal/session_data.py` |
| `internal_intervene_respond` | endpoint | CH-facing intervention response; advances the resume record | `backend/app/api/v1/internal/session_data.py` |
| `human_intervene_tool` | endpoint | Persists the intervention and the waiting activity for a pause | `backend/app/api/v1/internal/system_tools.py` |
| `execute_management_tool` | endpoint | Confirmed-write chokepoint; honours the turn idempotency key | `backend/app/api/v1/internal/management_tools.py` |
| `_dispatch` | function | Routes a management tool to its resource handler | `backend/app/api/v1/internal/management_tools.py` |
| `respond_to_intervene_request` | endpoint | Dialog-facing intervention response; transactional resume advance | `backend/app/api/v1/intervene.py` |
| `_resume_agent_session` | function | Dispatches one resume via the CH resume route | `backend/app/api/v1/intervene.py` |
| `_deliver_interruption_notice` | function | Legacy single terminal notice; replaced by reason-keyed outcomes | `backend/app/api/v1/conversations.py` |
| `_INTERRUPTION_NOTICE` | constant | Legacy fixed notice text being replaced | `backend/app/api/v1/conversations.py` |
| `list_conversation_sessions_paged` | endpoint | Sessions listing; returns the resume projection | `backend/app/api/v1/conversations.py` |
| `ConversationSessionRead` | schema | Session read model; gains `resume_state`/`resume_outcome`/`resume_expires_at` | `backend/app/schemas/conversations.py` |
| `require_service_certificate` | dependency | mTLS + caller-allowlist guard for internal endpoints | `backend/app/api/deps.py` |
| `_CH_ALLOWLIST` | constant | CH allowlist; gains the new resume/checkpoint route templates | `backend/app/api/deps.py` |
| `AgentRuntimeClient.resume_session` | method | CC → CH resume dispatch | `backend/app/services/control_center/agent_runtime_client.py` |
| `AgentRuntimeExecutor` | class | AR executor; owns conversational turn execution | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor.execute_conversation_turn_from_context` | method | Conversational turn entry (suppression wrapper) | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._execute_conversation_turn_from_context_inner` | method | Builds the agent, swaps in the durable checkpointer, detects pauses | `backend/app/services/agents/runtime_executor.py` |
| `LangChainHumanInterveneTool` | class | `human_intervene` tool; conversational path uses `interrupt()` again | `backend/app/services/agents/langchain_system_tools.py` |
| `DurableCheckpointSaver` | class | LangGraph checkpointer backed by the CC-owned payload store | `backend/app/agent_runtime/durable_checkpointer.py` |
| `CheckpointTransportClient` | class | AR → CH courier for checkpoint/index/claim/complete calls | `backend/app/agent_runtime/checkpoint_transport.py` |
| `JsonPlusSerializer` | class (external) | LangGraph JSON+ checkpoint serialiser used for payload encoding | `langgraph.checkpoint.serde.jsonplus` |
| `MemorySaver` | class (external) | In-memory checkpointer being replaced for conversational turns | `langgraph.checkpoint.memory` |
| `interrupt` | function (external) | LangGraph pause primitive used by the conversational tool | `langgraph.types` |
| `Command` | class (external) | LangGraph resume command carrying the operator response | `langgraph.types` |
| `execute_conversation_turn` | endpoint | `POST /internal/conversation/turn`; stream can end with `paused` | `backend/app/agent_runtime/api/conversation.py` |
| `resume_conversation_turn` | endpoint | `POST /internal/conversation/resume` | `backend/app/agent_runtime/api/conversation.py` |
| `resume_session` | endpoint | `POST /internal/resume`; delegates conversation-scoped resumes | `backend/app/agent_runtime/api/intervene.py` |
| `ResumeRequest` | schema | Resume body (`session_id`, `response_value`) | `backend/app/agent_runtime/api/intervene.py` |
| `conversation_resume` | module | In-process resume registry being retired from production paths | `backend/app/agent_runtime/conversation_resume.py` |
| `wait_for_resume` | function | In-process future wait; no longer used for conversational turns | `backend/app/agent_runtime/conversation_resume.py` |
| `is_pending` | function | In-process registry lookup; no longer used for conversational turns | `backend/app/agent_runtime/conversation_resume.py` |
| `ControlCenterDataClient` (AR) | class | AR's CC data client (agent-context/model/session calls) | `backend/app/agent_runtime/data_client.py` |
| `CommHubToolClient` | class | AR's CH tool-call client | `backend/app/agent_runtime/comm_hub_client.py` |
| `CommHubToolClient.call_tool` | method | Tool-call egress; now carries the turn idempotency key | `backend/app/agent_runtime/comm_hub_client.py` |
| `CertificateManager` | class | AR certificate lifecycle manager | `backend/app/agent_runtime/certificate_manager.py` |
| `CertificateManager.instance_id` | property | AR instance identity used as `claimed_by_instance_id` | `backend/app/agent_runtime/certificate_manager.py` |
| `internal_httpx_client` | function | Single egress client that forwards signed tenant headers | `backend/app/core/internal_http.py` |
| `get_settings` | function | Settings accessor (new resume/claim/payload settings) | `backend/app/core/config.py` |
| `forward_resume_session` | endpoint | CH resume router (`POST /internal/agent/resume/{session_id}`) | `backend/app/communication_hub/api/internal/agent_resume.py` |
| `_dispatch_conversation_resume` | function | Supervised background resume dispatch (stream, persist, push once) | `backend/app/communication_hub/api/internal/agent_resume.py` |
| `_notify_orphaned_resume` | function | Terminal notification; now only for durably unresumable turns | `backend/app/communication_hub/api/internal/agent_resume.py` |
| `save_turn_checkpoint` | endpoint | AR-facing checkpoint save (`PUT /internal/checkpoint/{id}`) | `backend/app/communication_hub/api/internal/turn_checkpoint.py` |
| `load_turn_checkpoint` | endpoint | AR-facing checkpoint load (`GET /internal/checkpoint/{id}`) | `backend/app/communication_hub/api/internal/turn_checkpoint.py` |
| `ControlCenterDataClient` (CH) | class | CH's CC internal-data client | `backend/app/communication_hub/data_client.py` |
| `ControlCenterDataClient.save_conversation_turn_resume` | method | Relays resume upsert/read to CC | `backend/app/communication_hub/data_client.py` |
| `ControlCenterDataClient.save_conversation_turn_checkpoint` | method | Relays checkpoint save/load to CC | `backend/app/communication_hub/data_client.py` |
| `ControlCenterDataClient.claim_conversation_turn_resume` | method | Relays claim/release to CC | `backend/app/communication_hub/data_client.py` |
| `ControlCenterDataClient.complete_conversation_turn_resume` | method | Relays the single-transaction outcome closer to CC | `backend/app/communication_hub/data_client.py` |
| `ControlCenterDataClient.get_conversation_activity` | method | Hydrates the persisted activity (now with resume fields) | `backend/app/communication_hub/data_client.py` |
| `route_tool_call` | endpoint | CH tool-call route; forwards the turn idempotency key | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `run_conversation_turn` | function | CH-side turn supervision; handles a `paused` stream end | `backend/app/api/ws/chat.py` |
| `_delegate_conversation_turn_to_agent_runtime` | function | Streaming AR delegation; pattern reused by the resume dispatch | `backend/app/api/ws/chat.py` |
| `_persist_activity_transition` | function | Persists a status transition to CC | `backend/app/api/ws/chat.py` |
| `_activity_state_message` | function | Connect-hydration payload builder; gains resume fields | `backend/app/api/ws/chat.py` |
| `_build_chat_status_event` | function | Normalizes a wire status event; gains the optional message | `backend/app/api/ws/chat.py` |
| `_send_to_live_socket` | function | Delivers a message to the live socket (best-effort) | `backend/app/api/ws/chat.py` |
| `ActiveSessionTracker` | class | Live-session registry and pending-intervention flags | `backend/app/api/ws/chat.py` |
| `_handle_intervention_response` | function | WS intervention response → CC internal respond | `backend/app/api/ws/chat.py` |
| `useChatSession` | hook | Conversation state, status model, and hydration parsing | `frontend/src/hooks/useChatSession.ts` |
| `ChatStatus` | interface | Normalized status (kind, detail, message, resume state) | `frontend/src/hooks/useChatSession.ts` |
| `ChatStatusKind` | type | Status kind union (persisted states + legacy wire states) | `frontend/src/hooks/useChatSession.ts` |
| `TERMINAL_CHAT_STATUS_KINDS` | constant | Terminal status kinds | `frontend/src/hooks/useChatSession.ts` |
| `isTerminalChatStatusKind` | function | Terminal detection used by the dialog | `frontend/src/hooks/useChatSession.ts` |
| `parseActivityState` | function | Parses the connect-time `activity_state` push | `frontend/src/hooks/useChatSession.ts` |
| `activityStateFromPayload` | function | Maps persisted activity to `ChatStatus` (now keeps message/resume fields) | `frontend/src/hooks/useChatSession.ts` |
| `parseChatStatus` | function | Parses live `chat_status` messages | `frontend/src/hooks/useChatSession.ts` |
| `ConversationDialog` | component | Conversation UI: status chip/bubble, terminal card, input state | `frontend/src/components/agents/ConversationDialog.tsx` |
| `ConversationSessionsTab` | component | Sessions list with resume state badges | `frontend/src/components/agents/ConversationSessionsTab.tsx` |
| `useConversationSessions` | hook | Sessions listing query hook | `frontend/src/hooks/useConversationSessions.ts` |
| `ConversationSession` | interface | Frontend session type; gains the resume projection | `frontend/src/types/index.ts` |
| English locale bundle | resource | All user-facing recovery/status strings | `frontend/src/i18n/locales/en.json` |
| `test_conversation_turn_resume_store` | test module | Resume store lifecycle and claim contention | `backend/tests/unit/conversations/test_conversation_turn_resume_store.py` |
| `test_resume_terminal_resolver` | test module | Terminal Resolver branches and activity/resume agreement | `backend/tests/unit/conversations/test_resume_terminal_resolver.py` |
| `test_turn_checkpoint_endpoints` | test module | New CC internal endpoints, allowlist, and cross-tenant denial | `backend/tests/unit/test_turn_checkpoint_endpoints.py` |
| `test_durable_checkpointer` | test module | Saver round-trip, flush-before-waiting, unavailable-checkpoint error | `backend/tests/agent_runtime/test_durable_checkpointer.py` |
| `test_conversational_resume_from_checkpoint` | test module | Resume on a second instance, contention, re-pause | `backend/tests/agent_runtime/test_conversational_resume_from_checkpoint.py` |
| `test_resume_router_dedup` | test module | Single dispatch / single outcome under duplicate responses | `backend/tests/communication_hub/test_resume_router_dedup.py` |
| `test_resume_registry_miss_orphan` | test module | Existing orphan test rewritten to durable-state semantics | `backend/tests/agent_runtime/test_resume_registry_miss_orphan.py` |
| `ConversationDialog.resumeRecovery.test.tsx` | test file | Four-state rendering, terminal card, input re-enable | `frontend/src/__tests__/ConversationDialog.resumeRecovery.test.tsx` |
