# Demo Cases: passthrough-sessions
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/passthrough-sessions/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Passthrough Sessions — Mocked > passthrough session chip displayed in session table
- Passthrough Sessions — Mocked > creating passthrough session excludes credentials from payload
- Passthrough Sessions — Mocked > passthrough session auth_type value is correct in API response
- Real Backend Integration — Passthrough Sessions > passthrough session creation with credentials is rejected by real backend — AC-1 validation

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Passthrough chip in session table | User sees a "Passthrough" chip badge in the session list, confirming the auth type is displayed correctly | passthrough-sessions.spec.ts | passthrough session chip displayed in session table |
| 2 | Admin creates passthrough session | Admin selects passthrough auth type, credential fields are hidden, and the submitted payload contains no credentials | passthrough-sessions.spec.ts | creating passthrough session excludes credentials from payload |
| 3 | Passthrough API contract | API response for a passthrough session carries the correct `auth_type`, `is_active`, and connection test values — no encrypted credentials in the payload | passthrough-sessions.spec.ts | passthrough session auth_type value is correct in API response |
| 4 | Real backend rejects credentials on passthrough | Live backend enforces the constraint: submitting credentials with a passthrough session returns 422, never 500 | passthrough-sessions.spec.ts | passthrough session creation with credentials is rejected by real backend — AC-1 validation |
