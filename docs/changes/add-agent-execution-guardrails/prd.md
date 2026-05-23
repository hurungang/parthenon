# PRD: Add Agent Execution Guardrails

## Epic Overview
Parthenon needs execution guardrails so Agent Sessions remain predictable, safe, and cost-aware at enterprise scale. This epic introduces policy limits by Agent Type and delegation path, including cycle prevention, bounded execution, runtime limits, and token-budget policies that distinguish conversational sessions from non-conversational automated runs. The outcome is lower runaway-execution risk, clearer operational control, and stronger governance confidence.

## Business Goals
- Reduce failed or runaway Agent Sessions caused by recursive delegation loops to near zero in production operations.
- Improve cost predictability by enforcing configurable execution ceilings per Agent Type, including iteration/delegation limits and token budgets when available.
- Preserve bounded delegation behavior by keeping per-Agent-Type delegation depth and delegated-step controls in the same guardrail profile as cycle, iteration, and timeout limits.
- Shorten incident triage time by providing clear guardrail-stop outcomes in Agent Session tracking and operational observability.
- Ensure every Agent Type has an independently configurable guardrail profile in Control Center UI so governance policies can be applied consistently.
- Strengthen governance compliance with documented enforcement of execution boundaries aligned to established service boundaries.
- Increase operator confidence to onboard new SOPs and Agent Types without materially increasing execution risk.

## Users & Personas
- Platform Administrator: needs configurable guardrails per Agent Type to control risk and spend.
- AI Operations Lead: needs predictable Agent Session behavior and clear failure reasons for fast remediation.
- Security and Compliance Owner: needs evidence that delegation paths are bounded and cannot create uncontrolled execution chains.
- Business Process Owner: needs SOP automation that is reliable and does not stall workflows through infinite loops or excessive runtime.

## User Stories
- As a Platform Administrator, I want delegation-cycle detection across nested SOP delegation chains so that infinite loops are blocked before causing runaway execution.
- As an AI Operations Lead, I want configurable execution limits that include delegated activity so that Agent Sessions end within defined guardrails.
- As a Platform Administrator, I want to view and compare a separate guardrail profile for each Agent Type in the Control Center UI so that I can apply governance consistently across agent portfolios.
- As a Platform Administrator, I want to edit and save each Agent Type's guardrail profile in the Control Center UI so that approved policy changes are applied quickly.
- As a Platform Administrator, I want configurable timeout limits per Agent Type so that long-running executions are stopped predictably.
- As a conversational-user experience stakeholder, I want current-session token consumption to remain continuously visible during active conversation so that users can review usage while continuing the same session.
- As a Finance and Governance stakeholder, I want token-budget guardrails to continue applying to non-conversational or automated runs so that unattended executions stay within approved cost controls.
- As an AI Operations Lead, I want a defined fallback when token-budget enforcement is unavailable so that execution behavior remains deterministic and auditable.

## Acceptance Criteria
- System detects cyclic references in agent-to-agent delegation chains, including indirect recursion across downstream SOP delegation, and blocks execution with a clear user-visible reason.
- Cycle prevention is applied consistently throughout Agent Session execution so risky delegation paths are stopped with a clear reason.
- Control Center UI presents a distinct guardrail configuration profile for each Agent Type so administrators can view configured iteration, timeout, and token-budget limits by type.
- Control Center UI allows authorized administrators to edit and save each Agent Type's guardrail profile, and saved values are reflected in subsequent policy views.
- Each Agent Type supports configurable maximum iteration limits that count direct and delegated execution activity toward the same execution ceiling.
- Each Agent Type supports configurable delegation depth and delegated-step limits, and limit breaches end execution with a clear guardrail reason.
- Each Agent Type supports configurable execution timeout limits, and sessions exceeding the limit end with a clear timeout status and reason.
- Conversational sessions display continuously updated token consumption for the current session in user-visible session views so users can keep reviewing usage while continuing the conversation.
- Conversational sessions are not hard-stopped solely because a token budget threshold is reached, while recursion, iteration, and timeout guardrails remain active.
- Token budget per execution remains configurable and enforceable for non-conversational or automated runs where supported by the model/provider integration.
- When token-budget enforcement is not supported, the system applies a defined fallback that is transparent to operators while other guardrails remain active.
- Guardrail outcomes are visible in Agent Session and operational monitoring contexts so operators can distinguish policy stops from functional failures.
- Guardrail behavior preserves architecture segregation expectations: execution remains in Agent Runtime, policy/governance settings are managed through Control Center, and no change bypasses established service boundaries.

## Out of Scope
- Redesign of SOP authoring experience beyond fields required to configure guardrail policies.
- Provider-specific optimization tuning for model quality, latency, or prompt engineering.
- Changes to role/permission model semantics unrelated to execution guardrail policies.
- Billing-system redesign or full cost allocation reporting initiatives.
- New end-user workflow automation features unrelated to guardrail enforcement.

## Dependencies & Constraints
- Depends on model/provider capability visibility for token accounting and enforcement support.
- Must align with top-priority segregation constraints, especially Agent Runtime execution boundaries and Control Center governance boundaries.
- Depends on Communication Hub and Agent Session observability pathways to expose guardrail stop reasons.
- Must remain compatible with existing SOP and Agent Type governance workflows in Control Center.
- Constrained by enterprise expectations for predictable execution, auditability, and low operational disruption.
