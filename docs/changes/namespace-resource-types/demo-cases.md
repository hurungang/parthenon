# Demo Cases: namespace-resource-types
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/namespace-resource-types/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
- Namespace Resource Types — Full CRUD Lifecycle > resource types endpoint returns 17 namespaced entries (real backend)
- Namespace Migration Visibility > dashboard remains accessible without specific permission
- AddStatementDialog > Add Statement dialog shows Resource IDs section
- Edit Policy Statement > Edit button opens dialog pre-filled with existing policy data
- Namespace Validation Errors > POST policy with unknown namespaced type 'agent::nonexistent' is rejected
- RolePolicyDialog E2E > roles page renders with mocked namespaced data
- RolePolicyDialog E2E > batch save with wildcard module value is accepted

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Namespace Structure | Backend returns exactly 17 resource types with `::` delimiter across 3 modules, no legacy flat values remain | namespace-resource-types.spec.ts | resource types endpoint returns 17 namespaced entries (real backend) |
| 2 | Migration Visibility | Dashboard page loads without 403 — proves migration didn't break core pages or add unintended permission gates | namespace-migration-visibility.spec.ts | dashboard remains accessible without specific permission |
| 3 | Add Policy UI | Administrator navigates to Roles, expands a role, clicks "Add Statement", and sees the full dialog with resource type dropdown and resource ID management section | role-policy-management.spec.ts | Add Statement dialog shows Resource IDs section |
| 4 | Edit Policy UI | Administrator expands a role, clicks Edit on an existing policy, and sees the dialog pre-filled with current data (effect, module, actions, resources) | role-policy-management.spec.ts | Edit button opens dialog pre-filled with existing policy data |
| 5 | Validation | Backend rejects a properly-namespaced but unknown type (`agent::nonexistent`) — proves validation distinguishes format from validity | namespace-validation-errors.spec.ts | POST policy with unknown namespaced type 'agent::nonexistent' is rejected |
| 6 | RolePolicyDialog UI | Roles page renders with mocked namespaced resource data — the RolePolicyDialog loads correctly with the batch save endpoint, module dropdown populated from namespaced resource types API | role-policy-dialog.spec.ts | roles page renders with mocked namespaced data |
| 7 | FreeSolo Wildcard Input | Batch save API accepts free-text wildcard patterns (`agent::*`, `integration::*`, `*::*`) as valid module values — enables freeSolo autocomplete entry in resource type selectors | role-policy-dialog.spec.ts | batch save with wildcard module value is accepted |
