# Operations: Resumable Agent Turn Persistence

Operating notes for durably resumable paused conversational turns: CC owns the resume index (`ConversationTurnResume`) and the opaque checkpoint payload (`ConversationTurnCheckpoint`) plus `ConversationActivity.active_resume_id`; AR persists and loads paused state only through CH over mTLS; the extended activity reaper is the Terminal Resolver.

The invariant operators must be able to prove at any moment: **a turn shown as "waiting for your input" is actually answerable, and a turn that is not answerable is not shown as waiting.**

---

## 1. Monitoring

### 1.1 Metrics

All signals below are emitted by the code paths added in this change; group by `tenant_id` on the tenancy dashboard when multi-tenancy is enabled. `reason`/`reason_code` values are the terminal reason codes (`expired`, `superseded`, `cancelled`, `resume_failed`, claim-abandoned variants).

| Signal | Metric (proposed name) | Labels | Why it matters |
|---|---|---|---|
| Pause persisted / failed | `conversation_turn_pause_persisted_total` | `outcome` (`persisted`, `failed`, `failed_payload_too_large`, `failed_transport`), `agent_type` | A pause that cannot persist is an operator-visible dead end. `failed` rate > 0 means the assistant cannot safely ask for confirmation. |
| Resume dispatched | `conversation_turn_resume_total` | `event` (`dispatched`, `deduplicated`, `succeeded`, `failed`) | Primary resume-success/failure ratio. `deduplicated` confirms the single-dispatch guard is absorbing repeats. |
| Resume failure reason | `conversation_turn_resume_failure_total` | `reason` (`checkpoint_missing`, `checkpoint_consumed`, `checkpoint_unavailable`, `deserialisation_failed`, `claim_held`, `dispatch_failed`, `instance_unreachable`) | Distinguishes "our durable state is wrong" (checkpoint reasons) from "our transport/routing is wrong" (dispatch/instance reasons). |
| Orphaned turn | `conversation_turn_resume_orphaned_total` | `reason` | A turn that was shown as waiting and turned out not to be answerable, i.e. the invariant broke. Should be **zero**; any value is a defect signal, not routine expiry. |
| Claim contention | `conversation_turn_claim_total` | `result` (`acquired`, `held_by_other`, `expired_reacquired`, `terminal`, `not_found`) | `held_by_other` in steady state means duplicate deliveries are being correctly serialised; sustained contention means a stale claim or a duplicate dispatch loop. `expired_reacquired` is the failover path. |
| Terminal resolutions | `conversation_turn_terminal_total` | `reason_code`, `state` (`resolved`, `unresumable`) | Expiry, supersede, cancel and genuine failure are operationally different; a uniform "timed out" line hides the difference. |
| Outcome application | `conversation_turn_write_applied_total` | `result` (`applied`, `replayed`, `denied`, `expired_skipped`) | Proves exactly-once: `replayed` means an idempotency key short-circuited a duplicate, which is correct; more than one `applied` per pause is not. |
| Checkpoint size | `conversation_turn_checkpoint_bytes` (histogram) | `payload_kind` | Watch p99 against `CONVERSATION_TURN_CHECKPOINT_MAX_BYTES`; a histogram pinned at the cap means pauses will start failing with `failed_payload_too_large`. |
| Checkpoint lifecycle | `conversation_turn_checkpoint_total` | `event` (`written`, `consumed`, `purged`, `rejected_too_large`) | Confirms purge is running and payloads are consumed once. `written` growing with a flat `purged` means storage leak. |
| Checkpoint storage | `conversation_turn_checkpoint_bytes_stored` (gauge) and table size | — | Capacity planning for the CC database. |
| Resume latency | `conversation_turn_resume_duration_seconds` (histogram) | `result` | Time from resume acceptance to first streamed status; p99 regression points at checkpoint load or agent rebuild, not at the model. |
| Reaper sweep | `conversation_activity_reaper_total` | `outcome` (`swept`, `protected`, `resolved`, `purged`, `error`) | `protected` counts waiting rows correctly left alone; a sweep that stops reporting means waiting turns will never be terminalised. |

### 1.2 Dashboard

Add a **Conversational Turn Resume** panel group to the Control Center Assistant dashboard:

- **Pause → Resume Funnel** — paused (`persisted`) → answered (intervention responded) → resumed (`dispatched`) → resolved (`succeeded`); the drop between stages is the operator-visible failure count.
- **Resume Success Rate** — `succeeded / (succeeded + failed)` with the answerable-window default annotated; the SLO is ≥ 0.99 for turns answered inside the window.
- **Orphaned / Unresumable Split** — `orphaned_total` as one line (target zero) and `terminal_total` by `reason_code` stacked separately, so genuine expiry never masks a durability defect.
- **Claim Contention** — `claim_total` by `result`; annotate the configured claim TTL.
- **Terminal Resolutions by Reason** — stacked `terminal_total` by `reason_code`, with the terminal message key shown in the legend.
- **Checkpoint Payload Size** — p50/p99 histogram bars plus the configured cap as a threshold line.
- **Checkpoint Storage** — stored bytes and row count over time, with purge rate overlaid.
- **Resume Latency p99** — by result, per service segment (CC claims, CH dispatch, AR load).
- **Per-tenant view** — pause/resume/terminal counts grouped by `tenant_id` for noisy-neighbour and isolation checks.

### 1.3 Alerts

| Alert | Condition | Severity | Action |
|---|---|---|---|
| `ResumeSuccessRateDegraded` | resume success ratio < 0.95 over 15 min (min 20 attempts) | Critical | Split by `reason`: checkpoint reasons → see §3.4; dispatch reasons → check AR reachability and CH routing (§3.5). |
| `ResumeOrphanedTurn` | `increase(conversation_turn_resume_orphaned_total[10m]) > 0` | Critical | The core invariant broke — a waiting turn was not answerable. Capture the `conv_session_id`s immediately, verify `ConversationActivity.active_resume_id` for those sessions, then page the owning team. |
| `ResumePausePersistFailed` | `increase(conversation_turn_pause_persisted_total{outcome!="persisted"}[10m]) > 0` | Critical | Pauses cannot be made durable; approvals will not survive a restart. Check CH checkpoint relay and the byte cap (§3.1, §3.4). |
| `ResumeCheckpointUnavailable` | `increase(conversation_turn_resume_failure_total{reason=~"checkpoint_.*"}[10m]) > 0` | Critical | Purge horizon too short, cap too small, or payload schema drift after an upgrade (§3.4). |
| `ResumeClaimContentionSustained` | `claim_total{result="held_by_other"}` > 50% of claims for 10 min | Warning | Duplicate dispatch loop or stale claim from a crashed AR (§3.3). |
| `ResumeTerminalExpirySpike` | `terminal_total{reason_code="expired"}` > baseline for 15 min | Warning | Operators are answering outside the window; raise `CONVERSATION_TURN_RESUME_TTL_SECONDS` or fix notification delivery. |
| `ResumeCheckpointSizePressure` | checkpoint bytes p99 > 80% of cap, or any `rejected_too_large` | Warning | Reduce agent context or raise the cap deliberately, in both CC and the CH relay guard (§3.4). |
| `ResumeCheckpointStorageGrowth` | stored bytes or row count monotonic for 6 h with flat `purged` | Warning | Purge sweep not running (§3.6). |
| `ResumeReaperStalled` | no `conversation_activity_reaper_total` sample for 15 min | Critical | Waiting turns will never terminalise; check the CC background loop and its logs. |
| `ResumeWriteAppliedDuplicated` | more than one `write_applied_total{result="applied"}` per pause within 24 h | Critical | Exactly-once violation in the confirmed-write chokepoint — treat as a data-integrity incident (§3.2). |

---

## 2. Logging

Structured logs; every line carries `trace_id` and, where applicable, `tenant_id`, `conv_session_id`, `resume_id`, `claimed_by_instance_id`, `attempt_count`.

### Control Center — `backend/logs/control-center.log`

| Event | Level | Key fields |
|---|---|---|
| Pause recorded / resume index created | INFO | `conv_session_id`, `resume_id`, `intervene_request_id`, `expires_at` |
| Live resume record superseded by a newer pause | INFO | `conv_session_id`, `superseded_resume_id`, `new_resume_id` |
| Checkpoint written | INFO | `resume_id`, `payload_bytes`, `schema_version`, `payload_kind` |
| Checkpoint rejected (size / kind / schema) | WARN | `resume_id`, `payload_bytes`, `cap_bytes`, `reason` |
| Claim acquired / renewed | INFO | `resume_id`, `claimed_by_instance_id`, `claim_expires_at`, `attempt_count` |
| Claim refused (held by another instance) | WARN | `resume_id`, `held_by_instance_id`, `claim_expires_at` |
| Resume accepted (answer recorded, dispatch starting) | INFO | `resume_id`, `idempotency_key`, `responded_by` |
| Duplicate answer short-circuited to stored outcome | INFO | `resume_id`, `idempotency_key`, `resume_outcome` |
| Confirmed write applied / replayed from applied marker | INFO | `resume_id`, `idempotency_key`, `applied_by_user_id`, `tool_name`, `result` |
| Outcome turn appended and activity resolved | INFO | `resume_id`, `outcome_turn_id`, `resume_state`, `resume_outcome` |
| Terminal resolution by the reaper | WARN | `resume_id`, `conv_session_id`, `reason_code`, `terminal_message_key`, `state` |
| Waiting row protected (still answerable) | DEBUG | `conv_session_id`, `resume_id`, `expires_at` |
| Checkpoint purged | INFO | `resume_id`, `age_seconds`, `payload_bytes` |
| Reaper sweep error | ERROR | `error` (stack), `swept`, `resolved` |

### Communication Hub — `backend/logs/communication-hub.log`

| Event | Level | Key fields |
|---|---|---|
| Checkpoint save relayed / load relayed | DEBUG (INFO on failure) | `conv_session_id`, `payload_bytes`, `upstream_status` |
| Checkpoint relay rejected by size guard | WARN | `conv_session_id`, `payload_bytes`, `guard_bytes` |
| Resume dispatch started (conversation-scoped) | INFO | `conv_session_id`, `target_instance`, `resume_id` |
| Resume dispatch de-duplicated (in-flight guard) | INFO | `conv_session_id`, `duplicate_of` |
| Resume outcome short-circuited (already stored) | INFO | `conv_session_id`, `resume_outcome` |
| Resumed stream paused again | INFO | `conv_session_id`, `resume_id`, `paused_turn_id` |
| Terminal notification emitted for a durably unresumable turn | WARN | `conv_session_id`, `reason_code`, `terminal_message_key` |
| Resume dispatch failed | ERROR | `conv_session_id`, `reason`, `target_instance`, `error` |
| Activity hydration served with resume state | DEBUG | `conv_session_id`, `active_resume_id`, `resume_state` |

Never logged by CH: the checkpoint payload body, minted tenant headers (CH forwards, never signs), or any credential.

### Agent Runtime — `backend/logs/agent-runtime.log`

| Event | Level | Key fields |
|---|---|---|
| Checkpoint flush before reporting waiting | INFO | `conv_session_id`, `resume_key`, `payload_bytes`, `flush_duration_ms` |
| Pause could not be persisted | ERROR | `conv_session_id`, `reason` (`transport`, `payload_too_large`, `cc_rejected`), `error` |
| Resume claim acquired / refused | INFO / WARN | `conv_session_id`, `instance_id`, `claim_result` |
| Checkpoint loaded / load failed | INFO / ERROR | `conv_session_id`, `payload_bytes`, `schema_version`, `reason` |
| Turn resumed from checkpoint | INFO | `conv_session_id`, `instance_id`, `resume_id` |
| Resumed turn paused again | INFO | `conv_session_id`, `new_resume_key` |
| Checkpoint schema incompatible with this build | WARN | `conv_session_id`, `payload_schema_version`, `supported` |
| Claim released after failure | WARN | `conv_session_id`, `instance_id`, `reason` |

Correlation hints: a user-reported "approval did nothing" is resolved by following one `conv_session_id` across `control-center.log` (answer recorded → dispatch), `communication-hub.log` (dispatch → dedup → outcome), and `agent-runtime.log` (claim → checkpoint load → resumed). Absence in AR with a CH dispatch line means the dispatch never reached a live instance.

---

## 3. Common Issues

### 3.1 Approval after a restart does nothing / "delegated step timed out or failed"

- **Confirm the deployed build first.** The legacy message means the request was handled by old code (in-process resume path). If CC/AR/CH are not all on this build, this is expected behaviour, not a defect.
- On the new build, expected behaviour is: the confirmation is still presented as pending after any single service restart, and approving continues the turn (a resumed turn shows thinking / using tool, then the reply).
- **Diagnose**: find the `conv_session_id`; in `control-center.log` look for "Resume accepted" and the dispatch; in `communication-hub.log` look for the dispatch and outcome; in `agent-runtime.log` look for claim and checkpoint load.
- **If the answer was recorded but no dispatch exists** → CC-side dispatch failure; re-answering is safe (the stored outcome short-circuits, no double write).
- **If dispatch exists and AR never claimed** → AR unreachable or certificate/tenant-header rejection; check the AR boundary logs and the fleet's certificate state.
- **If the turn resolved as `expired`** → the answer arrived outside `CONVERSATION_TURN_RESUME_TTL_SECONDS`. Live with the terminal message, and raise the TTL if it recurs.

### 3.2 Duplicate approvals / a change applied twice

- Exactly-once is enforced by `idempotency_key` + `write_applied`/`applied_at`, committed with the write. A repeat answer returns the stored effect summary and must **not** re-execute.
- **Check**: `conversation_turn_resume.write_applied` is true once; `applied_at` set once; exactly one `outcome_turn_id`; only one `applied` log line for the key (further ones are `replayed`).
- **Two `applied` lines for one key** is an exactly-once violation: freeze the involved management tool, capture the idempotency key, `resume_id`, and both log lines, and escalate as a data-integrity incident.
- A duplicated *effect in an external system* the tool called is out of scope for this change (no third-party compensation); the platform guarantee is one dispatch of the tool, not one external side effect.
- Never "fix" a duplicate by deleting the resume row or the applied marker — that removes the guard and invites a third application.

### 3.3 Resume contention / "another instance is resuming this turn"

- Normal: duplicate answers, or a reconnect during a resume, hit the claim and are serialised. No action; resolve itself.
- Abnormal: `held_by_other` persisting for many minutes with no active resume → a stale claim from an AR instance that died mid-resume (crash, OOM, node loss).
- **Resolution**: wait for `CONVERSATION_TURN_CLAIM_TTL_SECONDS` (the claim expires and frees the turn), then have the operator re-answer — the answer is idempotent. If the same instance id keeps re-acquiring and dying, remove that instance from the fleet.
- Do **not** clear claim fields by hand; expiry is the supported release path and hand-clearing removes the single-resumer guarantee.

### 3.4 A turn says it is no longer resumable (`resume_failed` / checkpoint unavailable)

- Cause classes: payload purged before the answer arrived (purge horizon shorter than the answerable window), payload over the byte cap, payload schema version produced by a different build, or a checkpoint consumed by an earlier resume attempt that then failed.
- **Diagnose in `control-center.log` / `agent-runtime.log`**: "Checkpoint rejected", "Checkpoint loaded / load failed", "Checkpoint schema incompatible", or a purge line timestamped before the answer.
- **Resolution**: the index is authoritative — the turn resolves terminally with an actionable message; the operator re-issues the request. Nothing was written, so re-issuing is safe.
- **Prevent**: keep `CONVERSATION_TURN_CHECKPOINT_PURGE_AFTER_SECONDS` above `CONVERSATION_TURN_RESUME_TTL_SECONDS`; keep the CC cap and the CH relay guard equal; treat payload schema changes as a compatibility decision in the release (a build must refuse, not mis-deserialise, an unknown schema version).
- **After a version upgrade**, a paused turn created by the previous build may legitimately resolve as incompatible. If this is not acceptable for the environment, drain paused turns before upgrades (see 3.7).

### 3.5 "Pause could not be persisted" (the assistant fails instead of asking for confirmation)

- The pause is only reported as waiting after the checkpoint flush **and** the resume-index write both succeed. This message means one of them failed.
- **Check ordering**: is this rollout's AR running ahead of the CH checkpoint relay, or CH ahead of CC? See `deployment.md` §3 — a new AR without the relay is the most common cause.
- **Check the cap**: `failed_payload_too_large` in AR and a size-guard rejection in CH mean the payload exceeded `CONVERSATION_TURN_CHECKPOINT_MAX_BYTES` (or the CH guard is set lower than CC's).
- **Check CC health**: 5xx on the internal resume/checkpoint routes points at unapplied migration (missing tables/column) — verify `alembic current` reports head.
- The turn ends as a terminal failure; no write occurred. Operator re-issues after the fix.

### 3.6 Checkpoint storage keeps growing

- Payloads are consumed once and purged after the retention horizon or on resolution, while the index row survives.
- **Check**: `conversation_turn_checkpoint_total{event="purged"}` is flat, or `conversation_activity_reaper_total` has no samples → the sweep is not running (reaper loop disabled/stalled in CC). Confirm the loop is alive and the resume purge step is registered in it.
- **Check** for records stuck non-terminal: an abandoned `resuming` record whose claim expired long ago indicates the resolver branch is not reaching it; those rows hold payloads indefinitely until resolved.
- **Emergency**: payloads for terminal records are safe to purge once the outcome is recorded (the index row must remain). Never delete the index row.

### 3.7 Activity says "waiting for your input" but the turn is not answerable

- This is the orphan case and must not happen: `waiting_for_human` is only displayed while a live resume record backs the activity (`active_resume_id` set, unexpired, checkpoint present). A stale waiting row means the Terminal Resolver has not yet swept it, or the resume record was lost/superseded without updating the activity.
- **Immediate remediation**: the reaper resolves waiting rows on its next sweep — wait one sweep interval; the UI then shows the reason-specific terminal card and re-enables input.
- **If it persists across sweeps**: inspect the resume record's state/`expires_at` and the activity row's `active_resume_id`. A live-looking record with a missing checkpoint is resolved as `resume_failed` by design; a `null` `active_resume_id` on a waiting row is a defect — capture both rows and escalate.
- **Operator workaround**: ask the user to start a new conversation turn (new pause supersedes the old record); do not edit rows by hand.
- Treat every occurrence as a monitoring incident (`ResumeOrphanedTurn`), not as routine expiry.

### 3.8 Planned maintenance / release checklist

- Paused turns survive restarts of CC, CH, and AR individually — no need to drain before a restart.
- **Do drain before a schema downgrade or a payload-incompatible upgrade**: have operators answer or abandon pending confirmations, wait for the terminal state, then proceed.
- After any release, verify in `control-center.log` that the reaper swept without error and that resume records show `waiting_for_human` with an `expires_at` in the future.

---

## 4. Master Operations Update Instructions

Update these files in `docs/master/operations/`:

1. **`monitoring.md`**
   - **Key Metrics by Component** table: add rows for pause persisted/failed, resume dispatched/succeeded/failed, orphaned turns, claim contention, terminal resolutions by reason, write-applied/replayed, checkpoint payload size, checkpoint storage/purge, resume latency, and reaper sweep health (all under **Control Center Assistant** / conversational turn supervision).
   - **Dashboards to Create**: add a **Conversational Turn Resume** dashboard (or a panel group on the Control Center Assistant dashboard) with the panels in §1.2.
   - **Alerts to Configure**: add the §1.3 alert table under a new **Conversational Turn Resume Alerts** heading, stating that these counters are new with this change and that the orphaned alert is a zero-tolerance invariant alert.
2. **`logging.md`**
   - **Conversation Turn Lifecycle** and **Intervention Lifecycle (Confirmation / HITL)** tables: update the pause/resume rows to durable semantics (pause persisted, checkpoint flushed, resume dispatched, claim acquired/refused, resumed, re-paused).
   - Add a **Resumable Turn Events** subsection with the per-service event tables from §2, required fields (`conv_session_id`, `resume_id`, `resume_key`, `claimed_by_instance_id`, `attempt_count`, `reason_code`, `payload_bytes`, `resume_outcome`), and explicit sensitive-data exclusions: never log the checkpoint payload body, and never log checkpoint contents as `detail`.
3. **`README.md`** — add a **Conversational Turn Resume** row to the dashboards table and list the new runbook in §Runbooks.
4. **`runbooks/conversational-turn-resume.md`** (new) — operator runbook containing §3 as sections: approval after restart, duplicate approvals, resume contention, checkpoint unavailable, pause could not be persisted, checkpoint storage growth, stale waiting vs unresumable, maintenance checklist. Each section: symptom → signal/log line → action → when to escalate.
5. **`runbooks/control-center-assistant.md`** — cross-reference the new runbook from §4 (turn hangs/timeouts) and §5 (WebSocket reconnect and reply delivery), and correct the guidance that a restart orphans a pending confirmation: on this build a restart no longer loses the pause; only genuine expiry or a lost checkpoint resolves a turn terminally.
6. **`runbooks/agent-runtime.md`** — note that a paused conversational turn is reloadable by any AR instance and that a stale claim expires after `CONVERSATION_TURN_CLAIM_TTL_SECONDS`; add the checkpoint-load-failure branch to its troubleshooting list.
