# Technical Specification: implement-global-access-control

## Technical Overview

The change applies the existing `require_permission` FastAPI dependency factory (already used by the permissions module) uniformly across the five resource-managing API modules (`agents`, `mcp_hub`, `skills/sops`, `scheduling`, `notifications`) and two read-only modules (`conversations`, `results`) that currently lack access control. A new `RT_RESULT` resource type is registered in the manifest. Audit logging and OTEL instrumentation are added to `PermissionEngine.authorize()`. On the frontend, the existing permission-denied infrastructure (API interceptor, `PermissionErrorSnackbar`, `permissionError.ts`) is extended with a "Request Access" pathway and a full-page `AccessDeniedPage` component, both conforming to the approved prototype.

## Component Breakdown

### Backend: Permission Enforcement Infrastructure (existing — no structural changes)

- **`require_permission(module, action)`** — Cached dependency factory. On each request: resolves the calling user's `PlatformUser` record by `sub` claim, calls `PermissionEngine.authorize()`, and raises `HTTPException(403, PermissionDeniedDetail.model_dump())` on denial. Returns JWT claims dict on success. Keyed by `(module, action)` pair for `dependency_overrides` compatibility in tests.
- **`PermissionEngine`** — Deny-by-default IAM-style evaluator. Validates module/action against `ResourceTypeManifest`, loads the caller's effective role IDs (direct `UserRole` + group-inherited `GroupRole`), fetches matching `PolicyStatement` rows, and evaluates each allow statement's action list, resource-ID patterns (exact or wildcard), and tag conditions. Returns `AuthorizationResult(allowed, reason)`.
- **`PermissionDeniedDetail` / `RequiredPermission`** — Pydantic models that define the structured 403 response body. Consumed by the frontend's `parsePermissionError()` utility.
- **`ResourceTypeManifest`** — Python dict keyed by resource type string; maps each type to its allowed action list. Used by `PermissionEngine` for fast-fail validation on unknown types/actions.

### Backend: Resource Endpoint Modules (permission enforcement being added)

| Module File | Router(s) | Current State |
|-------------|-----------|---------------|
| `backend/app/api/v1/agents.py` | `AgentTypeRouter`, `AgentInstanceRouter` | DELETE only, inline pattern (non-standard) |
| `backend/app/api/v1/mcp_hub.py` | `McpServerRouter`, `McpSessionRouter`, `McpToolRouter` | No guards |
| `backend/app/api/v1/skills.py` | `SkillRouter` | No guards |
| `backend/app/api/v1/sops.py` | `SopRouter` | No guards |
| `backend/app/api/v1/scheduling.py` | `ScheduleRouter` | No guards |
| `backend/app/api/v1/notifications.py` | `NotificationRouter` | No guards |
| `backend/app/api/v1/conversations.py` | `ConversationRouter` | No guards |
| `backend/app/api/v1/results.py` | `ResultRouter` | No guards; RT_RESULT not yet registered |
| `backend/app/api/v1/user_access_requests.py` | `AccessRequestsRouter` | Inline `_has_permission` helper (non-standard) |

### Backend: Audit Logging Extension

- **`PermissionEngine.authorize()`** — Extended to emit one structured log record per call (both allow and deny) and to set `permission.*` attributes on the active OTEL span. No interface changes.

### Frontend: Permission Error UX (partially existing, partially new)

| Component / Utility | Status | Purpose |
|--------------------|--------|---------|
| `apiClient` interceptor | Existing — no change | Detects 403, calls `parsePermissionError`, dispatches `parthenon:permissionDenied` event |
| `parsePermissionError` | Existing — no change | Extracts `PermissionDeniedDetail` from Axios 403 error |
| `dispatchPermissionDeniedEvent` | Existing — no change | Fires custom DOM event carrying `PermissionDeniedDetail` |
| `PermissionErrorSnackbar` | Existing — extended | Adds "Request Access" action button; stores full `PermissionDeniedDetail` context in state |
| `RequestPermissionModal` | **New** | Pre-fills resource/action/id context; collects justification; submits access request |
| `AccessDeniedPage` | **New** | Full-page route-level denial view; mirrors prototype error-state card design |
| i18n `permissions.errors.*` keys | **New** | String keys for all new and extended UI text |

### Frontend: Group-Role Assignment UI (new)

The `GroupsPage` currently supports creating groups (with initial role assignments via `role_ids` in the creation body) but has no UI for adding or removing roles on an existing group. The backend endpoints for this already exist with proper permission guards:

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /api/v1/user-groups/{id}/roles` | `permissions:manage` or group owner | List roles currently assigned to a group |
| `POST /api/v1/user-groups/{id}/roles` | `permissions:manage` | Assign a role to a group |
| `DELETE /api/v1/user-groups/{id}/roles/{role_id}` | `permissions:manage` | Remove a role from a group |

The frontend API functions (`listGroupRoles`, `assignGroupRole`, `removeGroupRole`) already exist in `permissionsApi.ts` but the corresponding React Query hooks and the management UI are missing.

- **`useGroupRoles(groupId)`** — `useQuery` hook; fetches the role list for a given group. Enabled only when `groupId` is non-null.
- **`useAssignGroupRole()`** — `useMutation` hook; calls `assignGroupRole`; invalidates the group roles query on success.
- **`useRemoveGroupRole()`** — `useMutation` hook; calls `removeGroupRole`; invalidates the group roles query on success.
- **`ManageGroupRolesModal`** — New component rendered within `GroupsPage`. Opens via a "Manage Roles" icon button in the groups table. Displays the group's current roles as removable chips and provides a dropdown to add any platform role not yet assigned. All strings use `t()`.

### Frontend: Error Handling Approach (improvement)

Currently `UsersPage`, `RolesPage`, and `AccessRequestsPage` display a generic `t('app.error')` string when a data-loading query fails. This obscures the actual problem (network error, 403, 404, backend validation message, etc.).

The improved pattern extracts the real error message before falling back to the generic key:

- For Axios errors: read `error.response.data.detail` (FastAPI error body) if present.
- For generic `Error` objects: use `error.message`.
- Fall back to `t('app.error')` only when neither is available.

A shared utility function `extractErrorMessage(error: unknown, fallback: string): string` is added to `frontend/src/utils/errorUtils.ts` and used consistently across `UsersPage`, `RolesPage`, `AccessRequestsPage`, and `GroupsPage` error alerts.

## API Changes

No new endpoints are introduced. All changes below add a `Depends(require_permission(...))` parameter to existing handlers — the request/response schema is unchanged for authorized callers. Unauthorized callers receive HTTP 403 with the body format below.

**Standard 403 response body (all guarded endpoints):**
```
{
  "detail": "<reason>",
  "required_permission": {
    "resource_type": "<module>",
    "action": "<action>",
    "resource_id": null
  }
}
```

### Agents (`RT_AGENT`)

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/v1/agents/types` | `read` |
| POST | `/api/v1/agents/types` | `create` |
| GET | `/api/v1/agents/types/{id}` | `read` |
| PUT | `/api/v1/agents/types/{id}` | `update` |
| DELETE | `/api/v1/agents/types/{id}` | `delete` |
| GET | `/api/v1/agents/types/{id}/instances` | `read` |
| DELETE | `/api/v1/agents/instances/{id}` | `execute` |

### MCP Hub (`RT_MCP_SERVER`)

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/v1/mcp/servers` | `read` |
| POST | `/api/v1/mcp/servers` | `create` |
| GET | `/api/v1/mcp/servers/{id}` | `read` |
| PUT | `/api/v1/mcp/servers/{id}` | `update` |
| DELETE | `/api/v1/mcp/servers/{id}` | `delete` |
| POST | `/api/v1/mcp/servers/{id}/sync` | `execute` |
| MCP session CRUD | `/api/v1/mcp/servers/{id}/sessions/…` | `manage` |
| Tool permission CRUD | `/api/v1/mcp/servers/{id}/tools/…` | `manage` |

### Skills and SOPs (`RT_SKILL`)

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/v1/skills` | `read` |
| POST | `/api/v1/skills` | `create` |
| GET | `/api/v1/skills/{id}` | `read` |
| PUT | `/api/v1/skills/{id}` | `update` |
| DELETE | `/api/v1/skills/{id}` | `delete` |
| GET | `/api/v1/sops` | `read` |
| POST | `/api/v1/sops` | `create` |
| GET | `/api/v1/sops/{id}` | `read` |
| PUT | `/api/v1/sops/{id}` | `update` |
| DELETE | `/api/v1/sops/{id}` | `delete` |
| SOP step sub-endpoints | `/api/v1/sops/{id}/steps/…` | `update` |

### Scheduling (`RT_SCHEDULING`)

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/v1/schedules` | `read` |
| POST | `/api/v1/schedules` | `create` |
| GET | `/api/v1/schedules/{id}` | `read` |
| PUT | `/api/v1/schedules/{id}` | `update` |
| DELETE | `/api/v1/schedules/{id}` | `delete` |
| POST | `/api/v1/schedules/{id}/pause` | `update` |
| POST | `/api/v1/schedules/{id}/resume` | `update` |
| GET | `/api/v1/schedules/{id}/executions` | `read` |

### Notifications (`RT_NOTIFICATION`)

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/v1/notifications/channels` | `read` |
| POST | `/api/v1/notifications/channels` | `manage` |
| GET | `/api/v1/notifications/channels/{id}` | `read` |
| PUT | `/api/v1/notifications/channels/{id}` | `manage` |
| DELETE | `/api/v1/notifications/channels/{id}` | `manage` |
| POST | `/api/v1/notifications/channels/{id}/test` | `manage` |
| GET | `/api/v1/notifications/events` | `read` |

### Conversations (`RT_CONVERSATION`)

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/v1/conversations` | `read` |
| GET | `/api/v1/conversations/{id}` | `read` |

### Results (`RT_RESULT` — new resource type)

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/v1/results` | `read` |
| GET | `/api/v1/results/{id}` | `read` |

### Access Requests — admin endpoints standardized (`RT_ACCESS_REQUEST`)

| Method | Path | Action | Before |
|--------|------|--------|--------|
| GET | `/api/v1/user-access-requests/pending` | `read` | Inline `_has_permission` helper |
| PATCH | `/api/v1/user-access-requests/{id}/approve` | `approve` | Inline `_has_permission` helper |
| PATCH | `/api/v1/user-access-requests/{id}/reject` | `reject` | Inline `_has_permission` helper |

User-facing endpoints (`POST /user-access-requests`, `GET /user-access-requests/my`) require only JWT authentication — no additional permission check.

## State Management

No new global stores or context providers are introduced.

- **`PermissionErrorSnackbar`** local state gains a `permissionContext: RequiredPermission | null` field alongside existing `open: boolean` and `message: string`. The event handler stores the full `PermissionDeniedDetail` so the "Request Access" button can pass context to `RequestPermissionModal`.
- **`RequestPermissionModal`** is fully controlled via props (`open`, `onClose`, `permissionContext`). Internal state manages the justification textarea value, submission loading state, and success/error feedback.
- **`AccessDeniedPage`** reads permission context from `useLocation().state` (a `RequiredPermission` object placed in router state by the 403 handler when navigating to `/access-denied`). No component state beyond modal open/close.

## Data Access Patterns

| Layer | Pattern | Rationale |
|-------|---------|-----------|
| Backend permission check | `PermissionEngine.authorize(db, user_id, module, action, ...)` called via `require_permission` dependency before handler logic executes | Single authoritative gate per request; deny-by-default semantics; no handler code paths reachable without authorization |
| Permission engine DB reads | Async SQLAlchemy: `UserRole`, `GroupRole`, `PolicyStatement`, `PolicyAction`, `PolicyResource`, `PolicyTagCondition` loaded per request | Real-time policy evaluation; no cache prevents stale-allow after role removal |
| Audit logging | `logger.info()` structured record in `PermissionEngine.authorize()` — written synchronously before return | Guarantees every check is logged regardless of handler outcome |
| OTEL span attributes | `opentelemetry.trace.get_current_span().set_attribute(...)` in `PermissionEngine.authorize()` | Correlates permission outcomes with distributed traces; uses existing instrumentation |
| Frontend 403 handling | Axios response interceptor → `parsePermissionError` → `dispatchPermissionDeniedEvent` → `PermissionErrorSnackbar` listens via `window.addEventListener` | Decouples per-page error handling from global denial UX; no prop drilling through route tree |
| Access request submission | `submitAccessRequest()` → `POST /api/v1/user-access-requests` (existing endpoint) | No new API surface; permission context is embedded in the justification string |

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PermissionEngine` | class | IAM-style policy evaluator; deny-by-default | `backend/app/services/permissions/permission_engine.py` |
| `PermissionEngine.authorize` | method | Evaluates allow/deny for user + module + action + resource_id; emits audit log and OTEL attributes | `backend/app/services/permissions/permission_engine.py` |
| `AuthorizationResult` | dataclass | Return type of `PermissionEngine.authorize`; carries `allowed` and `reason` | `backend/app/services/permissions/permission_engine.py` |
| `require_permission` | function | FastAPI dependency factory keyed by `(module, action)`; raises HTTP 403 on denial | `backend/app/api/deps.py` |
| `get_current_claims` | function | Extracts decoded JWT claims from `request.state.identity` | `backend/app/api/deps.py` |
| `PermissionDeniedDetail` | Pydantic model | Structured 403 response body | `backend/app/schemas/errors.py` |
| `RequiredPermission` | Pydantic model | Nested model inside `PermissionDeniedDetail`; carries resource_type, action, resource_id | `backend/app/schemas/errors.py` |
| `ResourceTypeManifest` | dict | Registry of valid resource type + action combinations; used by `PermissionEngine` for manifest validation | `backend/app/core/resource_types.py` |
| `RT_AGENT` | constant | Resource type identifier: agents | `backend/app/core/resource_types.py` |
| `RT_MCP_SERVER` | constant | Resource type identifier: MCP servers | `backend/app/core/resource_types.py` |
| `RT_SKILL` | constant | Resource type identifier: skills and SOPs | `backend/app/core/resource_types.py` |
| `RT_SCHEDULING` | constant | Resource type identifier: scheduled jobs | `backend/app/core/resource_types.py` |
| `RT_NOTIFICATION` | constant | Resource type identifier: notification channels | `backend/app/core/resource_types.py` |
| `RT_CONVERSATION` | constant | Resource type identifier: conversation sessions | `backend/app/core/resource_types.py` |
| `RT_RESULT` | constant | Resource type identifier: result records (new) | `backend/app/core/resource_types.py` |
| `RT_ACCESS_REQUEST` | constant | Resource type identifier: access requests | `backend/app/core/resource_types.py` |
| `AgentTypeRouter` | router | Agent type CRUD endpoints | `backend/app/api/v1/agents.py` |
| `AgentInstanceRouter` | router | Agent instance lifecycle endpoints | `backend/app/api/v1/agents.py` |
| `McpServerRouter` | router | MCP server CRUD + sync endpoints | `backend/app/api/v1/mcp_hub.py` |
| `McpSessionRouter` | router | MCP session CRUD endpoints | `backend/app/api/v1/mcp_hub.py` |
| `McpToolRouter` | router | MCP tool permission CRUD endpoints | `backend/app/api/v1/mcp_hub.py` |
| `SkillRouter` | router | Skill CRUD endpoints | `backend/app/api/v1/skills.py` |
| `SopRouter` | router | SOP CRUD and step management endpoints | `backend/app/api/v1/sops.py` |
| `ScheduleRouter` | router | Scheduled job CRUD + pause/resume endpoints | `backend/app/api/v1/scheduling.py` |
| `NotificationRouter` | router | Notification channel CRUD + test + event history | `backend/app/api/v1/notifications.py` |
| `ConversationRouter` | router | Conversation session read endpoints | `backend/app/api/v1/conversations.py` |
| `ResultRouter` | router | Result record read endpoints | `backend/app/api/v1/results.py` |
| `AccessRequestsRouter` | router | Access request submission and admin review endpoints | `backend/app/api/v1/user_access_requests.py` |
| `parsePermissionError` | function | Extracts `PermissionDeniedDetail` from an Axios 403 error | `frontend/src/utils/permissionError.ts` |
| `dispatchPermissionDeniedEvent` | function | Fires `parthenon:permissionDenied` custom DOM event | `frontend/src/utils/permissionError.ts` |
| `PERMISSION_DENIED_EVENT` | constant | Custom event name for 403 denial broadcast | `frontend/src/utils/permissionError.ts` |
| `apiClient` | axios instance | HTTP client with auth header injection and 401/403 response interceptors | `frontend/src/api/apiClient.ts` |
| `submitAccessRequest` | function | Posts a new access request batch to the backend | `frontend/src/api/permissionsApi.ts` |
| `PermissionErrorSnackbar` | component | Global MUI Snackbar for 403 denial messages; mounts in `AppShell`; extended with "Request Access" button | `frontend/src/components/permissions/PermissionErrorSnackbar.tsx` |
| `RequestPermissionModal` | component | Modal: displays read-only permission context; collects justification; submits access request (new) | `frontend/src/components/permissions/RequestPermissionModal.tsx` |
| `AccessDeniedPage` | component | Full-page access denied view for route-level 403s; reads context from router state (new) | `frontend/src/pages/AccessDeniedPage.tsx` |
| `AppShell` | component | Root shell that mounts `PermissionErrorSnackbar` globally | `frontend/src/app/AppShell.tsx` |
| `AppRouter` | component | Route configuration; registers `/access-denied` route for `AccessDeniedPage` | `frontend/src/app/AppRouter.tsx` |
| `ManageGroupRolesModal` | component | Modal for viewing, adding, and removing role assignments on an existing group (new) | `frontend/src/components/permissions/ManageGroupRolesModal.tsx` |
| `useGroupRoles` | hook | React Query `useQuery` hook for fetching roles assigned to a group | `frontend/src/hooks/usePermissions.ts` |
| `useAssignGroupRole` | hook | React Query `useMutation` hook for assigning a role to a group | `frontend/src/hooks/usePermissions.ts` |
| `useRemoveGroupRole` | hook | React Query `useMutation` hook for removing a role from a group | `frontend/src/hooks/usePermissions.ts` |
| `listGroupRoles` | function | API call: GET `/user-groups/{id}/roles` — list roles assigned to a group | `frontend/src/api/permissionsApi.ts` |
| `assignGroupRole` | function | API call: POST `/user-groups/{id}/roles` — assign a role to a group | `frontend/src/api/permissionsApi.ts` |
| `removeGroupRole` | function | API call: DELETE `/user-groups/{id}/roles/{role_id}` — remove role assignment from a group | `frontend/src/api/permissionsApi.ts` |
| `extractErrorMessage` | function | Utility: extracts a human-readable message from an unknown error (Axios detail, Error.message, or fallback) | `frontend/src/utils/errorUtils.ts` |
| `GroupsPage` | component | Groups management page — extended with "Manage Roles" button and `ManageGroupRolesModal` | `frontend/src/pages/permissions/GroupsPage.tsx` |
| `UsersPage` | component | Users management page — error display updated to show actual error details | `frontend/src/pages/permissions/UsersPage.tsx` |
| `RolesPage` | component | Roles management page — error display updated to show actual error details | `frontend/src/pages/permissions/RolesPage.tsx` |
| `AccessRequestsPage` | component | Access requests page — error display updated to show actual error details | `frontend/src/pages/permissions/AccessRequestsPage.tsx` |
