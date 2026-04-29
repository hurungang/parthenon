# Demo Cases: user-permission-management
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/user-permission-management/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Tags Management > renders tag definitions table
- Roles Management > navigates to Roles tab and shows role data
- Groups Management > groups tab shows group data
- User Access Management > users tab shows user data
- Access Request Flow > access requests tab renders

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Tag Management | User views tag definitions table with environment tags (dev, prod, staging) | permissions.spec.ts | renders tag definitions table |
| 2 | Role Management | User navigates to Roles tab and views admin role with policy assignments | permissions.spec.ts | navigates to Roles tab and shows role data |
| 3 | Group Management | User views groups table showing dev-team with member and role counts | permissions.spec.ts | groups tab shows group data |
| 4 | User Management | User views platform users table showing user Alice with role and group assignments | permissions.spec.ts | users tab shows user data |
| 5 | Access Request Workflow | User views access requests tab showing pending group join requests | permissions.spec.ts | access requests tab renders |
