# Test Plan: Sandboxed Scripting & LLM Mocking

**Change:** `sandboxed-scripting-and-llm-mocking` · **Hardening follow-ups:** `sandboxed-scripting-follow-ups` (2026-11-03) · **Tech spec:** `docs/master/technology/modules/sandboxed-scripting/tech-spec.md`

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

### 8. Hardening Follow-ups (`sandboxed-scripting-follow-ups`, 2026-11-03)

**Sandbox baseline seeding & construct regressions**
- Globals are seeded wholesale from RestrictedPython's audited safe baseline; only documented custom guards (tools facade, context binding, resource caps) are layered on top — no construct-by-construct patching.
- Valid business scripts that depend on baseline builtins (`json`, `statistics`, etc. with no imports) execute — the regression the incremental globals construction broke.
- Tuple unpacking (`a, b = pair` via `_unpack_sequence_`) executes, and an unpack-length mismatch raises instead of silently mis-binding. Augmented assignment (`_inplacevar_`) is exercised inside sandboxed scripts; it has no dedicated named test.
- The existing fail-closed invariants must stay green alongside the wider baseline: I/O, import, dunder traversal, forbidden builtins, resource caps.

**`partial_failure` outcome — enum shipped, detection DEFERRED**
- `ScriptExecutionOutcome.partial_failure` exists (model + migration) as an unused placeholder.
- **Deferred by product decision:** semantic-error detection (an upstream error report inside a successful tool envelope) and the fallback / repair / re-optimization reactions that would consume it. There is no test asserting semantic error → `partial_failure`, and the presence of the enum value must not be read as proof of the behaviour. Accepted mitigation: scripts are authored defensively against unexpected tool-result shapes.
- Do not add "partial failure" to any acceptance claim until a detection contract exists.

**Mandatory self-reflection ordering**
- The optimization mission mandates reading `get_scripts` → `get_execution_log` → `get_optimized_implementation_plan` before authoring or repairing a script, and mandates skipping re-authoring (stating so) when scripts/logs are healthy and the agent is unchanged.
- The three read surfaces are each covered by a backend test; the ordering itself is prompt-enforced and is not asserted by an automated test.

**Optimization failure visibility (`error` on `needs_feedback`)**
- A `needs_feedback` (or otherwise non-ready) plan never leaves a serving artifact — no script promotion, no plan that gates execution.
- The failure reason is persisted on the plan's `error` field and rendered in the Optimized Plan tab (i18n-wrapped) with a steer-via-feedback prompt; empty/long/unicode reasons must render safely.

**Retire UX**
- Already-shipped launch-dialog cache refresh stays regression-covered: retire invalidates the whole agent-type query scope so the Run Agent action re-gates immediately (no page reload).
- When the plan is already retired / there is nothing active to retire, retire shows a clear "nothing to retire" state and the retire action is disabled — no silent no-op and no request issued. This state is component-level only (no E2E).

**Pre-existing test health (fixed — none quarantined)**
- AppShell tenant-admin sidebar gating flake resolved (gating assertions are deterministic per tenancy/permission probe state).
- Tenant-isolation sweep `KeyError: _OWN_KWARGS` for script models resolved (script definition/version/execution models registered in the sweep's own-kwargs and parent-FK maps).
- `test_full_execution_flow` middleware failures resolved: CH control-plane routes `/internal/agent/execute|terminate|resume` now require the `service:control-center` certificate (no cert-exempt bypass). The suite still self-skips when the live services are unreachable — that is a pre-existing integration-test precondition, not a quarantine.

## Deferred & Uncovered (accepted)
- Semantic tool-error detection and its fallback/repair/re-optimization reactions — deferred by product decision (see §8).
- Automated assertion of the literal self-reflection read *ordering* — prompt-enforced only.
- "Nothing to retire" empty state has no E2E spec (nested agent-type dialog flow); covered at component level.
- No explicit allowlist-diff test proving the baseline seed did not widen access; the invariant is covered indirectly by the fail-closed suite (I/O, import, dunder, forbidden builtins).

## Test File References (verified in workspace 2026-10-25; follow-ups verified 2026-11-03)

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

### Hardening Follow-ups (`sandboxed-scripting-follow-ups`, verified 2026-11-03)
| Layer | File | Coverage |
|---|---|---|
| Backend | `backend/tests/test_sandbox_unpack.py` | Tuple-unpacking regression (`_unpack_sequence_`) executes; unpack-length mismatch raises |
| Backend | `backend/tests/test_sandbox_engine.py` | Baseline-seeded globals (`json`/`statistics` used without imports), augmented assignment inside sandboxed scripts, fail-closed invariants, resource caps, tool facade |
| Backend | `backend/tests/services/test_oauth_refresh_classification.py` | Unrecoverable refresh sets `requires_reauth` + reason; transient refresh leaves both unset; successful refresh clears both |
| Backend | `backend/tests/services/test_mcp_oauth_reauth_tenant.py` | In-place same-session re-auth (no duplicate row), re-auth state carries the session id, cross-tenant re-auth creates a separate session, superseding old OAuth sessions migrates bindings, refreshed credentials used by the next tool call |
| Backend | `backend/tests/test_optimized_plan.py` | Non-ready plan never promotes scripts; `error` persisted on a failed plan (`mark_failed`); self-reflection read surfaces (`get_scripts`, `get_execution_log`, `get_optimized_implementation_plan`); retire endpoint (marks retired, keeps rows, stops serving) |
| Backend | `backend/tests/test_tenant_isolation_sweep.py` | `_OWN_KWARGS` / parent-FK coverage for script definition, version and execution models (sweep `KeyError` fix) |
| Backend | `backend/tests/unit/test_control_plane_middleware.py` | CH control-plane execute path requires the `service:control-center` certificate; A2A route expects the agent-runtime service |
| Backend | `backend/tests/integration/test_full_execution_flow.py` | Full CC→CH→AR flow middleware invariants (self-skips when live services are unreachable) |
| Frontend | `frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx` | `needs_feedback` renders status + persisted failure reason + steer prompt; "nothing to retire" state with retire disabled and no request; retire invalidates the agent-type query scope (cache-refresh regression) |
| Frontend | `frontend/src/__tests__/McpSessionManager.test.tsx` | Expired refresh token renders the error-coloured re-auth action and suppresses the success refresh action |
| Frontend | `frontend/src/__tests__/AppShell.tenantAdmin.test.tsx` | Tenant Admin / Platform sidebar gating (flake fix) |
| E2E | `e2e/tests/mcp-hub.spec.ts` (`MCP Session re-auth state`) | Session flagged `requires_reauth` shows the "Needs re-authentication" status with no page errors |
| E2E | `e2e/tests/agent-type-scripts-tab.spec.ts` | Operator retires a version from the Scripts tab (retire flow referenced by this change's demo case) |

## CI / Strategy Notes
- All agent-execution tests run with the LLM mock layer active — deterministic, zero LLM cost. CI sets `LLM_MOCK_MODE: off` as the production-safe default for non-test paths. See `docs/master/qa/testing-strategy.md` → "LLM Mock Layer for Agent-Execution Testing".
