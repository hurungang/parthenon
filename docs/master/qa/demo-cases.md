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
- Agent Role Management > renders agent roles page with role list
- Agent Identity Management > renders agent identities page with identity list
- Agent Identity Management > renders realm_name column values
- Agent Identity Management > OAuth sign-in button appears in create dialog
- Agent Type Configuration > renders agent type with input_type chip
- Agent Session Launch > opens launch dialog when launch button is clicked
- Agent Session Status > renders completed session with result
- Agent Realm Bootstrap — Mocked > agent identities page loads when realm is initialized (mocked)
- Agent Realm Bootstrap — Mocked > realm name column displays configured agent realm
- Agent Realm Bootstrap — Real Keycloak Integration > agent realm openid-configuration is reachable after bootstrap
- Real Backend Integration — Agent Runtime Migration > GET /agents/roles returns valid response (validates DB schema)
- Model Config CRUD > renders model configs page with config list
- Agent Instance Dashboard > shows status filter dropdown
- Conversation History Display > renders chat interface for conversational session
- Real Backend Integration — Agent Runtime Migration > GET /agents/model-configs returns valid response (validates model_configs table with enabled_models)
- Agent Role Identity Constraints > create role with identity type constraint — allowed_identity_types persisted
- Agent Role Identity Constraints > assigning role with incompatible identity type shows validation error
- Agent Role Identity Constraints > assigning role with compatible identity type succeeds
- Identity-First Role Selection > selecting identity filters role dropdown to compatible roles only
- Identity-First Role Selection > changing identity selection clears previously selected role
- Agent Plan Mode — Mocked > Create agent type with plan: modal opens with steps and diagram after save
- Agent Plan Mode — Mocked > Dismiss plan modal: modal closes and agent type row appears in table
- Agent Plan Mode — Mocked > Update agent type: PlanPreviewModal opens with updated plan on save
- Agent Plan Mode — Mocked > Failed plan: modal opens with error message when generation_status is failed
- Real Backend Integration — Agent Plan Mode > POST /api/v1/agents/types returns plan field in response
- Agent Log Viewer > Summary panel displays identity and role from system instruction
- Agent Log Viewer > Expand working steps section reveals step rows
- Agent Log Viewer > Expand individual step detail block
- Agent Log Viewer > Toggle to raw mode shows monospace raw log block
- Agent Log Viewer > Raw mode copy button is visible
- AI Agent nav group > nav group is expanded by default and shows child items
- AI Agent nav group > collapses and expands nav group on header click
- Agent Executions page > selecting agent type filter refetches sessions
- Agent Type Details Dialog > dialog Details tab shows agent metadata
- Agent Type Details Dialog > Plan Preview tab shows plan steps when plan is populated
- Agent Type Details Dialog > "View All Executions" button opens executions dialog
- Nav menu order > Agent Roles and Agent Identities appear above Agent Types in the nav
- Agent Types table columns > Role column shows resolved role name for agent type
- Agent Types table columns > Identity column shows resolved identity name for agent type
- Agent Type Details Dialog > clicking identity name in Details tab opens identity view dialog
- Agent Type Details Dialog > identity view dialog has Edit button that navigates to identities page
- Agent Type Details Dialog > clicking role name in Details tab opens role view dialog
- Agent Type Details Dialog > role view dialog has Edit button that opens role edit form

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
| 41 | Agent Role Management | User views list of agent roles with SOP count and Skill count chips | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 42 | Agent Identity — List | User views agent identities with realm_name and status chips (active/suspended/deprovisioned) | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 43 | Agent Identity — Realm Name | Identity list shows the agent realm name (ai_agents by default), confirming agents live in a separate realm from users | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 44 | Agent Identity — OAuth Sign-In | Create dialog exposes OAuth sign-in button so admin can authorize the agent user in the IdP and store tokens | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 45 | Agent Type — New Schema | Agent type rows show input_type chip (none/typed/conversation), confirming the rearchitected schema | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 46 | Agent Session Launch | User clicks Launch on an agent type row to open the launch dialog with an input form | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 47 | Agent Session Result | Completed session page shows session ID, status chip, and output data from agent execution | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 48 | Agent Realm Bootstrap — Initialized | Identities page loads after the ai_agents realm has been bootstrapped in the identity provider (mocked) | implement-agent-runtime-with-gateway | agent-bootstrap.spec.ts |
| 49 | Agent Realm Bootstrap — Configurable Realm | Realm name column shows the bootstrap-configured realm name (not hardcoded), proving realm is driven by config | implement-agent-runtime-with-gateway | agent-bootstrap.spec.ts |
| 50 | Agent Realm Bootstrap — Real Keycloak | After bootstrap, the ai_agents realm exposes its OpenID configuration on the same Keycloak instance | implement-agent-runtime-with-gateway | agent-bootstrap.spec.ts |
| 51 | Real Backend — Agent Roles DB | Calls real backend (no mocks) to verify agent_roles table exists — validates migration applied | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 52 | Model Config CRUD | Admin views model configurations showing provider type chips (openai, litellm_proxy); encrypted API key values never exposed | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 53 | Agent Instance Dashboard — Filters | Operator filters instance dashboard by status via dropdown alongside time range filters | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 54 | Conversational Instance Detail | Instance detail renders chat interface for conversational agent sessions with session metadata | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 55 | Real Backend — Model Configs DB | Calls real backend (no mocks) to verify model_configs table with enabled_models column exists — validates migration applied | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 56 | Agent Role Identity Constraint — Create | Admin creates agent role with allowed_identity_types constraint; field persisted and echoed in API response | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 57 | Agent Role Identity Constraint — Incompatible | Assigning identity whose type does not match role's allowed_identity_types returns 400; UI handles gracefully | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 58 | Agent Role Identity Constraint — Compatible | Assigning identity whose type matches role's allowed_identity_types succeeds (201) | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 59 | Identity-First Role Selection — Filter | Selecting an identity in AgentTypeForm filters the role dropdown to only compatible roles | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 60 | Identity-First Role Selection — Clear | Changing the selected identity clears the previously selected role, preventing stale incompatible assignments | implement-agent-runtime-with-gateway | agent-runtime.spec.ts |
| 41 | MCP Hub — Server List | MCP Hub renders server list with server names and active/inactive status indicators | enhance-mcp-hub-skills-sops | mcp-hub.spec.ts |
| 42 | MCP Session — Identity Binding | Session data carries `identity_binding` (agent/realm) and `credential_config` (required keys); `encrypted_credentials` is never exposed | enhance-mcp-hub-skills-sops | mcp-hub.spec.ts |
| 43 | Skills — List with Names | Skills list shows all skill names loaded from the API | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 44 | Skills — `instructions` Field | Skills API schema exposes the `instructions` field (agent-facing guidance) alongside `tool_ids` for multi-tool binding | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 45 | Skills — Create with `instructions` | Skill creation POST payload accepts an `instructions` field for agent guidance | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 46 | SOPs — List with Names | SOPs list renders SOP names, descriptions, and step counts from the API | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 47 | SOP Steps — `skill_invocation` Type | SOP steps use the `skill_invocation` enum (not legacy `skill`) and expose `target_agent_type_id` and `step_config` fields | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 48 | SOPs — `instructions` Field | SOPs API schema exposes the `instructions` field for workflow-level agent guidance; field is present even when `null` | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 49 | SOPs — Create with `instructions` | SOP creation POST payload accepts an `instructions` field for workflow guidance | enhance-mcp-hub-skills-sops | skills-sops.spec.ts |
| 61 | Agent Plan — Create + Modal | User creates an agent type, saves, and the PlanPreviewModal opens automatically showing all three generated plan steps | agent-plan-mode | agent-plan-mode.spec.ts |
| 62 | Agent Plan — Table Refresh After Dismiss | User closes the plan modal and the agent type row immediately appears in the management table without a page reload | agent-plan-mode | agent-plan-mode.spec.ts |
| 63 | Agent Plan — Edit + Regeneration | User edits an existing agent type, saves, and the PlanPreviewModal opens with an updated plan reflecting the changes | agent-plan-mode | agent-plan-mode.spec.ts |
| 64 | Agent Plan — Failed Generation State | When the LLM is unavailable the plan modal still opens but shows the generation error message instead of plan steps | agent-plan-mode | agent-plan-mode.spec.ts |
| 65 | Agent Plan — Real Backend + CASCADE | The real backend returns a `plan` field on POST and fully cascades the plan record when the agent type is deleted | agent-plan-mode | agent-plan-mode.spec.ts |
| 66 | Agent Log Viewer — Summary Panel | Session page shows agent identity, role, and model parsed from the system instruction | user-friendly-agent-logs | agent-logs.spec.ts |
| 67 | Agent Log Viewer — Working Steps | "Show N Working Steps" expands to reveal each LLM/tool call as a readable row | user-friendly-agent-logs | agent-logs.spec.ts |
| 68 | Agent Log Viewer — Step Detail | Expanding a tool call step reveals its structured input/output detail block | user-friendly-agent-logs | agent-logs.spec.ts |
| 69 | Agent Log Viewer — Raw Mode | Toggling "Raw Output" replaces the friendly panels with a full timestamped monospace log | user-friendly-agent-logs | agent-logs.spec.ts |
| 70 | Agent Log Viewer — Copy Raw | "Copy Raw Log" button is visible in raw mode so users can copy the full log to clipboard | user-friendly-agent-logs | agent-logs.spec.ts |
| 71 | Navigation menu structure | Sidebar "AI Agent" group is expanded with all child links (Agent Types, Executions, Logs, Roles, Identities) visible | unified-agent-navigation | agent-navigation.spec.ts |
| 72 | Collapsible nav group toggle | User clicks "AI Agent" header to collapse the group, then clicks again to expand | unified-agent-navigation | agent-navigation.spec.ts |
| 73 | Agent Executions filter | Selecting an agent type from the dropdown re-fetches sessions with agent_type_id in the request | unified-agent-navigation | agent-navigation.spec.ts |
| 74 | Agent Type Details Dialog — Details tab | Clicking an agent type row opens dialog showing model ID, system prompt, and other metadata | unified-agent-navigation | agent-navigation.spec.ts |
| 75 | Agent Type Details Dialog — Plan Preview tab | Switching to Plan Preview tab renders plan step names and topology | unified-agent-navigation | agent-navigation.spec.ts |
| 76 | Agent Type Details Dialog — Execution Logs tab | Switching to Execution Logs tab shows recent sessions; "View All Executions" opens the full executions dialog | unified-agent-navigation | agent-navigation.spec.ts |
| 77 | Nav menu order (Roles/Identities before Types) | Nav items ordered Roles → Identities → Types → Executions → Logs confirmed via bounding box positions | unified-agent-navigation | agent-navigation.spec.ts |
| 78 | Agent Types table — Role column | Agent Types table shows a resolved "Role" column with the role name looked up from the roles list | unified-agent-navigation | agent-navigation.spec.ts |
| 79 | Agent Types table — Identity column | Agent Types table shows a resolved "Identity" column with the identity name looked up from the identities list | unified-agent-navigation | agent-navigation.spec.ts |
| 80 | Clickable identity name in Details tab | Identity field in Details dialog renders as a clickable button; clicking opens the Agent Identity view dialog | unified-agent-navigation | agent-navigation.spec.ts |
| 81 | Edit button in identity view dialog | Agent Identity view dialog has an Edit button that navigates to /agents/identities | unified-agent-navigation | agent-navigation.spec.ts |
| 82 | Clickable role name in Details tab | Role field in Details dialog renders as a clickable button; clicking opens the Agent Role view dialog | unified-agent-navigation | agent-navigation.spec.ts |
| 83 | Edit button in role view dialog | Agent Role view dialog has an Edit button that opens the role edit form dialog | unified-agent-navigation | agent-navigation.spec.ts |
