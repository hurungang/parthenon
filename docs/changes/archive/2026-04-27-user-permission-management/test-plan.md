# User Permission Management — Test Plan

## 1. Test Strategy

Testing uses a three-layer approach, all layers required for the feature to be considered complete:

- **Backend Unit & Integration Tests** (`backend/tests/`): Validate Permission Engine policy evaluation and wildcard matching, tag condition enforcement, role/group service logic, Access Request batch creation, approval/rejection with reviewer_reason, auth middleware integration.
- **Frontend Component Tests** (`frontend/src/__tests__/`): Verify rendering and behavior of tag add-button chip UI, role policy builder (wildcard resource IDs, tag value dropdowns), Manage Access modal tabs, multi-group request form with justification, approval/rejection modals with reason validation.
- **End-to-End Tests** (`e2e/tests/`): Simulate full user journeys — permission assignment, access request submission and approval, group claim auto-assignment, manage-access flows. All API calls mocked via `page.route()`.

Manual testing covers complex approval workflows and IdP claim mapping configuration.

---

## 2. Coverage Areas

- **Tag System**: Creation of tags with add-button value entry; values stored individually; values available in policy condition dropdowns; duplicate value prevention.
- **Role Management**: Policy builder with wildcard and exact resource ID matching; tag condition values selected from allowed values dropdown; role assignment and enforcement; single-dialog policy management for comprehensive role editing.
- **Resource Type Manifest**: Centralized definition of resource types and their allowed actions; validation of resource type and action combinations during policy creation; UI dropdowns driven by manifest schema.
- **Permission Engine**: Accurate evaluation of module/action/resource/tag conditions; wildcard pattern evaluation for resource IDs; deny by default when no matching allow policy; manifest-based validation of resource type and action combinations.
- **Permission Error Messages**: Structured 403 responses with required_permission field; clear display of resource type, action, and resource ID when access is denied.
- **Group Management**: Group creation with owner, roles, and IdP claim mapping; auto-assignment from JWT group claims; membership management.
- **User Management**: OIDC user caching on login; Manage Access modal for assigning/removing direct roles and group memberships.
- **Access Request Flow**: Multi-group batch submission with mandatory justification; per-group independent approval/rejection; justification visibility for reviewers; required rejection reason; optional approval note.
- **Auth Middleware**: User cache write and group claim mapping triggered on each authenticated request.
- **Negative Cases**: Access denied for missing permissions, invalid tag conditions, missing required fields, unauthorized self-assignment; invalid resource type and action combinations rejected via manifest validation.

---

## 3. Critical Scenarios

### Tag System
- WHEN a tag definition is created with allowed values added one at a time THEN each value is independently stored and available in policy condition dropdowns
- WHEN a tag condition references a non-existent tag key or value THEN access is denied

### Role Management & Policy Builder
- WHEN a policy statement contains wildcard resource ID "support_*" THEN the Permission Engine grants access to resources with IDs "support_001", "support_002", and "support_team"
- WHEN a policy statement contains wildcard resource ID "support_*" THEN the Permission Engine denies access to resources with IDs "monitoring_001" and "eng_support"
- WHEN a policy statement contains exact resource ID "agent_001" THEN only that specific resource is matched and access to "agent_002" is denied
- WHEN a user selects a tag key in the role policy builder THEN the value dropdown is populated with only that key's allowed values
- WHEN no tag key is selected in the policy builder THEN the value dropdown shows a disabled placeholder
- WHEN a user without the required role attempts an action THEN access is denied
- WHEN a role is updated with new tag conditions THEN the updated conditions take effect immediately on subsequent requests
- WHEN an admin opens the role policy dialog THEN all existing policies for that role are visible in one comprehensive view
- WHEN an admin adds multiple policies within the dialog THEN all changes are managed without closing the dialog
- WHEN an admin saves policy changes THEN all policies are persisted atomically and the dialog closes

### Resource Type Manifest
- WHEN an admin attempts to create a policy with a resource type not defined in the manifest THEN the system rejects the creation with a validation error
- WHEN an admin attempts to create a policy with an action not allowed for the selected resource type THEN the system rejects the creation referencing the manifest
- WHEN the permission engine evaluates a policy with an invalid action for its resource type THEN the policy evaluation fails and access is denied
- WHEN an admin opens the policy builder THEN resource type and action dropdowns display only values defined in the manifest

### Structured Permission Error Messages
- WHEN a user attempts an action without the required permission THEN a 403 response is returned with a required_permission field containing resource_type, action, and resource_id
- WHEN the frontend receives a 403 with required_permission details THEN the UI displays a clear message showing "Access Denied: You need permission for [resource_type] [action] on [resource_id]"
- WHEN a user sees a permission error with structured details THEN they can request the specific permission from an administrator

### Group Management
- WHEN a group is created with an owner THEN only that owner (and admins) can modify group membership
- WHEN a user is added to a group THEN they inherit all roles assigned to that group
- WHEN a user's JWT token contains a group claim matching a group's idp_claim_value THEN the user is automatically assigned to that group on login

### User Management
- WHEN a new user logs in via OIDC THEN a PlatformUser record is created with their profile information
- WHEN a returning user logs in THEN their last_seen timestamp is updated and no duplicate record is created
- WHEN an admin opens Manage Access for a user THEN the Direct Roles tab and Group Memberships tab display the user's current assignments
- WHEN an admin assigns a new role via the Manage Access modal THEN the role appears in the user's direct roles and their permissions update
- WHEN an admin removes a group membership via the Manage Access modal THEN the user loses all roles inherited from that group

### Access Request Flow
- WHEN a user submits an access request selecting multiple groups with a justification THEN one AccessRequestBatch is created and one AccessRequest per selected group is created
- WHEN a user submits an access request without providing a justification THEN the submission is rejected with a validation error
- WHEN a user submits an access request without selecting any group THEN the submission is rejected
- WHEN a group owner reviews a pending request THEN the requester's justification text is visible before making a decision
- WHEN a group owner approves a request with an optional approval note THEN the note is stored as the reviewer_reason on the AccessRequest record
- WHEN a group owner attempts to reject a request without providing a reason THEN the rejection is blocked with a validation error
- WHEN a group owner rejects a request with a required reason THEN the reason is stored as reviewer_reason and the requester is notified
- WHEN a user has a pending request for a resource THEN access is denied until the request is approved

### Permission Engine & Enforcement
- WHEN a user with the correct role and matching tag conditions makes an API request THEN access is granted
- WHEN all tag conditions are correct but the resource ID does not match (exact or wildcard) THEN access is denied
- WHEN a policy is deleted THEN affected users immediately lose access granted by that policy
- WHEN a user attempts to escalate privileges via a direct API call THEN access is denied and the attempt is logged

---

## 4. Edge Cases & Risks

- **Non-trailing wildcards**: Wildcard patterns like "support_*_test" — behavior must be defined and documented; only trailing wildcards should be supported unless explicitly extended.
- **Multi-group batch, mixed outcomes**: One batch may have some groups approve and others reject — each AccessRequest is independently reviewed by its group owner; batch status reflects all group statuses.
- **Rejection reason length**: Maximum length validation must be enforced both on the frontend and backend.
- **Tag value deduplication**: Submitting a duplicate value via the add-button should be prevented on the frontend and rejected by the backend.
- **Stale group claim assignments**: If a group's idp_claim_value is changed, existing memberships from the old claim are not automatically removed — document this behavior.
- **Race conditions**: Simultaneous approval/rejection of the same AccessRequest by two different group owners could cause conflicting state — handle with optimistic locking or status pre-check.
- **Auth middleware failures**: If User Cache write or Group Claim Mapper fails, it must not block the request — failures must be logged and silently bypassed.
- **Unauthorized self-assignment**: Users must not be able to assign themselves to restricted groups or roles via API manipulation.

---

## 5. Acceptance Criteria Checklist

- [ ] Tag system supports creation with add-button value entry; values are individually stored and available in policy condition dropdowns
- [ ] Duplicate tag values are rejected at submission
- [ ] Resource IDs in role policies support wildcard patterns; Permission Engine evaluates wildcards correctly (trailing wildcard only)
- [ ] Exact resource ID matching is unaffected by the wildcard implementation
- [ ] Tag condition values in the policy builder are selected from the tag's defined allowed values (not free-text input)
- [ ] Resource Type Manifest defines all resource types and their allowed actions
- [ ] Policy creation validates resource type and action combinations against the manifest
- [ ] UI dropdowns for resource type and action are driven by manifest schema
- [ ] Single-dialog policy management allows viewing and editing all policies for a role in one comprehensive dialog
- [ ] Permission error responses include required_permission field with resource_type, action, and resource_id
- [ ] Frontend displays clear permission error messages showing what specific permission is missing
- [ ] Manage Access modal is fully functional — admins can assign and remove direct roles and group memberships for any user
- [ ] Access requests support multi-group selection with a mandatory justification field
- [ ] Requests without justification or without any group selected are rejected
- [ ] Approval view shows requester justification; approval note is optional; rejection reason is required
- [ ] Rejection without a reason is blocked by frontend validation and backend validation
- [ ] Multi-group batch creates one AccessRequest per group; each is independently approved or rejected
- [ ] Group claim mapper auto-assigns users to matching groups at login based on JWT claims
- [ ] All permission policies and tag conditions are enforced by the Permission Engine on every API request
- [ ] All access requests, approvals, rejections, and permission changes are logged for audit

---

## 6. Test File References

**Backend Tests** (`backend/tests/`):
- `backend/tests/permissions/test_permission_engine.py`
- `backend/tests/permissions/test_wildcard_matching.py`
- `backend/tests/permissions/test_tag_conditions.py`
- `backend/tests/unit/test_resource_type_manifest.py` — Validates manifest structure and completeness
- `backend/tests/api/v1/test_roles_api.py` — Updated to verify structured error responses with required_permission field
- `backend/tests/roles/test_role_management.py`
- `backend/tests/groups/test_group_management.py`
- `backend/tests/users/test_user_management.py`
- `backend/tests/access_requests/test_access_request_flow.py`
- `backend/tests/auth/test_auth_middleware.py`

**Frontend Component Tests** (`frontend/src/__tests__/`):
- `frontend/src/__tests__/TagManagement.test.tsx`
- `frontend/src/__tests__/pages/RolesPage.test.tsx` — Updated for single-dialog policy management workflow
- `frontend/src/__tests__/RoleManagement.test.tsx`
- `frontend/src/__tests__/GroupManagement.test.tsx`
- `frontend/src/__tests__/UserManagement.test.tsx`
- `frontend/src/__tests__/ManageAccessModal.test.tsx`
- `frontend/src/__tests__/AccessRequestForm.test.tsx`

**E2E Tests** (`e2e/tests/`):
- `e2e/tests/permissions.spec.ts` — Updated for policy creation flow with manifest validation and error message display
- `e2e/tests/permission-management.spec.ts`
- `e2e/tests/tag-system.spec.ts`
- `e2e/tests/group-claim-mapping.spec.ts`
- `e2e/tests/access-request-flow.spec.ts`
- `e2e/tests/manage-user-access.spec.ts`
