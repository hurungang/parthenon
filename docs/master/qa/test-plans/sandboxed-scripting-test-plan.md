# Test Plan: Sandboxed Scripting & LLM Mocking

**Change:** `sandboxed-scripting-and-llm-mocking` · **Tech spec:** `docs/master/technology/modules/sandboxed-scripting/tech-spec.md`

## Coverage Areas

### 1. Sandbox Security (Sandbox Engine + Resource Caps)
- I/O, network, import, and dunder-path escape attempts all fail closed with recorded violation detail; `_getattr_`/`_getitem_`/`_write_` guards block unsafe access.
- CPU/memory/wall-time cap breaches terminate scripts safely (`ResourceLimitExceededError`, `sandbox_termination=True`, one-line detail); awaited tool-call time is excluded from the wall-time budget.
- Secret-shape guard: credential-shaped sources rejected at validation (`sandbox_validation_status` + reason; version stays draft).
- MCP-only egress: the injected `CommHubToolClient` facade is the sole external binding; `tools.call` returns the UNWRAPPED MCP payload; tenant headers carry across the thread bridge (SEC1 parity).
- Sandbox capability contract: business-logic-only wording asserted.

### 2. Script Execution / Dispatch
- Model-authored `python_source` executes verbatim; no auto-appended `semantic____render` step (regression for removed `_append_render_step`).
- Fresh `ready` optimized plan supersedes the base plan (`fully_scripted` → zero-LLM; tool-mode serves no script); absent/stale/failed/retired → base-plan LLM path; lookups always fresh (retire is immediately effective); a legacy `auto-<id8>` serving script never shadows a fresh optimized plan; lineage-based (`source_optimized_plan_id`) artifact detection.
- Command bypass: `input_data["__command"]` runs the plain LLM loop (no script dispatch, no auto-compile).
- Fallback: any script failure → unconditional LLM fallback with recorded trigger reason; run never fails solely because a script failed.
- Generate → test → refine loop: recorded-run replay testing, repair feed with the capability contract, ≤3 attempts, exhaustion promotes nothing; autocompile promotion gate under a fresh optimized plan.

### 3. Optimized Plan
- Base plan stays high-level (no composition in prompt/parsed plan).
- Opt-in launch flow (`optimize: true/false`; ready plan → no dialog); retire marks rows `retired` (kept, one active record, never gates execution) and retires serving versions.
- Authored-plan normalization: consecutive scripted segments collapse into ONE chained step; empty steps dropped; duplicates merged; verification-gated chaining splits at the first failing segment (demote to tool mode; `needs_feedback` only when even split segments fail).
- Feedback memory: one-shot summarization + accumulation; ALL stored feedback included in regeneration prompts; feedback survives regeneration.
- Tool-name validation: literal `tools.call('name', ...)` AST-checked against actual allowed tools (structured `validation_error` lists valid names); runtime tool-not-found → `ExecutionError` → LLM fallback; "Final answer" mission section (business result, no meta-commentary).

### 4. Allowlist Coverage Guard
- Static scan asserts every (method, path) pair issued by AR/CH callers to `/api/v1/internal/...` exists in the CC-side allowlists (`_AR_ALLOWLIST`/`_CH_ALLOWLIST`); reverse cross-check enumerates CC internal routes (scripts/llm-mock routers, `SystemToolRegistry` map) and asserts allowlisting. Fails on any future `403 endpoint_not_allowlisted` bug of this class.

### 5. Command Execution
- `_command_tool_schemas` returns the optimization tools for command runs (empty for non-command); command `tool_definitions` include the full optimization toolset; `__command` marker threads from the launch flag through `trigger_execution` → dispatcher; command runs get at least `COMMAND_TOKEN_BUDGET`.

### 6. LLM Mock Layer
- Scripted/record/replay modes; determinism (identical inputs + mock scripts → identical runs); prompt assertions; record/replay round-trip through the CC internal mock API (AR never touches the DB; missing key → typed error); credential-shaped recording fields rejected 422; semantic-bridge steps run zero-LLM in mock mode.

### 7. Service Segregation Invariants
- Sandbox executes ONLY in AR (CC's `execute_script` handler is sandbox-segregated — pinned by test; CC→AR always via CH forward); AR consumes everything via mTLS CC REST with signed headers; no credentials reach scripts.

## Test File References (verified in workspace 2026-10-25)

### Backend (`backend/tests/`)
| File | Coverage |
|---|---|
| `test_sandbox_engine.py` | Sandbox invariants, caps (wall-time excludes awaited tool-call I/O), escapes fail-closed, capability contract, minimal business-logic script e2e through the facade |
| `test_script_validator.py` | Validator/normalizer, AST scan, secret-shape guard, render-append removal regression |
| `test_llm_mock_layer.py` | Scripted/record/replay, determinism, prompt assertions, provider selection |
| `test_script_refinement_loop.py` | Generate→test→refine loop convergence/exhaustion |
| `test_model_authored_composition.py` | Model-authored composition execution verbatim |
| `test_optimized_plan.py` | Base-plan prompt/parse, optimize generation, chaining/split, verification log, feedback memory, retire endpoint, launch `optimize` injection, optimization system tools + self-reflection |
| `test_script_first_dispatcher.py` | Composition validation, optimized-plan preference, legacy-script precedence, retire freshness, command-execution bypass |
| `test_command_execution.py` | `_command_tool_schemas` wiring, "Final answer" mission, mocked command run produces the business result |
| `test_script_runner.py` | Sandboxed execution path, humanized logs, MCP envelope unwrapping, tenant-context propagation, accounting fields |
| `test_script_compiler.py`, `test_autocompile.py` | Compiler validation; autocompile verification gate + promotion gate |
| `test_script_security_invariants.py`, `test_script_mcp_only_boundary.py` | Segregation invariants; injected-client-only egress |
| `test_internal_scripts_api.py` | Registry REST new fields; CC internal mock API; semantic-bridge mock routing |
| `test_internal_endpoint_allowlist_coverage.py` | Internal-endpoint allowlist regression guard (AR/CH callers ↔ CC allowlists) |
| `tests/unit/test_agent_runtime_executor.py` | Command-aware guardrail state (`COMMAND_TOKEN_BUDGET`) |
| `tests/unit/test_execution_logging_callback.py` | Full `execute_script` input kept in the execution log |
| `tests/communication_hub/test_script_tool_routing.py`, `test_script_forwarding.py` | `script____<name>` routing to AR; CC→CH forward hop |
| `tests/agent_runtime/test_script_tool_execute.py` | AR `/internal/script-tools/execute` |
| `tests/api/v1/internal/test_execute_script_sandbox_segregation.py` | CC never runs the sandbox; never calls `/internal/tools/call` for script execution |
| `tests/e2e/test_agent_execution_e2e.py` | Backend end-to-end agent execution (mock-driven) |
| Migration round-trip | Alongside the scripting revisions under `backend/alembic/versions/` |

### Frontend (`frontend/src/__tests__/`)
| File | Coverage |
|---|---|
| `AgentOptimizedPlanTab.test.tsx` | Steps, "View script" → `ScriptViewDialog` (`onViewScript`), feedback submit, retire call, absent/retired hint, `needs_feedback` surfacing |
| `AgentTypeDetailsDialog.test.tsx` | 4 tabs (Scripts tab removed), "View agent" header link, retire flow |
| `AgentSessionLaunchDialog.test.tsx` | Opt-in dialog flow, `optimize: true/false` passthrough, ready-plan direct launch |
| `ScriptViewDialog.test.tsx` | Inline python_source viewer |

### E2E (`e2e/tests/`)
- `agent-zero-llm-execution.spec.ts` — mock-provider-driven full run with zero LLM API connectivity and humanized log assertions (runs in the CI `e2e-test` job with `LLM_MOCK_MODE` scripted/replay).

## CI / Strategy Notes
- All agent-execution tests run with the LLM mock layer active — deterministic, zero LLM cost. CI sets `LLM_MOCK_MODE: off` as the production-safe default for non-test paths. See `docs/master/qa/testing-strategy.md` → "LLM Mock Layer for Agent-Execution Testing".
