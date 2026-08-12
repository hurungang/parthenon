# Demo Cases: add-conversational-agent-intervention
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/add-conversational-agent-intervention/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Human Intervene > submitting approval response sends API call
- Conversation Delegation Visibility > shows delegating label and waiting indicator with fold-expand-collapse snippet behavior
- Real Backend Integration - Conversational Agent Intervention > GET /api/v1/intervene/requests returns data

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Intervention Response with Approval Dialog | User opens intervention dialog, selects Yes, submits approval, and verifies the API call was sent — the complete user decision-making loop | e2e/tests/intervene.spec.ts | Human Intervene > submitting approval response sends API call |
| 2 | Conversation Delegation Status and Waiting UI | Status transitions thinking→delegating→waiting, delegation agent label, collapsible snippet UI with fold/expand/collapse interaction | e2e/tests/conversation-delegation-visibility.spec.ts | Conversation Delegation Visibility > shows delegating label and waiting indicator with fold-expand-collapse snippet behavior |
| 3 | Intervention API Endpoint Integration | Real-backend validation that the intervention requests data endpoint serves correctly against live services with migrations applied | e2e/tests/conversation-intervention.spec.ts | Real Backend Integration - Conversational Agent Intervention > GET /api/v1/intervene/requests returns data |
