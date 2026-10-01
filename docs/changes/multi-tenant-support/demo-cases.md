# Demo Cases: multi-tenant-support
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/multi-tenant-support/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Single-Tenant Regression (switch OFF) > CS-01: /platform/* routes are absent — navigating there lands on dashboard
- Platform Settings Toggle (mocked) > toggle requires the typed ENABLE confirmation and reflects server state
- Platform Tenant Management Lifecycle (mocked) > CS-07/CS-09: create → edit → suspend → resume → delete → slug reusable, all without page reload
- Multi-org picker — one session = one tenant > multi-org user sees the picker; single selection binds the session
- Platform Audit View (mocked) > lists events with tenant attribution and exposes filters; no business data
- Self-Serve Sign-Up (mocked) > CS-26: full journey — entry link → wizard → lands in onboarding as root
- Quota Enforcement (mocked) > CS-35/CS-41: blocked invite shows tier/limit/usage/upgrade; unblocked once the license is raised
- Quota Enforcement (mocked) > CS-34: the tenant usage panel mirrors tier and limits
<!-- Gap: root-only alias editing and platform license assignment have no E2E specs yet — no test can be added for them. -->

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Single-tenant regression (switch off = unchanged) | Deep-linking to `/platform/*` with the tenancy switch off silently lands on the dashboard — the pre-change single-tenant product is untouched | e2e/tests/single-tenant-regression.spec.ts | CS-01: /platform/* routes are absent — navigating there lands on dashboard |
| 2 | Platform tenancy toggle/adoption | Enabling multi-tenancy demands the typed ENABLE confirmation (button stays disabled on wrong input) and reflects server state immediately | e2e/tests/multi-tenant-lifecycle.spec.ts | toggle requires the typed ENABLE confirmation and reflects server state |
| 3 | Tenant lifecycle (create/suspend/delete) | Platform console full CRUD: create → edit → suspend → resume → typed-confirmation delete → address reusable again, parent table refreshing without page reload | e2e/tests/multi-tenant-lifecycle.spec.ts | CS-07/CS-09: create → edit → suspend → resume → delete → slug reusable, all without page reload |
| 4 | Tenant-aware sign-in (tenant picker) | Multi-org user picks an organization at sign-in with roles shown; the session binds to that tenant and survives reload without re-prompting | e2e/tests/multi-tenant-login-flows.spec.ts | multi-org user sees the picker; single selection binds the session |
| 5 | Platform audit | Cross-tenant audit events listed with tenant attribution (including platform-sentinel events), filters exposed, and no tenant business data rendered | e2e/tests/multi-tenant-lifecycle.spec.ts | lists events with tenant attribution and exposes filters; no business data |
| 6 | Self-serve sign-up (becomes tenant root) | Switch on → login page advertises sign-up → two-step wizard (account → organization) → registration stores the session and lands the new ROOT user in guided onboarding — no platform-admin action involved | e2e/tests/self-serve-signup.spec.ts | CS-26: full journey — entry link → wizard → lands in onboarding as root |
| 7 | Quota-blocked action feedback | A blocked invitation surfaces the structured contract (tier, limit, current usage, upgrade path); after the license is raised the SAME action succeeds without a page reload | e2e/tests/quota-enforcement.spec.ts | CS-35/CS-41: blocked invite shows tier/limit/usage/upgrade; unblocked once the license is raised |
| 8 | License tier/usage panel | Tenant settings shows the usage panel with tier chip, free-tier note when no license assigned, and per-quota usage (members, executions this month) | e2e/tests/quota-enforcement.spec.ts | CS-34: the tenant usage panel mirrors tier and limits |
