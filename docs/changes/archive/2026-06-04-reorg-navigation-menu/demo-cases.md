# Demo Cases: reorg-navigation-menu
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/reorg-navigation-menu/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Agents nav group > collapses and expands nav group on header click

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Sidebar nav group expand/collapse | User clicks the "Agents" group header to collapse the group (hides child items), then clicks again to re-expand them — exercises the new 3-group structure and the primary expand/collapse interaction. | `e2e/tests/agent-navigation.spec.ts` | `collapses and expands nav group on header click` |
