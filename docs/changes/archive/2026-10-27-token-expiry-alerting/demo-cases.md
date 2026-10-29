# Demo Cases: token-expiry-alerting
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/token-expiry-alerting/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
- Token expiry — dashboard alerts & remediation > warnings disappear after remediation (refetch returns healthy)
- Token expiry — execution preflight > expired token (including a subagent) BLOCKS execution with a named identity
- Token expiry — execution preflight > expiring token (≤7 days) WARNS but execution PROCEEDS
- Token expiry — topology badges > expired identity renders an error badge on its container

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Dashboard alerts + remediation routing | Full remediation round-trip: expired/expiring warnings appear on the dashboard, user click-throughs to the remediation page, refresh/re-auth succeeds, and warnings clear on refetch | e2e/tests/token-expiry-dashboard-remediation.spec.ts | warnings disappear after remediation (refetch returns healthy) |
| 2 | Execution preflight — blocking | Expired token (including on a subagent) blocks execution before start with a user-facing message naming the affected identity | e2e/tests/token-expiry-execution-preflight.spec.ts | expired token (including a subagent) BLOCKS execution with a named identity |
| 3 | Execution preflight — warn path | Expiring token (≤7 days) surfaces a warning but does not block — execution proceeds | e2e/tests/token-expiry-execution-preflight.spec.ts | expiring token (≤7 days) WARNS but execution PROCEEDS |
| 4 | Topology badges | Expired token renders an error badge on the affected container in the live topology view | e2e/tests/token-expiry-topology-badges.spec.ts | expired identity renders an error badge on its container |
