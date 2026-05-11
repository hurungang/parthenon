# Test Plan: unified-agent-navigation

## 1. Test Strategy

This change is entirely frontend UI — no backend API or database changes. Testing focuses on component behavior, navigation structure correctness, and end-to-end user flows.

| Layer | Framework | Scope |
|---|---|---|
| Unit | Vitest + React Testing Library | `AgentTypeDetailsDialog` component logic, tab switching, disabled states, error display |
| Integration | Vitest + React Testing Library | `AgentManagementPage` row-click → dialog flow; `AgentInstanceDashboardPage` filter behavior |
| E2E | Playwright | Full navigation flows: group collapse/expand, executions filtering, dialog tabs, route redirects |
| Manual | — | Visual polish: collapsible nav group highlight when child route active, responsive sidebar behavior |

No database migration testing is required. No backend integration tests are needed — all data access uses existing endpoints without change.

---

## 2. Coverage Areas

### Navigation Menu Structure
Critical because it is the primary entry point for all agent features. A broken group or missing child link directly prevents users from reaching agent management.
- "AI Agent" collapsible group present in sidebar
- All five children present and correctly linked: Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs
- Children appear in the exact prescribed order: Agent Roles (1st), Agent Identities (2nd), Agent Types (3rd), Agent Executions (4th), Agent Logs (5th)
- Each child link navigates to its correct route: `/agents/roles`, `/agents/identities`, `/agents`, `/agents/executions`, `/conversations`
- Group defaults to expanded on first render
- Group header highlights when any child route is active
- Active child menu item is highlighted when its route is active (all five items individually)
- Collapse/expand toggle persists within a session
- Legacy `/agents/instances` URL redirects to `/agents/executions`

### Agent Roles Navigation
Agent Roles is an existing page reorganized into the AI Agent menu. Testing focuses on menu linkage and active-state highlighting, not page functionality.
- Clicking "Agent Roles" menu item navigates to the Agent Roles page
- Agent Roles page loads without error when reached via the menu
- "Agent Roles" menu item is highlighted when the current route is `/agents/roles`
- "AI Agent" group header is highlighted when on the Agent Roles route

### Agent Identities Navigation
Agent Identities is an existing page reorganized into the AI Agent menu. Testing focuses on menu linkage and active-state highlighting, not page functionality.
- Clicking "Agent Identities" menu item navigates to the Agent Identities page
- Agent Identities page loads without error when reached via the menu
- "Agent Identities" menu item is highlighted when the current route is `/agents/identities`
- "AI Agent" group header is highlighted when on the Agent Identities route

### Agent Executions Filtering
Critical for operators who monitor specific agent types. Incorrect filtering would show unrelated data and break troubleshooting workflows.
- Agent type dropdown populated from `useAgentTypes()` results
- Selecting a type passes `agent_type_id` query param to `GET /agents/sessions`
- React Query key includes `agentTypeId` (ensures cache isolation)
- Clearing filter returns to unfiltered result set
- Page title and all UI strings use "Executions" (not "Instances")
- `agentTypeId` prop pre-selects dropdown when dialog embeds the component

### Agent Type Details Dialog — General
- Dialog opens when agent type row is clicked in `AgentManagementPage`
- `AgentTypeDetailsDialog` receives correct `agentTypeId`
- Tab state resets to Details (index 0) on each open
- Dialog close triggers `queryClient.invalidateQueries(['agents', 'types'])` so parent table refreshes
- Row action buttons (Edit, Launch, Plan Preview) do not open dialog (stopPropagation is preserved)

### Agent Types Table — Role and Identity Columns
Critical for at-a-glance understanding of each agent type's configuration without opening a dialog.
- Agent Types table has a "Role" column displaying the role name for each agent type
- Agent Types table has an "Identity" column displaying the identity name for each agent type
- Columns show the actual name (not an ID or technical key)
- When an agent type has no role, the Role column shows a dash or empty placeholder (not a crash or blank render)
- When an agent type has no identity, the Identity column shows a dash or empty placeholder
- Columns sort and filter consistently with other text columns

### Dialog Width Consistency
All dialogs must match the width of `PlanPreviewModal` to provide a consistent, content-rich experience across the product.
- `AgentTypeDetailsDialog` width matches `PlanPreviewModal` width
- Role view dialog width matches `PlanPreviewModal` width
- Identity view dialog width matches `PlanPreviewModal` width
- Dialogs are fully responsive on smaller viewports
- No dialog is narrower than `PlanPreviewModal` at the same viewport size

### Agent Type Details Dialog — Details Tab
- Displays correct field values: Name, Description, Status chip, LLM Model, Input/Output Type, System Prompt
- Role name is displayed as a clickable link; clicking opens the Role view dialog (does not navigate away)
- Identity name is displayed as a clickable link; clicking opens the Identity view dialog (does not navigate away)
- Role name link is non-clickable (disabled or absent) when `role_id` is null
- Identity name link is non-clickable (disabled or absent) when `identity_id` is null
- "Run Agent" opens `AgentJobLaunchDialog` within the dialog

### Role and Identity View Dialogs
View dialogs must support in-place editing via an Edit button, enabling admins to make changes without leaving the agent type details context.
- Role view dialog includes an "Edit" button
- Clicking "Edit" in the role view dialog switches the dialog to edit mode
- Identity view dialog includes an "Edit" button
- Clicking "Edit" in the identity view dialog switches the dialog to edit mode
- Edit button is hidden or disabled for users without edit permissions

### Agent Type Details Dialog — Plan Preview Tab
- Plan steps and topology render correctly when `agentType.plan` is non-null
- Placeholder text is shown when `plan` is null

### Agent Type Details Dialog — Execution Logs Tab
- Fetches `GET /agents/sessions?agent_type_id=<id>&limit=10` using a distinct query key
- Table displays: truncated Session ID, Status chip, Created At, "View" link to `/agents/sessions/:id`
- "View All Executions" button navigates to `/agents/executions` and closes dialog
- Empty state renders when no executions exist for the agent type

### i18n Translation Keys
All UI strings must use `t()` — hardcoded strings would break localization and cause CI lint failures.
- `nav.aiAgent`, `nav.agentTypes`, `nav.agentExecutions`, `nav.agentLogs`, `nav.agentRoles`, `nav.agentIdentities` present in `en.json`
- `agents.sessions.dashboardTitle` updated to "Executions" wording
- `nav.agentInstances` key removed (or aliased if backward compat needed)
- No string in changed components is rendered as a plain string literal

### Error Handling
- Dialog displays `PermissionDeniedAlert` when agent type fetch returns 403
- Dialog shows error state when agent type fetch returns 404 or network failure
- Execution Logs tab shows error state independently when its fetch fails
- Agent type dropdown in filter toolbar degrades gracefully if `useAgentTypes()` fails

---

## 3. Critical Scenarios

### Navigation

**WHEN** a user opens the app for the first time  
**THEN** the sidebar shows an "AI Agent" group that is expanded, with all five child links visible in this exact order: Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs

**WHEN** a user navigates to `/agents/executions`  
**THEN** the Agent Executions page loads and "AI Agent" group header is highlighted

**WHEN** a user navigates to the legacy URL `/agents/instances`  
**THEN** they are redirected to `/agents/executions` without error

**WHEN** a user clicks the "AI Agent" group header  
**THEN** the group collapses, hiding all child links

**WHEN** a user clicks the "AI Agent" group header again  
**THEN** the group expands, restoring all child links

**WHEN** a user clicks the "Agent Roles" menu item  
**THEN** the Agent Roles page is displayed and the "Agent Roles" menu item is highlighted

**WHEN** a user clicks the "Agent Identities" menu item  
**THEN** the Agent Identities page is displayed and the "Agent Identities" menu item is highlighted

**WHEN** a user navigates directly to `/agents/roles`  
**THEN** the "Agent Roles" child item is highlighted and the "AI Agent" group header is highlighted

**WHEN** a user navigates directly to `/agents/identities`  
**THEN** the "Agent Identities" child item is highlighted and the "AI Agent" group header is highlighted

**WHEN** a user navigates between Agent Types, Agent Executions, Agent Logs, Agent Roles, and Agent Identities  
**THEN** only the currently active child menu item is highlighted (no two items highlighted simultaneously)

### Agent Types Table — Role and Identity Columns

**WHEN** the Agent Types table loads with agent types that have roles and identities assigned  
**THEN** the Role column displays each agent type's role name and the Identity column displays each agent type's identity name

**WHEN** an agent type has no role assigned  
**THEN** the Role column for that row shows a dash or empty placeholder (not a crash or blank)

**WHEN** an agent type has no identity assigned  
**THEN** the Identity column for that row shows a dash or empty placeholder (not a crash or blank)

### Dialog Width Consistency

**WHEN** a user opens `AgentTypeDetailsDialog`  
**THEN** the dialog width matches the width of `PlanPreviewModal`

**WHEN** a user opens a Role view dialog  
**THEN** the dialog width matches the width of `PlanPreviewModal`

**WHEN** a user opens an Identity view dialog  
**THEN** the dialog width matches the width of `PlanPreviewModal`

### Agent Executions Filtering

**WHEN** a user opens Agent Executions and selects an agent type from the dropdown  
**THEN** the executions table shows only sessions belonging to that agent type

**WHEN** a user clears the agent type filter  
**THEN** the executions table returns to the unfiltered view

**WHEN** there are no executions for the selected agent type  
**THEN** the table displays an empty state (not an error)

### Agent Type Details Dialog

**WHEN** a user clicks an agent type row on the Agent Types page  
**THEN** `AgentTypeDetailsDialog` opens showing Details tab by default

**WHEN** the dialog is already open and the user closes it and clicks a different agent type row  
**THEN** the dialog opens showing Details tab (tab state is reset, not carried over)

**WHEN** a user clicks the "Plan Preview" tab  
**THEN** the plan steps and topology render; if no plan exists, a placeholder message is shown

**WHEN** a user clicks the "Execution Logs" tab  
**THEN** up to 10 recent sessions for this agent type are listed; an empty state shows if none exist

**WHEN** a user clicks "View All Executions" in the Execution Logs tab  
**THEN** the dialog closes and the user is navigated to `/agents/executions`

**WHEN** a user clicks the identity name link in the Details tab and `identity_id` is set  
**THEN** the Identity view dialog opens (the Agent Type Details dialog does not close or navigate away)

**WHEN** a user clicks the role name link in the Details tab and `role_id` is set  
**THEN** the Role view dialog opens (the Agent Type Details dialog does not close or navigate away)

**WHEN** `identity_id` is null  
**THEN** the identity name is not clickable (displayed as plain text or absent)

**WHEN** `role_id` is null  
**THEN** the role name is not clickable (displayed as plain text or absent)

**WHEN** a user opens a Role view dialog from the Details tab  
**THEN** an "Edit" button is visible in the dialog

**WHEN** a user clicks "Edit" in the Role view dialog  
**THEN** the dialog switches to edit mode

**WHEN** a user opens an Identity view dialog from the Details tab  
**THEN** an "Edit" button is visible in the dialog

**WHEN** a user clicks "Edit" in the Identity view dialog  
**THEN** the dialog switches to edit mode

**WHEN** the dialog closes after any interaction  
**THEN** the Agent Types parent table refreshes automatically (no page reload required)

**WHEN** a user clicks an action button (Edit, Launch, Plan Preview) on a row  
**THEN** the dialog does NOT open (click event is stopped from propagating to the row handler)

### Error Handling

**WHEN** the agent type fetch returns a 403 error  
**THEN** the dialog shows a `PermissionDeniedAlert` instead of content

**WHEN** the agent type fetch returns a 404 or network error  
**THEN** the dialog shows a clear error message

**WHEN** the Execution Logs tab fetch fails independently  
**THEN** only the Execution Logs tab shows an error; the Details and Plan Preview tabs are unaffected

---

## 4. Edge Cases & Risks

| Risk | Why It Matters |
|---|---|
| Agent Roles or Agent Identities menu item missing from sidebar | Users with appropriate permissions cannot navigate to these pages; must be verified that both items render when the AI Agent group is expanded |
| Menu children in wrong order | PRD specifies exact order: Agent Roles (1st), Agent Identities (2nd), Agent Types (3rd), Agent Executions (4th), Agent Logs (5th); wrong order breaks user muscle memory and documentation |
| Incorrect route wired to Agent Roles or Agent Identities link | A typo in the `to` prop silently lands users on a 404 or wrong page |
| Active highlight missing for Agent Roles / Agent Identities routes | Without correct route matching in the nav component, the menu item appears inactive even when on the correct page, breaking visual context |
| Permission-gated visibility of Agent Roles / Agent Identities | If these items are shown only to users with specific roles (e.g., admin), the menu must hide them for users without that permission — verify both visible and hidden states |
| Role or Identity column missing from Agent Types table | Users cannot see configuration at a glance; requires clicking into every row to understand role/identity assignment |
| Role or Identity column shows ID instead of name | Technical IDs are meaningless to users; must resolve and display the human-readable name |
| Role or Identity column crashes when value is null | Agent types without assigned roles/identities are valid; null must render a placeholder, not throw a render error |
| Dialog width inconsistency | If AgentTypeDetailsDialog or view dialogs are narrower than PlanPreviewModal, content is harder to read; width must match across all dialogs |
| Clickable role/identity name does not open view dialog | If the click handler is wired to page navigation instead of opening a dialog, users are unexpectedly routed away from their current context |
| Clickable name still triggers when role/identity is null | A null name must not be clickable; if it is, the view dialog would open with no ID and likely crash or show empty content |
| Edit button missing from role view dialog | Users cannot edit roles without leaving the agent type details context; the Edit button must be present and functional |
| Edit button missing from identity view dialog | Same risk as above for identity view dialogs |
| Edit button visible to users without edit permissions | Edit button must be hidden or disabled for read-only users to prevent unauthorized edits |
| Agent type with null plan | Plan Preview tab must show placeholder, not crash; `agentType.plan` can legitimately be null on new types |
| Empty executions list in dialog | Execution Logs tab empty state must render; an empty table must not show spinner indefinitely |
| Rapid dialog open/close with different IDs | Tab state must reset on each open; stale `agentTypeId` from previous render must not persist |
| React Query cache collision | Execution Logs tab uses a separate query key (`['agents', 'sessions', 'dialog', agentTypeId]`) to avoid overwriting the page-level sessions cache — must be verified |
| Parent table not refreshing after dialog close | `queryClient.invalidateQueries` must fire in the `onClose` handler of `AgentManagementPage`, not inside the dialog — if wired incorrectly, the table will show stale data |
| Row action buttons opening dialog unintentionally | Edit, Launch, Plan Preview buttons all call `e.stopPropagation()` — a missing call would open the dialog on every row action click |
| Missing i18n keys causing render crash | Any `t('nav.agentInstances')` call left over from old code must be cleaned up; missing keys show key strings in production |
| `/agents/instances` redirect missing | Deep links and bookmarks from before this change would 404 without the redirect |
| `agentTypeId` prop not controlling dropdown in embedded mode | When dialog embeds `AgentInstanceDashboardPage` via prop, the dropdown must reflect the prop value, not independent state |

---

## 5. Acceptance Criteria Checklist

From PRD:

- [ ] "AI Agent" top-level menu exists in sidebar with all agent-related modules as child links
- [ ] All five agent child links are present and correctly routed: Agent Roles (`/agents/roles`), Agent Identities (`/agents/identities`), Agent Types (`/agents`), Agent Executions (`/agents/executions`), Agent Logs (`/conversations`)
- [ ] Children appear in the exact prescribed order: Agent Roles (1st), Agent Identities (2nd), Agent Types (3rd), Agent Executions (4th), Agent Logs (5th)
- [ ] Clicking "Agent Roles" navigates to the Agent Roles page and highlights that menu item
- [ ] Clicking "Agent Identities" navigates to the Agent Identities page and highlights that menu item
- [ ] Active child menu item is highlighted correctly for all five agent pages
- [ ] "Agent Instances" is renamed to "Agent Executions" in all UI strings and route paths
- [ ] Agent Executions view has an agent type filter (dropdown) that narrows the executions list
- [ ] Agent Types table has a "Role" column displaying the role name for each agent type (dash/placeholder when null)
- [ ] Agent Types table has an "Identity" column displaying the identity name for each agent type (dash/placeholder when null)
- [ ] Clicking an agent type row opens `AgentTypeDetailsDialog`
- [ ] `AgentTypeDetailsDialog` width matches `PlanPreviewModal` width
- [ ] Dialog Details tab shows: Name, Description, Status, LLM Model, Input Type, Output Type, System Prompt
- [ ] Role name in Details tab is a clickable link that opens the Role view dialog (non-clickable when `role_id` is null)
- [ ] Identity name in Details tab is a clickable link that opens the Identity view dialog (non-clickable when `identity_id` is null)
- [ ] Role view dialog width matches `PlanPreviewModal` width
- [ ] Role view dialog includes an "Edit" button that switches the dialog to edit mode
- [ ] Identity view dialog width matches `PlanPreviewModal` width
- [ ] Identity view dialog includes an "Edit" button that switches the dialog to edit mode
- [ ] Dialog Plan Preview tab shows saved agent plan steps and topology (or placeholder when null)
- [ ] Dialog Execution Logs tab shows list of recent executions for this agent type
- [ ] "Active instances" row-click behavior works via the new dialog (replaces broken sub-table)
- [ ] Closing the dialog refreshes the parent Agent Types table automatically (no page reload)
- [ ] All changes are visible in the UI without a page reload
- [ ] `/agents/instances` redirect to `/agents/executions` is in place
- [ ] Error messages are clear and displayed when data fetches fail
- [ ] All UI text for changed areas uses `t()` and corresponding keys exist in `en.json`

---

## 6. Test File References

| Test Type | File | Coverage |
|---|---|---|
| Unit | [frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx](frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx) | Dialog rendering, tab switching, disabled button states, error display, tab reset on open; clickable role/identity names open view dialogs; null role/identity shows dash |
| Unit | [frontend/src/__tests__/AgentRoleViewDialog.test.tsx](frontend/src/__tests__/AgentRoleViewDialog.test.tsx) | Role view dialog loading state, role details display, Edit button enabled/disabled state, clicking Edit opens AgentRoleDialog, Close button, error display, no-fetch when roleId null |
| Unit | [frontend/src/__tests__/AgentIdentityViewDialog.test.tsx](frontend/src/__tests__/AgentIdentityViewDialog.test.tsx) | Identity view dialog loading state, identity details display, Edit button closes dialog and navigates to /agents/identities, Close button, error display, no-fetch when identityId null |
| Integration | [frontend/src/__tests__/AgentManagementPage.test.tsx](frontend/src/__tests__/AgentManagementPage.test.tsx) | Row click opens dialog, action buttons do not open dialog, parent table invalidation on close; Role/Identity column headers rendered; dash shown when null; role name resolved from API |
| E2E | [e2e/tests/agent-navigation.spec.ts](e2e/tests/agent-navigation.spec.ts) | Nav group expand/collapse, menu order (Roles→Identities→Types→Executions→Logs), route redirect, executions filter; Agent Types table Role/Identity column headers and resolved names; dialog full flow, clickable identity/role names open view dialogs; view dialog Edit buttons; "View All Executions" nav |
