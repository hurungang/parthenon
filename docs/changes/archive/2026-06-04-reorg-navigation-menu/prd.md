# PRD: Reorganize Navigation Menu

## Epic Overview

The Parthenon management Web UI currently exposes 11 flat top-level navigation items plus 2 collapsible groups (AI Agent with 6 children and Notifications with 3 children), producing 20 total visible entry points and an inconsistent mental model — agent-related items (Skills, SOPs, Model Configs) sit at the top level while their closest conceptual neighbors (Agent Roles, Agent Types) are buried in a submenu. This change reorganizes the sidebar into a focused, scannable structure: one standalone Dashboard entry plus three named groups — **Agents**, **Integrations**, and **System** — that align with how administrators think about the platform. The reorganization also aligns the sidebar visual treatment (width, typography, icon size, active-state styling) with the target prototype, reducing cognitive load and shortening the path to the screens users open most.

---

## Business Goals

- Reduce average time to locate a target management screen by replacing the flat list with three intent-aligned groups (Agents, Integrations, System).
- Improve discoverability of agent-adjacent capabilities (Skills, SOPs, Model Configs) by moving them into the Agents group alongside Agent Roles, Agent Types, and Agent Logs.
- Align the live sidebar visuals with the approved target prototype so operators see a consistent, professional navigation experience.
- Lower training and onboarding friction for new administrators by giving the sidebar an explicit, predictable structure.
- Preserve all existing routes and functionality — zero capability removal, zero permission changes.

---

## Users & Personas

**Platform Operators / Administrators** — Day-to-day users managing agents, MCP servers, notifications, and platform configuration. They navigate the sidebar dozens of times per session and benefit from a structure that mirrors their mental model (what kind of work am I doing right now?).

**Onboarding Engineers** — New team members learning the platform. They benefit from clearly labeled groups with predictable membership so they can guess where an item lives before searching.

**Auditors / Reviewers** — Users traversing logs, conversations, and operational artifacts. They need Observability and Permissions grouped under a single, easy-to-remember System heading, and they need Schedules and Results co-located with the agent capabilities they relate to.

**Support Staff** — Users triaging notification delivery and recipient configuration. They benefit from having notification administration clustered with MCP Hub and Gateway under Integrations.

---

## User Stories

- As a **platform operator**, I want the sidebar to group all agent-related screens under one heading, so that I can switch between Agent Types, Agent Executions, Agent Logs, Skills, and SOPs without scanning a long flat list.
- As a **platform operator**, I want integration-adjacent screens (MCP Hub, Gateway, Notification Channels, Recipient Groups, Notification Logs) grouped together, so that I can manage external connectivity from one predictable place.
- As a **platform operator**, I want system-administration screens (Observability, Permissions, System Config) grouped together, so that platform-level operations are visually distinct from agent and integration work.
- As a **platform operator**, I want Schedules and Results to live in the Agents group, so that the screens I use to drive and inspect agent runs are co-located with the agent configuration screens.
- As a **platform operator**, I want the active navigation item to be clearly highlighted with a pill-shaped, light-blue background and primary-color text, so that I always know which screen I am on.
- As a **platform operator**, I want the sidebar to remain accessible on mobile devices (existing drawer behavior preserved), so that the reorganization does not regress responsive navigation.
- As an **onboarding engineer**, I want consistent icon sizing and typography in the sidebar, so that the navigation looks polished and matches the rest of the application.
- As a **user with permission for only a subset of screens**, I want my permitted items to appear inside the correct group, so that the group structure reflects what I can actually do.

---

## Acceptance Criteria

### Structural acceptance criteria

1. The sidebar contains exactly **4 top-level entries** in this order: **Dashboard**, **Agents**, **Integrations**, **System**.
2. **Dashboard** is a standalone top-level entry (not part of any group) and navigates to the existing Dashboard route.
3. The **Agents** group contains exactly these 11 children, in this order: Agent Roles, Agent Identities, Agent Types, Agent Executions, Runtime Control, Agent Logs, Skills, SOPs, Model Configs, Schedules, Results.
4. The **Integrations** group contains exactly these 5 children, in this order: MCP Hub, Gateway, Notification Channels, Recipient Groups, Notification Logs.
5. The **System** group contains exactly these 3 children, in this order: Observability, Permissions, System Config.
6. Every existing route remains reachable from the sidebar at exactly one location (no route is duplicated across groups; no route is removed from the sidebar).
7. All existing i18n label keys for the moved items continue to resolve (no missing translations, no fallback to raw keys).

### Visual acceptance criteria (aligned with target prototype at `docs/master/ux/prototype/index.html`)

8. The sidebar width is **256px** on desktop, unchanged mobile drawer behavior.
9. Sidebar item font size is **13.5px**; sidebar group-label typography is distinct (smaller, uppercase, letter-spaced) per the prototype.
10. Sidebar icons render at **16px** with consistent vertical alignment to text.
11. The currently selected item is rendered with a **pill-shaped highlight** using the primary light-blue background (`--sidebar-active-bg`) and primary text color (`--sidebar-active-text`).
12. The active-state pill is visually distinct from hover state in both color and shape.

### Behavioral acceptance criteria

13. Collapsible group behavior is preserved: groups may be expanded or collapsed by clicking the group header; expanded state is preserved across navigation within a session.
14. When a route inside a group is the active route, the group header is visually indicated as active (e.g., bolded label or matching color treatment).
15. The sidebar renders correctly in both English and any other configured locale (all moved items have translations in every supported language file).
16. On viewport widths below the `sm` breakpoint, the drawer continues to behave as a temporary overlay (existing responsive behavior preserved).
17. After closing any create / edit / delete dialog, the parent table on the active page automatically refreshes (existing CRUD refresh behavior preserved — this change introduces no new dialogs).

### Permission and accessibility acceptance criteria

18. Items the current user does not have permission to access are hidden from the sidebar, but their group remains visible if at least one child is permitted (existing permission-gating behavior preserved).
19. The sidebar is fully keyboard navigable: Tab moves between items, Enter activates the focused item, group headers are activatable to toggle expansion (existing a11y behavior preserved).
20. Active-item and focus-visible styles meet WCAG AA contrast against the sidebar background.

---

## Out of Scope

- **No changes to routes, paths, or backend APIs.** All existing URLs continue to resolve to the same screens.
- **No changes to feature behavior, permissions, or data models.** This is a navigation-presentation change only.
- **No new navigation items.** No capability currently missing from the sidebar is being added by this change.
- **No removal of any existing capability.** Every screen reachable in the current sidebar remains reachable after the change.
- **No changes to the AppBar / top bar, header layout, page content, or page-level navigation.**
- **No new dark-mode, theming, or branding work.** The change adopts the prototype's light theme styling; introducing a dark mode is a separate effort.
- **No user-customizable navigation** (e.g., user-reorderable items, user-collapsible groups persisted to user profile).
- **No changes to the global UX prototype at `docs/master/ux/prototype/index.html`** — the prototype already shows the target look-and-feel; this change brings the live app into alignment.

---

## Dependencies & Constraints

- **Source of truth for current navigation:** `frontend/src/app/AppShell.tsx` (defines `NAV_ITEMS`, `AI_AGENT_GROUP`, `NOTIFICATIONS_GROUP`, drawer rendering, group-expand state, active-route logic).
- **Source of truth for target visuals:** `docs/master/ux/prototype/index.html` (sidebar width, font sizes, icon sizes, pill-shaped active state, group-label typography, color tokens).
- **i18n dependency:** All new group labels (Agents, Integrations, System) must be added to every locale file under `frontend/src/i18n/locales/` (or equivalent directory per current project structure) following the existing `nav.*` key convention.
- **Material-UI constraints:** Active-state pill, icon sizing, and group-label typography must be achievable with the existing MUI 7 component set (List, ListItem, ListItemButton, Collapse) or by extending the MUI theme — no replacement of the component library.
- **Routing constraint:** React Router 7 routes must remain unchanged; grouping is purely a presentation-layer concern.
- **Mobile responsiveness constraint:** Temporary-drawer behavior below the `sm` breakpoint must continue to work identically.
- **Permission system constraint:** The existing permission-gating logic that hides items the current user cannot access must be preserved and applied to the new group structure.
- **Top-priority rules from `docs/config.yaml`:** No top-priority rule is impacted by this change (it is a UI presentation change only).
