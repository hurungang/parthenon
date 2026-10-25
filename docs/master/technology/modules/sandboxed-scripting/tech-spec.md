# Module: sandboxed-scripting — Tech Spec

## Overview

Model-authored Python scripting with a RestrictedPython sandbox executed exclusively in Agent Runtime, plus the LLM mock layer that makes agent-execution tests zero-LLM. The subsystem spans all three backend services without violating segregation:

- **Agent Runtime**: sandbox engine (`RestrictedPython` compile+exec), script compiler/validator, script runner, script-first dispatcher (with optimized-plan preference), fallback controller, verification engine, generate→test→refine loop, AR internal script-tool execute endpoint.
- **Control Center**: script registry REST, DB models (ScriptVersion/ScriptExecutionRecord/LLMMockRecording/OptimizedImplementationPlan), the `optimize-and-verify` command (command prompts + optimization system tools), the command-driven Optimized Plan service, and the CC-internal LLM mock recordings API.
- **Communication Hub**: `script____<name>` virtual-tool routing to AR `/internal/script-tools/execute` (and the CC→CH `/internal/script-tools/forward` hop).
- **Frontend**: "Optimized Plan" tab (steps with "View script" links via the inline `ScriptViewDialog`, feedback, retire), opt-in "Run with optimization" launch dialog.

**Sandbox technology**: RestrictedPython (pinned `RestrictedPython~=7.0` in `backend/pyproject.toml`). AST-level isolation (guarded builtins, no `import` statement — `json`/`math`/`statistics` pre-bound, `_getattr_`/`_getitem_`/`_write_` guards) + OS resource caps + a single injected MCP-only client. Defense in depth: validator (AST scan + secret-shape guard), resource caps, and the injected client are independent layers.

**Compliance**: sandbox runs only in AR; only CC touches PostgreSQL (AR reads/writes everything via mTLS CC REST with signed internal headers); scripts receive no credentials (secret-shape guard at validation; identity-context-only invocation contract; per-call token injection by CH); MCP-only egress — the sandbox exposes exactly one external binding (`tools` facade over `CommHubToolClient`), all other vectors fail closed.

---

## Key Components

### Agent Runtime

| Component | Description |
|-----------|-------------|
| Sandboxed Script Engine | `compile_restricted_exec` + allowlisted builtins (no `import`), `_getattr_`/`_write_` guards, `SandboxToolFacade` (MCP-only, sync bridge onto the running loop; re-enters the dispatch task's `contextvars` snapshot so forwarded signed tenant headers attach to sandbox-issued tool calls; awaited tool-call time excluded from the wall-time budget), `unwrap_mcp_tool_result` envelope unwrapping, typed errors `SandboxCompileError`/`SandboxViolationError`/`ResourceLimitExceededError` |
| Resource Cap Enforcer | Wall-time daemon-thread deadline loop (counts only sandbox-compute time), `RLIMIT_AS` memory cap; caps from ScriptVersion → env (`SANDBOX_WALL_TIME_SECONDS`/`SANDBOX_CPU_SECONDS`/`SANDBOX_MEMORY_LIMIT_MB`) → safe fallbacks; breach → typed error (`sandbox_termination=True`) |
| Script Validator (compiler.py) | Restricted compile check, AST safety scan, secret-shape guard, `validate_or_raise`; hardcoded `semantic____render` append (`_append_render_step`) **removed**; `build_capability_contract` documents the business-logic-only script contract |
| Script Runner | `execute_python_source` whole-script sandbox path; injected-client-only egress; humanized one-line logs (no JSON blobs); MCP envelope unwrapping in `_run_tool_step`; records `tokens_saved_actual`, `sandbox_termination`, `sandbox_violation_detail` |
| Script-First Dispatcher | Pre-execution composition validation; command bypass (`input_data["__command"]` → plain LLM loop, no script dispatch); **fresh ready optimized plan supersedes the base plan** (`fully_scripted` → zero-LLM; otherwise scripts-as-tools); absent/stale/failed → base-plan LLM path; lookups ALWAYS fresh (60s cache removed); lineage-based optimized-artifact detection (`source_optimized_plan_id`, legacy `optimized-` prefix accepted); a legacy `auto-<id8>` compiled script never shadows a fresh optimized plan; tool-mode plans serve no script |
| Fallback Controller | Adds `sandbox_violation` / `resource_limit_exceeded` trigger reasons; unconditional LLM fallback (a run never fails solely because a script failed); `sandbox_fields()` on fell-back records |
| Verification Engine | Shadow-runs sandbox-compliant candidates; records `sandbox_check_passed` evidence |
| Capture/Autocompile/Repair | Generate → test → refine loop: compositions tested against recorded run data (`_RecordedToolReplayClient`), failures fed (with the capability contract) to the injectable repair generator for ≤ `MAX_SCRIPT_REFINEMENT_ATTEMPTS` (3); first passing script promoted, exhaustion promotes NOTHING; autocompile promotion gate — candidate stays draft while a fresh optimized plan exists |
| AR script-tool endpoint | `POST /internal/script-tools/execute` — resolves `script____<name>` via `get_script_tool` and runs its `python_source` (or declarative graph) in the sandbox with a session-bound MCP-only client; returns `{"result": ...}` / `{"error": ...}` (never a 502) |

### Control Center

| Component | Description |
|-----------|-------------|
| Script Registry Service | Persists `python_source` + caps + validation fields; `get_serving_version` exposes `script_definition_name` + `source_optimized_plan_id` (prefers the optimized-plan-linked definition); `retire_serving_versions(agent_type_id)` called from `regenerate-plan` |
| Optimized Plan Service | Thin persistence + association layer behind the `optimize-and-verify` command; authored-plan normalization (consecutive scripted segments collapse into ONE chained "Execute workflow script" step; `LLM` bridge steps segment; dict results merge into `context`); **verification-gated chaining** (`_split_failed_chain`: passing prefix re-collapses, failing+later segments become tool-mode script tools, plan demoted to tool mode); feedback memory (all stored feedback summaries included in the authoring prompt); `retire_optimized_plan` MARKS rows `retired` (kept for reference, never deleted; exactly one active record per agent type; `get_fresh_optimized_plan` serves only `ready`) |
| Optimization System Tools | `get_implementation_plan`, `get_optimized_implementation_plan`, `generate_optimized_plan`, `generate_script`, `execute_script`, `list_scripts`, `get_scripts`, `get_script`, `get_execution_log` — registered as standard system tools routed by CH; `execute_script` accepts FULL inline `python_source` (no save required) and routes EVERY execution through `CommunicationHubClient.forward_sandboxed_script` (CC → CH `/internal/script-tools/forward` → AR `/internal/script-tools/execute`; the old CC→CH `/internal/tools/call` path was rejected — `ControlPlaneMiddleware` only accepts AR certs there); **malformed tool-name validation**: every literal `tools.call('name', ...)` AST-checked against the agent's actual allowed tool names; mismatch → `validation_error` with valid names; `generate_script` only after a successful `execute_script` (save-on-success) |
| Command Prompts | Stored mission text for the `optimize-and-verify` command (seeded idempotently with in-code fallback); mandates self-reflection FIRST, verification against REAL tool executions, and a mandatory "Final answer" section (the final message IS the business result — no meta-commentary); `COMMAND_TOKEN_BUDGET` (default 2,000,000, env-overridable) guarantees command runs a generous dedicated token budget |
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
| `AgentOptimizedPlanTab.tsx` | "Optimized Plan" tab (panel index 4): steps list with per-step "View script" links (open the reusable inline `ScriptViewDialog` — python_source + description + version), status/error surfacing, feedback textarea + submit (one-shot-LLM-summarized), "Retire plan" action (marks rows `retired`; invalidates the whole agent-type query scope so the launch dialog immediately re-offers optimization); absent/retired state shows the "next run offers optimization" hint |
| `AgentJobLaunchDialog.tsx` (pages/agents) | Optimized-plan existence check + opt-in dialog ("Run with optimization" / "Skip optimization"); `optimize` passed through the launch call; a `ready` plan launches directly without the dialog |
| `AgentTypeDetailsDialog.tsx` | 4 tabs (standalone Scripts tab removed; "View agent" header link opens the dialog on the default tab) |
| Types / Scripts tab chips | `frontend/src/types/scripts.ts`: `python_source` presence + sandbox-validation fields; `AgentJob.output_data` widened to `Record \| string` (raw string output rendered as text) |

---

## Code Reference Map

All paths verified in the workspace (2026-10-25).

### Agent Runtime (`backend/app/agent_runtime/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Sandbox engine + caps + `build_capability_contract` + `unwrap_mcp_tool_result` | module | RestrictedPython exec, resource caps, fail-closed typed errors, MCP-only `SandboxToolFacade` | `backend/app/agent_runtime/scripts/sandbox.py` |
| Composition schemas | module | `StepKind.script_segment` + `ScriptSegmentStep`; `CompositionSegment`/`WorkflowComposition`; legacy StepGraph retained | `backend/app/agent_runtime/scripts/schemas.py` |
| `ScriptValidator` | module | Restricted compile, AST scan, secret-shape guard; render-append removed | `backend/app/agent_runtime/scripts/compiler.py` |
| `ScriptRunner.execute_python_source` | module | Sandboxed execution, humanized logs, envelope unwrapping, accounting fields | `backend/app/agent_runtime/scripts/runner.py` |
| `run_session_script_first` | function | Optimized-plan preference, command bypass via `input_data["__command"]`, always-fresh lookups, lineage-based artifact detection | `backend/app/agent_runtime/scripts/dispatch.py` |
| Fallback classification | module | `sandbox_violation`/`resource_limit_exceeded`; `sandbox_fields()` | `backend/app/agent_runtime/scripts/fallback.py` |
| Verification shadow runs | module | `sandbox_check_passed` evidence | `backend/app/agent_runtime/scripts/verification.py` |
| Generate→test→refine loop | module | `_RecordedToolReplayClient`, `set_script_repair_generator`, promotion gate | `backend/app/agent_runtime/scripts/capture.py`, `autocompile.py`, `repair.py` |
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
| Optimized plan service | module | Normalization/chaining/split, feedback memory, `retire_optimized_plan` | `backend/app/services/agents/optimized_plan_service.py` |
| Command prompts + budget | module | `optimize-and-verify` mission, "Final answer" section, `COMMAND_TOKEN_BUDGET` | `backend/app/services/agents/command_prompts.py`, `backend/app/db/models/command_prompt.py` |
| Optimization system tools | module | `execute_script`/`generate_script` tool-name validation + sandbox-segregated forward | `backend/app/api/v1/internal/optimization_tools.py` + `backend/app/services/agents/system_tool_registry.py` |
| Script registry service | module | New ScriptVersion/Verification fields, `retire_serving_versions` | `backend/app/services/script_registry/service.py` |
| DB models | module | ScriptVersion (+6 fields), ScriptExecutionRecord accounting, `LLMMockRecording`, `OptimizedImplementationPlan` | `backend/app/db/models/script_registry.py`, `script_execution.py`, `llm_mocking.py`, `optimized_plan.py` |
| REST APIs | module | Script fields on create/read; optimized-plan get/feedback/retire; launch `optimize` opt-in flag | `backend/app/api/v1/scripts.py`, `backend/app/schemas/scripts.py`, `backend/app/api/v1/agents.py` |
| CC internal APIs | module | Mock recordings upsert/lookup; semantic-bridge mock routing; string `output_data` | `backend/app/api/v1/internal/llm_mocking.py`, `backend/app/api/v1/internal/system_tools.py`, `backend/app/api/v1/internal/session_data.py` |
| Migrations | applied | Sandbox/mock fields; optimized plan + verification log + `retired` status | `backend/alembic/versions/7d0fe5f1308d_*`, `4108dac629ef_*`, `93d25e577411_*`, `a1dbc4760d9a_*`, `c2d3e4f5a6b7_*` |
| Dependency | pyproject | `RestrictedPython~=7.0` | `backend/pyproject.toml` |

### Communication Hub (`backend/app/communication_hub/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Script-tool routing + forwarding | module | `_route_to_script_tool` → AR execute; `/internal/script-tools/forward` for the CC hop | `backend/app/communication_hub/api/internal/tool_routing.py` |

### Frontend (`frontend/src/`)

| Symbol / Area | Type | Description | File |
|---|---|---|---|
| Optimized Plan tab | component | Steps, "View script" (`ScriptViewDialog`), feedback, retire, absent/retired hint | `frontend/src/components/agents/AgentOptimizedPlanTab.tsx` |
| Script view dialog | component | Inline python_source/description/version viewer | `frontend/src/components/agents/ScriptViewDialog.tsx` |
| Agent type dialog (4 tabs) | component | Scripts tab removed; "View agent" header link | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| Launch dialog | component | Opt-in "Run with optimization" flow | `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` |
| Types + i18n | module | `python_source`/sandbox fields; `output_data: Record \| string`; all strings via `t()` | `frontend/src/types/scripts.ts`, `frontend/src/i18n/locales/en.json` |

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
