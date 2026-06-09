# Specification Delta: Human Intervene

## Affected Spec Areas

| Spec Area | Description of Change |
|-----------|----------------------|
| Agent Execution (`docs/master/product/features/agent-execution.md`) | New execution lifecycle state "waiting for human intervention"; new system tool `system____human_intervene`; new suspend/resume behavior |
| Result Management (`docs/master/product/features/result-management.md`) | Pattern reference — this feature follows the same "default system tool available to all agents" pattern as `system____save_result` |
| Agent Runtime & Gateway (`docs/master/product/features/agent-runtime-gateway.md`) | New dashboard filter for executions waiting on human input; new response interface for operators |
| Execution Log Streaming (`docs/master/product/features/execution-log-streaming.md`) | Intervene popup interrupts the live log stream when agent pauses for human input; stream resumes after response |
| Notification Integration (`docs/master/product/features/notification-integration.md`) | New notification trigger type for intervene request created and responded events |
| Observability (`docs/master/product/features/observability.md`) | New metrics and events for intervene request lifecycle (created, responded, timed out, cancelled) |
| Communication Hub (`docs/master/product/features/communication-hub.md`) | New tool routing for `system____human_intervene`; new control messages for suspend/resume |
| Conversation Management (`docs/master/product/features/conversation-management.md`) | New conversation event types for intervene request creation and response |

---

## New Capabilities

1. **`system____human_intervene` System Tool** — A new built-in platform tool (server: `system`, tool: `human_intervene`) available to all agents by default, following the same pattern as the existing `system____save_result` tool. The tool accepts an intervention type (approval, choice, or text) and type-specific parameters, suspends execution, and awaits human response.

2. **Agent Execution Suspend/Resume** — A new execution lifecycle state (`waiting_for_human`) that pauses the agent's observe-reason-act loop. No further LLM calls or tool calls are made while waiting. When the human responds, execution resumes at the same point with the input delivered to the agent as the tool's return value.

3. **Intervene Request Dashboard** — A filtered view within the Agent Executions dashboard showing all executions currently waiting for human intervention, with pending count badges and sorting by priority/timestamp.

4. **Operator Response Interface** — A dialog-based response interface supporting three intervention types:
   - **Approval**: Yes/No button pair with the agent's reason displayed
   - **Choice**: Selectable option cards/radio buttons with the agent's question
   - **Text**: Free-form text input area with character limit and agent's prompt

5. **Intervene Request Audit Trail** — Persistent record of every intervene request including requester, request type, reason, respondent, response value, timestamps, and outcome, visible in execution detail views.

6. **Notification Trigger for Intervene Requests** — New notification event type that dispatches through configured channels (email, Slack, Teams, webhook, in-app) when an intervene request is created.

7. **Inline Intervene Popup on Execution Log Streaming Page** — When a user is viewing an agent's live execution log stream and the agent triggers a `human_intervene` request, a modal popup appears directly on the log page. The live stream freezes behind the popup. After the user responds, the popup closes and the stream resumes automatically with new log entries from the agent's continued execution. A dismissible persistent banner reminds users of pending requests if they close the popup without responding.

---

## Modified Capabilities

| Capability | Before | After |
|------------|--------|-------|
| Agent Execution Lifecycle | States: `running`, `completed`, `failed`, `terminated` | States: `running`, `waiting_for_human` (new), `completed`, `failed`, `terminated` |
| Agent Execution Dashboard | Filter by status (running/completed/failed/terminated) | Additional filter: `waiting_for_human` status with pending count badge |
| System Tool Set | Tools: `system____save_result`, `system____send_notification`, `system____get_recipient_group` | Tools: adds `system____human_intervene` to the built-in system tool catalog |
| Agent Execution Details View | Shows input, output, conversation history, status | Additionally shows pending and resolved intervene requests inline |
| Execution Log Streaming Page | Continuously streams real-time execution logs while agent is running | When agent calls `human_intervene`, a modal popup interrupts the stream with the intervention request; after response, stream resumes automatically |
| Agent Execution Timeout | Timeout terminates the execution | Timeout during `waiting_for_human` marks pending requests as cancelled/expired with a clear reason |

---

## Removed Capabilities

*None.* This change introduces new capabilities without removing existing functionality.

---

## Spec Update Instructions

1. **`docs/master/product/features/agent-execution.md`**: Add the `system____human_intervene` tool to the "Unified Tool Naming Convention" section alongside `system____save_result` and `system____send_notification`. Add a new subsection "Human-in-the-Loop Intervention" describing the three intervention types, the suspend/resume lifecycle, and the `waiting_for_human` execution state. Update the "Explicit Result Saving" section to note that human intervention follows a similar explicit-trigger pattern.

2. **`docs/master/product/features/result-management.md`**: No direct changes — this file serves as the pattern reference; add a cross-reference note in the "Key Concepts" section pointing to the human_intervene feature as a sibling system tool.

3. **`docs/master/product/features/agent-runtime-gateway.md`**: Add user stories for operators reviewing and responding to intervene requests. Add acceptance criteria for the `waiting_for_human` filter in the execution dashboard. Add user story for the response interface (approval, choice, text).

4. **`docs/master/product/features/notification-integration.md`**: Add "human intervene request created" and "human intervene request responded" as new notification event types in the event catalogue.

5. **`docs/master/product/features/observability.md`**: Add intervene request lifecycle events (created, responded, expired, cancelled) to the observability event catalogue. Add metrics for pending intervention count, average response time, and intervention resolution rate.

6. **`docs/master/product/features/execution-log-streaming.md`**: Add the inline intervene popup flow to the execution log streaming page description. Document that the stream pauses when an intervene request is active, the popup displays the intervention type and context, and the stream resumes seamlessly after the user responds. Add the persistent pending banner as an alternative to the modal.

7. **`docs/master/product/features/communication-hub.md`**: Add the `system____human_intervene` tool to the default system tool routing table. Add suspend/resume control message flows to the agent gateway section.

7. **`docs/master/product/features/conversation-management.md`**: Add intervene request creation and response as new conversation event types in the conversation history schema.
