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

### Role Management & Single-Dialog UI
- Single-dialog policy management displays all role policies in one view
- Policy creation uses resource type and action dropdowns from manifest
- Tag condition dropdowns populated from tag definition allowed values
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

### Structured Permission Error Messages
- 403 responses include required_permission field (resource_type, action, resource_id)
- Frontend displays clear permission error messages
- Users can see exactly which permission they need

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

## Test File References

### Backend Unit Tests
- `backend/tests/unit/test_oidc_client.py`
- `backend/tests/unit/test_health.py`
- `backend/tests/unit/test_resource_type_manifest.py`
- `backend/tests/unit/test_permission_engine.py`
- `backend/tests/permissions/test_permission_engine.py`
- `backend/tests/permissions/test_wildcard_matching.py`
- `backend/tests/permissions/test_tag_conditions.py`

### Backend API Tests
- `backend/tests/api/v1/test_user_tags_api.py`
- `backend/tests/api/v1/test_user_roles_api.py`
- `backend/tests/api/v1/test_user_groups_api.py`
- `backend/tests/api/v1/test_platform_users_api.py`
- `backend/tests/api/v1/test_user_access_requests_api.py`
- `backend/tests/api/v1/test_permissions_api.py`

### Backend Integration Tests
- `backend/tests/roles/test_role_management.py`
- `backend/tests/groups/test_group_management.py`
- `backend/tests/users/test_user_management.py`
- `backend/tests/access_requests/test_access_request_flow.py`
- `backend/tests/auth/test_auth_middleware.py`

### Frontend Component Tests
- `frontend/src/__tests__/RolesPage.test.tsx`
- `frontend/src/__tests__/GroupsPage.test.tsx`
- `frontend/src/__tests__/UsersPage.test.tsx`
- `frontend/src/__tests__/TagsPage.test.tsx`
- `frontend/src/__tests__/AccessRequestsPage.test.tsx`
- `frontend/src/__tests__/TagManagement.test.tsx`
- `frontend/src/__tests__/RoleManagement.test.tsx`
- `frontend/src/__tests__/GroupManagement.test.tsx`
- `frontend/src/__tests__/UserManagement.test.tsx`
- `frontend/src/__tests__/ManageAccessModal.test.tsx`
- `frontend/src/__tests__/AccessRequestForm.test.tsx`
- `frontend/src/__tests__/permissionsApi.test.ts`
- `frontend/src/__tests__/permissionsStore.test.ts`

### E2E Tests
- `e2e/tests/auth.spec.ts`
- `e2e/tests/permissions.spec.ts`
- `e2e/tests/permission-management.spec.ts`
- `e2e/tests/tag-system.spec.ts`
- `e2e/tests/group-claim-mapping.spec.ts`
- `e2e/tests/access-request-flow.spec.ts`
- `e2e/tests/manage-user-access.spec.ts`
