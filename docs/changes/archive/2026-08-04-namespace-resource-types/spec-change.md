# Specification Delta — Namespaced Resource Types

## Affected Spec Areas

| Spec Area | Master Doc | Nature of Change |
|-----------|-----------|------------------|
| Platform Permissions & IAM | `docs/master/product/features/foundation-platform.md` | Resource type model replaced; dialog-based policy editing UX added |
| Policy Statement Data Model | `docs/master/data-model/` (to be created/updated) | `module` field values change |
| Permission Engine | `docs/master/technology/` (to be created/updated) | Module matching logic changes |
| Role Policy Editor UI | `docs/master/ux/prototype/index.html` (to be updated) | Inline expand replaced with dialog; Form/JSON toggle added; free-text selectors added |

## New Capabilities

### Namespaced Resource Type Model
The platform adopts a two-layer namespace scheme (`module::submodule`) for all permission resource types. Each identifier directly maps to a visible sidebar menu item, creating a single, consistent mental model for administrators.

### Module-Level Wildcards
Administrators can now grant permissions at module granularity:
- `agent::*` — Covers all 12 agent submodules (roles, identities, management, runtime_control, skills, sops, model_configs, schedules, trails, human_intervention, data_types, outputs)
- `integration::*` — Covers both integration submodules (mcp_hub, notifications)
- `system::*` — Covers all 3 system submodules (observability, permissions, system_config)
- `*::*` — Matches every resource type in the manifest (equivalent to the legacy `*` wildcard)

### Grouped Resource Type Selection
The policy editor's resource type dropdown groups options by module (Agents, Integrations, System), mirroring the sidebar organization so administrators can navigate both structures the same way.

### Manifest-Validated Identifiers
All resource type identifiers are validated against a central manifest. Invalid or unknown types are rejected at policy creation/edit time with clear error messaging indicating the correct format (`module::submodule`).

### Dialog-Based Role Policy Editing
Role policy editing moves from inline row expansion to a focused dialog that displays all policies for a role in a single view. The dialog supports two editing modes:
- **Form view** — structured input using dropdowns and chips for resource types and actions
- **JSON Source Code view** — a textarea for direct editing of the policy JSON payload with an in-dialog Validate button that checks JSON parseability before submission

Changes made in either view are saved as a single batch operation when the user clicks Save, ensuring atomic updates to the full policy set.

### Free-Text Wildcard Input in Selectors
Resource type and action selector components support free-text entry in addition to dropdown selection. Administrators can type partial submodule names, full `module::submodule` identifiers, or wildcard patterns directly:
- `agent::*` — all submodules within a module
- `agent::mana*` — prefix wildcard matching (e.g., `agent::management`)
- `*::*` — every resource type in the manifest
- `*` — all actions

Dropdown options remain available for guided selection; free-text input is an additional input path within the same component.

### Inline JSON Validation
The JSON Source Code view provides a Validate button that performs a client-side parse check on the current textarea content. Valid JSON shows a success indicator; invalid JSON surfaces the parse error message and line reference in-place so the administrator can fix syntax errors before attempting to save.

## Modified Capabilities

### Resource Type Identifiers (Before → After)

**Agents Module** (`agent::*`):
| Before | After | Sidebar Label |
|--------|-------|---------------|
| `role` | `agent::roles` | Agent Roles |
| _(none)_ | `agent::identities` | Agent Identities |
| `agent` | `agent::management` | Agent Types / Agent Management |
| _(none)_ | `agent::runtime_control` | Runtime Control |
| `skill` | `agent::skills` | Skills |
| _(none)_ | `agent::sops` | SOPs |
| _(none)_ | `agent::model_configs` | Model Configs |
| `scheduling` | `agent::schedules` | Schedules |
| `conversation`, `result` | `agent::trails` | Agent Trails |
| `intervene` | `agent::human_intervention` | Human Intervene |
| `data_type` | `agent::data_types` | Data Types |
| _(none)_ | `agent::outputs` | Agent Outputs |

**Integrations Module** (`integration::*`):
| Before | After | Sidebar Label |
|--------|-------|---------------|
| `mcp_server` | `integration::mcp_hub` | MCP Hub |
| `notification` | `integration::notifications` | Notifications |

**System Module** (`system::*`):
| Before | After | Sidebar Label |
|--------|-------|---------------|
| _(none)_ | `system::observability` | Observability |
| `permissions`, `group`, `user`, `tag`, `access_request` | `system::permissions` | Permissions |
| _(none)_ | `system::system_config` | System Config |

### Manifest Growth
The resource type manifest grows from **15 flat identifiers** to **17 namespaced identifiers** across 3 modules. Several previously unpermissioned sidebar items (Agent Identities, Runtime Control, SOPs, Model Configs, Agent Outputs, Observability, System Config) gain dedicated resource types, enabling finer-grained access control.

### Consolidated Submodules
- `conversation` and `result` consolidate into `agent::trails` (matching the "Agent Trails" combined page)
- `permissions`, `group`, `user`, `tag`, and `access_request` consolidate into `system::permissions` (matching the unified Permissions page)

### Permission Engine Module Matching
The permission engine's `module` parameter now accepts `::`-delimited identifiers. Wildcard matching extends from the current `*` (match all) to support `module::*` (match all submodules within a module) and `*::*` (match all modules and submodules). The engine validates identifiers against the updated manifest.

## Removed Capabilities

- **Flat resource type identifiers** — The 15 legacy flat strings (`agent`, `mcp_server`, `conversation`, `group`, `user`, `tag`, `role`, `access_request`, `permissions`, `skill`, `scheduling`, `notification`, `result`, `data_type`, `intervene`) are no longer accepted as valid resource types after migration.
- **Single-level wildcard `*`** — The legacy `*` wildcard in the `module` field is replaced by `*::*`, which is semantically equivalent but explicitly represents the two-layer namespace. (Internal references to `*` may be preserved for backward compatibility during the transition.)

## Spec Update Instructions

Update the following master documentation files after this change is implemented and verified:

### `docs/master/product/features/foundation-platform.md`
- Replace any references to flat resource type identifiers with the namespaced equivalents
- Add a section documenting the `module::submodule` naming convention with a table mapping sidebar menu items to their resource type identifiers
- Document wildcard semantics: `agent::*`, `integration::*`, `system::*`, `*::*`
- Document prefix wildcard support in resource type selectors (e.g., `agent::mana*`)
- Document the dialog-based role policy editing UX and the Form/JSON toggle
- Note that Dashboard remains permission-exempt

### `docs/master/data-model/` (create or update)
- Document the `policy_statements.module` field's new value format (`module::submodule`)
- Document the `policy_resources.resource_type` field's new value format
- Ensure the entity-relationship diagram reflects the resource type namespace model

### `docs/master/technology/` (create or update)
- Update any technical references to the `ResourceTypeManifest` structure
- Document the permission engine's wildcard evaluation rules for `::`-delimited modules
- Update code reference maps to reflect renamed constants and files
