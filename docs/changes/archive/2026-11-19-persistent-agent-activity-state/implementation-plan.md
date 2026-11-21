# Implementation Plan: persistent-agent-activity-state

## Overview

This change replaces the ephemeral, process-local conversational status signals with a single, persisted, authoritative activity record per conversation session. A new `ConversationActivity` entity (owned and written only by Control Center) records what the assistant is doing right now; Agent Runtime forwards activity transitions through Communication Hub, Communication Hub projects/hydrates the persisted state, and the frontend reads it on (re)connect so the processing indicator is accurate across reload, restart, and server failover. Paused conversational turns are recovered or resolved to a terminal state rather than leaving a stuck spinner.

## Task Checklist

### Phase 1 — Schema & Migration
- [x] 1.1 — Add `ConversationActivity` model + `ActivityState` enum and the `ConversationSession.activity` relationship
- [x] 1.2 — Register the model and generate + review the Alembic migration
- [x] 1.3 — Apply the migration and verify the schema

### Phase 2 — Control Center Persistence & Read Endpoints
- [x] 2.1 — Implement the `ConversationActivityStore` service (upsert / read / terminal resolve)
- [x] 2.2 — Add the internal write endpoint (upsert activity transition)
- [x] 2.3 — Add the internal read endpoint (hydrate current activity)
- [x] 2.4 — Wire `prepare_conversation_turn` / `append_conversation_turn` to set working and terminal states
- [x] 2.5 — Implement the timeout / orphan reaper resolving stale or non-resumable activity

### Phase 3 — Agent Runtime Status-Forwarding
- [x] 3.1 — Enrich activity transitions with state-specific context (tool, delegation, intervention)
- [x] 3.2 — Forward terminal and resume transitions with correct semantics
- [x] 3.3 — Verify AR never writes the DB and forwards all transitions through CH

### Phase 4 — Communication Hub Projection & Status-Answer Rework
- [x] 4.1 — Forward each AR status transition to the CC activity endpoint
- [x] 4.2 — Add CC data-client methods for activity upsert and hydration
- [x] 4.3 — Hydrate current activity from CC on WebSocket connect
- [x] 4.4 — Rework `status_ping` → `status_pong` to read persisted activity, not in-memory state

### Phase 5 — Frontend Parse, Hydration & Bubble Lifecycle
- [x] 5.1 — Extend `parseChatStatus` to accept `waiting_for_human` and terminal states
- [x] 5.2 — Hydrate `chatStatus` on connect from the pushed activity state
- [x] 5.3 — Reconcile the activity bubble lifecycle (waiting state, stuck/vanished bubble)
- [x] 5.4 — Add/verify i18n strings and the pending-intervention indicator

### Phase 6 — Resume, Restart & Failover
- [x] 6.1 — Re-establish a working activity state at the start of every (re)turned conversation
- [x] 6.2 — Verify reconnect hydration end-to-end across reload, restart, and failover
- [x] 6.3 — Resolve restart-abandoned paused turns to a terminal state

### Phase 7 — Tests
- [x] 7.1 — Backend tests: schema, activity endpoints, turn wiring, reaper
- [x] 7.2 — Backend tests: AR/CH forwarding and CH status-answer rework
- [x] 7.3 — Frontend tests: parse, hydration, bubble lifecycle
- [x] 7.4 — E2E tests: real-backend migration + reconnect/restart scenario

### Phase 8 — Deployment & Operations
- [x] 8.1 — Author migration rollout steps and rollback
- [x] 8.2 — Author operations notes (monitoring, logging, common issues)
- [ ] 8.3 — Update master docs (architecture, data-model, technology, QA, deployment, operations)

---

## Phase 1 — Schema & Migration

### 1.1 — Add `ConversationActivity` model + `ActivityState` enum and the `ConversationSession.activity` relationship

Create `backend/app/db/models/conversation_activity.py` with:
- `ActivityState` enum — seven states: `thinking`, `using_tool`, `delegating`, `waiting_for_human`, `finished`, `failed`, `timed_out` (three terminal states: `finished`, `failed`, `timed_out`).
- `ConversationActivity` entity with a `conversation_session_id` unique (0..1 live record per session), nullable `current_turn_id` (→ `conversation_turns.id`), nullable `pending_intervene_request_id` (→ `intervene_requests.id`), nullable `tool_name`, nullable `target_agent_type_id` (→ `agent_types.id`), nullable `detail` (JSON, status-only), `is_terminal` boolean, `started_at`, `last_updated_at`, `finished_at` — matching `docs/changes/persistent-agent-activity-state/data-model.md` exactly.
- Add the `ConversationSession.activity` back-reference relationship in `backend/app/db/models/conversations.py` (relationship only — no column changes). Use `postgresql.ENUM(..., create_type=False)` semantics for the enum (see migration best practices).

**Done when:** the model file exists and mirrors the data-model entity/attribute list; `ConversationSession` exposes an `activity` relationship; no `ConversationSession` column was added.

### 1.2 — Register the model and generate + review the Alembic migration

Import the new model wherever the other conversation models are imported so `alembic revision --autogenerate` detects it, then generate the migration. Review it for: correct `down_revision` chain, `postgresql.ENUM(..., create_type=False)` usage, a unique constraint on `conversation_session_id`, FK `ondelete` behavior matching `ConversationTurn`/`InterveneRequest`, and a reversible `downgrade()`.

**Done when:** a migration file exists under `backend/alembic/versions/` with a correct down-revision, no parameterized DDL, no raw `sa.Enum()` (uses `postgresql.ENUM`), and a reviewed `downgrade()`.

### 1.3 — Apply the migration and verify the schema

Run `alembic upgrade head` (backend working dir) and confirm `alembic current` shows the new revision. Optionally query `information_schema` to confirm the table, the unique index on `conversation_session_id`, and the enum type exist.

**Done when:** `alembic current` reports the latest revision; the `conversation_activity` table and its unique constraint exist in PostgreSQL; no "column does not exist" or "type already exists" errors.

---

## Phase 2 — Control Center Persistence & Read Endpoints

### 2.1 — Implement the `ConversationActivityStore` service (upsert / read / terminal resolve)

Add `backend/app/services/conversations/activity_store.py` with a `ConversationActivityStore` that:
- Upserts exactly one live `ConversationActivity` row per session (atomic create-or-update on `conversation_session_id`).
- Reads the current activity for a session (returns `None` when no live record).
- Resolves a session's activity to a terminal state (`finished` / `failed` / `timed_out`), setting `is_terminal`, `finished_at`, and clearing the resume checkpoint fields appropriately.

All operations are tenant-scoped via the existing request tenant context; no direct DB access is exposed to AR or CH.

**Done when:** the store is implemented with typed inputs, atomic upsert, and a terminal-resolve path; a unit test stub for the store passes.

### 2.2 — Add the internal write endpoint (upsert activity transition)

Add `PUT /internal/data/conversations/{conv_session_id}/activity` to `backend/app/api/v1/internal/session_data.py` (service-cert + `require_internal_tenant_context`). The body accepts `state`, optional `current_turn_id`, `tool_name`, `target_agent_type_id`, `pending_intervene_request_id`, and `detail`. It validates the state against `ActivityState`, resolves the conversation session (404 if missing), and upserts through the store.

**Done when:** the endpoint is reachable via the service-cert path, fails closed (401) without valid signed tenant headers, and upserts the single live row; a backend integration test covers create + update.

### 2.3 — Add the internal read endpoint (hydrate current activity)

Add `GET /internal/data/conversations/{conv_session_id}/activity` to `backend/app/api/v1/internal/session_data.py`. It returns the current activity (or an explicit `null`/`{"activity": null}` body when none exists) and is tenant-scoped and service-cert gated.

**Done when:** the endpoint returns the persisted state for a live session and an explicit null for an idle session; a backend test covers both.

### 2.4 — Wire `prepare_conversation_turn` / `append_conversation_turn` to set working and terminal states

- In `prepare_conversation_turn`, after persisting the user turn, set the session activity to `thinking` (working) with the new user turn id as `current_turn_id`.
- In `append_conversation_turn`, after persisting the agent turn, resolve the activity to `finished` (or, when the last status event is `timeout_or_failed` / a guardrail stop, to the matching terminal state).

**Done when:** starting a turn sets `thinking` and ending a turn sets a terminal state, verified via the read endpoint; no stale `thinking` remains after a completed turn.

### 2.5 — Implement the timeout / orphan reaper resolving stale or non-resumable activity

Add `backend/app/services/conversations/activity_reaper.py` with a `ConversationActivityReaper` background task (scheduled in the CC app startup/lifespan) that:
- Finds non-terminal activity whose `last_updated_at` is older than a configurable threshold, or whose session is `closed`/`archived`/`error` (or whose turn can no longer be resumed).
- Resolves those rows to a terminal state (`timed_out` when the turn watchdog/guardrail expired, `failed` otherwise) and clears resume references.
- Never touches `waiting_for_human` records whose `InterveneRequest` is still `pending` and whose session is still `active`.

**Done when:** the reaper runs on a schedule, resolves stale/orphaned rows to terminal, and leaves live pending-intervention rows untouched; a backend test simulates a stale row and asserts terminal resolution.

---

## Phase 3 — Agent Runtime Status-Forwarding

### 3.1 — Enrich activity transitions with state-specific context (tool, delegation, intervention)

In `backend/app/services/agents/runtime_executor.py` (`_execute_conversation_turn_from_context_inner` and the `emit_status_event` helper), ensure every transition carries the context the persisted record needs: `using_tool` → `tool_name`, `delegating`/`waiting` → `agent_type` (and `receiver_session_id` when known), `waiting_for_human` → a pending-intervention marker. CC resolves the concrete `pending_intervene_request_id` server-side (AR does not need the request id).

**Done when:** the status events streaming over the NDJSON channel include the correct `tool_name`/`agent_type`/intervention context for each state; a backend test inspects the emitted events.

### 3.2 — Forward terminal and resume transitions with correct semantics

Ensure `timeout_or_failed` (watchdog fire, guardrail stop, provider error) and `thinking` (post-resume) transitions continue to emit in the right order, and that a paused `waiting_for_human` transition is followed by either a `thinking` resume transition or a terminal `timeout_or_failed` when the intervention window elapses. No new secret material is added to any transition.

**Done when:** the AR executor's transition sequence for a confirm-before-write pause → resolve → resume is deterministic and carries no sensitive fields; covered by a backend test.

### 3.3 — Verify AR never writes the DB and forwards all transitions through CH

Confirm the activity persistence path is AR → CH → CC only: AR emits transitions over the existing status channel and never invokes a CC activity endpoint directly nor opens a DB connection. Add or extend a structural/unit assertion that AR has no DB access and that the resume registry (`backend/app/agent_runtime/conversation_resume.py`) remains process-local and is complemented (not replaced) by the persisted state.

**Done when:** a structural test confirms AR's data access is CH/CC-http only; the `conversation_resume` registry still works but is no longer the only source of truth for the UI.

---

## Phase 4 — Communication Hub Projection & Status-Answer Rework

### 4.1 — Forward each AR status transition to the CC activity endpoint

In `backend/app/api/ws/chat.py` (`_delegate_conversation_turn_to_agent_runtime`'s streaming handler), for each normalized status event received from AR, call the CC activity upsert (under `_signed_tenant_forwarding`) before pushing to the live socket. Forward `thinking`, `using_tool`, `delegating`, `waiting`, `waiting_for_human`, and terminal `timeout_or_failed`; map the wire status value to the `ActivityState` (e.g. `waiting` with `agent_type` → `delegating`, `waiting_for_human` → `waiting_for_human`, `timeout_or_failed` → `failed`/`timed_out` as appropriate).

**Done when:** every status event in a turn is persisted via CC before/alongside the socket push; a CH integration test records one CC upsert per transition.

### 4.2 — Add CC data-client methods for activity upsert and hydration

Add `upsert_conversation_activity` and `get_conversation_activity` to `backend/app/communication_hub/data_client.py` (using the existing `_post`/`_get` helpers and `internal_httpx_client`, which auto-attaches signed tenant headers). These are the only CH→CC activity calls.

**Done when:** the two client methods exist, use the standard egress path, and fail closed on non-2xx; a unit test with a mocked CC endpoint passes.

### 4.3 — Hydrate current activity from CC on WebSocket connect

In `websocket_chat`, after registration and tenant binding, fetch the current activity via `get_conversation_activity` and push it to the client as a normalized `activity_state` message (state + optional `tool_name`, `agent_type`, `pending_intervention`, `timestamp`). This replaces the current "no on-connect status hydration" gap.

**Done when:** a fresh (or restarted) CH pushes the persisted activity immediately on connect; a CH test asserts the hydration push fires once per connect.

### 4.4 — Rework `status_ping` → `status_pong` to read persisted activity, not in-memory state

Replace the `_pending_turn_tasks` + `ActiveSessionTracker` derivation in the `status_ping` handler with a CC hydration read. `status_pong` now returns the persisted `state` (plus context and a `pending_intervention` flag). Keep the in-memory task registry only for cancellation, not as the status source of truth.

**Done when:** `status_pong` reflects the persisted `ConversationActivity` (verified when the in-memory task dict is empty but a live activity row exists); a CH test asserts the answer comes from CC.

---

## Phase 5 — Frontend Parse, Hydration & Bubble Lifecycle

### 5.1 — Extend `parseChatStatus` to accept `waiting_for_human` and terminal states

In `frontend/src/hooks/useChatSession.ts`, remove the `waiting_for_human` rejection from `parseChatStatus` (currently lines ~148-157), and accept `waiting_for_human`, `finished`, `failed`, `timed_out` alongside the existing kinds. Add a `parseActivityState` helper for the new `activity_state` hydration message, mapping persisted states to `ChatStatus`.

**Done when:** `parseChatStatus`/`parseActivityState` accept all seven persisted states and normalize them to the `ChatStatus` shape; a unit test covers the mapping.

### 5.2 — Hydrate `chatStatus` on connect from the pushed activity state

In `useChatSession`, handle the `activity_state` message on `onmessage` (and extend the `status_pong` handler) so that, on (re)connect, `chatStatus`, `turnInFlight`, and `interventionActiveRef` are reconciled from the hydrated state. A hydrated `waiting_for_human` re-surfaces the pending-intervention indicator; a hydrated terminal state clears `turnInFlight`.

**Done when:** a reconnect hydrates the correct `chatStatus` without an empty window; a frontend test asserts hydration sets state and clears/keeps `turnInFlight` appropriately.

### 5.3 — Reconcile the activity bubble lifecycle (waiting state, stuck/vanished bubble)

In `frontend/src/components/agents/ConversationDialog.tsx`, extend `showThinking`/`standaloneDelegationStatusLine` so `waiting_for_human` renders the pending-intervention indicator continuously (no blank gap), and so terminal states (finished/failed/timed out) clear the bubble rather than leaving it stuck. Use the hydrated state to reconcile a bubble that vanished on a dead socket or lingered after completion.

**Done when:** `waiting_for_human` renders `InterventionPendingIndicator` with no blank gap; a terminal hydration clears the bubble; a frontend test covers the stuck/vanished reconciliation.

### 5.4 — Add/verify i18n strings and the pending-intervention indicator

Add any missing `conversations.sessions.*` i18n keys (e.g. waiting-for-input, terminal-state labels) in the translation catalogs and confirm `InterventionPendingIndicator` renders the waiting state. All UI text flows through `t()` (no hardcoded strings).

**Done when:** the new status labels resolve via `t()` in all locale catalogs used; `InterventionPendingIndicator` renders for `waiting_for_human`.

---

## Phase 6 — Resume, Restart & Failover

### 6.1 — Re-establish a working activity state at the start of every (re)turned conversation

Confirm that resuming a conversation (or re-running a turn after a reconnect) always sets `thinking`/working at `prepare_conversation_turn` (Phase 2.4), so a resumed session never shows an empty status while the assistant is processing. Ensure the `ConversationDialog` resume path does not clear an in-flight activity prematurely.

**Done when:** resuming a still-running conversation re-establishes a visible working/thinking status; a backend + frontend test covers the resume→working transition.

### 6.2 — Verify reconnect hydration end-to-end across reload, restart, and failover

Manually and via E2E verify: a page reload while `waiting_for_human` restores the pending-intervention indicator; a CH restart hydrates the correct persisted state; a conversation handed to a different CH instance still pushes the authoritative status. Confirm the status never depends on process-local memory.

**Done when:** the reconnect/restart/failover scenario is validated in the E2E test (real backend) and the UI shows the persisted status immediately on reconnect.

### 6.3 — Resolve restart-abandoned paused turns to a terminal state

Verify the reaper (Phase 2.5) resolves a `waiting_for_human` record whose session/process can no longer resume (e.g. after an AR restart whose in-memory resume registry was lost) to `timed_out`/`failed`, rather than leaving a perpetual "waiting" indicator. Confirm the user sees a clear terminal message instead of a stuck bubble.

**Done when:** a backend test simulates a lost resume registry + stale activity and asserts terminal resolution; the UI renders the terminal state on the next connect.

---

## Phase 7 — Tests

### 7.1 — Backend tests: schema, activity endpoints, turn wiring, reaper

Add unit/integration tests under `backend/tests/` for the `ConversationActivity` model + migration (including a real-DB negative test), the write/read endpoints (tenant isolation, fail-closed), the `prepare`/`append` turn wiring, and the reaper (stale resolution, pending-intervention protection).

**Done when:** tests pass against the real schema (migration applied in fixture setup); `alembic current` matches the latest revision before the suite runs.

### 7.2 — Backend tests: AR/CH forwarding and CH status-answer rework

Add tests for AR transition enrichment, CH→CC forwarding (one upsert per transition), and the reworked `status_pong` (reads persisted state, not in-memory). Include a structural test that AR never opens a DB connection.

**Done when:** the forwarding and status-answer tests pass; the AR-no-DB structural test is green.

### 7.3 — Frontend tests: parse, hydration, bubble lifecycle

Add tests under `frontend/src/__tests__/` for `parseChatStatus`/`parseActivityState` (all seven states), connect-time hydration, and the `ConversationDialog` bubble lifecycle (waiting state, terminal clearing, stuck/vanished reconciliation).

**Done when:** frontend tests pass with the JSON reporter; the new parse/hydration paths are covered.

### 7.4 — E2E tests: real-backend migration + reconnect/restart scenario

Add E2E coverage under `e2e/tests/` including at least one real-backend variant (labeled `Real Backend Integration - persistent agent activity state`) that exercises the migration and a reconnect/restart while `waiting_for_human`. Mocked variants cover the remaining state transitions for speed.

**Done when:** the real-backend E2E variant passes against an applied migration; the reconnect restores the persisted status.

---

## Phase 8 — Deployment & Operations

### 8.1 — Author migration rollout steps and rollback

Document the ordered deployment steps (apply `alembic upgrade head` on CC before rolling AR/CH, restart backend services via the project management script), and a rollback procedure (downgrade + service restart) for `docs/changes/persistent-agent-activity-state/deployment.md`.

**Done when:** deployment steps are ordered and reversible; the migration is listed as a prerequisite before AR/CH restart.

### 8.2 — Author operations notes (monitoring, logging, common issues)

Document in `docs/changes/persistent-agent-activity-state/operations.md`: new logs (activity upsert/hydration in `control-center.log`, forwarding in `communication-hub.log`), staleness metrics for the reaper, and common issues (stale `waiting_for_human` after restart, CH hydration failures).

**Done when:** operations notes cover monitoring, logging, and known failure modes with resolution guidance.

### 8.3 — Update master docs (architecture, data-model, technology, QA, deployment, operations)

Apply the master-update instructions from `architecture.md`, `data-model.md`, and `spec-change.md` to `docs/master/`, and add the `Code Reference Map` entries from `tech-spec.md` to the master technology docs.

**Done when:** master architecture, data-model, technology (code reference map), QA, deployment, and operations docs reflect the persisted activity state and its ownership boundary (CC-owned, AR/CH read-only via CC).

---

## Completion Checklist

- [x] `ConversationActivity` model + migration applied and verified against PostgreSQL
- [x] CC owns the single authoritative activity row; write/read endpoints are service-cert + tenant-scoped
- [x] `prepare`/`append` turn set working and terminal states; the reaper resolves stale/orphaned activity
- [x] AR forwards transitions through CH only and never writes the DB
- [x] CH projects/hydrates the persisted state; `status_pong` reads CC, not in-memory state
- [x] Frontend accepts all seven states, hydrates on connect, and shows no blank gaps or stuck spinners
- [x] Reconnect, restart, and failover restore the persisted status; abandoned pauses resolve to a terminal state
- [x] Backend, frontend, and E2E (real-backend) tests pass
- [ ] Deployment and operations docs authored; master docs updated
