# Spec Change: Reorganize Navigation Menu

## Affected Spec Areas

This change is a **UI presentation delta only**. It does not alter any product feature, route, permission, data model, or backend contract. The affected spec area is the navigation/presentation layer of the Web UI.

| Master Spec Area | Path | Impact |
|---|---|---|
| Foundation Platform — Web UI shell | `docs/master/product/features/foundation-platform.md` | Sidebar structure and visual treatment change; shell, theming, and auth integration unchanged. |
| Master UX prototype | `docs/master/ux/prototype/index.html` | No change required — the prototype already reflects the target sidebar structure and visual treatment this change implements. |
| Agent Management / Agent Types / Agent Identity / Agent Execution / Agent Logs / Skills / SOPs / Model Configs | `docs/master/product/features/agent-management.md`, `agent-types.md`, `agent-identity.md`, `agent-execution.md`, `agent-session-logs.md`, `skill-management.md`, `sop-management.md` | Each feature spec has a "Where it lives in the UI" or similar sidebar reference that must be updated from "top-level" or "AI Agent submenu" to the **Agents** group. |
| MCP Hub | `docs/master/product/features/mcp-hub.md` | Sidebar reference must be updated from "top-level" to the **Integrations** group. |
| Agent Gateway | `docs/master/product/features/agent-gateway.md` | Sidebar reference must be updated from "top-level" to the **Integrations** group. |
| Notification Integration | `docs/master/product/features/notification-integration.md` | Sidebar reference must be updated from "Notifications submenu" to the **Integrations** group. |
| Observability | `docs/master/product/features/observability.md` | Sidebar reference must be updated from "top-level" to the **System** group. |
| Schedule Management | `docs/master/product/features/schedule-management.md` | Sidebar reference must be updated from "top-level" to the **System** group. |
| Result Management | `docs/master/product/features/result-management.md` | Sidebar reference must be updated from "top-level" to the **System** group. |
| Conversation Management | `docs/master/product/features/conversation-management.md` | Sidebar reference must be updated from "AI Agent submenu" to the **Agents** group. |
| Foundation Platform — Permissions & System Config | `docs/master/product/features/foundation-platform.md` | Sidebar references must be updated from "top-level" to the **System** group. |

> **Note:** No `openspec/specs/` directory exists in this project — master product specs are stored under `docs/master/product/features/`. Links above point to the equivalent locations.

---

## New Capabilities

None. This change does not introduce any new product capability, screen, route, permission, or data entity.

---

## Modified Capabilities

The **navigation structure** of the Web UI shell is modified. No underlying feature capability is modified — every existing screen, route, permission, and behavior is preserved; only its location in the sidebar changes.

### Before (current)

Sidebar contains **11 top-level items** plus **2 collapsible submenus** (20 visible entry points total):

- **Top-level (flat):** Dashboard, MCP Hub, Skills, SOPs, Model Configs, Gateway, Schedules, Results, Observability, System Config, Permissions
- **AI Agent submenu:** Agent Roles, Agent Identities, Agent Types, Agent Executions, Runtime Control, Agent Logs
- **Notifications submenu:** Notification Channels, Recipient Groups, Notification Logs

Drawer width: **240px**. Active item is rendered using default MUI selection styling (no pill shape, no explicit color token).

### After (target)

Sidebar contains **1 standalone entry** plus **3 named collapsible groups** (20 visible entry points total — same count, new structure):

- **Standalone:** Dashboard
- **Agents group:** Agent Roles, Agent Identities, Agent Types, Agent Executions, Runtime Control, Agent Logs, Skills, SOPs, Model Configs, Schedules, Results
- **Integrations group:** MCP Hub, Gateway, Notification Channels, Recipient Groups, Notification Logs
- **System group:** Observability, Permissions, System Config

Drawer width: **256px**. Item font size: **13.5px**. Icon size: **16px**. Active item uses a **pill-shaped highlight** with primary light-blue background (`#E3F2FD`) and primary text color (`#1976D2`), per the target prototype.

### Item-by-item relocation map

| Existing location | New location | Notes |
|---|---|---|
| Dashboard (top-level) | **Dashboard** (standalone) | No change in grouping, now visually separated from groups. |
| MCP Hub (top-level) | **Integrations** group | Moved from flat top-level. |
| Skills (top-level) | **Agents** group | Moved from flat top-level; joins related agent capabilities. |
| SOPs (top-level) | **Agents** group | Moved from flat top-level. |
| Model Configs (top-level) | **Agents** group | Moved from flat top-level. |
| Gateway (top-level) | **Integrations** group | Moved from flat top-level. |
| Schedules (top-level) | **Agents** group | Moved from flat top-level; co-located with the agent capabilities it triggers. |
| Results (top-level) | **Agents** group | Moved from flat top-level; co-located with the agent capabilities that produce it. |
| Observability (top-level) | **System** group | Moved from flat top-level. |
| System Config (top-level) | **System** group | Moved from flat top-level. |
| Permissions (top-level) | **System** group | Moved from flat top-level. |
| Agent Roles (AI Agent submenu) | **Agents** group | Group restructured; same item, new parent. |
| Agent Identities (AI Agent submenu) | **Agents** group | Group restructured. |
| Agent Types (AI Agent submenu) | **Agents** group | Group restructured. |
| Agent Executions (AI Agent submenu) | **Agents** group | Group restructured. |
| Runtime Control (AI Agent submenu) | **Agents** group | Group restructured. |
| Agent Logs (AI Agent submenu) | **Agents** group | Group restructured. |
| Notification Channels (Notifications submenu) | **Integrations** group | Submenu merged into Integrations. |
| Recipient Groups (Notifications submenu) | **Integrations** group | Submenu merged into Integrations. |
| Notification Logs (Notifications submenu) | **Integrations** group | Submenu merged into Integrations. |

### Group label i18n keys

Three new group-label translation keys are introduced under the existing `nav.*` namespace:

| Key | English value |
|---|---|
| `nav.groupAgents` | Agents |
| `nav.groupIntegrations` | Integrations |
| `nav.groupSystem` | System |

All other existing `nav.*` keys (item labels) are preserved unchanged.

---

## Removed Capabilities

None. No item, route, screen, or feature is removed by this change.

---

## Spec Update Instructions

Update the following master spec areas to reflect the new sidebar structure. **No code, schema, or architecture changes are required.**

### 1. `docs/master/product/features/foundation-platform.md`

- In the "Web UI Shell" / "Navigation" section (whichever describes the sidebar), replace any current sidebar structure description with the new 4-entry structure: Dashboard (standalone) + Agents / Integrations / System groups.
- Update any sidebar-width, font-size, icon-size, or active-state styling references to match the target prototype (256px, 13.5px, 16px, pill-shaped primary-light-blue).
- Update the inventory of navigation items to reflect the new grouping (use the relocation map in this document).
- Add a note that `nav.groupAgents`, `nav.groupIntegrations`, and `nav.groupSystem` are new i18n keys.

### 2. Per-feature spec updates (sidebar location)

For each of the following feature specs, find the "Navigation" or "Where it lives in the UI" subsection and update the sidebar location text from its current value to the new group:

| Feature spec | Old sidebar location | New sidebar location |
|---|---|---|
| `docs/master/product/features/agent-management.md` | AI Agent submenu (or top-level, depending on subsection) | Agents group |
| `docs/master/product/features/agent-types.md` | AI Agent submenu | Agents group |
| `docs/master/product/features/agent-identity.md` | AI Agent submenu | Agents group |
| `docs/master/product/features/agent-execution.md` | AI Agent submenu | Agents group |
| `docs/master/product/features/agent-session-logs.md` | AI Agent submenu (as Agent Logs) | Agents group |
| `docs/master/product/features/skill-management.md` | Top-level | Agents group |
| `docs/master/product/features/sop-management.md` | Top-level | Agents group |
| `docs/master/product/features/sops.md` | Top-level (if a sidebar reference exists) | Agents group |
| `docs/master/product/features/mcp-hub.md` | Top-level | Integrations group |
| `docs/master/product/features/agent-gateway.md` | Top-level | Integrations group |
| `docs/master/product/features/agent-runtime-gateway.md` | Top-level (if a sidebar reference exists) | Integrations group |
| `docs/master/product/features/notification-integration.md` | Notifications submenu | Integrations group |
| `docs/master/product/features/observability.md` | Top-level | System group |
| `docs/master/product/features/schedule-management.md` | Top-level | Agents group |
| `docs/master/product/features/result-management.md` | Top-level | Agents group |
| `docs/master/product/features/conversation-management.md` | AI Agent submenu | Agents group |
| `docs/master/product/features/foundation-platform.md` (Permissions & System Config subsections) | Top-level | System group |

If a feature spec has no explicit "Navigation" subsection, skip it — do not invent one.

### 3. Master UX prototype — `docs/master/ux/prototype/index.html`

- **Visual treatment is already correct — no CSS changes required.** The prototype already encodes the target sidebar look-and-feel. Spot-check by confirming the following tokens and rules are present in the inline styles:
  - `--sidebar-w: 256px` (sidebar width on desktop)
  - `.nav-item` font size: `13.5px`
  - `.nav-item .nav-icon` font size: `16px` (consistent with group-label icon sizing)
  - `--sidebar-active-bg: #E3F2FD` and `--sidebar-active-text: #1976D2` applied to `.nav-item.active`
  - Right-pill `border-radius` (`0 24px 24px 0`) on `.nav-item.active`, visually distinct from the hover state
- **Structural grouping is NOT yet present — the prototype sidebar markup must be updated.** The current markup at lines 414–444 still reflects the legacy structure (flat top-level items plus the "AI Agent" and "Notifications" submenus). It must be restructured to add the three named group sections (**Agents**, **Integrations**, **System**) per the relocation map above, with the target children in the target order:
  - **Dashboard** as a standalone top-level entry (unchanged, now visually separated from the groups)
  - **Agents** group: Agent Roles, Agent Identities, Agent Types, Agent Executions, Runtime Control, Agent Logs, Skills, SOPs, Model Configs
  - **Integrations** group: MCP Hub, Gateway, Notification Channels, Recipient Groups, Notification Logs
  - **System** group: Observability, Permissions, System Config
- **Reconciliation note for the prototype update:** the prototype's current "AI Agent" submenu has only 5 children (Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs), while the live app has 6 — **Runtime Control** is present in the live app but missing from the prototype. Add Runtime Control to the Agents group during the prototype update so the two stay in sync.
- The prototype remains the source of truth for visual treatment; the live app must continue to match it. If during implementation the two diverge, update the prototype first, then update the live app to match.

### 4. Master technology spec — `docs/master/technology/modules/frontend/tech-spec.md` (or equivalent)

- Update the **Code Reference Map** entry for the sidebar component to reflect any new component / sub-component names introduced by the group restructure. The group structure should be data-driven (e.g., a grouped config object) so the three groups can be defined declaratively.
- Update the component's responsibility description to mention the 3-group structure and the standalone Dashboard.
- No new routes, API calls, or state stores are introduced by this change.

### 5. i18n locale files

- **Remove** the legacy `nav.aiAgent` key from every locale file under `frontend/src/i18n/locales/` (or the project's current i18n directory). The key is no longer referenced by the component (the new `Agents` group uses `nav.groupAgents`) and removing it prevents stale raw-key strings from leaking back into the UI if a future change accidentally re-introduces a reference to it.
- Add the three new keys (`nav.groupAgents`, `nav.groupIntegrations`, `nav.groupSystem`) to every locale file under `frontend/src/i18n/locales/` (or the project's current i18n directory). Currently only `en.json` exists, but the new keys must be added to all current **and future** locale files so the structure stays in sync as translations are added.
- Verify all existing `nav.*` keys for moved items still resolve in every supported locale — no label changes are intended, but the keys must still be present.

### 6. Master QA / test plan

- If a Web UI shell test plan exists under `docs/master/qa/test-plans/`, update its sidebar-structure assertions to reflect the new group membership.
- Add a regression note: tests must verify that every previously reachable route is still reachable from exactly one sidebar location after the reorganization.

### 7. Master architecture / data model / deployment / operations

- **No changes required.** This change has no architectural, data-model, deployment, or operational impact.
