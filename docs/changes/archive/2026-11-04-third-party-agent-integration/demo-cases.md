# Demo Cases: third-party-agent-integration
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/third-party-agent-integration/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Agent Clients - Mocked Management > lists clients with agent type and credential type
- Agent Clients - Mocked Management > shows the publishable soft warning in the create dialog
- Agent Clients - Mocked Management > creates a client and shows the credential once

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Client list | A tenant's clients with their bound agent type and credential type (secret vs publishable) | e2e/tests/agent-clients.spec.ts | lists clients with agent type and credential type |
| 2 | Publishable soft warning | Creating a publishable client surfaces the "exposes this agent type publicly" warning | e2e/tests/agent-clients.spec.ts | shows the publishable soft warning in the create dialog |
| 3 | Create + credential once | Creating a client and displaying the clear-text credential exactly once | e2e/tests/agent-clients.spec.ts | creates a client and shows the credential once |
