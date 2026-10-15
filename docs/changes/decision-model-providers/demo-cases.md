# Demo Cases: decision-model-providers
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/decision-model-providers/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (describe > test, exact titles, use > not ›) -->
- Decision Model Providers (mocked) > settings > navigation and page header show "Decision Model Providers" with no trace of "System One Providers"
- Decision Model Providers (mocked) > settings > admin creates a decision model provider and sees it appear without reload
- Decision Model Providers (mocked) > settings > vendor-level disable cascades and per-model toggles call the availability APIs
- Decision Model Providers (mocked) > decision tools > model selector lists only enabled models and submits the availability id
- Real Backend Integration - Decision Model Providers > multi-provider CRUD, availability cascade, delete blocking, DB persistence

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Terminology rename | Nav label, page header and rendered settings UI use "Decision Model Providers" with zero occurrences of the legacy "System One Providers" string | e2e/tests/system-one-decision-tools.spec.ts | settings > navigation and page header show "Decision Model Providers" with no trace of "System One Providers" |
| 2 | Provider CRUD | Admin fills the create dialog (vendor, display name, endpoint, credential) and the new provider row appears in the table immediately without a page reload, with correct vendor chip and credentials-set indicator | e2e/tests/system-one-decision-tools.spec.ts | settings > admin creates a decision model provider and sees it appear without reload |
| 3 | Model enable/disable + vendor cascade | Flipping the provider-level toggle cascades to all its models and per-model toggles call the availability APIs, mirroring Model Configurations semantics | e2e/tests/system-one-decision-tools.spec.ts | settings > vendor-level disable cascades and per-model toggles call the availability APIs |
| 4 | Per-tool model selection | Decision tool authoring form lists only enabled models across providers and the selection is submitted as the availability reference | e2e/tests/system-one-decision-tools.spec.ts | decision tools > model selector lists only enabled models and submits the availability id |
| 5 | Guardrail/budget | No E2E test exists by design (test-plan Section 4 note): guardrail/budget enforcement on decision evaluations is covered end-to-end at the integration layer, plus the real-backend E2E exercises live CRUD against the actual API + database as a supporting demo | e2e/tests/decision-model-providers-real-backend.spec.ts (real-backend E2E); backend/tests/integration/test_decision_tool_full_journey.py (guardrail/budget) | multi-provider CRUD, availability cascade, delete blocking, DB persistence |

Notes:
- Skipped render-only / duplicate-flow tests: authoring-gate journey, duplicate-name rejection, edit pre-population, delete-and-recreate, disabled-model-selector (overlaps #4), connection-test states, legacy mocked journeys.
- Scenario 5's guardrail/budget behaviour has no Playwright coverage; for a live demo, pair the real-backend E2E with the `test_decision_tool_full_journey.py` integration suite or demonstrate manually per test-plan Section 4.
