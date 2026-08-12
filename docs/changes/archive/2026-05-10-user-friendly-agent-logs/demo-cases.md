# Demo Cases: user-friendly-agent-logs
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/user-friendly-agent-logs/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Agent Log Viewer > Summary panel displays identity and role from system instruction
- Agent Log Viewer > Expand working steps section reveals step rows
- Agent Log Viewer > Expand individual step detail block
- Agent Log Viewer > Toggle to raw mode shows monospace raw log block
- Agent Log Viewer > Raw mode copy button is visible

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Summary panel | Agent identity, role, and model parsed from system instruction are displayed to the user on the session page | e2e/tests/agent-logs.spec.ts | Summary panel displays identity and role from system instruction |
| 2 | Expand working steps | Clicking "Show N Working Steps" expands the collapsible section and reveals each LLM/tool step as a readable row | e2e/tests/agent-logs.spec.ts | Expand working steps section reveals step rows |
| 3 | Individual step detail | Clicking the expand icon on a tool call step reveals its structured input/output detail block | e2e/tests/agent-logs.spec.ts | Expand individual step detail block |
| 4 | Raw mode toggle | Toggling "Raw Output" replaces the friendly panels with a monospace pre-block containing the full timestamped log | e2e/tests/agent-logs.spec.ts | Toggle to raw mode shows monospace raw log block |
| 5 | Copy raw logs | In raw mode, a "Copy Raw Log" button is visible so the user can copy the full log to clipboard | e2e/tests/agent-logs.spec.ts | Raw mode copy button is visible |
