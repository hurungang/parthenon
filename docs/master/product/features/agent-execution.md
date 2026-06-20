# Agent Execution Flow (Business Overview)

## Overview
Agent execution in Parthenon is governed by a secure, auditable, and policy-driven process with explicit service segregation. Agent Runtime is restricted to approved execution responsibilities, while sensitive identity handling and data-access governance remain centralized in the Control Center. Agents never receive or store identity tokens. Runtime access to internal business operations is controlled through a dedicated allowlist for runtime-essential paths, with deny-by-default behavior for all other internal control paths. This reduces privilege overlap and strengthens boundary assurance.

## Business Goals
- Provide a secure, auditable execution environment for AI agents in enterprise settings
- Enforce explicit service segregation between runtime execution and identity/credential management
- Prevent recursive or unbounded agent delegation through guardrail policies
- Give operators visibility into running agent topology and the ability to terminate execution trees
- Support human-in-the-loop intervention for decisions requiring operator judgment

## User Stories
- As a **platform operator**, I want to see all running agents and their delegation chains in a topology view so that I can understand execution relationships at a glance.
- As a **security administrator**, I want agent identities and credentials to never be accessible to agent runtime code so that credential exposure risk is eliminated.
- As an **SOP author**, I want agents to be able to pause and request human input during execution so that critical decisions can be reviewed before proceeding.
- As an **operations lead**, I want to identify cycle, iteration, delegation, timeout, and token-policy outcomes quickly in session summaries so that I can triage incidents efficiently.
- As a **platform operator**, I want to see delegation status events (`delegating`, `waiting`, `delegation_resumed`) in the non-conversational agent execution log, so that I can follow the progress of automated workflows that involve agent-to-agent delegation in real time.
- As a **platform operator**, I want a paused execution log with an inline intervention popup when a delegated sub-agent requests human input, so that I can respond to approve, choose, or provide text without leaving the log view.
- As an **operator**, I want to terminate an entire execution tree (parent and all delegated children) from a single action so that I can stop problematic runs immediately.

## Key Principles
- Agent runtime instances are authenticated using unique certificates
- Identity tokens are never distributed to agent runtimes
- All identity and authorization operations are managed centrally
- Runtime access is limited to caller-specific, business-essential internal control paths
- Non-allowlisted internal control paths are denied by default
- Every tool call is authorized before execution
- All actions are logged for compliance and audit

## Execution Guardrails and Cost Controls
- Each Agent Type follows a distinct guardrail policy profile for execution boundaries and cost controls
- Delegation chains are checked for direct and indirect recursion before and during execution
- Execution boundaries are enforced as one bounded policy that includes direct and delegated activity
- Delegation boundaries are enforced through per-Agent-Type depth and delegated-step limits
- Non-conversational agent delegation is limited to 1 level — delegated sub-agents cannot further delegate; attempts are blocked and recorded in execution logs
- Runtime boundaries are enforced through per-Agent-Type timeout policies
- Conversational sessions keep current-session token consumption continuously visible to users
- Conversational sessions are not hard-stopped solely by token-budget thresholds
- Non-conversational and automated runs keep token-budget enforcement where provider support exists
- When token-budget enforcement is unavailable, a defined fallback behavior is applied and surfaced to operators
- Guardrail outcomes are represented as policy-stop outcomes so operators can distinguish them from functional failures
- **Guardrail enforcement is applied consistently across direct and delegated execution paths** with no policy bypass between parent and child runs
- **The default enforcement mode for newly configured guardrails is `terminate`** unless an authorized operator explicitly selects a different posture
- **Observe-only guardrail limit events are surfaced as user-visible alerts** in frontend execution logs for the affected run
- **Agent execution is blocked when the requested model is disabled**, or when the model is under a disabled vendor, and the block is surfaced in execution logs with a clear operator-visible reason

## Model-Usage Guardrails
- Model-usage guardrails are organised under a **vendor → model → guardrail hierarchy**: vendors group their models, and each model carries one to four guardrail records, one per period (hour, day, week, month)
- Operators configure only the periods they actually need — no forced four-period entry
- Each guardrail has its own enforcement posture (`terminate` or `observe-only`) and can be individually enabled, disabled, or removed
- An authorized operator can temporarily disable an individual model; while disabled, any agent execution that would use that model is blocked
- An authorized operator can temporarily disable an entire vendor; while disabled, every model under that vendor is treated as disabled
- When a vendor is disabled, the per-model disable affordances remain visible to show the cascade source
- Disabled-model and disabled-vendor block events appear in execution logs as user-visible operational signals distinct from standard execution failures
- A multi-vendor guardrail breach dominates other deny reasons in the execution log block reason

## Unified Tool Naming Convention

All tools available to agents — whether built-in platform tools or external MCP server tools — use a consistent naming scheme that separates the server namespace from the tool name. This convention ensures tool names are globally unique and routing is deterministic.

## Explicit Result Saving

The agent runtime does **not** automatically save results at the end of execution. If an SOP or agent instruction requires a result to be persisted, the agent must explicitly call the `system____save_result` tool. If no such instruction is given, no result record is created. This design ensures result creation is intentional and traceable to a specific SOP step.

## Human-in-the-Loop Intervention

Agents can pause execution and request human input during the observe-reason-act loop by calling the `system____human_intervene` tool. This supports three intervention types:

- **Approval**: Agent requests a yes/no decision. The tool returns `{"approved": true}` or `{"approved": false}` to the agent.
- **Choice**: Agent presents a list of selectable options. The tool returns the selected option string.
- **Text**: Agent prompts for free-form contextual input. The tool returns the operator's text.

When an agent calls `human_intervene`, the session transitions from `running` to `waiting_for_human` state. No further LLM or tool calls are made while waiting. An operator views and responds to the request through the Web UI, and the session automatically resumes with the response value injected as the tool's return value. If the session is terminated while waiting, all pending intervene requests are automatically cancelled.

### Intervention in Conversational Delegation

When a **delegated sub-agent** calls `human_intervene` during a conversational session, the intervention request is routed to the parent conversation's UI — not just to the operator dashboard. An intervention dialog (approval, choice, or text) appears inline in the chat at the point of delegation. The parent conversation pauses with a "Waiting for your input" indicator. The user responds in-place, and the response is injected into the sub-agent's execution. The conversation resumes automatically, and the response is recorded as a conversation turn. If multiple delegated sub-agents request intervention in parallel, requests are queued and presented sequentially — one intervention at a time — in the conversation UI.

### Intervention in Non-Conversational Delegation

When a **delegated sub-agent** calls `human_intervene` during a non-conversational (task) agent execution, the intervention request is surfaced as an inline popup in the parent agent's execution log view — not as a separate modal. The execution log pauses and displays the intervention type (approval, choice, or text) with context. The operator can respond directly from the log view. After responding, the log stream resumes automatically and the response is recorded as a timeline event. If the popup is dismissed or the operator navigates away, a persistent banner at the top of the execution log indicates the session is waiting for human input. On reconnect, pending interventions are re-surfaced automatically.

The runtime control dashboard now surfaces intervention requests from both non-conversational standalone agents and delegated agents in conversational sessions, giving operators a single view of all pending human interventions regardless of execution context.

The `human_intervene` tool follows the same explicit-trigger pattern as `system____save_result` — it is available to all agents by default and must be referenced in SOP or agent instructions to be used.

## Runtime Control and Termination Governance
- A **runtime control dashboard** surfaces all currently running agents, their delegated children, and operator-controlled termination actions
- A **topology diagram** visualises active parent-child agent execution relationships with selectable nodes
- Authorized operators can **terminate any running or delegated node** from the dashboard
- **Terminating a parent execution cascades** to all active delegated child executions it triggered
- Operator-initiated termination is recorded as a distinct `terminated` outcome in execution logs, distinct from `failed` (genuine agent or runtime error)
- Termination requests are routed from Control Center through the Communication Hub to Agent Runtime to preserve service segregation and certificate-based authentication boundaries
- If a user lacks required permission, termination controls are unavailable or rejected with a clear user-visible message

## Recursion and Dead-Loop Prevention
- Agent create, update, and run flows **validate recursive delegation risk** at entry points
- Recursion-prone agent delegation configurations are blocked before execution proceeds
- Dead-loop scenarios are prevented during run initiation when risk conditions are detected
- Recursion validation outcomes are reflected in execution logs

## User Impact
- Security administrators can verify and revoke agent instances
- Platform operators do not manage or distribute identity tokens
- Compliance officers can verify evidence of both permitted and blocked access outcomes
- SOP authors control when and what results are saved by including explicit save instructions, and can instruct agents to request human input using `human_intervene`
- Operators can review and respond to agent-initiated intervene requests (approval, choice, or text) from the Web UI
- Tool naming is predictable and consistent across all agent interactions
- Operations leads can identify cycle, iteration, delegation, timeout, and token-policy outcomes quickly in session summaries
- Operations leads can see live execution topology and stop problematic execution trees quickly, including all active child delegations
- Compliance owners can verify evidence of observe-only guardrail alerts and disabled-model / disabled-vendor block events

## Acceptance Criteria
- Delegation cycle checks prevent direct and indirect recursion and provide a clear stop reason
- Maximum iteration policy includes both direct and delegated activity in one bounded ceiling
- Delegation depth and delegated-step limits end sessions with clear guardrail outcomes when breached
- Timeout policy ends overrun sessions with clear status and reason
- Conversational session views continuously show current-session token usage
- Conversational sessions continue when only token budget thresholds are reached, while other guardrails remain active
- Non-conversational and automated runs enforce token budgets when supported
- Unsupported token-budget enforcement follows a transparent fallback while other guardrails stay active
- Session summaries and monitoring views clearly distinguish guardrail-policy stops from functional failures
- **Guardrail enforcement is applied consistently for agent execution and delegation paths, with no policy bypass between parent and child runs**
- **The default enforcement mode for newly configured guardrails is terminate unless an authorized operator explicitly selects a different posture**
- **When guardrail limits are reached in observe-only mode, a clear alert is visible in user-facing execution logs for the affected run**
- **Agent execution is blocked when the requested model is disabled or when the model is under a disabled vendor, and the block is surfaced in execution logs**
- Delegated sub-agent intervention requests in conversational sessions are routed to the parent conversation and surfaced as inline intervention dialogs in the conversation UI
- Parallel intervention requests from multiple delegated sub-agents are queued and presented sequentially in the conversation — one at a time
- The runtime control dashboard surfaces intervention requests from conversational delegated agents alongside those from standalone non-conversational agents
- When a non-conversational agent initiates delegation, the execution log displays a `delegating to <agent_type>` event in real time
- While the non-conversational agent is waiting for a delegated sub-agent to complete, the execution log displays a `waiting` status with a visible indicator
- When the delegated sub-agent completes and the parent agent resumes, the execution log displays a `delegation_resumed` event
- All delegation status events appear in the execution log without requiring manual page refresh
- Sub-agent intervention requests in non-conversational execution surface as inline popups in the log view with full context
- Non-conversational agents are limited to 1-level delegation depth; sub-agents cannot further delegate
- Blocked delegation attempts due to depth limit produce clear outcome messages in execution logs
- Delegation exit conditions (success, timeout, failure, termination) appear as distinct statuses in execution logs

## Out of Scope
- Technical implementation details, code, or architecture diagrams
- Legacy agent execution models without certificate-based security

## Dependencies & Constraints
- Requires Control Center for certificate management and audit logging
- Relies on OIDC-compliant identity provider
- Requires approved service-boundary policies and runtime allowlist governance
- All changes must comply with Parthenon's security and audit conventions
- Must comply with service segregation rules: execution remains in Agent Runtime; governance and control remain in Control Center boundaries
- Must preserve secure handling of sensitive credentials and identity material; no expansion of agent access to sensitive data
- Depends on trustworthy model-usage measurement and period rollup data so hourly, daily, weekly, and monthly posture can be shown accurately
- Depends on a vendor and model catalogue that the new hierarchy can be built on top of, so that vendor enable/disable and model selection have a stable source of truth
- Depends on reliable runtime state and delegation relationship signals to render accurate running-agent topology
- Depends on permission enforcement so only authorized users can configure guardrails, disable vendors or models, and terminate executions
- Constrained by enterprise auditability requirements: guardrail alerts, model-usage posture changes, vendor/model disable changes, and termination actions must be visible in operational logs
