# Demo Cases: conversation-agent-sessions
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/conversation-agent-sessions/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Conversation Sessions (Mocked) > Sessions tab shows session list
- Conversation Sessions (Mocked) > Resume navigates to chat page with session history
- Conversation Sessions (Mocked) > End session shows confirmation dialog
- Real Backend Integration — Conversation Sessions > POST /conversations creates session; POST /end closes it

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Sessions tab | Opens the agent detail dialog for a conversation-type agent, switches to the Sessions tab, and verifies the session list renders with a titled entry | conversation-sessions.spec.ts | Sessions tab shows session list |
| 2 | Session resume | Navigates directly to the chat page with a `sessionId` route param and verifies the full prior turn history (user + agent messages) is restored | conversation-sessions.spec.ts | Resume navigates to chat page with session history |
| 3 | End session | Opens the Sessions tab, clicks the End Session action button, and confirms the End Conversation Session confirmation dialog appears | conversation-sessions.spec.ts | End session shows confirmation dialog |
| 4 | Backend lifecycle | Calls the real backend (no mocks) to create a session via `POST /conversations`, then ends it via `POST /end`, and asserts the status transitions from `active` to `closed` | conversation-sessions.spec.ts | POST /conversations creates session; POST /end closes it |
