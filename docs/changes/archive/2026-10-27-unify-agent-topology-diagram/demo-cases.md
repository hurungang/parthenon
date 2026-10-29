# Demo Cases: unify-agent-topology-diagram
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/unify-agent-topology-diagram/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Agent Type preview — unified panel topology canvas > preview shows the unified zoned panel topology canvas with hub bar
- Agent Type preview — unified panel topology canvas > zoom controls work in the preview fullscreen (parity with panel)
- Agent Type preview — unified panel topology canvas > clicking a topology node opens the entity view dialog
- Agent Management Panel — live topology > panel topology renders every equipped node plus the Communication Hub

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Unified topology view in agent preview | Opening an agent preview renders the same zoned panel canvas as the management panel — hub bar, zones, placeholders — instead of the old conversation topology | e2e/tests/agent-type-preview-topology.spec.ts | preview shows the unified zoned panel topology canvas with hub bar |
| 2 | Zoom in/out in preview | User zooms in/out within the preview fullscreen with the same limits and behavior as the management panel | e2e/tests/agent-type-preview-topology.spec.ts | zoom controls work in the preview fullscreen (parity with panel) |
| 3 | Node interaction in preview | Clicking a topology node opens the matching entity view dialog — a real user interaction on the unified canvas | e2e/tests/agent-type-preview-topology.spec.ts | clicking a topology node opens the entity view dialog |
| 4 | Management panel topology unchanged | Regression: panel still renders every equipped node plus the Communication Hub exactly as before the change | e2e/tests/agent-management-panel-topology.spec.ts | panel topology renders every equipped node plus the Communication Hub |

## Selection Notes
- Skipped duplicate/narrow tests: fullscreen auto-fit on the panel (duplicates the preview zoom parity flow), zero-request draft mutations, agent switching, draft-leak, discarded-changes, and typed-agent plan preview tests — each validates a small detail or a flow already covered above.
