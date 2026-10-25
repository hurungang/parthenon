# Test Plan: Sandboxed Scripting & LLM Mocking

**Related:** [prd.md](prd.md) · [tech-spec.md](tech-spec.md) · [architecture.md](architecture.md) · [data-model.md](data-model.md)

## Test Strategy

This epic touches security-critical execution (sandbox), composition semantics (dispatcher/compiler), and test infrastructure (mock LLM layer). The strategy is layered:

1. **Backend unit/integration tests (pytest, `backend/tests/`)** are the primary layer. Sandbox invariants, resource caps, validator/secret-shape guard, mock provider modes, runner accounting, dispatcher fallback, and lifecycle transitions are all testable without any external LLM API.
2. **E2E tests (Playwright, `e2e/tests/`)** exercise full agent executions with the mock LLM layer active (zero LLM API connectivity) — both the pure LLM agent loop and script paths containing model-backed (semantic-bridge) steps. Also verifies humanized log entries surfaced to operators and the Scripts tab governance UI.
3. **Frontend component tests (`frontend/src/__tests__/`)** cover the light Scripts tab changes (`python_source` presence indicator, sandbox validation status chips) without code duplication.
4. **CI determinism:** all agent-execution tests must run with `LLM_MOCK_MODE` active (scripted/replay) — no provider flakiness, zero LLM cost. Mock determinism is itself tested (identical inputs + mock scripts → identical runs).
5. **Security tests are adversarial by construction:** each sandbox invariant is tested with a deliberate escape attempt, asserting fail-closed behavior and recorded error detail. Service-segregation invariants (AR-only execution, CC-only DB, no credentials to scripts) get dedicated structural tests.
6. **Migration round-trip:** upgrade → verify schema (new enums, columns, `llm_mock_recordings` table) → downgrade → verify clean revert of only the new objects.

## Coverage Areas

### 1. Sandbox Security (Sandboxed Script Engine + Resource Cap Enforcer)
- **I/O attempts rejected:** file open/read/write, `os` filesystem access, subprocess, socket, database connection attempts — all blocked, fail-closed, with recorded violation detail.
- **Network attempts rejected:** direct socket use, HTTP client construction, DNS resolution — blocked.
- **Import policy:** no `import` statement; only pre-bound allowlisted builtins/modules visible; attempts to reach non-allowlisted modules or dunder paths (`__import__`, `__builtins__`, `__class__` chains) fail closed.
- **Attribute/item/write guards:** `_getattr_`/`_getitem_`/`_write_` guards block access to private/dunder attributes and unsafe mutation vectors.
- **Resource caps:** CPU-time breach, memory breach (`RLIMIT_AS`), wall-time breach (asyncio timeout) each terminate the script safely, produce a typed `resource_limit_exceeded` error with one-line detail, and trigger unconditional LLM fallback.
- **Secret-shape guard:** validator rejects sources embedding credential/token-shaped strings (identity tokens, DB connection strings, API keys) with `sandbox_validation_status` set and the version staying in draft.
- **MCP-only egress:** the injected `CommHubToolClient` binding is the only external access; calls use agent identity/permissions per the unchanged invocation contract; all other vectors fail closed.

### 2. Model-Authored Composition (Two-Layer Plan Model + Optimizer + Compiler + Dispatcher)
- **Base plan stays high-level:** the base implementation-plan prompt carries no composition authoring — no execution-semantics decision, no script source; the plan parses as a plain step list; `user_requirement` travels as context only.
- **Optimization is an opt-in step of the Run Agent flow:** with a verified (`ready`) optimized plan the run uses it directly; without one, the launch shows an opt-in dialog ("Run with optimization" / "Skip optimization"). Opting in turns the execution into the optimization opportunity: the agent self-reflects first (`get_scripts`, `get_execution_log`, `get_optimized_implementation_plan` — skipping re-authoring when healthy and unchanged), authors the composition, and verifies every script against REAL tool-call executions while accomplishing the user's real task; the verified plan is persisted for reuse. "Retire plan" MARKS the plan `retired` (kept for reference) so the next run triggers the check again.
- **Tool names are exact + command runs are budget-safe (2026-10-25):** `execute_script`/`generate_script` validate every literal `tools.call('name', ...)` against the agent's actual allowed tool names (structured `validation_error` lists valid names); a tool-not-found error at runtime converts to `ExecutionError` → unconditional LLM fallback; command executions get at least `COMMAND_TOKEN_BUDGET` (env-overridable). Cover: authoring validation (reject with valid names / accept exact names), runtime fallback trigger, command/non-command budget selection, retire-marks-retired (rows kept, one active record, retired plan never gates execution), frontend retire cache invalidation.
- **LLM-authored script segments execute verbatim:** stored `python_source` runs exactly as authored; no transformation, no injected steps.
- **Execution preference:** a fresh optimized plan (ready AND newer than the base plan) supersedes the base plan — `fully_scripted` → zero-LLM script, otherwise scripts as tools; an absent, stale, or failed optimized plan (e.g. base plan regenerated) falls back to the base-plan LLM path; registry unavailability never blocks execution.
- **NO automatic render step:** compiled compositions contain `semantic____render` only when the model's composition includes one; the hardcoded `_append_render_step`/`RENDER_STEP_NAME` path is removed (regression test: composition without a model-authored render step contains none).
- **Mixed script/LLM graphs:** compositions interleaving script segments, LLM bridge steps, and decision steps execute in the model-authored order with correct data hand-off.
- **Validation gate:** scripts failing syntax or sandbox-compliance validation stay in `draft` with a recorded reason and cannot be promoted; valid scripts promote draft → verified → compiled normally.
- **Pre-execution composition validation:** dispatcher rejects/falls back when a referenced script is missing, not in runnable state, or fails sandbox compile.
- **Repair loop:** repair output is re-fed through the validator (a repaired candidate that still fails validation does not execute).

### 3. Lifecycle Integration
- Draft → verified → compiled promotion requires passing validation + verification (shadow-run with `sandbox_check_passed` evidence).
- **Fallback:** any script failure — sandbox violation, resource cap, runtime error — triggers unconditional full-LLM-path fallback with the reason recorded (`sandbox_violation`, `resource_limit_exceeded`, generic script failure); the run itself never fails solely because a script failed.
- Lifecycle/lineage unchanged from predecessor epic: versioning, retirement, registry persistence via CC REST only.

### 4. LLM Mock Framework
- **Scripted mode:** hand-authored responses produce deterministic runs.
- **Record/replay round-trip:** a recorded real interaction, replayed by `recording_key` (tenant + key), reproduces identical LLM behavior; recordings persisted via CC internal API (batch upsert + lookup); recordings not found → clear typed error.
- **Prompt assertions:** tests can deterministically assert on prompt content and structure sent to the (mocked) LLM.
- **Mock provider selection:** `LLM_MOCK_MODE`/`LLM_MOCK_RECORDING_SET` route model dispatch to the mock provider; real providers otherwise.
- **Zero-LLM-API e2e runs:** (a) pure LLM agent loop and (b) script paths with model-backed semantic-bridge steps run end-to-end with zero LLM connectivity, including the semantic-bridge endpoint's test-only mock routing.

### 5. Observability & Accounting
- **Humanized logs:** script execution log entries are clean one-liners (step, outcome, what was produced) — no truncated JSON blobs; asserted in backend tests and e2e output.
- **`tokens_saved_actual`:** records the tokens actually avoided vs. the LLM path (not estimates); verified for accuracy against a known mock-scripted baseline; `sandbox_termination` and `sandbox_violation_detail` populated correctly on failure.

### 6. Service Segregation Invariants (per `docs/config.yaml` top-priority rules)
- Sandbox and script execution occur only in Agent Runtime.
- AR accesses registry, execution records, and mock recordings exclusively via mTLS CC internal REST with signed internal headers — no direct DB connectivity from AR.
- Mock recording API is CC-internal, mTLS-only; external/agent-instance cert access fails closed.
- Scripts and agents receive no credentials: no identity tokens, no DB connection strings; secret-shape guard enforces at validation, identity-context-only invocation contract at runtime.

### 7. Migration Round-Trip
- Alembic upgrade creates new enums (`SandboxValidationStatus`, extended fallback reasons, `MockInteractionKind`, `OptimizedPlanStatus`), new columns (ScriptVersion +6, execution accounting fields, ScriptDefinition optimized-plan lineage), and the `llm_mock_recordings` + `optimized_implementation_plans` tables; downgrade removes exactly these objects and nothing else; upgrade→downgrade→upgrade is idempotent; backend restarts cleanly post-migration.

## Critical Scenarios (WHEN/THEN)

- **WHEN** a script attempts file I/O / network access / a non-allowlisted import / dunder escape → **THEN** execution fails closed immediately, a typed sandbox error with one-line violation detail is recorded, and the run falls back unconditionally to the LLM path.
- **WHEN** a script exceeds its CPU, memory, or wall-time cap → **THEN** the script is terminated safely (no orphaned execution, service healthy), a `resource_limit_exceeded` failure with `sandbox_termination` recorded, and the LLM path completes the run.
- **WHEN** a script source embeds a credential-shaped string → **THEN** validation rejects it, `sandbox_validation_status`/`sandbox_validation_reason` are set, and the version cannot be promoted from draft.
- **WHEN** the base implementation plan is generated → **THEN** the prompt contains no composition authoring and the parsed plan is a plain high-level step list (no `fully_scripted` mark, no script source).
- **WHEN** the user opts into optimization at launch (no ready plan) and the authored composition is verified against real tool executions → **THEN** a `ready` `OptimizedImplementationPlan` is persisted with the verified composition, and the authored script versions are associated and promoted; when a ready plan already exists → **THEN** the run uses it directly without the opt-in dialog.
- **WHEN** the authored composition has no script segments, or the repair loop is exhausted → **THEN** the optimized plan is persisted as `failed` with a one-line reason and nothing is promoted.
- **WHEN** a fresh optimized plan exists and its serving script is `fully_scripted` → **THEN** execution runs the script zero-LLM; **WHEN** the optimized plan is absent/stale/failed → **THEN** the base plan's LLM path runs instead.
- **WHEN** an optimized composition with script segments, LLM bridge steps, and decision steps (no render step) is served → **THEN** the dispatcher executes exactly that composition verbatim; no `semantic____render` step appears anywhere in the executed graph or logs.
- **WHEN** a mixed graph runs where a verified script exists for a step → **THEN** the script segment runs first, its output feeds the next model-backed step, and model-backed steps invoke the LLM via the semantic-bridge path.
- **WHEN** any script segment fails during a mixed-graph run → **THEN** the entire run falls back to the full LLM path, completes successfully, and the fallback event records the specific trigger reason.
- **WHEN** an agent execution runs with the mock LLM in scripted or replay mode → **THEN** the run completes end-to-end with zero LLM API calls, and a repeated run with identical inputs/mock scripts produces an identical result (determinism).
- **WHEN** a run is recorded and then replayed → **THEN** the replay reproduces the recorded run's behavior identically, with recordings round-tripped through the CC internal mock API (AR never touches the DB).
- **WHEN** a script step completes successfully → **THEN** its execution log entry is a single human-readable line, and `tokens_saved_actual` on the execution record matches the real tokens avoided vs. the equivalent LLM path.
- **WHEN** the migration is applied and then downgraded → **THEN** new schema objects exist / are removed exactly, with no impact on pre-existing registry, execution, or lifecycle data.

## Edge Cases

- Script with caps set to `null` → platform default limits apply.
- Script completing exactly at (not over) a cap boundary → succeeds without spurious termination.
- Script returning a very large result / deeply nested structure → handled without crashing the runner; logs remain one-liners.
- Script calling an MCP tool that itself fails → per the unchanged invocation contract, surfaced as script failure → fallback.
- Replay mode with a missing `recording_key` → clear typed error, run falls back (never silent corruption).
- Record mode batch-upsert with duplicate `recording_key`s → idempotent upsert semantics per data-model.md.
- Empty or malformed `python_source` on a version → validation rejects; cannot promote or execute.
- Concurrent script executions → resource caps and sandbox isolation hold per-execution; no cross-run state leakage.
- Fallback triggered mid-run after some script steps already succeeded → full LLM path reruns the workflow cleanly; partial script results never leak into the final output.
- Mock mode enabled but semantic-bridge step present → bridge routes through mock layer; run completes with zero LLM API (test-only routing does not affect production behavior when mock mode is off).
- Legacy StepGraph types (pre-epic compositions) → backward compatibility maintained per tech spec schemas.
- Scripts tab UI with versions having missing/null new fields (pre-migration rows) → renders gracefully, no crash.

## Acceptance Criteria Checklist

### Sandbox & Scripting
- [ ] Scripted scripts can compute statistics, derive/pivot data, and assemble reports beyond declarative transforms.
- [ ] File, network, database, and all other I/O attempts are blocked and logged (fail-closed).
- [ ] Only allowlisted builtins and pre-bound safe modules are visible; import escape attempts fail closed with a recorded error.
- [ ] CPU, memory, and wall-time cap breaches terminate scripts safely, record the failure, and fall back to the LLM path.
- [ ] MCP tool calls via the injected client are the only external access; invocation contract unchanged (identity + permissions).
- [ ] Deliberate sandbox escapes produce clear, recorded errors — never partial execution.

### Model-Authored Composition (two-layer plan model)
- [ ] The base implementation plan stays high-level; its prompt carries no composition authoring.
- [ ] Opt-in launch flow: no ready plan → opt-in dialog; "Skip optimization" launches with `optimize: false`; "Run with optimization" launches with `optimize: true` and the execution runs as the `optimize-and-verify` command with the user's real task in the mission prompt; a ready plan launches directly without the dialog.
- [ ] Real-integration verification + self-reflection skip: the optimization run first reads `get_scripts`/`get_execution_log`/`get_optimized_implementation_plan`, skips re-authoring when scripts/logs are healthy and the agent is unchanged, otherwise authors and verifies scripts against real tool executions before persisting a `ready` plan.
- [ ] Retire → re-check: "Retire plan" deletes the optimized plan rows (and retires serving scripts); the next Run Agent flow finds no ready plan and offers the opt-in dialog again.
- [ ] ~~"Optimize & Verify" authors the full composition (script segments, bridge steps, decision steps, `fully_scripted` mark) as a separate optimized plan; no hardcoded compiler templates.~~ — superseded: authoring is unchanged, but the trigger is now the launch opt-in flow (covered by the scenarios above).
- [ ] A verified optimized plan is persisted `ready` with its script versions associated and promoted; failures persist `failed` with a recorded reason.
- [ ] Execution prefers a fresh optimized plan (`fully_scripted` → zero-LLM; otherwise scripts as tools) and falls back to the base-plan LLM path when absent/stale/failed.
- [ ] **Bug regression:** a legacy auto-compiled (`auto-<id8>`) serving script NEVER shadows a fresh optimized plan — with a fresh `fully_scripted` optimized plan and only a legacy serving script present, the run takes the LLM path.
- [ ] **Bug regression:** a tool-mode optimized plan never serves any script directly — the LLM orchestrates and scripts stay `script____<name>` tools.
- [ ] **Bug regression:** auto-compile skips promotion while a fresh optimized plan exists (candidate stays draft).
- [ ] **Bug regression:** authored optimized-plan steps are normalized — consecutive scripted segments collapse into ONE chained "Execute workflow script" step per segment group (all-scripted one-script plan → exactly 1 step marked no-LLM; script, bridge, script → 3 steps); empty steps dropped; duplicated same-script steps merged; unchainable all-scripted segments demote the plan to tool mode.
- [ ] ~~**Bug regression (FIX-20261024-optimize-false-success):** a failed CH→AR launch trigger makes `POST .../optimize-plan` return HTTP 502...~~ — reverted with the standalone endpoint; launch-path outcome signaling is inherited from the normal session lifecycle (a failed trigger surfaces as a failed session in the dashboard).
- [ ] **Verification visibility:** refinement exhaustion sets optimized plan status `needs_feedback` (NOT silent `failed`) with every attempt (incl. the final run) in `verification_log` and the last failure in `error`; dispatch gating serves only `status=ready` — a `needs_feedback`/`failed` plan is never used by execution.
- [ ] No `semantic____render` step is ever appended automatically (regression test for removed `_append_render_step`).
- [ ] Script segments run verbatim where verified scripts exist; model-backed steps invoke the LLM; script failures fall back unconditionally with recorded reasons.
- [ ] Model-authored source is stored/versioned in the registry; lifecycle draft → verified → compiled → retired and lineage unchanged.
- [ ] Scripts failing validation/compilation stay in draft with a recorded reason and cannot be promoted.

### LLM Mocking Framework
- [ ] Agent executions run end-to-end with zero LLM connectivity in scripted, record, and replay modes.
- [ ] Both the pure LLM path and script paths with model-backed steps are testable via the mock layer.
- [ ] Prompts sent to the mocked LLM are deterministically assertable (content + structure).
- [ ] Mock layer is wired into the pytest suite and Playwright e2e suite; CI runs agent-execution tests with zero LLM cost/flakiness.
- [ ] Identical inputs + identical mock scripts produce identical runs.

### Observability & Accounting
- [ ] Script execution log entries are human-readable one-liners; no truncated JSON blobs.
- [ ] `tokens_saved_actual` reflects real tokens avoided (validated against a known baseline), with `sandbox_termination` and `sandbox_violation_detail` recorded on failure.

### Architecture & Data
- [ ] Sandbox + execution run only in Agent Runtime; only CC touches the database.
- [ ] AR consumes registry/execution/mock-recording data exclusively via mTLS CC internal REST with signed internal headers.
- [ ] Scripts/agents never receive identity tokens, DB credentials, or any other sensitive data (secret-shape guard + runtime contract).
- [ ] Alembic migration round-trips cleanly (upgrade/downgrade/upgrade), enums via `create_type=False` pattern, downgrade removes only new objects.
- [ ] Scripts tab renders new fields (`python_source`, sandbox validation status) without breaking existing governance flows; all UI text via i18next `t()`.

## Test File References

### Backend (`backend/tests/`)
- `test_sandbox_engine.py` — sandbox invariants, I/O/network/import rejection, resource caps, escape fail-closed, MCP-only egress boundary.
- `test_script_validator.py` — validator/normalizer, AST safety scan, secret-shape guard, render-append removal regression.
- `test_llm_mock_layer.py` — scripted/record/replay modes, determinism, prompt assertions, mock provider selection via env/config.
- `test_script_runner.py` — sandboxed execution path, humanized one-line logs, `tokens_saved_actual`/`sandbox_termination`/`sandbox_violation_detail` accounting; **MCP content-envelope unwrapping (`TestMcpEnvelopeUnwrapping`): JSON-text envelope → parsed list in `output_key`, non-JSON text → string, `isError` envelope → `ExecutionError`, non-envelope passthrough, step log entry notes unwrapping, and the sandboxed `tools.call` facade returns the unwrapped payload (live-defect regression: script iterating a raw envelope concluded "no supabase project found")**.
- `test_optimized_plan.py` — `TestLaunchOptimizeInjection` (opt-in flag injects the `__command` markers + mission with the user's real task preserved; flag-off passes input through untouched), `TestRetireOptimizedPlanEndpoint` (retire deletes plan rows and reports the count; 404 unknown agent type; **end-to-end retirement: seeded ready plan + compiled serving version → retire → rows gone, `get_fresh_optimized_plan` returns None, serving version `retired`**), `TestOptimizedPlanMarkFailed` (`mark_failed` persists `failed` + failed verification entry), and `TestOptimizationSystemTools` (the `optimize-and-verify` command mission — self-reflection-first text, interpolation, toolset including `get_scripts`/`get_execution_log`, inline-source/save-on-success mission assertions — and idempotent seeding; the optimization SYSTEM TOOLS (`get_implementation_plan`, `generate_script` valid + unsafe-rejection, `execute_script` version-path output + sandbox-error **plus inline `python_source` execution without save, inline structured sandbox error, no persistence on inline execute, save-only-after-success flow**, `generate_optimized_plan` + `record_verification` → persisted `ready` plan + `verification_log`, `list_scripts`/`get_script`, **`get_scripts` self-reflection payload, `get_execution_log` entries**, `get_optimized_implementation_plan` not-found) driven through the internal client; and the stripped `OptimizedPlanService` persistence (generate/record/feedback/retire).
- `test_agent_runtime_executor.py` — `_build_guardrail_state` command-awareness: `__command` runs get `COMMAND_MAX_ITERATIONS` (40) regardless of policy; plain task runs keep the policy/default (10).
- `test_execution_logging_callback.py` — `on_tool_start` keeps the FULL `execute_script` input (drafted source reviewable in the execution log); other tools still truncate at 500 chars.
- `test_script_first_dispatcher.py` — composition validation, verbatim model-authored execution, no auto-appended steps, extended fallback triggers; **`fully_scripted` dispatch gating** — a `fully_scripted=true` serving script runs directly (zero-LLM) while `fully_scripted=false` falls to the LLM path and is exposed as an invocable tool; **optimized-plan execution preference** — fresh ready optimized plan gates the zero-LLM path, absent/stale → base-plan LLM path, lookup caching + registry-error degradation, **legacy-serving-script precedence + tool-mode no-serve regressions**; **`TestCommandExecutionBypass` (2)** — a command side execution (`__command`) bypasses script-first/optimized-plan dispatch entirely (runs the LLM loop even when a fully_scripted serving script + fresh optimized plan exist) and a NON-command session still follows script-first (zero-LLM) preference.
- `test_command_execution.py` (NEW, 4) — command-execution toolset wiring: `_command_tool_schemas` returns the optimization tools (empty for non-command); a command execution's `tool_definitions` include the full optimization system toolset (mock LLM) while a non-command execution's do not.
- `test_autocompile.py` — post-run auto-compilation eligibility/duplicate-protection/verification; **verification gate (2 new)** — a `fully_scripted` candidate whose test output mismatches the recorded LLM run is submitted with `comparison_outcome="mismatch"` evidence and never promoted (stays draft); a match promotes.
- `test_script_security_invariants.py` — service segregation (AR-only execution, CC-only DB), no-credentials invariants, mTLS-only mock recording access.
- `test_script_mcp_only_boundary.py` — injected `CommHubToolClient` as sole egress; identity/permission invocation contract.
- `test_internal_scripts_api.py` — CC registry REST new fields; CC internal mock API (upsert/lookup, mTLS fail-closed); semantic-bridge mock routing in test mode.
- `test_internal_endpoint_allowlist_coverage.py` — **internal-endpoint allowlist regression guard (NEW)**: statically scans AR (`scripts/cc_client.py`, `data_client.py`) and CH (`data_client.py`, auth middleware, tool routing, tool registry bridge) caller sources for the (method, path) pairs they issue to `/api/v1/internal/...` and asserts each pair exists in the CC-side allowlists in `app/api/deps.py` (`_AR_ALLOWLIST` / `_CH_ALLOWLIST`) — fails on any future `403 endpoint_not_allowlisted` bug of this class. Secondary cross-check enumerates the CC internal scripts/llm-mock router routes and the `SystemToolRegistry` CC endpoint map and asserts they are allowlisted (catches drift in the other direction). Path params canonicalized to `{}`; intentionally-unauthenticated endpoints (cert revocation check, bootstrap) documented as exempt.
- `communication_hub/test_script_tool_routing.py` — **scripts-as-tools routing (5 new)** — `script____<name>` virtual tools route to Agent Runtime `/internal/script-tools/execute` (not CC / MCP proxy) with the session-bound agent identity (`session_id` + `agent_type_id`) and `provenance="llm"`; the AR script result is unwrapped into the `call_tool` contract; missing CH service certificate fails closed (503).
- Lifecycle/verification/repair coverage (promotion gates, shadow-run `sandbox_check_passed` evidence, repair re-validation) within the above runner/dispatcher suites.
- Migration round-trip test alongside the new Alembic revision under `backend/alembic/versions/`.

### Frontend (`frontend/src/__tests__/`)
- Tests for `AgentScriptsTab.tsx` / `useScripts.ts` rendering `python_source` presence and sandbox validation status chips; graceful handling of pre-migration rows (no new fields).
- `AgentTypeDetailsDialog.test.tsx` — regenerate-plan call with the 180s timeout; ~~"Optimize & Verify" button~~ removed — **"Retire plan"** posts to `/agents/types/{id}/optimized-plan/retire`; the absent/retired state shows the "next run offers optimization" hint.
- `AgentJobLaunchDialog.test.tsx` (`AgentSessionLaunchDialog.test.tsx`) — **opt-in dialog flow**: with no ready optimized plan, clicking Run Agent opens the opt-in dialog; "Skip optimization" posts `optimize: false`; "Run with optimization" posts `optimize: true`; with a `ready` optimized plan the launch posts `optimize: false` directly (no dialog); permission-denied error surfacing.
- `AgentOptimizedPlanTab.test.tsx` (**new, 8**) — Optimized Plan tab renders steps (name/description), "View script" links only on script-backed steps (click opens the Scripts tab), per-attempt verification log entries, accumulated feedback comments; feedback submit posts to `/agents/types/{id}/optimize-plan/feedback` and refreshes the plan; 404 → absent state with the "next run offers optimization" hint; `needs_feedback` status renders distinctly (warning chip + failure alert + feedback steer prompt); **"View optimization log" button reopens the raw log dialog (one monospace line per verification_log entry, close works, no failure header on ready plans)**. `AgentTypeDetailsDialog.test.tsx` extended: **5 tabs** including the new "Optimized Plan" tab at panel index 5; **"Retire plan" posts to `/agents/types/{id}/optimized-plan/retire`; the absent/retired state shows the hint that the next run will offer optimization again**.
- Backend additions in `test_optimized_plan.py` (→ 29 tests): `verification_log` persisted (passed entry on ready plans; one failed entry per exhausted attempt; **failed entry ALSO on pre-refine failures — empty composition, authoring LLM exception — so every optimize attempt leaves an inspectable log**); feedback one-shot summarization + accumulation (+ raw-text fallback when the model call fails); regeneration prompt includes ALL stored feedback summaries; feedback survives regeneration (not wiped by the upsert); **verification-gated chaining (NEW, 3 in `TestVerificationGatedChaining`)**: 3 chained segments with no bridge → exactly ONE step / one script tool, verification passes → plan stays chained + `fully_scripted`; chained script fails at segment 2 → split at the failing segment (prefix chain + individual tool-mode script tools), plan READY with the split reason in `verification_log` (NOT `needs_feedback`); `needs_feedback` only when every split segment also fails; **chain registry:** `_normalize_composition` returns the per-chain constituent segments (4-tuple) used by `_split_failed_chain`

### E2E (`e2e/tests/`)
- New zero-LLM agent-execution spec: mock-provider-driven full runs (agent loop + script path with model-backed steps), zero LLM API connectivity asserted, humanized log entries visible in operator surfaces, Scripts tab governance flow.

## Execution Status (verified 2026-10-21)

- **Backend**: full script framework suite (16 files: sandbox engine, validator, LLM mock layer, runner, compiler, autocompile, dispatcher, MCP-only boundary, security invariants, scripts API, internal scripts API, registry service, registry migration, verification engine, repair loop, drop-execution-mode migration) **+ two-layer plan model tests (`test_optimized_plan.py` + extended dispatcher gating)** — **387 passed, 0 failed**.
- **Refinement re-run (2026-10-21)**: backend scripting suite + `test_optimized_plan.py` (17 tests, incl. verification-log + feedback-memory additions) — **195 passed, 0 failed**; migration `93d25e577411` applied (`alembic current` = head). Frontend touched tests (`AgentOptimizedPlanTab` 6, `AgentTypeDetailsDialog` 25, `agent-type-scripts-tab`, `AgentExecutionDetailsDialog`) — **49 passed, 0 failed**; `tsc --noEmit` clean.
- **Retire e2e lock + execution-dialog header link (2026-10-24)**: backend `tests/test_optimized_plan.py tests/test_scripts_api.py tests/test_script_first_dispatcher.py` — **92 passed, 0 failed** (new `TestRetireOptimizedPlanEndpoint.test_retire_clears_fresh_optimized_plan_and_serving_versions` — written failing first on the freshness-gate seeding, green after the seed matched the gate semantics; confirms rows deleted + `get_fresh_optimized_plan` None + serving version retired). Frontend `AgentExecutionDetailsDialog.test.tsx` + `AgentOptimizedPlanTab.test.tsx` — **11 passed, 0 failed** (removed-button test replaced by the header "View agent" link test asserting `AgentTypeDetailsDialog` opens with `agent_type_id=at-42` on tab 0); `tsc --noEmit` clean.
- **Verification-gated chaining re-run (2026-10-23)**: `test_optimized_plan.py` (27) + `test_script_first_dispatcher.py` + `test_script_runner.py` — **79 passed, 0 failed**; full optimized-plan + dispatcher + runner + sandbox/validator/mock/refinement/compiler/autocompile/model-authored-composition suite — **220 passed, 0 failed**.
- **Refinement re-run (2026-10-22)**: new allowlist guard `test_internal_endpoint_allowlist_coverage.py` (4 tests) + `test_internal_scripts_api.py` + `test_script_first_dispatcher.py` — **58 passed, 0 failed**. Guard sweep found and fixed 4 real `endpoint_not_allowlisted` bugs: AR missing `GET /internal/scripts/invocable`, `POST|GET /internal/llm-mock/recordings`; CH missing `POST /internal/data/sessions/{session_id}/log`.
- **Frontend**: `AgentTypeDetailsDialog.test.tsx` + `AgentSessionLaunchDialog.test.tsx` + `AgentOptimizedPlanTab.test.tsx` — all passing (opt-in dialog flow, direct launch with a ready plan, `optimize` flag passthrough, retire call, absent-state hint); `tsc --noEmit` clean.
- **Optimize false-success fix (FIX-20261024-optimize-false-success, 2026-10-24)**: backend `tests/test_optimized_plan.py tests/test_scripts_api.py tests/test_script_first_dispatcher.py` — **80 passed, 0 failed**. Frontend `AgentTypeDetailsDialog.test.tsx` — **28 passed, 0 failed**; `tsc --noEmit` clean.
- **Raw optimize log visibility (2026-10-24)**: backend `test_optimized_plan.py` — **29 passed, 0 failed** (incl. 2 new pre-refine-failure log-persistence tests). Frontend touched tests (`AgentOptimizedPlanTab` 8, `AgentTypeDetailsDialog` 27) — **35 passed, 0 failed**; `tsc --noEmit` clean.
- **E2E**: `agent-zero-llm-execution.spec.ts` typechecks (Playwright compile via `--list` succeeds; 1 test discovered). **Not executed locally** — Playwright browsers/app stack unavailable in this environment; run in CI or with a live stack.
- **Verification-log removal + retire freshness fix (2026-10-24)**: backend `tests/test_optimized_plan.py tests/test_script_first_dispatcher.py tests/test_scripts_api.py` — **84 passed, 0 failed** (record-verification tool tests removed; `TestRetireFreshness` written failing first then green: retired plan/serving version never served from cache, lookups always re-hit the registry); `test_internal_endpoint_allowlist_coverage.py` + `test_internal_scripts_api.py` — **27 passed** (allowlist entry removed in lockstep); migration `a1dbc4760d9a` applied (`alembic current` = head). Frontend `AgentOptimizedPlanTab.test.tsx` + `AgentTypeDetailsDialog.test.tsx` — **33 passed, 0 failed** (verification-log section + raw-log dialog assertions replaced with absence assertions); `tsc --noEmit` clean.

### Live-defect regression additions (2026-10-24)

- Backend `test_script_first_dispatcher.py` — `TestOptimizedPlanUsedOnNextRun` (2): mirrors the live state — agent-chosen serving-script name + `source_optimized_plan_id` lineage is recognized as an optimized artifact, and a fresh ready fully_scripted optimized plan dispatches zero-LLM on the NEXT run.
- Backend `test_command_execution.py` (+2): the mission prompt's "Final answer" section is asserted (business result, not meta-talk), and a command run with a mocked LLM completes with the scripted business result as the session output (no optimization meta-talk markers).
- Backend `test_sandbox_engine.py` (+2): minimal business-logic-only script end-to-end through the sandbox facade with a fake tool client (context carries task input + prior outputs; `tools.call` reaches the agent-bound client with `provenance=script` and an unwrapped payload); capability contract states the agent-behalf / business-logic-only contract.
- Frontend — `AgentScriptsTab` test file deleted with the component; `AgentTypeDetailsDialog.test.tsx`: **4 tabs** (Scripts tab gone; Optimized Plan at panel index 4); clicking a per-step "View script" link opens `ScriptViewDialog` inline with the step's `python_source`; new `ScriptViewDialog.test.tsx` (3); `AgentOptimizedPlanTab.test.tsx` — `onViewScript(step)` receives the clicked step.

**Re-run (2026-10-24)**: backend dispatcher (37) + optimized-plan/command/sandbox/runner/autocompile/model-authored-composition suites — all passing; frontend touched suites (AgentTypeDetailsDialog 26, AgentOptimizedPlanTab 8, ScriptViewDialog 3) — **37 passed**, `tsc --noEmit` clean.
- **Cert-routing + renewal (2026-10-25):** `test_script_forwarding.py` (6) — CH `/internal/script-tools/forward` targets AR `/internal/script-tools/execute` with CH cert (inline source/identity/provenance forwarded; AR result/structured error passed through; 503 without CH cert); CC client posts to the forward endpoint (never `/internal/tools/call`) and `execute_sandboxed_script` is gone; `test_execute_script_sandbox_segregation.py` pins the new seam + no `/internal/tools/call` in the CC handler. `test_cc_service_cert_renewal.py` (10) — expired/near-expiry/missing/corrupt cert re-issued (new expiry > old, CN preserved, 365d/SAN/EKU args, atomic write, no .tmp), valid cert untouched, env threshold honored, CA failure logged not raised with files intact.
