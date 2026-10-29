# Demo Cases: sandboxed-scripting-follow-ups
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/sandboxed-scripting-follow-ups/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- MCP Session re-auth state > shows a "Needs re-authentication" status for a session flagged requires_reauth
- Agent Type Scripts tab — agent-owned script governance > operator retires a version from the Scripts tab

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | MCP session re-auth state | A session whose OAuth refresh failed unrecoverably shows a "Needs re-authentication" status with the stored reason, instead of silently deactivating | e2e/tests/mcp-hub.spec.ts | shows a "Needs re-authentication" status for a session flagged requires_reauth |
| 2 | Script retire (Optimized Plan lifecycle) | The operator retires a script version from the Scripts tab — the retire flow that now has a clear empty state | e2e/tests/agent-type-scripts-tab.spec.ts | operator retires a version from the Scripts tab |

> **Note:** The "nothing to retire" empty state is covered at the component level
> (`frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx`) — there is no dedicated E2E spec
> for it because the optimized-plan tab lives inside a nested agent-type dialog flow.
