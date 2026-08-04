# Implementation Plan: Namespaced Resource Types

## Overview

This change replaces the platform's 15 flat resource type identifiers (e.g. `agent`, `role`, `conversation`) with 17 two-layer namespaced identifiers (`agent::management`, `agent::roles`, `agent::trails`) using `::` as the delimiter and organised into three module groups (`agent`, `integration`, `system`) that mirror the sidebar navigation. The implementation spans backend manifest/engine changes, router-wide constant updates, database migration of legacy values, and frontend dropdown grouping — all without changing the sidebar navigation structure itself.

## Task Checklist

### Phase 1 — Backend Manifest & Engine

- [x] 1.1 — Update RT_* constants to namespaced format in `resource_types.py`
- [x] 1.2 — Restructure ResourceTypeManifest with module grouping and wildcard helpers
- [x] 1.3 — Update PermissionEngine.authorize() for `::`-delimited module matching and wildcards

### Phase 2 — Backend Router Updates

- [x] 2.1 — Audit all `require_permission()` calls across router files and map to new constants
- [x] 2.2 — Update all `require_permission()` calls to use namespaced constants

### Phase 3 — Bootstrap & Policy API

- [x] 3.1 — Update bootstrap_service.py system_admin wildcard policy to `*::*`
- [x] 3.2 — Update /policy/resource-types endpoint to return grouped manifest and update schemas

### Phase 4 — Database Migration

- [x] 4.1 — Create Alembic migration for legacy flat → namespaced value transformation

### Phase 5 — Frontend Manifest & Components

- [x] 5.1 — Update resourceTypes.ts with namespaced manifest and module group definitions
- [x] 5.2 — Update AddStatementDialog resource type dropdown to show grouped options
- [x] 5.3 — Update PolicyEditor and related components for namespaced display and validation

### Phase 6 — Backend Batch Save API

- [x] 6.1 — Create batch save schema `BatchPolicySaveRequest` in `perm_roles.py`
- [x] 6.2 — Implement `PUT /user-roles/{role_id}/policies/batch` endpoint with atomic transaction
- [x] 6.3 — Add `batchSaveRolePolicies` API client function in `permissionsApi.ts`
- [x] 6.4 — Add `BatchPolicySaveRequest` TypeScript type in `permissions.ts`

### Phase 7 — RolePolicyDialog & Supporting Components

- [x] 7.1 — Create RolePolicyDialog component with Form view / JSON Source Code view toggle
- [x] 7.2 — Implement JSON Source Code editor with Validate button and error display
- [x] 7.3 — Create freeSolo Autocomplete components for resource type and action selectors supporting wildcards
- [x] 7.4 — Implement unsaved changes detection and confirmation guard
- [x] 7.5 — Wire RolePolicyDialog into RolesPage replacing inline expansion

### Phase 8 — Testing

- [x] 8.1 — Update backend permission engine unit tests
- [x] 8.2 — Update backend API integration tests (policy, roles, permissions endpoints)
- [x] 8.3 — Update frontend PolicyEditor tests for namespaced resource types
- [x] 8.4 — Verify migration execution and rollback on a test database
- [x] 8.5 — End-to-end policy CRUD verification with namespaced types

## Phase 1 — Backend Manifest & Engine

### 1.1 — Update RT_* constants to namespaced format

**Scope**: File `backend/app/core/resource_types.py`.

Replace the 15 flat `RT_*` constants (`RT_AGENT = "agent"`, `RT_ROLE = "role"`, etc.) with 17 namespaced constants matching the `module::submodule` pattern defined in the PRD mapping table:

| New Constant | Value |
|---|---|
| `RT_AGENT_ROLES` | `"agent::roles"` |
| `RT_AGENT_IDENTITIES` | `"agent::identities"` |
| `RT_AGENT_MANAGEMENT` | `"agent::management"` |
| `RT_AGENT_RUNTIME_CONTROL` | `"agent::runtime_control"` |
| `RT_AGENT_SKILLS` | `"agent::skills"` |
| `RT_AGENT_SOPS` | `"agent::sops"` |
| `RT_AGENT_MODEL_CONFIGS` | `"agent::model_configs"` |
| `RT_AGENT_SCHEDULES` | `"agent::schedules"` |
| `RT_AGENT_TRAILS` | `"agent::trails"` |
| `RT_AGENT_HUMAN_INTERVENTION` | `"agent::human_intervention"` |
| `RT_AGENT_DATA_TYPES` | `"agent::data_types"` |
| `RT_AGENT_OUTPUTS` | `"agent::outputs"` |
| `RT_INTEGRATION_MCP_HUB` | `"integration::mcp_hub"` |
| `RT_INTEGRATION_NOTIFICATIONS` | `"integration::notifications"` |
| `RT_SYSTEM_OBSERVABILITY` | `"system::observability"` |
| `RT_SYSTEM_PERMISSIONS` | `"system::permissions"` |
| `RT_SYSTEM_CONFIG` | `"system::system_config"` |

All old flat constants (`RT_AGENT`, `RT_ROLE`, `RT_MCP_SERVER`, `RT_CONVERSATION`, `RT_GROUP`, `RT_USER`, `RT_TAG`, `RT_ACCESS_REQUEST`, `RT_PERMISSIONS`, `RT_SKILL`, `RT_SCHEDULING`, `RT_NOTIFICATION`, `RT_RESULT`, `RT_DATA_TYPE`, `RT_INTERVENE`) are removed.

**Done when**:
- 17 `Final[str]` constants exist with the exact namespaced values listed above
- No flat resource type constants remain
- A new `MODULE_GROUPS` constant maps module names to their submodule lists (`{"agent": [...], "integration": [...], "system": [...]}`)
- Python syntax check passes

### 1.2 — Restructure ResourceTypeManifest with module grouping

**Scope**: File `backend/app/core/resource_types.py`.

Restructure the `ResourceTypeManifest` dictionary so that keys are the 17 namespaced identifiers. Each entry retains its `"actions"` list from the legacy manifest, mapped per the migration table in `data-model.md`:

| Namespaced Key | Inherited Actions From |
|---|---|
| `agent::roles` | `role` |
| `agent::identities` | new (assign actions: `read`, `manage`) |
| `agent::management` | `agent` |
| `agent::runtime_control` | new (assign actions: `read`, `execute`) |
| `agent::skills` | `skill` |
| `agent::sops` | new (assign actions: `read`, `manage`) |
| `agent::model_configs` | new (assign actions: `read`, `manage`) |
| `agent::schedules` | `scheduling` |
| `agent::trails` | merge of `conversation` + `result` |
| `agent::human_intervention` | `intervene` |
| `agent::data_types` | `data_type` |
| `agent::outputs` | new (assign actions: `read`) |
| `integration::mcp_hub` | `mcp_server` |
| `integration::notifications` | `notification` |
| `system::observability` | new (assign actions: `read`) |
| `system::permissions` | merge of `permissions` + `group` + `user` + `tag` + `access_request` |
| `system::system_config` | new (assign actions: `read`, `manage`) |

For consolidation merges (e.g., `conversation → agent::trails`, `permissions → system::permissions`), take the union of all actions from the source types.

New submodules that had no prior legacy permission get default action sets as noted above.

Add a helper function `get_module_from_resource_type(rt: str) -> str | None` that extracts the module prefix (everything before `::`) so consumers can group or filter by module.

Add a helper function `is_valid_wildcard(value: str) -> bool` that accepts bare wildcards (`*::*`) or module-level wildcards (`agent::*`, `integration::*`, `system::*`).

**Done when**:
- `ResourceTypeManifest` has exactly 17 keys, all namespaced
- `MODULE_GROUPS` lists all submodules per module
- `get_module_from_resource_type()` correctly extracts the module prefix
- `is_valid_wildcard()` returns `True` for valid wildcards and `False` otherwise
- Python syntax check passes

### 1.3 — Update PermissionEngine.authorize() for `::`-delimited module matching and wildcards

**Scope**: File `backend/app/services/permissions/permission_engine.py`.

Update the `authorize()` method to handle the new namespace format:

1. **Manifest validation** (lines 56-66): Update `module not in ResourceTypeManifest` check so that:
   - Bare wildcard `*::*` bypasses manifest validation (already handled by `module != "*"` guard — update this to `module not in ({"*", "*::*"})`)
   - Module-level wildcards (`agent::*`, `integration::*`, `system::*`) bypass manifest validation for the submodule lookup but still validate the module prefix exists in `MODULE_GROUPS`
   - Standard `module::submodule` identifiers are validated directly against `ResourceTypeManifest`

2. **Policy statement fetching** (line 76): Update the `or_(PolicyStatement.module == module, PolicyStatement.module == "*")` filter to also match:
   - `*::*` wildcard policies (add `PolicyStatement.module == "*::*"`)
   - Module-level wildcard policies when the requested module matches (e.g., requesting `agent::management` should match a policy with `module = "agent::*"`)
   
   The WHERE clause must handle:
   - Exact match: `module == module`
   - Global wildcards: `module == "*"` OR `module == "*::*"`
   - Module-level wildcards: `module == "agent::*"` when the requested module starts with `agent::`

3. **Action validation** (lines 62-65): When a wildcard is used (`*::*`, `module::*`), the action validation against `ResourceTypeManifest[module]["actions"]` must be skipped — wildcard-type modules are not direct keys in the manifest.

4. **Backward compatibility**: Keep support for legacy `*` wildcard in the `PolicyStatement.module` filter for the transition period, logically treating it as equivalent to `*::*`.

**Done when**:
- `authorize("agent::management", "read", ...)` succeeds for a user with `*::*` wildcard policy
- `authorize("agent::management", "read", ...)` succeeds for a user with `agent::*` wildcard policy
- `authorize("agent::skills", "create", ...)` succeeds for a user with `agent::*` wildcard policy
- `authorize("integration::mcp_hub", "read", ...)` succeeds for a user with `integration::*` wildcard policy
- `authorize("invalid::type", "read", ...)` returns `allowed=False` with "Unknown resource type" reason
- Legacy `*` wildcard policies still match all modules (backward compatibility)
- Python syntax check passes

## Phase 2 — Backend Router Updates

### 2.1 — Audit all `require_permission()` calls across router files and map to new constants

**Scope**: All files under `backend/app/api/v1/`.

Create a complete audit of every `require_permission()` call site. Map each legacy constant usage to its new namespaced equivalent:

| Router File | Legacy Constant(s) | New Constant(s) |
|---|---|---|
| `agents.py` | `RT_AGENT` | `RT_AGENT_MANAGEMENT`, `RT_AGENT_IDENTITIES`, `RT_AGENT_RUNTIME_CONTROL`, `RT_AGENT_SKILLS`, `RT_AGENT_SOPS`, `RT_AGENT_MODEL_CONFIGS`, `RT_AGENT_SCHEDULES`, `RT_AGENT_TRAILS`, `RT_AGENT_DATA_TYPES`, `RT_AGENT_OUTPUTS` |
| `skills.py` | `RT_SKILL` | `RT_AGENT_SKILLS` |
| `sops.py` | (currently none/minimal) | `RT_AGENT_SOPS` |
| `scheduling.py` | `RT_SCHEDULING` | `RT_AGENT_SCHEDULES` |
| `conversations.py` | `RT_CONVERSATION` | `RT_AGENT_TRAILS` |
| `results.py` | `RT_RESULT` | `RT_AGENT_TRAILS` |
| `intervene.py` | `RT_INTERVENE` | `RT_AGENT_HUMAN_INTERVENTION` |
| `data_types.py` | `RT_DATA_TYPE` | `RT_AGENT_DATA_TYPES` |
| `agent_outputs.py` | `RT_RESULT` | `RT_AGENT_OUTPUTS` |
| `platform_users.py` | `RT_USER` | `RT_SYSTEM_PERMISSIONS` |
| `user_roles.py` | `RT_PERMISSIONS`, `RT_ROLE` | `RT_SYSTEM_PERMISSIONS` |
| `user_groups.py` | `RT_GROUP` | `RT_SYSTEM_PERMISSIONS` |
| `user_tags.py` | `RT_TAG` | `RT_SYSTEM_PERMISSIONS` |
| `user_access_requests.py` | `RT_ACCESS_REQUEST` | `RT_SYSTEM_PERMISSIONS` |
| `mcp_hub.py` | `RT_MCP_SERVER` | `RT_INTEGRATION_MCP_HUB` |
| `notifications.py` | `RT_NOTIFICATION` | `RT_INTEGRATION_NOTIFICATIONS` |
| `policy.py` | `RT_ROLE` | `RT_SYSTEM_PERMISSIONS` |
| `certificates.py` | (internal only) | N/A (no change needed) |
| `setup.py` | (public) | N/A (no change needed) |
| `identity.py` | (no permissions) | N/A (no change needed) |
| `telemetry.py` | (no permissions) | N/A (no change needed) |

**Done when**:
- Complete mapping table documented in this section
- All 198+ `require_permission()` call sites identified and mapped to their new constants
- Special attention to `agents.py` which uses `RT_AGENT` for all agent-related endpoints but needs to be split across multiple namespaced submodules (management, identities, runtime_control, etc.)

### 2.2 — Update all `require_permission()` calls to use namespaced constants

**Scope**: All files listed in task 2.1.

For each router file:
1. Update the import to reference only the new constants needed by that router
2. Replace each `require_permission(OLD_CONST, "action")` call with the appropriate new constant
3. For multi-endpoint routers like `agents.py` that cover multiple submodules (management, identities, runtime_control, schedules, trails, etc.), assign the correct submodule constant per endpoint rather than using a single module-wide constant

**Done when**:
- Zero references to old flat constants (`RT_AGENT`, `RT_ROLE`, `RT_MCP_SERVER`, etc.) remain in any `require_permission()` call
- All 198+ calls use namespaced constants
- Python syntax check passes across all modified files
- All imports updated to reflect new constant names

## Phase 3 — Bootstrap & Policy API

### 3.1 — Update bootstrap_service.py system_admin wildcard policy

**Scope**: File `backend/app/services/permissions/bootstrap_service.py`.

In `_ensure_full_access_policy()` (line 79), change the `PolicyStatement.module` from `"*"` to `"*::*"`. This ensures the system_admin role retains full access after the namespace migration.

Also update the `PolicyResource.resource_type` from `"*"` to `"*::*"` (line 87) to keep consistency.

**Done when**:
- `PolicyStatement(module="*::*")` is used for the bootstrap wildcard policy
- Existing system_admin role on a test database continues to have access to all endpoints after migration
- Python syntax check passes

### 3.2 — Update /policy/resource-types endpoint and related schemas

**Scope**: Files `backend/app/api/v1/policy.py` and `backend/app/schemas/perm_roles.py`.

1. **Route `/policy/resource-types`** (`policy.py`): Update the endpoint to return namespaced resource types grouped by module. The response format should include a `modules` grouping alongside the flat list for backward compatibility.

2. **Schema** (`perm_roles.py`): 
   - Update `ResourceTypeRead` to optionally include a `module` field (the prefix before `::`)
   - Add a new `ResourceTypeGroupedResponse` schema or extend the endpoint response to provide module-grouped data

3. **Route guard**: Change `require_permission(RT_ROLE, "read")` to `require_permission(RT_SYSTEM_PERMISSIONS, "read")` (the old `RT_ROLE` constant no longer exists; `system::permissions` is the correct replacement for the consolidated permissions module)

**Done when**:
- `GET /policy/resource-types` returns all 17 namespaced resource types with their actions
- Response includes module grouping information
- Python syntax check passes

## Phase 4 — Database Migration

### 4.1 — Create Alembic migration for legacy flat → namespaced value transformation

**Scope**: New file under `backend/alembic/versions/`.

Create an Alembic migration (auto-generated with `--autogenerate` then hand-edited) that transforms:
- `policy_statements.module` — update all legacy flat values to their namespaced equivalents
- `policy_resources.resource_type` — update all legacy flat values to their namespaced equivalents
- Wildcard `*` values in both columns — transform to `*::*`

Use explicit UPDATE statements mapping each legacy value. The migration must:

1. **Direct 1:1 maps** — Simple renames:
   - `agent` → `agent::management`
   - `role` → `agent::roles`
   - `skill` → `agent::skills`
   - `intervene` → `agent::human_intervention`
   - `scheduling` → `agent::schedules`
   - `mcp_server` → `integration::mcp_hub`
   - `notification` → `integration::notifications`
   - `data_type` → `agent::data_types`

2. **Many:1 consolidations** — Multiple legacy values → single namespaced value:
   - `conversation` AND `result` → both become `agent::trails`
   - `permissions` AND `group` AND `user` AND `tag` AND `access_request` → all become `system::permissions`

3. **Wildcard transformation**:
   - `*` → `*::*`

4. **Idempotent**: Use `WHERE` clauses that only match the old values (skip rows that already have `::` in their value) so the migration can be safely re-run.

5. **Downgrade**: The `downgrade()` function should reverse the transformations where possible. For consolidation reversals, map `agent::trails` back to `conversation` (not to `result`) and `system::permissions` back to `permissions` (not the other four consolidated types).

**Done when**:
- `alembic revision --autogenerate -m "namespace_resource_types"` produces a migration file
- Migration file manually edited with explicit UPDATE statements for all 15 legacy values
- `alembic upgrade head` succeeds on a test database with existing policy data
- All legacy flat values in `policy_statements.module` are transformed to namespaced equivalents
- All legacy flat values in `policy_resources.resource_type` are transformed to namespaced equivalents
- `alembic downgrade -1` successfully reverts the migration
- Wildcard `*` values become `*::*`

## Phase 5 — Frontend Manifest & Components

### 5.1 — Update resourceTypes.ts with namespaced manifest and module group definitions

**Scope**: File `frontend/src/constants/resourceTypes.ts`.

Replace the flat `RESOURCE_TYPES` constants and `RESOURCE_TYPE_MANIFEST` with the namespaced equivalents that mirror the backend `ResourceTypeManifest`:

1. Remove the old `RESOURCE_TYPES` flat constant object
2. Replace with namespaced type constants using the same 17 identifiers
3. Update `RESOURCE_TYPE_MANIFEST` with the 17 namespaced keys and their inherited action arrays
4. Add a `MODULE_GROUPS` constant:
   ```
   {
     agents: { label: "...", submodules: ["agent::roles", "agent::identities", ...] },
     integrations: { label: "...", submodules: ["integration::mcp_hub", ...] },
     system: { label: "...", submodules: ["system::observability", ...] }
   }
   ```
5. Update `RESOURCE_TYPE_OPTIONS` to return namespaced keys
6. Update `getActionsForResourceType()` to use the new manifest keys
7. Add a `getModuleForResourceType()` helper that extracts the module prefix

**Done when**:
- `RESOURCE_TYPE_MANIFEST` has 17 namespaced keys matching the backend manifest
- `MODULE_GROUPS` defines all three module groups with their submodule arrays
- `getActionsForResourceType("agent::management")` returns `["create", "read", "update", "delete", "execute"]`
- `getModuleForResourceType("agent::management")` returns `"agent"`
- TypeScript compilation passes with no errors

### 5.2 — Update AddStatementDialog resource type dropdown to show grouped options

**Scope**: File `frontend/src/components/permissions/AddStatementDialog.tsx`.

Update the resource type Select dropdown (line 272-283) to display options grouped by module:

1. Import the `MODULE_GROUPS` constant from `resourceTypes.ts`
2. Replace the flat `<MenuItem>` list with grouped `<ListSubheader>` entries using MUI Select's native grouping support or a custom render using `ListSubheader` components:
   - First group: `Agents` (12 submodules)
   - Second group: `Integrations` (2 submodules)
   - Third group: `System` (3 submodules)
3. Each menu item displays the submodule name (the portion after `::`) as the visible label with the namespaced identifier as the value
4. Update the `handleResourceTypeChange` to reset actions and resources when the type changes (existing logic, verify it still works)
5. Update the `ResourceRowEditor` to display the namespaced `resource_type` value (line 126 currently shows `resourceType` directly — ensure it displays nicely)

**Done when**:
- Resource type dropdown shows all 17 options grouped under `Agents`, `Integrations`, and `System` headings
- Selecting a resource type populates the available actions from the manifest
- Form submission sends the `module::submodule` format as the `module` field
- Creating a new policy statement with a namespaced type succeeds via the API
- Editing an existing policy statement correctly pre-populates the namespaced resource type

### 5.3 — Update PolicyEditor and related components for namespaced display and validation

**Scope**: Files:
- `frontend/src/components/permissions/PolicyEditor.tsx`
- `frontend/src/components/permissions/PermissionDeniedAlert.tsx`
- `frontend/src/components/permissions/PermissionErrorSnackbar.tsx`
- `frontend/src/hooks/usePermissions.ts`

1. **PolicyEditor** — The `module` field displayed in the policy card chip (line 99) already renders `policy.module`. Ensure it displays namespaced values correctly (they are longer strings — verify the chip doesn't overflow).

2. **PermissionDeniedAlert** — The `required_permission.resource_type` field will now contain namespaced values like `agent::management`. Ensure the error display (line 52) renders these clearly. No structural changes are likely needed as it already renders `required_permission.resource_type` as a string.

3. **PermissionErrorSnackbar** — Similar to above; the snackbar message (line 24-28) interpolates `resource_type` via `t()` translation. Ensure the i18n key `permissions.errors.missingPermission` accepts namespaced values.

4. **usePermissions hook** — Verify that `useResourceTypes()` (which calls `listResourceTypes()`) correctly parses the updated API response format with module grouping. Update types as needed.

**Done when**:
- Policy cards display namespaced resource types without layout issues
- Error alerts and snackbars display namespaced resource types legibly
- All CRUD operations (create, read, edit, delete) work with namespaced resource types
- `useResourceTypes()` returns properly typed data with the new API response format
- TypeScript compilation passes

## Phase 6 — Backend Batch Save API

### 6.1 — Create batch save schema in perm_roles.py

**Scope**: File `backend/app/schemas/perm_roles.py`.

Add a new Pydantic v2 schema `BatchPolicySaveRequest` that accepts a `policies` array of `PolicyStatementCreate` objects. Each policy in the array follows the same structure as the existing single-policy creation endpoint — including `module`, `actions`, `effect`, `resources`, and `tag_conditions` fields.

Add validation at the schema level:
- `policies` must be a list (accepts empty list to clear all policies)
- Each policy's `module` field is validated against `ResourceTypeManifest` keys and valid wildcard patterns
- Each policy's `actions` array must not be empty

**Done when**:
- `BatchPolicySaveRequest` schema defined with `policies: list[PolicyStatementCreate]` field
- JSON Schema validation accepts valid policies and rejects invalid ones
- Python syntax check passes

### 6.2 — Implement `PUT /user-roles/{role_id}/policies/batch` endpoint with atomic transaction

**Scope**: File `backend/app/api/v1/user_roles.py`.

Add a new route `PUT /user-roles/{role_id}/policies/batch` to the `RolesRouter`. The endpoint:

1. **Permission gate**: `require_permission(RT_SYSTEM_PERMISSIONS, "manage")`
2. **Role existence check**: Returns 404 if the role does not exist
3. **Atomic transaction**: Wraps all operations in a single database transaction:
   - Delete all existing `PolicyStatement` records for the role (cascading to `PolicyResource`, `PolicyAction`, `PolicyTagCondition`)
   - For each policy in the request body, create a new `PolicyStatement` with its nested `PolicyResource`, `PolicyAction`, and `PolicyTagCondition` records
4. **Commit or rollback**: If any policy creation fails (validation error, foreign key violation), roll back the entire transaction — the role retains its original policies
5. **Response**: Returns the updated list of policy statements (same format as `GET /user-roles/{role_id}/policies`) with HTTP 200

**Done when**:
- `PUT /user-roles/{role_id}/policies/batch` replaces all policies atomically
- Batch with valid policies succeeds and returns updated policy list
- Batch with one invalid policy rolls back entirely (original policies preserved)
- Empty `policies` array clears all role policies
- Non-existent role returns 404
- Python syntax check passes

### 6.3 — Add `batchSaveRolePolicies` API client function in permissionsApi.ts

**Scope**: File `frontend/src/api/permissionsApi.ts`.

Add a typed API client function `batchSaveRolePolicies(roleId: string, policies: PolicyStatementCreate[]): Promise<PolicyStatement[]>` that sends a `PUT` request to `/user-roles/{role_id}/policies/batch`. Uses the existing `apiClient` base URL and Axios instance.

**Done when**:
- Function defined with correct TypeScript types
- Function calls `apiClient.put()` with the correct URL and body shape
- TypeScript compilation passes

### 6.4 — Add `BatchPolicySaveRequest` TypeScript type in permissions.ts

**Scope**: File `frontend/src/types/permissions.ts`.

Add a TypeScript interface `BatchPolicySaveRequest` with a `policies` field typed as `PolicyStatementCreate[]`. This mirrors the backend `BatchPolicySaveRequest` Pydantic schema.

**Done when**:
- `BatchPolicySaveRequest` interface defined with correct type
- `PolicyStatementCreate` reused for individual policy entries
- TypeScript compilation passes

## Phase 7 — RolePolicyDialog & Supporting Components

### 7.1 — Create RolePolicyDialog component with Form view / JSON Source Code view toggle

**Scope**: New file `frontend/src/components/permissions/RolePolicyDialog.tsx`.

Create a dialog component that opens when the user clicks the policy edit action on a role row in `RolesPage`. The component:

1. **Dialog layout**: MUI `Dialog` with a title showing the role name, a segmented toggle (MUI `ToggleButtonGroup`) at the top for `Form` / `JSON`, a scrollable content area for the active view, and footer buttons `Cancel` and `Save`
2. **Data loading**: On open, call `GET /user-roles/{role_id}/policies` and populate local `policies` state array. Each policy object gets a `_state` discriminator (`"unchanged"`, `"modified"`, `"added"`, `"deleted"`)
3. **Form view**: Renders each policy as an editable row using `FreeSoloResourceTypeSelect` and `FreeSoloActionSelect`, with an `Add Policy` button to append new rows and a delete button per row. Deleted rows are visually struck through and hidden on save
4. **JSON view**: Renders the `JsonPolicyEditor` component (task 7.2) with the serialized policies array
5. **View toggle**: Toggling Form→JSON serializes current `policies` state to JSON text; toggling JSON→Form parses JSON text back into `policies` state. Changes in either view are preserved bidirectionally
6. **Save flow**: On Save click, collect non-deleted policies from `policies` state (or parse from JSON view), call `batchSaveRolePolicies()`. On success, close dialog and trigger parent table refresh via callback. On failure, display error via `PermissionDeniedAlert` and keep dialog open
7. **Dialog error handling**: Follows the standard dialog error pattern — `dialogError` state, try-catch wrapping save, `PermissionDeniedAlert` display
8. **Unsaved changes guard** (task 7.4): Detect changes by comparing current `policies` with initial load state. On Cancel/Escape/backdrop with changes, show confirmation dialog

**Done when**:
- Dialog opens loaded with all existing role policies in Form view
- Toggle Form↔JSON preserves all changes bidirectionally
- Add/edit/delete policy rows works in Form view
- Save calls `PUT /user-roles/{role_id}/policies/batch` with correct payload
- Save success closes dialog and triggers parent refresh
- Save failure displays error and keeps dialog open
- Dialog error handling follows the standard pattern
- TypeScript compilation passes

### 7.2 — Implement JSON Source Code editor with Validate button and error display

**Scope**: New file `frontend/src/components/permissions/JsonPolicyEditor.tsx`.

Create a sub-component rendered inside `RolePolicyDialog` when JSON view is active. The component:

1. **Textarea**: MUI `TextField` with `multiline` and `minRows={15}`, monospace font, displaying the current policies as formatted JSON (via `JSON.stringify(policies, null, 2)`)
2. **Validate button**: MUI `Button` below the textarea labelled "Validate". On click, performs synchronous client-side validation:
   - **Parse check**: `JSON.parse(textareaValue)` — catches `SyntaxError` and displays line/column reference
   - **Structure check**: Verifies the parsed result is an object with a `policies` array field; reports error if missing
   - **Content check**: Iterates each policy in the `policies` array, verifying `resource_type` is a non-empty string in `module::submodule` or valid wildcard format, and `actions` is a non-empty array; reports specific errors per policy index
3. **Error display**: Displays validation errors in an MUI `Alert` with `severity="error"` below the Validate button. Parse errors show the line number and character position. Structure errors list each missing or invalid field with the policy index
4. **Success indicator**: On valid JSON, displays an MUI `Alert` with `severity="success"` and a message confirming the JSON is parseable and structurally correct
5. **Validation blocking**: The parent `RolePolicyDialog` checks `validationResult` before allowing save from JSON view — if validation has not been run or errors exist, save is blocked

**Done when**:
- Validate button catches `SyntaxError` and displays error with line/column reference
- Validate button detects missing `policies` array and displays structure error
- Validate button detects empty/missing `resource_type` or `actions` per policy entry
- Validate button detects flat resource type values and flags them as invalid
- Valid JSON displays success indicator
- Validation errors are cleared when textarea content changes
- TypeScript compilation passes

### 7.3 — Create freeSolo Autocomplete components for resource type and action selectors supporting wildcards

**Scope**: New files:
- `frontend/src/components/permissions/FreeSoloResourceTypeSelect.tsx`
- `frontend/src/components/permissions/FreeSoloActionSelect.tsx`

Create two reusable autocomplete components using MUI `Autocomplete` with `freeSolo` mode:

**FreeSoloResourceTypeSelect**:
1. Uses MUI `Autocomplete` with `freeSolo={true}` and `options={allResourceTypes}` (all 17 manifest values plus `agent::*`, `integration::*`, `system::*`, `*::*` wildcard options)
2. Options grouped by module (`agent`, `integration`, `system`) using MUI's `groupBy` prop
3. Accepts free-text typing for wildcards not in the predefined list (e.g., `agent::mana*`, `*`, custom module patterns)
4. Displays a subtle visual distinction (different chip colour or italic text) for free-text values not in the manifest
5. Props: `value`, `onChange`, `disabled`, `error`, `helperText` — standard controlled component interface

**FreeSoloActionSelect**:
1. Uses MUI `Autocomplete` with `freeSolo={true}`, `multiple={true}`, and `options={STANDARD_ACTIONS}` (the 10 predefined actions)
2. Accepts free-text typing for wildcard (`*`) and custom action strings
3. Chip-based display for multiple selected/typed values
4. Props: `value: string[]`, `onChange`, `disabled`, `error`, `helperText`

Both components accept an optional `manifestValues: string[]` prop to customise the dropdown options (defaulting to the full manifest).

**Done when**:
- Resource type autocomplete accepts `agent::*` as free-text input and displays it as a selected value
- Resource type autocomplete accepts `agent::mana*` as free-text input
- Resource type autocomplete accepts `*::*` as free-text input
- Resource type autocomplete dropdown shows manifest values grouped by module
- Action autocomplete accepts `*` as free-text input and displays as a chip
- Action autocomplete accepts custom action strings (e.g., `deploy`) as free-text input
- Action autocomplete dropdown shows the 10 standard actions
- Both components follow standard MUI controlled-component interface
- TypeScript compilation passes

### 7.4 — Implement unsaved changes detection and confirmation guard

**Scope**: New file `frontend/src/hooks/useUnsavedChangesDialog.ts`.

Create a composable hook that can be reused across dialogs. Accepts:
- `isDirty: boolean` — whether there are unsaved changes
- `allowClose: boolean` — whether the dialog may currently close (e.g., not during save)

Returns:
- `handleClose(closeFn: () => void): void` — call on Cancel, Escape, or backdrop click; shows confirmation if dirty, otherwise closes directly
- `ConfirmationDialog` — MUI `Dialog` rendered by the hook, asking "Discard unsaved changes?" with "Keep Editing" (cancel) and "Discard" (confirm) buttons

The hook manages the open/close state of the confirmation dialog internally.

**Integration in RolePolicyDialog**:
- `isDirty` derived from comparing current `policies` state with the initial loaded state (deep comparison ignoring `_state` flags)
- Dialog `onClose` prop uses `handleClose` — on backdrop click and Escape key, the hook intercepts and shows confirmation if dirty
- Cancel button uses `handleClose` directly

**Done when**:
- Clicking Cancel with unsaved changes shows confirmation dialog
- Pressing Escape with unsaved changes shows confirmation dialog
- Clicking backdrop with unsaved changes shows confirmation dialog or is disabled
- "Discard" in confirmation closes both dialogs without saving
- "Keep Editing" in confirmation keeps the RolePolicyDialog open with changes intact
- Closing with no unsaved changes dismisses immediately without confirmation
- TypeScript compilation passes

### 7.5 — Wire RolePolicyDialog into RolesPage replacing inline expansion

**Scope**: File `frontend/src/pages/permissions/RolesPage.tsx`.

Replace the current inline row expansion for policy editing with the `RolePolicyDialog`:

1. **Remove inline expansion**: Delete or comment out the inline policy editing UI that expands within the table row
2. **Add dialog trigger**: Each role row gets an "Edit Policies" action button (or use the existing edit button) that opens `RolePolicyDialog` for that role
3. **Open state**: Manage `dialogOpen: boolean` and `selectedRoleId: string | null` in `RolesPage` state
4. **Refresh callback**: Pass an `onSave` callback to `RolePolicyDialog` that invalidates the React Query cache for role policies (`queryClient.invalidateQueries({ queryKey: ['rolePolicies', roleId] })`)
5. **Policy count update**: After save, the role's policy count badge in the table row refreshes via the invalidated query

**Done when**:
- Clicking policy edit on a role row opens the RolePolicyDialog instead of expanding inline
- Dialog shows all existing policies in Form view
- Saving via dialog closes it and refreshes the parent table
- Policy count badges update after save without page reload
- Inline expansion code is removed (or clearly marked as deprecated)
- TypeScript compilation passes

## Phase 8 — Testing

### 8.1 — Update backend permission engine unit tests

**Scope**: File `backend/tests/unit/test_permission_engine.py`.

Update existing tests and add new test cases:
- Test `*::*` wildcard matching (any module, any action)
- Test `agent::*` wildcard matching (specific module, any submodule)
- Test `integration::*` wildcard matching
- Test `system::*` wildcard matching
- Test exact namespaced module matching (`agent::management`)
- Test invalid namespaced module rejection (`invalid::type`)
- Test action validation for namespaced modules
- Test backward compatibility with legacy `*` wildcard (if retained)

**Done when**:
- All new wildcard test cases pass
- All existing tests pass after constant updates
- Test coverage includes both positive (allowed) and negative (denied) scenarios for each wildcard level

### 8.2 — Update backend API integration tests

**Scope**: Files:
- `backend/tests/api/v1/test_policy_endpoints.py`
- `backend/tests/api/v1/test_roles_api.py`
- `backend/tests/api/v1/test_permissions_api.py`

Update test cases to use namespaced resource types when creating/reading policy statements. Verify:
- Policy creation with namespaced `module` values succeeds
- `GET /policy/resource-types` returns namespaced types with module grouping
- Policy statements persisted in the database use the new format after migration
- `require_permission` checks in router endpoints use new constants (verify via test infrastructure, not by testing the router directly)

**Done when**:
- All API tests pass with namespaced resource types
- No test references legacy flat resource type strings in test data

### 8.3 — Update frontend PolicyEditor tests

**Scope**: File `frontend/src/__tests__/PolicyEditor.test.tsx`.

Update test cases:
- Mock API responses to return namespaced resource types with module grouping
- Test that the dropdown renders grouped options
- Test CRUD operations with namespaced types
- Test form pre-population in edit mode with namespaced types

**Done when**:
- All PolicyEditor tests pass
- Tests cover grouped dropdown rendering
- Tests cover namespaced type CRUD flows

### 8.4 — Verify migration execution and rollback on a test database

**Procedure**:
1. Populate a test database with policy data using legacy flat resource type values
2. Run `alembic upgrade head` to apply the migration
3. Verify all `module` and `resource_type` columns contain namespaced values
4. Verify no legacy flat values remain
5. Run `alembic downgrade -1` to rollback
6. Verify values are restored to their pre-migration state (where possible)

**Done when**:
- Migration runs to completion without errors on a database with existing legacy data
- Post-migration queries confirm all values transformed correctly
- Rollback restores database to pre-migration state

### 8.5 — End-to-end policy CRUD verification with namespaced types

**Procedure**:
1. Start the full stack with migrated database
2. Log in as system_admin
3. Create a new role with a policy statement using a namespaced resource type (e.g., `agent::management`)
4. Verify the policy statement appears in the role detail view with the namespaced type displayed
5. Edit the policy statement to change the resource type to a different namespaced value
6. Delete the policy statement
7. Verify the bootstrap `system_admin` role still has `*::*` wildcard policy granting full access

**Done when**:
- Full CRUD lifecycle works with namespaced types
- system_admin retains unrestricted access
- No errors or regressions in existing functionality

## Completion Checklist

- [x] All 17 namespaced RT_* constants defined in `resource_types.py`
- [x] ResourceTypeManifest restructured with 17 namespaced entries
- [x] PermissionEngine handles `::`-delimited modules and all wildcard levels
- [x] All 198+ `require_permission()` calls use namespaced constants
- [x] Bootstrap system_admin uses `*::*` wildcard
- [x] `/policy/resource-types` returns grouped namespaced manifest
- [x] Alembic migration transforms all legacy values → namespaced values
- [x] Frontend manifest mirrors backend with 17 namespaced entries
- [x] Policy editor dropdown shows grouped module options
- [x] Error display components render namespaced types legibly
- [x] All backend tests pass
- [x] All frontend tests pass
- [x] Migration verified on test database with rollback
- [x] End-to-end CRUD verified manually
- [x] Python syntax check passes across all modified backend files
- [x] TypeScript compilation passes across all modified frontend files
- [x] BatchPolicySaveRequest schema defined in `perm_roles.py`
- [x] `PUT /user-roles/{role_id}/policies/batch` endpoint implemented with atomic transaction
- [x] `batchSaveRolePolicies` API client function added in `permissionsApi.ts`
- [x] `BatchPolicySaveRequest` TypeScript type added in `permissions.ts`
- [x] RolePolicyDialog component created with Form/JSON toggle and bidirectional sync
- [x] JSON Source Code editor with Validate button and structured error display implemented
- [x] FreeSoloResourceTypeSelect and FreeSoloActionSelect components created supporting wildcards
- [x] Unsaved changes detection and confirmation guard hook implemented
- [x] RolePolicyDialog wired into RolesPage replacing inline expansion
- [x] Role policy count badges update after dialog save without page reload
