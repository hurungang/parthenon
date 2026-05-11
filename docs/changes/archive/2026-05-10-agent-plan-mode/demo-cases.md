# Demo Cases: agent-plan-mode
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/agent-plan-mode/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Agent Plan Mode — Mocked > Create agent type with plan: modal opens with steps and diagram after save
- Agent Plan Mode — Mocked > Dismiss plan modal: modal closes and agent type row appears in table
- Agent Plan Mode — Mocked > Update agent type: PlanPreviewModal opens with updated plan on save
- Agent Plan Mode — Mocked > Failed plan: modal opens with error message when generation_status is failed
- Real Backend Integration — Agent Plan Mode > POST /api/v1/agents/types returns plan field in response

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Create agent type → plan modal | User creates an agent type, saves, and the PlanPreviewModal opens automatically showing all three generated plan steps | e2e/tests/agent-plan-mode.spec.ts | Create agent type with plan: modal opens with steps and diagram after save |
| 2 | Dismiss plan modal → table refresh | User closes the plan modal and the agent type row immediately appears in the management table without a page reload | e2e/tests/agent-plan-mode.spec.ts | Dismiss plan modal: modal closes and agent type row appears in table |
| 3 | Edit agent type → plan regeneration | User edits an existing agent type, saves, and the PlanPreviewModal opens with an updated plan reflecting the changes | e2e/tests/agent-plan-mode.spec.ts | Update agent type: PlanPreviewModal opens with updated plan on save |
| 4 | Failed plan generation → error state | When the LLM is unavailable the plan modal still opens but shows the generation error message instead of plan steps | e2e/tests/agent-plan-mode.spec.ts | Failed plan: modal opens with error message when generation_status is failed |
| 5 | Real backend: plan field + cascade delete | The real backend returns a `plan` field on POST and fully cascades the plan record when the agent type is deleted | e2e/tests/agent-plan-mode.spec.ts | POST /api/v1/agents/types returns plan field in response |
