# Test Plan: Gated Optimization, Explicit Plan Authoring & Self-Healing Plans

**Changes merged:** `separate-optimization-from-execution` (2026-11), plus the one-shot-optimize and model-configuration parts of `optimizer-conversational-agent` (2026-11). Final shipped state.
**Companion plan:** `optimizer-conversation-test-plan.md` (optimization-mode conversation, ask/decide, live-test approval).

## Scope

- The **separate, gated Optimize action** — Run is execution-only; "run with optimization" no longer exists.
- **Explicit-only implementation-plan authoring** from the Plan Preview tab.
- The **workspace authoring model** (`workflow_generation_model_id`) and the **workspace optimizer model** (`optimizer_model_id`), with their System Config surfaces.
- The **`requires_fix` self-healing loop**: fallback → auto-recorded feedback → alert → re-optimize → auto-refresh.

Out of scope: scripting sandbox internals (`sandboxed-scripting-test-plan.md`), script governance UI (`software-3.0-agent-framework-test-plan.md`), the optimization conversation and live-test ledger (`optimizer-conversation-test-plan.md`), the Control Center Assistant (`control-center-assistant-test-plan.md`).

## Test Strategy

| Layer | Location | What it proves |
|---|---|---|
| Backend unit | `backend/tests/`, `backend/tests/unit/` | Authoring/optimizer model resolution and non-rewriting reads; explicit-only generation; gate computation and precedence; `requires_fix` transition and feedback shape; command-run model override; dead-loop guard |
| Backend integration/API | `backend/tests/` | `POST /agents/sessions/optimize` gate enforcement (`412 optimize_gate_unmet`), `optimization-gate` payload, `regenerate-plan` blocked path, no generation on create/update, internal agent-context override, `GET/PUT /agents/model-configs/{workflow-generation,optimizer-model}` |
| Frontend component | `frontend/src/__tests__/` | Gated Optimize action (panel + list), explicit Generate plan states, System Config guidance/reminders (both models), `requires_fix` alert + source badges + re-optimize |
| E2E (mocked first) | `e2e/tests/` | Gate blocks then enables; requires-fix → re-optimize; explicit-only generation; authoring-model reminder; conversational-agent exclusion; optimizer-model stale/unset |
| E2E (real backend) | `e2e/tests/` | `test.describe('Real Backend Integration …')` variants (mandatory for `has_db_changes: true`), failing loudly on an unapplied migration |
| Manual drill | live stack | Optimize against a real agent; restart mid-optimization; re-optimize after a genuine fallback |

Lifecycle focus: plan = create (explicit only) → read (gate/tab) → update (regenerate / re-optimize) → retire (delete-equivalent with re-author verification); model setting = unset → configured → disabled/removed → re-selected.

## Coverage Areas

| Area | What & Why |
|---|---|
| Run vs Optimize separation | `POST /agents/sessions` carries no `optimize` field; a normal run always uses the agent's own system + skill instructions and never injects `__command`. The epic's core: no side-effect optimization. |
| Optimize gate | `can_optimize` = usable authoring model **and** non-conversational agent **and** ≥1 successful execution (a `completed` job counts even with an empty result). `can_generate_plan` = usable authoring model **and** non-conversational (no execution needed). Precedence conversational → authoring model → executions is shared by the gate endpoint, `regenerate-plan` and the optimize trigger. |
| Authoring model (workspace) | One tenant setting (the same one used for Skill/SOP workflow generation) resolved against that tenant's enabled catalogue. Unset → `authoring_model_not_configured`; saved-but-not-listed → `authoring_model_not_enabled` with the stale id still echoed. **No fallback** to `AgentType.model_id`, a first-available config or a default; reads never rewrite the stored row. |
| Optimizer model (workspace) | `optimizer_model_id`: explicit-and-enabled → `source="optimizer"`; unset → the authoring model (`source="authoring"`); explicit-but-unusable → `optimizer_model_not_enabled`; unset-with-unusable-authoring → `optimizer_model_not_configured`. Never the agent's runtime model; the internal context fails closed with `412 optimizer_model_unavailable`. |
| Model-config API & System Config | `GET` returns tenant-scoped enabled options + raw selection + effective id/source/reason; `PUT` writes only the session tenant, `null` clears to inherit, `422` for a not-enabled id; the UI explains workspace scope, "not a runtime model", inherit-from-authoring, no-substitution, shows unset/stale reminders and blocks Save until a stale value is re-selected. Gate, availability, internal `412` and WS `chat_error` share one reason vocabulary. |
| Command-run model override | The internal agent-context endpoint returns authoring-model identifiers for `__command` sessions and `AgentType.model_id` for normal/conversational/auto-compile/turn-resume runs; resolution failure fails closed rather than silently running on the agent model. |
| Explicit-only generation | Creating, saving or updating an agent type never authors a plan (no background task, no spend). `POST /agents/types/{id}/regenerate-plan` is the only authoring path; a failed attempt records `generation_status`/`generation_error` while preserving the last successful steps/topology/hash/`generated_at`; a blocked attempt writes no plan and retires no serving version. |
| Plan Preview UX | Empty state before the first generation; blocked-with-reason + System Config shortcut when the model is unusable; stale banner that only *offers* regeneration; auto-refresh after an explicit generation; hidden for conversational agents. |
| Conversational agents (one-shot surface) | The gated Optimize action and plan generation are absent for `input_type=conversation`; direct API calls are rejected with `reason_code: conversational_agent`; an existing plan is retained for reference but never served. (The optimization *conversation* is available to conversational agents — different surface, see the companion plan.) |
| `requires_fix` self-healing | A fallback attributed to an optimized artifact sets the plan `requires_fix` and appends one `execution_derived` feedback entry (with `source_execution_id`) in the same transaction; a `requires_fix` plan is never re-served (serving predicate stays `status == ready`); authoring can only produce `ready` / `needs_feedback` / `failed`. Repeated fallbacks stay idempotent; a retired plan is never marked. |
| Feedback sources | Manual feedback is tagged `source: "manual"` (missing `source` reads as manual); execution-derived entries are badged distinctly; all entries are carried verbatim into the next regeneration. |
| Alert & re-optimize | The Optimized Plan tab renders the requires-fix alert with the auto-recorded feedback; Re-optimize from the alert carries the prior plan + accumulation and the tab refreshes without a reload. |
| Optimization execution | A dedicated command execution consumes optimization instructions + current plan + agent info + the latest successful **normal** execution's bounded text log (default 100 / max 500 lines; command and current runs excluded); the goal is correct script syntax and proper tool invocation, not identical output; the dead-loop guard stops after three identical consecutive tool calls. |
| Migration | `requires_fix` added additively to `optimized_plan_status_enum` (no `sa.Enum` re-create); documented no-op downgrade; the live-test schema belongs to the companion plan. |
| Tenancy & segregation | Settings, plans, feedback and alerts resolve from the session tenant (root when multi-tenancy is off); CC writes only, AR executes, CH injects identity; the context response carries model identifiers only. |
| No regression | One-shot Optimize outcomes unchanged; manual feedback still steers refinement; retire and its "nothing to retire" state unchanged; script-first dispatch/fallback and assistant conversation unchanged. |

## Critical Scenarios

### Run vs Optimize
- WHEN the Run/launch surface is opened THEN there is no "run with optimization" option or opt-in dialog, and a launched run submits no `optimize` field.
- WHEN a normal run executes THEN its prompt is the agent's own system + skill instructions and is never replaced by an optimization mission.

### Gates
- WHEN an agent has zero successful executions THEN `can_optimize` is false with `reason_code: no_successful_execution` and Optimize is disabled with that explanation while Run stays available.
- WHEN a completed execution exists and the authoring model is usable THEN `can_optimize: true` and the control enables on refetch without a page reload.
- WHEN the authoring model is unset / no longer enabled THEN `can_generate_plan: false` with the matching `reason_code` (stale id still echoed for the not-enabled case) and both generation and Optimize are blocked with a System Config path.
- WHEN the agent is conversational THEN the gate reports `reason_code: conversational_agent` and no plan/one-shot-optimize affordance renders.
- WHEN a blocked action is called directly THEN the server re-checks and returns `412` with the structured reason, creates no session, writes no plan and retires no serving version.

### Explicit plan authoring
- WHEN an agent type is created or saved THEN no plan is authored, no background task is scheduled and the previous plan/`generated_at` are untouched.
- WHEN the operator clicks Generate plan THEN exactly one authoring request is sent and the plan renders in place (the action then reads Regenerate plan) with no page reload.
- WHEN an explicit generation fails THEN the reason is shown while the last successful plan stays visible.
- WHEN the agent configuration changed since generation THEN the plan is flagged as possibly out of date and only offers regeneration.
- WHEN the launch dialog is opened THEN it offers no plan-generation action, only an informational stale/optimized-plan note pointing at Plan Preview.

### Model configuration
- WHEN options are resolved THEN only the session tenant's enabled models are offered; a `422` for a not-enabled id leaves the previous selection unchanged; a smaller enabled model saves (the larger-model recommendation is advisory).
- WHEN the saved value is no longer available THEN it stays visible as a disabled option, the reminder asks for re-selection and Save is blocked — never auto-cleared or silently substituted.
- WHEN `null` is submitted to the optimizer model THEN the setting row is cleared and the effective model falls back to the authoring model.
- WHEN multi-tenancy is enabled THEN only the session tenant's settings and catalogue are consulted (identical-name cross-tenant probes fail).
- WHEN a command run starts THEN the internal context returns the authoring model identifiers and no credentials/tokens; a resolution failure between trigger and execution fails closed (`412`).

### requires_fix self-healing
- WHEN a later execution's optimized script fails THEN the run falls back to the LLM path and still completes, and the attributed plan becomes `requires_fix` with one `execution_derived` feedback entry.
- WHEN a plan is `requires_fix` THEN it is never re-served, so subsequent runs stay on the LLM path.
- WHEN the operator next opens the Optimized Plan tab THEN the alert and the auto-recorded feedback (badged vs manual) render without a manual reload.
- WHEN Re-optimize is triggered from the alert THEN the new run receives the prior plan + accumulated feedback and the tab refreshes to the new state.
- WHEN manual feedback is added at any time THEN it is tagged `manual` and included in the next refinement.

### Migration & invariants
- WHEN the migration is applied THEN `alembic current` is at head, `requires_fix` exists in the enum, and pre-existing rows round-trip unchanged.
- WHEN Control Center starts twice THEN no optimizer/assistant-support rows beyond the documented seeds are created.

## Edge Cases & Risks

| Risk | Mitigation / coverage |
|---|---|
| Authoring/optimizer model removed mid-life | Gate flips to not-enabled/not-configured with the stale value visible; a command run fails closed (`412`) instead of silently using the agent model |
| No enabled models in the catalogue | Not-configured state, empty options, `422` for an arbitrary id, generation/optimization blocked rather than falling back |
| Conversational agent converted to/from typed | Prior plan retained for reference only while conversational; controls restored on conversion back (Optimize still needs an execution) |
| Legacy launch body with `optimize: true` | Runs as a normal execution; legacy plans stay readable and are never auto-re-authored |
| Gate race (job completes or model configured between read and trigger) | Server re-checks current DB state; a stale UI snapshot never creates a session |
| Empty or drifting tool results | A completed-but-empty run still satisfies the gate; the optimizer verifies syntax + tool invocation rather than output equality and never loops for an identical result |
| Dead loop re-reading a terminal plan | Guard stops after three identical consecutive tool calls with a canonical guardrail reason |
| Multiple fallbacks on one plan / retired plan | Marking stays idempotent; a retired plan is never marked, and a `requires_fix` plan can be retired or regenerated without leaving stale alerts |
| Concurrent optimize + normal run | One active non-retired plan; generation upsert retires the prior plan atomically |
| Unapplied migration | Real-backend E2E fails loudly on `5xx` from the affected endpoints rather than skipping |
| i18n drift | Every new authoring/optimizer-model string resolves from `en.json` with required params declared |

## Acceptance Criteria

- Run and Optimize are distinct actions; a normal run never performs optimization and submits no `optimize` field.
- Optimize requires a usable authoring model and ≥1 successful execution; otherwise it is disabled with the specific reason and the server rejects a direct call with `412`.
- Plans are authored only on explicit request; saving an agent generates nothing and preserves the last successful plan.
- Plan generation and optimization use the workspace authoring model with no fallback; the agent's runtime model is never used for authoring.
- Both model settings are workspace-scoped, catalogue-constrained, single-setting, and show an unset/stale reminder that clears on a valid save.
- Conversational agents are excluded from one-shot plan generation and optimization.
- A fallback caused by an optimized artifact marks it `requires_fix`, records execution-derived feedback, alerts the operator, is never re-served, and can be re-optimized with the prior plan + feedback (auto-refresh, no reload).
- Manual feedback still works and is tagged `manual`.
- No sensitive material (tokens, credentials, decrypted secrets) appears in context responses, plan/feedback payloads or logs.

## Test File References

All paths verified present in the workspace (2026-11).

### Backend — `backend/tests/`

| File | Covers |
|---|---|
| `test_optimized_plan_requires_fix_migration.py` | `requires_fix` member + round-trip; additive DDL; no-op downgrade; head ancestry |
| `unit/services/test_workflow_generation_settings.py` | Authoring-model state matrix, reason codes, tenant scoping, read-vs-write, no fallback |
| `unit/services/test_plan_generation_service.py` | Authoring-model-driven completion; agent/first-available fallbacks gone; failure preserves last plan; explicit-only |
| `integration/api/test_agent_types_plan.py` | `regenerate-plan` `412` paths, no plan write, no serving retirement; create/update never generate |
| `test_optimization_gate.py` | Gate payload, compound precedence, trigger `412` per reason code, blocked→enabled transition |
| `test_internal_agent_context_authoring_model.py` | Command-run authoring identifiers vs normal-run agent model; fail-closed `412`; identifiers only |
| `test_tenant_settings_workflow_generation.py` | Tenant-scoped GET/PUT contract (authoring model) |
| `test_optimizer_model_config_api.py` | `GET/PUT /agents/model-configs/optimizer-model`, raw vs effective, `422`, `null` clears, stale visible |
| `unit/services/test_optimizer_model_settings.py` | Optimizer-model resolution/fallback matrix, no rewrite on read, tenant scoping, CC-only import boundary |
| `test_optimized_plan.py` | Mission wording, `mark_requires_fix`, feedback `source`, `requires_fix` never served, non-ready promotes nothing, retire |
| `test_script_registry_service.py` | Fallback attribution → `requires_fix` + execution-derived feedback; idempotence; retired/base-plan exclusion |
| `test_internal_scripts_api.py` | `POST /internal/scripts/fallbacks` reaction end-to-end; un-attributed fallback leaves the plan alone |
| `test_execution_log_bounds.py` | Reference-run selection, chronological bounded log, explicit `session_id`, invalid limit |
| `test_dispatcher_script_context.py` | Session `input_data` bound as sandbox `initial_context` on both dispatch paths |
| `test_sandbox_engine.py` | MCP envelope unwrap, per-call tool records, structured `validation_error` for missing input keys |
| `unit/test_guardrail_callback.py` | Repeat-identical-tool-call guard (off by default, third call stops, resets on change) |
| `test_command_execution.py` | Command tool wiring, mission goal wording, bounded `needs_feedback` stop with `error` |
| `test_script_first_dispatcher.py` | Unconditional LLM fallback, command bypass, serving freshness |

### Frontend — `frontend/src/__tests__/`

| File | Covers |
|---|---|
| `SystemConfigPage.authoring-model.test.tsx` | Three uses, workspace scope, advisory recommendation, unset/stale reminder, single save path, `422` |
| `SystemConfigPage.optimizer-model.test.tsx` | Workspace scope, inherit-from-authoring, catalogue-only, stale + blocked Save, `null` clears |
| `AgentTypeDetailsDialog.test.tsx` | Generate plan (empty/blocked/stale/success), query invalidation, `412` keeps last plan, conversational exclusion, gated footer Optimize |
| `AgentOptimizedPlanTab.test.tsx` | `requires_fix` chip + alert + source badges, re-optimize from alert/header, `needs_feedback` state, retire |
| `AgentSessionLaunchDialog.test.tsx` | Execution-only Run: no opt-in dialog, no `optimize` field, no `regenerate-plan`, informational stale note |
| `AgentManagementPanelPage.test.tsx` | Gate-aware Optimize beside Run (hidden/disabled/enabled), launches the optimization run |
| `AgentManagementPage.test.tsx` | Row-level gated Optimize + dedicated dialog |
| `useOptimizationGate.optimizerModel.test.tsx` | Extended gate payload, legacy degradation, reason localization |
| `useOptimizerModelConfig.test.tsx` | Tenant-scoped read/save, clear-to-inherit, `422`, stale/blocked helpers |

> `frontend/src/__tests__/AgentOptimizeDialog.test.tsx` is named by the change plan but **does not exist**; its trigger/`412`/error-copy coverage is carried by `agent-optimize-gate.spec.ts` and the panel/list dialog suites.

### E2E — `e2e/tests/`

| File | Covers |
|---|---|
| `agent-optimize-gate.spec.ts` | Gate blocks then enables, model-not-configured/not-enabled copy, conversational exclusion, dedicated launch, `412` re-check |
| `agent-optimize-requires-fix.spec.ts` | `ready` plan → fallback marks `requires_fix` → alert + auto-recorded feedback → re-optimize refreshes the tab |
| `agent-plan-mode.spec.ts` | Explicit-only generation, blocked state + System Config shortcut, conversational exclusion, `412` keeps last plan; real-backend variant asserts no plan on create |
| `agent-plan-generation.spec.ts` | Authoring-model System Config section (three uses, scope, advisory, unset reminder, stale selection, single save) |
| `agent-optimizer-model-config.spec.ts` | Optimizer-model section, stale value + blocked Save, `null` clear, unset entry/chat block |
| `agent-optimizer.real-backend.spec.ts` | No mocks: config reads + fail-closed paths (migration signal) |
| `agent-management-panel.spec.ts` | Panel CRUD unaffected by the added gated Optimize action |
| `agent-type-scripts-tab.spec.ts` | Requires-fix alert surface from the Optimized Plan tab (rest of the suite targets a removed Scripts tab) |

## Superseded / Removed Behaviour (do not test)

- "Run with optimization" opt-in and its dialog; the `optimize` launch field.
- Plan auto-generation on agent create/edit and the `PlanPreviewModal`-on-save journey.
- A seeded optimizer agent type / identity / role / permission bridge.
- Fallback to the agent's runtime model or a first-available config for authoring.

## Related Test Plans

- [Optimizer Conversation](optimizer-conversation-test-plan.md) — optimization-mode conversation, ask/decide, live-test approval, audit.
- [Sandboxed Scripting](sandboxed-scripting-test-plan.md) — sandbox, replay client, dispatch/fallback internals.
- [Software 3.0 Agent Framework](software-3.0-agent-framework-test-plan.md) — script lifecycle and governance UI.
- [Agents](agents-test-plan.md) / [Agents UI](agents-ui-test-plan.md) — Optimized Plan tab and dialog surfaces.
