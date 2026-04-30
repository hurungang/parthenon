# Identity & Auth Test Plan

## What to Test
- OIDC login (Keycloak, Azure EntraID)
- JWT validation and expiry
- Role assignment and permission enforcement
- User permission system: tag management, policy authoring, resource type manifest
- Permission Engine policy evaluation with wildcard resource matching
- User group management and IdP claim-based auto-assignment
- Access request submission, approval, and rejection workflows
- Structured permission error messages with required_permission details
- Bootstrap service system admin role initialization

## Critical Scenarios

### OIDC Authentication & User Caching
- OIDC authentication grants role-appropriate access
- New user login creates PlatformUser record with correct profile data
- Returning user login updates last_seen_at timestamp
- JWT group claims trigger automatic group assignment via Group Claim Mapper

### Permission Engine & Policy Evaluation
- Permission Engine grants access when matching allow policy exists
- Permission Engine denies access by default when no policy matches
- Wildcard resource ID patterns (e.g., "support_*") match correctly
- Tag conditions are correctly enforced in policy evaluation
- Resource type manifest validates resource types and actions
- Invalid resource type or action combinations are rejected

### Tag System
- Tag definitions created with add-button value entry
- Tag values stored individually and available in policy condition dropdowns
- Duplicate tag values prevented

### Role Management & Policy Editing
- Single-dialog policy management displays all role policies in one view
- Policy creation uses resource type and action dropdowns from `GET /api/v1/policy/resource-types` manifest
- Resource type dropdown contains all eight platform types: `user`, `role`, `group`, `tag`, `agent`, `mcp_server`, `skill`, `sop`
- Actions multi-select is scoped to the selected resource type; clears automatically when resource type changes
- Tag key dropdown populated from tag definitions; tag value dropdown auto-populates with allowed values when a key is selected
- Tag value dropdown clears and repopulates when the tag key changes; does not retain stale values from the previous key
- All policy statements for a role are rendered in the PolicyEditor with effect, actions, resource IDs, and tag conditions visible
- Remove statement triggers immediate list refresh without page reload
- Adding a statement via the Add Statement dialog causes the statement list to refresh automatically without page reload
- View JSON button opens the JSONViewModal showing all policy statements as formatted, read-only JSON
- Copy button in JSONViewModal copies full JSON string to clipboard and shows a confirmation indicator
- Clone Role dialog pre-fills source role name and description; name field is editable before submission
- Cloning a role deep-copies all policy statements; cloned role appears in the roles list automatically without page reload
- Duplicate clone name returns 409; error is displayed inside the Clone Role dialog; dialog stays open for correction
- 403 response on add-statement or clone shows `PermissionDeniedAlert` inside the dialog (not a silent failure or page-level error)
- Removing the last statement from a role shows an empty state in PolicyEditor; the role itself remains in the roles list
- System roles cannot be edited or deleted

### User Group Management
- Groups created with owner, roles, and IdP claim value
- Users automatically assigned to groups based on JWT claims at login
- Group owner can manage their own group membership
- Admin can manage all group memberships

### Access Request Flow
- Multi-group batch submission creates one AccessRequestBatch and one AccessRequest per group
- Justification required for submission
- Group owner sees requester justification when reviewing
- Approval with optional note creates UserGroup membership
- Rejection requires reason (422 validation error if missing)
- Each AccessRequest independently reviewed and approved/rejected

### Group-Optional Access Request Flow
- User with no group visibility sees informational alert instead of group selector in the request dialog
- Request submitted with empty group_ids creates one AccessRequest row with group_id = NULL
- Second group-less request while one is pending returns 409 Conflict; duplicate is not created
- Admin pending table displays "Unassigned" chip in the Group column for group-less requests
- Admin approve dialog for a group-less request shows a mandatory group-selection dropdown
- Frontend inline validation blocks approval without a group selection; API is not called
- Approving a group-less request with a selected group_id creates UserGroup membership and updates status to Approved
- Approving a request that already has a stored group_id ignores any group_id in the approval body
- Pending requests table refreshes automatically (no page reload) after admin approve or reject actions

### Structured Permission Error Messages
- 403 responses include required_permission field (resource_type, action, resource_id)
- Frontend displays clear permission error messages
- Users can see exactly which permission they need

### Group-Role Management (ManageGroupRolesDialog)
- Admin opens Manage Roles dialog for a group; currently assigned roles are listed
- Admin assigns a role to a group; confirmation shown; role appears in dialog list
- Admin removes a role from a group; confirmation shown; role absent from dialog list
- After assign or remove, parent groups table reflects updated role data automatically — no page reload required
- Re-opening Manage Roles after removal confirms role is truly gone (proves true removal, not hiding)
- Re-assigning the same role after removal succeeds
- Non-admin attempting to open Manage Roles receives permission error with actual error context (not generic fallback)
- Any API error from assign/remove shows the actual backend `detail` field — not a generic string

### Error Message Detail
- When a 403 response includes resource type, action, and ID, the UI renders all three fields in the snackbar — not just "Access Denied"
- When the backend returns `{"detail": "..."}` on any error, the UI renders that exact message — not a generic fallback
- 422 validation errors propagate field-level messages to the relevant form inputs
- 500 server errors show the most specific available message rather than only a generic fallback
- No existing error path regresses to showing a generic string when it previously showed contextual detail

## Edge Cases
- Token expiry mid-session
- Clock skew between client and provider
- Identity provider downtime
- Non-trailing wildcards in resource ID patterns
- Multi-group batch with mixed approval/rejection outcomes
- Rejection reason length validation
- Tag value deduplication
- Stale group claim assignments when idp_claim_value changes
- Race conditions in access request approval/rejection
- Auth middleware failures (User Cache or Group Claim Mapper)
- Unauthorized self-assignment attempts
- Null propagation through _enrich_request when group_id is None (must not throw)
- approveGroupId state not reset between consecutive approve dialogs (wrong group assigned)
- Mixed pending list rendering: table contains both group-assigned and group-less requests
- Alembic migration for nullable group_id applied on database with existing non-null rows
- User granted group visibility after submitting a group-less request; pending request remains group-less, admin still assigns group on approval
- ManageGroupRolesDialog opened for different groups in sequence; role list correctly refreshes for each group
- Parent groups table role count chip stale after assign/remove (must update without page reload)
- Adding a policy statement with a duplicate resource type + action combination → validation error shown; duplicate not saved
- Removing the last policy statement from a role → empty state displayed in PolicyEditor; role still visible in roles list
- Cloning a role with the same name as the source (easy to trigger accidentally) → 409 surfaced inside dialog; dialog remains open
- Cloning a role whose source was deleted between list load and submit → 404 surfaced inside dialog
- Tag value dropdown when no tag definitions exist in the system → empty state or graceful fallback; no crash
- `useResourceTypes` fetch failure (API unreachable during Add Statement) → error state shown inside dialog; form submission blocked
- JSON view with a statement that has no actions (corrupted data) → rendered without crash; empty actions array shown
- Rapid double-click on "Add Statement" → only one dialog instance opens; no duplicate API submissions

## Test File References

### Backend Unit Tests
- `backend/tests/unit/test_oidc_client.py`
- `backend/tests/unit/test_health.py`
- `backend/tests/unit/test_resource_type_manifest.py`
- `backend/tests/unit/test_permission_engine.py`
- `backend/tests/unit/test_group_claim_mapper.py`
- `backend/tests/unit/test_user_cache_service.py`

### Backend API Tests
- `backend/tests/api/v1/test_tags_api.py`
- `backend/tests/api/v1/test_roles_api.py`
- `backend/tests/api/v1/test_access_requests_api.py`
- `backend/tests/api/v1/test_permissions_api.py`
- `backend/tests/api/v1/test_policy_endpoints.py`

### Backend Service Tests
- `backend/tests/services/permissions/test_access_request_service.py`
- `backend/tests/services/identity/test_bootstrap_service.py`

### Backend Integration Tests
- `backend/tests/integration/test_identity_setup_flow.py`

### Frontend Component Tests
- `frontend/src/__tests__/RolesPage.test.tsx`
- `frontend/src/__tests__/GroupsPage.test.tsx`
- `frontend/src/__tests__/UsersPage.test.tsx`
- `frontend/src/__tests__/TagsPage.test.tsx`
- `frontend/src/__tests__/AccessRequestsPage.test.tsx`
- `frontend/src/__tests__/ManageGroupRolesModal.test.tsx`
- `frontend/src/__tests__/PolicyEditor.test.tsx`
- `frontend/src/__tests__/AddStatementDialog.test.tsx`
- `frontend/src/__tests__/CloneRoleDialog.test.tsx`
- `frontend/src/__tests__/JSONViewModal.test.tsx`
- `frontend/src/__tests__/permissionsApi.test.ts`
- `frontend/src/__tests__/AppShell.test.tsx`

### E2E Tests
- `e2e/tests/auth.spec.ts`
- `e2e/tests/permissions.spec.ts`
- `e2e/tests/tag-management.spec.ts`
- `e2e/tests/role-policy-management.spec.ts`
- `e2e/tests/access-control.spec.ts` — permission-denied scenarios, group-role assignment (assign/remove/permission-error), error message detail
- `e2e/tests/permission-errors.spec.ts` — structured 403 rendering across all pages and dialog contexts
