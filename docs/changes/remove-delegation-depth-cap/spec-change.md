# Spec Change: Remove the Hard-Coded Delegation Depth Cap

## Affected Spec Areas

| Master spec area | Impact |
|---|---|
| [Agent Execution](../../master/product/features/agent-execution.md) | Delegation depth limit statements change: the fixed one-level task-agent rule is removed and depth becomes configured-only. Log-scoping statements are made explicit. |
| [Agent Session Logs](../../master/product/features/agent-session-logs.md) | Delegation status display now reflects the configured maximum; single-level log scoping is documented as a guarantee. |
| [Agent Gateway](../../master/product/features/agent-gateway.md) | The "Delegation Depth Limit" concept (one level for non-conversational agents) is replaced by a configured-limit concept. |
| [SOP Management](../../master/product/features/sop-management.md) | Delegation boundary wording clarifies that depth boundaries follow agent-type configuration at any level of a chain. |
| [Agent Management](../../master/product/features/agent-management.md) | Guardrail profile wording clarifies Max Delegation Depth is the sole depth limit for every agent type. |
| [Agent A2A Communication and Slug Enforcement](../../master/product/features/agent-a2a-communication-and-slug-enforcement.md) | Recursion and dead-loop prevention unchanged; wording confirms depth limits are separate from cycle detection and are configuration-driven. |
| [Agent Types](../../master/product/features/agent-types.md) | Guardrail wording states that Max Delegation Depth applies equally to conversational and task agent types. |
| [Operations — Agent Execution Guardrails](../../master/operations/runbooks/agent-execution-guardrails.md) | Runbook wording updated: unexpected depth stops must be traced to configuration, not to a platform cap. |

## New Capabilities

- **Configuration-authoritative delegation depth.** Operators can configure any permitted Max Delegation Depth on any agent type, and that value is the only depth limit the platform applies.
- **Multi-level task delegation.** Delegated task (non-conversational) agents can delegate onward whenever their own configured guardrail allows it, enabling multi-level automated workflows.
- **Configuration-true depth reporting.** The delegation status shown in the execution log reports the agent type's configured maximum depth, so the displayed limit always matches the configuration screen.
- **Explicit single-level log scoping.** An agent's execution log is confirmed to contain only that agent's own execution plus its direct delegation lifecycle events, with deeper activity reached by drilling into the delegated agent's own log.

## Modified Capabilities

| Capability | Before | After |
|---|---|---|
| Depth limit for conversational agents | Hidden effective ceiling of two levels (originating agent plus one delegated level) applied by the platform alongside configuration | Configured Max Delegation Depth is the only limit; the platform imposes no additional ceiling |
| Depth limit for task (non-conversational) agents | Forcibly restricted to one delegation level regardless of configured guardrail; sub-agents could not delegate | Configured Max Delegation Depth governs; delegated task agents may delegate onward while within the configured limit |
| Delegation status in the execution log | Reported the platform's fixed depth value, contradicting the configured maximum on task-agent runs | Reports the agent type's configured maximum depth |
| Over-deep delegation outcomes | Blocked, with messages describing a platform-imposed depth limit | Blocked at the configured limit, with messages stating the limit that was reached; outcome remains recorded and auditable |
| Depth guardrail semantics (all agent types) | Guardrail value could be silently overridden depending on how an agent type is used | Guardrail value is authoritative and never silently reduced |
| Configurable guardrail value range | Configurable depth was capped at a fixed platform maximum (32) | Any non-negative depth is accepted; negative values are still rejected, and the setting's location and default are unchanged |
| Execution-log visibility scope | Each log shows the agent's own execution and direct delegation lifecycle events; deeper logs reached by drill-in | Unchanged in behaviour; now stated as a product guarantee, explicitly excluding recursive aggregation of sub-agent logs |
| Delegation depth default | Default applied to agents without an explicit setting | Unchanged; agents that never configured a depth keep the same effective default |

## Removed Capabilities

- **Platform-imposed depth ceiling.** The invisible cap that stopped a delegation chain after one delegated level and forced task agents to a single delegation level is removed. No user-facing feature or setting is deleted; only the hidden override disappears.
- No other capability is removed: cycle and dead-loop prevention, delegated-step budgets, iteration ceilings, timeouts, token budgets, preview-and-approval flows, permissions, and tenant scoping for delegation targets all remain in force.

## Spec Update Instructions

- In **Agent Execution**: replace the acceptance criterion stating task agents are limited to one delegation level; replace it with a criterion stating that delegation depth is bounded solely by the agent type's configured Max Delegation Depth, for both conversational and task agents, and that blocked attempts report the configured limit.
- In **Agent Execution**: add explicit criteria that an execution log shows only the current agent's execution and its direct delegation events, that sub-agent sub-delegation logs are never recursively included, and that drilling into a delegated agent's log reveals that agent's own sub-delegation events.
- In **Agent Session Logs**: add that the delegation status and maximum depth shown in the execution log reflect the agent type's configured maximum rather than a fixed value; add the single-level log-scoping guarantee to the acceptance criteria.
- In **Agent Gateway**: rewrite the "Delegation Depth Limit" key concept so the limit is described as the agent type's configured guardrail applying to all agent types, and that attempts are blocked and recorded when the configured limit is reached.
- In **Agent Management** and **Agent Types**: state that Max Delegation Depth is the sole delegation depth limit, applies to conversational and task agent types alike, and is never silently reduced; keep the setting's location and default unchanged, and remove the fixed upper bound on the value so configuration is not capped by the platform.
- In **SOP Management**: clarify that delegation depth boundaries are inherited from each participating agent type's configuration, so a multi-step SOP can extend beyond one delegation level when the participating agent types are configured to allow it.
- In **Agent A2A Communication and Slug Enforcement**: retain all recursion and dead-loop statements; add a note distinguishing configuration-driven depth limits from cycle detection, so the two are not conflated.
- In **Operations — Agent Execution Guardrails**: revise troubleshooting guidance so an unexpected delegation depth stop is diagnosed as a guardrail configuration issue on the agent type, and note that depth limits now vary by agent type configuration rather than by agent-type category.
- Verify no other master product or operations document asserts a fixed delegation depth for any agent category; correct any such statement to reference the configured guardrail. (Fixed-depth statements in master architecture documents — Agent Runtime, Agent Lifecycle, Tool Execution — are covered by the architecture change document.)
