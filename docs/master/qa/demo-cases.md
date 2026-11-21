# Master Demo Cases
<!-- Whole-product curated demo — one representative scenario per feature -->
<!-- Use with: /demo-app --cases docs/master/qa/demo-cases.md -->
<!-- Updated automatically by /change:update-master — do not edit grep patterns manually -->

> **Maintenance log:** per-change pattern additions/removals and verification
> notes live in [`docs/changes/archive/demo-cases-merge-log.md`](../../changes/archive/demo-cases-merge-log.md).

## Grep Patterns
<!-- Matches Playwright test titles and Vitest describe > it names (same format) -->
<!-- One pattern per line; joined with | at runtime for --grep / regex matching -->
- Dashboard Operational Metrics > operational metric cards are visible
- Dashboard Operational Metrics > time-sensitive metrics section is visible
- Dashboard Operational Metrics > date range picker preset buttons are visible
- Namespace Resource Types — Full CRUD Lifecycle > resource types endpoint returns the full namespaced manifest (real backend)
- Namespace Migration Visibility > dashboard remains accessible without specific permission
- Add Policy Statement > Resource IDs section appears once a resource type is set
- Edit Policy Statement > Edit button opens the card pre-filled with existing policy data
- Namespace Validation Errors > POST policy with unknown namespaced type 'agent::nonexistent' is rejected
- RolePolicyDialog E2E > roles page renders with mocked namespaced data
- RolePolicyDialog E2E > wildcard module values are accepted by the client validation and saved
- Login Page States > shows both when both enabled
- OIDC Callback Flow > callback with valid code exchanges token and lands on /dashboard
- System Config Page > system config page renders without crash
- Authentication > unauthenticated request to protected route redirects to login
- Agent Management > displays list of agent types from API
- Agent Management > shows create agent type button and opens dialog on click
- Chat > chat page shows agent type selector or session list
- Conversation History > clicking a conversation expand button shows its turns
- Conversation Delegation Visibility > shows delegating label and waiting indicator with inline delegation snippet log
- Conversation Delegation Visibility > shows timeout_or_failed terminal status in chat
- Gateway Configuration > gateway page shows agent type names
- MCP Hub > MCP Hub shows server slugs from API
- MCP Hub > MCP Hub has a register/add server button
- MCP Hub — System Entry > MCP server table shows one System entry with Built-in chip
- MCP Hub — System Entry > server with zero sessions shows sync button disabled with tooltip
- Real Backend Integration - MCP Default Session > POST /mcp/servers/{id}/sync returns 422 when no sessions exist
- MCP Session CRUD with new fields > MCP session API response includes identity_binding and credential_config
- Notification Configuration > notification page shows channel names from API
- Notification Channel Management > create channel updates list without page reload
- Recipient Group Management > create group updates list without page reload
- Notification Log Page > clicking a log row opens the detail view
- Real Backend Integration - Notifications > notification channels endpoint returns 200
- Observability Dashboard > observability dashboard shows request rate metric
- Result Repository > result repository shows result payload text
- Skills > skills page lists skill names from API
- Skills > skills page has create skill button
- Skill editor with instructions and tool binding > skills API response includes instructions field
- Skill editor with instructions and tool binding > create skill POST payload can include instructions field
- Skill workflow generation and preview (mocked API) > uses Workflow terminology and not legacy System Instruction in editor
- Skill workflow generation and preview (mocked API) > preview renders one instruction file and uses latest unsaved workflow text
- Skill workflow generation and preview (mocked API) > missing model returns user-visible error and does not fallback to generated workflow
- SOPs > SOPs page lists SOP names from API
- SOPs > clicking a SOP shows its steps
- SOP editor with instructions and steps > SOP steps use skill_invocation type (not legacy skill)
- SOP editor with instructions and steps > SOPs API response includes instructions field
- SOP editor with instructions and steps > create SOP POST payload can include instructions field
- SOP workflow generation and preview (mocked API) > uses Workflow terminology and not legacy System Instruction in editor
- SOP workflow generation and preview (mocked API) > preview renders one SOP instruction file and uses latest unsaved workflow text
- SOP workflow generation and preview (mocked API) > missing model returns user-visible error and does not fallback to generated SOP workflow
- Tags Management > renders tag definitions table
- Roles Management > navigates to Roles tab and shows role data
- Groups Management > groups tab shows group data
- User Access Management > users tab shows user data
- Access Request Flow > access requests tab renders
- Theme Application > Inter font is applied globally
- Component Theming > Cards have 12px border radius
- Accessibility > Color contrast meets WCAG AA standards
- Group-Optional Access Request Flow > user with no groups sees informational alert in request dialog and can submit with justification only
- Group-Optional Access Request Flow > admin can assign a group and approve a group-less request
- Permissions Page > renders tabs for tag/role/group/user/access management
- Bug Reproduction: Group View Members > View Members button for groups should open members drawer
- Notification Configuration > notification page shows event log with event types
- Result Repository > result repository shows tags for results
- Permission Denied: Snackbar > 403 on agent create triggers permission-denied snackbar
- Permission Denied: Request Access Flow > user can submit access request with justification and sees confirmation
- AccessDeniedPage > renders at /access-denied with lock icon and action buttons
- Group-Role Assignment > ManageGroupRoles dialog opens and shows assigned roles
- Group-Role Assignment > Admin can assign a role to a group and dialog reflects the change
- Add Policy Statement > Add Policy opens an editable card with resource type, effect and actions
- Role Policy JSON View > JSON toggle shows the policy document in a monospace editor
- CloneRoleDialog > Clone dialog pre-fills source role name with Copy prefix
- Agent Role Management > renders agent roles page with role list
- Agent Type Configuration > renders agent type with input_type chip
- Agent Session Launch > opens launch dialog when the Run Agent action is clicked
- Agent Session Status > renders completed session with result
- Agent Realm Bootstrap — Mocked > agent identities page loads when realm is initialized (mocked)
- Agent Realm Bootstrap — Mocked > realm name column displays configured agent realm
- Agent Realm Bootstrap — Real Keycloak Integration > agent realm openid-configuration is reachable after bootstrap
- Real Backend Integration — Agent Runtime Migration > GET /agents/roles returns valid response (validates DB schema)
- Model Config CRUD > renders model configs page with config list
- Model Config CRUD > renders provider type chip for openai config
- Model Config CRUD > renders provider type chip for litellm_proxy config
- Agent Instance Dashboard > shows status filter dropdown
- Conversation History Display > renders chat interface for conversational session
- Real Backend Integration — Agent Runtime Migration > GET /agents/model-configs returns valid response (validates model_configs table with enabled_models)
- Agent Role Identity Constraints > create role dialog posts name and bindings (allowed_identity_types is not exposed in the UI)
- Agent Role Identity Constraints > assigning role with incompatible identity type shows validation warning
- Agent Role Identity Constraints > assigning role with compatible identity type succeeds
- Identity-First Role Selection > role dropdown lists all roles regardless of the selected identity type
- Identity-First Role Selection > changing identity selection preserves the previously selected role
- Agent Log Viewer > Summary panel displays identity and role from system instruction
- Agent Log Viewer > Agent Working Steps section is collapsed by default
- Agent Log Viewer > Expand working steps section reveals step rows
- Agent Log Viewer > Expand individual step detail block
- Agent Log Viewer > Toggle to raw mode shows monospace raw log block
- Agent Log Viewer > Raw mode copy button is visible
- Agent Live Logs Stream > uses live stream endpoint for running non-conversation session and shows live-stream hint
- Agents nav group > nav group is expanded by default and shows child items
- Agents nav group > collapses and expands nav group on header click
- Agent Executions page > selecting agent type filter refetches sessions
- Agent Type Details Dialog > dialog Details tab shows agent metadata
- Agent Type Details Dialog > Implementation Plan tab shows plan steps when plan is populated
- Nav menu order > Agent Roles and Agent Identities appear above Agent Management in the nav
- Agent Types table columns > Role column shows resolved role name for agent type
- Agent Types table columns > Identity column shows resolved identity name for agent type
- Agent Type Details Dialog > clicking identity name in Details tab opens identity view dialog
- Agent Type Details Dialog > identity view dialog has Edit button that navigates to identities page
- Agent Type Details Dialog > clicking role name in Details tab opens role view dialog
- Agent Type Details Dialog > role view dialog is read-only; role edit form opens from the Agent Roles page
- Passthrough Sessions — Mocked > passthrough session chip displayed in session table
- Passthrough Sessions — Mocked > creating passthrough session excludes credentials from payload
- Passthrough Sessions — Mocked > passthrough session auth_type value is correct in API response
- Real Backend Integration — Passthrough Sessions > passthrough session creation with credentials is rejected by real backend — AC-1 validation
- Mocked — Certificate Authentication: Issue response excludes identity tokens > certificate issue response has cert/key but never identity tokens
- Mocked — Metadata Security: zero identity tokens in Agent Runtime boundary > authorization response: identity_token present at Communication Hub boundary (not Agent Runtime)
- Mocked — Tool Authorization Decision Outcomes > authorized=false: insufficient permissions — no token, includes reason
- Mocked — Certificate Revocation Response and Downstream Effects > after revocation: tool authorization returns unauthorized with revoked reason
- Real Backend Integration - Service Segregation Deny Paths > internal authorize endpoint is wired and rejects missing service certificate
- Real Backend Integration - Service Segregation Deny Paths > internal system-tools endpoint is wired and rejects missing service certificate
- Real Backend Integration - Service Segregation Deny Paths > revocation contract endpoint uses revoked/{serial_number} path
- Browser Boundary - Frontend Uses API/WS Boundaries Only > dashboard traffic does not attempt direct database connections
- test_hello_agent_tool_with_role_returns_greeting
- test_hello_agent_tool_without_role_returns_access_denied
- test_hello_user_tool_with_role_returns_greeting
- test_hello_user_tool_without_role_returns_access_denied
- test_tools_call_with_real_jwt_returns_agent_sub
- Human Intervene > submitting approval response sends API call
- Real Backend Integration - Conversational Agent Intervention > GET /api/v1/intervene/requests returns data
- agent-save-data-get-tools > agent context does not expose save_result
- agent-save-data-get-tools > save_data stores multiple records per session
- agent-save-data-get-tools > get_data requires at least one filter
- agent-save-data-get-tools > get_output returns output history by date range
- GitHub Pages showcase page > renders core sections and switches walkthrough tabs
- Data Types CRUD > displays list of data types from API
- Data Types CRUD > create button opens form dialog
- Data Types CRUD > delete button invokes delete guard for referenced type
- Agent Outputs Query > displays agent output records with data type names
- Agent Outputs Query > has export CSV button
- Agent Outputs Query > shows validation status badges
- Typed Execution Flow > agent management page shows output data type badge
- Typed Execution Flow > execution logs page shows typed sessions
- ContentRenderer > renders complex nested HTML
- ContentRenderer > strips script tags via DOMPurify
- ContentRenderer > handles mixed HTML and markdown-like content by following HTML path
- ContentRenderer > does not treat angle bracket comparison as HTML
- MaximizableContent > opens dialog when maximize button is clicked
- MaximizableContent > closes dialog via Escape key
- OutputTypeResultTab > extracts text from Claude content blocks for auto output type
- API Key Management - Mocked Admin CRUD > displays status chips
- API Key Management - Create Key Flow > can select identity and role then create
- API Key Management - Revoke Key Flow > revoke dialog shows key name and warning
- API Key Management - Filtering > status filter has all/active/revoked options
- Agent Runtime Monitor > presents the view as "Agent Runtime Monitor" and renders the map canvas
- Agent Runtime Monitor > auto-fits the map and groups each delegation tree into a team container
- Agent Runtime Monitor > renders a delegation connector between parent and child
- Agent Runtime Monitor > surfaces a sleeping agent awaiting intervention and opens the intervention dialog
- Agent Runtime Monitor > selects a node and opens the termination dialog from the detail bubble
- Agent Runtime Monitor > zooms in and out via the toolbar
- Agent Runtime Monitor > pans the canvas via drag
- Agent Runtime Monitor > toggles fullscreen and restores
- Agent Runtime Monitor > shows a cross-type parent/child delegation connector
- Agent Runtime Monitor > recovers from the filtered-empty state via "Reset filters"
- Agent Runtime Monitor > shows trigger provenance as a person entity wired to the execution
- Agent Runtime Monitor > renders the Communication Hub and tool-call routes to MCP servers
- Agent Runtime Monitor > renders the System Tools node and skips unknown-slug and a2a tool calls
- Agent Runtime Monitor > shows schedule creator attribution and no person line for a null-creator schedule
- Agent Management Panel — CRUD lifecycle > creates an agent from the panel and shows it in sidebar + header immediately (no reload)
- Agent Management Panel — equipment slots (inline create-and-assign) > role slot: create-new mounts the real Agent Role dialog and assigns the created role
- Agent Management Panel — live topology > topology updates immediately on draft mutations with zero network requests
- Agent Type preview — unified panel topology canvas > preview shows the unified zoned panel topology canvas with hub bar
- Agent Type preview — unified panel topology canvas > zoom controls work in the preview fullscreen (parity with panel)
- Agent Type preview — unified panel topology canvas > clicking a topology node opens the entity view dialog
- Agent Management Panel — live topology > panel topology renders every equipped node plus the Communication Hub
- Agent Management Panel — Communication Hub in existing preview topologies > Agent Types details dialog shows the unified topology canvas for a typed agent
- Agent Management Panel — permissions > 403 on the roles list disables only the role slot with a localized explanation
- Agent Management Panel — CRUD lifecycle > pending-changes tray saves the draft with exactly one agent-type PUT
- Decision Model Providers (mocked) > settings > navigation and page header show "Decision Model Providers" with no trace of "System One Providers"
- Decision Model Providers (mocked) > settings > admin creates a decision model provider and sees it appear without reload
- Decision Model Providers (mocked) > settings > admin deletes an unreferenced provider and can recreate the same name afterwards
- Decision Model Providers (mocked) > decision tools > model selector lists only enabled models and submits the availability id
- Real Backend Integration - Decision Model Providers > multi-provider CRUD, availability cascade, delete blocking, DB persistence
- System One Decision Tools (mocked) > provider config journey enables the decision tool authoring gate
- System One Decision Tools (mocked) > round-2 form journey: data types → mapping properties → placeholders → AI generate → save
- System One Decision Tools (mocked) > duplicate tool name shows a structured error and keeps the dialog open
- System One Decision Tools (mocked) > decision results API contract: persisted result keyed to the tool
- Agent Type script governance — plan surfaces (mocked) > no Scripts tab — script visibility lives on the Implementation Plan and Optimized Plan tabs
- Agent Type script governance — plan surfaces (mocked) > version lineage, verification, fallback and repair lists are retired — no registry API is called
- Agent Type script governance — plan surfaces (mocked) > Implementation Plan links a script-backed step to the Optimized Plan tab (E4a)
- Agent Type script governance — plan surfaces (mocked) > requires-fix alert surfaces in the Optimized Plan tab (auto-feedback dump retired)
- Agent Type script governance — plan surfaces (mocked) > optimized plan lifecycle: a ready plan retires into the retired state
- Agent Type script governance — plan surfaces (mocked) > script viewer shows the model-authored source and step description
- Agent Type script governance — plan surfaces (mocked) > permission-gated retire surfaces via the dialog error pattern without crashing
- Control Center Assistant (mocked) > clicking the assistant FAB opens the conversational surface
- Control Center Assistant (mocked) > Agent Types list marks system agent types and disables edit/delete
- Real Backend Integration - Control Center Assistant > OAuth token establishes a session and lists management tools
- Real Backend Integration - Control Center Assistant > unauthenticated MCP request is rejected (401)
- External MCP client parity - Control Center Assistant > tools/list filters and tools/call authorizes with parity
- Control Center Assistant entry point (AppShell) > opens ConversationDialog with the resolved system agent type id on click
- ConversationDialog — View All Sessions upgrades (FIX-120618 WI1) > toggling show-ended refetches with ended sessions included
- ConversationDialog — action bar > New Session starts a FRESH session without ending/archiving the current one
- InlineInterventionDialog expand (FIX-20261101-223511) > expanded dialog shows the full-width preview table
- ConversationDialog assistant model guidance > shows the guidance banner, Configure-model action, and disables input when unconfigured
- MCP Session re-auth state > shows a "Needs re-authentication" status for a session flagged requires_reauth
- Agent Clients - Mocked Management > lists clients with agent type and credential type
- Agent Clients - Mocked Management > shows the publishable soft warning in the create dialog
- Agent Clients - Mocked Management > creates a client and shows the credential once
- Control Center Assistant — agent-type update journey (mocked WS/API) > preview is presented, approval is sent, and the list reflects the update
- Optimize gate — blocks then enables the separate Optimize action > a completed run satisfies the gate and Optimize becomes enabled without a reload
- Optimized plan — requires-fix alert and re-optimization journey > optimize → ready plan → fallback marks requires_fix → re-optimize from the alert refreshes the tab
- Agent Plan Mode — explicit-only generation (mocked) > explicit Generate plan authors the plan and it renders without a page reload
- System Config — plan & workflow authoring model > unset authoring model: reminder is visible, and saving a model clears it
- Agent Plan Mode — explicit-only generation (mocked) > conversational agent: no plan-generation affordances, only the explanation
- Conversational optimizer — conversation journey (mocked) > typed agent: entry → scoped chat → single status indicator → plan refresh without a reload
- Conversational optimizer — conversation journey (mocked) > conversational agent: same entry, informational empty state, no work started
- Conversational optimizer — conversation journey (mocked) > in-chat ask/decide: the question pauses the turn and is answered once
- Conversational optimizer — conversation journey (mocked) > an out-of-scope request is declined in the conversation with zero writes
- Conversational optimizer — conversation journey (mocked) > a business conversation on the same agent type keeps the ordinary chat
- Live-test approval — approve runs the approved script once > review script → approve → running → executed run record → plan ready
- Live-test approval — approve runs the approved script once > deny runs nothing, keeps replay-only and does not retry
- Live-test approval — approve runs the approved script once > expiry is a distinct terminal state — nothing ran and no retry
- System Config — optimizer model (workspace-scoped) > a stale saved value stays visible, blocks Save, and can be re-selected
- Optimizer model missing — entry annotated, chat blocked, System Config path > the Optimized Plan entry explains the reason and the chat blocks on the model
- Conversational Activity State (Mocked) > chat surface renders status bubbles for the full activity lifecycle
- Conversational Activity State (Mocked) > reload hydration restores the persisted waiting status
- Resumable Paused Turn Recovery (Mocked) > pending → approve → resumed and continuing → resolved (input re-enabled)
- Resumable Paused Turn Recovery (Mocked) > pending → deny → resolved without a terminal card
- Resumable Paused Turn Recovery (Mocked) > no-longer-resumable turn renders one reason-specific terminal card
- Resumable Paused Turn Recovery (Mocked) > a stale approval on a terminal turn is never sent
- Resumable Paused Turn Recovery (Mocked) > reload hydration restores the waiting state and the terminal message

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
| 39 | JSON View | Admin toggles the JSON view in the role policy dialog and sees the policy document as formatted read-only JSON in a monospace editor | improve-role-policy-management | role-policy-management.spec.ts |
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
| 66 | Agent Log Viewer — Summary Panel | Session page shows agent identity, role, and model parsed from the system instruction | user-friendly-agent-logs | agent-logs.spec.ts |
| 67 | Agent Log Viewer — Working Steps | "Show N Working Steps" expands to reveal each LLM/tool call as a readable row | user-friendly-agent-logs | agent-logs.spec.ts |
| 68 | Agent Log Viewer — Step Detail | Expanding a tool call step reveals its structured input/output detail block | user-friendly-agent-logs | agent-logs.spec.ts |
| 69 | Agent Log Viewer — Raw Mode | Toggling "Raw Output" replaces the friendly panels with a full timestamped monospace log | user-friendly-agent-logs | agent-logs.spec.ts |
| 70 | Agent Log Viewer — Copy Raw | "Copy Raw Log" button is visible in raw mode so users can copy the full log to clipboard | user-friendly-agent-logs | agent-logs.spec.ts |
| 71 | Navigation menu structure | Sidebar "Agents" group is expanded with all 11 child links (Agent Roles, Agent Identities, Agent Types, Agent Executions, Runtime Control, Agent Logs, Skills, SOPs, Model Configs, Schedules, Results) visible alongside Integrations (5) and System (3) groups | reorg-navigation-menu | agent-navigation.spec.ts |
| 72 | Collapsible nav group toggle | User clicks "Agents" header to collapse the group, then clicks again to expand | reorg-navigation-menu | agent-navigation.spec.ts |
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
| 84 | MCP Demo App — Health Check | `GET /health` returns HTTP 200 with `{"status":"ok","slug":"demo"}` — no auth required | mcp-demo-app | (manual) |
| 85 | MCP Demo App — Hub Registration | After `start.ps1`, the `demo` server appears in MCP Hub with status `active` and the `helloWorld` tool listed under the `demo/` namespace | mcp-demo-app | (manual) |
| 86 | MCP Demo App — Agent JWT Tool Call | Agent obtains a Keycloak client-credentials JWT and POSTs a `tools/call` for `helloWorld`; response includes `"message":"Hello from MCP Demo App!"` and `agent_sub` matching the JWT `sub` claim | mcp-demo-app | (manual) |
| 87 | MCP Demo App — Auth Guard (401) | POSTing to `/mcp` with an invalid or missing Bearer token returns HTTP 401 Unauthorized | mcp-demo-app | (manual) |
| 88 | Passthrough chip in session table | User sees a "Passthrough" chip badge in the session list, confirming the auth type is displayed correctly | passthrough-sessions | passthrough-sessions.spec.ts |
| 89 | Admin creates passthrough session | Admin selects passthrough auth type, credential fields are hidden, and the submitted payload contains no credentials | passthrough-sessions | passthrough-sessions.spec.ts |
| 90 | Passthrough API contract | API response for a passthrough session carries the correct `auth_type`, `is_active`, and connection test values — no encrypted credentials in the payload | passthrough-sessions | passthrough-sessions.spec.ts |
| 91 | Real backend rejects credentials on passthrough | Live backend enforces the constraint: submitting credentials with a passthrough session returns 422, never 500 | passthrough-sessions | passthrough-sessions.spec.ts |
| 92 | Certificate Lifecycle | Admin issues a certificate and receives `certificate_pem`, `private_key_pem`, `serial_number`, and `expires_at` — confirming the cert carries no identity tokens (AC-1 one-time delivery to admin only) | agent-runtime-security-segregation | agent-security-segregation.spec.ts |
| 93 | Security Boundary (Agent Runtime vs Communication Hub) | The `authorize/tool-call` response carries `identity_token` to the Communication Hub, but the certificate validate endpoint (Agent Runtime boundary) never does — demonstrating the token never crosses into Agent Runtime | agent-runtime-security-segregation | agent-security-segregation.spec.ts |
| 94 | Authorization Flow — Permission Denial | An agent with a valid certificate but insufficient permissions receives `authorized=false`, a null identity token (no credential exposure on deny — AC-6 fail-safe), and a structured `reason` + `required_permission` for auditing | agent-runtime-security-segregation | agent-security-segregation.spec.ts |
| 95 | Certificate Revocation — Downstream Effect | After a certificate is revoked, a tool-call authorization using that serial number returns `authorized=false` with `reason: certificate_revoked` and a null identity token — proving revocation propagates immediately to tool access | agent-runtime-security-segregation | agent-security-segregation.spec.ts |
| 96 | Internal Authorize Endpoint Hardening | Real backend call confirms internal authorize endpoint is wired and rejects missing service certificate with auth-deny status (not 404/500) | service-segregation-security-audit | service-segregation-security-audit.spec.ts |
| 97 | Internal System-Tools Endpoint Hardening | Real backend call confirms internal system-tools endpoint is wired and denies unauthenticated direct invocation without service certificate | service-segregation-security-audit | service-segregation-security-audit.spec.ts |
| 98 | Revocation Contract Endpoint | Real backend call confirms revocation check path uses `revoked/{serial_number}` contract and is operationally wired | service-segregation-security-audit | service-segregation-security-audit.spec.ts |
| 99 | Frontend API/WS Boundary | Browser traffic inspection confirms dashboard flow uses API boundary and does not attempt direct database channels (`postgres`, `supabase`, `:5432`) | service-segregation-security-audit | service-segregation-security-audit.spec.ts |
| 100 | Skill Workflow Terminology Rename | Skill editor uses Workflow terminology and removes legacy System Instruction wording | ai-assisted-workflow-authoring-for-sop-and-skill | skills-workflow-generation-preview.spec.ts |
| 101 | Skill Workflow Preview Freshness | Skill workflow preview renders single instruction file using latest unsaved workflow and description | ai-assisted-workflow-authoring-for-sop-and-skill | skills-workflow-generation-preview.spec.ts |
| 102 | Skill Missing-Model Guardrail | Skill generation shows user-visible not-configured error and preserves manual workflow text without fallback | ai-assisted-workflow-authoring-for-sop-and-skill | skills-workflow-generation-preview.spec.ts |
| 103 | SOP Workflow Terminology Rename | SOP editor uses Workflow terminology and removes legacy System Instruction wording | ai-assisted-workflow-authoring-for-sop-and-skill | sops-workflow-generation-preview.spec.ts |
| 104 | SOP Workflow Preview Freshness | SOP workflow preview renders single instruction file using latest unsaved workflow and description | ai-assisted-workflow-authoring-for-sop-and-skill | sops-workflow-generation-preview.spec.ts |
| 105 | SOP Missing-Model Guardrail | SOP generation shows user-visible not-configured error and preserves manual workflow text without fallback | ai-assisted-workflow-authoring-for-sop-and-skill | sops-workflow-generation-preview.spec.ts |
| 106 | Delegation Handoff Visibility | Conversational chat shows normalized delegation label, waiting indicator, and fold/expand snippet behavior during delegated execution | agent-delegation-visibility | conversation-delegation-visibility.spec.ts |
| 107 | Delegation Timeout/Failure Terminal State | Conversational delegated execution resolves waiting to a clear timeout/failure terminal state in the same chat surface | agent-delegation-visibility | conversation-delegation-visibility.spec.ts |
| 108 | Live Non-Conversation Progress Stream | Running non-conversation session appends execution progress from live stream endpoint without manual refresh | agent-delegation-visibility | agent-live-logs-stream.spec.ts |
| 109 | Working Steps Collapsed-by-Default Readability | Agent log viewer starts with Working Steps collapsed so users can expand details on demand | agent-delegation-visibility | agent-logs.spec.ts |
| 114 | Model guardrail hierarchy (vendor → model → guardrail) | Operator opens the runtime control panel and sees a vendor row with its enabled models and per-period guardrails, replacing the previous flat list | harden-agent-guardrails-and-runtime-control-dashboard | runtime-control-dashboard.spec.ts |
| 115 | Vendor disable cascade | Operator disables a vendor and immediately sees the cascade-source badge on every model underneath; pre-execution availability check returns `vendor_disabled` for those models | harden-agent-guardrails-and-runtime-control-dashboard | runtime-control-dashboard.spec.ts |
| 119 | Agent Type SOP/Skill Bindings — Browse | Binding list section renders below the role picker and shows all SOP/skill entries in order with type badges and order numbers | agent-type-multi-sop-binding | agent-type-bindings-mocked.spec.ts |
| 120 | Agent Type SOP/Skill Bindings — Add | User opens the add binding dialog, selects SOP or Skill type, picks an item from the role-filtered dropdown, and saves — binding appears in the list | agent-type-multi-sop-binding | agent-type-bindings-mocked.spec.ts |
| 121 | Agent Type SOP/Skill Bindings — Remove | User clicks the remove control on a binding row; the entry disappears from the list before save | agent-type-multi-sop-binding | agent-type-bindings-mocked.spec.ts |
| 122 | Agent Type SOP/Skill Bindings — Reorder | User moves a binding up/down using the arrow controls; the order updates immediately in the UI | agent-type-multi-sop-binding | agent-type-bindings-mocked.spec.ts |
| 123 | Agent Type SOP/Skill Bindings — Save Payload | User saves the agent type; the PUT payload includes `sop_bindings` and `skill_bindings` arrays matching the current UI state | agent-type-multi-sop-binding | agent-type-bindings-mocked.spec.ts |
| 124 | Agent Type SOP/Skill Bindings — Real Backend | Real backend POST returns `sop_bindings` and `skill_bindings` in the response, confirming binding persistence round-trip | agent-type-multi-sop-binding | agent-type-bindings.spec.ts |
| 119 | Sidebar nav group expand/collapse (3-group structure) | User clicks the "Agents" group header to collapse the group (hides child items), then clicks again to re-expand them — exercises the new 3-group structure (Agents: 11, Integrations: 5, System: 3) and the primary expand/collapse interaction | reorg-navigation-menu | agent-navigation.spec.ts |
| 125 | Schedule Create | User opens create dialog, fills schedule name, and saves; new schedule appears in list with `active` status | implement-schedule-feature | scheduling.spec.ts |
| 126 | Schedule Pause | User clicks pause button on an active schedule; pause API is called and schedule transitions to `paused` | implement-schedule-feature | scheduling.spec.ts |
| 127 | Schedule Resume | User clicks resume button on a paused schedule; resume API is called and schedule transitions to `active` | implement-schedule-feature | scheduling.spec.ts |
| 128 | Schedule Delete | User clicks delete button on a schedule, confirms dialog; delete API is called and schedule removed from list | implement-schedule-feature | scheduling.spec.ts |
| 129 | Schedule Edit | User clicks edit button on a schedule; dialog pre-fills with existing data; user modifies name and saves; PUT request submitted with updated data | implement-schedule-feature | scheduling.spec.ts |
| 130 | System Entry — Deduplication | Admin opens MCP Hub and sees exactly one "System" entry with a "Built-in" chip — visually distinct from user-registered servers | fix-mcp-hub-sync-and-sessions | mcp-hub.spec.ts |
| 131 | Sync Visibility — Session Gate | Admin sees sync button disabled with tooltip for servers with zero sessions, guiding them to create a session first | fix-mcp-hub-sync-and-sessions | mcp-hub.spec.ts |
| 132 | Sync — Real Backend 422 Guard | Admin creates a server via API, attempts sync without sessions, and receives HTTP 422 with "no configured sessions" detail | fix-mcp-hub-sync-and-sessions | mcp-hub.spec.ts |
| 133 | MCP Dual-Identity — helloAgent authorized | Agent with `mcp_role: demo_agent` calls helloAgent and receives greeting with agent claims (sub, realm, role) | mcp-dual-identity-tools | mcp-demo-app/tests/integration/test_agent_flow.py |
| 134 | MCP Dual-Identity — helloAgent access-denied | Agent without required `demo_agent` role gets JSON-RPC success response with `access_denied: true` (HTTP 200, not 403) | mcp-dual-identity-tools | mcp-demo-app/tests/integration/test_agent_flow.py |
| 135 | MCP Dual-Identity — helloUser authorized | User identity via `X-User-Identity` header with `mcp_role: demo_user` gets greeting with user claims — demonstrates dual-identity chain | mcp-dual-identity-tools | mcp-demo-app/tests/integration/test_agent_flow.py |
| 136 | MCP Dual-Identity — helloUser access-denied | User without required `demo_user` role gets access-denied — proves per-tool role gating works independently from agent identity | mcp-dual-identity-tools | mcp-demo-app/tests/integration/test_agent_flow.py |
| 137 | MCP Dual-Identity — helloWorld regression | Existing helloWorld tool unchanged: still surfaces agent identity, no role gating, works with real Keycloak JWT | mcp-dual-identity-tools | mcp-demo-app/tests/integration/test_agent_flow.py |
| 138 | Intervention Response with Approval Dialog | User opens intervention dialog, selects Yes, submits approval, and verifies the API call was sent — the complete user decision-making loop | add-conversational-agent-intervention | e2e/tests/intervene.spec.ts |
| 139 | Intervention API Endpoint Integration | Real-backend validation that the intervention requests data endpoint serves correctly against live services with migrations applied | add-conversational-agent-intervention | e2e/tests/conversation-intervention.spec.ts |
| 140 | Inline MCP Session Assignment — Create Role | User creates an agent role with SOPs/Skills, sees required MCP servers appear inline, assigns sessions via dropdowns, and saves — the role is fully configured with all sessions in one operation | improve-role-mcp-session-assignment | (planned) |
| 141 | Inline MCP Session Assignment — Save Blocked | User selects SOPs that require MCP servers but does not assign all sessions — the Save button is disabled with a clear inline validation message naming the missing servers | improve-role-mcp-session-assignment | (planned) |
| 142 | Inline MCP Session Assignment — Refresh & Passthrough | User clicks the refresh button on an inline dropdown to reload sessions; passthrough badge is visible on configured servers | improve-role-mcp-session-assignment | (planned) |
| 143 | System tool rename and exposure | User-visible tool context includes save_data/get_data/get_output and excludes legacy save_result | agent-save-data-get-tools | agent-save-data-get-tools.spec.ts |
| 144 | Intermediate data persistence | A single session can save multiple named records, demonstrating repeatable data capture during a run | agent-save-data-get-tools | agent-save-data-get-tools.spec.ts |
| 145 | Data query guardrail validation | Query without filters is rejected, showing protection against unbounded retrieval requests | agent-save-data-get-tools | agent-save-data-get-tools.spec.ts |
| 146 | Output history retrieval | Output history is returned for a requested date window, showing timeline-based retrieval behavior | agent-save-data-get-tools | agent-save-data-get-tools.spec.ts |
| 147 | Showcase page walkthrough | Renders architecture/security sections and exercises demo tab switching end-to-end in browser | github-pages-project-showcase | github-pages-showcase.spec.ts |
| 148 | Data Types — List | Admin navigates to Data Types page and sees all created data types with field counts and slug names | enhance-agent-output-system | data-types-crud.spec.ts |
| 149 | Data Types — Create Dialog | Admin clicks Create Data Type to open a form dialog with a field editor for adding typed fields (string, number, boolean, date, enum) | enhance-agent-output-system | data-types-crud.spec.ts |
| 150 | Data Types — Delete Guard | Admin attempts to delete a data type referenced by an agent type; deletion is blocked with reference information | enhance-agent-output-system | data-types-crud.spec.ts |
| 151 | Agent Outputs — Query Page | Admin filters agent outputs by data type; table columns dynamically update to show field-level columns from the schema | enhance-agent-output-system | agent-outputs-query.spec.ts |
| 152 | Agent Outputs — CSV Export | Admin clicks Export CSV; a streaming download is triggered with columns matching the current data type filter | enhance-agent-output-system | agent-outputs-query.spec.ts |
| 153 | Agent Outputs — Validation Status | Results table shows validation status badges (valid/validation_error) for typed outputs | enhance-agent-output-system | agent-outputs-query.spec.ts |
| 154 | Typed Execution — Data Type Badge | Agent management page shows the assigned data type name as a badge on agent type rows | enhance-agent-output-system | typed-execution-flow.spec.ts |
| 155 | Typed Execution — Logs Display | Execution logs page shows typed session entries with structured output and data type name in the Result tab | enhance-agent-output-system | typed-execution-flow.spec.ts |
| 156 | Rich HTML Rendering | Tables, headings, and nested divs render as formatted content (not raw markup); demonstrates HTML detection in agent auto-output | improve-agent-response-rendering | ContentRenderer.test.tsx |
| 157 | XSS Sanitization | `<script>` tags stripped via DOMPurify before rendering; safe HTML content preserved | improve-agent-response-rendering | ContentRenderer.test.tsx |
| 158 | HTML Detection Priority | Mixed HTML+markdown content follows HTML rendering path; markdown syntax appears as literal text, not converted | improve-agent-response-rendering | ContentRenderer.test.tsx |
| 159 | False-Positive Avoidance | Comparison operators like `x < 5` NOT misdetected as HTML; plain text passes through markdown conversion normally | improve-agent-response-rendering | ContentRenderer.test.tsx |
| 160 | Maximize to Full-View | Clicking maximize button opens MUI Dialog with same rendered content; title displayed in dialog header | improve-agent-response-rendering | MaximizableContent.test.tsx |
| 161 | Keyboard Dismiss | Escape key closes the maximize dialog and returns to inline view | improve-agent-response-rendering | MaximizableContent.test.tsx |
| 162 | Claude Content Blocks Integration | Auto output type with Claude content blocks flows through ContentRenderer for HTML detection; text extracted and rendered correctly | improve-agent-response-rendering | OutputTypeResultTab.test.tsx |
| 163 | API Key List — Status Chips | Admin views key list with active/revoked status chips — shows both key states in a single glance with colored indicators | api-key-mcp-hub | api-key-management.spec.ts |
| 164 | API Key — Create Flow | Full two-step create flow: fill in name, select identity + role from dropdowns, submit form, transition to step 2 showing the one-time key and save warning | api-key-mcp-hub | api-key-management.spec.ts |
| 165 | API Key — Revoke Flow | Revoke confirmation dialog showing key name, identity/role binding, warning message, and description — complete pre-revoke verification UI | api-key-mcp-hub | api-key-management.spec.ts |
| 166 | API Key — Status Filtering | Status filter dropdown interaction opening the select and revealing all/active/revoked filter options | api-key-mcp-hub | api-key-management.spec.ts |
| 167 | Dashboard Operational Metrics | Section heading and all 7 snapshot stat cards render with mock data | implement-dashboard-metrics | dashboard.spec.ts |
| 168 | Dashboard Time-Sensitive Metrics | Date-range-filtered metrics section with 3 time-sensitive cards | implement-dashboard-metrics | dashboard.spec.ts |
| 169 | Dashboard Date Range Presets | Last Hour, Last 24h, and Last 7d preset shortcut buttons render correctly | implement-dashboard-metrics | dashboard.spec.ts |
| 170 | Namespace Structure | Backend returns the full namespaced resource-type manifest (29 entries today, 17 at introduction) with `::` delimiters across the module groups; no legacy flat values remain | namespace-resource-types | namespace-resource-types.spec.ts |
| 171 | Namespace Migration Visibility | Dashboard page loads without 403 — proves migration didn't break core pages or add unintended permission gates | namespace-resource-types | namespace-migration-visibility.spec.ts |
| 172 | Add Policy — Resource IDs | Administrator navigates to Roles, expands a role, clicks "Add Statement", and sees the full dialog with resource type dropdown and resource ID management section | namespace-resource-types | role-policy-management.spec.ts |
| 173 | Edit Policy — Pre-fill | Administrator expands a role, clicks Edit on an existing policy, and sees the dialog pre-filled with current data (effect, module, actions, resources) | namespace-resource-types | role-policy-management.spec.ts |
| 174 | Namespace Validation | Backend rejects a properly-namespaced but unknown type (`agent::nonexistent`) — proves validation distinguishes format from validity | namespace-resource-types | namespace-validation-errors.spec.ts |
| 175 | RolePolicyDialog UI | Roles page renders with mocked namespaced resource data — the RolePolicyDialog loads correctly with the batch save endpoint, module dropdown populated from namespaced resource types API | namespace-resource-types | role-policy-dialog.spec.ts |
| 176 | FreeSolo Wildcard Input | Batch save API accepts free-text wildcard patterns (`agent::*`, `integration::*`, `*::*`) as valid module values — enables freeSolo autocomplete entry in resource type selectors | namespace-resource-types | role-policy-dialog.spec.ts |
| 177 | Login Page State | Login page adapts to show both OIDC login button and super admin credential form when both are configured | refine-oidc-integration | oidc-login-flows.spec.ts |
| 178 | OIDC Authorization Code Flow | User returns from identity provider with an auth code, token is exchanged, and dashboard loads | refine-oidc-integration | auth-required/oidc-callback.spec.ts |
| 180 | System Config Identity Management | Super admin navigates to system config page, identity provider tabs render with user/agent provider sections | refine-oidc-integration | oidc-login-flows.spec.ts |
| 181 | Consolidated `setup dev` bootstrap | Single command replaces 7+ ad-hoc scripts — provisions Keycloak realms/clients, seeds database roles/permissions/skills, bootstraps certificate authority, and seeds test agent identities in one idempotent invocation | production-ready-configuration | (manual) |
| 182 | Zero-Trust Control Center | Control Center validates the OIDC realm exists via discovery endpoint only — never calls Keycloak admin API | production-ready-configuration | (manual) |
| 183 | Env Variable Override Config | All infrastructure config resolved from environment variables — no YAML editing, no container rebuilds | production-ready-configuration | (manual) |
| 184 | Fail-Fast Startup Validation | Services detect unreachable dependencies at startup and exit with clear, actionable diagnostics | production-ready-configuration | (manual) |
| 185 | Setup Tool Full Idempotency | Operators can safely re-run `setup dev` without errors — all steps detect existing resources and report `skipped` | production-ready-configuration | (manual) |
| 186 | Page rename & map composition | The runtime view opens as "Agent Runtime Monitor" with the interactive map canvas as the primary view (no residual "topology" naming). | agent-runtime-monitor | runtime-control-dashboard.spec.ts |
| 187 | Map auto-fit & team containers | Many agents fit on screen automatically and each delegation tree groups into a labelled team container (`team-container-*`): root at depth 0, delegated children at deeper depth columns, with a count chip. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 188 | Delegation relationship | A parent agent and its delegated child render adjacent with a visible connector line. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 189 | Human-intervention alert | A sleeping agent awaiting intervention shows an alert icon; clicking it opens the human-intervention dialog for that session. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 190 | Selection & terminate | Selecting a node opens the detail bubble with a terminate action; the termination flow completes with the correct payload. | agent-runtime-monitor | runtime-control-dashboard.spec.ts |
| 191 | Zoom in/out | The toolbar zoom controls scale the map canvas up and down. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 192 | Drag-to-pan | Dragging empty canvas pans the viewport across the map. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 193 | Fullscreen toggle | Maximising expands the map to fullscreen and toggling again restores the normal layout. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 194 | Cross-type delegation | A parent agent and its delegated child of a different type remain adjacent and joined by a visible connector line. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 195 | Filter reset recovery | Hiding every agent-kind node empties the map; the "Reset filters" control restores the population without a page reload. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 196 | Trigger provenance | Person/schedule entities appear in the leftmost column, wired by trigger lines to the executions they triggered. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 197 | Communication Hub & MCP routes | The Communication Hub renders as a full-height vertical bar and tool-call routes run orthogonally to MCP server nodes (per tool slug) with tool chips; selecting an agent highlights its route and involved MCP/tools. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 198 | System Tools & excluded calls | System-slug tool calls collapse into the single synthetic "System Tools" node with its tool chip; unknown-slug calls (NULL route_type degrade rows) render no MCP node or chip, and a2a rows (delegations) are excluded outright. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 199 | Creator attribution & trigger cards | Schedule entities render in the trigger column wired to their executions. The schedule card with a known creator shows the creator caption ("by Alice Operator"); a legacy null-creator schedule shows no creator caption, and its execution degrades the "Triggered by" line to "Unknown" — the schedule name never appears as a person. | agent-runtime-monitor | agent-runtime-monitor.spec.ts |
| 200 | Agent CRUD lifecycle | Admin fills the Create Agent dialog (name, role, SOP binding); the saved agent appears in the sidebar and header immediately with the agent count updated and no page reload | agent-management-panel | agent-management-panel.spec.ts |
| 201 | Inline create-and-assign (role slot) | "Create new" in the role slot mounts the real Agent Role dialog (same title/fields as the source module); the persisted role lands on the draft instantly without leaving the panel | agent-management-panel | agent-management-panel-slots.spec.ts |
| 202 | Live topology without saving | Unassigning and re-assigning the role re-renders the topology canvas instantly, proving zero network requests are fired until save | agent-management-panel | agent-management-panel-topology.spec.ts |
| 203 | Communication Hub in existing preview topologies | The Agent Types details dialog shows the unified topology canvas for a typed agent — the same zoned panel canvas as the management panel, including the Communication Hub bar (the old plan-topology "platform messaging" edge branch is removed) | agent-management-panel, unify-agent-topology-diagram | agent-management-panel-topology.spec.ts |
| 204 | Permission degradation (403 slot disable) | A 403 on the roles list disables only the role slot with a localized explanation while every other slot keeps working and no error alert appears | agent-management-panel | agent-management-panel-permissions.spec.ts |
| 205 | Unsaved-changes tray / single-PUT save | Assigning a model dirties the draft with zero write calls and the tray lists the pending change; Save Changes issues exactly one agent-type PUT and flips the tray to saved | agent-management-panel | agent-management-panel.spec.ts |
| 211 | Unified topology in agent preview | Opening an agent preview renders the same zoned panel canvas as the management panel — hub bar, zones, placeholders — instead of the old conversation topology | unify-agent-topology-diagram | agent-type-preview-topology.spec.ts |
| 212 | Zoom in/out in preview | User zooms in/out within the preview fullscreen with the same limits and behavior as the management panel | unify-agent-topology-diagram | agent-type-preview-topology.spec.ts |
| 213 | Node interaction in preview | Clicking a topology node opens the matching entity view dialog — a real user interaction on the unified canvas | unify-agent-topology-diagram | agent-type-preview-topology.spec.ts |
| 214 | Panel topology unchanged | Regression: panel still renders every equipped node plus the Communication Hub exactly as before the change | unify-agent-topology-diagram | agent-management-panel-topology.spec.ts |
| 206 | Decision Providers — Terminology | Settings nav, page header, and rendered UI use "Decision Model Providers" with zero occurrences of the legacy "System One Providers" string | decision-model-providers | system-one-decision-tools.spec.ts |
| 207 | Decision Providers — Create | Admin fills the create dialog (vendor, display name, endpoint, credential) and the new provider row appears in the table immediately without a page reload, with correct vendor chip and credentials-set indicator | decision-model-providers | system-one-decision-tools.spec.ts |
| 208 | Decision Providers — Delete & Recreate | Admin deletes an unreferenced provider and can recreate one with the same display name/vendor afterwards — proves true deletion, not soft-hide | decision-model-providers | system-one-decision-tools.spec.ts |
| 209 | Decision Tools — Model Selection | Decision tool authoring form lists only enabled models across providers and submits the availability id as the selection | decision-model-providers | system-one-decision-tools.spec.ts |
| 210 | Decision Providers — Real Backend | Live backend (no mocks): multi-provider CRUD, availability cascade, referenced-provider delete blocking, and DB persistence against the actual API + PostgreSQL — validates migration applied | decision-model-providers | decision-model-providers-real-backend.spec.ts |
| 211 | System One Provider Config | Admin saves the TypeSafe API key via the dialog (preset read-only base URL); the decision-tool authoring gate opens once a model is configured | system-one-decision-skills | system-one-decision-tools.spec.ts |
| 212 | Decision Tool Authoring (Data Types + AI) | Guided form: select input/output Agent Data Types (with View dialogs) → state mapping properties auto-populate → auto-detect placeholders → Generate-with-AI fills questions → save as `decision____<name>` | system-one-decision-skills | system-one-decision-tools.spec.ts |
| 213 | Tenant-Contained Naming | Defining a second tool with the same name in one tenant shows a structured conflict error and keeps the dialog open (names unique per tenant, reusable across tenants) | system-one-decision-skills | system-one-decision-tools.spec.ts |
| 214 | Decision Results | Execution result is keyed to the decision tool with typed answers, probabilities, confidence, and gate outcome | system-one-decision-skills | system-one-decision-tools.spec.ts |
| 215 | Plan-surface script visibility | Agent-owned scripts are reachable from the Agent Type detail dialog's plan surface — there is no Scripts tab; the Optimized Plan tab shows its absent/ready state | software-3.0-agent-framework | agent-type-scripts-tab.spec.ts |
| 216 | Registry UI retired | Version lineage, verifications, fallbacks and repairs lists are retired from the UI; no registry API is called by the plan surfaces | software-3.0-agent-framework | agent-type-scripts-tab.spec.ts |
| 217 | Requires-fix alert | Requires-fix alert surfaces in the Optimized Plan tab with the re-optimize action (the auto-feedback dump is retired) | software-3.0-agent-framework | agent-type-scripts-tab.spec.ts |
| 218 | Plan-step script link | The Implementation Plan links the script-backed step to the Optimized Plan tab | software-3.0-agent-framework | agent-type-scripts-tab.spec.ts |
| 219 | Optimized-plan retire | A ready optimized plan retires into the retired state and the retire action disables | software-3.0-agent-framework | agent-type-scripts-tab.spec.ts |
| 220 | Script viewer | The script viewer shows the model-authored source and the step description for the scripted step | software-3.0-agent-framework | agent-type-scripts-tab.spec.ts |
| 221 | Permission gating | A permission-denied retire surfaces the dialog error pattern without crashing | software-3.0-agent-framework | agent-type-scripts-tab.spec.ts |
| 222 | Token expiry — dashboard alerts & remediation | Warnings disappear after remediation (refetch returns healthy) | token-expiry-alerting | e2e/tests/token-expiry-dashboard-remediation.spec.ts |
| 223 | Token expiry — execution preflight | Expired token (including a subagent) BLOCKS execution with a named identity | token-expiry-alerting | e2e/tests/token-expiry-execution-preflight.spec.ts |
| 224 | Token expiry — execution preflight | Expiring token (≤7 days) WARNS but execution PROCEEDS | token-expiry-alerting | e2e/tests/token-expiry-execution-preflight.spec.ts |
| 225 | Token expiry — topology badges | Expired identity renders an error badge on its container | token-expiry-alerting | e2e/tests/token-expiry-topology-badges.spec.ts |
| 226 | Assistant entry point | The seeded system assistant agent type resolves to a launcher; clicking it opens the reused conversational surface (change's demo case 1) | control-center-chatbot | e2e/tests/control-center-chatbot.spec.ts |
| 227 | `is_system` protection | System agent types show the System badge with Edit/Delete disabled, so the seeded assistant cannot be modified or removed from the UI (demo case 2) | control-center-chatbot | e2e/tests/control-center-chatbot.spec.ts |
| 228 | OAuth-gated management catalog | A real user OAuth JWT establishes a `/mcp` session and receives the permission-filtered management catalog — no mocks, live CC resolve (demo case 3) | control-center-chatbot | e2e/tests/control-center-chatbot.real-backend.spec.ts |
| 229 | External MCP client parity | An external MCP client with the user's OAuth credentials gets the same filtered `tools/list` (no delete tools) and user-attributed `tools/call` (demo case 4) | control-center-chatbot | e2e/tests/control-center-chatbot-mcp.spec.ts |
| 230 | Fail-closed MCP auth | Unauthenticated `/mcp` requests return 401 with no catalog or session; complemented in-flow by in-band `deletion_not_supported` / `out_of_scope` declines (demo case 5) | control-center-chatbot | e2e/tests/control-center-chatbot.real-backend.spec.ts |
| 231 | Assistant launch click-through | Clicking the resolved assistant launcher opens `ConversationDialog` bound to the system agent type id (Vitest counterpart to case 226) | control-center-chatbot | frontend/src/__tests__/ControlCenterAssistantEntry.test.tsx |
| 232 | View All Sessions — ended toggle | Sessions list defaults to active-only over the last 7 days; toggling "show ended" refetches with closed/archived sessions and marks them non-resumable | control-center-chatbot | frontend/src/__tests__/ConversationDialog.sessionsView.test.tsx |
| 233 | New Session semantics | "New Session" starts a fresh conversation without ending or archiving the current one (Exit keeps resume semantics; End sets force-new) | control-center-chatbot | frontend/src/__tests__/ConversationDialog.actionBar.test.tsx |
| 234 | Expandable approval preview | The confirmation card expands into a full-width field/value preview table, and approve/deny from the expanded view run the same write path | control-center-chatbot | frontend/src/__tests__/InlineInterventionDialog.expand.test.tsx |
| 235 | Model-unconfigured guidance | With no assistant model selected the chat shows a Configure-model banner and disables input; a configured model removes the banner | control-center-chatbot | frontend/src/__tests__/AssistantModelConfigGuidance.test.tsx |
| 236 | MCP session re-auth state | A session whose OAuth refresh failed unrecoverably shows a "Needs re-authentication" status with the stored reason instead of silently deactivating | sandboxed-scripting-follow-ups | e2e/tests/mcp-hub.spec.ts |
| 237 | Script retire (Optimized Plan lifecycle) | Operator retires the ready optimized plan; it moves to the retired state and the retire action renders the "nothing to retire" state | sandboxed-scripting-follow-ups | e2e/tests/agent-type-scripts-tab.spec.ts |
| 238 | Agent Clients — Client List | A tenant's clients listed with their bound agent type and credential type (secret vs publishable) | third-party-agent-integration | e2e/tests/agent-clients.spec.ts |
| 239 | Agent Clients — Publishable Soft Warning | Creating a publishable client surfaces the "exposes this agent type publicly" warning in the create dialog | third-party-agent-integration | e2e/tests/agent-clients.spec.ts |
| 240 | Agent Clients — Create + Credential Once | Creating a client and displaying the clear-text credential exactly once | third-party-agent-integration | e2e/tests/agent-clients.spec.ts |
| 241 | Assistant agent-type update (confirm-before-write) | Administrator sees the canonical old→new preview in the conversation, approves it from the intervention inbox, and the Agent Types list immediately reflects the updated role/input/output configuration | cc-assistant-management-tool-coverage | e2e/tests/control-center-chatbot-agent-type-update.spec.ts |
| 242 | Separate, gated Optimize action | Run and Optimize are distinct actions; Optimize unlocks on its own the moment a normal run completes, then launches a dedicated optimization run | separate-optimization-from-execution | e2e/tests/agent-optimize-gate.spec.ts |
| 243 | Self-healing optimized plan (requires-fix → re-optimize) | A later failed execution flags the plan "requires a fix" with auto-recorded feedback, and Re-optimize from the alert refreshes the tab to the fixed plan without a reload | separate-optimization-from-execution | e2e/tests/agent-optimize-requires-fix.spec.ts |
| 244 | Explicit-only implementation-plan generation | Opening Agent Preview authors nothing; Generate plan sends exactly one authoring request and renders the plan in place | separate-optimization-from-execution | e2e/tests/agent-plan-mode.spec.ts |
| 245 | System Config — plan & workflow authoring model | An unset authoring model shows a reminder that blocks generation, and one save of an enabled model clears it | separate-optimization-from-execution | e2e/tests/agent-plan-generation.spec.ts |
| 246 | Conversational-agent exclusion | A conversational agent exposes no Optimize action and no plan-generation affordance — only the explanation | separate-optimization-from-execution | e2e/tests/agent-plan-mode.spec.ts |
| 247 | Conversational optimization — typed agent journey | Talk-to-optimizer entry opens a scoped chat with one processing indicator; the finished turn refreshes the plan in place without a reload | optimizer-conversational-agent | e2e/tests/agent-optimizer-conversation.spec.ts |
| 248 | Conversational agent — informational empty state | The same entry on a conversational agent explains a missing plan and starts no session, plan generation or live request | optimizer-conversational-agent | e2e/tests/agent-optimizer-conversation.spec.ts |
| 249 | In-chat ask/decide | The optimizer asks a choice question inline, the composer blocks, and exactly one answer frame resolves the turn | optimizer-conversational-agent | e2e/tests/agent-optimizer-conversation.spec.ts |
| 250 | Scope containment — out-of-scope refusal | A prompt-injected request to read another agent's scripts and delete its plan is declined in-channel with zero writes | optimizer-conversational-agent | e2e/tests/agent-optimizer-conversation.spec.ts |
| 251 | Mode containment — business conversation unaffected | A normal business chat on the same agent type keeps the ordinary composer and creates no optimization session | optimizer-conversational-agent | e2e/tests/agent-optimizer-conversation.spec.ts |
| 252 | Live-test approval — approve runs the saved script once | Review card names the script + tool-call preview; approve moves pending → running → executed run record and the refinement lands a ready plan | optimizer-conversational-agent | e2e/tests/agent-optimizer-live-test-approval.spec.ts |
| 253 | Live-test approval — deny | Deny runs nothing, collapses to a read-only denied summary, keeps replay-only and does not retry | optimizer-conversational-agent | e2e/tests/agent-optimizer-live-test-approval.spec.ts |
| 254 | Live-test approval — expiry | An unanswered request closes as a distinct `expired` terminal state; nothing ran and no retry is scheduled | optimizer-conversational-agent | e2e/tests/agent-optimizer-live-test-approval.spec.ts |
| 255 | Optimizer model — stale saved value | System Config keeps a no-longer-available saved model visible, blocks Save, and one PUT persists the re-selection | optimizer-conversational-agent | e2e/tests/agent-optimizer-model-config.spec.ts |
| 256 | Optimizer model unavailable — fail-closed entry | The Optimized Plan entry explains the shared reason, the chat blocks on the model, and the shortcut lands on System Config | optimizer-conversational-agent | e2e/tests/agent-optimizer-model-config.spec.ts |
| 257 | Live activity status | The processing bubble tracks using-tool → waiting-for-input → finished with no blank gap and no stuck spinner | persistent-agent-activity-state | e2e/tests/conversation-activity-state.spec.ts |
| 258 | Resume / reconnect hydration of activity | Reloading mid-turn restores the persisted "waiting for your input" status instead of an empty window | persistent-agent-activity-state | e2e/tests/conversation-activity-state.spec.ts |
| 259 | Paused turn — approve after a pause | Approve resumes the durable turn, keeps working through a real tool call, and resolves with input re-enabled and no misleading timeout text | resumable-agent-turn-persistence | e2e/tests/conversation-resume-recovery.spec.ts |
| 260 | Paused turn — deny after a pause | The rejection is sent once, the turn resolves cleanly, and no terminal card is shown | resumable-agent-turn-persistence | e2e/tests/conversation-resume-recovery.spec.ts |
| 261 | Paused turn — clear terminal outcome | A no-longer-resumable turn renders one reason-specific terminal card with what happened, what was not written, a next step and dismiss | resumable-agent-turn-persistence | e2e/tests/conversation-resume-recovery.spec.ts |
| 262 | Paused turn — exactly-once guard on stale approval | A confirmation that expires while the dialog is open is replaced by the "pause point could not be restored" card; a late click sends nothing | resumable-agent-turn-persistence | e2e/tests/conversation-resume-recovery.spec.ts |
| 263 | Paused turn — reload hydration | After a full reload the chat rehydrates the waiting state and preserves the terminal reason so reconnect matches the live push | resumable-agent-turn-persistence | e2e/tests/conversation-resume-recovery.spec.ts |
