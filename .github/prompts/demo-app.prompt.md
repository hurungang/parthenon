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
(from `e2e/` directory)

## Manual Control (UI Mode)

Launch Playwright UI as a detached background process:
```powershell
Start-Process -WindowStyle Hidden -FilePath "npx" -ArgumentList "playwright","test","--ui","--config=playwright.demo.config.ts","--ui-host=localhost","--ui-port=8080","--headed"
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
| Trigger provenance | `Agent Runtime Monitor > shows trigger provenance on the tile and detail bubble` | Who triggered each agent (user / inherited / schedule) on the tile and bubble |
| Tool-call routes (CH + MCP) | `Agent Runtime Monitor > renders the Communication Hub and tool-call routes to MCP servers` | Communication Hub node + agent→Hub→MCP tool-call routes, latest highlighted |

## Prerequisites

- App must be running (see `/start-app`)
- E2E dependencies installed: `cd e2e && npm install`
- Playwright browsers installed: `npx playwright install chromium`
- `playwright.demo.config.ts` exists in `e2e/`

## After Demo

Report results: which scenarios passed/failed.
