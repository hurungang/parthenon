# Implementation Plan: resumable-agent-turn-persistence

## Overview

Make a paused conversational turn (the confirm-before-write `human_intervene` pause) durable by moving pause state out of Agent Runtime memory into a Control Center–owned resume index plus an opaque checkpoint payload, and by replacing the in-process resume registry with LangGraph interrupt/resume against that durable checkpoint. Resume then becomes instance-independent (routed by Communication Hub, arbitrated by a turn claim), with exactly-once application of the confirmed write and one clear terminal outcome for genuinely unresumable turns. Work proceeds CC → AR → CH → frontend so every phase is testable on its own.

## Task Checklist

### Phase 1 — Schema and Migration

- [x] 1.1 — Add `ConversationTurnResume` + `ConversationTurnCheckpoint` models and their enums
- [x] 1.2 — Add `ConversationActivity.active_resume_id` and the resume/activity relationships
- [x] 1.3 — Register the new model module and autogenerate the Alembic migration
- [x] 1.4 — Apply the migration and verify enum, constraint, and downgrade correctness

### Phase 2 — Control Center Resume Store and Internal APIs

- [x] 2.1 — Implement `ConversationTurnResumeStore` (create, supersede, read live, claim, release, resolve)
- [x] 2.2 — Implement `ConversationTurnCheckpointStore` (upsert, load, consume, purge)
- [x] 2.3 — Expose internal resume-index read/write endpoints
- [x] 2.4 — Expose internal checkpoint-payload and claim/release endpoints
- [x] 2.5 — Add the new internal endpoints to the CH allowlist with tenant and size guards
- [x] 2.6 — Wire `active_resume_id` through the activity store and activity API responses

### Phase 3 — Agent Runtime Durable Checkpointing and Resume

- [x] 3.1 — Implement `CheckpointTransportClient` (AR → CH relay, no datastore access)
- [x] 3.2 — Implement `DurableCheckpointSaver` on the LangGraph checkpointer interface
- [x] 3.3 — Replace the conversational `MemorySaver` with the durable checkpointer and flush the pause write
- [x] 3.4 — Re-enable `interrupt()` for the conversational `human_intervene` tool with idempotent registration
- [x] 3.5 — Add the AR conversational resume endpoint (claim, load checkpoint, `Command(resume=…)`, stream)
- [x] 3.6 — Retire the in-process conversational registry from the legacy `/internal/resume` path
- [x] 3.7 — Propagate the turn idempotency key on the confirmed-write tool call

### Phase 4 — Communication Hub Relay, Resume Routing and Dedup

- [x] 4.1 — Add the CH checkpoint relay router (AR-facing save/load, CC-facing forward)
- [x] 4.2 — Rewrite resume dispatch as instance-independent, streamed, and outcome-persisting
- [x] 4.3 — De-duplicate repeated operator responses per answered intervention
- [x] 4.4 — Replace orphaned-resume terminal semantics with durable-state semantics
- [x] 4.5 — Extend activity hydration with `active_resume_id`, terminal reason, and message

### Phase 5 — Control Center Terminal Resolution and Exactly-Once Outcome

- [x] 5.1 — Advance the resume record transactionally when an intervention is answered
- [x] 5.2 — Extend the activity reaper into the Terminal Resolver for paused turns
- [x] 5.3 — Deliver one actionable terminal outcome instead of the interruption notice
- [x] 5.4 — Consume and purge checkpoint payloads on resolution with a retention sweep
- [x] 5.5 — Project the live resume state into the conversation sessions listing

### Phase 6 — Frontend Recovery Messaging

- [x] 6.1 — Extend the chat status model and activity-state parsing
- [x] 6.2 — Render the waiting / resumed / resolved / unresumable vocabulary in the conversation dialog
- [x] 6.3 — Add the unresumable terminal card with next-step and dismiss actions
- [x] 6.4 — Add all new user-facing strings to the i18n bundles
- [x] 6.5 — Show resume state badges in the conversation sessions list

### Phase 7 — Automated Tests

- [x] 7.1 — Model and migration tests for the resume index, checkpoint, and activity link (`tests/db/test_conversation_turn_resume_migration.py`: model↔DB reconciliation, enum sets, unique/partial-unique constraints, FK ondelete, negative inserts, session-delete cascade, gated upgrade/downgrade)
- [x] 7.2 — Control Center store and internal endpoint tests (`tests/unit/conversations/test_*`, `tests/unit/test_turn_checkpoint_endpoints.py`, allowlist cross-check in `tests/test_internal_endpoint_allowlist_coverage.py`)
- [x] 7.3 — Agent Runtime checkpointer, pause, and resume-from-checkpoint tests (`tests/agent_runtime/test_durable_checkpointer.py`, `test_conversational_resume_from_checkpoint.py`, `test_checkpoint_transport.py`)
- [x] 7.4 — Communication Hub relay, routing, and dedup tests (`tests/communication_hub/test_resume_router_dispatch.py`, `test_turn_checkpoint_relay.py`, forward-only structural guard)
- [x] 7.5 — Terminal Resolver and exactly-once application tests (`tests/unit/conversations/test_resume_terminal_resolver.py`, `tests/unit/test_management_tool_idempotency.py`, `tests/integration/test_conversation_pause_resume_flow.py`, `tests/e2e/test_assistant_resume_after_restart_e2e.py`)
- [x] 7.6 — Frontend status, terminal-card, and sessions-badge tests (Vitest resume/activity/intervention/sessions suites; full suite `1944 passed / 0 failed / 18 skipped`)
- [x] 7.7 — Segregation boundary and regression suite update (AR/CH no-DB + no-signing guards, checkpoint payload credential scan, E2E mocked + real-backend variant, conversational/intervention/activity/watchdog regressions re-run)

### Phase 8 — Deployment and Operations

- [x] 8.1 — Add and document the new settings
- [x] 8.2 — Write deployment steps for the migration and service rollout order
- [x] 8.3 — Add observability signals and the operator runbook
- [ ] 8.4 — Verify the three-service boundary end to end

## Phase 1 — Schema and Migration

### 1.1 — Add `ConversationTurnResume` + `ConversationTurnCheckpoint` models and their enums

Create `backend/app/db/models/conversation_turn_resume.py` holding both entities exactly as specified in `data-model.md`: the resume index (`tenant_id`, `conversation_session_id`, `turn_id`, `intervene_request_id`, `state`, `resume_outcome`, `is_terminal`, `resume_key`, `idempotency_key`, `write_applied`, `applied_by_user_id`, `applied_at`, `applied_effect_summary`, `outcome_turn_id`, `claimed_by_instance_id`, `claim_expires_at`, `attempt_count`, `last_attempt_at`, `terminal_reason_code`, `terminal_message_key`, `expires_at`, `resolved_at`, timestamps) and the 1:1 checkpoint payload (`resume_id`, `payload_kind`, `schema_version`, `payload`, `payload_bytes`, `is_consumed`, `expires_at`). Add `ResumeState`, `ResumeOutcome`, and `CheckpointPayloadKind` enums, plus a partial-unique constraint guaranteeing at most one live resume record per conversation session and a unique constraint on `idempotency_key`.

**Done when** — the module imports cleanly, both entities appear in `Base.metadata`, and a unit test asserts the one-live-resume and unique-idempotency constraints are declared on the model.

### 1.2 — Add `ConversationActivity.active_resume_id` and the resume/activity relationships

Add the nullable `active_resume_id` FK (and relationship) to `ConversationActivity`, the back-reference from `ConversationSession` to its resume records, and the optional back-reference from `InterveneRequest` (join on `intervene_request_id` is acceptable if a relationship is unnecessary). No lifecycle enum changes: `InterveneRequest.status` keeps `pending → responded`, `cancelled`, `expired`.

**Done when** — models import without circular-reference errors, and `ConversationActivity.active_resume_id` is present alongside the existing `pending_intervene_request_id` without altering existing columns.

### 1.3 — Register the new model module and autogenerate the Alembic migration

Add the new module to `backend/app/db/models/__init__.py` so autogenerate sees it, then run `alembic revision --autogenerate`. Review the generated file for the correct `down_revision` (current head `7127b840ae80`, the conversation-activity migration), `postgresql.ENUM(..., create_type=False)` usage for the three new enums, the partial unique index, and a real `downgrade()` that drops tables before types.

**Done when** — the generated migration matches the model diff with no spurious table drops, and `python -m alembic heads` shows exactly one head.

### 1.4 — Apply the migration and verify enum, constraint, and downgrade correctness

Run `python -m alembic upgrade head` and confirm `python -m alembic current` reports the new revision. Verify the enum types, the partial unique index, and the `active_resume_id` FK exist, then run `downgrade -1` / `upgrade head` once locally to prove reversibility.

**Done when** — a fresh database reaches head without manual DDL, `\d conversation_turn_resumes` shows the index/constraints, and one downgrade/upgrade cycle succeeds.

## Phase 2 — Control Center Resume Store and Internal APIs

### 2.1 — Implement `ConversationTurnResumeStore` (create, supersede, read live, claim, release, resolve)

Create `backend/app/services/conversations/turn_resume_store.py` as the single writer of the resume index. Required operations: `create_or_reuse` (called from the intervention-persist path — reuse a pending record for the same intervention, otherwise supersede any other live record for the session as `superseded`), `get_live_for_session`, `get_by_resume_key`, `get_by_idempotency_key`, `claim` (atomic conditional update: acquire when unclaimed or `claim_expires_at < now()`, increment `attempt_count`, stamp `last_attempt_at`; return a distinct "held by other instance" signal), `release`, `mark_resuming`, `resolve` (writes state/outcome/`resolved_at`/`is_terminal` and, for `approved_applied`, requires `write_applied`), `resolve_unresumable` (state `unresumable` + `terminal_reason_code` + `terminal_message_key`). Every transition raises on an illegal state change.

**Done when** — unit tests cover supersede-on-new-pause, claim contention (second claimer refused while the first lease is live), claim re-acquire after lease expiry, and rejection of `approved_applied` without `write_applied`.

### 2.2 — Implement `ConversationTurnCheckpointStore` (upsert, load, consume, purge)

Create `backend/app/services/conversations/turn_checkpoint_store.py`: `upsert_payload` (reject payloads over the configured byte cap, stamp `payload_bytes`, keep `schema_version` from the caller), `load_payload`, `mark_consumed`, and `purge_expired`. The store never inspects payload contents — the payload is opaque.

**Done when** — tests prove an oversized payload is rejected, a second upsert replaces the payload in place (one row per resume), and `load_payload` returns `None` for a consumed or expired payload.

### 2.3 — Expose internal resume-index read/write endpoints

Add to `InternalSessionDataRouter` in `backend/app/api/v1/internal/session_data.py`: `PUT /conversations/{conv_session_id}/resume` (create/supersede from AR pause intents), `GET /conversations/{conv_session_id}/resume` (live record or explicit `null`), `POST /conversations/{conv_session_id}/resume/release`, and `POST /conversations/{conv_session_id}/resume/complete` (single-transaction closer: append the outcome turn when `outcome_turn_id` is null, set the terminal state/outcome, consume the checkpoint, resolve activity to `finished`). Response schemas expose `resume_id`, `resume_key`, `state`, `resume_outcome`, `expires_at`, `write_applied`, `terminal_reason_code`, `active_resume_id`, but never the checkpoint payload.

**Done when** — endpoint tests (service-cert auth) cover create → read → complete, duplicate `complete` calls returning the stored outcome without a second outcome turn, and unknown sessions returning 404.

### 2.4 — Expose internal checkpoint-payload and claim/release endpoints

Add `PUT /conversations/{conv_session_id}/resume/checkpoint`, `GET /conversations/{conv_session_id}/resume/checkpoint`, and `POST /conversations/{conv_session_id}/resume/claim` to the same router. Claim requests carry the calling instance id and requested lease seconds; responses distinguish `acquired`, `already_held` (with the holder and expiry), `not_found`, and `terminal` (turn already resolved/unresumable). Forward-only: no endpoint accepts a client-supplied tenant; the signed headers decide the tenant.

**Done when** — tests cover claim success, contention returning `already_held` without a state change, `terminal` for a resolved record, and checkpoint read/write round-tripping through the router with the payload byte-for-byte unchanged.

### 2.5 — Add the new internal endpoints to the CH allowlist with tenant and size guards

Register the five new route templates in `_CH_ALLOWLIST` in `backend/app/api/deps.py` (deliberately not in `_AR_ALLOWLIST` — AR reaches CC only through the CH relay). Add request-size validation for the checkpoint payload and reject a `conversation_session_id` whose tenant disagrees with the signed tenant context.

**Done when** — the existing internal-endpoint coverage test enumerates the new routes as allowlisted for CH and denies them for AR, and a cross-tenant checkpoint write returns 403/404 without persisting.

### 2.6 — Wire `active_resume_id` through the activity store and activity API responses

Extend `ConversationActivityStore.upsert` to accept `active_resume_id`, keep it on non-terminal transitions, clear it in `resolve_terminal`, and add it to `ConversationActivityResponse` via `_activity_response`. Enforce the invariant at write time: a `waiting_for_human` upsert with no resolvable live resume record is rejected or downgraded rather than persisted as waiting.

**Done when** — tests show `waiting_for_human` cannot be persisted without a live resume id, terminal resolution clears `active_resume_id`, and the activity GET response includes the field.

## Phase 3 — Agent Runtime Durable Checkpointing and Resume

### 3.1 — Implement `CheckpointTransportClient` (AR → CH relay, no datastore access)

Create `backend/app/agent_runtime/checkpoint_transport.py` with `save_checkpoint`, `load_checkpoint`, `save_resume_index`, `claim`, `release`, and `complete_resume`, all calling Communication Hub through `internal_httpx_client` with the AR certificate. No database client, no credentials, no new infrastructure dependency; failures raise a typed transport error so the executor can decide between retrying and letting the turn pause fail closed.

**Done when** — unit tests assert every call goes to a CH URL, tenant headers come from the shared egress hook, and no AR module imports a DB session or SQLAlchemy for this path.

### 3.2 — Implement `DurableCheckpointSaver` on the LangGraph checkpointer interface

Create `backend/app/agent_runtime/durable_checkpointer.py` implementing the LangGraph checkpoint-saver contract (`aget_tuple` / `aput` / `aput_writes` / `alist` / `adelete_thread`) against `CheckpointTransportClient`, serialising with LangGraph's JSON+ serializer and stamping a `schema_version`. Intermediate super-step writes coalesce to the latest checkpoint id (only `latest` is authoritative), while `flush()` guarantees the pause-point checkpoint reached CC before the turn reports `waiting_for_human`. A load failure raises a typed "checkpoint unavailable" error that the resume handler maps to `resume_failed`.

**Done when** — tests round-trip a serialized checkpoint through a fake transport, prove `flush()` blocks on the outstanding write, and prove a deserialization/schema mismatch raises the typed unavailable error.

### 3.3 — Replace the conversational `MemorySaver` with the durable checkpointer and flush the pause write

In `_execute_conversation_turn_from_context_inner`, replace `MemorySaver()` with a `DurableCheckpointSaver` bound to `thread_id = conv_session_id`, and register the resume index (opaque `resume_key`, `expires_at` mirroring the `InterveneRequest` window) once the pause is detected. Emit `waiting_for_human` only after the checkpoint flush and the index write both succeed; on either failure emit `timeout_or_failed` with an explicit "pause could not be persisted" reason instead of pretending to wait.

**Done when** — an executor test with a fake transport shows the checkpoint + index are written before the `waiting_for_human` event, and a transport failure produces a terminal failure event with no waiting state.

### 3.4 — Re-enable `interrupt()` for the conversational `human_intervene` tool with idempotent registration

In `LangChainHumanInterveneTool._arun`, remove the conversational branch that awaits `conversation_resume.wait_for_resume` and let the conversational path call LangGraph `interrupt()` like the task path. Make the registration step idempotent (a replayed tool task must reuse the existing pending request rather than create a second one) by passing the turn's idempotency key through the CommHub call and keeping the CC-side replay dedupe as the authority. The executor's `GraphInterrupt` / `__interrupt__` handling must return the pause result immediately rather than block on a future.

**Done when** — a test drives one conversational tool call to the interrupt, asserts exactly one `InterveneRequest` is created across a replayed task, and asserts the executor returns after the pause instead of awaiting an in-process future.

### 3.5 — Add the AR conversational resume endpoint (claim, load checkpoint, `Command(resume=…)`, stream)

Add `POST /internal/conversation/resume` to `backend/app/agent_runtime/api/conversation.py`. Flow: resolve the conversational resume record through the transport, acquire the claim (map contention to a distinct HTTP 409 payload), load and validate the checkpoint, rebuild the agent with the same durable checkpointer and config, emit `thinking`, invoke with `Command(resume=response_value)`, then stream status events and a final `final` chunk exactly like `execute_conversation_turn`. Re-pausing inside the resumed turn must re-persist the checkpoint and stream `paused` again. On claim expiry mid-run the handler must not double-apply: it completes under its lease or aborts with `resume_failed`.

**Done when** — tests cover happy-path resume on a second simulated instance, contention (`409`), missing checkpoint (`unresumable` + `resume_failed`), and a re-pause during resume.

### 3.6 — Retire the in-process conversational registry from the legacy `/internal/resume` path

Change `backend/app/agent_runtime/api/intervene.py` so a conversational resume no longer consults `conversation_resume.is_pending`; it delegates to the new conversational resume handler and returns its outcome status. Remove the `is_pending`/`wait_for_resume` implementation from the executor and the tool, keep `conversation_resume` importable as a deprecated no-op shim only if a regression test still imports it, and update the orphan-notice tests accordingly.

**Done when** — no production code path awaits an in-process future for a conversational turn, and the legacy resume endpoint returns `resumed | already_resolved | unresumable | not_awaiting` for conversation-scoped ids.

### 3.7 — Propagate the turn idempotency key on the confirmed-write tool call

Thread the turn's `idempotency_key` from the resume record through `CommHubToolClient.call_tool` into the CH tool route and on to CC as a request header, so the confirmed management-tool dispatch can commit its applied marker with the write itself. The key must be stable for the whole paused turn (not regenerated per attempt) and must never be derived from user input.

**Done when** — a test asserts the same key is sent on a retried/duplicated call and on a re-delivered resume, and that calls outside a paused turn send no key.

## Phase 4 — Communication Hub Relay, Resume Routing and Dedup

### 4.1 — Add the CH checkpoint relay router (AR-facing save/load, CC-facing forward)

Create `backend/app/communication_hub/api/internal/turn_checkpoint.py` with AR-facing `PUT /internal/checkpoint/{conv_session_id}` and `GET /internal/checkpoint/{conv_session_id}`, forwarding to the CC resume/checkpoint endpoints via `ControlCenterDataClient` inside `_signed_tenant_forwarding()`. CH performs transport only: no payload inspection beyond the size guard, no persistence, no signing.

**Done when** — tests show the payload is forwarded byte-for-byte, tenant headers are forwarded (never minted), and a CC 4xx/5xx is surfaced as a typed relay error rather than a silent empty payload.

### 4.2 — Rewrite resume dispatch as instance-independent, streamed, and outcome-persisting

Rework `forward_resume_session` in `backend/app/communication_hub/api/internal/agent_resume.py`: keep the job path, but for conversation-scoped ids spawn a background task that (a) calls the AR conversational resume endpoint in streaming mode, (b) forwards status events to the live socket and persists them through `_persist_activity_transition`, (c) on `final` persists the outcome via the CC `complete` endpoint and pushes the reply once via `_send_to_live_socket`, (d) on `paused` records the new pause without delivering a reply, and (e) returns promptly with a status instead of holding the request open for the whole turn. Target the configured AR service endpoint so a load-balanced deployment can serve the resume from any instance.

**Done when** — a test with a live fake socket proves one reply is delivered and one outcome persisted, a paused-during-resume reply is not delivered, and the HTTP call returns before the turn completes.

### 4.3 — De-duplicate repeated operator responses per answered intervention

Add a per-conversation dispatch guard in the resume router keyed on the resume record / intervention id: while a dispatch is in flight, a repeated response returns the in-flight or stored outcome (`already_resolved`) instead of starting a second resume; once resolved, it short-circuits to the stored outcome. Combine with the AR claim so a cross-instance duplicate cannot produce two completions.

**Done when** — tests deliver the same response twice concurrently and sequentially and observe exactly one AR resume call and exactly one persisted outcome turn.

### 4.4 — Replace orphaned-resume terminal semantics with durable-state semantics

Delete the "restart means orphaned" assumption: emit the terminal `chat_status` only when CC reports a durably unresumable turn, and carry the actionable message and reason code from CC rather than a hardcoded restart string. Keep best-effort delivery when no live socket exists (the hydrated activity carries the same terminal state on reconnect).

**Done when** — a restart-only scenario produces no terminal message, an expired/unresumable scenario produces exactly one message with its reason, and an offline client sees the same state on reconnect.

### 4.5 — Extend activity hydration with `active_resume_id`, terminal reason, and message

Extend `_activity_state_message` to include `active_resume_id`, `resume_state`, `terminal_reason_code`, and a rendered `message`; extend `_build_chat_status_event` to accept the optional message; and only set `pending_intervention` when the activity has a live resume id. Extend `ControlCenterDataClient.get_conversation_activity` typing accordingly.

**Done when** — a connect-time `activity_state` push for a paused turn includes the live resume id, and for a resolved turn includes the terminal message; the hydration test asserts both shapes.

## Phase 5 — Control Center Terminal Resolution and Exactly-Once Outcome

### 5.1 — Advance the resume record transactionally when an intervention is answered

In `respond_to_intervene_request` and `internal_intervene_respond`, create/advance the resume record in the same transaction that stores the operator's response: stamp `applied_by_user_id`, mark `resuming` and bump the attempt counter, and reject a response for a record that is already terminal by returning the stored outcome instead of re-dispatching. Then call `_resume_agent_session` with the resume identity so the dispatch is idempotent.

**Done when** — a duplicate response returns the stored outcome with no second dispatch, and a response against an expired window marks the record `unresumable/expired` with no dispatch.

### 5.2 — Extend the activity reaper into the Terminal Resolver for paused turns

Extend `ConversationActivityReaper._resolve_waiting_for_human` so a waiting row consults its resume record: protected while the record is `waiting_for_human`, unexpired, and the checkpoint exists; resolved to `timed_out` with `expired` when `expires_at` passed; `failed` with `resume_failed` when the record is `resuming` but abandoned past the claim/staleness bound or the checkpoint is missing/consumed; superseded/cancelled records resolve to a clear terminal state. Every resolution must write the resume record and the activity row together in the same sweep transaction.

**Done when** — resolver tests cover each branch (protected, expired, superseded, cancelled, lost checkpoint, stale resuming) and assert activity state, resume state/outcome, and `active_resume_id` agree after each sweep.

### 5.3 — Deliver one actionable terminal outcome instead of the interruption notice

Replace the fixed `_INTERRUPTION_NOTICE` path in `backend/app/api/v1/conversations.py` with a reason-keyed outcome: persist exactly one outcome turn (guarded by `outcome_turn_id`) whose text names what happened and the next step, and set the terminal activity state. Applies to both the dialog-driven respond path and the internal CH respond path. Never deliver this notice for a turn that was successfully resumed.

**Done when** — tests assert one outcome turn per unresumable turn after repeated responses, no notice on a successful resume, distinct texts for expired vs lost-pause-point, and `write_applied` false in every unresumable case.

### 5.4 — Consume and purge checkpoint payloads on resolution with a retention sweep

Mark the checkpoint consumed when a resume rebuilds the turn, and add a periodic purge (reusing the reaper loop) that deletes payloads past their purge horizon or belonging to terminal records. Ensure the resume index row survives purge so the audit/outcome story remains intact.

**Done when** — tests show a resolved turn's payload is purged on schedule while its index row and outcome turn remain, and a consumed payload cannot be loaded again.

### 5.5 — Project the live resume state into the conversation sessions listing

Add an optional resume projection (`resume_state`, `resume_outcome`, `resume_expires_at`) to `ConversationSessionRead` and populate it in `ConversationStore.list_sessions_page` with a single joined lookup (no N+1), so the sessions list can badge waiting/resumed/resolved/unresumable exactly as the prototype shows.

**Done when** — the sessions endpoint returns resume projection for paused/resolved sessions and `null` for idle ones, with one extra query at most for a full page.

## Phase 6 — Frontend Recovery Messaging

### 6.1 — Extend the chat status model and activity-state parsing

In `frontend/src/hooks/useChatSession.ts`, add `resumeState`, `activeResumeId`, and `terminalReason` to `ChatStatus`; make `activityStateFromPayload` (and therefore `parseActivityState`) carry `message`, `active_resume_id`, and the terminal reason instead of dropping them; keep `parseChatStatus` accepting the same optional fields on `chat_status`. Preserve existing terminal detection through `isTerminalChatStatusKind`.

**Done when** — unit tests parse an `activity_state` payload with a terminal message and a live resume id and assert both survive into `ChatStatus`.

### 6.2 — Render the waiting / resumed / resolved / unresumable vocabulary in the conversation dialog

Update `ConversationDialog` so the status chip and bubble render: waiting for your input (only when a live resume id is present), resumed — thinking / using tool, resolved, and no longer resumable. A resumed turn must look distinct from a fresh turn, and a stale `waiting_for_human` without a live resume id must never render as waiting.

**Done when** — component tests cover the four states, plus the degraded case where waiting activity arrives without a resume id.

### 6.3 — Add the unresumable terminal card with next-step and dismiss actions

Render the no-longer-resumable card in the message stream (reason-specific body, "nothing was written", next step, Ask again / Dismiss), matching the approved prototype, and ensure the input is re-enabled while the card is visible and after dismissal. A duplicate approval against a terminal turn must surface "nothing to replay" feedback and must never re-send the response.

**Done when** — tests assert the card body differs for expired vs lost pause point, the input is enabled, and clicking approve/deny on a terminal turn sends no request.

### 6.4 — Add all new user-facing strings to the i18n bundles

Add keys for the four state labels, the two terminal bodies, the next-step hint, the "nothing to replay" notice, and the sessions badges — using `t()` for every string and removing any reliance on the misleading `statusTimeoutOrFailed` copy for still-valid turns (keep the key for genuine legacy failures).

**Done when** — no new hardcoded UI strings exist, and the English bundle contains every key referenced by the updated components.

### 6.5 — Show resume state badges in the conversation sessions list

Extend the `ConversationSession` type with the resume projection and render the waiting / resumed / resolved / no-longer-resumable badges in `ConversationSessionsTab`, reusing the dialog's state vocabulary.

**Done when** — the sessions list renders the badge from the API projection (not from client-side heuristics), and a session with no resume record renders no badge.

## Phase 7 — Automated Tests

### 7.1 — Model and migration tests for the resume index, checkpoint, and activity link

Cover the partial unique index (second live record rejected), unique `idempotency_key`, cascade behaviour when the conversation session is deleted, and the applied-marker invariants at the schema level.

**Done when** — tests pass against a migrated database and fail if the constraints are removed.

### 7.2 — Control Center store and internal endpoint tests

Cover store transitions, claim contention and expiry, checkpoint size/round-trip, complete idempotency, allowlist enforcement, and cross-tenant rejection.

**Done when** — the suite runs with service-cert auth fixtures and covers every new endpoint's success and denial paths.

### 7.3 — Agent Runtime checkpointer, pause, and resume-from-checkpoint tests

Cover the saver round-trip, flush-before-waiting, transport failure handling, resume on a second simulated instance, claim contention, missing checkpoint, and re-pause during resume.

**Done when** — tests prove a paused turn resumes with only the persisted payload (fresh executor instance, no shared memory).

### 7.4 — Communication Hub relay, routing, and dedup tests

Cover byte-for-byte relay, forwarded (never minted) tenant headers, single reply/single outcome under duplicate responses, paused-during-resume behaviour, and durable-state-based terminal notification.

**Done when** — the existing orphan test is rewritten to the new semantics and passes alongside the new dedup tests.

### 7.5 — Terminal Resolver and exactly-once application tests

Cover every resolver branch and the exactly-once write path: duplicate tool dispatch with the same idempotency key applies once and returns the stored summary; a denial/expiry never sets `write_applied`; a crash-style retry after commit does not re-apply.

**Done when** — the suite proves at-most-one applied write and at-most-one outcome turn under repeated delivery.

### 7.6 — Frontend status, terminal-card, and sessions-badge tests

Cover hydration parsing, the four status states, the terminal card, input re-enablement, and sessions badges.

**Done when** — `npx vitest run` passes for the new and updated component tests.

### 7.7 — Segregation boundary and regression suite update

Add assertions that AR never gains DB access or new datastore endpoints, CH never signs headers and never persists, CC remains the only DB writer, and the checkpoint payload carries no credentials/tokens. Re-run the conversational, intervention, activity, and watchdog regressions.

**Done when** — boundary tests and the full backend/frontend regression suites pass with no skipped tests in the touched areas.

## Phase 8 — Deployment and Operations

### 8.1 — Add and document the new settings

Add `conversation_turn_resume_ttl_seconds` (answerable window, default 900), `conversation_turn_claim_ttl_seconds` (default 45), `conversation_turn_checkpoint_max_bytes` (default ~2 MB), and `conversation_turn_checkpoint_purge_after_seconds` (default 3600) to `backend/app/core/config.py`, wired from env with sane bounds.

**Done when** — settings resolve from env with documented defaults and unit tests cover the clamping behaviour.

### 8.2 — Write deployment steps for the migration and service rollout order

Produce `deployment.md` covering: apply the migration before starting new code, rollout order CC → AR → CH → frontend, the compatibility window (old AR + new CC must still work, since the in-process registry path is only removed with the AR release), and rollback steps that keep resume index data intact.

**Done when** — a fresh environment and an in-place upgrade both follow the documented order, and rollback leaves no orphaned payloads.

### 8.3 — Add observability signals and the operator runbook

Produce `operations.md` with metrics/log lines for pause persisted, resume dispatched, claim contention, resume failure, terminal resolutions by reason, and payload size/purge; plus an operator runbook for "approval after restart", "turn says no longer resumable", and "resume contention".

**Done when** — each signal is emitted by the code paths from Phases 2–5 and the runbook maps every terminal reason code to an operator action.

### 8.4 — Verify the three-service boundary end to end

Run a scripted end-to-end check: pause a turn, restart AR, approve, confirm the resumed reply and single applied write; repeat with CH restarted; confirm no service other than CC touched the database and the checkpoint contains no secrets.

**Done when** — the recorded verification (with logs) is attached under `tmp/` and referenced from the change docs.

## Completion Checklist

- [ ] All Phase 1–8 tasks are checked off.
- [ ] Migration applied locally (`alembic current` = new head) and reversible.
- [ ] No production code awaits an in-process future for a conversational turn.
- [ ] A paused turn resumes after restarting AR, CH, and CC independently.
- [ ] A paused turn resumes on a different AR instance than the one that paused it.
- [ ] Duplicate operator responses apply the confirmed write exactly once and record one outcome turn.
- [ ] Every unresumable path yields one clear, reason-specific terminal message and re-enabled input.
- [ ] No misleading "delegated step timed out or failed" message for a still-valid confirmation.
- [ ] AR holds no DB credentials/datastore access; CH neither signs headers nor persists; CC is the only DB writer.
- [ ] Checkpoint payload contains no identity tokens, credentials, or decrypted secrets.
- [ ] Resumed turns stay inside their conversation's tenant.
- [ ] All new user-facing strings go through `t()` and exist in the i18n bundles.
- [ ] Strong typing on both sides (Pydantic/enums on the backend, no `any` on the new frontend state).
- [ ] Backend and frontend regression suites pass with no new skips.
- [ ] `deployment.md` and `operations.md` written for this change.
- [ ] Master docs updated (architecture, data model, technology map, product/feature deltas, QA test plans).
