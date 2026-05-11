# Technical Specification: unified-agent-navigation

## Technical Overview

This change is purely a frontend UI reorganization. It restructures the `AppShell` navigation into a collapsible grouped sidebar, renames the "Agent Instances" page to "Agent Executions" and adds agent-type filtering to it, and introduces a new `AgentTypeDetailsDialog` component that replaces the broken inline "active instances" sub-table on the Agent Types page.

All data access uses existing backend endpoints — no new API endpoints are needed. The `GET /agents/sessions?agent_type_id=` query parameter already exists in the backend. State management remains in React Query with local component state for dialog open/close. The dialog's three-tab structure (Details, Plan Preview, Execution Logs) consolidates information currently spread across multiple pages.

---

## Component Breakdown

### Modified Components

**`AppShell`** (`frontend/src/app/AppShell.tsx`)
- Replaces the flat `NAV_ITEMS` array with a mixed structure: flat items + a collapsible `NavGroup` for "AI Agent"
- Adds `NavGroup` type: `{ groupKey: string; labelKey: string; icon: React.ReactNode; children: NavItem[] }`
- "AI Agent" group positioned after Model Configs menu item (between Model Configs and Gateway)
- "AI Agent" group children (five items): Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs
- Agent Roles and Agent Identities are existing pages being reorganized — their routes (`/agents/roles`, `/agents/identities`) are unchanged; only their nav registration moves from the flat list into the group
- Group expand/collapse managed by local state; defaults to expanded
- Group header highlights when any child route is active (`location.pathname.startsWith('/agents') || location.pathname === '/conversations'`)
- Uses MUI `Collapse`, `ExpandMore`, `ExpandLess` icons

**`AgentManagementPage`** (`frontend/src/pages/agents/AgentManagementPage.tsx`)
- Row `onClick` changed from `setSelectedType(at)` → `setDetailsDialogTypeId(at.id)`
- New state: `detailsDialogTypeId: string | null`
- Removed state: `selectedType`, `instances` (from `useAgentInstances`)
- Removed: inline "Active instances" sub-table block and `useTerminateInstance` (if no longer needed here)
- Added: `AgentTypeDetailsDialog` mount with `onClose` that invalidates `['agents', 'types']` query
- Existing row action buttons (Edit, Launch, Plan Preview) retain `e.stopPropagation()`
- New table columns: **Role** (displays role name) and **Identity** (displays identity name) inserted after the "Status" column; cells show `"—"` when the field is not assigned
- Role and identity names resolved on the frontend: fetches all roles via `useAgentRoles()` and all identities via `useAgentIdentities()` (same hooks used by `AgentTypeForm`), builds `Map<id, name>` lookups; no additional network requests because these hooks share the React Query cache with the form

**`AgentInstanceDashboardPage`** (`frontend/src/pages/agents/AgentInstanceDashboardPage.tsx`)
- Renamed from "Agent Instances" to "Agent Executions" in all display strings (via i18n keys)
- Added `agentTypeId` optional prop (`string | undefined`) for embedding in dialog
- Added `agentTypeId` filter state (only applies when prop not set)
- Added MUI `Select` dropdown in filter toolbar: fetches agent types via `useAgentTypes()`, renders all type names
- When `agentTypeId` prop is set, pre-selects dropdown and skips the prop-driven value from state
- Passes `agent_type_id` query param to `GET /agents/sessions` when filter active
- `agentTypeId` included in React Query key

**`AppRouter`** (`frontend/src/app/AppRouter.tsx`)
- New route: `/agents/executions` → `AgentInstanceDashboardPage`
- New redirect: `/agents/instances` → `/agents/executions` (backward compatibility)
- No other route changes; all other agent routes (`/agents`, `/agents/roles`, `/agents/identities`, `/agents/sessions/:id`) unchanged — Agent Roles and Identities routes remain in place; only their nav group membership changes in `AppShell.tsx`

### New Components

**`AgentTypeDetailsDialog`** (`frontend/src/components/agents/AgentTypeDetailsDialog.tsx`)
- Props: `open: boolean`, `agentTypeId: string | null`, `onClose: () => void`
- Fully responsive dialog (`fullWidth`, `maxWidth` matching `PlanPreviewModal` — as wide as possible)
- Fetches agent type data with `useAgentType(agentTypeId ?? '')` (enabled when `agentTypeId` non-null)
- Dialog error handling: `dialogError` state, `PermissionDeniedAlert` at top of `DialogContent`
- Three MUI `Tabs`: Details, Plan Preview, Execution Logs
- Tab state resets to 0 (Details) on each open via `useEffect([open])`
- Mounts `AgentJobLaunchDialog` for "Run Agent" action

**`AgentRoleViewDialog`** (`frontend/src/components/agents/AgentRoleViewDialog.tsx`)
- Standalone view dialog for a single agent role
- Props: `open: boolean`, `roleId: string | null`, `onClose: () => void`
- Fetches role data via `useAgentRole(roleId)`
- Displays role fields in a two-column detail grid
- Actions bar: "Edit" button (opens role edit experience — navigate to edit page or open edit dialog, matching the pattern used in `AgentRoleListPage`) and "Close" button
- Opened from the clickable role name in `AgentTypeDetailsDialog` Details tab

**`AgentIdentityViewDialog`** (`frontend/src/components/agents/AgentIdentityViewDialog.tsx`)
- Standalone view dialog for a single agent identity
- Props: `open: boolean`, `identityId: string | null`, `onClose: () => void`
- Fetches identity data via `useAgentIdentity(identityId)`
- Displays identity fields in a two-column detail grid
- Actions bar: "Edit" button (opens identity edit experience, matching the pattern used in `AgentIdentityListPage`) and "Close" button
- Opened from the clickable identity name in `AgentTypeDetailsDialog` Details tab

**Details tab** (inside `AgentTypeDetailsDialog`):
- Two-column label/value grid: Name, Description, Status (Chip), LLM Model, Input Type, Output Type, Primary SOP (when applicable), System Prompt (truncated `<pre>` block), Role (clickable name text), Identity (clickable name text)
- Role name rendered as clickable `<Link>`-style text in the grid; clicking opens `AgentRoleViewDialog` for the linked role; renders non-clickable "—" when `role_id` is null
- Identity name rendered as clickable text in the grid; clicking opens `AgentIdentityViewDialog` for the linked identity; renders non-clickable "—" when `identity_id` is null
- Action button: "Run Agent" (opens `AgentJobLaunchDialog`)
- "View Identity" and "View Role" buttons removed (replaced by clickable name text above)

**Plan Preview tab** (inside `AgentTypeDetailsDialog`):
- Renders plan steps and topology from `agentType.plan`
- Reuses content components extracted from `PlanPreviewModal` (see `AgentPlanContent` below), or inline renders plan steps + topology nodes if extraction is not done in this change
- Placeholder text when plan is null

**Execution Logs tab** (inside `AgentTypeDetailsDialog`):
- Fetches `GET /agents/sessions?agent_type_id=<id>&limit=10` via `useQuery`
- React Query key: `['agents', 'sessions', 'dialog', agentTypeId]`
- Renders compact table: Session ID (truncated), Status (Chip), Created At, "View" button
- "View" button opens `AgentExecutionDetailsDialog` (shows full execution details in dialog)
- "View All Executions" button opens `AgentExecutionsDialog` (shows full execution list in dialog, does not navigate away)
- Empty state when no executions exist

### Extracted Shared Component

**`AgentPlanContent`** (`frontend/src/components/agents/AgentPlanContent.tsx`)
- Presentational component: receives `plan: AgentPlan | null | undefined` and optional `noPlanMessage: string`
- Renders plan step list and topology diagram (extracted from `PlanPreviewModal`)
- Used by both `PlanPreviewModal` and the Plan Preview tab of `AgentTypeDetailsDialog`

---

## API Changes

No new backend API endpoints are required for this change.

Existing endpoints used:

| Endpoint | Used by | Notes |
|---|---|---|
| `GET /agents/types` | `AgentManagementPage`, `AgentTypeDetailsDialog` (via `useAgentTypes`/`useAgentType`) | No change |
| `GET /agents/types/:id` | `AgentTypeDetailsDialog` (via `useAgentType`) | No change |
| `GET /agents/sessions?agent_type_id=` | `AgentInstanceDashboardPage`, Execution Logs tab | `agent_type_id` filter already supported by backend |
| `GET /agents/sessions?status=&from_date=&to_date=` | `AgentInstanceDashboardPage` | No change |
| `GET /agents/roles` | `AgentTypeForm`, `AgentManagementPage` (name resolution for Role column) | Now also fetched in `AgentManagementPage` to build role name lookup; uses same React Query cache key so no additional network request when navigating from the form |
| `GET /agents/identities` | `AgentTypeForm`, `AgentManagementPage` (name resolution for Identity column) | Now also fetched in `AgentManagementPage` to build identity name lookup; same cache-sharing behaviour as roles |
| `GET /agents/roles/:id` | `AgentRoleViewDialog` (via `useAgentRole`) | Existing endpoint; no change |
| `GET /agents/identities/:id` | `AgentIdentityViewDialog` (via `useAgentIdentity`) | Existing endpoint; no change |

---

## State Management

All state is managed in local React component state and React Query. No global store changes.

| State | Location | Type | Purpose |
|---|---|---|---|
| `mobileOpen` | `AppShell` | `boolean` | Sidebar toggle on mobile |
| `aiAgentGroupExpanded` | `AppShell` | `boolean` | AI Agent nav group expand/collapse |
| `detailsDialogTypeId` | `AgentManagementPage` | `string \| null` | Controls which agent type's dialog is open |
| `dialogError` | `AgentTypeDetailsDialog` | `unknown` | Dialog-level error display |
| `activeTab` | `AgentTypeDetailsDialog` | `number` | Currently selected tab (0=Details, 1=Plan, 2=Logs) |
| `launchOpen` | `AgentTypeDetailsDialog` | `boolean` | Controls `AgentJobLaunchDialog` within dialog |
| `filterAgentTypeId` | `AgentInstanceDashboardPage` | `string` | Agent type filter dropdown value |
| `filterStatus` | `AgentInstanceDashboardPage` | `AgentJobStatus \| ''` | Existing status filter |
| `fromDate`, `toDate` | `AgentInstanceDashboardPage` | `string` | Existing date range filters |

---

## Data Access Patterns

**Agent Types list** — `AgentManagementPage` fetches all agent types via `useAgentTypes()` (query key `['agents', 'types']`). After `AgentTypeDetailsDialog` closes, `AgentManagementPage` calls `queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })` to ensure the table reflects any changes made inside the dialog (e.g., plan generation triggered by a launch).

**Single Agent Type details** — `AgentTypeDetailsDialog` fetches via `useAgentType(agentTypeId)` (query key `['agents', 'types', agentTypeId]`). Only enabled when `agentTypeId` is non-null. Data includes `plan` field for the Plan Preview tab.

**Executions filtered by agent type** — `AgentInstanceDashboardPage` appends `agent_type_id` to its existing `GET /agents/sessions` call when a filter is active. The Execution Logs tab inside `AgentTypeDetailsDialog` makes a separate, narrower query (`limit=10`) using a distinct query key to avoid interfering with the page-level cache.

**Agent Types for filter dropdown** — `AgentInstanceDashboardPage` uses `useAgentTypes()` to populate the filter dropdown. The result is cached under the same query key as the Agent Types page, so no extra network call when navigating from that page.

---

## Code Reference Map

### New Files

| File | Description |
|---|---|
| `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` | New dialog component: agent type details, plan preview, execution logs tabs |
| `frontend/src/components/agents/AgentExecutionsDialog.tsx` | New dialog wrapper for `AgentInstanceDashboardPage`: shows execution list in dialog context |
| `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` | New dialog wrapper for `AgentJobPage`: shows execution details and logs in dialog context |
| `frontend/src/components/agents/AgentPlanContent.tsx` | New presentational component for plan steps + topology (extracted from `PlanPreviewModal`) |
| `frontend/src/components/agents/AgentRoleViewDialog.tsx` | New view dialog for a single agent role: detail grid + Edit and Close actions |
| `frontend/src/components/agents/AgentIdentityViewDialog.tsx` | New view dialog for a single agent identity: detail grid + Edit and Close actions |
| `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` | Unit tests for `AgentTypeDetailsDialog`: loading state, all three tabs, clickable name behaviour, error handling, tab reset |
| `e2e/tests/agent-navigation.spec.ts` | E2e tests for nav group, executions page, filter dropdown, dialog flows, refinement assertions |

### Modified Files

| File | Change Summary |
|---|---|
| `frontend/src/app/AppShell.tsx` | Add `NavGroup` type; restructure nav to collapsible "AI Agent" group with children in order: Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs; remove those items from flat nav list; add group expand state |
| `frontend/src/app/AppRouter.tsx` | Add `/agents/executions` route; add `/agents/instances` → `/agents/executions` redirect |
| `frontend/src/pages/agents/AgentManagementPage.tsx` | Replace `selectedType` row-click with `detailsDialogTypeId`; remove inline instances sub-table; add `AgentTypeDetailsDialog` mount; add "Role" and "Identity" columns resolved via `useQuery(['agents','roles'])` / `useQuery(['agents','identities'])` Maps; add `useQuery` import |
| `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` | Add `agentTypeId` prop and filter state; add agent type dropdown to filter toolbar; add execution details dialog state and mount; View button opens `AgentExecutionDetailsDialog` instead of navigating; update i18n strings for "Executions" rename |
| `frontend/src/pages/agents/AgentJobPage.tsx` | Add `sessionId` prop for embedded usage; conditionally hide back button when embedded in dialog |
| `frontend/src/i18n/locales/en.json` | Add `nav.aiAgent`, `nav.agentTypes`, `nav.agentExecutions`, `nav.agentLogs`, `nav.agentRoles`, `nav.agentIdentities`; add `agents.roles.viewTitle`, `agents.identities.viewTitle`, `agents.sessions.detailsTitle`; update `agents.sessions.dashboardTitle`; remove `nav.agentInstances` |
| `frontend/src/__tests__/AgentManagementPage.test.tsx` | Added `useAgentType` to useAgentTypes mock; added `defaultAgentTypeFormValues` mock with `input_type: 'typed'`; fixed pre-existing plan preview test failures; added row-click behaviour tests; added Role/Identity column tests |
| `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` | Updated dialog to `maxWidth="xl"` with `PaperProps` matching `PlanPreviewModal`; replaced "View Identity"/"View Role" buttons with clickable `<Link>` text opening `AgentRoleViewDialog`/`AgentIdentityViewDialog`; added role/identity name resolution via `useQuery(['agents','roles'])` and `useQuery(['agents','identities'])`; View button in execution logs opens `AgentExecutionDetailsDialog`; onLaunched callback opens `AgentExecutionDetailsDialog`; added view dialog state and mounts |

### Key Existing Files (Unchanged, Referenced)

| File | Role in this change |
|---|---|
| `frontend/src/hooks/useAgentTypes.ts` | Provides `useAgentTypes()` and `useAgentType(id)` hooks used by new dialog and updated dashboard |
| `frontend/src/components/agents/PlanPreviewModal.tsx` | Plan display logic; content may be extracted to `AgentPlanContent` |
| `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` | Reused inside `AgentTypeDetailsDialog` for "Run Agent" action |
| `frontend/src/pages/agents/AgentJobPage.tsx` | Session detail page; linked from Execution Logs tab "View" button |
| `frontend/src/pages/agents/AgentIdentityListPage.tsx` | Existing page moved into the AI Agent nav group (Task 1.4); route `/agents/identities` unchanged; also the target of "View Identity" navigation from `AgentTypeDetailsDialog` |
| `frontend/src/pages/agents/AgentRoleListPage.tsx` | Existing page moved into the AI Agent nav group (Task 1.4); route `/agents/roles` unchanged; also the target of "View Role" navigation from `AgentTypeDetailsDialog` |
| `frontend/src/components/permissions/PermissionDeniedAlert.tsx` | Used for dialog error display per project convention |
| `frontend/src/types/index.ts` | `AgentType`, `AgentJob`, `AgentPlan`, `AgentJobStatus` types; no changes needed |
| `backend/app/api/v1/agents.py` | Provides `GET /agents/sessions?agent_type_id=` filter (line ~485); no changes |
