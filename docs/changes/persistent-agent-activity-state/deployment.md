# Deployment: persistent-agent-activity-state

Persists a single authoritative "current agent activity" record (`ConversationActivity`) in Control Center so the chat processing indicator is correct across reload, restart, and server failover. This is an additive DB change (new table + enum migration) plus a shift of the live-status source of truth from process-local CH state to CC-persisted state.

## 1. Environment Variables

No mandatory new environment variables.

| Variable | Service | Secret | Default / behavior |
|----------|---------|--------|--------------------|
| `CONVERSATION_ACTIVITY_STALE_SECONDS` | CC | | Configurable staleness threshold for the timeout/orphan reaper (how old a non-terminal activity row must be before it resolves to a terminal state). Unset → service-level default. Confirm the final name at implementation. |

Notes:
- No new DB/Redis/OIDC credentials — AR and CH gain **no** direct database path; the activity endpoints are reached over the existing internal HTTP (mTLS + signed tenant headers) path.
- **Internal allowlist** (existing var, relevant here): if `INTERNAL_API_POLICY_MODE=enforce`, the two new CC routes — `PUT`/`GET /internal/data/conversations/{conv_session_id}/activity` — must be allowlisted for the `communication_hub` caller type. Verify before cutover to avoid fail-closed 401s.
- No sticky-session configuration is introduced or required for chat status (see Infrastructure Changes).

## 2. Infrastructure Changes

- **No new services, containers, or pods.** No scaling limits change.
- **Scaling / failover of the chat-status path is enabled**: multiple CH/AR instances now all read the authoritative activity from CC; the shared PostgreSQL record is the source of truth. No sticky session or session-affinity requirement is needed for a correct processing indicator — any CH instance can hydrate and serve the current status on (re)connect.
- **CH role change (not a topology change)**: CH's in-memory status tracking becomes a read-through projection/cache; the `status_pong` answer and on-connect `activity_state` push now read CC-persisted state rather than process-local `ActiveSessionTracker`/`_pending_turn_tasks` derivation. The in-memory task registry is retained for **cancellation only**.
- **CC role change**: CC becomes the sole owner/writer of the `conversation_activity` table and runs the timeout/orphan reaper background task.
- **Data access boundaries unchanged**: PostgreSQL remains owned solely by Control Center; AR/CH read activity only via CC over mTLS.
- **Internal API surface grows** by two CC routes (activity upsert + hydration) — confirm the caller-scoped allowlist (see Environment Variables).

## 3. Migration Steps

Deploy order: **Control Center → Communication Hub → Agent Runtime → Web UI** (CC owns the migration and the new endpoints; CH forwards/hydrates against those endpoints; AR enriches transition context last — its existing transitions remain backward compatible with an old CH).

1. **Backup** the PostgreSQL database and record the current `alembic_version`.
2. **Apply the migration** before rolling other services: `cd backend && python -m alembic upgrade head`.
3. **Verify** `python -m alembic current` reports the new head revision; confirm the `conversation_activity` table, its unique `conversation_session_id` constraint, and the `activity_state` enum exist.
4. **Deploy/restart Control Center** (new model + store + reaper + internal endpoints are loaded at startup). Confirm `/health` passes.
5. **Deploy Communication Hub** (activity forwarding, on-connect hydration, `status_pong` reads CC). Confirm `/health` passes.
6. **Deploy Agent Runtime** (enriched activity transitions with tool/delegation/intervention context). Confirm `/health` passes.
7. **Deploy Web UI** (parse full state model, hydrate on connect, bubble lifecycle).
8. **Validate**: run the real-backend E2E variant (`Real Backend Integration - Conversation Activity State`) and a manual reload/restart/failover smoke check (start a turn, reload mid-`waiting_for_human`, restart CH, reconnect) to confirm the persisted status is hydrated.

Docker Compose / self-hosted: restart via the management script in standard order (`infra → control-center → agent-runtime → communication-hub → frontend`), or `.\parthenon.ps1 restart -Services backend -Force` after the migration.

## 4. Rollback Procedure

The migration is **additive** (new table + new enum only; no existing table/column modified or dropped), so the common case is **code-only rollback** — the new table can be left in place and ignored by the previous code.

**Code-only rollback (preferred):**
1. Revert Web UI, Agent Runtime, Communication Hub, and Control Center images to last-known-good tags in reverse order (CH → AR → CC, or all backend services together via the management script).
2. The previous CH ignores `activity_state` messages and re-derives status from in-memory state; the previous frontend tolerates the old `status_pong` shape. No data migration reversal needed.

**Full rollback (schema removal — only if the table must be removed):**
1. Stop the backend services (leave PostgreSQL/Redis running).
2. Run `python -m alembic downgrade -1` from `backend/` to drop `conversation_activity` and the `activity_state` enum type.
3. Redeploy previous images in standard startup order (CC → AR → CH), then Web UI.
4. Validate via the standard smoke test.

Data-loss note: `conversation_activity` holds only transient "what is the assistant doing right now" state. Dropping it loses current-activity indicators only; they are re-derived on the next turn. No conversation history, intervention requests, or business data is affected.

## 5. Master Deployment Update Instructions

Update in `docs/master/deployment/`:

- **`database-migrations.md`** — add a Migration History row for the new revision: creates `conversation_activity` table + `activity_state` enum (additive; one live row per session via unique `conversation_session_id`; three terminal states). Note the additive/rollback behavior.
- **`services.md`** — update the Control Center role (persisted activity-state owner + timeout/orphan reaper) and the Communication Hub role (projects/hydrates authoritative activity; live-status source of truth is now CC, not CH's in-memory tracker); add a one-line Agent Runtime note that activity transitions are forwarded to CC for persistence. Data Access Boundaries table is unchanged but re-confirm.
- **`environment-variables.md`** — add `CONVERSATION_ACTIVITY_STALE_SECONDS` (CC) and a note that the two new internal activity routes must be allowlisted for `communication_hub` under `INTERNAL_API_POLICY_MODE=enforce`.
- **`rollback.md`** — add a "Change-Specific Rollback: Persistent Agent Activity State" section (code-only-first, additive-migration caveat, order CH → AR → CC).
- **`README.md`** — add a "Persistent Agent Activity State Rollout Order" block (CC → CH → AR → Web UI) mirroring the other rollout-order sections.
