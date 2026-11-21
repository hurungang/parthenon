# Test Plan: Conversational Optimizer (Optimization Mode on the Agent Itself)

Owner: tester
Change: `docs/changes/optimizer-conversational-agent/` — optimization becomes an **optimization-mode conversation on the subject agent type itself** (the avatar model). Same identity, same role, same tool permissions; **no** seeded optimizer agent type, identity, role, or permission bridge. The conversation is a `ConversationSession` bound to the agent type with `channel="optimization"` and **no scope column** — the session's own agent type *is* the subject, so scope is inherent. Optimization mode runs the conversational loop for **both typed and conversational** agent types; normal business runs are unchanged. Replay stays the default; one precisely listed live test can be approved **once**. The optimizer runs on a workspace `optimizer_model_id` that falls back to the plan-authoring model, never the agent's runtime model. `has_db_changes: true` (one new entity `OptimizationLiveTestRequest` + enum, one nullable `runtime_tool_calls.optimization_live_test_request_id`; `channel` is an existing free-form string, so the mode needs no migration).

Scope note: the guarantee under test is **not** "the optimizer behaves" but "the optimizer cannot exceed the agent": identity/permission parity, inherent scope, replay-only default, single-use approval and model choice are all enforced server-side, so the suite must prove refusals and no-write outcomes, not just happy paths. The second guarantee is **mode containment**: optimization replaces the agent's business instruction and skills only inside that conversation channel, and never leaks into a business run.

## Test Strategy

Four layers, each proving a different slice of the same lifecycles (identity parity, mode routing, replay-vs-live routing, single-use approval, optimizer-model resolution, plan outcome):

1. **Backend unit tests** (`backend/tests/`, `backend/tests/unit/`) — the primary safety net. Deterministic, no-network coverage of:
   - the optimizer **model resolver** (explicit → authoring fallback, stale/disabled/not-configured derivation, never rewritten, never the agent runtime model),
   - **optimization-mode turn composition** (the optimization mission replaces the business system instruction and skills, the optimization tools are injected, the agent's granted MCP tools are absent from the loop except for an approved live test, and a business turn is composed exactly as today),
   - **routing derivation** (an optimization-channel session always selects the conversational loop regardless of the agent type's input type; every other run keeps today's routing),
   - the **live-test ledger** (validation matrix, state machine, conditional single-shot transition, denial retained, expiry sweep + lazy expiry, audit projection),
   - the **turn-resolution answer path** (consume-once-before-resume ordering, duplicate answer is a no-op returning the stored outcome, denial resume),
   - the **gate** (optimizer-model fields; conversational agent types no longer refused for optimization; existing precedence for the one-shot action intact).
2. **Backend integration/API tests** (`backend/tests/` API-level over the real ASGI app) — the contract surface: the optimization-conversation create/read endpoints (guards, subject stored as the session's own agent type, `channel="optimization"`, availability returned but never stored, creation starts no work), channel isolation in listing/permissions, the inherent-scope guard across every `agent_type_id`-taking optimization handler (refusal with zero writes), **identity parity** (the resolved turn context uses the subject's own identity/role/tool grants; no created identity, role, or binding rows; no elevated/shared identity), the internal agent-context `412 optimizer_model_unavailable` fail-closed path and optimization-mode context, `request_live_test` refusals, the CC→CH→AR live-test run chain, `RuntimeToolCallRecord.optimization_live_test_request_id` ingest, the WS `chat_error`/`live_test` payloads, and `GET/PUT /agents/model-configs/optimizer-model` (tenant-scoped options, `422`, `null` clears, stale value still visible) plus the extended `optimization-gate` payload.
3. **Frontend component tests** (`frontend/src/__tests__/`) — Vitest + Testing Library over the operator-visible contract: the Optimized Plan tab entry (**available for typed and conversational agent types**; scope annotation "this agent only"; blocked-with-reason + System Config shortcut; post-turn plan refresh; existing Optimize/retire/feedback actions retained), optimizer chat chrome (subject title + identity-parity chip tooltip, the compact default-collapsed "What ran in this session" bar with replay-only / live-used / running chips that expands to the audit detail + scope + identity, model alert with composer disabled, the single chat-status processing indicator — the folded optimizer-activity block was removed from the chat), the ask card (options + free text, resolved state, composer blocked while pending), the **script-based** live-test approval card (script name/version, informational tool-call preview, approve/deny payloads, pending as the only expanded state and collapse to a one-line history summary for approved/running/executed/failed/denied/expired/cancelled that expands to the script run record, "the whole script once, not remembered"), the System Config optimizer-model section (workspace scope, inherit-from-authoring, catalogue-only, stale/unset reminder, `422` through the dialog error standard), and `useChatSession` parsing/blocking. i18n regression: every new string resolves from `en.json` via `t()`.
4. **E2E tests** (`e2e/tests/`, Playwright — mocked-first via `page.route()`) — the journeys: open from the tab on a **typed** agent → scoped chat → activity expansion → inline ask/decide → out-of-scope decline → plan refresh without reload; the same journey on a **conversational** agent; review the script request → approve → that script runs once → its run record in chat → plan `ready`; deny → replay-only bounded stop; expiry keeps replay-only; System Config unset/stale/unconfigured states. Because this change has DB schema changes, **one `test.describe('Real Backend Integration - …')` spec is mandatory** (per `docs/master/qa/testing-strategy.md`) to catch an unapplied migration behind the conversation/ledger endpoints, skipping honestly when the stack/token is unavailable.

Live-verification note: heartbeat/watchdog behaviour and real socket re-surface of a pending decision are asserted at the transport layer by the existing conversation suites; if a live run is used to confirm the paused-turn/socket path, it is evidence only and never reported as a substitute for the deterministic suites.

Testing is lifecycle-focused: conversation = create (open on the subject agent type, mode set) → read (mode/scope/availability/audit) → update (turns, ask/decide) → end (bounded stop, plan outcome, mode released); approval = request (create) → read (ledger, pending re-surface) → decide (attack surface for double-decision) → execute (single use) → terminal (executed/failed/denied/expired, retained for audit). No test code lives in this plan.

## Coverage Areas

| Area | What & Why |
|---|---|
| **No seeded optimizer agent, role, or identity** | Startup creates **nothing**: no optimizer `AgentType`, no `is_system` row, no agent role, no identity, no skill/binding rows, no data seed. Optimization is a conversation mode of an existing agent type, so there is nothing optimizer-specific to administer, edit, remove, govern, assign, schedule, delegate, or itself optimize. A second startup writes nothing. This is the difference between "no new privilege surface" and "a new system agent nobody asked for". |
| **Identity & permission parity** | An optimization-mode turn resolves the **subject agent type's** own identity, role and tool grants — the same envelope a business run uses. No permission bridge, no elevated/service/shared identity, no widened grants. Starting the conversation requires the operator's existing permission to optimize/execute and to view the agent type; a missing permission is a clear decline with no work. Any operation the agent could not perform is refused. |
| **Optimization-mode conversation on the subject agent type** | A `ConversationSession` with `agent_type_id` = the subject and `channel="optimization"`. There is **no scope field**: nothing to compare, widen, or repoint. The subject is a row property, survives reconnect/resume/model change, and cannot be changed through any public API. Different subject = different session. |
| **Conversation entry & availability (typed and conversational)** | The Optimized Plan tab of an agent type offers the optimization conversation for **both typed and conversational** agent types, annotated as reaching only that agent. Missing preconditions (no successful reference execution, no usable optimizer model) are **explained by the conversation**, which is created with an availability projection computed (never stored) and starts no work. Entry hides only where optimization is genuinely unavailable; the one-shot Optimize action stays where it exists. |
| **Turn routing** | The executor chooses its loop from the session's mode: `channel="optimization"` selects the conversational loop for typed **and** conversational agent types. A typed agent's business submit, a conversational agent's business chat, an assistant turn and an integration-client turn all keep today's routing byte-for-byte. |
| **Prompt & tool mode inside optimization mode** | Inside the conversation the optimization mission replaces the business system instruction and skills, and the optimization system tools are injected. The agent's granted MCP tools are **not** available to the loop; they are usable only through an approved live test. Outside the conversation the business instruction, skills and grants are unchanged, and after the session ends no residual mode survives. |
| **Chat turns & activity** | Reuses the conversational runtime unchanged: prepare-turn persists the user turn + `thinking`; append-turn persists the reply, status and guardrail usage. While working, the transcript shows exactly ONE processing indicator (the normal chat-status indicator: working → which tool is running, updated in place) — there is no separate folded activity block. A finished turn reports what was produced. A hang/failure surfaces as a structured terminal outcome (`timeout_or_failed` / `guardrail_<reason>`), never an eternal spinner. The first turn opens already scoped and informed (scope block + subject plan/script/reference-run context). |
| **In-chat ask/decide (lightweight)** | Question/choice/free-text rendered inline through the existing `human_intervene` → `InterveneRequest` → resume chain. While pending: session is `waiting_for_human`, the composer is disabled and a new user turn is **refused server-side with no side effect**; the pending request re-surfaces on reconnect/resume via the pending-interventions read. The answer is recorded in the conversation record and steers refinement. Explicitly **not** the interventions dashboard: no queue, no cross-session list, no background retry. |
| **Live-test approval (single use, SCRIPT-level)** | A live test runs the SAVED SCRIPT end-to-end — never an individual MCP tool call (MCP tools are assumed to work). `request_live_test` takes `{script_version_id, reason}` and persists one `OptimizationLiveTestRequest` (`pending`, with a server-derived tool-call **preview** in `requested_operations`) plus the linked approval intervention in one transaction. Validation: the version exists in the conversation's tenant, has `python_source`, belongs to the subject agent type, contains at least one literal `tools.call`, its preview is within the subject's own grants when resolvable, one pending per conversation, per-session approved-live cap. Approval is consumed **once** (conditional transition + the resume's exactly-once marker), then that one script runs once, end to end, under the subject agent type's identity → the **script run record** (`kind: "script_run"`, result summary, per-`tools.call` outcomes, telemetry, duration) returns into the resume value → the model refines with **no further live call**. Deny/silence/expiry keeps the session replay-only, closes the request, and never retries it. Approval never persists beyond the single test. |
| **Replay-only default vs approved live** | `execute_script` remains replay-only (`ReplayToolClient`, recorded `tool_calls`); a miss/missing transcript is a terminal `needs_user_input` stop, never a live fallback and never a retry loop. The approved live test is the **only** live route and has no public or AR/CH-callable entry point (initiated only by CC's ledger service). A permission denial mid-run stops the run, does not attempt the remaining operations, marks the ledger `failed`, restores replay-only and shows the failure in chat. |
| **Optimizer model setting & fallback** | `optimizer_model_id` (tenant `TenantSetting`) resolves explicit-and-enabled → `source="optimizer"`; unset → existing plan-authoring model → `source="authoring"`; explicit-but-unusable → `optimizer_model_not_enabled`; unset-and-authoring-unusable → `optimizer_model_not_configured` echoing the authoring reason. Reads never rewrite the setting row (a stale value stays visible). **Never** falls back to `AgentType.model_id` or a first-available config, and no resolved model is persisted. Tenant-scoped (root tenant when multi-tenancy off). CC-only module (AR/CH import boundary). |
| **Optimizer-model config API + System Config** | `GET` returns tenant-scoped options from the enabled, non-disabled catalogue plus raw `selected_model_id`, effective id/source/configured/enabled/reason; `PUT` writes only the session tenant's row, `null` clears to inherit, `422` for a not-enabled id. UI section explains workspace scope, inherit-from-authoring, catalogue-only, and no substitution; stale/unset reminders; save blocked until a stale value is re-selected. One condition must produce one consistent message across gate → availability → internal `412` → WS `chat_error`. |
| **Scope inherent (server-side)** | Every optimization handler that takes an `agent_type_id` accepts only the session's own agent type; any other agent type, plan, script list, execution log, workspace setting, permission change or deletion is declined with a structured refusal and **zero writes**. Refusals are visible in the conversation so a prompt-injected or drifting turn cannot widen scope. `__command` one-shot runs keep their existing attributed behaviour. |
| **Channel isolation from business conversations** | An optimization session is a separate channel: creating it writes no business session and changes no business state; a business conversation never becomes an optimization one (and vice versa); listings/filters/attribution distinguish `channel="optimization"`; ending or archiving the optimization conversation leaves the agent's business conversations, history and runtime behaviour untouched. |
| **Audit: replay vs live** | Every live request, the approved script + its tool-call preview, the operator's decision and the script run record are recorded and tied to tenant + conversation + agent type. Replay evidence stays `VerificationRun`/`ScriptExecutionRecord`; live evidence is the ledger row plus `RuntimeToolCall` rows carrying `optimization_live_test_request_id` — so "a real integration was contacted" is unambiguous in the conversation, the audit block and the agent type's history. Attribution is the **agent type's identity plus the authenticated operator**; never a shared/privileged identity. |
| **Plan outcome & refresh** | Conversation outcomes are persisted through the unchanged `generate_optimized_plan` allow-list (`ready` / `needs_feedback` / `failed`) — nothing bypasses verification because it was discussed in chat. `needs_feedback` carries a specific "what is missing" `error`. The Optimized Plan tab invalidates the subject's query scope on turn completion (and polls while a turn is in flight) so state appears without a reload and polling stops afterwards. |
| **Migration** | One revision, single child of `992bbc77bf6a`: new enum + live-test-approval table (table creation owns the type — no separate/parameterised DDL), plus the **one** nullable `RuntimeToolCall` pointer with FK/index. **No** conversation scope column, **no** agent-type change, **no** data seeding, and `channel="optimization"` needs no schema change because the column is already a free-form string. Reversible `downgrade()` (drop column then table). Applied head verified via `alembic current`; ORM round-trip; existing rows unaffected (`NULL` pointer). |
| **Tenant isolation & top-priority rules** | Conversation, availability, ledger, audit and model choice resolve from the **session** tenant (root tenant when multi-tenancy off) — identical-name cross-tenant probes for the agent type and `optimizer_model_id`. Only CC writes PostgreSQL; AR executes the turn/replay/live operations; CH is the only holder of identity material and injects per call; no tokens/credentials/decrypted secrets in the ledger, conversation record, checkpoint or internal payloads (identifiers only). The new `OptimizationLiveTestRequest` and both new internal `/internal/live-test/run` endpoints must be reflected in the tenant-isolation sweep and the internal endpoint allowlist coverage. |
| **No regression** | One-shot `POST /agents/sessions/optimize` and its `ready`/`needs_feedback`/`failed` outcomes unchanged; manual feedback path unchanged and still steers the next refinement alongside chat messages; `can_optimize` semantics unchanged apart from the removed conversational-type restriction; replay verification rules, plan lifecycle, retire behaviour, execution preference/fallback, `requires_fix` marking, script registry/sandbox rules and tool-permission semantics unchanged; assistant (`ConversationDialog` non-optimizer mode) byte-identical; normal agent runs never become optimization sessions. |

## Critical Scenarios

### No seeded optimizer agent, identity, or role

- WHEN Control Center starts on a fresh install THEN no optimizer `AgentType`, agent role, identity, skill binding or other row is created, and no optimizer-specific capability becomes assignable, schedulable or delegable.
- WHEN Control Center restarts THEN startup writes nothing optimizer-related (idempotent by construction), and existing tenants gain the capability with no data step.
- WHEN the agent-type and role administration surfaces are inspected THEN there is no system optimizer entry to edit, remove, assign or govern, and governing the agent type is sufficient to govern its optimization.
- WHEN an optimization conversation is created THEN no identity, role or tool grant is minted for it; the session references only the existing subject agent type.
- WHEN the one-shot optimization path is inspected THEN it still requires the agent's existing plan and permissions and gains no new identity either.

### Identity and permission parity (never beyond the agent)

- WHEN an optimization-mode turn runs THEN the resolved identity, role and tool grants are exactly the subject agent type's — identical to a business run.
- WHEN the internal agent context is inspected for an optimization turn THEN it carries the subject's identity/permission envelope and no elevated, service, shared or bridging identity or additional grant.
- WHEN the optimizer attempts an operation the subject agent could not perform THEN it is refused with a clear explanation and nothing is written.
- WHEN the operator lacks permission to optimize/execute that agent type THEN the conversation declines and starts no work; lacking permission to view the agent type is declined at the entry and at the API.
- WHEN an approved live test runs THEN it executes inside the agent type's workspace under the same permission, tenancy and safety rules as a normal run — not a broader envelope.
- WHEN attribution is inspected THEN both the decision and the execution reference the agent type's own identity plus the authenticated operator, never a privileged or shared identity.

### Optimization-mode conversation on the subject agent type (scope inherent)

- WHEN the operator opens the conversation from an agent type's Optimized Plan tab THEN one session is created with `agent_type_id` = that agent type and `channel="optimization"`, and the chat is annotated "this agent only".
- WHEN the conversation is read back THEN it exposes the subject id/name, the availability projection and the audit summary (replay verifications, live operations, last live time, replay-only flag), with ownership and tenant checks.
- WHEN the session is resumed, reconnected, or the model changes THEN the subject is unchanged, because it is a row property and not prompt text.
- WHEN any public API is called after creation THEN the session's agent type cannot be widened, repointed or rewritten.
- WHEN two optimization conversations exist on the same agent type THEN each acts only on that agent type, and neither can read the other's pending approvals or ledger rows.
- WHEN an optimization tool call names a **different** agent type, another plan, another script list or another execution log THEN the call is refused (`out_of_scope`), nothing is read or written for the other agent type, and the chat explains the refusal.
- WHEN the request asks to change workspace settings, permissions, other agents, or to delete/retire anything THEN it is declined with a clear explanation, nothing is changed, and no delete/retire tool exists to call.
- WHEN the request asks for credentials, identity tokens or database access THEN it is refused and never requested.
- WHEN an unscoped one-shot `__command` run calls the same handlers THEN behaviour is unchanged — replay semantics, history bounds and authoring allow-lists are identical.

### Conversation entry, availability, and both agent topologies

- WHEN the Optimized Plan tab is rendered for a **typed** agent type THEN the optimization conversation entry is offered, annotated as scoped to that agent type, and the existing Optimize/retire/manual-feedback actions remain.
- WHEN the Optimized Plan tab is rendered for a **conversational** agent type THEN the same conversation entry is offered with the same annotation and the same safety rules (the previous hard restriction on optimizing conversational agents no longer applies).
- WHEN the subject agent type does not exist or the operator lacks view permission THEN the API returns `404`/`403` respectively and no session row is written.
- WHEN a successful reference execution is missing THEN the conversation is still created, availability reports `no_successful_execution`, the chat explains what is missing, and no optimization work starts.
- WHEN no usable optimizer model exists THEN the conversation is still created, availability reports the model reason, the chat shows the model alert with a System Config shortcut and a disabled composer, and no work starts.
- WHEN a conversational agent type has no base plan or no usable reference evidence THEN the conversation still opens, states exactly what is missing, and authors nothing speculative.
- WHEN the conversation is created THEN `channel="optimization"`, `triggered_by_user_id` is the authenticated operator, and nothing optimization-shaped is dispatched.
- WHEN the operator starts the conversation without an explicit action (page load, listing, reconnect) THEN no turn, no work and no live request is created.
- WHEN availability changes between the gate read and the turn (model fixed, execution completes) THEN the server re-checks at request time and the client re-fetches, so UI and server never disagree about `available`.

### Turn routing (optimization mode vs business runs)

- WHEN an optimization-channel session is executed on a **typed** agent type THEN the conversational loop runs (not the typed task loop).
- WHEN an optimization-channel session is executed on a **conversational** agent type THEN the conversational loop runs with identical behaviour and identical safety rules.
- WHEN a typed agent type receives a normal business submit THEN routing and behaviour are exactly as today.
- WHEN a conversational agent type receives a normal business chat turn THEN routing and behaviour are exactly as today.
- WHEN an assistant, integration-client, `__command` or other session with any other (or absent) channel value is executed THEN no optimization routing applies and behaviour is unchanged.
- WHEN the mode is derived THEN it comes from the persisted session channel, not from prompt text, so a drifting turn cannot switch loops.

### Prompt and tool mode inside optimization mode

- WHEN an optimization-mode turn is prepared THEN its system instruction is the optimization mission, not the agent's business instruction, and the business skills are not composed.
- WHEN an optimization-mode turn is prepared THEN the optimization system tools are present (including `request_live_test`) and the agent's granted MCP tools are **not** exposed to the loop.
- WHEN a normal business run of the same agent type is prepared after an optimization conversation THEN its business instruction, skills and granted tools are exactly as before (no residual mode).
- WHEN an optimization turn tries to reach an MCP tool directly (outside an approved live test) THEN no such tool is available and the attempt is refused rather than executed live.
- WHEN an approved live test runs THEN the approved script's own `tools.call(...)` lines are the only egress, under the same identity, and the loop itself remains replay-only afterwards.
- WHEN the conversation ends THEN the mode is released; a subsequent business run shows the business instruction and skills and never an optimization mission.

### Chat turns, activity, and safe stop

- WHEN the operator sends a message in an optimization conversation THEN the turn is prepared with the scope block, the subject context and the optimizer model, and the reply is persisted to the conversation record.
- WHEN the optimizer works THEN the chat shows working state plus expandable step/tool detail ("what it looked at"), and a busy turn remains readable at a glance.
- WHEN a turn takes longer than expected or fails THEN it ends in a typed terminal outcome (`timeout_or_failed` / `guardrail_<reason>`) with what to do next — never an indefinite spinner.
- WHEN a finished turn produced a plan, a script authoring/refinement, or a verification attempt THEN the outcome is described in readable language.
- WHEN `execute_script` returns terminal `needs_user_input` THEN the conversation stops with a specific account of the missing evidence and at most one decision point, persists `needs_feedback` with `error`, starts no second identical attempt, and makes no live call.
- WHEN a session ends THEN it is in a bounded state — `ready` plan, an explicit needs-input stop the operator can act on, or an explicit failure — with no unbounded retry anywhere on the path.

### In-chat ask/decide (lightweight, not the dashboard)

- WHEN the optimizer needs a decision THEN a question/choice/free-text card is rendered inline, the session enters `waiting_for_human`, and the activity reflects the waiting state.
- WHEN a decision is pending THEN sending another message is refused server-side with a "waiting for your decision" response, the composer is disabled, and no second turn or background work is created.
- WHEN the operator reconnects or reopens the Optimized Plan tab THEN the pending request is re-surfaced from persisted state (including the script, its preview and the scope) and can still be answered.
- WHEN the operator selects an option or types free text THEN the request is resolved once, the answer is recorded as part of the conversation (visible in history and session review), and exactly one resume is dispatched with the same subject, mode and model.
- WHEN the operator never answers THEN the session stays waiting; the optimizer does not assume, retry, or proceed in the background.
- WHEN the interventions surfaces are inspected THEN there is no optimization queue, no cross-session list and no dashboard route; the decision lives only in the conversation.
- WHEN the session is ended while a request is pending THEN the request is closed and no work resumes.

### Live-test request validation and the script preview

- WHEN the optimizer asks for a live test THEN it names the SAVED script version it wants to run, and the chat shows a reviewable card naming that script, its server-derived tool-call preview ("it will call: …"), why, and that the whole script runs once as this agent.
- WHEN the request is presented THEN the preview is derived server-side from the version's own `python_source` (ordered, de-duplicated, bounded) — the caller never supplies an operation list — and it is informational, never the unit of execution.
- WHEN the script version is missing/unknown/from another tenant, has no `python_source`, belongs to another agent type, has no literal `tools.call` line, or previews a tool outside the subject agent type's granted set THEN the request is refused with the matching reason code (`invalid_script_version` / `script_version_not_found` / `out_of_scope` / `no_tool_calls` / `operation_not_permitted`) and **no ledger row and no intervention** are created.
- WHEN an operation's arguments contain a sensitive-material key (token / password / secret / credential / api_key) THEN the request is refused with `sensitive_material` and nothing is persisted.
- WHEN a live test is already pending for the conversation THEN a second request is refused with `live_test_already_pending`; when the per-session approved-live cap is reached THEN it is refused with `live_test_quota_exhausted`.
- WHEN the request targets another agent type or a non-optimization resource THEN it is refused with `out_of_scope`.
- WHEN a request would fan out into an unbounded or session-long live mode THEN it is refused with a clear explanation rather than converted into a narrower test.
- WHEN a valid request is accepted THEN one `pending` ledger row is created together with the approval intervention in the same transaction, `expires_at` is set, and the turn pauses.
- WHEN the request is presented THEN the ledger row's `script_version_id` and tool-call preview are the authoritative record and are immutable afterwards; a changed script is a new version and a new request.

### Live-test approval: approve (single use)

- WHEN the operator approves THEN the approval is consumed exactly once, the approved script executes once end to end, and its run record returns to the conversation.
- WHEN the operations execute THEN they run under the subject agent type's identity and the session tenant's scope, through the existing CH tool route (identity injected per call by CH), and nothing outside the listed set is added or substituted.
- WHEN the run completes THEN `executed_operations` records one script run record (result summary, per-`tools.call` outcomes, telemetry, duration), the ledger reaches `executed`, and the resume carries the record so the refinement continues **without any further live call**.
- WHEN a live test has been used THEN the conversation's "What ran in this session" bar shows the live-used state (N approved live operations) and a later need produces a **new** script request with a **new** approval.
- WHEN the operator approves but the model/plan work then continues THEN further verification is replay-only again.

### Live-test approval: deny, expiry, and non-approval

- WHEN the operator denies THEN nothing runs, the ledger records `denied` (retained for audit), the session returns/stays replay-only, and the optimizer continues or stops with a specific "what is missing" explanation without retrying the same request.
- WHEN the operator never answers and `expires_at` passes THEN the expiry sweep closes the request as `expired`, cancels the linked intervention, resolves the resume as unresumable/expired, and appends the bounded-stop turn — nothing runs and no retry is scheduled.
- WHEN a decision arrives after expiry THEN the lazy expiry check fires first: no execution, nothing runs, and the stored terminal outcome is surfaced.
- WHEN the session is ended or cancelled while a request is pending THEN the request is cancelled and nothing runs.
- WHEN the decision is recorded THEN its attribution is the authenticated operator (value, operator, responded time) and the request is never resurrected.

### Single-use / idempotency guarantees

- WHEN the same approval is re-delivered or replayed THEN the conditional transition finds no row to transition and the stored outcome is returned — no second execution, no duplicate tool calls.
- WHEN the respond endpoint is called a second time for the same intervention THEN it returns the terminal outcome with the existing `409`-style semantics and never re-executes.
- WHEN an approval is consumed THEN a previously used approval cannot be re-applied to a later need (no inheritance, no "always allow", no remembered consent).
- WHEN two decisions race (double-click, concurrent operator tabs) THEN exactly one execution occurs and the loser writes no evidence.

### Permission denial during a live run

- WHEN a tool call in the approved list is denied by permissions THEN the run stops, the remaining operations are **not** attempted, the ledger becomes `failed`, the failure is shown in the conversation, and the session returns to replay-only.
- WHEN the runtime permission check happens before execution THEN an operation not in the subject's allowed set is refused before any tool call is made, and the refusal writes no execution evidence beyond the recorded failure.
- WHEN a permission-denied decline occurs THEN it starts no work, is never retried automatically, and does not widen the identity to make the call succeed.

### Replay-only default routing

- WHEN the optimizer verifies a script without an approved live test THEN verification uses the recorded reference transcript only, and no live tool client is reachable from that code path.
- WHEN the reference transcript is missing or does not cover the needed tool/response THEN the result is a terminal `needs_user_input` stop — not a live fallback, not a live request invented silently.
- WHEN a live test was approved earlier in the session THEN a later verification attempt still defaults to replay; the earlier approval does not make live the default.
- WHEN CC, CH or AR receives a live-test run request THEN it can only be triggered by CC's ledger service (no public or directly callable entry point), and AR/CH can only receive an already-authorized script (source + subject, never an operation list).

### Optimizer model resolution (setting & fallback)

- WHEN the workspace has `optimizer_model_id` set to a model enabled in that workspace's catalogue THEN the optimization turn runs on **that** model (`source="optimizer"`), and the subject agent type's runtime model is not used.
- WHEN `optimizer_model_id` is unset THEN the resolver uses the workspace's existing plan-authoring model (`source="authoring"`), with no second setting to keep in sync, and no value is written back to the setting store.
- WHEN `optimizer_model_id` points at a model no longer enabled/available in the workspace catalogue THEN the state is `optimizer_model_not_enabled`: the stale value stays visible, nothing is generated, the chat blocks with guidance, and **no** fallback model is substituted.
- WHEN nothing is configured and the authoring model is also unusable THEN the state is `optimizer_model_not_configured` echoing the authoring reason, and the conversation starts no work.
- WHEN the subject agent type's own runtime model is the only configured model THEN it is never used for optimization (no agent-model substitution), and the model-unavailable state is reported instead.
- WHEN the resolver is called for a read THEN the stored `TenantSetting` row is not rewritten (derived at read time only), and with multi-tenancy enabled only the session tenant's setting and catalogue are consulted.
- WHEN the internal agent-context endpoint resolves an optimization-mode conversation whose model is unusable THEN it fails closed with `412 optimizer_model_unavailable` carrying the reason code — never a silent run on another model.
- WHEN the internal agent-context response is inspected THEN it carries model **identifiers** only (no credentials, API keys or identity tokens).
- WHEN the model changes mid-life THEN subsequent optimization in that workspace uses the new model immediately; a change in workspace A never affects workspace B.

### Optimizer-model config API & System Config

- WHEN the administrator opens System Config THEN the optimizer section states it powers the optimizer conversation and its plan work (not a runtime model, not the agent's model), that unset inherits the plan-authoring model, that the choice is workspace-scoped, and that replay-only / single-use approval / script lifecycle are unaffected.
- WHEN options are loaded THEN only the session tenant's enabled, non-disabled models appear, with an explicit "inherit the plan authoring model" option.
- WHEN a model id that is not enabled in this workspace is submitted THEN the save is rejected with `422` and the previous selection is unchanged (surfaced through the dialog error standard).
- WHEN `null` is submitted THEN the setting row is cleared and the effective model falls back to the authoring model.
- WHEN a stale saved value exists THEN it renders as a disabled "no longer available" option, a re-select reminder is shown, and Save is blocked until re-selected — the stale value is never auto-cleared.
- WHEN no usable model exists THEN a reminder with a pointer to the section appears, and it clears once a valid model is saved.
- WHEN the gate, availability projection, internal `412` and WS `chat_error` describe the same condition THEN they use the same reason vocabulary and produce one consistent message.

### Audit: replay vs live distinguishable

- WHEN the conversation is reviewed THEN counts of replay verifications and approved live operations are shown distinctly, with the single-use note.
- WHEN a live operation ran THEN its `RuntimeToolCall` row carries the ledger pointer, so it is distinguishable from replay calls and from ordinary conversation turns in the raw tool log and in the agent type's history.
- WHEN an ordinary run, a replay verification, or a normal conversation turn writes tool calls THEN the ledger pointer is `NULL`.
- WHEN the ledger is listed for a session THEN every request appears with status, requested operations, executed operations, timings, expiry and the decision (value, operator, responded time) — including denied and expired ones.
- WHEN attribution is inspected THEN the decision is attributed to the authenticated operator and the execution to the operator + the subject agent type, never to a shared, privileged or elevated identity.
- WHEN the conversation record is reviewed THEN questions, answers, previews and approvals are retained.

### Channel isolation from business conversations

- WHEN an optimization conversation is created for an agent type THEN no business `ConversationSession` is created, modified or closed, and the agent's business history is untouched.
- WHEN the sessions are listed or filtered THEN optimization sessions are distinguishable by `channel="optimization"` and never appear as business conversations of that agent.
- WHEN a business conversation is underway THEN it never turns into an optimization session, and an optimization session never absorbs its turns or context.
- WHEN a business chat turn is sent on the same agent type while an optimization conversation exists THEN it uses the business instruction/skills and its own session; the optimization session is unaffected.
- WHEN the optimization conversation is ended or archived THEN the agent's business conversations and normal runs continue unchanged.
- WHEN a business session is executed THEN it never uses the optimizer model or the optimization tool set, and never writes a live-test ledger row.

### Plan outcome and auto-refresh

- WHEN the conversation authors a verified plan THEN the optimized plan persists as `ready` through the unchanged tool path and is served to later executions by the unchanged predicate.
- WHEN verification compares script syntax and tool invocation against the reference THEN output equality is still not required — differing or legitimately empty results do not produce re-attempts.
- WHEN the conversation cannot resolve the gap THEN the plan persists `needs_feedback` with the specific `error`, rendered on the plan and in the conversation.
- WHEN a turn completes (reply, pause, denial, live-test result) THEN the Optimized Plan tab refreshes automatically — plan state appears without a manual reload — and in-flight polling stops afterwards.
- WHEN manual feedback is added on the plan and chat messages were also exchanged THEN both are carried into the next refinement.
- WHEN the plan is retired THEN the existing retire behaviour and its "nothing to retire" state are unchanged.

### Migration

- WHEN the revision is applied THEN `alembic current` shows the new head, and the revision is the single child of `992bbc77bf6a`.
- WHEN the schema is inspected THEN the live-test approval table, its enum, and the one nullable `runtime_tool_calls.optimization_live_test_request_id` with its FK/index exist; no existing column changed type or nullability; **no** conversation scope column and no agent-type column/seed exists.
- WHEN the conversation channel value is written THEN it requires no schema change (`channel` is already a free-form string) and existing channel values are unaffected.
- WHEN an upgrade is followed by `downgrade -1` and `upgrade head` THEN both succeed (column dropped before the table; the enum is owned by the table creation, no parameterised DDL).
- WHEN existing rows are read after the migration THEN `runtime_tool_calls.optimization_live_test_request_id` is `NULL` and every pre-existing behaviour is unaffected.
- WHEN the new entity round-trips through the ORM THEN all documented fields, the status enum and the relationships persist and reload correctly.
- WHEN the backend starts after migrating THEN no optimizer agent type, role, identity or setting row is created (the change is behaviour, not data).

### Tenant isolation and top-priority rules

- WHEN multi-tenancy is enabled THEN tenant A's optimization conversations, ledger rows, audit and `optimizer_model_id` are invisible to tenant B, using identical names/settings in both tenants to prove qualified resolution.
- WHEN multi-tenancy is disabled THEN everything resolves to the root tenant and behaves as before, with no orphaned or duplicated setting.
- WHEN internal live-test traffic flows CC → CH → AR THEN it uses `internal_httpx_client` with signed tenant headers, CH/AR never sign, and a missing/invalid header fails closed before handler execution.
- WHEN internal payloads are inspected THEN they carry identifiers plus the approved script source and reference input only — no identity tokens, credentials or decrypted secrets; the persisted preview is state context only.
- WHEN database writes are traced THEN only Control Center writes (conversation, ledger, plan, audit); AR executes; CH injects identity.
- WHEN the tenant-isolation sweep runs THEN the new entity is classified as tenant-scoped and probed, and the new internal endpoints appear in the internal endpoint allowlist coverage.

### No-regression

- WHEN the operator runs the one-shot Optimize action THEN it behaves exactly as before (gate, `202`, command execution, `ready` / `needs_feedback` / `failed`), and `can_optimize` is not affected by the optimizer-model setting.
- WHEN a plan becomes `requires_fix` after a fallback THEN the marking, alert, auto-recorded feedback and re-optimize path are unchanged.
- WHEN replay verification runs for a `__command` optimize run THEN selection of the reference execution, bounds and the terminal stop are unchanged.
- WHEN the Control Center Assistant conversation is used THEN its surface, preview and approval rules are unchanged.
- WHEN a normal agent execution runs THEN it never becomes an optimization session, never uses the optimizer model and never composes the optimization mission.
- WHEN the frontend renders the Optimized Plan tab THEN the existing Optimize, retire and manual-feedback actions remain available beside the new conversation entry.
- WHEN i18n keys are resolved THEN every new string renders from `en.json` without untranslated fallbacks.
- WHEN the full suites run THEN no pre-existing optimization/conversation/plan/tenancy suite regresses.

## Edge Cases & Risks

- **Typed agent optimization conversation**: the typed agent has a base plan and reference executions, so the conversation is fully usable, but the typed submit path must remain untouched. Expect: the optimization session uses the conversational loop, typed `POST` submissions keep the task loop and their output schema, the plan authored in chat is served to later executions by the unchanged predicate, and no typed-input validation changes.
- **Conversational agent without a plan**: a conversational agent type is optimizable but may have no base plan and no reference transcript. Expect: the conversation opens, availability states exactly which precondition is missing (`no_successful_execution` and/or no plan), no plan is fabricated and no live request is invented; after a successful business conversation provides evidence, availability clears without a code change.
- **Approval expires mid-run**: `expires_at` passes while the approved operations are executing. Expect: an in-flight execution is not torn down by the sweep (the row is no longer `pending`), the run completes and records its evidence, and no *additional* run can start — assert the sweep only closes `pending` rows and that the lazy check cannot cancel an already-transitioned row.
- **Double-approve / concurrent decisions**: two approvals (or a double-click, or a re-delivered WS answer) arrive for the same request. Expect: exactly one execution; the second returns the stored terminal outcome, writes no extra tool calls and no second resume.
- **Approval for an operation not in the list**: an operation is added/substituted at execution time (tampered request, or a runner bug). Expect: AR verifies every operation against the approved list and the subject's allowed set; anything unlisted is rejected before the call, the remainder is not attempted, and the ledger ends `failed`. Nothing outside `requested_operations` may ever produce a `RuntimeToolCall` with the ledger pointer.
- **Malformed/oversized arguments**: non-serialisable arguments or arguments above the per-operation cap are refused at request creation (and again at execution) with no write — never truncated silently.
- **Model removed mid-conversation**: the optimizer model is disabled/removed between turns (or between approval and resume). Expect: the next turn fails closed with `optimizer_model_not_enabled` guidance and no work starts; a pending decision still resolves without execution; the session's agent type, channel and business behaviour are unchanged.
- **Reconnect with a pending question**: the socket drops while a question or approval is pending. Expect: the pending request re-surfaces on reconnect (with the script, expiry and the rendered tool-call preview), the composer stays blocked, and answering resumes exactly once. If the approval expired while disconnected, the client shows expired/replay-only rather than a live card.
- **Normal business conversation unaffected**: a business chat or typed run on the same agent type is issued while an optimization conversation exists (including one with a pending approval). Expect: the business run composes the business instruction/skills and the agent's granted tools, uses its own session and model, never reads the ledger, and is not blocked by the optimization pause.
- **Mode leakage after the conversation**: after an optimization session ends, a business run is executed. Expect: business instruction, skills, grants and routing are exactly as before; no optimization tool, mission text or live-test path is present anywhere in the business context.
- **Permission denial**: the operator lacks view/optimize permission (entry/creation) or a tool grant (live operation). Expect: distinct behaviours — `403` at creation, a clear decline with no work at start, and `live_test_permission_denied` (ledger `failed`, remaining operations skipped, replay-only restored) at execution. Nothing is retried and no audit attribution leaks to another identity.
- **Concurrent live test and one-shot Optimize**: an approved live test runs while an operator triggers the one-shot Optimize (or a normal execution consumes a `ready` plan). Expect: no plan corruption (one active non-retired plan; unchanged upsert/retire semantics), the live test's evidence stays attached to its own conversation/agent type, and neither path silently inherits the other's state.
- **Two optimization conversations on the same agent type**: both act on the same agent type, both can author; expect no cross-session leakage of pending approvals or ledger rows, and the plan reflects the last writer atomically. Each session's `request_live_test` quota and one-pending rule are per session.
- **Cross-session reach**: a caller tries to read another session's ledger, audit or pending decision. Expect: ownership + tenant checks refuse it, and an optimization session cannot be used to read another session's conversation record.
- **Prompt-injected scope drift**: a message asks the optimizer to read another agent's scripts, change a setting, or reveal a token. Expect: structured refusal in the conversation and zero writes/reads for the other resource, with no change to the session's agent type.
- **Availability/staleness races**: the model is fixed or an execution completes between the gate read and the turn. Expect: the server re-checks at request time, the client re-fetches, and the UI/server never disagree about `available`.
- **Bounded stops vs loops**: a repeating replay miss must not produce repeated identical attempts, repeated live requests, or repeated resumes. Expect: at most one decision point per gap and `MAX_SCRIPT_ATTEMPTS`/guardrails intact.
- **Ledger housekeeping**: an expired-then-answered, denied-then-reapproved, or cancelled-by-end request must not resurrect; `executed_operations` stays empty for denied/expired/cancelled; only `executed`/`failed` carry timings.
- **Migration/enum safety**: creating the table owns the enum (no `sa.Enum` re-creation on restart); `downgrade()` must drop the column before the table and must not attempt to drop a shared enum value; an unapplied migration surfaces as a 500 on conversation/ledger endpoints — the real-backend E2E variant must fail loudly on that, not skip.
- **Long-running turn under mock delay/hang**: heartbeat + per-call timeout + whole-turn watchdog + iteration budget still bound the turn; the new optimization path must not add an unbounded wait around the approval pause (the pause is a terminal chunk, not a spinner).
- **Top-priority rule drift**: a shortcut that lets AR read the ledger, CH forward a token, or CC execute a script must be caught — assert CC-only DB writes, AR-only execution, and identifier-only payloads.

## Acceptance Criteria Checklist

Mapping to PRD acceptance criteria (`prd.md` → Acceptance Criteria):

**Entry, Scope & Availability**

- [ ] The Optimized Plan tab of an agent offers a way to start an optimization conversation for that agent; it is clearly tied to that one agent and unavailable when no agent is selected → Conversation entry scenarios; tab entry + create-guard tests
- [ ] Optimization is a mode of the agent, running on the agent type itself with its existing identity, role and permissions; there is no separate optimizer identity or role to create, administer, edit or remove → No-seeded + identity-parity scenarios; startup/identity tests
- [ ] Optimization mode is available for both typed and conversational agent types with the same behaviour and safety rules → Entry + routing scenarios; typed/conversational conversation tests
- [ ] Entering optimization mode does not change normal business behaviour; instructions, skills and tool permissions are unchanged outside the conversation → Prompt/tool-mode + channel-isolation scenarios; context-composition tests
- [ ] Scope is exactly the selected agent's optimized plan, generated scripts, execution history and base plan; other agents, plans, settings, permissions or resources are declined with a clear explanation and nothing is changed → Scope-inherent scenarios; per-handler refusal tests
- [ ] Optimization never deletes anything; retire/remove requests are declined as not supported → Scope refusal scenarios; guard tests
- [ ] Optimization never reveals or requests sensitive material → Scope/ledger validation scenarios; sensitive-key deny-list + payload tests
- [ ] Starting the conversation is available whenever optimization would be available; a missing precondition is explained and starts no work → Availability scenarios; create/availability tests
- [ ] Conversation history is retained and resumable, and a new optimization conversation can be started without losing the previous one → Chat turn + resume scenarios; conversation read tests

**Identity & Permission Parity**

- [ ] The optimizer acts with exactly the agent's permissions and never broader; anything the agent could not do is refused, and no elevated/shared/system access is used → Identity-parity scenarios; context/identity tests
- [ ] Optimizing requires permission to optimize and execute the agent; an operator who may not optimize cannot start, and the refusal is explained → Permission scenarios; `403` + entry-state tests
- [ ] Tool permissions are not widened for optimization; the agent's granted tools are used only for an approved live test, all other optimization activity is replay-only → Prompt/tool-mode + replay-only scenarios; toolset composition tests
- [ ] An approved live test runs as the agent's own operation within the agent's workspace, under the same permission/tenancy/safety rules as a normal run → Approve scenarios; runner identity tests

**Visibility of What the Optimizer Is Doing**

- [ ] While working, the conversation shows ongoing activity — that it is working, which steps it takes, which information it looked at → Chat/activity scenarios; single chat-status-indicator assertions (the folded activity block was removed — exactly one processing indicator per turn)
- [ ] Work taking longer than expected ends in a clear outcome rather than an indefinite wait; a hang/failure is explicit with next steps → Bounded-stop/timeout scenarios; turn-resolution + WS error tests
- [ ] Finished turns show what was produced (plan authored, script authored/refined, verification attempted) and its outcome in readable language → Chat turn scenarios; append-turn + frontend tests
- [ ] Only one spinner animates per turn and none survives a terminal turn; a decided live-test card collapses rather than lingering expanded → Chat/activity scenarios; chat-status-indicator count tests + `OptimizerChatDialog.test.tsx` (approval card collapse)

**Ask and Decide, In-Chat**

- [ ] The optimizer can ask a question or present a decision inside the conversation → Ask/decide scenarios; ask card + intervention tests
- [ ] The conversation indicates it is waiting, blocks further messages until answered, and re-surfaces the pending request on reconnect/reopen → Waiting-state scenarios; server-side block + pending-intervention tests
- [ ] Choosing an answer or typing free text resolves the request; the response is recorded in the conversation and visible in history/session review → Ask/decide resolution scenarios; turn persistence tests
- [ ] An unanswered question causes no assumption and no background retry → Waiting-state scenarios; no-retry assertions
- [ ] No dashboard or intervention queue is introduced; the decision lives inline in the conversation → Ask/decide + route-surface checks

**Live-Test Approval (Replay-Only by Default)**

- [ ] Replay-only is the default and stays in force unless a live test is explicitly approved; nothing runs live without it → Replay-only routing scenarios; replay + runner tests
- [ ] A live-test request lists the exact operations (tool/action + arguments) in a reviewable form → Exact-operation-list scenarios; ledger validation + approval card tests
- [ ] The operator can approve or deny; denial leaves the session replay-only and the optimizer continues or stops without retrying on its own → Deny scenarios; ledger + turn-resolution tests
- [ ] An unanswered request expires after a bounded period; the session stays replay-only, the request is closed, and it is not retried → Expiry scenarios; sweep + lazy-expiry tests
- [ ] On approval the approved script runs once, end to end, as the agent's own operations in the agent's workspace, with no additional or substitute call → Approve + unlisted-tool edge case; runner + forwarding tests
- [ ] No automatic repeat: a second live test needs a new request and a new approval, and a used approval cannot be re-applied → Single-use/idempotency scenarios; conditional-transition + resume-marker tests
- [ ] Approval does not persist beyond the single test → Single-use + later-need scenarios; ledger tests
- [ ] If the approved script cannot run as approved (e.g. permission denied mid-run), the failure is shown, the script stops, nothing further runs live, and the session returns to replay-only → Permission-denial scenarios; runner + ledger `failed` tests
- [ ] Results of the approved live test return to the conversation, are visible to the operator and usable by the refinement without further live calls → Approve scenarios; resume-carried results tests
- [ ] Requests for unbounded/session-long live modes or beyond the agent's existing capability are refused with a clear explanation → Validation refusal scenarios; registry + ledger tests

**Safe Stop Instead of Loop**

- [ ] When replay cannot prove a script — or the operator explicitly asks for a live verification — the optimizer asks or stops with a specific readable explanation and never retries in a loop; an explicit request is a valid live-test reason → Safe-stop scenarios; `execute_script` terminal-stop tests; live-test approval tests
- [ ] A reference transcript recorded with provider-sanitized tool names (`mcp_demo__searchFlights`) still replays a canonical script call (`mcp-demo____searchFlights`); a genuine miss still stops → `test_replay_tool_client_names.py`; tool-call logging tests
- [ ] When the agent has no base implementation plan, optimization generates one first (authoring model) and proceeds; if generation fails, the operator is told and no plan is fabricated → `test_optimized_plan.py` auto-generation tests
- [ ] An optimization run — successful or `needs_feedback` — shows its final summary in the Result tab, formatted, even when the typed output has no field values; a plain failure detail remains readable → `OutputTypeResultTab.test.tsx` final-result cases; `test_agent_runtime_executor.py` raw-output test
- [ ] The agent dialog refreshes its plan/sessions after optimization completes, and the header reload button re-reads the dialog without reopening → `AgentOptimizedPlanTab.test.tsx`; `AgentTypeDetailsDialog.test.tsx` reload-button case
- [ ] The optimization tab shows only the model, chat and a help icon; the help dialog explains the interaction; the manual feedback form and the pre-start confirmation dialog are absent → `AgentOptimizedPlanTab.optimizerEntry.test.tsx`; `AgentTypeDetailsDialog.test.tsx` direct-trigger case
- [ ] Flat steps with `parent_order` render as a tree (children nested, missing/self parents stay visible) and a script step's action is a button, not an overlapping link → `PlanStepTree.test.tsx`; `AgentOptimizedPlanTab.test.tsx` View-script case; `test_plan_generation_service.py` parent-order parsing
- [ ] The implementation plan is on its own tab, the topology tab is named Agent Topology, and generating shows a spinner until the new plan is ready → `AgentTypeDetailsDialog.test.tsx` tab order and plan-tab cases
- [ ] Steps use an action icon (not a number), with a lighter icon for sub-steps → `PlanStepTree.test.tsx` icon case
- [ ] A step keeps `sop_invocation`/`skill_invocation`/`tool_call` only when it invokes an existing SOP/skill/tool; validation/selection/formatting steps become `processing` → `test_plan_generation_service.py` `_enforce_step_types` cases; `PlanPreviewModal.test.tsx` type chips
- [ ] A session always reaches a bounded end state (ready plan, explicit needs-input stop actionable in-session, or explicit failure) with no unbounded retry → Bounded-end scenarios; plan outcome tests

**Optimized Plan Outcome & Refresh**

- [ ] Improvements agreed in the conversation are reflected on the plan and its state is visible after the conversation ends → Plan outcome scenarios; `generate_optimized_plan` + read tests
- [ ] The Optimized Plan tab refreshes automatically after a turn/authoring step without a manual reload → Auto-refresh scenarios; frontend invalidation + e2e tests
- [ ] A conversation-produced plan follows the same lifecycle and verification rules; nothing bypasses verification → Plan outcome + no-regression scenarios; tool allow-list tests
- [ ] Manual feedback remains available alongside the conversation, and feedback from both paths is used on the next refinement → Feedback no-regression scenario; plan feedback tests
- [ ] A failure reason stays visible on the plan and in the conversation → `needs_feedback` scenarios; payload + rendering tests

**Configurable Optimizer Model (Workspace-Scoped)**

- [ ] Optimization runs on a model chosen per workspace from that workspace's approved, enabled catalogue, kept separate from the agent's runtime model → Optimizer-model config scenarios; model-config API tests
- [ ] Unset falls back automatically to the plan-authoring model, explicitly and with no second setting to keep in sync → Fallback scenarios; resolver tests
- [ ] Changing the model affects subsequent optimization in that workspace only, never other workspaces or the agent's runtime → Tenant-scope scenarios; cross-tenant probes
- [ ] System Config exposes the choice, explains workspace scope and the fallback → System Config scenarios; frontend section test
- [ ] When no usable model exists the conversation explains it, points to System Config, and does not start optimization with an unapproved model → Model-unavailable scenarios; availability + `412` + chat alert tests
- [ ] Optimization never runs on the agent's runtime model unless that model was explicitly chosen for optimization → No-agent-model-substitution scenarios; resolver + context tests

**Audit & Visibility of What Ran**

- [ ] Every live-test request, the approved script + preview, the decision and the script run record are recorded and associated with workspace, agent type and conversation → Audit scenarios; ledger + list endpoint tests
- [ ] Live executions are distinguishable from replay/verification work in what the operator sees and in the agent type's history → Audit-distinguishability scenarios; tool-call pointer + audit block tests
- [ ] Each entry attributes the action to the agent's own identity together with the approving operator, never a privileged/shared identity → Audit attribution scenarios; ledger/intervene response tests
- [ ] The conversation record (questions, answers, previews, approvals) is retained for audit and session review → Chat/ask scenarios; persistence tests
- [ ] An operator can review from the conversation what the optimizer looked at and what it ran, with decided live tests kept INLINE at their decision position (never a trailing section) → Activity + audit scenarios; frontend audit tests + live-test timeline-order E2E

**Conversational Experience Reuse & No Regression**

- [ ] The optimization conversation reuses the existing conversational experience (multi-turn, working/waiting/progress, inline input requests, session controls, persisted history) → Chat turn scenarios; dialog reuse tests
- [ ] Optimization mode is a distinct conversation channel: it never mixes with the agent's business conversations, and a business conversation never becomes an optimization one → Channel-isolation scenarios; channel/filter tests
- [ ] Non-conversational optimization keeps working: outcomes, plan states, retire behaviour, execution preference and fallback unchanged → No-regression scenarios; existing optimize/plan suites
- [ ] Execution of an agent is never affected; a normal run never becomes an optimization session and runtime behaviour is never altered → No-regression + routing scenarios; run/context tests
- [ ] No optimization work starts from the conversation without the operator's explicit action → Creation-starts-no-work + entry scenarios; create API + frontend tests
- [ ] Missing permission to optimize or view the agent declines with a clear message and starts no work → Permission scenarios; `403` tests + UI disabled state
- [ ] All optimizer-facing text is localised, and errors use the standard error presentation → i18n + dialog-error-standard checks; frontend tests

## Test File References

Per `easyspec-config.yaml` `source.tests`; naming follows the avatar model (no seeded optimizer type, no scope column, `channel="optimization"`).

Backend (`backend/tests/`, run with `cd backend && python -m pytest <file> -q`):

*Mode, routing, no-seed, subject guard (8.1)*

- `backend/tests/test_optimization_mode_context.py` — mission replaces the business instruction/SOP/skills; optimization + `request_live_test` tools present and the subject's business MCP/decision tools absent; optimizer-model identifiers (never the agent's runtime model) and the fail-closed `412 optimizer_model_unavailable`; no typed output contract; identity/role/grant parity; unscoped, `__command`, foreign-conversation-id and post-conversation business contexts unchanged.
- `backend/tests/test_optimization_mode_routing.py` — typed **and** conversational subjects both run the optimization turn through the conversational prepare/loop shape; a typed agent still cannot hold a business conversation; business channel prepare has no optimization block; the mode derives from the persisted channel only (prompt text never switches it); no optimizer agent type/role/identity/binding is seeded (two idempotent seeder runs, only the assistant is `is_system`) and creating the conversation mints no grants.
- `backend/tests/test_optimization_subject_guard.py` — `require_subject_match` allows the subject and refuses every other agent type with the structured `out_of_scope`; every `agent_type_id`-taking handler is exercised (`get_implementation_plan`, `get_optimized_implementation_plan`, `generate_optimized_plan`, `generate_script`, `execute_script`, `list_scripts`, `get_scripts`, `get_script`, `get_execution_log`, `request_live_test`) with zero writes/no leaked data for the other agent type; no-conversation-id / business-conversation / unknown-id paths keep legacy behaviour; live tests outside an optimization conversation are refused.

*Conversation API, model resolver, model-config API, gate (8.2)*

- `backend/tests/test_optimization_conversation_api.py` — create on typed and conversational subjects (`channel="optimization"`, operator attribution, availability computed and never stored, creation starts no work), `404`/`403` guards, no scope/second-agent-type field, permission/execution/model availability reasons, read endpoint (subject + availability + audit) with ownership/`422` for a business conversation, subject immutability through the public API, ledger read (empty, denied/expired rows with decision attribution, ownership).
- `backend/tests/unit/services/test_optimizer_model_settings.py` — explicit / unset→authoring / stale / disabled derivation with distinct reason codes, no agent-runtime-model or first-available fallback, reads never rewrite the setting row, clear restores inherit, tenant scoping (root when multi-tenancy off, qualified cross-tenant probe), never-raising state vs raising `require_`, CC-only import boundary.
- `backend/tests/test_optimizer_model_config_api.py` — `GET/PUT /agents/model-configs/optimizer-model`: workspace catalogue options (disabled excluded), raw vs effective selection, `422` for a not-enabled/disabled model with the previous selection kept, `null` clears to inherit with no second value, stale value still visible, cross-tenant isolation with the scoped session path.
- `backend/tests/test_optimization_gate.py` (updated) — extended payload (conversation availability + optimizer-model fields), conversational subjects reported as optimizable for the **conversation** while the one-shot `can_optimize` precedence/semantics are unchanged, optimizer-model state does not affect `can_optimize`.
- `backend/tests/api/test_model_configs_api.py`, `backend/tests/services/test_intervene_service.py` (updated) — realistic `is_disabled` mock for the authoring options list; the additive live-test projection query is allowed by the `get_request` assertion.

*Ledger, runner orchestration, answer path, migration (8.3)*

- `backend/tests/unit/conversations/test_optimization_live_test_ledger.py` — script validation matrix (server-derived subject, unknown/business/subject-less conversation, missing/malformed/unknown/foreign-tenant/foreign-agent `script_version_id`, version without `python_source`, no literal `tools.call`, preview-within-grants refusal, one-pending, per-session approved cap with denied rows not consuming it), tool-call **preview derivation** (ordered, de-duplicated, `+N more` bound, never caller-supplied, immutable), the approval-card text, state machine transitions only, script-run record persistence/resume payload, single-shot `begin_execution`, denial retained with empty evidence, expiry sweep (pending-only, linked intervention closed, in-flight untouched), lazy `is_overdue`, cancellation, replay matching by script version, `session_audit` replay-vs-live projection.
- `backend/tests/test_optimization_live_test_runner.py` — forwards the approved version's `python_source` + the reference input once (no operation list crosses the boundary) with the server-derived subject, the script run record persisted and carried in the resume, run failure/transport failure terminal and never retried, a retired/repointed script never runs, second execution returns the stored outcome, denied/expired/missing never forward, tenant context threaded, CC-only origination.
- `backend/tests/unit/conversations/test_turn_resolution_live_test.py` — `prepare_live_test_decision` (ordinary intervention untouched, approve owns the one attempt, deny carries the stored outcome, overdue closes as expired and settles the pause, terminal rows return their outcome, late answer to an expired row refused) plus the endpoint ordering claim → execute → resume and duplicate-answer no-re-execution.
- `backend/tests/test_optimization_live_test_migration.py` — ORM round-trip of the full entity (including the nullable `script_version_id` → `script_versions.id` `SET NULL` pointer), the single nullable tool-call pointer (`NULL` for pre-existing rows), `channel="optimization"` writable without a schema change and no scope column, `3d7c2a5940bc` the single child of `992bbc77bf6a` and `7b1e4c2d9f03` its single child, additive/reversible DDL (table owns the enum, columns dropped before the table, no parameterised DDL, no backfill, no agent-type/data change).
- `backend/tests/test_internal_request_live_test_tool.py` — the CC `request-live-test` handler on the script contract: one transaction writes the `pending` ledger row (server-derived subject, `script_version_id`, derived preview) + the linked approval intervention whose card is "Run this script live"; the caller-supplied `operations` is ignored; a replay of the same version returns the stored proposal (no second row/approval); a second different proposal is refused `live_test_already_pending`; a script with no literal `tools.call` is refused `no_tool_calls` with nothing written.
- `backend/tests/test_tenant_isolation_sweep.py` (updated) — `OptimizationLiveTestRequest` row construction + tenant-scoped probe.

*AR runner, CH forwarding, WS payloads (8.4)*

- `backend/tests/agent_runtime/test_live_test_execute.py` — capability check of the script's statically extracted `tools.call` names against the subject's own (unscoped) grants with zero work on refusal, one end-to-end sandbox execution of the approved source (no per-operation execution), the reference input reaching the script as `context`, conversation + subject agent type + `live_test` provenance per call, one `script_run` record with per-`tools.call` outcomes/telemetry/result summary, mid-script stop-on-first-error, sandbox/run-bound mapping, ledger pointer on every recorded call, recording failures never break the run, no DB access, route registration/cert expectations.
- `backend/tests/communication_hub/test_live_test_forwarding.py` — verbatim CC→CH→AR body through `internal_httpx_client` (`script_version_id`/`script_name`/`script_version_label`/`python_source`/`input_context`, byte-identical source, no operation list), CH service certificate (mTLS or header), CC-signed tenant headers forwarded unchanged and never signed by CH, no identity material, `503` without a certificate, `4xx`→structured failure / `5xx`/transport→`502`, control-plane certificate classification and route registration.
- `backend/tests/test_api_ws_chat_optimizer_errors.py` — the four optimizer `chat_error` codes mapped from `412`/structured `403` (business refusals unmapped) through the HTTP and CC-error-chain helpers, `chat_blocked` (`decision_pending` + ids + expiry, nothing dispatched/persisted), the `live_test` block on `intervene_request` (dispatch and reconnect reads, absent for a plain ask) and the `live_test_result` chunk (and its socket-failure tolerance).
- `backend/tests/test_internal_endpoint_allowlist_coverage.py` (updated) — `request-live-test` is CH-allowlisted; `/internal/live-test/run` is never a CC internal endpoint.

Pre-existing, unrelated failures observed while running the broader regression (not caused by this change): `test_internal_endpoint_allowlist_coverage::test_system_tool_registry_endpoints_are_ch_allowlisted` (management-tools literal names), `tests/unit/test_setup_tenant_demo.py` (collection error — the repo-root `setup/` package is not importable when pytest runs from `backend/`), `test_tenant_header_verification` (CH cert middleware on `/internal/agent/execute`), `test_control_center_comm_hub_client` / `test_fix_20261031_131030_cert_paths` (Path-vs-str), `test_fix_20261102_062047_mcp_tool_listing`, `test_tenant_isolation_sweep` registry/`AgentClient`/`ConversationTurnResume` cases, `tests/api/v1/test_skills_api.py` + `tests/api/v1/test_mcp_hub_api.py` mock/schema drift, and the cert/tenant-header `tests/integration/*` service-flow suites.

Backend status (8.1–8.4 complete, script-level contract): 273 tests in the new/updated files pass (mode context 16, routing 10, subject guard 19, conversation API 16, model resolver 20, model-config API 12, gate 42, ledger 41, runner 12, answer path 11, migration 18, internal request-live-test tool 5, AR runner 21, CH forwarding 14, WS payloads 16). The directly related regression suites (`test_optimized_plan`, `test_internal_scripts_api`, `test_execution_log_bounds`, `test_internal_agent_context_authoring_model`, `tests/unit/*`, `tests/services/*`, `tests/agent_runtime/*`, `tests/communication_hub/*`, `tests/api/*`) are green apart from the pre-existing failures listed above. Frontend coverage is complete (8.5 — see below); E2E coverage is complete (8.6 — see below).

Frontend (`frontend/src/__tests__/`, run with `cd frontend && npx vitest run --reporter=json --outputFile=vitest_results.json`):

*All frontend suites below are implemented and green (8.5): 130 new tests.*

- `AgentOptimizedPlanTab.optimizerEntry.test.tsx` (new, 9) — entry action with the "this agent only" annotation for **both typed and conversational** agent types, identity chip, no separate-optimizer chrome, blocked-with-permission disabled vs model-reason open + System Config shortcut, missing-plan informational empty state that still opens the conversation, retained Optimize/retire actions, and plan refresh after a conversation turn settles without a reload.
- `OptimizerChatDialog.test.tsx` (new, 18) — subject title + identity-parity chip tooltip (no separate optimizer identity), the compact default-collapsed "What ran in this session" bar (replay-only / live-used / running chips; expansion to audit + scope), model-unavailable alert with a working System Config shortcut and disabled composer, stale-model naming, optimizer `chat_error` presentation, decision-pending composer block, inline ask card answer payload, script-based approval-card approve/deny payloads with collapse-after-decision, expandable activity, subject-only conversation creation payload, and the turn-settled refresh callback; plus business/assistant mode unchanged (no optimization chrome leaks, generic intervention card retained).
- `OptimizerPanels.test.tsx` (new, 15) — `OptimizationSessionBar` (compact, default-collapsed "What ran in this session" bar: replay / approved-live counts, replay-only / live-used / running chips, expansion to the audit detail + identity parity + scope), `OptimizerActivityBlock` (collapsed summary, expansion, running state), `OptimizerAuditBlock` (replay count vs approved live operations, replay-only chip, last-live time, attribution), `OptimizerModelAlert` (unconfigured / stale / unknown-model / generic).
- `LiveTestApprovalCard.test.tsx` (new, 13) — script-based approval (script name/version, informational `tools.call` preview, "the whole script once / MCP tools are assumed to work / not remembered" copy + answer window), approve/deny payloads and in-flight disabling, pending as the ONLY expanded state, collapse to a one-line history summary for approved/running/executed/failed/denied/expired/cancelled with expansion to the script run record (output, telemetry, per-`tools.call` outcomes), expiry explicitly distinct (dashed chip + preview-kept note), explicit local state override, defensive formatting.
- `OptimizerAskCard.test.tsx` (new, 8) — question/choices/free-text, trimmed single submission, approval approve/deny, resolved read-only state, in-flight blocking, dialog-error presentation.
- `SystemConfigPage.optimizer-model.test.tsx` (new, 11) — workspace scope, what the model powers (not a runtime model), inherit-from-authoring, catalogue-only options + explicit inherit, unset/stale reminder with stale option kept disabled and Save blocked until re-select, save + clear-to-inherit (`null`), `422` through the dialog error standard, no-options state, no-substitution note.
- `useChatSession.optimizer.test.ts` (new, 10) — `live_test` / `live_test_result` parsing, optimizer `chat_error`, `chat_blocked` (`decision_pending`) and its clearing, activity-step derivation from the status stream, and the pure parsers' defensive shapes.
- `useOptimizationConversation.test.tsx` (new, 10) — query keys, subject-only creation payload, conversation read (subject/availability/audit), disabled reads without a session, ledger read, card-state mapping/priority, per-operation outcomes, and `invalidateOptimizedPlanQueries` refetching the subject's plan + gate only (7.5).
- `useOptimizationGate.optimizerModel.test.tsx` (new, 11) — extended gate payload (conversational reported optimizable for the conversation, additive optimizer-model fields), legacy/partial degradation, `localizeOptimizerModelReason` / `localizeOptimizationConversationReason` for every reason code, and `isAuthoringModelReasonCode`.
- `useOptimizerModelConfig.test.tsx` (new, 7) — tenant-scoped read, save, clear-to-inherit, `422` propagation, inherit sentinel, stale-selection and blocked helpers.
- `errorUtils.optimizer.test.ts` (new, 13) — `extractOptimizerRefusal` for the conversation-`422`, internal-`412`, system-tool-refusal and WS shapes; `isOptimizerChatErrorCode`; `isDecisionPendingBlock`; `isOptimizerModelReasonCode`.
- `optimizerI18n.test.ts` (new, 6) — every literal `t()` key in the optimizer components/hooks resolves in `en.json` with non-empty copy, required interpolation params declared, reason/chat-error vocabularies covered, and the single-use safety copy present.

Affected existing suites (verified unchanged-green): `AgentOptimizedPlanTab.test.tsx`, the `ConversationDialog.*` suites, `SystemConfigPage.authoring-model.test.tsx` / `SystemConfigPage.assistant-model.test.tsx`, `useChatSession.intervention.test.ts` / `useChatSession.activityState.test.ts`, `AgentTypeDetailsDialog.test.tsx`, `AgentManagementPage.test.tsx` / `AgentManagementPanelPage.test.tsx`, `ConversationSessionsTab.test.tsx`.

Full-suite status (8.5, re-verified after the script-level card/bar round-out): 527 suites / 2115 passed / 0 failed / 18 pre-existing pending; `npx tsc --noEmit` clean. No `ConversationDelegationVisibility` flake observed in the final full run.


E2E (`e2e/tests/`, Playwright — mocked first via `page.route()` + shared helpers). Status (8.6, re-verified after the script-level card/bar round-out): implemented and green — conversation 6 passed, live-test approval 5 passed, model config 6 passed, real-backend 3 tests skipping honestly when no token/stack is available. Existing `agent-optimize-gate` (7) and `agent-optimize-requires-fix` (1) re-run unchanged-green. Run with `cd e2e && npx playwright test tests/<spec>.spec.ts --project=chromium --reporter=line` (build once with `cd frontend && npm run build:e2e`, preview on `:4173`).

- `e2e/tests/_agent_optimizer_world.ts` (new, shared world) — the mocked optimizer API surface (composed gate, optimized plan, subject-only conversation create, conversation read with availability + audit replay/live projection, ledger, pending interventions, session lifecycle), script-level live-test fixtures (`LIVE_TEST_SCRIPT`, `SCRIPT_PREVIEW`, `scriptRunRecord`), a drivable fake chat socket (frame log + server-event emitter), a highest-priority request observer for "zero writes" assertions, and the navigation/interaction helpers (`openOptimizerChat` asserting the collapsed session bar, `expandSessionBar`, `expandLiveTestCard`, `sendChatMessage`, `closeChatDialog`, `markNoReload`).
- `e2e/tests/agent-optimizer-conversation.spec.ts` (new, 6 passed) — typed journey: entry annotated "scoped to this agent" + model disclosure, retained one-shot Optimize/retire actions, chat opens in optimization mode with the identity chip tooltip and the compact default-collapsed "What ran in this session" bar (replay-only / 0 live operations; expansion reveals identity parity + scope + audit detail), opening starts no work, the first message creates the conversation through the subject-only endpoint (`{agent_type_id}`), **exactly one chat-status indicator while the turn streams** (thinking → tool, updated in place, never accumulating) with **no folded optimizer-activity block anywhere** and **no indicator once the turn is terminal**, finished turn outcome, and the plan refreshing without a reload (plan step replaced, no page reload); conversational agent: same entry with conversational scope, missing plan as information, zero work/zero writes on open; in-chat ask/decide answered once through the socket with the answer retained; out-of-scope `chat_error` explained with zero writes and no other agent type's plan/scripts/logs touched; business conversation on the same agent type keeps the ordinary chat (no optimization chrome, no ledger/optimizer-model reads, business create endpoint); a typed agent with **no optimized plan** sends the first message and keeps its session (exactly one conversation-create request, no remount).
- `e2e/tests/agent-optimizer-live-test-approval.spec.ts` (new, 5 passed) — pending card names the saved script + version and its informational `tools.call` preview ("It will call: …"), states the run is the whole script once as this agent, not remembered, with the answer window, composer blocked; approve sends one decision frame and the card is **collapsed by decision** (summary visible, detail body hidden until expanded — no second spinner / activity block), moving pending → running ("running once", session-bar running chip) → executed one-line summary that expands to the script run record (output, telemetry, per-`tools.call` outcomes) with "approval used"/no re-approve controls; the decided card is asserted to sit **inline in the timeline at its decision position** (after the operator's request, before the assistant's final summary — bounding-box order, never a trailing section); the session bar's audit detail distinguishes 1 replay verification from 2 approved live operations and the refinement lands without a reload, with a later need requiring a NEW script request; the bar drops back to "2 approved live operations" once the result chunk lands (never stuck on "running"); deny runs nothing (collapsed denied summary, empty evidence, replay-only, no retry, only the conversation create written); expiry is a distinct collapsed terminal state (dashed chip, preview-kept note, "expired unanswered", no approval frame, not retried); a re-delivered decision for an already-executed request renders read-only and sends nothing.
- `e2e/tests/agent-optimizer-model-config.spec.ts` (new, 6 passed) — System Config optimizer section: workspace scope, "not a runtime model", inherit-from-authoring, catalogue-only options, no-substitution note, inherited/selected/blocked state, single PUT on save, `null` clear-to-inherit, stale value kept visible as a disabled option with Save blocked until re-selected, `422` through the dialog error standard; and with no usable model the Optimized Plan entry is annotated with the shared reason + System Config shortcut, the chat shows the model alert with a disabled composer, and the shortcut lands on the System Config section.
- `e2e/tests/agent-optimizer.real-backend.spec.ts` (new, mandatory for `has_db_changes: true`) — `Real Backend Integration` block with no route mocking: optimizer-model config read, subject-only optimization conversation create + read (subject/channel/availability/audit) + empty ledger, and fail-closed reads for an unknown session. Skips honestly when no token/stack is available; any 5xx on the new endpoints fails loudly with the body (unapplied-migration signal).
- Pre-existing specs re-run unchanged (no regression): `agent-optimize-gate.spec.ts`, `agent-optimize-requires-fix.spec.ts`, `agent-plan-mode.spec.ts`, `agent-plan-generation.spec.ts`.

Two genuine product defects were found by the E2E suite and fixed in production code; each is now covered by an ordinary (non-`fixme`) spec:

1. **Plan-less agent: the optimization chat lost its session right after the first message.** `AgentOptimizedPlanTab` returned the `ConversationDialog` from three different JSX branches (loading spinner / no-plan alert / full plan), so any branch switch remounted the dialog. `ConversationDialog` counted the conversation-create request as a turn in flight (`isResuming` fed `turnStreaming`), so when the create resolved it called `onOptimizationTurnSettled()` → the tab invalidated the plan queries → the 404 plan query refetched with no data (`isLoading === true`) → the tab flipped to the loading branch → the chat remounted, the websocket closed and the created session was forgotten (a following message would create another conversation). Fixed by mounting the dialog **once** outside the plan section and reporting only real turn activity (not the create request) to the host; covered by `agent-optimizer-conversation.spec.ts` → "typed agent with NO optimized plan can send the first message and keep the session".
2. **The chat chrome stuck on "Live test running…" after the approved live test finished.** `ConversationDialog` set `liveTestApprovedRequestId` on approve and only cleared it on dialog close/reset, while the chrome treated a non-null value as running — so a completed run still claimed to be in flight while the approval card and the audit block correctly said it ran once and is spent. Fixed by clearing the marker when the `live_test_result` chunk (or a terminal ledger row) for that request arrives, so the chip falls back to "N approved live operations"; covered by `agent-optimizer-live-test-approval.spec.ts` → "the session bar reports the used live test after its result landed".


Note: the Python SDK (`sdk/parthenon-python/test/`), the JS SDK (`sdk/parthenon-js/`) and the MCP demo app (`mcp-demo-app/tests/`) are not exercised by this change — no SDK, widget, integration-client or demo-app surface is touched (`/integrate/*` behaviour is unchanged).
