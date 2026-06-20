# PRD: Agent Delegation Visibility & HITL for Non-Conversational Agents

## Epic Overview

Non-conversational (task) agents in Parthenon can already delegate work to other agents using the same `agent____<slug>` tool call mechanism that conversational agents use. However, when task agents delegate, the execution log provides no visibility into what happens during delegation — operators cannot see when delegation starts, when the task agent is waiting, or when delegation completes. Furthermore, task agents cannot pause for human input (Human-in-the-Loop) while waiting for a delegated sub-agent. This change brings delegation transparency and user intervention support to non-conversational agents by reusing the proven delegation status events (`delegating`, `waiting`, `delegation_resumed`) and HITL mechanisms already built into conversational agents, and enforces a one-level delegation depth limit to prevent unbounded delegation chains in automated workflows.

---

## Business Goals

- Give operators live visibility into delegation activity within non-conversational agent execution logs, eliminating the "black box" period where operators cannot tell if automated workflows are progressing or stuck.
- Enable human oversight during task agent delegations by surfacing sub-agent intervention requests as inline popups in the execution log, so critical decisions receive operator review before automated workflows proceed.
- Maintain operational safety by enforcing a strict 1-level delegation depth limit on non-conversational agents, preventing runaway delegation chains.
- Reuse existing conversational-agent delegation and HITL infrastructure to minimise implementation effort and ensure consistent behaviour across both agent modes.
- Ensure every delegation event and intervention decision is recorded in the execution timeline for full auditability.

---

## Users & Personas

- **Platform Operators** — Monitor non-conversational agent execution logs and need to understand delegation progress at a glance, including when delegation starts, when the agent is waiting, and when delegation resumes.
- **SOP Authors** — Design automated workflows that include delegation steps and need the ability to specify where human intervention is required within those workflows.
- **Operations / Support Teams** — Troubleshoot stalled non-conversational agent runs and need delegation status information to identify root causes quickly.
- **Compliance Officers** — Require audit trails showing delegation events and human intervention decisions for automated workflow governance.

---

## User Stories

- As a **platform operator**, I want to see delegation status events (`delegating`, `waiting`, `delegation_resumed`) in the non-conversational agent execution log, so that I can follow the progress of automated workflows that involve agent-to-agent delegation in real time.
- As a **platform operator**, I want a paused execution log with an inline intervention popup when a delegated sub-agent requests human input, so that I can respond to approve, choose, or provide text without leaving the log view.
- As a **platform operator**, I want the execution log to resume automatically after I respond to an intervention request, so that I can continue monitoring without manual refresh.
- As an **SOP author**, I want to include human intervention steps within delegated workflows in non-conversational agents, so that critical decisions in automated processes can receive operator review.
- As an **operations lead**, I want non-conversational agents to enforce a 1-level delegation depth limit, so that automated workflows cannot create unbounded or recursive delegation chains.
- As a **compliance officer**, I want delegation events and intervention decisions recorded in the execution log timeline, so that automated workflow decisions are fully auditable.
- As a **platform operator**, I want the execution log to display agent output formatted according to the agent's output type definition (markdown rendered as rich text, typed JSON shown as structured data, auto shown as raw), so that I can review results in the intended presentation format without switching to a separate view.
- As an **SOP author**, I want non-conversational agents to respect their configured output type when generating results, so that downstream processes receive output in the expected format (markdown documents, structured JSON, or free-form text).

---

## Acceptance Criteria

### Delegation Status Visibility in Execution Log

- When a non-conversational agent initiates delegation to a sub-agent, the execution log displays a `delegating to <agent_type>` event in real time.
- While the non-conversational agent is waiting for the delegated sub-agent to complete, the execution log displays a `waiting` status with a visible indicator showing the delegation is in progress.
- When the delegated sub-agent completes and the non-conversational agent resumes processing, the execution log displays a `delegation_resumed` event.
- All delegation status events appear in the execution log in real time without requiring manual page refresh.
- During active delegation, the live log stream clearly shows that work is in progress rather than appearing stuck or idle.

### User Intervention During Delegation

- When a delegated sub-agent calls for human intervention (`system____human_intervene`), the non-conversational agent execution log pauses and displays an inline intervention popup showing the intervention type (approval, choice, or text) and context.
- The operator can respond directly from the inline popup: approve/reject, choose an option, or enter text.
- After the operator responds, the log stream resumes automatically and the response is recorded as a distinct timeline event.
- If the operator dismisses the popup or navigates away while an intervention request is pending, a persistent banner at the top of the execution log indicates the session is waiting for human input.
- When the operator returns to an execution log with a pending intervention, the pending intervention request is re-surfaced automatically.
- The intervention response (operator identity, decision, and timestamp) is captured in the execution timeline for audit.

### Delegation Depth Enforcement

- A non-conversational agent may delegate to one or more sub-agents.
- A sub-agent delegated by a non-conversational agent cannot itself delegate further. Any attempt to delegate from a delegated sub-agent is blocked.
- When delegation is blocked due to the depth limit, a clear outcome message is recorded in the execution log indicating the depth limit was reached.
- The 1-level delegation depth limit is enforced server-side at the Agent Runtime level and cannot be bypassed from the frontend.

### Exit Conditions for Delegation

- If the delegated sub-agent completes successfully, the `delegation_resumed` event reflects the successful outcome and the parent agent continues execution.
- If the delegated sub-agent times out, the execution log shows a clear, distinct delegation-timeout status (not a generic failure).
- If the delegated sub-agent encounters a runtime error, the execution log shows a clear, distinct delegation-failure status.
- If the operator terminates the parent non-conversational agent session while delegation is in progress, all active delegated sub-agents are terminated and the log reflects the terminated outcome.

### Output Type Respect & Result Display in Execution Log

- When a non-conversational agent is configured with `output_type: markdown`, the agent's system prompt includes an explicit instruction to produce markdown-formatted output.
- When a non-conversational agent is configured with `output_type: typed`, the agent's system prompt includes the output schema and an explicit instruction to produce structured JSON matching the schema.
- When a non-conversational agent is configured with `output_type: auto`, no additional output format instruction is added to the system prompt.
- The execution log viewer includes a "Result" tab that renders the agent output formatted per the output type definition: markdown output rendered as rich text (not raw markdown source), typed JSON displayed as a structured tree/table, auto output displayed as raw text.
- The Result tab is visible immediately when the agent session completes — no additional navigation required.
- The output type definition used by the agent is clearly labelled in the Result tab header for operator awareness.

### Error Handling & Edge Cases

- If the live log stream connection is interrupted and reconnected, previously emitted delegation status events are still visible in the log timeline on reconnect.
- If the operator responds to an intervention request after the sub-agent has already timed out, a clear message is shown indicating the request is no longer valid.
- Guardrail outcomes (termination, observe-only alerts) during delegation are surfaced in the execution log with clear labelling, consistent with existing non-conversational agent behaviour.

---

## Out of Scope

- Changes to conversational agent delegation — conversational delegation visibility and HITL support already exist and are not modified by this change.
- Multi-level delegation for non-conversational agents — depth is strictly limited to 1 level.
- New intervention types beyond the existing approval, choice, and text intervention types (`system____human_intervene`).
- Changes to how sub-agents are created, configured, or launched — the existing agent-to-agent tool call mechanism is reused as-is.
- Changes to the conversation UI — this change only affects the non-conversational execution log view.
- Backend agent runtime execution engine changes — this builds on the existing delegation status event infrastructure and HITL routing mechanisms.

---

## Dependencies & Constraints

- Reuses the existing delegation status event infrastructure (`delegating`, `waiting`, `delegation_resumed`) already built and proven for conversational agents.
- Reuses the existing HITL tool (`system____human_intervene`) and intervention routing mechanisms already built for conversational agents.
- Must comply with service segregation rules (`docs/config.yaml`): delegation routing and intervention routing must go through the Communication Hub; Agent Runtime must not access the database directly for delegation or intervention state.
- Execution log delegation status events must be delivered through the existing live log streaming channel already used for non-conversational agent progress updates.
- Must comply with existing RBAC and permission enforcement for termination actions and intervention responses.
- Delegation depth limit must be enforced at the Agent Runtime level — frontend-only validation is insufficient.
- Must be compatible with existing guardrail policies (timeout, iteration, token budget) for both parent and delegated sub-agent sessions.
