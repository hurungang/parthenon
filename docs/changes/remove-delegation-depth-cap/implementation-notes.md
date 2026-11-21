# Implementation Notes: remove-delegation-depth-cap

**Status**: Implementation complete and tester-verified (2026-11-21). Two defects found during
verification were fixed — see §3 "Defects fixed during verification".
**Change scope**: `has_db_changes: false`, no migration, no model change, no new endpoint.

---

## 1. Behaviours changed (what the tester must verify)

### Configured depth is the only limit
- `AgentRuntimeExecutor._build_guardrail_state()` no longer has the input-type branch that forced
  `max_delegation_depth = 1` for non-conversational agents. The value from
  `context["guardrail_policy"]["max_delegation_depth"]` is used as-is for task **and** conversational
  agents; `PLATFORM_DEFAULT_MAX_DELEGATION_DEPTH` (3) only fills an absent value. A configured `0`
  is honoured (not treated as "unset").
- The Control-Center-side task loop (`_run_task_loop`) seeds its `TaskAgentLoop` context and its
  fallback `RuntimeGuardrailState` from the new `_build_agent_type_guardrail_state(agent_type, job)`
  helper: configured iterations / max depth / delegated steps / timeout / token settings + a
  `policy_snapshot_id` of `agent_type:<id>`. No depth constant remains in that loop.
- `_act()`'s fallback guardrail state (used only when no state is supplied) is derived from the loop
  context (`ctx.max_iterations`, `ctx.max_delegation_depth`, `ctx.delegation_depth`, `ctx.tree_depth`).

### Delegated child starts from its recorded depth
- `GET /internal/data/sessions/{session_id}` now returns a required integer `delegation_depth`
  populated from `AgentJob.delegation_depth`.
- `_resolve_starting_delegation_depth()` reads `job_data["delegation_depth"]` first, then the legacy
  `input_data["__delegation_depth"]`, then 0. Both `RuntimeGuardrailState.delegation_depth` and
  `.tree_depth` are seeded from it.
- Enforcement (`_check_runtime_limits_or_raise` and `GuardrailCallback._check_delegation_depth` both compare the
  deepest of `tree_depth` / `delegation_depth`) still stops only when depth **exceeds** the configured
  maximum; the task-loop hop guard and the AR delegation tool wrapper's pre-dispatch hop guard both block
  when `next_depth > max` before dispatching.

### Blocked outcome messaging
- `delegation_depth_blocked` still carries `delegation_target`, `current_depth`, `max_depth`
  (`max_depth` is the configured maximum). The message and blocked tool result now name the
  configured maximum; the stale "Non-conversational agents are limited to 1 level of delegation"
  text is gone.

### Delegation status reflects configuration
- `GET /agents/sessions/{id}/delegation/status` returns `job.agent_type.guardrail_max_delegation_depth`;
  falls back to `PLATFORM_DEFAULT_MAX_DELEGATION_DEPTH` (3) when the agent type is unavailable.
  `DelegationStatusResponse.max_depth` is now a required field (no `= 1` default). JSON shape is
  unchanged.

### Validation bounds
- REST (`_validate_guardrail_contract` in `backend/app/schemas/agents.py`) and assistant-managed
  (`_validate_guardrails_structured` in `backend/app/api/v1/internal/management_tools.py`) both accept
  any non-negative delegation depth. The former `32` ceilings (`_MAX_MAX_DELEGATION_DEPTH`) were
  deleted from both modules; negative values still fail with a structured/per-field error. All other
  guardrail bounds are untouched.
- `AgentTypeUpdate` now enforces the same non-negative floor for the depth field (the update path is
  the operator's main editing entry point). Failing values return a 422 naming the field.
- `POST /agents/types` now persists every submitted guardrail value (previously the create endpoint
  validated them but silently stored the column defaults, resetting a configured depth of 64 to 3).
- Assistant tool-schema description for `guardrail_max_delegation_depth` no longer advertises 0–32.

### Execution-log scoping (unchanged guarantee, one filter added)
- New pure module `frontend/src/services/delegationPeek.ts` keeps the existing peek allow-list
  (`agent_initialized`, `tool_call`, `tool_response`, `llm_request`, `llm_response`, `observe`,
  `session_completed`) and excludes delegation lifecycle event types plus `tool_call`/`tool_response`
  entries whose tool name is a delegation target (`agent____<slug>`, legacy `agent__<slug>`, sanitized
  variants) or whose data carries `delegation_target`.
- `WorkingStepsPanel` applies it only to the parent's direct-child progress peek (before `.slice(-5)`).
  The child log fetch and the "View Execution Logs" drill-in remain unfiltered.
- Server-side log queries were not touched: still single-session, no recursive/descendant aggregation.

### Explicitly preserved (must not change)
- Orientation: cycle/dead-loop detection, delegated-step budget, iteration ceiling, timeout, token
  budget. CH remains a forward-only relay; AR reads depth/config only via CC internal APIs.

---

## 2. Accepted boundary / documented limitation

Conversational delegation has no backing `AgentJob` for the requesting turn, so `prepare_a2a_request`
cannot resolve a parent job and the child's recorded depth is `0` (verified in
`backend/app/api/v1/internal/session_data.py`). Each conversational hop therefore starts from depth 0,
while task-agent hops inherit `parent.delegation_depth + 1`. This is documented in `tech-spec.md` §2
and is `test-plan` edge case 8.

---

## 3. Test entry points

### Backend (pytest)
| Suite | Covers |
|---|---|
| `backend/tests/unit/test_delegation_depth_guard.py` | configured depth for task/conversational, no forced-1, default 3, 0 honoured, starting-depth provenance (recorded > legacy > 0), act-path block at configured max, hop reaching exactly the max allowed, act fallback from loop ctx |
| `backend/tests/unit/test_agent_runtime_executor.py` | `_build_guardrail_state` depth seeding/precedence, `_build_agent_type_guardrail_state` configured profile + defaults + legacy fallback, `_run_task_loop` seeds its context from the agent type + recorded job depth |
| `backend/tests/unit/test_guardrail_callback.py` | `>` semantics, seeded `tree_depth` enforced, configured max 5 allows 5 / blocks 6 |
| `backend/tests/unit/test_langchain_tool_wrapper.py` | AR delegation tool pre-dispatch hop guard: at depth == max blocked (blocked result + `delegation_depth_blocked` with target/current/next/max, no A2A dispatch, counters unchanged), below max unchanged, max 0 blocks the root's first hop, no state keeps legacy behaviour |
| `backend/tests/unit/test_agent_schemas.py` | REST create contract accepts 0/1/32/33/64/1000, rejects negatives, other bounds unchanged; REST update contract (`AgentTypeUpdate`) accepts non-negatives, rejects negatives, and is unaffected when the field is omitted |
| `backend/tests/unit/test_delegation_depth_status_api.py` | internal payload persisted depth (required int), status max for two agent types, platform-default fallback, unchanged response shape, direct-child intervention scope |
| `backend/tests/integration/test_management_tool_full_field_parity.py` | assistant-managed create/update depth 64/1000, negative structured error, REST↔management parity for −1/0/1/32/33/64/10000 |
| `backend/tests/integration/test_agent_type_rest_create_guardrails.py` | REST create persists submitted depth 64 (read back from the row); REST update accepts 1000, rejects −1, leaves the stored value intact |

### Frontend (Vitest)
| Suite | Covers |
|---|---|
| `frontend/src/__tests__/delegationPeek.test.ts` | allow-list, canonical/legacy/sanitized delegation tool names, delegation tool responses, lifecycle types, no mutation |
| `frontend/src/__tests__/WorkingStepsPanel.test.tsx` | peek hides child's onward delegation, keeps child activity, child log fetched raw + drill-in wired |
| `frontend/src/__tests__/delegationDepthInputs.test.tsx` | Agent Type form + Agent Properties panel accept 40, keep `min=0`, no `max`; other guardrail limits unchanged |
| `frontend/src/__tests__/agentTypeToDraftComposition.test.ts` | draft composition carries 40 unchanged |
| `frontend/src/__tests__/LogPresenter.test.ts` | displayed max delegation depth comes from logged values (3 vs 9) |

### E2E (Playwright)
| Suite | Covers |
|---|---|
| `e2e/tests/delegation-depth-scoping.spec.ts` | mocked: create dialog + properties panel submit 40 unchanged, no `max`/cap advertised, parent log + peek exclude the child's own delegation, drill-in opens the unfiltered child log, depth indicator shows 3 vs 7 |
| `e2e/tests/delegation-depth-scoping.real-backend.spec.ts` | live: REST create persists depth 64, update to 1000, negative rejected, stored value intact (skips cleanly when the stack/tenant provisioning is unavailable) |

### Run results (tester verification, 2026-11-21)
- `pytest tests/unit` → **1614 passed, 11 skipped, 0 failed**.
- `pytest tests/api` → **232 passed, 68 skipped, 0 failed**.
- Depth-related integration suites (`test_agent_type_rest_create_guardrails`,
  `test_management_tool_full_field_parity`, `test_data_clients`, `test_a2a_tenant_delegation`,
  `test_agent_execution_logs`) → **69 passed, 2 skipped, 0 failed**.
- `npx vitest run` (full frontend, JSON reporter) → **2168 passed, 0 failed** (18 skipped).
- `npx playwright test tests/delegation-depth-scoping.spec.ts` (preview build) → **5 passed**.
- `npx playwright test tests/delegation-depth-scoping.real-backend.spec.ts` (restarted local stack)
  → **1 passed**. Existing delegation/log/management E2E specs → all passed.

### Defects fixed during verification
1. `POST /agents/types` validated guardrails but never copied them onto the new `AgentType`, so a
   create with depth 64 stored the column default (3). Fixed in `backend/app/api/v1/agents.py`.
2. `AgentTypeUpdate` had no guardrail validation, so `PUT /agents/types/{id}` accepted and persisted
   a negative depth. Added a non-negative floor validator in `backend/app/schemas/agents.py`.
3. The Agent Runtime LangChain delegation tool wrapper (`_make_delegation_tool`) dispatched the A2A
   request before advancing `delegation_depth`, so a run already at its configured maximum could
   dispatch one over-depth hop that was only stopped when the child started. Added a pre-dispatch hop
   guard: at `current + 1 > max` it logs `delegation_depth_blocked` (target/current/next/max), returns
   `{"blocked": true, "reason": ...}`, and does not dispatch or move counters. Covered by
   `backend/tests/unit/test_langchain_tool_wrapper.py`.

### E2E notes
The mocked journeys (create/edit depth > 32, parent/child log scoping + drill-in, 3-vs-7 depth
display) run without Keycloak. The live suite proves REST persistence and negative rejection against
the real stack; it intentionally does not trigger an LLM-backed nested delegation run, because the
canonical E2E environment has no configured model provider. The change adds no migration, so no
`alembic upgrade` is required beyond the current head.

---

## 4. Deferred master-doc updates (architecture change doc §5)

These remain for the update-master stage (not performed here):
- `docs/master/architecture/modules/agent-runtime/architecture.md` — rewrite Delegation Depth Guard.
- `docs/master/architecture/modules/agent-lifecycle.md` — configured guardrail wording.
- `docs/master/architecture/modules/tool-execution.md` — configured-maximum depth check.
- `docs/master/architecture/modules/execution-logs.md` — status/stop-reason + peek wording.
- `docs/master/architecture/system-overview.md`, `.../modules/agent-types.md`, `.../control-center/runtime-monitoring.md`, `.../README.md`.
- Product/operations docs listed in `spec-change.md` (agent-execution, agent-session-logs, agent-gateway,
  sop-management, agent-management, agent-types, a2a-communication, guardrails runbook).
