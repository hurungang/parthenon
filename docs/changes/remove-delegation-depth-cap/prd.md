# Epic PRD: Remove the Hard-Coded Delegation Depth Cap

## Epic Overview

Parthenon lets operators govern agent-to-agent delegation through a per-agent-type guardrail called **Max Delegation Depth**, which is meant to be the single, deliberate limit on how deep a delegation chain may go. In practice the platform also applies a limit of its own that operators can neither see nor configure: a delegated agent cannot pass work on, so a chain never extends past the originating agent plus one delegated level — conversational agents stop there whatever their agent type allows, and task-oriented (non-conversational) agents are held to a single delegation level even when their configuration says otherwise — and the delegation depth reported in the execution log reflects that fixed platform value rather than the configured maximum. Operators who deliberately configure deeper delegation therefore see workflows stopped for reasons they cannot find or explain, and the limit displayed in the log contradicts the limit they set. This epic makes the configured guardrail the only depth limit, for every agent type, while keeping every other guardrail intact and keeping execution-log visibility exactly as scoped today: an agent's log shows its own execution and its direct delegation events, and deeper sub-agent activity is reached by drilling into the delegated agent's own log rather than being folded into the parent's.

## Business Goals

- Eliminate all code-imposed delegation depth limits so that 100% of delegation depth outcomes are attributable to an operator-configured guardrail.
- Enable delegated task (non-conversational) agents to themselves delegate whenever their configured Max Delegation Depth allows it, so multi-level automated workflows behave as designed.
- Ensure the delegation status shown to operators in the execution log always reflects the agent type's configured maximum, so configuration and observed behaviour cannot disagree.
- Preserve guardrail integrity: no reduction in blocked over-deep delegation outcomes, and every block remains clearly reported and auditable.
- Preserve execution-log scoping exactly as today: no increase in log volume or cross-agent leakage, with zero grandchild entries appearing inside a parent agent's log.

## Users & Personas

- **Platform Administrators / AI Operations Leads** — Set and tune guardrails per agent type. They need a configured limit to be honoured precisely, with no hidden override they cannot see or audit.
- **SOP Authors / Workflow Designers** — Compose multi-step, multi-agent procedures. They need delegated task agents to be able to hand work on when the design and configuration call for it.
- **Runtime Operators / Support Staff** — Watch live runs and interpret execution logs. They need the delegation depth displayed to match configuration, and they need logs to stay readable and single-agent scoped.
- **Compliance & Audit Stakeholders** — Need proof that every delegation depth decision came from an explicit, recorded policy, and that nothing was silently truncated or silently expanded.
- **Tenant Owners** — Rely on bounded, predictable execution costs. They need deeper delegation to be a deliberate, configured choice rather than an accidental one.

## User Stories

- As a platform administrator, I want the Max Delegation Depth I configure to be the only depth limit that applies, so that delegation behaviour matches the policy I set.
- As a platform administrator, I want to set any permitted Max Delegation Depth on any agent type and have it honoured exactly, so that I can model the workflows my organisation actually needs.
- As an SOP author, I want task agents to be able to delegate onward when their configured guardrail allows it, so that multi-level automated workflows complete instead of stopping at an unexplained wall.
- As an SOP author, I want over-deep delegation to still be blocked when my configured limit is reached, so that bounded execution and cost control are never lost.
- As a compliance stakeholder, I want every blocked delegation to be reported with a clear, auditable outcome, so that I can prove the block came from policy and not from a hidden platform rule.
- As a runtime operator, I want an agent's execution log to show that agent's own work plus the lifecycle of its direct delegations, so that a single log stays comprehensible.
- As a runtime operator, I want to drill into a delegated agent's own execution log and see that agent's sub-delegation events there, so that I can follow a chain one hop at a time without wading through merged output.
- As a runtime operator, I want the delegation depth indicator in the execution log to show the agent type's configured maximum, so that I never see a limit that contradicts the configuration screen.
- As a platform administrator, I want agent types that never configured a depth limit to keep today's default behaviour, so that this change has no unintended effect on existing agents.

## Acceptance Criteria

**Configured depth is the only limit**
- An operator can set any permitted Max Delegation Depth on any agent type (conversational or task), and the platform honours exactly that value as the only depth limit.
- No agent type is limited to a shallower depth than its configured value by the platform itself; configured depth is never silently reduced.
- Task (non-conversational) agents can delegate through additional levels when their configured guardrail allows it, and those delegated agents can in turn delegate further while depth remains within the configured limit.

**Guardrails remain in force and auditable**
- When a delegation would exceed the agent's configured Max Delegation Depth, the attempt is blocked and the run ends or continues per existing guardrail behaviour, with a clear outcome message surfaced to the operator.
- Every blocked over-deep delegation is recorded in the agent's execution history in terms the operator can see and audit, distinguishing policy enforcement from functional failure.
- Delegation depth blocks are reported against the configured limit, so the recorded outcome states what limit was reached.
- Other guardrails are unchanged: delegation cycle and dead-loop validation, delegated-step budgets, iteration ceilings, timeouts, and token budgets continue to apply exactly as before.

**Execution-log visibility stays single-level scoped**
- An agent's execution log shows that agent's own execution and the lifecycle events of its direct delegations only.
- An execution log never recursively displays the logs of a delegated agent's own sub-agents (grandchildren); no grandchild activity is folded into the parent log.
- From a delegated agent's own execution log, the operator can see that agent's sub-delegation events — including the delegation it made, its progress, and its outcome.
- Drill-in via the existing "View Execution Logs" action on a delegation entry is sufficient to move from a parent log to the delegated agent's log; no new navigation model is required.
- Opening a delegated agent's log does not change the parent log's contents, and the parent log remains readable and unaffected once the operator returns.

**Status display reflects configuration**
- The delegation status surfaced to the execution-log viewer reflects the agent type's configured maximum, not a fixed platform value.
- Two agent types configured with different maximum depths display different maximums in their respective logs.
- When a run is actively delegating, the depth shown is consistent with the configured maximum for that agent type and with the delegation events recorded in the log.

**Compatibility**
- Agent types that never configured a Max Delegation Depth keep their current effective default behaviour, with no change to stored values or to what operators see on the configuration screen.
- Agent types that already configured a value see no change to that stored value; only the hidden override stops applying.

## Out of Scope

- Redesigning the Max Delegation Depth setting itself — its location, label, and default value are unchanged, and basic non-negative validation still applies. The only validation change is that the platform-level upper bound on the value is removed, so operators are no longer limited by a fixed maximum.
- Recursive or tree-style log aggregation of any kind, including an expandable nested log view, a merged multi-agent log, or a chain-wide log search.
- Building a new delegation-chain visualisation in the execution log; the existing delegation entry, its status timeline, and its drill-in action are reused as-is.
- Changing the Agent Runtime Monitor's layout, depth columns, or live visualisation behaviour.
- Changes to delegation cycle and recursion prevention, delegated-step budgets, iteration ceilings, timeouts, or token budgets.
- Any data migration, backfill, or retroactive change to previously recorded executions or their logs.
- Automatic or model-driven decisions about how deep an agent *should* delegate; depth remains an operator policy, not a runtime inference.
- Changes to permission resolution, preview-and-approval requirements, or tenant isolation for delegation targets.

## Dependencies & Constraints

- **Single source of truth.** The per-agent-type Max Delegation Depth guardrail is the sole depth limit after this change; nothing in the product may silently impose a shallower limit.
- **Existing default preserved.** Agent types with no explicitly configured depth must inherit today's default so that existing deployments behave predictably without operator action.
- **Guardrails stay consistent.** Depth limits continue to be applied alongside the other execution guardrails, and the change must not weaken adjacent limits or blur the distinction between a policy stop and a failure.
- **Log-scoping contract is a product guarantee.** Single-level log visibility is deliberate and is preserved by this epic, not relaxed; operators rely on predictable log contents for audit and troubleshooting.
- **Explainability for operators.** Because depth is now solely configured, the operational burden shifts to clear messaging: blocked delegation must state the limit that was reached, and the log's displayed maximum must be traceable to configuration.
- **No change to stored data.** The change affects runtime behaviour and what operators see, not previously recorded executions or configured values, so no data migration or downtime is required.
- **Deployment and entitlement neutrality.** No new configuration setting or licence dimension is introduced; the change is confined to delegation behaviour and the status shown to operators.
