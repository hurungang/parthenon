# Demo Cases: configurable-telemetry-system
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/configurable-telemetry-system/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Telemetry Configuration System > app starts successfully with telemetry enabled
- Telemetry Configuration System > app initializes telemetry from backend config
- Telemetry Configuration System > app starts successfully with telemetry disabled
- Telemetry Configuration System > app degrades gracefully when telemetry config fetch fails

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Telemetry Enabled | App starts without errors when telemetry is fully enabled | e2e/tests/observability.spec.ts | app starts successfully with telemetry enabled |
| 2 | Backend Config | Frontend initializes telemetry from backend-provided config | e2e/tests/observability.spec.ts | app initializes telemetry from backend config |
| 3 | Telemetry Disabled | App works normally when telemetry is disabled in config | e2e/tests/observability.spec.ts | app starts successfully with telemetry disabled |
| 4 | Graceful Degradation | App continues to function when telemetry config API fails | e2e/tests/observability.spec.ts | app degrades gracefully when telemetry config fetch fails |
