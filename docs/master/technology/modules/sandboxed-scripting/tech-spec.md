# Module: sandboxed-scripting — Tech Spec

> Part of the [technology documentation](../../README.md).

## Overview

Model-authored Python scripting with a RestrictedPython sandbox executed exclusively in Agent Runtime, plus the LLM mock layer that makes agent-execution tests zero-LLM. The subsystem spans all three backend services without violating segregation:

- **Agent Runtime**: sandbox engine (`RestrictedPython` compile+exec), script compiler/validator, script runner, script-first dispatcher (with optimized-plan preference), fallback controller, verification engine, generate→test→refine loop, replay-only tool client, the AR script-tool execute endpoint, and the internal live-test run endpoint.
- **Control Center**: script registry REST, DB models (`ScriptVersion`/`ScriptExecutionRecord`/`LLMMockRecording`/`OptimizedImplementationPlan`), the `optimize-and-verify` command (command prompts + optimization system tools), the reference-transcript builder, the authoring-model resolver, and the CC-internal live-test orchestration.
- **Communication Hub**: `script____<name>` virtual-tool routing to AR `/internal/script-tools/execute`, the CC→CH `/internal/script-tools/forward` hop (with the replay contract), and the CC→CH `/internal/live-test/run` relay.
- **Frontend**: "Implementation Plan" and "Optimized Plan" tabs (shared step-tree renderer, per-step script links), the explicit **Optimize** action, and the "Talk to optimizer" conversation entry.

**Sandbox technology**: RestrictedPython (pinned `RestrictedPython~=7.0`). `build_safe_globals()` seeds the runtime globals **wholesale** from RestrictedPython's audited `safe_builtins` baseline instead of maintaining a hand-curated allowlist, then layers only documented guards: `_getattr_` (rejects underscore attributes), `_getitem_`, the full `_write_` guard, `_getiter_`, sequence-length guards for `_unpack_sequence_`/`_iter_unpack_sequence_`, an operator map for `_inplacevar_` (augmented assignment), and `_print_`; `json`/`math`/`statistics` are pre-bound and there is no `import`. Custom additions are limited to the MCP-only tools facade, context binding, and resource caps. Defense in depth: validator (AST scan + secret-shape guard), OS resource caps, and the single injected MCP client are independent layers.

**Compliance**: sandbox runs only in AR; only CC touches PostgreSQL (AR reads/writes everything via mTLS CC REST with signed internal headers); scripts receive no credentials (secret-shape guard at validation; identity-context-only invocation contract; per-call token injection by CH); MCP-only egress — the sandbox exposes exactly one external binding (`tools` facade over `CommHubToolClient`), all other vectors fail closed.

---

## Verification model (replay-only)

Optimization verification never touches live data. `execute_script` — the optimizer's verification primitive — validates a script **only** by replaying the exact reference input and the recorded tool responses of a selected execution:

1. **Capture** — the execution log stores replayable evidence: `tool_call` carries structured `arguments` and an `input` text capped at 10,000 chars; `tool_response` carries a pairing `run_id`, `output` up to 50,000 chars and `output_truncated`; a sandboxed `script_tool_call` event carries the full recorded `result` (JSON, 50,000-char cap) alongside `result_preview`.
2. **Transcript** — `_build_reference_transcript` selects the reference execution (latest completed NORMAL run, or an explicit session) and returns `{session_id, input, input_schema, tool_calls: [{tool, arguments, response}], truncated}`. `script_tool_call` events are preferred; otherwise LLM `tool_call`/`tool_response` entries are paired by `run_id` in call order. Command/current optimization runs are excluded.
3. **Replay execution** — with no recorded tool data, `execute_script` returns a structured `validation_error` and does **not** execute. Otherwise it forwards `reference_tool_responses` + `replay_required=True` through `forward_sandboxed_script` (CC→CH→AR). AR answers every `tools.call` from `ReplayToolClient` (exact tool+arguments match, then the next unconsumed entry for that tool) and fails with a typed sandbox error on a miss. It never falls back to the live session-bound client.
4. **Terminal stop** — when replay cannot proceed, the optimizer receives a terminal `status: "needs_user_input"` result with blockers (`no_reference_tool_data` / `reference_transcript_incomplete`), so it stops and asks the user instead of looping.

Live verification of the **whole script** exists only as an explicit, operator-approved experiment inside an optimization conversation (see [agents — plans & optimization](../agents/plans-optimization.md)). There is no "run with live tools" verification path inside `execute_script`.

---

## Key Components

### Agent Runtime

| Component | Description |
|-----------|-------------|
| Sandboxed Script Engine | `compile_restricted_exec` + `build_safe_globals()` with documented guards only — `_getattr_`, `_getitem_`, full `_write_` guard, `_getiter_`, sequence-length guards, `_inplacevar_` operator map, `_print_`; plus `SandboxToolFacade` (MCP-only sync bridge onto the running loop; re-enters the dispatch task's `contextvars` snapshot so forwarded signed tenant headers attach to sandbox-issued tool calls; awaited tool-call time excluded from the wall-time budget), `unwrap_mcp_tool_result`, and typed errors `SandboxCompileError` / `SandboxViolationError` / `ResourceLimitExceededError` |
| Resource Cap Enforcer | Wall-time daemon-thread deadline loop (counts sandbox-compute time only), `RLIMIT_AS` memory cap; caps from `ScriptVersion` → env → safe fallbacks; breach → typed error (`sandbox_termination=True`) |
| Script Validator | Restricted compile check, AST safety scan, secret-shape guard, `validate_or_raise`; `build_capability_contract` documents the business-logic-only script contract |
| Script Runner | `execute_python_source` whole-script sandbox path; injected-client-only egress; humanized one-line logs; MCP envelope unwrapping; records `tokens_saved_actual`, `sandbox_termination`, `sandbox_violation_detail`; optional `tool_calls_out` sink so the live-test runner can record each `tools.call` |
| Script-First Dispatcher | Pre-execution composition validation; command bypass (`input_data["__command"]` → plain LLM loop); **fresh ready optimized plan supersedes the base plan** (`fully_scripted` → zero-LLM; otherwise scripts-as-tools); absent/stale/failed → base-plan LLM path; lookups always fresh; lineage-based optimized-artifact detection (`source_optimized_plan_id`); the serving path binds the session `input_data` as the sandbox `initial_context` for both the whole-`python_source` and step-graph paths |
| Replay tool client | `ReplayToolClient` answers `tools.call` from the recorded transcript; a miss is a typed error, never a live fallback |
| Fallback Controller | `sandbox_violation` / `resource_limit_exceeded` trigger reasons; unconditional LLM fallback; `sandbox_fields()` on fell-back records; reporting unchanged (`fell_back` + `FallbackEvent`) |
| Verification / capture / repair | Shadow verification of sandbox-compliant candidates (`sandbox_check_passed`); generate → test → refine loop against recorded run data (`_RecordedToolReplayClient`); bounded self-improvement repair (`MAX_REPAIR_ATTEMPTS` = 2) with `RepairAttempt` records and `repaired_from` lineage; autocompile promotion gate (a candidate stays draft while a fresh optimized plan exists) |
| Provenance tagging | AR marks each tool call with `provenance: "script" \| "llm"` + `script_version`; carried through the CH client into CC audit records |
| Tool-name extraction | Shared, DB-free `extract_tools_call_names` / `preview_entries` helpers used by CC authoring/ledger and the AR live-test runner |
| AR script-tool endpoint | `POST /internal/script-tools/execute` — resolves `script____<name>` and runs its `python_source` (or declarative graph) in the sandbox; accepts the replay contract (`reference_tool_responses`, `replay_required`); returns `{"result"}` / `{"error"}` (never a 502) |
| AR live-test endpoint | `POST /internal/live-test/run` — one end-to-end sandbox run of an approved saved script version under the subject's own identity/grants, with a hard wall clock; records each `tools.call` with the ledger pointer; never LLM-driven |

### Control Center

| Component | Description |
|-----------|-------------|
| Script Registry Service | Persists `python_source` + caps + validation fields; `get_serving_version` exposes `script_definition_name` + `source_optimized_plan_id`; `retire_serving_versions(agent_type_id)`; repair bookkeeping; `link_plan_steps_to_version`; lifecycle transitions with 409 on illegal moves; `record_fallback` attributes a fallback to the plan that produced the script and marks it `requires_fix` |
| Optimized Plan Service | Persistence + association behind optimization (the agent authors and verifies compositions via tools). Persists authored steps as-is, merging the final output contract onto the last step; promotes authored scripts to compiled **only** for `ready` plans; feedback memory (all stored feedback entries enter the authoring prompt); persists the failure reason into `error` for `needs_feedback` and `mark_failed`; `mark_requires_fix` writes `requires_fix` + an `execution_derived` feedback entry targeting the attributed plan; `retire_optimized_plan` marks rows `retired` (never deleted; exactly one active record per agent type; `get_fresh_optimized_plan` serves only `ready`) |
| Authoring-model resolver | One tenant-scoped source of the workspace authoring model (`AuthoringModelState` / `require_authoring_model`), wrapping the `workflow_generation_model_id` setting + `ModelBindingLayer.resolve_model_config`; no fallback to the agent's runtime model or an arbitrary config |
| Plan generation service | Authors the base implementation plan with the authoring model via `complete_from_context`; explicit `regenerate-plan` only (no background scheduling on save); failed attempts preserve the last successful steps/topology/hash; `_enforce_step_types` reclassifies non-entity typed steps to `processing` and preserves optional explicit references |
| Optimization System Tools | `get_implementation_plan` (auto-generates a missing base plan), `get_optimized_implementation_plan`, `generate_optimized_plan`, `generate_script`, `execute_script`, `list_scripts`, `get_scripts`, `get_script`, `get_execution_log`; registered as standard system tools routed by CH; `generate_optimized_plan` enforces the authoring allow-list (`ready` / `failed` / `needs_feedback`) and persists the caller-supplied `error`; `execute_script` is replay-only; every optimization handler applies the subject guard for optimization conversations |
| Reference transcript builder | Shared reference selection + transcript construction used by `get_execution_log` and `execute_script`; returns the reference input, typed `input_schema`, bounded text log and the `tool_calls` replay window |
| Command Prompts | Stored mission text for `optimize-and-verify` (seeded idempotently with in-code fallback): mandatory pre-authoring self-reflection in a fixed order (`get_scripts` → `get_execution_log` → `get_optimized_implementation_plan` → `get_implementation_plan`), explicit skip-when-healthy rule, REPLAY-only verification, no invention of tool calls absent from the transcript, mandatory "Final answer" section, mandatory `needs_feedback` + `error` on terminal authoring failure; `COMMAND_TOKEN_BUDGET` (default 2,000,000) |
| Live-test orchestration | CC consumes a single-use approval, loads the approved version's `python_source` + reference input, forwards through CH, persists the script run record and carries it into the resume value |
| LLM Mock Provider | `MockChatModel` (`BaseChatModel` subclass) registered in `LangChainModelFactory`; modes scripted/record/replay; `compute_recording_key`; production default off (`LLM_MOCK_MODE`) |
| Mock Recording API | CC internal `POST/GET /internal/llm-mock/recordings` (batch upsert idempotent per `recording_key`; credential-shaped fields rejected 422); mTLS service-cert only |
| String output plumbing | `output_data` accepts a plain string (raw script render output) end-to-end: AR completion → CC status/result endpoints → session reads |

### Communication Hub

| Component | Description |
|-----------|-------------|
| Script-tool routing | `_route_to_script_tool` forwards `script____<name>` invocations to AR `POST /internal/script-tools/execute` with the session's agent identity; unwraps `{"result"}`/`{"error"}`; provenance tagging unchanged |
| Script forwarding | `POST /internal/script-tools/forward` (CC → CH hop) forwards inline `python_source` **and the replay contract** (`reference_tool_responses`, `replay_required`) to AR using CH's own service certificate |
| Live-test forwarding | `POST /internal/live-test/run` (CC → CH hop) forwards the approved script payload verbatim; CH performs no authorization of its own beyond the existing control-plane checks |

### Frontend

| Component | Description |
|-----------|-------------|
| `AgentOptimizedPlanTab` | Optimized Plan tab: compact entry (optimizer model + "Talk to optimizer" + help), plan status/feedback, `requires_fix` chip + alert + re-optimize, `needs_feedback` warning with blocker + replay-only note, absent "nothing to optimize yet" state, retire (success / "nothing to retire" / disabled) |
| `PlanStepTree` | Shared step-tree renderer (flat steps with optional `parent_order` nesting, action icons, type chips) used by the base plan, the preview modal and the optimized plan |
| `AgentPlanContent` / `PlanPreviewModal` | Base-plan rendering and preview; per-step "View script" on `script_version_id` steps |
| `OptimizationHelpDialog` | "What optimization does / how to interact" help (runs as this agent, replay-only, live test needs approval, ask-and-stop) |
| `AgentOptimizeAction` | One-shot Optimize trigger (self-hides for conversational agents; disabled with the localized backend reason; failures surface as a snackbar) |
| Registry hooks | `frontend/src/hooks/useScripts.ts`: `useScripts`, `useScriptVersions`, `useScriptVerifications`, `useScriptFallbacks`, `useScriptRepairs`, `useScriptHealth`, `usePromoteScriptVersion`, `useRetireScriptVersion` — consume the CC `/api/v1/scripts` REST surface; resource type `agent::scripts` registered in both manifests |
| Types / chips | `frontend/src/types/scripts.ts`: `python_source` presence + sandbox-validation fields; `AgentJob.output_data` widened to `Record \| string` |

> **Retired (do not reference):** the opt-in "Run with optimization" / "Skip optimization" launch dialog and the `AgentJobCreate.optimize` flag; the standalone Scripts registry tab; the verification-log dialog; the standalone `POST /agents/types/{id}/optimize-plan` endpoint.

---

## Script Execution Outcomes

`ScriptExecutionRecord.outcome` is the append-only audit classification persisted by Control Center from Agent Runtime execution reports.

| Outcome | Meaning | Writer today |
|---|---|---|
| `success` | Script completed and produced a usable result (AR reports it on the script path) | Yes |
| `fell_back` | Script path failed and execution degraded to the LLM path | Yes |
| `validation_failure` | Reserved for a script rejected by compile/sandbox validation | No app-code writer |
| `partial_failure` | Reserved for a "successful" envelope whose tool results were semantically unusable | **No** |

> **Deferred by product decision (do not assume automation).** The `partial_failure` enum value and its migration exist, but **nothing writes it yet**. Semantic-error detection inside successful tool envelopes, and the corresponding fallback / repair / re-optimization reactions, were explicitly deferred. Scripts are expected to handle unexpected tool-result shapes defensively; the UI does not infer partial failure.

---

## Code Reference Map

All paths verified in the workspace.

### Agent Runtime (`backend/app/agent_runtime/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Sandbox engine (`build_safe_globals`, guards, caps) + `build_capability_contract` + `unwrap_mcp_tool_result` | module | Globals seeded wholesale from RestrictedPython `safe_builtins`; documented guards; resource caps; fail-closed typed errors; MCP-only `SandboxToolFacade` | `backend/app/agent_runtime/scripts/sandbox.py` |
| Composition schemas | module | `StepKind.script_segment` + `ScriptSegmentStep`; `CompositionSegment`/`WorkflowComposition`; legacy StepGraph retained | `backend/app/agent_runtime/scripts/schemas.py` |
| `ScriptValidator` | module | Restricted compile, AST scan, secret-shape guard | `backend/app/agent_runtime/scripts/compiler.py` |
| `ScriptRunner.execute_python_source` | module | Sandboxed execution, humanized logs, envelope unwrapping, accounting fields, optional per-call sink | `backend/app/agent_runtime/scripts/runner.py` |
| `run_session_script_first` | function | Optimized-plan preference, command bypass, always-fresh lookups, lineage detection, `initial_context` binding | `backend/app/agent_runtime/scripts/dispatch.py` |
| Fallback classification | module | `sandbox_violation`/`resource_limit_exceeded`; `sandbox_fields()` | `backend/app/agent_runtime/scripts/fallback.py` |
| Verification shadow runs | module | `sandbox_check_passed` evidence | `backend/app/agent_runtime/scripts/verification.py` |
| Generate→test→refine / repair | modules | `_RecordedToolReplayClient`, `set_script_repair_generator`, promotion gate, `MAX_REPAIR_ATTEMPTS`, `repaired_from` lineage | `backend/app/agent_runtime/scripts/capture.py`, `autocompile.py`, `repair.py` |
| Post-run autocompile hook | function | Fire-and-forget `schedule_autocompile` on LLM-path completion | `backend/app/agent_runtime/api/execute.py` |
| Mock-recording + script-tool client | module | `submit_mock_recordings` / `get_mock_recording`; `get_script_tool` | `backend/app/agent_runtime/scripts/cc_client.py` |
| AR script-tool execute endpoint | module | `POST /internal/script-tools/execute` incl. `ReplayToolClient` and the replay contract | `backend/app/agent_runtime/api/script_tools.py` |
| AR live-test endpoint | module | `POST /internal/live-test/run` — one approved-script run, grant pre-check, per-call recording | `backend/app/agent_runtime/api/live_test.py` |
| Execution trigger | module | Threads `input_data` through to the dispatcher (command marker) | `backend/app/agent_runtime/api/execute.py` |
| Command toolset wiring | module | `_command_tool_schemas(command)` derives optimization-tool schemas; `_build_guardrail_state` applies `COMMAND_TOKEN_BUDGET`; repeat guard enabled for command/optimization turns | `backend/app/services/agents/runtime_executor.py` |
| Tool-name extraction | module | `extract_tools_call_names`, `preview_entries` (shared with CC) | `backend/app/services/agents/script_tool_names.py` |

### Control Center (`backend/app/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Plan generation (explicit only) | module | Authoring-model `complete_from_context`, failure preserves last success, step-type enforcement | `backend/app/services/agents/plan_generation_service.py` |
| Authoring-model resolver | module | `AuthoringModelState`, `require_authoring_model`, reason codes; CC-only | `backend/app/services/agents/workflow_generation_settings.py` |
| Model dispatch | module | `get_model` returns the mock provider when `LLM_MOCK_MODE` active; `build_completion_context` helper | `backend/app/services/agents/langchain_model_factory.py`, `backend/app/services/agents/model_binding.py` |
| Mock provider | module | `MockChatModel`, `compute_recording_key`, sinks, prompt-assertion helpers | `backend/app/services/agents/llm_mock_provider.py` |
| Optimized plan service | module | Authored-plan persistence + association, feedback memory, `error` persistence, `mark_requires_fix`, `retire_optimized_plan` | `backend/app/services/agents/optimized_plan_service.py` |
| Command prompts + budget | module | `optimize-and-verify` mission (replay-only, pre-authoring read order, skip-when-healthy, mandatory `error`) | `backend/app/services/agents/command_prompts.py` |
| Optimization system tools | module | Replay-only `execute_script`; reference transcript; authoring allow-list; subject guard | `backend/app/api/v1/internal/optimization_tools.py` |
| Registry + request-live-test tool | module | `request_live_test` registration; optimization tool schemas | `backend/app/services/agents/system_tool_registry.py` |
| Script registry service | module | `record_fallback` → plan attribution → `requires_fix`; serving-version/plan lookups; repair bookkeeping | `backend/app/services/script_registry/service.py` |
| DB models | module | ScriptDefinition/ScriptVersion (+ `repaired_from_id`), VerificationRun, FallbackEvent, RepairAttempt; `ScriptExecutionOutcome.partial_failure` (no writer); ScriptExecutionRecord accounting; `LLMMockRecording`; `OptimizedImplementationPlan` (+ `requires_fix`) | `backend/app/db/models/script_registry.py`, `script_execution.py`, `llm_mocking.py`, `optimized_plan.py` |
| Registry REST API | module | CRUD, versions + diff, promote/retire, verifications/fallbacks/repairs/health, executions, cost reports | `backend/app/api/v1/scripts.py`, `backend/app/schemas/scripts.py` |
| CC internal scripts API | module | `GET /serving-version`, `GET /versions/{vid}`, candidates, verifications, fallbacks, executions, repairs, promote, LLM reference; AR service-cert only | `backend/app/api/v1/internal/scripts.py` |
| Plan-step script links | module | `PlanStepRead.script_definition_id` / `script_version_id` stamped via `link_plan_steps_to_version` | `backend/app/schemas/agents.py` |
| REST APIs | module | Optimized-plan get/feedback/retire, plan regeneration, optimization gate; no run-mode optimization flag | `backend/app/api/v1/agents.py` |
| CC internal APIs | module | Mock recordings, semantic-bridge mock routing, string `output_data`, live-test run dispatch | `backend/app/api/v1/internal/llm_mocking.py`, `system_tools.py`, `session_data.py`, `backend/app/services/control_center/comm_hub_client.py` |
| Execution-log capture | module | Tool-call arguments/`run_id` capture; 10,000/50,000-char caps and truncation flags (the replay source) | `backend/app/services/agents/execution_logging_callback.py` |
| Migrations | applied | Sandbox/mock fields; optimized plan + `retired`; registry + execution tables (`a1b2c3d4f5e6`); repair tables + `repaired_from_id` + `identity_parity_confirmed` (`b2c3d4e5f6a7`); script session FK repoint (`c3d4e5f6a7b8`); `partial_failure` enum value (`e4f66f7c7f1c`); `requires_fix` enum value (`a7b8c9d0e1f2`) | `backend/alembic/versions/` |
| Dependency | pyproject | `RestrictedPython~=7.0` | `backend/pyproject.toml` |

### Communication Hub (`backend/app/communication_hub/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Script-tool routing + forwarding | module | `_route_to_script_tool` → AR execute; `/internal/script-tools/forward` carries the replay contract | `backend/app/communication_hub/api/internal/tool_routing.py`, `backend/app/communication_hub/api/internal/script_forwarding.py` |
| Live-test forwarding | module | `POST /internal/live-test/run` CC → AR relay | `backend/app/communication_hub/api/internal/live_test_forwarding.py` |

### Frontend (`frontend/src/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Optimized Plan tab | component | Entry, status/feedback, `requires_fix` alert + re-optimize, `needs_feedback` blocker, retire states | `frontend/src/components/agents/AgentOptimizedPlanTab.tsx` |
| Optimization help dialog | component | Interaction model help | `frontend/src/components/agents/OptimizationHelpDialog.tsx` |
| Step tree | component | Shared nested step renderer (base/preview/optimized) | `frontend/src/components/agents/PlanStepTree.tsx` |
| Base plan / preview | components | Plan content, per-step script links, preview modal | `frontend/src/components/agents/AgentPlanContent.tsx`, `frontend/src/components/agents/PlanPreviewModal.tsx` |
| Optimize action | component | One-shot Optimize trigger + localized gate reason | `frontend/src/components/agents/AgentOptimizeAction.tsx` |
| Script view dialog | component | Inline python_source/description/version viewer | `frontend/src/components/agents/ScriptViewDialog.tsx` |
| Registry hooks | hooks | `useScripts`, `useScriptVersions`, `useScriptVerifications`, `useScriptFallbacks`, `useScriptRepairs`, `useScriptHealth`, `usePromoteScriptVersion`, `useRetireScriptVersion` | `frontend/src/hooks/useScripts.ts` |
| Types + i18n | module | `python_source`/sandbox fields; `output_data: Record \| string`; `agents.scripts.*`, `agents.optimizedPlan.*`; `agent::scripts` in both manifests | `frontend/src/types/scripts.ts`, `frontend/src/i18n/locales/en.json`, `frontend/src/constants/resourceTypes.ts` |
| Output rendering | component | Raw-output fallback for typed runs whose validation failed | `frontend/src/components/executions/OutputTypeResultTab.tsx` |

### Tests

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Sandbox engine tests | backend test | Baseline guards (`_unpack_sequence_`, `_iter_unpack_sequence_`, `_inplacevar_`, attribute/item/write) | `backend/tests/test_sandbox_engine.py` |
| Script runner tests | backend test | Sandbox path, envelope unwrapping, accounting, detailed per-call records | `backend/tests/test_script_runner.py` |
| Dispatcher tests | backend test | Optimized-plan preference, command bypass, `initial_context` binding | `backend/tests/test_script_first_dispatcher.py` |
| Optimized-plan / replay tests | backend test | Reference transcript, `ReplayToolClient`, replay-only `execute_script`, `mark_requires_fix`, feedback tagging | `backend/tests/test_optimized_plan.py` |
| Script-tool execute tests | backend test | `replay_required` never builds a live client; miss/absent transcript → structured error | `backend/tests/agent_runtime/test_script_tool_execute.py` |
| CH forwarding tests | backend test | Replay contract forwarded verbatim CC→CH→AR | `backend/tests/communication_hub/test_script_forwarding.py` |
| Live-test forwarding + runner tests | backend test | CH relay and AR approved-script run (grant pre-check, recording, cap) | `backend/tests/communication_hub/test_live_test_forwarding.py`, `backend/tests/test_optimization_live_test_runner.py` |
| Execution-log bounds tests | backend test | Reference selection, caps, transcript window | `backend/tests/test_execution_log_bounds.py` |
| Script registry service tests | backend test | Fallback attribution, retired exclusion, serving predicate | `backend/tests/test_script_registry_service.py` |
| Tenant-isolation sweep | backend test | Script model coverage + `command_prompts` registry entry | `backend/tests/test_tenant_isolation_sweep.py` |
| Optimized Plan tab test | frontend test | `requires_fix` / `needs_feedback` alerts, re-optimize, retire states | `frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx` |
| Step tree test | frontend test | Nested `parent_order` tree and script action rendering | `frontend/src/__tests__/PlanStepTree.test.tsx` |

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `SANDBOX_WALL_TIME_SECONDS` / `SANDBOX_CPU_SECONDS` / `SANDBOX_MEMORY_LIMIT_MB` | Sandbox default resource caps (per-script ScriptVersion caps win) |
| `LLM_MOCK_MODE` / `LLM_MOCK_RECORDING_SET` | Activate the mock LLM provider (scripted/record/replay) for tests; production default off |
| `COMMAND_TOKEN_BUDGET` | Minimum token budget for command-driven special executions (default 2,000,000) |
| `OPTIMIZER_LIVE_TEST_*` (settings: decision TTL, approved cap, run timeout, operation timeout, sweep interval) | Bounds for operator-approved live script tests; all clamped to ≥ 1 |

---

## Tests

See `docs/master/qa/test-plans/sandboxed-scripting-test-plan.md` — sandbox security, validator, mock layer, refinement loop, optimized plan, replay-only verification, live-test approval, command execution, dispatch, allowlist coverage guard, and the zero-LLM e2e suites.
