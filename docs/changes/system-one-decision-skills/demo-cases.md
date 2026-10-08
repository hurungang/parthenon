# Demo Cases: system-one-decision-skills
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/system-one-decision-skills/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- System One Decision Tools (mocked) > provider config journey enables the decision tool authoring gate
- System One Decision Tools (mocked) > round-2 form journey: data types → mapping properties → placeholders → AI generate → save
- System One Decision Tools (mocked) > duplicate tool name shows a structured error and keeps the dialog open
- System One Decision Tools (mocked) > decision results API contract: persisted result keyed to the tool

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | System One provider config | Admin saves the TypeSafe API key via the dialog (preset read-only base URL); the decision-tool authoring gate opens once a model is configured | e2e/tests/system-one-decision-tools.spec.ts | provider config journey enables the decision tool authoring gate |
| 2 | Decision tool authoring (data types + AI) | Guided form: select input/output Agent Data Types (with View dialogs) → state mapping properties auto-populate → auto-detect placeholders → Generate-with-AI fills questions → save as `decision____<name>` | e2e/tests/system-one-decision-tools.spec.ts | round-2 form journey: data types → mapping properties → placeholders → AI generate → save |
| 3 | Tenant-contained naming | Defining a second tool with the same name in one tenant shows a structured conflict error and keeps the dialog open (names unique per tenant, reusable across tenants) | e2e/tests/system-one-decision-tools.spec.ts | duplicate tool name shows a structured error and keeps the dialog open |
| 4 | Decision results | Execution result is keyed to the decision tool with typed answers, probabilities, confidence, and gate outcome | e2e/tests/system-one-decision-tools.spec.ts | decision results API contract: persisted result keyed to the tool |
