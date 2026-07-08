# Demo Cases: refine-oidc-integration
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/refine-oidc-integration/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
- Login Page Rendering > shows both OIDC and super admin options
- OIDC Callback Flow > callback with valid code exchanges token and lands on /dashboard
- Setup Wizard — full user journey > bundled Keycloak happy path completes and shows success
- System Config Navigation > system config page shows tabs

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Login Page State Rendering | Login page adapts to show both OIDC login button and super admin credential form when both are configured | oidc-login-flows.spec.ts | shows both OIDC and super admin options |
| 2 | OIDC Authorization Code Flow | User returns from identity provider with an auth code, token is exchanged, and dashboard loads | auth-required/oidc-callback.spec.ts | callback with valid code exchanges token and lands on /dashboard |
| 3 | Setup Wizard | Operator completes first-run setup via bundled Keycloak flow, fills config form, and sees success confirmation | setup-wizard.spec.ts | bundled Keycloak happy path completes and shows success |
| 4 | System Config Identity Management | Super admin navigates to system config page, identity provider tabs render with user/agent provider sections | oidc-login-flows.spec.ts | system config page shows tabs |
