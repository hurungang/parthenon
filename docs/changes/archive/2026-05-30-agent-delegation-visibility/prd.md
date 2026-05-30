# Agent Delegation Visibility PRD

## Epic Overview
When Parthenon processes work through conversational and non-conversational agent flows, users can experience uncertainty when progress is not visible. This epic introduces clear, live execution visibility across both contexts: real-time progress for non-conversation agent runs and concise delegation progress cues in chat with expandable execution details. The business value is higher trust, faster issue awareness, and better perceived reliability for enterprise multi-agent operations.

## Business Goals
- Reduce user-reported confusion during agent execution and delegation flows by at least 40% within one release cycle.
- Improve user trust score for execution transparency by at least 20% in post-release feedback.
- Decrease repeated manual status-check behavior during running agent work by at least 30%.
- Increase successful completion rate of longer delegated conversations by at least 15% through clearer in-progress guidance.
- Increase operator ability to identify stalled non-conversation runs in real time, measured by a 25% reduction in delayed intervention.

## Users & Personas
- Business Operator: Runs operational workflows and needs immediate confirmation that the system is actively working.
- Platform Administrator: Supports users during long-running conversations and needs clear user-facing status to distinguish progress from delay.
- Process Owner: Depends on reliable multi-agent outcomes and needs transparent status updates across both chat and non-chat execution contexts.

## User Stories
- As a business operator, I want to see a thinking indicator while the primary conversational agent is processing, so that I know my request is being handled.
- As a business operator, I want the chat to show "Delegating to agent <agent_type>" when delegation starts, so that I know which agent is taking over the delegated step.
- As a business operator, I want a waiting indicator during delegated execution, so that I know the conversation is still active.
- As a business operator, I want delegation execution log snippets shown in chat in a compact folded state, so that I can expand details only when I need deeper visibility.
- As a platform administrator, I want non-conversation agent execution progress to update live while a run is in progress, so that I can detect stalls and intervene quickly.
- As a platform administrator, I want a clear timeout or failure state in the chat flow, so that stalled delegations are visible to users without ambiguity.
- As a process owner, I want clear completion feedback after delegation returns, so that users can confidently continue the conversation.

## Acceptance Criteria
- While the primary conversational agent is processing, the front chatbox shows a visible thinking indicator.
- When delegation starts, the chat displays the label exactly in the format: "Delegating to agent <agent_type>".
- After delegation begins, the chat shows a waiting indicator until a delegated response is received or a timeout occurs.
- In delegated chat flows, the delegation label and active waiting indicator appear before the first delegated agent reply and remain visible during the wait period.
- During non-conversation agent runs, users can observe live execution progress updates without needing to manually refresh the view.
- In chat, delegation execution log snippets are presented folded by default and can be expanded by users on demand.
- Folded delegation snippets in chat provide enough context to confirm progress at a glance while keeping the conversation readable.
- If delegated execution times out or fails, users see a clear final status state and are not left in an indefinite waiting state.
- Delegation-related status messages and execution visibility cues are understandable to non-technical users and consistently visible where relevant.
- The required user experience is limited to execution visibility and user-facing progress communication and does not require altering core delegation or runtime business logic.

## Out of Scope
- Redesign of the full conversation interface beyond simple status indicators.
- Redesign of non-conversation monitoring surfaces beyond adding live progress visibility.
- Changes to agent authorization, role assignment, identity, or security model.
- Changes to delegation decisioning, runtime orchestration behavior, or core business logic.
- Engineering-only diagnostic panels, technical trace views, or implementation-level observability additions beyond user-facing progress visibility.
- Historical analytics or reporting dashboards for delegation performance.

## Dependencies & Constraints
- The status experience must align with existing Parthenon conversational patterns and language conventions.
- User-facing status text must be clear, concise, and understandable for non-technical stakeholders.
- Delegation status and non-conversation progress updates must accurately reflect user-visible execution state to maintain trust and reduce ambiguity.
- Chat execution snippets must default to a folded presentation so additional detail is available without overwhelming core conversation readability.
- Delivery must focus on simple UX signaling and execution visibility (thinking, delegating, waiting, live progress, timeout/failure outcome) without expanding scope into runtime redesign.
