# Master UX — Index

Canonical user-experience documentation for Parthenon. Everything here describes **what the
product looks like and how it behaves** — not how it is implemented.

## Contents

| Path | What it is |
|---|---|
| [`prototype/index.html`](prototype/index.html) | **The master interactive prototype.** Self-contained single file (inline CSS/JS, no server, no external assets). Open it directly in a browser. |
| [`agent-session-log-ui.md`](agent-session-log-ui.md) | Business requirements for the agent session log UI — what an execution log must show and how it is organised. |
| [`conversation-sessions-prototype-updates.md`](conversation-sessions-prototype-updates.md) | Notes on the Conversation Agent Sessions additions to the prototype (Agent Type details → Sessions tab). |

## About the master prototype

`prototype/index.html` is the single visual reference for the product. It is a clickable
walkthrough of the shipped UI: the sidebar and top bar are the real navigation chrome, and each
nav entry opens a working screen populated with realistic placeholder data. There is no backend —
every interaction is simulated in the page.

**How to use it**

- Open the file in any modern browser. No build step or web server is required.
- Use the left-hand navigation to move between areas (Dashboard, Agents, Integrations, System,
  Tenant Admin, Platform).
- Screens are demonstrative, not exhaustive: they cover the flows that matter to a given epic's
  acceptance criteria.

**Conventions to follow when extending it**

- Keep the file self-contained: inline `<style>` and `<script>` only, no CDNs, web fonts, or
  external images.
- Reuse the existing design tokens in `:root` (colours, radii, shadows, spacing) and the existing
  component classes (`.card`, `.table-wrap`, `.chip`, `.alert`, `.btn`, `.modal-overlay`,
  `.tooltip-wrap`) rather than introducing new ones.
- Add a new `<div id="view-…" class="view">` and a matching `.nav-item` with `onclick="nav(this,'…')"`;
  never restructure existing views.
- Keep user-facing copy identical to the strings shipped in the product (i18n values), so the
  prototype stays an accurate reference.

## Recently reflected flows

- **MCP session re-authentication** — Integrations → MCP Hub shows a cross-server banner when a
  session's OAuth refresh failed unrecoverably. The Sessions dialog lists a **Token Status** column
  (`Valid (Nd)` / `Expired` / `Needs re-authentication`), carries the stored failure reason as a
  tooltip, and offers a red re-auth action. Completing re-auth updates the same session row in place.
- **Optimized Plan failure and retire states** — Agents → Agent Types → **🧩 Plan** shows the
  persisted failure reason above the plan content (error severity when the run `failed`, warning
  when `needs_feedback`), and renders **Nothing to retire** with a disabled retire action once the
  plan is `retired`. A successful retire shows the success hint while keeping the plan for reference.
