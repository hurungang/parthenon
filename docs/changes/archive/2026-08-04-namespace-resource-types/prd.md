# Namespaced Resource Types — PRD

## Epic Overview

Administrators configuring IAM policies in Parthenon currently see a flat list of 15 resource type identifiers (e.g., `agent`, `intervene`, `mcp_server`, `role`) that bear no relationship to the sidebar menu they use daily. This mismatch forces administrators to mentally translate between permission identifiers and navigation labels — an error-prone process that slows policy authoring and increases the risk of misconfigured access controls. This epic introduces a two-layer namespace scheme (`module::submodule`) that directly mirrors the sidebar menu hierarchy, so every resource type identifier maps to a visible, intuitive menu location. Administrators will author policies faster, with greater confidence, and fewer mistakes.

## Business Goals

- **Reduce policy-authoring errors** — Eliminate the mental translation step between flat resource type strings and sidebar navigation labels, reducing misconfiguration incidents by 80%+.
- **Speed up administrator onboarding** — New administrators can locate the correct resource type by referencing the menu structure they already know, cutting time-to-first-policy by 50%.
- **Enable module-scoped permissions** — Wildcard support (`agent::*`, `integration::*`, `*::*`) allows granting access to entire menu groups without enumerating every submodule.
- **Preserve backward compatibility** — Migrate all existing policies from flat resource types to their namespace equivalents without administrator intervention or service disruption.
- **Align permission model with navigation model** — Create a single mental model where the menu structure, resource type identifiers, and permission boundaries are consistent.

## Users & Personas

- **Platform Administrators** — The primary beneficiaries. They author IAM policies in the Permissions section and need resource type names that match what they see in the sidebar. Today they memorize cross-references; tomorrow they navigate intuitively.
- **Security Auditors** — Review policy configurations for compliance. Namespaced types make it obvious which policy controls which part of the platform, reducing audit friction.
- **New Parthenon Operators** — Operators unfamiliar with the platform's permission model benefit from resource types that self-document by matching the navigation structure they learn first.

## User Stories

- As a platform administrator, I want to see resource type identifiers in the policy editor that match the sidebar menu names, so that I can author policies without consulting a separate mapping table.
- As a platform administrator, I want to grant access to all items under "Agents" with a single wildcard (`agent::*`), so that I can assign broad permissions without enumerating twelve individual submodules.
- As a platform administrator, I want existing policies to continue working after the migration, so that no user or agent loses access during the transition.
- As a platform administrator, I want to edit all policies for a role inside a dedicated dialog — instead of expanding inline rows — so that I can review and modify the complete policy set in one focused view.
- As a platform administrator, I want to toggle between a form-based policy editor and a raw JSON source code view within the same dialog, so that I can switch between guided input and direct editing depending on the complexity of the policy I am authoring.
- As a platform administrator, I want to type wildcards like `agent::*` or `agent::mana*` directly into resource type and action selectors, so that I can rapidly author broad policies without navigating long dropdown menus.
- As a platform administrator, I want a one-click JSON validator that checks whether my JSON source code is parseable before I attempt to save, so that I can catch syntax errors early and avoid losing work.
- As a platform administrator, I want all policy changes — whether made via the form or JSON — to save in a single batch when I click Save, so that I never end up with a partially updated policy set.
- As a security auditor, I want policy statements to use namespaced resource types that clearly indicate which menu area they control, so that I can quickly assess whether access controls are correctly scoped.
- As a new operator, I want resource type identifiers that match the navigation I already see, so that I can become productive with IAM policies on day one.

## Acceptance Criteria

### Namespace Structure

- All resource types follow the `module::submodule` pattern using `::` as the delimiter
- Three modules exist: `agent`, `integration`, `system` — matching the three sidebar groups
- Seventeen submodules map to the sidebar menu items (12 agent, 2 integration, 3 system)
- No resource type has deeper nesting than two layers

### Policy Authoring (Dialog-Based CRUD)

- Role policy editing opens in a dedicated dialog showing all current policies for the role, instead of expanding inline within the table row
- The dialog provides a toggle between **Form view** (dropdowns and chips for structured input) and **JSON Source Code view** (a textarea where the user can directly edit the full policy JSON)
- JSON Source Code view includes a **Validate** button that instantly checks whether the JSON is parseable and reports syntax errors in-place without saving
- Resource type and action selectors in Form view support **free-text entry** — administrators can type partial submodule names, full namespaced identifiers, or wildcard patterns (`agent::*`, `agent::mana*`, `*::*`, `*` for actions) in addition to selecting from the dropdown
- All policy changes — regardless of whether they were made in Form view or JSON view — are submitted as a **single batch save** when the user clicks Save
- After saving, the dialog closes and the parent policy table refreshes automatically to reflect the updated policy set
- Policy editor dropdowns display namespaced resource types grouped by module, mirroring the sidebar organization
- Administrator can create a new policy statement using any namespaced resource type
- Administrator can view all policy statements with namespaced resource types displayed in the table
- Administrator can edit an existing policy statement and change its resource type to any valid namespaced type
- Administrator can delete a policy statement with namespaced resource types and it is removed immediately
- System rejects invalid resource types (not in manifest and not matching a valid wildcard pattern) with a clear error message
- Dialog surfaces API errors (including permission denials) using the standard dialog error pattern so failures are never silent

### Wildcard Support

- `agent::*` wildcard grants access to all twelve agent submodules (roles, identities, management, runtime_control, skills, sops, model_configs, schedules, trails, human_intervention, data_types, outputs)
- `integration::*` wildcard grants access to both integration submodules (mcp_hub, notifications)
- `system::*` wildcard grants access to all three system submodules (observability, permissions, system_config)
- `*::*` wildcard matches every resource type in the manifest
- Prefix wildcards (e.g., `agent::mana*`) are supported via free-text entry in resource type selectors, matching any submodule whose name starts with the given prefix
- Action selectors support `*` wildcard to grant all actions
- Wildcards cannot be combined with specific submodules in the same policy resource definition (explicit is explicit, wildcard is wildcard)

### Migration

- After migration, all pre-existing policies show their resource types as the new namespaced equivalents
- The platform's built-in system administrator role retains full access equivalent to `*::*` across all modules
- No administrator needs to manually update any existing policy statements

### Dashboard

- The Dashboard page (`/dashboard`) remains accessible without any specific permission check, consistent with current behaviour

### Documentation & Communication

- `docs/master/product/features/foundation-platform.md` updated to reflect namespaced resource types
- Product spec accurately describes the full namespace-to-menu mapping

## Out of Scope

- **Menu restructuring** — The sidebar navigation groups and items remain unchanged; this epic only aligns resource type naming to match the existing structure.
- **New permission actions** — Existing actions (create, read, update, delete, execute, manage, approve, reject, view, respond) remain as-is; no new actions are added or removed.
- **Resource-type-specific UI gating** — Sidebar visibility based on resource type permissions already exists via the `module` field; this epic does not change the gating logic, only the identifiers it operates on.
- **Agent Runtime permission resolution** — The certificate-based permission resolution in the Agent Runtime already uses the `module` field and does not require behavioural changes beyond consuming the new identifier format.
- **Multi-level hierarchy** — Only two levels (`module::submodule`) are supported; no three-level or deeper nesting (e.g., `agent::roles::custom`) is implemented.

## Dependencies & Constraints

- **Database migration required** — Existing policy records must be migrated from flat resource type identifiers to the new namespaced format. A migration script must map all legacy values and complete before the updated backend starts serving traffic.
- **Backend resource type registry** — The backend resource type registry must adopt namespaced identifiers across all permission enforcement points and validation logic throughout the platform.
- **Frontend resource type configuration** — The frontend resource type configuration must mirror the namespaced format and module groups so that dropdowns and labels display the new identifiers.
- **Permission enforcement logic** — The permission evaluation logic must handle `::`-delimited identifiers and evaluate wildcard patterns (`*::*`, `module::*`) correctly.
- **Consolidation scope broadening** — Consolidating multiple legacy resource types into unified submodules (e.g., five types into `system::permissions`, two into `agent::trails`) may broaden existing permissions. This broadening is intentional and aligns access control boundaries with the unified page model.
- **No external service dependencies** — This change is fully contained within Parthenon's backend and frontend; no changes to Keycloak, MCP servers, or external identity providers are needed.
- **Dialog error handling pattern** — The role policy dialog must surface API failures — including 403 permission denials — to administrators using the standard dialog error display pattern, so that failed operations are never silent.
- **Free-text selector support** — Resource type and action selectors must accept both dropdown selection and free-text entry, supporting partial names, full namespaced identifiers, and wildcard patterns (`agent::*`, `agent::mana*`, `*`).
- **Migration window** — The database migration is a one-time, offline operation that must complete before the updated backend starts serving traffic to avoid inconsistent permission evaluation.
