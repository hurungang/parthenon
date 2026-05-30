# Demo Cases: agent-delegation-visibility
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/agent-delegation-visibility/demo-cases.md -->

## Grep Patterns
- Conversation Delegation Visibility > shows delegating label and waiting indicator with fold-expand-collapse snippet behavior
- Conversation Delegation Visibility > shows timeout_or_failed terminal status in chat
- Agent Live Logs Stream > uses live stream endpoint for running non-conversation session and shows live-stream hint
- Agent Log Viewer > Agent Working Steps section is collapsed by default

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Delegation handoff visibility | In chat, users see the normalized delegation label, active waiting indicator, and fold-expand-collapse snippet interaction during delegated execution | e2e/tests/conversation-delegation-visibility.spec.ts | shows delegating label and waiting indicator with fold-expand-collapse snippet behavior |
| 2 | Terminal timeout/failure state | Delegated runs that time out or fail transition to a clear terminal status in the same chat view | e2e/tests/conversation-delegation-visibility.spec.ts | shows timeout_or_failed terminal status in chat |
| 3 | Live non-conversation progress stream | Running non-conversation sessions use the stream endpoint and display a live-stream progress hint without manual refresh | e2e/tests/agent-live-logs-stream.spec.ts | uses live stream endpoint for running non-conversation session and shows live-stream hint |
| 4 | Collapsed-by-default readability | Execution progress remains readable by default because working steps start collapsed until the user expands them | e2e/tests/agent-logs.spec.ts | Agent Working Steps section is collapsed by default |
