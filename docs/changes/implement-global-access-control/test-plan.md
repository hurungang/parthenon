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

## 4. Edge Cases & Risks

- Inconsistent error message formats across modules
- Permission checks missed on new or rarely used endpoints
- Race conditions: permissions change between check and action
- UI not updating after permission changes (stale state)
- i18n keys missing for new error messages
- Audit logs missing or incomplete for some permission checks
- Bulk operations leaking unauthorized resource data
- Frontend failing to parse or display new error structure

## 5. Acceptance Criteria Checklist

- [ ] All resource-managing endpoints enforce permission checks (deny by default)
- [ ] 403 errors specify resource type, action, and resource ID
- [ ] Users denied access see actionable, clear error messages in the UI
- [ ] Users can initiate access requests with full context from the error
- [ ] Audit logs capture all permission check results
- [ ] No resource is accessible without explicit permission
- [ ] Existing functionality is preserved for authorized users
- [ ] i18n coverage for all new/changed error messages

## 6. Test File References

**Backend Tests:**
- [backend/tests/api/](../../backend/tests/api/)
- [backend/tests/integration/](../../backend/tests/integration/)
- [backend/tests/core/](../../backend/tests/core/)
- [backend/tests/services/](../../backend/tests/services/)
- [backend/tests/unit/](../../backend/tests/unit/)

**Frontend Tests:**
- [frontend/src/__tests__/permissionsApi.test.ts](../../frontend/src/__tests__/permissionsApi.test.ts)
- [frontend/src/__tests__/AppShell.test.tsx](../../frontend/src/__tests__/AppShell.test.tsx)
- [frontend/src/__tests__/AgentManagementPage.test.tsx](../../frontend/src/__tests__/AgentManagementPage.test.tsx)
- [frontend/src/__tests__/McpHubPage.test.tsx](../../frontend/src/__tests__/McpHubPage.test.tsx)
- [frontend/src/__tests__/RolesPage.test.tsx](../../frontend/src/__tests__/RolesPage.test.tsx)
- [frontend/src/__tests__/UsersPage.test.tsx](../../frontend/src/__tests__/UsersPage.test.tsx)

**E2E Tests:**
- [e2e/tests/permissions.spec.ts](../../e2e/tests/permissions.spec.ts)
- [e2e/tests/agent-management.spec.ts](../../e2e/tests/agent-management.spec.ts)
- [e2e/tests/mcp-hub.spec.ts](../../e2e/tests/mcp-hub.spec.ts)
- [e2e/tests/skills-sops.spec.ts](../../e2e/tests/skills-sops.spec.ts)
- [e2e/tests/scheduling.spec.ts](../../e2e/tests/scheduling.spec.ts)
- [e2e/tests/notifications.spec.ts](../../e2e/tests/notifications.spec.ts)
- [e2e/tests/conversations.spec.ts](../../e2e/tests/conversations.spec.ts)
- [e2e/tests/results.spec.ts](../../e2e/tests/results.spec.ts)
