# Fix Log: resumable-agent-turn-persistence

This document tracks bug fixes and issues resolved for this change.

---

## FIX-20261112-230000

**Created:** 2026-11-12T23:00:00Z
**Status:** Resolved (code); blocked in testing by external LLM 402
**Issue:** Answering a human intervention shows "resumed", then fails with "The paused turn could not be resumed. Nothing was applied — ask again to repeat the request."; duplicate intervention outcomes.

### Observed Behavior
- Answering an intervention returned `status=unresumable` immediately; each answer persisted a separate terminal outcome turn.
- AR logging showed the resume failing at the CH→CC checkpoint/claim relay: `HTTP 502 … upstream_status 401 "Signed tenant context headers are required on internal data-plane endpoints"`.
- Separately, all normal chat turns were failing with the model provider returning `HTTP 402 "Insufficient Balance"`.

### Analysis
- **Root cause (code defect, this change):** the **conversation-scoped** resume dispatch in `backend/app/services/conversations/turn_resolution.py` (`dispatch_answered_conversation_turn` → `_resume_agent_session`) did **not** pass the resolved tenant context, unlike the job-session branch in `intervene.py`. Under multi-tenancy every internal data-plane call must carry signed `X-Internal-Tenant-*` headers, so the CC→CH→AR→CH→CC resume chain was headerless and the CH→CC relay was rejected 401 → the turn was marked `unresumable/resume_failed` and a terminal outcome turn was written.
- **Confounder (external, not code):** the user was answering interventions created **Nov 11**, before this feature existed (no `ConversationTurnResume`/checkpoint — the DB had 0 resume rows). Those can never resume; each produced its own outcome. There were also multiple stale pending approval requests for the same action (from earlier attempts), rendered as multiple boxes.
- **Separate external failure:** normal chat is failing because the configured OpenAI-compatible model provider returns `402 Insufficient Balance` for every completion (AR log). Not caused by this change.

### Fix
- `backend/app/services/conversations/turn_resolution.py` — `dispatch_answered_conversation_turn` now resolves `get_current_tenant_context()` and passes `tenant_context=` to `_resume_agent_session`, so the whole CC→CH→AR→CH→CC resume chain carries signed tenant headers. Single-tenant (context unset) → `None` → no headers (unchanged).

### Verification
- `python -c "import app.main"` OK.
- `tests/unit/conversations/test_answer_path_advance.py`, `test_resume_terminal_resolver.py`, `tests/integration/test_internal_intervene_respond.py`, `test_conversation_interruption_notice.py` → **35 passed**.

### Follow-ups (not required for the fix)
- The user must top up / switch the model provider (402) before end-to-end chat/resume can be exercised.
- Test resume on a **fresh** conversation (post-feature) — the Nov-11 stale interventions have no durable resume state by design and cannot resume.
- Consider superseding older pending interventions for the same conversation when a new pause is created (UX), and avoid the optimistic "resumed" label until the dispatch confirms `resumed` (minor).

**Deploy:** restart Control Center (this fix), and Communication Hub / Agent Runtime if not already running the change.

---

## FIX-20261113-080000

**Created:** 2026-11-13T08:00:00Z
**Status:** Resolved
**Issue:** Clicking "Ask again" on the "no longer resumable" card did nothing.

### Root cause
`ConversationDialog.handleAskAgain` only dismissed the terminal card and cleared the input — it never re-sent the request, so the button appeared inert (and the card's own copy says "ask again to repeat the request").

### Fix
`frontend/src/components/agents/ConversationDialog.tsx` — `handleAskAgain` now re-sends the last user message via `sendMessage(...)` (a confirmed write never happened on the dead turn, so repeating is safe), falling back to clearing the input when there is no prior user message. Added a Vitest asserting the replay.

### Context on "no longer resumable"
The card reflects a terminal turn. The single fresh pause created after this feature (resume record `8e5fc886`, 2026-11-13) genuinely could not resume because the resume **claim** hit the same CH→CC 401 tenant-header bug (FIX-20261112-230000) — the checkpoint had been flushed and was then purged when the turn became terminal. With the tenant fix deployed and a fresh turn (and a funded model provider), a pause should resume. Pre-feature (Nov 11) interventions can never resume by design.

### Verification
- `tsc` clean; `ConversationDialog.resumeRecovery` → 12/12 (incl. the new replay test).

### Follow-up UX fix (same day)
- A terminal turn no longer renders the actionable intervention dialog. The lingering confirmation is folded into a **grey, read-only block** (no Approve/Deny, `intervention-closed`), the pending-intervention indicator is suppressed, and the chat input is **re-enabled** so the operator can "Ask again" or retype. "Ask again" re-sends the last user message (history is reloaded server-side, the dead confirmation is not part of the new turn).
- Files: `ConversationDialog.tsx` (`interventionActionable`, folded block, input gating), `en.json` (`intervention.closedReadOnly`); updated `ConversationDialog.resumeRecovery` tests. `tsc` clean; dialog suite 34/34.

---

## FIX-20261113-213000

**Created:** 2026-11-13T21:30:00Z
**Status:** Code resolved — requires backend restart to take effect
**Issue:** Confirmation pauses expired after ~4 minutes; resume still failed (401) on 2026-11-13 21:16.

### Analysis (from live logs + DB)
- The resume **claim** still returned `401 "Signed tenant context headers are required"` at 2026-11-13 21:16 — the tenant-forwarding fix (FIX-20261112-230000) is in code but the services were **not restarted**, so the running CC still dispatches the resume headerless.
- Pauses expired quickly: `expires=10:01:39 → 10:05:39` = ~4 min, because the answerable window used `conversation_intervention_timeout_seconds` (240s) instead of the intended 15-min resume TTL. The user answered the 10:01 pause at ~10:16 → `expired`; the 10:14 pause was answered in-window but the claim 401'd → `resume_failed`.
- `conversation_turn_checkpoints = 0` is expected once a turn is terminal — Phase 5 purges payloads for terminal records (the checkpoint *was* flushed at pause per the AR log, then purged after the failed/expired resolution).

### Fix
- `backend/app/services/agents/runtime_executor.py` — the paused turn's `expires_at` now uses `conversation_turn_resume_ttl_seconds` (default 900s) instead of the 240s intervention timeout, matching the answerable window. (The legacy in-process fallback keeps the intervention timeout.)

### Verification
- `import app.main` OK; `tests/agent_runtime/test_conversational_resume_from_checkpoint.py`, `test_durable_checkpointer.py`, `test_checkpoint_transport.py`, `tests/core/test_conversation_turn_settings.py` → **67 passed**.

**Deploy:** restart **Control Center, Communication Hub, and Agent Runtime** together (the tenant fix spans CC→CH→AR→CH→CC; the TTL change is AR).

---

## FIX-20261113-230000

**Created:** 2026-11-13T23:00:00Z
**Status:** Resolved (code + unit tests); needs a CC + CH restart
**Issue:** A turn emitted `using_tool…` and then stopped, leaving a forever-spinning "Using tool cc____invoke_management_tool…" bubble while a live-looking confirmation dialog offered a dead pause. Approving it said "resuming", then the dialog vanished and the stale spinner remained.

### Observed Behavior (production logs + DB)
- Session `c07651e1`: `conversation_activities.state='using_tool'`, `active_resume_id=NULL`, `is_terminal=False`, while its `conversation_turn_resumes` rows were `unresumable` (`expired`, then `resume_failed`) and `conversation_turn_checkpoints=0`.
- An older pause's `intervene_requests` row stayed `status='pending'` although its resume record was already `expired`, so the REST pending-interventions fetch kept returning it as actionable.
- The stale `using_tool` row stayed non-terminal for >30 min (the old `CONVERSATION_ACTIVITY_STALE_SECONDS` default), so the reaper never healed it.

### Analysis (three independent defects)
1. **Dead confirmation kept actionable.** Neither `resolve_unresumable_turn` nor the reaper's unresumable/expired branch touched the linked `InterveneRequest`. The record died; the confirmation stayed `pending` (and `list_pending_for_conversation` returns only `pending`), so the dialog kept offering it.
2. **Stale working activity could not self-heal.** `ConversationActivity.last_updated_at` was only refreshed by AR status events, never by the CH heartbeat. A live-but-quiet turn and a dead turn looked identical, so the only safe bound was very long — and a dead `using_tool` row therefore spun for 30+ minutes.
3. **The UI treated any present confirmation as actionable.** `ConversationDialog` rendered the actionable dialog whenever an intervention existed and the turn was not terminal, and independently rendered the working-status bubble — so a stale `using_tool` plus a pending confirmation produced a spinner *and* a live-looking confirmation at once.

### Fix
- **Backend — expire the linked confirmation (CC, same transaction):**
  - `backend/app/services/conversations/turn_resolution.py` — new `expire_linked_intervention()` sets a still-`pending` request linked to the record to `expired` (+ `responded_at`); called from `resolve_unresumable_turn`. Only the record's own request is touched, so an operator's just-submitted answer is never clobbered.
  - `backend/app/services/conversations/activity_reaper.py` — the sweep expires the linked confirmation when a referenced resume record is already terminal, and after closing one as unresumable.
- **Backend — activity heartbeat touch (self-healing staleness):**
  - `ConversationActivityStore.touch()` refreshes `last_updated_at` only; a no-op for terminal rows and for `waiting_for_human` (a paused turn deliberately stops beating, and its timing comes from the durable resume record).
  - `POST /api/v1/internal/data/conversations/{conv_session_id}/activity/touch` (service-cert + tenant gated, CH-allowlisted) exposes it.
  - CH `ControlCenterDataClient.touch_conversation_activity()` calls it via the standard internal egress; `_thinking_heartbeat_loop` in `backend/app/api/ws/chat.py` touches once per ~15s beat, so a live turn stays fresh and the heartbeat stops with the turn (including on a pause).
  - CH resume dispatch (`_activity_heartbeat_loop` in `backend/app/communication_hub/api/internal/agent_resume.py`) beats the same way while a **resumed** turn streams, so the short bound cannot terminalise a quiet-but-live resumed turn either.
  - `get_stale_threshold_seconds()` default lowered `1800 → 180` (env `CONVERSATION_ACTIVITY_STALE_SECONDS` still overrides, min 30s). The reaper's existing stale `thinking`/`using_tool`/`delegating` branch now resolves a dead turn within a few minutes; `waiting_for_human` protection is unchanged.
- **Frontend — a confirmation is actionable only during a live pause:**
  - `ConversationDialog.tsx` — `interventionIsLive = interventionRequest != null || chatStatus.kind === 'waiting_for_human' || pendingIntervention`; the actionable `InlineInterventionDialog` requires `activeIntervention && !isTerminal && interventionIsLive`; otherwise the confirmation folds into the existing grey read-only `intervention-closed` block (and the input stays enabled).
  - `workingStatusSuppressed` gates `showThinking`, the standalone delegation status line and the in-cycle live status line, so a stale working status alongside a pending/terminal confirmation renders no progressing bubble.
  - `en.json` — `intervention.closedReadOnly` reworded for the non-terminal stale case.

### Verification
- `import app.main` OK; `npx tsc --noEmit` clean.
- Backend: `tests/unit/conversations/test_activity_touch_and_heartbeat.py` (new — default bound, store/endpoint touch, touched-row protection, dead `thinking`/`using_tool`/`delegating` → terminal, CH heartbeat touch, client method), `tests/communication_hub/test_resume_activity_heartbeat.py` (new — resumed-turn beats and stops on success/failure), `test_resume_terminal_resolver.py` (new `TestDeadConfirmationExpiry`: expiry on resolve, reaper expiry, reaper heals a terminal record + pending request, superseded confirmation expiry, answered request untouched), `test_conversation_activity_endpoints.py` (touch route: 401 without cert, refresh without state change, paused/terminal no-op, idle null, 404), plus the `tests/unit/conversations`, activity/intervention/turn-resume integration, CH relay/dispatch and AR checkpointer suites → **451 passed, 2 pre-existing failures** — both in `tests/communication_hub/test_tenant_header_verification.py`, which expects the retired cert-exempt CH passthrough (`no client certificate` → 401); the pre-existing `test_system_tool_registry_endpoints_are_ch_allowlisted` also fails unchanged when the allowlist-coverage file is included. Neither is touched by this fix (verified with the fix reverted).
- Frontend: `ConversationDialog.resumeRecovery` **18/18** (6 new: stale `using_tool`/`thinking` folds read-only with no spinner, in-cycle live status suppressed, terminal + lingering confirmation, live pause stays actionable, no-confirmation working bubble intact), all `ConversationDialog.*` suites **68/68**, `useChatSession.*` **53 passed / 1 skipped**, full Vitest suite **1947 passed / 3 unrelated flaky failures** (AgentTypeForm / DecisionToolForm / DecisionModelProvidersPage pass in isolation).

**Deploy:** restart **Control Center** (expiry + touch endpoint + 180s bound) and **Communication Hub** (heartbeat touch for both first and resumed turns). No migration, no AR change.

---

## FIX-20261114-110000

**Created:** 2026-11-14T11:00:00Z
**Status:** Resolved (code + regression tests); needs a CC restart
**Issue:** Every resume claim still failed 401 at the CH→CC relay on a live multi-tenant deployment (2026-11-14), even after restarting all services — the last blocker for live resume.

```
AR : resume_session: failed to claim conversation … Checkpoint relay rejected
     http://localhost:8002/internal/turn-resume/…/claim: HTTP 502 — upstream_status 401
CH : Turn resume relay upstream rejection:
     POST /api/v1/internal/data/conversations/…/resume/claim → HTTP 401
```

### Root cause
`dispatch_answered_conversation_turn` (CC) resolved the tenant from the **module contextvar**
(`get_current_tenant_context()`). That contextvar is **not bound on the answer path**:

- `/api/v1/internal/*` is a `TenantResolutionMiddleware` **bypass**, and
  `require_internal_tenant_context` returned the verified `TenantContext` **without binding the
  contextvar** — and the handler discarded the dependency result.
- The production UI answer route for an intervention is exactly that internal path
  (browser → CH WS → `POST /internal/data/intervene/respond`, signed headers minted by
  `_signed_tenant_forwarding`).

So the CC→CH resume dispatch went out **headerless**, CH relayed headerless, and CC's
`.../resume/claim` failed closed 401 (multi-tenancy on) → the still-valid pause was marked
`unresumable`. The earlier fix (FIX-20261112-230000) only worked where the contextvar happened to be
bound (plain HTTP paths), which is why restarting never helped.

### Fix
The tenant is now resolved **from the request / the internal-auth dependency and threaded
explicitly** — never read from the contextvar as the source:

- `backend/app/core/tenant_context.py` — new `optional_tenant_context(request)`: the
  middleware-resolved context on `request.state`, `None` when tenancy is off. Documented as the
  request-derived accessor (the contextvar is explicitly not a propagation source).
- `backend/app/services/conversations/turn_resolution.py` — `dispatch_answered_conversation_turn(…,
  *, tenant_context: TenantContext | None = None)`; passes it to `_resume_agent_session`, falling
  back to `get_current_tenant_context()` only when `None`.
- `backend/app/api/v1/intervene.py` — the conversation-scoped respond branch resolves
  `optional_tenant_context(http_request)` (same as the JOB-session branch) and passes it.
- `backend/app/api/v1/conversations.py` — the conversation intervention respond handler resolves
  `optional_tenant_context(request)` and passes it.
- `backend/app/api/v1/internal/session_data.py` — `internal_intervene_respond` now **consumes** the
  `require_internal_tenant_context` dependency (it was router-level only and discarded) and threads
  that verified context into both the conversation resume dispatch and the legacy job resume.

### Verified (defensive items — no change needed)
- **Pause checkpoint SAVE (AR → CH → CC `PUT …/resume/checkpoint`) already carries headers.** It
  runs inside the WS turn where CH→AR sent the signed set, AR's inbound middleware binds both the
  contextvar and the forwarded set, and `CheckpointTransportClient` uses `internal_httpx_client`.
- **`DurableCheckpointSaver.flush` is fail-closed.** `save_checkpoint` raises
  `CheckpointTransportError` on a refused CC write (`_raise_for_status`), the success log is only
  emitted after the await, and `runtime_executor._handle_conversational_pause` turns that into
  `persistence_failed` (`timeout_or_failed`), never `waiting_for_human`. Pinned by a new test.
- **CH `agent_resume.py` lookup + dispatch** already forward the verified set through
  `ControlCenterDataClient` / `internal_httpx_client` (no re-signing); `_lookup_resume` and the AR
  stream call both use the single egress mechanism.

### Tests
- **New** `tests/unit/conversations/test_respond_tenant_propagation.py` (6 tests) — the regression
  this missed. Exercises all three respond callers (intervene REST, conversation intervention REST,
  internal WS answer path) under simulated multi-tenancy with the tenant bound on
  `request.state` / supplied by the internal-auth dependency and the **contextvar explicitly
  unbound**; asserts `AgentRuntimeClient.resume_session` receives that exact `TenantContext` and that
  `get_current_tenant_context()` was `None`. Verified red against the previous contextvar-only
  implementation (3 failures: `assert None == TenantContext(...)`) and green after the fix. Plus 3
  unit tests for `optional_tenant_context`.
- **New** `tests/agent_runtime/test_durable_checkpointer.py::test_flush_is_fail_closed_when_the_cc_write_is_rejected`
  — flush raises and never logs a successful flush on a refused write.
- Green: `test_answer_path_advance`, `test_internal_intervene_respond`,
  `test_conversation_interruption_notice`, `test_resume_terminal_resolver` (46 passed together with
  the new file); `tests/unit/conversations` + pause/resume flow + turn-checkpoint endpoints +
  internal-tenant fail-closed + checkpoint transport + CH resume dispatch + WS signed forwarding
  (**204 passed**); `test_tenant_signature`, `test_internal_http_egress`,
  `test_internal_auth_security` green.
- `python -c "import app.main"` OK; `py_compile` clean on every touched file.

### Known unrelated failure
`tests/integration/test_multitenant_auth_chain.py::TestInternalEndpoints::test_stale_timestamp_401`
fails identically with this change stashed (pre-existing, untouched by this fix).

**Deploy:** restart **Control Center** (all three respond callers + the internal dependency
threading). CH/AR unchanged by this fix — they already forward the verified set.

---

## FIX-20261114-120000

**Created:** 2026-11-14T12:00:00Z
**Status:** Resolved (code + unit/UI tests); needs a CC restart (CH restart only for the message text)
**Issue (two follow-ups):**
1. The paused turn's answerable window (`conversation_turn_resume_ttl_seconds`, platform default
   900s) was global-only; a tenant could not choose its own window.
2. A turn that died **mid-flight** (crash / server restart — heartbeat stopped while
   `thinking` / `using_tool` / `delegating`) leaked into `timed_out` + `resume_failed`, whose copy
   talks about a *confirmation* that could not be resumed instead of "the assistant stopped".

### Analysis
- **TTL**: the platform setting was the only source and Agent Runtime computed `expires_at` and
  pushed it through `PUT .../resume` — so CC merely stored a client-supplied window. Tenant policy
  needs CC to own the value.
- **Watchdog**: the reaper's working-state staleness branch reused the *pause* vocabulary
  (`timed_out`/`resume_failed`). A stale working row is not a timeout (the client is not waiting)
  and not a failed resume (there may be no pause at all): it is an unexpected termination.
- **Consistency gap** (found while implementing): the checkpoint payload's `expires_at` was also
  client-supplied (AR's platform TTL), so a tenant window **longer** than the platform default
  would have its saved state purged (and reaped as `checkpoint_unavailable`) before the answer
  window closed.

### Fix
**Task A — per-tenant resume TTL (default 15 min)**
- `backend/app/services/conversations/turn_resume_settings.py` (**new**) —
  `resolve_resume_ttl_seconds(db, tenant_id)` reads `TenantSetting["conversation_turn_resume_ttl_seconds"]`,
  coerces (int/float/numeric string) and clamps (min 30), else falls back to
  `settings.conversation_turn_resume_ttl_seconds` (900); `resolve_resume_expiry(...) -> now + ttl`;
  `set_resume_ttl_seconds(...)` persists clamped.
- `backend/app/services/agents/intervene_service.py` — the pause path (`create_request`) stamps the
  resume record's `expires_at` from tenant policy (was `request.expires_at`, which was always None /
  the 240s intervention window in the earlier incident). Tenant resolved from `request.tenant_id`,
  falling back to the conversation session's tenant.
- `backend/app/api/v1/internal/session_data.py` — `PUT .../resume` **ignores** the client-supplied
  `expires_at` and recomputes it from tenant policy; the checkpoint `PUT` now uses the live resume
  record's window (CC authority), so the payload can never expire before the answer window.
- `backend/app/api/v1/tenant.py` — `TenantSettingsRead` exposes
  `conversation_turn_resume_ttl_seconds` (effective value: override or platform default) and
  `TenantSettingsUpdate` accepts it (`ge=30`, 422 below), persisted via the tenant settings store.
  No UI control was added (API-only, per request).

**Task B — watchdog: stuck in-progress → "failed unexpectedly"**
- `backend/app/services/conversations/turn_resolution.py` — new reason
  `REASON_UNEXPECTEDLY_TERMINATED = "unexpectedly_terminated"` with an actionable message
  ("The assistant stopped unexpectedly (e.g. a server restart) before finishing. Nothing was
  applied. Please resend your request or ask again.") and key `chat.resume.unexpectedlyTerminated`.
  `terminal_activity_state_for_reason` maps it to `failed` (not `timed_out`).
- `backend/app/services/conversations/activity_reaper.py` — a **stale** working row (`thinking` /
  `using_tool` / `delegating`) now resolves to activity `failed` + `unexpectedly_terminated`, closing
  any abandoned live resume record with the same reason and expiring its pending confirmation. Dead
  sessions keep `failed`/`cancelled`; a paused (`waiting_for_human`) row is untouched by heartbeat
  staleness.
- `backend/app/services/conversations/activity_store.py` — `resolve_terminal(..., detail=...)` can
  persist the terminal reason on the activity; a non-terminal upsert strips a previous turn's
  terminal reason so a live row never hydrates a stale card.
- `backend/app/api/v1/internal/session_data.py` — `_activity_response` falls back to the activity
  detail's reason when no resume record exists (a stale working row has none), so reconnect and
  `status_ping`/`status_pong` self-heal to the reason-keyed card.
- `backend/app/communication_hub/api/internal/agent_resume.py` — same message added to CH's terminal
  vocabulary (hydration message text only; no signing/persistence change).
- `frontend/src/components/conversations/ResumeTerminalCard.tsx` + `en.json` — third body variant
  `bodyUnexpectedlyTerminated`; "Ask again" (replays the last user request) already works for the
  `failed` terminal kind.
- `frontend/src/api/tenantApi.ts` — typed the new settings field (no UI).

### Tests
- **New** `backend/tests/unit/test_tenant_resume_ttl_setting.py` (22) — default 900, tenant override
  3600, clamp <30, malformed/bool/None/string values, two-tenant isolation, setter clamp,
  `now + ttl` expiry; `create_request` uses the tenant value and the platform default; `PUT .../resume`
  overrides a client-supplied 60s expiry; checkpoint lives for the resume window; tenant-settings API
  GET default / PATCH round-trip / 422 below 30 / unrelated PATCH keeps the TTL.
- **New** `backend/tests/unit/conversations/test_watchdog_unexpected_termination.py` (9) — vocabulary
  (message/key/`failed` mapping), stale `thinking` → `failed` + reason on the activity detail, stale
  `using_tool` closes the linked resume record with the dedicated reason, stale `delegating` while
  `resuming` likewise, linked confirmation expired, fresh touched row untouched, dead session stays
  `failed`/`cancelled`, live pause protected.
- **Updated** `test_conversation_activity_reaper.py`, `test_activity_touch_and_heartbeat.py`
  (stale working rows now `failed` + `unexpectedly_terminated` instead of `timed_out`).
- **Frontend** `ConversationDialog.resumeRecovery.test.tsx` (+2: new body rendered with the card /
  Ask again replays the request).
- Green: `tests/unit/conversations` + activity/checkpoint/resume-projection suites → **183 passed**;
  turn-resume store / terminal resolver / answer path / checkpoint / tenant-propagation → **82**;
  pause→resume flow + interruption notice + internal respond + sessions projection → **40**;
  CH resume/checkpoint suites → **179 passed, 2 pre-existing** `test_tenant_header_verification`
  failures (unchanged fail-closed 401 expectation); AR checkpointer/transport/resume → **68**;
  tenant membership/root/licensing/workflow suites → **48 passed, 1 pre-existing** cross-file
  `display_name="Invitee"` collision (`MultipleResultsFound`, reproduces without these changes).
  Full `tests/unit tests/integration` → **2112 passed, 150 skipped, 34 pre-existing
  environment failures** (cert files missing, migration revision mismatch, legacy `int` UUID column
  family) — none in a touched area. `python -c "import app.main"` OK; `py_compile` clean.
- Frontend: `tsc --noEmit` clean; `ConversationDialog.resumeRecovery` **20/20**; all
  `ConversationDialog.*` **70/70**; `TenantWorkspacePages` + dialog suites **88/88**;
  `useChatSession.*` **53 passed / 1 skipped**.

### Deviations / notes
- No DB migration: `TenantSetting` already exists and the resume outcome enum is unchanged — the
  dedicated reason travels in `terminal_reason_code` (the outcome stays `resume_failed`).
- CC now owns the pause window end-to-end (resume record **and** checkpoint payload expiry); AR's
  `expires_at` is accepted on the wire but ignored.
- The terminal card's title/subtitle copy ("This confirmation can no longer be resumed") is still
  pause-flavoured for this reason; only the body variant was in scope.
- A still-connected client learns about a reaper resolution via the existing client watchdog
  (`status_ping` → `status_pong`, which now carries the reason) or on reconnect — CC does not push
  to CH.

**Deploy:** restart **Control Center** (TTL authority + reaper + activity projection); restart
**Communication Hub** only for the new terminal message text. No AR change required (AR's
`expires_at` is now ignored by CC).





---

## FIX-20261114-130000

**Created:** 2026-11-14T13:00:00Z
**Status:** Resolved
**Issue:** Resume worked after a restart, but a SECOND confirmation created during the resumed turn failed with "This confirmation can no longer be resumed" — no restart involved.

### Analysis (AR/DB logs)
- The resumed turn re-paused (new `InterveneRequest` + resume record `7dcfcb91`), but that record had `expires_at=None` and `terminal_reason_code=checkpoint_unavailable`.
- AR log: `Resume …: claim lost (already_held, holder=agent-runtime) — aborting` / `claim lost mid-run — aborting without completing`.
- **Root cause:** the resume service renews its claim every ~1/3 lease (~15s). The store's `claim` only acquired when unclaimed or the lease had expired, so a **same-instance renewal** returned `already_held` → the resume aborted mid-run. Any resume lasting >~15s aborted, and its re-pause was not persisted (no checkpoint/window) → approving the re-pause hit `checkpoint_unavailable`.
- Secondary: the claim identity was a constant (`agent-runtime`) shared by all AR processes.

### Fix
- `backend/app/services/conversations/turn_resume_store.py` — the holder may now **renew its own live lease** (`claimed_by_instance_id == instance_id` added to the acquisition condition); a different instance still gets `already_held`.
- `backend/app/agent_runtime/turn_resume_service.py` — claim identity is now **process-unique** (`<base>-<process-token>`).

### Verification
- New store test: holder renews its own live lease → `acquired`; different instance → `already_held`; after expiry → acquired.
- `import app.main` OK; store + resume + transport suites **48 passed**.

**Deploy:** restart Control Center (claim store) + Agent Runtime (claim identity) + Communication Hub (accumulated heartbeat/touch).

---

## FIX-20261114-153000

**Created:** 2026-11-14T15:30:00Z
**Status:** Resolved
**Issue:** After approving an ordinary (in-process) human intervention, the chat showed a thinking
bubble **and** the amber "waiting for your input" bar kept spinning, and the thinking bubble carried
a "Resumed · continuing" chip — even though nothing had been resumed (no restart/reconnect).

### Analysis
Two independent client-side effects, both triggered by the answered-pause path:
- `sendInterventionResponse` closed the confirmation and set the status optimistically but **never
  cleared `pendingIntervention`**, so the amber indicator (driven by
  `waitingForInput || pendingIntervention`) stayed visible until — and only if — an
  `intervene_status: responded` echo arrived.
- Both answered paths stamped `resumeState: 'resuming'` on the client status, which is what drives
  `resumedTurnActive` → the "Resumed" chip. A live in-process approval is not a resumed turn; the
  resumed vocabulary is only meaningful for a turn recovered from a durable checkpoint.

A third, server-side contributor: the persisted activity stayed `waiting_for_human` (linked to the
live resume id) after the answer, so a reconnect hydration or a watchdog `status_pong` could
re-surface "waiting for your input" for a turn that was already processing again.

### Fix
- `frontend/src/hooks/useChatSession.ts` — `sendInterventionResponse` clears `pendingIntervention`
  immediately and shows the ordinary `thinking` status (no `resumeState`). The
  `intervene_status: responded` handler likewise emits plain `thinking`.
- `backend/app/services/conversations/turn_resolution.py` — `advance_answered_intervention` now
  flips a still-`waiting_for_human` activity to `thinking` in the **same transaction** as the stored
  answer (the live resume link is kept, the pending confirmation reference is cleared).

### Result
A normal approval closes the confirmation, removes the amber bar at once, and shows the plain
processing bubble. "Resumed · continuing" is now only produced by server hydration after a real
reconnect/restart, never by a local answer.

### Verification
- Frontend: `useChatSession.intervention` / `activityState` / `ConversationDialog.resumeRecovery`
  47/47; full Vitest suite **1954 passed, 0 failed**.
- Backend: new unit test `test_answer_moves_the_persisted_activity_out_of_waiting`; all
  `tests/unit/conversations` **143 passed**.

**Deploy:** restart Control Center (answer-path activity transition) + frontend rebuild.
