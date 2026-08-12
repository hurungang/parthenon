# Demo Cases: harden-agent-guardrails-and-runtime-control-dashboard
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/harden-agent-guardrails-and-runtime-control-dashboard/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Runtime Control Dashboard > shows running sessions and opens execution details dialog
- Runtime Control Dashboard > surfaces observe-only threshold policy events in execution logs
- Runtime Control Dashboard > shows topology selection and opens termination dialog for selected node
- Runtime Control Dashboard > returns recursion_validation_failed contract for run preflight dead-loop checks
- Runtime Control Dashboard > renders vendor → model → guardrail hierarchy in the runtime control panel
- Runtime Control Dashboard > vendor disable cascades the cascade-source badge to all child models

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Runtime visibility and execution drill-down | Operator opens Agent Executions, sees active sessions, and drills into a run from the dashboard detail flow. | e2e/tests/runtime-control-dashboard.spec.ts | Runtime Control Dashboard > shows running sessions and opens execution details dialog |
| 2 | Guardrail policy visibility | Operator reviews execution logs and sees an observe-only guardrail threshold event surfaced as a policy signal rather than a functional failure. | e2e/tests/runtime-control-dashboard.spec.ts | Runtime Control Dashboard > surfaces observe-only threshold policy events in execution logs |
| 3 | Runtime topology and termination control | Operator selects a running node from topology, opens the terminate dialog, submits a reason, and triggers a governed termination request. | e2e/tests/runtime-control-dashboard.spec.ts | Runtime Control Dashboard > shows topology selection and opens termination dialog for selected node |
| 4 | Recursion and dead-loop prevention | Operator attempts to start a risky run and sees the request blocked before execution with a recursion validation failure contract. | e2e/tests/runtime-control-dashboard.spec.ts | Runtime Control Dashboard > returns recursion_validation_failed contract for run preflight dead-loop checks |
| 5 | Model guardrail hierarchy (vendor → model → guardrail) | Operator opens the runtime control panel and sees a vendor row with its enabled models and per-period guardrails, replacing the previous flat list. | e2e/tests/runtime-control-dashboard.spec.ts | Runtime Control Dashboard > renders vendor → model → guardrail hierarchy in the runtime control panel |
| 6 | Vendor disable cascade | Operator disables a vendor and immediately sees the cascade-source badge on every model underneath; pre-execution availability check returns `vendor_disabled` for those models. | e2e/tests/runtime-control-dashboard.spec.ts | Runtime Control Dashboard > vendor disable cascades the cascade-source badge to all child models |
