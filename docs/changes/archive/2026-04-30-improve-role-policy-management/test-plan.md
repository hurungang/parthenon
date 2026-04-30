# Improve Role & Policy Management — Test Plan

## 1. Test Strategy

This change is frontend-only with two lightweight backend additions (`GET /api/v1/policy/resource-types` and `POST /api/v1/user-roles/{role_id}/clone`). The test strategy covers three layers:

- **Backend unit/integration tests** (pytest): Validate the two new endpoints — resource-type catalogue response and clone deep-copy correctness, including error cases (404, 409).
- **Frontend component tests** (Vitest + React Testing Library): Validate each new component (`PolicyEditor`, `AddStatementDialog`, `JSONViewModal`, `CloneRoleDialog`) in isolation, including dialog error handling per the project's Dialog Error Handling Standard.
- **E2E tests** (Playwright): Validate complete admin workflows end-to-end: adding a statement via dropdowns, removing a statement, viewing JSON, and cloning a role. At least one E2E test hits the real backend (no `page.route()` mock) to catch any integration issues.

Manual exploratory testing is recommended for the JSON view copy-to-clipboard interaction and visual rendering of policy statement cards.

---

## 2. Coverage Areas

### 2.1 New Backend Endpoints

| Area | Why It Matters |
|---|---|
| `GET /api/v1/policy/resource-types` response shape | Frontend dropdowns depend entirely on this data; wrong shape breaks the Add Statement form |
| `ResourceTypeManifest` completeness | All expected resource types (`user`, `role`, `group`, `tag`, `agent`, `mcp_server`, `skill`, `sop`) must be present with their allowed actions |
| `POST /api/v1/user-roles/{role_id}/clone` deep copy | Must copy all `PolicyStatement`, `PolicyAction`, `PolicyResource`, and `PolicyTagCondition` rows — missing any breaks the cloned role's permissions |
| Clone name uniqueness (409) | Duplicate role names must be rejected; error must bubble to UI |
| Clone source not found (404) | Deleted source role must not silently create orphaned data |
| Authentication on both endpoints | `role:read` required for resource types; `role:manage` required for clone |

### 2.2 AddStatementDialog Component

| Area | Why It Matters |
|---|---|
| Resource Type dropdown populated from API | Dropdowns replace free-text inputs — empty dropdown means admin cannot create statements |
| Effect dropdown shows Allow / Deny | Effect is required; wrong values corrupt policy |
| Actions multi-select scoped to selected resource type | Cross-resource action assignments are invalid |
| Tag key dropdown from `useTagDefinitions` | Tag key must come from real definitions, not be free-typed |
| Tag value from `useTagValueOptions` per selected key | Tag value mismatch causes policy to never match |
| Adding / removing condition rows | Multiple conditions per statement are valid; removal must not corrupt remaining rows |
| Validation: required fields enforced | Resource type, effect, and at least one action are required |
| Validation: duplicate resource/action detection | Prevents identical statements that confuse policy evaluation |
| Dialog error handling (PermissionDeniedAlert) | Per Dialog Error Handling Standard; 403 and other errors must appear in dialog, not fail silently |
| Dialog state reset on close/reopen | Stale form values across openings would create wrong statements |

### 2.3 PolicyEditor Component

| Area | Why It Matters |
|---|---|
| All policy statements rendered for a role | Admin needs a single consolidated view |
| Statement card shows resource type, effect, actions, tag conditions | Visual accuracy; incorrect display misleads admins |
| Remove statement triggers refetch | Parent view must update without manual reload (PRD acceptance criterion) |
| Remove error shown inline per statement | Admin must know which remove failed |
| Add Statement button opens AddStatementDialog | Entry point for all new statements |
| After add, statement list refreshes automatically | PRD acceptance criterion: no manual reload |

### 2.4 JSONViewModal Component

| Area | Why It Matters |
|---|---|
| Modal opens on "View JSON" action | Core feature access |
| JSON output matches expected canonical shape | Audit/export usefulness depends on format correctness |
| All statements included in JSON output | Missing statements = incomplete audit record |
| Copy-to-clipboard button copies full JSON string | Admin workflow requires clipboard copy for documentation |
| Read-only: no edit controls present | JSON view is explicitly read-only; editable fields would mislead |

### 2.5 CloneRoleDialog Component

| Area | Why It Matters |
|---|---|
| Pre-filled name includes "(Copy)" suffix or source name | Admin immediately knows it is a copy |
| Pre-filled description matches source | Reduces manual re-entry |
| Submitting creates new role with all policy statements | Core clone feature; incomplete copy breaks access for new role |
| Duplicate name rejected with visible error | 409 must surface in dialog (Dialog Error Handling Standard) |
| After successful clone, roles list refreshes automatically | PRD acceptance criterion; `permissionKeys.roles` invalidation |
| Dialog error handling (PermissionDeniedAlert) | 403 and other failures must appear in dialog |

### 2.6 RolesPage Integration

| Area | Why It Matters |
|---|---|
| "View JSON" icon button present per role row | New entry point |
| "Clone" icon button present per role row | New entry point |
| PolicyEditor replaces old inline expanded row | Regression: old inline form must not co-exist |
| Removed state (`policyRoleId`, `policyForm`) no longer causes stale data | State cleanup prevents ghost data in UI |

### 2.7 Tag Value Bug Fix

| Area | Why It Matters |
|---|---|
| Tag value dropdown populates when a tag key is selected | Previously broken; tags are critical for attribute-based access control |
| Tag value dropdown updates when tag key changes | Stale options from previous key would create invalid conditions |
| Empty tag values handled gracefully (no tags defined) | Should not crash; show empty state or allow free-text fallback |

---

## 3. Critical Scenarios

### Scenario: Admin adds policy statement with dropdowns
**WHEN** an admin opens a role and clicks "Add Statement"  
**THEN** the Add Statement dialog opens with a Resource Type dropdown (not a text input)  
**AND** the Resource Type dropdown contains: `user`, `role`, `group`, `tag`, `agent`, `mcp_server`, `skill`, `sop`  
**AND** the Effect dropdown contains: `Allow`, `Deny`  
**AND** the Actions field is a multi-select driven by the selected resource type

### Scenario: Actions multi-select updates when resource type changes
**WHEN** an admin selects "skill" as the Resource Type  
**THEN** the Actions multi-select shows only actions valid for `skill`  
**WHEN** the admin then changes Resource Type to "mcp_server"  
**THEN** the Actions multi-select refreshes to show actions valid for `mcp_server`  
**AND** any previously selected actions are cleared

### Scenario: Tag value dropdown auto-populates
**WHEN** an admin adds a tag condition and selects a Tag Key (e.g., "environment")  
**THEN** the Tag Value dropdown shows the allowed values defined for that key (e.g., "production", "staging", "development")  
**AND** the values come from the tag definitions, not free text

### Scenario: Tag value dropdown updates on key change
**WHEN** an admin has selected "environment" as Tag Key and "production" as Tag Value  
**AND** the admin changes the Tag Key to "department"  
**THEN** the Tag Value dropdown clears and repopulates with values for "department"  
**AND** the previously selected value "production" is no longer shown

### Scenario: Policy statement saved and list refreshes
**WHEN** an admin completes the Add Statement form and clicks "Save Statement"  
**THEN** the dialog closes  
**AND** the PolicyEditor displays the new statement immediately  
**AND** no manual page reload is required

### Scenario: Admin removes a policy statement
**WHEN** an admin clicks "Remove" on a policy statement card  
**THEN** a confirmation is requested (if implemented) or the statement is removed immediately  
**AND** the PolicyEditor updates the statement list without a page reload  
**AND** the removed statement is no longer visible

### Scenario: Admin views JSON for a role
**WHEN** an admin clicks the "View JSON" icon button on a role row  
**THEN** the JSONViewModal opens  
**AND** all policy statements for that role are represented in the JSON output  
**AND** the JSON is rendered in a read-only dark monospace code block  
**AND** a "Copy" button is visible

### Scenario: Admin copies JSON to clipboard
**WHEN** the admin clicks the "Copy" button in JSONViewModal  
**THEN** the full JSON string is copied to the clipboard  
**AND** a confirmation indicator is shown (button label change or toast)

### Scenario: Admin clones a role
**WHEN** an admin clicks the "Clone" icon button on a role row  
**THEN** the CloneRoleDialog opens pre-filled with the source role's name and description  
**AND** the name field is editable  
**WHEN** the admin submits the dialog  
**THEN** a new role is created with all policy statements from the source role  
**AND** the roles list refreshes automatically to show the new role  
**AND** no manual page reload is required

### Scenario: Clone rejected on duplicate name
**WHEN** an admin attempts to clone a role using a name that already exists  
**THEN** the API returns 409  
**AND** an error message is displayed inside the CloneRoleDialog  
**AND** the dialog remains open so the admin can change the name

### Scenario: Non-admin attempts to modify policies
**WHEN** a user without `role:manage` permission attempts to add a statement or clone a role  
**THEN** the API returns 403  
**AND** a PermissionDeniedAlert is displayed inside the relevant dialog  
**AND** the dialog does not close silently

### Scenario: Removing last statement from a role
**WHEN** an admin removes the only remaining policy statement from a role  
**THEN** the removal succeeds without error  
**AND** PolicyEditor shows an empty state (e.g., "No policy statements")  
**AND** the role still exists in the roles list

---

## 4. Edge Cases & Risks

| Edge Case | Risk | Expected Behaviour |
|---|---|---|
| Adding statement with duplicate resource type + action combination | Policy engine may behave unexpectedly with duplicate rules | Validation error shown; duplicate rejected before save |
| Removing last statement from a role | Role becomes effectively permissionless — admin may not intend this | Removal succeeds with empty-state display; no implicit protection |
| Cloning a role using the same name as source | Name collision is easy to trigger by accident | 409 returned; dialog error shown; dialog stays open |
| Cloning a role whose source is deleted mid-flow | Race condition between list load and clone submit | 404 returned; dialog error shown clearly |
| Tag value dropdown when no tags are defined in system | `useTagDefinitions` returns empty; dropdown would be empty | Empty state shown; tag condition rows either hidden or allow free-text fallback |
| JSON view when a statement has no actions (corrupted data) | JSON output could be malformed or misleading | Statement rendered with empty actions array; no crash |
| JSON view with very large number of statements | Performance issue in modal rendering | Scrollable container; no truncation of statements |
| Actions multi-select with no options for selected resource type | Edge case in ResourceTypeManifest | Graceful empty state in actions selector; save blocked until at least one action added |
| Dialog opened concurrently (rapid double-click on Add Statement) | Duplicate dialog instances or duplicate API calls | Only one dialog instance opens; submit button disabled after first click |
| `useResourceTypes` fetch failure (API unreachable) | Dropdown data unavailable; form unusable | Error state shown in dialog; form cannot be submitted without resource types |
| RolesPage state after PolicyEditor replaces inline form | Leftover state (`policyRoleId`, `policyForm`) may cause ghost UI | Old state fields removed; regression test verifies no stale expansion |

---

## 5. Acceptance Criteria Checklist

Mapped directly to PRD acceptance criteria:

- [ ] **Admin can add new policy statements to a role using dropdowns for resource type, effect, and actions** — `AddStatementDialog` renders dropdowns for all three fields populated from `GET /api/v1/policy/resource-types`
- [ ] **Tag values are auto-populated and selectable in the statement form** — Tag value dropdown in `AddStatementDialog` populates from `useTagValueOptions(tagKey)` when a tag key is selected
- [ ] **Admin can remove policy statements from a role in the same interface** — `PolicyEditor` shows a Remove button per statement; removal triggers list refresh
- [ ] **All policy statements for a role are visible in a single view** — `PolicyEditor` renders all statements for the selected role in one consolidated component
- [ ] **Admin can switch to a JSON view of all policy statements for a role** — "View JSON" button opens `JSONViewModal` showing full policy JSON in a read-only code block
- [ ] **Admin can clone an existing role, including all policy statements, and edit the new role before saving** — "Clone" button opens `CloneRoleDialog` pre-filled with source data; `POST /api/v1/user-roles/{id}/clone` deep-copies all statements
- [ ] **After adding, editing, or deleting a statement, the parent table/view refreshes automatically without manual reload** — React Query cache invalidation on `permissionKeys.role(roleId)` triggers refetch; roles list invalidated on clone
- [ ] **Validation errors are shown for invalid or duplicate entries** — `AddStatementDialog` blocks save on missing required fields; `CloneRoleDialog` surfaces 409 as an inline dialog error
- [ ] **System enforces required fields and prevents saving incomplete statements** — Resource type, effect, and at least one action required; form submit disabled or blocked otherwise

---

## 6. Test File References

**Backend Tests**: [backend/tests/api/v1/test_policy_endpoints.py](../../../backend/tests/api/v1/test_policy_endpoints.py) (9 tests) — `GET /api/v1/policy/resource-types` and `POST /api/v1/user-roles/{role_id}/clone`

**Frontend Tests**:
- [frontend/src/__tests__/PolicyEditor.test.tsx](../../../frontend/src/__tests__/PolicyEditor.test.tsx) (5 tests) — Statement list rendering, remove mutation, add trigger
- [frontend/src/__tests__/AddStatementDialog.test.tsx](../../../frontend/src/__tests__/AddStatementDialog.test.tsx) (7 tests) — Dropdown population, actions scoping, tag value auto-populate, validation, dialog error handling
- [frontend/src/__tests__/CloneRoleDialog.test.tsx](../../../frontend/src/__tests__/CloneRoleDialog.test.tsx) (7 tests) — Pre-fill, submit, 409 error display, roles list refresh
- [frontend/src/__tests__/JSONViewModal.test.tsx](../../../frontend/src/__tests__/JSONViewModal.test.tsx) (6 tests) — JSON output shape, read-only enforcement, copy-to-clipboard

**E2E Tests**: [e2e/tests/role-policy-management.spec.ts](../../../e2e/tests/role-policy-management.spec.ts) (10 tests) — Full CRUD flows: add statement, remove statement, view JSON, clone role; includes at least one real-backend test (no `page.route()` mock) to catch integration issues
