# Demo Cases: remove-delegation-depth-cap
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/remove-delegation-depth-cap/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Delegation Depth Configuration (mocked API) > create dialog accepts a depth above 32 and submits it unchanged
- Delegation Depth Configuration (mocked API) > Agent Properties panel accepts a depth above 32 and persists it unchanged
- Execution Log Scoping (mocked API) > parent log shows direct delegation only and the peek hides the child’s own delegation
- Execution Log Scoping (mocked API) > View Execution Logs drills into the child log, which shows the child’s own delegation
- Delegation Depth Status Display (mocked API) > shows the configured maximum for each agent type (3 and 7), not a fixed 1

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Configurable delegation depth (create) | In the Agent Management Panel the operator opens "Execution Guardrails", sees no advertised depth ceiling, types 40 into Max Delegation Depth, saves, and the new agent is created with 40 submitted unchanged. | `e2e/tests/delegation-depth-scoping.spec.ts` | create dialog accepts a depth above 32 and submits it unchanged |
| 2 | Configurable delegation depth (edit) | The operator edits an existing agent in the Agent Properties panel, raises Max Delegation Depth to 40 while other guardrail bounds stay unchanged, saves, and the value is persisted server-side. | `e2e/tests/delegation-depth-scoping.spec.ts` | Agent Properties panel accepts a depth above 32 and persists it unchanged |
| 3 | Parent log scoping and peek | The parent's execution log shows its own work plus the direct delegation lifecycle, and the delegation card peek shows the child's own activity but never the child's onward delegation — no grandchild session is ever fetched. | `e2e/tests/delegation-depth-scoping.spec.ts` | parent log shows direct delegation only and the peek hides the child’s own delegation |
| 4 | Drill-in to the child log | Clicking "View Execution Logs" opens the child's Execution tab where the child's own delegation block, target and delegation tool call are fully visible, and returning to the parent leaves its scoped log unchanged. | `e2e/tests/delegation-depth-scoping.spec.ts` | View Execution Logs drills into the child log, which shows the child’s own delegation |
| 5 | Depth indicator reflects configuration | The Guardrail Usage card in two sessions shows "1 / 3" and "1 / 7" — each matching its agent type's configured maximum instead of a fixed one-level platform value. | `e2e/tests/delegation-depth-scoping.spec.ts` | shows the configured maximum for each agent type (3 and 7), not a fixed 1 |
