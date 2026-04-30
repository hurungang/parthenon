# Improve Role & Policy Management — Technical Specification

## Technical Overview
All new capabilities are delivered as frontend component additions on top of the existing permissions stack. Two lightweight backend endpoints are added: one to expose the `ResourceTypeManifest` over HTTP so the frontend can populate dropdowns without hardcoding, and one to deep-copy a role and its policy statements. No database schema changes are required. The existing `user_roles.py` router, `permissionsApi.ts` client, and `usePermissions.ts` hooks are extended in-place; new React components are created under `frontend/src/components/permissions/`.

## Component Breakdown

### Backend

**`policy.py` router**
New FastAPI router that exposes a single read-only endpoint returning the contents of `ResourceTypeManifest`. No database access required — the manifest is a static in-memory dict. Requires `role:read` permission.

**`user_roles.py` clone endpoint**
New route added to the existing `RolesRouter`. Reads source role and all nested `PolicyStatement` / `PolicyAction` / `PolicyResource` / `PolicyTagCondition` rows using eager loading, then inserts a full deep copy under a new `Role` record. Name uniqueness is validated before insert.

### Frontend API Layer

**`permissionsApi.ts` additions**
Two new typed async functions: one for fetching resource types, one for posting a clone request. Both follow the existing Axios `apiClient` pattern.

### Frontend Types

**`permissions.ts` additions**
`ResourceTypeDef` interface and `RoleCloneCreate` interface added to the existing types file.

### Frontend Hooks

**`usePermissions.ts` additions**
`useResourceTypes()` query hook (cached) and `useCloneRole()` mutation hook that invalidates the roles list cache on success.

### Frontend Components

**`PolicyEditor`**
Replaces the inline expanded row in `RolesPage`. Owns the fetch of a role's statements, the Remove mutation, and the trigger for `AddStatementDialog`. Pure display + delete; no add logic.

**`AddStatementDialog`**
Self-contained dialog with structured form. Replaces the existing inline Add Policy Statement dialog in `RolesPage`. Owns all statement-creation state and the `useCreatePolicyStatement` mutation. Resource type dropdown drives the actions dropdown.

**`JSONViewModal`**
Read-only dialog. Transforms the role's policy statements (from `useRole()`) into the canonical JSON shape shown in the prototype. Renders in a dark monospace code block with a clipboard copy action.

**`CloneRoleDialog`**
Dialog for cloning a role. Pre-populates name and description from the source role. Owns the `useCloneRole` mutation and inline error display.

**`RolesPage` (modified)**
Wires together `PolicyEditor`, `JSONViewModal`, and `CloneRoleDialog`. Adds two new icon buttons per role row (View JSON, Clone). Removes inline policy form state and `handleAddPolicy`.

## API Changes

### New Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/v1/policy/resource-types` | Returns all resource types and their allowed actions from `ResourceTypeManifest`. Response: array of `{ resource_type, actions }`. | `role:read` |
| `POST` | `/api/v1/user-roles/{role_id}/clone` | Deep-copies the source role and all its policy statements. Body: `{ name, description? }`. Response: new `PermRoleRead` (201). Returns 409 on duplicate name, 404 if source not found. | `role:manage` |

### Unchanged Endpoints (used by new components)

| Method | Path | Used by |
|--------|------|---------|
| `GET` | `/api/v1/user-roles/{role_id}` | `PolicyEditor`, `JSONViewModal` (via `useRole`) |
| `GET` | `/api/v1/user-roles/{role_id}/policies` | Existing; used by `useRole` |
| `POST` | `/api/v1/user-roles/{role_id}/policies` | `AddStatementDialog` |
| `DELETE` | `/api/v1/user-roles/{role_id}/policies/{policy_id}` | `PolicyEditor` |
| `GET` | `/api/v1/user-tags/definitions` | `AddStatementDialog` (tag key dropdown) |

## State Management

All server state is managed via TanStack Query (React Query). No Zustand store changes are required.

### New query keys (added to `permissionKeys`)
- `permissionKeys.resourceTypes` — caches `GET /api/v1/policy/resource-types`; never invalidated (static data)

### New mutation
- `useCloneRole` — on success, invalidates `permissionKeys.roles` to refresh the roles list

### Local dialog state (per component, not shared)
- `AddStatementDialog`: `resourceType`, `effect`, `actions`, `tagConditions[]` — reset on dialog open/close
- `CloneRoleDialog`: `name`, `description`, `dialogError` — reset on open/close
- `JSONViewModal`: stateless; derives output from `useRole(roleId)` data
- `PolicyEditor`: no local state beyond what the underlying hooks provide; `deleteError` per-statement remove action

### RolesPage new state fields
- `jsonViewRole: Role | null` — controls JSONViewModal open state
- `cloneTargetRole: Role | null` — controls CloneRoleDialog open state
- Removed: `policyRoleId`, `policyForm` (moved into `AddStatementDialog`)

## Data Access Patterns

### Resource type / actions catalogue
Frontend calls `GET /api/v1/policy/resource-types` once per session (React Query caches indefinitely). Backend reads `ResourceTypeManifest` from `backend/app/core/resource_types.py` — no DB query.

### Policy statement list (read)
`PolicyEditor` and `JSONViewModal` both consume `useRole(roleId)` which calls `GET /api/v1/user-roles/{id}`. The role object includes `policies: PolicyStatement[]` via eager loading in the backend. After any mutation (add or delete statement), React Query invalidates `permissionKeys.role(roleId)`, triggering a refetch.

### Tag value options
`AddStatementDialog` uses `useTagDefinitions()` for the tag key dropdown and passes the selected tag key to `useTagValueOptions(tagKey)`, which derives the allowed values from the already-loaded tag definitions without an additional API call.

### Role clone (write)
`CloneRoleDialog` calls `useCloneRole()` which posts to `POST /api/v1/user-roles/{id}/clone`. The backend performs all reads and inserts in a single async database transaction. On success, `permissionKeys.roles` is invalidated.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PolicyEditor` | component | Consolidated role policy statement list with Remove and Add Statement | `frontend/src/components/permissions/PolicyEditor.tsx` |
| `AddStatementDialog` | component | Add policy statement dialog with dropdowns for resource type, effect, and actions | `frontend/src/components/permissions/AddStatementDialog.tsx` |
| `JSONViewModal` | component | Read-only JSON view of all policy statements for a role with copy-to-clipboard | `frontend/src/components/permissions/JSONViewModal.tsx` |
| `CloneRoleDialog` | component | Clone a role dialog with pre-filled name/description | `frontend/src/components/permissions/CloneRoleDialog.tsx` |
| `RolesPage` | page | Roles management page; integrates PolicyEditor, JSONViewModal, CloneRoleDialog | `frontend/src/pages/permissions/RolesPage.tsx` |
| `useResourceTypes` | hook | React Query hook fetching resource type / actions catalogue | `frontend/src/hooks/usePermissions.ts` |
| `useCloneRole` | hook | React Query mutation hook for POST clone; invalidates roles list on success | `frontend/src/hooks/usePermissions.ts` |
| `useCreatePolicyStatement` | hook | Existing mutation; used by AddStatementDialog | `frontend/src/hooks/usePermissions.ts` |
| `useDeletePolicyStatement` | hook | Existing mutation; used by PolicyEditor | `frontend/src/hooks/usePermissions.ts` |
| `useRole` | hook | Existing query; used by PolicyEditor and JSONViewModal | `frontend/src/hooks/usePermissions.ts` |
| `useTagDefinitions` | hook | Existing query; used by AddStatementDialog for tag key dropdown | `frontend/src/hooks/usePermissions.ts` |
| `useTagValueOptions` | hook | Existing derived hook; used by AddStatementDialog per condition row | `frontend/src/hooks/useTagValueOptions.ts` |
| `listResourceTypes` | function | API function: GET /api/v1/policy/resource-types | `frontend/src/api/permissionsApi.ts` |
| `cloneRole` | function | API function: POST /api/v1/user-roles/{id}/clone | `frontend/src/api/permissionsApi.ts` |
| `ResourceTypeDef` | interface | `{ resource_type: string; actions: string[] }` | `frontend/src/types/permissions.ts` |
| `RoleCloneCreate` | interface | `{ name: string; description?: string }` | `frontend/src/types/permissions.ts` |
| `list_resource_types` | function | GET /api/v1/policy/resource-types handler | `backend/app/api/v1/policy.py` |
| `PolicyRouter` | router | FastAPI router for policy utility endpoints | `backend/app/api/v1/policy.py` |
| `clone_role` | function | POST /api/v1/user-roles/{role_id}/clone handler | `backend/app/api/v1/user_roles.py` |
| `ResourceTypeManifest` | constant | Static dict of resource types → allowed actions | `backend/app/core/resource_types.py` |
| `RolesRouter` | router | Existing FastAPI router for roles and policy statements | `backend/app/api/v1/user_roles.py` |
| `PolicyStatement` | model | SQLAlchemy ORM model for policy statements | `backend/app/db/models/policy_statement.py` |
| `PolicyAction` | model | SQLAlchemy ORM model for statement actions | `backend/app/db/models/policy_action.py` |
| `PolicyResource` | model | SQLAlchemy ORM model for statement resources | `backend/app/db/models/policy_resource.py` |
| `PolicyTagCondition` | model | SQLAlchemy ORM model for statement tag conditions | `backend/app/db/models/policy_tag_condition.py` |
| `PermRoleRead` | schema | Pydantic read schema for Role; returned by clone endpoint | `backend/app/schemas/perm_roles.py` |
| `PolicyEditor.test.tsx` | test | Unit tests for PolicyEditor component | `frontend/src/__tests__/PolicyEditor.test.tsx` |
| `AddStatementDialog.test.tsx` | test | Unit tests for AddStatementDialog component | `frontend/src/__tests__/AddStatementDialog.test.tsx` |
| `CloneRoleDialog.test.tsx` | test | Unit tests for CloneRoleDialog component | `frontend/src/__tests__/CloneRoleDialog.test.tsx` |
| `JSONViewModal.test.tsx` | test | Unit tests for JSONViewModal component | `frontend/src/__tests__/JSONViewModal.test.tsx` |
| `test_policy_endpoints.py` | test | Backend tests for /policy/resource-types and /clone endpoints | `backend/tests/api/v1/test_policy_endpoints.py` |
