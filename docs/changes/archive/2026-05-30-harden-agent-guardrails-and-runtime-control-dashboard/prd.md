# PRD: Harden Agent Guardrails and Runtime Control Dashboard

## Epic Overview
Parthenon must strengthen agent guardrail reliability and operator control so enterprise teams can trust autonomous execution at scale. This epic hardens guardrail enforcement across execution and delegation flows, shifts the default enforcement mode from observe to terminate, introduces model-level usage limits expressed as a vendor → model → guardrail hierarchy with per-period guardrails and per-vendor/per-model disable toggles, expands runtime visibility of running agents and delegation chains, and adds governed termination controls that can stop a full execution tree when risk thresholds are reached. The business outcome is safer automation, faster incident response, better cost and capacity governance, and reduced operational and compliance exposure from runaway, excessive, or recursive agent behavior.

## Business Goals
- Reduce uncontrolled, recursive, or excessive agent execution by enforcing guardrails consistently across direct and delegated runs and by making terminate the default enforcement mode for new guardrails.
- Give operators bounded control of model consumption through a vendor → model → guardrail hierarchy where each guardrail is scoped to a single period (hour, day, week, or month) and operators configure only the periods they want.
- Let operators temporarily disable individual models or entire vendors, with disabling a vendor cascading to every model under it, so risk can be cut off at the right level during incidents.
- Improve mean time to detect and respond to runtime risk through live dashboard visibility of execution topology, guardrail status, current usage posture, and the three-level vendor/model/guardrail hierarchy.
- Enable authorized operators to stop problematic execution trees quickly, including all active child delegations.
- Prevent dead-loop scenarios before runtime by validating delegation risk during agent create, update, and run actions.

## Users & Personas
- Platform Administrator: needs reliable guardrail enforcement, policy-safe execution controls, and a clean way to manage model usage per vendor.
- AI Operations Lead: needs live visibility of running agents and delegations to diagnose and stop risk quickly, and to see at a glance which models and vendors are enabled.
- Security and Compliance Owner: needs evidence that high-risk recursion and uncontrolled delegation are prevented and auditable, and that disabled vendors/models reliably block execution.
- FinOps or Platform Governance Lead: needs visibility and controls to keep model usage within approved limits over time, including the ability to disable expensive or risky models without touching others.
- Business Process Owner: needs automation that remains available, bounded, and predictable, even when one vendor or model is temporarily disabled.

## User Stories
- As a Platform Administrator, I want guardrail enforcement to apply consistently to both direct execution and delegated execution so that risky behavior is reliably contained.
- As a Platform Administrator, I want new guardrails to default to terminate mode so that unsafe executions are stopped without relying on optional operator tuning.
- As a Platform Administrator, I want model-usage guardrails organised under a vendor → model → guardrail hierarchy so that I can see at a glance which limits apply to which model from which provider.
- As a Platform Administrator, I want to select which of a vendor's models are allowed to be used so that retired, expensive, or risky models are simply not available to agents.
- As a Platform Administrator, I want to add only the guardrail periods I actually need (one to four per model) so that I am not forced to configure unused hour, day, week, or month limits just to save the others.
- As a Platform Administrator, I want each guardrail to have its own enforcement posture (terminate or observe-only) and to be individually enabled, disabled, or removed so that I can tune model limits independently per period.
- As a Platform Administrator, I want to temporarily disable an individual model so that any agent execution that would use that model is blocked while I investigate or rotate providers.
- As a Platform Administrator, I want to temporarily disable an entire vendor so that all models under that vendor are treated as disabled at once, and so that the per-model disable affordances remain visible to show the cascade source.
- As an AI Operations Lead, I want the UI to show vendors as a list, each vendor expanding to show its models, and each model expanding to show its guardrails, so that I can navigate the hierarchy without losing context.
- As an AI Operations Lead, I want to see all currently running agents and their delegated relationships in one dashboard so that I can assess operational health quickly.
- As an AI Operations Lead, I want a topology view of running parent and child agents so that I can identify problematic execution branches.
- As an AI Operations Lead, I want the runtime dashboard to show model guardrail settings and current usage posture so that I can recognize approaching or breached limits before they cause wider disruption.
- As an authorized operator, I want to terminate a selected running agent or delegated node so that I can stop harmful or unnecessary execution immediately.
- As a Security and Compliance Owner, I want observe-only guardrail limit events shown in execution logs so that policy risks are visible even when runs are not automatically blocked.
- As a Security and Compliance Owner, I want attempts to use a disabled model or a model under a disabled vendor to be clearly logged and blocked so that policy violations are auditable.
- As a Platform Administrator, I want recursive-delegation risk validation during agent create, update, and run so that dead-loop configurations are prevented before execution proceeds.

## Acceptance Criteria
- Guardrail enforcement is applied consistently for agent execution and delegation paths, with no policy bypass between parent and child runs.
- The default enforcement mode for newly configured guardrails is terminate unless an authorized operator explicitly selects a different posture.
- When guardrail limits are reached in observe-only mode, a clear alert is visible in user-facing execution logs for the affected run.
- Model-usage guardrails are managed under a vendor → model → guardrail hierarchy: vendors are listed, each vendor expands to show its models, and each model expands to show its guardrails.
- For each vendor, operators can see and select which of that vendor's models are allowed to be used.
- For each model, operators can configure between one and four guardrails, one per period (hour, day, week, month), and may save the model with only the periods they actually want — no forced four-period entry.
- Each guardrail has its own enforcement posture (terminate or observe-only) and can be individually enabled, disabled, or removed by an authorized operator.
- An authorized operator can temporarily disable an individual model; while disabled, any agent execution that would use that model is blocked and the block is visible in execution logs.
- An authorized operator can temporarily disable an entire vendor; while disabled, every model under that vendor is treated as disabled and blocked from agent execution.
- When a vendor is disabled, the per-model disable affordances remain visible so operators can see the cascade source, not a hidden state.
- When a model is under a disabled vendor, attempts to use it surface a clear operator-visible reason that points to the disabled vendor as the root cause.
- The runtime or dashboard experience shows the configured model-level usage limits together with current model usage posture in a way operators can interpret without leaving the monitoring workflow, including whether each period is within limit, approaching limit, or breached.
- Operators can view a consolidated list of all currently running agents and associated delegated agents.
- A runtime topology dashboard displays active agent and delegation relationships in a user-comprehensible diagram.
- The runtime or dashboard experience shows both execution guardrails and model-usage guardrails together so operators can assess runtime risk and consumption risk in one place.
- Authorized users can select any running or delegated node and request termination from the dashboard.
- Terminating a parent execution also terminates all active delegated child executions it triggered.
- If a user lacks required permission, termination controls are unavailable or rejected with a clear user-visible message.
- During agent create and update, the system validates SOP/delegation configuration for recursive delegation risk and blocks invalid submissions.
- During agent run initiation, the system validates recursion/dead-loop risk and prevents execution when risk conditions are detected.
- Guardrail, termination, and disable-state outcomes (including model-disabled and vendor-disabled blocks) are reflected in execution logs so operators can distinguish policy events from functional failures.

## Out of Scope
- Redesign of role and permission model semantics beyond access checks required for termination and guardrail-management actions.
- Model-quality tuning, prompt-quality optimization, or provider-specific response improvements.
- Provider contract renegotiation, chargeback policy design, or enterprise budgeting processes outside product-level model usage visibility and limits.
- Broader workflow authoring redesign outside recursion/dead-loop risk prevention checks.
- New billing or cost-allocation modules beyond runtime guardrail alerting and control.

## Dependencies & Constraints
- Must comply with service segregation rules: execution remains in Agent Runtime; governance and control remain in Control Center boundaries.
- Must preserve secure handling of sensitive credentials and identity material; no expansion of agent access to sensitive data.
- Depends on trustworthy model-usage measurement and period rollup data so hourly, daily, weekly, and monthly posture can be shown accurately.
- Depends on a vendor and model catalogue that the new hierarchy can be built on top of, so that vendor enable/disable and model selection have a stable source of truth.
- Depends on reliable runtime state and delegation relationship signals to render accurate running-agent topology.
- Depends on permission enforcement so only authorized users can configure guardrails, disable vendors or models, and terminate executions.
- Constrained by enterprise auditability requirements: guardrail alerts, model-usage posture changes, vendor/model disable changes, and termination actions must be visible in operational logs.
