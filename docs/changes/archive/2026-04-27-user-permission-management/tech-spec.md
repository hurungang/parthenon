# Tech Spec: User Permission Management

---

## 1. Technical Overview

This change introduces a **user** policy-based access control layer on top of the existing flat RBAC model, distinct from the existing agent permission system. The platform gains a User Permission Engine capable of evaluating IAM-style policy statements with tag-based conditions, a User Tag Registry for managing resource labels, a User Cache for persisting OIDC-authenticated principals, a User Group Claim Mapper for automatic group assignment via JWT claims, a User Access Request Service for self-service group join workflows, and a User Notification Hook for owner/requester alerts.

The backend exposes five new REST API router groups (`/user-tags`, `/user-roles`, `/user-groups`, `/platform-users`, `/user-access-requests`), all prefixed with `user-` to distinguish from the existing agent permission system, all requiring JWT authentication. The auth middleware is extended to run User Cache and Group Claim Mapper on every authenticated request. The frontend gains a User Permission Management module with five sub-pages routed under `/user-permissions`, backed by a Zustand store and a typed API client.

**Namespace note:** The platform has two distinct permission systems — the existing agent permission system (controls AI agent access) and this new user permission system (controls human user access). All user permission API routes use the `/user-*` prefix (e.g., `/user-roles`, `/user-groups`, `/user-tags`, `/user-access-requests`); frontend routes use `/user-permissions` as the base path.

No existing entities are modified or removed. The change is purely additive at the data layer.

---

## 2. Component Breakdown

### User Permission Engine
Evaluates authorization requests against the user's effective policy set. Given a user ID, target module, action, resource ID, and resource tags, it resolves the user's direct roles and group-inherited roles, fetches all policy statements for those roles, and applies a deny-by-default evaluation: the request is allowed only if at least one matching policy statement covers the module, action, resource scope, and all tag conditions. Returns an `AuthorizationResult` containing the decision and an audit reason string. Supports wildcard matching for resource IDs via an internal `_match_resource_id(pattern, resource_id)` method — e.g., the pattern `"support_*"` matches `"support_001"` and `"support_002"`.

### User Tag Registry
Manages `TagDefinition` and `TagValue` records. Enforces key uniqueness per scope (`global` or `resource_type`). Provides a validation method that checks a proposed tag key/value pair against the allowed values list for that definition. Used by the User Permission Engine when evaluating `PolicyTagCondition` records and by the User Tag API for CRUD operations.

### User Cache Service
Upserts a `PlatformUser` record on every successful JWT validation. On first encounter for a given OIDC subject (`sub`), creates the record with `first_seen_at` and `last_seen_at`. On subsequent encounters, updates only `last_seen_at`. Provides a lookup method used by the User Permission Engine to resolve the user's identity context.

### User Group Claim Mapper
Processes JWT group claims after User Cache write. Queries `Group` records whose `idp_claim_value` appears in the JWT claims list and creates `UserGroup` membership records for any that are missing. Safe to call on every request — will not duplicate existing memberships. Returns the list of newly assigned group IDs for observability logging.

### User Access Request Service
Manages the full lifecycle of group join requests at batch level. Handles submission via `submit_batch_request(user_id, group_ids, justification)` which creates one `AccessRequestBatch` record and one `AccessRequest` per group ID. Approval transitions the individual `AccessRequest` to `approved`, accepts an optional `reviewer_reason`, and creates a `UserGroup` record. Rejection transitions to `rejected` and requires a `reviewer_reason`. Enforces the constraint that only one pending request per user/group pair may exist at a time. Delegates notification triggers to the User Notification Hook after each state transition.

### User Notification Hook
Wraps the existing notification service to send two types of user permission-domain alerts: owner notification when a new join request is submitted (targets the group owner's `PlatformUser` record), and requester notification when their request is approved or rejected. Uses the existing in-platform notification infrastructure already present in `backend/app/services/notifications/`.

### Bootstrap Service
Runs once at application startup to ensure the platform is in a valid initial state. Checks for the existence of a `system_admin` role with `role_type = "system"` in the `Role` table; if absent, creates it with a pre-defined full-access policy set and marks it as a system role. System roles are immutable — they cannot be edited or deleted via the API. Exposed as a FastAPI startup event handler; idempotent and safe to call on every restart.

### Resource Type Manifest
A centralized constant module that defines every resource type recognized by the platform and the complete set of allowed actions for each. The backend module (`backend/app/core/resource_types.py`) is the authoritative source — it maps resource type identifiers (e.g., `agent`, `mcp_server`, `conversation`, `group`) to their permitted action sets (e.g., `read`, `write`, `delete`, `execute`). The `PermissionEngine` imports the manifest to validate that `resource_type` and `action` values in an authorization request are known before evaluation, failing fast on unrecognized inputs. All user permission API routers import resource type name constants from this module rather than using raw strings, ensuring that any resource type rename is a single-file change. A TypeScript mirror (`frontend/src/constants/resourceTypes.ts`) is derived from the same definitions and used to populate the resource type and action dropdowns in the single-dialog policy builder on the Roles page.

### Auth Middleware (Modified)
The existing JWT validation middleware is extended with two additional async calls after a successful token validation: `UserCacheService.upsert_user()` and `GroupClaimMapper.map_claims()`. Both calls are wrapped in exception handlers so that failures produce a log entry without failing the overall request. This ensures every authenticated request keeps the user record current and group memberships up to date.

### User Permission Management Frontend Module
A React module containing five page-level components under `/user-permissions`. Backed by a Zustand store (`permissionsStore`) and a typed API client (`permissionsApi`). All user-visible text is routed through `i18next` `t()` calls. Route access is gated by admin role check in the router guard. The layout component provides tab-based navigation between the five sub-pages.

---

## 3. API Changes

All new endpoints are under the `/api/v1` prefix and require a valid JWT bearer token unless stated otherwise. Admin-only endpoints enforce access via the `require_permission` dependency rather than hardcoded role checks — the caller must hold a permission that grants the `admin` action on the relevant module. This allows fine-grained delegation without tying access to a fixed role name. All list endpoints support pagination via `page` and `page_size` query parameters unless noted.

### User Tag Definition Endpoints (`/api/v1/user-tags`)

**List tag definitions** — `GET /user-tags/definitions`: Returns a paginated list of all `TagDefinition` records. Accepts optional `scope` and `resource_type` query filters. Accessible to all authenticated users (needed for policy authoring UI). Response contains id, key, scope, resource_type, description, allowed values, and created_at.

**Create tag definition** — `POST /user-tags/definitions`: Admin only. Request body provides key, scope (global or resource_type), optional resource_type, description, and initial list of allowed values. Returns the created `TagDefinitionRead` record. Returns `409 Conflict` if a definition with the same key and scope already exists.

**Update tag definition** — `PATCH /user-tags/definitions/{id}`: Admin only. Accepts partial updates to description and the allowed values list. Key and scope are immutable after creation. Returns the updated record.

**Delete tag definition** — `DELETE /user-tags/definitions/{id}`: Admin only. Returns `204 No Content` on success. Returns `409 Conflict` if the tag key is referenced by any active `PolicyTagCondition`.

### User Role and Policy Endpoints (`/api/v1/user-roles`)

**List roles** — `GET /user-roles`: Returns a paginated list of all `Role` records with policy count and assignment counts (users and groups). Accessible to admins.

**Create role** — `POST /user-roles`: Admin only. Request body provides name and description. Returns the created `RoleRead` record.

**Get role** — `GET /user-roles/{id}`: Admin only. Returns the role with its full list of `PolicyStatement` records, each including actions, resource scope, and tag conditions.

**Update role** — `PATCH /user-roles/{id}`: Admin only. Updates name and/or description. Returns the updated record.

**Delete role** — `DELETE /user-roles/{id}`: Admin only. Returns `409 Conflict` if the role has active user or group assignments, unless the `force=true` query parameter is provided. Cascades deletion to all associated `PolicyStatement`, `PolicyAction`, `PolicyResource`, and `PolicyTagCondition` records.

**List policy statements for a role** — `GET /user-roles/{id}/policies`: Admin only. Returns all `PolicyStatement` records for the role including nested actions, resources, and tag conditions.

**Create policy statement** — `POST /user-roles/{id}/policies`: Admin only. Request body provides effect (allow/deny), module, list of actions, list of resource scopes (resource_type + optional resource_id wildcard), and optional list of tag conditions (tag_key + tag_value pairs). Returns the created `PolicyStatementRead`.

**Delete policy statement** — `DELETE /user-roles/{id}/policies/{policy_id}`: Admin only. Returns `204 No Content`.

### User Group Endpoints (`/api/v1/user-groups`)

**List groups** — `GET /user-groups`: All authenticated users. Returns paginated list with name, description, owner display name, member count, role count, and idp_claim_value. Used by the self-service join flow to discover available groups.

**Create group** — `POST /user-groups`: Admin only. Request body provides name, description, owner user ID, optional idp_claim_value, and initial list of role IDs. Returns `GroupRead`.

**Get group** — `GET /user-groups/{id}`: All authenticated users. Returns group detail.

**Update group** — `PATCH /user-groups/{id}`: Admin or the group owner. Accepts updates to name, description, and idp_claim_value. Role and member management use dedicated sub-endpoints.

**Delete group** — `DELETE /user-groups/{id}`: Admin only. Returns `204 No Content`.

**List group members** — `GET /user-groups/{id}/members`: Admin or group owner. Returns list of `PlatformUserRead` records with joined_at and join_reason.

**Add group member (direct)** — `POST /user-groups/{id}/members`: Admin only. Request body provides user_id and optional join_reason. Returns `204 No Content`. Used for direct admin-driven assignment without the request workflow.

**Remove group member** — `DELETE /user-groups/{id}/members/{user_id}`: Admin only. Returns `204 No Content`.

**List group roles** — `GET /user-groups/{id}/roles`: Admin or group owner. Returns list of assigned `RoleRead` records.

**Assign role to group** — `POST /user-groups/{id}/roles`: Admin only. Request body provides role_id. Returns `204 No Content`. Returns `409 Conflict` if the role is already assigned.

**Remove role from group** — `DELETE /user-groups/{id}/roles/{role_id}`: Admin only. Returns `204 No Content`.

### Platform User Endpoints (`/api/v1/platform-users`)

**List platform users** — `GET /platform-users`: Admin only. Paginated list with display name, email, direct role count, group count, first_seen_at, and last_seen_at.

**Get platform user** — `GET /platform-users/{id}`: Admin only. Returns full user detail including list of directly assigned roles and list of group memberships.

**Assign role to user** — `POST /platform-users/{id}/roles`: Admin only. Request body provides role_id. Returns `204 No Content`. Returns `409` if already assigned.

**Remove role from user** — `DELETE /platform-users/{id}/roles/{role_id}`: Admin only. Returns `204 No Content`.

**Add user to group** — `POST /platform-users/{id}/groups`: Admin only. Request body provides group_id and optional join_reason. Returns `204 No Content`.

**Remove user from group** — `DELETE /platform-users/{id}/groups/{group_id}`: Admin only. Returns `204 No Content`.

### User Access Request Endpoints (`/api/v1/user-access-requests`)

**Submit join request** — `POST /user-access-requests`: Any authenticated user. Request body provides a batch payload: `justification` string and `group_ids` list. Creates one `AccessRequestBatch` record plus one `AccessRequest` per group ID. Returns the created batch ID and the list of per-group `AccessRequestRead` records. Returns `409 Conflict` if a pending request already exists for any user/group pair in the batch.

**List own requests** — `GET /user-access-requests/my`: Any authenticated user. Returns all `AccessRequestBatch` records for the calling user, each including the batch-level justification, submitted_at, and the list of per-group `AccessRequest` statuses (group name, status, reviewed_at).

**List pending requests for owned groups** — `GET /user-access-requests/pending`: Group owners and admins. Returns all pending `AccessRequest` records for groups the caller owns (or all groups for admins), including requester display name and group name.

**Approve request** — `PATCH /user-access-requests/{id}/approve`: Group owner of the target group or admin. Accepts an optional `approval_reason` string in the request body; stored as `reviewer_reason` on the `AccessRequest` record. Returns the updated `AccessRequestRead` with status set to approved. Triggers `UserGroup` record creation and requester notification.

**Reject request** — `PATCH /user-access-requests/{id}/reject`: Group owner of the target group or admin. Request body requires a non-empty `rejection_reason` string (returns `422 Unprocessable Entity` if missing); stored as `reviewer_reason` on the `AccessRequest` record. Returns the updated `AccessRequestRead` with status set to rejected. Triggers requester notification.

### Structured Permission Error Responses

All `403 Forbidden` responses raised by the `require_permission` dependency include a structured `required_permission` object in the response body alongside the standard `detail` string. The `required_permission` object contains three fields: `resource_type` (the manifest resource type identifier the caller lacked access to), `action` (the specific action that was denied), and `resource_id` (the specific resource ID if applicable, or `null` for wildcard denials). This structure is defined as the `PermissionDeniedDetail` Pydantic model (with nested `RequiredPermission`) in `backend/app/schemas/errors.py`. The `require_permission` dependency constructs and passes this payload as the `detail` argument when raising `HTTPException(status_code=403)`. The frontend error handler inspects `required_permission` and displays a targeted message (e.g., "You need `write` access to `agent/support_001`") rather than a generic "Access Denied" string.

---

## 4. State Management

The `permissionsStore` is a Zustand store that manages all client-side state for the Permission Management module. It is divided into the following state slices:

**Tags slice** — Holds `TagDefinition[]`, a loading flag, and an error string. Actions: `fetchTags`, `createTag`, `updateTag`, `deleteTag`.

**Roles slice** — Holds `Role[]` (each with nested `PolicyStatement[]`), a loading flag, an error string, and a `selectedRole: Role | null` field that drives the single-dialog policy management pattern. Actions: `fetchRoles`, `createRole`, `updateRole`, `deleteRole`, `addPolicyStatement`, `removePolicyStatement`, `setSelectedRole`. The single-dialog pattern opens one comprehensive `RolePolicyDialog` for the selected role, displaying and managing all policy statements in a single view (matching the Roles page prototype). This replaces any pattern where separate add and edit flows opened distinct dialogs.

**Groups slice** — Holds `Group[]`, a loading flag, and an error string. Actions: `fetchGroups`, `createGroup`, `updateGroup`, `deleteGroup`, `fetchGroupMembers`, `addGroupMember`, `removeGroupMember`, `assignGroupRole`, `removeGroupRole`.

**Platform Users slice** — Holds a paginated `PlatformUser[]`, total count, current page, a loading flag, and an error string. Actions: `fetchUsers`, `assignUserRole`, `removeUserRole`, `addUserToGroup`, `removeUserFromGroup`.

**Access Requests slice** — Holds `AccessRequest[]` for the pending list and a separate `AccessRequest[]` for the current user's own requests. Includes loading and error flags. Actions: `fetchPendingRequests`, `fetchMyRequests`, `submitRequest`, `approveRequest`, `rejectRequest`.

---

## 5. Data Access Patterns

All data access follows the established project pattern: browser client sends authenticated REST calls to the FastAPI backend, which executes async SQLAlchemy queries against PostgreSQL.

**Admin management flow** — Admin opens a permissions page → React component calls `permissionsStore` action → store calls `permissionsApi` function → API function sends `GET`/`POST`/`PATCH`/`DELETE` to the corresponding `/api/v1/` endpoint with the JWT bearer token → FastAPI route handler validates JWT via middleware (triggering User Cache and Group Claim Mapper), validates admin role, calls the relevant service class method (TagRegistry, Role handler, Group handler, or AccessRequestService) → service executes async SQLAlchemy query → DB returns result → serialized via Pydantic schema → response returned to store → store updates state slice → component re-renders.

**Login auto-assignment flow** — User's browser sends any authenticated request → auth middleware validates JWT → `UserCacheService.upsert_user()` creates or updates `PlatformUser` record → `GroupClaimMapper.map_claims()` reads JWT group claims, queries `Group` table for matching `idp_claim_value` entries, inserts missing `UserGroup` records → request proceeds normally.

**Resource authorization flow** — Frontend calls a protected resource endpoint (e.g., `DELETE /agents/{id}`) → auth middleware validates JWT → route handler calls `PermissionEngine.authorize()` with module, action, resource_id, and resource_tags → engine loads user's roles (direct `UserRole` + group-inherited via `GroupRole`) → engine queries `PolicyStatement` records for those roles → evaluates each statement for module match, action match, resource scope match, and all tag condition matches → returns allow or deny → route handler returns `403` on deny, proceeds on allow.

**Self-service join flow** — User opens Access Requests page → `permissionsStore.fetchGroups()` loads available groups → user selects a group and clicks "Request Access" → `permissionsStore.submitRequest()` calls `POST /access-requests` → `AccessRequestService` creates pending `AccessRequest` record, calls `NotificationHook.notify_owner_new_request()` → notification service creates in-platform notification for group owner → group owner sees request in their pending list → owner approves/rejects → `AccessRequestService` updates status, creates `UserGroup` record (on approval), calls `NotificationHook.notify_requester_decision()` → requester sees updated status in "My Requests" tab.

---

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `BootstrapService` | class | Seeds system admin role on first startup; idempotent; runs as FastAPI startup event | `backend/app/services/permissions/bootstrap_service.py` |
| `BootstrapService.initialize` | method | Ensures system_admin role + full-access policy + assigns initial admin by BOOTSTRAP_ADMIN_EMAIL env var | `backend/app/services/permissions/bootstrap_service.py` |
| `require_permission` | function | FastAPI dependency factory: resolves PlatformUser from JWT sub, calls PermissionEngine, raises 403 on deny | `backend/app/api/deps.py` |
| `require_admin` | function | Legacy JWT-claim-based admin check; kept for non-permission-managed endpoints | `backend/app/api/deps.py` |
| `is_system` | column | Boolean column on `Role` (default False); True marks immutable system roles | `backend/app/db/models/identity.py` |
| `PermRoleRead.role_type` | computed field | Returns `'system'` when `is_system=True`, `'user_defined'` otherwise | `backend/app/schemas/perm_roles.py` |
| `Role.role_type` | TS field | `'system' \| 'user_defined'` — drives badge display and button disabling in RolesPage | `frontend/src/types/permissions.ts` |
| `PermissionEngine` | class | Evaluates user permission policies; returns allow/deny with reason | `backend/app/services/permissions/permission_engine.py` |
| `AuthorizationResult` | dataclass | Return type of `PermissionEngine.authorize()` — decision + reason | `backend/app/services/permissions/permission_engine.py` |
| `get_permission_engine` | function | FastAPI dependency that provides a `PermissionEngine` instance | `backend/app/services/permissions/permission_engine.py` |
| `TagRegistry` | class | Manages tag definitions and validates tag key/value assignments | `backend/app/services/permissions/tag_registry.py` |
| `UserCacheService` | class | Upserts `PlatformUser` records from OIDC token claims | `backend/app/services/permissions/user_cache_service.py` |
| `GroupClaimMapper` | class | Maps JWT group claims to `UserGroup` memberships idempotently | `backend/app/services/permissions/group_claim_mapper.py` |
| `AccessRequestService` | class | Handles submit, approve, and reject of group join requests | `backend/app/services/permissions/access_request_service.py` |
| `NotificationHook` | class | Sends permission-domain notifications via existing notification service | `backend/app/services/permissions/notification_hook.py` |
| `TagDefinition` | SQLAlchemy model | Tag key with scope and allowed values | `backend/app/db/models/tag_definition.py` |
| `TagValue` | SQLAlchemy model | Allowed value entry for a `TagDefinition` | `backend/app/db/models/tag_value.py` |
| `Role` | SQLAlchemy model | Named permission role containing policy statements | `backend/app/db/models/role.py` |
| `PolicyStatement` | SQLAlchemy model | A permission statement scoped to module, actions, resources, and tag conditions | `backend/app/db/models/policy_statement.py` |
| `PolicyAction` | SQLAlchemy model | Action string within a `PolicyStatement` | `backend/app/db/models/policy_action.py` |
| `PolicyResource` | SQLAlchemy model | Resource scope entry within a `PolicyStatement` | `backend/app/db/models/policy_resource.py` |
| `PolicyTagCondition` | SQLAlchemy model | Tag key/value condition on a `PolicyStatement` | `backend/app/db/models/policy_tag_condition.py` |
| `PlatformUser` | SQLAlchemy model | Cached OIDC-authenticated user record | `backend/app/db/models/platform_user.py` |
| `UserRole` | SQLAlchemy model | Junction: direct role assignment to a platform user | `backend/app/db/models/user_role.py` |
| `Group` | SQLAlchemy model | Named group with owner, roles, and optional IdP claim binding | `backend/app/db/models/group.py` |
| `GroupRole` | SQLAlchemy model | Junction: role assigned to a group | `backend/app/db/models/group_role.py` |
| `UserGroup` | SQLAlchemy model | Junction: user membership in a group | `backend/app/db/models/user_group.py` |
| `AccessRequest` | SQLAlchemy model | Group join request with lifecycle status | `backend/app/db/models/access_request.py` |
| `PolicyEffect` | Python Enum | `allow` / `deny` — effect of a policy statement | `backend/app/schemas/roles.py` |
| `AccessRequestStatus` | Python Enum | `pending` / `approved` / `rejected` | `backend/app/schemas/access_requests.py` |
| `TagScope` | Python Enum | `global` / `resource_type` — scope of a tag definition | `backend/app/schemas/tags.py` |
| `TagDefinitionCreate` | Pydantic model | Request schema for creating a tag definition | `backend/app/schemas/tags.py` |
| `TagDefinitionRead` | Pydantic model | Response schema for a tag definition | `backend/app/schemas/tags.py` |
| `RoleCreate` | Pydantic model | Request schema for creating a role | `backend/app/schemas/roles.py` |
| `RoleRead` | Pydantic model | Response schema for a role with policy statement list | `backend/app/schemas/roles.py` |
| `PolicyStatementCreate` | Pydantic model | Request schema for creating a policy statement | `backend/app/schemas/roles.py` |
| `PolicyStatementRead` | Pydantic model | Response schema for a policy statement with actions/resources/conditions | `backend/app/schemas/roles.py` |
| `GroupCreate` | Pydantic model | Request schema for creating a group | `backend/app/schemas/groups.py` |
| `GroupRead` | Pydantic model | Response schema for a group with member and role counts | `backend/app/schemas/groups.py` |
| `PlatformUserRead` | Pydantic model | Response schema for a platform user with role and group lists | `backend/app/schemas/platform_users.py` |
| `AccessRequestCreate` | Pydantic model | Request schema for submitting a join request | `backend/app/schemas/access_requests.py` |
| `AccessRequestRead` | Pydantic model | Response schema for an access request with status and review info | `backend/app/schemas/access_requests.py` |
| User Tags API router | FastAPI router | CRUD endpoints for user tag definitions under `/api/v1/user-tags`; rename `tags.py` → `user_tags.py` | `backend/app/api/v1/user_tags.py` |
| User Roles API router | FastAPI router | CRUD endpoints for user roles and policy statements under `/api/v1/user-roles`; rename `roles.py` → `user_roles.py` | `backend/app/api/v1/user_roles.py` |
| User Groups API router | FastAPI router | CRUD and membership endpoints for user groups under `/api/v1/user-groups`; rename `groups.py` → `user_groups.py` | `backend/app/api/v1/user_groups.py` |
| Platform Users API router | FastAPI router | User list and assignment endpoints under `/api/v1/platform-users` | `backend/app/api/v1/platform_users.py` |
| User Access Requests API router | FastAPI router | Submit, list, approve, reject endpoints under `/api/v1/user-access-requests`; rename `access_requests.py` → `user_access_requests.py` | `backend/app/api/v1/user_access_requests.py` |
| `AccessRequestBatch` | SQLAlchemy model | Batch entity grouping multiple group join requests under a single justification | `backend/app/db/models/access_request_batch.py` |
| `AccessRequestBatchSchema` | Pydantic model | Request/response schema for the batch submit endpoint | `backend/app/schemas/access_requests.py` |
| `submit_batch_request` | method | Creates an `AccessRequestBatch` + one `AccessRequest` per group ID | `backend/app/services/permissions/access_request_service.py` |
| `_match_resource_id` | private method | Evaluates wildcard patterns against resource IDs in `PermissionEngine` | `backend/app/services/permissions/permission_engine.py` |
| `ManageAccessModal` | React component | Tabbed modal for assigning/removing roles and groups for a given user | `frontend/src/components/permissions/ManageAccessModal.tsx` |
| `useTagValueOptions` | React hook | Returns allowed values array for a given tag key from the tag definition store | `frontend/src/hooks/useTagValueOptions.ts` |
| Auth middleware (modified) | middleware | Extended to call `UserCacheService` and `GroupClaimMapper` on every validated request | `backend/app/middleware/auth.py` |
| `permissionsApi` | TypeScript module | Typed async functions for all permission management endpoints | `frontend/src/api/permissionsApi.ts` |
| `permissionsStore` | Zustand store | Client-side state for tags, roles, groups, users, and access requests | `frontend/src/stores/permissionsStore.ts` |
| `TagDefinition` (TS) | TypeScript interface | Client-side type for a tag definition | `frontend/src/types/permissions.ts` |
| `Role` (TS) | TypeScript interface | Client-side type for a role with policy statements | `frontend/src/types/permissions.ts` |
| `PolicyStatement` (TS) | TypeScript interface | Client-side type for a policy statement | `frontend/src/types/permissions.ts` |
| `Group` (TS) | TypeScript interface | Client-side type for a group | `frontend/src/types/permissions.ts` |
| `PlatformUser` (TS) | TypeScript interface | Client-side type for a platform user | `frontend/src/types/permissions.ts` |
| `AccessRequest` (TS) | TypeScript interface | Client-side type for a join request | `frontend/src/types/permissions.ts` |
| `PolicyEffect` (TS) | TypeScript enum | `allow` / `deny` | `frontend/src/types/permissions.ts` |
| `AccessRequestStatus` (TS) | TypeScript enum | `pending` / `approved` / `rejected` | `frontend/src/types/permissions.ts` |
| `TagScope` (TS) | TypeScript enum | `global` / `resource_type` | `frontend/src/types/permissions.ts` |
| `PermissionsPage` | React component | Layout with tab navigation for the five permission sub-pages; admin-gated | `frontend/src/pages/permissions/PermissionsPage.tsx` |
| `TagsPage` | React component | Tag definitions table with add/edit/delete | `frontend/src/pages/permissions/TagsPage.tsx` |
| `RolesPage` | React component | Roles table with policy statement detail and CRUD | `frontend/src/pages/permissions/RolesPage.tsx` |
| `GroupsPage` | React component | Groups table with member/role management and IdP claim binding | `frontend/src/pages/permissions/GroupsPage.tsx` |
| `UsersPage` | React component | Paginated platform users table with role/group assignment | `frontend/src/pages/permissions/UsersPage.tsx` |
| `AccessRequestsPage` | React component | Pending requests view for owners/admins and own-requests view for users | `frontend/src/pages/permissions/AccessRequestsPage.tsx` |
| `ResourceTypeManifest` | Python constant | Centralized dict mapping resource type identifiers to allowed action sets; authoritative source for `PermissionEngine` validation and router constants | `backend/app/core/resource_types.py` |
| `RESOURCE_TYPES` | TypeScript const | Frontend mirror of `ResourceTypeManifest`; populates resource type and action dropdowns in the single-dialog policy builder | `frontend/src/constants/resourceTypes.ts` |
| `PermissionDeniedDetail` | Pydantic model | 403 response body schema; contains `detail` string and nested `required_permission` object | `backend/app/schemas/errors.py` |
| `RequiredPermission` | Pydantic model | Nested model within `PermissionDeniedDetail`; contains `resource_type`, `action`, and `resource_id` fields | `backend/app/schemas/errors.py` |
| `RolePolicyDialog` | React component | Single comprehensive dialog for viewing and managing all policy statements for a selected role; replaces separate add/edit flows | `frontend/src/pages/permissions/RolesPage.tsx` |
