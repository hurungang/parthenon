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
- Conversation Delegation Visibility > shows delegating label and waiting indicator with fold-expand-collapse snippet behavior
- Conversation Delegation Visibility > shows timeout_or_failed terminal status in chat
- Gateway Configuration > gateway page shows agent type names
- MCP Hub > MCP Hub shows server names from API
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
- Schedule Manager > schedule manager shows schedule names from API
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
- Model Config CRUD > renders provider type chip for openai config
- Model Config CRUD > renders provider type chip for litellm_proxy config
- Real Backend Integration - Model Configurations > GET /agents/model-configs returns all 12 provider types from the live catalogue
- Real Backend Integration - Model Configurations > POST /agents/model-configs accepts a new-provider key (gemini)
- Real Backend Integration - Model Configurations > Model Configurations page renders provider chips for a new-provider record
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
- Agent Type SOP/Skill Bindings — Mocked > binding section renders below the role picker
- Agent Type SOP/Skill Bindings — Mocked > add binding dialog opens with type selector
- Agent Type SOP/Skill Bindings — Mocked > remove binding removes entry from list
- Agent Type SOP/Skill Bindings — Mocked > reorder moves entry up and down
- Agent Type SOP/Skill Bindings — Mocked > save payload includes sop_bindings and skill_bindings
- Agent Type SOP/Skill Bindings — Real Backend > POST returns binding fields in response
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
- Agent Type Details Dialog > Plan Preview tab shows plan steps when plan is populated
- Nav menu order > Agent Roles and Agent Identities appear above Agent Types in the nav
- Agent Types table columns > Role column shows resolved role name for agent type
- Agent Types table columns > Identity column shows resolved identity name for agent type
- Agent Type Details Dialog > clicking identity name in Details tab opens identity view dialog
- Agent Type Details Dialog > identity view dialog has Edit button that navigates to identities page
- Agent Type Details Dialog > clicking role name in Details tab opens role view dialog
- Agent Type Details Dialog > role view dialog has Edit button that opens role edit form
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
- Runtime Control Dashboard > shows running sessions and opens execution details dialog
- Runtime Control Dashboard > surfaces observe-only threshold policy events in execution logs
- Runtime Control Dashboard > shows topology selection and opens termination dialog for selected node
- Runtime Control Dashboard > returns recursion_validation_failed contract for run preflight dead-loop checks
- Runtime Control Dashboard > renders vendor → model → guardrail hierarchy in the runtime control panel
- Runtime Control Dashboard > vendor disable cascades the cascade-source badge to all child models
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

## Scenario Index table
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
| 110 | Runtime visibility and execution drill-down | Operator opens Agent Executions, sees active sessions, and drills into a run from the dashboard detail flow | harden-agent-guardrails-and-runtime-control-dashboard | runtime-control-dashboard.spec.ts |
| 111 | Guardrail policy visibility | Operator reviews execution logs and sees an observe-only guardrail threshold event surfaced as a policy signal rather than a functional failure | harden-agent-guardrails-and-runtime-control-dashboard | runtime-control-dashboard.spec.ts |
| 112 | Runtime topology and termination control | Operator selects a running node from topology, opens the terminate dialog, submits a reason, and triggers a governed termination request | harden-agent-guardrails-and-runtime-control-dashboard | runtime-control-dashboard.spec.ts |
| 113 | Recursion and dead-loop prevention | Operator attempts to start a risky run and sees the request blocked before execution with a recursion validation failure contract | harden-agent-guardrails-and-runtime-control-dashboard | runtime-control-dashboard.spec.ts |
| 114 | Model guardrail hierarchy (vendor → model → guardrail) | Operator opens the runtime control panel and sees a vendor row with its enabled models and per-period guardrails, replacing the previous flat list | harden-agent-guardrails-and-runtime-control-dashboard | runtime-control-dashboard.spec.ts |
| 115 | Vendor disable cascade | Operator disables a vendor and immediately sees the cascade-source badge on every model underneath; pre-execution availability check returns `vendor_disabled` for those models | harden-agent-guardrails-and-runtime-control-dashboard | runtime-control-dashboard.spec.ts |
| 116 | Model Configurations — Expanded 12-Provider Catalogue | Admin opens the Model Configurations page to see provider chips for all 12 supported LLM vendors (including Gemini, Mistral, Cohere, Groq, Together, Fireworks, Perplexity, DeepSeek) each with a unique colour | expand-model-config-providers | agent-runtime.spec.ts |
| 117 | Model Configurations — Real Backend Confirms Migration | Live backend (no `page.route()` mocks) validates that the Postgres `model_provider_enum` migration was applied — the list endpoint returns configs for all 12 provider types | expand-model-config-providers | agent-runtime.spec.ts |
| 118 | Model Configurations — Create a New Provider (Gemini) | Admin creates a `ModelConfig` for the Gemini provider through the real backend; the API key is AES-256 encrypted and never returned; the new row appears on the list page without page reload | expand-model-config-providers | agent-runtime.spec.ts |
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
| 140 | Inline MCP Session Assignment — Create Role | User creates an agent role with SOPs/Skills, sees required MCP servers appear inline, assigns sessions via dropdowns, and saves — the role is fully configured with all sessions in one operation | improve-role-mcp-session-assignment | agent-role-mcp-assignment.spec.ts |
| 141 | Inline MCP Session Assignment — Save Blocked | User selects SOPs that require MCP servers but does not assign all sessions — the Save button is disabled with a clear inline validation message naming the missing servers | improve-role-mcp-session-assignment | agent-role-mcp-assignment.spec.ts |
| 142 | Inline MCP Session Assignment — Refresh & Passthrough | User clicks the refresh button on an inline dropdown to reload sessions; passthrough badge is visible on configured servers | improve-role-mcp-session-assignment | agent-role-mcp-assignment.spec.ts |
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
