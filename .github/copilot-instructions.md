# Parthenon — Copilot Instructions

## Mandatory Pre-Change Check

Before making any code or documentation change, contributors and agents must first review `docs/config.yaml` and ensure the change complies with every `top_priority_rules` entry; if any conflict exists, stop and escalate for clarification.

## Running Dev Servers (Windows)

**Do NOT use `powershell` async sessions to run dev servers.** Async sessions (even with `detach: true`) are tied to the agent context and die when the session closes.

**Always use `Start-Process` to launch servers** so they persist in their own window independent of the agent:

```powershell
# Backend
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "cd /d c:\...\backend && python -m uvicorn app.main:app --reload --port 8000"

# Frontend
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "cd /d c:\...\frontend && npm run dev"
```

This opens a visible cmd window that survives agent session end. Verify the server is up with a quick HTTP check after starting:

```powershell
Start-Sleep 8
Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing | Select-Object StatusCode
```

## Port Conflicts

Port 8080 is already occupied on this machine (Node.js / Docker backend process).  
**Keycloak must use port 8082** (`docker-compose.yml` maps `8082:8080`).

Env defaults for local dev (`frontend/.env.local`):
- `VITE_OIDC_AUTHORITY=http://localhost:8082/realms/parthenon`
- `VITE_OIDC_CLIENT_ID=parthenon-api-ui`
- `VITE_API_BASE_URL=http://localhost:8000/api/v1`

<!-- ## Running Frontend Vitest Tests (Windows / Copilot CLI)

**NEVER run `npx vitest run` with a terminal reporter inside the Copilot CLI agent.**  
Vitest's default and verbose reporters use ANSI escape sequences that overflow/deadlock the Copilot CLI's stdout pipe on Windows, causing the process to hang indefinitely after ~988 lines of output. This affects all Vitest versions including 4.x. (See: https://github.com/github/copilot-cli/issues/3308) -->
<!-- 
**Always use the JSON reporter writing directly to a file:**

```powershell
cd frontend
npx vitest run --reporter=json --outputFile=vitest_results.json
Write-Host "EXIT: $LASTEXITCODE"
```

Then read the results:
```powershell
$j = Get-Content frontend/vitest_results.json | ConvertFrom-Json
Write-Host "Passed: $($j.numPassedTests) / $($j.numTotalTests)  Failed: $($j.numFailedTests)"
```

To see which tests failed:
```powershell
$j.testResults | Where-Object { $_.status -eq 'failed' } | ForEach-Object {
    Write-Host $_.testFilePath
    $_.assertionResults | Where-Object { $_.status -eq 'failed' } | ForEach-Object { Write-Host "  × $($_.fullName)" }
}
```

## temporary test scripts

temporary test scripts for quick local testing of auth flows, etc. must be saved under `scripts/` and should be named descriptively (e.g. `test-auth-flows.ps1`) to avoid confusion with production scripts. These are not intended for long-term use and can be deleted after testing is complete.

temporary output files generated during testing (e.g. token dumps, test logs) should be saved under `tmp/` with descriptive names (e.g. `auth-flow-test-output.txt`) and can be deleted after review. This keeps the project organized and prevents clutter in the main directories.   -->

## use tmp folder for any temporary output files generated during testing (e.g. token dumps, test logs) with descriptive names (e.g. `auth-flow-test-output.txt`) and can be deleted after review. This keeps the project organized and prevents clutter in the main directories.