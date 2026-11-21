# Test Plan: Remove the Hard-Coded Delegation Depth Cap

**Change**: `remove-delegation-depth-cap`
**Date**: 2026-11-20 (verified 2026-11-21)
**Status**: Verified — all three layers executed; see §6 Verification results. `has_ui_changes: true`, `has_db_changes: false`

---

## 1. Test Strategy

The change makes the agent type's configured **Max Delegation Depth** the only depth limit. Three code surfaces must be verified: Control Center depth plumbing (recorded depth on the internal session payload, configured maximum on the delegation status API, relaxed guardrail validation bounds), Agent Runtime depth resolution and enforcement (configured limit authoritative for task and conversational agents, runs seeded from persisted depth), and the Web UI (no depth input ceiling, parent peek excludes the child's own delegation activity).

**No database schema change.** There is no migration to apply and no `information_schema` assertion to write for this change. The only new data carried is an additive integer field on an existing internal payload, sourced from a column that already exists on `AgentJob`. Cross-service integration tests still require the backend stack running (Control Center + Agent Runtime + Communication Hub); the in-process REST agent-type suite runs against the test database. None require `alembic upgrade head` beyond the already-current head.

Coverage is verification-heavy: most assertions must prove a *removed* constant no longer influences behaviour, so each unit test should be written to fail against the pre-change code (a "cap-removal" assertion) rather than merely re-asserting the new value.

### Test Layers

| Layer | Framework | Location | Purpose |
|-------|-----------|----------|---------|
| Backend unit | pytest | `backend/tests/unit/` | Guardrail state resolution, starting-depth precedence, enforcement comparisons, blocked event payloads, validation bounds, peek-independent server logic |
| Backend integration | pytest + real stack | `backend/tests/integration/`, `backend/tests/api/` | Internal session payload field, delegation-status values for two agent types, assistant-managed validation parity, A2A parent-link depth derivation, single-session log scope |
| Frontend unit | Vitest | `frontend/src/__tests__/` | Pure peek filter, log presenter max depth, configuration inputs above the former ceiling |
| Frontend component | Vitest + RTL | `frontend/src/__tests__/` | Delegation card peek exclusion, drill-in renders the child log unfiltered |
| E2E mocked | Playwright | `e2e/tests/` | End-to-end execution-log scoping and configuration flows via `page.route()` mocks |
| E2E real backend | Playwright | `e2e/tests/` | One suite against the live stack for delegated execution + log drill-in |
| Manual / exploratory | — | — | Multi-level task delegation across services, depth display vs. configuration, intervention scope |

### Layer Bar

All layers must pass. A backend-only pass is insufficient because the two most operator-visible behaviours (displayed maximum and peek scoping) live entirely in the UI, and the depth removal is only meaningful if a real delegated run honours the configured value end to end.

---

## 2. Coverage Areas

### 2.1 Depth resolution in the guardrail state builder
The input-type branch that forced a single delegated level is removed. Coverage must prove:
- Task (non-conversational) and conversational agents both resolve the configured maximum unchanged.
- The platform default applies only as a default when policy carries no value, never as a reduction.
- Both the tree depth and the delegation depth are seeded from the same resolved starting depth.

### 2.2 Starting depth provenance
A delegated child run must begin at its persisted recorded depth. Coverage must prove:
- The payload's recorded depth wins over the legacy `input_data` key when both are present.
- The legacy key alone still resolves correctly (backward compatibility).
- Neither present resolves to zero, so root runs are unaffected.

### 2.3 Enforcement sites
Three checks bound depth (the task-loop delegation guard, the runtime hard-limit check, and the guardrail callback depth check). Coverage must prove:
- The delegation guard blocks a hop when the next depth would exceed the configured maximum, so an agent already at the maximum cannot delegate onward.
- The two run-level checks read the same configured maximum and the same actual chain depth, and stop a run only when its own depth exceeds the maximum.
- All checks still emit / raise the pre-existing guardrail reason rather than a new one.

### 2.4 Blocked-delegation outcome and auditability
A blocked delegation must remain observable and attributable to policy:
- A depth-blocked execution event is recorded.
- The blocked tool result is returned.
- The recorded outcome states the configured maximum that was reached; no message asserts a fixed one-level task-agent rule.

### 2.5 Delegation status API
The displayed maximum must be traceable to configuration:
- Returns the session agent type's configured maximum for two agent types with different values.
- Falls back to the platform guardrail default (not a one-level constant) when the agent type cannot be resolved.
- Response shape unchanged; pending-intervention scope unchanged.

### 2.6 Internal session payload
The persisted delegation depth is the only channel Agent Runtime uses to learn a child's depth. Coverage must prove the field reflects the stored job column and is required (no construction site left unpopulated).

### 2.7 Guardrail validation bounds
- Direct REST path and assistant-managed path both accept any non-negative integer, including values above the former 32 ceiling.
- The REST create path persists the submitted guardrail values (the configured depth is not replaced by the column default).
- The REST update contract enforces the same non-negative floor as create; unlike create, the update path previously accepted `-1`.
- Both reject negative values with structured, per-field errors.
- Both validators return identical accept/reject outcomes for the depth field.
- No other guardrail bound changed.
- Assistant-facing field description no longer advertises a numeric ceiling.

### 2.8 Frontend configuration inputs
- Agent Type form and Agent Properties panel accept a typed depth above the former ceiling and submit it unchanged through draft composition.
- Non-negative minimum still enforced.
- No other guardrail input constraint altered.

### 2.9 Execution-log scoping (product guarantee)
- Parent log and parent peek show only the current agent's execution plus its **direct** delegation lifecycle.
- Child's own sub-delegation events appear only in the child's own log.
- Server-side log queries remain single-session; no recursive or descendant aggregation is introduced.

### 2.10 Adjacent guardrails unchanged (regression)
Cycle detection, dead-loop detection, delegated-step budget, iteration ceiling, timeout, and token budget must behave identically. These are the highest-risk collateral areas because depth plumbing changes sit in the same task-loop and fallback constructions.

---

## 3. Critical Scenarios

### Configured depth is authoritative

- **WHEN** a task (non-conversational) agent type is configured with Max Delegation Depth 3
  **THEN** the resolved guardrail maximum is 3, not 1, and the task loop context and its fallback guardrail state both carry 3.

- **WHEN** a conversational agent type is configured with Max Delegation Depth 3
  **THEN** the resolved guardrail maximum is 3 and is identical to the task-agent outcome for the same configuration.

- **WHEN** an agent type has no explicitly configured depth
  **THEN** the platform default is resolved, matching the pre-change effective default, with no change to the stored value or to what the configuration screen shows.

### Nested delegation allowed within the maximum

- **WHEN** a delegated task agent at chain depth 1 (configured maximum 3) invokes a delegation tool
  **THEN** the delegation is permitted and a child job is enqueued with recorded depth 2.

- **WHEN** a run at chain depth 2 with configured maximum 3 attempts a further delegation
  **THEN** the attempt is allowed (the hop reaches depth 3, the last permitted level) and no depth block is recorded.

- **WHEN** a run already at chain depth 3 with configured maximum 3 attempts a further delegation
  **THEN** the delegation is blocked, because the hop would reach depth 4 and exceed the configured maximum.

### Blocked delegation is recorded and states the configured limit

- **WHEN** a delegation would exceed the configured maximum (e.g. actual depth 4, maximum 3)
  **THEN** the delegation is blocked, a depth-blocked execution event is emitted, a blocked tool result is returned, and the outcome states that the configured maximum of 3 was reached.

- **WHEN** an operator inspects the blocked event in the execution history
  **THEN** the event is distinguishable as policy enforcement (guardrail category / existing guardrail reason), not a functional failure, and it names the limit reached.

- **WHEN** an act-phase delegation runs without a supplied guardrail state
  **THEN** the fallback state blocks at the loop context's configured maximum, the emitted event carries that maximum, and no message references a fixed one-level task-agent rule.

### Delegated child starts from persisted depth

- **WHEN** a delegated child's payload carries a recorded delegation depth of 2
  **THEN** the guardrail state's tree depth and delegation depth are both 2, and nested delegation from that run is evaluated from depth 2 rather than from zero.

- **WHEN** the payload carries only the legacy `input_data` depth key
  **THEN** the same starting depth resolves.

- **WHEN** the payload carries both a recorded depth and the legacy input key with different values
  **THEN** the recorded depth takes precedence.

- **WHEN** a root run starts
  **THEN** its starting depth resolves to zero and its behaviour is unchanged.

### Delegation status reflects configuration

- **WHEN** the delegation status for a session of an agent type configured with maximum 3 is requested
  **THEN** the response's maximum-depth field is 3.

- **WHEN** the same request is made for a session of a second agent type configured with maximum 7
  **THEN** the response's maximum-depth field is 7, proving the value is per-agent-type and not a constant.

- **WHEN** the session's agent type cannot be resolved
  **THEN** the response falls back to the platform guardrail default and never to a one-level constant.

- **WHEN** the delegation status response is compared to the pre-change shape
  **THEN** the field set and JSON shape are identical.

### Guardrail validation accepts values above the former ceiling

- **WHEN** an agent type is created or updated through the direct REST path with Max Delegation Depth 64
  **THEN** validation succeeds and the value is persisted unchanged.

- **WHEN** the same value is submitted through the assistant-managed path
  **THEN** validation succeeds with no structured problems and the stored value matches.

- **WHEN** either path is given a negative depth
  **THEN** validation fails with a structured, per-field error identifying the depth field.

- **WHEN** the two validators are exercised with the same set of depth values (negative, 0, 1, 32, 33, large)
  **THEN** they produce identical accept/reject outcomes.

- **WHEN** an operator reads the assistant-facing guardrail field description
  **THEN** it states the non-negative floor and the default and advertises no numeric ceiling.

- **WHEN** other guardrail fields are submitted at and beyond their bounds
  **THEN** their accept/reject behaviour is unchanged by this change.

### Frontend configuration inputs

- **WHEN** an operator types 40 into Max Delegation Depth in the Agent Type form
  **THEN** the input accepts the value and the submitted payload carries 40.

- **WHEN** the same value is typed in the Agent Properties panel
  **THEN** the panel accepts it, the draft composition carries 40 unchanged, and saving preserves 40.

- **WHEN** a negative depth is typed in either input
  **THEN** non-negative enforcement still applies.

- **WHEN** other guardrail inputs (iterations, delegated steps, timeout, token budgets) are inspected
  **THEN** their constraints and defaults are unchanged.

### Parent log and peek scoping

- **WHEN** a parent agent delegates to a child which itself delegates to a grandchild
  **THEN** the parent's execution log contains the parent's own execution and its direct delegation lifecycle events only, with zero grandchild entries.

- **WHEN** the parent's delegation card renders its progress peek for the child
  **THEN** the peek excludes the child's own delegation tool calls and delegation tool responses, and excludes delegation lifecycle event types.

- **WHEN** the same parent peek is inspected for the child's own non-delegation activity
  **THEN** the child's initialization, model, tool, observation, and completion entries still appear, and the existing slice length is unchanged.

- **WHEN** the operator uses "View Execution Logs" on the delegation entry
  **THEN** the child's own execution log opens and does show the child's own sub-delegation events and its own peek.

- **WHEN** the operator returns to the parent log after drilling in
  **THEN** the parent log's contents are unchanged and still contain no grandchild entries.

- **WHEN** the peek filter helper is exercised with a canonical-prefix delegation tool call, a legacy-prefix delegation tool call, a delegation tool response, a delegation lifecycle event, and an allow-listed non-delegation entry
  **THEN** only the allow-listed entry is returned, with no input mutation and no I/O.

### Multi-level delegation with all guardrails intact

- **WHEN** a task agent chain runs three levels deep within a configured maximum of 3
  **THEN** every level executes and each delegated job's recorded depth increments by one per hop.

- **WHEN** the same chain is configured so that cycle detection, dead-loop detection, delegated-step count, iteration ceiling, timeout, or token budget is reached
  **THEN** the corresponding guardrail still blocks/terminates with its pre-existing reason and outcome, unaffected by the depth change.

---

## 4. Edge Cases & Risks

| # | Edge case / risk | Expected behaviour | Why it matters |
|---|---|---|---|
| 1 | Configured depth `0` | No delegation permitted at the root; a first delegation attempt is blocked with the configured limit stated as 0 | Zero is a valid non-negative value; must not be treated as "unset" and fall back to the default |
| 2 | Very large configured depth (e.g. 1000) | Accepted by both validators, both config inputs, and honoured at runtime with no platform ceiling | The core promise of the epic; any residual constant resurfacing here would be a silent cap |
| 3 | Missing / unknown agent type on the status API | Falls back to the platform default guardrail value; response shape intact | Must not 500 and must not fall back to a one-level constant |
| 4 | Legacy input key vs recorded job depth both present | Recorded job depth wins | Guards against an old request payload inflating or deflating the effective depth |
| 5 | Payload with the recorded depth field absent (older producer) | Resolves zero (root behaviour) without error | The field is additive; a stale in-flight payload must not crash the run |
| 6 | Parallel sibling delegations from one parent | Each child receives parent depth + 1 and is evaluated independently; depth is per-chain, not cumulative across siblings | A shared mutable depth counter would mis-block siblings at the cap |
| 7 | Intervention propagation scope | Remains direct-child scoped; deeper levels do not surface interventions in the parent | Explicitly preserved; a wider query would leak deeper activity into the parent log |
| 8 | Conversational delegation with no parent job link | Child recorded depth is zero; hop-by-hop degeneracy is accepted and documented | Documented limitation — test should assert the boundary rather than assume chain inheritance |
| 9 | Log stream performance with more levels | Streaming remains single-session; entry volume per log is bounded by that session's own work | A recursive fetch would multiply volume per level |
| 10 | Recursive log queries re-entering the backend | No descendant traversal in the logs snapshot or stream handlers | Product guarantee; verify by asserting the child's entries never appear when only the parent id is queried |
| 11 | Two enforcement sites drifting apart | Both compare the same configured maximum against the same chain depth | Divergence would produce a block that the other site would allow |
| 12 | Stale one-level wording / comments | No message, event payload, or assistant description implies a platform cap | Operators must be able to attribute every block to configuration |
| 13 | Existing agent types with configured values | Stored value unchanged; only the hidden override stops applying | Compatibility criterion — no silent data rewrite |
| 14 | Frontend peek filter accidentally applied to the child log | Child log remains unfiltered | Would hide the child's own delegation, breaking drill-in observability |
| 15 | Peek filter regression on the non-delegation allow-list | Existing peek contents preserved | Avoid over-filtering in the name of excluding sub-delegation |

---

## 5. Acceptance Criteria Checklist

**Configured depth is the only limit**
- [x] Any permitted Max Delegation Depth can be set on any agent type (conversational or task) and is honoured exactly as the only depth limit.
- [x] No agent type is limited to a shallower depth than its configured value by the platform; configured depth is never silently reduced.
- [x] Task (non-conversational) agents can delegate through additional levels when their configured guardrail allows it, and those delegates can delegate further while within the limit.

**Guardrails remain in force and auditable**
- [x] A delegation that would exceed the configured maximum is blocked, and the run ends or continues per existing guardrail behaviour with a clear outcome message.
- [x] Every blocked over-deep delegation is recorded in the agent's execution history in operator-visible, auditable terms, distinguishing policy enforcement from functional failure.
- [x] Delegation depth blocks are reported against the configured limit, stating what limit was reached.
- [x] Cycle and dead-loop validation, delegated-step budgets, iteration ceilings, timeouts, and token budgets continue to apply exactly as before.

**Execution-log visibility stays single-level scoped**
- [x] An agent's execution log shows that agent's own execution and the lifecycle events of its direct delegations only.
- [x] No grandchild activity is folded into a parent log; no recursive log display exists.
- [x] From a delegated agent's own log, its sub-delegation events — delegation made, progress, and outcome — are visible.
- [x] Drill-in via the existing "View Execution Logs" action moves the operator from parent to delegated log with no new navigation model.
- [x] Opening a delegated log does not change the parent log's contents, and the parent log remains readable on return.

**Status display reflects configuration**
- [x] The delegation status surfaced to the execution-log viewer reflects the agent type's configured maximum, not a fixed platform value.
- [x] Two agent types configured with different maximums display different maximums in their respective logs.
- [x] While a run is actively delegating, the depth shown is consistent with the configured maximum and with the recorded delegation events.

**Compatibility**
- [x] Agent types that never configured a Max Delegation Depth keep their current effective default behaviour, with no change to stored values or to the configuration screen.
- [x] Agent types that already configured a value see no change to that stored value; only the hidden override stops applying.

---

## 6. Test File References

Paths follow `easyspec-config.yaml` → `source.tests` (`backend/tests/`, `frontend/src/__tests__/`, `e2e/tests/`).

### Backend — existing, to update or extend

| File | Status | Focus |
|---|---|---|
| `backend/tests/unit/test_delegation_depth_guard.py` | Updated | Guardrail state resolution for task/conversational agents; one-level assertions replaced; starting-depth provenance (recorded vs legacy vs 0, recorded wins); runtime limit check reads the deepest known depth; act-phase blocked event carries the configured maximum; new: a hop reaching exactly the configured maximum is allowed |
| `backend/tests/unit/test_agent_runtime_executor.py` | Updated | `_build_guardrail_state` depth provenance; `_build_agent_type_guardrail_state` configured profile + defaults + legacy fallback; new: `_run_task_loop` captures its `TaskAgentLoop` context to prove configured max depth and recorded starting depth are used (no constants) |
| `backend/tests/unit/test_guardrail_callback.py` | Updated | Callback depth check reads configured maximum vs the deepest of delegation/tree depth; block only when depth exceeds the maximum; depth-equal-to-maximum allowed; configured 5 allowed vs 6 blocked |
| `backend/tests/unit/test_langchain_tool_wrapper.py` | Updated | AR delegation tool pre-dispatch hop guard: at depth == max the hop is blocked (blocked result, `delegation_depth_blocked` with target/current/next/max, no A2A dispatch, counters unchanged); below max the existing started/waiting/resumed path and counter advance are preserved; configured max 0 blocks the root's first hop; no guardrail state keeps legacy behaviour |
| `backend/tests/unit/test_conversation_intervention_turns.py` | Reviewed — no change required | Intervention depth fields are persisted from the request/model and never encode a one-level constant; direct-child scoping unchanged |
| `backend/tests/unit/test_agent_schemas.py` | Updated | REST create contract accepts 0/1/32/33/64/1000, rejects negatives, other bounds unchanged; new: REST **update** contract (`AgentTypeUpdate`) accepts all non-negatives and rejects negatives, and an update that omits the field is unaffected |
| `backend/tests/unit/test_delegation_depth_status_api.py` | **New** | Internal session payload exposes the persisted depth as a required integer; delegation-status returns the configured max (3 vs 7) and the platform-default fallback; response shape unchanged; pending-intervention query remains direct-child scoped |
| `backend/tests/integration/test_management_tool_full_field_parity.py` | Updated | Assistant-managed create/update accept 64/1000 and persist unchanged; negative returns a per-field structured error; REST ↔ management accept/reject parity over −1/0/1/32/33/64/10000 |
| `backend/tests/integration/test_agent_type_rest_create_guardrails.py` | **New** | REST `POST /agents/types` persists submitted guardrails (delegation depth 64 read back from the stored row); REST `PUT` accepts 1000 and rejects −1 without corrupting the stored value |

### Backend — existing, regression / nearest-pattern references

| File | Status | Focus |
|---|---|---|
| `backend/tests/unit/test_agent_guardrails.py` | Regression — passed | Guardrail state dataclass values reflect configuration; adjacent guardrail budgets unchanged |
| `backend/tests/unit/test_task_delegation_status_events.py` | Regression — passed | Task delegation status event sequence and recorded depth values |
| `backend/tests/unit/test_hitl_delegation_status_events.py` | Regression — passed | HITL delegation status sequence unaffected by the depth change |
| `backend/tests/unit/test_ws_delegation_visibility.py` | Regression — passed | Delegation visibility/filtering unchanged; no deeper leakage |
| `backend/tests/integration/test_a2a_tenant_delegation.py` | Regression — passed | A2A parent-link resolution and child depth = parent depth + 1 persisted at enqueue |
| `backend/tests/integration/test_data_clients.py` | Regression — passed (payload shape exercised by the new status-API suite) | Internal session payload depth surface unchanged for existing clients |
| `backend/tests/api/test_agents_api.py` | Route conventions reference; delegation-status route covered directly in `test_delegation_depth_status_api.py` | Route-level request/response conventions; no route-shape change was needed |
| `backend/tests/integration/test_agent_execution_logs.py` | Regression — passed | Single-session log query; no descendant/grandchild entries returned |

### Frontend — Vitest

| File | Status | Focus |
|---|---|---|
| `frontend/src/__tests__/delegationPeek.test.ts` | **New** (helper `frontend/src/services/delegationPeek.ts` also new) | Pure filter: allow-list preserved; canonical `agent____<slug>` and legacy `agent__<slug>` delegation tool calls excluded; delegation tool responses (`delegation_target`) excluded; delegation lifecycle event types excluded; no mutation, no I/O |
| `frontend/src/__tests__/WorkingStepsPanel.test.tsx` | Updated | Delegation card peek excludes the child's onward delegation entries while retaining the child's own non-delegation entries; the child log is still fetched raw and the drill-in action is wired |
| `frontend/src/__tests__/delegationDepthInputs.test.tsx` | **New** | Agent Type form and Agent Properties panel accept depth 40, retain `min=0`, expose no `max`, submit 40 unchanged, and leave other guardrail bounds untouched |
| `frontend/src/__tests__/AgentTypeForm.test.tsx` | Not modified — depth coverage lives in `delegationDepthInputs.test.tsx` | Existing form regression coverage retained |
| `frontend/src/__tests__/LogPresenter.test.ts` | Updated | Derived current and maximum delegation depth come from logged snapshot values (3 vs 9), not a hard-coded constant |
| `frontend/src/__tests__/useSessionExecutionLogStream.test.ts` | Regression — passed | Peek stream still subscribes to the direct child session only |
| `frontend/src/__tests__/agentTypeToDraftComposition.test.ts` | Updated | Draft composition carries depth 40 unchanged (no ceiling) |

### E2E — Playwright

| File | Status | Focus |
|---|---|---|
| `e2e/tests/delegation-depth-scoping.spec.ts` | **New (mocked, executed)** | Create dialog and Agent Properties panel submit depth 40 unchanged with no cap advertised; parent log + peek exclude the child's own delegation while "View Execution Logs" opens the unfiltered child log; guardrail depth indicator shows 3 vs 7 |
| `e2e/tests/delegation-depth-scoping.real-backend.spec.ts` | **New (unmocked, executed against the live stack)** | Live REST create with depth 64 persists 64; update to 1000 persists; negative rejected with a field error. Does not run an LLM-backed nested delegation (see execution notes) |
| `e2e/tests/delegation-lifecycle-visibility.spec.ts` | Regression — passed (extended coverage lives in the new mocked spec) | Parent log renders each direct delegation lifecycle event type |
| `e2e/tests/agent-logs.spec.ts` | Regression — passed | Log viewer summary/working steps unchanged |
| `e2e/tests/conversation-delegation-visibility.spec.ts` | Regression — passed | Conversational delegation visibility unchanged in scope |
| `e2e/tests/agent-management.spec.ts` | Regression — passed | Agent type list/create dialog guardrail controls unchanged |

### Execution notes

- Backend unit suites are fast and should be the first gate; the delegation depth guard, executor, and callback suites are the primary defence against a cap silently returning.
- Frontend tests should run with the JSON reporter to avoid stdout issues, then assert zero failures.
- Stack-dependent integration and E2E require the running stack (`./scripts/restart-backend.sh` on macOS / `parthenon.ps1` on Windows); the in-process REST agent-type suite only needs the test database. No migration step is required for this change.
- No test may assert a platform-imposed one-level delegation depth after this change ships.

### Verification results (2026-11-21)

| Layer | Command | Result |
|---|---|---|
| Backend unit | `../.venv/bin/python -m pytest tests/unit -q` (in `backend/`, repo-root venv) | 1614 passed, 11 skipped, 0 failed |
| Backend API | `../.venv/bin/python -m pytest tests/api -q` | 232 passed, 68 skipped, 0 failed |
| Backend integration (depth-related) | `test_agent_type_rest_create_guardrails`, `test_management_tool_full_field_parity`, `test_data_clients`, `test_a2a_tenant_delegation`, `test_agent_execution_logs` | 69 passed, 2 skipped, 0 failed |
| Backend integration (whole folder) | `../.venv/bin/python -m pytest tests/integration -q` | 683 passed, 135 skipped, 21 failed — all 21 are pre-existing, unrelated to this change: cross-service certificate flows (`test_service_auth`, `test_cross_service_flows`, `test_full_execution_flow`, `test_agent_execution_flow`) documented in-suite as expected-to-fail without the full cert fix, plus decision-tool data-type tenant visibility (`test_system_one_decision_tools`) |
| Frontend | `npx vitest run --reporter=json --outputFile=vitest_results.json` (in `frontend/`) | 2168 passed, 0 failed, 18 skipped |
| E2E mocked | `npx playwright test tests/delegation-depth-scoping.spec.ts` (default preview build) | 5 passed, 0 failed |
| E2E live | `npx playwright test tests/delegation-depth-scoping.real-backend.spec.ts` | 1 passed against the restarted local stack |
| E2E regression | delegation-lifecycle-visibility, agent-logs, conversation-delegation-visibility, agent-management, agent-management-panel-topology, agent-type-preview-topology | All passed |

### Defects found and fixed during verification

1. **REST create dropped the submitted guardrail policy.** `POST /agents/types`
   validated `guardrail_max_delegation_depth` but never copied any guardrail
   field onto the `AgentType` row, so a create with 64 persisted the column
   default (3). Fixed in `backend/app/api/v1/agents.py`; pinned by
   `backend/tests/integration/test_agent_type_rest_create_guardrails.py`.
2. **REST update accepted negative delegation depth.** `AgentTypeUpdate` had no
   guardrail validation, so `PUT /agents/types/{id}` with `-1` returned 200 and
   persisted `-1` (the update path is the operator's main editing entry point).
   Added a non-negative floor validator mirroring the create contract; pinned by
   the update tests in `test_agent_schemas.py` and the integration suite above.

### Not executed

- A live multi-level delegation run (three hops with a real model provider) is
  not executable in the canonical E2E environment; nested-hop allowance/blocking
  is covered deterministically by the backend unit suites (act guard, runtime
  limit check, guardrail callback), and parent/child log scoping by the mocked
  E2E spec.
- Unrelated pre-existing E2E flakiness was observed in
  `e2e/tests/agent-type-bindings-mocked.spec.ts` (2 multi-binding tests); it
  reproduces with this change reverted and is not caused by this work.
