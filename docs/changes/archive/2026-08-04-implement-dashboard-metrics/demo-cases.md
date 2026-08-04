# Demo Cases: implement-dashboard-metrics
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/implement-dashboard-metrics/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Dashboard Operational Metrics > operational metric cards are visible
- Dashboard Operational Metrics > time-sensitive metrics section is visible
- Dashboard Operational Metrics > date range picker preset buttons are visible

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Operational metrics | Section heading and all 7 snapshot stat cards render with mock data | dashboard.spec.ts | Dashboard Operational Metrics > operational metric cards are visible |
| 2 | Time-sensitive metrics | Date-range-filtered metrics section with 3 time-sensitive cards | dashboard.spec.ts | Dashboard Operational Metrics > time-sensitive metrics section is visible |
| 3 | Date range presets | Last Hour, Last 24h, and Last 7d preset shortcut buttons render correctly | dashboard.spec.ts | Dashboard Operational Metrics > date range picker preset buttons are visible |
