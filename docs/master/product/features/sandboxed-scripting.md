# Sandboxed Scripting & Model-Authored Composition (Software 3.0 Workflows)

## 1. Epic Overview

Parthenon's Software 3.0 capability lets the platform turn an agent's workflow, normally driven step-by-step by the AI model, into compiled, repeatable automations that largely avoid repeated model calls. This feature graduates those compiled workflows from a limited set of fixed data operations to **real sandboxed scripting**: the model authors genuine programs that can compute statistics, derive and pivot data, and assemble reports — running under hard security invariants so that expressiveness never weakens the platform's security model. Workflow composition itself moves from hardcoded templates to **model-authored composition**: alongside the agent's plain high-level implementation plan, the model authors a separate **optimized implementation plan** (script segments, model bridge steps, decision steps), verified against the agent's recorded tool-call evidence before it is served. Optimization is its own explicit action — never a side effect of running the agent — and is also available as an interactive **optimization conversation** held on the agent itself. Execution prefers a fresh optimized plan — including a fully-scripted mode that runs with **zero model calls** — and falls back unconditionally to the standard model-driven path whenever the optimized plan or any script is unavailable or fails, so optimization can never degrade behaviour. A hardening pass aligns the sandbox with the sandboxing technology's own audited safe-language baseline (so valid language constructs stop failing), makes optimization failures visible to operators, requires the optimizer to review its own evidence before authoring, and removes silent no-ops from the optimization lifecycle.

## 2. Business Goals

- Increase the share of agent runs served by compiled scripts instead of live model calls (the "compilation rate"), making more workflows cheaper, faster, and repeatable.
- Reduce model spend with trustworthy measurement: reported token savings on script executions reflect real avoided model usage, credible enough for cost governance.
- Eliminate wasted steps: workflows contain only the steps the model's composition actually needs, with no unconditionally appended summary step.
- Enable continuous, deterministic end-to-end testing of agent executions with zero model-API cost and zero provider flakiness.
- Preserve trust and auditability: script executions are logged as clean, human-readable entries, any failure degrades silently to the familiar model-driven path, valid business logic is never rejected because of a gap in the sandbox's language baseline, and optimization failures are visible to operators rather than silent.
- Eliminate the confusion between running an agent and optimizing it: a normal run is always the user's task, and optimization is a deliberate, preconditioned action.
- Author plans with the right model: optimized plans are written by the workspace's approved authoring (optimizer) model, never by the agent's small runtime model.
- Turn optimization dead ends into resolutions: an interactive optimization conversation replaces blind retries, while replay remains the default and every live script run needs a single-use approval.

## 3. Users & Personas

- **Platform Administrator** — governs model-authored scripts from the agent type's plan surface (script viewer with version history, lifecycle from draft through verified and compiled to retired, health, description); needs confidence that richer scripting introduces no security regression.
- **Agent Operator** — launches and monitors executions; triggers optimization deliberately (one-shot or conversationally), reviews optimized plans and their alerts, and needs readable script execution logs and trustworthy fallback behaviour.
- **Workspace Administrator** — chooses the workspace's authoring/optimizer model and is told plainly when it is missing or no longer available.
- **Developer / QA Engineer** — tests agent executions end-to-end; needs deterministic runs without any model-API access, including tests that assert on what was asked of the model.
- **Enterprise Consumer / Business Owner** — benefits silently: more workflows run compiled (cheaper, faster, repeatable) while execution provenance remains visible.

## 4. User Stories

### Sandboxed Scripting

- As a platform administrator, I want scripts to run in a hard sandbox (no file, network, or database access; only vetted language capabilities; capped computing resources) so that more expressive scripting cannot weaken the security model.
- As a platform administrator, I want the sandbox to start from one audited safe-language baseline with only documented guards layered on top, so that valid scripts stop failing on standard language constructs and the capability surface stays auditable.
- As a platform administrator, I want every script validated and compiled before promotion so that broken or unsafe scripts never reach execution.
- As a platform administrator, I want model-authored scripts stored and versioned in the existing script registry with the unchanged lifecycle (draft → verified → compiled → retired) so that governance does not change.
- As an agent operator, I want scripts to reach external tools only through the agent's own permitted tool access so that scripts never gain identities or permissions of their own.

### Optimization as Its Own Action

- As an agent operator, I want the base implementation plan to stay a plain, readable high-level step list so that I can review and govern what the agent will do.
- As an agent operator, I want a dedicated Optimize action separate from Run, so that running the agent is always focused on my task and never turns into an optimization mission.
- As an agent operator, I want Optimize to require at least one successful run of the agent and an available authoring model first, so that optimization starts only when it has a real reference execution and a model to work from — and I am told exactly what is missing otherwise.
- As an agent operator, I want the optimization mission to use the agent's optimization instructions, the current implementation plan, other agent information, and its execution history, and to prefer the latest execution rather than fetching excessive logs, so that optimization stays focused on current reality.
- As an agent operator, I want the optimization goal to be correct script syntax and proper tool invocation rather than an identical result to the reference run, so that legitimately empty or varying tool results do not trigger endless retries.
- As an agent operator, I want optimization to stop when it cannot reach high confidence, so that it never burns compute in a dead loop.
- As an agent operator, I want every script verified against recorded execution evidence by default, and a live run only when I approve one specific script once, so that the optimized plan is proven without unattended live testing.
- As an agent operator, I want the next execution after optimization to try the optimized plan first, so that optimization delivers faster, cheaper runs.
- As an agent operator, I want the platform to mark an optimized plan as requiring a fix and record feedback automatically when a later execution falls back because of it, and to alert me the next time I open the agent, so that a known-bad plan does not keep silently failing and I can re-optimize with that feedback.
- As an agent operator, I want to add feedback to an optimized plan manually at any time, so that I can steer re-optimization myself.
- As an agent operator, I want to retire an optimized plan so that the next run offers optimization again, and a clear "nothing to retire" message when there is no active plan, so that retire is never a silent no-op.

### Conversational Optimization

- As an agent operator, I want to start an optimization conversation from the agent's Optimized Plan tab, so that I can watch and steer optimization instead of triggering it blind.
- As an agent operator, I want that conversation to be a mode of my own agent — same identity and same permissions — so that optimizing can never do anything the agent could not already do.
- As an agent operator, I want the optimizer to ask me a question or a decision in the chat when it is blocked, so that I can resolve it in the same session rather than re-optimizing blindly.
- As an agent operator, I want a roomy, readable chat: a compact "What ran in this session" summary, and a live-test request that folds into one line once I have decided.
- As an agent operator of a conversational agent, I want the same optimization conversation available to me, so that conversational agents are not a second-class case.

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
- Optimization is a **separate, explicitly triggered action** on the agent surface; a normal run always uses the agent's own instructions and never becomes an optimization mission, and no run-mode option turns a real task into optimization.
- The Optimize action is available only after at least one successful execution of the agent exists; before that it is unavailable with a clear explanation of what is missing.
- The Optimize action is also unavailable while no usable authoring (optimizer) model is configured for the workspace; the user is told the model is missing, pointed to System Config, and no optimization run starts.
- Triggering Optimize launches a dedicated optimization execution — guided by a built-in optimization directive plus the agent's optimization instructions, the current implementation plan, other agent information, and its execution history — with no hardcoded composition templates.
- The optimization mission reviews the agent's current scripts, its execution history, and any prior optimized plan before authoring anything; it prefers the latest execution and reviews only a limited amount of recent history.
- The optimized plan and its scripts are authored by the **workspace's approved authoring/optimizer model**, never by the agent type's own runtime model.
- The optimization goal is correct script syntax and proper tool invocation — not reproducing the reference run's result; a differing or legitimately empty tool result does not cause re-attempts to force a match.
- Verification proceeds from the agent's recorded execution evidence by default (replay). When replay cannot proceed — no recorded tool data, or a script needing a tool or response that run did not record — optimization stops, records "needs your input" with a specific explanation, and asks the user for a real run or guidance; it never retries in a loop and never invokes a live tool on its own.
- A live run of the script under test happens only through an explicit, single-use operator approval (see Conversational Optimization); the tools it calls are assumed to work, and there is no separate per-tool test.
- Verification is bounded; failures are recorded honestly, and a "needs your input" state prompts the user for steering rather than looping.
- When optimization ends needing input, the blocker is recorded on the optimized plan and displayed in the Optimized Plan tab, so the operator can see what to fix or how to steer — no empty failure states.
- The optimized plan is persisted for reuse, is associated with the script versions it authored, and follows the same lifecycle and verification rules whether it was produced by the one-shot action or by a conversation — nothing bypasses verification because it was discussed in chat.
- "Retire plan" on the Optimized Plan tab clears the optimized plan and its serving scripts, so the next run offers optimization again.
- When there is no active optimized plan, the Optimized Plan tab shows a clear "nothing to retire" state instead of a silent no-op.
- Workflows contain a summary step only when the model's composition includes one — no step is ever appended unconditionally.
- Model-authored scripts are validated (structure and sandbox compliance) and compiled before promotion; scripts failing validation remain in draft with a recorded reason.

### Conversational Optimization

Optimization is also available as a distinct conversation channel on the agent being optimized, opened from the Optimized Plan tab:

- The conversation runs on the agent type itself, as an optimization mode: the optimization mission replaces the agent's business instructions and skills for the duration of that conversation, and the agent's business behaviour, skills and tool permissions are unchanged outside it.
- It is available for both typed and conversational agent types, with the same behaviour and safety rules, and is gated by the same preconditions as the one-shot action (a successful reference execution and a usable authoring model); when one is missing, the conversation explains it and starts no work.
- No new agent identity, agent type, role, or permission is introduced: the optimizer acts with exactly the agent's identity, role and permissions and never more broadly.
- Its scope is the one selected agent's plan, scripts, execution history, and base plan; requests touching other agents, plans, workspace settings, permissions, or deletions are declined with a clear explanation and change nothing.
- The operator sees that the optimizer is working, which steps it is taking, and what it looked at; detail can be expanded or collapsed so a busy turn stays readable.
- The optimizer can ask a question or present a decision in the chat; the conversation shows it is waiting, blocks further messages until answered, and re-surfaces the pending question after reconnect. An unanswered question never causes an assumption or a background retry.
- **Replay-only is the default.** When replay cannot prove a script, or when the operator explicitly asks for a live check, the optimizer may ask to run the **script under test once**, named with its version, showing the tool calls it will make as an informational preview; the approval covers running that script, not individual tool calls.
- Approve or deny: approval runs the script once end to end as the agent's own operation in its workspace, the result returns to the conversation, and further live work requires a new request and approval. Denial, silence, or expiry keeps the session replay-only, and a used approval cannot be re-applied.
- Requests for unbounded or session-long live access, or beyond the agent's existing permissions, are refused with a clear explanation; a failed or permission-denied run starts no further live work and returns the session to replay-only.
- The chat shows a compact, **default-collapsed "What ran in this session"** bar — replay versus approved-live counts plus the current replay-only state — that expands into the audit detail rather than occupying the conversation as a persistent header.
- The live-test approval card collapses into a one-line chat-history summary once decided (approved, running, executed, failed, denied, expired, or cancelled) and can be expanded again; collapsing changes display only, never the recorded decision or audit entry.
- A session always reaches a bounded end state — a ready plan, an explicit needs-input stop the operator can act on in the same session, or an explicit failure — with no unbounded retry.
- Improvements agreed in the conversation land on the agent's optimized plan, and the Optimized Plan tab refreshes automatically afterwards without a page reload.
- The script lifecycle, retire behaviour, and execution preference/fallback behaviour are unchanged by conversational optimization.

### Execution Preference & Fallback

- Execution prefers a fresh optimized plan (verified and newer than the base plan).
- A fully-scripted optimized plan runs with zero model calls.
- Otherwise, the optimized plan's scripts are exposed to the model as invocable tools, and the model orchestrates them.
- An absent, stale (e.g., base plan regenerated), retired, or failed optimized plan falls back to the base plan's model-driven path.
- Any script failure — including sandbox cap violations — falls back unconditionally to the model-driven path with the reason recorded; a run never fails solely because a script failed.
- When the fallback is caused by the optimized plan, the plan is marked **requires a fix** and feedback describing the failure is recorded automatically (kept distinct from operator-entered feedback), so a known-bad plan is not silently re-served.
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
- New standalone admin surfaces for scripts — governance remains on the agent type's plan surface via the script viewer.
- Automatic platform-level detection of a semantic error hidden inside an otherwise successful tool response, and any automatic fallback, repair, or re-optimization reaction to partial failure. By product decision this detection is deferred: the partial-failure outcome exists in the execution outcome model, but nothing sets it automatically yet, and scripts are expected to handle unexpected tool-result shapes defensively. That defensive handling is the accepted mitigation.
- Automatic or unattended re-optimization: a plan that requires a fix is recorded and the operator is alerted, but optimization never re-runs on its own.
- Automatic or scheduled optimization, and any plan authoring triggered by creating or saving an agent.
- A dedicated optimizer agent, agent type, role, or permission set — optimization adds no identity of its own.
- Approving individual tool calls one at a time, or any "always allow live" / remembered-approval mode.
- Changing how scripts are sandboxed, validated, versioned, promoted, or retired; the script registry and lifecycle stay as they are.
- Changing execution preference and fallback semantics beyond the requires-fix marking and auto-recorded feedback.
- Redesign of the Optimized Plan view beyond the recorded failure reason, the "nothing to retire" state, the conversation entry, and the refresh after a generation.

## 7. Dependencies & Constraints

- Depends on the Software 3.0 Agent Framework: script registry, script-first dispatcher, lifecycle states, script viewer, and the standardized invocation contract.
- Depends on the workspace's approved authoring model setting (shared with Skill/SOP workflow generation) and, when set, the workspace optimizer model that falls back to it; without a usable model, optimization and plan authoring are unavailable by design rather than silently substituted.
- Depends on the existing conversational-agent experience for the optimization conversation (multi-turn context, working/waiting indicators, inline input requests, session persistence), and on the existing agent identity, role, and tool-permission model, which optimization inherits unchanged.
- Live tests carry real cost and side effects: replay-only, explicit script-based single-use approval, and no automatic re-run are the controls, not options.
- Complies with platform top-priority rules: fully segregated services; agents and their scripts run only in Agent Runtime; only Control Center connects to the database; agents and scripts never receive sensitive data such as identity tokens or database credentials.
- The sandbox runs inside Agent Runtime; its underlying technology is chosen in the technical specification, subject to the hard invariants above.
- Script storage, versioning, and governance reuse the existing script registry and Control Center interfaces without breaking the existing script viewer.
- The mock model layer integrates with the existing backend and end-to-end test suites.
- The sandbox's language capability tracks the sandboxing technology's own audited baseline; platform guards are strictly additive, documented, and individually tested. Script authors must not rely on capabilities outside that baseline plus the documented guards.
- Partial-failure reporting is a recorded outcome only. Because automatic semantic-error detection is deferred, operators should not expect automatic fallback, repair, or re-optimization to react to a partial failure today; scripts must tolerate unexpected tool-result shapes.
