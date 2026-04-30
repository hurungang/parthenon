# Demo Cases: implement-global-access-control
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/implement-global-access-control/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Permissions Page > renders tabs for tag/role/group/user/access management
- Tags Management > renders tag definitions table
- Bug Reproduction: Role Policy Management > should allow editing role policy as JSON
- Bug Reproduction: Group View Members > View Members button for groups should open members drawer
- User Access Management > users tab shows user data
- Agent Management > shows create agent type button and opens dialog on click
- MCP Hub > MCP Hub has a register/add server button
- Skills > skills page has create skill button
- SOPs > clicking a SOP shows its steps
- Schedule Manager > schedule execution history is available
- Notification Configuration > notification page shows event log with event types
- Conversation History > clicking a conversation expand button shows its turns
- Result Repository > result repository shows tags for results
- Permission Denied: Snackbar > 403 on agent create triggers permission-denied snackbar
- Permission Denied: Request Access Flow > user can submit access request with justification and sees confirmation
- AccessDeniedPage > renders at /access-denied with lock icon and action buttons

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Permissions Management Page | All five management tabs (Tags, Roles, Groups, Users, Access Requests) visible on the /user-permissions page | permissions.spec.ts | renders tabs for tag/role/group/user/access management |
| 2 | Tags Management | Tag definitions table populated from API, showing tag key ('env') with its allowed values | permissions.spec.ts | renders tag definitions table |
| 3 | Role Policy Management | User expands a role row, clicks "Edit as JSON", and sees the full JSON policy editor textarea | permissions.spec.ts | should allow editing role policy as JSON |
| 4 | Group Member Management | User navigates to Groups tab, clicks "View Members" for a group, and a members drawer opens listing Alice and Bob | permissions.spec.ts | View Members button for groups should open members drawer |
| 5 | Platform User Management | Users tab displays platform user list (Alice) after navigating to the fourth tab | permissions.spec.ts | users tab shows user data |
| 6 | Agent Management | Create Agent Type button is visible and clicking it opens the MUI create dialog | agent-management.spec.ts | shows create agent type button and opens dialog on click |
| 7 | MCP Hub | Register Server button is visible and clicking it opens the MUI register dialog | mcp-hub.spec.ts | MCP Hub has a register/add server button |
| 8 | Skills | Create Skill button is visible and clicking it opens the MUI create dialog | skills-sops.spec.ts | skills page has create skill button |
| 9 | SOPs | Clicking an SOP row drills into its steps, showing step-level actions (Collect user info, Send welcome email, Schedule follow-up) | skills-sops.spec.ts | clicking a SOP shows its steps |
| 10 | Scheduling | Execution history panel shows 'success' status for a completed schedule run | scheduling.spec.ts | schedule execution history is available |
| 11 | Notifications | Event log displays delivered notification events (agent.result.saved) alongside configured channels | notifications.spec.ts | notification page shows event log with event types |
| 12 | Conversation History | Expanding a conversation row reveals its individual turns (user and agent messages) | conversations.spec.ts | clicking a conversation expand button shows its turns |
| 13 | Result Repository | Results list shows tag chips (research, q1-2026) attached to each result entry | results.spec.ts | result repository shows tags for results |
| 14 | Permission Denied: Snackbar | A 403 response with `required_permission` body triggers the global snackbar with "Request Access" button, showing resource type and action context | access-control.spec.ts | 403 on agent create triggers permission-denied snackbar |
| 15 | Request Access Flow | User clicks "Request Access" in the snackbar, fills in a justification, submits, and sees confirmation — modal is pre-filled with denied resource/action/ID | access-control.spec.ts | user can submit access request with justification and sees confirmation |
| 16 | Access Denied Full Page | User navigates to /access-denied and sees the full-page denial view with lock icon, error message, "Return to Dashboard" and "Request Access" buttons | access-control.spec.ts | renders at /access-denied with lock icon and action buttons |
