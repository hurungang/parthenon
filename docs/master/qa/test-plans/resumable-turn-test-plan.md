# Test Plan: Resumable Turns (Durable Pause / Approve After Restart)

**Change:** `resumable-agent-turn-persistence` (2026-11). Final shipped state.
**Builds on:** `persistent-agent-activity-state` — see `conversation-intervention-test-plan.md` §8.

## Scope

A paused confirm-before-write conversational turn becomes durable:

- an authoritative **resume index** plus an opaque **checkpoint payload**, both owned by Control Center,
- **instance-independent resume** through Communication Hub to any Agent Runtime instance (including a restart of CC, CH or AR individually),
- **exactly-once** application of the confirmed write,
- **one clear reason-keyed terminal outcome** when a turn genuinely cannot be continued (replacing the misleading "delegated step timed out or failed"), with input re-enabled.

Out of scope: non-conversational (typed/task) job resume, which is unchanged; and the activity-state model itself (`conversation-intervention-test-plan.md`).

## Test Strategy

| Layer | Location | Purpose | Weight |
|---|---|---|---|
| Backend unit | `backend/tests/unit/`, `agent_runtime/`, `communication_hub/` | Resume-state legality, claim arbitration, checkpoint cap/consume, resolver branches, checkpointer round-trip + flush order, dispatch de-dup, interrupt-key idempotency | High |
| Backend integration | `backend/tests/integration/`, `db/`, `e2e/` | Real Postgres schema verification, CC internal endpoints under service-cert auth, cross-tenant denial, single-transaction complete, exactly-once tool application | High |
| Frontend component | `frontend/src/__tests__/` | Status model + hydration fields, four-state dialog vocabulary, terminal card, input re-enable | Medium |
| E2E | `e2e/tests/` | Waiting → resume → continuing → resolved; unresumable card; reload/reconnect parity. One real-backend suite is mandatory | High |
| Manual | Restart drills | Restart CC, CH, AR individually while a confirmation is pending, then approve | Mandatory evidence |
| Structural guard | `agent_runtime/`, `integration/` suites | AR holds no DB session/model/connection string; CH mints no tenant headers and persists nothing; no raw httpx clients | High |

**Assertion hygiene:** every scenario asserts **state agreement** across the resume record (`state`, `resume_outcome`, `write_applied`), the `ConversationActivity` row (`state`, `is_terminal`, `active_resume_id`) and what the operator sees. The change is not verified until backend, frontend and E2E layers pass, including the real-backend variant and the manual restart drills.

## Coverage Areas

| Area | Why it is critical |
|---|---|
| Pause capture durability | Checkpoint + index must commit **before** the turn reports waiting, or the original defect survives |
| Restart of each service (CC, CH, AR) | The requirement is *any* service restart — testing one path leaves two thirds of the promise unverified |
| Cross-instance resume / failover | The scaling promise, and the only proof that pause state is not still process-local |
| Exactly-once application | A duplicate approval double-applying a management change is the highest-severity regression |
| Terminal resolution & vocabulary | The headline user-facing goal: no misleading timeout for a valid turn, one actionable message otherwise |
| Turn claim arbitration | Two instances must never continue the same turn concurrently during retry/failover |
| Intervention path conversion | The legacy in-process future must no longer gate conversational pauses |
| Payload hygiene & segregation | No tokens/credentials in the payload; AR never touches the DB; CH forwards verified headers and mints none |
| Tenant scoping | Cross-tenant resume would be a containment breach; must fail closed |
| Frontend state agreement | "Shown as waiting" must equal "actually answerable"; hydration preserves resume fields |
| Sessions-list projection | Returning users discover pending confirmations from the list; stale badges mislead |

## Critical Scenarios

### Pause capture
- WHEN a conversational turn pauses for a confirm-before-write approval THEN a resume record exists in `waiting_for_human` with a live checkpoint and a non-null `active_resume_id`, all committed before the operator is shown "waiting for your input".
- WHEN the checkpoint flush fails or times out at pause time THEN the turn terminates with a clear failure event and no `waiting_for_human` state is persisted.
- WHEN the same pause is detected twice for one tool task THEN exactly one intervention request, one resume record and one checkpoint exist.
- WHEN a new pause occurs while a previous resume record is live THEN the previous record becomes `superseded` and is no longer actionable.

### Approve / deny after restarting each service
- WHEN the operator approves after **Control Center** restarted THEN the turn continues from the pause point to `resolved` / `approved_applied`, with no "timed out or failed".
- WHEN the operator denies after **Control Center** restarted THEN the turn resolves `denied`, nothing is written, and the rejection is acknowledged.
- WHEN the operator approves after **Communication Hub** restarted THEN the answer is accepted and the resume is dispatched once to the configured AR endpoint.
- WHEN the operator approves after **Agent Runtime** restarted THEN the turn is rebuilt from the persisted checkpoint on the new AR process and continues.
- WHEN an approval is sent while a service is mid-restart THEN the outcome is a successful resume or a retryable transient error — never a terminal failure of a still-valid confirmation.
- WHEN the operator reloads the conversation after a restart THEN the pending confirmation is still actionable and the status still reads waiting.
- WHEN a post-restart approval completes THEN history contains one response turn and one outcome turn, in order, with no duplicates or gaps.

### Cross-instance resume and failover
- WHEN a turn paused on AR instance A is answered on instance B THEN B claims, loads the checkpoint, continues and completes.
- WHEN two instances are sequentially handed the same conversation THEN neither treats the turn as lost and the operator sees one coherent conversation.
- WHEN the number of AR instances changes between pause and answer THEN the outcome is unchanged.
- WHEN the claim-holding instance dies and its lease expires THEN another instance acquires the claim and finishes; the lifecycle state never changed as a side effect of expiry.

### Exactly-once
- WHEN the same approval is delivered twice (reconnect, repeated click, retry after instance change) THEN the write is applied exactly once, `write_applied`/`applied_at` are set once, and the duplicate returns the stored outcome.
- WHEN a duplicate `resume/complete` arrives after the outcome was recorded THEN the stored outcome is returned and no second outcome turn is appended.
- WHEN a management-tool dispatch is retried with the same idempotency key after commit THEN the stored summary is returned and no second write occurs; after a failed commit the write is attempted again (no false "already applied").
- WHEN the approval was denied or has expired THEN no write occurs under any retry.
- WHEN the same approval is submitted twice concurrently THEN exactly one AR resume call and one persisted outcome are observed.

### Terminal resolution
- WHEN the answer arrives after the validity window THEN the turn resolves `unresumable` / `expired` with one message naming what happened and the next step; no legacy generic timeout text.
- WHEN the checkpoint is missing, consumed, unreadable or version-incompatible THEN the turn resolves `unresumable` / `resume_failed` with a distinct message and no write.
- WHEN a turn is deliberately ended/cancelled THEN it resolves `cancelled` and the confirmation is no longer actionable.
- WHEN any terminal resolution occurs THEN the activity row becomes terminal, `active_resume_id` is cleared, message input is re-enabled and the confirmation is no longer offered.
- WHEN a turn is still legitimately valid THEN no terminal notice is emitted (no false orphan/expiry notices on slow or successful resumes).
- WHEN the resolver re-runs on a terminal turn THEN it is a no-op: one outcome turn, unchanged reason code.
- WHEN a stale approval is clicked on a terminal turn THEN no response frame is sent and nothing is replayed.
- WHEN the session is listed or rehydrated THEN plain-terms states are distinguishable: waiting for the user / resumed and continuing / resolved / no longer resumable.

### Turn claim
- WHEN two instances claim the same turn concurrently THEN exactly one acquires it and the other receives `already-held` with no lifecycle change and no resume.
- WHEN an instance holds a live claim THEN a second instance cannot load-and-continue (claim is checked before checkpoint consumption).
- WHEN a claim's lease expires THEN the turn becomes re-acquirable with its lifecycle state unchanged; release is idempotent and never resurrects a terminal turn.
- WHEN a claim is requested for a resolved/unresumable turn or an unknown session THEN the response is `terminal` / not-found and nothing is created.

### Intervention path conversion
- WHEN the conversational `human_intervene` pauses THEN it returns via the LangGraph interrupt/resume mechanism and the executor does not await an in-process future; the in-process registry is not consulted and its absence changes nothing.
- WHEN an interrupt is replayed for the same tool task THEN the same pending intervention is reused (idempotent registration key).
- WHEN the resumed turn pauses again THEN a `paused` stream end is emitted, a new live resume record replaces the old one, and the operator sees a new actionable confirmation.
- WHEN `POST /internal/resume` is called with a conversation-scoped id THEN it delegates to the conversational resume handler with the same outcome semantics.
- WHEN an ordinary (in-process) approval happens without any restart THEN the confirmation closes, the amber waiting bar disappears immediately, and "Resumed · continuing" is **not** shown (that vocabulary is reserved for genuinely recovered turns).

### Payload hygiene, segregation, tenancy
- WHEN a checkpoint payload is persisted THEN a content scan finds no identity/access tokens, client secrets, DB credentials or decrypted MCP credentials.
- WHEN a checkpoint is loaded from persisted state only THEN resume succeeds with no reliance on any process-local structure from the pausing instance.
- WHEN AR pause/resume modules are inspected structurally THEN they import no DB session/model, hold no connection string or datastore endpoint, and reach CC only through CH via the shared egress client.
- WHEN CH relays a checkpoint THEN it forwards the verified signed tenant header set, mints none, persists nothing, and rejects payloads above the configured byte cap with a typed relay error; an oversized re-upsert keeps exactly one row.
- WHEN a CC internal resume/checkpoint route is called THEN only CH is allowlisted, AR certificates are denied and unauthenticated calls fail closed (401).
- WHEN a resume is processed THEN record, checkpoint, claim and outcome all resolve within the conversation's tenant; cross-tenant targets fail closed (403/404) with nothing mutated; the resumed action never elevates the responding user's privileges.

### Regression & retention
- WHEN a non-conversational (typed/task) resume runs THEN the existing job path is unchanged.
- WHEN a conversation ends, is terminated or times out normally THEN existing terminal semantics and reaper behaviour hold.
- WHEN the retention horizon passes after resolution THEN the checkpoint payload is purged while the index row, outcome turn and audit fields survive.

## Edge Cases & Risks

| Risk | Mitigation / coverage |
|---|---|
| Pause reported before the checkpoint is durable | Ordering assertions + transport-failure scenario |
| In-process registry still shadowing the durable path | Structural test + instance-B resume scenario |
| Duplicate approval double-applying a change | Concurrent and sequential duplicate tests at HTTP, router and tool-dispatch layers |
| Resolver off-by-one on the validity window | Clock-injected boundary tests |
| Activity/resume divergence | Every terminal/resolver test asserts three-way agreement |
| Claim applied after checkpoint consumption | Claim-before-load ordering assertion |
| Payload leaking secrets | Content scan on the persisted payload + serializer boundary review |
| Cross-tenant resume via session id | Explicit 403/404 tests on resume, checkpoint, claim and complete |
| Migration applied in tests but not in the environment | Real-backend E2E suite + pre-test checklist (`alembic current` at head, fixture applies migrations, services restarted after migrating) |
| Legacy rows without `active_resume_id` | Upgrade-integrity test with pre-existing activity/intervention rows |
| CH dispatch duplication on supervision restart | Per-conversation in-flight guard + stored-outcome short-circuit tests |
| Re-pause during a resume loop | Explicit re-pause scenario (original dispatch terminates, no orphans) |
| Payload size growth / version skew | Byte-cap rejection test; schema-version mismatch → typed unavailable → clear message |
| Reaper racing the operator's answer | Answer-after-terminal and resolution-after-answer ordering; exactly one outcome turn |

## Acceptance Criteria

- A confirmation pending when any backend service restarted is still presented as pending, and approving/denying it resolves the turn cleanly (deny writes nothing).
- The resumed turn keeps history and context: no duplicated or missing turns, no repeated side effects.
- A turn paused on one instance can be continued on a different instance; scaling instances up or down changes nothing.
- A genuinely unresumable turn (window elapsed, deliberately ended, checkpoint unusable) shows one clear message with a next step and leaves the conversation unstuck (terminal status, input re-enabled, confirmation no longer actionable).
- The plain-terms state vocabulary distinguishes waiting / resumed and continuing / resolved / no longer resumable, and acknowledging a no-longer-resumable turn never retries or double-applies a change.
- Approving applies the confirmed change exactly once even when the approval is delivered more than once; a denied or expired confirmation never applies anything.
- Resuming requires no identity token or DB credential from an execution service, and the durable turn information contains no sensitive material.
- A resumed turn stays scoped to its conversation and tenant and is attributed to the user who actually responded.
- "Shown as waiting for your input" is structurally equal to "actually resumable" (`active_resume_id` gate), and the in-process pause future is retired from conversational production paths.
- No new datastore dependency is introduced: CC remains the only DB accessor.

## Test File References

All paths verified present in the workspace (2026-11). Naming: **new** = added by this change · **extended** = grown by this change · **existing** = delivered earlier and re-run here.

### Backend — unit
| File | Status | Covers |
|---|---|---|
| `backend/tests/unit/conversations/test_conversation_turn_resume_store.py` | existing | Create-or-reuse, supersede, legal/illegal transitions, claim contention and re-acquire after lease expiry, reject `approved_applied` without `write_applied` |
| `backend/tests/unit/conversations/test_turn_checkpoint_store.py` | existing | Upsert-in-place, byte cap, consume-once, expired/consumed load, purge while the index survives |
| `backend/tests/unit/conversations/test_resume_terminal_resolver.py` | existing | Resolver branches (protected, expired, superseded, cancelled, checkpoint-lost, stale resuming), three-way agreement, one outcome turn, no false notice |
| `backend/tests/unit/test_turn_checkpoint_endpoints.py` | existing | Internal resume/checkpoint/claim/release/complete under service-cert auth; duplicate complete; unknown session 404; cross-tenant denial; allowlist membership |
| `backend/tests/unit/test_management_tool_idempotency.py` | new | Crash-retry after commit returns the stored summary; denied/cancelled/expired/`resume_failed` turns refuse a late dispatch; row lock serialises duplicate marker reads |
| `backend/tests/unit/test_management_tool_applied_marker.py` | existing | Marker commits with the write, rolls back with a failed write, absent without a key |
| `backend/tests/unit/test_conversation_sessions_resume_projection.py` | existing | Sessions listing resume projection (`resume_state` / `resume_outcome` / `resume_expires_at`), null for idle |
| `backend/tests/unit/test_human_intervene_persists_activity.py` | existing | Pause persists intervention + waiting activity + live resume id |

### Backend — Agent Runtime
| File | Status | Covers |
|---|---|---|
| `backend/tests/agent_runtime/test_durable_checkpointer.py` | existing | Saver round-trip via fake transport, super-step coalescing, `flush()` blocks on the outstanding write, schema/deserialisation mismatch raises typed unavailable, re-pause persists the new pause point |
| `backend/tests/agent_runtime/test_conversational_resume_from_checkpoint.py` | existing | Pause persists checkpoint + index before waiting; resume on a second simulated instance; contention 409; missing checkpoint → `unresumable`/`resume_failed`; re-pause during resume; paused-stream end on first pause; claim lost mid-run aborts |
| `backend/tests/agent_runtime/test_checkpoint_transport.py` | existing | All calls target CH URLs, tenant headers from the shared egress hook, typed relay errors, idempotency header only inside a paused turn, no DB access |
| `backend/tests/agent_runtime/test_resume_registry_miss_orphan.py` | existing | Durable-state semantics replace the in-process registry miss; no false terminal notice; job path unchanged |
| `backend/tests/agent_runtime/test_ar_activity_persistence_boundaries.py` | existing | AR holds no DB session/model import, connection string, datastore endpoint or raw httpx client; pause/resume ordering; no secrets in status events |
| `backend/tests/agent_runtime/test_turn_idempotency_propagation.py` | existing | The turn key travels on every confirmed-write call and never outside a paused turn |

### Backend — Communication Hub
| File | Status | Covers |
|---|---|---|
| `backend/tests/communication_hub/test_resume_router_dispatch.py` | existing | Single dispatch/outcome under duplicate or concurrent responses, stored-outcome short-circuit, one reply pushed, paused-during-resume reply withheld, durable-state terminal notice, retryable dispatch failure |
| `backend/tests/communication_hub/test_turn_checkpoint_relay.py` | existing | Byte-for-byte relay, forwarded-not-minted signed headers, size guard (413, nothing forwarded), typed relay errors, no persistence |
| `backend/tests/integration/test_multitenant_auth_chain.py` | existing | Structural proof that AR/CH trees never sign tenant contexts |
| `backend/tests/communication_hub/test_tenant_header_verification.py` | existing | Signed-set verification on `/internal/*` |

### Backend — integration / DB / e2e
| File | Status | Covers |
|---|---|---|
| `backend/tests/db/test_conversation_turn_resume_migration.py` | new | `information_schema`/`pg_catalog` verification of both tables, column/nullability reconciliation, `active_resume_id` FK, enum value sets, unique `idempotency_key`, 1:1 checkpoint, one-live-resume index, FK ondelete, negative constraint tests, legacy-shaped activity row, upgrade/downgrade cycle |
| `backend/tests/integration/test_conversation_pause_resume_flow.py` | new | Real pause → waiting activity + live resume; approve → resuming → exactly one write → `approved_applied` once, `active_resume_id` cleared, one outcome turn; deny → `denied`, nothing written, late dispatch refused; payload content scan |
| `backend/tests/integration/test_conversation_interruption_notice.py` | existing | Reason-keyed terminal outcomes replace the fixed notice; no notice on success; distinct expired vs lost-pause-point texts; repeated responses keep one outcome turn |
| `backend/tests/integration/test_internal_intervene_respond.py` | existing | Respond advances the resume record in the same transaction as the stored answer; duplicate answers return the stored outcome |
| `backend/tests/integration/test_internal_allowlist_partitioning.py` | existing | AR vs CH internal route partitioning |
| `backend/tests/integration/test_internal_tenant_header_failclosed.py` / `test_database_isolation.py` | existing | Fail-closed internal data plane without signed headers; AR/CH hold no DB session factory |
| `backend/tests/e2e/test_assistant_resume_after_restart_e2e.py` | new | Pause on instance A, flush, discard A's memory, claim + load + continue on instance B; contention and failover after lease expiry; terminal turn not claimable or re-appliable; one applied write and one outcome turn |

### Frontend
| File | Status | Covers |
|---|---|---|
| `frontend/src/__tests__/ConversationDialog.resumeRecovery.test.tsx` | existing | Four-state rendering, reason-specific terminal card with next step + dismiss, input re-enabled, approve/deny inert on terminal, degraded waiting without a resume id |
| `frontend/src/__tests__/useChatSession.activityState.test.ts` | existing | Hydration preserves `message`, `activeResumeId`, `terminalReason`, `resumeState`; live status projection |
| `frontend/src/__tests__/useChatSession.finality.test.ts` | existing | Terminal detection unchanged across the extended kind union |
| `frontend/src/__tests__/useChatSession.intervention.test.ts` | extended | `responded` closes the confirmation and keeps/advances the turn correctly; no false "Resumed · continuing" on a local answer |
| `frontend/src/__tests__/ConversationDialog.activityIndicator.test.tsx` | existing | Waiting indicator gated on the live resume id; cleared on terminal |
| `frontend/src/__tests__/ConversationDialog.intervention.test.tsx` | existing | Confirmation controls only while resumable |
| `frontend/src/__tests__/ConversationSessionsTab.test.tsx` | existing | Resume-state badges match the API projection; no badge without a resume record |

### E2E
| File | Status | Covers |
|---|---|---|
| `e2e/tests/conversation-resume-recovery.spec.ts` | new | Pending → approve → resumed and continuing → resolved with input re-enabled; deny → resolved without a card; terminal card (reason, next step, dismiss, input enabled); stale approval on a terminal turn sends nothing; reload hydration restores waiting and the terminal message; degraded waiting without a resume id |
| `e2e/tests/conversation-resume-recovery.real-backend.spec.ts` | new | `Real Backend Integration - resumable agent turn persistence` — no `page.route()`: live CC internal resume/checkpoint/claim/release/complete routes registered and fail-closed for non-CH callers and for an operator JWT; sessions listing carries the resume projection from the migrated database (500 → explicit migration error); a real session round-trips through the resume endpoint. Skips without a live stack/token |
| `e2e/tests/conversation-activity-state.spec.ts` | extended | Waiting assertion disambiguated for the resume-state chip; terminal `finished` asserted through the resolved vocabulary and spinner clearing |
| `e2e/tests/conversation-intervention.spec.ts` | extended | Live-backend probes tolerate the tenant-gated 403 |
| `e2e/tests/conversation-sessions.spec.ts` | extended | Paginated `/conversations/sessions` mocks; `load` instead of `networkidle` |
| `e2e/tests/conversations.spec.ts` | extended | Query-param conversation list mock; turn-count assertion scoped to the table cell |
| `e2e/tests/intervene.spec.ts` | extended | Translated Respond/Yes labels; approval submits on Yes; page-level pending-count assertion |

### Manual / operational drills (recorded evidence)
- Pause → restart CC / CH / AR respectively → approve: continued turn plus the matching service log (resolution lines, dispatch count = 1, checkpoint load on the new process); no `timeout_or_failed`.
- Pause → wait past the validity window → approve: terminal card with the specific reason and next step, input enabled.
- Pause on AR A → answer on AR B: single continued turn with claim ownership visible in logs.

**Test data & cleanup:** identifiable prefixes (`e2e-test-resume-<timestamp>`), fixture teardown removing resume records, checkpoints, interventions, activity rows, turns and sessions; clock-dependent scenarios use injected time, never real sleeps; tenant-scoping scenarios create two tenants and clean both.

## Related Test Plans

- [Conversational Intervention](conversation-intervention-test-plan.md) — activity state, inline intervention surfacing, pause bookends.
- [Human Intervene](human-intervene-test-plan.md) — non-conversational dashboard flow (unchanged).
- [Conversation Sessions](conversation-sessions-test-plan.md) — session lifecycle and listing.
- [Agent Runtime](agent-runtime-test-plan.md) / [Communication Hub](communication-hub-test-plan.md) — execution and internal routing boundaries.
- [Optimizer Conversation](optimizer-conversation-test-plan.md) — the optimization conversation reuses this pause/resume chain for in-chat decisions.
