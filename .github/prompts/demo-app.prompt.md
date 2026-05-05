---
description: Demo the Parthenon application by running Playwright E2E tests in headed (visible browser) mode. By default runs curated demo scenarios from master demo-cases file. Supports --cases, --filter, --speed, and --pause flags. Uses named IDE terminal for preview server.
---

Demo the Parthenon application using Playwright in headed browser mode.

**Usage**: `/demo-app [--cases <file>] [--filter <scenario>] [--speed <fast|normal|slow>] [--pause]`

- No flags → reads `docs/master/qa/demo-cases.md` if it exists; otherwise runs all scenarios. Asks user to choose speed before starting.
- `--cases <file>` → load grep patterns from the specified demo-cases.md file (e.g. `docs/changes/my-change/demo-cases.md` or `docs/master/qa/demo-cases.md`). Only the tests matching those patterns will run.
- `--filter <scenario>` → additionally filter by scenario/feature name (applies on top of `--cases` if both given)
- `--speed fast` → 1000ms delay between actions (quick review)
- `--speed normal` → 5000ms delay (default — comfortable viewing pace)
- `--speed slow` → 10000ms delay (very deliberate, good for presentations)
- `--pause` → open Playwright UI mode — user manually clicks ▶ to run each scenario (full pause control)

Examples:
- `/demo-app` — curated product demo at normal speed (uses master demo-cases if available)
- `/demo-app --cases docs/changes/enterprise-ai-harness/demo-cases.md` — demo only the change's curated cases
- `/demo-app --cases docs/master/qa/demo-cases.md --speed slow` — full product demo, slow pace
- `/demo-app --filter notifications` — demo notification management only
- `/demo-app --speed slow` — slow, presentation-friendly demo
- `/demo-app --pause` — interactive mode: you control when each scenario runs
- `/demo-app --cases docs/changes/my-change/demo-cases.md --pause` — step through change scenarios manually

Available scenarios (from `e2e/tests/`):
- `dashboard` — main dashboard overview
- `conversations` — conversation history and chat
- `chat` — real-time chat with AI agents
- `notifications` — notification management
- `scheduling` — job scheduling
- `results` — results viewing
- `agent-management` — agent configuration and management
- `agent-runtime` — agent roles, identities, session launch, and session tracking
- `agent-bootstrap` — agent realm initialization and OAuth-based identity creation
- `gateway` — gateway / agent types configuration
- `mcp-hub` — MCP hub management
- `skills-sops` — skills and SOPs
- `observability` — metrics and traces
- `permissions` — user permission management (tags, roles, groups, users, access requests)

---

## Step 1: Resolve Cases and Ask User for Demo Preferences

### Resolve the cases source

Determine which test cases to run:

1. **If `--cases <file>` is provided**: Read the specified demo-cases.md file. Extract all lines under the `## Grep Patterns` heading that start with `- ` and strip the `- ` prefix. These are the Playwright test title patterns. Join them with `|` to form the `--grep` regex.

2. **If no `--cases` flag but `docs/master/qa/demo-cases.md` exists**: Read it and extract grep patterns the same way. Announce: "Using master demo-cases from `docs/master/qa/demo-cases.md`."

3. **If no cases file found at all**: Run all scenarios (no `--grep` filter).

4. **If `--filter <pattern>` is also given**: Apply it as an additional `--grep` to narrow down further (append `.*<pattern>` or use it as the sole grep if no cases file was loaded).

### Ask speed if not specified

If the user has **not already specified flags**, ask before running:

```
## 🎬 Ready to Demo

How would you like to run the demo?

**Speed (headed browser — automatic):**
1. Fast   — 1s between actions (quick review)
2. Normal — 5s between actions (comfortable viewing)  ← default
3. Slow   — 10s between actions (presentation pace)

**Control (manual):**
4. UI mode — Playwright UI opens; you click ▶ to run each scenario yourself

Type 1/2/3/4 — or include a scenario name to filter (e.g. "3, notifications")
```

Wait for the user's response, then map it:
- `1` / `fast` → `DEMO_SPEED=fast`, headed mode
- `2` / `normal` / Enter → `DEMO_SPEED=normal`, headed mode
- `3` / `slow` → `DEMO_SPEED=slow`, headed mode
- `4` / `ui` / `manual` / `pause` → `--ui` mode (DEMO_SPEED ignored)

If the user also names a scenario (e.g. "3, notifications"), apply `--grep` accordingly.

**If flags were already provided** (e.g. `/demo-app --speed slow --filter notifications`), skip the question and proceed directly.

Parse flags from user message if present:
- `--cases <path>` — demo-cases.md file to load patterns from
- `--filter <pattern>` — scenario to demo
- `--speed <fast|normal|slow>` — mapped to DEMO_SPEED above
- `--pause` — UI mode

---

## Step 2: Check Prerequisites and Start Preview Server

**Frontend preview server** must be running and responding at `http://localhost:4173`.

### Check if server is running, start if needed

First check if preview server is already running:

```powershell
$projectRoot = "C:\Users\rhu\source\personal\coding-workspace\Parthenon"

try {
    $response = Invoke-WebRequest -Uri "http://localhost:4173" -Method HEAD -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    $serverReady = $response.StatusCode -eq 200
} catch {
    $serverReady = $false
}

if ($serverReady) {
    Write-Host "✅ Preview server is already running on port 4173"
}
```

**If server is NOT running**, start it:

1. **Build frontend first** (synchronous):
   ```powershell
   cd frontend
   npm run build
   ```
   Check `$LASTEXITCODE` - if non-zero, build failed, stop execution.

2. **Start preview server in IDE terminal with reusable name "Parthenon Preview":**
   
   Use `run_in_terminal` with `mode=async`:
   ```powershell
   cd frontend
   npm run preview
   ```
   
   **Terminal will remain visible in IDE** and can be reused. The terminal will be named "Parthenon Preview" for easy identification.

3. **Poll for readiness** (synchronous):
   ```powershell
   $maxWait = 30
   $waited = 0
   $serverReady = $false
   
   while (-not $serverReady -and $waited -lt $maxWait) {
       Start-Sleep -Seconds 2
       $waited += 2
       try {
           $response = Invoke-WebRequest -Uri "http://localhost:4173" -Method HEAD -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
           if ($response.StatusCode -eq 200) {
               Write-Host "✅ Preview server ready on port 4173"
               $serverReady = $true
           }
       } catch {
           # Still starting
       }
   }
   
   if (-not $serverReady) {
       Write-Host "❌ Preview server failed to start within ${maxWait}s"
       Write-Host "Check the 'Parthenon Preview' terminal for errors"
       return  # Stop execution
   }
   ```

**Only proceed if HTTP probe succeeds with 200 status.**

### Check demo config exists

**Demo config** (`e2e/playwright.demo.config.ts`) must exist. If missing, create it:
```typescript
import { defineConfig, devices } from '@playwright/test'

const slowMoMap: Record<string, number> = { fast: 1000, normal: 5000, slow: 10000 }
const slowMo = slowMoMap[process.env.DEMO_SPEED ?? 'normal'] ?? 800

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    launchOptions: { slowMo },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
```

---

## Step 3: Launch Playwright Demo

```powershell
cd <project_root>/e2e
```

Build the `--grep` argument from the resolved cases (Step 1):
- If patterns were loaded from a demo-cases.md: `$grepArg = '"(pattern1|pattern2|...)"'` (join with `|`)
- If `--filter` was also given: append to the pattern or use it alone
- If no patterns: omit `--grep` entirely (runs all tests)

### Pause mode (`--pause` flag)

Open the Playwright UI as a **web app**. Run it as a **detached background process** so it stays alive independently.

If a `--grep` pattern was resolved from a cases file, include it in the command:
```powershell
# With cases filter
Start-Process -FilePath "cmd.exe" -ArgumentList "/c cd /d <project_root>\e2e && npx playwright test --ui-host=localhost --ui-port=8080 --headed --config playwright.demo.config.ts --project=chromium --grep <grepPattern>" -WindowStyle Hidden

# Without filter (all scenarios)
Start-Process -FilePath "cmd.exe" -ArgumentList "/c cd /d <project_root>\e2e && npx playwright test --ui-host=localhost --ui-port=8080 --headed --config playwright.demo.config.ts --project=chromium" -WindowStyle Hidden
```

Wait ~6 seconds, then verify port 8080 is listening:
```powershell
Start-Sleep -Seconds 6
$raw = (netstat -ano | Select-String ":8080 .*LISTEN" | Select-Object -First 1).ToString()
$uiPid = ($raw.Trim() -split '\s+' | Select-Object -Last 1)
Write-Host "Playwright UI running on PID $uiPid"
```

Once confirmed, announce:
"🎮 **Playwright UI is open at http://localhost:8080** — open that URL in your browser. Click ▶ next to any scenario in the left sidebar to run it. The app browser will open automatically (headed mode is forced). Use the timeline at the bottom to step through each action."

> To stop the UI server: find PID with `(netstat -ano | Select-String ":8080 .*LISTEN").ToString().Trim() -split '\s+' | Select-Object -Last 1` then `Stop-Process -Id <PID> -Force`

> Note: `--ui` mode ignores `DEMO_SPEED` / slow-mo. Use the built-in action timeline in the UI to review steps at your own pace.

---

### Headed mode (default — with slow-mo)

> **Windows note**: On Windows, `|` in a `--grep` argument is interpreted as a pipe operator by both PowerShell and cmd.exe — even inside quoted strings or batch files. The only reliable fix is to pass the grep pattern via a Node.js runner script that sets `process.argv` directly, bypassing the shell entirely.

**If patterns were resolved** (from `--cases` or `--filter`), build and run a temp Node.js script:

```powershell
$speed = "<fast|normal|slow>"   # from --speed flag, default 'normal'
$e2eDir = "C:\path\to\project\e2e"   # absolute path to e2e dir
$cliPath = "$e2eDir\node_modules\@playwright\test\cli.js"

# Build a JS array literal from the resolved patterns (each already has › replaced with >)
$patternsJs = ($resolvedPatterns | ForEach-Object {
    '"' + ($_ -replace '\\', '\\' -replace '"', '\"') + '"'
}) -join ','

$nodeScript = @"
process.chdir('$($e2eDir -replace '\\','\\')');
process.env.DEMO_SPEED = '$speed';
const grep = [$patternsJs].join('|');
process.argv = ['node', 'pw', 'test', '--headed', '--config', 'playwright.demo.config.ts', '--grep', grep, '--project=chromium'];
require('$($cliPath -replace '\\','\\')');
"@

$scriptFile = [System.IO.Path]::GetTempFileName() + '.demo.js'
$nodeScript | Out-File -FilePath $scriptFile -Encoding utf8
node $scriptFile
Remove-Item $scriptFile -ErrorAction SilentlyContinue
```

**If no patterns** (run all scenarios):
```powershell
$env:DEMO_SPEED = "<fast|normal|slow>"
Set-Location $e2eDir
npx playwright test --headed --config playwright.demo.config.ts --project=chromium
```

The `playwright.demo.config.ts` reads `DEMO_SPEED` and maps it to `launchOptions.slowMo`:
- `fast` → 1000ms
- `normal` → 5000ms  
- `slow` → 10000ms

This delay is applied between every Playwright action (clicks, navigations, inputs), giving viewers time to follow along.

---

## Step 4: Report Demo Results

After the demo run completes:

```
## 🎬 Demo Complete

### Scenarios Demonstrated
| Scenario             | Result    |
|----------------------|-----------|
| Dashboard            | ✅ / ❌    |
| Conversations        | ✅ / ❌    |
| ...                  |           |

### Overall: ✅ All scenarios passed / ❌ <N> scenarios had issues

> View full Playwright report: cd e2e && npm run test:report
```

If any scenarios failed during demo, list the failures with a note that these are test/mock issues vs actual bugs.

---

## Guardrails

- Default slow-mo is **800ms** — always apply it in headed mode unless `--speed` overrides it
- Always use `--headed` + `--slow-mo` for normal demo; `--ui` for pause mode (they are mutually exclusive)
- Only use the `chromium` project for demos (consistent experience)
- If the browser fails to open (headless environment), inform the user and suggest running locally
- Note that E2E tests mock the API — the demo shows the UI flow, not a live backend
