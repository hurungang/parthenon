# Deployment: Resumable Agent Turn Persistence

Deployment notes for making paused conversational turns durably resumable: Control Center (CC) owns the resume index and the opaque checkpoint payload, Agent Runtime (AR) persists/loads state only through Communication Hub (CH) over mTLS, and the activity reaper becomes the Terminal Resolver.

**Change flags**: `has_db_changes: true` (two new tables + one nullable column on `conversation_activity`), `has_deployment_changes: true`.

**Headline constraint**: only CC touches PostgreSQL. This change adds **no** new service, container, datastore, credential, or external dependency — checkpoint transport rides the existing CC internal data plane.

---

## 1. Environment Variables

Four new settings, all optional with working defaults. They live in CC settings (`backend/app/core/config.py`) and are wired from environment variables; no existing variable changes meaning.

| Variable | Consumed by | Default | Purpose |
|---|---|---|---|
| `CONVERSATION_TURN_RESUME_TTL_SECONDS` | Control Center | `900` | Answerable window for a paused turn. Must agree with the intervention window (`conversation_intervention_timeout_seconds`) — a resume record's `expires_at` mirrors the pending `InterveneRequest`. Answering later resolves the turn terminally as `expired`. |
| `CONVERSATION_TURN_CLAIM_TTL_SECONDS` | Control Center | `45` | Lease length of the single-active-resumer claim (`claim_expires_at`). Also the failover bound: after an AR instance dies mid-resume, the turn becomes claimable again after this interval. Keep it comfortably above one resume's expected setup time (checkpoint load + agent rebuild) and well below the resume watchdog. |
| `CONVERSATION_TURN_CHECKPOINT_MAX_BYTES` | Control Center (+ CH relay guard) | `2097152` (~2 MB) | Hard cap on a stored checkpoint payload. Oversize payloads are rejected at write time, so the pause reports "could not be persisted" rather than silently truncating. **The CH relay size guard must not be lower than the CC cap** — set both to the same value in a deployment so a payload accepted by AR is not rejected in transit. |
| `CONVERSATION_TURN_CHECKPOINT_PURGE_AFTER_SECONDS` | Control Center | `3600` | Retention horizon for checkpoint payloads after resolution. The payload is deleted; the resume index row, outcome turn, and applied marker survive for audit. |

Deployment guidance:

- **No new secret.** None of the four values is sensitive.
- **CC is authoritative.** Claim expiry and the answerable window are computed by CC, so a mismatch across services cannot change lifecycle behaviour.
- **Tuning, not required config.** Leave defaults unless the environment's operator-answer latency (raise the resume TTL) or checkpoint sizes (raise the byte cap) demand otherwise. A very large cap directly increases `conversation_turn_checkpoint` storage.
- **Not set on AR/CH:** AR/CH receive no new variables except the shared byte-cap value used by the CH relay guard (if implemented as a CH setting, keep it equal to CC's).

---

## 2. Infrastructure Changes

- **No new services or containers.** Service inventory (`nginx`, `control-center`, `agent-runtime`, `communication-hub`, `postgres`, `redis`, `otel-collector`, `web-ui`, optional Keycloak) is unchanged.
- **No new external dependency.** Checkpoint persistence is CC-mediated over the existing mTLS internal API. AR gains no datastore endpoint, credential, or Redis usage; CH persists nothing.
- **Redis is not in the resume path.** Paused-turn durability lives entirely in PostgreSQL. A Redis flush or outage does not lose a paused turn.
- **Storage growth (the one real capacity change).** `conversation_turn_checkpoint` holds opaque payloads of up to `CONVERSATION_TURN_CHECKPOINT_MAX_BYTES` each, for as long as a turn is paused plus the purge horizon. Size the CC database for concurrent-paused-turn count × typical payload size (expect far below the cap), and include the table in database-size trending.
- **Scaling becomes safer, not harder.** Because a paused turn is loadable by any AR instance, horizontal AR scaling and instance replacement no longer orphan in-flight work. No sticky-session or session-affinity requirement is introduced.
- **CH replicas:** dispatch de-duplication combines a per-conversation in-flight guard (per CH process), the stored-outcome short-circuit in CC, and the AR turn claim (CC-arbitrated). Multiple CH replicas are therefore supported, but the in-flight guard alone is not a global lock — the AR claim is the authoritative single-resumer guarantee. Do not rely on CH affinity for correctness.
- **No migration-time downtime for unrelated features.** The schema change is additive; old code continues to run against the new schema.

---

## 3. Migration Steps

Ordered. Assumes an in-place upgrade of an existing deployment; the same sequence works for a fresh environment (migration runs as part of first-time bootstrap).

1. **Pre-flight — verify current head.** From `backend/`, confirm the database revision matches the pre-change head and that no unrelated migration is pending. Record the active revision for rollback.
2. **Pre-flight — back up PostgreSQL.** A logical backup is sufficient; the new tables are additive, but rollback of this change *drops* them.
3. **Pre-flight — review the generated migration** in `backend/alembic/versions/` before applying. Confirm:
   - `down_revision` chains onto the current head.
   - `conversation_turn_resume` and `conversation_turn_checkpoint` are created, plus a nullable `active_resume_id` on `conversation_activity`.
   - The "at most one live resume record per conversation session" rule is expressed as a **partial** unique index (scoped to non-terminal rows), not a plain unique constraint — a plain one would block any second pause in the same session.
   - `idempotency_key` carries a global unique constraint.
   - Enum types are handled with `create_type=False` at the migration level (they are created from the model import), and all DDL is non-parameterised.
   - `downgrade()` is reversible (drops both tables and the column).
4. **Stop new conversational work from being *created* on new code before the schema exists.** Practically: apply the migration **before** any new build starts.
5. **Apply the migration from Control Center**: `alembic upgrade head` (from `backend/`). Only CC runs migrations — never AR or CH.
6. **Verify**: `alembic current` reports the new head; both tables exist; `conversation_activity.active_resume_id` is nullable. No backfill is required — nothing needs to be populated for existing rows.
7. **Roll out Control Center first** (new build). CC must be the first service on the new code because it owns the new tables, the resume endpoints, the Terminal Resolver and the applied-marker chokepoint.
8. **Roll out Communication Hub second.** New CH serves the AR-facing checkpoint relay routes (`/internal/checkpoint/...`) and the de-duplicated resume dispatch. New CH against the previous AR is compatible for job-path work; conversation-scoped resumes against an old AR still take the legacy in-process path.
9. **Roll out Agent Runtime third.** New AR writes checkpoints through CH and resumes from CC-owned state. **Do not start the new AR before the new CH is serving the checkpoint relay** — a pause on a new AR with no relay up cannot persist and resolves terminally with "pause could not be persisted".
10. **Restart in a controlled order:** CC → CH → AR (then `nginx`/web UI). On Windows use `parthenon.ps1 restart -Services backend -Force`; on macOS use `./scripts/restart-backend.sh`. Note the platform's standard bootstrap order is CC → AR → CH; when a single full-stack restart is used, accept a short AR-before-CH window and schedule the release outside active approvals (turns pausing in that window resolve terminally, never silently).
11. **Deploy the frontend** (recovery vocabulary, terminal card, sessions badges). The frontend tolerates the new optional fields being absent, so it can also ship after the backend.
12. **Post-deploy verification:**
    - Pause a turn (ask the assistant for a change that needs confirmation), confirm it shows as waiting.
    - Restart AR only; confirm the pending confirmation is still presented as actionable.
    - Approve; confirm the resumed reply arrives once, in order, and the confirmed change landed exactly once.
    - Restart CH, then CC, and repeat on a separate paused turn.
    - Confirm a second AR instance can serve a resume (scale to 2, pause on one, answer through the other).
    - Confirm no service other than CC established a database connection, and inspect one stored payload to confirm it carries no tokens or credentials.
    - Check the reaper log for a successful sweep and no unexpected terminal resolutions.
13. **Watch the new signals for one full answerable window** (≥ `CONVERSATION_TURN_RESUME_TTL_SECONDS`) before declaring the rollout complete.

Compatibility window notes:

- New CC + old AR: supported. Old AR keeps using its in-process resume path; new resume endpoints simply go unused for conversation-scoped work.
- New CH + old CC: **not** supported — the checkpoint relay target routes do not exist on old CC. CC must be upgraded first.
- Old CC + new AR: **not** supported — checkpoint writes fail. Never roll AR forward ahead of CC.

---

## 4. Rollback Procedure

Two distinct rollbacks. Prefer the first.

### 4.1 Code-only rollback (default, non-destructive)

Use when the new build misbehaves but the schema is fine. The schema change is additive, so old code runs against it unchanged.

1. Redeploy the previous builds in reverse dependency order: stop the new **AR** first (stop new checkpoint writes), then **CH**, then **CC**, then the frontend.
2. Leave the migration applied. Old code ignores `conversation_turn_resume`, `conversation_turn_checkpoint`, and `active_resume_id`.
3. **In-flight paused turns created on the new schema are not resumable by old code.** Old AR has no durable checkpoint path and old CH/CC do not consult the resume index — an operator answering one of these gets the legacy "delegated step timed out or failed" behaviour. This is expected and finite: those turns expire with their intervention window.
4. Confirm `alembic current` still reports the new head (do not downgrade), and verify conversational chat works on the previous build.

### 4.2 Schema rollback (`alembic downgrade -1`, destructive)

Use only when the new schema itself must be removed (e.g. a constraint is wrong and a corrected migration cannot be shipped forward quickly).

1. **Stop AR, then CH first.** New AR writes to the new tables; a downgrade under a running new AR produces write failures on every pause.
2. **Export the resume index for audit** (`conversation_turn_resume`, `conversation_turn_checkpoint` row counts, states, outcomes, applied markers). The downgrade drops them; applied-marker history is not recoverable afterwards.
3. **Accept the loss explicitly**: every paused turn created under the new schema becomes unresumable. Operators with pending confirmations must re-issue the request after the rollback.
4. Redeploy the previous CC build.
5. Run `alembic downgrade -1` from `backend/` and verify `alembic current` reports the pre-change head and both tables are gone.
6. Re-verify conversational pause/approve behaviour on the previous build (legacy in-process path).
7. If a corrected migration follows later, re-apply `alembic upgrade head`; no data backfill is needed, but any pause created during the rollback window is already lost.

### 4.3 Rollback guardrails

- Never downgrade while any new-build service is running.
- Never delete rows from `conversation_turn_resume` to "clean up" — unresolved records are resolved by the Terminal Resolver, not by hand; deleting a live record while activity still shows waiting recreates the exact inconsistency this change removes.
- A payload purge is not a rollback action: purge removes payloads only, and the index row must survive.
- After any rollback, verify no orphaned payloads remain if the schema was downgraded (the tables are gone, so verify only that CC logs no resume-endpoint 500s).

---

## 5. Master Deployment Update Instructions

Update these files in `docs/master/deployment/`:

1. **`environment-variables.md`** — add a **Conversational Turn Resume** subsection (under the Control Center / Agent Engine area) with the four variables, defaults, consumer service, and the notes: no secret; resume TTL must agree with the intervention window; claim TTL is also the failover bound; the CH relay size guard must not be lower than the CC byte cap; purge horizon deletes payloads but retains the index.
2. **`services.md`** — no inventory change. Add to the rollout-order guidance: conversational turn resume deploys **CC → CH → AR → frontend** (CC owns the schema and endpoints; AR needs the CH relay before it can persist a pause). Add to **Data Access Boundaries**: paused-turn checkpoint state is CC-owned, AR is a courier, CH persists nothing — the existing "AR: None / CH: None" rows are unchanged by this feature.
3. **`database-migrations.md`** — add the migration row (revision, file, description, tables added/modified) and a note: **additive**; creates `conversation_turn_resume` and `conversation_turn_checkpoint`, adds nullable `conversation_activity.active_resume_id`, includes a partial unique index for one live resume per session and a unique `idempotency_key`; no backfill; `downgrade()` drops both tables and the column and therefore destroys all paused-turn state (export before downgrade); CC-only — AR/CH are unaffected at the schema level.
4. **`rollback.md`** — add a **Change-Specific Rollback: Resumable Agent Turn Persistence** section mirroring §4 above: trigger conditions, code-only rollback (preferred, keeps schema), the in-flight-paused-turn caveat, destructive schema rollback with export-before-downgrade, stop order (AR → CH → CC), and the guardrail that the resume index is never hand-deleted.
5. **`README.md`** — add a "Conversational Turn Resume Rollout Order" block to the deployment-rollout list: migrate on CC → CC → CH → AR → frontend → verify across an AR restart and a second-instance resume → watch the new signals for one answerable window.
6. **No change required** to `first-time-deployment.md` (defaults apply; the migration is part of the normal head) or `configuration-files.md` (no platform config file is added).
