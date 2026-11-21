# PRD: Separate Optimization from Execution

## Epic Overview

Today, optimizing an agent's workflow and running that agent are the same act. The "Run Agent" dialog offers "Run with optimization," which silently converts the user's real task into a special optimization mission — replacing the agent's own system and skill instructions with an optimization directive and running it as a side execution. This entangles two very different goals (complete a real task vs. author a better plan) in a single run. It confuses the agent, and when the real task has a legitimately empty result — for example, a booking lookup that finds nothing — the optimizer can chase an unreproducible outcome and loop indefinitely. This epic separates the two concerns: running an agent stays focused on the user's task, while optimization becomes its own explicit, preconditioned, human-kept-in-the-loop action that stays realistic, bounded, and self-correcting without burning compute in dead loops. It also puts plan authoring on the right footing: implementation plans and optimized plans are written only when an operator asks for them, by the workspace's single approved higher-end authoring model rather than by the small model an agent happens to run on, and only for agents that can actually be optimized.

## Business Goals

- Eliminate confusion between "run the agent" and "optimize the agent": a normal execution never doubles as an optimization mission.
- Author plans with the right model: implementation plans and optimized plans are written by one approved, higher-end workspace model instead of the agent's own (typically small and cheap) runtime model, so plan quality is never capped by the agent's model choice.
- Generate plans on demand only: no plan authoring work or model spend happens as a side effect of creating or editing an agent; plans are produced when an operator explicitly asks for them.
- Make the model dependency obvious and safe: administrators can see in one place what the authoring model is used for, are advised to choose a larger model, and are clearly reminded when it is not configured — with no silent fallback that could degrade plan quality.
- Reduce wasted compute and dead loops: optimization always stops when it lacks high confidence instead of looping to reproduce an identical result.
- Make improvement self-correcting but human-gated: when an optimized plan fails on a later run, the platform records it as needing a fix and alerts the operator, without ever mutating behavior silently or re-optimizing on its own.

## Users & Personas

- **Agent Operator** — launches agents, generates plans, triggers optimization, and reviews optimized plans; wants a clean separation so running and optimizing don't interfere, wants plans generated only when they ask, and wants clear warnings when an optimized plan has failed in production.
- **Workspace Administrator** — owns the workspace's model configuration; needs to understand what the authoring model is used for (Skill/SOP workflow generation, implementation plans, optimization plans), pick one higher-end model for the workspace, and be told plainly when it is missing.
- **Platform Administrator** — governs agents and their optimized plans; wants optimization to be realistic, bounded, and auditably human-driven so it never risks runaway compute or silent regressions.
- **Business Owner** — benefits silently: normal runs stay focused and predictable, and optimization improves cost/latency without destabilizing execution.

## User Stories

- As an agent operator, I want a dedicated Optimize action separate from Run, so that running an agent never turns into an optimization mission.
- As an agent operator, I want optimization to require at least one successful run of the agent first, so that the optimizer always has a real reference execution to learn from.
- As an agent operator, I want the optimization run to use the agent's optimization instructions, the current implementation plan, other agent information, and access to execution logs, so that it can complete the optimized plan with scripts without hijacking a normal run.
- As an agent operator, I want the optimizer to prefer the latest execution and not fetch excessive execution logs, so that optimization stays fast and focused on current reality.
- As an agent operator, I want the optimizer to accept that the agent's tool calls may return different results on each call and to aim for correct script syntax and proper tool invocation rather than identical output, so that legitimately empty or varying results don't cause infinite loops.
- As an agent operator, I want the optimizer to stop when it has no high-confidence result, so that it never enters a dead loop.
- As an agent operator, I want the next execution after optimization to try the optimized plan first, so that optimization delivers faster, cheaper runs.
- As an agent operator, I want the platform to automatically mark an optimized plan as requiring a fix and record feedback when a later execution falls back to the model path because of it, so that a known-bad plan doesn't keep silently failing.
- As an agent operator, I want to see an alert about a problematic optimized plan the next time I open the agent, so that I can decide to re-optimize with the prior plan plus the recorded feedback as context.
- As an agent operator, I want to be able to add feedback to an optimized plan manually at any time (as today), so that I can steer re-optimization myself.
- As an agent operator, I want to re-run optimization after a failure with the prior plan and the recorded feedback, so that the next optimized plan is informed by what actually failed.
- As an agent operator, I want to generate or re-generate the implementation plan only when I explicitly ask, so that saving an agent never spends model time or silently replaces a plan I have reviewed.
- As an agent operator, I want plan generation and optimization to be driven by my workspace's approved authoring model rather than the agent's own model, so that a cheap runtime model never holds back plan quality.
- As an agent operator, I want to be told clearly that no authoring model is configured when I try to generate a plan or optimize, so that I know exactly what to fix instead of seeing a failed or empty result.
- As a workspace administrator, I want the System Config page to explain what the authoring model is used for, recommend a larger model, and remind me when it is not set, so that I can configure it correctly once for my workspace.
- As a workspace administrator, I want the authoring model to apply to my workspace only, so that each workspace can choose a model that fits its own plan quality and cost expectations.
- As an agent operator working with a conversational agent, I want plan generation and optimization to be unavailable with a clear explanation, so that I'm not misled into expecting a plan for an agent that doesn't have one.

## Acceptance Criteria

### Separation & Precondition

- The agent launch/run surface exposes a distinct Optimize action that is separate from Run; running an agent never performs optimization.
- The Optimize action is available only after at least one successful execution of the agent has been recorded; before that, it is disabled (or hidden) with a clear explanation.
- The Optimize action is also unavailable while no authoring model is configured for the workspace; in that state the user is told the model is missing and pointed to System Config, and no optimization run is started.
- A normal execution uses the agent's own system and skill instructions; no normal run has its prompt replaced by an optimization mission.

### Plan Generation Trigger

- Creating, saving, or updating an agent never generates or regenerates an implementation plan; no authoring work, model spend, or plan overwrite happens as a side effect of a save.
- The implementation plan is generated only on an explicit user request; the Plan Preview surface offers that request and shows, before the first generation, that no plan exists yet and how to generate one.
- Requesting a plan while no authoring model is configured produces a clear, user-facing explanation that the model is not configured (with a pointer to System Config); no plan is generated and no alternative model is used.
- A failed generation attempt shows its reason and never discards the last successful plan.
- If the agent's configuration has changed since the plan was last generated, the Plan Preview indicates the plan may be out of date and offers regeneration; it is not regenerated automatically.
- After an explicit generation completes, the plan view updates automatically to show the new plan without a manual page reload.
- The same explicit-only rule applies to the optimized plan: it is produced only when the operator triggers Optimize.

### Plan Authoring Model & System Config

- Implementation-plan generation and optimization-plan generation both use the workspace's approved authoring model (the same workspace-level model used for Skill/SOP workflow generation); the agent type's own runtime model is never used for authoring plans.
- There is exactly one authoring model per workspace: setting or changing it immediately governs all subsequent implementation-plan and optimization-plan generation in that workspace, with no second setting to keep in sync.
- The authoring model setting is workspace-scoped (a workspace is a tenant): a change made in one workspace never affects plan generation in another, and a deployment with multi-tenancy disabled uses its single default workspace's setting.
- Only models enabled in the workspace's model catalogue can be chosen as the authoring model.
- If the configured authoring model is later disabled or removed from the workspace catalogue, plan generation and optimization become unavailable, the same "not configured" reminder appears, and the user is asked to re-select a valid model.
- The recommendation to use a larger model is advisory: choosing a smaller enabled model is allowed and is never blocked.
- The System Config surface explains what the model is used for — Skill/SOP workflow generation, implementation-plan generation, and optimization-plan generation — and states that the choice applies to the current workspace.
- The System Config surface recommends choosing a larger / higher-end model, making clear that plan authoring quality depends on it and that agents' runtime models are a separate choice.
- When no authoring model is configured, System Config shows a clearly visible reminder to configure one; the reminder disappears once a model is saved.

### Conversational Agents Excluded

- Implementation-plan generation and optimization-plan generation are not available for conversational agents; the related controls are hidden or disabled with a clear explanation.
- No plan or optimization is generated for a conversational agent in the background or indirectly through any other surface.
- Conversational agents continue to behave exactly as before this epic: they keep their own instructions, have no plan preview generation, and are never compiled into optimized plans.
- Any plan authored before an agent is converted to conversational is retained for reference but is not used to generate or optimize again while the agent remains conversational.

### Optimization Execution

- Triggering Optimize launches a dedicated optimization execution that uses the agent's optimization instructions, the current implementation plan, other agent information, and access to execution logs — without changing the agent's normal behavior.
- The optimization execution prefers the latest successful execution as its reference and reviews only a limited amount of recent execution history.
- The optimization goal is: produced scripts have correct syntax and invoke the agent's tools properly — not to reproduce an identical result to the reference execution. A differing (or legitimately empty) tool result does not cause re-attempts to force a match.
- When the optimizer cannot reach high confidence in the result, it stops and records its outcome rather than looping; there is a clear, bounded end state with no dead loop.
- When replay verification cannot proceed — the reference execution recorded no tool data, or the script needs a tool/response that run did not record — the optimizer stops, records `needs_feedback` with a specific explanation of what is missing, and asks the user for a real run or guidance; it never retries in a loop and never invokes a live tool.
- The Optimized Plan tab presents a `needs_feedback` outcome as "Optimization needs your input", showing the specific blocker and the feedback / re-optimize actions.

### Plan Consumption & Self-Healing

- After a successful optimization, the next execution attempts to use the optimized plan first.
- If that execution fails and falls back to the model-driven path, and the platform determines the optimized plan is the cause, the platform marks the plan as requiring a fix and automatically records feedback describing the failure.
- A plan marked as requiring a fix is not silently re-served as-is; execution continues to fall back to the model-driven path so behavior never degrades.

### Human-in-the-Loop Alert & Re-Optimization

- The next time the user opens the agent (or its Optimized Plan tab), an alert is shown about the problematic plan, indicating it requires a fix.
- From that alert, the user can trigger optimization again; the new optimization run receives the context of the previous plan plus the feedback recorded from the failed execution.
- The user can still add feedback to an optimized plan manually, as before.
- After a re-optimization completes, the Optimized Plan tab refreshes automatically to show the updated plan state without a manual page reload.

### No-Regression Guarantees

- Execution remains focused on the user's task in all cases; optimization is never a side effect of a normal run.
- No plan is authored unless a user asked for it; there is no automatic or scheduled plan generation anywhere in the product.
- Plan authoring and optimization are always performed by the workspace's approved authoring model; the agent's runtime model is never used for them, and there is no silent fallback when the authoring model is absent.
- Optimization remains bounded and realistic: it never loops to reproduce an identical result, and it always terminates with a clear outcome.
- All self-improvement is human-gated: the platform records and alerts, but never loops automatically.

## Out of Scope

- Automatic (unattended) re-optimization loops: the platform records a requires-fix plan and alerts the user, but does not re-run optimization on its own.
- Automatic plan generation or regeneration on agent create/save, on configuration change, or on any schedule.
- Choosing a different authoring model per agent type, per skill, or per user; there is one approved authoring model per workspace.
- Falling back to the agent's runtime model, a default model, or any other model when the authoring model is not configured.
- Any plan generation or optimization capability for conversational agents.
- Letting users hand-edit generated plan steps, or maintain multiple plan versions side by side.
- Changing how scripts are sandboxed, versioned, or promoted; the script registry and lifecycle stay as they are.
- Changing execution preference and fallback semantics beyond the new requires-fix marking and auto-feedback.
- Automatically detecting semantic errors hidden inside an otherwise successful tool response (still deferred per existing product decision).
- Redesigning the broader Run dialog, Agent Type dialog, or Optimized Plan tab beyond the separate Optimize action, the explicit generation controls, the requires-fix alert, and the auto-recorded feedback.

## Dependencies & Constraints

- Depends on the existing Software 3.0 framework: the optimized-plan lifecycle, the script registry, script-first execution with unconditional LLM fallback, and the built-in workflow-optimization capability.
- Depends on the workspace-level authoring (workflow generation) model setting already used for Skill/SOP workflow generation; this epic extends its use to implementation-plan and optimization-plan generation rather than introducing a second model setting.
- Requires at least one enabled model in the workspace's model catalogue so an authoring model can be chosen; without one, plan generation and optimization remain unavailable by design.
- Workspace administrators own the authoring model choice; missing configuration is surfaced as a visible reminder and as a clear point-of-use message, never as a silent fallback.
- Must preserve platform top-priority rules: agents and their scripts run only in Agent Runtime; only Control Center touches the database; agents never receive sensitive data such as identity tokens or database credentials.
- Execution of the dedicated optimization run remains subject to the same guardrails, sandboxing, and permission rules as any other execution.
- The requires-fix marking, auto-recorded feedback, and generation outcomes must be visible to operators in the Plan Preview and Optimized Plan tabs without a manual reload.
- Multi-tenancy: when enabled, plans, feedback, alerts, and the authoring model choice remain tenant-owned and tenant-scoped.
