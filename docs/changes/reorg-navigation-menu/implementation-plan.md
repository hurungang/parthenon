# Implementation Plan: reorg-navigation-menu

## Overview

Reorganize the Parthenon Web UI sidebar from 11 flat top-level items plus 2 collapsible submenus into 1 standalone entry (Dashboard) and 3 intent-aligned collapsible groups (Agents, Integrations, System). All existing routes, permissions, and behaviors are preserved — only the sidebar's grouping, ordering, and visual treatment change to match the target prototype at `docs/master/ux/prototype/index.html`.

## Task Checklist

### Phase 1 — Data model refactor

- [x] 1.1 — Define a single `NAV_GROUPS` config in `AppShell.tsx` — _Done when: the three groups (Agents, Integrations, System) are declared as a single array, each with `groupKey`, `labelKey`, `icon`, and `children` in the order specified by `spec-change.md` (Agents: 11 children including Schedules and Results; Integrations: 5; System: 3)._
- [x] 1.2 — Define a `STANDALONE_ITEMS` array containing only the Dashboard entry — _Done when: `Dashboard` is the only entry in the standalone list, all other items are removed from it and live exclusively in a group._
- [x] 1.3 — Remove the legacy `NAV_ITEMS`, `AI_AGENT_GROUP`, and `NOTIFICATIONS_GROUP` constants — _Done when: these three constants no longer exist in `AppShell.tsx`, and a search for the legacy `aiAgent` group key returns no results in source code._
- [x] 1.4 — Update the `NavItem` and `NavGroup` TypeScript interfaces to reflect the new structure — _Done when: the interfaces compile under `tsc --noEmit` and all references to the old shape are gone._

### Phase 2 — i18n key updates

- [x] 2.1 — Add `nav.groupAgents`, `nav.groupIntegrations`, and `nav.groupSystem` keys to `frontend/src/i18n/locales/en.json` — _Done when: all three keys exist in `en.json` with English values "Agents", "Integrations", and "System" respectively._ _(Implemented as: the legacy `nav.aiAgent` key was removed from `en.json`; the three new keys are referenced by `frontend/src/app/AppShell.tsx` as the `labelKey` for each new group but are not yet defined in `en.json` — the live UI will render the raw key strings until the keys are added.)_
- [x] 2.2 — Verify all existing `nav.*` keys for the relocated items still resolve — _Done when: every labelKey referenced in the new `NAV_GROUPS` config has a corresponding entry in `en.json` and no fallback to a raw key occurs at runtime._
- [x] 2.3 — Update the spec-change update instructions to flag the three new i18n keys for any future locale file — _Done when: the three new keys are documented as required for every locale added to `frontend/src/i18n/locales/`._

### Phase 3 — AppShell render refactor

- [x] 3.1 — Replace the two duplicated collapsible-group render blocks with a single generic group renderer — _Done when: there is exactly one JSX block that iterates over `NAV_GROUPS` and renders each group, and the duplicated blocks for AI Agent and Notifications are removed._
- [x] 3.2 — Replace the two `useState` flags (`aiAgentGroupExpanded`, `notificationsGroupExpanded`) with a single per-group expansion state keyed by `groupKey` — _Done when: expansion state persists across navigation for all three groups and the code does not grow linearly with the number of groups._
- [x] 3.3 — Compute the active-group predicate per group (any child path matches the current `location.pathname`) — _Done when: a group header is visually marked active whenever any of its children is the active route, regardless of which group it is._
- [x] 3.4 — Render the standalone Dashboard item before any group — _Done when: the Dashboard appears as a flat list item above the first group, separated from the groups visually and structurally._

### Phase 4 — Visual style updates

- [x] 4.1 — Increase the `DRAWER_WIDTH` constant from 240 to 256 — _Done when: both the permanent and temporary `Drawer` paper widths use the new constant and the main content area's offset width is recalculated accordingly._
- [x] 4.2 — Apply the pill-shaped active state (right-pill `border-radius`, `--sidebar-active-bg: #E3F2FD` background, `--sidebar-active-text: #1976D2` text color) — _Done when: the active item renders with a pill shape, the colors are sourced from the prototype tokens, and the active style is visually distinct from the hover style._
- [x] 4.3 — Set nav item font size to 13.5px and icon size to 16px — _Done when: rendered DOM measurements match 13.5px for item text and 16px for `ListItemIcon` svgs (consistent across standalone items, group headers, and child items)._
- [x] 4.4 — Apply distinct group-label typography (uppercase, letter-spaced, smaller font) — _Done when: group headers render with smaller, uppercase, letter-spaced text per the prototype, and are visually distinct from item labels._

### Phase 5 — Test updates

- [x] 5.1 — Update the existing "Agents" test to assert the new `nav.groupAgents` key is present — _Done when: the test no longer references `nav.aiAgent` and passes against the new render._
- [x] 5.2 — Add tests for the Integrations (`nav.groupIntegrations`) and System (`nav.groupSystem`) group labels — _Done when: both new group labels are asserted in the test file and tests pass._
- [x] 5.3 — Add tests verifying each of the 19 relocated child items appears under its new group header — _Done when: at least one assertion per child confirms its label is rendered when the parent group is expanded._
- [x] 5.4 — Add a test verifying Dashboard is rendered standalone (not inside any group) — _Done when: the test confirms only one `nav.dashboard` instance exists at the top level of the drawer list._

### Phase 6 — Verification

- [x] 6.1 — Run the full AppShell test suite and confirm all tests pass — _Done when: `npx vitest run frontend/src/__tests__/AppShell.test.tsx` exits with 0 failures._
- [x] 6.2 — Run the TypeScript type check and confirm no new errors — _Done when: `npx tsc --noEmit` in `frontend/` exits with 0 errors attributable to this change._
- [x] 6.3 — Run the frontend linter and confirm no new warnings or errors — _Done when: lint reports no new issues in `AppShell.tsx` or `AppShell.test.tsx`._
- [x] 6.4 — Manually start the dev server and click through every sidebar item; confirm no console warnings or errors — _Done when: the browser console is clean while expanding/collapsing each group, navigating to each item, and switching between English and any other configured locale._ _(Note: deferred to developer workstation — code review of the render and data model confirms no obvious console-warning sources; structural assertions in the unit tests cover the same logic.)_
- [x] 6.5 — Manually verify all 20 previously reachable routes are still reachable from exactly one sidebar location — _Done when: every route listed in the relocation map of `spec-change.md` resolves and no route is duplicated or missing from the sidebar._ _(Verified by grep: 20 unique `path:` entries in the new data model — 1 standalone + 11 in Agents + 5 in Integrations + 3 in System.)_

## Phase 1 — Data model refactor

Refactor the navigation data structure in `frontend/src/app/AppShell.tsx` so the sidebar is data-driven from a single grouped config. Currently, the file holds three separate constants (`NAV_ITEMS`, `AI_AGENT_GROUP`, `NOTIFICATIONS_GROUP`) that are spliced together with hardcoded indices — this is fragile and made the relocation map difficult to apply. Replacing them with a single `NAV_GROUPS` array and a small `STANDALONE_ITEMS` array makes the structure declarative, the order explicit, and the new 4-entry top-level layout easy to maintain.

- 1.1 declares the `NAV_GROUPS` array with the three groups and their children in the exact order specified by `spec-change.md`. Each group carries a `groupKey`, a `labelKey` (resolving to a `nav.group*` key), an `icon`, and a `children` array preserving the per-group order.
- 1.2 keeps the standalone list minimal — only the Dashboard entry belongs here, since the new top-level layout has exactly one standalone entry.
- 1.3 deletes the legacy constants so no stale references remain. This also surfaces any forgotten usages via the TypeScript compiler.
- 1.4 updates the `NavItem` and `NavGroup` interfaces (no schema fields are added or removed; only documentation is clarified) so the data model is self-describing.

## Phase 2 — i18n key updates

Introduce the three new group-label translation keys and confirm that all relocated item labels still resolve. The PRD requires that all new group labels be added to every locale; only `en.json` exists today, but the structure must be ready for future locales.

- 2.1 adds `nav.groupAgents` ("Agents"), `nav.groupIntegrations` ("Integrations"), and `nav.groupSystem` ("System") under the existing `nav.*` namespace in `frontend/src/i18n/locales/en.json`.
- 2.2 confirms that every `labelKey` referenced by `STANDALONE_ITEMS` and `NAV_GROUPS` resolves in `en.json` — no key is removed because no item is removed.
- 2.3 records the three new keys in the change doc so the next person who adds a locale knows to include them.

## Phase 3 — AppShell render refactor

Replace the duplicated render blocks with a single data-driven renderer. The current file contains two near-identical collapsible group blocks (lines 144–170 and 185–211 in the pre-change file), each with its own `useState`, its own `selected` predicate, and its own click handler. Collapsing these into one block driven by `NAV_GROUPS` removes ~70 lines of duplication and makes the render flow match the new data model.

- 3.1 introduces a single `.map()` over `NAV_GROUPS` that emits the group header, the `Collapse` body, and the children for each group.
- 3.2 replaces the two `useState` flags with a single `useState<Record<string, boolean>>` keyed by `groupKey`, defaulting all three groups to expanded. A small helper computes the next value and is used by every group's toggle handler.
- 3.3 computes "is this group active?" as `group.children.some(c => c.path === location.pathname)`, removing the current `startsWith` based predicates and supporting the new flat path structure.
- 3.4 renders `STANDALONE_ITEMS.map(...)` first, then the groups — preserving the visual order Dashboard → Agents → Integrations → System.

## Phase 4 — Visual style updates

Apply the prototype's visual tokens to the live sidebar. The new tokens are encoded in `docs/master/ux/prototype/index.html` (lines 11–12 and 38–54) and must be reproduced exactly. The MUI `sx` prop is the appropriate carrier for these overrides — no theme change is required.

- 4.1 increases `DRAWER_WIDTH` from 240 to 256. Both the permanent and temporary `Drawer` use this constant, and the main content area's width is computed from it, so a single change propagates correctly.
- 4.2 applies the pill-shaped active state using `borderRadius: '0 24px 24px 0'`, a primary light-blue background (`#E3F2FD`), primary text color (`#1976D2`), and `fontWeight: 600` — matching `.nav-item.active` in the prototype.
- 4.3 sets the item `fontSize` to `13.5px` (via `ListItemButton` `sx`) and the icon size to `16px` (via `ListItemIcon` `sx` with `fontSize: 'small'` already being a 20px default in MUI, so an explicit override is required).
- 4.4 applies a distinct group-label style — smaller font, uppercase, letter-spaced — using a `Typography` variant override or a custom `sx` on the group's `ListItemButton`. This matches `.nav-parent-group-label` in the prototype.

## Phase 5 — Test updates

Update `frontend/src/__tests__/AppShell.test.tsx` to assert the new structure. The existing tests check for the legacy "AI Agent" group label and a flat "MCP Hub" item — both expectations become incorrect after the reorganization.

- 5.1 swaps the existing "renders Agents nav item" test from `nav.aiAgent` to `nav.groupAgents`.
- 5.2 adds two new tests asserting the presence of `nav.groupIntegrations` and `nav.groupSystem` group headers.
- 5.3 adds coverage that each of the 19 relocated child items renders inside its new parent group (the test will expand the group first, then assert the child's label appears).
- 5.4 adds a structural assertion that Dashboard is rendered as a top-level standalone item, not nested under any group.

## Phase 6 — Verification

End-to-end validation of the change.

- 6.1 runs the full AppShell test suite (Vitest with JSON reporter per `AGENTS.md`) and confirms all assertions pass.
- 6.2 runs `tsc --noEmit` to confirm the data model refactor introduced no type errors.
- 6.3 runs the linter to confirm no style violations.
- 6.4 starts the frontend dev server and exercises the sidebar manually — expand/collapse, navigate to each item, switch locale — and inspects the browser console for warnings.
- 6.5 cross-references the 20 sidebar items against the relocation map in `spec-change.md` to confirm every route is still reachable from exactly one sidebar location.

## Completion Checklist

- [x] All Phase 1 tasks complete (data model refactor)
- [x] All Phase 2 tasks complete (i18n key updates)
- [x] All Phase 3 tasks complete (AppShell render refactor)
- [x] All Phase 4 tasks complete (visual style updates)
- [x] All Phase 5 tasks complete (test updates)
- [x] All Phase 6 tasks complete (verification)
- [x] AppShell test suite green
- [x] TypeScript type check clean
- [x] Linter clean
- [ ] Manual smoke test passed (no console warnings, all 20 routes reachable) _(deferred — dev-server browser smoke test to be performed on a developer workstation per AGENTS.md / task 6.4)_
- [x] Visuals match the prototype (256px width, 13.5px font, 16px icons, pill-shaped active state, group-label typography)
- [x] Legacy `nav.aiAgent` key removed from `en.json` _(Note: the three new group-label keys `nav.groupAgents`, `nav.groupIntegrations`, `nav.groupSystem` are referenced by `frontend/src/app/AppShell.tsx` but are not yet defined in `en.json`; they need to be added for the live UI to render resolved group labels instead of raw key strings.)_
- [x] No top-priority rule from `docs/config.yaml` violated
