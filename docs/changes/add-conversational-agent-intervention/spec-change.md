# Spec-Change: Conversational Agent Intervention

## Affected Spec Areas

| Spec Area | File | Reason |
|-----------|------|--------|
| Conversation Management | `docs/master/product/features/conversation-management.md` | New intervention dialogs and "waiting for input" state in conversation UI |
| Agent Execution | `docs/master/product/features/agent-execution.md` | Intervention routing for delegated agents; parallel intervention queueing |
| Agent Management | `docs/master/product/features/agent-management.md` | Conversation sessions now support inline intervention resolution |
| SOP Management | `docs/master/product/features/sop-management.md` | SOP delegation with human-approval gates now reliable inside conversations |
| Agent Gateway | `docs/master/product/features/agent-gateway.md` | Gateway must route delegated intervention requests to parent conversation sessions |

## New Capabilities

- **In-Conversation Intervention Dialog**: When a delegated sub-agent within a conversational session calls `human_intervene`, an intervention dialog (approval, choice, or text) appears inline in the conversation UI at the point of delegation
- **Conversation Pause-on-Intervention**: The conversation visually pauses when a sub-agent is waiting for human input — the chat shows a distinct "Waiting for your input" indicator, and no new messages can be sent until the intervention is resolved
- **Delegated Intervention Audit Trail**: Every intervention request and response within a conversational session is persisted as a distinct conversation turn (`intervene_request` + `intervene_response`) with delegation chain metadata, operator identity, and timestamp
- **Intervention Reconnect Resilience**: If a user disconnects while an intervention dialog is open, the pending intervention request is re-surfaced automatically when the user reconnects to the conversation

## Modified Capabilities

### 1. Human-in-the-Loop Intervention (in `agent-execution.md`)

**Before**: `human_intervene` invocations during conversational delegation were not surfaced to the user. The conversation showed indefinite waiting with no visible intervention prompt. Operator could not respond.

**After**: `human_intervene` invocations from delegated sub-agents in conversational sessions are routed to the parent conversation's UI. An intervention dialog appears inline in the chat. The conversation pauses. The user responds, and the response is injected into the sub-agent. The conversation resumes with the response recorded as a turn.

### 2. Delegation Visibility Cues (in `conversation-management.md`)

**Before**: Delegation cues were limited to: thinking indicator, "Delegating to agent <type>", waiting indicator, folded execution snippets, and timeout/failure end states. There was no cue for "delegated agent needs human input."

**After**: A new delegation cue is added: when a delegated sub-agent requests human intervention, the chat shows a "Waiting for your input" indicator with the intervention dialog. This replaces the indefinite waiting state previously shown. The cue resolves when the user responds or the intervention is cancelled/terminated.

### 3. Conversation Session Lifecycle (in `conversation-management.md`)

**Before**: Active conversation sessions accepted messages continuously. There was no concept of the conversation being blocked on an intervention.

**After**: While an intervention request is outstanding in a conversation, the session enters a distinct blocked state: the message input is disabled or shows a clear indication that input is pending intervention resolution. The session transitions back to active when the intervention is resolved.

### 4. Session State for Conversational Delegation (in `conversation-management.md`)

**Before**: The parent session remained in `running` state while delegated sub-agents executed, regardless of sub-agent state.

**After**: The parent conversational session can enter a temporary `waiting_for_human` state when a sub-agent requests intervention. This state is visible in the session list and dashboard, allowing operators to identify conversations needing attention.

### 5. Runtime Control Dashboard (in `agent-execution.md`)

**Before**: The runtime control dashboard showed intervention requests from non-conversational (standalone) agents only.

**After**: The dashboard also surfaces intervention requests originating from delegated agents in conversational sessions, enabling central monitoring of all pending human interventions regardless of execution context.

## Removed Capabilities

None. All existing intervention and conversation capabilities are preserved. This change is purely additive — it fills the gap where delegated intervention requests were previously invisible.

## Spec Update Instructions

### Update `docs/master/product/features/conversation-management.md`

- Add "Intervention Dialog in Conversations" to the **What It Does** section: when a delegated sub-agent calls `human_intervene`, the conversation UI shows an inline intervention dialog (approval, choice, or text)
- Add "Conversation Pause-on-Intervention" to **What It Does**: the conversation shows a distinct "Waiting for your input" state, message input is blocked until the intervention is resolved
- Add "Intervention Turn Types" to the **Turn Types** concept: already listed as `intervene_request` and `intervene_response`; expand to note these now include turns from delegated sub-agents with delegation chain metadata
- Add "Delegation Intervention Cue" to the **Delegation Visibility Cues** concept: a new visible state in chat when delegated agent requires human input
- Add to **Acceptance Criteria**:
  - When a delegated sub-agent requests intervention in a conversation, an intervention dialog appears inline in the chat
  - The conversation pauses and shows a clear "waiting for human input" indicator during the intervention wait
  - The user's intervention response is recorded as a conversation turn visible in history and replay
  - If the user reconnects mid-intervention, the pending intervention dialog is re-surfaced

### Update `docs/master/product/features/agent-execution.md`

- Extend the **Human-in-the-Loop Intervention** section to document how intervention requests from delegated sub-agents in conversational sessions are surfaced to the parent conversation UI, not only to the operator dashboard
- Add that the runtime control dashboard now surfaces intervention requests from conversational delegated agents
- Add acceptance criterion: delegated sub-agent intervention requests in conversational sessions are routed to the parent conversation and surfaced in the conversation UI
- Add acceptance criterion: parallel intervention requests from multiple sub-agents are queued and presented sequentially in the conversation

### Update `docs/master/product/features/agent-management.md`

- In the **Conversation agent sessions** bullet group under **What It Does**, add: conversation sessions surface inline intervention dialogs when delegated sub-agents request human input
- Add acceptance criterion: conversation sessions show intervention requests from delegated agents and allow inline response

### Update `docs/master/product/features/sop-management.md`

- In the **Agent Delegation** concept, note that delegation-based human intervention gates now work reliably inside conversational sessions
- Add acceptance criterion: SOPs with delegated human intervention steps surface intervention requests in the parent conversation UI when executed conversationally

### Update `docs/master/product/features/agent-gateway.md`

- Extend **What It Does** to note that the gateway routes delegated intervention requests from Agent Runtime back to parent conversational sessions via the Communication Hub
- Add acceptance criterion: delegated intervention requests are routed from sub-agent sessions to the parent conversation session without requiring direct database access from Agent Runtime
