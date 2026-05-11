# Demo Cases: unified-agent-navigation
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/unified-agent-navigation/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- AI Agent nav group > nav group is expanded by default and shows child items
- AI Agent nav group > collapses and expands nav group on header click
- Agent Executions page > selecting agent type filter refetches sessions
- Agent Type Details Dialog > dialog Details tab shows agent metadata
- Agent Type Details Dialog > Plan Preview tab shows plan steps when plan is populated
- Agent Type Details Dialog > "View All Executions" button navigates to /agents/executions
- Nav menu order > Agent Roles and Agent Identities appear above Agent Types in the nav
- Agent Types table columns > Role column shows resolved role name for agent type
- Agent Types table columns > Identity column shows resolved identity name for agent type
- Agent Type Details Dialog > clicking identity name in Details tab opens identity view dialog
- Agent Type Details Dialog > identity view dialog has Edit button that navigates to identities page
- Agent Type Details Dialog > clicking role name in Details tab opens role view dialog
- Agent Type Details Dialog > role view dialog has Edit button that opens role edit form

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Navigation menu structure | Sidebar "AI Agent" group is expanded with all five child links (Agent Types, Executions, Logs, Roles, Identities) visible | agent-navigation.spec.ts | nav group is expanded by default and shows child items |
| 2 | Collapsible nav group toggle | User clicks "AI Agent" header to collapse the group, hiding all child links, then clicks again to expand them | agent-navigation.spec.ts | collapses and expands nav group on header click |
| 3 | Agent Executions filter | User selects an agent type from the dropdown and the page re-fetches sessions with `agent_type_id` in the request | agent-navigation.spec.ts | selecting agent type filter refetches sessions |
| 4 | Agent Type Details Dialog — Details tab | User clicks an agent type row; dialog opens showing model ID, system prompt, and other metadata | agent-navigation.spec.ts | dialog Details tab shows agent metadata |
| 5 | Agent Type Details Dialog — Plan Preview tab | User switches to Plan Preview tab; plan step names and topology render from the agent plan | agent-navigation.spec.ts | Plan Preview tab shows plan steps when plan is populated |
| 6 | Agent Type Details Dialog — Execution Logs tab | User switches to Execution Logs tab, sees recent sessions, then clicks "View All Executions" which closes the dialog and lands on `/agents/executions` | agent-navigation.spec.ts | "View All Executions" button navigates to /agents/executions |
| 7 | Nav menu order (Roles/Identities before Types) | Nav items are ordered Roles → Identities → Types → Executions → Logs top-to-bottom, confirmed via bounding box positions | agent-navigation.spec.ts | Agent Roles and Agent Identities appear above Agent Types in the nav |
| 8 | Agent Types table — Role column | Agent Types table shows a resolved "Role" column; the row for "Research Agent" displays "Research Role" looked up from the roles list | agent-navigation.spec.ts | Role column shows resolved role name for agent type |
| 9 | Agent Types table — Identity column | Agent Types table shows a resolved "Identity" column; the row displays "Research Bot" looked up from the identities list | agent-navigation.spec.ts | Identity column shows resolved identity name for agent type |
| 10 | Clickable identity name in Details tab | In the Agent Type Details dialog, the identity field renders as a clickable button ("Research Bot"); clicking it opens the Agent Identity view dialog | agent-navigation.spec.ts | clicking identity name in Details tab opens identity view dialog |
| 11 | Edit button in identity view dialog | The Agent Identity view dialog has an Edit button; clicking it navigates to `/agents/identities` | agent-navigation.spec.ts | identity view dialog has Edit button that navigates to identities page |
| 12 | Clickable role name in Details tab | In the Agent Type Details dialog, the role field renders as a clickable button ("Research Role"); clicking it opens the Agent Role view dialog | agent-navigation.spec.ts | clicking role name in Details tab opens role view dialog |
| 13 | Edit button in role view dialog | The Agent Role view dialog has an Edit button; clicking it opens the role edit form dialog | agent-navigation.spec.ts | role view dialog has Edit button that opens role edit form |
