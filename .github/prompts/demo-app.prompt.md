# /demo-app

Run a live demo of Parthenon features using Playwright E2E tests in headed mode.

## Before Starting

Ask the user:
> How would you like to demo?
> - **fast** (quick review — ~1s between actions)
> - **normal** (comfortable viewing — ~5s between actions, default)
> - **slow** (presentation pace — ~10s between actions)
> - **manual** (UI mode — click ▶ to run each scenario yourself)

## Speed Modes

Create/update `e2e/playwright.demo.config.ts` that reads `DEMO_SPEED` env var:

- `fast` → `launchOptions.slowMo: 1000`
- `normal` → `launchOptions.slowMo: 5000`
- `slow` → `launchOptions.slowMo: 10000`
- Config extends `playwright.dev.config.ts` with `headed: true`

Run:
```powershell
$env:DEMO_SPEED="normal"; npx playwright test --config=playwright.demo.config.ts --project=chromium --grep "..."
```
macOS/Linux equivalent:
```bash
DEMO_SPEED=normal npx playwright test --config=playwright.demo.config.ts --project=chromium --grep "..."
```
(from `e2e/` directory)

## Manual Control (UI Mode)

Launch Playwright UI as a detached background process:
```powershell
Start-Process -WindowStyle Hidden -FilePath "npx" -ArgumentList "playwright","test","--ui","--config=playwright.demo.config.ts","--ui-host=localhost","--ui-port=8080","--headed"
```
macOS/Linux equivalent:
```bash
nohup npx playwright test --ui --config=playwright.demo.config.ts --ui-host=localhost --ui-port=8080 --headed > /tmp/pw-ui.log 2>&1 &
```
Open `http://localhost:8080` — clicking ▶ runs each scenario with the app browser opening automatically.

## Filtering Scenarios

- `--cases <file>` — Load grep patterns from a demo-cases.md file (see format below)
- `--grep <pattern>` — Filter by test name directly (e.g., `"Mocked Admin CRUD > displays status chips"`)
- `--filter <keyword>` — Alias for --grep

### Windows grep caveat (CRITICAL)

On Windows, `|` in a `--grep` argument is interpreted as a pipe operator by PowerShell — even inside quoted strings. When filtering by multiple patterns joined with `|`, use a temp Node.js script:

```javascript
// temp-demo-runner.js
const path = require('path');
process.chdir(path.resolve(__dirname, 'e2e'));
process.env.DEMO_SPEED = process.env.DEMO_SPEED || 'normal';
const grep = ['pattern1 > test name', 'pattern2 > test name'].join('|');
process.argv = ['node', 'pw', 'test', '--headed', '--config', 'playwright.demo.config.ts', '--grep', grep, '--project=chromium'];
require(path.resolve('e2e/node_modules/@playwright/test/cli.js'));
```

### demo-cases.md format

```markdown
## Grep Patterns
- Describe Block Name > test name exactly matches
- Another Describe > another test name

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
```

## Available Scenarios

| Feature | Test | What You'll See |
|---------|------|-----------------|
| **API Key Management** (api-key-mcp-hub) | | |
| API Key List View | `API Key Management - Mocked Admin CRUD > displays status chips` | Active (green) and revoked (red) status chips in key table |
| Create API Key | `API Key Management - Create Key Flow > can select identity and role then create` | Two-step dialog: select identity+role → one-time key reveal with copy |
| Revoke API Key | `API Key Management - Revoke Key Flow > revoke dialog shows key name and warning` | Confirmation dialog with irreversible warning |
| Filter API Keys | `API Key Management - Filtering > status filter has all/active/revoked options` | Dropdown filter toggling between key states |
| Real Backend Auth | `Real Backend Integration - API Key Endpoints > GET /api/v1/api-keys returns 200 with valid admin token` | Backend integration verification |
| **Agent Runtime Monitor** (agent-runtime-monitor) | | |
| Page rename & map | `Agent Runtime Monitor > presents the view as "Agent Runtime Monitor" and renders the map canvas` | Page rebranded; interactive map canvas is the primary view (no guardrail panel) |
| Auto-fit & grouping | `Agent Runtime Monitor > auto-fits the map and groups same-type agents into containers` | All agents on screen; same-type agents grouped in labelled containers |
| Delegation connector | `Agent Runtime Monitor > renders a delegation connector between parent and child` | Parent → child delegation shown as a connecting line |
| Human-intervention alert | `Agent Runtime Monitor > surfaces a sleeping agent awaiting intervention and opens the intervention dialog` | Sleeping agent shows alert icon; click opens the intervention dialog |
| Selection & terminate | `Agent Runtime Monitor > selects a node and opens the termination dialog from the detail bubble` | Select agent → detail bubble → terminate |
| Zoom | `Agent Runtime Monitor > zooms in and out via the toolbar` | Map zoom in/out via toolbar controls |
| Drag-to-pan | `Agent Runtime Monitor > pans the canvas via drag` | Drag empty canvas to pan the map |
| Fullscreen | `Agent Runtime Monitor > toggles fullscreen and restores` | Maximize the map to fullscreen and back |
| Cross-type delegation | `Agent Runtime Monitor > shows a cross-type parent/child delegation connector` | Parent and delegated child laid out adjacent across agent types with a connector |
| Filter empty-state recovery | `Agent Runtime Monitor > recovers from the filtered-empty state via "Reset filters"` | Legend/toolbar stay usable when a filter hides all agents; "Reset filters" restores them |
| Trigger provenance | `Agent Runtime Monitor > shows trigger provenance as a person entity wired to the execution` | Person/schedule entity in the left column wired by trigger lines to the executions |
| Schedule creator attribution | `Agent Runtime Monitor > shows schedule creator attribution and no person line for a null-creator schedule` | Schedule card shows the human creator; legacy null-creator schedules show no person line |
| Tool-call routes (CH + MCP) | `Agent Runtime Monitor > renders the Communication Hub and tool-call routes to MCP servers` | Communication Hub node + agent→Hub→MCP tool-call routes, latest highlighted |
| **Agent Management Panel** (agent-management-panel) | | |
| Create agent | `Agent Management Panel — CRUD lifecycle > creates an agent from the panel and shows it in sidebar + header immediately (no reload)` | RPG-style panel: create dialog → agent appears in sidebar + header instantly, no reload |
| Inline create-and-assign | `Agent Management Panel — equipment slots (inline create-and-assign) > role slot: create-new mounts the real Agent Role dialog and assigns the created role` | Create a role inside the panel via the real module dialog; it's assigned to the agent immediately |
| Live topology | `Agent Management Panel — live topology > topology updates immediately on draft mutations with zero network requests` | Topology re-renders on every equip/unequip BEFORE saving — zero API calls |
| Hub in preview topology | `Agent Management Panel — Communication Hub in existing preview topologies > Agent Types details dialog shows the hub in a typed agent plan preview topology` | Communication Hub node rendered in the existing Agent Types plan preview topology |
| Permission degradation | `Agent Management Panel — permissions > 403 on the roles list disables only the role slot with a localized explanation` | Denied slot disables gracefully with an explanation — no error surface |
| Single-PUT save | `Agent Management Panel — CRUD lifecycle > pending-changes tray saves the draft with exactly one agent-type PUT` | Pending-changes tray persists the whole draft with exactly one agent-type update call |
| **System One Decision Tools** (system-one-decision-skills) | | |
| Provider config journey | `System One Decision Tools (mocked) > provider config journey enables the decision tool authoring gate` | Admin saves the TypeSafe API key (masked, "Stored" chip only); the decision-tool authoring gate opens once a model is configured |
| Decision tool authoring | `System One Decision Tools (mocked) > round-2 form journey: data types → mapping properties → placeholders → AI generate → save` | Guided authoring: select input/output Agent Data Types with View dialogs, mapping properties auto-populate, auto-detect placeholders, Generate-with-AI fills questions, saves as `decision____<name>` |
| Tenant-contained naming | `System One Decision Tools (mocked) > duplicate tool name shows a structured error and keeps the dialog open` | Same tool name within one tenant → structured conflict error; names are unique per tenant, reusable across tenants |
| Decision results contract | `System One Decision Tools (mocked) > decision results API contract: persisted result keyed to the tool` | Result keyed to the tool with typed answers, probability distributions, confidence, and gate outcome |
| **Multi-Tenancy** (multi-tenant-support) | | |
| Single-tenant regression | `Single-Tenant Regression (switch OFF) > CS-01: /platform/* routes are absent — navigating there lands on dashboard` | With tenancy off, `/platform/*` deep links land on the dashboard — unchanged single-tenant product |
| Platform settings toggle | `Platform Settings Toggle (mocked) > toggle requires the typed ENABLE confirmation and reflects server state` | Typed ENABLE confirmation; button disabled on wrong input; state reflects server immediately |
| Tenant lifecycle | `Platform Tenant Management Lifecycle (mocked) > CS-07/CS-09: create → edit → suspend → resume → delete → slug reusable, all without page reload` | Platform console CRUD with typed-confirmation delete; parent table refreshes without reload |
| Multi-org tenant picker | `Multi-org picker — one session = one tenant > multi-org user sees the picker; single selection binds the session` | Multi-org user picks an org at sign-in; session binds and survives reload |
| Platform audit | `Platform Audit View (mocked) > lists events with tenant attribution and exposes filters; no business data` | Cross-tenant audit events with tenant attribution and filters |
| Sign-up off (switch OFF) | `Self-Serve Sign-Up (mocked) > CS-29: switch off — no entry link on login, /signup inert` | No sign-up link on login; /signup renders an unavailable note with no form |
| Self-serve sign-up journey | `Self-Serve Sign-Up (mocked) > CS-26: full journey — entry link → wizard → lands in onboarding as root` | Two-step wizard (account → organization); new root lands in guided onboarding, no platform-admin action |
| Duplicate email blocked | `Self-Serve Sign-Up (mocked) > CS-27: duplicate email blocked with a clear inline error` | Inline "already exists" error; user stays on /signup, no session |
| One-tenant-per-user | `Self-Serve Sign-Up (mocked) > CS-28: one-tenant-per-user message on a second registration attempt` | Second registration attempt blocked with the dedicated message |
| Quota-blocked invitation | `Quota Enforcement (mocked) > CS-35/CS-41: blocked invite shows tier/limit/usage/upgrade; unblocked once the license is raised` | Structured block alert (tier, limit, usage, upgrade path); raising the license unblocks with no reload |
| License usage panel | `Quota Enforcement (mocked) > CS-34: the tenant usage panel mirrors tier and limits` | Tenant settings shows the tier chip and usage against limits |
| Real-backend tenant isolation | `Real Backend Integration - Multi-Tenant Isolation > isolation contract holds against the live backend` | ⚠️ Requires a live running stack (see `/start-app`); auto-skips otherwise |
| Real-backend self-serve registration | `Real Backend Integration - Self-Serve Registration & Quotas > registration + one-tenant block + usage read against the live backend` | ⚠️ Requires a live running stack (see `/start-app`); auto-skips otherwise |

## Prerequisites

- App must be running (see `/start-app`)
- E2E dependencies installed: `cd e2e && npm install`
- Playwright browsers installed: `npx playwright install chromium`
- `playwright.demo.config.ts` exists in `e2e/`

## After Demo

Report results: which scenarios passed/failed.
