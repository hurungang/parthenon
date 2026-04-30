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
| `AppShell` | Top-level layout component; renders a fixed sidebar `Drawer` (width `DRAWER_WIDTH`), a white-surface `AppBar` with `border-bottom` separator, a `<main>` outlet for routed page content, and mounts `PermissionErrorSnackbar` globally so all 403 denials surface without per-page handling |
| `DRAWER_WIDTH` | Module-level constant defining sidebar pixel width (260 px); referenced by both the `Drawer` and the `main` offset margin |
| `NAV_ITEMS` | Array of navigation item descriptors (path, MUI icon component, i18n key); drives the sidebar `List` rendered in `AppShell` |

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
| `AppShell` | component | Top-level layout — sidebar drawer, AppBar, page outlet; mounts `PermissionErrorSnackbar` globally | `frontend/src/app/AppShell.tsx` |
| `DRAWER_WIDTH` | const | Sidebar pixel width — 260 px | `frontend/src/app/AppShell.tsx` |
| `NAV_ITEMS` | const | Navigation item definitions (path, icon, i18n key) | `frontend/src/app/AppShell.tsx` |
| `AppRouter` | component | Route configuration; first-run redirect guard (`getIdentityStatus` on mount); registers `/access-denied` route for `AccessDeniedPage` | `frontend/src/app/AppRouter.tsx` |
| `index.css` | stylesheet | Global root layout rules (font-family removed, Inter via MUI theme) | `frontend/src/styles/index.css` |

### API Client & Permission Error Infrastructure

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `apiClient` | axios instance | HTTP client with auth header injection; 401 interceptor redirects to OIDC login; 403 interceptor calls `parsePermissionError` and fires `dispatchPermissionDeniedEvent` | `frontend/src/api/apiClient.ts` |
| `parsePermissionError` | function | Extracts `PermissionDeniedDetail` from an Axios 403 error response body; returns `null` for non-403 or malformed payloads | `frontend/src/utils/permissionError.ts` |
| `dispatchPermissionDeniedEvent` | function | Fires `parthenon:permissionDenied` custom DOM event carrying the `PermissionDeniedDetail` payload | `frontend/src/utils/permissionError.ts` |
| `PERMISSION_DENIED_EVENT` | constant | Custom event name `"parthenon:permissionDenied"` shared between dispatcher and snackbar listener | `frontend/src/utils/permissionError.ts` |
| `PermissionErrorSnackbar` | component | Global MUI Snackbar in `AppShell`; listens for `PERMISSION_DENIED_EVENT`; displays denial message + "Request Access" button that opens `RequestPermissionModal` with full `PermissionDeniedDetail` context | `frontend/src/components/permissions/PermissionErrorSnackbar.tsx` |
| `RequestPermissionModal` | component | Controlled modal; displays read-only permission context (resource type, action, ID); collects justification; submits via `submitAccessRequest`; shows inline success/error feedback | `frontend/src/components/permissions/RequestPermissionModal.tsx` |
| `AccessDeniedPage` | component | Full-page route-level 403 view at `/access-denied`; reads `RequiredPermission` from `useLocation().state`; mirrors the approved prototype error-state card design | `frontend/src/pages/AccessDeniedPage.tsx` |
| `extractErrorMessage` | function | Shared utility: reads `error.response.data.detail` (Axios), `error.message` (Error), or falls back to provided `fallback` string; used across `UsersPage`, `RolesPage`, `AccessRequestsPage`, and `GroupsPage` | `frontend/src/utils/errorUtils.ts` |
