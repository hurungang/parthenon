# Demo Cases: api-key-mcp-hub
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/api-key-mcp-hub/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- API Key Management - Mocked Admin CRUD > displays status chips
- API Key Management - Create Key Flow > can select identity and role then create
- API Key Management - Revoke Key Flow > revoke dialog shows key name and warning
- API Key Management - Filtering > status filter has all/active/revoked options

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | API Key List View | Admin views the key list with active/revoked status chips — shows both key states in a single glance with colored indicators | api-key-management.spec.ts | API Key Management - Mocked Admin CRUD > displays status chips |
| 2 | Create API Key | Full two-step create flow: fill in name, select identity + role from dropdowns, submit form, transition to step 2 showing the one-time key and save warning | api-key-management.spec.ts | API Key Management - Create Key Flow > can select identity and role then create |
| 3 | Revoke API Key | Revoke confirmation dialog showing key name, identity/role binding, warning message, and description — complete pre-revoke verification UI | api-key-management.spec.ts | API Key Management - Revoke Key Flow > revoke dialog shows key name and warning |
| 4 | Status Filtering | Status filter dropdown interaction opening the select and revealing all/active/revoked filter options | api-key-management.spec.ts | API Key Management - Filtering > status filter has all/active/revoked options |
