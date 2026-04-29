---
description: Run Parthenon tests. By default runs all 3 layers (backend pytest, frontend Vitest, E2E Playwright). Supports --backend, --frontend, --e2e to target specific layers. Supports --filter <pattern> to run specific tests or scenarios. Runs in IDE terminals for immediate feedback.
---

Run Parthenon application tests.

**Usage**: `/test-app [--backend] [--frontend] [--e2e] [--filter <pattern>]`

- No flags → run all 3 test layers
- `--backend` → run only backend pytest tests
- `--frontend` → run only frontend Vitest tests
- `--e2e` → run only E2E Playwright tests
- `--filter <pattern>` → filter tests by name/file pattern; applies to **all active layers**

**Important**: `--filter` alone (no layer flag) runs **all 3 layers** with the filter applied to each. Combine `--filter` with a layer flag to restrict to one layer.

Examples:
- `/test-app` — all 3 layers, no filter
- `/test-app --filter agent` — all 3 layers filtered by "agent"
- `/test-app --e2e` — E2E only, no filter
- `/test-app --backend --filter test_agents` — backend only, filtered by "test_agents"
- `/test-app --e2e --filter notifications` — E2E only, filtered by "notifications"

---

## Step 1: Parse Input

Read flags from the user's message.

If no layer flag is given, run all 3 layers. Capture `--filter <pattern>` if provided.

---

## Step 2: Run Backend Tests (pytest)

**Skip if `--frontend` or `--e2e` only.**

Run in IDE terminal (synchronous mode to see results immediately):

```powershell
cd backend
```

If `--filter <pattern>`:
```powershell
python -m pytest -v -k "<pattern>"
```
Otherwise:
```powershell
python -m pytest -v
```

Capture pass/fail counts from output. Record any failures with file + line.

---

## Step 3: Run Frontend Tests (Vitest)

**Skip if `--backend` or `--e2e` only.**

Run in IDE terminal (synchronous mode to see results immediately):

```powershell
cd frontend
```

If `--filter <pattern>`:
```powershell
npm run test -- --reporter=verbose -t "<pattern>"
```
Otherwise:
```powershell
npm run test
```

Capture pass/fail counts. Record any failures with component + test name.

---

## Step 4: Run E2E Tests (Playwright)

**Skip if `--backend` or `--frontend` only.**

**Pre-check**: Verify frontend preview server is running on port 4173.
```powershell
try {
    $response = Invoke-WebRequest -Uri "http://localhost:4173" -Method HEAD -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    $frontendUp = $response.StatusCode -eq 200
} catch {
    $frontendUp = $false
}
```

If NOT running, build and start it in IDE terminal:
```powershell
cd frontend
npm run build
```

Then start preview server using `run_in_terminal` with `mode=async` (will use "Parthenon Preview" terminal if available):
```powershell
cd frontend
npm run preview
```

Wait for server to be ready (max 20 seconds):
```powershell
$maxWait = 20
$waited = 0
while (-not $frontendUp -and $waited -lt $maxWait) {
    Start-Sleep -Seconds 2
    $waited += 2
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:4173" -Method HEAD -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        $frontendUp = $response.StatusCode -eq 200
    } catch { }
}

if (-not $frontendUp) {
    Write-Host "❌ Preview server failed to start - E2E tests cannot run"
    return
}
```

Run E2E tests in IDE terminal (synchronous):
```powershell
cd e2e
```

If `--filter <pattern>`:
```powershell
npx playwright test --grep "<pattern>"
```
Otherwise:
```powershell
npx playwright test
```

Capture pass/fail counts per spec file.

---

## Step 5: Report Results

```
## 🧪 Test Results

### Layer 1 — Backend (pytest)
- Total: N | ✅ Passed: N | ❌ Failed: N
<failures listed if any>

### Layer 2 — Frontend (Vitest)
- Total: N | ✅ Passed: N | ❌ Failed: N
<failures listed if any>

### Layer 3 — E2E (Playwright)
- Total: N | ✅ Passed: N | ❌ Failed: N
<failures listed if any>

### Overall: ✅ All Passing / ❌ <N> failures across <layers>
```

If any tests fail:
- List each failure with file, test name, and error message
- Suggest next steps (fix tests or check implementation)

---

## Guardrails

- Never skip a layer unless explicitly requested with a flag
- Always report full pass/fail counts, not just "tests passed"
- If frontend preview server was started to support E2E, note it in the report
- If E2E fails due to port 4173 not being available even after setup, report the setup error clearly
