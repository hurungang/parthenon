# Specification Delta: Agent Delegation Visibility & HITL for Non-Conversational Agents

## Affected Spec Areas

| Spec Area | Description of Change |
|-----------|----------------------|
| Agent Execution (`docs/master/product/features/agent-execution.md`) | Add delegation status visibility for non-conversational agents; extend HITL support to cover non-conversational delegation scenarios; add 1-level delegation depth enforcement as a new guardrail; add output type prompt injection so non-conversational agents respect their configured output type |
| Agent Session Logs (`docs/master/product/features/agent-session-logs.md`) | Add delegation status events (`delegating`, `waiting`, `delegation_resumed`) to the list of live progress updates visible in non-conversational execution logs; extend inline intervention popup behaviour to cover delegation sub-agent requests; add output-type-aware Result tab rendering in the execution log viewer |
| Conversation Management (`docs/master/product/features/conversation-management.md`) | Cross-reference update — note that delegation visibility and HITL intervention now apply to both conversational and non-conversational agent modes, not conversational only |
| Agent Gateway (`docs/master/product/features/agent-gateway.md`) | Cross-reference update — note that intervention request routing now serves non-conversational delegated sub-agents in addition to conversational delegated sub-agents |
| Agent Configuration (`docs/master/product/features/agent-configuration.md`) | Add note that `output_type` is now actively enforced via system prompt injection for non-conversational agents, not just stored as metadata |

---

## New Capabilities

1. **Delegation Status Events in Non-Conversational Execution Logs** — When a non-conversational (task) agent delegates to a sub-agent, the execution log now displays live delegation status events: `delegating to <agent_type>` when delegation begins, `waiting` while the sub-agent executes, and `delegation_resumed` when the parent agent resumes processing. These events are delivered through the existing live log streaming channel and require no manual page refresh.

2. **Human-in-the-Loop During Non-Conversational Delegation** — When a sub-agent delegated by a non-conversational agent calls `system____human_intervene`, the intervention request is surfaced as an inline popup in the parent agent's execution log. The operator can respond (approve/reject, choose an option, or enter text) directly from the log view. After responding, the log stream resumes automatically and the intervention is recorded as a timeline event. A persistent banner indicates pending intervention if the popup is dismissed.

3. **1-Level Delegation Depth Enforcement** — Non-conversational agents may delegate to sub-agents, but those sub-agents are blocked from further delegation. Any delegation attempt beyond one level is rejected and recorded as a clear outcome event in the execution log. This limit is enforced server-side at the Agent Runtime level.

4. **Delegation Exit Condition Visibility** — The execution log displays distinct, clearly labelled status events for each delegation exit condition: successful completion, timeout, runtime failure, and operator-initiated termination of the parent session (which cascades to all active delegated sub-agents).

5. **Output Type Prompt Injection** — Non-conversational agents now automatically receive output format instructions in their system prompt based on their configured `output_type`:
   - `markdown`: system prompt includes instruction to produce markdown-formatted output
   - `typed`: system prompt includes the agent's `output_schema` and an instruction to produce structured JSON matching the schema
   - `auto`: no additional output format guidance added (agent decides format freely)

6. **Output-Type-Aware Result Tab** — The execution log viewer's Result tab now renders agent output formatted per the `output_type` definition: markdown rendered as rich formatted text (HTML), typed JSON displayed as a structured tree view, and auto displayed as raw text. The Result tab label includes the output type for operator awareness.

---

## Modified Capabilities

| Capability | Before | After |
|------------|--------|-------|
| Non-conversational delegation visibility | No delegation status visible in execution log; the delegation period is a black box with no progress indication | Live delegation status events (`delegating`, `waiting`, `delegation_resumed`) appear in the execution log in real time via the existing live log streaming channel |
| Human-in-the-Loop during non-conversational delegation | Not supported; sub-agent intervention requests are not surfaced to operators and appear as indefinite stalls | Sub-agent intervention requests surface as inline popups in the execution log; operator can respond to approve, choose, or provide text; response is recorded in the timeline |
| Delegation depth for non-conversational agents | No explicit limit enforced; delegation depth is unbounded | Hard limit of 1 level enforced server-side; sub-agents of non-conversational agents cannot further delegate; blocked attempts produce clear log outcomes |
| Intervention request routing scope | Intervention requests are routed only for conversational delegated sub-agents back to the parent conversation UI | Intervention requests are routed for both conversational and non-conversational delegated sub-agents — conversational requests go to the conversation UI, non-conversational requests go to the execution log view |
| Output type enforcement | `AgentType.output_type` is stored as metadata but not injected into the agent's system prompt; agents may not follow the configured output format | `output_type` is actively injected into the system prompt for non-conversational agents, instructing the LLM to produce output in the configured format |
| Execution log result display | Result tab renders all output as raw JSON `<pre>` block (unless `output_data.markdown` is a string, in which case it renders as HTML without consulting `output_type`) | Result tab renders output formatted per the agent's `output_type` definition: markdown → rendered rich text, typed → structured JSON view, auto → raw text |

---

## Removed Capabilities

None. All existing delegation and HITL behaviour for conversational agents is preserved unchanged. Non-conversational agents gain new capabilities without removing any existing functionality.

---

## Spec Update Instructions

### 1. `docs/master/product/features/agent-execution.md`

- **Human-in-the-Loop Intervention section**: Add a new sub-section "Intervention in Non-Conversational Delegation" describing how delegated sub-agent intervention requests surface as inline popups in the non-conversational execution log, mirroring the existing conversational pattern but targeting the execution log view instead of the conversation UI.
- **Execution Guardrails and Cost Controls section**: Add a bullet point for the new 1-level delegation depth limit enforcement: *"Non-conversational agent delegation is limited to 1 level — delegated sub-agents cannot further delegate; attempts are blocked and recorded in execution logs."*
- **Acceptance Criteria section**: Add criteria for: delegation status events appearing in non-conversational execution logs; inline intervention popups during non-conversational delegation; 1-level depth limit enforcement; distinct delegation exit condition statuses.
- **User Stories section**: Add a user story for platform operators around delegation visibility in non-conversational execution logs.

### 2. `docs/master/product/features/agent-session-logs.md`

- **Live Progress Updates**: Update the description of live progress updates to explicitly include delegation status events (`delegating`, `waiting`, `delegation_resumed`) as part of the real-time progress stream for non-conversational agents.
- **Inline Intervention Popup**: Extend the existing intervention popup acceptance criteria to cover the non-conversational delegation scenario — when a sub-agent requests intervention, the popup appears in the parent agent's execution log with full context.
- **Acceptance Criteria section**: Add criteria for: delegation status events appearing live in the non-conversational log stream; intervention popup surfacing during delegation; persistent waiting banner when popup is dismissed; automatic re-surfacing of pending intervention on reconnect.

### 3. `docs/master/product/features/conversation-management.md`

- **Delegation Visibility Cues (Key Concepts)**: Add a note clarifying that delegation status events (`delegating`, `waiting`, `delegation_resumed`) and HITL intervention support are now available in both conversational and non-conversational agent modes. The conversation UI handles conversational delegation; the execution log view handles non-conversational delegation.
- **Acceptance Criteria section**: No changes needed — all existing conversational acceptance criteria remain valid. Note for future reviewers that the conversational delegation behaviour is unchanged.

### 4. `docs/master/product/features/agent-gateway.md`

- **What It Does section**: Update the intervention routing bullet point from "Routes delegated intervention requests from Agent Runtime back to parent conversational sessions" to "Routes delegated intervention requests from Agent Runtime back to parent sessions — to the conversation UI for conversational agents, and to the execution log view for non-conversational agents."
- **Key Concepts section**: Add "Delegation Depth Limit" as a new concept noting that non-conversational agent delegation is limited to 1 level.

### 5. `docs/master/product/features/agent-configuration.md`

- **Output Type section**: Update description to reflect that `output_type` is now actively enforced for non-conversational agents via system prompt injection, not just stored as passive metadata.
- Add acceptance criteria for output type prompt injection behaviour (markdown → markdown instruction, typed → schema instruction, auto → no extra instruction).
- Add acceptance criteria for output-type-aware Result tab rendering in the execution log viewer.

### 6. Master Tech Spec Updates (`docs/master/technology/modules/agent-runtime/tech-spec.md`)

- Add delegation depth enforcement as a new guardrail check in the execution flow.
- Note that existing delegation status event emission logic (previously conversational-only) is now invoked for non-conversational delegation as well.
- Note that existing HITL intervention routing logic now handles non-conversational delegation scenarios in addition to conversational ones.
- Add output type prompt injection as a new step in the system prompt assembly for non-conversational agents.
- Note that the Result tab rendering now consults `output_type` for display format selection.
