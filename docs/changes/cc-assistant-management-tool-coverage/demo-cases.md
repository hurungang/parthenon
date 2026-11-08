# Demo Cases: cc-assistant-management-tool-coverage
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/cc-assistant-management-tool-coverage/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Control Center Assistant — agent-type update journey (mocked WS/API) > preview is presented, approval is sent, and the list reflects the update

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Assistant agent-type update (confirm-before-write) | Administrator sees the canonical old→new preview in the conversation, approves it from the intervention inbox, and the Agent Types list immediately reflects the updated role/input/output configuration. | e2e/tests/control-center-chatbot-agent-type-update.spec.ts | preview is presented, approval is sent, and the list reflects the update |
