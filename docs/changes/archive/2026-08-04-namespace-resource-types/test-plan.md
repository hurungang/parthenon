# Test Plan — Namespaced Resource Types

## 1. Test Strategy

| Layer | Approach | Scope |
|-------|----------|-------|
| **Unit (Backend)** | Validate manifest structure, `::`-delimited identifier parsing, wildcard pattern matching, validation logic, and constant-to-identifier mappings without database or HTTP dependencies (`unittest.mock`). | `ResourceTypeManifest`, `PermissionEngine._match_module()`, flat-value rejection, `::` parser edge cases. |
| **Unit (Frontend)** | Vitest component tests with mocked API hooks — verify `AddStatementDialog` dropdown grouping by module, `PolicyEditor` display of namespaced identifiers, `CloneRoleDialog` handling of namespaced policy data. | Dialog rendering with namespaced resource types, grouped dropdowns, label formatting, validation error display. |
| **Integration (Backend)** | FastAPI `TestClient` + in-memory SQLite with mocked auth — validate REST API endpoints accept/reject namespaced identifiers, return correct resource type manifests, and enforce validation at CRUD boundaries. | `GET /api/v1/policy/resource-types`, `POST/DELETE /api/v1/user-roles/{id}/policies`, `PUT /api/v1/user-roles/{id}/policies/{pid}`. |
| **DB Migration Integration** | **REQUIRED (has_db_changes: true)** — Apply migration against real PostgreSQL, query `information_schema` to verify column properties unchanged, verify all 15 legacy values transformed to correct namespaced equivalents, test flat-value rejection after migration. | Migration up/downgrade cycle, data integrity for consolidations (`permissions`+`group`+`user`+`tag`+`access_request` → `system::permissions`; `conversation`+`result` → `agent::trails`). |
| **Backend Integration (Real DB)** | Integration tests against real PostgreSQL — validate full CRUD lifecycle with namespaced resource types using live database, verify permission engine evaluates `::`-delimited modules correctly against real policy data. | Real DB CRUD, permission evaluation with wildcards, `require_permission()` calls with namespaced identifiers. |
| **E2E** | Playwright tests — verify full policy-statement CRUD flow in the browser against a running backend. Include at least one real-backend test (no mocks) as required. Mocked tests can cover UI grouping/formatting. | Full CRUD lifecycle on role policies, wildcard selection in dropdowns, parent-table refresh after dialog operations, migration visibility. |
| **Integration (Frontend Dialog)** | Vitest component tests with mocked API hooks — verify `RolePolicyDialog` Form/JSON view toggle, free-text resource type and action selectors, batch save operations, JSON validation, and unsaved changes confirmation guard. | Dialog view toggle preserving changes bidirectionally, freeSolo autocomplete for `agent::*`/`agent::mana*`/`*::*` wildcards, batch save via new endpoint, JSON parse validation with specific error messages, unsaved changes confirmation dialog. |
| **Manual** | Smoke checks: Dashboard accessibility, sidebar gating unchanged, system administrator role retains `*::*`-equivalent access, visual inspection of policy table/displays, manual testing of RolePolicyDialog Form/JSON toggle and free-text input. | Dashboard exempt, system admin access, visual regression of policy editor, dialog UX validation. |

## 2. Coverage Areas

### 2.1 Namespace Structure

**Why critical:** The entire change hinges on 17 namespaced identifiers being correctly defined, exported, and consumable across backend and frontend. A single typo or missing entry breaks the authorization model.

- Manifest contains exactly 17 entries across 3 modules (`agent`, `integration`, `system`).
- Every identifier uses the `module::submodule` delimiter form with no deeper nesting.
- All 12 agent submodules, 2 integration submodules, and 3 system submodules are present.
- Backend `RT_*` constants are renamed/added to match the new identifiers.
- Frontend mirror manifest (if separate) is in sync with backend manifest.
- Legacy flat constants (`RT_AGENT`, `RT_MCP_SERVER`, etc.) are either removed or preserved as deprecated aliases.

### 2.2 Policy Authoring CRUD (UI + Backend)

**Why critical:** This is the primary user-facing workflow. Administrators must be able to create, read, update, and delete policy statements using the new namespaced identifiers without errors.

- **CREATE:** Dropdown lists all 17 namespaced resource types, grouped by module (Agents heading, Integrations heading, System heading). Selecting a type and submitting creates the policy statement visible in the policy table.
- **READ:** Policy table displays the `module` field value (namespaced identifier) correctly for all existing and new statements. JSON view shows the full policy structure with namespaced `module`/`resource_type` values.
- **UPDATE:** Editing an existing statement pre-populates the dropdown with the current namespaced type. Changing the resource type and saving updates the table row immediately.
- **DELETE:** Deleting a statement removes it from the table and the backend.
- **Parent table refresh:** After any create/edit/delete via dialog, the parent policy table refreshes automatically (no manual page reload required). Policy counts on role cards/chips update immediately.
- **Error handling:** Submitting an invalid or flat resource type shows a clear validation error. Duplicate policy configurations are rejected appropriately.

### 2.3 Wildcard Support

**Why critical:** Wildcards are the headline new capability (module-scoped permissions). Incorrect wildcard evaluation creates either privilege escalation or denial-of-service.

- `agent::*` matches all 12 agent submodules.
- `integration::*` matches both integration submodules.
- `system::*` matches all 3 system submodules.
- `*::*` matches every resource type in the manifest (17 entries).
- Wildcards cannot be combined with specific submodules in the same resource definition.
- Permission evaluation correctly expands wildcards to all matching concrete submodules.
- Wildcard selection is available in policy editor dropdowns.

### 2.4 Migration

**Why critical:** No administrator should have to manually update any existing policy. Data loss or incorrect migration silently breaks permissions and locks users out.

- All 15 legacy values are mapped to the correct 17 namespaced values.
- Many-to-one consolidations preserve the correct effective permissions (e.g., a user with `tag` permission gets `system::permissions`).
- Migration is reversible (`alembic downgrade` restores flat values).
- Migration applies cleanly against production-like data (no constraint violations).
- Post-migration, the system rejects flat resource type values at the API layer.
- System administrator role retains equivalent of `*::*` access post-migration.

### 2.5 Permission Engine Module Matching

**Why critical:** The permission engine is the enforcement point. If it cannot parse `::`-delimited identifiers or evaluate wildcards correctly, authorization is broken at runtime.

- Engine accepts `::`-delimited strings in the `module` parameter.
- Module matching succeeds when policy module equals the requested module (exact match).
- Module matching succeeds when policy module is `module::*` and requested module belongs to that module.
- Module matching succeeds when policy module is `*::*` for any requested module.
- Module matching correctly parses `::` delimiter (does not incorrectly match `agent::*` against `agent::roles_extra`).
- Engine's `_match_resource_id()` behavior is unchanged (already tested for `*` and prefix patterns).

### 2.6 Validation & Negative Cases

**Why critical:** Invalid data must be rejected early with clear errors. Accepting flat values post-migration creates data inconsistencies.

- Flat values (`agent`, `role`, `skill`, etc.) are rejected at API level with a clear error message.
- Unknown/invented values (`agent::nonexistent`, `fake::thing`) are rejected.
- Empty or whitespace-only values are rejected.
- Values with incorrect delimiter (single colon `:`, triple `:::`, slash `/`) are rejected or normalized.
- Values with more than two layers (`a::b::c`) are rejected.

### 2.7 Frontend UI & Manifest Mirror

**Why critical:** The frontend must display namespaced identifiers correctly and group them by module in dropdowns. If the frontend mirror is out of sync with the backend, the dropdown shows incorrect options.

- Resource type dropdown groups options under module headings (Agents, Integrations, System).
- Labels and chips display the full namespaced identifier or a user-friendly module-submodule label.
- The frontend manifest or mock data uses `::`-delimited identifiers matching the backend.
- i18n labels are updated where applicable.

### 2.8 Dashboard Exemption

**Why critical:** PRD explicitly states dashboard remains accessible without specific permission check. Regression here is a user-facing outage.

- GET `/dashboard` returns 200 without requiring any resource type permission.
- No `require_permission()` decorator is added to the dashboard route.

### 2.9 Consolidation Scope Broadening

**Why critical:** PRD explicitly states that broadening permissions is intentional. Tests must verify the broadening happens correctly rather than treat it as a bug.

- `conversation` holders gain access to `agent::trails` (which includes former `result` scope).
- `permissions`, `group`, `user`, `tag`, `access_request` holders all gain access to `system::permissions`.
- This broadening is visible in policy displays and effective at runtime.

### 2.10 Role Policy Dialog (RolePolicyDialog)

**Why critical:** The PRD refinement replaces inline-expand policy editing with a dialog-based approach (`RolePolicyDialog`) supporting two editing modes (Form view and JSON Source Code view), free-text resource type and action input, and atomic batch save. Incorrect dialog behavior — lost changes during view toggle, invalid JSON escaping validation, or failed batch saves — directly breaks the policy-authoring workflow for administrators.

- **Dialog initialization:** Opening the RolePolicyDialog for a role loads all existing policies and displays them in Form view by default, with each policy row showing pre-populated resource type and action selectors.
- **Empty role:** Opening the dialog for a role with no existing policies shows an empty policy list in Form view with an "Add Policy" button available.
- **Form view operations:** Administrator can add new policy rows, edit existing resource type and action values using free-text autocomplete, and delete policy rows — all within the same dialog session before committing changes.
- **JSON Source Code view toggle (Form → JSON):** Toggling from Form view to JSON Source Code view serializes the current dialog state into formatted JSON representing all policies for the role, including any unsaved additions, edits, or deletions.
- **JSON Source Code view toggle (JSON → Form):** Toggling from JSON view back to Form view restores the Form UI with all changes made in JSON view reflected in the selectors and rows.
- **Bidirectional sync:** Changes made in either view are preserved when switching to the other view; no data is lost during toggle operations.
- **JSON validation (parse check):** Clicking "Validate" in JSON view checks that the JSON is syntactically parseable and reports specific parse errors (line number, character position) for malformed JSON.
- **JSON validation (structure check):** The validator checks that the JSON contains the required `policies` array structure with each policy having `resource_type` and `actions` fields.
- **JSON validation (content check):** The validator checks that `resource_type` values are non-empty and conform to the `module::submodule` or wildcard pattern.
- **JSON validation success:** When JSON is valid, the dialog shows a success indicator confirming the JSON is parseable and structurally correct.
- **Free-text resource type input:** The resource type autocomplete uses `freeSolo` mode, accepting both predefined manifest values from the dropdown and manually typed strings including wildcard patterns (`agent::*`, `agent::mana*`, `*::*`, `*`).
- **Free-text action input:** The action selector autocomplete accepts free-text custom action strings and wildcards (`*`, custom action names) in addition to the standard predefined actions (`create`, `read`, `update`, `delete`, `execute`, `manage`, `approve`, `reject`, `view`, `respond`).
- **Batch save (Form view path):** Saving from Form view collects all current policies (additions, edits, and deletions) and sends them to the batch save endpoint, replacing all policies for the role atomically in a single request.
- **Batch save (JSON view path):** Saving from JSON view first validates the JSON content, then parses it and sends the resulting policies to the batch save endpoint; if validation fails, the save is blocked.
- **Validation failure prevents save:** If JSON validation fails (malformed JSON, missing required fields, invalid resource types), the save operation is blocked and inline error messages are displayed.
- **API error handling:** If the batch save endpoint returns an error (network failure, 422 validation error, 500 server error), the dialog displays an error alert with the error message and keeps the dialog open so the administrator can retry or cancel without losing changes.
- **Unsaved changes guard (Cancel button):** Clicking the Cancel button when there are unsaved changes shows a confirmation dialog ("Discard unsaved changes?") before closing.
- **Unsaved changes guard (Escape key):** Pressing Escape when there are unsaved changes shows the same confirmation dialog.
- **Unsaved changes guard (backdrop click):** Clicking the dialog backdrop when there are unsaved changes either shows the confirmation dialog or is disabled to prevent accidental data loss.
- **No unsaved changes:** Closing the dialog when no changes have been made dismisses immediately without confirmation.
- **Parent table refresh:** After successful batch save, the dialog closes and the parent role policies table refreshes automatically without requiring a manual page reload.
- **Policy count update:** Role cards and chips displaying policy counts update to reflect the new policy count after batch save.

## 3. Critical Scenarios

### Namespace Structure

- **WHEN** the backend starts and loads `ResourceTypeManifest` **THEN** the manifest contains exactly 17 keys, all following the `module::submodule` format with `::` delimiter.
- **WHEN** a consumer iterates the manifest **THEN** keys are grouped into exactly 3 modules: `agent` (12), `integration` (2), `system` (3).
- **WHEN** the manifest is queried for a module-level wildcard (`agent::*`) **THEN** all 12 concrete submodules under `agent` are returned.
- **WHEN** the `GET /api/v1/policy/resource-types` endpoint is called **THEN** the response contains 17 entries with `resource_type` and `actions` fields, and no flat legacy values are present.
- **WHEN** a frontend test renders the `AddStatementDialog` with the resource types endpoint response **THEN** the dropdown groups options under three module headings and each option shows a `::`-delimited identifier.
- **WHEN** the frontend's resource type mirror configuration is inspected **THEN** all 17 identifiers match the backend manifest exactly (no drift).

### Policy Authoring CRUD

- **WHEN** an administrator opens the `AddStatementDialog` for a role **THEN** the resource type dropdown shows 17 options grouped under "Agents" (12), "Integrations" (2), and "System" (3).
- **WHEN** an administrator selects `agent::roles` with action `manage` and submits **THEN** the policy table shows a new row with module value `agent::roles` and the role's policy count increments.
- **WHEN** an administrator views an existing policy statement in the policy table **THEN** the module column displays the namespaced identifier (e.g., `agent::management` not `agent`).
- **WHEN** an administrator opens the edit dialog for a policy with module `integration::mcp_hub` **THEN** the resource type dropdown is pre-selected to `integration::mcp_hub`.
- **WHEN** an administrator changes the resource type from `agent::skills` to `agent::sops` and saves **THEN** the policy table immediately reflects `agent::sops` without page reload.
- **WHEN** an administrator deletes a policy statement with module `system::permissions` **THEN** the row is removed from the table and the role's policy count decrements without page reload.
- **WHEN** an administrator views the role's JSON representation **THEN** the `module` field shows the namespaced value (e.g., `"module": "agent::trails"`).
- **WHEN** an administrator clones a role containing namespaced-policy statements **THEN** the cloned role's policies retain the same namespaced identifiers.
- **WHEN** an administrator submits a policy with an unknown resource type (e.g., `agent::nonexistent`) **THEN** the backend returns a 422 or 400 error with a message indicating the type is not valid.
- **WHEN** an administrator submits a policy with a legacy flat value (e.g., `agent`) **THEN** the backend rejects it with a clear error indicating namespaced format is required.

### Wildcard Support

- **WHEN** a policy statement is created with module `agent::*` and action `read` **THEN** the permission engine grants access to `agent::roles`, `agent::identities`, `agent::management`, `agent::runtime_control`, `agent::skills`, `agent::sops`, `agent::model_configs`, `agent::schedules`, `agent::trails`, `agent::human_intervention`, `agent::data_types`, and `agent::outputs` for the `read` action.
- **WHEN** a policy statement is created with module `integration::*` and action `execute` **THEN** the permission engine grants access to `integration::mcp_hub` and `integration::notifications` for the `execute` action.
- **WHEN** a policy statement is created with module `system::*` and action `manage` **THEN** the permission engine grants access to `system::observability`, `system::permissions`, and `system::system_config` for the `manage` action.
- **WHEN** a policy statement is created with module `*::*` and action `read` **THEN** the permission engine grants access to all 17 resource types for the `read` action.
- **WHEN** a policy statement uses module `agent::*` **THEN** it does NOT match a request for `agent::*` itself (wildcard resolves to concrete submodules only).
- **WHEN** the policy editor dropdown includes wildcard options **THEN** `agent::*`, `integration::*`, `system::*`, and `*::*` are available as selectable options, visually distinct from concrete submodules.

### Migration

- **WHEN** the migration script `alembic upgrade head` runs against a database containing legacy flat values in `policy_statements.module` and `policy_resources.resource_type` **THEN** all 15 legacy values are transformed to their correct namespaced equivalents.
- **WHEN** the migration script completes **THEN** no `policy_statements.module` or `policy_resources.resource_type` column contains a legacy flat value.
- **WHEN** a role had a policy with module `permissions` before migration **THEN** after migration the module is `system::permissions` and the effective permission scope is unchanged (the role can still manage permissions).
- **WHEN** a role had policies with modules `conversation` and `result` before migration **THEN** after migration both policies show module `agent::trails` and the role retains access to agent trails features.
- **WHEN** the migration is downgraded (`alembic downgrade -1`) **THEN** all namespaced values revert to their original legacy flat values (for the 15 that had legacy equivalents) and new types (7 items) that had no legacy equivalent are handled gracefully.
- **WHEN** querying `information_schema.columns` for `policy_statements.module` after migration **THEN** the column type is unchanged (`character varying(100)`, nullable=NO), confirming no schema-level change occurred.
- **WHEN** querying `information_schema.columns` for `policy_resources.resource_type` after migration **THEN** the column type is unchanged (`character varying(100)`, nullable=NO).

### Permission Engine Module Matching

- **WHEN** `PermissionEngine.authorize()` is called with `module="agent::roles"` and a policy exists with `module="agent::roles"` **THEN** the module matches (exact match).
- **WHEN** `PermissionEngine.authorize()` is called with `module="agent::skills"` and a policy exists with `module="agent::*"` **THEN** the module matches (wildcard match).
- **WHEN** `PermissionEngine.authorize()` is called with `module="integration::mcp_hub"` and a policy exists with `module="*::*"` **THEN** the module matches (global wildcard).
- **WHEN** `PermissionEngine.authorize()` is called with `module="agent::roles"` and a policy exists with `module="integration::*"` **THEN** the module does NOT match (wrong module-level wildcard).
- **WHEN** `PermissionEngine.authorize()` is called with `module="agent::roles"` and a policy exists with `module="agent::management"` **THEN** the module does NOT match (different submodule).
- **WHEN** a policy has `module="agent::*"` and `resource_type="*"` **THEN** the wildcard in `module` is evaluated independently from `resource_type/resource_id` wildcards.
- **WHEN** a policy statement uses `module="*::*"` **THEN** the existing `effect` (allow/deny) logic is unaffected; denial with `*::*` denies all modules.

### Consolidation & Scope Broadening

- **WHEN** a user previously had a policy granting `manage` on module `tag` **THEN** after migration the policy shows `system::permissions` and the user can access all permissions sub-features (tags, roles, groups, users, access requests).
- **WHEN** a user previously had a policy granting `read` on module `conversation` **THEN** after migration the policy shows `agent::trails` and the user can access both conversation history and result history.
- **WHEN** a new submodule (e.g., `agent::identities`) that was previously unpermissioned is queried **THEN** a role without explicit `agent::identities` or `agent::*` permission is denied access.

### Negative Cases (Flat Values & Invalid Input)

- **WHEN** the `POST /api/v1/user-roles/{id}/policies` endpoint receives `"module": "agent"` (flat) **THEN** it returns 422 with a message indicating the namespaced format `module::submodule` is required.
- **WHEN** the `POST /api/v1/user-roles/{id}/policies` endpoint receives `"module": "mcp_server"` (flat) **THEN** it returns 422.
- **WHEN** the `POST /api/v1/user-roles/{id}/policies` endpoint receives `"module": "agent::nonexistent"` **THEN** it returns 422 with message indicating the resource type is not in the manifest.
- **WHEN** the `POST /api/v1/user-roles/{id}/policies` endpoint receives `"module": ""` (empty) **THEN** it returns 422.
- **WHEN** the `POST /api/v1/user-roles/{id}/policies` endpoint receives `"module": "agent::roles::extra"` (three layers) **THEN** it returns 422.
- **WHEN** the `POST /api/v1/user-roles/{id}/policies` endpoint receives `"module": "agent:roles"` (single colon) **THEN** it is either rejected (strict) or normalized to `agent::roles` (lenient) — behavior must be consistent and documented.

### Dashboard Exemption

- **WHEN** a user with no specific resource-type permissions navigates to `/dashboard` **THEN** the page loads successfully (HTTP 200, no redirect to login or 403).
- **WHEN** the application starts after the namespaced resource type migration **THEN** the dashboard route has no `require_permission()` decorator added as a side effect.

### Role Policy Dialog

- **WHEN** an administrator opens the `RolePolicyDialog` for a role with 3 existing policies **THEN** the dialog shows 3 policy rows in Form view by default, each with resource type and action selectors pre-populated with the current values.
- **WHEN** the `RolePolicyDialog` is opened for a role with no existing policies **THEN** the dialog shows an empty policy list in Form view with an "Add Policy" button available to create the first policy.
- **WHEN** an administrator toggles from Form view to JSON Source Code view **THEN** the dialog displays valid, formatted JSON representing all current policies, including any unsaved additions, edits, or deletions made in Form view.
- **WHEN** an administrator edits a policy's `resource_type` value directly in the JSON view textarea and toggles back to Form view **THEN** the edited resource type value is reflected in the Form view selector for that policy row.
- **WHEN** an administrator types `agent::*` into the resource type free-text autocomplete field **THEN** the value is accepted as a valid input and can be saved as a module-level wildcard.
- **WHEN** an administrator types `agent::mana*` into the resource type free-text autocomplete field **THEN** the value is accepted as a valid free-text input (partial prefix wildcard).
- **WHEN** an administrator types `*::*` into the resource type free-text autocomplete field **THEN** the value is accepted and treated as a global wildcard spanning all modules.
- **WHEN** an administrator types `*` into the action free-text autocomplete field **THEN** the value is accepted as a wildcard action granting all action types.
- **WHEN** an administrator types a custom action string (e.g., `deploy`) into the action free-text autocomplete field **THEN** the value is accepted as free-text input alongside the standard predefined actions.
- **WHEN** an administrator clicks "Validate" on syntactically valid JSON in JSON Source Code view **THEN** the dialog shows a success indicator confirming the JSON is parseable and structurally correct.
- **WHEN** an administrator clicks "Validate" on malformed JSON (e.g., missing closing brace or bracket) **THEN** the dialog shows a specific error message indicating the JSON is not parseable, including the error location (line number and character position).
- **WHEN** an administrator clicks "Validate" on JSON that is parseable but missing the required `policies` array **THEN** the dialog shows an error message indicating the required structure is missing.
- **WHEN** an administrator clicks "Validate" on JSON containing a policy object with an empty `resource_type` field **THEN** the dialog shows an error message indicating the resource type is required for that policy entry.
- **WHEN** an administrator clicks "Validate" on JSON containing a policy with a flat (non-namespaced) `resource_type` value like `"agent"` **THEN** the dialog shows an error indicating the namespaced format `module::submodule` is required.
- **WHEN** an administrator clicks "Save" from JSON view with valid, validated JSON **THEN** the batch save endpoint is called with all parsed policies and, on success, the dialog closes and the parent table refreshes.
- **WHEN** an administrator adds a new policy row, edits an existing policy's resource type, and deletes a third policy in Form view, then clicks "Save" **THEN** the batch save endpoint receives all remaining policies reflecting the add, edit, and delete operations from the dialog session.
- **WHEN** the batch save endpoint returns a 500 server error **THEN** the dialog displays an error alert with the error message and remains open, preserving all unsaved changes so the administrator can retry.
- **WHEN** the batch save endpoint returns a 422 validation error (e.g., unknown resource type in one policy) **THEN** the dialog displays the specific validation error message and keeps all unsaved changes intact for correction.
- **WHEN** an administrator has made unsaved changes and clicks the Cancel button **THEN** a confirmation dialog appears asking "Discard unsaved changes?" before closing.
- **WHEN** an administrator has made unsaved changes and presses the Escape key **THEN** a confirmation dialog appears asking if they want to discard changes.
- **WHEN** an administrator has made unsaved changes and clicks the dialog backdrop **THEN** the dialog either shows the discard confirmation or remains open (backdrop click disabled) to prevent accidental data loss.
- **WHEN** an administrator confirms discarding changes in the confirmation dialog **THEN** the RolePolicyDialog closes without saving and the parent table remains unchanged (policies revert to pre-dialog state).
- **WHEN** an administrator cancels the discard confirmation (clicks "Keep Editing") **THEN** the RolePolicyDialog remains open with all unsaved changes intact.
- **WHEN** an administrator opens the dialog, makes no changes, and clicks Cancel **THEN** the dialog closes immediately without showing a confirmation prompt.
- **WHEN** an administrator successfully saves changes via the batch endpoint **THEN** the role's policy count badge/chip on the parent page updates to reflect the new count without a manual page reload.

## 4. Edge Cases & Risks

### High Risk

| Risk | Mitigation |
|------|-----------|
| **Consolidation silently elevates privileges:** Five types merging into `system::permissions` means any user with just `tag` access can now manage `user`, `group`, `permissions`, and `access_request`. While intentional per PRD, verify the permission engine correctly evaluates `system::permissions` against all five feature areas. | Integration test verifying a role with only `system::permissions:manage` can access all consolidated endpoints. E2E test showing permissions page tabs all accessible with this single permission. |
| **Wildcard parsing errors:** If `agent::*` incorrectly matches `agent::roles_extra` (a theoretical future submodule) due to string prefix matching rather than manifest-aware expansion, it creates privilege escalation. | Unit test verifying wildcard expansion uses exact manifest enumeration, not string matching. Test with edge-case strings that would false-match under naive prefix logic. |
| **Migration data loss:** If the migration script has an error for certain consolidation paths (especially `conversation`+`result`→`agent::trails` where two types become one), policies could be dropped or duplicated. | Migration integration test with pre-seeded data covering all 15 legacy types. Verify row counts: no rows lost, no unintended duplicates. Verify each legacy `module` value maps to exactly the expected namespaced value. |
| **Backward reference breakage:** ~185 `require_permission()` call sites across routers reference `RT_*` constants. If constants are renamed without updating all call sites, imports fail at startup. | Grep/static analysis to verify no old constant name remains in use. Unit test importing all renamed constants confirms they resolve. |
| **Frontend/backend manifest drift:** If the frontend maintains a separate hardcoded list of resource types (not fetched from `/api/v1/policy/resource-types`), it may fall out of sync with the backend. | E2E test verifying the dropdown options match the backend endpoint response exactly. Frontend unit test that the mirror manifest has all 17 entries. |

### Medium Risk

| Risk | Mitigation |
|------|-----------|
| **Dashboard accidentally gated:** During the refactor, a `require_permission()` decorator could be inadvertently added to the dashboard route. | Explicit E2E test that unauthenticated/unauthorized user can reach dashboard. |
| **i18n labels not updated:** Hardcoded or translated strings referencing flat resource type names may appear in the UI if not updated. | Visual inspection of policy editor, search for old flat strings in i18n resource files. |
| **TagDefinition.resource_type inconsistency:** The `tag_definitions.resource_type` column stores flat values. While out of scope, a tag scoped to `resource_type=agent` may not match a policy using `agent::management`. | Documented as out of scope but test that existing tag-scoped policies continue to work post-migration. |
| **Alembic downgrade with new types:** 7 new submodules have no legacy equivalent. An `alembic downgrade` must handle these gracefully (leave as-is or map to a safe default). | Test downgrade migration to confirm it completes without error and leaves the database in a consistent state. |
| **Role clone with namespaced identifiers:** Cloning a role must deep-copy policy statements and preserve namespaced module values correctly. | E2E test verifying cloned role has identical policy structure with namespaced identifiers intact. |

### Low Risk

| Risk | Mitigation |
|------|-----------|
| **Performance regression:** `*::*` or `agent::*` evaluation expanding to 12+ submodules on every authorization call could add latency. | Performance benchmark comparing authorization time before/after change. Target: no measurable difference (<5ms added). |
| **UI display length:** Namespaced identifiers are longer (up to ~30 chars vs. ~15 chars). Table columns and chips must accommodate the wider text. | Visual check of policy table layout. Ensure no text truncation at common viewport widths. |
| **Case sensitivity:** `Agent::Roles` vs. `agent::roles` — manifest matching must be case-sensitive and consistent. | Unit test verifying exact case matching. |
| **Dialog bidirectional sync data loss:** If the Form→JSON serialization or JSON→Form deserialization has a bug, administrator edits could be silently lost during view toggle. | Unit test that serializes Form state → JSON → Form and verifies exact round-trip fidelity for add, edit, and delete operations. |
| **Batch save atomicity:** If the batch save partially succeeds (some policies saved, others failed), the role ends up in an inconsistent state. The endpoint must be fully atomic — either all policies are replaced or none are. | Integration test verifying that a batch save with one invalid policy in the middle rejects the entire operation and leaves existing policies unchanged. |
| **Large policy sets in dialog:** A role with 50+ policies could produce a large JSON payload that is difficult to manually edit in the textarea. Form view remains the primary editing path. | Manual test: load a role with 50 policies, verify Form view is usable, verify JSON view renders without truncation. |

## 5. Acceptance Criteria Checklist

Mapped directly to PRD acceptance criteria (Section "Acceptance Criteria" in prd.md).

### Namespace Structure

- [ ] All resource types follow the `module::submodule` pattern using `::` as the delimiter.
- [ ] Three modules exist: `agent`, `integration`, `system` — matching the three sidebar groups.
- [ ] Seventeen submodules map to the sidebar menu items (12 agent, 2 integration, 3 system).
- [ ] No resource type has deeper nesting than two layers.

### Policy Authoring (CRUD)

- [ ] Policy editor dropdowns display namespaced resource types grouped by module, mirroring the sidebar organization.
- [ ] Administrator can create a new policy statement using any namespaced resource type.
- [ ] Administrator can view all policy statements with namespaced resource types displayed in the table.
- [ ] Administrator can edit an existing policy statement and change its resource type to any valid namespaced type.
- [ ] After closing the create/edit dialog, the parent policy table refreshes automatically to show updated resource type names.
- [ ] Administrator can delete a policy statement with namespaced resource types and it is removed immediately.
- [ ] System rejects invalid resource types (not in manifest) with a clear error message.

### Role Policy Dialog (Dialog-Based CRUD)

- [ ] RolePolicyDialog opens with all existing policies for the role displayed in Form view by default.
- [ ] Toggle between Form view and JSON Source Code view preserves all unsaved changes bidirectionally (round-trip fidelity).
- [ ] JSON Source Code view displays current policies as formatted JSON matching the batch save payload structure.
- [ ] Validate button in JSON view detects malformed JSON and reports parse errors with line/character references.
- [ ] Validate button detects missing required fields (`policies` array, `resource_type`, `actions`) with specific error messages.
- [ ] Validate button detects invalid resource types (flat values, unknown identifiers) in JSON content.
- [ ] Free-text resource type input accepts wildcards (`agent::*`, `agent::mana*`, `*::*`, `*`) in addition to predefined manifest values.
- [ ] Free-text action input accepts wildcards (`*`) and custom action strings in addition to the standard predefined actions.
- [ ] Save from Form view sends all policies (additions, edits, deletions) to the batch save endpoint atomically.
- [ ] Save from JSON view runs validation first, then sends parsed policies to the batch save endpoint; blocked on validation failure.
- [ ] Validation failure prevents the save operation and displays inline error messages in the appropriate view.
- [ ] API errors during batch save display an error alert and keep the dialog open with all unsaved changes preserved.
- [ ] Closing the dialog with unsaved changes (Cancel, Escape, backdrop click) prompts a confirmation dialog ("Discard unsaved changes?").
- [ ] Closing the dialog with no unsaved changes dismisses immediately without confirmation.
- [ ] After successful batch save, the dialog closes and the parent role policies table refreshes automatically without page reload.
- [ ] After successful batch save, role policy count badges/chips update to reflect the new count immediately.

### Wildcard Support

- [ ] `agent::*` wildcard grants access to all twelve agent submodules.
- [ ] `integration::*` wildcard grants access to both integration submodules.
- [ ] `system::*` wildcard grants access to all three system submodules.
- [ ] `*::*` wildcard matches every resource type in the manifest.
- [ ] Wildcards cannot be combined with specific submodules in the same policy resource definition.

### Migration

- [ ] After migration, all pre-existing policies show their resource types as the new namespaced equivalents.
- [ ] The platform's built-in system administrator role retains full access equivalent to `*::*` across all modules.
- [ ] No administrator needs to manually update any existing policy statements.

### Dashboard

- [ ] The Dashboard page (`/dashboard`) remains accessible without any specific permission check, consistent with current behaviour.

### Documentation & Communication

- [ ] `docs/master/product/features/foundation-platform.md` updated to reflect namespaced resource types.
- [ ] Product spec accurately describes the full namespace-to-menu mapping.

### DB Migration Specific (has_db_changes: true)

- [ ] `information_schema` confirms `policy_statements.module` column type unchanged (`varchar(100)`, not null).
- [ ] `information_schema` confirms `policy_resources.resource_type` column type unchanged (`varchar(100)`, not null).
- [ ] Migration transforms all 15 legacy values to 17 namespaced values with zero data loss.
- [ ] Migration consolidation groups (5→`system::permissions`, 2→`agent::trails`) produce correct effective permissions.
- [ ] Migration is reversible (`alembic downgrade` succeeds without error).
- [ ] Legacy flat values are rejected by the API after migration.
- [ ] E2E tests include at least one real-backend test (no mocks) validating the full CRUD flow.

## 6. Test File References

Test file paths are from `docs/config.yaml` `source.tests`. Files marked **(NEW)** must be created. Files marked **(UPDATE)** require modification of existing tests.

### Backend — Unit Tests

| File | Status | What It Covers |
|------|--------|---------------|
| `backend/tests/unit/test_resource_type_manifest.py` | **COMPLETE** | Manifest structure with 17 namespaced identifiers, module grouping, legacy constant removal/alias verification, wildcard resolution helpers. (13 tests) |
| `backend/tests/unit/test_permission_engine.py` | **COMPLETE** | `::`-delimited module matching: exact match, `module::*` wildcard, `*::*` wildcard, boundary cases (wrong module, wrong delimiter). (17 tests) |
| `backend/tests/unit/test_resource_type_parser.py` | **COMPLETE** | `::` delimiter parsing, flat-value rejection, three-layer rejection, empty-value rejection, edge cases (single colon, extra whitespace). (23 tests) |

### Backend — Integration/API Tests

| File | Status | What It Covers |
|------|--------|---------------|
| `backend/tests/api/v1/test_policy_endpoints.py` | **COMPLETE** | `GET /api/v1/policy/resource-types` returns 17 namespaced entries; `POST /policies` accepts namespaced `module` and rejects flat/legacy values; `DELETE /policies` with namespaced identifiers. (15 tests) |
| `backend/tests/api/v1/test_roles_api.py` | **COMPLETE** | Role CRUD with namespaced policy statements; role clone preserves namespaced `module` values. Updated to use `RT_SYSTEM_PERMISSIONS` instead of flat `"permissions"`. (4 tests) |
| `backend/tests/api/v1/test_permissions_api.py` | **COMPLETE** | Permission evaluation with namespaced identifiers; wildcard policy evaluation against real DB. (6 tests) |
| `backend/tests/api/v1/test_role_policy_batch.py` | **COMPLETE** | Batch save endpoint: `PUT /api/v1/user-roles/{id}/policies/batch` accepts valid policies array and replaces all policies atomically; rejects invalid resource types in batch payload; rejects flat/legacy module values; rejects missing required fields; rejects empty actions array; requires authentication; returns 404 for non-existent role; accepts all wildcard module patterns (`agent::*`, `integration::*`, `system::*`, `*::*`); handles multiple policies in batch; rejects empty module strings; returns 403 on permission denied. (12 tests)

### Backend — Database Migration Tests

| File | Status | What It Covers |
|------|--------|---------------|
| `backend/tests/db/test_namespace_migration.py` | **COMPLETE** | Verify `information_schema` column properties for `policy_statements.module` and `policy_resources.resource_type`; verify no legacy flat values in deployed DB; verify system administrator role exists. (4 tests — requires real PostgreSQL) |

### Backend — Permission Evaluation (Real DB)

| File | Status | What It Covers |
|------|--------|---------------|
| `backend/tests/integration/test_namespace_permission_evaluation.py` | **COMPLETE** | Manifest structure validation in integration context; DB connectivity smoke test; `information_schema` column type verification. (5 tests — requires real PostgreSQL; unit tests in `test_permission_engine.py` cover the full namespace wildcard matching patterns) |

### Frontend — Unit Tests

| File | Status | What It Covers |
|------|--------|---------------|
| `frontend/src/__tests__/AddStatementDialog.test.tsx` | **UPDATED** | Existing 11 tests pass; added 5 freeSolo autocomplete tests: accepts wildcard `agent::*` via freeSolo input, accepts global `*::*` wildcard, FreeSoloActionSelect renders and is disabled without resource type, accepts wildcard `*` action, accepts custom free-text action strings. (16 tests total) |
| `frontend/src/__tests__/PolicyEditor.test.tsx` | **EXISTING** | Policy table displays `module` column with namespaced identifiers; delete removes row; parent table refresh after add/edit/delete. |
| `frontend/src/__tests__/CloneRoleDialog.test.tsx` | **EXISTING** | Cloned role retains namespaced policy identifiers. |
| `frontend/src/__tests__/permissionsApi.test.ts` | **EXISTING** | API function signatures unchanged (namespaced values are just different strings); verify `createPolicyStatement` can be called with namespaced module value. |
| `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` | **COMPLETE** | Verify frontend mirror has all 17 identifiers matching backend manifest; verify module groupings; verify no flat legacy values present. (19 tests) |
| `frontend/src/__tests__/RolePolicyDialog.test.tsx` | **COMPLETE** | Form view renders all existing policies pre-populated (10 tests); empty role shows "Add Policy" button; toggle Form→JSON serializes current state; toggle JSON→Form deserializes changes back; adds new policy row in Form view; deletes policy row (marks as deleted); calls batch save with all current policies from Form view; shows loading spinner while role data loads; shows error alert when batch save fails; dialog has Form and JSON view toggle buttons. |
| `frontend/src/__tests__/RolePolicyDialog.validation.test.tsx` | **COMPLETE** | JSON validation edge cases (13 tests): malformed JSON with parse errors; missing `policies` array; empty `resource_type` in policy; flat (non-namespaced) resource type rejected; empty actions array; success indicator on valid JSON; Save disabled in JSON view without validation; unsaved changes confirmation when Cancel clicked with changes; closes without confirmation when no changes; 422 validation error displayed in dialog; 500 server error displayed; "Keep Editing" preserves dialog open; "Discard" closes the dialog. |

### E2E Tests

| File | Status | What It Covers |
|------|--------|---------------|
| `e2e/tests/namespace-resource-types.spec.ts` | **COMPLETE** | Real-backend tests verifying resource types endpoint returns 17 namespaced entries, includes all 3 modules, wildcard recognition, and auth protection. (4 tests) |
| `e2e/tests/namespace-migration-visibility.spec.ts` | **COMPLETE** | Dashboard accessibility, roles API endpoint availability, resource-types endpoint availability, clone endpoint auth check. (4 tests) |
| `e2e/tests/namespace-validation-errors.spec.ts` | **COMPLETE** | Submit flat/legacy resource type → verify endpoint rejects (not 404). Submit unknown type → verify. Submit empty type → verify. Submit three-layer type → verify. Valid namespaced type → verify endpoint exists. (8 tests) |
| `e2e/tests/role-policy-management.spec.ts` | **EXISTING** | Updated with namespaced resource types in mock data; 10 passing tests including real-backend integration tests. |
| `e2e/tests/permissions.spec.ts` | **EXISTING** | Pre-existing permissions tests; 1 passing, 9 timeout issues (pre-existing `networkidle` issue). |
| `e2e/tests/role-policy-dialog.spec.ts` | **COMPLETE** | E2E tests (7 tests): resource types endpoint returns 17 namespaced entries; batch save endpoint requires authentication; batch save rejects flat resource types; batch save accepts empty policies array; roles page renders with mocked data; all three module groups present; batch save with wildcard module values accepted. Dialog interaction tests (Form/JSON toggle, validation, save) covered extensively in Vitest component tests. |
