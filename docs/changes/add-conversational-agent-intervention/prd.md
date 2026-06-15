# PRD: Conversational Agent Intervention

## Epic Overview

Currently, non-conversational agents can pause and request human input via `system____human_intervene`, surfacing an intervention dialog for operator approval, choice selection, or free-text input before resuming. However, in conversational agent sessions, when a delegated sub-agent requires human intervention, the request is invisible to the user — the conversation shows only an indefinite waiting state with no way to respond. The sub-agent hangs or fails silently. This change surfaces delegated intervention requests within the conversation UI so users can see and respond to them in context, completing the human-in-the-loop loop for the full spectrum of agent execution patterns. This is essential for enterprise deployments where conversational agents orchestrate complex SOPs involving sub-agents that may require human judgment at any delegation depth.

## Business Goals

- Eliminate silent failures during conversational agent delegation by surfacing all sub-agent intervention requests to the conversation UI
- Reduce mean time to resolve intervention requests during conversations from indefinite (current broken state) to under the operator's response time
- Ensure 100% of delegated intervention requests in conversational sessions are surfaced and resolvable inline without leaving the conversation view
- Maintain audit integrity: every intervention request and response within conversational sessions is captured as a conversation turn with full traceability
- Preserve the existing non-conversational intervention flow without regression

## Users & Personas

- **Business User** — interacts with conversational agents daily; needs to see and respond to sub-agent intervention requests without switching context or leaving the conversation
- **SOP Author** — designs multi-agent workflows with delegation and conditional human approval gates; needs confidence that intervention points work reliably inside conversational executions
- **Platform Operator** — monitors agent sessions and intervenes when manual decisions are needed; needs intervention requests surfaced clearly in the operator dashboard, whether from direct or delegated agents
- **Compliance Auditor** — reviews conversation history; needs all intervention requests and responses fully captured in the conversation record

## User Stories

- As a **business user**, I want to see an intervention dialog appear inline during a conversation when a delegated sub-agent requests my input, so that I can respond without losing conversation context.
- As a **business user**, I want the conversation to visibly pause with a clear indicator when a sub-agent is waiting for my intervention, so that I understand why the conversation isn't progressing.
- As a **business user**, I want to respond to intervention requests during delegation with the same approval/choice/text options as non-conversational interventions, so that the experience is consistent.
- As a **platform operator**, I want to see all active intervention requests — including those from delegated agents in conversational sessions — in the runtime control dashboard, so that I can monitor and respond from a central view.
- As a **compliance auditor**, I want every intervention request and response within a conversational session recorded as a distinct conversation turn, so that the full decision trail is auditable.
- As an **SOP author**, I want agents at any delegation depth to reliably surface human intervention requests to the parent conversation, so that I can build approval gates into multi-agent workflows with confidence.

## Acceptance Criteria

### Core Intervention Flow in Conversations

- When a delegated sub-agent calls `human_intervene` during a conversational session, an intervention dialog appears in the conversation UI at the point of delegation
- The conversation shows a clear "Waiting for your input" indicator in the chat flow, replacing the current indefinite waiting state
- The intervention dialog presents the same three intervention types as the non-conversational flow: Approval (yes/no), Choice (select from options), and Text (free-form input)
- After the user responds, the intervention dialog closes, the response is injected into the sub-agent's execution, and the conversation resumes automatically
- The user's response appears as a conversation turn clearly marked as an intervention response

### Conversation Pause and Resume

- While a sub-agent is waiting for intervention, the primary conversational agent's processing indicator shows a distinct "waiting for human input" state
- No new user messages can be sent in the conversation while an intervention request is outstanding
- If the user dismisses or cancels the intervention dialog, the sub-agent receives a cancellation signal and the conversation resumes
- If the parent session is terminated while a sub-agent is waiting for intervention, the intervention request is cancelled and the conversation shows the termination outcome

### Audit and Traceability

- Every intervention request is persisted as a conversation turn with type `intervene_request`, including the intervention type (approval/choice/text), context message, and available options
- Every intervention response is persisted as a conversation turn with type `intervene_response`, including the operator's identity, response value, and timestamp
- Intervention turns are visible in conversation history, audit views, and replay
- The delegation chain is preserved in intervention records so auditors can trace which sub-agent at which depth made the request

### Non-Conversational Flow Preservation

- Existing non-conversational intervention flow continues to work without any change in behavior
- Non-conversational intervention requests continue to appear in the operator dashboard as before
- Session state transitions (`running` → `waiting_for_human` → `running`) are preserved for non-conversational executions

### Error Handling and Edge Cases

- If the user's connection drops while an intervention dialog is open, the intervention request remains pending and is re-surfaced when the user reconnects to the conversation
- If multiple delegated sub-agents request intervention in parallel, intervention requests are queued and presented one at a time in the conversation UI
- If the sub-agent times out while waiting for intervention, a clear timeout message appears in the conversation and the session state reflects the timeout
- Permission errors (e.g., user lacks permission to respond to a specific intervention type) are surfaced with a clear error message in the dialog, not a silent failure

## Out of Scope

- Changes to the intervention tool itself (`system____human_intervene`): the tool's interface and behavior remain unchanged; only the routing and surfacing of its invocation during delegation is affected
- Parallel/batch intervention resolution: multiple concurrent intervention requests are queued sequentially, not presented simultaneously
- Custom intervention types beyond the existing three (Approval, Choice, Text)
- Changes to non-conversational agent intervention flow or the operator dashboard intervention view
- Mobile or push-notification-based intervention response
- Intervention delegation or escalation (e.g., routing an intervention request to a specific operator role)
- Changes to how intervention requests are handled for agent-to-agent (A2A) communication outside of a user-facing conversation

## Dependencies & Constraints

- Depends on the Communication Hub to route intervention requests from delegated Agent Runtime instances back to the parent conversational session
- Depends on Control Center to persist intervention request/response turns in the conversation store with correct delegation chain metadata
- Must comply with service segregation rules: intervention routing must not require Agent Runtime to have direct database access or identity token access
- Must preserve certificate-based authentication boundaries: delegated agent instances authenticate with agent-instance certificates; intervention routing must respect these boundaries
- Must maintain audit integrity: all intervention turns must be captured with operator identity and timestamp regardless of delegation depth
- Constrained by existing `human_intervene` tool contract: the tool's input/output schema is fixed; this change only affects how invocations during delegation are surfaced to the user
- Must not introduce new sensitive data exposure paths: delegated agents must never receive user identity tokens or database credentials through the intervention flow
