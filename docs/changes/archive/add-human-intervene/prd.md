# PRD: Human Intervene — Agent-Driven Human-in-the-Loop Requests

## Epic Overview

The Parthenon agent platform currently executes all agent workflows autonomously with no mechanism for an agent to pause and request human input during execution. This creates a critical gap for enterprise use cases where decisions require human judgment — approving a high-value transaction, selecting between business-critical options, or providing context that only a human possesses. This change introduces a `human_intervene` system tool (alongside the existing `save_result` tool) that enables any agent to suspend its execution, request input from a human operator, and resume seamlessly once the human responds. This human-in-the-loop capability transforms Parthenon from a fully autonomous execution engine into a collaborative decision-support platform, unlocking compliance-mandated approval workflows, error-recovery flows, and interactive agent-guided processes that require human judgment.

---

## Business Goals

- Enable agents to request human approval for high-stakes actions, reducing the risk of autonomous decisions in compliance-sensitive workflows.
- Allow agents to present choices to humans and act on the selected option, enabling guided decision-support scenarios without custom integrations.
- Support free-form human input for cases where agents need contextual information only a human can provide, improving execution accuracy and reducing failures.
- Provide operators with a clear, actionable interface to view and respond to pending intervene requests, including notification of new requests.
- Eliminate the need for custom polling or webhook workarounds for human-in-the-loop scenarios by providing a first-class platform tool.

---

## Users & Personas

**Platform Operators / Approvers** — Users responsible for reviewing, approving, or providing input when an agent requests human intervention during execution. They need a clear interface to see pending requests, understand context, and respond quickly.

**SOP / Agent Authors** — Users who design agent instructions and SOPs. They need a simple tool they can reference in agent prompts ("if you encounter this scenario, call the human_intervene tool to ask for approval") without needing custom development.

**Compliance & Audit Teams** — Stakeholders who require documented evidence that human approval was obtained before certain actions were taken. They need to see that intervene requests were made, who responded, and what decision was provided.

**Business Users Triggering Agents** — Users who launch agent executions and monitor them via the live execution log stream. When an agent triggers an intervene request, they need the popup to appear directly on the execution log page so they can respond without navigating away, then return to watching the logs resume.

---

## User Stories

- As a **platform operator**, I want to see a list of all pending human intervene requests sorted by priority and timestamp, so that I can triage and respond to the most critical requests first.
- As an **approver**, I want to review the full context of an intervene request — including the agent's current output and the reason for intervention — so that I can make an informed decision.
- As an **approver**, I want to approve or reject a request with a single Yes/No action, so that I can quickly gatekeep sensitive operations.
- As a **decision-maker**, I want to select one option from a set of choices presented by the agent, so that the agent can proceed down the correct path based on my guidance.
- As a **subject-matter expert**, I want to provide free-form text input when an agent needs contextual information, so that the agent can continue execution with the information I provided.
- As a **platform operator**, I want to receive a notification (email, Slack, Teams, or in-app) when a new intervene request is created, so that I do not need to poll the dashboard for pending items.
- As an **SOP author**, I want to instruct agents to use the `human_intervene` tool for approval requests, choice selection, or text input within my SOP definitions, so that human-in-the-loop scenarios are handled consistently without custom code.
- As an **auditor**, I want to review the history of all intervene requests for a given agent execution — including who responded, what they chose, and when — so that I can verify compliance with approval policies.
- As a **business user**, I want the agent execution to resume automatically after I respond to an intervene request, so that I do not need to manually restart or re-trigger the workflow.
- As a **business user viewing execution logs**, I want an intervene request popup to appear directly on the execution log streaming page when the agent pauses for input, so that I can respond immediately without navigating away from the live stream — then seamlessly return to watching the logs resume streaming.

---

## Acceptance Criteria

### Intervene Request Creation (Tool)
- Agents can call the `human_intervene` tool with a request reason, an intervention type (approval, choice, text), and type-specific parameters (choices list for choice type, prompt text for text type).
- When an agent calls `human_intervene`, the agent execution pauses immediately and transitions to a "Waiting for Human Intervention" state.
- The tool call returns a unique intervene request ID to the agent so the agent can reference it in logs.
- The request is persisted and immediately visible in the UI with full context (agent name, execution ID, reason, intervention type, current execution state snapshot).

### Intervene Request Review and Response — Approval Type
- Approvers can view all open "approval" type requests with the agent's reason for requesting approval.
- Approvers can approve or reject the request with a single click.
- After approval, the agent execution resumes and the tool call returns "approved: true" to the agent.
- After rejection, the agent execution resumes and the tool call returns "approved: false" to the agent, allowing it to handle the rejection gracefully.

### Intervene Request Review and Response — Choice Type
- Approvers can view choice-type requests with the agent's question and the list of available options.
- Approvers can select exactly one option from the provided choices.
- After selection, the agent execution resumes and the tool call returns the selected option value to the agent.
- The UI prevents submission if no option is selected.

### Intervene Request Review and Response — Text Type
- Approvers can view text-type requests with the agent's prompt for information.
- Approvers can enter free-form text as their response.
- After submission, the agent execution resumes and the tool call returns the text input to the agent.
- The UI enforces a configurable maximum character limit on text responses.

### Execution State Management
- When an intervene request is created, the agent execution enters a "waiting_for_human" state that is clearly distinguishable from "running", "completed", "failed", or "terminated" states.
- The agent session remains active but paused — no further LLM calls or tool calls are made until the human responds.
- When the human responds, the agent execution automatically resumes from the point it paused without requiring manual restart.
- If the agent execution is terminated by an operator while waiting, the pending intervene request is automatically marked as stale/cancelled.

### UI — Dashboard and Request List
- The agent execution dashboard shows a filterable view of all executions waiting for human intervention.
- Pending intervene requests are displayed with agent name, execution ID, request reason, intervention type, timestamp, and elapsed wait time.
- The pending count is visible as a badge or indicator in the navigation so operators can immediately see if action is needed.
- Completed/cancelled requests are also visible in the history with their resolution.

### UI — Response Interface
- The approval response interface shows the agent's reason and a clear Yes/No button pair.
- The choice response interface shows the agent's question and all options as selectable cards or radio buttons.
- The text response interface shows the agent's prompt and a text input area with character count.
- After responding, the UI provides confirmation that the response was delivered and the agent is resuming.
- All response UIs show the execution context (what the agent was doing, recent tool calls, current output) so the operator can make an informed decision.

### UI — Inline Popup on Execution Log Page
- When a user is viewing an agent execution's live log stream and the agent triggers a `human_intervene` request, an intervene popup appears directly on the execution log page without navigating away.
- The live log stream freezes/pauses visually behind the popup (last log entries remain visible) while the user responds.
- The popup shows the intervention type (approval/choice/text) with the agent's reason and full execution context.
- After the user submits their response, the popup closes and the live log stream automatically resumes streaming new log entries from the agent's continued execution.
- If the user dismisses the popup without responding (closes it), it minimizes to a persistent banner at the top of the log page reminding them a response is pending.
- The persistent banner remains visible even if the user scrolls through the log history, with a "Respond" button to re-open the popup.

### Notifications
- When a new intervene request is created, an in-app notification is generated visible in the platform's notification system.
- When a new intervene request is created, a notification is dispatched through configured notification channels (email, Slack, Teams, webhook) as defined in the existing notification integration feature.

### Audit and History
- Every intervene request is logged with: request ID, agent ID, execution ID, intervention type, request timestamp, reason/prompt, operator who responded, response value, response timestamp, and outcome (responded, cancelled, timed out).
- The audit log is visible in the execution details view for each agent run.
- The audit log is accessible to authorized users (platform admins, auditors).

### Error Handling
- If no operator is available to respond within a configurable timeout period, the intervene request can be escalated or the execution can be terminated with a clear timeout reason.
- If the operator does not have permission to respond to intervene requests, the UI shows a clear permission-denied message consistent with the platform's dialog error handling standard.
- If the agent execution has already been terminated or completed, responding to a stale intervene request shows a clear error message.
- The system rejects duplicate requests from the same execution point (no duplicate waiting states).

---

## Out of Scope

- Automated decision-making or AI-driven responses to intervene requests — the entire purpose is human input.
- Bulk or batch response to multiple intervene requests at once — each request requires individual human consideration.
- Scheduling or SLA enforcement for intervene response times beyond basic timeout — operator responsiveness is an organizational concern, not a platform feature.
- Real-time communication channels (chat, voice, video) between operator and agent — responses are asynchronous via the request/response model.
- Machine-initiated overrides of human decisions — human decisions are final.
- Changes to how existing SOPs or agent instructions are authored — SOP authors continue to reference the tool in prompt text.

---

## Dependencies & Constraints

- The tool naming convention `system____human_intervene` must follow the existing platform convention for system tools (four underscores separator, `system` server prefix) as documented in the Agent Execution feature spec.
- The agent execution model must be extended to support a suspend/resume lifecycle state distinct from running, completed, failed, or terminated — this is a new execution state.
- The existing notification integration system must be extended to support intervene request events as a new notification trigger type.
- The existing permission model must be extended to control who can view and respond to intervene requests (viewer vs. responder roles).
- All changes must comply with Parthenon's service segregation rules: agent runtime manages execution state, control center manages permissions and audit logging, communication hub routes tool calls and responses.
- The existing save_result tool implementation pattern serves as the architectural reference for adding new system-level tools.
- Audit logging must integrate with the platform's existing OpenTelemetry instrumentation for trace consistency.
