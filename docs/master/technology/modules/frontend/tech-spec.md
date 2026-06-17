# Module: frontend — Tech Spec

## Overview

The frontend module covers the global application shell, MUI theming infrastructure, root bootstrap, and platform-wide API client and permission error handling infrastructure for the Parthenon Web UI. It defines the composed Material-UI theme (indigo/slate palette, Inter typography, refined shadows, and component overrides), provides it to the entire React tree via `ThemeProvider`, and houses the top-level layout shell (`AppShell`) that renders the sidebar drawer, AppBar, and routed page outlet. It also owns the Axios `apiClient` instance (with 401/403 interceptors), the permission denied event utilities, the global `PermissionErrorSnackbar` with "Request Access" integration, the `AccessDeniedPage` for route-level 403s, and the shared `extractErrorMessage` utility. No runtime state or backend changes are required for the theming concerns — the theme is a static constant.

---

## Key Components

### Theming

| Component | Description |
|-----------|-------------|
| `parthenon` | Composed MUI theme assembled from palette, typography, shadows, and components modules; exported from `frontend/src/theme/index.ts` as the single theme constant passed to `ThemeProvider` |
| `palette` | Color token definitions using an indigo/slate system; maps semantic roles (`primary`, `secondary`, `error`, `warning`, `background`, `text`, `divider`) to hex values aligned with the prototype's CSS variable tokens |
| `typography` | Inter font family (`@fontsource/inter`) with a five-weight hierarchy (300/400/500/600/700); defines heading variants h1–h6 and all MUI text variants |
| `shadows` | 25-element `Shadows` array replacing MUI defaults; three named levels (sm, md, lg); cards rest on shadow 1 and elevate to shadow 2 on hover |
| `components` | MUI component style overrides applied globally via the theme system; covers `MuiCard`, `MuiPaper`, `MuiButton`, `MuiChip`, `MuiListItemButton`, `MuiAppBar`, `MuiDrawer`, `MuiAvatar`, `MuiTableCell`, and `MuiTableRow` |

### App Bootstrap

| Component | Description |
|-----------|-------------|
| `ThemeProvider` | MUI context provider wrapping the entire React tree in `main.tsx`; positioned as the outermost wrapper inside `React.StrictMode` so all MUI components throughout `I18nextProvider`, `QueryClientProvider`, and `AuthProvider` consume the theme |
| `CssBaseline` | MUI global CSS reset rendered immediately inside `ThemeProvider`; applies `background.default` as the page background colour and normalises browser defaults |

### Layout Shell

| Component | Description |
|-----------|-------------|
| `AppShell` | Top-level layout component; renders a fixed sidebar `Drawer` (width `DRAWER_WIDTH`), a white-surface `AppBar` with `border-bottom` separator, a `<main>` outlet for routed page content, and mounts `PermissionErrorSnackbar` globally so all 403 denials surface without per-page handling. The sidebar is data-driven: three named collapsible groups (Agents, Integrations, System) and one standalone entry (Dashboard). Expansion state is managed by a single `expandedGroups: Record<string, boolean>` object. |
| `DRAWER_WIDTH` | Module-level constant defining sidebar pixel width (256 px); referenced by both the `Drawer` and the `main` offset margin |
| `NAV_GROUPS` | Declarative array of three sidebar groups: Agents (roles, identities, types, runtime control, skills, SOPs, model configs, schedules, agent trails), Integrations (MCP Hub, notifications), and System (observability, permissions, system config). Each group has `groupKey`, `labelKey`, `icon`, and `children: NavItem[]`. The Integrations group is locked open (`lockedOpen: true`). |
| `STANDALONE_ITEMS` | Declarative array of top-level sidebar entries not in any collapsible group. Currently a single Dashboard entry at `/dashboard`. |

### Sidebar Navigation

The sidebar render tree in `AppShell` is data-driven, defined entirely by the module-level constants `NAV_GROUPS` and `STANDALONE_ITEMS`. The render loop renders `STANDALONE_ITEMS` first as flat entries, then maps each group in `NAV_GROUPS` to a collapsible header `ListItemButton` plus a `Collapse` body containing the group's child entries. Expansion state for all groups is held in a single `expandedGroups: Record<string, boolean>` object initialised from `DEFAULT_EXPANDED_GROUPS`.

| Token | Description |
|-------|-------------|
| `DEFAULT_EXPANDED_GROUPS` | Record initialising all three groups to `true` so users see all items on first load |
| `expandedGroups` | `useState<Record<string, boolean>>` keyed by `groupKey`; replaces two prior separate `useState<boolean>` flags |
| `toggleGroup` | Handler that flips expansion for a given `groupKey`; skips groups marked `lockedOpen` |
| `isGroupActive` | Inline predicate computed per group; `group.children.some(c => c.path === location.pathname)`. Drives the group header `selected` state and force-expands the body on deep links |
| `showChildren` | Inline predicate; `isExpanded \|\| isGroupActive`. Passed to `<Collapse in={...}>` so an active child is always visible |

#### Sidebar Style Tokens

The sidebar uses module-level `sx` constants for consistent appearance:

| Token | Type | Description |
|-------|------|-------------|
| `SIDEBAR_ACCENT` | const | Accent colour for group header hover/active state (`#2563EB`) |
| `SIDEBAR_ACTIVE_BG` | const | Active-item background (`rgba(0, 0, 0, 0.03)`) |
| `SIDEBAR_HOVER_BG` | const | Hover background (`rgba(0, 0, 0, 0.02)`) |
| `SIDEBAR_FONT_SIZE` | const | Base font size (`15px`) |
| `SIDEBAR_CHILD_FONT_SIZE` | const | Child item font size (`13px`) |
| `SIDEBAR_CHILD_ICON_SIZE` | const | Child item icon size (`16px`) |
| `SIDEBAR_ICON_SIZE` | const | Standalone/group header icon size (`18px`) |
| `SIDEBAR_ITEM_RADIUS` | const | Item border radius (`8px`) |
| `itemButtonSx` | sx object | Shared styles for standalone items and group children; includes `mx: 4px`, `borderRadius: 8px`, `hover` and `Mui-selected` overrides |
| `childItemButtonSx` | sx object | Extends `itemButtonSx` with `pl: 4`, `py: 3px`, smaller font, `text.secondary` colour |
| `groupHeaderSx` | sx object | Group header styles; transparent background, accent colour on hover/active, no pill radius |
| `iconSx` | sx object | Icon slot for standalone items and group headers; `minWidth: 28`, `fontSize: 18px` |
| `childIconSx` | sx object | Icon slot for child items; `minWidth: 20`, `mr: 6px`, `fontSize: 16px` |
| `groupLabelTypographyProps` | sx object | Group label typography; `15px`, weight 600, `text.secondary` colour |

#### Tabbed Module Pages

The sidebar "Agent Trails" child item navigates to a consolidated tabbed page; "Notifications" navigates to another:

| Page | Route | Description |
|------|-------|-------------|
| `AgentTrailsPage` | `/agent-trails` | Tabbed view consolidating conversation history, agent executions, and results |
| `NotificationConfigPage` | `/notifications` | Tabbed view consolidating notification channels, groups, and logs |

### API Client

| Component | Description |
|-----------|-------------|
| `apiClient` | Axios instance with auth header injection and response interceptors; the 401 interceptor redirects to the OIDC login; the 403 interceptor calls `parsePermissionError` and fires `dispatchPermissionDeniedEvent` so `PermissionErrorSnackbar` can display a structured denial message |

### Permission Error Handling

| Component | Description |
|-----------|-------------|
| `parsePermissionError` | Extracts a `PermissionDeniedDetail` object from an Axios 403 error response body; returns `null` for non-403 or malformed responses |
| `dispatchPermissionDeniedEvent` | Fires the `parthenon:permissionDenied` custom DOM event carrying the `PermissionDeniedDetail` payload; decouples the interceptor from the snackbar component |
| `PERMISSION_DENIED_EVENT` | String constant `"parthenon:permissionDenied"` — the custom event name; shared between the dispatcher and the snackbar listener to avoid string duplication |
| `PermissionErrorSnackbar` | Global MUI Snackbar mounted in `AppShell`; listens for `PERMISSION_DENIED_EVENT`; displays the denial message and a "Request Access" action button that opens `RequestPermissionModal` with the full `PermissionDeniedDetail` context pre-filled |
| `RequestPermissionModal` | Controlled modal component; displays read-only permission context (resource type, action, resource ID); collects justification text; submits via `submitAccessRequest`; shows inline success/error feedback |
| `AccessDeniedPage` | Full-page route-level access denied view registered at `/access-denied`; reads `RequiredPermission` context from `useLocation().state` (placed there by the 403 handler when navigating); mirrors the approved prototype error-state card design |
| `extractErrorMessage` | Shared utility; extracts a human-readable message from an unknown error: reads `error.response.data.detail` for Axios errors, `error.message` for generic `Error` objects, or falls back to the provided `fallback` string; used consistently across `UsersPage`, `RolesPage`, `AccessRequestsPage`, and `GroupsPage` error alerts |

### Global Styles

| Component | Description |
|-----------|-------------|
| `index.css` | Root stylesheet loaded by Vite; provides global layout rules (full-height `html`/`body`, `box-sizing: border-box`); the legacy `font-family` stack was removed when Inter was adopted via the MUI theme |

---

## State Management

The MUI theme is a static constant — no runtime state is introduced. Dark-mode switching and runtime theme mutation are out of scope. `ThemeProvider` does not consume any store or context value; it wraps the tree at the module boundary.

`AppShell` manages sidebar group expansion via a single `expandedGroups: Record<string, boolean>` state object initialised from `DEFAULT_EXPANDED_GROUPS` (all groups expanded). The `toggleGroup` handler flips the boolean for a given `groupKey`. Expansion state is per-session only; it is not persisted across reloads.

`PermissionErrorSnackbar` manages local state: `open` boolean, `message` string, and `permissionContext: RequiredPermission | null`. The snackbar stores the full `PermissionDeniedDetail` on receipt of the DOM event so the "Request Access" button can pass context to `RequestPermissionModal`.

`RequestPermissionModal` is fully controlled via props (`open`, `onClose`, `permissionContext`). Internal state manages the justification textarea value, submission loading state, and success/error feedback.

`AccessDeniedPage` reads permission context from `useLocation().state` — no component state beyond modal open/close.

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `parthenon` | const | Composed MUI theme — palette + typography + shadows + components | `frontend/src/theme/index.ts` |
| `palette` | object | Color token definitions (indigo/slate) | `frontend/src/theme/palette.ts` |
| `typography` | object | Inter font family and weight-mapped variant scale | `frontend/src/theme/typography.ts` |
| `shadows` | array | 25-element refined shadow array | `frontend/src/theme/shadows.ts` |
| `components` | object | MUI component style overrides | `frontend/src/theme/components.ts` |
| `ThemeProvider` | component | Injects theme into React context | `frontend/src/main.tsx` |
| `CssBaseline` | component | Global CSS reset applying theme background | `frontend/src/main.tsx` |
| `AppShell` | component | Top-level layout — sidebar drawer, AppBar, page outlet; mounts `PermissionErrorSnackbar` globally; sidebar is driven by `NAV_GROUPS` (3 collapsible groups) + `STANDALONE_ITEMS` (Dashboard); expansion state managed by `expandedGroups: Record<string, boolean>` | `frontend/src/app/AppShell.tsx` |
| `DRAWER_WIDTH` | const | Sidebar pixel width — 256 px | `frontend/src/app/AppShell.tsx` |
| `NAV_GROUPS` | const | Declarative array of three sidebar groups (Agents, Integrations, System); each has `groupKey`, `labelKey`, `icon`, `children: NavItem[]`; Integrations group has `lockedOpen: true` | `frontend/src/app/AppShell.tsx` |
| `STANDALONE_ITEMS` | const | Declarative array of top-level sidebar entries not in any collapsible group (currently Dashboard at `/dashboard`) | `frontend/src/app/AppShell.tsx` |
| `NavItem` | interface | TypeScript shape for a single sidebar entry (`labelKey: string`, `path: string`, `icon: React.ReactNode`) | `frontend/src/app/AppShell.tsx` |
| `NavGroup` | interface | TypeScript shape for a collapsible sidebar group (`groupKey: string`, `labelKey: string`, `icon: React.ReactNode`, `children: NavItem[]`, `lockedOpen?: boolean`) | `frontend/src/app/AppShell.tsx` |
| `AppRouter` | component | Route configuration; first-run redirect guard (`getIdentityStatus` on mount); registers `/agents/executions` route and `/agents/instances` → `/agents/executions` redirect for backward compatibility; registers `/access-denied` route for `AccessDeniedPage` | `frontend/src/app/AppRouter.tsx` |
| `index.css` | stylesheet | Global root layout rules (font-family removed, Inter via MUI theme) | `frontend/src/styles/index.css` |

### Sidebar Navigation

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DEFAULT_EXPANDED_GROUPS` | const | Initial expansion state for all three groups (all `true`); seeds the `expandedGroups` `useState` | `frontend/src/app/AppShell.tsx` |
| `expandedGroups` | state | `useState<Record<string, boolean>>` keyed by `groupKey`; replaces two legacy `useState<boolean>` flags | `frontend/src/app/AppShell.tsx` |
| `toggleGroup` | function | Toggles the `expandedGroups` entry for a given `groupKey`; skips groups with `lockedOpen: true` | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_ACCENT` | const | Accent colour for group header hover/active state (`#2563EB`) | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_ACTIVE_BG` | const | Active-item background (`rgba(0, 0, 0, 0.03)`) | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_HOVER_BG` | const | Hover background (`rgba(0, 0, 0, 0.02)`) | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_FONT_SIZE` | const | Base font size for standalone items and group headers (`15px`) | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_CHILD_FONT_SIZE` | const | Font size for child items (`13px`) | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_CHILD_ICON_SIZE` | const | Icon size for child items (`16px`) | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_ICON_SIZE` | const | Icon size for standalone items and group headers (`18px`) | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_ITEM_RADIUS` | const | Border radius for items (`8px`) | `frontend/src/app/AppShell.tsx` |
| `itemButtonSx` | const | Shared `sx` for standalone and child items — font size, white-space, `mx: 4px`, `borderRadius: 8px`, hover and `Mui-selected` overrides | `frontend/src/app/AppShell.tsx` |
| `childItemButtonSx` | const | `sx` for child items — extends `itemButtonSx` with `pl: 4`, `py: 3px`, smaller font, `text.secondary` colour | `frontend/src/app/AppShell.tsx` |
| `groupHeaderSx` | const | `sx` for group headers — transparent background, accent colour hover/active, no pill radius | `frontend/src/app/AppShell.tsx` |
| `iconSx` | const | `sx` for `ListItemIcon` slots — `minWidth: 28`, `fontSize: 18px` | `frontend/src/app/AppShell.tsx` |
| `childIconSx` | const | `sx` for child item `ListItemIcon` slots — `minWidth: 20`, `mr: 6px`, `fontSize: 16px` | `frontend/src/app/AppShell.tsx` |
| `groupLabelTypographyProps` | const | `primaryTypographyProps` for group header `ListItemText` — `15px`, weight 600, `text.secondary` colour | `frontend/src/app/AppShell.tsx` |
| `nav.groupAgents` | i18n key | English label "Agents" for the Agents group header | `frontend/src/i18n/locales/en.json` |
| `nav.groupIntegrations` | i18n key | English label "Integrations" for the Integrations group header | `frontend/src/i18n/locales/en.json` |
| `nav.groupSystem` | i18n key | English label "System" for the System group header | `frontend/src/i18n/locales/en.json` |
| `AppShell` test suite | test file | Vitest + Testing Library tests for the sidebar; asserts the new group structure and relocated child items | `frontend/src/__tests__/AppShell.test.tsx` |

### Tabbed Module Pages

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentTrailsPage` | component | Tabbed view consolidating agent executions (tab 0), results (tab 1), and conversation history (tab 2) at `/agent-trails` | `frontend/src/pages/trails/AgentTrailsPage.tsx` |
| `NotificationConfigPage` | component | Tabbed view consolidating notification channels, groups, and logs at `/notifications` | `frontend/src/pages/notifications/NotificationConfigPage.tsx` |

### API Client & Permission Error Infrastructure

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `API_CONFIG` | config object | Defines frontend REST and WebSocket base endpoints used by `apiClient` and chat/session hooks | `frontend/src/api/API_CONFIG.ts` |
| `apiClient` | axios instance | HTTP client with auth header injection; 401 interceptor redirects to OIDC login; 403 interceptor calls `parsePermissionError` and fires `dispatchPermissionDeniedEvent` | `frontend/src/api/apiClient.ts` |
| `parsePermissionError` | function | Extracts `PermissionDeniedDetail` from an Axios 403 error response body; returns `null` for non-403 or malformed payloads | `frontend/src/utils/permissionError.ts` |
| `dispatchPermissionDeniedEvent` | function | Fires `parthenon:permissionDenied` custom DOM event carrying the `PermissionDeniedDetail` payload | `frontend/src/utils/permissionError.ts` |
| `PERMISSION_DENIED_EVENT` | constant | Custom event name `"parthenon:permissionDenied"` shared between dispatcher and snackbar listener | `frontend/src/utils/permissionError.ts` |
| `PermissionErrorSnackbar` | component | Global MUI Snackbar in `AppShell`; listens for `PERMISSION_DENIED_EVENT`; displays denial message + "Request Access" button that opens `RequestPermissionModal` with full `PermissionDeniedDetail` context | `frontend/src/components/permissions/PermissionErrorSnackbar.tsx` |
| `RequestPermissionModal` | component | Controlled modal; displays read-only permission context (resource type, action, ID); collects justification; submits via `submitAccessRequest`; shows inline success/error feedback | `frontend/src/components/permissions/RequestPermissionModal.tsx` |
| `AccessDeniedPage` | component | Full-page route-level 403 view at `/access-denied`; reads `RequiredPermission` from `useLocation().state`; mirrors the approved prototype error-state card design | `frontend/src/pages/AccessDeniedPage.tsx` |
| `extractErrorMessage` | function | Shared utility: reads `error.response.data.detail` (Axios), `error.message` (Error), or falls back to provided `fallback` string; used across `UsersPage`, `RolesPage`, `AccessRequestsPage`, and `GroupsPage` | `frontend/src/utils/errorUtils.ts` |
| `useDialogErrorHandler` | hook | Reusable hook implementing the Dialog Error Handling Standard: manages `dialogError` state, clear-on-open/close lifecycle, and error display pattern used by all dialogs with API calls | `frontend/src/hooks/useDialogErrorHandler.ts` |
| `toolNaming` | utility module | Shared frontend naming/slug formatting helpers used for consistent slug validation and normalization across MCP and agent surfaces | `frontend/src/utils/toolNaming.ts` |

### Agent Guardrails & Execution Summary UI

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `LogPresenter` | service module | Derives guardrail usage summaries and conversational token-usage visibility from execution log entries | `frontend/src/services/LogPresenter.ts` |
| `LogSummaryPanel` | component | Renders execution summary chips including guardrail usage and token-visibility information | `frontend/src/components/executions/LogSummaryPanel.tsx` |
| `AgentTypeForm` | component | Agent Type editor surface where guardrail policy values are configured and displayed in k-token units | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentTypeDetailsDialog` | component | Read-only/details surface that presents the configured guardrail profile for an Agent Type | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |

### Segregation Audit Coverage

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useChatSession` | hook | Manages WebSocket session lifecycle and chat turn transport to Communication Hub with API-only frontend boundaries | `frontend/src/hooks/useChatSession.ts` |
| `service-segregation-security-audit` | frontend test | Verifies frontend boundary stays API/WS-only and does not introduce direct database transport references | `frontend/src/__tests__/service-segregation-security-audit.test.ts` |
