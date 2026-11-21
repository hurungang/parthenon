# Test Plan: Separate Optimization from Execution

Owner: tester
Change: `docs/changes/separate-optimization-from-execution/` — split "Run with optimization" into a dedicated, preconditioned Optimize action with a self-healing human-in-the-loop (`requires_fix` plan status + auto-appended execution-derived feedback). `has_db_changes: true` (one enum value: `requires_fix` added to `optimized_plan_status_enum`).

Refinement covered by this plan: plan authoring is now performed by the **tenant-level authoring model** (`workflow_generation_model_id`, the same setting used for Skill/SOP workflow generation) with **no fallback**, generation happens **only on explicit request**, both plan generation and optimization are **gated on a usable authoring model and a non-conversational agent**, the optimization run **executes on the authoring model**, and System Config **explains the three uses, recommends a larger model (advisory), reminds when unset, and stays tenant-scoped**.

## Test Strategy

The change spans three backend surfaces plus the frontend launch surface, the Plan Preview, the Optimized Plan tab, and System Config. Each layer validates a different slice of the same lifecycles (authoring-model resolution, explicit plan authoring, optimize-authoring, and the fallback reaction):

1. **Backend unit tests** (`backend/tests/`) — the primary safety net. Fast, deterministic coverage against the in-memory SQLite/ASGI app of:
   - the `OptimizedPlanStatus` enum + Alembic migration (`requires_fix` present, reversible downgrade),
   - the **authoring-model resolver** (tenant-scoped read of `workflow_generation_model_id`, enabled-model resolution, derived "not configured" vs "not enabled", never raising for gates / raising for authoring),
   - **plan generation** authoring through the authoring model, with the first-available `ModelConfig` fallback and the `AgentType.model_id` path removed,
   - the reworded `optimize-and-verify` command mission (syntax + tool-invocation verification, high-confidence stop rule, no identical-result matching),
   - the optimization system tools (`generate_optimized_plan` emits `needs_feedback` with `error`, never `requires_fix`; `get_execution_log` lists recent normal executions, selects the latest successful normal one, and returns its bounded text log; feedback entries carry `source`),
   - the command-run dead-loop guard (three consecutive identical tool calls stop the run),
   - `ScriptRegistryService.record_fallback` resolving `script_version_id → ScriptDefinition.source_optimized_plan_id → plan` and invoking `mark_requires_fix` + execution-derived feedback in one transaction,
   - the **gate computation** (`can_generate_plan`, `can_optimize`, model state, conversational flag, compound precedence, reason codes).

2. **Backend integration/API tests** (`backend/tests/` API-level suites, `backend/tests/integration/api/`) — exercise the REST surface end-to-end over the real app with an in-memory DB: the removed `optimize` launch field, the new `POST /agents/sessions/optimize` trigger (compound gate enforcement → `412 optimize_gate_unmet` with `reason_code`, command dispatch), `GET /agents/types/{id}/optimization-gate` (extended payload), `POST /agents/types/{id}/regenerate-plan` (blocked → `412 plan_generation_unavailable`, no plan write, no serving-version retirement), the **absence of plan generation on create/update**, the internal `GET /internal/data/agent-types/{id}/context` **command-run authoring-model override** (and normal-run pass-through), the extended `_optimized_plan_payload` (status `requires_fix`, feedback `source`), and the internal `POST /api/v1/internal/scripts/fallbacks` requires-fix reaction. mTLS/internal-tenant fail-closed invariants are asserted as regression.

3. **Frontend component tests** (`frontend/src/__tests__/`) — Vitest + Testing Library coverage of: Run vs Optimize separation (Run is execution-only, no opt-in optimization dialog, no `optimize` payload field, no plan-generation action), the Optimize gate state (disabled/hidden for conversational agents, disabled with reason for missing authoring model or missing execution, enabled once all preconditions hold), the **Plan Preview explicit Generate plan UX** (empty state, blocked-with-reason + System Config shortcut, stale-not-auto-regenerated, refresh after generation), **System Config authoring-model guidance** (three uses, advisory larger-model recommendation, unset/disabled reminder, tenant-scoped options/selection), the requires-fix alert + auto-recorded feedback + re-optimize on the Optimized Plan tab, feedback `source` badge, and auto-refresh after re-optimization. i18n regression: removed `runWithOptimization`/`skipOptimization`/`optimizePrompt*` strings are no longer referenced, and the new authoring-model / generate-plan strings resolve from `en.json`.

4. **E2E tests** (`e2e/tests/`) — Playwright journeys over a mocked stack (`page.route()`, no live backend needed) for the user-visible contract: the Optimize action appears only after a successful execution and a usable authoring model, is absent for conversational agents, triggers a distinct execution, surfaces the requires-fix alert, and re-optimization carries prior plan + feedback. Saving an agent generates nothing; Plan Preview shows the empty state and only generates on explicit request; the model-missing blocked state points at System Config; conversational agents expose no plan/optimize affordances; and System Config explains the three uses with the advisory recommendation and unset/stale reminder. The requires-fix marking and the authoring-model override are server-side behaviours covered by the backend/API layers; the E2E layer asserts their observable consequences (blocked/enabled controls, reminders, alerts, refreshed views, no reload).

Testing is **lifecycle-focused** (full CRUD-equivalent): author plan = create (explicit only), gate/plan tab = read, re-optimize = update, retire = delete with re-author verification, plus the requires-fix transition as the self-healing state change. Authoring-model state is exercised across its full lifecycle too: unset → configured → disabled/removed → re-selected. No test code lives in this plan — implementation detail is in the referenced test files.

## Coverage Areas

| Area | What & Why |
|---|---|
| Enum + migration | `requires_fix` added to `optimized_plan_status_enum` via additive DDL (`ADD VALUE IF NOT EXISTS`, `create_type=False`-equivalent: no `sa.Enum`/`CREATE TYPE`); `downgrade()` is a documented no-op (PostgreSQL cannot drop one enum value without rewriting the type); status survives a model round-trip. DB-schema correctness — migration is the only DDL change. |
| **Authoring-model resolution (tenant)** | `get_authoring_model_state` / `require_authoring_model` resolve the session tenant's `workflow_generation_model_id` (root tenant when multi-tenancy is off) against that tenant's enabled model catalogue. Unset (blank/absent) and disabled (id no longer listed) are derived at read time with distinct `reason_code`s; the stored setting is never rewritten. Single source of truth for Skill/SOP workflow generation, implementation-plan generation, and optimization-plan generation. |
| **No-fallback guarantee** | Plan authoring never uses `AgentType.model_id`, never picks the first available `ModelConfig`, and never substitutes a default model. An unusable authoring model produces a structured "not configured / re-select" error and **no write** — plan quality is never silently degraded. |
| **Explicit-only generation** | Agent create and update schedule no plan generation; `POST /agents/types/{id}/regenerate-plan` is the only authoring path, and the optimized plan is produced only by an explicit Optimize trigger. A failed attempt records `generation_status`/`generation_error` while preserving the last successful steps/topology/hash/`generated_at`. |
| **Plan/optimize gates** | `can_generate_plan` = authoring model usable **and** non-conversational agent; `can_optimize` = `can_generate_plan` **and** ≥1 successful execution. Compound precedence (conversational → authoring model → executions) is shared by the gate endpoint, `regenerate-plan`, and the optimize trigger, so UI and server never disagree; the server always re-checks. |
| **Conversational agents excluded** | Conversational agents (`input_type == conversation`) never get plan generation or optimization: controls hidden, direct API calls rejected with `reason_code: conversational_agent`, no background generation through any surface, and existing plans retained for reference but not used. |
| **Command-run authoring model** | The internal agent-context endpoint returns the tenant authoring model (`model_id` + resolved `model_config_id`, identifiers only) for `__command` sessions and keeps `AgentType.model_id` for normal/conversational/auto-compile/turn-resume runs. Resolution failure fails closed with `412 authoring_model_unavailable` — the run never silently falls back to the agent model. |
| **System Config authoring model** | One selector per workspace whose copy explains the three uses, states the workspace scope, gives the advisory "choose a larger model" recommendation, and shows a visible reminder when unset or when the saved selection is no longer in the catalogue ("re-select"). Options and selection come from the session tenant's catalogue; a smaller enabled model still saves. |
| **Explicit Generate-plan UX** | Plan Preview shows an empty state before the first generation, a blocked-with-reason state plus System Config shortcut when the authoring model is unusable, a stale banner (never auto-regenerated) when the agent config changed, and refreshes the plan automatically after an explicit generation. Hidden for conversational agents. |
| Successful-execution gate | `can_optimize` derived from `AgentJob.status == completed` count; `reason` populated when false; gate re-checked server-side by the optimize trigger. The precondition that keeps the optimizer grounded in a real reference run. |
| Run vs Optimize separation | `POST /agents/sessions` drops `optimize`; a normal run always uses the agent's own system + skill instructions, never injects `__command`. The core of the epic: no side-effect optimization. |
| Optimize trigger | New `POST /agents/sessions/optimize` enforces the compound gate, runs quota/recursion pre-flight, injects `__command: optimize-and-verify` + mission, dispatches CC→CH→AR as a command execution, returns `202`. |
| Optimization execution (command side-run) | Uses optimization instructions + current plan + agent info + the latest successful normal execution's text log; authoring goal = correct script syntax + proper tool invocation (not identical result); persists `ready` or stops at `needs_feedback` with no dead loop. |
| `get_execution_log` reference selection | Lists recent normal executions (newest first), excludes the current optimization session and other command runs, selects the latest completed normal execution (or explicit `session_id`), and returns its chronological text log bounded (default 100, max 500). |
| Dead-loop guard | Command runs stop after three consecutive identical tool calls (e.g. re-reading a terminal plan); the stop is a canonical guardrail reason. |
| Fallback → `requires_fix` | `record_fallback` attributes the fallback to `source_optimized_plan_id`, sets the plan `requires_fix`, and appends an `execution_derived` feedback entry in one transaction; a `requires_fix` plan is never re-served (serving predicate stays `status == ready`). |
| Feedback shape | Manual feedback tagged `source: "manual"`; execution-derived tagged `source: "execution_derived"` + `source_execution_id` (and optional `source_fallback_event_id`); missing `source` treated as `manual`; all entries carried verbatim into regeneration context. |
| Alert + re-optimize | Optimized Plan tab renders the requires-fix alert + auto-recorded feedback; re-optimize triggers a new optimize run carrying prior plan + full feedback; tab auto-refreshes without manual reload. |
| Retire / status semantics | `needs_feedback` (authoring) vs `requires_fix` (later fallback) distinction documented and enforced; `requires_fix` never authored by `generate_optimized_plan`; retirement/regeneration marks old plan `retired`. |
| Manual feedback regression | Add-feedback still works and is tagged `source: "manual"`; steer re-optimization unchanged. |
| Tenancy + top-priority rules | Plans, feedback, alerts, and the authoring-model selection are tenant-owned/scoped; CC-only DB writes; AR executes sandbox only; agents never receive sensitive data (context response carries model identifiers only). Regression assertions. |

## Critical Scenarios

### Authoring model: tenant-scoped resolution, no fallback

- WHEN a workspace has `workflow_generation_model_id` set to a model enabled in that workspace's catalogue THEN implementation-plan generation and optimization-plan generation both author with that model (the same setting used for Skill/SOP workflow generation), and the agent type's `model_id` is never used for authoring.
- WHEN the workspace administrator saves a different authoring model THEN all subsequent plan generations in that workspace use the new model immediately, with no second setting to keep in sync.
- WHEN the setting is unset or blank THEN plan generation and optimization report "not configured" (`authoring_model_not_configured`), nothing is generated or written, and no fallback model (agent model, first available config, or default) is used.
- WHEN the stored model id is no longer present in the workspace's enabled model catalogue THEN the derived state is "not enabled" (`authoring_model_not_enabled`), the user is asked to re-select a valid model, nothing is generated, and the stored setting value is left untouched (so the stale value stays visible in the UI).
- WHEN a generation proceeds THEN the completion call receives the authoring model id and its resolved binding context (provider type, base URL, credentials path) rather than anything derived from the agent type; log/output extraction uses the authoring provider type.
- WHEN the request is served with multi-tenancy enabled THEN only the session tenant's setting and model catalogue are consulted; a selection in another tenant never influences this workspace.
- WHEN multi-tenancy is disabled THEN the root tenant's setting and catalogue are the sole source, and no other tenant's stored selection is read.

### Explicit-only plan generation (no side effects from create/save)

- WHEN an agent type is created THEN no implementation plan is authored, no background generation task is scheduled, and no authoring model call is made.
- WHEN an agent type is updated or saved THEN the same applies: nothing is generated, the last successful plan and its `generated_at` are untouched, and stale plans are not silently replaced.
- WHEN an agent is saved while an optimized plan exists THEN the optimized plan is not regenerated either — optimization remains an explicit action.
- WHEN an operator explicitly requests generation via `POST /agents/types/{id}/regenerate-plan` THEN exactly one generation runs (serving versions retired, authoring call made) and the refreshed plan is returned.
- WHEN an explicit generation fails (model error/timeout) THEN `generation_status: failed` plus `generation_error` are recorded and surfaced, while the previous `plan_steps`, `topology`, `agent_config_hash`, and `generated_at` are preserved — a failure never discards the last successful plan.
- WHEN generation is blocked by a precondition THEN no plan row is written **and** compiled serving versions are not retired (no destructive step before the precondition check).
- WHEN an explicit generation completes THEN the Plan Preview (and any dependent script view) refreshes automatically to show the new plan without a manual page reload.
- WHEN the agent configuration has changed since the last generation THEN the plan is flagged as possibly out of date with a regeneration offer, and no auto-generation occurs.

### Generate-plan gate: authoring model + non-conversational

- WHEN the agent is non-conversational and the authoring model is usable THEN `can_generate_plan` is `true` and the Generate plan control is enabled — a successful execution is **not** required for base-plan generation.
- WHEN the authoring model is unset THEN the gate reports `can_generate_plan: false`, `workflow_model_configured: false`, `reason_code: authoring_model_not_configured`, and the UI blocks generation with that reason plus a System Config shortcut.
- WHEN the saved authoring model is no longer enabled THEN the gate reports `can_generate_plan: false`, `workflow_model_configured: false`, `workflow_model_id` still echoes the stale id, `reason_code: authoring_model_not_enabled`, and the UI explains the model is no longer available and must be re-selected.
- WHEN the agent is conversational THEN the gate reports `can_generate_plan: false`, `is_conversational: true`, `reason_code: conversational_agent`, and generation is not offered at all.
- WHEN `regenerate-plan` is called directly while blocked THEN the server returns `412` with `detail: { error: "plan_generation_unavailable", reason_code, reason }`, writes no plan, retires no serving versions, and never calls a fallback model.
- WHEN all preconditions hold THEN `reason` and `reason_code` are `null` in the gate payload.

### Conversational agents: no plan generation, no optimization

- WHEN an agent type's `input_type` is conversation THEN the Plan Preview generation control is hidden, the Optimize action renders nothing, and no plan/optimize affordance appears on any launch surface.
- WHEN `POST /agents/sessions/optimize` or `POST /agents/types/{id}/regenerate-plan` is called directly for a conversational agent THEN the server rejects with `412` and `reason_code: conversational_agent`; no execution is dispatched and no plan is written.
- WHEN a conversational agent is created or saved THEN no plan generation is scheduled anywhere (no background task, no indirect surface).
- WHEN a conversational agent runs THEN its own instructions are used exactly as before, it is never compiled into an optimized plan, and no plan is served to it.
- WHEN an agent that already had a plan is converted to conversational THEN the prior plan is retained for reference only: it is not served, not regenerated, and not used for optimization while the agent remains conversational.
- WHEN a conversational agent is converted back to a non-conversational type and a usable authoring model exists THEN the Generate plan and Optimize affordances become available again (subject to the successful-execution precondition for Optimize).

### Optimization executes on the authoring model

- WHEN an optimization command run starts (`input_data["__command"]` present) THEN the internal agent-context response returns the tenant authoring model's `model_id` and its resolved `model_config_id`.
- WHEN a normal run starts (no `__command`; including conversational prepare, auto-compile, and turn resume) THEN the internal agent-context response keeps returning `AgentType.model_id` and the config that enables it.
- WHEN authoring-model resolution fails for a command run (e.g. the config was removed between trigger and execution) THEN the response is `412` with `authoring_model_unavailable` and the run fails closed — it never silently executes on the agent's runtime model.
- WHEN the command run executes THEN the runtime consumes the returned model identifiers for its LLM calls (no runtime-side model selection logic), while guardrails, sandboxing, permissions, and the token/credential injection path remain unchanged.
- WHEN the context response is inspected THEN it carries model identifiers only — no credentials, API keys, or identity tokens.

### Gates: blocks & enables Optimize

- WHEN an agent type has zero recorded successful executions (and otherwise usable preconditions) THEN `GET /agents/types/{id}/optimization-gate` returns `can_optimize: false` with a human-readable `reason` and `reason_code: no_successful_execution`, and the Optimize action is disabled with that explanation.
- WHEN an agent type has one completed execution THEN the gate returns `can_optimize: true` (with `successful_executions` ≥ 1), `can_generate_plan: true`, and the Optimize action is enabled.
- WHEN multiple preconditions are unmet THEN the gate reports the **first** unmet one in the order conversational → authoring model → executions, and the optimize trigger applies the same order.
- WHEN the gate is unmet AND Optimize is triggered directly via the API THEN the server re-checks and rejects with `412` and `detail: { error: "optimize_gate_unmet", reason_code, reason }` — the UI state is not trusted alone, and no session is created.
- WHEN the authoring model is fixed or an execution completes THEN the gate is refetched on mount/focus (execution-count states may poll) and the control enables without a page reload.

### System Config: three uses, advisory recommendation, tenant scope, unset reminder

- WHEN the workspace administrator opens System Config THEN the authoring-model section explains the three uses (Skill/SOP workflow generation, implementation-plan generation, optimization-plan generation) and states that the choice applies to the current workspace.
- WHEN the copy is read THEN it recommends choosing a larger / higher-end model, explains that plan-authoring quality depends on it, and clarifies that agents' runtime models are a separate choice.
- WHEN no authoring model is saved THEN a clearly visible reminder to configure one is shown.
- WHEN the saved selection is no longer in the workspace catalogue THEN the reminder appears with a "no longer available — re-select" indication and the stale value remains visible (as a disabled item); saving a valid model clears the reminder.
- WHEN a smaller enabled model is chosen THEN the save succeeds — the larger-model recommendation is advisory only and never blocks.
- WHEN an id that is not enabled in the tenant catalogue is submitted THEN the save is rejected with `422` and the previous selection is unchanged.
- WHEN options are loaded THEN only the session tenant's model configurations are offered, and the selected value is the tenant's own stored value.
- WHEN tenant A saves a model THEN a request in tenant B still returns tenant B's own options and selection (no root/global leakage), and there is only one Save path for the setting.

### Explicit Generate-plan UX

- WHEN the agent type has no plan THEN Plan Preview shows an empty state ("no plan yet — generate one") with the Generate plan action as the primary affordance.
- WHEN the authoring model is unusable THEN Plan Preview shows a blocked state with the gate `reason` and a System Config shortcut, and the Generate plan action is disabled; nothing is generated.
- WHEN the agent config changed since the last generation THEN Plan Preview shows that the plan may be out of date and offers regeneration, without regenerating automatically.
- WHEN an explicit generation completes THEN the plan view updates automatically (dependent queries invalidated) without a manual page reload.
- WHEN an explicit generation fails THEN the failure reason is shown in the dialog surface and the previous plan remains displayed.
- WHEN the agent is conversational THEN the Generate plan action and stale/empty states are not shown at all.
- WHEN the Run/launch dialog is opened THEN it offers no plan-generation action; it only carries an informational stale-plan / optimized-plan-present note pointing at Plan Preview.

### A completed-but-empty-result run still satisfies the gate

- WHEN a completed execution produced a legitimately empty result (e.g., a booking lookup that found nothing) THEN the gate still counts it as a successful execution (the gate keys off `status == completed`, not result richness), so Optimize remains available with a real reference run.

### Optimize run produces a `ready` plan

- WHEN Optimize is triggered THEN a dedicated optimization execution launches (distinct from any normal run), using the agent's optimization instructions, the current implementation plan, other agent info, and the text log of the latest successful normal execution (the current optimization run is excluded) — the agent's normal system/skill instructions are not mutated.
- WHEN the optimizer authors and verifies scripts with correct syntax and proper tool invocation THEN `generate_optimized_plan` persists `status: ready` (promoting authored script versions to `compiled`), and the Optimized Plan tab shows the fresh `ready` plan.
- WHEN a `ready` plan exists THEN the next execution prefers it (script-first) via `get_fresh_optimized_plan` (serving predicate `status == ready`).

### Optimize run stops at `needs_feedback` instead of looping

- WHEN the optimizer cannot reach high confidence (e.g., tool results differ across calls, or a result is legitimately empty) THEN it stops and calls `generate_optimized_plan` with `status: needs_feedback` (persisting `error`) instead of re-attempting to reproduce an identical result.
- WHEN the optimizer ends at `needs_feedback` THEN the failure reason is persisted in `OptimizedImplementationPlan.error` and rendered in the Optimized Plan tab; there is a clear, bounded end state (no dead loop, no unbounded re-attempts, within `COMMAND_MAX_ITERATIONS` / `COMMAND_TOKEN_BUDGET`).
- WHEN replay verification cannot proceed (no recorded tool data, or the script needs a tool/response the reference run did not record) THEN `execute_script` returns a terminal `status: "needs_user_input"` with `blockers`, the optimizer stops and persists `needs_feedback` with a specific, actionable ask (no retry, no live tool), and the Optimized Plan tab renders "Optimization needs your input" with the blocker + replay-only note + feedback/re-optimize.

### Execution uses the plan, falls back → `requires_fix` + feedback appended

- WHEN a later execution attempts the optimized plan's script and that script fails (execution error / schema mismatch / output validation failure) THEN the dispatcher falls back to the LLM path (unconditional fallback preserved) and the run still completes — never a hard failure solely because a script failed.
- WHEN the fallback is attributed to an optimized-artifact script (`source_optimized_plan_id` set) THEN `record_fallback` sets the source plan to `requires_fix` and appends an `execution_derived` feedback entry (with `source_execution_id` and optional `source_fallback_event_id`) in the same transaction.
- WHEN a plan is `requires_fix` THEN `get_fresh_optimized_plan` (predicate `status == ready`) never re-serves it, so subsequent executions continue on the LLM path — no silent degradation, no silent re-use of a known-bad plan.

### Alert renders

- WHEN the user next opens the agent (or its Optimized Plan tab) after a plan was marked `requires_fix` THEN an alert is shown indicating the plan requires a fix, alongside the auto-recorded execution-derived feedback (badged with its `source`), without a manual page reload.

### Re-optimization carries prior plan + feedback

- WHEN the user triggers optimization again from the requires-fix alert THEN the new optimize run receives the prior plan plus the full accumulated `feedback_comments` as context (the old plan is marked `retired` on regeneration), and the new plan is authored informed by what actually failed — on the authoring model, and only if it is still usable and the agent is non-conversational.
- WHEN a re-optimization completes THEN the Optimized Plan tab refreshes automatically to show the updated plan state without a manual reload.

### Manual feedback still works

- WHEN the user adds feedback to an optimized plan manually THEN the entry is appended with `source: "manual"` (and a missing `source` is treated as `manual` by readers), and it is included verbatim in the next regeneration context.

### Run no longer offers "run with optimization"

- WHEN the user opens the Run/launch surface THEN there is no "Run with optimization" option and no optimization opt-in dialog; a Run submits no `optimize` field and the backend `AgentJobCreate` no longer accepts `optimize`.
- WHEN a normal run is launched THEN its prompt is the agent's own system + skill instructions and is never replaced by an optimization mission (no `__command` injection).

## Edge Cases & Risks

- **Authoring model removed or disabled mid-life**: after a successful setup, the model is disabled/removed from the catalogue (or the config row is deleted). Expect: the gate flips to `workflow_model_configured: false` with `authoring_model_not_enabled`/`authoring_model_not_configured`, the System Config reminder reappears with the stale value visible, generation and optimization are blocked with a re-select message, nothing is written, and no fallback model is chosen. If the removal happens **between** optimize trigger and execution, the command run fails closed with `authoring_model_unavailable` (visible failure, not a silent agent-model run).
- **Multi-tenancy off**: with multi-tenancy disabled the deployment resolves to the root tenant, so the authoring model is the root tenant's `TenantSetting`. Assert generation, gates, and both System Config endpoints read/write the root setting, and that toggling multi-tenancy does not orphan or duplicate the selection.
- **No enabled models in the catalogue**: with zero enabled models no authoring model can be selected. Assert the gate/reminder show the not-configured state, the selector offers no options, an arbitrary model id is rejected (`422`), and generation/optimization remain blocked rather than falling back.
- **Conversational agent conversion**: a typed agent with an existing plan is converted to conversational (and back). Expect the prior plan retained for reference, not served/regenerated/optimized while conversational, controls hidden, and — on conversion back with a usable model — controls restored (Optimize still needs a completed execution).
- **Legacy plans**: plans authored before this change (possibly under the agent's model or under a since-removed authoring model) remain readable. They are served only while `ready`; they are never auto-re-authored; regeneration requires a usable authoring model; a legacy `requires_fix` plan is never served. A legacy launch body containing `optimize: true` still runs as a normal execution.
- **Gate precedence**: conversational outranks authoring model, which outranks execution count — assert the reported `reason_code` is the first unmet precondition and that the optimize trigger rejects with the same code.
- **`workflow_model_id` with `configured: false`**: the id is non-null while the model is not configured, so the UI can render "<id> is no longer available — re-select"; assert the payload shape and that clients do not treat a non-null id as configured.
- **Change during an in-flight generation**: the authoring model is changed while a generation is running — the in-flight call completes with the model resolved at start, and the next generation uses the new selection (no mid-call switching, no partial write).
- **Empty tool result**: an execution whose tool calls returned no rows must (a) still satisfy the gate and (b) not make the optimizer loop to force a non-empty/identical result — assert the mission text and the bounded-stop behavior.
- **Varying tool results across calls**: the optimizer accepts differing results and verifies syntax + tool invocation correctness rather than output equality — assert no re-attempt loop is triggered by result drift.
- **Multiple fallbacks on the same plan**: repeated failures on the same optimized artifact must not duplicate `requires_fix` marking incorrectly or append unbounded feedback; the second fallback while already `requires_fix` stays idempotent (plan remains `requires_fix`, no re-serve, feedback appended but no crash).
- **Retired vs `requires_fix`**: a retired plan must never be marked `requires_fix` by a late-arriving fallback report (attribution resolves only live, non-retired plans); conversely a `requires_fix` plan can later be retired or regenerated without leaving stale alerts.
- **`needs_feedback` vs `requires_fix`**: authoring can only produce `needs_feedback`/`failed`/`ready`, never `requires_fix`; `requires_fix` is set only by the fallback path — assert the authoring tools reject/never emit it.
- **Concurrent optimize + run**: an Optimize in flight while a run consumes an older `ready` plan, or a run falling back while Optimize is regenerating, must not corrupt plan state (one active non-retired plan; generation upsert retires the prior plan atomically).
- **No prior executions**: first-time agent with no completed jobs — gate blocks Optimize while still allowing plan generation; the Optimize trigger endpoint enforces the gate server-side; the UI never offers Optimize.
- **Gate race**: a job transitions to `completed` between gate read and optimize trigger, or the authoring model is configured between them — the trigger must re-check against current DB state, not a stale UI snapshot.
- **Bounded log fetch**: the tool returns only the selected execution's log, chronologically, clamped at max 500 lines (default 100); the current optimization session and command runs are never selected as the reference (no unbounded history fetch).
- **Dead loop**: three consecutive identical tool calls (same tool + args) in a command run stop the run with a guardrail reason instead of re-reading a terminal plan until the timeout.
- **Feedback source backward-compatibility**: existing feedback entries without `source` are treated as `manual` (readers must not fail on missing `source`); the extended payload shape must not break older clients.
- **Polling scope**: the gate hook polls only while `no_successful_execution` is the outstanding blocker; model/conversational states refetch on mount/focus (they need an admin/config change), so no busy polling on a permanently blocked state.
- **Migration reversibility + enum safety**: the additive `ADD VALUE IF NOT EXISTS` is idempotent and safe to re-run; `downgrade()` is a documented no-op (PostgreSQL cannot remove a single enum value without recreating the type, and the value is inert when unused); `create_type=False`-style model-import ownership avoids duplicate-type errors. Downgrade behaviour is asserted as an explicit no-op, not as a value removal.
- **Tenancy isolation**: with multi-tenancy enabled, gates, plans, feedback, alerts, and the authoring-model selection are scoped to the resolved tenant; cross-tenant fallback attribution never marks another tenant's plan, and cross-tenant model options never appear.
- **Top-priority rule regressions**: the fallback→requires-fix write and authoring-model reads are CC-only; AR never writes the DB directly; the sandbox remains AR-only; no identity token/credential reaches the optimizer's log slice, feedback content, or the agent-context model response.

## Acceptance Criteria Checklist

Mapping to PRD acceptance criteria:

**Separation & Precondition**

- [ ] Launch surface exposes a distinct Optimize action separate from Run; running never performs optimization → Run vs Optimize separation scenario; frontend + backend launch tests
- [ ] Optimize available only after ≥1 successful execution, otherwise disabled/hidden with explanation → Gate scenarios; gate + trigger tests
- [ ] Optimize unavailable while no authoring model is configured; user is told the model is missing and pointed to System Config, and no optimization run starts → Authoring-model resolution + gate + System Config scenarios; resolver + gate + trigger tests
- [ ] A normal execution uses the agent's own system/skill instructions; no prompt replaced by an optimization mission → Run no longer offers "run with optimization" scenario; launch API tests

**Plan Generation Trigger**

- [ ] Creating, saving, or updating an agent never generates/regenerates a plan; no authoring work, spend, or plan overwrite on save → Explicit-only generation scenarios; create/update API tests
- [ ] Implementation plan generated only on explicit request; Plan Preview offers that request and shows a pre-generation empty state → Explicit-only + Explicit Generate-plan UX scenarios; details-dialog + e2e tests
- [ ] Requesting a plan with no authoring model produces a clear explanation with a System Config pointer; nothing generated and no alternative model used → Generate-plan gate + authoring-model-resolution scenarios; plan generation + integration tests
- [ ] A failed generation shows its reason and never discards the last successful plan → Explicit-only failure scenario; plan generation service tests
- [ ] Changed agent config marks the plan possibly out of date and offers regeneration, without auto-regeneration → Explicit Generate-plan UX stale scenario; details-dialog + e2e tests
- [ ] After explicit generation the plan view updates automatically without a page reload → Explicit Generate-plan UX refresh scenario; details-dialog + e2e tests
- [ ] The same explicit-only rule applies to the optimized plan (produced only on Optimize) → Explicit-only generation scenarios; optimize trigger tests

**Plan Authoring Model & System Config**

- [ ] Implementation-plan and optimization-plan generation both use the workspace authoring model; the agent type's runtime model is never used for authoring → Authoring-model resolution + command-run authoring-model scenarios; resolver + plan generation + internal context tests
- [ ] Exactly one authoring model per workspace; changing it governs all subsequent generation with no second setting → Authoring-model resolution scenario + System Config single-save scenario; resolver + System Config tests
- [ ] The setting is workspace-scoped; a change in one workspace never affects another, and multi-tenancy off uses the single default workspace → Authoring-model resolution + System Config tenant-scope scenarios; tenancy edge case; tenant-scoped resolver and endpoint tests
- [ ] Only models enabled in the workspace catalogue can be chosen as the authoring model → System Config save-rejection scenario; System Config tests (`422`)
- [ ] A disabled/removed authoring model makes generation and optimization unavailable with the same reminder and a re-select request → Authoring-model resolution disabled scenario + removed/disabled mid-life edge case; resolver + gate tests
- [ ] The larger-model recommendation is advisory; a smaller enabled model is allowed and never blocked → System Config advisory scenario; System Config tests
- [ ] System Config explains the three uses and that the choice applies to the current workspace → System Config scenario; frontend System Config test
- [ ] System Config recommends a larger/higher-end model and clarifies runtime models are a separate choice → System Config scenario; frontend System Config test
- [ ] Unset authoring model shows a clearly visible reminder that disappears once a model is saved → System Config unset/reminder scenarios; frontend System Config test

**Conversational Agents Excluded**

- [ ] Plan generation and optimization are not available for conversational agents; controls hidden/disabled with a clear explanation → Conversational exclusion scenarios; gate + details-dialog + e2e tests
- [ ] No plan or optimization is generated for a conversational agent in the background or indirectly → Conversational exclusion + explicit-only scenarios; create/update + integration tests
- [ ] Conversational agents behave exactly as before (own instructions, no plan preview generation, never compiled into optimized plans) → Conversational exclusion run scenario; regression tests
- [ ] A plan authored before conversion to conversational is retained for reference but not used while conversational → Conversational conversion edge case; details-dialog + optimized-plan tests

**Optimization Execution**

- [ ] Optimize launches a dedicated optimization execution (optimization instructions + current plan + agent info + execution logs) without changing normal behavior → Optimize run scenarios; command-execution tests
- [ ] The optimization execution prefers the latest successful execution and reviews only limited history → `get_execution_log` bounds coverage; bounded-log edge case
- [ ] Optimization goal = correct script syntax + proper tool invocation, not identical result; differing/empty results don't cause re-attempts → Optimize run / needs_feedback scenarios; mission + tool tests
- [ ] Optimizer stops when it can't reach high confidence, records its outcome, no dead loop → needs_feedback scenarios; edge cases

**Plan Consumption & Self-Healing**

- [ ] After successful optimization, the next execution attempts the optimized plan first → ready-plan consumption; dispatcher/serving tests
- [ ] A fallback caused by the optimized plan marks it `requires_fix` and auto-records feedback describing the failure → fallback scenarios; record_fallback tests
- [ ] A `requires_fix` plan is not silently re-served; execution continues on the LLM path → serving predicate; get_fresh_optimized_plan tests

**Human-in-the-Loop Alert & Re-Optimization**

- [ ] The next time the user opens the agent/Optimized Plan tab, an alert indicates the plan requires a fix → alert-render scenario; frontend + E2E
- [ ] From the alert, re-optimize carries the previous plan plus recorded feedback → re-optimization scenario; regenerate-context tests
- [ ] Manual feedback can still be added at any time → manual-feedback scenario; add_feedback tests
- [ ] After re-optimization the Optimized Plan tab refreshes automatically (no manual reload) → auto-refresh; frontend + E2E

**No-Regression Guarantees**

- [ ] Execution remains focused on the user's task; optimization is never a side effect of a normal run → Run vs Optimize separation scenarios; full suite
- [ ] No plan is authored unless a user asked for it; no automatic/scheduled generation anywhere → Explicit-only generation scenarios + i18n/launch-surface assertions
- [ ] Plan authoring and optimization always use the approved authoring model; the runtime model is never used and there is no silent fallback → Authoring-model resolution + no-fallback + command-run scenarios; resolver + plan generation + internal context tests
- [ ] Optimization remains bounded and realistic: never loops for an identical result and always terminates with a clear outcome → needs_feedback + dead-loop guard scenarios
- [ ] All self-improvement is human-gated: the platform records and alerts but never loops automatically → alert + re-optimization scenarios; no scheduled re-optimization asserted

## Test File References

Per `easyspec-config.yaml` `source.tests`:

Backend (`backend/tests/`):

- `backend/tests/test_optimized_plan_requires_fix_migration.py` (new) — `OptimizedPlanStatus.requires_fix` member + ORM round-trip; migration file is the single additive `ADD VALUE IF NOT EXISTS` DDL (no `sa.Enum`/`CREATE TYPE`/parameterized DDL), documented no-op `downgrade()`, and the revision is a script-directory head.
- `backend/tests/unit/services/test_workflow_generation_settings.py` (new) — `get_authoring_model_state` / `require_authoring_model`: unset vs blank vs not-in-catalogue derivation, distinct `reason_code`s, session-tenant scoping (root tenant when multi-tenancy is off), non-raising vs raising variants, and that the stored setting row is never rewritten by a read; no fallback branch.
- `backend/tests/unit/services/test_plan_generation_service.py` (modified) — authoring-model resolution drives the completion call (set / unset / not-in-catalogue); `AgentType.model_id` and the first-available `ModelConfig` fallback are gone; not-configured → nothing written and the structured error propagates; failed attempt preserves the last successful steps/topology/hash/`generated_at`; authoring context is built from the authoring model; explicit-only contract asserted (no implicit invocation from create/update — the background helper is gone).
- `backend/tests/integration/api/test_agent_types_plan.py` (modified) — `regenerate-plan` gate: `412 plan_generation_unavailable` for conversational + unconfigured/disabled model with the matching `reason_code`, serving versions **not** retired and no plan written; success path authors with the authoring model; failed attempt preserves the last plan in the API payload; agent create/update never schedule generation; the refreshed plan is returned.
- `backend/tests/test_optimization_gate.py` (modified) — extended gate payload (`can_generate_plan`, `workflow_model_*`, `is_conversational`, `reason_code`), compound precedence (conversational → authoring model → executions), optimize trigger `412` per reason code, no session created when blocked, and gate-to-enabled transition after an execution completes.
- `backend/tests/test_internal_agent_context_authoring_model.py` (new) — command-run context returns the authoring `model_id` + resolved `model_config_id`; normal run (and conversational prepare / auto-compile / turn resume) returns `AgentType.model_id`; missing authoring model fails closed (`412 authoring_model_unavailable`); response contains identifiers only.
- `backend/tests/test_tenant_settings_workflow_generation.py` (verified, unchanged) — existing tenant-scoped GET/PUT contract for the authoring model setting (options from the tenant catalogue, raw stored selection, `422` for a non-enabled id, cross-tenant isolation, single setting).
- `backend/tests/test_optimized_plan.py` (verified, unchanged in 6.4) — reworded mission assertions (syntax + tool-invocation verification, no identical-result matching, high-confidence stop); `mark_requires_fix` (status transition, exact `execution_derived` entry shape, prior feedback preserved, `error` untouched, no-live-plan no-op, retired-plan exclusion, repeated-fallback safety, `requires_fix` never served); `add_feedback` tags `source: "manual"` (legacy entries without `source` preserved); `GET /types/{id}/optimized-plan` payload exposes `requires_fix` + feedback `source`; manual feedback endpoint returns `source: "manual"`. The removed `optimize: true` launch test is gone.
- `backend/tests/test_script_registry_service.py` (modified) — `record_fallback` attribution (`script_version_id → ScriptDefinition.source_optimized_plan_id → plan`) → `mark_requires_fix` + `execution_derived` feedback with execution/fallback references; idempotence on repeated fallback; retired-plan exclusion; base-plan script no-op; `requires_fix` plan no longer served.
- `backend/tests/test_internal_scripts_api.py` (modified) — `POST /api/v1/internal/scripts/fallbacks` end-to-end reaction (AR→CC): attributed optimized-artifact fallback flags the plan + appends execution-derived feedback; un-attributed base-plan fallback leaves the plan untouched. mTLS/tenant fail-closed invariants retained.
- `backend/tests/test_execution_log_bounds.py` (new) — `get_execution_log` reference selection (latest completed normal run; excludes command/current), explicit `session_id`, chronological text log, default 100 / clamp 500, invalid limit → default, bounded executions list, empty-history validity, `agent_type_id` required, reference `input` + `input_schema` (internal `__*` keys stripped).
- `backend/tests/test_dispatcher_script_context.py` (new) — the serving dispatcher binds the session `input_data` as the sandbox `initial_context` for both the whole-`python_source` and step-graph paths (regression: scripts saw an empty context and mis-validated real input).
- `backend/tests/test_sandbox_engine.py` (extended) — MCP envelope unwrap prefers the structured `result` field and parses Python-repr `content` text (regression: a flight-search script saw a repr string and reported "no flights found"); the sandbox records detailed per-call tool records (name/args/duration/result preview/error).
- `backend/tests/test_optimized_plan.py` (extended) — `execute_script` rejects an input context missing the agent's required typed keys (guessed/renamed fields) with a structured `validation_error` (`missing_input_keys` / `valid_input_keys`).
- `backend/tests/unit/test_guardrail_callback.py` (modified) — repeat-identical-tool-call guard: disabled by default, stops on the third identical consecutive call (canonical stop), resets on different args/tool.
- `backend/tests/test_command_execution.py` (verified, unchanged in 6.4) — command tool wiring unchanged; mission reword assertions (operator-facing final status report, syntax + tool-invocation goal vs identical output, mandatory bounded `needs_feedback` stop with `error`); executor final-message passthrough.
- `backend/tests/communication_hub/test_fix_20261101_120618_inherent_skills.py` (modified fixture) — the optimize-run context test now configures a tenant authoring model, because a `__command` run executes on the authoring model and fails closed (`412 authoring_model_unavailable`) without one; the inherent-skill assertions themselves are unchanged.
- `backend/tests/test_optimized_plan_requires_fix_migration.py` (modified assertion) — the revision check now asserts the migration is an ancestor of a script-directory head instead of being the single head (a later, unrelated migration extends the chain; the intent — the additive enum migration is part of the applied chain — is preserved).
- `backend/tests/test_script_first_dispatcher.py` (verified, unchanged) — unconditional LLM fallback, command-execution bypass, and serving freshness regression remain green.
- Pre-existing unrelated failures observed during the 6.4 run (reproduce without these test changes; none touch plan authoring, gates, or the command-run model override): the order-dependent `test_list_agent_types_does_not_include_plan_field` in the agent-type plan suite; `tests/api/v1/test_skills_api.py` / `tests/api/v1/test_mcp_hub_api.py` pydantic MagicMock errors; `tests/test_internal_endpoint_allowlist_coverage.py` management-tools allowlist; `tests/unit/test_fix_20261102_062047_mcp_tool_listing.py` (order-dependent within `tests/unit`), cert-path tests, and `tests/unit/test_setup_tenant_demo.py` (collection: `No module named 'setup'`); `tests/test_tenant_isolation_sweep.py` registry entries for `AgentClient` / `ConversationTurnResume`; live-service/mTLS integration suites (`test_service_auth.py`, `test_cross_service_flows.py`, `test_full_execution_flow.py`, `test_agent_execution_flow.py`, `test_websocket_communication_hub.py`) plus the PostgreSQL-only migration suites.

Frontend (`frontend/src/__tests__/`):

- `frontend/src/__tests__/SystemConfigPage.authoring-model.test.tsx` (new) — three-uses copy (Skill/SOP workflow generation, implementation-plan generation, optimization-plan generation) + workspace-scope statement, the advisory larger-model recommendation with the runtime-model-is-separate clarification, tenant-scoped GET/PUT (`/agents/model-configs/workflow-generation`) with options drawn only from the workspace catalogue, the unset reminder clearing once a valid model is saved, the disabled/stale selection (reminder echoes the saved id, "no longer available" disabled option, Save blocked until re-selected), saving a smaller enabled model allowed (advisory only), and a rejected `422` surfaced via the dialog error standard.
- `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` (modified) — Plan Preview explicit **Generate plan** action (empty state when no plan; blocked-with-reason + `/system-config` shortcut when the authoring model is unusable/unset/not-enabled; stale banner that only offers regeneration), agent-type/scripts/optimized-plan query invalidation so the plan appears without a reload, `412 plan_generation_unavailable` failure rendering while the last good plan stays visible, hidden plan/optimize affordances + conversational explanation for conversational agents, and the gated Optimize action in the footer (self-hides for conversational; localized `reason_code` tooltip with legacy reason fallback).
- `frontend/src/__tests__/AgentOptimizeDialog.test.tsx` (modified) — trigger payload `{ agent_type_id }`, query invalidation, `412` reason-code rendering for conversational / authoring-model-not-configured / authoring-model-not-enabled / no-successful-execution (System Config shortcut only for the model cases), unknown-reason fallback to the backend reason, other failures via `PermissionDeniedAlert`, busy/re-optimize variants, error clearing on reopen.
- `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx` (modified) — Run is execution-only: it launches immediately with no optimization sub-dialog, the `POST /agents/sessions` payload has no `optimize` field (ready-plan-absent and ready-plan-present paths), no plan-generation action or `regenerate-plan` request is ever issued from the launch surface, the stale-plan note is informational and points at the Plan Preview tab, the removed `runWithOptimization`/`skipOptimization` affordances are never rendered, and API failures surface inline in the launch dialog.
- `frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx` (modified) — `requires_fix` status chip + prominent alert + auto-recorded (`execution_derived`) feedback and its `auto-recorded` vs `manual` source badges; explicit empty auto-feedback state; Re-optimize from the alert and from the header action posts to `/agents/sessions/optimize` and refreshes the plan automatically; no re-optimize offered for a `ready` plan; `needs_feedback` renders the "Optimization needs your input" warning with the blocker + replay-only note (feedback/re-optimize retained); retired/legacy plan states; retire scope invalidation.
- `frontend/src/__tests__/AgentManagementPanelPage.test.tsx` (modified) — separate gate-aware Optimize action adjacent to Run: renders nothing for conversational agents, disabled with the localized `reason_code` copy in the tooltip when the authoring model is missing/unset or no execution exists (legacy reason-only payloads still show the backend reason; Run stays available), enabled after ≥1 successful execution, and confirming launches the optimization run and opens its execution details.
- `frontend/src/__tests__/AgentManagementPage.test.tsx` (modified) — the list surface renders the same separate, gated Optimize action per agent-type row (hidden for conversational rows), disables it with the authoring-model not-configured / not-enabled (re-select) copy, and opens the dedicated Optimize dialog (never the Run dialog).

E2E (`e2e/tests/`, Playwright — mocked first via `page.route()`, no live backend required):

- `e2e/tests/agent-plan-mode.spec.ts` (reworked in 6.6) — explicit-only plan authoring: creating **and** saving an agent type fires no `regenerate-plan` request and leaves Plan Preview in the empty state ("No implementation plan yet"); the plan is authored only by the explicit Generate plan action and renders in place without a page reload (the action then reads Regenerate plan); with no usable authoring model the tab shows the blocked state with the localized reason, a disabled Generate plan, and a System Config shortcut that lands on the authoring-model section (nothing dispatched); conversational agents get no generate/regenerate/empty-state affordances and only the explanation, plus no row-level Optimize action; a `412 plan_generation_unavailable` on an explicit attempt shows the reason with the System Config shortcut while the last successful plan stays visible. The live-backend variant asserts a newly created agent carries no plan (skips without `AGENT_TEST_TOKEN`/backend).
- `e2e/tests/agent-optimize-gate.spec.ts` (reworked in 6.6) — the composed gate blocks then enables the separate Optimize action: disabled with the localized `no_successful_execution` copy before any successful execution while Run stays available; disabled with the authoring-model not-configured copy, and with the not-enabled "re-select" copy even when a completed execution exists (the stale `workflow_model_id` is never treated as configured); no Optimize action at all for a conversational agent; a completed run enables Optimize without a page reload and launches the dedicated optimization execution (never the Run dialog); the Run dialog has no "run with optimization" affordance; a server-side `412 optimize_gate_unmet` re-check surfaces the structured `reason_code` copy with the System Config shortcut (and a legacy reason-only payload still surfaces the backend reason) while launching nothing.
- `e2e/tests/agent-plan-generation.spec.ts` (new in 6.6) — System Config authoring-model section: the three uses (Skill/SOP workflow generation, implementation-plan generation, optimization-plan generation), the workspace-scope note, the advisory larger-model recommendation (explicitly separate from agents' runtime models), the unset reminder clearing once an enabled model is saved (single save path → `PUT /agents/model-configs/workflow-generation`), a stale/no-longer-available selection echoed in the reminder as a disabled option with Save blocked until re-selected, and a smaller enabled model saving without being blocked.
- `e2e/tests/agent-optimize-requires-fix.spec.ts` (verified, unchanged in 6.6) — full self-healing journey through the Agent Type detail dialog: no plan yet → Optimize launches the dedicated run (`POST /agents/sessions/optimize` with `{agent_type_id}`, never the Run dialog) → `ready` plan with no alert → a later fallback flags the plan `requires_fix` → the alert renders with the auto-recorded (`execution_derived`) feedback + `auto-recorded`/`manual` badges → Re-optimize from the alert (prior plan + feedback carried) → the tab refreshes to the new plan without a page reload.
- `e2e/tests/agent-type-scripts-tab.spec.ts` (unchanged in 6.6) — requires-fix alert + auto-recorded feedback visible from the Agent Type detail dialog's Optimized Plan tab (source badges, re-optimize action). Note: the rest of that suite targets the Scripts tab, which was removed from the dialog before this change; those scenarios fail on the pre-change tree too (unrelated to this change).
- `e2e/tests/agent-management-panel.spec.ts` (unchanged) — the mocked panel CRUD scenarios pass (the added gated Optimize action does not affect the draft-only/parent-refresh assertions); the live-stack variant requires a dev server on `:5173` with real OIDC and fails pre-change as well (unrelated).
- `e2e/tests/agent-zero-llm-execution.spec.ts` (unchanged) — pre-existing failure on the pre-change tree (session log route mock no longer matches the app's log page); no optimization or authoring-model assertions are affected by this change, so no edit was made.

6.6 run: `agent-plan-mode.spec.ts`, `agent-optimize-gate.spec.ts`, `agent-optimize-requires-fix.spec.ts`, `agent-plan-generation.spec.ts` → 18 passed / 1 skipped (the live-backend `agent-plan-mode` variant) on Chromium. The unrelated suites listed above were not re-run in 6.6.

Note: the Python SDK (`sdk/parthenon-python/test/`) and MCP demo app (`mcp-demo-app/tests/`) are not exercised by this change — no SDK or demo-app surface is touched.
