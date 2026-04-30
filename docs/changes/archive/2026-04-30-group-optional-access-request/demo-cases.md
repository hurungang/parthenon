# Demo Cases: group-optional-access-request
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/group-optional-access-request/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Group-Optional Access Request Flow > user with no groups sees informational alert in request dialog and can submit with justification only
- Group-Optional Access Request Flow > admin can assign a group and approve a group-less request

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Group-optional submission | User with no group permissions opens the Request Access dialog, sees an informational alert instead of a group selector, fills in a justification, and submits — request created with no group | e2e/tests/access-control.spec.ts | user with no groups sees informational alert in request dialog and can submit with justification only |
| 2 | Admin group-assignment approval | Admin opens the approve dialog for an "Unassigned" request, selects a group from the dropdown, clicks Approve — dialog closes and the API is called with the assigned group_id | e2e/tests/access-control.spec.ts | admin can assign a group and approve a group-less request |
