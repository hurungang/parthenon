# Spec Delta: Separate Optimization from Execution

## Affected Spec Areas

- `docs/master/product/features/sandboxed-scripting.md` — the "Optimize-and-Verify" section currently describes optimization as an opt-in step of the Run Agent flow ("Run with optimization" / "Skip optimization"); it changes to a separate Optimize action with a successful-execution precondition, an authoring-model precondition, a realistic (non-identical-result) optimization goal, and a conversational-agent exclusion. The optimized plan is authored by the workspace authoring model, never by the agent's runtime model
- `docs/master/product/features/software-3-0-agent-framework.md` — the workflow-optimization / self-improvement description gains the requires-fix marking and automatic feedback recording on fallback, the explicit-generation rule, and the authoring-model policy (plan authoring uses the workspace model, not the agent model); conversational agents are never plan-generated or compiled
- `docs/master/product/features/agent-execution.md` — "Optimized Plan Execution Preference & Fallback" gains the plan-consumption + requires-fix + auto-feedback behavior when a later run falls back because of the optimized plan
- `docs/master/product/features/agent-plan-mode.md` — the "plan is generated automatically when the agent is saved" behavior and the "plan regenerates on config change" criterion become explicit, user-initiated generation; the plan is authored with the workspace authoring model and the tab shows no-plan, out-of-date, and model-not-configured states; generation is unavailable for conversational agents
- `docs/master/product/features/agent-types.md` — agent type model selection is for execution only; plan authoring and optimization are governed by the workspace authoring model, and conversational agent types have no plan generation
- `docs/master/product/features/agent-management.md` — the Agent Type detail dialog / Plan Preview / Optimized Plan tab and the launch surface gain the separate Optimize action, explicit generation controls, the requires-fix alert, the model-not-configured message, and the conversational-agent disabled state
- `docs/master/product/features/control-center.md` — "Workflow Generation Model Policy" broadens from Skill/SOP authoring to all plan authoring (Skill/SOP workflow generation, implementation plans, optimization plans), gains selection guidance (recommend a larger/higher-end model), an explicit reminder when unset, and workspace scoping
- `docs/master/data-model/modules/agents/entities.md` — `AgentPlan` generation is no longer triggered by agent save; `generation_status` / `generation_error` reflect explicit requests and retain the last successful plan. `OptimizedImplementationPlan` gains a requires-fix marking (alongside the existing status / error / feedback fields) and the auto-recorded feedback semantics
- `docs/master/data-model/modules/tenancy/entities.md` — `TenantSetting` key `workflow_generation_model_id` is documented as the single workspace authoring model serving Skill/SOP workflow generation, implementation-plan generation, and optimization-plan generation; with multi-tenancy disabled it resolves to the default workspace's setting, and a disabled/removed selected model puts plan generation and optimization into the "not configured / re-select" state
- `docs/master/data-model/modules/workflow-compilation/entities.md` — `FallbackEvent` / `RepairAttempt`: document that a fallback attributable to the optimized plan marks the plan requires-fix, in addition to existing script-health degradation
- `docs/master/ux/README.md` — System Config flow, Plan Preview, Optimized Plan tab, and Run dialog flows reflect the authoring-model guidance/reminder, explicit generation, the separate Optimize action, the precondition, the requires-fix alert, and the conversational-agent exclusion
- `docs/master/ux/agent-session-log-ui.md` — execution-log / launch surface reflect the separated Optimize action, explicit plan generation, and the requires-fix alert

## New Capabilities

- **Dedicated Optimize action**
  - Optimization becomes its own explicit action on the agent surface, separate from Run; running an agent never performs optimization.
  - The action requires at least one successful execution of the agent as a precondition; before that it is unavailable with a clear explanation.
  - The action also requires a configured workspace authoring model; when none is set, the user is told the model is missing, pointed to System Config, and no optimization run starts.
- **Workspace authoring model for plan generation**
  - Implementation-plan and optimization-plan generation both use the single approved authoring model configured per workspace (the same model used for Skill/SOP workflow generation); the agent type's own runtime model is never used for authoring plans.
  - The workspace setting is the only place this model is chosen, applies to all subsequent generations in that workspace, and never affects other workspaces.
- **Explicit plan generation**
  - Creating, saving, or updating an agent never generates or regenerates a plan and incurs no authoring model spend.
  - The implementation plan is produced only on explicit user request from the Plan Preview surface; the same applies to the optimized plan, which is produced only when Optimize is triggered.
  - An explicit request without a configured authoring model produces a clear user-facing explanation and never falls back to another model.
  - A failed generation shows its reason and preserves the last successful plan; a plan older than the agent's current configuration is flagged as out of date with an offer to regenerate, not regenerated automatically.
- **System Config guidance and reminder**
  - The setting explains what the model is used for (Skill/SOP workflow generation, implementation-plan generation, optimization-plan generation), recommends a larger / higher-end model, and states that the choice applies to the current workspace.
  - When nothing is configured, a visible reminder prompts the administrator to configure it, and point-of-use surfaces repeat the explanation.
- **Conversational-agent exclusion**
  - Implementation-plan generation and optimization-plan generation are unavailable for conversational agents; controls are hidden or disabled with an explanation, and no generation happens through any other surface.
- **Realistic, bounded optimization mission**
  - The optimization execution uses the agent's optimization instructions, the current implementation plan, other agent information, and access to execution logs — as a dedicated run, not a modified normal run.
  - The optimizer prefers the latest execution and limits how much execution history it reviews; it aims for correct script syntax and proper tool invocation rather than reproducing the reference result, so a legitimately empty or differing tool result does not trigger forced re-attempts.
  - The optimizer stops when it lacks high confidence, guaranteeing a bounded end state with no dead loop.
- **Requires-fix marking + automatic feedback on fallback**
  - When a later execution fails and falls back to the model path because of the optimized plan, the platform marks the plan as requiring a fix and records feedback automatically.
- **Human-in-the-loop alert + re-optimization**
  - The next time the user opens the agent, an alert surfaces the problematic plan; the user can re-trigger optimization with the prior plan plus the recorded feedback as context. Manual feedback remains available.

## Modified Capabilities

- **Workflow Generation Model policy (system configuration)**
  - Before: a single setting selected the model used for AI-assisted Skill and SOP workflow drafting and preview, with a fallback error when unset.
  - After: the same setting is the workspace authoring model for all plan authoring — Skill/SOP workflow generation, implementation-plan generation, and optimization-plan generation — presented with usage guidance, a recommendation to choose a larger model, workspace scoping, and a visible reminder when unset.
- **Implementation plan generation trigger**
  - Before: saving an Agent Type automatically invoked a model to generate the plan, and configuration changes triggered re-generation on save.
  - After: generation happens only when the user explicitly requests it; saves never generate or overwrite a plan, out-of-date plans are flagged for regeneration, and the authoring model is the workspace model rather than the agent's model.
- **Optimize-and-Verify (command-driven side execution)**
  - Before: optimization was offered as an opt-in step of the Run Agent flow ("Run with optimization" / "Skip optimization"); opting in converted the user's real execution into an optimize-and-verify mission, replacing the agent's prompt.
  - After: optimization is a separate, preconditioned action (successful execution + configured authoring model); a normal run keeps the agent's own instructions, optimization runs as its own dedicated execution with a realistic, bounded goal, and conversational agents are excluded.
- **Optimized Plan Execution Preference & Fallback**
  - Before: execution preferred a fresh optimized plan and fell back unconditionally to the base-plan path; a fallback recorded its reason but did not flag the plan.
  - After: when a fallback is attributable to the optimized plan, the plan is marked requires-fix and feedback is recorded automatically, surfacing a human-in-the-loop alert for re-optimization.
- **Optimized Plan tab / launch surface / Plan Preview (UX)**
  - Before: the Optimized Plan tab showed status/error, feedback, retire, and "nothing to retire"; the launch dialog offered "Run with optimization"; the plan preview simply displayed an auto-generated plan.
  - After: the surfaces add a separate Optimize action and an explicit Generate/Regenerate action, show no-plan, out-of-date, and model-not-configured states, display the requires-fix alert, refresh automatically after a generation or re-optimization, and explain that plan generation is unavailable for conversational agents.

## Removed Capabilities

- The "Run with optimization" mode of the Run dialog — running and optimizing are no longer a single act. The underlying optimize-and-verify execution is retained, but as its own explicit action rather than a run mode.
- Automatic implementation-plan generation and automatic re-generation triggered by agent create/save/update or by configuration changes.
- Use of the agent type's own runtime model — or any default/fallback model — for plan authoring and optimization.
- Implementation-plan and optimization-plan generation for conversational agents.

## Spec Update Instructions

- Update **Sandboxed Scripting** spec: replace the "opt-in step of the Run Agent flow" description of optimization with the separate Optimize action, the successful-execution plus authoring-model preconditions, the realistic (non-identical-result) optimization goal, and the conversational-agent exclusion; state that the optimized plan is authored by the workspace authoring model. Keep the script-first execution preference and fallback sections but note the new requires-fix marking.
- Update **Software 3.0 Agent Framework** spec: document the requires-fix marking and automatic feedback recording on fallback as part of self-improvement, clarify that self-improvement remains human-gated (no unattended re-optimization loops), state the authoring-model policy (workspace model, never the agent's model), and note that conversational agents are never plan-generated or compiled.
- Update **Agent Execution** spec: in "Optimized Plan Execution Preference & Fallback," add the plan-consumption + requires-fix + auto-feedback behavior.
- Update **Agent Plan Mode** spec: replace "automatically invokes an LLM when an Agent Type is saved" and "plan and diagram update automatically on config change" with explicit, user-initiated generation using the workspace authoring model; add the no-plan, out-of-date, and model-not-configured states and the conversational-agent exclusion; remove the "100% of new Agent Types have an auto-generated plan" goal.
- Update **Agent Types** spec: clarify that the agent type's model drives execution only, while plan authoring and optimization use the workspace authoring model; note that conversational agent types have no plan generation.
- Update **Agent Management** spec: document the separate Optimize action, explicit Generate/Regenerate controls, the requires-fix alert, the model-not-configured message, and the conversational-agent disabled state on the agent surface.
- Update **Control Center** spec: broaden "Workflow Generation Model Policy" to cover all plan authoring (Skill/SOP workflow generation, implementation plans, optimization plans), add the usage explanation, the recommendation to choose a larger model, workspace scoping, and the visible reminder when unset.
- Update **data-model agents entities** spec: document that `AgentPlan` generation is explicit and retains the last successful plan, and add the requires-fix marking plus auto-recorded feedback semantics to `OptimizedImplementationPlan`.
- Update **data-model tenancy entities** spec: document that `workflow_generation_model_id` is the single workspace authoring model for Skill/SOP workflow generation, implementation-plan generation, and optimization-plan generation; with multi-tenancy disabled it resolves to the default workspace, and a disabled/removed selected model surfaces the "not configured / re-select" state.
- Update **data-model workflow-compilation entities** spec: note that a fallback attributable to the optimized plan marks the plan requires-fix in addition to the existing script health degradation and repair evidence.
- Update **UX docs** (`README` and `agent-session-log-ui`): reflect the separated Optimize action, explicit plan generation, the preconditions, the System Config guidance and reminder, the requires-fix alert, and the conversational-agent exclusion.
- Explicitly do NOT modify the script registry lifecycle, sandbox baseline, security model, identity topology, or tenant isolation specs — those are unchanged; this epic changes how optimization and plan authoring are triggered, which model authors plans, and how a failing plan is flagged and surfaced.
