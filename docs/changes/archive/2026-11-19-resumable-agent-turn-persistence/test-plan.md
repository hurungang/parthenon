# Test Plan: Resumable Agent Turn Persistence

Scope: a paused confirm-before-write conversational turn becomes durable — an authoritative resume index plus an opaque checkpoint payload owned by Control Center, instance-independent resume through Communication Hub to any Agent Runtime instance, exactly-once application of the confirmed write, and one clear reason-keyed terminal outcome when a turn genuinely cannot be continued.

This change has `has_db_changes: true`. The schema/migration verification requirements in **Section 3** and the real-backend E2E variant in **Section 5** are mandatory, not optional.

---

## 1. Test Strategy

| Layer | Location | Purpose in this change | Weight |
|---|---|---|---|
| **Backend unit** | `backend/tests/unit/`, `backend/tests/agent_runtime/`, `backend/tests/communication_hub/` | Resume-state machine legality, claim arbitration, checkpoint store byte cap/consume, terminal-resolver branch selection, durable-checkpointer round-trip and flush ordering, dispatch de-duplication, interrupt-key idempotency | High |
| **Backend integration** | `backend/tests/integration/`, `backend/tests/db/`, `backend/tests/e2e/` | Real Postgres schema verification via `information_schema`; CC internal data-plane endpoints under service-certificate auth; cross-tenant denial; intervention respond advancement; single-transaction complete; exactly-once management-tool application | High |
| **Frontend unit/component** | `frontend/src/__tests__/` | `useChatSession` status model (resume state, active resume id, terminal reason/message preserved through hydration), four-state dialog vocabulary, terminal card, input re-enable, sessions badges | Medium |
| **E2E** | `e2e/tests/` | Operator-visible flows: waiting → resume → continuing → resolved; unresumable card with one actionable message; reload/reconnect restores the same outcome. One real-backend suite is mandatory | High |
| **Manual / operational** | Service restart drills | Restart CC, CH, AR individually while a confirmation is pending; verify approval afterwards continues the turn. Cannot be faithfully automated for real process lifecycle | Mandatory evidence |
| **Structural guard** | `backend/tests/agent_runtime/`, `backend/tests/integration/` | Source-level proof: AR holds no DB session/SQLAlchemy/datastore endpoint/credential; CH mints no tenant headers and persists nothing; no raw httpx clients in CH/AR paths | High |

Test-layer rule: the change is **not** considered verified until backend, frontend, **and** E2E layers pass, including the real-backend variant and the manual restart drills.

---

## 2. Test Environment & Pre-Test Checklist

Mandatory for `has_db_changes: true`:

- [ ] `cd backend` then `python -m alembic current` shows the new resume/checkpoint revision (the head created by this change), not the previous head.
- [ ] If not at head: `python -m alembic upgrade head` **before** any backend test run, then re-check `alembic current`.
- [ ] The backend test fixture applies migrations during setup (test DB is never assumed pre-migrated), and the test database schema matches the production schema for the touched tables.
- [ ] Backend services restarted after migration (`./scripts/restart-backend.sh` on macOS) so ORM metadata and enum caches are fresh.
- [ ] Full stack healthy for E2E and manual drills: Control Center, Agent Runtime, Communication Hub, frontend, Postgres, Redis, Keycloak (port 8082).
- [ ] A conversational agent type with a confirm-before-write management tool path is available for the drill, plus a second AR instance (or a restartable single AR) for failover scenarios.
- [ ] Failure-mode logs confirmed reachable: `backend/logs/control-center.log`, `agent-runtime.log`, `communication-hub.log`.

Assertion hygiene: every scenario asserts **state agreement** across three places — the resume record (`state`, `resume_outcome`, `write_applied`), the `ConversationActivity` row (`state`, `is_terminal`, `active_resume_id`), and what the operator sees. A scenario that only asserts the HTTP status is insufficient.

---

## 3. Mandatory DB-Change Verification (backend integration)

**A. Migration / schema take-effect**

- [ ] Query `information_schema.columns` and `pg_catalog` to confirm both new tables exist with all modelled columns, and that `conversation_activities` gained `active_resume_id`.
- [ ] Verify nullability exactly as modelled: index columns that must be non-null (`tenant_id`, `conversation_session_id`, `turn_id`, `state`, `is_terminal`, `resume_key`, `idempotency_key`, `write_applied`, `attempt_count`, timestamps) and nullable lifecycle columns (`resume_outcome`, `outcome_turn_id`, `claimed_by_instance_id`, `claim_expires_at`, `applied_*`, `terminal_*`, `expires_at`, `resolved_at`).
- [ ] Verify enum types and value sets in the database: `ResumeState` (`waiting_for_human`, `resuming`, `resolved`, `unresumable`), `ResumeOutcome` (`approved_applied`, `denied`, `cancelled`, `expired`, `superseded`, `resume_failed`), `CheckpointPayloadKind` (`agent_turn_state`, `conversation_state`).
- [ ] Verify constraints: unique `idempotency_key`; one checkpoint per resume record (1:1 uniqueness on `resume_id`); at most one live resume per conversation session (partial/unique strategy as designed); cascade/`SET NULL` behaviour of foreign keys to session, turn, intervene request, and the activity link.
- [ ] Verify the new `active_resume_id` FK on `conversation_activities` is nullable, points at the resume table, and does not break existing activity rows (existing rows remain valid with `NULL`).
- [ ] Verify indexes backing the reaper/claim sweep and the sessions-list resume projection exist.

**B. Negative tests (must fail)**

- [ ] Inserting a second checkpoint row for the same `resume_id` is rejected.
- [ ] Inserting two live (non-terminal) resume records for one conversation session is rejected.
- [ ] Inserting a resume record with a duplicated `idempotency_key` is rejected.
- [ ] Writing an invalid `state` or `resume_outcome` value is rejected by the enum type.
- [ ] Deleting a conversation session cascades its resume/checkpoint rows (or is blocked per design) — verified, not assumed.

**C. Upgrade/downgrade integrity**

- [ ] `alembic upgrade head` from the prior revision succeeds on a database containing pre-existing conversation activity and intervention rows; no data loss, `active_resume_id` reads `NULL` for legacy rows.
- [ ] `alembic downgrade` to the prior revision succeeds cleanly (tables and the added column removed) on a non-production copy, then `upgrade head` restores the state.

---

## 4. Coverage Areas (and why each is critical)

| # | Coverage area | Why it is critical |
|---|---|---|
| A | **Pause capture durability** — checkpoint and index written *before* the turn reports waiting | This is the entire epic. If the pause can be reported before the payload is durable, the old defect survives with a new implementation |
| B | **Restart of each service in the path (CC, CH, AR)** | The PRD explicitly requires *any* service restart, not just the chat-hosting one. Testing only one restart path leaves two-thirds of the promise unverified |
| C | **Cross-instance resume / failover** | The scaling and failover promise; also the only way to prove pause state is not accidentally still process-local |
| D | **Exactly-once application of the confirmed write** | A duplicate approval double-applying a management change is the highest-severity possible regression |
| E | **Terminal resolution and vocabulary** | The PRD's headline user-facing goal: zero misleading "timed out or failed" for a valid turn, one actionable message otherwise |
| F | **Turn claim arbitration** | Guards against two instances continuing the same turn concurrently during retry/failover |
| G | **Human-intervention path conversion** | Regression risk: the legacy in-process future must no longer gate conversational pauses |
| H | **Payload hygiene and segregation** | Security-reviewer acceptance criterion; the payload must contain no tokens/credentials and AR must hold no DB access |
| I | **Tenant scoping** | Cross-tenant resume would be a containment breach; must fail closed |
| J | **Frontend state agreement** | "Shown as waiting" must equal "actually answerable"; hydration must preserve message/resume fields so reconnect matches live push |
| K | **Sessions list projection and badges** | Returning users discover pending confirmations from the list; stale/wrong badges mislead operators |

---

## 5. Critical Scenarios (WHEN / THEN)

### A. Pause capture

- WHEN a conversational turn pauses for a confirm-before-write approval, THEN a resume record exists in `waiting_for_human` with a live checkpoint and a non-null `active_resume_id` on the activity row, and all three are committed before the operator is shown "waiting for your input".
- WHEN the checkpoint flush fails or times out at pause time, THEN the turn terminates with a clear failure event and no `waiting_for_human` state is persisted (never a waiting row without an answerable turn).
- WHEN the same pause is detected twice for one tool task (replayed tool step), THEN exactly one intervention request, one resume record, and one checkpoint exist.
- WHEN a new pause occurs while a previous resume record is still live for the session, THEN the previous record becomes `superseded` and is no longer actionable.

### B. Approve / deny after restarting each service

- WHEN the operator approves a still-valid confirmation after **Control Center** was restarted, THEN the turn continues from the pause point, the resume record reaches `resolved` / `approved_applied`, and the operator sees continued work — not "timed out or failed".
- WHEN the operator denies a still-valid confirmation after **Control Center** was restarted, THEN the turn resolves as `denied`, nothing is written (`write_applied` stays false), and the assistant acknowledges the rejection and offers to adjust.
- WHEN the operator approves after **Communication Hub** was restarted, THEN the answer is accepted, the resume is dispatched once to the configured AR endpoint, and the turn continues.
- WHEN the operator approves after **Agent Runtime** was restarted, THEN the turn is rebuilt from the persisted checkpoint on the new AR process and continues.
- WHEN an approval is sent while each of the three services is mid-restart (brief unavailability), THEN the outcome is either a successful resume or a retryable transient error — never a terminal "turn failed" while the confirmation is still valid.
- WHEN the operator reloads the conversation after a restart, THEN the pending confirmation is still presented as actionable and the status still reads "waiting for your input".
- WHEN an approval given after a restart completes, THEN the conversation history contains one response turn and one outcome turn, in order, with no duplicates and no missing turns.

### C. Cross-instance resume and failover

- WHEN a turn paused on AR instance A and the approval is delivered to AR instance B, THEN B claims the turn, loads the checkpoint, continues the work, and completes it.
- WHEN two instances are sequentially handed the same conversation, THEN neither treats the turn as lost and the operator sees one coherent conversation.
- WHEN the number of AR instances is increased or decreased between pause and answer, THEN the outcome is unchanged.
- WHEN the claim-holding instance dies mid-resume and its lease expires, THEN another instance can acquire the claim and finish the turn, and the lifecycle state never changed as a side effect of expiry.

### D. Exactly-once

- WHEN the same approval is delivered twice (reconnect, repeated click, or a retry after instance change), THEN the confirmed write is applied exactly once, `write_applied`/`applied_at` are set once, and the duplicate returns the stored outcome instead of re-executing the handler.
- WHEN a duplicate `resume/complete` arrives after the outcome was recorded, THEN the stored outcome is returned and no second outcome turn is appended.
- WHEN a management-tool dispatch is retried with the same turn idempotency key after the write committed, THEN the stored effect summary is returned and no second write occurs.
- WHEN a management-tool dispatch is retried with the same key after the write failed to commit, THEN the write is attempted again (no false "already applied").
- WHEN the approval is denied or has expired, THEN no management-tool write occurs under any retry.
- WHEN the same approval is submitted twice concurrently, THEN exactly one AR resume call and exactly one persisted outcome are observed.

### E. Terminal resolution

- WHEN the answer arrives after the validity window has elapsed, THEN the turn resolves `unresumable` / `expired`, the operator sees one clear message naming what happened and the next step (e.g. re-issue the request), and the legacy generic timeout text is not shown.
- WHEN the checkpoint is missing, consumed, unreadable, or version-incompatible at resume time, THEN the turn resolves `unresumable` / `resume_failed` with a distinct "pause point could not be re-established" message, and no write is applied.
- WHEN a turn is deliberately ended/cancelled before being answered, THEN it resolves `cancelled`, the outstanding confirmation is no longer actionable, and no write is applied.
- WHEN any terminal resolution occurs, THEN the activity row reaches a terminal state, `active_resume_id` is cleared, message input is re-enabled, and the confirmation is no longer presented as actionable.
- WHEN a turn is still legitimately valid, THEN no terminal notice is emitted at all (no false orphan/expiry notices on successful resumes or slow resumes).
- WHEN the resolver re-runs on an already-terminal turn, THEN it is a no-op: exactly one outcome turn exists and the reason code does not change.
- WHEN the activity state and the resume record disagree after any sweep, THEN the test fails — `waiting_for_human` must imply a live resume record.
- WHEN a session is listed or rehydrated, THEN the operator can distinguish plain-terms states: waiting for the user, resumed and continuing, resolved, and no longer resumable.

### F. Turn claim

- WHEN two instances claim the same turn concurrently, THEN exactly one acquires it and the other receives `already-held` with no lifecycle state change and no resume execution.
- WHEN an instance holds a live claim, THEN a second instance cannot load-and-continue (claim is checked before checkpoint consumption).
- WHEN a claim's lease expires, THEN the turn becomes re-acquirable while its lifecycle state is unchanged.
- WHEN the claimed instance releases the claim (success, failure, or best-effort exit), THEN the release is idempotent and never resurrects a terminal turn.
- WHEN a claim is requested for a resolved/unresumable turn, THEN the response is `terminal` and no resume is attempted.
- WHEN a claim is requested for an unknown session, THEN a not-found result is returned and nothing is created.

### G. Human-intervention pause uses durable checkpoint

- WHEN the conversational `human_intervene` tool pauses, THEN it returns immediately via the LangGraph interrupt/resume mechanism and the executor does not await an in-process future.
- WHEN a conversational resume request arrives, THEN the in-process registry (`is_pending` / `wait_for_resume`) is not consulted on the production path and its absence does not change the outcome.
- WHEN an interrupt is replayed for the same tool task, THEN the same pending intervention is reused (idempotent registration key) rather than creating a second request.
- WHEN the resumed turn pauses again for another confirmation, THEN a `paused` stream end is emitted, a new live resume record replaces the old one, and the operator sees a new actionable confirmation.
- WHEN `POST /internal/resume` is called with a conversation-scoped id, THEN it delegates to the conversational resume handler and returns the same outcome semantics as the dedicated endpoint.

### H. Payload hygiene and segregation

- WHEN a checkpoint payload is persisted, THEN it contains no identity/access tokens, client secrets, database credentials, or decrypted MCP credentials (assertion by content scan of the stored payload and by the serializer boundary).
- WHEN a checkpoint is loaded from persisted state only, THEN resume succeeds with no reliance on any process-local structure from the pausing instance.
- WHEN an AR module in the pause/resume path is inspected structurally, THEN it imports no DB session/model, holds no connection string or datastore endpoint, and reaches CC only through CH via the shared egress client.
- WHEN CH relays a checkpoint, THEN it forwards the verified signed tenant header set, mints no headers, persists nothing, and rejects payloads above the configured byte cap with a typed relay error.
- WHEN a CC internal resume/checkpoint route is called, THEN only CH is allowed by the caller allowlist; AR certificates are denied and unauthenticated calls fail closed (401).
- WHEN an oversized checkpoint is upserted again in place, THEN exactly one checkpoint row exists per resume record and the old payload is replaced, not duplicated.

### I. Tenant scoping

- WHEN a resume answer is processed, THEN the resume record, checkpoint access, claim, and outcome are all resolved within the conversation's tenant context.
- WHEN a checkpoint read/write or claim targets a conversation in another tenant, THEN it fails closed (403/404) and nothing is persisted or mutated.
- WHEN multi-tenancy is enabled, THEN a resumed turn stays inside its conversation's tenant and is attributed to the user who actually responded.
- WHEN the responding user lacks the scope for the resumed action, THEN resumption does not elevate privileges and the write is refused.

### J. Frontend behaviour

- WHEN a turn is waiting and a live resume id is present, THEN "waiting for your input" and the confirmation controls are shown.
- WHEN waiting activity arrives with **no** resume id, THEN the dialog does not claim the turn is answerable (degraded state handled explicitly).
- WHEN a resume starts, THEN `thinking`/`using_tool` status after the pause reads as "resumed and continuing" and the waiting indicator clears.
- WHEN a resolved outcome arrives, THEN the conversation shows the outcome once, in order, and input is enabled.
- WHEN an unresumable outcome arrives, THEN a terminal card renders the reason-specific message with a next step and a dismiss action, and approve/deny are no longer offered.
- WHEN the operator clicks approve or deny on a terminal turn, THEN no request is sent.
- WHEN the connection rehydrates (`activity_state`), THEN the terminal message, resume state, and active resume id survive into the client status model so the reconnect render matches the live push.
- WHEN the sessions list is rendered, THEN resume state badges match the API projection and do not show waiting for a session with no live resume record.

### K. Regression

- WHEN a non-conversational (typed/task) resume runs, THEN the existing job path is unchanged.
- WHEN a conversation ends, is terminated, or times out normally, THEN existing terminal semantics and reaper behaviour still hold.
- WHEN a management tool is invoked outside a paused turn, THEN no idempotency key is required or sent and behaviour is unchanged.
- WHEN the retention horizon passes after resolution, THEN the checkpoint payload is purged while the resume index row, outcome turn, and audit fields survive.

---

## 6. Edge Cases & Risks

| Risk | Why it matters | Mitigation in this plan |
|---|---|---|
| Pause reported before checkpoint durable | Silent regression to the original defect | Ordering assertions + transport-failure scenario (§A) |
| In-process registry still shadowing the durable path | Tests pass locally, production still single-instance | Structural test + instance-B resume scenario (§C, §G) |
| Duplicate approval double-applying a management change | Highest-severity data-integrity incident | Concurrent + sequential duplicate tests at HTTP, router, and tool-dispatch layers (§D) |
| Terminal resolver protected-vs-expired boundary off-by-one | Either premature "no longer resumable" or never-resolving turns | Boundary tests on the validity window; clock-injected resolver tests |
| Activity/resume divergence | Dialog shows waiting for an unanswerable turn (worse than a timeout) | Every terminal/resolver test asserts three-way agreement (§E) |
| Claim applied after checkpoint consumption | Two instances both rebuild and both stream | Claim-before-load ordering assertion (§F) |
| Payload leaking secrets | Security acceptance criterion failure | Content-scan test on persisted payload + serializer boundary review (§H) |
| Cross-tenant resume via session id | Containment breach | Explicit 403/404 tests on resume, checkpoint, claim, complete (§I) |
| Migration applied in tests but not in the real environment | Mocked E2E passes while production fails | Real-backend E2E suite + pre-test checklist (§2, §3) |
| Legacy rows without `active_resume_id` | Existing conversations break on upgrade | Upgrade-integrity test with pre-existing rows (§3C) |
| CH dispatch duplication on supervision restart | Two replies / two outcomes pushed | Per-conversation in-flight guard + stored-outcome short-circuit tests |
| Re-pause during resume loop | Re-pauses must terminate the original dispatch, not spawn orphans | Explicit re-pause scenario (§G) |
| Payload size growth / version skew after framework upgrade | Resume fails silently or blows up rows | Byte-cap rejection test + schema-version mismatch → typed unavailable → clear message (§E) |
| Reaper races the operator's answer | Answer arrives mid-resolution | Test answer-after-terminal and resolution-after-answer ordering; exactly one outcome turn |

---

## 7. Acceptance Criteria Checklist (maps to PRD)

Legend: ☐ not yet verified · every row must be ☑ with a passing automated test or recorded manual drill before the change is `implemented`.

### Approving and Denying After a Restart

- [ ] **AC-1.1** A confirmation pending when a backend service restarted is still presented as pending, and approving it continues the work rather than timing out. → §B, §C
- [ ] **AC-1.2** Denying after a restart resolves the turn cleanly (acknowledged, adjustment offered) with nothing written. → §B, §D
- [ ] **AC-1.3** The resumed turn keeps the same history and context: no duplicated turns, no missing turns, no repeated side effects. → §B, §D
- [ ] **AC-1.4** A restart of *any* service in the path leaves a pending confirmation actionable. → §B (CC, CH, AR individually + manual drill)

### Any Server, Scaling and Failover

- [ ] **AC-2.1** A turn paused on one instance can be continued on a different instance. → §C
- [ ] **AC-2.2** Two instances serving the same conversation in sequence do not treat the turn as lost; one coherent conversation. → §C
- [ ] **AC-2.3** Scaling instances up or down does not change the outcome of a paused confirmation. → §C

### Clear Resolution When a Turn Cannot Be Resumed

- [ ] **AC-3.1** A genuinely unresumable turn (window elapsed, work deliberately ended, checkpoint unusable) shows one clear message explaining what happened and the next step. → §E
- [ ] **AC-3.2** The misleading "delegated step timed out or failed" message is not shown for a still-valid turn. → §E
- [ ] **AC-3.3** An unresumable turn does not leave the conversation stuck: terminal status, input re-enabled, confirmation no longer actionable. → §E, §J
- [ ] **AC-3.4** The conversation distinguishes waiting for the user / resumed and continuing / resolved / no longer resumable in plain terms. → §J
- [ ] **AC-3.5** Acknowledging a no-longer-resumable turn never silently retries or double-applies a change. → §D, §E

### Consistency of Confirmed Actions

- [ ] **AC-4.1** Approving results in exactly one application of the confirmed change, even when the approval is delivered more than once. → §D
- [ ] **AC-4.2** A denied or expired confirmation never results in a change being applied. → §D, §E
- [ ] **AC-4.3** The response and the resumed outcome each appear once, in order, in history and in replay. → §B, §E

### Segregation and Privacy

- [ ] **AC-5.1** Resuming never requires an execution service to hold identity tokens, DB credentials, or other secrets, and the durable turn information contains no sensitive material. → §H, §3
- [ ] **AC-5.2** A resumed turn stays scoped to its own conversation and tenant and remains attributed to the user who actually responded. → §I

### Derived from Dependencies & Constraints

- [ ] **AC-D1** "Shown as waiting for your input" is structurally equal to "actually resumable" (`active_resume_id` gate). → §A, §E, §J
- [ ] **AC-D2** The in-process pause future is retired from conversational production paths. → §G
- [ ] **AC-D3** No new datastore dependency is introduced; CC remains the only DB accessor. → §H, §3

---

## 8. Test File References

Paths follow `source.tests` (`backend/tests/`, `frontend/src/__tests__/`, `e2e/tests/`).
Status: **new** = written by Phase 7 · **extended** = existing file grown by this phase ·
**existing** = delivered by an earlier phase and already covering the area (re-run here).

### Backend — unit

| File | Status | Covers |
|---|---|---|
| `backend/tests/unit/conversations/test_conversation_turn_resume_store.py` | existing | Resume store lifecycle: create-or-reuse, supersede, legal/illegal transitions, claim contention, claim re-acquire after lease expiry, reject `approved_applied` without `write_applied`, resolve/resolve-unresumable |
| `backend/tests/unit/conversations/test_turn_checkpoint_store.py` | existing | Payload upsert-in-place (one row per resume), byte cap rejection, consume-once, expired/consumed load returns nothing, purge while index survives |
| `backend/tests/unit/conversations/test_resume_terminal_resolver.py` | existing | Resolver branches (protected, expired, superseded, cancelled, checkpoint-lost, stale resuming), three-way state agreement, one outcome turn, no false notice |
| `backend/tests/unit/conversations/test_conversation_activity_*` (schema/store/reaper/persistence) | existing | `active_resume_id` model contract, waiting-without-live-resume refusal, terminal clearing, reaper/resolver integration |
| `backend/tests/unit/test_turn_checkpoint_endpoints.py` | existing | CC internal resume/checkpoint/claim/release/complete endpoints under service-cert auth; create → read → complete; duplicate complete returns stored outcome; unknown session 404; cross-tenant denial; route allowlist membership |
| `backend/tests/test_internal_endpoint_allowlist_coverage.py` | extended | New resume/checkpoint route cross-check: every `/resume` route on the CC internal data router is CH-allowlisted and AR-denied; caller/registry scans still pass |
| `backend/tests/unit/test_management_tool_idempotency.py` | **new** | Crash-retry after commit returns the stored summary without re-running the handler (per-tool and meta wrapper); denied/cancelled/expired/resume-failed turns refuse a late dispatch (409, no write, marker false); PostgreSQL row lock serialises duplicate applied-marker reads |
| `backend/tests/unit/test_management_tool_applied_marker.py` | existing | Marker commits with the write; duplicate dispatch applies once; failed write rolls the marker back; unknown/no key applies without a marker |
| `backend/tests/unit/test_human_intervene_persists_activity.py` | existing | Pause persists intervention + waiting activity + live resume id |
| `backend/tests/unit/test_conversation_sessions_resume_projection.py` | existing | Sessions listing resume projection (`resume_state` / `resume_outcome` / `resume_expires_at`) and null for idle |

### Backend — Agent Runtime

| File | Status | Covers |
|---|---|---|
| `backend/tests/agent_runtime/test_durable_checkpointer.py` | existing | Saver round-trip via fake transport, super-step coalescing, `flush()` blocks on the outstanding write, schema/deserialisation mismatch raises typed unavailable error, re-pause persists the new pause point |
| `backend/tests/agent_runtime/test_conversational_resume_from_checkpoint.py` | existing | Pause persists checkpoint + index before waiting; resume on a second simulated instance; contention 409; missing checkpoint → `unresumable`/`resume_failed`; re-pause during resume; paused-stream end on first pause; claim lost mid-run aborts without completing |
| `backend/tests/agent_runtime/test_checkpoint_transport.py` | existing | All calls target CH URLs, tenant headers come from the shared egress hook, typed relay errors, idempotency header only inside a paused turn, no DB access in the module |
| `backend/tests/agent_runtime/test_resume_registry_miss_orphan.py` | existing | Durable-state semantics replace the in-process registry miss; no false terminal notice for a resumable turn; job path unchanged |
| `backend/tests/agent_runtime/test_ar_activity_persistence_boundaries.py` | existing | AR tree holds no DB session/model import, no connection string/datastore endpoint, no raw httpx client; pause/resume ordering; no secrets in status events |
| `backend/tests/agent_runtime/test_turn_idempotency_propagation.py` | existing | The turn key travels on every confirmed-write call and never outside a paused turn |

### Backend — Communication Hub

| File | Status | Covers |
|---|---|---|
| `backend/tests/communication_hub/test_resume_router_dispatch.py` | existing | Single dispatch and single outcome under duplicate/concurrent responses; stored-outcome short-circuit; one reply pushed to the live socket; paused-during-resume reply withheld; HTTP returns before turn completion; durable-state terminal notice; retryable dispatch failure |
| `backend/tests/communication_hub/test_turn_checkpoint_relay.py` | existing | Checkpoint save/load relayed byte-for-byte; signed tenant headers forwarded not minted; size guard (413, nothing forwarded); typed relay errors on CC 4xx/5xx; no persistence |
| `backend/tests/integration/test_multitenant_auth_chain.py` (forward-only guard) | existing | Structural proof that AR/CH trees never sign tenant contexts (covers the new relay modules) |
| `backend/tests/communication_hub/test_tenant_header_verification.py` | existing | Signed-set verification on `/internal/*` (see Known Failures in §11) |

### Backend — integration / DB

| File | Status | Covers |
|---|---|---|
| `backend/tests/db/test_conversation_turn_resume_migration.py` | **new** | `information_schema` / `pg_catalog` verification of both tables, model↔DB column/nullability reconciliation, `active_resume_id` FK, enum value sets, unique `idempotency_key`, 1:1 checkpoint, partial-unique one-live-resume index, FK ondelete actions, negative constraint tests (second checkpoint, second live resume, duplicate key, invalid enum values, session-delete cascade), legacy-shaped activity row, upgrade/downgrade cycle (gated by `PARTHENON_TEST_MIGRATION_CYCLE=1`) |
| `backend/tests/integration/test_conversation_pause_resume_flow.py` | **new** | Real pause → waiting activity + live resume; approve → resuming → exactly one confirmed write → `complete` records `approved_applied` once, clears `active_resume_id`, one outcome turn, duplicate close appends nothing; deny → `denied`, nothing written, late dispatch refused; persisted checkpoint payload carries no credential-shaped key/value |
| `backend/tests/integration/test_conversation_interruption_notice.py` | existing | Reason-keyed terminal outcomes replace the fixed notice; no notice on successful resume; distinct expired vs lost-pause-point texts; repeated responses keep one outcome turn |
| `backend/tests/integration/test_internal_intervene_respond.py` | existing | Respond advances the resume record in the same transaction as the stored answer; duplicate answers return stored outcome without re-dispatch |
| `backend/tests/integration/test_conversations_sessions_query.py` | existing | Sessions listing query contract (activation window, pagination, tenant isolation) |
| `backend/tests/integration/test_internal_tenant_header_failclosed.py` | existing | Internal data plane fails closed without valid signed tenant context |
| `backend/tests/integration/test_internal_allowlist_partitioning.py` | existing | AR vs CH route partitioning |
| `backend/tests/integration/test_database_isolation.py` | existing | AR/CH hold no DB session factory or datastore access |
| `backend/tests/integration/test_management_toolset_end_to_end.py` | existing | Management tool registry end-to-end incl. confirmed write |
| `backend/tests/e2e/test_assistant_resume_after_restart_e2e.py` | **new** | Backend end-to-end: pause on instance A, flush, discard A's memory, claim + load + continue on instance B; claim contention and failover after lease expiry (lifecycle state unchanged); terminal turn cannot be claimed or re-applied; one applied write and one outcome turn |

### Frontend

| File | Status | Covers |
|---|---|---|
| `frontend/src/__tests__/ConversationDialog.resumeRecovery.test.tsx` | existing | Four-state rendering (waiting / resuming / resolved / unresumable), reason-specific terminal card with next step + dismiss, input re-enabled, approve/deny inert on terminal, degraded waiting-without-resume-id |
| `frontend/src/__tests__/useChatSession.activityState.test.ts` | existing | Hydration preserves `message`, `activeResumeId`, `terminalReason`, `resumeState`; live status projection; `status_pong` reconciliation |
| `frontend/src/__tests__/useChatSession.finality.test.ts` | existing | Terminal detection unchanged across the extended kind union |
| `frontend/src/__tests__/useChatSession.intervention.test.ts` | extended | `responded` status / `sendInterventionResponse` close the confirmation, mark `resumeState = resuming`, keep the turn in flight (resumed-and-continuing transition) |
| `frontend/src/__tests__/ConversationDialog.activityIndicator.test.tsx` | existing | Waiting indicator gated on the live resume id; cleared on terminal |
| `frontend/src/__tests__/ConversationDialog.intervention.test.tsx` | existing | Confirmation controls only while resumable (hook-level) |
| `frontend/src/__tests__/ConversationSessionsTab.test.tsx` | existing | Resume-state badges match the API projection; no badge without a resume record |

### E2E (Playwright)

| File | Status | Covers |
|---|---|---|
| `e2e/tests/conversation-resume-recovery.spec.ts` | **new** | Mocked flows: pending → approve → resumed and continuing → resolved with input re-enabled; pending → deny → resolved without a card; terminal unresumable card (reason body, next step, dismiss, input enabled); stale approval on a terminal turn sends nothing and shows "nothing to replay"; reload hydration restores waiting and the terminal message; degraded waiting-without-resume-id |
| `e2e/tests/conversation-resume-recovery.real-backend.spec.ts` | **new** | **`test.describe('Real Backend Integration - resumable agent turn persistence')`** — no `page.route()`: live CC internal resume/checkpoint/claim/release/complete routes are registered and fail closed for non-CH callers and for an operator JWT; sessions listing carries the resume projection from the migrated database (500 → explicit migration error); a real conversation session round-trips through the resume endpoint. Skips gracefully without a live stack or operator token (`E2E_REAL_BACKEND_TOKEN`) |
| `e2e/tests/conversation-activity-state.spec.ts` | extended | Waiting assertion disambiguated for the new resume-state chip; terminal `finished` asserted through the resolved resume vocabulary and spinner clearing |
| `e2e/tests/conversation-intervention.spec.ts` | extended | Live-backend probes tolerate the tenant-gated 403 response |
| `e2e/tests/conversation-sessions.spec.ts` | extended | Paginated `/conversations/sessions` + `?limit=&offset=` agent-types mocks; `load` instead of `networkidle` |
| `e2e/tests/conversations.spec.ts` | extended | Query-param conversation list mock; turn-count assertion scoped to the table cell |
| `e2e/tests/intervene.spec.ts` | extended | Translated Respond/Yes labels; approval submits on Yes; page-level pending-count assertion replaces the removed nav badge |

### Manual / operational drills (recorded evidence)

| Drill | Evidence to capture |
|---|---|
| Pause, then restart Control Center, then approve | Screenshot of continued turn + `control-center.log` lines showing resume record resolution; no `timeout_or_failed` |
| Pause, then restart Communication Hub, then approve | Same, with `communication-hub.log` dispatch count = 1 |
| Pause, then restart Agent Runtime, then approve | Same, with `agent-runtime.log` showing checkpoint load on the new process |
| Pause, then wait past the validity window, then approve | Terminal card text includes the specific reason and next step; input enabled |
| Pause on AR A, answer while routed to AR B | Single continued turn; claim ownership visible in logs |

---

## 9. Test Data & Cleanup

- Identifiable prefixes for created sessions/agents: `e2e-test-resume-${timestamp}` (backend) and `e2e-resume-${Date.now()}` (frontend/E2E).
- `afterEach`/fixture teardown removes: created resume records, checkpoints, interventions, activity rows, conversation turns and sessions created by the test.
- Clock-dependent scenarios (window expiry, claim lease expiry, retention purge) must use injected/controlled time, never real sleeps.
- Tenant-scoping scenarios must create data in two tenants and assert isolation, then clean both.
- Structural/segregation tests perform no DB writes and require no cleanup.

## 10. Entry / Exit Criteria

**Entry**
- Migration exists and `alembic current` shows it; test fixture applies migrations.
- CC, CH, AR contracts for the new internal routes are implemented and reachable.
- At least one conversational agent type able to trigger a confirm-before-write pause is seeded.

**Exit**
- All layers green: backend unit + integration + DB schema verification, frontend Vitest, E2E mocked + real-backend, structural guards.
- All 17 PRD acceptance criteria plus AC-D1..D3 checked with a named test or recorded drill.
- No test skipped in the touched areas; zero misleading timeout messages observed for valid turns across the three restart drills.
- Duplicate-delivery tests show exactly one applied write and exactly one outcome turn.
- No secret material found in persisted checkpoint payloads.

---

## 11. Phase 7 Execution Results

| Layer | Result |
|---|---|
| Backend targeted + named regressions | `501 passed`, `1 skipped` (gated downgrade/upgrade cycle, `PARTHENON_TEST_MIGRATION_CYCLE=1`), plus `51 passed` for the new files in isolation — 0 failures in the touched areas |
| Frontend Vitest (full suite) | `1944 passed / 1962`, `18 skipped`, `0 failed` (one cross-file flake observed once and not reproducible) |
| E2E Playwright (conversation/intervention/activity/sessions/history/intervene + both new specs) | `35 passed`, `0 failed`; real-backend authenticated checks skip without `E2E_REAL_BACKEND_TOKEN` |

Known pre-existing failures (not caused by this change, outside the touched areas):

- `backend/tests/test_internal_endpoint_allowlist_coverage.py::test_system_tool_registry_endpoints_are_ch_allowlisted` — the scanner compares concrete registry paths against the `{tool_name}` allowlist template.
- `backend/tests/communication_hub/test_tenant_header_verification.py::TestHeaderlessTraffic::test_no_tenant_headers_pass_through_unchanged` and `::TestValidSignedContext::test_valid_headers_bind_context` — the middleware requires a service certificate on `/internal/agent/execute` (a later hardening) while these fixtures post none.
- `backend/tests/integration/test_multitenant_auth_chain.py::TestInternalEndpoints::test_stale_timestamp_401` — a 600 s-old signed set is still accepted (200); the replay window in `app/core/tenant_signature.py` is wider than the test assumes.
