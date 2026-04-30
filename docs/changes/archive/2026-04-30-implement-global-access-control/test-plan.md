# Test Plan: Implement Global Access Control

## 1. Test Strategy

Testing will be performed at multiple layers to ensure robust, end-to-end validation of global access control:
- **Backend Unit Tests (pytest):** Validate permission enforcement logic, error response structure, and audit logging at the API handler and `PermissionEngine` level.
- **Backend Integration Tests (pytest):** Simulate real API calls with various user roles/permissions to verify enforcement across all resource endpoints.
- **Frontend Unit/Component Tests (Vitest):** Ensure permission-denied UI components (snackbar, modal, full-page) display correct messages and actions.
- **E2E Tests (Playwright):** Validate user flows, permission errors, and access request pathways in the browser, covering all resource management modules.
- **Manual Testing:** Confirm error message clarity, i18n coverage, and UX polish for edge cases not easily automated.

## 2. Coverage Areas

- **Backend:**
  - All resource-managing API endpoints (agents, MCP hub, skills/SOPs, scheduling, notifications, conversations, results)
  - Permission enforcement via `require_permission` dependency
  - Standardized 403 error response structure
  - Audit logging and OTEL instrumentation for permission checks
- **Frontend:**
  - Permission error handling in API client and UI
  - Permission error snackbar, access request modal, and full-page denial
  - i18n coverage for all new/changed error messages
- **E2E:**
  - Full CRUD flows for each resource type, including permission-denied scenarios
  - Access request initiation from error messages

## 3. Critical Scenarios (WHEN/THEN)

- **WHEN** a user without permission attempts to access a resource endpoint
  **THEN** the backend returns a 403 with resource type, action, and resource ID in the error body

- **WHEN** a user with correct permissions accesses a resource
  **THEN** the request succeeds and data is returned as expected

- **WHEN** a permission error is received by the frontend
  **THEN** the UI displays a clear, actionable error message with resource/action/ID context

- **WHEN** a user clicks "Request Access" in the error UI
  **THEN** the access request modal is pre-filled with the denied resource/action/ID and allows justification submission

- **WHEN** an audit log is reviewed
  **THEN** all permission checks (allow/deny) are present with full context

- **WHEN** a resource is deleted or its permissions change
  **THEN** subsequent access attempts are denied until explicit permission is granted

- **WHEN** a user with insufficient permissions attempts a bulk/list operation
  **THEN** only permitted resources are returned, and denied resources are omitted or trigger errors as per spec

- **WHEN** an admin/team lead navigates to the Groups page and clicks "Manage Roles" for a group
  **THEN** a dialog/panel opens showing the group's currently assigned roles and available roles to add

- **WHEN** an admin assigns a role to a group via the Manage Roles dialog
  **THEN** the role appears in the group's role list in the dialog, and the group-role table in the parent view updates automatically without a page reload

- **WHEN** an admin removes a role from a group via the Manage Roles dialog
  **THEN** the role is removed from the group's role list in the dialog, and the group-role table in the parent view updates automatically without a page reload

- **WHEN** any API or UI operation returns an error
  **THEN** the displayed error message includes the actual error details and context (e.g., which field, resource, or constraint caused the error) — not a generic fallback message

## 4. Edge Cases & Risks

[//]: # (=== BEGIN INSERTED SECTION ===)

## 3a. Detailed E2E Test Scenarios

For each of the following modules, E2E tests must cover both the happy path (full user journey with correct permissions) and the permission denied scenario (error handling and access request flow):

**Modules:**
- Agents
- MCP Hub
- Skills/SOPs
- Scheduling
- Notifications
- Conversations
- Results
- Access Requests
- User Permissions Management
- Groups (role assignment)

**For each module:**
1. **Happy Path:**
  - User with correct permissions completes the full CRUD flow (create, read, update, delete) for the resource.
  - All UI elements and data update as expected.
  - Parent tables and related counts refresh automatically after dialog operations.
  - Audit logs reflect all permission checks and actions.
2. **Permission Denied:**
  - User without required permission attempts each CRUD operation.
  - Backend returns 403 with resource/action/ID in error body.
  - UI displays permission error (snackbar, modal, or full-page denial) with actionable messaging.
  - Error message displays actual error details and context — not a generic fallback string.
  - User can initiate an access request from the error UI; modal is pre-filled with denied resource/action/ID and allows justification submission.
  - After submitting access request, confirmation is shown and request is logged.

## 3d. Group-Role Assignment E2E Scenarios

These scenarios validate the new group-role assignment UI introduced by this change.

**Happy Path — Assign Role to Group:**
1. Admin navigates to the Groups page.
2. Clicks "Manage Roles" (or equivalent) for a target group.
3. Dialog/panel opens; currently assigned roles are visible.
4. Admin selects a role to add and confirms.
5. Confirmation toast/snackbar is shown.
6. Dialog reflects the new role in the group's role list.
7. Parent groups table updates automatically (role count or role chip) — no page reload required.

**Happy Path — Remove Role from Group:**
1. Admin navigates to the Groups page.
2. Clicks "Manage Roles" for a group that has at least one assigned role.
3. Admin removes a role and confirms.
4. Confirmation toast/snackbar is shown.
5. Role is no longer listed in the dialog.
6. Parent groups table updates automatically — no page reload required.
7. Re-opening the Manage Roles dialog confirms the role is absent.

**CRUD Lifecycle Validation:**
- Assign a role → verify it appears (READ).
- Remove the same role → verify it is gone (DELETE).
- Re-assign the same role → verify it can be re-added (proves true removal, not hiding).

**Error Handling — Permission Denied:**
- A user without `permissions:manage` attempts to open Manage Roles; action is blocked and a permission error is displayed with actual error context.

**Error Handling — API/Validation Errors:**
- Any error from the assign/remove API call displays the actual backend error message (not "An error occurred").
- Required fields or invalid role assignments show field-level or inline error details.

## 3e. Error Message Detail Scenarios

These scenarios validate that error messages show actual, contextual details rather than generic fallbacks — across all modules.

**API Error Display:**
- When the backend returns an error with a `detail` field (e.g., `{"detail": "Role 'admin' already assigned to group 'ops'"}`), the UI renders that exact detail to the user, not a generic string.
- When the backend returns a validation error (422) with field-level messages, those messages are shown per field in the form.

**Permission Error Display:**
- 403 responses include resource type, action, and resource ID; the UI renders all three fields in the error component — not just "Access Denied".

**Network / Unexpected Error Display:**
- Even for unexpected errors (500, network failure), the UI shows the most specific available message from the response body rather than only a generic fallback.

**Regression Check:**
- No existing error path that previously showed the actual message has regressed to showing a generic one.

## 3b. Backend Endpoint Test Cases

For each affected endpoint (from tech-spec.md), verify permission enforcement for both allowed and denied users:

- `GET /api/v1/agents/types` — test with/without `agent:read`
- `POST /api/v1/agents/types` — test with/without `agent:create`
- `GET /api/v1/mcp/servers` — test with/without `mcp_server:read`
- `POST /api/v1/mcp/servers` — test with/without `mcp_server:create`
- `GET /api/v1/skills` — test with/without `skill:read`
- `POST /api/v1/skills` — test with/without `skill:create`
- `GET /api/v1/schedules` — test with/without `scheduling:read`
- `POST /api/v1/schedules` — test with/without `scheduling:create`
- `GET /api/v1/notifications/channels` — test with/without `notification:read`
- `POST /api/v1/notifications/channels` — test with/without `notification:manage`
- `GET /api/v1/conversations` — test with/without `conversation:read`
- `GET /api/v1/results` — test with/without `result:read`
- `GET /api/v1/user-access-requests/pending` — test with/without `access_request:read`
- `PATCH /api/v1/user-access-requests/{id}/approve` — test with/without `access_request:approve`
- `GET /api/v1/platform-users` — test with/without `permissions:read`
- `PATCH /api/v1/platform-users/{id}/roles` — test with/without `permissions:manage`

Each endpoint:
- Returns 403 with correct error structure when permission is missing
- Allows operation when permission is present
- Logs all permission checks

## 3c. Frontend Component Test Cases

**RequestPermissionModal**
- Renders when triggered by permission error
- Pre-fills denied resource/action/ID context
- Allows user to submit justification
- Shows confirmation on successful submission

**AccessDeniedPage**
- Renders for full-page permission errors
- Displays resource/action/ID and error details
- Provides clear guidance and link to request access

**PermissionErrorSnackbar**
- Displays on permission error from API
- Shows actionable message with resource/action/ID — including actual resource type, action, and ID (not generic text)
- Includes "Request Access" button that triggers modal

**ManageGroupRolesDialog (new)**
- Renders the list of currently assigned roles for the target group
- Allows adding an available role; shows confirmation on success
- Allows removing an existing role; shows confirmation on success
- After add/remove, triggers parent table refresh so groups table reflects updated role data without page reload
- Displays actual API error details when assign/remove fails (not a generic fallback)

**Error Message Utilities / API Client**
- Error display helper surfaces the `detail` field from backend responses
- 422 validation errors propagate field-level messages to the relevant form inputs
- No code path hard-codes a generic "An error occurred" string as the sole displayed message

[//]: # (=== END INSERTED SECTION ===)
- Inconsistent error message formats across modules
- Permission checks missed on new or rarely used endpoints
- Race conditions: permissions change between check and action
- UI not updating after permission changes (stale state)
- i18n keys missing for new error messages
- Audit logs missing or incomplete for some permission checks
- Bulk operations leaking unauthorized resource data
- Frontend failing to parse or display new error structure

## 5. Acceptance Criteria Checklist

- [x] All resource-managing endpoints enforce permission checks (deny by default)
- [x] 403 errors specify resource type, action, and resource ID
- [x] Users denied access see actionable, clear error messages in the UI
- [x] Users can initiate access requests with full context from the error
- [x] Audit logs capture all permission check results
- [x] No resource is accessible without explicit permission
- [x] Existing functionality is preserved for authorized users
- [x] i18n coverage for all new/changed error messages
- [ ] UI is provided for assigning and removing roles for any group (Manage Roles dialog)
- [ ] Group-role table updates automatically after assign/remove — no page reload required
- [ ] All error messages (permission errors, API errors, validation errors) display actual error context and details, not generic fallback strings

## 6. Test File References

**Backend Tests:**
- [backend/tests/api/v1/test_permissions_api.py](../../backend/tests/api/v1/test_permissions_api.py)
- [backend/tests/unit/test_permission_engine.py](../../backend/tests/unit/test_permission_engine.py)
- [backend/tests/unit/test_resource_type_manifest.py](../../backend/tests/unit/test_resource_type_manifest.py)
- [backend/tests/integration/](../../backend/tests/integration/)
- [backend/tests/unit/](../../backend/tests/unit/)

**Frontend Tests:**
- [frontend/src/__tests__/permissionsApi.test.ts](../../frontend/src/__tests__/permissionsApi.test.ts)
- [frontend/src/__tests__/AppShell.test.tsx](../../frontend/src/__tests__/AppShell.test.tsx)
- [frontend/src/__tests__/AccessRequestsPage.test.tsx](../../frontend/src/__tests__/AccessRequestsPage.test.tsx)
- [frontend/src/__tests__/AgentManagementPage.test.tsx](../../frontend/src/__tests__/AgentManagementPage.test.tsx)
- [frontend/src/__tests__/McpHubPage.test.tsx](../../frontend/src/__tests__/McpHubPage.test.tsx)
- [frontend/src/__tests__/RolesPage.test.tsx](../../frontend/src/__tests__/RolesPage.test.tsx)
- [frontend/src/__tests__/UsersPage.test.tsx](../../frontend/src/__tests__/UsersPage.test.tsx)

**E2E Tests:**
- [e2e/tests/access-control.spec.ts](../../e2e/tests/access-control.spec.ts) — permission-denied scenarios, PermissionErrorSnackbar, request access flow, AccessDeniedPage (8 tests, all passing)
- [e2e/tests/permissions.spec.ts](../../e2e/tests/permissions.spec.ts)
- [e2e/tests/agent-management.spec.ts](../../e2e/tests/agent-management.spec.ts)
- [e2e/tests/mcp-hub.spec.ts](../../e2e/tests/mcp-hub.spec.ts)
- [e2e/tests/skills-sops.spec.ts](../../e2e/tests/skills-sops.spec.ts)
- [e2e/tests/scheduling.spec.ts](../../e2e/tests/scheduling.spec.ts)
- [e2e/tests/notifications.spec.ts](../../e2e/tests/notifications.spec.ts)
- [e2e/tests/conversations.spec.ts](../../e2e/tests/conversations.spec.ts)
- [e2e/tests/results.spec.ts](../../e2e/tests/results.spec.ts)
- [e2e/tests/access-control.spec.ts](../../e2e/tests/access-control.spec.ts) — to be extended with group-role assignment scenarios (sections 3d) and error message detail scenarios (section 3e)
