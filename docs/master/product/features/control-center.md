# Control Center

## Overview
Control Center is the governance center for policy-driven operation of Parthenon. It provides administrators with a consistent place to manage agent policy controls, including a **vendor → model → guardrail hierarchy** for model-usage guardrails, per-Agent-Type guardrail profiles that keep execution behavior predictable, auditable, and aligned with enterprise risk and cost expectations, and a **runtime control dashboard** that surfaces live execution state, delegation topology, and operator-controlled termination actions.

## Who Uses It
- Platform Administrators: Define and maintain governance policies for agent execution behavior
- AI Operations Leads: Review policy outcomes, monitor live runtime topology, and tune limits for reliability and predictable operations
- Security and Compliance Owners: Verify that policy boundaries are enforced and auditable, and that high-risk recursion and uncontrolled delegation are prevented
- FinOps or Platform Governance Leads: Manage model consumption across vendors and disable expensive or risky models without touching others

## What It Does
- Presents a distinct guardrail profile for every Agent Type
- Allows authorized administrators to edit and save guardrail profiles by Agent Type
- Organises model-usage guardrails under a **vendor → model → guardrail hierarchy**, replacing the previous flat per-model configuration
- Allows per-vendor model selection: under a vendor, operators can see and select which of the vendor's models are allowed to be used
- Allows per-model temporary disable: while a model is disabled, any agent execution that would use that model is blocked, and the block is surfaced in execution logs
- Allows per-vendor temporary disable: while a vendor is disabled, every model under that vendor is treated as disabled; the per-model disable affordances remain visible to show the cascade source
- Allows per-guardrail enforcement posture (terminate or observe-only) and individual enable, disable, and remove controls on each guardrail
- Presents vendors as a list, each vendor expanding to its models, and each model expanding to its guardrails — a navigable three-level hierarchy
- Governs execution boundaries, including iteration ceilings, delegation boundaries, and timeout limits
- Governs token-budget policy behavior for supported non-conversational and automated runs
- Presents token-budget values in k-token units, with 1000k as the default presentation value
- Keeps the guardrail editor compact by default for efficient policy administration
- Reflects saved guardrail values in policy views used for governance and oversight
- Provides system-level configuration for selecting the model used by AI-assisted Skill and SOP workflow authoring
- Uses centrally managed model options so workflow-generation governance aligns with enterprise model policy
- Provides a **runtime control dashboard** showing all currently running agents, their delegated children, configured model-usage limits, and current usage posture (within limit, approaching limit, breached) alongside execution guardrail status
- Provides a **topology diagram view** of active agent-to-agent delegation relationships
- Provides **node-level termination** from the dashboard for authorized users, with **cascade termination** of delegated children when a parent is terminated
- Provides **disabled-vendor** and **disabled-model** block surfaces in the operator UI, with the cascade source clearly visible

## Key Concepts
- **Per-Agent-Type Guardrail Profile**: A policy profile tied to one Agent Type for consistent execution governance
- **Vendor → Model → Guardrail Hierarchy**: A three-level model-usage governance structure where vendors group their models, and each model carries one to four guardrail records, one per period (hour, day, week, month)
- **Per-Period Guardrail**: A single guardrail scoped to one of the supported time periods (hour, day, week, or month). A model may have one to four such guardrails; operators configure only the periods they actually need
- **Enforcement Posture**: Each guardrail is either `terminate` (stops execution when the limit is breached) or `observe-only` (records the breach without stopping). New guardrails default to `terminate`
- **Per-Vendor Model Selection**: The set of a vendor's models that are allowed to be used by agents. Models not in the selection are treated as disabled
- **Per-Model Disable**: A temporary disable flag on a model that blocks any agent execution that would use that model
- **Per-Vendor Disable**: A temporary disable flag on a vendor that cascades to every model under it. The per-model disable affordances remain visible to show the cascade source
- **Usage Posture**: The current state of a model's usage against its configured guardrail limits — `within limit`, `approaching limit`, or `breached`
- **Runtime Control Dashboard**: A read-only operator view of all currently running agents, their delegation relationships, and operator-controlled termination actions
- **Topology Diagram**: A visual representation of active parent-child agent execution relationships with selectable nodes
- **Cascade Termination**: Terminating a parent execution that also stops all active delegated child executions it triggered
- **Execution Boundaries**: Policy limits that bound run behavior to approved operational ranges
- **Delegation Boundaries**: Policy limits that bound delegation depth and delegated-step volume
- **Conversational Policy Behavior**: Continuous token usage visibility while preserving conversation continuity unless other guardrails require a stop
- **Policy Outcome Transparency**: Clear representation of guardrail outcomes for triage and governance reporting
- **Workflow Generation Model Policy**: Central selection of the approved model used for AI-assisted workflow drafting and preview

## Acceptance Criteria
- A distinct guardrail profile is visible for each Agent Type
- Authorized administrators can edit and save each Agent Type guardrail profile
- Saved guardrail values are reflected in subsequent policy views
- Token-budget values are displayed in k-token units with 1000k as the default presentation value
- Guardrail editing remains compact by default and supports efficient policy review across many Agent Types
- After closing create/edit/delete or guardrail dialogs, parent tables refresh automatically to show updated data without manual page reload
- Governance views clearly distinguish guardrail policy outcomes from functional execution failures
- Authorized administrators can select the workflow-generation model from system configuration
- Workflow-generation model choices align with the centrally managed model configuration catalog
- If no workflow-generation model is configured, AI-assisted generation and preview actions show a clear user-facing error instead of silently using a fallback
- Model-usage guardrails are managed under a vendor → model → guardrail hierarchy: vendors are listed, each vendor expands to show its models, and each model expands to show its guardrails
- For each vendor, operators can see and select which of that vendor's models are allowed to be used
- For each model, operators can configure between one and four guardrails, one per period (hour, day, week, month), and may save the model with only the periods they actually want — no forced four-period entry
- Each guardrail has its own enforcement posture (terminate or observe-only) and can be individually enabled, disabled, or removed by an authorized operator
- An authorized operator can temporarily disable an individual model; while disabled, any agent execution that would use that model is blocked and the block is visible in execution logs
- An authorized operator can temporarily disable an entire vendor; while disabled, every model under that vendor is treated as disabled and blocked from agent execution
- When a vendor is disabled, the per-model disable affordances remain visible so operators can see the cascade source, not a hidden state
- When a model is under a disabled vendor, attempts to use it surface a clear operator-visible reason that points to the disabled vendor as the root cause
- The runtime or dashboard experience shows the configured model-level usage limits together with current model usage posture in a way operators can interpret without leaving the monitoring workflow, including whether each period is within limit, approaching limit, or breached
- Operators can view a consolidated list of all currently running agents and associated delegated agents
- A runtime topology dashboard displays active agent and delegation relationships in a user-comprehensible diagram
- The runtime or dashboard experience shows both execution guardrails and model-usage guardrails together so operators can assess runtime risk and consumption risk in one place
- Authorized users can select any running or delegated node and request termination from the dashboard
- Terminating a parent execution also terminates all active delegated child executions it triggered
- If a user lacks required permission, termination controls are unavailable or rejected with a clear user-visible message
- Guardrail, termination, and disable-state outcomes (including model-disabled and vendor-disabled blocks) are reflected in execution logs so operators can distinguish policy events from functional failures
- Disabled vendors and disabled models block agent execution before any LLM call, and the block is surfaced in execution logs with a clear operator-visible reason

## Out of Scope
- Technical implementation details, architecture internals, or service-level configuration mechanics
- Provider-specific model tuning and optimization strategy
- Changes to non-governance UI areas unrelated to Control Center policy management

## Dependencies & Constraints
- Requires role-based authorization so only approved administrators can manage guardrail profiles
- Depends on policy outcome visibility from execution and session monitoring views
- Must preserve service-segregation expectations for execution responsibilities and governance responsibilities
- Must remain compatible with existing enterprise audit and compliance standards
- Requires trustworthy model-usage measurement and period rollup data so hourly, daily, weekly, and monthly posture can be shown accurately
- Requires a vendor and model catalogue that the new hierarchy can be built on top of, so that vendor enable/disable and model selection have a stable source of truth
- Requires reliable runtime state and delegation relationship signals to render accurate running-agent topology
- Terminate operations must be routed through the Communication Hub to Agent Runtime to preserve service segregation and certificate-based authentication boundaries
