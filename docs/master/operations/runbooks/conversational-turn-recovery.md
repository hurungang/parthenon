# Runbook: Conversational Turn Recovery

Covers a conversational turn that was **paused, working, or awaiting an answer** when a service restarted, an instance was replaced, or a failover occurred — plus every way a paused turn can fail to resume. Applies to the Control Center Assistant and any conversational agent type (including third-party client sessions).

The invariant to prove in every case: **a turn shown as "waiting for your input" is actually answerable, and a turn that is not answerable is not shown as waiting.**

Related: [control-center-assistant.md](control-center-assistant.md) (chat/auth/permission paths), [agent-runtime.md](agent-runtime.md) §7 (durable checkpoint behaviour in AR), [communication-hub-disconnect.md](communication-hub-disconnect.md) (hub restart and reconnect hydration), [../monitoring-metrics.md](../monitoring-metrics.md) and [../monitoring-alerts.md](../monitoring-alerts.md) (Conversational Turn Resume metrics/alerts), [../logging-conversation-turns.md](../logging-conversation-turns.md) (Conversation Activity and Resumable Turn Events).

Log files: `backend/logs/control-center.log`, `communication-hub.log`, `agent-runtime.log`. Files rotate at ~10 MB with `.1`/`.2` retained. Always follow **one** `conv_session_id` across all three files, in the order CC → CH → AR.

---

## 0. First: what should happen (so you know what "broken" means)

| Situation | Expected behaviour on this build |
|---|---|
| Restart CC, CH, or AR while a confirmation is pending | The pause survives. Reconnect shows the confirmation still actionable; answering resumes the turn on any AR instance |
| Answer a pending confirmation | One row recorded, one dispatch, one resume, one reply, and **at most one** application of the confirmed write |
| Restart while a turn was actively working (no pause) | The turn resolves terminally as "the assistant stopped unexpectedly (e.g. a server restart)…" with no write applied. The user re-sends |
| Answer after the answerable window | The turn resolves `expired` with an actionable message and no dispatch. Nothing was applied |
| Answer a turn that genuinely cannot resume | One reason-specific terminal message (saved state unavailable/already used/cancelled/superseded) — never the generic legacy timeout |

Answerable window = the tenant's `conversation_turn_resume_ttl_seconds` (platform default 900 s). `conversation_intervention_timeout_seconds` (240 s) applies only to the legacy in-process fallback.

---

## 1. Approval after a restart does nothing / "delegated step timed out or failed"

**Symptoms**: a confirmation is still visible after a restart; approving shows "resuming" and then either nothing or the legacy "Delegated step timed out or failed. Please try again."

**Diagnose**

1. Confirm the deployed build on **all three** services. The legacy message is the signature of old code handling the answer (in-process resume path) — that is a rollout problem, not a durability defect.
2. Follow the session in `control-center.log`: is there a `Resume record … registered for conversation …`, then `Answered intervention … → resume … resuming`? No record at all means the pause predates the feature (or the pause path failed — see §5).
3. `communication-hub.log`: `Resume dispatch started for conversation … (resume_id=…)`, optionally `Resume dispatch de-duplicated …` or `Resume outcome short-circuited …`.
4. `agent-runtime.log`: `Durable checkpoint flushed for conversation …` (at pause time) then, at answer time, claim and checkpoint-load lines.
5. Inspect the durable state conceptually: the session's activity row should carry a **live resume link** while it shows waiting; the resume record should be non-terminal with an `expires_at` in the future; a checkpoint payload should exist for it.

**Resolve**

- **Answer recorded, no dispatch** → CC-side dispatch failure. Re-answering is safe: the stored outcome short-circuits and no second write occurs.
- **Dispatch logged, AR never claimed** → AR unreachable or a certificate/tenant-header rejection. Check the AR boundary lines and the fleet's certificate state; then re-answer.
- **Resolved `expired`** → the answer arrived after the window. The terminal message stands (nothing applied). Raise the tenant TTL if it recurs, or fix notification delivery.
- **No resume record for the session** → the pause was created by pre-feature code or the pause path failed; the turn cannot resume. Have the user re-issue the request.

**Escalate** if a live, unexpired record exists and neither dispatch nor a terminal resolution appears within one sweep (~60 s) — capture `conv_session_id`, `resume_id`, and the three log excerpts.

---

## 2. Duplicate approvals / the same change applied twice

**Symptoms**: two identical replies, two outcome turns, or the same confirmed management change applied twice.

**Diagnose**

- Exactly-once is keyed on the resume record's unique idempotency key and its applied marker, committed with the write.
- `control-center.log`: exactly **one** `Resume … recorded the confirmed write` per resume id; later answers log `Resume outcome short-circuited …` (or `… targets terminal resume …`).
- Conceptually: one applied marker set once, one outcome turn linked to the resume record, one reply turn.
- `communication-hub.log`: one `Resume dispatch started …`; repeats appear as `de-duplicated`.

**Resolve**: a repeat answer returning the stored effect is correct behaviour — no action. **Two** applied-write lines for one resume id is an exactly-once violation: freeze the involved management capability, capture the idempotency key, resume id, both log lines, and the affected record, and escalate as a data-integrity incident.

**Never** "fix" a duplicate by deleting the resume row or the applied marker — that removes the guard and invites a third application. A duplicated side effect *inside an external system* the tool called is out of scope (the platform guarantees one dispatch of the tool, not one external side effect).

---

## 3. "Another instance is resuming this turn" / contention

**Symptoms**: `409` on approval, `Resume already in flight elsewhere for conversation …`, or `Resume …: claim lost (…, holder=…) — aborting`.

**Diagnose**

- **Normal**: duplicate answers or a reconnect during a resume serialise on the claim. Self-resolving — no action.
- **Abnormal**: contention persisting for many minutes with no active resume → a stale claim from an instance that died mid-resume (crash, OOM, node loss).

**Resolve**

1. Wait one claim lease (`CONVERSATION_TURN_CLAIM_TTL_SECONDS`, default 45 s); the lease expires and frees the turn.
2. Have the operator re-answer — the answer is idempotent.
3. If the same instance id keeps re-acquiring and dying, remove that instance from the fleet. Check its certificate and memory pressure.

**Never** clear claim fields by hand; expiry is the supported release path and hand-clearing removes the single-resumer guarantee.

**Escalate** if contention survives two consecutive lease expiries with a healthy fleet.

---

## 4. A turn says it is no longer resumable (saved state unavailable / already used)

**Symptoms**: terminal card "The paused turn can no longer be restored…", "…saved state was already used…", "This confirmation can no longer be resumed."

**Diagnose** (the index is authoritative; the payload is disposable)

- `control-center.log`: `Checkpoint for resume … persisted` at pause time, then a purge line timestamped before the answer, or `Resume … marked unresumable (reason=checkpoint_unavailable|checkpoint_consumed|resume_failed)`.
- `agent-runtime.log`: `checkpoint load failed`, `no loadable checkpoint — marking unresumable`, `checkpoint unusable`, or `checkpoint carries no agent_type_id`.
- Conceptually: the resume record is terminal with a reason code, and the session's activity shows a terminal state carrying the same reason — they must agree.

**Resolve**: nothing was applied and the write never happened, so re-issuing the request is safe. Use "Ask again" (replays the last user request) or retype.

**Prevent**

- Keep `CONVERSATION_TURN_CHECKPOINT_PURGE_AFTER_SECONDS` above `CONVERSATION_TURN_RESUME_TTL_SECONDS`.
- Keep `CONVERSATION_TURN_CHECKPOINT_MAX_BYTES` identical on Control Center and Communication Hub.
- Treat payload schema changes as a release compatibility decision: a build must refuse an unknown schema version, never mis-deserialise it. Drain pending confirmations before a payload-incompatible upgrade.

**Escalate** if payloads are lost well inside the answer window with a healthy sweep — that is a store defect, not expiry.

---

## 5. "Pause could not be persisted" (the assistant fails instead of asking for confirmation)

**Symptoms**: the turn ends with a failure instead of showing a confirmation; `agent-runtime.log` has `Conversation … pause could not be persisted — failing the turn closed`.

**Diagnose**

1. **Deploy ordering**: is AR running ahead of the CH checkpoint relay, or CH ahead of CC? A new AR with no relay is the most common cause (`Turn resume relay … HTTP 404/502` in `communication-hub.log`).
2. **Payload size**: `… bytes > … byte guard` in CH, or a rejected-too-large write, means the payload exceeded `CONVERSATION_TURN_CHECKPOINT_MAX_BYTES` (or CH's value is lower than CC's).
3. **CC health/schema**: 5xx on the internal resume/checkpoint routes usually means an unapplied migration. Compare `alembic current` with the latest revision in `backend/alembic/versions/`.
4. **Auth**: `HTTP 401` on the relay means missing/stale signed tenant headers or a lost allowlist entry — the caller must be rebuilt, never "work around" by loosening the check.

**Resolve**: fix the ordering/cap/schema/auth cause, then have the user re-issue the request (no write occurred, so re-issuing is safe).

**Escalate** if pauses fail with an in-order, healthy deployment and a payload well under the cap.

---

## 6. Checkpoint storage keeps growing

**Symptoms**: the checkpoint table's size or row count rises monotonically; `ResumeCheckpointStorageGrowth` firing.

**Diagnose**

- Healthy: payloads are consumed once and deleted after resolution (or the retention horizon); the index row survives.
- `control-center.log`: purge and sweep lines are emitted **only when something was deleted/resolved**, so silence alone is not a fault. Growing storage with no `Purged … checkpoint payload(s)` line means either nothing is purgeable (stuck non-terminal records — see below) or the sweep is not running; the reaper startup line tells you which.
- Conceptually: look for resumes stuck non-terminal long after their window (an abandoned "resuming" record whose claim expired hours ago means the resolver never reached it) — those hold payloads indefinitely.

**Resolve**

1. Confirm the reaper loop is alive (startup line + periodic sweep lines). Restart Control Center only if it is genuinely stalled.
2. For terminal records, purging payloads is safe **once the outcome is recorded**; never delete the index row.
3. Do not delete live records to reclaim space — a live record whose payload vanishes becomes an orphan (§7).

**Escalate** if storage grows with an active sweep and no non-terminal rows older than the window.

---

## 7. Activity says "waiting for your input" but the turn is not answerable

**Symptoms**: the amber waiting indicator or the confirmation dialog is shown, answering fails, and no terminal message ever appears.

**This is the orphan case and must not happen.** Treat every occurrence as an incident (`ResumeOrphanedTurn`), not as routine expiry.

**Diagnose**

1. `control-center.log`: does the session have a `Terminal Resolver closed conversation … (reason=…)` line? If yes, the reaper has already healed it — the client corrects on the next `status_pong` or reconnect.
2. Conceptually: compare the session's activity row with its live resume record. A waiting row with **no** live resume link is a defect. A live-looking record with a **missing** checkpoint is resolved as saved-state-unavailable by design.
3. `communication-hub.log`: `Activity hydration failed …` / `Activity heartbeat touch failed …` indicate the projection is stale rather than the record being wrong.

**Resolve**

- Immediate: wait one sweep (~60 s); the UI then shows the reason-specific terminal card and re-enables input.
- Operator workaround: have the user start a new turn — a new pause supersedes the old record. **Do not edit rows by hand.**
- If it persists across two sweeps: capture `conv_session_id`, the activity row (state, live resume link, terminal flag, last-updated time), the resume record (state, outcome, expiry, claim holder), and whether a checkpoint exists; then escalate.

---

## 8. Spinner never clears / activity looks stale

**Symptoms**: "Thinking…" or "Using tool …" persists with no live turn; the input stays disabled; no intervention is pending.

**Diagnose**

- A live turn refreshes its activity row every ~15 s through the hub heartbeat. A dead turn stops, and the reaper resolves it after the staleness bound (`CONVERSATION_ACTIVITY_STALE_SECONDS`, default 180 s, min 30).
- `control-center.log`: `Terminal Resolver closed conversation … → failed (reason=unexpectedly_terminated)` is the expected healing line for a turn that died while working.
- If that line never appears, check the reaper is sweeping (`Activity reaper resolved …`) and that `Activity heartbeat touch failed` is not firing for live sessions.
- A stale working status shown **alongside** a pending or dead confirmation is suppressed by the UI; if it renders a progressing bubble and an actionable confirmation at once, that is a UI defect — capture a screenshot and the session id.

**Resolve**: no manual state change. Confirm one healing line per stale session and that the client self-corrects on reconnect. Lowering the staleness bound is a deliberate tuning decision, not a fix.

**Escalate** if stale rows remain non-terminal beyond two sweeps despite a running reaper, or if the healing line appears but the UI still shows a spinner after reconnecting.

---

## 9. Planned maintenance and release checklist

- **Restarts of CC, CH, or AR individually**: no need to drain — paused turns survive all three. A working turn is lost either way (it has no pause checkpoint).
- **Full-stack restart**: the standard bootstrap order is CC → AR → CH, which leaves a short AR-before-CH window. Turns that pause inside that window cannot persist a checkpoint and resolve terminally (clear message, nothing applied). Schedule releases outside active approvals.
- **Before a schema downgrade or a payload-incompatible upgrade**: drain. Have operators answer or abandon pending confirmations, wait for the terminal state, then proceed. Export the resume index before any downgrade.
- **After any release**: confirm the reaper started line in `control-center.log`, no sustained relay 401s in `communication-hub.log`, and that a test pause survives an AR restart and resumes once.

---

## Escalation summary

| Condition | Severity | Escalate to |
|---|---|---|
| Waiting shown but turn not answerable, or persisted state disagrees with the resume record | Critical | Platform on-call + owning team, with both records captured |
| Two applied writes for one resume id | Critical | Data-integrity incident |
| Pauses cannot persist at all (in-order healthy deployment) | Critical | Platform on-call |
| Resume success rate < 0.95 over 15 min | Critical | Platform on-call |
| Sustained claim contention across lease expiries | Warning | Platform on-call |
| Terminal `expired` above baseline | Warning | Product owner (window/notification policy) |
| Checkpoint storage growth with an active sweep | Warning | Platform on-call |

**Never** remediate by deleting resume rows or applied markers, clearing claim fields, editing the activity table, disabling tenant-header checks, or widening the internal allowlist beyond the shipped route set.
