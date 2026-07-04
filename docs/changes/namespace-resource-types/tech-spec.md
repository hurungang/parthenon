# Technical Specification — Namespaced Resource Types

## 1. Technical Overview

The platform's resource type system is being upgraded from 15 flat string identifiers (e.g. `agent`, `role`, `conversation`) to 17 two-layer namespace identifiers (`agent::management`, `agent::roles`, `agent::trails`) using `::` as the delimiter. Three module groups (`agent`, `integration`, `system`) mirror the existing sidebar navigation structure.

The change is a **semantic evolution** of string columns — no new database tables or columns are added. The `policy_statements.module` and `policy_resources.resource_type` columns already accept 100-character strings and are size-compatible with the new format. Legacy values are transformed via a one-time Alembic data migration. The permission engine's module matching logic is extended to handle `::`-delimited identifiers and three levels of wildcards (`*::*`, `module::*`, exact match). All 198+ `require_permission()` call sites across 20 router files are updated to use the new namespaced constants.

The frontend resource type manifest is updated to mirror the backend structure, and the policy editor dropdown is reorganised to show grouped options under `Agents`, `Integrations`, and `System` headings.

## 2. Component Breakdown

### 2.1 Backend — Resource Type Manifest (`resource_types.py`)

**Responsibility**: Single source of truth for all valid resource type identifiers, their allowed actions, and module grouping. Exported constants (`RT_*`) are imported by all router files and the permission engine.

**Current state**: 15 flat `Final[str]` constants and a flat `ResourceTypeManifest` dict.

**Target state**: 17 namespaced `Final[str]` constants, a namespaced `ResourceTypeManifest` dict, a `MODULE_GROUPS` constant, and two helper functions (`get_module_from_resource_type`, `is_valid_wildcard`).

### 2.2 Backend — Permission Engine (`permission_engine.py`)

**Responsibility**: Evaluates whether a user may perform an action on a resource within a given module. Validates module and action against the manifest, collects effective role IDs, matches policy statements including wildcard policies.

**Current state**: Handles flat module strings and a single `*` wildcard.

**Target state**: Handles `::`-delimited module strings and three wildcard levels:
- `*::*` — matches every resource type in the manifest
- `module::*` — matches all submodules within a given module (e.g., `agent::*`)
- Exact match — matches a specific namespaced identifier (e.g., `agent::management`)

The legacy `*` wildcard is retained for backward compatibility during the transition, treated as equivalent to `*::*`.

### 2.3 Backend — Permission Dependency (`deps.py`)

**Responsibility**: FastAPI dependency factory (`require_permission()`) that calls the Permission Engine for each protected endpoint. No structural change needed — it passes the `module` string through to `PermissionEngine.authorize()`, which now handles the new format.

### 2.4 Backend — Routers (20 files in `api/v1/`)

**Responsibility**: Each router file protects its endpoints with `require_permission()` calls using constants from `resource_types.py`. The import statements and constant references are updated from flat to namespaced constants.

### 2.5 Backend — Bootstrap Service (`bootstrap_service.py`)

**Responsibility**: Seeds the `system_admin` role with a full-access wildcard policy on first startup. The wildcard value is changed from `"*"` to `"*::*"` to use the explicit two-layer namespace format.

### 2.6 Backend — Policy API Endpoint (`policy.py`)

**Responsibility**: The `GET /policy/resource-types` endpoint returns the complete manifest of valid resource types and their allowed actions. Updated to return namespaced identifiers with module grouping metadata.

### 2.7 Backend — Schemas (`perm_roles.py`)

**Responsibility**: Pydantic v2 schemas for the policy API, including `ResourceTypeRead` and `PolicyStatementCreate`. No structural changes needed — the `module` and `resource_type` fields already accept strings up to 100 characters, which is compatible with `module::submodule` format.

### 2.8 Backend — Database Models (no changes)

**Responsibility**: SQLAlchemy declarative models for `PolicyStatement`, `PolicyResource`, `PolicyAction`, `PolicyTagCondition`, `TagDefinition`, `Role`. No column type changes required — the `String(100)` columns for `module` and `resource_type` are size-compatible.

### 2.9 Backend — Alembic Migration (new)

**Responsibility**: One-time data migration that transforms all legacy flat values in `policy_statements.module` and `policy_resources.resource_type` to their namespaced equivalents. Includes an idempotent `upgrade()` and a reversible `downgrade()`.

### 2.10 Frontend — Resource Types Constants (`resourceTypes.ts`)

**Responsibility**: Mirrors the backend manifest for use in dropdowns, validation, and type definitions. Updated from flat constants to namespaced identifiers with module group definitions.

### 2.11 Frontend — Policy Editor Components

**Responsibility**: UI for creating, viewing, editing, and deleting policy statements within a role.

- **`PolicyEditor.tsx`** — Displays policy statement cards with module chip, action chips, resource definitions, and tag conditions. Uses `policy.module` for display (already string-based, no structural change).
- **`AddStatementDialog.tsx`** — Modal dialog for creating/editing policy statements. Contains the resource type dropdown that is reorganised to show grouped options by module.
- **`PermissionDeniedAlert.tsx`** — Displays structured 403 errors including the `required_permission.resource_type` field (now namespaced).
- **`PermissionErrorSnackbar.tsx`** — Global snackbar for 403 errors, interpolates `resource_type` via i18n.

### 2.12 Frontend — Hooks & API Client

**Responsibility**: Data fetching layer for permissions data.

- **`usePermissions.ts`** — React Query hooks for roles, policies, and resource types. The `useResourceTypes()` hook fetches from `/policy/resource-types` which now returns namespaced data.
- **`permissionsApi.ts`** — Typed API client functions. Type definitions in `types/permissions.ts` remain compatible (strings). No structural changes needed.

### 2.13 Frontend — Types (`permissions.ts`)

**Responsibility**: TypeScript type definitions for the permissions domain. `PolicyStatement.module` and `PolicyResource.resource_type` remain typed as `string` — no changes needed.

### 2.14 Frontend — RolePolicyDialog Component

**Responsibility**: Dialog wrapper component that replaces inline-expand policy editing on the Roles page. Displays all policies for a role in a single view and supports two editing modes: Form view and JSON Source Code view, toggled via a segmented control at the top of the dialog. All policy changes — additions, edits, and deletions — are submitted as a single batch save when the user clicks Save.

**Key features**:
- Loads all existing policies for the role on open and renders them in Form view by default
- Toggle between Form view (free-text autocomplete selectors) and JSON Source Code view (textarea with syntax highlighting)
- Bidirectional sync: changes made in either view are preserved when switching views
- Unsaved changes detection with confirmation dialog on Cancel, Escape key, or backdrop click
- Dialog error surface using `PermissionDeniedAlert` and `dialogError` state pattern
- Parent table refresh triggered after successful batch save

### 2.15 Frontend — JSON Source Code Editor

**Responsibility**: Embedded editing surface within the RolePolicyDialog's JSON view. Provides a Monaco-editor-style or syntax-highlighted textarea where administrators can directly author the full policy JSON for the role.

**Key features**:
- Displays current policies as formatted JSON (indented, readable) matching the batch save payload structure
- Validate button that performs client-side parse check and structure validation
- Parse errors displayed in-place with line number and character position references
- Structure validation verifies required `policies` array, non-empty `resource_type` and `actions` fields per policy, and `module::submodule` or wildcard format compliance
- Success indicator on valid JSON
- Validation failure blocks save operation and displays inline error messages

### 2.16 Frontend — FreeSolo Autocomplete Selectors

**Responsibility**: Enhanced resource type and action selector components using MUI `Autocomplete` with `freeSolo` mode. Replaces the current constrained dropdown-only selectors in `AddStatementDialog` and the new `RolePolicyDialog`.

**Key features**:
- Resource type selector: dropdown lists all 17 manifest entries grouped by module, plus accepts free-text input for wildcard patterns (`agent::*`, `agent::mana*`, `*::*`, `*`)
- Action selector: dropdown lists the 10 standard actions (`create`, `read`, `update`, `delete`, `execute`, `manage`, `approve`, `reject`, `view`, `respond`), plus accepts free-text input for `*` wildcard and custom action strings
- Free-text values are visually distinct from predefined dropdown values (chip colour or icon)
- Typing filters the dropdown list in real-time while also allowing arbitrary input
- No validation at the component level — validation occurs at save time via the batch API or JSON validation

### 2.17 Backend — Batch Policy Save Endpoint

**Responsibility**: New API endpoint that accepts an array of policy definitions and replaces all policies for a role atomically in a single transaction. Eliminates the need for multiple sequential create/update/delete calls in the dialog-based workflow.

**Key features**:
- `PUT /user-roles/{role_id}/policies/batch` — accepts JSON body with `policies` array
- Atomicity: all policies are replaced within a single database transaction; partial failures roll back entirely
- Idempotent: submitting the same batch payload twice produces the same result
- Validation: each policy in the array is validated against `ResourceTypeManifest`; wildcard values are accepted
- Empty `policies` array clears all policies for the role
- Returns the updated list of policies for the role as the response
- Permission-gated with `require_permission(RT_SYSTEM_PERMISSIONS, "manage")`

## 3. API Changes

### 3.1 Modified: `GET /policy/resource-types`

**Current response** (flat array):
```json
[
  { "resource_type": "agent", "actions": ["create", "read", "update", "delete", "execute"] },
  { "resource_type": "role", "actions": ["read", "manage"] }
]
```

**New response** (flat array with namespaced identifiers and module grouping metadata):
```json
[
  { "resource_type": "agent::management", "actions": ["create", "read", "update", "delete", "execute"], "module_group": "agent" },
  { "resource_type": "agent::roles", "actions": ["read", "manage"], "module_group": "agent" }
]
```

The response format remains a flat `ResourceTypeRead[]` array for backward compatibility. A new `module_group` field is added to `ResourceTypeRead` (derived via `get_module_from_resource_type()`). The frontend groups options client-side using `MODULE_GROUPS` from `resourceTypes.ts`; the `module_group` field is available for downstream consumers that need the module prefix.

**Permission guard**: Changes from `require_permission(RT_ROLE, "read")` to `require_permission(RT_SYSTEM_PERMISSIONS, "read")`.

### 3.2 Modified: `POST /user-roles/{role_id}/policies`

**Request body**: The `module` field in `PolicyStatementCreate` now accepts namespaced identifiers (`agent::management`) instead of flat strings (`agent`). The `resource_type` field in nested `PolicyResourceCreate` objects also accepts namespaced identifiers.

**Validation**: The API validates the `module` field against the updated `ResourceTypeManifest`. Legacy flat values are rejected with a validation error.

### 3.3 Modified: `PATCH /user-roles/{role_id}/policies/{policy_id}`

Same changes as the POST endpoint — the `module` field accepts namespaced identifiers.

### 3.4 Modified: `GET /user-roles/{role_id}/policies`

Response now returns `module` fields containing namespaced identifiers per the migrated database values.

### 3.5 New: `PUT /user-roles/{role_id}/policies/batch`

**Purpose**: Replaces all policy statements for a role atomically in a single request. The frontend `RolePolicyDialog` submits all policies (additions, edits, deletions) as a single batch payload.

**Request body**:
```json
{
  "policies": [
    {
      "module": "agent::roles",
      "actions": ["read", "manage"],
      "effect": "allow",
      "resources": [],
      "tag_conditions": []
    },
    {
      "module": "agent::skills",
      "actions": ["read", "execute"],
      "effect": "allow",
      "resources": [],
      "tag_conditions": []
    }
  ]
}
```

**Response**: Returns the updated list of policy statements for the role (same structure as `GET /user-roles/{role_id}/policies`).

**Validation**:
- Each `module` value is validated against `ResourceTypeManifest`; wildcard values (`agent::*`, `integration::*`, `system::*`, `*::*`, `*`) are also accepted
- Each `actions` array may contain standard actions and wildcards (`*`)
- The entire operation is wrapped in a database transaction for atomicity — any validation failure in any policy rolls back all changes

**Permission guard**: `require_permission(RT_SYSTEM_PERMISSIONS, "manage")`

### 3.6 Internal Endpoints (no changes)

The internal allow-list endpoints in `deps.py` (`_AR_ALLOWLIST`, `_CH_ALLOWLIST`) are not affected. The permission engine's internal calls from the Communication Hub and Agent Runtime use the `module` field which is passed through unchanged from the policy database.

## 4. State Management

### 4.1 React Query Hooks (`usePermissions.ts`)

The `useResourceTypes()` hook fetches the resource type manifest from `GET /policy/resource-types`. The response shape (`ResourceTypeDef[]`) remains a flat array of `{ resource_type: string, actions: string[] }` objects. The hook's return type is unchanged.

**Client-side grouping**: The `MODULE_GROUPS` constant in `resourceTypes.ts` is used by `AddStatementDialog` to render grouped dropdown options. This is a presentation concern — no state management changes are needed.

### 4.2 Policy Form State (`AddStatementDialog.tsx`)

Local component state (`form.resourceType`) holds the selected namespaced identifier. The form state shape is unchanged — `resourceType` remains a string. The only change is that the string values are now `module::submodule` instead of flat identifiers.

### 4.3 Error State

`PermissionDeniedAlert` and `PermissionErrorSnackbar` both read `required_permission.resource_type` from structured 403 error responses. This field will now contain namespaced values (e.g. `agent::management`). The components render these as strings — no structural changes needed.

### 4.4 RolePolicyDialog State

Local component state manages the full policy editing session:

- **`policies: EditingPolicy[]`** — Array of policy objects being edited in the dialog, initialized from the API on open. Tracks per-policy changes (add, edit, delete) via a `_state` flag (`"unchanged" | "modified" | "added" | "deleted"`). Deleted policies remain in the array with `_state: "deleted"` and are visually struck through until save.
- **`viewMode: "form" | "json"`** — Toggles between Form view and JSON Source Code view. Changing the view serializes/deserializes the current `policies` state bidirectionally.
- **`jsonText: string`** — Raw text content of the JSON editor in JSON view. Synchronized from `policies` on view toggle (Form→JSON) and parsed back on toggle (JSON→Form) or on save.
- **`jsonValidation: { valid: boolean; errors: ValidationError[] } | null`** — Validation state from the Validate button. `null` when not yet validated; populated on each Validate click.
- **`dialogError: unknown`** — Error state following the dialog error handling standard. Set on batch save API failure; displayed via `PermissionDeniedAlert`.
- **`isSaving: boolean`** — Loading state during batch save operation; disables Save button and shows spinner.
- **`hasUnsavedChanges: boolean`** — Derived state: true when any policy has been added, modified, or deleted compared to the initial loaded state. Controls unsaved-changes confirmation dialog.
- **`isDirty: boolean`** — Tracks whether any changes exist, used by the unsaved-changes guard on Cancel, Escape, and backdrop click.

### 4.5 JSON Editor Validation State

The JSON Source Code view manages its own validation state independent of the dialog's save flow:

- **`jsonText: string`** — Controlled textarea value, updated on keystroke
- **`validationResult: { type: "success" } | { type: "parse_error"; message: string; line?: number; column?: number } | { type: "structure_error"; errors: string[] } | null`** — Result of the most recent Validate click; `null` before first validation
- **`isValidating: boolean`** — True during client-side validation (synchronous, typically instantaneous)

### 4.6 FreeSolo Autocomplete State

The enhanced `Autocomplete` components for resource type and action selection use MUI's built-in `freeSolo` state:

- **`inputValue: string`** — Raw keystroke value in the text field, used for filtering dropdown options and capturing free-text input
- **`value: string`** — Selected or typed value; may be a manifest entry or a free-text wildcard
- No additional state management needed — `freeSolo` mode handles the dual dropdown/free-text behaviour natively

## 5. Data Access Patterns

### 5.1 Policy Statement Lookups (Permission Engine)

The Permission Engine queries `policy_statements` with a WHERE clause that filters by `module`. After migration, the query must match namespaced identifiers:

- **Exact match**: `WHERE module = 'agent::management'` — finds policies scoped to the exact submodule
- **Global wildcards**: `WHERE module = '*::*' OR module = '*'` — finds system_admin-style policies
- **Module-level wildcards**: `WHERE module = 'agent::*'` — finds policies scoped to an entire module

The engine uses SQLAlchemy `or_()` to combine these conditions. Module-level wildcards require a LIKE or prefix-matching clause: `WHERE module LIKE 'agent::%' AND module LIKE '%::*'` or an explicit `module = 'agent::*'` check.

### 5.2 Policy CRUD (Routers)

Policy creation and update do not perform deep validation of the `module` field at the database level — validation is enforced at the application layer by checking against `ResourceTypeManifest`. The router calls `PolicyStatement(module=body.module)` directly, and the Pydantic `StringConstraints(max_length=100)` schema validation ensures the value fits the column.

### 5.3 Migration Data Access (Alembic)

The migration uses raw SQL `UPDATE` statements with explicit value mappings. It reads from and writes to `policy_statements.module` and `policy_resources.resource_type`. The migration is idempotent by only updating rows where the current value does not already contain `::`.

### 5.4 Frontend Data Access

The frontend accesses resource type data through:
- `GET /policy/resource-types` — for the manifest (dropdown options, action lists)
- `GET /user-roles/{role_id}/policies` — for existing policy statements (display in PolicyEditor, initialization of RolePolicyDialog)
- `PUT /user-roles/{role_id}/policies/batch` — for atomic batch save of all role policies from RolePolicyDialog

All access is through the typed API client (`permissionsApi.ts`) which uses Axios with the centralized `apiClient` base URL. No direct database access — all data goes through REST API endpoints.

### 5.5 Batch Save Transaction (Permission Engine + Database)

The `PUT /user-roles/{role_id}/policies/batch` endpoint performs its work within a single database transaction:
1. Begin transaction
2. Delete all existing policy statements, resources, actions, and tag conditions for the role
3. Insert all policies from the request body with their nested resources, actions, and tag conditions
4. Commit transaction (or rollback on any validation/insertion failure)

This ensures atomicity: the role never exists in an intermediate state with partial policies.

## 6. Code Reference Map

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
| `RT_SYSTEM_OBSERVABILITY` | constant | Namespaced resource type `"system::observability"` | `backend/app/core/resource_types.py` |
| `RT_SYSTEM_PERMISSIONS` | constant | Namespaced resource type `"system::permissions"` | `backend/app/core/resource_types.py` |
| `RT_SYSTEM_CONFIG` | constant | Namespaced resource type `"system::system_config"` | `backend/app/core/resource_types.py` |
| `ResourceTypeManifest` | dict | Maps 17 namespaced identifiers to allowed actions | `backend/app/core/resource_types.py` |
| `MODULE_GROUPS` | dict | Maps module names to their submodule lists | `backend/app/core/resource_types.py` |
| `get_module_from_resource_type` | function | Extracts module prefix from a namespaced identifier | `backend/app/core/resource_types.py` |
| `is_valid_wildcard` | function | Validates wildcard patterns (`*::*`, `module::*`) | `backend/app/core/resource_types.py` |
| `PermissionEngine` | class | Evaluates policy-based authorization requests | `backend/app/services/permissions/permission_engine.py` |
| `PermissionEngine.authorize` | method | Checks if user may perform action on a resource within a module | `backend/app/services/permissions/permission_engine.py` |
| `AuthorizationResult` | dataclass | Result of a permission engine check (allowed/reason) | `backend/app/services/permissions/permission_engine.py` |
| `require_permission` | function | FastAPI dependency factory for permission-gated endpoints | `backend/app/api/deps.py` |
| `BootstrapService` | class | Seeds system_admin role and wildcard policy on startup | `backend/app/services/permissions/bootstrap_service.py` |
| `BootstrapService._ensure_full_access_policy` | method | Creates `*::*` wildcard policy for system_admin | `backend/app/services/permissions/bootstrap_service.py` |
| `list_resource_types` | function | `GET /policy/resource-types` endpoint handler | `backend/app/api/v1/policy.py` |
| `RolesRouter` | router | `APIRouter` for `POST/GET /user-roles` and nested policies | `backend/app/api/v1/user_roles.py` |
| `create_policy_statement` | function | `POST /user-roles/{id}/policies` endpoint handler | `backend/app/api/v1/user_roles.py` |
| `list_role_policies` | function | `GET /user-roles/{id}/policies` endpoint handler | `backend/app/api/v1/user_roles.py` |
| `update_policy_statement` | function | `PATCH /user-roles/{id}/policies/{pid}` endpoint handler | `backend/app/api/v1/user_roles.py` |
| `ResourceTypeRead` | schema | Pydantic model for `/policy/resource-types` response | `backend/app/schemas/perm_roles.py` |
| `PolicyStatementCreate` | schema | Pydantic model for policy creation request body | `backend/app/schemas/perm_roles.py` |
| `PolicyStatement` | model | SQLAlchemy ORM model for `policy_statements` table | `backend/app/db/models/policy_statement.py` |
| `PolicyResource` | model | SQLAlchemy ORM model for `policy_resources` table | `backend/app/db/models/policy_resource.py` |
| `PolicyAction` | model | SQLAlchemy ORM model for `policy_actions` table | `backend/app/db/models/policy_action.py` |
| `PolicyTagCondition` | model | SQLAlchemy ORM model for `policy_tag_conditions` table | `backend/app/db/models/policy_tag_condition.py` |
| `namespace_resource_types` | migration | Alembic data migration: transforms 15 legacy flat values → 17 namespaced values; idempotent; reversible | `backend/alembic/versions/868d278f04db_namespace_resource_types.py` |
| `RESOURCE_TYPE_MANIFEST` | constant | Frontend mirror of backend manifest (17 namespaced entries) | `frontend/src/constants/resourceTypes.ts` |
| `MODULE_GROUPS` | constant | Module-to-submodule grouping for dropdowns | `frontend/src/constants/resourceTypes.ts` |
| `getActionsForResourceType` | function | Returns allowed actions for a resource type | `frontend/src/constants/resourceTypes.ts` |
| `getModuleForResourceType` | function | Extracts module prefix from a namespaced identifier | `frontend/src/constants/resourceTypes.ts` |
| `AddStatementDialog` | component | Modal dialog for creating/editing policy statements with grouped dropdown | `frontend/src/components/permissions/AddStatementDialog.tsx` |
| `PolicyEditor` | component | Displays role policy statements with module/action chips | `frontend/src/components/permissions/PolicyEditor.tsx` |
| `PermissionDeniedAlert` | component | Displays structured 403 error with resource type and action | `frontend/src/components/permissions/PermissionDeniedAlert.tsx` |
| `PermissionErrorSnackbar` | component | Global snackbar for 403 permission denied events | `frontend/src/components/permissions/PermissionErrorSnackbar.tsx` |
| `useResourceTypes` | hook | React Query hook fetching resource type manifest | `frontend/src/hooks/usePermissions.ts` |
| `listResourceTypes` | function | API client for `GET /policy/resource-types` | `frontend/src/api/permissionsApi.ts` |
| `PolicyStatement` | type | TypeScript interface for policy statement data | `frontend/src/types/permissions.ts` |
| `ResourceTypeDef` | type | TypeScript interface for resource type manifest entry | `frontend/src/types/permissions.ts` |
| `PolicyStatementCreate` | type | TypeScript interface for policy creation payload | `frontend/src/types/permissions.ts` |
| `extractPermissionError` | function | Parses structured 403 error body | `frontend/src/utils/errorUtils.ts` |
| `parsePermissionError` | function | Extracts PermissionDeniedDetail from Axios error | `frontend/src/utils/permissionError.ts` |
| `RolePolicyDialog` | component | Dialog wrapper for role policy editing with Form/JSON toggle, batch save, unsaved changes guard | `frontend/src/components/permissions/RolePolicyDialog.tsx` |
| `FreeSoloResourceTypeSelect` | component | MUI Autocomplete with freeSolo for resource type selection; supports dropdown selection and free-text wildcard input | `frontend/src/components/permissions/FreeSoloResourceTypeSelect.tsx` |
| `FreeSoloActionSelect` | component | MUI Autocomplete with freeSolo for action selection; supports predefined actions, `*` wildcard, and custom free-text input | `frontend/src/components/permissions/FreeSoloActionSelect.tsx` |
| `EditingPolicy` | type | Local state type for policies being edited in RolePolicyDialog; includes `_state` flag for add/modify/delete tracking | `frontend/src/components/permissions/RolePolicyDialog.tsx` |
| `JsonValidationResult` | type | Union type for JSON validation outcomes: success, parse_error (with line/col), or structure_error (with messages) | `frontend/src/components/permissions/RolePolicyDialog.tsx` |
| `batchSaveRolePolicies` | function | API client for `PUT /user-roles/{role_id}/policies/batch` | `frontend/src/api/permissionsApi.ts` |
| `useBatchSaveRolePolicies` | hook | React Query mutation hook for batch save; invalidates role and roles queries on success | `frontend/src/hooks/usePermissions.ts` |
| `BatchPolicySaveRequest` | type | TypeScript interface for batch save request body (`{ policies: PolicyStatementCreate[] }`) | `frontend/src/types/permissions.ts` |
| `batch_replace_policies` | function | `PUT /user-roles/{role_id}/policies/batch` endpoint handler; atomic transaction, validates all policies against manifest | `backend/app/api/v1/user_roles.py` |
| `BatchPolicySaveRequest` | schema | Pydantic model for batch save request body with `policies` array validation | `backend/app/schemas/perm_roles.py` |
| `useUnsavedChangesDialog` | hook | Composable hook for unsaved-changes detection: tracks dirty state, shows confirmation dialog on Cancel/Escape/backdrop | `frontend/src/hooks/useUnsavedChangesDialog.tsx` |
