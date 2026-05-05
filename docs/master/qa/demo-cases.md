# Master Demo Cases
<!-- Whole-product curated demo — one representative scenario per feature -->
<!-- Use with: /demo-app --cases docs/master/qa/demo-cases.md -->
<!-- Updated automatically by /change:update-master — do not edit grep patterns manually -->

## Grep Patterns
<!-- Playwright --grep filter: one pattern per line, joined with | at runtime -->
<!-- Format: <Describe suite name> > <test name> -->
- Authentication > unauthenticated request to protected route redirects to login
- Dashboard > dashboard renders app shell layout with header
- Agent Management > displays list of agent types from API
- Agent Management > shows create agent type button and opens dialog on click
- Chat > chat page shows agent type selector or session list
- Conversation History > clicking a conversation expand button shows its turns
- Gateway Configuration > gateway page shows agent type names
- MCP Hub > MCP Hub shows server names from API
- MCP Hub > MCP Hub has a register/add server button
- MCP Session CRUD with new fields > MCP session API response includes identity_binding and credential_config
- Notification Configuration > notification page shows channel names from API
- Observability Dashboard > observability dashboard shows request rate metric
- Result Repository > result repository shows result payload text
- Schedule Manager > schedule manager shows schedule names from API
- Skills > skills page lists skill names from API
- Skills > skills page has create skill button
- Skill editor with instructions and tool binding > skills API response includes instructions field
- Skill editor with instructions and tool binding > create skill POST payload can include instructions field
- SOPs > SOPs page lists SOP names from API
- SOPs > clicking a SOP shows its steps
- SOP editor with instructions and steps > SOP steps use skill_invocation type (not legacy skill)
- SOP editor with instructions and steps > SOPs API response includes instructions field
- SOP editor with instructions and steps > create SOP POST payload can include instructions field
- Tags Management > renders tag definitions table
- Roles Management > navigates to Roles tab and shows role data
- Groups Management > groups tab shows group data
- User Access Management > users tab shows user data
- Access Request Flow > access requests tab renders
- Theme Application > Inter font is applied globally
- Component Theming > Cards have 12px border radius
- Page Consistency > Dashboard uses theme consistently
- Accessibility > Color contrast meets WCAG AA standards
- Group-Optional Access Request Flow > user with no groups sees informational alert in request dialog and can submit with justification only
- Group-Optional Access Request Flow > admin can assign a group and approve a group-less request
- Permissions Page > renders tabs for tag/role/group/user/access management
- Bug Reproduction: Role Policy Management > should allow editing role policy as JSON
- Bug Reproduction: Group View Members > View Members button for groups should open members drawer
- Schedule Manager > schedule execution history is available
- Notification Configuration > notification page shows event log with event types
- Result Repository > result repository shows tags for results
- Permission Denied: Snackbar > 403 on agent create triggers permission-denied snackbar
- Permission Denied: Request Access Flow > user can submit access request with justification and sees confirmation
- AccessDeniedPage > renders at /access-denied with lock icon and action buttons
- Group-Role Assignment > ManageGroupRoles dialog opens and shows assigned roles
- Group-Role Assignment > Admin can assign a role to a group and dialog reflects the change
- AddStatementDialog > Add Statement dialog opens with resource type dropdown
- JSONViewModal > View JSON button opens modal with formatted JSON
- CloneRoleDialog > Clone dialog pre-fills source role name with Copy prefix

## Scenario Index
| # | Feature | What it Shows | Change | Spec File |
|---|---------|---------------|--------|-----------|
| 1 | Authentication | Unauthenticated user is redirected away from protected pages | enterprise-ai-harness | auth.spec.ts |
| 2 | Dashboard | App shell loads with header and navigation sidebar | enterprise-ai-harness | dashboard.spec.ts |
| 3 | Agent Management — List | Agent types returned from API appear in the table | enterprise-ai-harness | agent-management.spec.ts |
| 4 | Agent Management — Create | Create Agent Type button opens the configuration dialog | enterprise-ai-harness | agent-management.spec.ts |
| 5 | Chat | Agent type selector is visible so user can start a conversation | enterprise-ai-harness | chat.spec.ts |
| 6 | Conversation History | Expanding a session row reveals the conversation turns | enterprise-ai-harness | conversations.spec.ts |
| 7 | Gateway | Agent names are shown with their gateway endpoint info | enterprise-ai-harness | gateway.spec.ts |
| 8 | MCP Hub | Register Server button opens the server configuration dialog | enterprise-ai-harness | mcp-hub.spec.ts |
| 9 | Notifications | Configured notification channels are listed by name | enterprise-ai-harness | notifications.spec.ts |
| 10 | Observability | Live request-rate metric value is displayed on the dashboard | enterprise-ai-harness | observability.spec.ts
| 16 | Tag Management | User views tag definitions table with environment tags | user-permission-management | permissions.spec.ts |
| 17 | Role Management | User navigates to Roles tab and views role with policy assignments | user-permission-management | permissions.spec.ts |
| 18 | Group Management | User views groups table showing groups with member and role counts | user-permission-management | permissions.spec.ts |
| 19 | User Management | User views platform users table showing users with role and group assignments | user-permission-management | permissions.spec.ts |
| 20 | Access Request Workflow | User views access requests tab showing pending group join requests | user-permission-management | permissions.spec.ts | |
| 11 | Result Repository | Stored agent results are visible with their payload text | enterprise-ai-harness | results.spec.ts |
| 12 | Scheduling | Scheduled job names appear in the schedule manager list | enterprise-ai-harness | scheduling.spec.ts |
| 13 | Skills — Create | Create Skill button opens the skill editor dialog | enterprise-ai-harness | skills-sops.spec.ts |
| 14 | SOPs — Steps | Clicking a SOP reveals its ordered step list | enterprise-ai-harness | skills-sops.spec.ts |
| 15 | Setup Wizard | Wizard shows input fields for initial platform configuration | enterprise-ai-harness | setup-wizard.spec.ts |
| 21 | Global Font | Inter font loaded and applied throughout the app | apply-material-theme | theme-application.spec.ts |
| 22 | Card Polish | 12px border radius on cards demonstrates refined Material styling | apply-material-theme | component-theming.spec.ts |
| 23 | Page Theme | Dashboard shows complete theme with indigo nav and slate background | apply-material-theme | page-consistency.spec.ts |
| 24 | Accessibility | WCAG AA color contrast proves professional, accessible polish | apply-material-theme | accessibility.spec.ts |
| 25 | Group-Optional Submission | User with no group permissions sees informational alert instead of group selector, enters justification, and submits — request created with no group assigned | group-optional-access-request | access-control.spec.ts |
| 26 | Admin Group-Assignment Approval | Admin opens approve dialog for an "Unassigned" request, selects a group from the dropdown, clicks Approve — request moves to Approved with the assigned group | group-optional-access-request | access-control.spec.ts |
| 27 | Permissions Management Tabs | All five management tabs (Tags, Roles, Groups, Users, Access Requests) visible on the /user-permissions page | implement-global-access-control | permissions.spec.ts |
| 28 | Role Policy JSON Editor | User expands a role row, clicks "Edit as JSON", and sees the full JSON policy editor textarea | implement-global-access-control | permissions.spec.ts |
| 29 | Group Members Drawer | User navigates to Groups tab, clicks "View Members" for a group, and a members drawer opens listing members | implement-global-access-control | permissions.spec.ts |
| 30 | Schedule Execution History | Execution history panel shows success/failure status for a completed schedule run | implement-global-access-control | scheduling.spec.ts |
| 31 | Notification Event Log | Event log displays delivered notification events alongside configured channels | implement-global-access-control | notifications.spec.ts |
| 32 | Result Tags | Results list shows tag chips attached to each result entry | implement-global-access-control | results.spec.ts |
| 33 | Permission Denied: Snackbar | A 403 response with `required_permission` body triggers the global snackbar with "Request Access" button, showing resource type and action context | implement-global-access-control | access-control.spec.ts |
| 34 | Permission Denied: Request Access Flow | User clicks "Request Access" in the snackbar, fills in a justification, submits, and sees confirmation — modal pre-filled with denied resource/action/ID | implement-global-access-control | access-control.spec.ts |
| 35 | Access Denied Full Page | User navigates to /access-denied and sees the full-page denial view with lock icon, "Return to Dashboard" and "Request Access" buttons | implement-global-access-control | access-control.spec.ts |
| 36 | Group-Role Assign | Admin opens Manage Roles for a group, selects a role, confirms — role appears in dialog list and groups table updates automatically without page reload | implement-global-access-control | access-control.spec.ts |
| 37 | Group-Role Remove | Admin removes a role from a group — role absent from dialog; groups table role count updates automatically; re-assigning same role succeeds | implement-global-access-control | access-control.spec.ts |
| 38 | Add Statement Dialog | Admin expands a role, opens the Add Statement dialog, and sees resource type, effect, and actions dropdowns populated from the resource-type manifest API | improve-role-policy-management | role-policy-management.spec.ts |
| 39 | JSON View | Admin clicks the View JSON icon on a role row and the JSONViewModal opens showing all policy statements as formatted read-only JSON with a Copy button | improve-role-policy-management | role-policy-management.spec.ts |
| 40 | Role Clone | Admin clicks Clone on a role row — the Clone Role dialog opens pre-filled with the source role's name (including copy indicator) ready for editing before submission | improve-role-policy-management | role-policy-management.spec.ts |
| 41 | MCP Hub — Server List | MCP Hub renders server list with server names and active/inactive status indicators | enhance-mcp-hub-skills-sops | mcp-hub.spec.ts |
| 42 | MCP Session — Identity Binding | Session data carries `identity_binding` (agent/realm) and `credential_config` (required keys); `encrypted_credentials` is never exposed | enhance-mcp-hub-skills-sops | mcp-hub.spec.ts |
| 43 | Skills — List with Names | Skills list shows all skill names loaded from the API | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 44 | Skills — `instructions` Field | Skills API schema exposes the `instructions` field (agent-facing guidance) alongside `tool_ids` for multi-tool binding | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 45 | Skills — Create with `instructions` | Skill creation POST payload accepts an `instructions` field for agent guidance | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 46 | SOPs — List with Names | SOPs list renders SOP names, descriptions, and step counts from the API | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 47 | SOP Steps — `skill_invocation` Type | SOP steps use the `skill_invocation` enum (not legacy `skill`) and expose `target_agent_type_id` and `step_config` fields | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 48 | SOPs — `instructions` Field | SOPs API schema exposes the `instructions` field for workflow-level agent guidance; field is present even when `null` | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 49 | SOPs — Create with `instructions` | SOP creation POST payload accepts an `instructions` field for workflow guidance | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
