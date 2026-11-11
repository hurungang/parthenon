# Test Plan: persistent-agent-activity-state

## Test Strategy

Overall approach: this change replaces ephemeral, process-local activity signals with a single authoritative `ConversationActivity` record persisted by Control Center. Testing is layered to catch failures at the exact boundary where the old behavior diverges from the new, with heavy emphasis on **real-database** and **cross-service** validation because the failure modes (stuck spinner, blank gap, lost in-flight work) only manifest across process/restart boundaries.

- **Unit tests (backend)** — `ConversationActivityStore` upsert/read/terminal-resolution semantics; `ActivityState` enum transitions; CH data-client `upsert_conversation_activity`/`get_conversation_activity`; reaper resolution logic; AR status-event emission. Mock DB/HTTP boundaries.
- **Integration tests (backend, real DB)** — verify the schema change actually took effect (query `information_schema`), verify one-live-row-per-session upsert behavior, verify `prepare-turn`→`thinking` and `append-turn`→terminal state, verify fail-closed behavior of the internal endpoints without valid service cert/tenant headers. Uses the real test database with Alembic migrations applied.
- **Frontend unit/component tests** — `useChatSession` hydration of `activity_state`/`status_pong`, `parseActivityState`, `parseChatStatus`, `isTurnInFlight`/`markTurnInFlight` state machine, `ConversationDialog` bubble lifecycle (waiting-state continuity, terminal-state clearing), `InterventionPendingIndicator` re-arming.
- **E2E tests** — full conversational flow with the activity bubble; at least ONE **real-backend** variant (no mocks) exercising the real DB migration and real WebSocket, labeled `test.describe('Real Backend Integration - Conversation Activity State')`.
- **Manual testing** — service restart mid-turn, multi-instance failover, and session reload/reopen checks that are impractical to fully automate in CI.

## Coverage Areas

| Area | Why it's critical |
|------|-------------------|
| **Schema / migration** | `conversation_activity` table + `ActivityState` enum is the single source of truth. If the migration is not applied or the column/nullable/constraint properties are wrong, every other layer fails silently or the backend 500s. |
| **`ConversationActivityStore` (CC)** | The only writer. Upsert must be atomic and idempotent so one live row per session holds true; terminal-resolution must not overwrite a pending intervention on an active session. |
| **Internal write/read endpoints (CC)** | `PUT`/`GET` `/internal/data/conversations/{conv_session_id}/activity` must fail closed (401) without a valid service certificate + signed tenant context — a security boundary, not just a data path. |
| **CH status pipeline** | Forwards every AR transition to CC and pushes the normalized status to the live socket; hydrates persisted activity on connect. A dropped forward = stale bubble. |
| **AR conversational executor** | Emits correct transitions (thinking / using_tool / delegating / waiting / waiting_for_human / timeout_or_failed / delegation_resumed) with state-specific context, and never writes the DB. |
| **`prepare-turn` / `append-turn` (CC)** | Entry/exit bookends of a turn: `thinking` on prepare, terminal (`finished`/`failed`/`timed_out`) on append. Wrong bookends = stuck or vanishing spinner. |
| **`status_pong` / `activity_state` messages** | `status_pong` must report turn-in-flight / intervention-pending from the **persisted** state, not in-memory. `activity_state` on connect carries the hydrated record. |
| **Frontend `useChatSession` + `ConversationDialog`** | The only user-visible surface. Must render the bubble continuously for `waiting_for_human`, clear it on terminal states, and never show a blank gap or stuck spinner. |
| **`ConversationActivityReaper` (CC)** | Stale/orphaned activity must resolve to a terminal state (never a perpetual "working"/"waiting"), while protecting still-pending interventions on active sessions. |
| **Privacy / tenant scoping** | Persisted record must contain status-only context (tool name, delegation target, pending intervention id, detail) — never tokens/credentials/secrets; scoped per conversation and per tenant. |

## Critical Scenarios

### Accurate live status
- **WHEN** the assistant is working through a turn **THEN** the chat window shows a visible indicator that matches the actual current activity (thinking, using_tool, delegating, waiting_for_human).
- **WHEN** the assistant transitions between activities (e.g. thinking → using_tool → thinking) **THEN** the indicator updates promptly without lingering in the previous state.
- **WHEN** the assistant finishes a turn successfully **THEN** the indicator stops and a clear finished state is shown, and it never keeps spinning after completion.
- **WHEN** a turn fails or times out **THEN** the indicator resolves to a terminal failed/timed_out state rather than spinning forever.

### Human-intervention flows (confirm-before-write)
- **WHEN** the assistant pauses to request human input **THEN** the "waiting for your input" state is shown continuously from the moment it pauses until the user resolves — no blank gap before the intervention dialog appears.
- **WHEN** an intervention is outstanding **THEN** the chat window blocks new input and clearly shows the waiting state, consistent with the existing intervention dialog.
- **WHEN** the user approves the intervention **THEN** status advances to resumed work (and then finished), with no stuck spinner.
- **WHEN** the user rejects or cancels the intervention **THEN** status advances to the correct next state (resumed or terminal), with no stuck spinner.

### Resume, reload, and reconnect
- **WHEN** a user closes and reopens (or reloads) a conversation while the assistant is still working **THEN** the chat window immediately shows the current persisted status (working, delegating, waiting_for_human, or finished) — not empty or stale.
- **WHEN** a user reconnects to a conversation that was mid-intervention **THEN** the pending intervention and its "waiting for your input" status are re-surfaced automatically.
- **WHEN** a user reconnects **THEN** the restored status matches the assistant's real state at reconnection time, not the state when they left.

### Restart and failover resilience
- **WHEN** a backend service restarts while a turn is mid-flight **THEN** the persisted activity state survives and the correct status is shown when resumed.
- **WHEN** a conversation in flight is resumed on a different backend server **THEN** the latest status is intact (multi-server scaling/failover).
- **WHEN** activity can no longer be resumed (stale/orphaned) **THEN** it resolves to a clear terminal state (finished, failed, timed_out) — never a perpetual working/waiting indicator.

### Security boundaries
- **WHEN** the internal activity endpoint is called without a valid service certificate or signed tenant context **THEN** it fails closed (401) and no activity is written/read.
- **WHEN** activity is persisted **THEN** it contains only status context and never identity tokens, DB credentials, or decrypted secrets.

## Edge Cases & Risks

- **One-row-per-session invariant**: concurrent transitions for the same session must upsert into a single live row (no duplicate/partial rows). Risk: duplicate rows could hydrate a stale state.
- **Terminal vs. intervention race**: an intervention response arriving at the same time as a terminal resolution must not overwrite a still-pending intervention on an active session. Risk: wrong terminal state shown while user still needs to approve.
- **Hydration on a brand-new session with no activity row**: `GET` must return explicit null (idle), and the frontend must treat it as "not in flight" — no phantom bubble.
- **Rapid reload/reconnect bursts**: multiple `activity_state` hydration messages must be idempotent and not flash or double-render the bubble.
- **Transition out-of-order delivery over NDJSON**: a late `thinking` after a `finished` must not resurrect the spinner — terminal states are sticky and must not be overwritten by earlier states.
- **`current_turn_id` / `pending_intervene_request_id` dangling references**: activity referencing a turn/intervention that no longer exists must be resolvable to a terminal state by the reaper without error.
- **Multi-tenancy**: activity must be scoped per conversation and per tenant; cross-tenant reads/writes must be impossible (fail closed).
- **Reaper vs. active session**: the reaper must not terminate a `waiting_for_human` on an active session still awaiting operator input; conversely it must reap a waiting state whose session is genuinely gone.
- **Tool/delegation context fields**: tool name and delegation target are surfaced in the bubble — must be non-sensitive and correctly cleared when the activity transitions away.
- **Persistence of sensitive data**: accidental inclusion of tokens/credentials in `detail` or context fields — enforce at the store/endpoint layer, not just by convention.
- **Backward compatibility of `status_pong` shape**: clients must not break when `status_pong` changes from `turn_in_flight`/`intervention_pending` booleans to a persisted `state` + `pending_intervention` flag.

## Acceptance Criteria Checklist

### Accurate Live Status
- [ ] Visible activity indicator reflects actual current activity while working.
- [ ] Indicator changes state promptly across transitions (no lingering).
- [ ] Indicator stops on finish and shows a clear finished state; never spins after completion.
- [ ] Failed/timed-out turns resolve to a terminal indicator.

### Human-Intervention Flows
- [ ] Waiting state shown continuously from pause until resolution — no blank gap.
- [ ] New input blocked and waiting state clearly shown while intervention outstanding.
- [ ] Approve/reject advances status correctly (resumed or finished), no stuck spinner.

### Resume, Reload, and Reconnect
- [ ] Reload/reopen mid-turn immediately shows current persisted status.
- [ ] Mid-intervention reconnect re-surfaces pending intervention + waiting status.
- [ ] Restored status matches real state at reconnection, not at departure.

### Restart and Failover Resilience
- [ ] Activity state survives service restart mid-turn and shows correct status on resume.
- [ ] In-flight conversation resumes on a different server with latest status intact.
- [ ] Stale/orphaned activity resolves to a terminal status (no perpetual working/waiting).

### Privacy and Scope
- [ ] Persisted activity contains status-only info — no tokens/credentials/secrets.
- [ ] Activity scoped per conversation (and per tenant when multi-tenancy enabled).

## Database-Change Testing Requirements

This change has `has_db_changes: true`. The following are mandatory:

### Backend integration tests verifying the schema change took effect
- Query `information_schema.columns` to verify the `conversation_activity` table exists with the expected columns (`state`, `current_turn_id`, `tool_name`, `target_agent_type_id`, `pending_intervene_request_id`, `detail`, `conversation_session_id`, timestamps).
- Verify the `state` column is the `activity_state` enum (or the constrained type) with all seven values present and nullable/config as specified.
- Verify nullable properties: context columns (`tool_name`, `target_agent_type_id`, `pending_intervene_request_id`, `detail`, `current_turn_id`) are nullable where the model requires; non-nullable columns reject NULL.
- Verify constraint/uniqueness: one live row per session — attempting a second active row for the same session violates the intended invariant (negative test).
- **Negative test**: inserting an invalid `state` value (outside the seven-value enum) is rejected by the database/ORM.
- Verify the FK from `conversation_activity` to `conversation_session` (and to `conversation_turn` / `intervene_request` where applicable) enforces referential integrity, and that a NULL-able FK allows NULL.
- Verify the `ConversationSession.activity` back-reference resolves correctly.

### E2E real-backend variant
- At least ONE E2E test that hits the real backend (no `page.route()` mocks), labeled:
  `test.describe('Real Backend Integration - Conversation Activity State')`
- This variant must drive a real conversation turn through the real DB migration and real WebSocket, and assert the activity record is persisted and hydrated — catching migration issues that mocked tests miss.

### Pre-Test Checklist for Database Changes
- [ ] Verify `alembic current` shows the new migration revision for `conversation_activity`/`ActivityState`.
- [ ] If not applied, run `alembic upgrade head` before any tests.
- [ ] Confirm the backend test fixture applies migrations (`alembic upgrade head`) in setup before running integration tests.
- [ ] Confirm the test database schema matches production (same migration chain, no drift).
- [ ] Restart backend services after migration so ORM models/`ActivityState` enum are re-loaded (models cached at startup).

## Test File References

Actual test files created for this change:

### Backend (unit — real DB via asyncpg where `DATABASE_URL` is PostgreSQL)
- `backend/tests/unit/conversations/test_conversation_activity_store.py` — `ConversationActivityStore` upsert/read/terminal-resolution; one-row-per-session; terminal-state stickiness; enum contract.
- `backend/tests/unit/conversations/test_conversation_activity_reaper.py` — reaper resolves stale/orphaned activity to terminal while protecting pending interventions on active sessions.
- `backend/tests/unit/conversations/test_conversation_activity_schema.py` — model/table contract (columns, nullability, unique-per-session, FKs `ondelete`, reaper index, enum) + `information_schema`/`pg_catalog` verification of the applied migration.
- `backend/tests/unit/conversations/test_conversation_activity_persistence.py` — state survives a store-instance change (restart/failover), waiting-state hydration, terminal visibility, per-session scoping.
- `backend/tests/unit/test_conversation_activity_endpoints.py` — internal `PUT`/`GET` activity endpoints: fail-closed 401, upsert/echo, 422 unknown state, 404 unknown session, explicit null idle, one-live-row on repeated PUT.
- `backend/tests/unit/test_conversation_activity_prepare_append.py` — `prepare-turn` sets `thinking`; `append-turn` resolves `finished` / `timed_out` / `failed` per final status event.
- `backend/tests/unit/test_communication_hub_activity_client.py` — CH data-client `upsert_conversation_activity`/`get_conversation_activity` (payload/path, 404→None, non-404 propagates).
- `backend/tests/unit/test_agent_runtime_activity_emission.py` — wire→activity mapping, `activity_state` message shape, CH forwards each transition, failures swallowed.
- `backend/tests/agent_runtime/test_ar_activity_persistence_boundaries.py` — structural: AR has no DB access, never calls CC activity endpoints, resume registry stays process-local; transition ordering; no secrets in status events.
- `backend/tests/unit/test_internal_allowlist_activity.py` — regression: CH internal allowlist must include the `PUT`/`GET` activity routes (fixes the 403 `endpoint_not_allowlisted`).
- `backend/tests/unit/test_human_intervene_persists_activity.py` — regression: conversation-scoped `human_intervene` persists `waiting_for_human` activity with the pending intervention id.

### Frontend (component/hook)
- `frontend/src/__tests__/useChatSession.activityState.test.ts` — `parseActivityState`, connect-time hydration, `status_pong` reconciliation, intervention re-arm, terminal clearing.
- `frontend/src/__tests__/ConversationDialog.activityBubble.test.tsx` — continuous `waiting_for_human` (no blank gap), hydrated pending-intervention flag, terminal clearing (no stuck spinner).
- `frontend/src/__tests__/useChatSession.interventionGap.test.ts` — regression: full sequence (thinking → using_tool → silence → intervene_request) never blanks.
- `frontend/src/__tests__/useChatSession.finality.test.ts` — regression: non-final message keeps the bubble; `final: true` clears; heartbeat restores a blanked bubble.
- `frontend/src/__tests__/ConversationDialog.usingTool.test.tsx` — regression: `using_tool` renders "Using tool …" with/without an (empty) delegation cycle.

### E2E (Playwright)
- `e2e/tests/conversation-activity-state.spec.ts` — mocked full lifecycle (`using_tool` → `waiting_for_human` → `finished`) + reload hydration; plus a `test.describe('Real Backend Integration - Conversation Activity State')` variant that probes the live backend and asserts the internal activity endpoint is registered and fail-closed (skips when no live stack).

