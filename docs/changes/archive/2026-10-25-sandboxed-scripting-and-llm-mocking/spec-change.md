# Spec Change: Sandboxed Scripting & LLM Mocking

**Related PRD:** [prd.md](prd.md)
**Change type:** Capability extension (builds directly on the Software 3.0 Agent Framework — script registry, Script-First Dispatcher, lifecycle, and Scripts tab are reused unchanged)
**Positioning change:** Parthenon's Software 3.0 compiled workflows graduate from limited declarative transform operations to **real sandboxed Python scripting**, from **hardcoded compiler templates** to **model-authored workflow composition**, and gain a **first-class LLM mocking framework** for deterministic, LLM-free end-to-end testing.

## Relationship to the Predecessor Change

This change composes entirely on the Software 3.0 Agent Framework. Reused unchanged: the script registry and Control Center REST APIs, the script lifecycle (draft → verified → compiled → retired) with `repaired_from` lineage, the Script-First Dispatcher with unconditional LLM fallback, the Scripts tab in the Agent Type detail dialog (no standalone admin module), the standardized invocation contract (identity context always passed; scripts execute with the agent's dual identities and permissions), and the strict MCP-only external access boundary. What changes is *what scripts can express*, *who authors the composition*, and *how executions are tested*.

## NEW Capabilities

### N1. Sandboxed Scripting Language
Compiled scripts are real sandboxed Python programs (RestrictedPython is the primary candidate; WASM alternatives must be comparatively evaluated before final selection — the evaluation and decision belong in the tech spec). Scripts can compute statistics, derive and pivot data, and assemble reports — everything the previous declarative transform op set could not express. Hard security invariants, non-negotiable:

- No I/O of any kind: no filesystem, no network, no database, no subprocess.
- No imports beyond the platform allowlist; only allowlisted builtins and safe libraries are visible to script code.
- CPU, memory, and wall-time caps per script execution; exceeding a cap terminates the script safely.
- MCP tools remain the ONLY external access, invoked exclusively through the injected client under the standardized invocation contract (agent's identities and permissions; scripts hold no identity, credentials, or grants of their own).

### N2. Model-Authored Composition (two-layer plan model)
The base implementation plan remains a plain, high-level step list. The workflow composition is authored by the model in a SEPARATE **optimized implementation plan**, produced by an OPT-IN step of the Run Agent flow: when the user launches the agent and no verified optimized plan exists, a dialog explains what optimization does and offers "Run with optimization" or "Skip optimization". Opting in passes an opt-in flag through the launch/execute path, which reuses the existing `__command` side-execution marker mechanism — the execution is prompted by the `optimize-and-verify` command mission plus the user's real task, running the agent's model plus a set of optimization system tools (`get_implementation_plan`, `get_scripts`, `get_execution_log`, `get_script`/`list_scripts`, `get_optimized_implementation_plan`, `generate_script`, `execute_script`, `generate_optimized_plan`, `record_verification`). The optimization run FIRST assesses the current state (scripts, execution logs including past failures, existing optimized plan) and skips re-authoring when the scripts/logs show nothing wrong and the agent hasn't changed. Otherwise it authors script segments + LLM bridge steps + decision steps against the sandbox capability contract, and **verifies each script against the real integration**: the verification IS the real run — tool calls execute for real while accomplishing the user's task (no stub clients) — iterating until the scripts achieve the agent's mission. The hardcoded compiler templates are removed — today `semantic____render` is unconditionally appended to every compiled workflow regardless of need; that hardcoding must go. The verified optimized plan is persisted (and its script versions associated/promoted) as a side effect of the agent calling `generate_optimized_plan`; a bounded 3-attempt rule and `record_verification` failure entries keep failure honest (a `needs_feedback` status prompts the user for steering). "Retire plan" on the Optimized Plan tab clears the plan (and serving scripts compiled from it) so the next run triggers the optimized-plan check again. The Script-First Dispatcher prefers a fresh optimized plan (ready AND newer than the base plan): a `fully_scripted` composition runs zero-LLM; otherwise its scripts are exposed as invocable tools and the LLM orchestrates; any script failure falls back unconditionally to the full LLM path with the reason recorded. An absent, stale (e.g. base plan regenerated), retired, or failed optimized plan falls back to the base plan's LLM path. Composition authoring is validated before execution (every referenced script exists, is in a runnable lifecycle state, and compiles in the sandbox).

### N3. Model-Authored Script Source, Validation & Promotion
Scripts are authored by the model as Python source and stored/versioned in the existing script registry — the lifecycle remains draft → verified → compiled → retired, with lineage unchanged. Model-authored scripts are validated and compiled before promotion: syntax validation and sandbox-compliance validation (only allowlisted constructs/imports, I/O attempts rejected). Scripts failing validation remain in draft with a recorded reason; governance visibility stays in the Scripts tab of the Agent Type detail dialog.

### N4. LLM Mocking Framework
A first-class mock LLM layer makes agent executions testable end-to-end without any LLM API. Three modes:

- **Scripted**: deterministic, hand-authored responses keyed to expected calls.
- **Record**: capture real LLM interactions during a live (or manually driven) execution.
- **Replay**: deterministically replay recorded interactions for identical inputs.

The mock layer covers both the pure LLM path and script paths containing model-backed steps (LLM bridge and decision steps). Tests can assert on prompts sent to the (mocked) LLM. The layer is wired into the backend pytest suite and the e2e suite, so CI exercises full agent executions with zero LLM cost and zero provider flakiness.

### N5. Humanized Script Execution Logs & Accurate Token Accounting
Script execution log entries are rewritten as clean human-readable one-liners (what ran, what it produced) — no truncated JSON blobs embedded in log lines. Script execution records store **real `tokens_saved`**: the tokens genuinely avoided by running the script instead of the LLM path, measured from the reference LLM execution rather than estimated.

## CHANGED Capabilities

### C1. Script Expressiveness
- **Before:** scripts apply a fixed set of declarative transform operations between tool calls.
- **After:** scripts are sandboxed Python programs (N1) capable of statistics, derivation, pivoting, and report assembly, under hard sandbox invariants.

### C2. Workflow Composition
- **Before:** the compiler builds workflow composition from hardcoded templates, always appending `semantic____render`.
- **After:** the "Optimize & Verify" flow has the model author the composition (script segments, LLM bridge steps, decision steps, `fully_scripted` mark) as a separate optimized implementation plan, offered as an opt-in step of the Run Agent flow and verified against real tool-call executions (N2); the dispatcher prefers the fresh optimized plan — `fully_scripted` → zero-LLM, otherwise scripts as tools — and falls back to the base-plan LLM path when the optimized plan is absent/stale/retired/failed or any script fails; workflows contain only the steps the model designed.

### C3. Script Authorship
- **Before:** scripts are compiler-generated from declarative specifications.
- **After:** scripts are model-authored Python source, stored/versioned in the same registry with the same lifecycle (draft → verified → compiled → retired), gated by sandbox validation before promotion (N3).

### C4. Script Execution Observability
- **Before:** script execution log entries embed truncated JSON blobs; `tokens_saved` is not reliably recorded.
- **After:** log entries are human-readable one-liners; script execution records carry real measured `tokens_saved` (N5), making compilation-rate and cost-savings reporting trustworthy.

### C5. Testability of Agent Executions
- **Before:** end-to-end agent-execution tests require live LLM API access — costly, slow, flaky, and non-deterministic.
- **After:** a first-class mock LLM layer (N4) enables deterministic end-to-end testing of LLM and script paths in CI without any LLM API.

## UNCHANGED Capabilities

### U1. Security Architecture (fully preserved)
Three fully segregated services; agents and their scripts run only in Agent Runtime; only Control Center connects to the database; agents and scripts never receive sensitive data (identity tokens, database credentials). The sandbox strengthens — never relaxes — this boundary: no I/O, no network, allowlisted imports, resource caps, MCP-only external access via the injected client.

### U2. Script Registry & Lifecycle
Registry persistence, Control Center REST APIs, lifecycle states (draft → verified → compiled → retired), `repaired_from` lineage, and verification/promotion evidence are reused unchanged. No standalone admin module — governance remains in the Scripts tab of the Agent Type detail dialog.

### U3. Script-First Dispatcher Semantics
Script-first execution with unconditional LLM fallback remains the fixed strategy: verified scripts run automatically when present; any script failure (including sandbox cap violations and validation-at-runtime failures) always falls back to the LLM path with the reason recorded; a run never fails solely because a script failed. No execution-mode configuration is introduced.

### U4. Invocation Contract & Identity
The standardized invocation contract is unchanged: identity context is always passed; scripts execute with the agent's dual identities and resolved permissions, never their own; MCP tool access flows through the existing permission model only.

### U5. LLM Agent Loop & Fallback
The LangChain deep-agent loop remains the default for workflows without verified scripts, the unconditional fallback for all automation failures, and the engine for script repair. Self-improvement (defect-driven repair with bounded retry) semantics are those of the predecessor change, unmodified.

## Compliance Note

This change complies with `docs/config.yaml` `top_priority_rules`: services stay fully segregated; agents and sandboxed scripts run only in Agent Runtime; only Control Center touches the database; scripts hold no identities, credentials, or sensitive data. The sandbox invariants (no I/O, no network, allowlist-only imports, resource caps, MCP-only access) are hard constraints enforced independently of script authorship.
