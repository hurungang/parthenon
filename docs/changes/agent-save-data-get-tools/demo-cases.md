# Demo Cases: agent-save-data-get-tools
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/agent-save-data-get-tools/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- agent-save-data-get-tools > agent context does not expose save_result
- agent-save-data-get-tools > save_data stores multiple records per session
- agent-save-data-get-tools > get_data requires at least one filter
- agent-save-data-get-tools > get_output returns output history by date range

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | System tool rename and exposure | User-visible tool context includes save_data/get_data/get_output and excludes legacy save_result. | e2e/tests/agent-save-data-get-tools.spec.ts | agent context does not expose save_result |
| 2 | Intermediate data persistence | A single session can save multiple named records, demonstrating repeatable data capture during a run. | e2e/tests/agent-save-data-get-tools.spec.ts | save_data stores multiple records per session |
| 3 | Data query guardrail validation | Query without filters is rejected, showing protection against unbounded retrieval requests. | e2e/tests/agent-save-data-get-tools.spec.ts | get_data requires at least one filter |
| 4 | Output history retrieval | Output history is returned for a requested date window, showing timeline-based retrieval behavior. | e2e/tests/agent-save-data-get-tools.spec.ts | get_output returns output history by date range |
