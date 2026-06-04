# Tech Spec: reorg-navigation-menu

## Technical Overview

This change restructures the Web UI sidebar from a flat list with two ad-hoc submenus into a declarative, data-driven, three-group layout that aligns with the platform's intent domains (Agents, Integrations, System). The implementation is a frontend-only refactor confined to `frontend/src/app/AppShell.tsx`, its accompanying i18n locale file, and its test file. The existing React Router 7 routes, MUI 7 component primitives, permission-gating logic, and responsive drawer behavior are all preserved verbatim — the only additions are a single grouped config object, three new i18n keys, a generic collapsible-group renderer, and visual overrides for the prototype's sidebar tokens. No backend, database, API, or route change is involved.

## Component Breakdown

### `AppShell` (existing component, refactored)

The shell component at `frontend/src/app/AppShell.tsx` is the only component touched by this change. Its responsibility, structure, and export remain unchanged; its internal data model and render tree are restructured. The component continues to own:

- The MUI `AppBar` (top bar with title, user avatar, logout).
- The MUI `Drawer` (temporary on mobile, permanent on desktop) that wraps the sidebar content.
- The `<Outlet />` that hosts the active route's page content.
- The `PermissionErrorSnackbar` mounted at the bottom of the layout.

The render tree becomes a three-tier structure:

1. **Standalone items** — top-level entries with no parent group. Currently a single entry: Dashboard.
2. **Collapsible groups** — three named groups (Agents, Integrations, System), each rendered as a header `ListItemButton` plus a `Collapse` body containing the group's children.
3. **Group children** — the individual `ListItemButton`s nested under each group, with a left-padding override (`pl: 4`) to visually indent them.

A new internal state object holds the expansion state for all three groups in a single `useState<Record<string, boolean>>` keyed by `groupKey`, replacing the two prior `useState<boolean>` flags. The active-group predicate becomes `group.children.some(child => child.path === location.pathname)` and is computed per group inside the `.map()`.

### `NavItem` and `NavGroup` interfaces (refactored, not new)

The two TypeScript interfaces at the top of `AppShell.tsx` are retained; their field sets are unchanged. They are not exported, and no consumer outside this file relies on them. Documentation comments may be refreshed to reflect the new ownership pattern (declarative grouped config instead of spliced indices).

### `PermissionErrorSnackbar` (unchanged)

The mounted snackbar is not touched. It continues to live at the root of the layout for global permission-error surfacing and is unaffected by the sidebar refactor.

### `useAuthStore` (unchanged)

The auth store hook consumed by `AppShell` is read for `claims` and `logout` only. The refactor does not alter which fields are read or how they are rendered.

## API Changes

None. This change introduces no new API endpoints, no modified request/response shapes, no new query parameters, and no deprecations. All existing routes continue to resolve to the same screens. No backend service, database, or OpenAPI specification is touched.

## State Management

The change introduces a single piece of new local state in `AppShell` and removes two pieces of legacy local state. No global store, no URL parameter, no persistent storage, and no new context is involved.

- **Removed**: `aiAgentGroupExpanded: boolean` and `notificationsGroupExpanded: boolean` (two separate `useState` flags).
- **Added**: `expandedGroups: Record<string, boolean>` — a single `useState` keyed by `groupKey`, initialized with all three groups expanded to true so users see the relocated items by default after refresh.
- **Unchanged**: `mobileOpen: boolean` (drawer open state for mobile).
- **Unchanged**: navigation state lives in `useLocation()` and `useNavigate()` from React Router 7 — no path changes.

The toggle handler becomes a small inline function that flips the value at a given `groupKey`. Expansion state is per-session, not persisted across reloads (per PRD out-of-scope: no user-customizable navigation).

## Data Access Patterns

Not applicable. This is a frontend-only refactor of a presentational component. The component reads no backend data, makes no API calls, and subscribes to no stores other than `useAuthStore` for identity claims. All navigation data is hardcoded as module-level constants (`NAV_GROUPS` and `STANDALONE_ITEMS`).

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AppShell` | component | Top-level layout: AppBar + sidebar Drawer + page Outlet; renders the new 3-group sidebar driven by `NAV_GROUPS` and `STANDALONE_ITEMS` | `frontend/src/app/AppShell.tsx` |
| `NavItem` | interface | TypeScript shape for a single sidebar entry (`labelKey`, `path`, `icon`) | `frontend/src/app/AppShell.tsx` |
| `NavGroup` | interface | TypeScript shape for a collapsible sidebar group (`groupKey`, `labelKey`, `icon`, `children`) | `frontend/src/app/AppShell.tsx` |
| `NAV_GROUPS` | constant | Declarative array of the three sidebar groups (Agents, Integrations, System) with their children in spec order | `frontend/src/app/AppShell.tsx` |
| `STANDALONE_ITEMS` | constant | Declarative array of top-level sidebar entries that are not in any group (currently just Dashboard) | `frontend/src/app/AppShell.tsx` |
| `DRAWER_WIDTH` | constant | Sidebar width in pixels; updated to 256 to match the prototype | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_ACTIVE_BG` | constant | Active-state background token (`#E3F2FD`); prototype `--sidebar-active-bg` | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_ACTIVE_TEXT` | constant | Active-state text color token (`#1976D2`); prototype `--sidebar-active-text` | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_FONT_SIZE` | constant | Item font size token (`13.5px`); matches prototype `.nav-item` | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_ICON_SIZE` | constant | Sidebar icon size token (`16px`); matches prototype `.nav-item .nav-icon` | `frontend/src/app/AppShell.tsx` |
| `SIDEBAR_PILL_RADIUS` | constant | Right-pill border-radius (`0 24px 24px 0`); matches prototype `.nav-item.active` | `frontend/src/app/AppShell.tsx` |
| `DEFAULT_EXPANDED_GROUPS` | constant | Initial expansion state for all three groups (all `true`); used to seed `expandedGroups` `useState` | `frontend/src/app/AppShell.tsx` |
| `itemButtonSx` | constant | Shared `sx` for standalone items and group children — font size, white-space, and the pill-shaped `&.Mui-selected` override | `frontend/src/app/AppShell.tsx` |
| `childItemButtonSx` | constant | `sx` for child items — extends `itemButtonSx` with `pl: 4` to indent under the group header | `frontend/src/app/AppShell.tsx` |
| `groupHeaderSx` | constant | `sx` for the group header `ListItemButton` — active-state background / text color / weight; intentionally omits the pill radius so only leaf items get the pill | `frontend/src/app/AppShell.tsx` |
| `iconSx` | constant | `sx` for `ListItemIcon` slots — `minWidth: 36` (baseline gutter) and `fontSize: 16px` (icon size) | `frontend/src/app/AppShell.tsx` |
| `groupLabelTypographyProps` | constant | `primaryTypographyProps` for the group-label `ListItemText` — smaller (11px), uppercase, letter-spaced 1px, `text.secondary` color | `frontend/src/app/AppShell.tsx` |
| `expandedGroups` | state | `useState<Record<string, boolean>>` keyed by `groupKey`; replaces the two legacy `useState<boolean>` flags | `frontend/src/app/AppShell.tsx` |
| `toggleGroup` | function | Toggles the `expandedGroups` entry for a given `groupKey`; used by every group's header click handler | `frontend/src/app/AppShell.tsx` |
| `isGroupActive` (inline) | predicate | Computed per group inside the render `.map()`; `group.children.some(c => c.path === location.pathname)`. Drives group header `selected` state and force-expands the body (deep-link support per test plan §4.1) | `frontend/src/app/AppShell.tsx` |
| `showChildren` (inline) | predicate | Computed per group; `isExpanded || isGroupActive`. Passed to `<Collapse in={...}>` so an active child is always visible regardless of the user's prior collapsed state | `frontend/src/app/AppShell.tsx` |
| `nav.groupAgents` | i18n key | English label "Agents" for the Agents group header | `frontend/src/i18n/locales/en.json` |
| `nav.groupIntegrations` | i18n key | English label "Integrations" for the Integrations group header | `frontend/src/i18n/locales/en.json` |
| `nav.groupSystem` | i18n key | English label "System" for the System group header | `frontend/src/i18n/locales/en.json` |
| `useAuthStore` | hook | Existing Zustand store providing `claims` and `logout`; consumed by `AppShell` for the user avatar and logout button (unchanged) | `frontend/src/stores/authStore.ts` |
| `PermissionErrorSnackbar` | component | Existing global permission-error snackbar; mounted at the layout root (unchanged) | `frontend/src/components/permissions/PermissionErrorSnackbar.tsx` |
| `AppShell` test suite | test file | Vitest + Testing Library tests for the sidebar; updated to assert the new group structure and relocated child items | `frontend/src/__tests__/AppShell.test.tsx` |
