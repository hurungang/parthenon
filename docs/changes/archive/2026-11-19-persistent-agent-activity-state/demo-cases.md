# Demo Cases: persistent-agent-activity-state
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/persistent-agent-activity-state/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Conversational Activity State (Mocked) > chat surface renders status bubbles for the full activity lifecycle
- Conversational Activity State (Mocked) > reload hydration restores the persisted waiting status

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Live activity status | The chat processing bubble tracks the assistant through "using tool" → "waiting for your input" → finished, with no blank gap before the intervention prompt and no stuck spinner after completion. | `e2e/tests/conversation-activity-state.spec.ts` | chat surface renders status bubbles for the full activity lifecycle |
| 2 | Resume / reconnect hydration | Reloading the chat mid-turn immediately restores the persisted "waiting for your input" status instead of showing an empty window. | `e2e/tests/conversation-activity-state.spec.ts` | reload hydration restores the persisted waiting status |
