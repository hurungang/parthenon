# Demo Cases: separate-optimization-from-execution
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/separate-optimization-from-execution/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Optimize gate — blocks then enables the separate Optimize action > a completed run satisfies the gate and Optimize becomes enabled without a reload
- Optimized plan — requires-fix alert and re-optimization journey > optimize → ready plan → fallback marks requires_fix → re-optimize from the alert refreshes the tab
- Agent Plan Mode — explicit-only generation (mocked) > explicit Generate plan authors the plan and it renders without a page reload
- System Config — plan & workflow authoring model > unset authoring model: reminder is visible, and saving a model clears it
- Agent Plan Mode — explicit-only generation (mocked) > conversational agent: no plan-generation affordances, only the explanation

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---|---|---|---|
| 1 | Separate, gated Optimize action | The operator opens an agent in the management panel, sees Run and Optimize as two distinct actions, launches a normal run (no "run with optimization" option anywhere), and watches Optimize unlock on its own the moment the run completes — then triggers the dedicated optimization run from its own dialog. | `e2e/tests/agent-optimize-gate.spec.ts` | a completed run satisfies the gate and Optimize becomes enabled without a reload |
| 2 | Self-healing optimized plan (requires-fix → re-optimize) | From the Agent Type dialog's Optimized Plan tab: optimize produces a fresh ready plan with no alert, a later failed execution flags it "requires a fix" with auto-recorded feedback (badged against manual feedback), and Re-optimize from the alert carries the prior plan + feedback and refreshes the tab to the fixed plan without a reload. | `e2e/tests/agent-optimize-requires-fix.spec.ts` | optimize → ready plan → fallback marks requires_fix → re-optimize from the alert refreshes the tab |
| 3 | Explicit-only implementation-plan generation | Opening an agent's Agent Preview (Plan Preview) tab shows the explicit empty state — no plan exists and none is authored just by opening the surface; the operator clicks Generate plan, exactly one authoring request is sent, and the authored plan steps render in place (the action then reads Regenerate plan) without a page reload. | `e2e/tests/agent-plan-mode.spec.ts` | explicit Generate plan authors the plan and it renders without a page reload |
| 4 | System Config: authoring-model reminder + single tenant setting | The workspace-scoped Plan & Workflow Authoring Model section shows a prominent reminder while no model is selected (plan generation and Optimize are blocked until one is), then a single save of an enabled model persists the choice and clears the reminder immediately. | `e2e/tests/agent-plan-generation.spec.ts` | unset authoring model: reminder is visible, and saving a model clears it |
| 5 | Conversational-agent exclusion (no Plan, no Optimize) | A conversational agent's row exposes no Optimize action and its details dialog offers no Generate plan, Regenerate plan, or empty-state affordance — only the explanation that implementation plans are not available for conversational agents. | `e2e/tests/agent-plan-mode.spec.ts` | conversational agent: no plan-generation affordances, only the explanation |
