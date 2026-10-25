# Implementation Plan: Sandboxed Scripting & LLM Mocking

**Related:** [prd.md](prd.md) · [spec-change.md](spec-change.md) · [architecture.md](architecture.md) · [data-model.md](data-model.md) · [tech-spec.md](tech-spec.md)
**Evolves:** [Software 3.0 Agent Framework implementation plan](../software-3.0-agent-framework/implementation-plan.md) — the script registry, Script-First Dispatcher, lifecycle, and Scripts tab built by the predecessor are reused unchanged.

## Overview

This plan implements sandboxed Python scripting (RestrictedPython, adopted per the tech-spec evaluation) inside Agent Runtime, model-authored workflow composition replacing the hardcoded compiler templates, a first-class LLM mock layer for zero-LLM test runs, and humanized script logs with accurate `tokens_saved_actual` accounting. Work lands in six phases: schema + sandbox engine foundation, model-authored composition (compiler → validator, `semantic____render` append removed), runner execution with MCP-only client injection, the LLM mock layer, tests/CI wiring, and the **two-layer plan model**: the base implementation plan stays a plain high-level step list, and the model-authored composition (script segments, LLM bridge steps, output decision, `fully_scripted` mark) is produced as a SEPARATE `OptimizedImplementationPlan` by the on-demand "Optimize & Verify" flow. All database work stays Control-Center-owned with Alembic autogenerate + review; all script execution stays in Agent Runtime under the top-priority rules (segregated services, AR-only scripts, CC-only DB, no credentials, MCP-only egress).

## Task Checklist

### Phase 1 — Sandbox Engine & Schema Foundation
- [x] 1.1 — Add RestrictedPython dependency to backend/pyproject.toml
- [x] 1.2 — Extend DB models: script_registry.py (ScriptVersion python_source + caps + sandbox validation; VerificationRun.sandbox_check_passed; FallbackEvent enum)
- [x] 1.3 — Extend DB models: script_execution.py (tokens_saved_actual, sandbox_termination, sandbox_violation_detail)
- [x] 1.4 — New DB models: llm_mocking.py (LLM MockRecording)
- [x] 1.5 — Alembic migration (autogenerate + review + apply)
- [x] 1.6 — Sandboxed script engine module (allowlisted builtins/imports, no-I/O enforcement)
- [x] 1.7 — Resource caps enforcement (CPU / memory / wall-time with safe termination)

### Phase 2 — Model-Authored Composition
- [x] 2.1 — ⚠️ Plan-generation composition emission — **reverted**: the base implementation plan stays HIGH-LEVEL (plain step list); no composition authoring, `fully_scripted` decision, or `python_source` emission in the plan prompt. The parser retains forward-compat pass-through but finds nothing to parse. Composition authoring moved to Phase 6 (Optimize & Verify).
- [x] 2.2 — Script Compiler becomes validator/normalizer of model-authored Python
- [x] 2.3 — Remove hardcoded `semantic____render` append from the compiler
- [x] 2.4 — Model-authored script source storage & versioning via CC registry APIs (lifecycle unchanged)
- [x] 2.5 — Composition validation before execution (scripts exist, runnable state, sandbox-compile)

### Phase 3 — Runner Execution of Sandboxed Scripts
- [x] 3.1 — Runner executes sandboxed Python with MCP-only injected CommHubToolClient
- [x] 3.2 — Unconditional LLM fallback on sandbox violations & cap terminations with recorded reason
- [x] 3.3 — Humanized one-line script execution logs (replace truncated JSON blobs)
- [x] 3.4 — `tokens_saved_actual` measurement & persistence
- [x] 3.5 — Verification Engine sandbox-compliance evidence (`sandbox_check_passed`)

### Phase 4 — LLM Mock Layer
- [x] 4.1 — Mock LLM provider registered in the model dispatch layer (scripted mode)
- [x] 4.2 — Record mode: capture real interactions → `llm_mock_recordings` via CC
- [x] 4.3 — Replay mode: deterministic replay keyed by `recording_key`
- [x] 4.4 — Config/env selection of mock vs real providers (test environments only)
- [x] 4.5 — Mock the semantic-bridge CC endpoint path
- [x] 4.6 — Prompt-assertion helpers for tests

### Phase 5 — Tests & CI Wiring
- [x] 5.1 — Backend unit tests: sandbox engine (invariants, caps, escapes fail closed)
- [x] 5.2 — Backend unit tests: composition authoring, validator, render-append removal
- [x] 5.3 — Backend unit tests: runner execution, fallback triggers, token accounting, humanized logs
- [x] 5.4 — Backend unit tests: mock layer (scripted/record/replay, prompt assertions)
- [x] 5.5 — Playwright e2e: zero-LLM agent-execution runs via mock provider
- [x] 5.6 — CI wiring + master docs update

### Phase 6 — Two-Layer Plan Model (Optimized Implementation Plan)
- [x] 6.1 — New `OptimizedImplementationPlan` DB model (FK to `agent_plans.id` + `agent_type_id`, `plan_steps` JSON composition, `fully_scripted`, status generating/ready/failed, timestamps) + Alembic migration
- [x] 6.2 — `OptimizedPlanService` ("Optimize & Verify"): base plan + agent type + user requirement → capability contract → LLM authors the composition → bounded generate → test → refine loop → persist optimized plan + associate/promote the authored script version(s)
- [x] 6.3 — ~~CC API `POST /agents/types/{id}/optimize-plan` (180s server bound) + frontend "Optimize & Verify" button in the Agent Type dialog Preview tab (180s client timeout)~~ — **⚠️ REVERTED (Phase 8)**: the standalone button and endpoint were removed; optimization moved into the Run Agent flow as an opt-in step.
- [x] 6.4 — Execution preference in the Script-First Dispatcher: a fresh (ready AND newer than the base plan) optimized plan supersedes the base plan — `fully_scripted` → zero-LLM script; otherwise scripts are exposed as invocable tools; absent/stale/failed → base-plan LLM path as before. **Bugfix: the optimized-plan lookup resolves BEFORE the serving-script lookup — a legacy auto-compiled fully_scripted serving script can never shadow a fresh optimized plan (only the `optimized-<id8>` artifact serves), and auto-compile skips promotion while a fresh optimized plan exists (candidate stays draft)**
- [x] 6.5 — Optimized-plan composition normalization (bugfix): consecutive scripted segments collapse into ONE chained "Execute workflow script" step per segment group (LLM bridge steps segment the plan; segment outputs feed the next via `context` — `OptimizedPlanService._normalize_composition` / `_synthesize_chained_source`); empty steps dropped; duplicated same-script steps merged; an all-scripted plan whose segments cannot be chained is DEMOTED to tool mode (no-LLM claimed only when deliverable); the authoring prompt mandates one step per script and documents the chaining semantics
- [x] 6.5 — Tests: base-plan prompt is high-level; optimized-plan generation (success / no composition / repair convergence / exhaustion); execution-preference gating

### Phase 6 refinement — result visibility, Optimized-Plan tab, feedback memory
- [x] 6.6 — `verification_log` JSON column (+ migration `93d25e577411`) populated from the refine loop's per-attempt `{attempt, outcome, detail}` outcomes (persisted on ready AND failed plans)
- [x] 6.7 — Verification visibility & honest states (bugfix): refinement exhaustion lands the optimized plan in a distinct `needs_feedback` status (enum value + migration `b7c1d9e2a4f6`) with the last failure in `error` and EVERY attempt (incl. the final run) in `verification_log`; dispatch gating (`get_fresh_optimized_plan`) serves only `status=ready` plans, so `needs_feedback`/`failed` plans never execute; frontend renders the needs_feedback state (warning chip, failure alert, feedback steer prompt)
- [x] 6.7 — Result payload on `POST /agents/types/{id}/optimize-plan` (steps count, scripts authored, fully_scripted, verification log, error) + `GET /agents/types/{id}/optimized-plan`; frontend surfaces a success/error Alert from the payload
- [x] 6.8 — "Optimized Plan" tab (AgentTypeDetailsDialog panel 5, `AgentOptimizedPlanTab.tsx`): steps list with per-step "View script" links (opens the Scripts tab), per-attempt verification log, status
- [x] 6.9 — Verification-gated chaining (minimal steps, product decision): consecutive scripted segments chain into as FEW script invocations as possible in BOTH modes (`fully_scripted` zero-LLM AND tool mode — the chain becomes ONE tool invocation instead of N); the authoring prompt mandates "MINIMIZE THE NUMBER OF STEPS: chain consecutive deterministic work into one script; split only where an LLM bridge is required". When the chained composition fails compile/smoke-run verification, the chain splits at the FIRST FAILING SEGMENT (`OptimizedPlanService._split_failed_chain`, chain registry returned by `_normalize_composition`): the verified prefix re-collapses into ONE chained script, the failing + subsequent segments become individual tool-mode script tools (LLM bridges the gap at runtime), the plan is demoted to `fully_scripted=False`, and the split composition is re-verified with a fresh refine budget — the split reason lands in `verification_log`. `needs_feedback` only when even the split segments cannot be made to work
- [x] 6.10 — Raw optimization log visibility (user report: failed optimize was opaque): the backend persists a `verification_log` entry on EVERY failure path (pre-refine failures — authoring exceptions, empty composition — now append a failed entry before persisting the `failed` row); the frontend auto-opens a raw monospace log dialog (`AgentOptimizeLogDialog`) after optimize completes (success OR failure — on HTTP errors it fetches the persisted log via `GET optimized-plan`), the Optimized Plan tab gains a "View optimization log" reopen button, and a static stage-progress alert shows while the request is in flight
- [x] 6.9 — Feedback loop with memory: `POST /agents/types/{id}/optimize-plan/feedback` (LLM one-shot summary via the model layer → accumulated `{created_at, raw_feedback, summary}` entries in `feedback_comments`); regeneration includes ALL stored comments in the authoring prompt
- [x] 6.11 — Real-outcome signaling for Optimize & Verify (bugfix FIX-20261024-optimize-false-success): `AgentLifecycleHandler.launch` returns `{session_id, triggered, trigger_error}`; ~~`POST .../optimize-plan` marks the optimized plan `failed` (with a failed `verification_log` entry) and returns HTTP 502 when the CH→AR trigger fails (launch exceptions → 422); the frontend gates the success Alert on the side-execution session polling to `completed` with a `ready` persisted plan — a failed/terminated session forces the error Alert even when a stale `ready` plan exists~~ — **⚠️ REVERTED (Phase 8)**: the standalone optimize endpoint, its success/error Alerts, and the side-execution polling in the details dialog were removed together with the button.

## Phase 1 — Sandbox Engine & Schema Foundation

### 1.1 — Add RestrictedPython dependency
Add `RestrictedPython` to `backend/pyproject.toml` (pinned minor version). The tech spec commits to RestrictedPython over WASM alternatives: in-process inside AR, no serialization boundary for MCP calls/model-backed steps, hardened compile/exec model mapping 1:1 to the required invariants.

**Done when:** dependency installs; `pip check` clean; no new runtime services or processes required.

### 1.2 — Extend DB models: `backend/app/db/models/script_registry.py`
Per data-model.md §2: ScriptVersion gains `python_source` (text, nullable), `cpu_limit_seconds`, `memory_limit_mb`, `wall_time_limit_seconds` (int, nullable), `sandbox_validation_status` (enum `pending|passed|failed`, default `pending`), `sandbox_validation_reason` (text, nullable); `declarative_step_graph` stays (deprecated-but-retained). VerificationRun gains `sandbox_check_passed` (bool, nullable). `FallbackTriggerReason` enum gains `sandbox_violation`, `resource_limit_exceeded`. New Python enums: `SandboxValidationStatus`.

**Done when:** models import cleanly; typed enums only; no credential/token-shaped fields; relationships resolve.

### 1.3 — Extend DB models: `backend/app/db/models/script_execution.py`
ScriptExecutionRecord gains `tokens_saved_actual` (int, nullable), `sandbox_termination` (bool, nullable), `sandbox_violation_detail` (text, nullable — one-line human-readable summary, never JSON blobs). `tokens_saved_estimate` retained.

**Done when:** model imports cleanly; new columns nullable (historical rows unaffected).

### 1.4 — New DB models: `backend/app/db/models/llm_mocking.py`
New `LLMMockRecording` per data-model.md §1: `tenant_id` (nullable FK, SET NULL), `session_id` (nullable FK to AgentJob), `recording_key`, `model_identifier`, `interaction_kind` (enum `agent_loop|semantic_bridge|decision_step`), `request_payload`/`response_payload`/`usage_metadata` (JSON), `recorded_by`, timestamps. Indexes on `(tenant_id)`, `(session_id)`, `(recording_key)`. Prompt + response only — never API keys or identity tokens.

**Done when:** model follows the one-domain-per-file pattern; enums typed; exports added to the models package `__init__`.

### 1.5 — Alembic migration
`python -m alembic revision --autogenerate` + review + apply per AGENTS.md. New enum types created via model import; migration uses `postgresql.ENUM(..., create_type=False)`. `fallback_trigger_reason_enum` extension via `ALTER TYPE ... ADD VALUE` with string-formatted DDL (no bound params). Downgrade drops new columns/table; enum-value removal only via the documented enum-rebuild pattern.

**Done when:** `alembic upgrade head` succeeds; `alembic current` matches head; downgrade round-trips on a scratch DB.

### 1.6 — Sandboxed script engine module
New `backend/app/agent_runtime/scripts/sandbox.py`: RestrictedPython-based compile + exec of model-authored Python source. Hardened globals: allowlisted builtins only, `_getattr_`/`_getitem_`/`_write_` guards, no `import` statement (allowlisted modules exposed as pre-bound safe objects). Any disallowed import/attribute access fails closed with a typed, recorded error. MCP tool access exposed to scripts exclusively via the injected `CommHubToolClient` binding.

**Done when:** scripts can compute statistics/derivation/pivot/report assembly; file/network/db/subprocess attempts raise fail-closed errors; unit-testable in isolation from the runner.

### 1.7 — Resource caps enforcement
Per-execution CPU (`signal`/`resource` based CPU-time accounting), memory (`resource.RLIMIT_AS`), and wall-time (asyncio timeout + safe kill) caps, sourced from ScriptVersion limits with platform defaults when null. Breach → safe termination, typed error, details captured for `sandbox_violation_detail`.

**Done when:** a runaway script is terminated within its caps; termination recorded; process/request state unharmed.

## Phase 2 — Model-Authored Composition

### 2.1 — ⚠️ Plan-generation composition emission (reverted — two-layer plan model)
The base implementation plan prompt (`backend/app/services/agents/plan_generation_service.py`) stays HIGH-LEVEL only: a plain ordered step list (action type / name / description). The composition-emission prompt sections (output-requirement contract, execution-semantics `fully_scripted` decision, workflow composition with `python_source`) were **removed**; `user_requirement` plumbing is retained as context. The parser keeps forward-compat pass-through for scriptability marks but the base plan LLM emits none of them. Workflow composition authoring moved to the SEPARATE "Optimize & Verify" flow — see Phase 6.

**Done when:** the base plan prompt contains no composition authoring; the base plan parses as a plain step list; covered by tests.

### 2.2 — Compiler becomes validator/normalizer
Repurpose `backend/app/agent_runtime/scripts/compiler.py`: replace declarative-template generation with validation/normalization of model-authored Python — RestrictedPython compile check, AST safety checks (no I/O constructs, no forbidden names), secret-shape guard, resource-cap annotations → `sandbox_validation_status` outcome with `sandbox_validation_reason` on failure.

**Done when:** valid model scripts pass with normalized output; unsafe scripts fail validation with a recorded reason and stay in draft.

### 2.3 — Remove hardcoded `semantic____render` append
Delete `RENDER_STEP_NAME`/`RENDER_TOOL_NAME`/`_append_render_step` and the unconditional render-step injection from the compiler; workflows contain a summary step only when the model's composition includes one. Update downstream assumptions in `runner.py`/`dispatch.py` (no step is auto-appended).

**Done when:** no code path appends `semantic____render`; compiled compositions run exactly the authored steps; existing tests updated.

### 2.4 — Model-authored source storage & versioning
Submit validated/normalized candidates through the unchanged CC registry APIs (`backend/app/services/script_registry/service.py`, AR client `backend/app/agent_runtime/scripts/cc_client.py`). Lifecycle stays draft → verified → compiled → retired with `repaired_from` lineage; Scripts tab keeps working unchanged.

**Done when:** model-authored versions persist with `python_source`; lifecycle transitions behave exactly as the predecessor's; Scripts tab renders new versions.

### 2.5 — Composition validation before execution
The Script-First Dispatcher validates the composition at execution time: every referenced script exists, is in a runnable lifecycle state, and sandbox-compiles; otherwise record reason and fall back to the LLM path.

**Done when:** stale/retired/failed scripts never execute; fallback reason recorded; no run fails solely because a script failed.

## Phase 3 — Runner Execution of Sandboxed Scripts

### 3.1 — Runner executes sandboxed Python with MCP-only client injection
Extend `backend/app/agent_runtime/scripts/runner.py`: when the serving version carries `python_source`, execute it in the sandbox engine; the script's only external binding is the injected `CommHubToolClient` (same authenticated CH path, dual identities, per-call token injection, script provenance tags). Model-backed steps inside scripts call the semantic-bridge CC endpoint as today (`_run_semantic_bridge_step` path).

**Done when:** sandboxed scripts run end-to-end with tool calls flowing MCP-only; no other egress exists; invocation contract (session identity context) enforced unchanged.

### 3.2 — Unconditional fallback on sandbox failures
Extend `backend/app/agent_runtime/scripts/fallback.py` + `dispatch.py`: sandbox violations, cap terminations (`sandbox_termination=True`), and runtime validation failures trigger the unconditional LLM-path fallback with trigger reason (`sandbox_violation` / `resource_limit_exceeded`) recorded in FallbackEvent.

**Done when:** every sandbox failure mode falls back with a recorded reason; run never fails solely due to script failure.

### 3.3 — Humanized one-line script execution logs
Replace `_brief`-truncated JSON blob log entries (`_ship_log` payloads) with clean one-liners: step name, what ran, what it produced (short natural-language summary, no raw JSON). Sandbox violations use `sandbox_violation_detail` one-liners.

**Done when:** every script execution log entry is a readable one-liner; no truncated JSON in shipped logs; operator-visible in execution logs.

### 3.4 — `tokens_saved_actual` measurement
Record real tokens avoided: measure the reference LLM execution's token usage (from the recorded run that produced the script, or shadow-run reference) and store the difference as `tokens_saved_actual` on ScriptExecutionRecord via the CC execution API.

**Done when:** new script-path execution records carry `tokens_saved_actual` (measured, not estimated); estimates only remain on historical rows.

### 3.5 — Verification sandbox evidence
The Verification Engine (`backend/app/agent_runtime/scripts/verification.py`) shadow-runs sandbox-compliant candidates and records `sandbox_check_passed` on VerificationRun alongside the unchanged comparison outcome.

**Done when:** verification runs on model-authored scripts record sandbox evidence; promotion still gated on comparison verdict.

## Phase 4 — LLM Mock Layer

### 4.1 — Mock provider (scripted mode)
Register a mock LLM provider in the model dispatch layer (`backend/app/services/agents/langchain_model_factory.py`): a `BaseChatModel` implementation returning deterministic, hand-authored responses keyed to expected calls.

**Done when:** agent executions run against scripted mock responses; identical inputs → identical runs.

### 4.2 — Record mode
Capture real LLM request/response pairs (agent loop, semantic bridge, decision steps) during live runs; persist `LLMMockRecording` rows via a CC internal endpoint (AR never touches the DB). Payloads carry prompt + response + usage metadata only.

**Done when:** a recorded run produces replayable recordings; no credentials in any stored payload.

### 4.3 — Replay mode
Replay matches calls by `recording_key` (deterministic function of the request); identical inputs replay identically; unmatched calls fail loudly in tests.

**Done when:** a recorded run replays deterministically end-to-end; prompt assertions pass against stored `request_payload`.

### 4.4 — Config/env selection
Mock vs real provider selection via configuration/env vars (`LLM_MOCK_MODE=scripted|record|replay|off`, recording source config), effective only in test environments; production traffic paths unaffected (default off).

**Done when:** tests select the mock provider purely via env/config; production default unchanged; misconfiguration fails fast.

### 4.5 — Mock the semantic-bridge path
Model-backed script steps call the CC semantic-bridge endpoint (`backend/app/api/v1/internal/system_tools.py` `/internal/.../semantic-bridge`); in tests the CC-side LLM invocation backing this endpoint is served by the same mock layer, so script paths with model-backed steps run zero-LLM.

**Done when:** an execution containing semantic-bridge script steps completes with zero LLM API usage; prompt assertions cover the bridge call.

### 4.6 — Prompt-assertion helpers
Test utilities to assert on prompts sent to the mocked LLM (content, structure, tool schemas) against recorded `request_payload`s.

**Done when:** tests can deterministically assert prompt content/structure; helpers documented and used in Phase 5 tests.

## Phase 5 — Tests & CI Wiring

### 5.1 — Sandbox engine tests
`backend/tests/test_sandbox_engine.py`: allowlist enforcement, no-I/O invariants (fs/network/db/subprocess attempts fail closed), import/attribute escape attempts, cap terminations (cpu/memory/wall-time), determinism.

**Done when:** all invariants from PRD "Sandbox & Scripting" ACs covered and green.

### 5.2 — Composition & validator tests
`backend/tests/test_script_validator.py` (compiler repurposed): model-authored script validation, secret-shape guard, render-append removal regression tests, plan-emission schema parsing.

**Done when:** valid compositions normalize; unsafe/invalid stay draft with reasons; no test relies on the auto-appended render step.

### 5.3 — Runner/fallback/accounting tests
Extend `backend/tests/test_script_runner.py`, `test_script_first_dispatcher.py`, `test_script_security_invariants.py`: sandboxed execution with injected client, fallback trigger set, `tokens_saved_actual` persistence, humanized log assertions, MCP-only boundary (`test_script_mcp_only_boundary.py` updated).

**Done when:** PRD "Observability & Accounting" + fallback ACs covered; security invariant tests pass.

### 5.4 — Mock layer tests
`backend/tests/test_llm_mock_layer.py`: scripted determinism, record→replay round trip, key-matching, semantic-bridge mocking, env/config selection.

**Done when:** PRD "LLM Mocking Framework" ACs covered (all three modes, prompt assertions, determinism).

### 5.5 — Playwright zero-LLM e2e
New e2e under `e2e/tests/`: full agent execution (LLM path and script path with a model-backed step) with the mock provider selected, asserting results and humanized logs — zero LLM API access.

**Done when:** e2e runs green in CI without LLM credentials.

### 5.6 — CI wiring + master docs
Wire mock-mode env into CI workflows; update `docs/master/` per architecture.md §5 and data-model.md §6 (system overview, agent-runtime architecture, observability, security, entities, workflow-compilation docs — removing declarative-transform and hardcoded-render references).

**Done when:** CI runs the new suites; master docs reflect sandboxed scripting, model-authored composition, mock layer, and measured token accounting.

## Phase 6 — Two-Layer Plan Model (Optimized Implementation Plan)

### 6.1 — `OptimizedImplementationPlan` DB model
New `backend/app/db/models/optimized_plan.py` per data-model.md: FK to `agent_plans.id` (the base high-level plan it optimized from) and `agent_type_id`, `plan_steps` (JSON — the authored composition: script segments with `python_source`, LLM bridge steps, output decision), `fully_scripted` (execution-semantics mark), `status` (generating / ready / failed / needs_feedback), `error`, `verification_log`, `generated_at` / `created_at` / `updated_at`. Alembic migration autogenerated, reviewed, applied (`needs_feedback` enum value via `b7c1d9e2a4f6`).

**Done when:** migration applied (`alembic current` = head); relationships resolve; plan regeneration invalidates the optimized plan via the freshness gate.

### 6.2 — `OptimizedPlanService` (Optimize & Verify)
New `backend/app/services/agents/optimized_plan_service.py` (Control Center): takes the base plan + agent type + user requirement, builds the sandbox capability contract, prompts the LLM to author the full composition, normalizes it (collapse per segment group), runs the bounded generate → test → refine loop (compile/validate, smoke-run when `fully_scripted`, repair feedback with the contract — reusing the autocompile refinement machinery), and on success persists the ready optimized plan, retires stale serving versions, and associates/promotes the authored script version(s). Refinement exhaustion persists a `needs_feedback` plan row (last failure in `error`, full per-attempt log in `verification_log`) prompting the user to steer via feedback; other failures persist a `failed` row with a one-line reason.

**Done when:** a ready optimized plan carries the verified composition and a promoted script version; failures never leave a `generating` row behind.

### 6.3 — API + frontend entry point
CC `POST /agents/types/{id}/optimize-plan` (server bound to 180s, matching the frontend client timeout). The Agent Type detail dialog Preview tab gains an "Optimize & Verify" button next to "Regenerate plan" (pending state, error surfacing via the existing dialog error path, cache invalidation on success, all strings via i18n).

**Done when:** the button drives the flow end-to-end; optimization of an agent type without a base plan returns a clear 409.

### 6.4 — Execution preference (dispatcher)
The Script-First Dispatcher consults the optimized plan FIRST (CC internal lookup; freshness = ready AND newer than the base plan, resolved server-side, short-TTL cached), before any serving-script lookup: a `fully_scripted` optimized plan serves only its own optimized-plan end-to-end script (the `optimized-<id8>` artifact — a legacy auto-compiled `auto-<id8>` serving script NEVER shadows it); a tool-mode optimized plan serves no script directly (LLM orchestrates, scripts stay `script____<name>` tools). With no fresh optimized plan the legacy gates apply: a `fully_scripted` serving script runs zero-LLM only while its optimized plan is fresh; otherwise the LLM path. Auto-compile additionally never promotes a candidate while a fresh optimized plan exists (candidate stays draft). An absent, stale, or failed optimized plan — or a regenerated base plan — falls back to the base-plan LLM path exactly as before.

**Done when:** fresh optimized plan → optimized execution; stale/absent/failed → base-plan LLM path; registry unavailability never blocks execution.

### 6.5 — Tests
`backend/tests/test_optimized_plan.py` (base-plan prompt high-level, parse defaults, generation success/no-composition/repair-convergence/exhaustion) and extended `test_script_first_dispatcher.py` (fresh-optimized gating, absence → LLM path, lookup caching/error degradation).

### 6.6–6.9 — Refinement (result visibility / tab / feedback memory)
Migration `93d25e577411` adds `optimized_implementation_plans.verification_log` + `.feedback_comments` (autogenerate reviewed — unrelated pre-existing drift excluded; applied). The service records per-attempt refine-loop outcomes, summarizes feedback one-shot through the model layer (raw-text fallback on failure), accumulates comments, and injects ALL of them into the authoring prompt as "Past User Feedback on Previous Versions". Endpoints: extended `optimize-plan` payload, `GET optimized-plan`, `POST optimize-plan/feedback` (409 when no plan exists). Frontend: `AgentOptimizedPlanTab.tsx` (steps + View-script links + verification log + feedback input), success/error Alert from the optimize result payload, i18n keys under `agents.plan.optimizeSuccess`/`optimizeFailed` and `agents.optimizedPlan.*`.

**Done when:** the two-layer suites are green together with the full scripting suite.

## Completion Checklist

- [x] All Phase 1–5 tasks complete (sequential numbering, no gaps)
- [x] RestrictedPython committed and added to `backend/pyproject.toml`
- [x] Alembic migration autogenerated, reviewed, applied (`alembic current` = head)
- [x] `semantic____render` hardcoding fully removed; no auto-appended steps
- [x] Sandboxed scripts enforce: no I/O, allowlist-only imports, CPU/memory/wall-time caps, MCP-only egress via injected client — all covered by tests
- [x] Model-authored composition stored/versioned in the unchanged registry lifecycle; Scripts tab unaffected
- [x] Unconditional LLM fallback on every sandbox failure mode with recorded reason
- [x] Humanized one-line script execution logs; no truncated JSON blobs
- [x] `tokens_saved_actual` measured and persisted on new script executions
- [x] LLM mock layer (scripted/record/replay) wired to pytest and Playwright with zero-LLM CI runs
- [x] Top-priority rules verified: segregated services, AR-only script execution, CC-only DB access, no credentials to scripts/agents
- [x] `docs/master/` updated per architecture.md §5 and data-model.md §6
- [x] Two-layer plan model: base implementation plan stays high-level; composition lives in the separate `OptimizedImplementationPlan` produced by "Optimize & Verify"; execution prefers a fresh optimized plan and falls back to the base-plan LLM path otherwise

## Phase 7 — Re-scope: "Optimize & Verify" as a command-prompt-driven special agent execution

The bespoke optimizer was replaced with agent-infrastructure reuse. Instead of an in-service LLM authoring prompt + generate → test → refine loop, "Optimize & Verify" is now a **command-prompt-driven special agent execution**.

- [x] **Optimization system tools** (CC-side, routed by CH via the system-tool registry): `get_implementation_plan`, `get_optimized_implementation_plan`, `generate_optimized_plan`, `generate_script` (sandbox-validate then save a draft version), `execute_script` (runs FULL inline `python_source` in AR via `forward_sandboxed_script` — no save required; `script_version_id` path kept for saved versions — the verification primitive), `list_scripts`/`get_script`, and `record_verification`.
- [x] **Inline-source execute + save-on-success flow (refinement)**: `execute_script` gained a `python_source` path (agent keeps the source in its own context and iterates by passing modified source; sandbox compile/violation errors return as structured `{"error": ...}`); `generate_script` is called only AFTER a successful `execute_script` (no draft-first flow); the command mission (`command_prompts.py`) mandates: author → execute FULL source → iterate on source → save only after success, with no defensive layers / name-aliasing lists / defensive error handling and no size/line constraints; command-driven executions (`__command` marker) get a raised guardrail iteration limit (`COMMAND_MAX_ITERATIONS = 40` in `command_prompts.py`, applied command-aware in `_build_guardrail_state`); the execution log keeps the FULL `execute_script` tool input untruncated (`ExecutionLoggingCallback.on_tool_start`) so the drafted source is reviewable per iteration.
- [x] **Command prompt** `optimize-and-verify`: a stored command (new `command_prompts` table, seeded idempotently with an in-code fallback) whose text is the mission + how to use each tool + the rules (minimize steps, chain deterministic work into one script, split only at LLM bridges, verify every script by executing it, bounded 3 attempts, on final failure record `needs_feedback`).
- [x] **Button wiring**: ~~`POST /agents/types/{id}/optimize-plan` now creates a SIDE EXECUTION — an AgentJob whose prompt is the command mission (with agent_type_id interpolated) and whose toolset includes the new system tools; returns the session id for status polling (the 180s timeout is now only a poll ceiling).~~ — **⚠️ REVERTED (Phase 8)**: replaced by the launch-path opt-in flag (see Phase 8).

## Phase 8 — Optimization as an opt-in step of the Run Agent flow

The standalone "Optimize & Verify" button/endpoint was retired. Optimization is now offered inline when the user runs the agent, the optimization run self-reflects before authoring, verification happens against the real integration, and plans can be retired for a redo.

- [x] **Launch opt-in flag**: `AgentJobCreate` gains `optimize: bool`; `launch_agent_session` injects the existing `__command` / `__command_agent_type_id` side-execution markers when set, composing the mission prompt from the `optimize-and-verify` command plus the user's real task (the run accomplishes the real task with real tool calls while authoring/verifying).
- [x] **Self-reflection tools**: new system tools `get_scripts` (script definitions + versions + python_source + sandbox validation + lifecycle) and `get_execution_log` (the agent's recent execution logs, including failures) — CC handlers in `optimization_tools.py`, registered in `SystemToolRegistry`, added to the CH internal allowlist and the command toolset; the command prompt mandates assessing current state FIRST and skipping re-authoring when scripts/logs show nothing wrong and the agent hasn't changed.
- [x] **Real-integration verification**: the command prompt reworked — verification IS the real run (tool calls execute for real, no stub clients); iterate until the scripts achieve the agent's mission, then persist.
- [x] **Retire plan**: `POST /agents/types/{id}/optimized-plan/retire` (`OptimizedPlanService.retire_optimized_plan` deletes the plan rows) + `ScriptRegistryService.retire_serving_versions` so no stale serving script shadows the next run; the Optimized Plan tab gains a "Retire plan" action and an absent/retired hint that the next run will offer optimization again.
- [x] **Standalone surface removal**: `POST /agents/types/{id}/optimize-plan` endpoint, the "Optimize & Verify" buttons, the side-execution polling, and the optimize result Alerts removed from `AgentTypeDetailsDialog`; unused i18n keys removed.
- [x] **Launch dialog opt-in flow**: `AgentJobLaunchDialog` checks for a `ready` optimized plan; absent → opt-in dialog (what optimization does + "Run with optimization" / "Skip optimization"); `optimize` passed through the launch call. All strings via `t()`.
- [x] **Tests**: launch injection (markers + mission + real task preserved; flag-off passthrough), retire endpoint (clears plans, 404 unknown), `get_scripts`/`get_execution_log` tools, allowlist coverage; frontend — direct launch with a ready plan, opt-in dialog (skip → `optimize: false`, opt-in → `optimize: true`), retire call, absent-state hint.

- [x] **Removed bespoke machinery**: `_refine_composition`, `_test_composition`, `_normalize_composition`, `_split_failed_chain`, `_consolidate_steps`, `_synthesize_chained_source` (and the authoring prompt / repair-generator hook) — the agent authors + verifies via tools. Kept: the `OptimizedImplementationPlan` entity + persistence + dispatch-preference gating.
- [x] **Frontend**: button triggers the command execution and shows the session/log UX as a normal run + the raw-log dialog on completion (verification_log from `get_optimized_plan`).
- [x] **Tests**: `test_optimized_plan.py` rewritten to drive the command model (system tools + command prompt + stripped service); dispatch-preference, tool-allowlist, tenant-propagation, and sandbox suites stay green.

### 7.1 — Bugfix: command side executions must bypass script-first dispatch (2026-10-24)

- [x] **Dispatch bypass** (`dispatch.py`): `run_session_script_first` detects the `__command` marker (threaded via `execute.py` `input_data`) and runs the plain LLM loop, skipping serving-script/optimized-plan resolution and auto-compile.
- [x] **Command toolset wiring** (`runtime_executor.py`): `_command_tool_schemas(command)` appends the optimization system tools to the command's LLM toolset (they are not in the agent type's permission-scoped allowed tools).
- [x] **Tests**: `TestCommandExecutionBypass` (dispatcher, 2) + `test_command_execution.py` (executor, 4).

### 7.3 — Malformed tool-name validation, command token budget, retire-keeps-rows + UX refresh (2026-10-25)

- [x] **Malformed tool name never fails a run again** (live defect: `supabase__list_projects`, two underscores → CH 502 `MCP tool not found` → session failed): (a) authoring-time — `execute_script`/`generate_script` AST-extract every literal `tools.call('name', ...)` and check against the agent's actual allowed tool names; mismatch → structured `validation_error` with `invalid_tool_names` + `valid_tool_names` so the LLM repairs in-iteration; (b) runtime — `CommHubToolClientError` escaping the sandbox converts to `ExecutionError` in `ScriptRunner.execute_python_source` → unconditional LLM fallback; (c) mission + capability contract mandate EXACT names with the `____` separator. TDD: `TestScriptToolNameAuthoringValidation` (3) + `TestToolNotFoundRuntimeFallback` (2, written failing first) + mission rule test.
- [x] **Command token budget**: command runs get at least `COMMAND_TOKEN_BUDGET` (default 2,000,000, `COMMAND_TOKEN_BUDGET` env override; larger policy budget wins) — no more bare "execution error: token_budget" failures. TDD: `TestCommandTokenBudget` (3).
- [x] **Retire keeps rows**: `OptimizedPlanStatus.retired` (+ migration `c2d3e4f5a6b7`, applied); `retire_optimized_plan` marks rows retired; regeneration retires the previous row and inserts the new ACTIVE one (one active record per agent type); `get_fresh_optimized_plan` serves only `ready`. TDD: updated `TestRetireOptimizedPlanEndpoint` (rows remain, retired; retired plan never gates execution; regeneration semantics) + `TestFreshOptimizedPlanGating.test_retired_plan_is_never_served`.
- [x] **Retire UX refresh**: `AgentOptimizedPlanTab` retire handler invalidates the whole agent-type query scope (`refetchType: 'all'`) + scripts, so Run Agent immediately shows the opt-in dialog; `OptimizedPlanView.status` gains `retired`. Test: retire invalidation test in `AgentOptimizedPlanTab.test.tsx`.

### 7.2 — Verification-log removal + retire-plan freshness fix (2026-10-24)

- [x] **`verification_log` surface removed** (verification now happens inside the agent's REAL execution — the optimize side-run IS the evidence): the `verification_log` column dropped (migration `a1dbc4760d9a`, applied, `alembic current` = head), `OptimizedPlanService.record_verification` deleted, the `record_verification` system tool + `/internal/system-tools/record-verification` CC endpoint + its CH allowlist entry removed from the command toolset/mission text, `mark_failed` no longer appends log entries, `/optimized-plan` payloads (public + internal) no longer expose `verification_log`. Frontend: the Optimized Plan tab's verification section and the raw-log dialog (`AgentOptimizeLogDialog.tsx` deleted) removed, unused i18n keys dropped. The agent's own in-run verification (execute_script against real integrations) is untouched.
- [x] **Retire-plan freshness fix** (defect: "Retire plan doesn't retire"): the CC retire endpoint/service DID delete the rows — the residual staleness was the Script-First Dispatcher's 60s-TTL `_optimized_plan_cache` / `_serving_cache` in Agent Runtime (no cross-process invalidation on retirement), so the next run within the TTL still used the retired plan/serving script and auto-compile's promotion gate stayed blocked. Lookups are now ALWAYS fresh (caches removed; `reset_serving_cache` kept as a no-op for compat; autocompile's cache-pop step dropped). TDD: `TestRetireFreshness` (2, written failing first) + updated caching tests in `test_script_first_dispatcher.py`.

### 7.3 — Live-defect fixes + UI simplification (2026-10-24)

- [x] **Optimized plan not used on the next run** (root cause: name-based `is_optimized_artifact` gate): the command flow authors scripts under agent-chosen definition names linked via `source_optimized_plan_id`; the dispatcher's `script_definition_name.startswith("optimized-")` check rejected them, so every post-optimization run fell back to the base-plan LLM path. Detection is now lineage-based (`get_serving_version` returns `source_optimized_plan_id`; the `optimized-` name prefix stays a fallback). TDD: `TestOptimizedPlanUsedOnNextRun` (2, mirrors the live state).
- [x] **Command-run output serves the user**: the optimize command mission gained a mandatory "Final answer" section (final message = the user's business result in the required format; optimization details recorded only via tools into the plan record). Regression test: command run with a mocked LLM → session output IS the business result, zero meta-talk.
- [x] **Sandbox = business logic only**: capability contract + command prompt Step 2 state the agent-behalf contract verbatim (`tools.call` = agent identity; `context` = task input + prior outputs; no infra/auth/envelope handling). End-to-end test: minimal business-logic script through the facade with a fake tool client (envelope unwrapped, provenance=script kwargs asserted).
- [x] **UI — Scripts tab removed**: `AgentScriptsTab.tsx` deleted; Optimized Plan per-step "View script" opens the new reusable `ScriptViewDialog` (python_source + description + version) inline; Optimized Plan tab moved to panel index 4; backend APIs unchanged. Tests updated (Scripts tab absent; direct dialog opens).
- [x] **Execution dialog follow-ups (2026-10-24)**: (a) the Result-tab "View agent scripts" button removed from `AgentExecutionDetailsDialog.tsx` (the Scripts tab it targeted no longer exists); (b) a "View agent" button added to the dialog HEADER (`agents.sessions.viewAgent`) that opens `AgentTypeDetailsDialog` for the session's `agent_type_id` on the default Overview tab (`initialTab=0`). TDD: header-link test written failing first (asserts the details dialog opens with `at-42` / tab 0 and the old button is gone).
- [x] **Retire end-to-end regression lock (2026-10-24)**: new test in `TestRetireOptimizedPlanEndpoint` seeds a `ready` plan + compiled serving version via the service, calls the retire endpoint, and asserts the plan rows are gone, `ScriptRegistryService.get_fresh_optimized_plan` returns `None` (dispatcher serving gate), and the serving version is `retired`. Confirms the 7.2 freshness fix holds across the full chain (frontend `AgentOptimizedPlanTab` invalidates the `optimized-plan` + `scripts` query keys after retire).
- [x] **Cert-path + renewal fixes (2026-10-25)**: (a) `execute_script` verification routes CC → CH `/internal/script-tools/forward` (NEW CH endpoint; CC-cert hop) → AR `/internal/script-tools/execute` on CH's own certificate — the old `execute_sandboxed_script` CC→CH `/internal/tools/call` call was architecturally broken (ControlPlaneMiddleware only accepts agent-runtime certs on `/internal/tools/`); `execute_sandboxed_script` removed; (b) CC self-renews its service certificate at startup + daily (`app/core/cc_service_cert_renewal.py`, env `CC_SERVICE_CERT_RENEWAL_DAYS` default 30; re-issues via `issue_service_certificate` with 365-day validity, SAN localhost/127.0.0.1, clientAuth+serverAuth; failures logged, never crash startup).
