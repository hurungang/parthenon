# Rollback: Conversational Turn Durability

Focused rollback runbook for the conversational-durability epics: `7127b840ae80` (persistent activity state) and `992bbc77bf6a` (resumable agent turn persistence). Part of the [rollback runbook](rollback.md) — execute its Steps 1–2 first. The schema change is **additive**, so the default rollback is **code-only**.

## Trigger Conditions

- Sustained 401/403 on the internal activity, resume, or checkpoint routes from legitimate CH traffic (check the allowlist and signed tenant headers before rolling back — that is a configuration fix, not a code rollback)
- Pauses cannot be persisted at all (`pause could not be persisted` in `agent-runtime.log`) after the CH relay is confirmed healthy
- Resume claims fail across instances with no consumed checkpoint and no stale claim, blocking all approvals
- Activity indicator regressions at scale (perpetual spinner, vanished bubble) that cannot be attributed to a single stale row

## Step C1 — Stop New AR First, Then CH, Then CC

Reverse of the deploy order: the newest build writes the resume index and checkpoint payloads, so stop **Agent Runtime** first (no new pause writes), then **Communication Hub** (relay and dispatch), then **Control Center** (last writer of the schema). Restart via `parthenon.ps1` on Windows or `./scripts/restart-backend.sh` on macOS.

**Completion condition:** all services healthy at the previous image versions; no resume relay or checkpoint write traffic.

## Step C2 — Code Rollback, Schema Kept (preferred)

Leave both migrations applied. Previous code ignores `conversation_activities`, `conversation_turn_resumes`, `conversation_turn_checkpoints`, and `active_resume_id`.

**Before switching traffic back, handle in-flight paused turns.** Turns paused under the new build are **not resumable by the previous code** — it has no durable checkpoint path and does not consult the resume index. Either:

1. **Drain** — have operators answer or abandon every pending confirmation and wait for the terminal state (bounded by `CONVERSATION_TURN_RESUME_TTL_SECONDS`, default 15 minutes), then roll back; or
2. **Let the TTL expire** — accept that answers during the rollback window return the legacy "delegated step timed out or failed" behaviour, and re-issue the requests afterwards. Nothing is applied on a dead turn, so re-issuing is safe.

Do **not** delete resume rows to "clean up" — a live record must be resolved by the reaper/Terminal Resolver, never by hand; deleting one while the activity still shows waiting recreates exactly the inconsistency this change removed.

**Completion condition:** conversational pause/approve works on the previous build; `alembic current` still reports the same head (no downgrade).

## Step C3 — Schema Rollback (destructive, only if the schema must be removed)

> **Warning — data loss:** `992bbc77bf6a`'s downgrade drops `conversation_turn_resumes` and `conversation_turn_checkpoints` and removes `active_resume_id`. Every paused turn becomes unresumable and applied-marker history is unrecoverable.

1. Confirm AR and CH are stopped (new AR writing to dropped tables produces a failure on every pause).
2. Export the resume index for audit before downgrading — row counts, states, outcomes, terminal reasons, and applied markers per session.
3. Accept the loss explicitly and tell operators that pending confirmations must be re-issued after the rollback.
4. Redeploy the previous Control Center build.
5. Run `alembic downgrade -1` from `backend/` to drop the durable-resume revision (`992bbc77bf6a`).
6. Only if the activity table must also go: run `alembic downgrade -1` again to drop `7127b840ae80` (`conversation_activities` + `activity_state_enum`). This also removes the indicator's persisted state — it is re-derived from in-memory state by the previous build, which is expected.
7. Verify `alembic current` reports the pre-change revision and the tables/types are gone.
8. Re-verify conversational pause/approve on the previous build (legacy in-process path) and a single clean reaper-free startup.

## Rollback Guardrails

- Never downgrade while any new-build service is running.
- Never hand-delete resume index rows, applied markers, or claim fields during a rollback; expiry and the Terminal Resolver are the supported release paths.
- A checkpoint payload purge is not a rollback action — purge deletes payloads only and must leave the index row intact.
- Keep the pre-deployment PostgreSQL backup: restoring it reverts **all** data, including conversation history, not just pause state.
- Do not grant database access to Agent Runtime or Communication Hub to "work around" a rollback problem.
