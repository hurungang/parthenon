# Agent UI Test Plan

## Scope

Covers frontend UI tests for agent navigation structure, `AgentTypeDetailsDialog`, agent executions filtering, and role/identity view dialogs. Backend engine logic, CRUD API operations, session lifecycle, and execution log rendering are covered in `agent-engine-test-plan.md`.

---

## Coverage Areas

### 1. Navigation Menu Structure

**What is tested:**
- "AI Agent" collapsible group present in sidebar with all five child links in the correct order
- Each child link routes to its correct path
- Group defaults to expanded on first render
- Group header highlights when any child route is active; active child item highlighted individually
- Collapse/expand toggle behavior within a session
- Legacy `/agents/instances` URL redirects to `/agents/executions`

**Acceptance criteria:**
- All five child links present in order: Agent Roles (`/agents/roles`), Agent Identities (`/agents/identities`), Agent Types (`/agents`), Agent Executions (`/agents/executions`), Agent Logs (`/conversations`)
- Exactly one child item highlighted at any time
- AI Agent group header highlighted when any child route is active
- `/agents/instances` redirect resolves without error

**Test files:**
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Full navigation structure: link routing, active highlighting, group collapse/expand, legacy redirect

---

### 2. Agent Roles and Agent Identities Navigation

**What is tested:**
- "Agent Roles" and "Agent Identities" menu items present in the AI Agent group
- Navigation to each page via the sidebar menu
- Active state highlighting for each route
- AI Agent group header highlighted when on Agent Roles or Agent Identities route

**Acceptance criteria:**
- Clicking "Agent Roles" navigates to the Agent Roles page and highlights that menu item
- Clicking "Agent Identities" navigates to the Agent Identities page and highlights that menu item
- Direct navigation to `/agents/roles` or `/agents/identities` activates the corresponding menu item and the group header

**Test files:**
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Agent Roles and Agent Identities navigation and active state
- [frontend/src/__tests__/AgentRoleListPage.test.tsx](../../../../frontend/src/__tests__/AgentRoleListPage.test.tsx) — Agent Roles page rendering
- [frontend/src/__tests__/AgentIdentityListPage.test.tsx](../../../../frontend/src/__tests__/AgentIdentityListPage.test.tsx) — Agent Identities page rendering

---

### 3. Agent Types Table — Role and Identity Columns

**What is tested:**
- "Role" column displays the role name for each agent type
- "Identity" column displays the identity name for each agent type
- Columns show the human-readable name, not a raw ID or technical key
- Null role or identity renders a dash or placeholder, not a crash or blank render

**Acceptance criteria:**
- Role column present; shows role name, or dash/placeholder when `role_id` is null
- Identity column present; shows identity name, or dash/placeholder when `identity_id` is null
- No render error on agent types without role or identity assignments

**Test files:**
- [frontend/src/__tests__/AgentManagementPage.test.tsx](../../../../frontend/src/__tests__/AgentManagementPage.test.tsx) — Role and Identity column rendering; null state placeholders
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Agent Types table column smoke (names visible, no crash)

---

### 4. Agent Type Details Dialog

**What is tested:**
- Dialog opens when an agent type row is clicked; row action buttons (Edit, Launch, Plan Preview) do not open dialog
- Tab state resets to Details (index 0) on every open; stale state from prior render does not carry over
- Details tab: all configured fields displayed; role and identity names are clickable links that open view dialogs without navigating away; links are non-clickable when `role_id` or `identity_id` is null
- Plan Preview tab: plan steps and topology rendered when plan exists; placeholder shown when `plan` is null
- Execution Logs tab: recent sessions fetched with a distinct React Query key (cache isolation); "View All Executions" closes dialog and navigates to `/agents/executions`
- Dialog shows `PermissionDeniedAlert` on 403; distinct error state on 404 or network failure
- Execution Logs tab error is isolated; Details and Plan Preview tabs unaffected
- Parent table refreshes automatically when dialog closes (no page reload required)

**Acceptance criteria:**
- Row click opens dialog; row action button clicks do not
- Tab state always resets to Details on open
- Role/identity name links open view dialogs inline; non-null check prevents clickable link when value is absent
- Parent Agent Types table shows updated data after dialog close without a page reload

**Test files:**
- [frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx](../../../../frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx) — Dialog rendering, tab switching, field display, error states, `stopPropagation` on action buttons
- [frontend/src/__tests__/AgentManagementPage.test.tsx](../../../../frontend/src/__tests__/AgentManagementPage.test.tsx) — Row click → dialog open; parent table refresh on dialog close
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Full dialog interaction: open, tab navigation, view dialog launch, close and table refresh

---

### 5. Role and Identity View Dialogs

**What is tested:**
- Role view dialog opens when the role name link is clicked in the Details tab
- Identity view dialog opens when the identity name link is clicked in the Details tab
- Both dialogs contain an "Edit" button that switches the dialog to edit mode
- Edit button is hidden or disabled for users without edit permissions
- All three dialog widths (`AgentTypeDetailsDialog`, role view, identity view) match `PlanPreviewModal`

**Acceptance criteria:**
- View dialogs open without navigating away from the agent type details context
- Edit button present and switches dialog to edit mode when clicked
- Edit button not visible to read-only users
- Dialog widths consistent with `PlanPreviewModal`

**Test files:**
- [frontend/src/__tests__/AgentRoleViewDialog.test.tsx](../../../../frontend/src/__tests__/AgentRoleViewDialog.test.tsx) — Role view dialog rendering, Edit button presence, edit mode switch
- [frontend/src/__tests__/AgentIdentityViewDialog.test.tsx](../../../../frontend/src/__tests__/AgentIdentityViewDialog.test.tsx) — Identity view dialog rendering, Edit button presence, edit mode switch
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Role and identity view dialog open/edit flows; dialog width assertions

---

### 6. Agent Executions Filtering

**What is tested:**
- Agent type dropdown populated from `useAgentTypes()` results
- Selecting an agent type passes `agent_type_id` as a query param to the sessions fetch
- React Query key includes `agentTypeId` to prevent cache collision with unfiltered page-level state
- Clearing the filter restores the unfiltered result set
- All page strings use "Executions" (not "Instances")
- `agentTypeId` prop pre-selects the dropdown when the component is embedded in the dialog

**Acceptance criteria:**
- Filter dropdown populated and functional
- Filter clears and restores correctly
- No "Instances" wording anywhere on the Agent Executions page

**Test files:**
- [frontend/src/__tests__/AgentInstanceDashboard.test.tsx](../../../../frontend/src/__tests__/AgentInstanceDashboard.test.tsx) — Dropdown population, filter application, cache key isolation, prop-controlled pre-selection, string assertions for "Executions"
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — Agent Executions filter interaction end-to-end

---

### 7. i18n Translation Keys

**What is tested:**
- All navigation and UI strings for agent features use `t()` with registered keys
- New keys present in `en.json`: `nav.aiAgent`, `nav.agentTypes`, `nav.agentExecutions`, `nav.agentLogs`, `nav.agentRoles`, `nav.agentIdentities`
- `agents.sessions.dashboardTitle` uses "Executions" wording
- `nav.agentInstances` removed or aliased; no leftover `t('nav.agentInstances')` calls in production code

**Acceptance criteria:**
- No hardcoded English strings in changed components
- No missing key warnings in browser console for agent nav items

**Test files:**
- [e2e/tests/agent-navigation.spec.ts](../../../../e2e/tests/agent-navigation.spec.ts) — UI text assertions use i18n-resolved values; missing keys would surface as key-string labels

---

## Manual Testing Requirements

| Scenario | Why Manual |
|---|---|
| Sidebar nav group header highlight when child route is active (visual) | CSS active-state styling requires visual confirmation; automated assertions cover presence, not visual weight |
| Collapsible nav group behavior on narrow/responsive sidebar | Responsive sidebar collapse is viewport-dependent; visual review confirms correctness beyond basic Playwright breakpoint checks |
| Dialog width matching `PlanPreviewModal` across viewports | Pixel-accurate width comparison across breakpoints requires visual review or a dedicated visual regression tool |

---

## Edge Cases & Risks

- Menu children rendered in wrong order — breaks user muscle memory and documentation references; exact order must be verified
- Active highlight missing for Agent Roles / Agent Identities routes — no visual context when on those pages
- Role or Identity column showing a raw ID instead of a human-readable name
- Null role or identity crashing the Agent Types table row render
- `AgentTypeDetailsDialog` tab state carrying over between opens (stale `agentTypeId` from prior render)
- React Query cache collision between Execution Logs tab fetch (`['agents', 'sessions', 'dialog', agentTypeId]`) and the page-level sessions cache
- Parent table not refreshing after dialog close — stale data displayed until manual reload
- Row action buttons (Edit, Launch, Plan Preview) accidentally opening the details dialog due to missing `stopPropagation`
- Clickable role/identity name triggering when `role_id`/`identity_id` is null — view dialog opens with no ID and may crash
- Edit button visible to read-only users — must be hidden or disabled by permission check
- `/agents/instances` redirect missing — bookmarks and deep links 404 after rename
- Missing i18n keys causing key-string literals to render in production

---

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| unified-agent-navigation | AI Agent nav group; AgentTypeDetailsDialog; Role/Identity columns; Agent Executions filter; view dialogs with Edit mode; legacy redirect | 2026-05-10 |
