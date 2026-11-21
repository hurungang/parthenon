# Identity — RBAC, Permissions & Resource Types

[← Identity tech spec hub](tech-spec.md) · [Identity providers & OIDC](identity-provider-oidc.md)

Roles, permissions, tags, user groups, platform users, access requests, the
Permission Engine, and the namespaced resource-type system.

## Components

### Backend — RBAC Layer

| Component | Description |
|-----------|-------------|
| `RoleRouter` | FastAPI router exposing full CRUD operations for Role records; supports assigning and revoking Permission associations on a role |
| `PermissionRouter` | FastAPI router for creating and listing Permission records; permissions represent individual grantable actions across the platform |
| `IdentityRouter` | FastAPI router for registering new identities (users or agents) and listing all registered identities |
| `SetupRouter` | FastAPI router with public endpoints for admin seeding (`POST /setup/init`) and identity provider provisioning (`GET /setup/identity-status`, `POST /setup/identity`); all three bypass JWT authentication |
| `IdentityBootstrapService` | Orchestrates the full identity provider setup lifecycle: detect setup state, provision Keycloak or register external OIDC, persist to DB and YAML, trigger OIDC client reload. Exposes `check_setup_state()`, `provision_bundled_keycloak()`, and `provision_external_oidc()`. Idempotent — re-running on an already-provisioned system is safe. |
| `KeycloakAdminClient` | Encapsulates all Keycloak Admin REST API calls. Authenticates to the master realm, retries on HTTP 503 with exponential back-off (3 attempts), raises typed `KeycloakAdminError` on unrecoverable failures, and provides idempotent existence-check helpers (`realm_exists`, `client_exists`). |
| `Identity` | SQLAlchemy declarative model representing a platform identity; records the OIDC subject identifier (`idp_subject`), role type (`user`, `agent`, or `both`) |
| `IdentityProviderConfig` | SQLAlchemy model storing the active identity provider configuration (provider type, OIDC URL, realm, client ID, encrypted client secret) |
| `IdentityProviderSetupState` | SQLAlchemy single-row model tracking setup state (`NOT_CONFIGURED`, `IN_PROGRESS`, `CONFIGURED`); primary source of truth for bootstrap status checks |
| `Role` | SQLAlchemy declarative model for a named permission set with role type classification; extended with `is_system` boolean flag (immutable system roles) and a relationship to `PolicyStatement` records |
| `Permission` | SQLAlchemy declarative model for a grantable platform action |
| `RolePermission` | SQLAlchemy join model linking roles to permissions (many-to-many) |
| `ProviderSetupRequest` | Pydantic request schema for `POST /setup/identity`; `provider_type`, connection URLs, credentials, and optional `force_reconfigure` flag |
| `ProviderSetupResult` | Pydantic response schema for `POST /setup/identity`; resolved OIDC URL, provider type, realm, client ID |
| `IdentityStatusResponse` | Pydantic response schema for `GET /setup/identity-status`; `setup_state`, `provider_type`, `oidc_provider_url` |
| `SetupState` | String enum: `NOT_CONFIGURED`, `IN_PROGRESS`, `CONFIGURED` |
| `ProviderType` | String enum: `keycloak_bundled`, `keycloak_external`, `azure_entraid`, `unconfigured`; shared between schemas and `Settings` |

### Backend — User Permission System

| Component | Description |
|-----------|-------------|
| `PolicyRouter` | New FastAPI router at `/api/v1/policy`; exposes `GET /resource-types` returning the full `ResourceTypeManifest` as a list of `{ resource_type, actions }` objects; no database access — manifest is a static in-memory dict; requires `system::permissions:read` permission |
| `BootstrapService` | Seeds a `system_admin` role with full-access policy on first startup; idempotent; runs as a FastAPI startup event handler |
| `PermissionEngine` | Evaluates authorization requests against the user's effective policy set; deny-by-default; supports wildcard resource ID patterns; returns `AuthorizationResult` with decision and audit reason; emits one structured audit log record and sets `permission.*` OTEL span attributes per call |
| `TagRegistry` | Manages `TagDefinition` and `TagValue` records; enforces key uniqueness per scope; validates proposed tag key/value pairs against allowed values list |
| `UserCacheService` | Upserts a `PlatformUser` record on every successful JWT validation; creates on first encounter, updates `last_seen_at` on subsequent calls |
| `GroupClaimMapper` | Processes JWT group claims after User Cache write; creates missing `UserGroup` membership records for groups whose `idp_claim_value` appears in JWT claims; idempotent |
| `AccessRequestService` | Manages the full lifecycle of group join requests; handles `submit_batch_request`, approval (creates `UserGroup` record), and rejection; enforces one-pending-per-user/group constraint; delegates notification triggers to `NotificationHook` |
| `NotificationHook` | Sends permission-domain alerts via the existing notification service: owner notification on new join request, requester notification on approve/reject |
| Auth middleware (modified) | Extended to call `UserCacheService.upsert_user()` and `GroupClaimMapper.map_claims()` after every successful JWT validation; failures are logged without failing the request |

### Frontend — User Permission Management

| Component | Description |
|-----------|-------------|
| `PermissionsPage` | Layout container with tab navigation for the five permission sub-pages; admin-gated via router guard |
| `TagsPage` | Tag definitions table with add/edit/delete |
| `RolesPage` | Roles table with "Manage Policies" icon button per row that opens `RolePolicyDialog`; adds "View JSON" (`JSONViewModal`) and "Clone" (`CloneRoleDialog`) icon buttons per row; system roles have all controls disabled |
| `RolePolicyDialog` | Dialog wrapper for role policy editing; displays all policies for a role in a single view; toggle between Form view (FreeSolo autocomplete selectors) and JSON Source Code view (Monaco-style editor with syntax highlighting); bidirectional sync between views; batch save on submit; unsaved changes guard on Cancel/Escape/backdrop; dialog error surface using `PermissionDeniedAlert` |
| `PolicyEditor` | Policy statement card component rendered inside `RolePolicyDialog`; displays module chip, action chips, resource definitions, and tag conditions per policy; supports remove and edit actions |
| `AddStatementDialog` | Self-contained dialog with structured form for creating a policy statement; uses FreeSolo autocomplete for resource type and action selection; owns `useCreatePolicyStatement` mutation |
| `FreeSoloResourceTypeSelect` | MUI `Autocomplete` with `freeSolo` mode for resource type selection; dropdown lists all manifest entries grouped by module; accepts free-text wildcard input (`agent::*`, `agent::mana*`, `*::*`, `*`) |
| `FreeSoloActionSelect` | MUI `Autocomplete` with `freeSolo` mode for action selection; dropdown lists 10 standard actions; accepts `*` wildcard and custom action strings |
| `PermissionDeniedAlert` | Alert component displaying structured 403 error with resource type, action, and reason; used as the primary error surface in dialogs with API calls |
| `PermissionErrorSnackbar` | Global snackbar component for 403 permission denied events; interpolates `resource_type` via i18n |
| `useUnsavedChangesDialog` | Composable hook for tracking dirty state; shows confirmation dialog on Cancel/Escape/backdrop dismiss |
| `JSONViewModal` | Read-only dialog rendering a role's effective policy as canonical JSON in a dark monospace block with clipboard copy action; data derived from `useRole()` |
| `CloneRoleDialog` | Dialog for cloning a role; pre-populates name and description from the source; owns `useCloneRole()` mutation and inline error display |
| `GroupsPage` | Groups table with member/role management, IdP claim binding, and "Manage Roles" action that opens `ManageGroupRolesModal` |
| `UsersPage` | Paginated platform users table with role/group assignment |
| `AccessRequestsPage` | Pending requests view for owners/admins; own-requests view for users |
| `ManageAccessModal` | Tabbed modal for assigning/removing roles and groups for a given user |
| `ManageGroupRolesModal` | Modal for viewing, adding, and removing role assignments on an existing group; opened via a "Manage Roles" icon button in the groups table; displays current roles as removable chips with a dropdown to add any unassigned platform role |
| `permissionsApi` | Typed async functions for all permission management endpoints |
| `useTagValueOptions` | React hook returning the allowed-values array for a given tag key from the tag definition store |
| `useResourceTypes` | React Query `useQuery` hook; fetches resource types from `GET /api/v1/policy/resource-types`; cached indefinitely (static data) |
| `useCloneRole` | React Query `useMutation` hook; posts to `POST /api/v1/user-roles/{id}/clone`; invalidates `permissionKeys.roles` on success |

**Manifest mirror (frontend)**

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `RESOURCE_TYPE_MANIFEST` | TypeScript const | Frontend mirror of backend `ResourceTypeManifest`; grouped dropdown source for `AddStatementDialog` and `RolePolicyDialog`. Must list the same types and actions as the backend — including `integration::control_center` — or every user sees 403 on those types | `frontend/src/constants/resourceTypes.ts` |
| `MODULE_GROUPS` (TS) | TypeScript const | Module-to-submodule grouping for dropdown rendering (`agent`, `integration`, `system`, `platform`, `tenant`); `integration::control_center` sits in the `integrations` submodule list | `frontend/src/constants/resourceTypes.ts` |
| `ResourceTypeManifestMirror.test.ts` | test | Pins backend/frontend manifest + module-group parity | `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` |

| Symbol | Type | Description |
|--------|------|-------------|
| `getActionsForResourceType` | function | Returns allowed actions for a namespaced resource type from the manifest |
| `getModuleForResourceType` | function | Extracts module prefix from a namespaced identifier (e.g. `agent::management` → `agent`) |
| `useBatchSaveRolePolicies` | hook | React Query `useMutation` hook; calls `PUT /user-roles/{id}/policies/batch`; invalidates role and roles queries on success |
| `BatchPolicySaveRequest` (TS) | TypeScript interface | Request body type for batch save: `{ policies: PolicyStatementCreate[] }` |

---

## API Endpoints

### Setup & RBAC

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/setup/identity-status` | None | Query current identity provider setup state |
| `POST` | `/api/v1/setup/identity` | None | Provision identity provider (returns 409 if already configured without `force_reconfigure`) |
| `POST` | `/api/v1/setup/init` | None | Seed first admin role and identity — public during initial setup only |
| `GET` | `/api/v1/roles` | JWT | List all roles |
| `POST` | `/api/v1/roles` | JWT | Create a role |
| `GET` | `/api/v1/roles/{role_id}` | JWT | Get a role by ID |
| `PUT` | `/api/v1/roles/{role_id}` | JWT | Update a role |
| `DELETE` | `/api/v1/roles/{role_id}` | JWT | Delete a role |
| `POST` | `/api/v1/roles/{role_id}/permissions` | JWT | Assign a permission to a role |
| `DELETE` | `/api/v1/roles/{role_id}/permissions/{permission_id}` | JWT | Remove a permission from a role |
| `GET` | `/api/v1/permissions` | JWT | List all permissions |
| `POST` | `/api/v1/permissions` | JWT | Create a permission |
| `GET` | `/api/v1/identities` | JWT | List all registered identities |
| `POST` | `/api/v1/identities` | JWT | Register an identity |

### User Tags (`/api/v1/user-tags`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/user-tags/definitions` | JWT | List all tag definitions; supports `scope` and `resource_type` filters |
| `POST` | `/api/v1/user-tags/definitions` | JWT (admin) | Create a tag definition; 409 on duplicate key+scope |
| `PATCH` | `/api/v1/user-tags/definitions/{id}` | JWT (admin) | Update description and allowed values (key and scope are immutable) |
| `DELETE` | `/api/v1/user-tags/definitions/{id}` | JWT (admin) | Delete tag definition; 409 if referenced by active `PolicyTagCondition` |

### User Roles (`/api/v1/user-roles`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/user-roles` | JWT (admin) | List roles with policy count and assignment counts |
| `POST` | `/api/v1/user-roles` | JWT (admin) | Create a role |
| `GET` | `/api/v1/user-roles/{id}` | JWT (admin) | Get role with full `PolicyStatement` list |
| `PATCH` | `/api/v1/user-roles/{id}` | JWT (admin) | Update name/description |
| `DELETE` | `/api/v1/user-roles/{id}` | JWT (admin) | Delete role; 409 if active assignments (override with `force=true`) |
| `GET` | `/api/v1/user-roles/{id}/policies` | JWT (admin) | List policy statements for role |
| `POST` | `/api/v1/user-roles/{id}/policies` | JWT (admin) | Create policy statement (effect, module, actions, resource scopes, tag conditions); `module` accepts namespaced identifiers (`agent::management`) validated against `ResourceTypeManifest` |
| `PATCH` | `/api/v1/user-roles/{id}/policies/{policy_id}` | JWT (admin) | Update an existing policy statement |
| `DELETE` | `/api/v1/user-roles/{id}/policies/{policy_id}` | JWT (admin) | Delete policy statement |
| `PUT` | `/api/v1/user-roles/{id}/policies/batch` | JWT (admin, `system::permissions:manage`) | Replace all policy statements for a role atomically in a single transaction; accepts `{ policies: PolicyStatementCreate[] }`; validates each module against `ResourceTypeManifest` (wildcards accepted); empty array clears all policies; idempotent |
| `POST` | `/api/v1/user-roles/{id}/clone` | JWT (admin) | Deep-copy role and all nested policy statements under a new name; 409 on duplicate name, 404 if source not found |

### Policy (`/api/v1/policy`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/policy/resource-types` | JWT (`system::permissions:read`) | Returns all namespaced resource types with `module_group` metadata and their allowed actions from `ResourceTypeManifest`; response is an array of `{ resource_type, actions, module_group }` objects; no database access |

### User Groups (`/api/v1/user-groups`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/user-groups` | JWT | List groups (used by self-service join flow) |
| `POST` | `/api/v1/user-groups` | JWT (admin) | Create group with name, owner, optional idp_claim_value, and initial role IDs |
| `GET` | `/api/v1/user-groups/{id}` | JWT | Get group detail |
| `PATCH` | `/api/v1/user-groups/{id}` | JWT (admin or owner) | Update name, description, idp_claim_value |
| `DELETE` | `/api/v1/user-groups/{id}` | JWT (admin) | Delete group |
| `GET` | `/api/v1/user-groups/{id}/members` | JWT (admin or owner) | List members with joined_at |
| `POST` | `/api/v1/user-groups/{id}/members` | JWT (admin) | Direct member add (bypasses request workflow) |
| `DELETE` | `/api/v1/user-groups/{id}/members/{user_id}` | JWT (admin) | Remove member |
| `GET` | `/api/v1/user-groups/{id}/roles` | JWT (admin or owner) | List assigned roles |
| `POST` | `/api/v1/user-groups/{id}/roles` | JWT (admin) | Assign role; 409 if already assigned |
| `DELETE` | `/api/v1/user-groups/{id}/roles/{role_id}` | JWT (admin) | Remove role from group |

### Platform Users (`/api/v1/platform-users`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/platform-users` | JWT (admin) | Paginated user list with direct role count, group count, first/last seen |
| `GET` | `/api/v1/platform-users/{id}` | JWT (admin) | Full user detail with direct roles and group memberships |
| `POST` | `/api/v1/platform-users/{id}/roles` | JWT (admin) | Assign role; 409 if already assigned |
| `DELETE` | `/api/v1/platform-users/{id}/roles/{role_id}` | JWT (admin) | Remove direct role |
| `POST` | `/api/v1/platform-users/{id}/groups` | JWT (admin) | Add user to group |
| `DELETE` | `/api/v1/platform-users/{id}/groups/{group_id}` | JWT (admin) | Remove user from group |

### User Access Requests (`/api/v1/user-access-requests`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/v1/user-access-requests` | JWT | Submit batch join request; 409 if pending request already exists for any group |
| `GET` | `/api/v1/user-access-requests/my` | JWT | List caller's own request batches with per-group statuses |
| `GET` | `/api/v1/user-access-requests/pending` | JWT (admin or owner) | List pending requests for owned groups |
| `PATCH` | `/api/v1/user-access-requests/{id}/approve` | JWT (admin or owner) | Approve request; creates `UserGroup` record; triggers notification |
| `PATCH` | `/api/v1/user-access-requests/{id}/reject` | JWT (admin or owner) | Reject request; requires non-empty `rejection_reason`; triggers notification |

---

## Namespaced Resource Types

The resource-type system uses `module::submodule` identifiers (e.g.
`agent::roles`, `integration::mcp_hub`, `system::permissions`). Wildcards are
manifest-aware (`agent::*`, `*::*`) and every grant stays inside the session's
tenant. The authoritative registry lives in
`backend/app/core/resource_types.py` with a mirrored frontend manifest.

---

## Code Reference Map

### RBAC — API & Models

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `RoleRouter` | router | CRUD endpoints for Role management including permission assignment/revocation | `backend/app/api/v1/identity.py` |
| `PermissionRouter` | router | CRUD endpoints for Permission management | `backend/app/api/v1/identity.py` |
| `IdentityRouter` | router | Registration and listing endpoints for platform Identities | `backend/app/api/v1/identity.py` |
| `Identity` | model | SQLAlchemy model for a platform identity with `idp_subject` (nullable, indexed), role type | `backend/app/db/models/identity.py` |
| `Role` | model | SQLAlchemy model for a named permission set; extended with `is_system` boolean flag (immutable system roles) and `policy_statements` relationship | `backend/app/db/models/identity.py` |
| `Permission` | model | SQLAlchemy model for a grantable platform action | `backend/app/db/models/identity.py` |
| `RolePermission` | model | SQLAlchemy join model linking roles to permissions (many-to-many) | `backend/app/db/models/identity.py` |
| `is_system` | column | Boolean column on `Role` (default `False`); `True` marks immutable system roles | `backend/app/db/models/identity.py` |
| `PermRoleRead` | schema | Response schema for a role; includes `role_type` computed field | `backend/app/schemas/perm_roles.py` |
| `PermRoleRead.role_type` | computed field | Returns `'system'` when `is_system=True`, `'user_defined'` otherwise | `backend/app/schemas/perm_roles.py` |
| `Role.role_type` | TS field | `'system' \| 'user_defined'` — drives badge display and button disabling in RolesPage | `frontend/src/types/permissions.ts` |

### User Permission System — Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `BootstrapService` | class | Seeds system admin role on first startup; idempotent; runs as FastAPI startup event | `backend/app/services/permissions/bootstrap_service.py` |
| `BootstrapService._ensure_system_admin_role` (modified) | method | The bootstrap `system_admin` role is created ROOT-scoped (pre-Phase-11 NULL rows re-homed by migration `b8e4f2a6c9d1`) — no global tenant-less roles on fresh deployments | `backend/app/services/permissions/bootstrap_service.py` |
| `BootstrapService.initialize` | method | Ensures `system_admin` role + full-access policy + assigns initial admin by `BOOTSTRAP_ADMIN_EMAIL` env var | `backend/app/services/permissions/bootstrap_service.py` |
| `PermissionEngine` | class | Evaluates user permission policies; deny-by-default; returns allow/deny with audit reason; emits structured audit log and OTEL span attributes per call | `backend/app/services/permissions/permission_engine.py` |
| `PermissionEngine.authorize` | method | Evaluates allow/deny for user + module + action + resource_id; validates against `ResourceTypeManifest`; loads effective role IDs (direct `UserRole` + group-inherited `GroupRole`); emits one structured log record and sets `permission.*` OTEL span attributes per call; returns `AuthorizationResult` | `backend/app/services/permissions/permission_engine.py` |
| `AuthorizationResult` | dataclass | Return type of `PermissionEngine.authorize()` — decision + reason | `backend/app/services/permissions/permission_engine.py` |
| `_match_resource_id` | private method | Evaluates wildcard patterns against resource IDs in `PermissionEngine` | `backend/app/services/permissions/permission_engine.py` |
| `get_permission_engine` | function | FastAPI dependency that provides a `PermissionEngine` instance | `backend/app/services/permissions/permission_engine.py` |
| `TagRegistry` | class | Manages tag definitions and validates tag key/value assignments | `backend/app/services/permissions/tag_registry.py` |
| `UserCacheService` | class | Upserts `PlatformUser` records from OIDC token claims | `backend/app/services/permissions/user_cache_service.py` |
| `GroupClaimMapper` | class | Maps JWT group claims to `UserGroup` memberships idempotently | `backend/app/services/permissions/group_claim_mapper.py` |
| `AccessRequestService` | class | Handles submit, approve, and reject of group join requests | `backend/app/services/permissions/access_request_service.py` |
| `submit_batch_request` | method | Creates an `AccessRequestBatch` + one `AccessRequest` per group (or one group-less request when `group_ids` is empty) | `backend/app/services/permissions/access_request_service.py` |
| `approve_request` | method | Approves a request, optionally assigning a group at approval time, then creates the `UserGroup` membership record | `backend/app/services/permissions/access_request_service.py` |
| `NotificationHook` | class | Sends permission-domain notifications via existing notification service | `backend/app/services/permissions/notification_hook.py` |
| `require_admin` | function | Legacy JWT-claim-based admin check; kept for non-permission-managed endpoints | `backend/app/api/deps.py` |
| Auth middleware (modified) | middleware | Extended to call `UserCacheService` and `GroupClaimMapper` on every validated request | `backend/app/middleware/auth.py` |

### User Permission System — Database Models

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TagDefinition` | model | SQLAlchemy model for a tag key with scope and allowed values | `backend/app/db/models/tag_definition.py` |
| `TagValue` | model | SQLAlchemy model for an allowed value entry for a `TagDefinition` | `backend/app/db/models/tag_value.py` |
| `PolicyStatement` | model | SQLAlchemy model for a permission statement scoped to module, actions, resources, and tag conditions | `backend/app/db/models/policy_statement.py` |
| `PolicyAction` | model | SQLAlchemy model for an action string within a `PolicyStatement` | `backend/app/db/models/policy_action.py` |
| `PolicyResource` | model | SQLAlchemy model for a resource scope entry within a `PolicyStatement` | `backend/app/db/models/policy_resource.py` |
| `PolicyTagCondition` | model | SQLAlchemy model for a tag key/value condition on a `PolicyStatement` | `backend/app/db/models/policy_tag_condition.py` |
| `PlatformUser` | model | SQLAlchemy model for a cached OIDC-authenticated user record | `backend/app/db/models/platform_user.py` |
| `UserRole` | model | SQLAlchemy junction model for direct role assignment to a platform user | `backend/app/db/models/user_role.py` |
| `Group` | model | SQLAlchemy model for a named group with owner, roles, and optional IdP claim binding | `backend/app/db/models/group.py` |
| `GroupRole` | model | SQLAlchemy junction model for a role assigned to a group | `backend/app/db/models/group_role.py` |
| `UserGroup` | model | SQLAlchemy junction model for user membership in a group | `backend/app/db/models/user_group.py` |
| `AccessRequest` | model | SQLAlchemy model for a group join request with lifecycle status | `backend/app/db/models/access_request.py` |
| `AccessRequestBatch` | model | SQLAlchemy model grouping multiple group join requests under a single justification | `backend/app/db/models/access_request_batch.py` |

### User Permission System — Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TagScope` | Python Enum | `global` / `resource_type` — scope of a tag definition | `backend/app/schemas/tags.py` |
| `TagDefinitionCreate` | Pydantic model | Request schema for creating a tag definition | `backend/app/schemas/tags.py` |
| `TagDefinitionRead` | Pydantic model | Response schema for a tag definition | `backend/app/schemas/tags.py` |
| `PolicyEffect` | Python Enum | `allow` / `deny` — effect of a policy statement | `backend/app/schemas/roles.py` |
| `RoleCreate` | Pydantic model | Request schema for creating a role | `backend/app/schemas/roles.py` |
| `RoleRead` | Pydantic model | Response schema for a role with policy statement list | `backend/app/schemas/roles.py` |
| `PolicyStatementCreate` | Pydantic model | Request schema for creating a policy statement | `backend/app/schemas/roles.py` |
| `PolicyStatementRead` | Pydantic model | Response schema for a policy statement with actions/resources/conditions | `backend/app/schemas/roles.py` |
| `GroupCreate` | Pydantic model | Request schema for creating a group | `backend/app/schemas/groups.py` |
| `GroupRead` | Pydantic model | Response schema for a group with member and role counts | `backend/app/schemas/groups.py` |
| `PlatformUserRead` | Pydantic model | Response schema for a platform user with role and group lists | `backend/app/schemas/platform_users.py` |
| `AccessRequestStatus` | Python Enum | `pending` / `approved` / `rejected` | `backend/app/schemas/access_requests.py` |
| `AccessRequestBatchCreate` | Pydantic model | Request schema for submitting a request batch; `group_ids` defaults to `[]` (empty list creates a group-less request) | `backend/app/schemas/access_requests.py` |
| `AccessRequestRead` | Pydantic model | Response schema for a single access request; `group_id` is nullable — consumers must handle `null` | `backend/app/schemas/access_requests.py` |
| `AccessRequestBatchRead` | Pydantic model | Response schema for a batch with its enriched request list | `backend/app/schemas/access_requests.py` |
| `ApproveRequestBody` | Pydantic model | Request schema for the approve PATCH payload; optional `group_id` — required by the service when the stored request has no assigned group | `backend/app/schemas/access_requests.py` |
| `PermissionDeniedDetail` | Pydantic model | 403 response body schema; contains `detail` string and nested `required_permission` object | `backend/app/schemas/errors.py` |
| `RequiredPermission` | Pydantic model | Nested model within `PermissionDeniedDetail`; contains `resource_type`, `action`, and `resource_id` fields | `backend/app/schemas/errors.py` |

### User Permission System — API Routes

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| User Tags API router | FastAPI router | CRUD endpoints for user tag definitions under `/api/v1/user-tags` | `backend/app/api/v1/user_tags.py` |
| User Roles API router | FastAPI router | CRUD endpoints for user roles and policy statements under `/api/v1/user-roles` | `backend/app/api/v1/user_roles.py` |
| `clone_role` | endpoint | `POST /api/v1/user-roles/{role_id}/clone` — deep-copies a role and all nested `PolicyStatement` / `PolicyAction` / `PolicyResource` / `PolicyTagCondition` rows in a single async transaction; validates name uniqueness (409) and source existence (404); requires `role:manage` | `backend/app/api/v1/user_roles.py` |
| `PolicyRouter` | FastAPI router | Read-only policy endpoint at `/api/v1/policy`; exposes `list_resource_types` returning the static `ResourceTypeManifest` as `ResourceTypeRead` list with `module_group` fields; requires `system::permissions:read` | `backend/app/api/v1/policy.py` |
| `list_resource_types` | endpoint | `GET /api/v1/policy/resource-types` — returns all resource types and their allowed actions from the in-memory `ResourceTypeManifest`; no database query | `backend/app/api/v1/policy.py` |
| User Groups API router | FastAPI router | CRUD and membership endpoints for user groups under `/api/v1/user-groups` | `backend/app/api/v1/user_groups.py` |
| Platform Users API router | FastAPI router | User list and assignment endpoints under `/api/v1/platform-users` | `backend/app/api/v1/platform_users.py` |
| `AccessRequestsRouter` | FastAPI router | Submit, list, approve, and reject endpoints under `/api/v1/user-access-requests`; admin endpoints (`pending`, `approve`, `reject`) guarded by `require_permission(RT_ACCESS_REQUEST, action)` | `backend/app/api/v1/user_access_requests.py` |
| `_enrich_request` | helper | Populates `group_name` and `requester_display_name` on `AccessRequestRead`; guards against `group_id` being `None` | `backend/app/api/v1/user_access_requests.py` |
| `submit_access_request` | endpoint | `POST /user-access-requests` — creates a request batch; accepts empty `group_ids` for a group-less request | `backend/app/api/v1/user_access_requests.py` |
| `approve_request` | endpoint | `PATCH /user-access-requests/{id}/approve` — approves a request; accepts optional `group_id` in body, required when the stored request has no group | `backend/app/api/v1/user_access_requests.py` |

### User Permission System — Frontend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `permissionsApi` | TypeScript module | Typed async functions for all permission management endpoints | `frontend/src/api/permissionsApi.ts` |
| `submitAccessRequest` | function | API call — `POST /user-access-requests`; accepts optional `groupIds` (empty array allowed) | `frontend/src/api/permissionsApi.ts` |
| `listGroupRoles` | function | API call — `GET /user-groups/{id}/roles`; returns roles currently assigned to the group | `frontend/src/api/permissionsApi.ts` |
| `assignGroupRole` | function | API call — `POST /user-groups/{id}/roles`; assigns a role to a group; 409 if already assigned | `frontend/src/api/permissionsApi.ts` |
| `removeGroupRole` | function | API call — `DELETE /user-groups/{id}/roles/{role_id}`; removes a role assignment from a group | `frontend/src/api/permissionsApi.ts` |
| `useGroupRoles` | hook | React Query `useQuery` hook; fetches roles assigned to a group; enabled only when `groupId` is non-null | `frontend/src/hooks/usePermissions.ts` |
| `useAssignGroupRole` | hook | React Query `useMutation` hook; calls `assignGroupRole`; invalidates the group roles query on success | `frontend/src/hooks/usePermissions.ts` |
| `useRemoveGroupRole` | hook | React Query `useMutation` hook; calls `removeGroupRole`; invalidates the group roles query on success | `frontend/src/hooks/usePermissions.ts` |
| `ManageGroupRolesModal` | component | Modal rendered within `GroupsPage`; displays current role assignments as removable chips; dropdown to add any unassigned platform role; all strings via `t()` | `frontend/src/components/permissions/ManageGroupRolesModal.tsx` |
| `GroupsPage` | component | Groups management page — group table with member/role management, IdP claim binding, and "Manage Roles" icon button that opens `ManageGroupRolesModal` | `frontend/src/pages/permissions/GroupsPage.tsx` |
| `approveAccessRequest` | function | API call — `PATCH /user-access-requests/{id}/approve`; includes optional `group_id` in body | `frontend/src/api/permissionsApi.ts` |
| `TagDefinition` (TS) | TypeScript interface | Client-side type for a tag definition | `frontend/src/types/permissions.ts` |
| `Role` (TS) | TypeScript interface | Client-side type for a role with policy statements | `frontend/src/types/permissions.ts` |
| `PolicyStatement` (TS) | TypeScript interface | Client-side type for a policy statement | `frontend/src/types/permissions.ts` |
| `Group` (TS) | TypeScript interface | Client-side type for a group | `frontend/src/types/permissions.ts` |
| `PlatformUser` (TS) | TypeScript interface | Client-side type for a platform user | `frontend/src/types/permissions.ts` |
| `AccessRequest` (TS) | TypeScript interface | Client-side type for a join request; `group_id` is optional | `frontend/src/types/permissions.ts` |
| `AccessRequestBatch` (TS) | TypeScript interface | Client-side type for a batch grouping multiple join requests | `frontend/src/types/permissions.ts` |
| `PolicyEffect` (TS) | TypeScript enum | `allow` / `deny` | `frontend/src/types/permissions.ts` |
| `AccessRequestStatus` (TS) | TypeScript enum | `pending` / `approved` / `rejected` | `frontend/src/types/permissions.ts` |
| `TagScope` (TS) | TypeScript enum | `global` / `resource_type` | `frontend/src/types/permissions.ts` |
| `ResourceTypeDef` | TypeScript interface | Client-side shape for a resource type entry: `{ resource_type: string; actions: string[] }` | `frontend/src/types/permissions.ts` |
| `RoleCloneCreate` | TypeScript interface | Request body for cloning a role: `{ name: string; description?: string }` | `frontend/src/types/permissions.ts` |
| `RESOURCE_TYPE_MANIFEST` | TypeScript const | Static frontend mirror of the backend `ResourceTypeManifest`; retained for display purposes; `AddStatementDialog` now uses `useResourceTypes()` backed by the API | `frontend/src/constants/resourceTypes.ts` |
| `listResourceTypes` | function | API call — `GET /api/v1/policy/resource-types`; returns `ResourceTypeDef[]` | `frontend/src/api/permissionsApi.ts` |
| `cloneRole` | function | API call — `POST /api/v1/user-roles/{id}/clone`; posts `RoleCloneCreate`; returns cloned `Role` | `frontend/src/api/permissionsApi.ts` |
| `useResourceTypes` | hook | React Query `useQuery` hook; fetches `listResourceTypes()`; cached indefinitely (static data) | `frontend/src/hooks/usePermissions.ts` |
| `useCloneRole` | hook | React Query `useMutation` hook; calls `cloneRole()`; invalidates `permissionKeys.roles` on success | `frontend/src/hooks/usePermissions.ts` |
| `PermissionsPage` | React component | Layout with tab navigation for the five permission sub-pages; admin-gated | `frontend/src/pages/permissions/PermissionsPage.tsx` |
| `TagsPage` | React component | Tag definitions table with add/edit/delete | `frontend/src/pages/permissions/TagsPage.tsx` |
| `RolesPage` | React component | Roles table with "Manage Policies" icon button per row that opens `RolePolicyDialog`; adds View JSON and Clone icon buttons per row | `frontend/src/pages/permissions/RolesPage.tsx` |
| `PolicyEditor` | React component | Policy statement card rendered inside `RolePolicyDialog`; displays module chip, action chips, resource definitions, and tag conditions per policy; owns Remove mutation | `frontend/src/components/permissions/PolicyEditor.tsx` |
| `AddStatementDialog` | React component | Self-contained dialog with structured form for creating a policy statement; uses FreeSolo autocomplete for resource type and action selection; owns `useCreatePolicyStatement` mutation; resets state on open/close | `frontend/src/components/permissions/AddStatementDialog.tsx` |
| `JSONViewModal` | React component | Read-only dialog rendering a role's effective policy as canonical JSON in a dark monospace block with clipboard copy action; derives data from `useRole(roleId)` | `frontend/src/components/permissions/JSONViewModal.tsx` |
| `CloneRoleDialog` | React component | Dialog for cloning a role; pre-populates name/description from source; owns `useCloneRole()` mutation and inline error display via `PermissionDeniedAlert` | `frontend/src/components/permissions/CloneRoleDialog.tsx` |
| `UsersPage` | React component | Paginated platform users table with role/group assignment | `frontend/src/pages/permissions/UsersPage.tsx` |
| `AccessRequestsPage` | React component | Top-level page containing the user and admin access request tabs | `frontend/src/pages/permissions/AccessRequestsPage.tsx` |
| `MyRequestsTab` | React component | User-facing request form (adaptive: hides group selection when user sees no groups) and request history list | `frontend/src/pages/permissions/AccessRequestsPage.tsx` |
| `PendingRequestsTab` | React component | Admin review table with approve/reject dialogs; renders "Unassigned" for group-less requests and provides a mandatory group-selection dropdown on approval | `frontend/src/pages/permissions/AccessRequestsPage.tsx` |
| `ManageAccessModal` | React component | Tabbed modal for assigning/removing roles and groups for a given user | `frontend/src/components/permissions/ManageAccessModal.tsx` |
| `en.json` (permissions.accessRequests) | i18n | Default locale file; contains translation keys under `permissions.accessRequests` for group-optional access request UI strings | `frontend/src/i18n/locales/en.json` |
| `useTagValueOptions` | React hook | Returns allowed values array for a given tag key from the tag definition store | `frontend/src/hooks/useTagValueOptions.ts` |
| `useSubmitAccessRequest` | React hook | React Query mutation for submitting an access request; `groupIds` parameter is optional | `frontend/src/hooks/usePermissions.ts` |
| `useApproveAccessRequest` | React hook | React Query mutation for approving an access request; threads optional `groupId` to `approveAccessRequest` | `frontend/src/hooks/usePermissions.ts` |

### Namespaced Resource Types — Backend Constants & Manifest

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `RT_AGENT_MANAGEMENT` | constant | Namespaced resource type `"agent::management"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_ROLES` | constant | Namespaced resource type `"agent::roles"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_IDENTITIES` | constant | Namespaced resource type `"agent::identities"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_RUNTIME_CONTROL` | constant | Namespaced resource type `"agent::runtime_control"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_SKILLS` | constant | Namespaced resource type `"agent::skills"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_SOPS` | constant | Namespaced resource type `"agent::sops"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_MODEL_CONFIGS` | constant | Namespaced resource type `"agent::model_configs"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_SCHEDULES` | constant | Namespaced resource type `"agent::schedules"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_TRAILS` | constant | Namespaced resource type `"agent::trails"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_HUMAN_INTERVENTION` | constant | Namespaced resource type `"agent::human_intervention"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_DATA_TYPES` | constant | Namespaced resource type `"agent::data_types"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_OUTPUTS` | constant | Namespaced resource type `"agent::outputs"` | `backend/app/core/resource_types.py` |
| `RT_INTEGRATION_MCP_HUB` | constant | Namespaced resource type `"integration::mcp_hub"` | `backend/app/core/resource_types.py` |
| `RT_INTEGRATION_NOTIFICATIONS` | constant | Namespaced resource type `"integration::notifications"` | `backend/app/core/resource_types.py` |
| `RT_INTEGRATION_CONTROL_CENTER` | constant | Namespaced resource type `"integration::control_center"` — entity-view permission for the platform-provisioned per-tenant Control Center MCP entity (`cc`). Actions: `read` (see the entity and its tools) and `manage` (grant/revoke its tools, configure sessions/rebinding). Deny-by-default; registered in `MODULE_GROUPS["integration"]` so `integration::*` / `*::*` cover admins. **Dual registration is mandatory** — backend manifest + `MODULE_GROUPS` AND the frontend `RESOURCE_TYPE_MANIFEST` + `integrations` submodule list; a missing side yields 403 for everyone (pinned by `ResourceTypeManifestMirror.test.ts`) | `backend/app/core/resource_types.py`, `frontend/src/constants/resourceTypes.ts` |
| `RT_SYSTEM_OBSERVABILITY` | constant | Namespaced resource type `"system::observability"` | `backend/app/core/resource_types.py` |
| `RT_SYSTEM_PERMISSIONS` | constant | Namespaced resource type `"system::permissions"` | `backend/app/core/resource_types.py` |
| `RT_SYSTEM_CONFIG` | constant | Namespaced resource type `"system::system_config"` | `backend/app/core/resource_types.py` |
| `ResourceTypeManifest` | dict | Maps every namespaced identifier to its allowed action set; single source of truth for all valid resource types (the count grows with each module; the frontend mirror must match) | `backend/app/core/resource_types.py` |
| `MODULE_GROUPS` (backend) | dict | Maps module names to their submodule lists (`agent`, `integration`, `system`, `platform`, `tenant`) | `backend/app/core/resource_types.py` |
| `get_module_from_resource_type` | function | Extracts module prefix from a namespaced identifier (e.g. `agent::trails` → `agent`) | `backend/app/core/resource_types.py` |
| `is_valid_wildcard` | function | Validates wildcard patterns (`*::*`, `module::*`) against the manifest | `backend/app/core/resource_types.py` |

### Namespaced Resource Types — Permission Engine

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `require_permission` | function | FastAPI dependency factory; passes the module string through to `PermissionEngine.authorize()` which handles `::`-delimited identifiers and wildcards | `backend/app/api/deps.py` |
| `BootstrapService._ensure_full_access_policy` | method | Creates `*::*` wildcard policy for the `system_admin` role on startup; uses explicit two-layer namespace format | `backend/app/services/permissions/bootstrap_service.py` |

### Namespaced Resource Types — API Routes & Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `batch_replace_policies` | function | `PUT /user-roles/{role_id}/policies/batch` endpoint handler; validates all policies against `ResourceTypeManifest`; atomic transaction | `backend/app/api/v1/user_roles.py` |
| `create_policy_statement` | function | `POST /user-roles/{id}/policies` endpoint handler; validates `module` against `ResourceTypeManifest` (rejects legacy flat values) | `backend/app/api/v1/user_roles.py` |
| `list_role_policies` | function | `GET /user-roles/{id}/policies` endpoint handler; returns namespaced `module` fields from migrated DB values | `backend/app/api/v1/user_roles.py` |
| `update_policy_statement` | function | `PATCH /user-roles/{id}/policies/{pid}` endpoint handler; validates `module` against `ResourceTypeManifest` | `backend/app/api/v1/user_roles.py` |
| `RolesRouter` | router | `APIRouter` hosting `POST/GET/PATCH/DELETE` for user roles and their nested policies at `/api/v1/user-roles` | `backend/app/api/v1/user_roles.py` |
| `ResourceTypeRead` | schema | Pydantic model for `/policy/resource-types` response; includes `resource_type` (namespaced), `actions` array, and `module_group` field | `backend/app/schemas/perm_roles.py` |
| `BatchPolicySaveRequest` (backend) | schema | Pydantic model for batch save request body with `policies: list[PolicyStatementCreate]` validation | `backend/app/schemas/perm_roles.py` |

### Namespaced Resource Types — Database Migration

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `namespace_resource_types` | migration | Alembic data migration: transforms 15 legacy flat values → 17 namespaced values in `policy_statements.module` and `policy_resources.resource_type`; idempotent (only updates rows without `::`); reversible | `backend/alembic/versions/868d278f04db_namespace_resource_types.py` |

### Namespaced Resource Types — Frontend Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `RolePolicyDialog` | component | Dialog wrapper for role policy editing; displays all policies in a single view; toggle between Form (FreeSolo selectors) and JSON Source Code views; bidirectional sync; batch save on submit; unsaved changes guard; `dialogError` surface | `frontend/src/components/permissions/RolePolicyDialog.tsx` |
| `FreeSoloResourceTypeSelect` | component | MUI `Autocomplete` with `freeSolo`; dropdown lists all manifest entries grouped by module; accepts free-text wildcard input | `frontend/src/components/permissions/FreeSoloResourceTypeSelect.tsx` |
| `FreeSoloActionSelect` | component | MUI `Autocomplete` with `freeSolo`; dropdown lists 10 standard actions; accepts `*` wildcard and custom action strings | `frontend/src/components/permissions/FreeSoloActionSelect.tsx` |
| `PermissionDeniedAlert` | component | Displays structured 403 error with resource type, action, and fallback message; used as primary error surface in dialogs | `frontend/src/components/permissions/PermissionDeniedAlert.tsx` |
| `PermissionErrorSnackbar` | component | Global snackbar for 403 permission denied events; interpolates `resource_type` via i18n | `frontend/src/components/permissions/PermissionErrorSnackbar.tsx` |
| `EditingPolicy` | type | Local state type for policies being edited in `RolePolicyDialog`; includes `_state` flag (`"unchanged" | "modified" | "added" | "deleted"`) for add/modify/delete tracking | `frontend/src/components/permissions/RolePolicyDialog.tsx` |
| `JsonValidationResult` | type | Union type for JSON validation outcomes: success, parse_error (with line/col), or structure_error (with messages) | `frontend/src/components/permissions/RolePolicyDialog.tsx` |

### Namespaced Resource Types — Frontend Data Layer

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `RESOURCE_TYPE_MANIFEST` | constant | Frontend mirror of the backend manifest with 28 namespaced entries | `frontend/src/constants/resourceTypes.ts` |
| `MODULE_GROUPS` (frontend) | constant | Module-to-submodule grouping for dropdown rendering | `frontend/src/constants/resourceTypes.ts` |
| `getActionsForResourceType` | function | Returns allowed actions for a namespaced resource type | `frontend/src/constants/resourceTypes.ts` |
| `getModuleForResourceType` | function | Extracts module prefix from a namespaced identifier | `frontend/src/constants/resourceTypes.ts` |
| `batchSaveRolePolicies` | function | API client for `PUT /user-roles/{role_id}/policies/batch` | `frontend/src/api/permissionsApi.ts` |
| `useBatchSaveRolePolicies` | hook | React Query `useMutation` hook for batch save; invalidates role and roles queries on success | `frontend/src/hooks/usePermissions.ts` |
| `BatchPolicySaveRequest` (TS) | type | TypeScript interface for batch save request body (`{ policies: PolicyStatementCreate[] }`) | `frontend/src/types/permissions.ts` |
| `useUnsavedChangesDialog` | hook | Composable hook for tracking dirty state; shows confirmation dialog on Cancel/Escape/backdrop dismiss | `frontend/src/hooks/useUnsavedChangesDialog.tsx` |
| `extractPermissionError` | function | Parses structured 403 error body from API responses | `frontend/src/utils/errorUtils.ts` |
| `parsePermissionError` | function | Extracts `PermissionDeniedDetail` from Axios error objects | `frontend/src/utils/permissionError.ts` |
