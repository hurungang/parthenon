# Operations: persistent-agent-activity-state

Operating notes for the persisted "current agent activity" state (`ConversationActivity`). The chat processing indicator is now driven by a single authoritative CC-persisted record rather than process-local CH state; a CC timeout/orphan reaper resolves stale or non-resumable activity to a terminal state.

## 1. Monitoring

New signals to instrument (most are log-derived until OTel counters ship, consistent with the Control Center Assistant pattern):

| Metric / signal | Source | Why it matters |
|-----------------|--------|----------------|
| Non-terminal `conversation_activity` rows past the staleness threshold (gauge) | CC (reaper scan) | Primary staleness signal — a rising count means the reaper is not resolving work (hung turn, lost resume registry) |
| Reaper resolutions per interval (by terminal state `finished`/`failed`/`timed_out`) | CC | Confirms the reaper is advancing orphaned/stale activity rather than leaving a perpetual spinner |
| CH activity hydration failures (`GET .../activity` non-2xx) | CH → CC | Hydration failure = on-connect `activity_state` is empty/stale; users see a blank gap |
| CH activity forward failures (`PUT .../activity` non-2xx) | CH → CC | A dropped forward = the persisted state lags the live transition; bubble can go stale |
| `status_pong` answered from persisted state (vs in-memory) | CH | Verifies the status-answer rework; a regression re-introduces stuck/vanished indicators |
| `activity_state` push count on WebSocket connect | CH | Confirms hydration fires once per connect (reload/reconnect correctness) |
| `waiting_for_human` rows with a still-pending `InterveneRequest` (gauge) | CC | Should be stable/non-zero only while an intervention is legitimately outstanding |

Alerts to add:
- `ConversationActivityStaleBacklog` — non-terminal rows past threshold > 0 for a sustained window → Warning (investigate reaper health / hung AR turn).
- `ConversationActivityHydrationFailure` — CH hydration failure rate > 0 for 5 min → Critical (users cannot recover status on reconnect).
- `ConversationActivityForwardFailure` — CH forward failure rate sustained above baseline → Warning.

Dashboards: add a **Conversation Activity State** panel group (staleness gauge, reaper resolution rate, hydration/forward failure rate, `waiting_for_human` gauge) under the Control Center Assistant / conversational surface.

## 2. Logging

Follow the existing structured-log conventions (`backend/logs/*.log`, rotation at ~10 MB with `.1`/`.2` retained; also shipped via OTEL → Loki).

| Event (proposed) | Level | Log file | When logged |
|------------------|-------|----------|-------------|
| `activity.upsert` (state, `conv_session_id`, optional `tool_name`/`agent_type`/`pending_intervene_request_id`) | DEBUG/INFO | `control-center.log` | CC persists an activity transition via the internal write endpoint |
| `activity.hydrated` (state, `conv_session_id`) | DEBUG | `control-center.log` | CC serves a current-activity read for CH on connect/status answer |
| `activity.resolved_terminal` (from_state → to_state, reason) | INFO | `control-center.log` | Store or reaper resolves a row to a terminal state |
| `activity.reaper.scan` (scanned, resolved, skipped) | DEBUG/INFO | `control-center.log` | Reaper periodic pass; `skipped` = still-pending interventions on active sessions |
| `activity.forward` (state, `conv_session_id`) | DEBUG | `communication-hub.log` | CH forwards an AR transition to CC before the socket push |
| `activity.hydrate_failed` (error/status) | WARN/ERROR | `communication-hub.log` | CH hydration read from CC failed |
| `activity.forward_failed` (error/status) | WARN/ERROR | `communication-hub.log` | CH forward write to CC failed |
| transition emission enriched with tool/delegation/intervention context | DEBUG | `agent-runtime.log` | AR emits a transition carrying state-specific context |

Sensitive-data exclusions (must be enforced at the store/endpoint layer, not just by convention): the persisted `detail` and context fields carry status-only context (tool name, delegation target, pending intervention id) — never identity tokens, DB credentials, or decrypted secrets. Log operational identifiers only.

## 3. Common Issues

**Stale `waiting_for_human` after an AR restart (lost in-memory resume registry)**
- Symptom: a conversation shows "waiting for your input" indefinitely after AR restarts mid-intervention.
- Resolution: the CC reaper resolves the abandoned row to `timed_out`/`failed`; on next connect the user sees a clear terminal message instead of a stuck bubble. If it does not resolve, check the reaper is running and its staleness threshold (see Monitoring).

**Reconnect shows no status (blank gap)**
- Symptom: reload/reopen mid-turn shows no indicator.
- Resolution: check CH → CC hydration (`activity.hydrate_failed` in `communication-hub.log`; CC `GET .../activity`). Verify the new internal activity routes are allowlisted for `communication_hub` under `INTERNAL_API_POLICY_MODE=enforce` (401 fail-closed). Verify the migration was applied (`column does not exist` → `alembic upgrade head`).

**Stuck spinner after completion / spinner resurrected**
- Symptom: indicator keeps spinning after `finished`, or a late `thinking` re-opens it.
- Resolution: terminal states must be sticky and never overwritten by earlier states. Confirm `status_pong` reads the persisted state, not in-memory `_pending_turn_tasks`; confirm terminal resolution is applied on `append-turn`.

**Live status diverges from persisted status**
- Symptom: the bubble shows a state that doesn't match the DB row.
- Resolution: a forward was dropped (`activity.forward_failed`). Re-check CH forwarding of every transition; reconcile on next connect (hydration).

**Internal 401 on new activity endpoints**
- Symptom: CH logs fail-closed 401s for `PUT`/`GET .../activity`.
- Resolution: add the two routes to the `communication_hub` caller-scoped allowlist; confirm service cert + signed tenant headers are present (CH is forward-only, never a signer).

**Intervention / resume flow**
- Operator approval/denial stays in the existing intervention dialog; the persisted `waiting_for_human` state surfaces the pending intervention on reconnect. A turn can be resumed on any AR instance because the resume checkpoint (`current_turn_id`, `pending_intervene_request_id`) lives on the persisted activity record.

## 4. Master Operations Update Instructions

Update in `docs/master/operations/`:

- **`monitoring.md`** — add the Conversation Activity State metric rows (staleness gauge, reaper resolution rate, hydration/forward failures, `status_pong` correctness, `waiting_for_human` gauge) and the two alerts (`ConversationActivityStaleBacklog`, `ConversationActivityHydrationFailure`); add the panel group to the Dashboards section.
- **`logging.md`** — add a "Conversation Activity State" subsection (upsert/hydrated/resolved_terminal/reaper events in `control-center.log`; forward/hydrate failures in `communication-hub.log`; enriched transition emission in `agent-runtime.log`) with the sensitive-data exclusions, adjacent to the Control Center Assistant / Conversation Turn Lifecycle sections.
- **`runbooks/control-center-assistant.md`** — extend with triage for activity-state staleness, reconnect hydration failures, and stuck/vanished bubble reconciliation (or add a dedicated `conversation-activity-state.md` runbook and link it from `README.md`).
- **`README.md`** — add the new dashboard to the Dashboards table and the new runbook to the Runbooks table.
