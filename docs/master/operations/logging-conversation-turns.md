# Logging — Conversation Turns and Resume

Conversational turn lifecycle, human-in-the-loop interventions, and the durable pause/resume vocabulary (activity projection, checkpoints, claims, resume dispatch, terminal resolution). Assistant management-plane events live in [logging-control-center-assistant.md](logging-control-center-assistant.md).

Hub: [logging.md](logging.md) · Operations index: [README.md](README.md)

## Conversation Turn Lifecycle

**Log sources**: `backend/logs/communication-hub.log` (socket, watchdog, heartbeat) and `backend/logs/agent-runtime.log` (agent loop, LLM timeout, guardrail stops)

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `WebSocket connected: session=… subject=…` | `chat.ws.connected` | INFO | `session_id`, `subject` | Authenticated conversation socket (also the point where the user JWT is cached for dual-identity tool calls) |
| `WebSocket rejected: invalid token for session …` | `chat.ws.rejected` (reason `invalid_token`) | WARN | `session_id` | Close `1008` — no valid OIDC or platform token |
| `WebSocket rejected: <reason> for session … (subject=…)` | `chat.ws.rejected` (reason `tenant_context`) | WARN | `session_id`, `subject`, `reason` | Close `4003` — tenant context could not be bound (fail-closed) |
| `WebSocket disconnected: session=… code=… reason=…` | `chat.ws.disconnected` | INFO | `session_id`, `code`, `reason` | Every socket close, including idle-proxy closes — correlate `code` with the disconnect alert |
| `Conversation turn watchdog fired for session … after …s` | `chat.turn.watchdog` (kind `timeout`) | WARN | `session_id`, `timeout_seconds` | Whole-turn bound (`agent_question_timeout_seconds`) fired before any reply |
| `Conversation turn persistence exceeded the watchdog for session …` | `chat.turn.watchdog` (kind `persistence_timeout`) | WARN | `session_id`, `timeout_seconds` | Reply already reached the user; only the CC persistence tail hung (no duplicate error emitted) |
| `Cancelled pending conversation turn for session … (session ended)` | `chat.turn.cancelled` | INFO | `session_id` | End-session termination canceled the in-flight CH turn |
| `Conversation turn blocked for session …: code=…` | `chat.turn.blocked` | WARN | `session_id`, `code` (`assistant_model_not_configured`, `iteration_limit`, `guardrail_<reason>`) | Structured turn error surfaced to the UI with typed guidance |
| `Background conversation turn failed for session …` | `chat.turn.failed` | ERROR | `session_id`, `error` (stack) | Unexpected exception in the turn pipeline |
| `WebSocket send failed for session … (socket=…)` | `chat.ws.send_failed` | WARN | `session_id`, `socket_state` | Dead socket during reply delivery; persistence is unaffected and the live-socket lookup retries on the next send |
| `Conversation turn … paused on human_intervene — waiting up to …s for operator response` | `chat.turn.waiting_for_human` | INFO | `conv_session_id`, `timeout_seconds` | Assistant called `human_intervene` (confirmation before a write) |
| `Conversation turn … still paused on human_intervene (…s) — extending wait` | `chat.turn.intervention_wait_extended` | INFO | `conv_session_id`, `elapsed_seconds` | LLM timeout re-armed while an intervention is legitimately pending |
| `Conversation turn timed out after …s (session=…, bound=…)` | `chat.turn.llm_timeout` | WARN | `conv_session_id`, `bound` | AR `conversation_llm_timeout_seconds` expired → `timeout_or_failed` |
| `Conversation guardrail stop (LangGraph[ , post-resume]): session=… reason=…` | `chat.turn.guardrail_stop` | WARN | `conv_session_id`, `reason` | Guardrail stop forwarded to CH; `iteration_limit` becomes the user-facing step-limit message |

The `thinking_heartbeat` status event is emitted every 15 s while a turn is in flight (keeps idle proxies open and the UI spinner alive); it is a WS status payload, not a log line — absence of heartbeats alongside a live socket is itself the signal.

With durable turn persistence, a pause no longer holds the turn in process memory: AR flushes the checkpoint and returns a `paused` result, and CH stops streaming. The pause rows above therefore describe the **legacy in-process fallback**; the authoritative pause/resume vocabulary is in [Conversation Activity and Resumable Turn Events](#conversation-activity-and-resumable-turn-events).

---

## Intervention Lifecycle (Confirmation / HITL)

**Log sources**: `backend/logs/agent-runtime.log` (graph pause/resume) and `backend/logs/control-center.log` (request state); OTEL spans `intervene.create_request`, `intervene.submit_response`, `intervene.cancel_request`

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `Created intervene request … for session … (type=…)` | `intervention.created` | INFO | `request_id`, `agent_session_id`, `intervention_type` | Assistant requested approval/choice/text before a mutating action |
| `Received intervention response for request … from session …` | `intervention.response_received` | INFO | `request_id`, `session_id` | WS `intervene_response` arrived |
| `Intervention response … persisted via CC` | `intervention.approved` / `intervention.denied` | INFO | `request_id` | Response persisted; approve/deny is carried in the response payload (`approval_value`) |
| `Resumed agent session … after human response to request …` | `intervention.session_resumed` | INFO | `request_id`, `session_id` | Non-conversational session resumed from `waiting_for_human` |
| `Conversation turn … resuming deep-agent loop after operator response (approval=…)` | `intervention.resumed` | INFO | `conv_session_id`, `approval_value` | Same conversational graph resumed via `Command(resume=…)` |
| `The confirmation request timed out without a response` (user-facing) + `timeout_or_failed` status | `intervention.timeout` | WARN | `conv_session_id`, `timeout_seconds` | No response within `conversation_intervention_timeout_seconds`; **the operation was not executed** |
| `Failed to persist intervention response …: …` | `intervention.persist_failed` | ERROR | `request_id`, `error` | CC submit failed; UI shows an intervention error and stays blocked |
| `Cancelled intervene request …` | `intervention.cancelled` | INFO | `request_id` | Operator or session-end canceled the pending request |

While an intervention is pending, further chat messages are rejected with a `chat_blocked` payload (`reason=intervention_pending`) rather than queued — a user reporting "the assistant stopped accepting messages" is usually an unanswered confirmation.

---

## Conversation Activity and Resumable Turn Events

**Log sources**: `backend/logs/control-center.log` (activity store, resume/checkpoint store, Terminal Resolver), `backend/logs/communication-hub.log` (socket projection, checkpoint relay, resume dispatch), `backend/logs/agent-runtime.log` (durable checkpointer, claim, resume).

The invariant these lines let you prove: **a turn shown as "waiting for your input" is answerable, and a turn that is not answerable is not shown as waiting.** Absence of an expected line is itself diagnostic, so every entry notes what a missing line means.

**Control Center — `backend/logs/control-center.log`**

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `Resume record … registered for conversation … (intervention=…)` | `resume.registered` | INFO | `resume_id`, `conv_session_id`, `intervene_request_id`, `expires_at` | A pause was recorded with its answerable window (tenant policy over platform default) |
| `Resume key … belongs to the previous pause of conversation … — allocating a fresh key for the new pause` | `resume.superseded` | INFO | `conv_session_id`, `previous_resume_key` | A newer pause supersedes the previous live record |
| `Checkpoint for resume … persisted (… bytes, schema v…)` | `checkpoint.written` | INFO | `resume_id`, `payload_bytes`, `schema_version` | AR's flushed payload was stored |
| `Purged … checkpoint payload(s) (consumed / expired / terminal)` | `checkpoint.purged` | INFO | `removed`, `age_seconds` | Retention sweep deleted payloads; the index row survives |
| `Activity reaper resolved … stale activity row(s) and purged … checkpoint payload(s)` | `reaper.swept` | INFO | `resolved`, `purged` | A sweep that did work (logged only when it resolved or purged something — silence on a healthy idle system is normal; use the `ConversationActivityReaper started (interval=…, stale=…)` startup line for liveness and a growing non-terminal row count as the stall signal) |
| `Terminal Resolver closed conversation … → … (reason=…)` | `resume.terminal_resolved` | INFO | `conv_session_id`, `state`, `reason_code`, `terminal_message_key` | A waiting row was resolved terminally (expired / superseded / cancelled / checkpoint lost / claim abandoned / unexpectedly terminated) |
| `Activity for conversation … re-pointed at live resume …` | `activity.repointed` | INFO | `conv_session_id`, `resume_id` | The activity row referenced a dead record while a newer live one existed |
| `Answered intervention … → resume … resuming (attempt=…)` | `resume.accepted` | INFO | `intervene_request_id`, `resume_id`, `attempt_count` | The answer was recorded and the activity moved out of waiting in the same transaction |
| `Answered intervention … outside its answerable window (resume …) — closing as unresumable/expired with no dispatch` | `resume.answer_expired` | INFO | `intervene_request_id`, `resume_id` | Answer arrived after `expires_at`; nothing was dispatched |
| `Answered intervention … targets terminal resume … (…) — returning the stored outcome` | `resume.duplicate_answer` | INFO | `intervene_request_id`, `resume_id`, `resume_outcome` | Repeat answer short-circuited to the stored outcome (safe, no second write) |
| `Resume … resolved: state=… outcome=… write_applied=…` / `Resume … marked … (reason=… message=…)` | `resume.resolved` | INFO | `resume_id`, `state`, `resume_outcome`, `write_applied`, `terminal_reason_code` | Lifecycle transition committed |
| `Resume … recorded the confirmed write (summary keys=…)` | `resume.write_applied` | INFO | `resume_id`, `applied_effect_summary` keys | The confirmed management write committed with its applied marker. **Two of these for one resume id is an exactly-once violation** |
| `Conversation activity reaper sweep failed; continuing.` | `reaper.error` | ERROR | `error` (stack) | A sweep raised; the loop continues but unresolved rows accumulate |

**Communication Hub — `backend/logs/communication-hub.log`**

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `Resume dispatch started for conversation … (resume_id=…) → …` | `resume.dispatch_started` | INFO | `conv_session_id`, `resume_id`, `target_instance` | Answer accepted; the single resume dispatch began |
| `Resume dispatch de-duplicated for conversation … (in flight, resume_id=…)` | `resume.dispatch_deduplicated` | INFO | `conv_session_id`, `resume_id` | Repeat answer absorbed by the in-flight guard |
| `Resume outcome short-circuited for conversation … (stored status=… reason=…)` | `resume.outcome_short_circuited` | INFO | `conv_session_id`, `resume_outcome` | The turn already had a stored outcome; nothing re-dispatched |
| `Resume for conversation …: no live resume record — nothing to dispatch (restart-only or already resolved)` | `resume.no_live_record` | INFO | `conv_session_id` | Resume requested with no durable record (legacy pause or already terminal) |
| `Resume already in flight elsewhere for conversation … (AR claim contention)` | `resume.claim_contention` | INFO | `conv_session_id` | Another AR instance holds the claim (HTTP 409 mapped, no double dispatch) |
| `Resumed turn paused again for conversation … (resume_id=…)` | `resume.repaused` | INFO | `conv_session_id`, `resume_id` | The resumed turn asked for a second confirmation |
| `Resumed turn closed for conversation … (outcome=… write_applied=…)` | `resume.closed` | INFO | `conv_session_id`, `resume_outcome`, `write_applied` | Outcome turn appended once and activity resolved |
| `Resume dispatch finished for conversation …: status=… reason=…` | `resume.dispatch_finished` | INFO | `conv_session_id`, `status`, `reason_code` | End of one dispatch attempt (success or terminal failure) |
| `Resume dispatch retrying for conversation … after a failed previous dispatch (…)` | `resume.dispatch_retried` | INFO | `conv_session_id` | A deduplicated answer arrived after a failed dispatch and was retried |
| `Resume dispatch failed for conversation …` / `Agent Runtime resume transport failed for conversation …: …` / `Agent Runtime unreachable for resume of conversation …: …` | `resume.dispatch_failed` | ERROR | `conv_session_id`, `error`, `target_instance` | Transport or routing failure — the answer was recorded, so re-answering is safe |
| `Turn resume relay upstream rejection: … → HTTP …` / `Turn resume relay failed: …` | `resume.relay_failed` | WARN | `method`, `path`, `upstream_status` | A checkpoint/resume relay call to CC failed. **HTTP 401 here is the signed-tenant-header or allowlist regression signature** |
| `Checkpoint relay rejected oversized payload for conversation …: … bytes > … byte guard` | `checkpoint.rejected_too_large` | WARN | `conv_session_id`, `payload_bytes`, `guard_bytes` | Payload exceeded `CONVERSATION_TURN_CHECKPOINT_MAX_BYTES` (CC and CH must agree) |
| `Activity upsert failed for conversation … (state=…): …` | `activity.forward_failed` | WARN | `conv_session_id`, `state`, `status` | A transition never reached CC; the persisted state lags the live one |
| `Activity hydration failed for conversation …: …` | `activity.hydrate_failed` | WARN | `conv_session_id`, `status` | Connect-time hydration failed → blank indicator until the next status event. Check allowlist, signed headers, migrations |
| `Activity heartbeat touch failed for conversation …: …` | `activity.touch_failed` | WARN | `conv_session_id` | The ~15 s liveness touch failed; if it stays down, the reaper will treat a live turn as dead after the staleness bound |
| `Unresumable turn for conversation … (reason=…): no live WebSocket client — terminal state persisted for the next hydration` | `resume.terminal_no_client` | INFO | `conv_session_id`, `reason_code`, `terminal_message_key` | Terminal outcome recorded while the user was offline |

**Agent Runtime — `backend/logs/agent-runtime.log`**

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `Durable checkpoint flushed for conversation … (checkpoint=…, … pending write(s))` | `checkpoint.flushed` | INFO | `conv_session_id`, `checkpoint_id`, `writes` | Flush before reporting a pause as waiting. **Missing before a `waiting_for_human` report means the pause is not durable** |
| `Background checkpoint autosave failed for conversation …: …` | `checkpoint.autosave_failed` | WARN | `conv_session_id`, `error` | Intermediate autosave failed; the authoritative flush retries at the pause point |
| `Conversation … pause could not be persisted — failing the turn closed: …` | `pause.persist_failed` | ERROR | `conv_session_id`, `error` | Flush or resume-index write refused; the turn ends `timeout_or_failed` (never a fake waiting state) |
| `Resume …: checkpoint load failed (…)` / `Resume …: no loadable checkpoint — marking unresumable` / `Resume …: checkpoint unusable (…)` | `resume.checkpoint_unavailable` | ERROR / WARN | `conv_session_id`, `reason` | The payload is gone, consumed, or unreadable → the record resolves `unresumable` |
| `Resume …: checkpoint carries no agent_type_id` / `unable to rebuild agent context (…)` | `resume.rebuild_failed` | ERROR | `conv_session_id`, `error` | Payload loaded but the agent could not be reconstructed |
| `Resume …: claim lost (…, holder=…) — aborting` / `claim lost mid-run — aborting without completing` | `resume.claim_lost` | WARN | `conv_session_id`, `holder`, `claim_expires_at` | Another instance took the lease; the turn is not completed twice |
| `Resume …: claim renewal failed (…) — lease will expire` | `resume.claim_renew_failed` | WARN | `conv_session_id`, `error` | Renewal failed; expiry will free the turn for failover |
| `Resume … failed: …` / `Resume … raised during the resumed turn` / `Resume …: could not record unresumable outcome (…)` | `resume.failed` | ERROR | `conv_session_id`, `error` | Resume aborted; the record is closed as `resume_failed` when reachable |

**Required fields**: `conv_session_id`, `resume_id` (where one exists), `claimed_by_instance_id`, `attempt_count`, `reason_code`, `payload_bytes`, `resume_outcome`.

**Sensitive-data exclusions**: never log the checkpoint payload body, never copy payload contents into `activity.detail`, and never log minted tenant headers (CH forwards, never signs) or any credential. Payloads carry conversation/agent state only.

**Grep hints**

- Turn resume end-to-end: `grep -n "resume\|Resume" control-center.log communication-hub.log agent-runtime.log` and follow one `conv_session_id` across the three files in order CC → CH → AR.
- Terminal resolution: `grep -n "Terminal Resolver closed\|resolved:|unresumable" control-center.log`.
- Activity reaping: `grep -n "Activity reaper\|stale activity row" control-center.log`.
- Activity projection faults: `grep -n "Activity upsert failed\|Activity hydration failed\|Activity heartbeat touch failed" communication-hub.log`.
- Tenant/allowlist regression on the data plane: `grep -n "HTTP 401\|Signed tenant context headers are required\|endpoint_not_allowlisted" communication-hub.log control-center.log`.
