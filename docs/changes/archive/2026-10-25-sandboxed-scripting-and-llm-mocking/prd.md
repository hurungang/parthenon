# PRD: Sandboxed Scripting & LLM Mocking

## Epic Overview

This epic evolves the Software 3.0 agent framework (built on the script registry/dispatcher from the predecessor change) from limited declarative transform operations to **real sandboxed Python scripting**, and moves workflow composition from hardcoded compiler templates to **model-authored composition via a two-layer plan model**: the base implementation plan stays a plain high-level step list, and the model authors the workflow composition — script segments, LLM bridge steps, and decision steps — as a SEPARATE optimized implementation plan produced by an opt-in step of the Run Agent flow (when no verified plan exists, the user chooses to run with optimization; that run authors and verifies the scripts against real tool-call executions while accomplishing the user's task) and verified before it is served. Today, compiled scripts can only apply a fixed set of declarative transforms, and the dispatcher unconditionally appends a hardcoded summary step (`semantic____render`) regardless of what the workflow actually needs. This epic replaces both limitations: scripts become genuine Python programs — able to compute statistics, derive and pivot data, and assemble reports — running under hard security invariants (no I/O, no network, no imports beyond an allowlist, capped CPU/memory/time, and MCP tools as the only external access via the injected client), and the Script-First Dispatcher executes the optimized composition when fresh, with unconditional fallback to the base-plan LLM path when any script fails or the optimized plan is absent, stale, or failed. Finally, a first-class **LLM mocking framework** makes agent executions testable end-to-end without any LLM API, and script execution logging is humanized with accurate token-savings accounting.

## Business Goals

- Expand the class of automatable workflows: real scripting enables statistics, data derivation/pivoting, and report assembly that declarative transforms cannot express — increasing the compilation rate (share of runs served by scripts instead of LLM calls).
- Reduce LLM spend further: more expressive scripts cover more of each workflow, and `tokens_saved` reporting becomes accurate enough to trust for cost governance.
- Eliminate hardcoded composition: removal of the unconditionally appended `semantic____render` template reduces wasted steps and cost, and lets the model design only the steps each workflow actually needs.
- Make agent executions continuously testable in CI with zero LLM API cost or flakiness, via the mock LLM layer (scripted, recorded, replayed responses).
- Preserve trust and auditability: humanized script execution log entries (no truncated JSON blobs) make runs readable by operators and auditors.

## Users & Personas

- **Platform Administrator** — governs model-authored scripts in the existing Scripts tab of the Agent Type detail dialog (version history, lifecycle draft → verified → compiled → retired, health, description); needs confidence that sandboxed Python introduces no security regression.
- **Agent Operator** — monitors executions; needs clean, human-readable script log entries and trustworthy fallback behaviour (any script failure silently degrades to the LLM path).
- **Developer / QA Engineer** — writes and maintains automated tests for agent executions; needs deterministic end-to-end testing of both LLM paths and script paths with model-backed steps, without LLM API access.
- **Enterprise Consumer / Business Owner** — benefits silently: more workflows become compiled, cheaper, faster, and repeatable; execution provenance remains visible.

## User Stories

- As a platform administrator, I want scripts to run in a hard sandbox (no I/O, no network, allowlisted imports, resource caps) so that more expressive scripting cannot weaken the security model.
- As a platform administrator, I want model-authored Python script sources stored and versioned in the existing registry with the unchanged lifecycle (draft → verified → compiled → retired) so that governance does not change.
- As a platform administrator, I want every model-authored script validated/compiled before it can be promoted so that broken or unsafe scripts never reach execution.
- As an agent operator, I want the base implementation plan to stay a plain, readable high-level step list so that I can review and govern what the agent will do.
- As an agent operator, I want optimization offered as an opt-in step of the Run Agent flow — when no verified optimized plan exists, a dialog explains the value and lets me run with optimization or skip it — so that optimizing a workflow and accomplishing a real task are the same act: the execution authors the workflow composition (script segments, LLM bridge steps, decision steps) as a separate optimized implementation plan, verifying every script against REAL tool-call executions while accomplishing my task, and the verified plan is persisted for reuse.
- As an agent operator, I want the optimization run to first read the agent's own scripts and recent execution logs (including past failures) and skip re-authoring when everything is healthy and unchanged, so that optimization never wastes effort redoing good work.
- As an agent operator, I want to retire an optimized plan from the Optimized Plan tab so that the next run offers optimization again.
- As an agent operator, I want execution to prefer a fresh optimized plan but fall back to the base plan's LLM path when the optimized plan is absent, stale, or failed, so that optimization can never degrade behaviour.
- As an agent operator, I want script failures to fall back unconditionally to the LLM path so that a run never fails solely because a script failed.
- As a developer, I want a mock LLM layer with scripted, recorded, and replayed response modes so that I can test agent executions end-to-end without any LLM API.
- As a developer, I want to assert on prompts sent to the (mocked) LLM so that I can verify agent behaviour deterministically in CI.
- As an agent operator, I want script execution logs as clean one-line entries instead of truncated JSON blobs so that I can read them at a glance.
- As a business owner, I want `tokens_saved` on script execution records to reflect real token savings so that cost reporting is credible.

## Acceptance Criteria

### Sandbox & Scripting

- Scripts written in the sandboxed Python language can compute statistics, derive and pivot data, and assemble reports — capabilities beyond the previous declarative transform set.
- Sandboxed scripts cannot perform file, network, database, or any other I/O; attempted violations are blocked and logged.
- Sandboxed scripts cannot import anything outside the platform allowlist; only allowlisted builtins and safe libraries are visible to script code.
- A script that exceeds its CPU, memory, or wall-time cap is terminated safely, the failure is recorded, and execution falls back to the LLM path.
- MCP tool calls remain the ONLY external access from scripts, made through the injected client under the agent's identities and permissions (unchanged invocation contract).
- A deliberate attempt to escape the sandbox (e.g., disallowed import or attribute access) fails closed with a clear, recorded error.

### Model-Authored Composition (two-layer plan model)

- The base implementation plan is a plain high-level step list (action type, name, description); its prompt carries no composition authoring, no execution-semantics decision, and no script source.
- The optimized plan is produced by an OPT-IN step of the Run Agent flow: when the user launches the agent and no verified (`ready`) optimized plan exists, a dialog explains what optimization does and offers "Run with optimization" or "Skip optimization". Opting in turns that execution into the optimization opportunity — a command-prompt-driven special execution (prompted by the `optimize-and-verify` command mission plus the user's real task) runs the agent's model + the optimization system tools, and the model authors the composition against the sandbox capability contract — no hardcoded compiler templates. A `ready` plan means the run uses it directly.
- The optimization run is self-reflecting and real-integration-verified: it FIRST reads the agent's own state via `get_scripts`, `get_execution_log`, and `get_optimized_implementation_plan` (skipping re-authoring when scripts/logs show nothing wrong and the agent hasn't changed), then authors each script and **executes it against the real integration** — the tool calls inside the verification run for real (no stub clients); iterating until the scripts achieve the agent's mission. A bounded 3-attempt rule and `record_verification` failure entries keep failures honest, and a `needs_feedback` status prompts the user for steering. The verified optimized plan is persisted for reuse.
- "Retire plan" on the Optimized Plan tab clears the optimized plan (and its serving scripts) so the next run triggers the optimized-plan check again.
- The unconditionally appended `semantic____render` hardcoding is removed; workflows contain a summary step only when the model's composition includes one.
- The Script-First Dispatcher prefers a fresh optimized plan (ready AND newer than the base plan): a `fully_scripted` composition runs zero-LLM; otherwise its scripts are exposed as invocable tools and the LLM orchestrates. An absent, stale (e.g. base plan regenerated), or failed optimized plan falls back to the base plan's LLM path.
- Script source authored by the model is stored and versioned in the script registry; the lifecycle remains draft → verified → compiled → retired, with lineage unchanged, and the optimized plan is associated with the script versions it authored.
- Scripts authored by the model are validated and compiled (syntax and sandbox-compliance checked) before promotion; scripts that fail validation stay in draft with a recorded reason.

### LLM Mocking Framework

- Agent executions can run end-to-end against a mock LLM with no LLM API connectivity, in all three modes: scripted responses (deterministic, hand-authored), recorded real interactions, and replay of those recordings.
- Both the pure LLM path and script paths containing model-backed steps are testable with the mock layer.
- Tests can assert on the prompts sent to the LLM (content and structure) deterministically.
- The mock layer is wired into the backend test suite and e2e tests, so CI runs agent-execution tests with zero LLM cost and zero provider flakiness.
- Mock behaviour is deterministic: identical inputs and mock scripts produce identical runs.

### Observability & Accounting

- Script execution log entries are human-readable one-liners describing what happened (e.g., which step ran, what the script produced) with no truncated JSON blobs.
- Script execution records store real `tokens_saved` values (tokens actually avoided by running the script instead of the LLM path), not estimates or placeholders.

## Out of Scope

- General-purpose scripting for users: scripts remain agent-authored bridge/composition code between permitted tools, not a user-facing programming platform.
- Changes to the security architecture, identity topology, tool permission semantics, or the script lifecycle definition.
- Replacing the LLM agent loop — the LLM path remains the default for uncompiled workflows and the unconditional fallback.
- Script repair/self-improvement semantics beyond what the predecessor change already defines (unchanged).
- Mocking non-LLM dependencies (MCP tools, databases) beyond what existing test infrastructure already provides.
- New standalone admin surfaces for scripts — governance remains in the Scripts tab of the Agent Type detail dialog.

## Dependencies & Constraints

- **Depends on** the Software 3.0 Agent Framework change: script registry, Script-First Dispatcher, lifecycle states, Scripts tab, and the standardized invocation contract must be in place.
- **Complies with** `docs/config.yaml` top-priority rules: services fully segregated; agents (and their scripts) run only in Agent Runtime; only Control Center connects to the database; scripts and agents never receive sensitive data such as identity tokens or database credentials.
- **Sandbox technology constraint**: the sandbox must run inside Agent Runtime; RestrictedPython is the primary candidate and must be evaluated against WASM alternatives before final selection — the comparison and decision belong in the tech spec, not this PRD.
- **Registry compatibility**: model-authored script storage and versioning must reuse the existing script registry persistence and Control Center REST APIs without breaking the Scripts tab.
- **Test infrastructure constraint**: the mock LLM layer must integrate with the existing pytest backend suite and Playwright e2e suite.
