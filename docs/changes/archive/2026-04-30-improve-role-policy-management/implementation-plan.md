# Improve Role & Policy Management — Implementation Plan

## Overview
This change improves the role policy management UI by replacing the current free-text module field with structured dropdowns for resource type, effect, and actions, adds auto-populated tag value selectors, and introduces JSON view and role clone features. The work is purely frontend-driven: two new backend endpoints expose the resource type/actions manifest and role-clone operation; all other changes are in React components.

## Task Checklist

### Phase 1 — Backend API
- [x] 1.1 — Add GET /api/v1/policy/resource-types endpoint
- [x] 1.2 — Add POST /api/v1/user-roles/{role_id}/clone endpoint

### Phase 2 — Frontend API & Hooks
- [x] 2.1 — Add API functions for new endpoints in permissionsApi.ts
- [x] 2.2 — Add React Query hooks for resource types and clone role

### Phase 3 — Frontend Components
- [x] 3.1 — Build PolicyEditor component (consolidated statement list with remove)
- [x] 3.2 — Build AddStatementDialog with dropdown resource type, effect, and actions
- [x] 3.3 — Build JSONViewModal for role policy JSON view
- [x] 3.4 — Build CloneRoleDialog
- [x] 3.5 — Integrate new components into RolesPage

### Phase 4 — Bug Fix
- [x] 4.1 — Fix tag value dropdown not populating in statement form

### Phase 5 — Testing
- [x] 5.1 — Unit tests for PolicyEditor component
- [x] 5.2 — Unit tests for AddStatementDialog
- [x] 5.3 — Unit tests for CloneRoleDialog and JSONViewModal
- [x] 5.4 — Backend tests for new endpoints

## Phase 1 — Backend API

### Task 1.1 — Add GET /api/v1/policy/resource-types endpoint
Create a new router file `backend/app/api/v1/policy.py` with a single endpoint that returns all resource types and their allowed action lists from the existing `ResourceTypeManifest` in `backend/app/core/resource_types.py`. This avoids duplicating the manifest in the frontend and keeps the resource type/action catalogue as a single source of truth. The endpoint requires JWT authentication with `role:read` permission, consistent with all other read endpoints. Register the new router in `backend/app/api/v1/__init__.py` (or `backend/app/main.py` wherever other routers are mounted).

**Done when**: `GET /api/v1/policy/resource-types` returns a JSON array of `{ resource_type: string, actions: string[] }` objects covering all entries in `ResourceTypeManifest`, and the endpoint returns 401 for unauthenticated callers.

### Task 1.2 — Add POST /api/v1/user-roles/{role_id}/clone endpoint
Add a `clone` sub-route to the existing `RolesRouter` in `backend/app/api/v1/user_roles.py`. The endpoint accepts a body with `name` (required) and `description` (optional). It reads the source role and all its `PolicyStatement` rows (with related `PolicyAction`, `PolicyResource`, `PolicyTagCondition` rows), creates a new `Role` with the given name/description, then deep-copies every policy statement and its nested rows to the new role. Returns the new `PermRoleRead` with a 201 status. Requires `role:manage` permission. Return 409 if the new role name already exists.

**Done when**: `POST /api/v1/user-roles/{id}/clone` with `{ "name": "Copy of X" }` creates a new role with identical policy statements; the source role is unchanged; 409 is returned for a duplicate name; 403 for callers without `role:manage`.

## Phase 2 — Frontend API & Hooks

### Task 2.1 — Add API functions for new endpoints in permissionsApi.ts
Add two typed functions to `frontend/src/api/permissionsApi.ts`:
- `listResourceTypes()` — calls `GET /api/v1/policy/resource-types`, returns `ResourceTypeDef[]`
- `cloneRole(sourceId, data)` — calls `POST /api/v1/user-roles/{id}/clone`, returns `Role`

Add the corresponding TypeScript interfaces to `frontend/src/types/permissions.ts`:
- `ResourceTypeDef { resource_type: string; actions: string[] }`
- `RoleCloneCreate { name: string; description?: string }`

**Done when**: Both functions compile without errors, are correctly typed, and their return types match the backend response shapes.

### Task 2.2 — Add React Query hooks for resource types and clone role
Add to `frontend/src/hooks/usePermissions.ts`:
- `useResourceTypes()` — `useQuery` wrapping `listResourceTypes()`; cached under a new `permissionKeys.resourceTypes` key
- `useCloneRole()` — `useMutation` wrapping `cloneRole()`; on success invalidates `permissionKeys.roles`

**Done when**: Both hooks are exported from `usePermissions.ts`; `useResourceTypes()` returns data without errors when the backend is running; `useCloneRole()` triggers a roles list refresh on success.

## Phase 3 — Frontend Components

### Task 3.1 — Build PolicyEditor component
Create `frontend/src/components/permissions/PolicyEditor.tsx`. This component receives a `roleId: string` prop, fetches the role's policy statements via the existing `useRole(roleId)` hook, and renders them as MUI `Card` components (matching the prototype layout). Each card shows:
- Resource type as a monospace badge
- Effect as a colour-coded `Chip` (green for Allow, red for Deny)
- Actions as a row of grey `Chip` elements
- Tag conditions as a `Box` with key/value pairs
- A "Remove" ghost-danger `Button` that calls `useDeletePolicyStatement`

The component also renders an "Add Statement" `Button` that opens the `AddStatementDialog`. All text goes through `t()`. Error handling follows the Dialog Error Handling Standard: `deletePolicyStatement` errors are caught and shown via `PermissionDeniedAlert`.

**Done when**: `PolicyEditor` renders existing policy statements for a role, Remove correctly deletes a statement and the list refreshes, and the Add Statement button opens `AddStatementDialog`.

### Task 3.2 — Build AddStatementDialog with dropdowns
Create `frontend/src/components/permissions/AddStatementDialog.tsx`. Props: `open: boolean`, `roleId: string`, `onClose: () => void`. 

Form fields:
- **Resource Type**: MUI `Select` populated from `useResourceTypes()` — replaces the current free-text `module` field
- **Effect**: MUI `Select` with Allow/Deny options (uses `PolicyEffect` enum)
- **Actions**: MUI `Autocomplete` (multiple, freeSolo=false) populated with the actions list for the selected resource type from `useResourceTypes()` data; selecting a resource type resets the actions selection
- **Tag Conditions**: dynamic list of rows (tag key dropdown from `useTagDefinitions()`, tag value dropdown/text from `useTagValueOptions()`); rows can be added and removed

On save, calls `useCreatePolicyStatement` with `module` set to the selected `resource_type`. Error handling follows the Dialog Error Handling Standard. All labels go through `t()`.

**Done when**: The dialog opens with dropdowns populated, resource type selection updates the available actions, tag value dropdown shows allowed values when a tag key is selected, saving creates the statement and closes the dialog, errors are displayed inline.

### Task 3.3 — Build JSONViewModal
Create `frontend/src/components/permissions/JSONViewModal.tsx`. Props: `open: boolean`, `roleId: string`, `roleName: string`, `onClose: () => void`.

Fetches policy statements via `useRole(roleId)` and formats them into a JSON structure matching the prototype: `{ role_id, name, statements: [ { effect, resource_type, actions: string[], conditions: { tags: { key: value } } } ] }`. Renders in a dark monospace `Box` (MUI `Paper` with `sx` styling). Includes a "Copy JSON" `IconButton` that writes to the clipboard. Close button in `DialogActions`. All labels through `t()`.

**Done when**: Modal opens with correctly formatted JSON, Copy JSON copies the text to clipboard, the JSON updates if statements change while the modal is open.

### Task 3.4 — Build CloneRoleDialog
Create `frontend/src/components/permissions/CloneRoleDialog.tsx`. Props: `open: boolean`, `sourceRole: Role | null`, `onClose: () => void`.

Form fields: new role `name` (pre-filled with "Copy of {source name}"), optional `description` (pre-filled from source). On submit, calls `useCloneRole()`. On success, calls `onClose()` and shows a success `Snackbar` (or uses the parent's existing notification pattern). Error handling follows the Dialog Error Handling Standard. All labels through `t()`.

**Done when**: Dialog opens with pre-filled fields, submitting creates the cloned role, the roles list refreshes, errors are shown inline.

### Task 3.5 — Integrate new components into RolesPage
Update `frontend/src/pages/permissions/RolesPage.tsx`:
- Replace the inline expanded `RolePoliciesDetail` with `<PolicyEditor roleId={role.id} />` in the `Collapse` row
- Remove the inline Add Policy Statement dialog (replaced by the dialog inside `PolicyEditor`/`AddStatementDialog`)
- Add a "View JSON" `IconButton` per role row that opens `JSONViewModal` for that role
- Add a "Clone" `IconButton` per role row that opens `CloneRoleDialog` with that role
- Wire up state: `jsonViewRole: Role | null`, `cloneRole: Role | null`
- Remove now-unused inline `policyForm` state and `handleAddPolicy` handler

**Done when**: The Roles page renders all roles; each row has View JSON and Clone icon buttons; expanding a row shows `PolicyEditor`; no inline policy dialog remains; all dialogs open/close correctly.

## Phase 4 — Bug Fix

### Task 4.1 — Fix tag value dropdown not populating in statement form
**Root cause**: In `RolesPage.tsx` the `tagKey` field in `policyForm` state is only tracked as a string but the `Select` rendering for tag key selection is missing an `onChange` that sets `policyForm.tagKey`, so `useTagValueOptions(policyForm.tagKey)` always receives a stale or empty value.

After the component refactor (Task 3.2), verify that `AddStatementDialog` correctly passes the selected tag key from each condition row's tag key `Select` into `useTagValueOptions()` for the corresponding row's value field. Because condition rows are dynamic, each row needs its own tag key tracked in the conditions array state so `useTagValueOptions` receives the correct value per row.

**Done when**: Selecting a tag key in a condition row immediately populates the tag value dropdown/autocomplete with the allowed values from the tag definition; changing the tag key updates the values; rows with no tag key show no value options.

## Phase 5 — Testing

### Task 5.1 — Unit tests for PolicyEditor component
Add `frontend/src/__tests__/PolicyEditor.test.tsx`. Tests:
- Renders statement cards with correct resource type, effect, and actions
- Remove button calls delete mutation and list refreshes
- Empty state renders correctly when no statements exist

**Done when**: All tests pass with `vitest`.

### Task 5.2 — Unit tests for AddStatementDialog
Add `frontend/src/__tests__/AddStatementDialog.test.tsx`. Tests:
- Resource type dropdown is populated from mock `useResourceTypes` data
- Selecting a resource type populates the actions dropdown
- Tag key selection populates tag value options
- Submitting with valid data calls `createPolicyStatement`
- API error is shown inline (Dialog Error Handling Standard)

**Done when**: All tests pass with `vitest`.

### Task 5.3 — Unit tests for CloneRoleDialog and JSONViewModal
Add `frontend/src/__tests__/CloneRoleDialog.test.tsx` and `frontend/src/__tests__/JSONViewModal.test.tsx`. Tests:
- CloneRoleDialog: pre-fills name/description from source role; submit calls `cloneRole`; error shown inline
- JSONViewModal: renders JSON with correct structure; Copy JSON button copies to clipboard

**Done when**: All tests pass with `vitest`.

### Task 5.4 — Backend tests for new endpoints
Add tests in `backend/tests/api/test_policy_endpoints.py`:
- `GET /api/v1/policy/resource-types` returns the expected resource types and their actions
- `POST /api/v1/user-roles/{id}/clone` creates a new role with copied policy statements
- Clone returns 409 when the target name already exists
- Clone returns 404 when the source role does not exist

**Done when**: All tests pass with `pytest`.

## Completion Checklist
- [ ] `GET /api/v1/policy/resource-types` returns all resource types and actions; requires auth
- [ ] `POST /api/v1/user-roles/{id}/clone` deep-copies role and all statements; requires role:manage
- [ ] `AddStatementDialog` resource type field is a dropdown (no free-text module entry)
- [ ] Actions dropdown is scoped to the selected resource type
- [ ] Tag value dropdown populates when a tag key is selected in any condition row
- [ ] `PolicyEditor` renders all statements for a role with Remove buttons
- [ ] Add Statement from `PolicyEditor` opens `AddStatementDialog` and refreshes on save
- [ ] View JSON button on role row shows correct JSON modal with Copy button
- [ ] Clone Role button pre-fills name/description and creates a cloned role on submit
- [ ] All new dialogs handle API errors inline per Dialog Error Handling Standard
- [ ] All UI text goes through `t()` — no hardcoded strings
- [ ] All new frontend tests pass (`vitest`)
- [ ] All new backend tests pass (`pytest`)
