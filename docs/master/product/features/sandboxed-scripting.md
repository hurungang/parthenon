# Sandboxed Scripting & Model-Authored Composition (Software 3.0 Workflows)

## 1. Epic Overview

Parthenon's Software 3.0 capability lets the platform turn an agent's workflow, normally driven step-by-step by the AI model, into compiled, repeatable automations that largely avoid repeated model calls. This feature graduates those compiled workflows from a limited set of fixed data operations to **real sandboxed scripting**: the model authors genuine programs that can compute statistics, derive and pivot data, and assemble reports — running under hard security invariants so that expressiveness never weakens the platform's security model. Workflow composition itself moves from hardcoded templates to **model-authored composition**: alongside the agent's plain high-level implementation plan, the model authors a separate **optimized implementation plan** (script segments, model bridge steps, decision steps) as an opt-in step of the Run Agent flow, verified against real tool-call executions before it is served. Execution prefers a fresh optimized plan — including a fully-scripted mode that runs with **zero model calls** — and falls back unconditionally to the standard model-driven path whenever the optimized plan or any script is unavailable or fails, so optimization can never degrade behaviour. A hardening pass aligns the sandbox with the sandboxing technology's own audited safe-language baseline (so valid language constructs stop failing), makes optimization failures visible to operators, requires the optimizer to review its own evidence before authoring, and removes silent no-ops from the optimization lifecycle.

## 2. Business Goals

- Increase the share of agent runs served by compiled scripts instead of live model calls (the "compilation rate"), making more workflows cheaper, faster, and repeatable.
- Reduce model spend with trustworthy measurement: reported token savings on script executions reflect real avoided model usage, credible enough for cost governance.
- Eliminate wasted steps: workflows contain only the steps the model's composition actually needs, with no unconditionally appended summary step.
- Enable continuous, deterministic end-to-end testing of agent executions with zero model-API cost and zero provider flakiness.
- Preserve trust and auditability: script executions are logged as clean, human-readable entries, any failure degrades silently to the familiar model-driven path, valid business logic is never rejected because of a gap in the sandbox's language baseline, and optimization failures are visible to operators rather than silent.

## 3. Users & Personas

- **Platform Administrator** — governs model-authored scripts in the existing Scripts tab of the Agent Type detail dialog (version history, lifecycle from draft through verified and compiled to retired, health, description); needs confidence that richer scripting introduces no security regression.
- **Agent Operator** — launches and monitors executions; needs the choice to run with optimization or skip it, readable script execution logs, and trustworthy fallback behaviour.
- **Developer / QA Engineer** — tests agent executions end-to-end; needs deterministic runs without any model-API access, including tests that assert on what was asked of the model.
- **Enterprise Consumer / Business Owner** — benefits silently: more workflows run compiled (cheaper, faster, repeatable) while execution provenance remains visible.

## 4. User Stories

### Sandboxed Scripting

- As a platform administrator, I want scripts to run in a hard sandbox (no file, network, or database access; only vetted language capabilities; capped computing resources) so that more expressive scripting cannot weaken the security model.
- As a platform administrator, I want the sandbox to start from one audited safe-language baseline with only documented guards layered on top, so that valid scripts stop failing on standard language constructs and the capability surface stays auditable.
- As a platform administrator, I want every script validated and compiled before promotion so that broken or unsafe scripts never reach execution.
- As a platform administrator, I want model-authored scripts stored and versioned in the existing script registry with the unchanged lifecycle (draft → verified → compiled → retired) so that governance does not change.
- As an agent operator, I want scripts to reach external tools only through the agent's own permitted tool access so that scripts never gain identities or permissions of their own.

### Optimize-and-Verify (Command-Driven Side Execution)

- As an agent operator, I want the base implementation plan to stay a plain, readable high-level step list so that I can review and govern what the agent will do.
- As an agent operator, I want optimization offered as an opt-in step of the Run Agent flow — when no verified optimized plan exists, a dialog explains the value and lets me run with optimization or skip it — so that optimizing a workflow and accomplishing a real task are the same act.
- As an agent operator, I want the optimization run to review the agent's own current scripts, recent execution logs (including past failures), and any prior optimized plan before authoring anything — and to skip re-authoring when everything is healthy and unchanged — so that optimization never works from stale state or wastes effort redoing good work.
- As an agent operator, I want every script verified against the real integration during the optimization run — the tool calls run for real while I accomplish my task — so that the optimized plan is proven on the actual work, not on artificial tests.
- As an agent operator, I want bounded verification attempts and honest failure recording, with the recorded failure reason shown to me alongside a prompt for my steering when the model needs feedback, so that optimization never silently claims success and I know what to fix.
- As an agent operator, I want to retire an optimized plan from the Optimized Plan tab so that the next run offers optimization again, and I want a clear "nothing to retire" message when there is no active plan so that retire is never a silent no-op.

### Scripts-as-Tools, Fully Scripted Mode, and Fallback

- As an agent operator, I want execution to prefer a fresh optimized plan but fall back to the base plan's model-driven path when the optimized plan is absent, stale, retired, or failed, so that optimization can never degrade behaviour.
- As an agent operator, I want script failures to fall back unconditionally to the model-driven path so that a run never fails solely because a script failed.
- As a business owner, I want fully-scripted workflows to complete with zero model calls so that routine work runs at minimal cost with maximum determinism.
- As a platform administrator, I want scripts in a mixed composition exposed to the model as invocable tools so that the model orchestrates only the steps that genuinely need its judgment.

### Testing & Observability

- As a developer, I want a mock model layer with scripted, recorded, and replayed responses so that I can test agent executions end-to-end without any model API.
- As a developer, I want to assert on the prompts sent to the model so that agent behaviour is verified deterministically in CI.
- As an agent operator, I want script execution logs as clean one-line descriptions instead of truncated data dumps so that I can read them at a glance.
- As a business owner, I want token-savings figures on script executions to reflect real avoided model usage so that cost reporting is credible.

## 5. Acceptance Criteria

### Sandbox & Scripting

- Sandboxed scripts can compute statistics, derive and pivot data, and assemble reports — beyond what the previous fixed transform operations allowed.
- Sandboxed scripts cannot perform file, network, database, or any other external access; attempted violations are blocked and logged.
- The sandbox's language capability comes from a single audited safe-language baseline supplied by the sandboxing technology, applied as a whole rather than assembled allowance by allowance; standard constructs such as assigning several values at once and updating a variable in place work without error.
- Only documented, individually tested platform guards sit on top of that baseline: the tool-access layer (permitted tools only), the agent-context binding, and the resource caps. Any future guard must be documented and tested before it is added.
- A script exceeding its computing, memory, or time cap is terminated safely, the failure is recorded, and execution falls back to the model-driven path.
- External tool access from scripts remains exclusively through the agent's permitted tool connections, under the agent's identities and permissions; scripts hold no identity, credentials, or grants of their own.
- A deliberate sandbox escape attempt fails closed with a clear, recorded error.

### Model-Authored Composition (Two-Layer Plan Model)

- The base implementation plan remains a plain high-level step list; its content carries no composition authoring and no script source.
- When a user launches an agent with no verified optimized plan, a dialog explains what optimization does and offers "Run with optimization" or "Skip optimization".
- Opting in turns that execution into an optimization run: guided by a built-in optimization directive plus the user's real task, the agent's model authors the composition (script segments, model bridge steps, decision steps) using dedicated optimization assistance tools — with no hardcoded composition templates.
- The optimization run's directive requires it to read the agent's current scripts, its execution logs, and any prior optimized plan before authoring anything; when those are healthy and the agent is unchanged, it skips re-authoring and says so.
- Each authored script is executed against the real integration during verification — tool calls run for real while the user's task is accomplished — iterating until the scripts achieve the agent's mission.
- Verification is bounded (a small fixed number of attempts); failures are recorded honestly, and a "needs feedback" state prompts the user for steering.
- When optimization ends in "needs feedback", the failure reason is recorded on the optimized plan and displayed in the Optimized Plan tab, so the operator can see what to fix or how to steer — no more empty failure states.
- The verified optimized plan is persisted automatically for reuse, and is associated with the script versions it authored.
- "Retire plan" on the Optimized Plan tab clears the optimized plan and its serving scripts, so the next run offers optimization again.
- When there is no active optimized plan, the Optimized Plan tab shows a clear "nothing to retire" state instead of a silent no-op.
- Workflows contain a summary step only when the model's composition includes one — no step is ever appended unconditionally.
- Model-authored scripts are validated (structure and sandbox compliance) and compiled before promotion; scripts failing validation remain in draft with a recorded reason.

### Execution Preference & Fallback

- Execution prefers a fresh optimized plan (verified and newer than the base plan).
- A fully-scripted optimized plan runs with zero model calls.
- Otherwise, the optimized plan's scripts are exposed to the model as invocable tools, and the model orchestrates them.
- An absent, stale (e.g., base plan regenerated), retired, or failed optimized plan falls back to the base plan's model-driven path.
- Any script failure — including sandbox cap violations — falls back unconditionally to the model-driven path with the reason recorded; a run never fails solely because a script failed.
- The execution outcome model includes a partial-failure outcome alongside clean success and failure, so a run whose tool interaction did not fully succeed can be recorded distinctly instead of as a plain success; classifying a run as a partial failure is not yet automatic (see Out of Scope).
- No execution-mode configuration is required from users; the preference and fallback behaviour is fixed.

### LLM Mocking & Testability

- Agent executions run end-to-end against a mock model with no model-API connectivity, in three modes: scripted (deterministic hand-authored responses), recorded (capture real interactions), and replayed.
- Both the pure model-driven path and script paths containing model-backed steps are testable with the mock layer.
- Tests can assert deterministically on the prompts sent to the model.
- Automated test suites exercise full agent executions with zero model cost and zero provider flakiness.
- Identical inputs and mock scripts produce identical runs.

### Observability & Accounting

- Script execution log entries are human-readable one-liners (which step ran, what it produced) with no truncated data blobs.
- Script execution records store real measured token savings — tokens genuinely avoided by running the script instead of the model-driven path — not estimates.
- After closing any script or optimized-plan management dialog, the parent view automatically refreshes to show updated lifecycle state, health, and counts without a manual page reload.

## 6. Out of Scope

- General-purpose scripting for users — scripts remain agent-authored automation glue between permitted tools, not a user-facing programming platform.
- Changes to the security architecture, identity topology, tool permission semantics, or the script lifecycle definition.
- Replacing the model-driven agent loop — it remains the default for uncompiled workflows and the unconditional fallback.
- Script repair/self-improvement semantics beyond those already defined by the Software 3.0 Agent Framework.
- Mocking of non-model dependencies (external tools, databases) beyond what existing test infrastructure provides.
- New standalone admin surfaces for scripts — governance remains in the Scripts tab of the Agent Type detail dialog.
- Automatic platform-level detection of a semantic error hidden inside an otherwise successful tool response, and any automatic fallback, repair, or re-optimization reaction to partial failure. By product decision this detection is deferred: the partial-failure outcome exists in the execution outcome model, but nothing sets it automatically yet, and scripts are expected to handle unexpected tool-result shapes defensively. That defensive handling is the accepted mitigation.
- Redesign of the Optimized Plan view beyond showing the recorded failure reason and the "nothing to retire" state.

## 7. Dependencies & Constraints

- Depends on the Software 3.0 Agent Framework: script registry, script-first dispatcher, lifecycle states, Scripts tab, and the standardized invocation contract.
- Complies with platform top-priority rules: fully segregated services; agents and their scripts run only in Agent Runtime; only Control Center connects to the database; agents and scripts never receive sensitive data such as identity tokens or database credentials.
- The sandbox runs inside Agent Runtime; its underlying technology is chosen in the technical specification, subject to the hard invariants above.
- Script storage, versioning, and governance reuse the existing script registry and Control Center interfaces without breaking the Scripts tab.
- The mock model layer integrates with the existing backend and end-to-end test suites.
- The sandbox's language capability tracks the sandboxing technology's own audited baseline; platform guards are strictly additive, documented, and individually tested. Script authors must not rely on capabilities outside that baseline plus the documented guards.
- Partial-failure reporting is a recorded outcome only. Because automatic semantic-error detection is deferred, operators should not expect automatic fallback, repair, or re-optimization to react to a partial failure today; scripts must tolerate unexpected tool-result shapes.
