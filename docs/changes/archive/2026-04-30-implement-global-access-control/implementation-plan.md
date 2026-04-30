# Implementation Plan: implement-global-access-control

## Overview

This change enforces the existing `require_permission` FastAPI dependency factory across all resource-managing API modules that currently lack access control, using the infrastructure already established in `backend/app/api/deps.py` and `backend/app/services/permissions/permission_engine.py`. Audit logging is added to `PermissionEngine.authorize()` to satisfy compliance requirements, and the frontend permission-denied UX is extended with contextual "Request Access" pathways matching the approved prototype.

## Task Checklist

### Phase 1 — Backend: Resource Endpoint Permission Enforcement

- [x] 1.1 — Add `require_permission` to `agents.py` endpoints
- [x] 1.2 — Add `require_permission` to `mcp_hub.py` endpoints
- [x] 1.3 — Add `require_permission` to `skills.py` and `sops.py` endpoints
- [x] 1.4 — Add `require_permission` to `scheduling.py` endpoints
- [x] 1.5 — Add `require_permission` to `notifications.py` endpoints
- [x] 1.6 — Add `require_permission` to `conversations.py` endpoints
- [x] 1.7 — Register `RT_RESULT`; add `require_permission` to `results.py`
- [x] 1.8 — Standardize `user_access_requests.py` permission checks

### Phase 2 — Backend: Audit Logging

- [x] 2.1 — Add structured audit log emission to `PermissionEngine.authorize()`
- [x] 2.2 — Add OTEL span attributes for permission check outcomes

### Phase 3 — Frontend: Permission Error UX

- [x] 3.1 — Add "Request Access" action to `PermissionErrorSnackbar`
- [x] 3.2 — Add `RequestPermissionModal` component
- [x] 3.3 — Add `AccessDeniedPage` component for route-level denials
- [x] 3.4 — Add i18n keys for permission error and access denied strings

### Phase 4 — Validation

- [x] 4.1 — Write backend unit tests for agents, mcp_hub, skills permission enforcement
- [x] 4.2 — Write backend unit tests for scheduling, notifications, conversations, results
- [x] 4.3 — Run full test suite; verify zero regressions

### Phase 5 — Frontend: Group-Role Assignment & Error Handling

- [x] 5.1 — Add `useGroupRoles`, `useAssignGroupRole`, `useRemoveGroupRole` hooks to `usePermissions.ts`
- [x] 5.2 — Add `ManageGroupRolesModal` component and wire into `GroupsPage`
- [x] 5.3 — Fix error handling in `UsersPage`, `RolesPage`, `AccessRequestsPage` to show actual error details
- [x] 5.4 — Add i18n keys for group-role assignment UI and error display strings

---

## Phase 1 — Backend: Resource Endpoint Permission Enforcement

### Task 1.1 — Add `require_permission` to `agents.py` endpoints

All `AgentTypeRouter` and `AgentInstanceRouter` endpoints must enforce permissions via `Depends(require_permission(...))`. The existing partial implementation on the DELETE handler (direct inline `PermissionEngine` call with a `platform_user_id` conditional) must be removed and replaced.

Endpoint-to-permission mapping:

| Endpoint | Resource Type | Action |
|----------|---------------|--------|
| `GET /agents/types` | `agent` | `read` |
| `POST /agents/types` | `agent` | `create` |
| `GET /agents/types/{id}` | `agent` | `read` |
| `PUT /agents/types/{id}` | `agent` | `update` |
| `DELETE /agents/types/{id}` | `agent` | `delete` |
| `GET /agents/types/{id}/instances` | `agent` | `read` |
| `DELETE /agents/instances/{id}` | `agent` | `execute` |

Import `require_permission` from `app.api.deps`. Remove the `get_permission_engine` import and the `Request` + `Depends(get_permission_engine)` parameters from the DELETE handler.

**Done when:** All 7 agent endpoints carry `Depends(require_permission(...))`. Calling any endpoint without a matching allow policy returns HTTP 403 with a `PermissionDeniedDetail` body. The inline `engine.authorize()` block is removed from the DELETE handler.

---

### Task 1.2 — Add `require_permission` to `mcp_hub.py` endpoints

All `McpServerRouter`, `McpSessionRouter`, and `McpToolRouter` endpoints must enforce permissions.

Endpoint-to-permission mapping:

| Endpoint | Resource Type | Action |
|----------|---------------|--------|
| `GET /mcp/servers` | `mcp_server` | `read` |
| `POST /mcp/servers` | `mcp_server` | `create` |
| `GET /mcp/servers/{id}` | `mcp_server` | `read` |
| `PUT /mcp/servers/{id}` | `mcp_server` | `update` |
| `DELETE /mcp/servers/{id}` | `mcp_server` | `delete` |
| `POST /mcp/servers/{id}/sync` | `mcp_server` | `execute` |
| MCP session CRUD | `mcp_server` | `manage` |
| Tool permission CRUD | `mcp_server` | `manage` |

**Done when:** All McpHub endpoints carry `Depends(require_permission(...))`. Unauthorized requests return HTTP 403 with a structured `PermissionDeniedDetail` body.

---

### Task 1.3 — Add `require_permission` to `skills.py` and `sops.py` endpoints

All `SkillRouter` endpoints in `skills.py` and all `SopRouter` endpoints in `sops.py` must enforce permissions. SOPs are a composition of skills and share the `RT_SKILL` resource type.

Endpoint-to-permission mapping:

| Endpoint | Resource Type | Action |
|----------|---------------|--------|
| `GET /skills` | `skill` | `read` |
| `POST /skills` | `skill` | `create` |
| `GET /skills/{id}` | `skill` | `read` |
| `PUT /skills/{id}` | `skill` | `update` |
| `DELETE /skills/{id}` | `skill` | `delete` |
| `GET /sops` | `skill` | `read` |
| `POST /sops` | `skill` | `create` |
| `GET /sops/{id}` | `skill` | `read` |
| `PUT /sops/{id}` | `skill` | `update` |
| `DELETE /sops/{id}` | `skill` | `delete` |
| SOP step sub-endpoints | `skill` | `update` |

**Done when:** All skill and SOP endpoints carry `Depends(require_permission(...))`. Unauthorized requests return HTTP 403.

---

### Task 1.4 — Add `require_permission` to `scheduling.py` endpoints

All `ScheduleRouter` endpoints must enforce permissions, including pause and resume actions.

Endpoint-to-permission mapping:

| Endpoint | Resource Type | Action |
|----------|---------------|--------|
| `GET /schedules` | `scheduling` | `read` |
| `POST /schedules` | `scheduling` | `create` |
| `GET /schedules/{id}` | `scheduling` | `read` |
| `PUT /schedules/{id}` | `scheduling` | `update` |
| `DELETE /schedules/{id}` | `scheduling` | `delete` |
| `POST /schedules/{id}/pause` | `scheduling` | `update` |
| `POST /schedules/{id}/resume` | `scheduling` | `update` |
| `GET /schedules/{id}/executions` | `scheduling` | `read` |

**Done when:** All schedule endpoints carry `Depends(require_permission(...))`. Unauthorized requests return HTTP 403.

---

### Task 1.5 — Add `require_permission` to `notifications.py` endpoints

All `NotificationRouter` endpoints must enforce permissions.

Endpoint-to-permission mapping:

| Endpoint | Resource Type | Action |
|----------|---------------|--------|
| `GET /notifications/channels` | `notification` | `read` |
| `POST /notifications/channels` | `notification` | `manage` |
| `GET /notifications/channels/{id}` | `notification` | `read` |
| `PUT /notifications/channels/{id}` | `notification` | `manage` |
| `DELETE /notifications/channels/{id}` | `notification` | `manage` |
| `POST /notifications/channels/{id}/test` | `notification` | `manage` |
| `GET /notifications/events` | `notification` | `read` |

**Done when:** All notification endpoints carry `Depends(require_permission(...))`. Unauthorized requests return HTTP 403.

---

### Task 1.6 — Add `require_permission` to `conversations.py` endpoints

Both read-only `ConversationRouter` endpoints must enforce permissions.

Endpoint-to-permission mapping:

| Endpoint | Resource Type | Action |
|----------|---------------|--------|
| `GET /conversations` | `conversation` | `read` |
| `GET /conversations/{session_id}` | `conversation` | `read` |

**Done when:** Both conversation endpoints carry `Depends(require_permission(...))`. Unauthorized requests return HTTP 403.

---

### Task 1.7 — Register `RT_RESULT`; add `require_permission` to `results.py`

Add `RT_RESULT = "result"` constant and a manifest entry with actions `["read"]` to `backend/app/core/resource_types.py`. Apply the new type to `ResultRouter`.

Endpoint-to-permission mapping:

| Endpoint | Resource Type | Action |
|----------|---------------|--------|
| `GET /results` | `result` | `read` |
| `GET /results/{result_id}` | `result` | `read` |

**Done when:** `RT_RESULT` exists in `ResourceTypeManifest` with `actions: ["read"]`. Both result endpoints carry `Depends(require_permission(...))`. Unauthorized requests return HTTP 403.

---

### Task 1.8 — Standardize `user_access_requests.py` permission checks

The `AccessRequestsRouter` uses an ad-hoc `_has_permission()` helper function that calls `PermissionEngine` directly with conditional logic. Admin-only endpoints must be refactored to use `Depends(require_permission(...))`.

Endpoint-to-permission mapping for standardization:

| Endpoint | Resource Type | Action |
|----------|---------------|--------|
| `GET /user-access-requests/pending` | `access_request` | `read` |
| `PATCH /user-access-requests/{id}/approve` | `access_request` | `approve` |
| `PATCH /user-access-requests/{id}/reject` | `access_request` | `reject` |

User-facing endpoints (`POST /user-access-requests`, `GET /user-access-requests/my`) remain guarded only by JWT authentication — any authenticated platform user may submit a request.

Remove the `_has_permission` helper function entirely.

**Done when:** All admin endpoints use `Depends(require_permission(...))`. The `_has_permission` helper is deleted from the module. User create/list-my endpoints remain accessible to any authenticated user.

---

## Phase 2 — Backend: Audit Logging

### Task 2.1 — Add structured audit log emission to `PermissionEngine.authorize()`

Add a `logger.info(...)` call at the end of `PermissionEngine.authorize()`, after the final allow/deny determination, emitting a structured log record with these fields:

- `event`: `"permission_check"`
- `user_id`: caller's UUID (as string)
- `module`: resource type string
- `action`: action string
- `resource_id`: resource_id parameter
- `allowed`: boolean result
- `reason`: reason string from `AuthorizationResult`

Use a dict-style argument compatible with the project's existing structlog or standard-library structured logging pattern.

**Done when:** Every call to `PermissionEngine.authorize()` emits one log entry containing all six fields, for both allow and deny outcomes. The `event` field is always `"permission_check"`.

---

### Task 2.2 — Add OTEL span attributes for permission check outcomes

Within `PermissionEngine.authorize()`, obtain the active span via `opentelemetry.trace.get_current_span()` and set these attributes before returning:

- `permission.user_id`
- `permission.module`
- `permission.action`
- `permission.resource_id`
- `permission.allowed`

Import `opentelemetry.trace` only if it is already a project dependency (it is — see `backend/app/core/telemetry.py`). Guard with a no-op if no active span is present.

**Done when:** OTEL traces for any guarded endpoint include `permission.*` attributes on the span that encompasses the handler. Attribute values match the `AuthorizationResult`.

---

## Phase 3 — Frontend: Permission Error UX

### Task 3.1 — Add "Request Access" action to `PermissionErrorSnackbar`

Extend `PermissionErrorSnackbar` (at `frontend/src/components/permissions/PermissionErrorSnackbar.tsx`) with:

- A `permissionContext: RequiredPermission | null` state field alongside the existing `open` and `message` fields
- The event handler stores the full `PermissionDeniedDetail` in state, not just the formatted message string
- The `<Alert>` action prop renders a "Request Access" button; clicking it sets `RequestPermissionModal` open with the stored context
- `RequestPermissionModal` is rendered conditionally within the component

**Done when:** The snackbar renders a "Request Access" action button when a 403 event fires. Clicking it opens `RequestPermissionModal` with `resource_type`, `action`, and `resource_id` pre-filled from the event context.

---

### Task 3.2 — Add `RequestPermissionModal` component

Create `frontend/src/components/permissions/RequestPermissionModal.tsx`.

Props:
- `open: boolean`
- `onClose: () => void`
- `permissionContext: RequiredPermission | null`

Behaviour:
- Displays `resource_type`, `action`, and `resource_id` as read-only fields (disabled text inputs or styled read-only display)
- Collects a business justification via a textarea (required)
- On submit, calls `submitAccessRequest()` from `frontend/src/api/permissionsApi.ts` with the justification; the resource context is appended to the justification string since the current API accepts group IDs + justification
- Shows an inline success message on successful submission, then closes after a short delay
- All strings must use `t()` from i18next

**Done when:** The modal renders with pre-filled context. Submitting with a justification calls `submitAccessRequest`, shows a success state, and closes. All visible strings use `t()`. Empty justification is prevented with a validation error.

---

### Task 3.3 — Add `AccessDeniedPage` component for route-level denials

Create `frontend/src/pages/AccessDeniedPage.tsx`.

This full-page component is displayed when a page load results in a 403 with `PermissionDeniedDetail`. It renders:
- A structured error card matching the prototype: red icon, "Access Denied" heading, resource type / action / resource ID detail rows
- "Request Access" button — opens `RequestPermissionModal` with the denial context
- "Return to Dashboard" button — navigates to `/`

The component reads permission context from `useLocation().state` (populated by the 403 handler) or from props if rendered directly. Register the page in `AppRouter.tsx` at a `/access-denied` route.

**Done when:** Navigating to `/access-denied` with router state containing a `RequiredPermission` renders the full-page error with correct context. Both action buttons function correctly. All strings use `t()`.

---

### Task 3.4 — Add i18n keys for permission error and access denied strings

Add the following keys to `frontend/src/i18n/locales/en.json` under `permissions.errors`:

| Key | Value |
|-----|-------|
| `missingPermission` | `"Permission denied: you need '{{action}}' on {{resource_type}} (ID: {{resource_id}})"` |
| `requestAccessButton` | `"Request Access"` |
| `accessDeniedTitle` | `"Access Denied"` |
| `accessDeniedMessage` | `"You do not have the required permissions to access this resource."` |
| `returnToDashboard` | `"Return to Dashboard"` |
| `resourceType` | `"Resource Type"` |
| `action` | `"Action"` |
| `resourceId` | `"Resource ID"` |
| `requestModalTitle` | `"Request Elevated Access"` |
| `requestJustificationLabel` | `"Business Justification"` |
| `requestJustificationPlaceholder` | `"Describe why you need this permission to perform your duties..."` |
| `requestJustificationRequired` | `"A justification is required"` |
| `requestSubmittedSuccess` | `"Your access request has been submitted."` |

**Done when:** All keys are present under `permissions.errors` in `en.json`. No hardcoded English strings exist in the new components. Pre-existing keys under `permissions.*` are unchanged.

---

## Phase 4 — Validation

### Task 4.1 — Write backend unit tests for agents, mcp_hub, skills permission enforcement

Permission enforcement for `agents.py`, `mcp_hub.py`, `skills.py`, and `sops.py` is covered via unit tests in `backend/tests/unit/`. `test_permission_engine.py` validates `PermissionEngine.authorize()` deny and allow scenarios against mock DB fixtures (no roles → deny; matching allow policy → allow; action mismatch → deny; tag condition mismatch → deny). `test_resource_type_manifest.py` validates all `RT_*` constants including `RT_AGENT`, `RT_MCP_SERVER`, and `RT_SKILL` are present in the manifest with expected actions.

**Done when:** All unit test functions in `test_permission_engine.py` and `test_resource_type_manifest.py` pass. Deny and allow scenarios are covered for `PermissionEngine.authorize()`.

---

### Task 4.2 — Write backend unit tests for scheduling, notifications, conversations, results

Same unit test coverage as Task 4.1. `test_resource_type_manifest.py` includes `RT_SCHEDULING`, `RT_NOTIFICATION`, `RT_CONVERSATION`, and `RT_RESULT` in the manifest validation suite, confirming each constant is registered and its action list is non-empty.

**Done when:** All unit test functions pass. `RT_RESULT` is present in `ResourceTypeManifest` and passes manifest structure validation.

---

### Task 4.3 — Run full test suite; verify zero regressions

Run the full backend test suite (`pytest backend/tests/`) and the frontend test suite (`npm test` in `frontend/`). All pre-existing tests must continue to pass.

**Done when:** Backend test suite exits with 0 failures and 0 errors. Frontend test suite exits with 0 failures. No pre-existing tests are newly broken.

### Phase 5 — Frontend: Group-Role Assignment & Error Handling

- [x] 5.1 — Add `useGroupRoles`, `useAssignGroupRole`, `useRemoveGroupRole` hooks to `usePermissions.ts`
- [x] 5.2 — Add `ManageGroupRolesModal` component and wire into `GroupsPage`
- [x] 5.3 — Fix error handling in `UsersPage`, `RolesPage`, `AccessRequestsPage` to show actual error details
- [x] 5.4 — Add i18n keys for group-role assignment UI and error display strings

---

## Phase 5 — Frontend: Group-Role Assignment & Error Handling

### Task 5.1 — Add `useGroupRoles`, `useAssignGroupRole`, `useRemoveGroupRole` hooks to `usePermissions.ts`

The API functions `listGroupRoles`, `assignGroupRole`, and `removeGroupRole` already exist in `frontend/src/api/permissionsApi.ts` but have no corresponding React Query hooks. Add to `frontend/src/hooks/usePermissions.ts`:

- **`useGroupRoles(groupId: string | null)`** — `useQuery` with key `['group-roles', groupId]`; enabled only when `groupId` is non-null; calls `listGroupRoles(groupId)`.
- **`useAssignGroupRole()`** — `useMutation`; calls `assignGroupRole(groupId, roleId)`; on success invalidates `['group-roles', groupId]`.
- **`useRemoveGroupRole()`** — `useMutation`; calls `removeGroupRole(groupId, roleId)`; on success invalidates `['group-roles', groupId]`.

**Done when:** All three hooks are exported from `usePermissions.ts` and their TypeScript types are consistent with `Role` from `../../types/permissions`.

---

### Task 5.2 — Add `ManageGroupRolesModal` component and wire into `GroupsPage`

Create `frontend/src/components/permissions/ManageGroupRolesModal.tsx`.

Props:
- `open: boolean`
- `onClose: () => void`
- `group: Group | null`

Behaviour:
- Uses `useGroupRoles(group?.id ?? null)` to load current assigned roles; shows `CircularProgress` while loading and an error alert (with actual message via `extractErrorMessage`) on failure.
- Displays each assigned role as a `Chip` with a delete icon; clicking the delete icon calls `useRemoveGroupRole` to remove that role assignment.
- Provides a `Select` dropdown populated with all platform roles (`useRoles()`), filtered to exclude already-assigned roles; an "Add" button calls `useAssignGroupRole` with the selected role ID.
- All strings use `t()` from i18next.

In `GroupsPage.tsx`:
- Add a "Manage Roles" icon button (e.g. `SecurityIcon` or `AdminPanelSettingsIcon`) to each row in the groups table.
- Add a `manageRolesGroup: Group | null` state field.
- Render `<ManageGroupRolesModal open={!!manageRolesGroup} onClose={() => setManageRolesGroup(null)} group={manageRolesGroup} />` at the bottom of the component.

**Done when:** Clicking "Manage Roles" on any group row opens the modal. Roles can be added and removed. The modal shows live-updated role list after each mutation. All strings use `t()`.

---

### Task 5.3 — Fix error handling in `UsersPage`, `RolesPage`, `AccessRequestsPage` to show actual error details

Create `frontend/src/utils/errorUtils.ts` with:

```
export function extractErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object') {
    const axiosDetail = (error as any)?.response?.data?.detail
    if (typeof axiosDetail === 'string' && axiosDetail) return axiosDetail
    const msg = (error as any)?.message
    if (typeof msg === 'string' && msg) return msg
  }
  return fallback
}
```

Update error alert rendering in `UsersPage`, `RolesPage`, and `AccessRequestsPage`:

- Replace `{error && <Alert severity="error">{t('app.error')}</Alert>}` with `{error && <Alert severity="error">{extractErrorMessage(error, t('app.error'))}</Alert>}` in every data-loading error display.
- Apply the same pattern to inline mutation error states where generic messages are currently shown.
- Also apply to `GroupsPage` error display for consistency.

**Done when:** When a data load fails (network error, 403, 404, server validation message), the alert shows the actual error text. When no detail is available, the generic `t('app.error')` fallback is shown. No hardcoded English strings are introduced.

---

### Task 5.4 — Add i18n keys for group-role assignment UI and error display strings

Add the following keys to `frontend/src/i18n/locales/en.json` under `permissions.groups`:

| Key | Value |
|-----|-------|
| `manageRoles` | `"Manage Roles"` |
| `manageRolesTitle` | `"Manage Roles — {{groupName}}"` |
| `assignedRoles` | `"Assigned Roles"` |
| `addRole` | `"Add Role"` |
| `selectRole` | `"Select a role"` |
| `noRolesAssigned` | `"No roles assigned to this group."` |
| `roleAlreadyAssigned` | `"This role is already assigned to the group."` |

**Done when:** All keys are present under `permissions.groups` in `en.json`. All new strings in `ManageGroupRolesModal` and the updated `GroupsPage` use `t()`. No hardcoded English strings exist in the new or changed components.

---

## Completion Checklist

- [x] All resource-managing backend endpoints (`agents`, `mcp_hub`, `skills`, `sops`, `scheduling`, `notifications`, `conversations`, `results`) enforce `Depends(require_permission(...))` on every route
- [x] Legacy inline `PermissionEngine` call and `get_permission_engine` import removed from `agents.py` DELETE handler
- [x] `user_access_requests.py` admin endpoints use `Depends(require_permission(...))`; `_has_permission` helper deleted
- [x] `RT_RESULT` constant and manifest entry added to `backend/app/core/resource_types.py`
- [x] `PermissionEngine.authorize()` emits a `permission_check` structured log entry on every invocation
- [x] `PermissionEngine.authorize()` sets `permission.*` OTEL span attributes on every invocation
- [x] `PermissionErrorSnackbar` includes a "Request Access" action button that opens `RequestPermissionModal`
- [x] `RequestPermissionModal` component created; submits access request with permission context in justification
- [x] `AccessDeniedPage` created and registered at `/access-denied` in `AppRouter.tsx`
- [x] All new frontend strings added to `permissions.errors` namespace in `en.json`; no hardcoded strings in new components
- [x] Backend tests cover deny and allow scenarios for all newly guarded endpoint modules
- [x] Full backend and frontend test suites pass with zero regressions
- [x] `useGroupRoles`, `useAssignGroupRole`, `useRemoveGroupRole` hooks added to `usePermissions.ts`
- [x] `ManageGroupRolesModal` component created; "Manage Roles" button wired into `GroupsPage` table rows
- [x] `extractErrorMessage` utility created in `frontend/src/utils/errorUtils.ts`
- [x] `UsersPage`, `RolesPage`, `AccessRequestsPage`, and `GroupsPage` error alerts show actual error details via `extractErrorMessage`
- [x] All new strings for group-role assignment UI added to `permissions.groups` namespace in `en.json`; no hardcoded English strings in new or changed components
