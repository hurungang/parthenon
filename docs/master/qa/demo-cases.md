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
- MCP Hub > MCP Hub has a register/add server button
- Notification Configuration > notification page shows channel names from API
- Observability Dashboard > observability dashboard shows request rate metric
- Result Repository > result repository shows result payload text
- Schedule Manager > schedule manager shows schedule names from API
- Skills > skills page has create skill button
- SOPs > clicking a SOP shows its steps
- Setup Wizard > setup wizard has input fields for configuration
- Tags Management > renders tag definitions table
- Roles Management > navigates to Roles tab and shows role data
- Groups Management > groups tab shows group data
- User Access Management > users tab shows user data
- Access Request Flow > access requests tab renders

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
