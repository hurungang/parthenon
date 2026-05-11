# Implementation Plan: unified-agent-navigation

## Overview

This change unifies all agent-related navigation under a single collapsible "AI Agent" group in the sidebar, renames "Agent Instances" to "Agent Executions" throughout the UI, adds agent type filtering to the Executions view, and replaces the broken inline "active instances" sub-table on the Agent Types page with a tabbed dialog showing details, plan preview, and filtered execution logs.

No backend changes are required — the `GET /agents/sessions?agent_type_id=` filter already exists.

---

## Task Checklist

### Phase 1 — Navigation Structure

- [x] 1.1 — Update `AppShell.tsx` to support grouped collapsible nav sections
- [x] 1.2 — Add new i18n keys for nav group and renamed items
- [x] 1.3 — Add `/agents/executions` route and redirect from `/agents/instances`
- [x] 1.4 — Move Agent Roles and Agent Identities from flat nav into AI Agent nav group
- [x] 1.5 — Reorder AI Agent nav group children to: Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs

### Phase 2 — Agent Executions Page

- [x] 2.1 — Add agent type filter dropdown to `AgentInstanceDashboardPage`
- [x] 2.2 — Update all "Agent Instances" display strings to "Agent Executions"

### Phase 3 — Agent Type Details Dialog

- [x] 3.1 — Create `AgentTypeDetailsDialog` component with Details tab
- [x] 3.2 — Add Plan Preview tab to `AgentTypeDetailsDialog`
- [x] 3.3 — Add Execution Logs tab to `AgentTypeDetailsDialog`
- [x] 3.4 — Increase dialog widths to fully responsive, matching `PlanPreviewModal`
- [x] 3.5 — Replace "View Identity" and "View Role" buttons with clickable name text opening view dialogs

### Phase 4 — Integration

- [x] 4.1 — Update `AgentManagementPage` row click to open `AgentTypeDetailsDialog`
- [x] 4.2 — Remove inline "active instances" sub-table from `AgentManagementPage`
- [x] 4.3 — Wire identity and role navigation links in dialog Details tab
- [x] 4.4 — Add "Role" and "Identity" columns to Agent Types table in `AgentManagementPage`
- [x] 4.5 — Add "Edit" button to role and identity view dialogs

### Phase 5 — Testing & Polish

- [x] 5.1 — Add unit tests for `AgentTypeDetailsDialog`
- [x] 5.2 — Update `AgentManagementPage` unit tests for new row-click behavior
- [x] 5.3 — Add e2e tests for navigation group and dialog flows
- [x] 5.4 — Update unit tests for refinements: Role/Identity columns, clickable names, dialog widths
- [ ] 5.5 — Update e2e tests for refinements: new nav order, clickable names opening view dialogs, Edit buttons

---

## Phase 1 — Navigation Structure

### Task 1.1 — Update `AppShell.tsx` to support grouped collapsible nav sections

**File**: `frontend/src/app/AppShell.tsx`

Replace the flat `NAV_ITEMS` array and its single `List` renderer with a structure that supports both flat nav items and collapsible group sections. Add a `NavGroup` type and a second data structure for grouped items. The "AI Agent" group contains five items: Agent Types (`/agents`), Agent Executions (`/agents/executions`), Agent Logs (`/conversations`), Agent Roles (`/agents/roles`), and Agent Identities (`/agents/identities`). Remove those items from the flat list — Agent Roles and Agent Identities are existing flat nav items being moved into the group (see Task 1.4). Use MUI `Collapse`, `ExpandMore`/`ExpandLess` icons, and `List`/`ListItemButton` to render the group. Group defaults to expanded. The active-path matching for the group header should highlight when any child is active.

**Done when**: The sidebar renders an "AI Agent" expandable/collapsible group containing all five agent sub-items (Agent Types, Agent Executions, Agent Logs, Agent Roles, Agent Identities); clicking the group header toggles expansion; the correct child item is highlighted when its route is active; all other flat nav items remain unchanged.

---

### Task 1.2 — Add new i18n keys for nav group and renamed items

**File**: `frontend/src/i18n/locales/en.json`

Add the following keys under the `nav` namespace:
- `nav.aiAgent` — "AI Agent"
- `nav.agentTypes` — "Agent Types"
- `nav.agentExecutions` — "Agent Executions"
- `nav.agentLogs` — "Agent Logs"
- `nav.agentRoles` — "Agent Roles"
- `nav.agentIdentities` — "Agent Identities"

Keep `nav.agents`, `nav.agentInstances` as-is for now (removed in Task 2.2 after all usages are updated). All new `AppShell.tsx` group/child labels must use the new keys.

**Done when**: `npm run build` reports no missing i18n key warnings; new nav labels appear correctly in the UI.

---

### Task 1.3 — Add `/agents/executions` route and redirect from `/agents/instances`

**File**: `frontend/src/app/AppRouter.tsx`

Add a new route `<Route path="/agents/executions" element={<AgentInstanceDashboardPage />} />`. Add a redirect `<Route path="/agents/instances" element={<Navigate to="/agents/executions" replace />} />` so existing bookmarks and links continue to work. Update the `AppShell.tsx` nav link for "Agent Executions" to use path `/agents/executions`.

**Done when**: Navigating to `/agents/executions` renders the `AgentInstanceDashboardPage`; navigating to `/agents/instances` redirects to `/agents/executions`; no broken routes exist.

---

### Task 1.4 — Move Agent Roles and Agent Identities into the AI Agent nav group

**File**: `frontend/src/app/AppShell.tsx`

Agent Roles (`/agents/roles`) and Agent Identities (`/agents/identities`) are existing pages with existing routes. They currently appear as standalone flat nav items in the sidebar. As part of the grouped nav restructure in Task 1.1, these two items must be removed from the flat `NAV_ITEMS` array and registered as children of the "AI Agent" collapsible group.

No route changes are needed — `AppRouter.tsx` already defines routes for both pages and they are not modified by this task. No new page components are created. Only the nav registration in `AppShell.tsx` changes.

Add i18n keys `nav.agentRoles` ("Agent Roles") and `nav.agentIdentities` ("Agent Identities") in Task 1.2 to support the new group child labels.

**Done when**: Agent Roles and Agent Identities no longer appear as standalone flat nav items; both appear as children inside the "AI Agent" nav group; navigating to `/agents/roles` and `/agents/identities` continues to work without any route changes; the correct child item is highlighted when its route is active.

---

### Task 1.5 — Reorder AI Agent nav group children

**File**: `frontend/src/app/AppShell.tsx`

**REWORK of Task 1.1.** The "AI Agent" nav group was initially implemented with child order: Agent Types, Agent Executions, Agent Logs, Agent Roles, Agent Identities. Change the order to place role/identity management items first: **Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs**.

Only the order of items in the group's children array needs to change. No new items, no route changes, no i18n key changes.

**Done when**: The "AI Agent" nav group renders children in the order: Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs.

---

## Phase 2 — Agent Executions Page

### Task 2.1 — Add agent type filter dropdown to `AgentInstanceDashboardPage`

**File**: `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx`

Add an `agentTypeId` filter state. Fetch the list of agent types using `useAgentTypes()` and render a MUI `Select` dropdown in the filter toolbar (alongside the existing status and date filters) with an "All Agent Types" default option. Pass `agent_type_id=<id>` as a query param to `GET /agents/sessions` when a type is selected (the backend parameter already exists). Include the `agentTypeId` in the React Query key so results re-fetch on change. Add the filter to `handleClearFilters`. Optionally accept an `agentTypeId` prop (for use from the dialog Execution Logs tab in Task 3.3) that pre-selects and locks the dropdown.

**Done when**: The filter dropdown renders all agent type names; selecting a type re-fetches and filters the table; clearing filters resets the dropdown; the `agentTypeId` prop pre-selects and (optionally) disables the dropdown when supplied.

---

### Task 2.2 — Update all "Agent Instances" display strings to "Agent Executions"

**Files**: `frontend/src/i18n/locales/en.json`, `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx`

In `en.json`:
- `agents.sessions.dashboardTitle` → "Agent Executions"
- `agents.sessions.dashboardSubtitle` → update if referencing "instances"
- Remove `nav.agentInstances` (replaced by `nav.agentExecutions`)
- Rename any `agents.instances` keys to `agents.executions` equivalents

In `AgentInstanceDashboardPage.tsx`, update the page `<Typography>` title if it is hardcoded (it should already use the i18n key).

Search for any remaining hardcoded "Agent Instances" strings in other components and update them.

**Done when**: No user-visible string in the UI reads "Agent Instances"; the Executions page title shows "Agent Executions"; `grep -r "Agent Instances"` returns no frontend source matches (outside of git history and test mock data).

---

## Phase 3 — Agent Type Details Dialog

### Task 3.1 — Create `AgentTypeDetailsDialog` with Details tab

> **⚠️ NEEDS REWORK**: (1) Dialog was created with `size="md"` — must be increased to fully responsive maximum width matching `PlanPreviewModal` (see Task 3.4). (2) "View Identity" and "View Role" are action buttons navigating to list pages — must be replaced with clickable name text opening view dialogs (see Task 3.5).

**New file**: `frontend/src/components/agents/AgentTypeDetailsDialog.tsx`

Create a new MUI `Dialog` (size `md`) that accepts props: `open: boolean`, `agentTypeId: string | null`, `onClose: () => void`. Internally use `useAgentType(agentTypeId)` hook to fetch agent type data when open. Apply the Dialog Error Handling Standard from `docs/config.yaml`: `dialogError` state, try-catch on any async action, `PermissionDeniedAlert` at top of `DialogContent`.

Implement a MUI `Tabs`/`Tab`/`TabPanel` structure with three tabs: **Details**, **Plan Preview**, **Execution Logs**.

The **Details tab** renders:
- A `detail-grid`-style two-column layout: Name, Description, Status (Chip), LLM Model, Input Type, Output Type, System Prompt (truncated with expand)
- Two action buttons: "View Identity" (navigates to `/agents/identities`) and "View Role" (navigates to `/agents/roles`); both call `onClose()` then `navigate()`
- A "Run Agent" button that opens `AgentJobLaunchDialog` for this agent type

Reset the active tab to "Details" each time the dialog opens.

**Done when**: Dialog opens with correct agent type data when `agentTypeId` is set; all Details tab fields display correct values; "View Identity" and "View Role" navigate correctly and close the dialog; dialog error handling works on fetch failure; tab resets to Details on re-open. *(Dialog width and clickable names rework tracked in Tasks 3.4 and 3.5.)*

---

### Task 3.2 — Add Plan Preview tab to `AgentTypeDetailsDialog`

**File**: `frontend/src/components/agents/AgentTypeDetailsDialog.tsx`

The **Plan Preview tab** renders the plan topology and step list from the fetched `AgentType.plan` field (already available from `useAgentType`). Reuse plan display logic by delegating to the shared `AgentPlanContent` presentational component (extracted from `PlanPreviewModal`), used by both `PlanPreviewModal` and the new dialog. Show a placeholder when no plan exists (e.g., "No plan generated yet. Save the agent type to generate a plan.").

**Done when**: The Plan Preview tab renders plan steps and topology when `AgentType.plan` is populated; shows placeholder when plan is null; topology diagram renders without errors.

---

### Task 3.3 — Add Execution Logs tab to `AgentTypeDetailsDialog`

**File**: `frontend/src/components/agents/AgentTypeDetailsDialog.tsx`

The **Execution Logs tab** renders a compact list of recent executions for this agent type. Use the existing `GET /agents/sessions?agent_type_id=<id>` endpoint (same as `AgentInstanceDashboardPage`). Fetch sessions with `useQuery` keyed on `['agents', 'sessions', 'dialog', agentTypeId]`. Show Session ID (truncated), Status (Chip), Created At, and a "View" link that navigates to `/agents/sessions/:id`. Show a "View All Executions" button that navigates to `/agents/executions` with the agent type pre-selected (via router state or query param). Limit the in-dialog list to the 10 most recent.

**Done when**: The Execution Logs tab displays sessions filtered by the dialog's agent type; Status chips use correct colors; "View" links navigate to the correct session detail page; "View All Executions" navigates to the Executions page.

---

### Task 3.4 — Increase dialog widths to fully responsive, matching `PlanPreviewModal`

**Files**: `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` and all other agent dialogs (AgentJobLaunchDialog, AgentIdentityViewDialog, AgentRoleViewDialog, etc.)

**REWORK of Task 3.1.** The dialog was created with `maxWidth="md"`. Change all agent dialogs to use `fullWidth` with the same maximum responsive width as `PlanPreviewModal` (inspect `PlanPreviewModal` to confirm its current `maxWidth` / `sx` settings, then apply the same pattern to all agent dialogs in this change).

The goal is a dialog that occupies as much horizontal space as reasonably possible on large screens while remaining fully responsive on smaller screens.

**Done when**: `AgentTypeDetailsDialog` (and other affected agent dialogs) render at the same width as `PlanPreviewModal` at all viewport sizes; no horizontal scrollbar or content clipping.

---

### Task 3.5 — Replace "View Identity" and "View Role" buttons with clickable name text opening view dialogs

**Files**: `frontend/src/components/agents/AgentTypeDetailsDialog.tsx`, `frontend/src/components/agents/AgentIdentityViewDialog.tsx` (new or existing), `frontend/src/components/agents/AgentRoleViewDialog.tsx` (new or existing)

**REWORK of Tasks 3.1 and 4.3.** The Details tab currently has "View Identity" and "View Role" buttons that navigate to the list pages. Replace these with:
- The **identity name** displayed as clickable `<Link>`-style text in the two-column detail grid; clicking opens `AgentIdentityViewDialog` scoped to that identity; shown as "—" (non-clickable) when `identity_id` is null
- The **role name** displayed as clickable text; clicking opens `AgentRoleViewDialog` scoped to that role; shown as "—" when `role_id` is null

If `AgentIdentityViewDialog` and `AgentRoleViewDialog` do not yet exist as standalone dialog components, create minimal view dialogs that display the identity/role fields (matching the detail layout of the list page's row detail). If they exist, import and reuse them.

The "Run Agent" action button remains unchanged.

**Done when**: Clicking an identity name in the Details tab opens `AgentIdentityViewDialog` for that identity; clicking a role name opens `AgentRoleViewDialog`; null `identity_id`/`role_id` renders non-clickable "—" text; the old "View Identity" and "View Role" buttons are removed; dialogs display correct field values.

---

## Phase 4 — Integration

### Task 4.1 — Update `AgentManagementPage` row click to open `AgentTypeDetailsDialog`

**File**: `frontend/src/pages/agents/AgentManagementPage.tsx`

Replace the row `onClick={() => setSelectedType(at)}` handler with `onClick={() => setDetailsDialogTypeId(at.id)}`. Add state `const [detailsDialogTypeId, setDetailsDialogTypeId] = useState<string | null>(null)`. Mount `<AgentTypeDetailsDialog open={detailsDialogTypeId !== null} agentTypeId={detailsDialogTypeId} onClose={() => setDetailsDialogTypeId(null)} />`. On dialog close, call `queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })` to auto-refresh the parent table.

Remove the `selectedType` state and the `useAgentInstances(selectedType?.id)` call (both unused after this task).

**Done when**: Clicking any agent type row opens `AgentTypeDetailsDialog` for that type; closing the dialog refreshes the agent types table; existing action buttons (Edit, Plan Preview, Launch) in the row still work correctly via `e.stopPropagation()`.

---

### Task 4.2 — Remove inline "active instances" sub-table from `AgentManagementPage`

**File**: `frontend/src/pages/agents/AgentManagementPage.tsx`

Delete the entire `{selectedType && ( <Box>...</Box> )}` block that renders the "Active instances for selected agent type" sub-table. Remove the `instances` state, `useTerminateInstance` usage if no longer needed elsewhere in this component, and the `statusColor` helper if unused. Remove unused imports (`useAgentInstances`, `useTerminateInstance`, `DeleteIcon` if only used in instance terminate action). Do not remove `useTerminateInstance` if it is still referenced elsewhere.

**Done when**: No "active instances" sub-table appears on the Agent Types page; no unused-import TypeScript errors; `AgentManagementPage` renders cleanly.

---

### Task 4.3 — Wire identity and role navigation links in dialog Details tab

> **⚠️ NEEDS REWORK**: The approach has changed. Instead of "View Identity"/"View Role" buttons that navigate to list pages, identity and role names must be rendered as clickable text that opens view dialogs in-place. See Task 3.5 for the replacement implementation.

**File**: `frontend/src/components/agents/AgentTypeDetailsDialog.tsx`

Ensure the "View Identity" button resolves the identity name from the fetched `AgentType.identity_id` and navigates to `/agents/identities`. Ensure the "View Role" button resolves the role name from `AgentType.role_id` and navigates to `/agents/roles`. If `identity_id` or `role_id` is null, disable the respective button. Buttons must call `onClose()` before navigating to prevent the dialog remaining open behind the new page.

**Done when**: ⚠️ Superseded by Task 3.5. Identity and role names render as clickable text that opens view dialogs; null values show non-clickable "\u2014".

---

### Task 4.4 — Add "Role" and "Identity" columns to Agent Types table

**File**: `frontend/src/pages/agents/AgentManagementPage.tsx`

Add two new columns to the Agent Types `<Table>`: **Role** and **Identity**. Each cell displays the human-readable name of the assigned role or identity, or "\u2014" when not assigned.

Name resolution: `AgentManagementPage` already has access to agent type data. Resolve names on the frontend by calling `useAgentRoles()` and `useAgentIdentities()` (the same hooks used by `AgentTypeForm`) to build `Map<id, name>` lookups. These hooks share the same React Query cache as the form, so no extra network requests occur when navigating from the form. No backend API changes are needed.

Column placement: insert "Role" and "Identity" after the existing "Status" column and before the "Actions" column.

**Done when**: The Agent Types table shows "Role" and "Identity" columns; names display correctly for assigned roles/identities; "\u2014" renders when not assigned; no extra network requests beyond the existing `useAgentRoles()` and `useAgentIdentities()` calls.

---

### Task 4.5 — Add "Edit" button to role and identity view dialogs

**Files**: `frontend/src/components/agents/AgentRoleViewDialog.tsx`, `frontend/src/components/agents/AgentIdentityViewDialog.tsx`

Add an "Edit" button to the dialog actions bar of both `AgentRoleViewDialog` and `AgentIdentityViewDialog`. Clicking "Edit" should either:
- Navigate to the role/identity edit page and close the view dialog, OR
- Open the existing role/identity edit form dialog (if one exists), replacing the view dialog

Follow the same pattern used by other view/edit dialog pairs in the codebase. Check `AgentRoleListPage` and `AgentIdentityListPage` to see how editing is currently triggered from those pages, and apply the same mechanism inside the view dialog.

**Done when**: Both `AgentRoleViewDialog` and `AgentIdentityViewDialog` render an "Edit" button in their actions bar; clicking it opens the edit experience (navigate or open edit dialog); edit flow completes and returns to the correct state.

---

## Phase 5 — Testing & Polish

### Task 5.1 — Add unit tests for `AgentTypeDetailsDialog`

**New file**: `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx`

Cover the following scenarios using Vitest + React Testing Library:
- Dialog renders with loading state when `agentTypeId` is set
- Details tab shows correct field values after data loads
- Tab switching renders the correct tab panel
- Plan Preview tab shows placeholder when plan is null
- Plan Preview tab shows plan steps when plan is populated
- Execution Logs tab shows session list
- "View Identity" button is disabled when `identity_id` is null
- "View Identity" button triggers navigation and closes dialog
- Dialog error handling: `PermissionDeniedAlert` appears when fetch fails

**Done when**: All tests pass (`npm test -- --run AgentTypeDetailsDialog`); no warnings about act() or missing providers.

---

### Task 5.2 — Update `AgentManagementPage` unit tests for new row-click behavior

**File**: `frontend/src/__tests__/AgentManagementPage.test.tsx`

Remove or update tests that verify the old inline "active instances" sub-table behavior (e.g., tests that expect an instances table to appear below the agent types table after row click). Add tests that verify:
- Clicking an agent type row opens `AgentTypeDetailsDialog` (mock the dialog component)
- `AgentTypeDetailsDialog` receives the correct `agentTypeId` prop
- Closing the dialog calls `queryClient.invalidateQueries` for agent types

**Done when**: All `AgentManagementPage` tests pass; no tests assert on the removed "active instances" sub-table.

---

### Task 5.3 — Add e2e tests for navigation group and dialog flows

**File**: `e2e/tests/agent-navigation.spec.ts` (new file)

Cover:
- "AI Agent" nav group is visible and expands/collapses on click
- Clicking "Agent Executions" navigates to `/agents/executions`
- Agent type filter dropdown filters the executions table
- Clicking an agent type row on the Agent Types page opens the details dialog
- Dialog shows Details, Plan Preview, and Execution Logs tabs
- Clicking "View Identity" closes the dialog and navigates to `/agents/identities`
- "View All Executions" button in the dialog navigates to `/agents/executions`

Use `page.route()` mocks for all API calls. Follow the existing pattern in `e2e/tests/agent-logs.spec.ts`.

**Done when**: `npx playwright test tests/agent-navigation.spec.ts` passes with all tests green.

---

### Task 5.4 — Update unit tests for refinements

**Files**: `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx`, `frontend/src/__tests__/AgentManagementPage.test.tsx`

Update existing unit tests to reflect the refinements:
- `AgentManagementPage.test.tsx`: add tests asserting "Role" and "Identity" column headers are present; assert role/identity names render correctly in rows; assert "\u2014" when not assigned
- `AgentTypeDetailsDialog.test.tsx`: replace assertions on "View Identity"/"View Role" buttons with assertions on clickable identity/role name text; assert that clicking the name opens `AgentIdentityViewDialog`/`AgentRoleViewDialog` (mock the dialogs); update dialog-width-related assertions if any; assert "\u2014" renders when `identity_id`/`role_id` is null

**Done when**: All updated unit tests pass (`npm test -- --run`); no stale assertions reference removed buttons.

---

### Task 5.5 — Update e2e tests for refinements

**File**: `e2e/tests/agent-navigation.spec.ts`

Update or extend the e2e test suite:
- Assert nav group renders children in order: Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs
- Assert "Role" and "Identity" columns are visible in the Agent Types table
- Assert clicking identity name in dialog Details tab opens an identity view dialog (not navigates away)
- Assert identity view dialog has an "Edit" button
- Assert clicking role name opens role view dialog with an "Edit" button

**Done when**: `npx playwright test tests/agent-navigation.spec.ts` passes with all tests green including the new refinement assertions.

---

## Completion Checklist

- [x] All five phases implemented and passing
- [ ] Refinements implemented: nav order, Role/Identity columns, dialog widths, clickable names, Edit buttons
- [x] No TypeScript errors (`npm run build` clean)
- [x] No hardcoded user-facing strings (all through `t()`)
- [x] All new i18n keys present in `en.json`
- [x] `nav.agentInstances` key and old "Agent Instances" strings removed or updated
- [x] `/agents/instances` route redirects to `/agents/executions`
- [x] Unit tests pass: `npm test -- --run`
- [x] E2e tests pass: `npx playwright test tests/agent-navigation.spec.ts`
- [x] Dialog error handling follows project standard (see `docs/config.yaml` conventions)
- [x] No backend changes required (confirmed by passing existing backend tests)
