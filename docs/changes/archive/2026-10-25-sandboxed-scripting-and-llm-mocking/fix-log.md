# Fix Log: sandboxed-scripting-and-llm-mocking

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20261020-124500

**Created:** 2026-10-20T12:45:00Z
**Status:** Verified
**Issue:** Regenerated plan still compiles to declarative JSON instead of sandboxed model-authored Python; output unchanged.

### Observed Behavior
After regenerating the implementation plan and re-running the agent twice, the promoted script version has empty `python_source`, `sandbox_validation_status=pending`, and runs as a legacy declarative graph.

### Expected Behavior
The regenerated plan carries the model-authored composition (script segments with Python source, LLM bridges); auto-compile validates and promotes a sandboxed Python version that the dispatcher executes in the sandbox.

### Analysis
- **Affected components:** plan_generation_service.py (composition prompt/schema), compiler.py (python_source path), autocompile.py (composition pass-through), dispatch.py (python_source serving path)
- **Root cause hypothesis:** the regenerated plan either does not contain the composition fields (prompt/parse gap) or autocompile/ignores them and falls back to the declarative sequence path
- **Documentation impact:** tech-spec.md Code Reference Map

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Implementation Details
<!-- Will be filled in as fix progresses -->

### Test Cases Added/Modified
- **File:** `backend/tests/test_model_authored_composition.py` (NEW — 2 tests, both FAIL on current code, no fix applied)
  - `test_regenerated_plan_autocompiles_to_sandboxed_python_version` — **FAIL**: regenerated plan with model-authored composition (2 `python_source` script segments + `semantic_bridge` LLM bridge + output decision) → `_run_autocompile` promotes **nothing**. Failure output:
    ```
    AssertionError: auto-compile must promote a candidate for a regenerated plan with model-authored composition; promoted=[], submitted=[]
    assert 0 == 1
    Captured log: Auto-compile skipped: not compilation-eligible: Plan contains model-backed steps
    (semantic bridging / System One judgment / interactive input) — not fully compilable (E5)
    ```
    → `analyze_compilability` rejects any plan containing LLM-bridge steps, so model-authored compositions are never compiled at all.
  - `test_fully_scriptable_python_source_plan_promotes_sandboxed_version` — **FAIL** (exact reproduction of live defect on version `d8d44c09`): all-scriptable plan whose steps carry `python_source` → `_run_autocompile` promotes a candidate compiled via `compile_from_tool_sequence` (recorded tool sequence), which **ignores the plan's `python_source`**. Failure output:
    ```
    AssertionError: promoted version has empty python_source — auto-compile compiled the recorded
    tool sequence into a DECLARATIVE graph instead of the plan's model-authored python_source composition
    assert ''
    Captured log: Compiled candidate step graph 'auto-aaaaaaaa' with 4 steps /
    Auto-compiled and promoted serving script version version-1 ... (2 recorded tool calls)
    ```
    → promoted version has `python_source=''` and `sandbox_validation_status='pending'` (matches live evidence).
  - **Root cause confirmed by both failures:** `backend/app/agent_runtime/scripts/autocompile.py` `_autocompile_inner` never calls `compiler.compile_from_plan`; it (a) skips plans with model-backed steps via `analyze_compilability` and (b) otherwise compiles the recorded tool sequence, discarding the composition. The compiler already supports composition (`compile_from_plan` + `ScriptSegmentStep` + `ScriptValidator`); autocompile does not use it.

### Code Changes
**File:** `backend/app/agent_runtime/scripts/autocompile.py` (`_autocompile_inner`)

1. **Composition detection (new `_plan_has_composition` helper)** — a plan carries model-authored composition when any plan step has `python_source` or an explicit `output_mode` final-output decision.
2. **Eligibility (E5) fix** — `analyze_compilability` is still run (conversational/interactive agents remain never-compiled, E6), but a `model_backed_steps` verdict no longer rejects the plan when the plan carries composition: LLM bridges are part of the authored composition and compile via `compile_from_plan`. Only plans with **no** composition AND model-backed steps are skipped (mixed script-segment + bridge plans now compile).
3. **Compile path fix** — when composition is present, the candidate is compiled via `compiler.compile_from_plan` (python_source script segments validated in-compiler via `ScriptValidator`, semantic bridges, plan output decision); `compile_from_tool_sequence` is kept only as the fallback for composition-less plans (recorded-sequence replay with the plan's output decision passed through).
4. **Sandbox-validation evidence** — when the compiled graph carries python_source segments, the joined source is validated with `ScriptValidator` and the candidate payload includes `python_source`, `sandbox_validation_status` (`passed`; the compiler already raises on unsafe segments) and `sandbox_validation_reason` when set.
5. **Invariants preserved** — fire-and-forget error containment, duplicate serving-version protection, unique `auto-*` version labels, secret-shape guard (SEC3, in compiler + validator), immediate promotion + serving-cache drop, humanized logs (composition path logs "compiled the plan's model-authored composition…").

### Test Results
- `tests/test_model_authored_composition.py`: **2 passed** (both previously failing tests now pass)
- Full script suite (composition, autocompile, compiler, runner, dispatcher, validator, security invariants): **143 passed, 0 failed**

### Verification Results (2026-10-20, verification run)
- **Reproduction tests** `tests/test_model_authored_composition.py`: **2 passed** ✅
- **Full affected backend suite** (12 files: composition, autocompile, script compiler, validator, runner, script-first dispatcher, security invariants, MCP-only boundary, sandbox engine, scripts API, internal scripts API, registry service): **327 passed, 0 failed** ✅
- **Frontend** `src/__tests__/agent-type-scripts-tab.test.tsx`: **13 passed** ✅
- **Frontend typecheck** `tsc --noEmit`: clean ✅
- **E2E spec compile** `playwright test --list tests/agent-zero-llm-execution.spec.ts`: compiles, 1 test discovered ("sandboxed script execution shows humanized one-line logs") ✅ (e2e project has no tsconfig; Playwright transpiler is the compiler)
- **Conclusion: fix verified — all layers pass. Status → Verified.**

### Documentation Updates
<!-- Will be updated as docs are revised -->

---

## Fix: Dispatch ignores the optimized plan when a legacy serving script exists; redundant same-script steps (2026-10-22)

**Status:** Fixed (tests green; awaiting verification)

### Defects (live evidence)
1. A run served the OLD auto-compiled declarative serving script (`auto-<id8>` artifact) even though a fresh (`ready`, newer than base plan) optimized plan existed.
2. The optimized plan showed ~a dozen steps ALL invoking the same script (should be ONE consolidated step per script).

### Root Causes
- **Bug A:** `dispatch.run_session_script_first` consulted the serving-script lookup FIRST; the gate "fresh optimized plan exists → run serving script" only checked the `fully_scripted` flag of whatever definition the serving lookup returned. A legacy auto-compiled `auto-<id8>` definition — marked `fully_scripted` by autocompile from the base plan's mark — won the lookup and was served in place of the optimized plan's composition. Post-run autocompile also kept re-promoting legacy declarative candidates, compounding the shadowing.
- **Bug B:** the optimized-plan authoring had no normalization — the LLM could emit multiple steps carrying the same `python_source`, and nothing merged them.

### Code Changes
- `backend/app/agent_runtime/scripts/dispatch.py` — the fresh optimized-plan lookup now resolves FIRST: tool-mode → LLM path (no script served); `fully_scripted` → serve only the optimized-plan artifact (`_ServingScript.is_optimized_artifact`, from the new `script_definition_name` payload field / `optimized-` prefix); legacy serving scripts never shadow; no fresh optimized plan → unchanged legacy gates.
- `backend/app/services/script_registry/service.py` (`get_serving_version`) — returns `script_definition_name` and prefers the optimized-plan-linked definition (`source_optimized_plan_id`).
- `backend/app/schemas/scripts.py` — `ServingVersionResponse.script_definition_name`.
- `backend/app/agent_runtime/scripts/autocompile.py` — promotion gate: while a fresh optimized plan exists the auto-compiled candidate stays draft (never promoted).
- `backend/app/services/agents/optimized_plan_service.py` — `_consolidate_steps` normalization (merge consecutive same-`python_source` steps, drop empty ones) applied after authoring; authoring prompt now mandates "EXACTLY ONE step per script; a script may contain multiple functions".

### Tests
- `backend/tests/test_script_first_dispatcher.py` (+2): legacy serving script never shadows a fresh optimized plan; tool-mode optimized plan never serves a script. Existing gating tests updated for the optimized-first lookup.
- `backend/tests/test_optimized_plan.py` (+2): consecutive same-script step consolidation + empty-step dropping + prompt rule assertion.
- Scripting suite: **327 passed** (13 test files) + communication-hub/agent-runtime script-tool tests: **10 passed**. Syntax check clean.

### Documentation Updates
- `tech-spec.md` (dispatcher/autocompile/optimize-service/registry rows + test rows), `implementation-plan.md` (6.4 updated, 6.5 added), `test-plan.md` (acceptance criteria + file references).

---

---

## Fix: Sandbox-issued tool calls dropped the signed forwarded tenant headers (2026-10-22)

**Status:** Fixed (tests green)

### Defect (live evidence)
`backend/logs/agent-runtime.log` (2026-10-22 21:38 & 22:16): during agent execution with scripts active, tool calls failed with `Communication Hub tool call failed: HTTP 502 - {"detail":"Signed tenant context headers are required on internal data-plane endpoints"}` — CC's data plane rejected the CH-forwarded call because the signed `X-Internal-Tenant-*` headers were missing.

### Root Cause (confirmed)
The sandbox executes scripts on a worker thread; `SandboxToolFacade.call` bridges tool calls back to the event loop via `asyncio.run_coroutine_threadsafe`. `contextvars.Context` does not cross that thread bridge: the bridged task is created with the loop thread's context, so the forwarded tenant-header set bound by AR's middleware (`bind_forwarded_tenant_headers`) was invisible to the `internal_httpx_client` egress hook (`forward_tenant_headers()` returned `{}`) → headerless egress → CC 401/422 → CH 502.

### Fix
- `backend/app/agent_runtime/scripts/sandbox.py`:
  - `run_sandboxed_python` snapshots `contextvars.copy_context()` at dispatch time (runs inside the dispatching task via `asyncio.to_thread`, which propagates contextvars) and threads it into `SandboxToolFacade`.
  - `SandboxToolFacade.call` wraps the bridged coroutine so the tool-call task is created inside the captured context (`ctx.run(asyncio.ensure_future, tool_coro)`) — the egress hook then sees the SAME signed forwarded header set as direct agent tool calls (identity parity, SEC1; forwarded verbatim, never re-signed). Invariant: the forwarded set is re-bound as-is — no re-signing, no widening.
- Script-as-tool path (`app/agent_runtime/api/script_tools.py`): unaffected — it is a fresh CH→AR request, so AR middleware binds the forwarded headers in the endpoint's own task; the sandbox bridge fix additionally protects any nested bridging on that path.

### Tests
- `backend/tests/test_script_runner.py` — NEW `TestSandboxTenantContextPropagation` (2 tests): the header set visible during a sandbox-issued tool call equals the set bound in the dispatch context (reproduction test failed before the fix); direct tool-call path parity control.
- Full mandated suite: `test_script_runner.py test_sandbox_engine.py test_script_first_dispatcher.py test_script_mcp_only_boundary.py test_script_security_invariants.py` — **199 passed, 0 failed**.

---

---

## Fix: Wall-time cap counted awaited MCP tool-call time → false resource-limit failures (2026-10-22)

**Status:** Fixed (tests green)

### Defect (live evidence)
User report: script execution fails with `ResourceLimitExceededError` ("Script exceeded its 30s wall-time limit") for multi-tool workflows whose compute is trivial.

### Root Cause (confirmed)
`backend/app/agent_runtime/scripts/sandbox.py` `_execute_with_caps` used a single flat `done.wait(timeout=caps.wall_time_limit_seconds)` over the whole worker thread. `SandboxToolFacade.call` blocks the worker for the entire awaited MCP call (each network call 1–10s, per-call limit 60s), and that awaited time was counted against the 30s cap. A 20-step workflow waits minutes in I/O with near-zero compute → guaranteed false cap breach. The cap's purpose is bounding the script's OWN compute, not penalizing awaited I/O.

### Fix
1. **Awaited-I/O exclusion (deadline pause):** `_execute_with_caps` passes a shared `io_time` tracker (`{"awaited": float, "in_flight_since": float}`, lock-guarded) into `SandboxToolFacade`. The facade sets `in_flight_since` when a call starts and, in a `finally`, adds the awaited duration to `awaited` and clears the in-flight marker. The main thread's flat wait is replaced with a deadline loop that computes `elapsed_compute = elapsed_real − awaited − (now − in_flight_since)` and terminates only when **compute** time exceeds the cap. The pause is LIVE while a call is in flight (not only after it returns), so long awaits never trip the loop mid-call.
2. **Configurable caps:** `SandboxCaps` defaults (and `from_version_fields` fallbacks) now resolve via env — `SANDBOX_WALL_TIME_SECONDS`, `SANDBOX_CPU_SECONDS`, `SANDBOX_MEMORY_LIMIT_MB` — with the hard-coded 30s / 10s / 512MB values as safe fallbacks (invalid/non-positive values log a warning and fall back). Operators can raise caps for heavyweight workflows.
3. **Security posture unchanged:** caps are still always enforced (only the accounting basis changed), a pure-compute infinite loop still terminates at the cap with `ResourceLimitExceededError` (`sandbox_termination=True`) → unconditional LLM fallback; per-call 60s limit and safe daemon-thread termination untouched.

### Tests
- `backend/tests/test_sandbox_engine.py`:
  - `TestWallTimeExcludesAwaitedIO.test_awaited_tool_time_does_not_count_against_wall_cap` — 2.5s awaited fake tool call + ~0.3s compute inside a 2s cap succeeds (this exact shape failed with `ResourceLimitExceededError` before the fix).
  - `test_pure_compute_still_terminates_at_cap` — compute-only `while True` still hits a 1s cap, `sandbox_termination=True`.
  - `test_multiple_tool_awaits_accumulate_exclusion` — two 1s awaited calls + trivial compute inside a 2s cap.
  - `TestResourceCaps.test_env_overrides_caps` / `test_invalid_env_falls_back_to_defaults` — env override respected; invalid env falls back to 30/10/512.
- Mandated suite `tests/test_sandbox_engine.py tests/test_script_runner.py tests/test_script_first_dispatcher.py tests/test_script_security_invariants.py` — **116 passed, 0 failed**; syntax check clean.

---

## Fix — Optimized plan shows per-tool steps; verification loop invisible; no-LLM honesty (2026-10-23)

**Status:** Fixed (tests green)

### Defect (user report, 3 issues)
1. The persisted optimized plan showed MANY per-tool steps although exactly ONE script artifact exists.
2. The user could not tell whether verification actually ran — the create → test-run → fix loop was invisible; failures landed in an opaque `failed` state.
3. A "no-LLM" plan was persisted even when the authored segments could not honestly deliver a single script.

### Root Cause (confirmed)
`OptimizedPlanService._consolidate_steps` only merged consecutive steps carrying the IDENTICAL `python_source`; the authored segments differ per step (each calls a different tool), so N authored segments persisted as N plan steps. Meanwhile `_associate_scripts` joins all `fully_scripted` segments into ONE serving script — so the plan view contradicted the executed artifact. Refinement exhaustion set `status='failed'` with no distinct user-facing steer state (the per-attempt `verification_log` existed but the terminal state did not prompt feedback).

### Fix
1. **Collapse rules** (`_normalize_composition` + `_synthesize_chained_source`): consecutive scripted steps (no LLM bridge between them) collapse into a SINGLE "Execute workflow script" step whose `python_source` CHAINS the segments — each segment's `run` is renamed to `partN` and a top-level `run` executes them in order, merging each dict result into `context` (script 1's output feeds script 2 — plain programming). The group's final `output_mode`/`output_template` wins; duplicated same-script steps still merge; empty steps drop. All-scripted one-script plan → exactly 1 step with the `fully_scripted` no-LLM mark preserved; script/bridge/script → 3 steps. The authoring prompt keeps the one-step-per-script rule and now documents the chaining semantics (belt-and-braces).
2. **Generation-time honesty:** if a segment cannot be chained (no `def run`), an all-scripted plan is DEMOTED to tool mode (LLM orchestrates the segments) with the reason recorded as an `info` entry in `verification_log` — a no-LLM plan is only claimed when deliverable.
3. **Verification visibility:** refinement exhaustion now persists `status='needs_feedback'` (new enum value, migration `b7c1d9e2a4f6` adds it to `optimized_plan_status_enum`) with EVERY attempt (including the final verification run) in `verification_log` and the last failure in `error`. Frontend renders `needs_feedback` distinctly (warning chip, failure alert, feedback steer prompt, i18n key `agents.optimizedPlan.needsFeedbackPrompt`).
4. **Execution safety:** unchanged gating `get_fresh_optimized_plan` serves only `status=ready` plans — `needs_feedback`/`failed` plans never reach the dispatcher (now regression-tested).

### Tests
- `backend/tests/test_optimized_plan.py`: collapse-to-one (all-scripted multi-segment → 1 chained step, no-LLM mark preserved), script/bridge/script → 3 steps, unchainable → tool-mode demotion + note, end-to-end generation persists one-step ready plan, exhaustion → `needs_feedback` with full per-attempt log + failure-explaining error (replaces the old `failed` expectation).
- `backend/tests/test_script_registry_service.py` `TestFreshOptimizedPlanGating`: `needs_feedback`/`failed` plans never served; fresh `ready` plan served.
- Mandated suites: `tests/test_optimized_plan.py tests/test_script_registry_service.py` (61 passed), `tests/test_model_authored_composition.py tests/test_script_first_dispatcher.py tests/test_script_runner.py tests/test_autocompile.py tests/test_script_refinement_loop.py tests/test_script_compiler.py tests/communication_hub/test_script_tool_routing.py` (143 passed), `tests/e2e/test_agent_execution_e2e.py tests/test_repair_loop.py` (15 passed); frontend `AgentOptimizedPlanTab.test.tsx` 7/7 (incl. needs_feedback rendering).

---

## FIX-20261024-command-dispatch-bypass

**Created:** 2026-10-24
**Status:** Fixed (tests green)

### Defect (user report + logs)
"Optimize & Verify" completes in ~1s and does nothing: the command side execution
(carrying the `__command` marker + mission prompt) is intercepted by Agent
Runtime's `run_session_script_first` dispatcher, which sees the target agent's
existing optimized-plan/serving script and immediately serves it (zero-LLM) —
the command's authoring+verification loop never runs, so `generate_script` /
`execute_script` / `generate_optimized_plan` are never invoked.

### Root Cause (confirmed)
`run_session_script_first` had no knowledge of the `__command` marker. It
unconditionally resolved the execution preference (fresh optimized plan →
serving script) and served the existing script for ANY session — including a
command side execution whose purpose is to AUTHOR the composition, not run it.
Two independent gaps:

1. **Dispatch interception:** `execute.py` discarded `body.input_data` (the
   marker never reached the dispatcher), and `run_session_script_first` had no
   guard to skip script-first/optimized-plan preference for command sessions.
2. **Missing command toolset:** the optimization system tools are NOT in the
   agent type's permission-scoped `allowed_tools`, so the CC context's
   `tool_definitions` excluded them — the command loop had no way to call
   `generate_script`/`execute_script`/`generate_optimized_plan` even once the
   LLM loop ran.

### Fix
- `backend/app/agent_runtime/scripts/dispatch.py` — `run_session_script_first`
  gains an `input_data` parameter and an explicit guard at the TOP: when
  `input_data["__command"]` is present it logs
  `"command execution (<slug>) — running LLM loop, bypassing script dispatch"`
  and calls `run_llm()` directly (no serving-script lookup, no optimized-plan
  lookup, no script path, no auto-compile).
- `backend/app/agent_runtime/api/execute.py` — `trigger_execution` now threads
  `body.input_data` → `_execute_session(input_data=...)` →
  `run_session_script_first(input_data=...)`.
- `backend/app/services/agents/runtime_executor.py` — new
  `_command_tool_schemas(command)` helper (derives the OpenAI schemas from
  `command_tool_names(command)` via `SystemToolRegistry`) and, in
  `_run_task_loop_ar`, appends those schemas to `tool_definitions` when
  `command` is set (before the `agent_initialized` snapshot), so the command
  loop actually has the optimization tools in its LLM toolset.

### Tests
- `backend/tests/test_script_first_dispatcher.py` — NEW `TestCommandExecutionBypass`
  (2): a `__command` session bypasses dispatch (no serving/optimized/script-path
  calls, `run_llm` runs) even when a fully_scripted serving script + fresh
  optimized plan exist; regression — a NON-command session still follows
  script-first (zero-LLM script path).
- `backend/tests/test_command_execution.py` (NEW, 4): `_command_tool_schemas`
  returns the optimization tools / empty for non-command; executor integration
  (mock LLM) — a command execution's `tool_definitions` include the full
  optimization toolset while a non-command execution's do not.
- Mandated suite: `tests/test_script_first_dispatcher.py tests/test_optimized_plan.py
  tests/test_script_runner.py tests/test_autocompile.py tests/test_command_execution.py
  tests/unit/test_agent_runtime_executor.py` — **155 passed, 6 skipped, 0 failed**.

---

## FIX-20261024-optimize-false-success

**Created:** 2026-10-24
**Status:** Resolved (all verification green)

### Defect (user report)
"Optimize & Verify" reported SUCCESS even when the side-execution never ran:
if the CH→AR launch trigger failed, the endpoint returned a `status: queued`
success payload (the session sat `failed` in the DB, invisible), and the
frontend showed the success alert on the immediate launch response — before
(and regardless of) the side-execution session actually completing. A stale
`ready` plan from a previous run could then be served as if the new optimize
run had succeeded.

### Root Cause (confirmed)
1. `AgentLifecycleHandler.launch` historically swallowed CH→AR trigger
   failures internally (logged + marked the session failed) and returned only
   `{"session_id": ...}` — `optimize_agent_type_plan` had no way to know the
   trigger failed and returned a success payload.
2. The frontend `optimizePlanMutation.onSuccess` treated the LAUNCH response
   as the optimize outcome (success path on `setOptimizeSessionId`), and the
   session-completion effect did not distinguish a failed session — it read
   the persisted plan and could surface a STALE `ready` plan as success.

### Fix
1. **Signaling** (`backend/app/services/gateway/lifecycle_handler.py`):
   `launch` now returns `{"session_id", "triggered", "trigger_error"}` —
   `_trigger_execution_via_comm_hub` already computed `(triggered, error)`.
2. **Endpoint** (`backend/app/api/v1/agents.py` `optimize_agent_type_plan`):
   when `triggered` is false → `mark_failed` on `OptimizedPlanService`
   (persists a `failed` plan + failed `verification_log` entry so
   `GET /optimized-plan` reflects the real outcome instead of any stale
   `ready` plan) and raise HTTP 502 with the trigger error. A direct launch
   exception surfaces as HTTP 422. Success returns `queued` + `session_id`
   only when the trigger actually fired.
3. **Frontend** (`frontend/src/components/agents/AgentTypeDetailsDialog.tsx`):
   the success alert is gated on the side-execution session polling to
   `completed` AND the persisted plan being `ready`; a `failed`/`terminated`
   session forces the failure alert with the run's `error_message` even when
   the fetched plan says `ready` (stale-success guard), and the raw-log
   dialog auto-opens with the failure either way. i18n key
   `agents.plan.optimizeExecutionFailed` added.

### Tests (written failing first, then fixed to green)
- `backend/tests/test_optimized_plan.py` `TestOptimizePlanEndpoint` (3):
  mocked launch `triggered: False` → endpoint returns 502 with `detail`
  (no success payload); trigger failure persists NO `ready` plan and NO
  `passed` verification entry; successful launch → 200 `queued` and no
  optimistic ready plan. Plus `TestOptimizedPlanMarkFailed` (1) —
  `mark_failed` persists `failed` status + failed verification entry.
- `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx`: optimize polls
  the side-execution session to completion then opens the raw-log dialog;
  a FAILED session with a stale `ready` plan shows the ERROR alert, never
  the success alert.

### Verification Results (re-verified 2026-10-24)
- Backend: `../.venv/bin/python -m pytest tests/test_optimized_plan.py
  tests/test_scripts_api.py tests/test_script_first_dispatcher.py
  tests/test_command_execution.py tests/test_script_runner.py
  tests/test_sandbox_engine.py
  tests/test_internal_endpoint_allowlist_coverage.py -q`
  → **160 passed, 0 failed**.
- Frontend: `npx vitest run src/__tests__/AgentTypeDetailsDialog.test.tsx
  src/__tests__/AgentOptimizedPlanTab.test.tsx`
  → **36 passed, 0 failed** (AgentTypeDetailsDialog + AgentOptimizedPlanTab);
  `npx tsc --noEmit` clean.
- E2E typecheck: `npx playwright test --list
  tests/agent-zero-llm-execution.spec.ts` (from `e2e/`) → parses/compiles
  cleanly, **1 test listed** (Zero-LLM agent execution).

---

## Fix: Malformed tool-name validation, command token budget, retire-keeps-rows + UX refresh (2026-10-25)

**Status:** Verified

### Observed Behavior (live, 2026-10-25)
1. **Session failed on a typo'd tool name**: a sandboxed script called `supabase__list_projects` (two underscores; the wire separator is four: `____`) → CH 502 `MCP tool not found: supabase__list_projects` → the session FAILED instead of falling back to the LLM path.
2. **Command run failed with "execution error: token_budget"** (00:21 run): an optimize-and-verify command run exhausted its role-level token budget mid-authoring and died with a bare, user-hostile error.
3. **Retire deleted history and didn't refresh the UX**: `retire_optimized_plan` DELETED the plan rows; after retiring in the Optimized Plan tab, the Run Agent launch dialog still did not immediately offer the opt-in optimization dialog (stale query cache).

### Root Causes
1. (a) No authoring-time check of `tools.call('name', ...)` literals against the agent's actual allowed tool names — the typo reached runtime. (b) At runtime, `CommHubToolClientError` raised inside the sandbox (from the CH 404/502) is a plain `Exception` — NOT a `ScriptExecutionError`/`SandboxError` — so `FallbackController.run_with_fallback` did not catch it and it propagated, failing the session.
2. `_build_guardrail_state` applied the role's guardrail `token_budget` unchanged to command runs; command runs are far more token-heavy than ordinary task runs.
3. Retire semantics deleted rows; the frontend retire handler only invalidated the narrow `optimized-plan` + `scripts` query keys, leaving base-plan/run-gate state stale.

### Fixes
- **Authoring-time validation** (`backend/app/api/v1/internal/optimization_tools.py`): `execute_script` (inline path) and `generate_script` AST-extract every literal `tools.call('name', ...)` and check against the agent's ACTUAL allowed tool names (`AgentPermissionManager.calculate_allowed_tools` with agent-type SOP/Skill binding overrides). Mismatch → `status: "validation_error"` + `invalid_tool_names` + `valid_tool_names` (no version persisted, no run) so the authoring LLM repairs the source in its next iteration.
- **Runtime fallback** (`backend/app/agent_runtime/scripts/runner.py`): `execute_python_source` converts a `CommHubToolClientError` escaping the sandbox into the typed `ExecutionError` (with a humanized one-line log) → `run_with_fallback` classifies `execution_error` → unconditional LLM fallback. The run never fails on a script tool-call error.
- **Prompt/contract** (`command_prompts.py` mission, `sandbox.py` `build_capability_contract`): tool names must be used EXACTLY as listed (four-underscore `____` separator); a wrong name is a validation error returning the valid names.
- **Command token budget** (`command_prompts.py`, `runtime_executor.py`): new `COMMAND_TOKEN_BUDGET` (default 2,000,000; `COMMAND_TOKEN_BUDGET` env override). Command runs get AT LEAST this budget; a larger explicit policy budget wins; ordinary runs unchanged.
- **Retire keeps rows** (`optimized_plan.py` + migration `c2d3e4f5a6b7` (applied), `optimized_plan_service.py`): `OptimizedPlanStatus.retired`; `retire_optimized_plan` MARKS rows retired; `_upsert_optimized_plan` retires previous non-retired row(s) and inserts the new ACTIVE one (one active record per agent type); `get_fresh_optimized_plan` serves only `ready` — a retired plan can never gate execution.
- **Frontend** (`AgentOptimizedPlanTab.tsx`): retire handler invalidates the whole agent-type query scope (`['agents','types',<id>]`, `refetchType: 'all'`) + `['scripts']`; `OptimizedPlanView.status` gains `'retired'` (shared with `AgentJobLaunchDialog`).

### Test Cases (all written failing first)
- `backend/tests/test_script_runner.py` — `TestToolNotFoundRuntimeFallback` (2): unknown tool → typed `ExecutionError`; controller falls back with `execution_error`.
- `backend/tests/test_optimized_plan.py` — `TestScriptToolNameAuthoringValidation` (3): reject with valid names (execute + generate), accept exact names; `TestRetireOptimizedPlanEndpoint` updated (rows remain `retired`; retired plan never gates; regeneration keeps exactly one active row); `TestCommandMissionToolNameRule`.
- `backend/tests/test_command_execution.py` — `TestCommandTokenBudget` (3).
- `backend/tests/test_script_registry_service.py` — `TestFreshOptimizedPlanGating.test_retired_plan_is_never_served`.
- `frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx` — retire invalidates the agent-type query scope (`refetchType: 'all'`) + scripts.

### Verification
- Backend affected suites: optimized-plan, command execution, script runner, script registry service, script-first dispatcher, sandbox engine, composition, MCP-only boundary, security invariants, internal scripts API, scripts API, autocompile, compiler, validator — **420 passed, 0 failed**.
- Frontend: `AgentOptimizedPlanTab.test.tsx` **8 passed**; `tsc --noEmit` clean.
- Migration `c2d3e4f5a6b7` applied (`alembic upgrade head`).

---

## Fix: execute_script sandbox ran in Control Center → `tools` facade was None (2026-10-25)

**Status:** Verified

### Observed Behavior (live)
Script verification failed with `TypeError: 'NoneType' object is not callable` —
`tools.call(...)` inside the sandbox hit a `None` facade. Any script that calls
MCP tools could NEVER verify.

### Root Causes (two compounding problems in `execute_script`)
1. **No tool client**: the CC handler called `run_sandboxed_python(...)` WITHOUT a
   `tool_client` → the `tools` facade passed to `run(context, tools)` was `None`.
2. **Architecture violation**: the sandbox executed INSIDE Control Center
   (`run_sandboxed_python` imported from `app.agent_runtime.scripts.sandbox` and
   run in the CC process) — violating "scripts execute only in Agent Runtime"
   and losing the session-bound identity/tenant context that exists in AR.

### Fixes
- **AR** (`backend/app/agent_runtime/api/script_tools.py`):
  `ScriptToolExecuteRequest` gains optional `python_source` — when present the
  endpoint executes THAT source directly in the sandbox with the session-bound
  tool client (registry lookup skipped; label `inline`, default `SandboxCaps`);
  `tool_args["input"]` becomes the script's `context`. The normal `tool_name`
  registry path is unchanged.
- **CH** (`backend/app/communication_hub/api/internal/tool_routing.py`):
  `ToolCallRequest` gains optional `python_source`; `_route_to_script_tool`
  forwards it verbatim in the AR payload.
- **CC client** (`backend/app/services/control_center/comm_hub_client.py`): new
  `CommunicationHubClient.execute_sandboxed_script` — POSTs
  `{tool_name: "script____inline", python_source, tool_args: {input}, session_id,
  agent_type_id, provenance: "script"}` to CH `/internal/tools/call` with signed
  tenant headers and a 120s timeout (sandbox wall-time), returning AR's
  `{"result", "error"}` contract. Routes CC → CH → AR because AR's middleware
  only accepts the `service:communication-hub` cert (direct CC → AR is rejected
  by design — same pattern as terminate/resume).
- **CC handler** (`backend/app/api/v1/internal/optimization_tools.py`): BOTH
  paths (inline `python_source` and saved `script_version_id`) now call
  `execute_sandboxed_script`; AR's structured sandbox error is surfaced as the
  tool's `{"error": ...}` response. No sandbox import remains in CC.
- **Segregation guard** (new
  `backend/tests/api/v1/internal/test_execute_script_sandbox_segregation.py`):
  source-scan assertion that `optimization_tools.py` never imports/calls
  `run_sandboxed_python`/`scripts.sandbox`/`SandboxCaps` and routes through the
  CH client — the violation cannot return.

### Test Cases (all written failing first)
- `backend/tests/agent_runtime/test_script_tool_execute.py` —
  `TestInlineSourceExecution` (4): inline source executes without registry
  lookup; `tools` facade NON-None and `tools.call('supabase____get_project', ...)`
  executes with session identity (`provenance=script`); `input` context mapping;
  sandbox error surfaced structurally.
- `backend/tests/communication_hub/test_script_tool_routing.py` (2): inline
  `python_source` forwarded verbatim to AR; field omitted on the registry path.
- `backend/tests/test_optimized_plan.py` — module-level `ar_boundary` stub at the
  `CommunicationHubClient` seam (emulates AR: real sandbox + recording tool
  client) + 3 new tests: inline source forwarded verbatim (not executed in CC);
  `tools` facade non-None regression; AR structured error surfaced. Existing
  execute-script tests now run through the same boundary.
- `backend/tests/api/v1/internal/test_execute_script_sandbox_segregation.py` (2):
  CC never imports/calls the sandbox; verification routes through the CH client.

### Verification Results (2026-10-25)
- New/updated suites: `tests/test_optimized_plan.py
  tests/agent_runtime/test_script_tool_execute.py
  tests/communication_hub/test_script_tool_routing.py
  tests/api/v1/internal/test_execute_script_sandbox_segregation.py`
  → **57 passed, 0 failed**.
- Optimization/script/dispatcher suites: `tests/test_scripts_api.py
  tests/test_script_first_dispatcher.py tests/test_command_execution.py
  tests/test_script_runner.py tests/test_sandbox_engine.py
  tests/test_internal_endpoint_allowlist_coverage.py
  tests/test_script_registry_service.py tests/test_internal_scripts_api.py
  tests/test_script_validator.py tests/test_sandbox_unpack.py
  tests/agent_runtime tests/communication_hub` → **341 passed, 0 failed**.

## Fix — execute_script routes via CC-cert-authorized CH forward hop; CC self-renews its service cert (2026-10-25)

### Root cause (two coupled defects)
1. **Broken verification hop**: CC's `execute_script` verification called
   `CommunicationHubClient.execute_sandboxed_script` → CH `POST /internal/tools/call`.
   But `ControlPlaneMiddleware` accepts ONLY `service:agent-runtime` certificates on
   `/internal/tools/` — CC's certificate is architecturally rejected there (and CC's
   cert had additionally expired Sep 7). The CC→CH hop could never succeed.
2. **No CC cert self-renewal**: CC's `service-cert.pem` was issued once at first
   startup and never renewed — silent expiry broke EVERY CC→CH/AR internal call.

### Fix 1 — `execute_script` routes CC → CH `/internal/script-tools/forward` → AR
- NEW `backend/app/communication_hub/api/internal/script_forwarding.py` —
  CH `POST /internal/script-tools/forward` (CC-cert hop, enforced by
  ControlPlaneMiddleware) → forwards to AR `/internal/script-tools/execute` using
  **CH's own service certificate** — the exact same CH→AR hop `script____<name>`
  tools take. AR contract (`result`/`error`) passed through verbatim.
- `tool_routing.py`: extracted the AR-forwarding core into
  `_build_ar_script_transport` + `_post_ar_script_execute` (shared by
  `_route_to_script_tool` and the new endpoint); `_route_to_script_tool`
  behavior unchanged.
- `comm_hub_client.py`: `execute_sandboxed_script` REMOVED (its CC-cert
  `/internal/tools/call` call was the broken path); replaced by
  `forward_sandboxed_script` → CH `/internal/script-tools/forward` (timeout 120s,
  tenant headers preserved).
- `optimization_tools.py`: `execute_script` verification now calls
  `forward_sandboxed_script` (inline AND saved-version paths).
- Router registered in `communication_hub/main.py`.

### Fix 2 — CC self-renewal of its own service certificate
- NEW `backend/app/core/cc_service_cert_renewal.py`:
  `renew_cc_service_certificate_if_needed` reads `service-cert.pem` expiry;
  missing/unreadable/expired/within-window (< `CC_SERVICE_CERT_RENEWAL_DAYS`,
  default 30) → re-issued via the CA module's own `issue_service_certificate`
  (NOT openssl), written atomically (`*.tmp` + `os.replace`), clearly logged;
  issuance failure logged, never raised, old files kept.
- `certificate_authority.issue_service_certificate` gained optional
  `validity_days` / `san_dns_names` / `san_ips` /
  `include_tls_extended_key_usage` (defaults preserve historical behavior);
  renewal issues 365-day certs with SAN localhost + 127.0.0.1 and
  clientAuth+serverAuth.
- `main.py`: `_ensure_cc_service_certificate` now delegates to the renewal
  module (issue-if-missing OR renew-if-stale) and starts a DAILY renewal
  asyncio task; shutdown cancels the task.

### Tests
- NEW `backend/tests/communication_hub/test_script_forwarding.py` (6): CH forward
  targets AR `/internal/script-tools/execute` (inline name/source/identity/
  provenance); AR result + structured error passed through; 503 without CH cert;
  CC client posts to `/internal/script-tools/forward` (never
  `/internal/tools/call`); `execute_sandboxed_script` removed from the client.
- `test_execute_script_sandbox_segregation.py`: seam assertion updated to
  `forward_sandboxed_script` + new guard: no `/internal/tools/call` /
  `script____inline` in the CC handler source.
- `test_optimized_plan.py`: `ar_boundary` stub moved to the
  `forward_sandboxed_script` seam.
- NEW `backend/tests/core/test_cc_service_cert_renewal.py` (10): expired cert →
  re-issued (new expiry > old + 300d, CN preserved, 365d/SAN/EKU issuance args,
  no .tmp leftovers); valid 60d cert untouched; 10d cert renewed under default
  30d window but NOT under env window 5; missing cert issued; corrupt PEM
  renewed; CA failure logged not raised (files intact); threshold env parsing +
  window logic.

### Verification (2026-10-25)
- `tests/core/test_cc_service_cert_renewal.py tests/communication_hub/
  tests/api/v1/internal/test_execute_script_sandbox_segregation.py
  tests/agent_runtime/test_script_tool_execute.py tests/test_optimized_plan.py
  tests/core` → **196 passed, 0 failed**.
- `tests/security/test_certificate_auth.py tests/test_internal_scripts_api.py`
  → 35 passed; internal auth/integration suites → 8 passed, 10 skipped;
  `tests/test_llm_mock_layer.py` + AR script suites → 24 passed.
- Import sanity: `app.main`, `app.communication_hub.main`, renewal + CA modules.
