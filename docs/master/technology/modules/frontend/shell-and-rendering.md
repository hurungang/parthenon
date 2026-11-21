# Module: frontend — Shell, Theming and Rendering

> Part of the [frontend hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

This page covers the platform-wide UI foundation: the composed MUI theme, root bootstrap providers, the layout shell and sidebar navigation, permission-error handling, global styles, and the shared rendering pipeline for agent output (HTML detection/sanitisation, markdown, maximizable content, execution result display). It also covers the frontend half of multi-tenancy (platform console, tenant workspace, sign-in binding).

None of the theming concerns involve runtime state — the theme is a static constant. Shell expansion state is per-session only. Everything here is API/WebSocket-only: the browser never talks to a database.

---

## Theming and bootstrap

| Component | Description |
|-----------|-------------|
| `parthenon` | Composed MUI theme (palette + typography + shadows + component overrides), passed to `ThemeProvider` |
| `palette` | Indigo/slate semantic colour tokens aligned with the prototype's CSS variables |
| `typography` | Inter (`@fontsource/inter`) five-weight hierarchy and h1–h6 variants |
| `shadows` | 25-element shadow array; cards rest on shadow 1 and elevate to 2 on hover |
| `components` | Global MUI overrides (Card, Paper, Button, Chip, ListItemButton, AppBar, Drawer, Avatar, TableCell, TableRow) |
| `ThemeProvider` / `CssBaseline` | Outermost providers in `main.tsx`; `CssBaseline` applies `background.default` and normalises browser defaults |

## Layout shell and navigation

| Component | Description |
|-----------|-------------|
| `AppShell` | Fixed sidebar `Drawer` (`DRAWER_WIDTH`), white-surface `AppBar`, routed `<main>` outlet, and the globally mounted `PermissionErrorSnackbar`. Sidebar is data-driven: three collapsible groups (Agents, Integrations, System), a Tenant Admin group for tenant-bound sessions, a Platform group only on a granted probe, plus standalone entries (Dashboard) |
| `NAV_GROUPS` / `STANDALONE_ITEMS` / `NavGroup` / `NavItem` | Declarative sidebar structure and its types |
| `DEFAULT_EXPANDED_GROUPS` / `expandedGroups` / `toggleGroup` | Single-record expansion state; `lockedOpen` groups cannot collapse; active child force-expands its group |
| Sidebar style tokens (`SIDEBAR_*`, `itemButtonSx`, `childItemButtonSx`, `groupHeaderSx`, `iconSx`, `childIconSx`, `groupLabelTypographyProps`) | Shared `sx` objects for consistent appearance |
| `AppRouter` | Route configuration, first-run guard, protected routes (`/agents/panel`, `/access-denied`, `/platform/*`, tenant workspace, `/signup`, `/agents/executions` with legacy redirect) |
| `AgentTrailsPage` / `NotificationConfigPage` | Consolidated tabbed pages at `/agent-trails` and `/notifications` |

## Permission error handling

| Component | Description |
|-----------|-------------|
| `parsePermissionError` | Extracts `PermissionDeniedDetail` from an Axios 403; `null` for non-403/malformed |
| `dispatchPermissionDeniedEvent` / `PERMISSION_DENIED_EVENT` | Fires the `parthenon:permissionDenied` DOM event carrying the detail |
| `PermissionErrorSnackbar` | Listens for the event, shows the denial message and a "Request Access" action |
| `RequestPermissionModal` | Read-only permission context + justification; submits via `submitAccessRequest` |
| `AccessDeniedPage` | Full-page 403 view reading `RequiredPermission` from router state |
| `extractErrorMessage` | Shared error-message extraction for page-level alerts |

## Content and result rendering

| Component | Description |
|-----------|-------------|
| `ContentRenderer` | Renders a string through sanitized HTML, markdown conversion or plain text based on detection and `mode` (`auto` / `chat`) |
| `MaximizableContent` | Maximize button + full-screen dialog wrapper (pure layout decorator) |
| `containsHtmlTags` / `sanitizeHtml` | HTML tag detection and DOMPurify sanitisation |
| `simpleMarkdownToHtml` / `escapeHtml` | Markdown-to-HTML conversion and HTML escaping |
| `OutputTypeResultTab` | Central result dispatcher by output type (`auto` / `markdown` / `typed`); `auto` delegates to `ContentRenderer`; typed runs whose validation failed render the raw final output as a first-class fallback (legacy `{'value': …}` unwrapped, markdown formatted) |
| `output type helpers` | `OutputTypeResultTabProps`, `extractResultText`, `badgeForType` |

## Multi-tenancy frontend plumbing

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| platform admin console | pages + guard | `/platform/*` tenant management, platform settings, audit; gated by `PlatformAdminRoute` + `usePlatformAccess` real-permission probe | `frontend/src/app/PlatformRoutes.tsx` |
| tenant workspace | pages | Tenant settings, license/usage panel, onboarding, members/invitations | `frontend/src/pages/tenant/` |
| `SignUpPage` / `LoginPage` | components | Account-first sign-up; tenancy-aware sign-in (password card, workspace-address finder, `?workspace=` deep link, discreet root-only super-admin entry) | `frontend/src/pages/auth/SignUpPage.tsx`, `frontend/src/pages/auth/LoginPage.tsx` |
| `AuthProvider` | store | Holds `activeTenant`, `availableTenants`, tri-state tenancy flag; refreshes providers after a workspace bind | `frontend/src/stores/AuthContext.tsx` |
| `tenantAuthApi` / `platformAdminApi` / `tenantApi` | API modules | Tenant discovery/registration/login, platform admin, tenant self-service | `frontend/src/api/tenantAuthApi.ts`, `frontend/src/api/platformAdminApi.ts`, `frontend/src/api/tenantApi.ts` |
| `apiClient` tenant binding | behaviour | `X-Tenant` from the per-tab resolved slug; self-heals a fail-closed unknown-slug 403 | `frontend/src/api/apiClient.ts` |
| `isTenantResolutionRejection` / `selfHealTenantBinding` | functions | Recognise the exact fail-closed wire shape and clear the invalid binding (no bounce loop) | `frontend/src/api/apiClient.ts` |
| `OidcCallback` verified bind | behaviour | Candidates (claim → session → remembered → memo) are verified via public discovery before binding | `frontend/src/pages/auth/OidcCallback.tsx` |
| `TenantPicker` / `TenantSessionGate` | components | One-session-one-tenant gate and chooser | `frontend/src/components/auth/TenantPicker.tsx`, `TenantSessionGate.tsx` |
| `usePlatformAccess` | hook | Sidebar/route gating by real permission evaluation | `frontend/src/hooks/usePlatformAccess.ts` |
| `QuotaBlockedAlert` / `extractQuotaBlocked` | component / function | Structured quota-block rendering on blocked actions | `frontend/src/components/tenant/QuotaBlockedAlert.tsx`, `frontend/src/utils/quotaErrorUtils.ts` |
| `LicenseUsagePanel` | component | Tier, effective limits and usage meters in tenant settings | `frontend/src/components/tenant/LicenseUsagePanel.tsx` |
| `tenantApi` settings typing | module | `ConversationTurnResumeTtl` setting field (API-only; no UI control) | `frontend/src/api/tenantApi.ts` |

---

## Code Reference Map

### Theme and bootstrap

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `parthenon` | const | Composed MUI theme | `frontend/src/theme/index.ts` |
| `palette` | object | Colour tokens | `frontend/src/theme/palette.ts` |
| `typography` | object | Inter variant scale | `frontend/src/theme/typography.ts` |
| `shadows` | array | Shadow array | `frontend/src/theme/shadows.ts` |
| `components` | object | MUI component overrides | `frontend/src/theme/components.ts` |
| `ThemeProvider` / `CssBaseline` | components | Root theme injection and CSS reset | `frontend/src/main.tsx` |
| `index.css` | stylesheet | Global layout rules | `frontend/src/styles/index.css` |

### Shell and navigation

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AppShell` | component | Layout shell; mounts the global permission snackbar and the assistant launcher | `frontend/src/app/AppShell.tsx` |
| `DRAWER_WIDTH` | const | Sidebar width (256 px) | `frontend/src/app/AppShell.tsx` |
| `NAV_GROUPS` / `STANDALONE_ITEMS` / `NavItem` / `NavGroup` | constants / interfaces | Declarative sidebar structure | `frontend/src/app/AppShell.tsx` |
| `DEFAULT_EXPANDED_GROUPS` / `expandedGroups` / `toggleGroup` | const / state / function | Group expansion state | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_ACCENT` / `SIDEBAR_ACTIVE_BG` / `SIDEBAR_HOVER_BG` / `SIDEBAR_FONT_SIZE` / `SIDEBAR_CHILD_FONT_SIZE` / `SIDEBAR_CHILD_ICON_SIZE` / `SIDEBAR_ICON_SIZE` / `SIDEBAR_ITEM_RADIUS` | consts | Sidebar style tokens | `frontend/src/app/AppShell.tsx` |
| `itemButtonSx` / `childItemButtonSx` / `groupHeaderSx` / `iconSx` / `childIconSx` / `groupLabelTypographyProps` | consts | Shared `sx` objects | `frontend/src/app/AppShell.tsx` |
| `AppRouter` | component | Route configuration and guards | `frontend/src/app/AppRouter.tsx` |
| `AgentTrailsPage` | component | Tabbed executions/results/history page | `frontend/src/pages/trails/AgentTrailsPage.tsx` |
| `NotificationConfigPage` | component | Tabbed notification channels/groups/logs | `frontend/src/pages/notifications/NotificationConfigPage.tsx` |
| `AppShell` test suite | test | Sidebar group structure and relocated items | `frontend/src/__tests__/AppShell.test.tsx` |
| `AppShell.tenantAdmin` test | test | Platform-group probe gating and single identity-providers entry | `frontend/src/__tests__/AppShell.tenantAdmin.test.tsx` |

### Permission and error infrastructure

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `API_CONFIG` | config object | REST/WS base endpoints | `frontend/src/api/API_CONFIG.ts` |
| `apiClient` | axios instance | Auth/tenant headers, 401 redirect, 403 event dispatch, unknown-slug self-heal | `frontend/src/api/apiClient.ts` |
| `parsePermissionError` / `dispatchPermissionDeniedEvent` / `PERMISSION_DENIED_EVENT` | functions / constant | 403 parsing and event dispatch | `frontend/src/utils/permissionError.ts` |
| `PermissionErrorSnackbar` / `RequestPermissionModal` / `AccessDeniedPage` | components | Global and route-level permission UX | `frontend/src/components/permissions/PermissionErrorSnackbar.tsx`, `RequestPermissionModal.tsx`, `frontend/src/pages/AccessDeniedPage.tsx` |
| `extractErrorMessage` | function | Shared error extraction | `frontend/src/utils/errorUtils.ts` |
| `useDialogErrorHandler` | hook | Dialog error standard | `frontend/src/hooks/useDialogErrorHandler.ts` |
| `toolNaming` | utility module | Shared slug/naming helpers | `frontend/src/utils/toolNaming.ts` |

### Content and result rendering

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ContentRenderer` | component | Format-aware content renderer | `frontend/src/components/ContentRenderer.tsx` |
| `MaximizableContent` | component | Maximize/fullscreen wrapper | `frontend/src/components/MaximizableContent.tsx` |
| `containsHtmlTags` / `sanitizeHtml` | functions | HTML detection and sanitisation | `frontend/src/utils/contentDetection.ts` |
| `simpleMarkdownToHtml` / `escapeHtml` | functions | Markdown conversion and escaping | `frontend/src/utils/markdown.ts` |
| `OutputTypeResultTab` / `OutputTypeResultTabProps` / `extractResultText` / `badgeForType` | component / interface / functions | Result dispatch, raw-output fallback, type badges | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `ContentRenderer.test.tsx` / `MaximizableContent.test.tsx` / `OutputTypeResultTab.test.tsx` | tests | Rendering, sanitisation, maximization, raw fallback | `frontend/src/__tests__/ContentRenderer.test.tsx`, `MaximizableContent.test.tsx`, `OutputTypeResultTab.test.tsx` |

### Tenant integration

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PlatformAdminRoute` / `PlatformRoutes` / `usePlatformAccess` | guard / routes / hook | Platform console gating by real permission probe | `frontend/src/app/PlatformAdminRoute.tsx`, `PlatformRoutes.tsx`, `frontend/src/hooks/usePlatformAccess.ts` |
| `TenantManagementPage` / `PlatformSettingsPage` / `PlatformAuditPage` | components | Platform console pages | `frontend/src/pages/platform/TenantManagementPage.tsx`, `PlatformSettingsPage.tsx`, `PlatformAuditPage.tsx` |
| `TenantSettingsPage` / `OnboardingPage` / `MembersPage` / `InvitationAcceptPage` | components | Tenant workspace pages | `frontend/src/pages/tenant/` |
| `LicenseUsagePanel` / `QuotaBlockedAlert` / `extractQuotaBlocked` | components / function | License/usage meters and quota-block UX | `frontend/src/components/tenant/LicenseUsagePanel.tsx`, `QuotaBlockedAlert.tsx`, `frontend/src/utils/quotaErrorUtils.ts` |
| `AuthProvider` / `useAuthStore` | component / hook | Session tenant state and token store | `frontend/src/stores/AuthContext.tsx`, `frontend/src/stores/authStore.ts` |
| `tenantAuthApi` / `platformAdminApi` / `tenantApi` | modules | Tenant discovery/registration/login, platform admin, self-service | `frontend/src/api/tenantAuthApi.ts`, `frontend/src/api/platformAdminApi.ts`, `frontend/src/api/tenantApi.ts` |
| `isTenantResolutionRejection` / `selfHealTenantBinding` | functions | Unknown-slug binding self-heal | `frontend/src/api/apiClient.ts` |
| `OidcCallback` | component | Verified sign-in tenant binding | `frontend/src/pages/auth/OidcCallback.tsx` |
| `LoginPage` / `SignUpPage` / `extractSlugCandidate` / `bindWorkspace` / `extractLoginErrorMessage` | components / functions | Tenancy-aware sign-in, sign-up and workspace finder | `frontend/src/pages/auth/LoginPage.tsx`, `frontend/src/pages/auth/SignUpPage.tsx` |
| `TenantPicker` / `TenantSessionGate` | components | One-session-one-tenant gate | `frontend/src/components/auth/TenantPicker.tsx`, `TenantSessionGate.tsx` |
| tenant TypeScript types | module | Tenant/license/quota/resume-TTL interfaces | `frontend/src/types/index.ts` |
| `ResourceTypeManifestMirror.test.ts` | test | Backend/frontend manifest parity | `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` |
