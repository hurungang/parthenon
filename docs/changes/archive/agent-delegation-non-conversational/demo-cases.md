# Demo Cases: agent-delegation-non-conversational
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/<name>/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
- Delegation Lifecycle Visibility (mocked API) > renders multiple delegation events in a single view
- Conversation Delegation Visibility > shows delegating label and waiting indicator with fold-expand-collapse snippet behavior

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Delegation Lifecycle Visibility | User opens a completed non-conversational execution log and sees the full delegation lifecycle: a `delegation_started` event when the parent delegates to a sub-agent followed by a `delegation_resumed` event when the sub-agent completes — all rendered in the Delegation Timeline without manual refresh | e2e/tests/delegation-lifecycle-visibility.spec.ts | renders multiple delegation events in a single view |
| 2 | Conversational Delegation (Regression) | User opens a conversational agent session and sees the `Delegating to agent` label, a `Waiting for delegated response…` indicator, and fold/expand snippet behaviour — confirming that the existing conversational delegation UI is unbroken by the non-conversational changes | e2e/tests/conversation-delegation-visibility.spec.ts | shows delegating label and waiting indicator with fold-expand-collapse snippet behavior |
