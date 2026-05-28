# Spec Change: Agent Execution Guardrails and Cost Controls

## Affected Spec Areas
- docs/master/product/features/agent-execution.md
- docs/master/product/features/agent-types.md
- docs/master/product/features/sops.md
- docs/master/product/features/communication-hub.md
- docs/master/product/features/control-center.md
- docs/master/ux/prototype/index.html
- docs/master/ux/conversation-sessions-prototype-updates.md
- docs/master/architecture/system-overview.md
- docs/master/architecture/modules/agent-runtime.md
- docs/master/architecture/modules/control-center.md
- docs/master/architecture/modules/communication-hub.md
- docs/master/qa/test-plans/agent-execution-test-plan.md
- docs/master/operations/README.md

## New Capabilities
- Delegation guardrail that detects and blocks cyclic Agent Type and SOP delegation chains, including indirect recursion.
- Configurable execution-limit policy per Agent Type that counts direct and delegated activity toward one bounded ceiling.
- Configurable delegation-depth and delegated-step guardrails per Agent Type to prevent unbounded delegation fan-out.
- Configurable timeout policy per Agent Type to end sessions that exceed approved runtime windows.
- Conversational-session policy that keeps current-session token consumption continuously visible while allowing users to continue the same conversation.
- Configurable token-budget policy per execution for non-conversational or automated runs where model and provider support is available.
- Standard fallback behavior when token-budget enforcement is unavailable, while preserving other guardrails.
- Clear guardrail-stop status visibility in Agent Session operations views for triage and governance reporting.
- Control Center UI capability for administrators to view a separate guardrail configuration profile for each Agent Type.
- Control Center UI capability for authorized administrators to edit and save each Agent Type's guardrail profile.
- User-facing execution summaries show conversational guardrail usage, including current-session token consumption, alongside other session outcome signals.
- Guardrail token budget values are displayed in k tokens in the Control Center UI, with 1000k as the default presentation value.

## Modified Capabilities
Before:
- Delegation could chain across SOPs without a formal cycle-blocking guarantee.
- Iteration and delegated execution depth/step budgets were not governed by a unified bounded policy.
- Time and token controls were not consistently defined as Agent Type-level business guardrails.
- Session stop reasons did not consistently distinguish guardrail policy enforcement from general execution failure.

After:
- Delegation chains are analyzed and blocked when cyclic references are detected.
- Agent Type policies enforce bounded execution through maximum iteration limits that include delegated activity.
- Agent Type policies enforce bounded delegation through explicit depth and delegated-step budgets.
- Agent Type policies enforce bounded runtime through configurable timeout limits.
- Conversational sessions keep current-session token consumption visible in session views and do not hard-stop solely due to token budget thresholds.
- Token-budget controls continue to apply to non-conversational or automated runs when supported, with explicit fallback behavior when unavailable.
- Guardrail-triggered session termination is clearly represented for operators and governance stakeholders.
- Control Center UI provides a distinct, per-Agent-Type guardrail profile with managed updates, and saved settings are reflected in governance views.
- Execution summary views surface guardrail usage and current-session token consumption for conversational sessions.

## Removed Capabilities
- Implicit tolerance for unbounded recursive delegation across SOP and agent delegation chains.
- Reliance on manual intervention as the primary control for runaway iteration or duration.
- Ambiguous handling of conversational-session token visibility and continuation behavior.
- Ambiguous handling of unsupported token-budget enforcement.

## Spec Update Instructions
- Update product feature specs for Agent Types, SOPs, Agent Sessions, Communication Hub, and Control Center to define guardrail policy behavior in business terms.
- Update product and UX specs to define how Control Center presents, edits, and saves a distinct guardrail profile per Agent Type for authorized administrators.
- Update product and UX specs so the guardrail editor stays compact by default and adapts its controls by input type.
- Add explicit delegation-cycle prevention rules that cover direct and indirect recursion across delegated SOP chains.
- Add execution-boundary policy language for maximum iterations and timeout controls at Agent Type scope.
- Add execution-boundary policy language for delegation depth and delegated-step controls at Agent Type scope.
- Add token policy language that defines continuous current-session token visibility for conversational sessions and clarifies that token budget alone does not hard-stop active conversation.
- Add token-budget policy language that preserves supported-mode enforcement for non-conversational or automated runs and unsupported-mode fallback behavior.
- Update architecture docs to reflect segregation-aligned responsibility boundaries for execution, governance, and guardrail enforcement outcomes.
- Update impacted master UX docs so Agent Types and execution-related views clearly represent per-Agent-Type guardrail configuration workflows.
- Update the QA master test plan to include scenarios for cyclic delegation blocking, iteration-limit stops, timeout stops, conversational current-session token visibility with continued conversation, supported token-budget stops for non-conversational or automated runs, and unsupported token-budget fallback behavior.
- Update the QA master test plan to include execution-summary visibility for conversational guardrail usage and token-budget presentation in k-token units.
- Update operations docs with guardrail outcome visibility expectations for session monitoring, alert interpretation, and incident triage.
