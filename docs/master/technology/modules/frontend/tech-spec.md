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
| `NAV_GROUPS` | Declarative array of three sidebar groups: Agents (roles, identities, types, agent management panel, runtime control, skills, SOPs, model configs, schedules, agent trails), Integrations (MCP Hub, notifications), and System (observability, permissions, system config). Each group has `groupKey`, `labelKey`, `icon`, and `children: NavItem[]`. The Integrations group is locked open (`lockedOpen: true`). |
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

### Agent Response Rendering

Reusable components and utilities for rendering agent response content. The `ContentRenderer` component detects whether content contains HTML markup and routes through the appropriate rendering pipeline: DOMPurify-sanitized HTML, markdown-to-HTML conversion, or plain pre-formatted text. The `MaximizableContent` component wraps any content area with a maximize button that opens a full-view MUI Dialog — it is a pure layout decorator that does not alter content rendering. Both are platform-wide reusable infrastructure, not tied to any specific agent page.

#### Content Rendering Components

| Component | Description |
|-----------|-------------|
| `ContentRenderer` | Inspects a content string and renders through sanitized HTML, markdown conversion, or plain text based on detected format and `mode` prop (`'auto'` or `'chat'`); handles null/undefined/empty content gracefully |
| `MaximizableContent` | Wraps children with a maximize icon button positioned absolutely in the top-right corner; clicking opens a fullscreen MUI `Dialog` containing the same children; accepts optional `title` prop for the dialog header; manages `isMaximized` boolean as internal React state |

#### Content Detection & Sanitization Utilities

| Component | Description |
|-----------|-------------|
| `containsHtmlTags` | Stateless regex-based function; tests whether a string contains HTML markup by matching opening (`<letter`) and closing (`</letter`) tag patterns; avoids false positives on comparison operators |
| `sanitizeHtml` | Synchronous wrapper around DOMPurify's `sanitize()`; strips disallowed tags and attributes from HTML strings; called by `ContentRenderer` before `dangerouslySetInnerHTML` |

#### Markdown Utilities

| Component | Description |
|-----------|-------------|
| `simpleMarkdownToHtml` | Converts markdown text to HTML; extracted from `OutputTypeResultTab.tsx` to a shared utility file so both `OutputTypeResultTab` and `ContentRenderer` can import it without circular dependencies |
| `escapeHtml` | Escapes HTML special characters (`&`, `<`, `>`, `"`, `'`) in a string for safe embedding in HTML context |

### Execution Result Display

Components responsible for rendering agent execution results. The `OutputTypeResultTab` component is the central dispatcher that inspects an output's type and renders it appropriately — it now delegates HTML-aware rendering to `ContentRenderer` and wraps results with `MaximizableContent`.

| Component | Description |
|-----------|-------------|
| `OutputTypeResultTab` | Central dispatcher for rendering execution results by output type (`auto`, `markdown`, `typed`); the `auto` branch now uses `ContentRenderer` with `mode="auto"` instead of calling `simpleMarkdownToHtml` directly; `markdown` and `typed` branches are unchanged in rendering logic |
| `OutputTypeResultTabProps` | TypeScript interface defining the props contract for `OutputTypeResultTab` (output data, schema, and rendering context); schema unchanged by this change |
| `extractResultText` | Helper function that extracts plain text from content block arrays or strings; used internally by `OutputTypeResultTab` |
| `badgeForType` | Helper function returning badge style configuration (color, label) for a given output type; used internally by `OutputTypeResultTab` |

### Agent Chat Interfaces

Existing chat interface components that now integrate `ContentRenderer` and `MaximizableContent` for improved agent response rendering.

| Component | Description |
|-----------|-------------|
| `ConversationDialog` | Dialog-based chat interface for conversational agents; agent messages (`msg.role !== 'user'`) now rendered via `ContentRenderer` with `mode="chat"` and wrapped with `MaximizableContent`; user messages unchanged |
| `AgentJobPage` | Standalone agent session page with chat and result views; chat interface and conversation history view both use `ContentRenderer`/`MaximizableContent` for agent messages; the standalone markdown rendering path for `session.output_data.markdown` remains unchanged (not routed through `ContentRenderer` since data is already markdown-safe) |
| `AgentExecutionDetailsDialog` | Tabbed execution detail dialog showing full session details and logs; uses `OutputTypeResultTab` for the Result tab, gaining the new HTML-aware rendering |
| `SessionExecutionLogsDialog` | Session execution logs dialog with result tab; benefits from the same `OutputTypeResultTab` improvements |

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
| `AppRouter` | component | Route configuration; first-run redirect guard (`getIdentityStatus` on mount); registers `/agents/executions` route and `/agents/instances` → `/agents/executions` redirect for backward compatibility; registers the protected `/agents/panel` route for the Agent Management Panel; registers `/access-denied` route for `AccessDeniedPage` | `frontend/src/app/AppRouter.tsx` |
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
| `extractErrorMessage` | function | Shared utility: reads `error.response.data.detail` (Axios - supports JSON object `detail` with `error`/`summary`/`messages` keys from FastAPI 422 responses), `error.message` (Error), or falls back to provided `fallback` string; used across `UsersPage`, `RolesPage`, `AccessRequestsPage`, `GroupsPage`, and `AgentManagementPage` for binding validation error display | `frontend/src/utils/errorUtils.ts` |
| `useDialogErrorHandler` | hook | Reusable hook implementing the Dialog Error Handling Standard: manages `dialogError` state, clear-on-open/close lifecycle, and error display pattern used by all dialogs with API calls | `frontend/src/hooks/useDialogErrorHandler.ts` |
| `toolNaming` | utility module | Shared frontend naming/slug formatting helpers used for consistent slug validation and normalization across MCP and agent surfaces | `frontend/src/utils/toolNaming.ts` |

### API Keys — UI Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ApiKeyListPage` | component | Main API key management page with table, filtering, search, empty/loading/error states | `frontend/src/pages/api-keys/ApiKeyListPage.tsx` |
| `CreateApiKeyDialog` | component | Two-step modal: form (identity+role selection) → key reveal with copy | `frontend/src/pages/api-keys/CreateApiKeyDialog.tsx` |
| `RevokeApiKeyDialog` | component | Confirmation modal for irreversible key revocation | `frontend/src/pages/api-keys/RevokeApiKeyDialog.tsx` |

### API Keys — Data Layer

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useApiKeys` | hook | React hook: fetches API key list with loading/error state, exposes `refresh()` | `frontend/src/hooks/useApiKeys.ts` |
| `fetchApiKeys` | function | HTTP GET `/api/v1/api-keys` — fetches key list with optional status filter | `frontend/src/api/apiKeysApi.ts` |
| `createApiKey` | function | HTTP POST `/api/v1/api-keys` — creates a new API key | `frontend/src/api/apiKeysApi.ts` |
| `revokeApiKey` | function | HTTP POST `/api/v1/api-keys/{key_id}/revoke` — revokes an API key | `frontend/src/api/apiKeysApi.ts` |
| `fetchIdentitiesWithRoles` | function | HTTP GET `/api/v1/api-keys/identities-with-roles` — dropdown data for create dialog | `frontend/src/api/apiKeysApi.ts` |
| `ApiKey` | interface | TypeScript type for API key list item | `frontend/src/types/apiKeys.ts` |
| `ApiKeyCreateRequest` | interface | TypeScript type for API key creation form data | `frontend/src/types/apiKeys.ts` |
| `ApiKeyCreateResponse` | interface | TypeScript type for API key creation response (includes one-time key) | `frontend/src/types/apiKeys.ts` |
| `ApiKeyStatus` | enum | TypeScript enum: `active` / `revoked` | `frontend/src/types/apiKeys.ts` |
| `IdentityWithRoles` | interface | TypeScript type for identity with available roles (dropdown data) | `frontend/src/types/apiKeys.ts` |

### Agent Guardrails & Execution Summary UI

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `LogPresenter` | service module | Derives guardrail usage summaries and conversational token-usage visibility from execution log entries | `frontend/src/services/LogPresenter.ts` |
| `LogSummaryPanel` | component | Renders execution summary chips including guardrail usage and token-visibility information | `frontend/src/components/executions/LogSummaryPanel.tsx` |
| `AgentTypeForm` | component | Agent Type editor surface where guardrail policy values are configured and displayed in k-token units | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentTypeDetailsDialog` | component | Read-only/details surface that presents the configured guardrail profile for an Agent Type | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |

### Agent Response Rendering — Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ContentRenderer` | component | Renders agent response content with HTML/markdown/plain-text auto-detection; supports `auto` and `chat` rendering modes; uses DOMPurify for sanitization and `simpleMarkdownToHtml` for markdown conversion | `frontend/src/components/ContentRenderer.tsx` |
| `MaximizableContent` | component | Wraps content area with a maximize icon button and full-view MUI Dialog; manages `isMaximized` boolean as local React state; accepts optional `title` prop | `frontend/src/components/MaximizableContent.tsx` |

### Agent Response Rendering — Utilities

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `containsHtmlTags` | function | Regex-based HTML tag detection in strings; matches opening (`<letter`) and closing (`</letter`) tag patterns without false positives on comparison operators | `frontend/src/utils/contentDetection.ts` |
| `sanitizeHtml` | function | Sanitizes HTML strings via DOMPurify's synchronous `sanitize()`; called by `ContentRenderer` before `dangerouslySetInnerHTML` | `frontend/src/utils/contentDetection.ts` |
| `simpleMarkdownToHtml` | function | Converts markdown text to HTML; extracted from `OutputTypeResultTab.tsx` to a shared utility for reuse by both `OutputTypeResultTab` and `ContentRenderer` | `frontend/src/utils/markdown.ts` |
| `escapeHtml` | function | Escapes HTML special characters (`&`, `<`, `>`, `"`, `'`) in a string for safe embedding in HTML context | `frontend/src/utils/markdown.ts` |

### Agent Response Rendering — Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ContentRenderer.test.tsx` | test | Unit tests for `ContentRenderer` covering auto/chat modes, HTML detection, markdown conversion, empty/null handling, and sanitization | `frontend/src/__tests__/ContentRenderer.test.tsx` |
| `MaximizableContent.test.tsx` | test | Unit tests for `MaximizableContent` covering maximize toggle, dialog open/close, title rendering, and escape key handling | `frontend/src/__tests__/MaximizableContent.test.tsx` |

### Execution Result Display

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OutputTypeResultTab` | component | Central dispatcher for rendering execution results by output type (`auto`, `markdown`, `typed`); the `auto` branch now uses `ContentRenderer` with `mode="auto"`; all branches wrap results with `MaximizableContent` | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `OutputTypeResultTabProps` | interface | TypeScript interface defining props for `OutputTypeResultTab` (output data, schema, context); schema unchanged | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `extractResultText` | function | Extracts plain text from content block arrays or strings; used internally by `OutputTypeResultTab` | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `badgeForType` | function | Returns badge style config (color, label) for a given output type; used internally by `OutputTypeResultTab` | `frontend/src/components/executions/OutputTypeResultTab.tsx` |

### Agent Chat Interfaces

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ConversationDialog` | component | Dialog-based chat interface for conversational agents; agent messages now rendered via `ContentRenderer` with `mode="chat"` and wrapped with `MaximizableContent` | `frontend/src/components/agents/ConversationDialog.tsx` |
| `AgentJobPage` | component | Standalone agent session page with chat and result views; chat and conversation history use `ContentRenderer`/`MaximizableContent` for agent messages; standalone markdown path for `session.output_data.markdown` remains unchanged | `frontend/src/pages/agents/AgentJobPage.tsx` |
| `AgentExecutionDetailsDialog` | component | Tabbed execution detail dialog; uses `OutputTypeResultTab` for the Result tab, gaining the new HTML-aware rendering pipeline | `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` |
| `SessionExecutionLogsDialog` | component | Session execution logs dialog with result tab; benefits from `OutputTypeResultTab` improvements via `ContentRenderer` and `MaximizableContent` | `frontend/src/pages/agents/SessionExecutionLogsDialog.tsx` |

### Segregation Audit Coverage

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useChatSession` | hook | Manages WebSocket session lifecycle and chat turn transport to Communication Hub with API-only frontend boundaries | `frontend/src/hooks/useChatSession.ts` |
| `service-segregation-security-audit` | frontend test | Verifies frontend boundary stays API/WS-only and does not introduce direct database transport references | `frontend/src/__tests__/service-segregation-security-audit.test.ts` |

---

## Multi-Tenancy Integration

The frontend gains multi-tenant surfaces since the multi-tenant support change (full details: [multi-tenancy module](../multi-tenancy/tech-spec.md)).

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| platform admin console | pages + guard (new) | `/platform/*` tenant management, platform settings, security audit; gated by `PlatformAdminRoute` + `usePlatformAccess` real-permission probe (never `multiTenancyEnabled` alone) | `frontend/src/app/PlatformRoutes.tsx` (+ `PlatformAdminRoute.tsx`, `frontend/src/hooks/usePlatformAccess.ts`, `frontend/src/pages/platform/`) |
| tenant workspace | pages (new) | Tenant settings (root-only alias edit, `LicenseUsagePanel`), guided onboarding, members/invitations | `frontend/src/pages/tenant/` |
| public sign-up + workspace sign-in | pages (new/modified) | `SignUpPage` (account-first registration), tenancy-aware `LoginPage` (password card, workspace-address finder, `?workspace=` deep link, discreet root-only super-admin entry) | `frontend/src/pages/auth/SignUpPage.tsx`, `frontend/src/pages/auth/LoginPage.tsx` |
| tenant state | store (modified) | `AuthProvider` holds `activeTenant`, `availableTenants`, tri-state `multiTenancyEnabled`; one session = one tenant | `frontend/src/stores/AuthContext.tsx` |
| tenant API clients | modules (new) | `tenantAuthApi` (discovery, register, login-password, remembered-slug hint), `platformAdminApi`, `tenantApi` | `frontend/src/api/tenantAuthApi.ts` (+ `platformAdminApi.ts`, `tenantApi.ts`) |
| `apiClient` self-heal | module (modified) | Attaches `X-Tenant` from the per-tab resolved slug; recognizes the middleware's fail-closed unknown-slug 403 and clears the invalid binding | `frontend/src/api/apiClient.ts` |
| quota-blocked UX | components (new) | `QuotaBlockedAlert` + `extractQuotaBlocked` rendering the structured quota contract on blocked actions | `frontend/src/components/tenant/QuotaBlockedAlert.tsx`, `frontend/src/utils/quotaErrorUtils.ts` |

---

## Optimized Plan UI (sandboxed-scripting-and-llm-mocking change)

Full details: [sandboxed-scripting module](../sandboxed-scripting/tech-spec.md).

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentOptimizedPlanTab` | component | Optimized Plan tab (panel index 4): steps with per-step "View script" links (open inline `ScriptViewDialog`), status/error surfacing, feedback textarea + submit, "Retire plan" (marks rows `retired` + full agent-type query-scope invalidation), absent/retired "next run offers optimization" hint | `frontend/src/components/agents/AgentOptimizedPlanTab.tsx` |
| `ScriptViewDialog` | component (new) | Inline python_source + description + version viewer replacing the removed standalone Scripts tab | `frontend/src/components/agents/ScriptViewDialog.tsx` |
| Opt-in launch flow | component (modified) | `AgentJobLaunchDialog` checks optimized-plan existence; opt-in dialog ("Run with optimization" / "Skip optimization") posts `optimize: true/false`; a `ready` plan launches directly | `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` |
| String output rendering | type (modified) | `AgentJob.output_data` widened to `Record \| string`; raw script string output rendered as text; sandbox-validation chips via `t()` | `frontend/src/types/scripts.ts` |

> Removed: `AgentScriptsTab.tsx` (standalone Scripts registry tab) and `AgentOptimizeLogDialog.tsx` (verification-log surface retired) — do not reference them.

---

## Control Center Assistant & skill-binding surfaces (control-center-chatbot change)

Frontend work for the seeded assistant plus two supporting surfaces: the single-surface skill tool-binding editor and the topology canvas's pending-state contract. Backend/agent detail: [agents module](../agents/tech-spec.md); MCP entity gating: [mcp-hub module](../mcp-hub/tech-spec.md).

### Assistant entry point and conversation surface

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `openAssistant` | handler (new) | Launcher in the app shell: resolves the seeded `is_system` agent type from the existing agent-types query, honours the per-agent-type force-new-session flag, otherwise resolves the most recent ACTIVE conversation session (`GET /conversations?agent_type_id=…`, `updated_at` desc) and opens the dialog with that `sessionId`; falls back to a new session on empty/error. The dialog is NOT mounted while resolving (no empty-conversation flash) | `frontend/src/app/AppShell.tsx` |
| Assistant launcher (FAB) | component (new usage) | Floating entry point with a resolving spinner; rendered only when a system assistant exists | `frontend/src/app/AppShell.tsx` |
| `assistantSessionState` | utility module (new) | `markAssistantSessionEnded` / `consumeForceNewSessionFlag`: closing the dialog only disconnects the socket (the session stays `active` and is re-resolved on reopen); an explicit End sets a per-agent-type flag so the NEXT open starts a new session | `frontend/src/utils/assistantSessionState.ts` |
| `useAssistantModelConfig` | hook (new) | Typed react-query hook for `GET /agents/model-configs/assistant-model` (`selected_model_id`, `options`); `enabled` flag keeps non-assistant surfaces from querying | `frontend/src/hooks/useAssistantModelConfig.ts` |
| `ConversationDialog` (`assistantModelConfigCheck`) | component (modified) | When opened for the assistant: renders a guidance MUI Alert inside the chat surface with a "Configure model" action navigating to `/system-config` whenever the selection is null (or the backend surfaces `assistant_model_not_configured` mid-session), and disables input/send. Regular agent types are unaffected | `frontend/src/components/agents/ConversationDialog.tsx` |
| `ConversationDialog` action bar | component (modified) | Four-option footer for ALL conversational agents: **View All Sessions**, **New Session**, **End Session**, **Exit**. Switch/end are blocked while a turn is streaming (thinking/delegating/waiting/tool/waiting-for-human/delegation-resumed/recovering) | `frontend/src/components/agents/ConversationDialog.tsx` |
| `resetForSessionSwitch` / `handleStartNewSession` / `handleSwitchToSession` | functions (new) | Clear messages/delegation/guardrail state then `POST /conversations` (previous session stays active — end/archive is never called, no force-new flag); in-place resume via `POST /conversations/{id}/resume` | `frontend/src/components/agents/ConversationDialog.tsx` |
| `SessionSwitcherList` | component (new) | "View All Sessions" sessions-tab experience: **Show ended sessions** switch (default off → `status=active`), From/To date inputs defaulting to the last-7-days window, pagination (page size 10, `total`-driven), time-desc rows with title/status/updated time; ended sessions carry an "Ended" chip and are never resumable | `frontend/src/components/agents/ConversationDialog.tsx` |
| `DEFAULT_SESSIONS_WINDOW_DAYS` / `SESSIONS_PAGE_SIZE` | constants (new) | Mirror the backend default window (7 days) and page size (10) | `frontend/src/components/agents/ConversationDialog.tsx` |
| `useConversationSessionsPage` / `ConversationSessionsPageParams` / `ConversationSessionsPage` | hook + types (new) | Query for the paginated `GET /conversations/sessions` endpoint | `frontend/src/hooks/useConversationSessions.ts` |
| `mergeUnseenMessages` | function (new) | Merges a resumed turn list into rendered + live messages with dedupe, so a reply generated during a WS outage renders after reconnect | `frontend/src/components/agents/ConversationDialog.tsx` |
| `useChatSession` | hook (modified) | Parses structured `chat_error` payloads into `chatError` (actionable codes → dedicated guidance UI); unexpected close during a turn auto-reconnects with the SAME session id (max 5 attempts, `intentionalCloseRef` guards unmount) and bumps `recoveryEpoch` on success so consumers re-fetch `/resume` | `frontend/src/hooks/useChatSession.ts` |
| `ContentRenderer` (assistant messages) | component (reused) | Assistant/agent replies render in `auto` mode (sanitized HTML or formatted markdown — headings, lists, tables, code blocks); user messages stay plain-text bubbles | `frontend/src/components/ContentRenderer.tsx` |
| `InlineInterventionDialog` | component (modified) | Approval previews render markdown tables via `ContentRenderer`; Expand toggles a 90vw × 80vh dialog rendering the SAME preview full-width (inline preview scrolls horizontally). Approve/Deny share one handler pair across both surfaces — no duplicated state to desync. i18n: `conversations.sessions.intervention.expand` / `.collapse` / `.previewTitle` | `frontend/src/components/conversations/InlineInterventionDialog.tsx` |
| `SystemConfigPage` (assistant + workflow sections) | page (modified) | Two per-workspace model selectors: workflow-generation (tenant `TenantSetting` row) and assistant model (persisted onto the tenant's assistant agent type). Both offer only the tenant's enabled models with a "not configured" option | `frontend/src/pages/system/SystemConfigPage.tsx` |

### Skill tool bindings — one editor surface

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SkillEditor` (`selectedToolIds`) | component state (modified) | Single source of truth for bindings: initialises from `skill.tool_ids`; the detail payload is applied once per skill and never overwrites a user edit (`toolSelectionDirtyRef`). Save payload = the union of selected ids | `frontend/src/components/agents/SkillEditor.tsx` |
| `buildSkillToolEntries` | function (new) | Resolves each id from the browsable catalogue, degrading to the `tool_bindings` payload (`tool_id`, `name`, `original_name`, `server_slug`, `server_name`) when the tool cannot be browsed | `frontend/src/components/agents/SkillEditor.tsx` |
| `groupToolEntries` | function (new) | Groups entries by server slug (sorted) for the grouped list under the Select Tools button | `frontend/src/components/agents/SkillEditor.tsx` |
| Grouped binding list | component block (modified) | The grouped list IS both display and editor: `original_name` (falling back to `name`) + owning-server chip + canonical name; edit mode adds a per-entry remove control (explicit unbind — PUT replaces bindings), view mode is the same list without controls. The separate read-only "Bound Tools" card is removed | `frontend/src/components/agents/SkillEditor.tsx` |
| Referenced read-only group | component block (new) | Permission-gated `cc` entries absent from the catalogue are reconstructed from `tool_bindings`, shown checked + disabled + locked in a "Referenced (read-only)" group, and always included on save — a save can never silently drop a dependency the caller cannot see. Note: `skills.editor.referencedToolReadOnlyNote`. Other unbrowsable ids stay visible but removable | `frontend/src/components/agents/SkillEditor.tsx` |
| `SkillListPage` tool column | page (modified) | "N tools" count (`skills.toolCountValue`) with a native `title` tooltip listing bound tool names; an explicit muted "No tools bound" chip at zero bindings. Type: `Skill.tool_bindings?: SkillToolBindingInfo[]` | `frontend/src/pages/skills/SkillListPage.tsx` |

### Topology canvas pending states

`PanelTopologyCanvas` is the single canonical topology view (Agent Management Panel and the Agent Type Details preview). On a slow network it previously rendered bound entities as raw ids with no loading feedback. Three states are now strictly distinguished: **pending** (request in flight, name not cached → `pending: true` + loading label + spinner), **genuinely missing** (request completed, row absent → historical raw-id fallback), and **deliberately empty/set** (dashed placeholder or solid None/Conversation/Auto node).

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PanelTopologyPending` / `NO_PENDING` | types/const (new) | Typed per-entity in-flight flags (`identity`, `role`, `model`, `dataTypes`, `skills`, `sops`, `sopDetails`, `tools`) with an all-resolved default; flags come from each query's `isLoading` (`isPending && isFetching`, false when completed/disabled) | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `buildPanelTopology` (pending argument) | function (modified) | Gains an optional typed `PanelTopologyPending` argument; a pending bound entity renders the loading label instead of its raw id, a pending SOP composition child renders an indented `sop_pending_<sopId>` placeholder, and a pending tools zone renders `tool_pending` rather than the "No tools" placeholder (which now means a RESOLVED graph with nothing in it) | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `PanelTopologyLabels.loading` | label (new) | Localized loading label for pending entities (`agents.panel.topologyLoading`) | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `resolveRef` / `refLabel` | helpers (new) | Resolution order: resolved name (never pending — cached entities must not flicker) → loading label (pending) → raw id (missing) | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `TopologyNode.pending` | type field (new) | Optional, backwards-compatible pending marker consumed by the renderer; generic layered and plan-based renderers are unaffected | `frontend/src/types/index.ts` |
| `PendingSpinner` | component (new) | ViewBox-unit SVG spinner in the icon gutter (same `NODE_ICON_SIZE` geometry, so the graph never jumps when data arrives); `role="progressbar"`, localized `aria-label`/`<title>`, SMIL animation, no HTML overlay; pending nodes are inert (`data-pending="true"`, no click handlers, default cursor) | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` |
| `agents.panel.topologyLoading` | i18n key | "Loading…" | `frontend/src/i18n/locales/en.json` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ControlCenterAssistantEntry` / `AppShell.assistantSession` | frontend tests | Launcher resolution, resume of the latest active session, force-new-session after End, no dialog mount while resolving | `frontend/src/__tests__/ControlCenterAssistantEntry.test.tsx`, `frontend/src/__tests__/AppShell.assistantSession.test.tsx` |
| `ConversationDialog.actionBar` / `.sessionsView` / `.resumeLiveDelivery` | frontend tests | Action-bar lifecycle, sessions-tab filters/pagination/ended chips, reconnect reply recovery | `frontend/src/__tests__/ConversationDialog.actionBar.test.tsx`, `frontend/src/__tests__/ConversationDialog.sessionsView.test.tsx`, `frontend/src/__tests__/ConversationDialog.resumeLiveDelivery.test.tsx` |
| `AssistantModelConfigGuidance` | frontend test | Guidance alert, disabled input, "Configure model" navigation, mid-session error code mapping | `frontend/src/__tests__/AssistantModelConfigGuidance.test.tsx` |
| `SkillEditor.singleSurface` / `SkillsToolBindingsVisibility` | frontend tests | Single binding surface, referenced read-only pinning, table tool count and zero-binding chip | `frontend/src/__tests__/SkillEditor.singleSurface.test.tsx`, `frontend/src/__tests__/SkillsToolBindingsVisibility.test.tsx` |
| `PanelTopologyCanvas.test` / `TopologyDiagramRenderer.test` | frontend tests | Pending vs missing vs empty rendering, spinner accessibility, geometry stability | `frontend/src/__tests__/PanelTopologyCanvas.test.tsx`, `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` |
| `conversation-sessions.spec.ts` | E2E test | Sessions listing filters, date window, pagination, resume of active vs ended | `e2e/tests/conversation-sessions.spec.ts` |
