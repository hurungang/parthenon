# Foundation Platform

## Overview
The Foundation Platform provides the core identity, access, and user experience layer for Parthenon. It enables secure onboarding, role-based access control, and a unified Web UI shell for all users and agents, ensuring that only authorized actions are performed and that setup is streamlined for enterprise environments.

The platform's permission model uses a namespaced resource type system (`module::submodule`) that directly mirrors the sidebar menu hierarchy. Every resource type identifier corresponds to a visible menu location, so administrators author policies using names they already recognise — eliminating the need to memorise cross-references between permission strings and navigation labels.

Parthenon supports two deployment modes for identity and infrastructure: **bundled** (where Keycloak and supporting services run alongside Parthenon in Docker Compose, ideal for development and self-hosted deployments) and **external** (where enterprise-managed PostgreSQL, Azure EntraID or an existing Keycloak instance, Redis, and observability infrastructure are provided externally and configured via environment variables — no YAML file editing or container rebuilding required). The same application code serves both modes; operators choose their configuration strategy without modifying Parthenon source.

Authentication is built on a provider-agnostic OIDC foundation that supports any OIDC-compliant identity provider — not only Keycloak and Azure EntraID. User identity and agent identity are decoupled, allowing enterprises to source each from separate, independent identity providers. A built-in super admin account provides guaranteed administrative access for production bootstrap and disaster recovery, functioning independently of any OIDC provider. All OIDC configuration is managed through a web UI and persisted to the database, eliminating the need for operators to hand-edit configuration files.

## Who Uses It

- Enterprise Admins: Configure roles, permissions, user tags, user groups, and identity provider integration
- User Group Owners: Approve or reject user group membership requests and manage group membership
- Business Users: Access the Web UI to interact with agents and workflows; request access to user groups as needed
- Compliance Auditors: Verify access controls and user activity
- Platform Operators: Deploy Parthenon in production; configure user and agent identity providers through the system config UI; rely on the super admin account for bootstrap and disaster recovery when OIDC is unavailable

## What It Does
- Supports OIDC-based authentication with any OIDC-compliant identity provider (not limited to Keycloak or Azure EntraID)
- Decouples user identity from agent identity, allowing each to point to an independent OIDC provider
- Provides a built-in super admin account that authenticates independently of OIDC, guaranteeing administrative access for bootstrap and disaster recovery
- Enables operators to configure and manage OIDC identity providers through a web UI in the system config module, with all settings persisted to the database
- Allows operators to test OIDC provider connectivity and attempt a test login from the UI before committing configuration changes
- Supports enabling or disabling the super admin account via configuration, with guard rails preventing disablement without at least one working OIDC provider
- Provides a consolidated environment setup command that operators run to bootstrap an environment in a single step: Keycloak realm and client provisioning, admin user creation, database readiness verification, certificate authority bootstrapping, and optional dev-mode data seeding — all idempotent and self-documenting
- Provides a setup wizard for initial platform configuration via the Web UI (dev/demo and production paths), which is complementary to the CLI setup command
- Manages user, agent, and hybrid roles with granular permissions
- Enables user tag management for flexible access control
- Allows policy-based user role authoring with fine-grained conditions
- Supports user group creation, assignment of group owners, and binding to IdP claims for automatic group assignment
- Provides user caching and direct user role assignment by admins
- Delivers a unified Web UI shell for all platform features
- Enables a self-service user group request and approval flow for users not auto-assigned to groups
- Provides an operational dashboard with real-time stat cards, time-sensitive metrics, and permission-aware widgets — giving operators an immediate platform health overview on login
- Uses namespaced resource types (`module::submodule`) that mirror the sidebar menu hierarchy, so every permission identifier maps to a visible navigation location
- Supports module-level wildcards (`agent::*`, `integration::*`, `system::*`, `*::*`) for granting broad access without enumerating individual submodules
- Provides dialog-based role policy editing with a toggle between Form view (guided dropdowns) and JSON Source Code view (direct policy editing)
- Supports free-text wildcard entry in resource type and action selectors, including prefix wildcards (`agent::mana*`)
- Provides inline JSON validation with a Validate button so administrators can catch syntax errors before committing policy changes

## Key Concepts
- **OIDC Integration**: Connecting to an external identity provider for authentication. The platform supports any OIDC-compliant provider (not just Keycloak or Azure EntraID). User and agent identity providers are configured independently through the UI.
- **Super Admin**: A platform-internal administrative account that authenticates independently of any OIDC provider. Credentials are sourced from the config system with environment variable override. The super admin can be enabled or disabled, and provides guaranteed administrative access for bootstrap and disaster recovery.
- **User Identity Provider**: The OIDC identity provider that authenticates human users. Configured independently from the agent identity provider.
- **Agent Identity Provider**: The OIDC identity provider that authenticates agent principals. Can be the same as or different from the user identity provider, enabling segregation of human and machine identity domains.
- **Database-Backed OIDC Configuration**: All OIDC provider settings (issuer URL, client ID, client secret, scopes, claims mapping) are persisted in the database and managed through the system config UI, replacing static YAML files as the source of truth.
- **OIDC Provider Testing**: Operators can validate provider reachability and client credentials (test connection) and attempt a full OIDC login flow (test login) from the system config UI before committing changes.
- **Role Management**: Assigning and managing user and agent roles
- **Permission Enforcement**: Controlling access to features and actions
- **Setup Wizard**: Guided onboarding for initial configuration
- **Web UI Shell**: The main user interface for all platform operations
- **User Tag**: A reusable label that categorizes users or resources and can be used as a condition in access policies
- **User Policy Statement**: A business rule defining what actions a user or group can perform on which resources, optionally filtered by user tags
- **User Group**: A collection of users managed together, which can be assigned roles and policies and linked to IdP claims for automatic membership
- **IdP Claim Mapping**: The process of binding identity provider attributes (such as group claims) to platform user groups for automatic assignment
- **User Group Request**: A self-service flow where users can request to join user groups, subject to approval by group owners
- **Namespaced Resource Type**: A two-layer permission identifier in the format `module::submodule` that directly mirrors the sidebar menu structure. For example, `agent::roles` controls access to the Agent Roles page, and `integration::mcp_hub` controls access to the MCP Hub page. The first segment names the sidebar group; the second segment names the menu item within that group. All resource type identifiers are validated against a central manifest — unknown or malformed identifiers are rejected at policy creation time with a clear error.
- **Module-Level Wildcard**: A permission identifier ending in `::*` that grants access to every submodule within a module. For example, `agent::*` covers all twelve agent submodules (roles, identities, management, runtime control, skills, SOPs, model configs, schedules, trails, human intervention, data types, outputs). This allows administrators to grant broad module access in a single policy statement instead of listing every submodule individually.
- **Prefix Wildcard**: A wildcard pattern typed directly into a resource type selector, such as `agent::mana*`, which matches any submodule whose name begins with the given prefix (e.g., `agent::management`). Prefix wildcards are supported through free-text entry in selectors — they are not visible in the dropdown and have no dedicated UI affordance.
- **Universal Wildcard** (`*::*`): Matches every resource type in the manifest across all modules. This is the modern equivalent of the legacy single-level `*` and is used by the platform's built-in system administrator role to retain full access.
- **Policy Editor Dialog**: A dedicated dialog that opens when editing role policies, displaying all current policies for a role in a single view. This replaces the previous inline row-expansion pattern, giving administrators a focused workspace where they can add, modify, or remove policy statements. All changes are saved in a single batch when the user clicks Save, ensuring atomic updates to the full policy set. On save, the dialog closes and the parent policy table refreshes automatically.
- **Form / JSON Toggle**: Within the policy editor dialog, a toggle switch lets administrators choose between two editing views. **Form view** provides structured input with dropdowns and chips for resource types and actions — best for guided policy authoring. **JSON Source Code view** provides a textarea where administrators can directly edit the full policy JSON payload — best for bulk editing or copy-pasting policy configurations. The toggle is within the same dialog; switching between views does not lose changes.
- **Free-Text Selector Input**: Resource type and action selector components accept both dropdown selection and free-text keyboard entry. Administrators can type partial submodule names (autocomplete), full `module::submodule` identifiers, or wildcard patterns (`agent::*`, `agent::mana*`, `*::*`, `*` for actions) directly into the selector. Dropdown options remain available for guided selection; free-text input is an additional input path within the same component.
- **Inline JSON Validation**: In the JSON Source Code view, a **Validate** button performs an immediate parse check on the current textarea content. Valid JSON shows a success indicator; invalid JSON surfaces the parse error message and line reference in-place so the administrator can fix syntax errors before attempting to save. This prevents loss of work due to undetected syntax errors at save time.

## Navigation (Sidebar)

The Parthenon Web UI sidebar is organized into **three intent-aligned groups** plus a standalone **Dashboard** entry:

- **Agents group** (12 items): Agent Roles, Agent Identities, Agent Types, Agent Executions, Runtime Control, Agent Trails (Conversation History, Agent Executions, Results on tabs), Skills, SOPs, Model Configs, Schedules
- **Integrations group** (3 items): Notification Integration (Channels, Recipient Groups, Delivery Logs on tabs), MCP Hub
- **System group** (3 items): Observability, Permissions, System Config

The sidebar provides a consistent width on desktop. Items use readable font sizing with distinctive styling for sub-items. The active state uses a subtle background with an accent colour and rounded corners. The Integrations group is locked open. Group labels are visually distinct (smaller, secondary colour).

Sidebar navigation items are gated by user permissions — items the user cannot access are hidden, but their group remains visible if at least one child is permitted.

## Resource Type Namespacing

All permission resource types follow the `module::submodule` naming convention, using `::` as the delimiter. This scheme creates a direct, intuitive mapping between the sidebar menu and the permission identifiers used in policy statements. There are three modules — `agent`, `integration`, and `system` — matching the three sidebar groups.

### Resource Type to Sidebar Mapping

**Agents Module** (`agent::*`):

| Resource Type Identifier | Sidebar Menu Item | Notes |
|---|---|---|
| `agent::roles` | Agent Roles | Manage agent roles with SOP/Skill permissions |
| `agent::identities` | Agent Identities | Manage agent identities and API key bindings |
| `agent::management` | Agent Types / Agent Management | Manage agent type definitions |
| `agent::runtime_control` | Runtime Control | Monitor and control running agent instances |
| `agent::skills` | Skills | Manage reusable skill definitions |
| `agent::sops` | SOPs | Manage standard operating procedures |
| `agent::model_configs` | Model Configs | Manage model configuration entries |
| `agent::schedules` | Schedules | Manage scheduled agent runs |
| `agent::trails` | Agent Trails | View conversation history, execution logs, and results |
| `agent::human_intervention` | Human Intervention | Review and respond to intervention requests |
| `agent::data_types` | Data Types | Manage typed data schemas for agent outputs |
| `agent::outputs` | Agent Outputs | View and search typed agent outputs |

**Integrations Module** (`integration::*`):

| Resource Type Identifier | Sidebar Menu Item | Notes |
|---|---|---|
| `integration::mcp_hub` | MCP Hub | Manage MCP server connections |
| `integration::notifications` | Notifications | Manage notification channels and delivery |

**System Module** (`system::*`):

| Resource Type Identifier | Sidebar Menu Item | Notes |
|---|---|---|
| `system::observability` | Observability | View platform telemetry and logs |
| `system::permissions` | Permissions | Manage user roles, policies, groups, tags, and access requests |
| `system::system_config` | System Config | Manage platform-wide configuration and identity providers |

### Consolidated Submodules

Several previously separate resource type identifiers have been consolidated into unified submodules that match combined pages:

- **`agent::trails`** replaces the former `conversation` and `result` identifiers. Since the Agent Trails page already presents conversation history, execution logs, and results as tabs on a single page, a single permission now governs access to the entire page.
- **`system::permissions`** replaces the former `permissions`, `group`, `user`, `tag`, and `access_request` identifiers. Since the Permissions page is a unified workspace for all IAM concepts, a single permission now governs access to the full Permissions area.

### Wildcard Semantics

Administrators can use wildcards to grant permissions at module granularity without enumerating every submodule:

| Wildcard | Matches | Description |
|---|---|---|
| `agent::*` | All 12 agent submodules | Grants access to the entire Agents group |
| `integration::*` | All 2 integration submodules | Grants access to the entire Integrations group |
| `system::*` | All 3 system submodules | Grants access to the entire System group |
| `*::*` | Every resource type in the manifest | Equivalent to full platform access; used by the system administrator role |

**Prefix wildcards** are supported through free-text entry in resource type selectors. An administrator can type `agent::mana*` to match any submodule whose name starts with "mana" (e.g., `agent::management`). Prefix wildcards are not visible in dropdowns and have no dedicated UI affordance — they are typed directly into the selector.

**Action wildcards**: The `*` wildcard can be used in the action field of a policy statement to grant all available actions on the specified resource type.

Wildcards cannot be combined with explicit submodules in the same policy resource definition. A policy either uses a wildcard to cover a range, or lists specific submodules — not both.

### Dashboard Permission Exemption

The Dashboard page (`/dashboard`) remains accessible without any specific permission check. It is not associated with any resource type and is not governed by policy statements. All authenticated users can view the dashboard, consistent with the platform's role as an operational landing page.

## Policy Editor UX

Role policy editing uses a dedicated dialog that provides a focused workspace for authoring, reviewing, and modifying the complete policy set for a role.

### Dialog-Based Editing

When an administrator opens the policy editor for a role, a dialog displays all current policy statements for that role. Administrators can add new statements, edit existing ones, or remove statements — all within the same dialog. This replaces the previous inline row-expansion pattern and gives administrators a single view of the role's entire permission set.

On saving, all changes (additions, modifications, and deletions) are committed as a single batch operation. The dialog then closes, and the parent policy table refreshes automatically to reflect the updated policy set — no manual page reload is required.

### Form / JSON Toggle

The policy editor dialog provides a toggle between two editing views:

- **Form View**: A structured interface with dropdown selectors for resource types (grouped by module) and action chips for selecting allowed operations. This view is designed for guided, error-resistant policy authoring.

- **JSON Source Code View**: A textarea where the full policy JSON is displayed for direct editing. This view is designed for administrators who prefer to copy-paste configurations, make bulk edits, or work with policy definitions as structured text.

Switching between views preserves changes made in either view. Administrators can start in Form view, switch to JSON to review the structure, and switch back to Form to make further adjustments — all within the same editing session.

### Free-Text Wildcard Input

Resource type and action selectors support free-text keyboard entry in addition to dropdown selection. Administrators can type directly into the selector to enter:

- **Partial submodule names** — e.g., typing `mana` filters to `agent::management`
- **Full namespaced identifiers** — e.g., typing `agent::roles`
- **Module-level wildcards** — e.g., typing `agent::*`
- **Prefix wildcards** — e.g., typing `agent::mana*`
- **Universal wildcards** — e.g., typing `*::*`
- **Action wildcards** — e.g., typing `*` to grant all actions

Dropdown options remain available for guided selection. Free-text input is an additional entry method within the same component, enabling rapid wildcard authoring without navigating long dropdown menus.

### Inline JSON Validation

In the JSON Source Code view, a **Validate** button performs a client-side parse check on the current textarea content:

- **Valid JSON** is confirmed with a success indicator, giving the administrator confidence before saving.
- **Invalid JSON** surfaces the parse error message and line reference in-place, directly below the textarea, so the administrator can locate and fix the syntax error without leaving the dialog.

The validation is instantaneous and read-only — it does not save, modify, or otherwise affect the policy data. It exists purely to catch syntax errors early and prevent loss of work.

## Acceptance Criteria
- Users and agents authenticate via OIDC and are assigned correct roles
- Permissions are enforced for all actions in the Web UI
- Setup wizard guides through initial configuration and identity provider setup
- Admins can manage roles, permissions, user tags, user groups, and user policies from the UI
- User tags can be created, updated, and deleted by admins
- Admins can author user policies with conditions based on user tags
- Admins can create user groups, assign group owners, and bind groups to IdP claims for automatic assignment
- All users who have authenticated are visible in a user list with their roles and group memberships
- Admins can assign or remove direct user roles and group memberships for any user
- Users not auto-assigned to groups can request access to available user groups, providing justification
- User group owners can approve or reject membership requests, and users are notified of outcomes
- Users can track the status of their group requests (pending, approved, rejected) from their dashboard
- All access and permission changes, group requests, and approvals are auditable
- All resource type identifiers follow the `module::submodule` format and match sidebar menu items
- The Dashboard page remains accessible to all authenticated users without a specific permission check
- Policy editor opens in a dedicated dialog showing all policies for the role, with a toggle between Form and JSON Source Code views
- Resource type and action selectors accept free-text entry including wildcards (`agent::*`, `agent::mana*`, `*::*`, `*`)
- JSON Source Code view provides a Validate button that checks parseability and reports syntax errors in-place
- Policy changes from both Form and JSON views are saved as a single batch when the administrator clicks Save
- Module-level wildcards (`agent::*`, `integration::*`, `system::*`, `*::*`) correctly grant access to all submodules within their scope
- Invalid or unknown resource type identifiers are rejected with a clear error message indicating the required format
