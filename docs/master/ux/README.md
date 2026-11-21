# Master UX — Index

Canonical user-experience documentation for Parthenon. Everything here describes **what the
product looks like and how it behaves** — not how it is implemented.

## Contents

| Path | What it is |
|---|---|
| [`prototype/index.html`](prototype/index.html) | **The hub of the master interactive prototype.** Landing screen (Dashboard), the real sidebar/topbar chrome, and a *Prototype map* that links to every module page. |
| [`prototype/modules/`](prototype/modules/) | One page per independently changing module area (see the table below). Every screen of the product lives on exactly one of these pages. |
| [`prototype/shared/`](prototype/shared/) | Shared assets: `styles.css` (all design tokens and component classes), `app.js` (navigation, dialogs, hub routing), `assistant.js` (Control Center Assistant), plus small feature bundles. |
| [`agent-session-log-ui.md`](agent-session-log-ui.md) | Business requirements for the agent session log UI — what an execution log must show and how it is organised. |
| [`conversation-sessions-prototype-updates.md`](conversation-sessions-prototype-updates.md) | Notes on the Conversation Agent Sessions additions to the prototype (Agent Type details → Sessions tab). |

## About the master prototype

The prototype is a clickable walkthrough of the shipped UI: the sidebar and top bar are the real
navigation chrome, and each nav entry opens a working screen populated with realistic placeholder
data. There is no backend — every interaction is simulated in the page.

It used to be one 15.7k-line file. It is now a small static site so that no page exceeds the
documented size limit and so that two change sets never collide in one file.

**How to use it**

- Open `prototype/index.html` in any modern browser. No build step, no server, no install.
- Move between modules with the left-hand navigation (real links, e.g.
  `modules/agents.html#view-agent-roles`) or with the *Prototype map* on the hub.
- Inside a module page the sidebar switches between that page's screens; screens that live on
  another page are ordinary links to it.
- The login screen (workspace picker, IdP sign-in, break-glass super admin, setup wizard, tenant
  picker) is part of the hub and is reachable from the prototype map, so the hub itself opens on the
  Dashboard.

**Conventions to follow when extending it**

- **File layout.** `index.html` = hub (chrome + landing screens + map). `modules/<module>.html` =
  one module area. `shared/` = everything shared. Never duplicate a `view-*` block: every view id
  appears exactly once in the tree, on the page that owns it.
- **Relative assets only.** Module pages reference `../shared/styles.css` and `../shared/*.js`;
  the hub references `shared/…`. Classic `<script src>` and `<link rel="stylesheet">` only — no
  `fetch`, no `type="module"`, no absolute paths, no CDNs, no web fonts, so every page opens from
  `file://`.
- **Navigation is links, not view switching across documents.** Sidebar entries are
  `<a class="nav-item" href="page.html#view-x">`. A same-page entry is `href="#view-x"`. Legacy
  in-page handlers still work: `showView('x')` for a view on another page navigates there, and
  `openModal('y')` for a dialog owned by another page opens that page and then the dialog
  (`?modal=y`).
- **Sizes.** Keep every file under 2,500 lines / 200 KB. If a module page grows past that, split it
  by sidebar area rather than moving a view back into the hub.
- **Styling.** Reuse the tokens in `shared/styles.css` `:root` and the existing component classes
  (`.card`, `.table-wrap`, `.chip`, `.alert`, `.btn`, `.modal-overlay`, `.tab`, `.tooltip-wrap`)
  rather than introducing new ones. Page-specific CSS stays a small inline block in that page only.
- **Copy.** Keep user-facing text identical to the strings shipped in the product (i18n values), so
  the prototype stays an accurate reference.

## Module pages

| Page | Screens it owns |
|---|---|
| `index.html` | Dashboard, Project Showcase, Setup Wizard, login / auth states, prototype map |
| `modules/agents.html` | Agent Types (incl. Run vs Optimize, Plan / Optimized Plan dialog, optimizer conversation), Agent Roles, Agent Identities |
| `modules/agent-panel.html` | Agent Management Panel (canvas, slots, pickers, fullscreen) |
| `modules/executions.html` | Agent Executions, Agent Runtime Monitor, Agent Trails, Agent Logs |
| `modules/skills-sops.html` | Skills, SOPs (editors and previews) |
| `modules/data-results.html` | Data Types, Agent Outputs, Result Repository |
| `modules/schedules.html` | Schedules (create/edit dialog, execution history, details) |
| `modules/integrations.html` | MCP Hub, Notification Integration, API Keys, Agent Client, Agent Gateway |
| `modules/system.html` | System Config (identity providers, general), Model Configs (+ authoring model, optimizer model), Permissions, Observability, Security Audit |
| `modules/decision.html` | Decision Tools, Decision Model Providers |
| `modules/tenancy.html` | Tenant Settings, Members, Identity Providers, Platform Settings, Tenants, Platform Security Audit |
| `modules/chat.html` | Chat (conversation + activity + resume states), Conversational Intervention, Intervene Requests |

## Recently reflected flows

- **Separate optimization from execution** — Agents → Agent Types exposes **▶ Run** and
  **✨ Optimize** as two distinct actions. Optimize is gated (disabled with the reason in its
  tooltip: no successful execution, no authoring model, conversational agent) and never converts a
  run into an optimization mission. The Optimized Plan dialog adds explicit **Generate plan /
  Regenerate plan**, the *No implementation plan yet* empty state, the **requires a fix** alert with
  auto-recorded feedback and **Re-optimize**, and the conversational-agent explanation. Model
  Configs carries the **Plan & Workflow Authoring Model** card with its unset reminder.
- **Conversational optimizer** — the Optimized Plan dialog offers **💬 Talk to optimizer**
  (identity parity, scope, the optimizer model disclosed). The conversation is scoped to that agent,
  shows a default-collapsed **What ran in this session** bar (replay-only until an approval is
  spent), exactly one processing indicator per turn, an in-chat **ask/decide** card that pauses the
  composer, and a live-test approval card that collapses to a one-line history summary
  (approved / running / executed / failed / denied / expired / cancelled). Model Configs adds the
  **Optimizer Model** section with inherit-from-authoring-model and stale-value handling.
- **Persistent agent activity state** — Conversational Intervention keeps one indicator across
  *thinking → using tool → delegating → waiting → waiting for your input → finished*, with no blank
  gap before an intervention prompt and no spinner left behind after a terminal state
  (`failed` / `timed out`).
- **Resumable agent turn persistence** — the same surface exposes the shared resume vocabulary
  **Waiting for your input / Resumed · continuing / Resolved / No longer resumable**, a single
  reason-specific terminal card (*This confirmation can no longer be resumed* — expired, pause point
  lost, stopped unexpectedly) with **Ask again** and **Dismiss** instead of a generic timeout, a
  re-enabled composer, and a "nothing to replay" guard for stale approvals.
- **MCP session re-authentication** — Integrations → MCP Hub shows a cross-server banner when a
  session's OAuth refresh failed unrecoverably. The Sessions dialog lists a **Token Status** column
  (`Valid (Nd)` / `Expired` / `Needs re-authentication`), carries the stored failure reason as a
  tooltip, and offers a red re-auth action. Completing re-auth updates the same session row in place.
- **Optimized Plan failure and retire states** — Agents → Agent Types → **🧩 Plan** shows the
  persisted failure reason above the plan content (error severity when the run `failed`, warning
  when `needs_feedback`), and renders **Nothing to retire** with a disabled retire action once the
  plan is `retired`. A successful retire shows the success hint while keeping the plan for reference.
