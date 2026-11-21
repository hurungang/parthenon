# Test Plan: Optimization-Mode Conversation & Live-Test Approval

**Change:** `optimizer-conversational-agent` (2026-11). Final shipped state.
**Companion plan:** `optimizer-test-plan.md` (gated Optimize action, explicit plan authoring, model settings, `requires_fix`).

## Scope

Optimization as an **optimization-mode conversation on the subject agent type itself**:

- a `ConversationSession` with `channel="optimization"` and the subject stored as its own `agent_type_id` (scope is inherent — there is **no** scope column),
- availability for **both typed and conversational** agent types, with the mode derived from the persisted channel,
- in-chat ask/decide (inline, never the interventions dashboard),
- replay-only verification with **one single-use live-test approval of a saved script**,
- replay-vs-live audit, and channel isolation from business conversations.

Out of scope: the one-shot gated Optimize action and model settings (`optimizer-test-plan.md`), sandbox internals (`sandboxed-scripting-test-plan.md`), and durable pause/resume transport (`conversation-intervention-test-plan.md`).

## Test Strategy

| Layer | Location | What it proves |
|---|---|---|
| Backend unit | `backend/tests/`, `backend/tests/unit/` | Optimization-mode turn composition (mission replaces business instruction/skills; business MCP tools absent), routing derivation from channel, live-test ledger state machine + preview derivation, answer-path consume-once ordering |
| Backend integration/API | `backend/tests/` | Conversation create/read guards, subject immutability, per-handler scope refusal with zero writes, identity/permission parity, internal `412 optimizer_model_unavailable`, CC→CH→AR live-test chain, `runtime_tool_calls.optimization_live_test_request_id` ingest, WS `chat_error` / `live_test` payloads, migration + tenant-isolation sweep |
| Frontend component | `frontend/src/__tests__/` | Optimizer entry (typed + conversational), chat chrome ("What ran in this session" bar, model alert, single processing indicator), ask card, script-based approval card, `useChatSession` / conversation hook parsing |
| E2E (mocked first) | `e2e/tests/` | Full journeys: entry → scoped chat → single indicator → plan refresh; conversational agent; ask/decide; out-of-scope refusal; business-chat containment; approve/deny/expiry; model stale/unset |
| E2E (real backend) | `e2e/tests/` | `test.describe('Real Backend Integration …')` — conversation create/read + empty ledger with no mocks (mandatory: `has_db_changes: true`), failing loudly on an unapplied migration |
| Manual drill | live stack | A real approved live test against the demo agent; reconnect during a pending decision |

Lifecycle focus: conversation = create → read (subject/availability/audit) → turns + ask/decide → end (bounded stop, plan outcome); approval = request → pending (re-surfaces) → decide → execute once → terminal (executed/failed/denied/expired/cancelled, retained for audit).

## Coverage Areas

| Area | What & Why |
|---|---|
| No seeded optimizer agent | Startup creates no optimizer `AgentType`, role, identity, skill binding or seed row; a second startup writes nothing. Optimization is a mode of an existing agent, so there is no new privilege surface to administer. |
| Identity & permission parity | A turn resolves the **subject agent type's** own identity, role and tool grants; no permission bridge, elevated/shared identity or widened grants. Lacking permission to optimize/execute declines with no work; attribution is the agent type + the authenticated operator. |
| Conversation on the subject | `agent_type_id` = the subject and `channel="optimization"`; the subject survives reconnect/resume/model change and cannot be repointed through any public API; different subject = different session. |
| Entry & availability (typed + conversational) | The Optimized Plan tab offers the conversation for both topologies, annotated "this agent only", with the optimizer model disclosed and the existing Optimize/retire actions retained. Missing preconditions are explained by the conversation, which is created with an availability projection (computed, never stored) and starts no work. |
| Turn routing | `channel="optimization"` selects the conversational loop for typed **and** conversational subjects; every other channel keeps today's routing. Mode comes from the persisted channel, not prompt text. |
| Prompt & tool mode containment | Inside the conversation the optimization mission replaces the business instruction and skills and the optimization tools are injected; the agent's granted MCP tools are reachable only through an approved live test. Outside it, business instruction/skills/grants are unchanged and no residual mode survives the session. |
| Chat turns & activity | `prepare-turn`/`append-turn` persistence; while working the transcript shows exactly ONE chat-status indicator (the folded optimizer-activity block is gone); a terminal turn clears it; a hang/failure surfaces as `timeout_or_failed` / `guardrail_<reason>`, never an eternal spinner. |
| In-chat ask/decide | Question/choice/free-text via `human_intervene` → `InterveneRequest` → resume: session `waiting_for_human`, composer disabled, a new turn refused server-side with no side effect, the request re-surfaces on reconnect, exactly one resume per answer, no dashboard/queue and no background retry. |
| Live-test approval (single use, script-level) | `request_live_test {script_version_id, reason}` persists one ledger row (`pending`, with a server-derived tool-call preview) plus the linked approval in one transaction. Validation refuses unknown/foreign-tenant/foreign-agent versions, versions without `python_source` or a literal `tools.call`, previews outside the subject's grants, sensitive-material arguments, a second pending request and the per-session cap. Approval is consumed once, the script runs once end to end as the subject, its run record returns into the resume, and a later need requires a brand-new request. |
| Deny / expiry / cancel | Nothing runs; the row is retained (`denied` / `expired` / `cancelled`), the session stays replay-only, expiry closes the linked intervention and appends a bounded stop, and the request is never retried or resurrected. |
| Exactly-once | Duplicate/replayed approvals and concurrent decisions produce exactly one execution, one applied write and one outcome turn; a stale answer to a terminal row returns the stored outcome and never re-applies anything. |
| Replay-only default | `execute_script` stays replay-only; a miss is a terminal `needs_user_input` stop, never a silent live call or retry. The approved live test is the only live route, initiated only by CC's ledger service (no public/AR/CH-callable entry point). |
| Permission denial mid-run | The run stops, remaining operations are not attempted, the ledger becomes `failed`, replay-only is restored and the failure is shown in chat. |
| Scope inherent (server-side) | Every `agent_type_id`-taking handler accepts only the session's own agent type; other agents/plans/scripts/logs, settings, permissions and deletion are refused (`out_of_scope`) with zero reads/writes, so prompt-injected drift cannot widen scope. |
| Channel isolation | Creating an optimization session writes no business session; a business chat on the same agent type keeps the ordinary composer, its own session and model, and never reads the ledger; listings distinguish `channel="optimization"`. |
| Audit: replay vs live | Replay evidence stays `VerificationRun`/`ScriptExecutionRecord`; live evidence is the ledger row plus `RuntimeToolCall` rows carrying `optimization_live_test_request_id` (`NULL` for ordinary/replay calls); the session bar distinguishes N replay verifications from N approved live operations; decided cards stay inline at their decision position. |
| Plan outcome & refresh | Outcomes persist through the unchanged `generate_optimized_plan` allow-list (`ready` / `needs_feedback` / `failed`); nothing bypasses verification because it was discussed in chat; the tab invalidates the subject's scope on turn completion and polls only while in flight. |
| Migration | One revision: live-test table + owned enum, one nullable `runtime_tool_calls.optimization_live_test_request_id` (FK/index); **no** conversation scope column and no seed data; reversible downgrade; `channel="optimization"` needs no schema change. |
| Tenancy & segregation | Everything resolves from the session tenant (root when multi-tenancy is off); CC→CH→AR live-test traffic uses the signed-tenant egress client (CH/AR never sign, fail closed without headers); only identifiers + the approved script source cross the boundary; the new entity and `/internal/live-test/run` are registered in the isolation sweep and allowlist coverage. |

## Critical Scenarios

### Entry & availability
- WHEN the Optimized Plan tab renders for a typed **or** conversational agent THEN the entry is offered, annotated as scoped to that agent, with the model disclosed and Optimize/retire retained.
- WHEN the conversation is created THEN `channel="optimization"`, `triggered_by_user_id` is the operator, availability is returned but not stored, and nothing is dispatched.
- WHEN the subject is missing or the operator lacks view permission THEN the API returns `404` / `403` and no session row is written; lacking optimize/execute permission declines and starts no work.
- WHEN no usable optimizer model exists THEN the conversation is still created, availability reports the reason, the chat shows the model alert with a disabled composer and a System Config shortcut, and no work starts.
- WHEN the operator opens the surface without sending a message (page load, listing, reconnect) THEN no turn, plan generation or live request is created.

### Routing & mode containment
- WHEN an optimization-channel session executes THEN the conversational loop runs for both topologies.
- WHEN a typed agent receives a normal business submit, or a conversational agent receives a business chat turn, THEN routing and behaviour are exactly as today.
- WHEN an optimization turn is prepared THEN the system instruction is the optimization mission, business skills are not composed, and the agent's granted MCP tools are not exposed.
- WHEN the conversation ends THEN a later business run shows the business instruction/skills and no optimization tool or mission text.

### Chat turns & ask/decide
- WHEN a turn streams THEN exactly one chat-status indicator is shown (thinking → tool, updated in place) and none survives a terminal turn.
- WHEN the optimizer needs a decision THEN an inline card appears, the composer blocks, a second message is refused server-side, the request re-surfaces after reconnect, and exactly one answer frame resumes the turn with the answer retained in the conversation record.
- WHEN nobody answers THEN the session stays waiting — no assumption, no retry, no background work.
- WHEN the session is ended while a request is pending THEN the request is closed and nothing resumes.

### Scope
- WHEN a request names another agent type's plan/scripts/execution log, or asks for settings/permission changes or deletion THEN it is declined with `out_of_scope` in-channel with zero reads/writes for the other resource.
- WHEN a request asks for credentials, identity tokens or database access THEN it is refused and never requested.

### Live-test approval
- WHEN a live test is requested THEN the card names the saved script version, shows the server-derived preview ("It will call: …"), states the whole script runs once as this agent and is not remembered, and blocks the composer.
- WHEN the request is invalid THEN it is refused with the matching reason code and neither a ledger row nor an intervention is created.
- WHEN the operator approves THEN one decision frame is sent, the card collapses, pending → running → executed shows the script run record inline at its decision position, the session bar moves from replay-only to N approved live operations, and the refinement lands a `ready` plan without a reload.
- WHEN the operator denies THEN nothing runs, the card collapses to a read-only `denied` summary, replay-only stays in force, and the turn ends with a bounded "what is missing" stop and no retry.
- WHEN the request expires unanswered THEN it closes as a distinct `expired` terminal state, no decision frame is sent, and no retry is scheduled.
- WHEN an approval is re-delivered, double-clicked, or arrives after expiry THEN the stored outcome is returned, exactly one execution occurred, and a stale answer can never re-apply a write.
- WHEN a permission denial occurs mid-run THEN the run stops, remaining operations are not attempted, the ledger becomes `failed`, replay-only is restored and the failure is visible in chat.

### Audit & isolation
- WHEN the conversation is reviewed THEN replay and live counts are distinct with the single-use note, every live call carries the ledger pointer (`NULL` for ordinary/replay calls), and the decision is attributed to the operator + subject agent type.
- WHEN a business conversation runs on the same agent type (even while a request is pending) THEN it uses the business instruction/skills, its own session and model, never reads the optimizer model or the ledger, and is not blocked by the optimization pause.
- WHEN an optimization session is ended or archived THEN business conversations and normal runs are unchanged.

### Migration / tenancy / segregation
- WHEN the revision is applied THEN the table, its enum and the nullable pointer exist, pre-existing rows keep `NULL`, upgrade → downgrade → upgrade succeeds, and no conversation/agent-type column or seed row was added.
- WHEN live-test traffic flows CC → CH → AR THEN it uses the signed-tenant egress client, fails closed without headers, and carries identifiers + the approved script source only.
- WHEN the tenant-isolation sweep and internal allowlist coverage run THEN the new entity is probed and `/internal/live-test/run` is never treated as a CC internal endpoint.

## Edge Cases & Risks

| Risk | Mitigation / coverage |
|---|---|
| Typed agent's business path disturbed | Optimization uses the conversational loop only for the optimization channel; typed submits keep the task loop and output schema (explicit assertions) |
| Conversational agent with no plan/evidence | Conversation opens, availability names exactly what is missing, nothing is fabricated; a later successful business conversation clears availability without a code change |
| Approval expiring while the run executes | The sweep closes only `pending` rows; an in-flight row is not torn down and no additional run can start |
| Double approve / concurrent tabs / re-delivered frame | Conditional transition + resume marker → one execution, one resume, one outcome turn |
| Operation not in the approved list | AR verifies against the approved set and the subject's grants before each call; unlisted calls are rejected, the remainder skipped, ledger `failed` |
| Model removed mid-conversation | Next turn fails closed with not-enabled guidance; a pending decision still resolves without execution |
| Reconnect with a pending question | Request re-surfaces with script + expiry + preview, composer stays blocked, one resume |
| Two optimization conversations on one agent type | Per-session ledger/quota isolation; the plan reflects the last writer atomically |
| Plan-less agent remount | The dialog is mounted once outside the plan section and only real turn activity is reported to the host (E2E-covered regression) |
| Chat chrome stuck on "live test running" | The approved marker clears when the `live_test_result` chunk or a terminal ledger row arrives (E2E-covered regression) |
| Prompt-injected scope drift / secrets | Structured in-channel refusal with zero reads/writes; secrets never requested or surfaced |
| Unapplied migration | Real-backend E2E fails loudly on `5xx` from the conversation/ledger endpoints rather than skipping |
| i18n drift | Every optimizer string resolves from `en.json`; reason/chat-error vocabularies covered |

## Acceptance Criteria

- Optimization is a mode of the selected agent type with its existing identity, role and permissions — no separate optimizer identity, role or seed rows.
- The conversation is available for typed and conversational agents, clearly scoped to one agent, and starts no work on open.
- Entering optimization mode does not change normal business behaviour; instructions, skills, grants and routing are unchanged outside the conversation.
- Scope is exactly the selected agent's plan, scripts, execution history and reference run; anything else is declined with nothing changed; deletion is never available.
- Replay-only is the default; one live test requires an explicit single-use approval of a saved script, runs once end to end as the agent, and its result returns to the conversation.
- Deny/expiry/cancel run nothing and never retry; duplicate/late answers never re-execute.
- Every live request, decision and run record is retained and auditable, attributed to the agent + operator, and distinguishable from replay.
- The plan produced follows the unchanged verification lifecycle and refreshes without a manual reload.
- No sensitive material crosses the conversation, ledger, resume or internal payloads.
- The conversation never mixes with business conversations in either direction.

## Test File References

All paths verified present in the workspace (2026-11).

### Backend — `backend/tests/`

| File | Covers |
|---|---|
| `test_optimization_mode_context.py` | Mission replaces business instruction/skills; optimization tools present, business tools absent; optimizer identifiers; fail-closed `412`; identity parity |
| `test_optimization_mode_routing.py` | Both topologies run the conversational loop in the optimization channel; business routing unchanged; channel-derived mode; no optimizer seed rows |
| `test_optimization_subject_guard.py` | Every `agent_type_id`-taking handler refuses foreign subjects with zero writes |
| `test_optimization_conversation_api.py` | Create/read guards, no scope field, availability never stored, creation starts no work, subject immutability, ledger read |
| `unit/conversations/test_optimization_live_test_ledger.py` | Validation matrix, preview derivation, state machine, single-shot begin, denial retained, expiry sweep + lazy expiry, audit projection |
| `test_optimization_live_test_runner.py` | Approved version forwarded once, run record carried in resume, terminal failures never retried, retired scripts never run |
| `unit/conversations/test_turn_resolution_live_test.py` | Claim → execute → resume ordering, duplicate answer no-op, late answer refused |
| `test_optimization_live_test_migration.py` | Entity round-trip, nullable pointer, channel needs no migration, reversible DDL, no seed data |
| `test_internal_request_live_test_tool.py` | One transaction writes ledger + approval; caller operations ignored; replay returns stored proposal |
| `test_tenant_isolation_sweep.py` | `OptimizationLiveTestRequest` registered and probed |
| `agent_runtime/test_live_test_execute.py` | Capability check, one end-to-end sandbox execution, one `script_run` record, ledger pointer per call, no DB access |
| `communication_hub/test_live_test_forwarding.py` | Verbatim CC→CH→AR body, signed headers forwarded not minted, `503` without certificate, error mapping |
| `test_api_ws_chat_optimizer_errors.py` | Optimizer `chat_error` codes, `chat_blocked` (`decision_pending`), `live_test` block, `live_test_result` chunk |
| `test_internal_endpoint_allowlist_coverage.py` | `request-live-test` CH-allowlisted; `/internal/live-test/run` never a CC internal endpoint |

### Frontend — `frontend/src/__tests__/`

| File | Covers |
|---|---|
| `AgentOptimizedPlanTab.optimizerEntry.test.tsx` | Entry for typed + conversational agents, "this agent only", blocked reasons, plan refresh after a turn |
| `OptimizerChatDialog.test.tsx` | Subject title + identity chip, session bar, model alert, decision-pending block, ask card payload, approval payloads, no chrome leakage in business/assistant mode |
| `OptimizerPanels.test.tsx` | Session bar (replay-only / live-used / running), activity block, audit block, model alert variants |
| `LiveTestApprovalCard.test.tsx` | Script-based approval copy + preview, approve/deny payloads, pending as the only expanded state, collapse-to-summary per terminal state, expiry distinct |
| `OptimizerAskCard.test.tsx` | Question/choices/free-text, single submission, resolved state, in-flight blocking |
| `useChatSession.optimizer.test.ts` | `live_test` / `live_test_result` parsing, optimizer `chat_error`, `chat_blocked`, activity-step derivation |
| `useOptimizationConversation.test.tsx` | Subject-only creation payload, conversation/ledger reads, card-state mapping, plan/gate invalidation |
| `errorUtils.optimizer.test.ts` | Refusal extraction (`422`/`412`/system-tool/WS), chat-error and decision-pending guards |
| `optimizerI18n.test.ts` | Every optimizer `t()` key resolves in `en.json`; single-use safety copy present |

### E2E — `e2e/tests/`

| File | Covers |
|---|---|
| `agent-optimizer-conversation.spec.ts` | Typed journey (entry, scoped chat, single indicator, plan refresh), conversational agent informational state, ask/decide, out-of-scope refusal with zero writes, business-chat containment |
| `agent-optimizer-live-test-approval.spec.ts` | Approve once (inline executed run record, audit counts), deny, expiry, re-delivered decision read-only, session bar returns from running |
| `agent-optimizer.real-backend.spec.ts` | No mocks: subject-only conversation create/read, empty ledger, fail-closed unknown session |
| `_agent_optimizer_world.ts` | Shared mocked optimizer world, script-level live-test fixtures, drivable fake chat socket, request observer for "zero writes" |

## Related Test Plans

- [Optimizer — Gate, Authoring & Self-Healing](optimizer-test-plan.md) — one-shot Optimize, plan authoring, model settings, `requires_fix`.
- [Conversational Intervention](conversation-intervention-test-plan.md) — pause/resume transport, activity state, durable resume.
- [Conversation Sessions](conversation-sessions-test-plan.md) — session lifecycle and listing.
- [Agent Runtime](agent-runtime-test-plan.md) / [Communication Hub](communication-hub-test-plan.md) — execution and internal routing boundaries.
- [Sandboxed Scripting](sandboxed-scripting-test-plan.md) — replay tool client and sandbox guarantees.
