
# Agent Plan Mode (Unified AI Agent Navigation)

## 1. Epic Overview

Agent Plan Mode provides a clear, actionable plan for each agent type, now accessible directly from the unified "AI Agent" menu. When configuring or reviewing agent types, users can open the Agent Type Details dialog, which includes a dedicated "Plan Preview" tab. This tab displays the LLM-generated implementation plan and a visual topology diagram, giving users confidence in agent setup, enabling better preview and validation before execution, and reducing errors in agent operation. The saved plan becomes part of the agent's execution context—during runtime, the agent follows the pre-approved plan to ensure compliant, predictable behavior. This dialog-based approach streamlines access to plan details and supports the new navigation structure.

The plan model is now **two-layered**: the plan described here is the **base implementation plan** — a plain, high-level step list kept deliberately simple and readable for review and governance. Separately, an **optimized implementation plan** (model-authored workflow composition with script segments, model bridge steps, and decision steps) is produced by a dedicated Optimize action or through an optimization conversation, and is governed on the Optimized Plan tab. See [Sandboxed Scripting & Model-Authored Composition](sandboxed-scripting.md). This document covers the base plan layer.

Plans are never authored as a side effect of configuration. A plan is generated only when an operator explicitly asks for it, and it is authored by the **workspace's approved authoring model** — not by the agent type's own runtime model, which exists for execution. The workspace setting is the single place this model is chosen, and when it is not configured the plan surfaces say so plainly and point to System Config rather than substituting another model.

## 2. Business Goals

- Increase successful agent deployments by 30% through improved plan transparency and validation
- Reduce agent misconfiguration support tickets by 40% within three months of launch
- Achieve 90% user satisfaction with the agent planning and preview experience (measured via in-app survey)
- Decrease average agent setup time by 25% for new users
- Give every agent type an explicitly generated, reviewable plan whenever an operator asks for one, without spending model time on saves
- Keep plan quality independent of the agent's execution model, by authoring plans with the workspace's approved authoring model

## 3. Users & Personas

- **AI Solution Architects**: Need to ensure agents are configured correctly and follow organizational SOPs
- **Business Analysts**: Want to understand and validate agent workflows before launch
- **Compliance Officers**: Require visibility into agent logic, SOPs, and tool usage for audit and approval
- **Developers/Integrators**: Need to preview agent plans to ensure correct integration with other systems

## 4. User Stories

- As an AI Solution Architect, I want to see a step-by-step plan for each agent, so that I can validate its workflow before saving or launching.
- As a Business Analyst, I want to preview the agent's SOPs, skills, and tools in a visual diagram, so that I can understand how the agent will operate.
- As a Compliance Officer, I want to review the agent's plan and associated SOPs/skills, so that I can approve agents for production use.
- As a Developer, I want to ensure the agent's plan aligns with integration requirements, so that downstream systems are not impacted by misconfiguration.
- As an Agent Designer, I want plan generation to include only SOPs and skills from the agent type's curated binding list, so that plan context remains focused and predictable.
- As an Agent Designer, I want the fallback to all role-assigned SOPs and skills used only when no bindings are defined, so that backward compatibility is transparent.
- As an agent operator, I want to generate or re-generate the plan only when I ask, so that saving an agent never spends model time or silently replaces a plan I reviewed.
- As an agent operator, I want plans authored by my workspace's approved authoring model, and to be told clearly when none is configured, so that quality and cost are a workspace decision rather than an accident of the agent's model.
- As an agent operator working with a conversational agent, I want a clear explanation instead of plan controls, so that I am not misled into expecting a plan for an agent that has none.
- As an agent operator, I want an optimized plan to be authorable through a conversation as well, with no change to how plans are verified, served, or retired.


## 5. Acceptance Criteria

- Saving, creating, or updating an Agent Type never generates or regenerates an implementation plan; no authoring work, model spend, or plan overwrite happens as a side effect of a save.
- The implementation plan is generated only on an explicit user request from the Plan Preview surface, using the agent's instruction, role, and curated binding list (SOP and skill bindings); before the first generation the surface shows that no plan exists yet and offers the generation action.
- Plan authoring uses the workspace's approved authoring model (the same workspace model used for Skill/SOP workflow generation and optimization), never the agent type's runtime model.
- Requesting a plan while no authoring model is configured produces a clear, user-facing explanation that the model is not configured, with a pointer to System Config; no plan is generated and no alternative model is used.
- A failed generation attempt shows its reason and never discards the last successful plan.
- If the agent's configuration has changed since the plan was last generated, the surface indicates the plan may be out of date and offers regeneration; it is not regenerated automatically.
- After an explicit generation completes, the plan view updates automatically to show the new plan without a manual page reload.
- Implementation-plan generation is not available for conversational agent types; the controls are absent and the surface explains why. The only way a plan is authored for them is inside an optimization conversation, which authors the plan it works from when none exists.
- The authored plan is persisted with the agent type and displayed in a human-readable format, outlining each action the agent will take.
- A topology diagram visually shows the Agent Role, bound SOPs, bound skills, and their tools, with clear relationships. The Communication Hub is rendered as a connected node in the diagram — shown as a hub bar between capabilities and tools, with connectors crossing it — so the full runtime picture (including the messaging/gateway path) is visible.
- Users can preview the full plan and diagram in the "Plan Preview" tab of the Agent Type Details dialog.
- The saved plan is loaded into the agent's execution context during runtime, guiding the agent to follow the pre-approved workflow.
- Plan preview and execution context support both traditional and passthrough session types for MCP servers; passthrough enables direct agent identity propagation without explicit session selection
- The plan and diagram are not re-generated when the agent's configuration, role, or binding list changes; instead the plan is shown as out of date until the operator regenerates it.
- Plan generation uses only the Agent Type's explicitly bound SOPs and skills from the ordered binding list.
- When no bindings are defined, plan generation falls back to all role-assigned SOPs and skills (current behaviour, backward compatible).
- All UI text uses the platform's localization framework.
- The feature is accessible and usable on both desktop and tablet devices.
- Error handling: if plan generation fails, users receive a clear, actionable error message and the last successful plan is retained.
- No direct database access occurs from the frontend; all data flows through the backend API.

## 6. Out of Scope

- Editing or customizing the generated plan steps directly in the UI (the plan is regenerated on explicit request, not manually edited)
- Manual override of SOP/Skill/Tool selection within the plan preview
- Real-time plan adjustment during agent execution (the saved plan guides execution but doesn't adapt dynamically)
- Support for legacy agent types not using the new configuration model
- Exporting plans to external formats (e.g., PDF, CSV)
- Plan versioning or history (only the current plan is stored and used)
- Dedicated admin surfaces or schedulers for plan authoring — plans are generated on explicit operator request only

## 7. Two-Layer Plan Model Note

The base plan remains the plain high-level step list this document describes. It is never modified by optimization. The optimized implementation plan is authored separately — by the dedicated Optimize action or by an optimization conversation on the agent — and lives on the Optimized Plan tab; it never alters the base plan's content. If the optimized plan is absent, stale, retired, or flagged as requiring a fix — or any script within it fails — execution falls back to following this base plan's model-driven path.

Authoring an optimized plan conversationally changes only the trigger and the interaction: verification, serving preference, retirement, and the requires-fix marking work exactly as they do for a plan produced by the one-shot action. See [Sandboxed Scripting & Model-Authored Composition](sandboxed-scripting.md).

## 8. Dependencies & Constraints

- Relies on accurate mapping between Agent Roles, SOPs, Skills, and Tools in the master data
- Requires up-to-date SOP and Skill definitions for meaningful plan generation
- Requires the workspace's approved authoring model to be configured; the agent type's runtime model is not used for authoring, and a missing model blocks generation with a clear message rather than falling back
- Plan generation happens on operator request, so authoring model response time affects that interaction rather than agent saves
- Must integrate with existing localization framework
- Subject to current frontend/backend API contract and strong typing conventions
- Agent execution runtime must support loading and following the saved plan
- Plan must be stored in a format that's both human-readable (for preview) and machine-parseable (for execution guidance)
