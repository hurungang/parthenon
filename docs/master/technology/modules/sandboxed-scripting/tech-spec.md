# Module: sandboxed-scripting — Tech Spec

## Overview

Model-authored Python scripting with a RestrictedPython sandbox executed exclusively in Agent Runtime, plus the LLM mock layer that makes agent-execution tests zero-LLM. The subsystem spans all three backend services without violating segregation:

- **Agent Runtime**: sandbox engine (`RestrictedPython` compile+exec), script compiler/validator, script runner, script-first dispatcher (with optimized-plan preference), fallback controller, verification engine, generate→test→refine loop, AR internal script-tool execute endpoint.
- **Control Center**: script registry REST, DB models (ScriptVersion/ScriptExecutionRecord/LLMMockRecording/OptimizedImplementationPlan), the `optimize-and-verify` command (command prompts + optimization system tools), the command-driven Optimized Plan service, and the CC-internal LLM mock recordings API.
- **Communication Hub**: `script____<name>` virtual-tool routing to AR `/internal/script-tools/execute` (and the CC→CH `/internal/script-tools/forward` hop).
- **Frontend**: "Optimized Plan" tab (steps with "View script" links via the inline `ScriptViewDialog`, feedback, retire), opt-in "Run with optimization" launch dialog.

**Sandbox technology**: RestrictedPython (pinned `RestrictedPython~=7.0` in `backend/pyproject.toml`). `build_safe_globals()` seeds the runtime globals **wholesale** from RestrictedPython's audited `safe_builtins` baseline instead of maintaining a hand-curated allowlist, then layers only documented guards: `_getattr_` (rejects underscore attributes), `_getitem_`, the full `_write_` guard, `_getiter_`, sequence-length guards for `_unpack_sequence_`/`_iter_unpack_sequence_`, an operator map for `_inplacevar_` (augmented assignment), and `_print_`; `json`/`math`/`statistics` are pre-bound and there is no `import` statement. Custom additions are limited to the MCP-only tools facade, context binding, and resource caps. Defense in depth: validator (AST scan + secret-shape guard), OS resource caps, and the single injected MCP client are independent layers.

**Compliance**: sandbox runs only in AR; only CC touches PostgreSQL (AR reads/writes everything via mTLS CC REST with signed internal headers); scripts receive no credentials (secret-shape guard at validation; identity-context-only invocation contract; per-call token injection by CH); MCP-only egress — the sandbox exposes exactly one external binding (`tools` facade over `CommHubToolClient`), all other vectors fail closed.

---

## Key Components

### Agent Runtime

| Component | Description |
|-----------|-------------|
| Sandboxed Script Engine | `compile_restricted_exec` + `build_safe_globals()` (globals seeded wholesale from RestrictedPython's `safe_builtins` baseline; no `import`; `json`/`math`/`statistics` pre-bound) with documented guards only — `_getattr_` (underscore attributes rejected), `_getitem_`, full `_write_` guard, `_getiter_`, `_unpack_sequence_`/`_iter_unpack_sequence_` length guards, `_inplacevar_` operator map, `_print_`; plus `SandboxToolFacade` (MCP-only, sync bridge onto the running loop; re-enters the dispatch task's `contextvars` snapshot so forwarded signed tenant headers attach to sandbox-issued tool calls; awaited tool-call time excluded from the wall-time budget), `unwrap_mcp_tool_result` envelope unwrapping, typed errors `SandboxCompileError`/`SandboxViolationError`/`ResourceLimitExceededError` |
| Resource Cap Enforcer | Wall-time daemon-thread deadline loop (counts only sandbox-compute time), `RLIMIT_AS` memory cap; caps from ScriptVersion → env (`SANDBOX_WALL_TIME_SECONDS`/`SANDBOX_CPU_SECONDS`/`SANDBOX_MEMORY_LIMIT_MB`) → safe fallbacks; breach → typed error (`sandbox_termination=True`) |
| Script Validator (compiler.py) | Restricted compile check, AST safety scan, secret-shape guard, `validate_or_raise`; hardcoded `semantic____render` append (`_append_render_step`) **removed**; `build_capability_contract` documents the business-logic-only script contract |
| Script Runner | `execute_python_source` whole-script sandbox path; injected-client-only egress; humanized one-line logs (no JSON blobs); MCP envelope unwrapping in `_run_tool_step`; records `tokens_saved_actual`, `sandbox_termination`, `sandbox_violation_detail` |
| Script-First Dispatcher | Pre-execution composition validation; command bypass (`input_data["__command"]` → plain LLM loop, no script dispatch); **fresh ready optimized plan supersedes the base plan** (`fully_scripted` → zero-LLM; otherwise scripts-as-tools); absent/stale/failed → base-plan LLM path; lookups ALWAYS fresh (60s cache removed); lineage-based optimized-artifact detection (`source_optimized_plan_id`, legacy `optimized-` prefix accepted); a legacy `auto-<id8>` compiled script never shadows a fresh optimized plan; tool-mode plans serve no script |
| Fallback Controller | Adds `sandbox_violation` / `resource_limit_exceeded` trigger reasons; unconditional LLM fallback (a run never fails solely because a script failed); `sandbox_fields()` on fell-back records |
| Verification Engine | Shadow-runs sandbox-compliant candidates; records `sandbox_check_passed` evidence |
| Capture/Autocompile/Repair | Generate → test → refine loop: compositions tested against recorded run data (`_RecordedToolReplayClient`), failures fed (with the capability contract) to the injectable repair generator for ≤ `MAX_SCRIPT_REFINEMENT_ATTEMPTS` (3); first passing script promoted, exhaustion promotes NOTHING; autocompile promotion gate — candidate stays draft while a fresh optimized plan exists |
| Self-improvement repair loop | Bounded defect-repair after automation failure (`MAX_REPAIR_ATTEMPTS` = 2): failure diagnosis → LLM-produced repaired candidate submitted as a new draft version with `repaired_from` lineage + a `RepairAttempt` record in CC → re-verification → bounded retry; exhaustion degrades to the LLM path. Reported to CC via the internal repairs endpoints |
| Provenance tagging | AR marks each tool call with `provenance: "script" \| "llm"` + `script_version` (script-path calls excluded from capture); carried through the CH client into CC audit records |
| AR script-tool endpoint | `POST /internal/script-tools/execute` — resolves `script____<name>` via `get_script_tool` and runs its `python_source` (or declarative graph) in the sandbox with a session-bound MCP-only client; returns `{"result": ...}` / `{"error": ...}` (never a 502) |

### Control Center

| Component | Description |
|-----------|-------------|
| Script Registry Service | Persists `python_source` + caps + validation fields; `get_serving_version` exposes `script_definition_name` + `source_optimized_plan_id` (prefers the optimized-plan-linked definition); `retire_serving_versions(agent_type_id)` called from `regenerate-plan`; repair bookkeeping (`create_repaired_candidate`, `record_repair_attempt`, `update_repair_outcome`, `list_repairs`); `link_plan_steps_to_version` stamps `script_definition_id`/`script_version_id` onto matching `AgentPlan.plan_steps` entries when a version is compiled from the definition's source plan; lifecycle transitions (`transition_version`) enforce verification-passing guards with 409 on illegal moves |
| Optimized Plan Service | Thin persistence + association layer behind the `optimize-and-verify` command (the agent authors and verifies compositions via tools; legacy normalization/refine machinery removed). Persists the authored steps as-is, merging the final output contract onto the last step; promotes authored scripts to compiled **only** for `ready` plans (a failed/`needs_feedback` plan never leaves a serving artifact); feedback memory (all stored feedback summaries included in the authoring prompt); **failure-reason persistence** — a `needs_feedback` authoring outcome and a `mark_failed` trigger failure both write the reason into the plan's existing `error` column so the UI can surface it; `retire_optimized_plan` MARKS rows `retired` (kept for reference, never deleted; exactly one active record per agent type; `get_fresh_optimized_plan` serves only `ready`) |
| Optimization System Tools | `get_implementation_plan`, `get_optimized_implementation_plan`, `generate_optimized_plan`, `generate_script`, `execute_script`, `list_scripts`, `get_scripts`, `get_script`, `get_execution_log` — registered as standard system tools routed by CH; `generate_optimized_plan` persists the caller-supplied `error` reason (used on `needs_feedback`); `execute_script` accepts FULL inline `python_source` (no save required) and routes EVERY execution through `CommunicationHubClient.forward_sandboxed_script` (CC → CH `/internal/script-tools/forward` → AR `/internal/script-tools/execute`; the old CC→CH `/internal/tools/call` path was rejected — `ControlPlaneMiddleware` only accepts AR certs there); **malformed tool-name validation**: every literal `tools.call('name', ...)` AST-checked against the agent's actual allowed tool names; mismatch → `validation_error` with valid names; `generate_script` only after a successful `execute_script` (save-on-success) |
| Command Prompts | Stored mission text for the `optimize-and-verify` command (seeded idempotently with in-code fallback); **mandatory pre-authoring self-reflection in a fixed order** — `get_scripts` → `get_execution_log` (including past failures) → `get_optimized_implementation_plan` → `get_implementation_plan` (base-plan steps are the sole source of WHAT the workflow must do); explicit **skip-when-healthy** rule (re-author only for no ready plan, failing scripts, repeated execution errors, or a changed base plan); mandates verification against REAL tool executions and a mandatory "Final answer" section (the final message IS the business result — no meta-commentary); on terminal authoring failure the mission REQUIRES calling `generate_optimized_plan` with status `needs_feedback` and a concise `error` reason (shown to the user); `COMMAND_TOKEN_BUDGET` (default 2,000,000, env-overridable) guarantees command runs a generous dedicated token budget |
| LLM Mock Provider | `MockChatModel` (`BaseChatModel` subclass) registered in `LangChainModelFactory`; modes scripted/record/replay; `compute_recording_key` (SHA-256 of kind+model+serialized messages); deterministic; production default off (`LLM_MOCK_MODE`) |
| Mock Recording API | CC internal `POST/GET /internal/llm-mock/recordings` (batch upsert idempotent per `recording_key`; credential-shaped fields rejected 422); mTLS service-cert only; AR never touches the DB |
| Semantic-Bridge Endpoint | `/internal/.../semantic-bridge` backing LLM invocation routes through the mock layer when mock mode is active → model-backed script steps run zero-LLM |
| String output plumbing | `output_data` accepts a plain string (raw script render output) end-to-end: AR `mark_session_completed(dict \| str)` → CC status/result endpoints → session reads |

### Communication Hub

| Component | Description |
|-----------|-------------|
| Script-tool routing | `_route_to_script_tool` forwards `script____<name>` invocations to AR `POST /internal/script-tools/execute` with the session's agent identity (`session_id` + `agent_type_id` + `tool_args`); `{"result"}`/`{"error"}` unwrapped into the `call_tool` contract; provenance tagging unchanged |
| Script forwarding | `POST /internal/script-tools/forward` (CC → CH hop) forwards inline `python_source` to AR using CH's own service certificate |

### Frontend

| Component | Description |
|-----------|-------------|
| `AgentOptimizedPlanTab.tsx` | "Optimized Plan" tab (panel index 4): steps list with per-step "View script" links (open the reusable inline `ScriptViewDialog` — python_source + description + version), status/error surfacing, feedback textarea + submit (one-shot-LLM-summarized), "Retire plan" action (marks rows `retired`; invalidates the whole agent-type query scope so the launch dialog immediately re-offers optimization); **persisted `error` alert** — shown for `failed` (error severity) and `needs_feedback` (warning severity) plans, with a separate `needs_feedback` prompt; **retire feedback** — success alert after retiring, "nothing to retire" info alert when the plan is already `retired`, and the retire button disabled when no plan exists or it is `retired`; absent state shows the "next run offers optimization" hint |
| `AgentJobLaunchDialog.tsx` (pages/agents) | Optimized-plan existence check + opt-in dialog ("Run with optimization" / "Skip optimization"); `optimize` passed through the launch call; a `ready` plan launches directly without the dialog |
| `AgentTypeDetailsDialog.tsx` | 5 tabs (Details=0, Preview=1, Execution Logs=2, Sessions=3 conversation-only, Optimized Plan=4); no standalone Scripts tab; "View agent" header link opens the dialog on the default tab |
| Plan-step script links | `AgentPlanContent.tsx` renders a per-step "View script" link for steps carrying `script_version_id` (opens the inline `ScriptViewDialog`, or switches the parent dialog to the Optimized Plan tab); backed by `PlanStepRead.script_definition_id`/`script_version_id` on the plan response |
| Registry hooks | `frontend/src/hooks/useScripts.ts`: `useScripts`, `useScriptVersions`, `useScriptVerifications`, `useScriptFallbacks`, `useScriptRepairs`, `useScriptHealth`, `usePromoteScriptVersion`, `useRetireScriptVersion` — consume the CC `/api/v1/scripts` REST surface; i18n keys under `agents.scripts.*`; resource type `agent::scripts` registered in both `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts` |
| Types / chips | `frontend/src/types/scripts.ts`: `python_source` presence + sandbox-validation fields; `AgentJob.output_data` widened to `Record \| string` (raw string output rendered as text) |

---

## Script Execution Outcomes

`ScriptExecutionRecord.outcome` is the append-only audit classification persisted by Control Center from Agent Runtime execution reports.

| Outcome | Meaning | Writer today |
|---|---|---|
| `success` | Script completed and produced a usable result (AR reports it on the script path) | Yes |
| `fell_back` | Script path failed and execution degraded to the LLM path | Yes |
| `validation_failure` | Reserved for a script rejected by compile/sandbox validation | No app-code writer |
| `partial_failure` | Reserved for a "successful" envelope whose tool results were semantically unusable | **No** |

> **Deferred by product decision (do not assume automation).** The `partial_failure` enum value and its migration exist, but **nothing writes it yet**. Semantic-error detection inside successful tool envelopes, and the corresponding fallback / repair / re-optimization reactions, were explicitly deferred. Scripts are expected to handle unexpected tool-result shapes defensively; the UI does not infer partial failure. Validation failures currently surface as typed sandbox errors and `fell_back` records rather than a distinct `validation_failure` outcome.

---

## Code Reference Map

All paths verified in the workspace (2026-11-03).

### Agent Runtime (`backend/app/agent_runtime/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Sandbox engine (`build_safe_globals`, guards, caps) + `build_capability_contract` + `unwrap_mcp_tool_result` | module | Globals seeded wholesale from RestrictedPython `safe_builtins`; documented guards (`_getattr_`, `_getitem_`, `_write_`, `_getiter_`, `_unpack_sequence_`, `_iter_unpack_sequence_`, `_inplacevar_` operator map, `_print_`); resource caps, fail-closed typed errors, MCP-only `SandboxToolFacade` | `backend/app/agent_runtime/scripts/sandbox.py` |
| Composition schemas | module | `StepKind.script_segment` + `ScriptSegmentStep`; `CompositionSegment`/`WorkflowComposition`; legacy StepGraph retained | `backend/app/agent_runtime/scripts/schemas.py` |
| `ScriptValidator` | module | Restricted compile, AST scan, secret-shape guard; render-append removed | `backend/app/agent_runtime/scripts/compiler.py` |
| `ScriptRunner.execute_python_source` | module | Sandboxed execution, humanized logs, envelope unwrapping, accounting fields | `backend/app/agent_runtime/scripts/runner.py` |
| `run_session_script_first` | function | Optimized-plan preference, command bypass via `input_data["__command"]`, always-fresh lookups, lineage-based artifact detection | `backend/app/agent_runtime/scripts/dispatch.py` |
| Fallback classification | module | `sandbox_violation`/`resource_limit_exceeded`; `sandbox_fields()` | `backend/app/agent_runtime/scripts/fallback.py` |
| Verification shadow runs | module | `sandbox_check_passed` evidence | `backend/app/agent_runtime/scripts/verification.py` |
| Generate→test→refine loop | module | `_RecordedToolReplayClient`, `set_script_repair_generator`, promotion gate | `backend/app/agent_runtime/scripts/capture.py`, `autocompile.py` (`schedule_autocompile`, OTEL span `script.autocompile`), `repair.py` (`MAX_REPAIR_ATTEMPTS`, `repaired_from` lineage candidates) |
| Post-run autocompile hook | function | Fire-and-forget `schedule_autocompile` launched on LLM-path completion from `backend/app/agent_runtime/api/execute.py`; duplicate-protected, eligibility-checked, auto-promotion on shadow-verification match | `backend/app/agent_runtime/scripts/autocompile.py` |
| Mock-recording + script-tool client | module | `submit_mock_recordings`/`get_mock_recording` (mTLS `/internal/llm-mock/*`); `get_script_tool` | `backend/app/agent_runtime/scripts/cc_client.py` |
| AR script-tool execute endpoint | module | `POST /internal/script-tools/execute` with session-bound client | `backend/app/agent_runtime/api/script_tools.py` (registered in `backend/app/agent_runtime/main.py`) |
| Execution trigger | module | Threads `input_data` through to the dispatcher (command marker) | `backend/app/agent_runtime/api/execute.py` |
| Command toolset wiring | module | `_command_tool_schemas(command)` derives optimization-tool OpenAI schemas; `_build_guardrail_state` applies `COMMAND_TOKEN_BUDGET` | `backend/app/services/agents/runtime_executor.py` |

### Control Center (`backend/app/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Plan generation (high-level only) | module | Composition authoring removed; parser forward-compat | `backend/app/services/agents/plan_generation_service.py` |
| Model dispatch | module | `get_model` returns the mock provider when `LLM_MOCK_MODE` active | `backend/app/services/agents/langchain_model_factory.py` |
| Mock provider | module | `MockChatModel`, `compute_recording_key`, sinks, prompt-assertion helpers | `backend/app/services/agents/llm_mock_provider.py` |
| Optimized plan service | module | Authored-plan persistence + script association (scripts promoted only for `ready` plans), feedback memory, `error` persistence on `needs_feedback`/`mark_failed`, `retire_optimized_plan` | `backend/app/services/agents/optimized_plan_service.py` |
| Command prompts + budget | module | `optimize-and-verify` mission with mandatory pre-authoring read order, skip-when-healthy rule, mandatory `error` on failed authoring, "Final answer" section, `COMMAND_TOKEN_BUDGET` | `backend/app/services/agents/command_prompts.py`, `backend/app/db/models/command_prompt.py` |
| Optimization system tools | module | `execute_script`/`generate_script` tool-name validation + sandbox-segregated forward; `generate_optimized_plan` persists the caller-supplied `error` reason | `backend/app/api/v1/internal/optimization_tools.py` + `backend/app/services/agents/system_tool_registry.py` |
| Script registry service | module | New ScriptVersion/Verification fields, `retire_serving_versions`, repair bookkeeping, `link_plan_steps_to_version` | `backend/app/services/script_registry/service.py` |
| DB models | module | ScriptDefinition/ScriptVersion (+ `repaired_from_id` lineage), VerificationRun, FallbackEvent, **RepairAttempt**; `ScriptExecutionOutcome.partial_failure` (enum value present, **no writer yet**); ScriptExecutionRecord accounting (`identity_parity_confirmed`, no execution-mode column); `LLMMockRecording`, `OptimizedImplementationPlan` (`error` populated on `needs_feedback`) | `backend/app/db/models/script_registry.py`, `script_execution.py`, `llm_mocking.py`, `optimized_plan.py` |
| Registry REST API | module | CRUD, versions + diff, promote/retire transitions, verifications/fallbacks/**repairs**/health listings, executions, compilation + cost-savings reports; no execution-mode endpoints | `backend/app/api/v1/scripts.py`, `backend/app/schemas/scripts.py` |
| CC internal scripts API | module | `GET /serving-version`, `GET /versions/{vid}` (compiled graph), `POST /candidates`, `/verifications`, `/fallbacks`, `/executions`, `/repairs`, `GET/POST /repairs`, `POST /promote`, `GET /llm-reference/{session_id}`; AR service-cert only | `backend/app/api/v1/internal/scripts.py` |
| Plan-step script links | module | `PlanStepRead.script_definition_id`/`script_version_id` on plan responses; stamps applied via `link_plan_steps_to_version` | `backend/app/schemas/agents.py` |
| REST APIs | module | Script fields on create/read; optimized-plan get/feedback/retire; launch `optimize` opt-in flag | `backend/app/api/v1/scripts.py`, `backend/app/schemas/scripts.py`, `backend/app/api/v1/agents.py` |
| CC internal APIs | module | Mock recordings upsert/lookup; semantic-bridge mock routing; string `output_data` | `backend/app/api/v1/internal/llm_mocking.py`, `backend/app/api/v1/internal/system_tools.py`, `backend/app/api/v1/internal/session_data.py` |
| Migrations | applied | Sandbox/mock fields; optimized plan + verification log + `retired` status; script registry + execution tables (`a1b2c3d4f5e6`); execution-mode drop + repair tables + `repaired_from_id` + `identity_parity_confirmed` (`b2c3d4e5f6a7`); script session FK repoint to agent jobs (`c3d4e5f6a7b8`); `partial_failure` added to the script execution outcome enum (`e4f66f7c7f1c`) | `backend/alembic/versions/7d0fe5f1308d_*`, `4108dac629ef_*`, `93d25e577411_*`, `a1dbc4760d9a_*`, `c2d3e4f5a6b7_*`, `a1b2c3d4f5e6_*`, `b2c3d4e5f6a7_*`, `c3d4e5f6a7b8_*`, `e4f66f7c7f1c_*` |
| Dependency | pyproject | `RestrictedPython~=7.0` | `backend/pyproject.toml` |

### Communication Hub (`backend/app/communication_hub/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Script-tool routing + forwarding | module | `_route_to_script_tool` → AR execute; `/internal/script-tools/forward` for the CC hop | `backend/app/communication_hub/api/internal/tool_routing.py` |

### Frontend (`frontend/src/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Optimized Plan tab | component | Steps, "View script" (`ScriptViewDialog`), feedback, retire, absent/retired hint; persisted `error` alert (`failed` = error, `needs_feedback` = warning), retire success + "nothing to retire" states, retire disabled when absent/retired | `frontend/src/components/agents/AgentOptimizedPlanTab.tsx` |
| Script view dialog | component | Inline python_source/description/version viewer | `frontend/src/components/agents/ScriptViewDialog.tsx` |
| Agent type dialog (5 tabs) | component | Details, Preview, Execution Logs, Sessions, Optimized Plan; no Scripts tab; "View agent" header link | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| Plan-step script links | component | Per-step "View script" for `script_version_id`-backed plan steps | `frontend/src/components/agents/AgentPlanContent.tsx`, `frontend/src/components/agents/ScriptViewDialog.tsx` |
| Registry hooks | hooks | `useScripts`, `useScriptVersions`, `useScriptVerifications`, `useScriptFallbacks`, `useScriptRepairs`, `useScriptHealth`, `usePromoteScriptVersion`, `useRetireScriptVersion` | `frontend/src/hooks/useScripts.ts` |
| Launch dialog | component | Opt-in "Run with optimization" flow | `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` |
| Types + i18n | module | `python_source`/sandbox fields; `output_data: Record \| string`; `agents.scripts.*` keys; `agents.optimizedPlan.nothingToRetire`/`retiredHint`; `agent::scripts` in both resource-type manifests (`backend/app/core/resource_types.py`, `frontend/src/constants/resourceTypes.ts`); all strings via `t()` | `frontend/src/types/scripts.ts`, `frontend/src/i18n/locales/en.json`, `frontend/src/constants/resourceTypes.ts` |

### Tests

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Sandbox engine tests | backend test | Baseline regressions for `_unpack_sequence_`/`_iter_unpack_sequence_`/`_inplacevar_`, attribute/item/write guards | `backend/tests/test_sandbox_engine.py` |
| Script runner tests | backend test | Sandboxed execution path, envelope unwrapping, accounting fields | `backend/tests/test_script_runner.py` |
| Script-first dispatcher tests | backend test | Optimized-plan preference, command bypass, fallback paths | `backend/tests/test_script_first_dispatcher.py` |
| Tenant-isolation sweep | backend test | `_OWN_KWARGS`/`_parent_fks` coverage for script models plus the `command_prompts` registry entry | `backend/tests/test_tenant_isolation_sweep.py` |
| CH control-plane middleware test | backend test | `/internal/agent/execute` now requires the `service:control-center` certificate (cert-exempt bypass removed) | `backend/tests/unit/test_control_plane_middleware.py` |
| Full execution flow (E2E) | backend integration test | CC→CH→AR execution flow; a non-Control-Center certificate is rejected on the CH execute path | `backend/tests/integration/test_full_execution_flow.py` |
| Optimized Plan tab test | frontend test | Persisted `error` alert, `needs_feedback` prompt, retire success, "nothing to retire", disabled retire | `frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx` |
| AppShell tenant-admin test | frontend test | Tenant Admin sidebar gating, single identity-providers entry, Platform group probe, tenancy-off behaviour | `frontend/src/__tests__/AppShell.tenantAdmin.test.tsx` |

> **Removed (stale references cleaned):** `frontend/src/components/agents/AgentScriptsTab.tsx` (DELETED — standalone Scripts registry tab removed), `AgentOptimizeLogDialog.tsx` (DELETED — verification-log UI surface retired with migration `a1dbc4760d9a`), the standalone `POST /agents/types/{id}/optimize-plan` endpoint and its 180s-bound side execution (optimization moved into the launch path).

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `SANDBOX_WALL_TIME_SECONDS` / `SANDBOX_CPU_SECONDS` / `SANDBOX_MEMORY_LIMIT_MB` | Sandbox default resource caps (per-script ScriptVersion caps win) |
| `LLM_MOCK_MODE` / `LLM_MOCK_RECORDING_SET` | Activate the mock LLM provider (scripted/record/replay) for tests; production default off |
| `COMMAND_TOKEN_BUDGET` | Minimum token budget for command-driven special executions (default 2,000,000) |

## Tests

See `docs/master/qa/test-plans/sandboxed-scripting-test-plan.md` — sandbox security, validator, mock layer, refinement loop, optimized plan, command execution, dispatch, allowlist coverage guard, and the zero-LLM e2e suites.

Follow-up coverage added by the `sandboxed-scripting-follow-ups` change is listed in the Code Reference Map "Tests" table above (sandbox baseline guards, tenant-isolation sweep entries, CH control-plane cert enforcement, optimized-plan UI states, tenant-admin sidebar gating).
