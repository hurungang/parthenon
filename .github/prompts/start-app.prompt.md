---
description: Start the Parthenon application. By default starts both frontend and backend (including infrastructure). Supports --frontend, --backend, --infra flags to start only specific parts. Use --docker to start everything via docker compose. Checks if already running before starting. Uses named IDE terminals that can be reused.
---

Start the Parthenon application.

**Usage**: `/start-app [--frontend] [--backend] [--infra] [--docker]`

- No flags → start everything (infra + backend + frontend) locally
- `--frontend` → start only the frontend dev server
- `--backend` → start only the backend API + infra (postgres, redis)
- `--infra` → start only infrastructure (postgres, redis via docker)
- `--docker` → start the full stack via `docker compose up -d`

**Terminal Management**: Services run in named IDE terminals that remain visible and can be reused:
- Backend: **"Parthenon Backend"** terminal (port 8000)
- Frontend: **"Parthenon Frontend"** terminal (port 5173)
- Preview: **"Parthenon Preview"** terminal (port 4173, for demos)

---

## Step 1: Parse Input

Read the user's message for flags: `--frontend`, `--backend`, `--infra`, `--docker`.

If no flags, default mode = start everything locally.

---

## Step 2: Check What Is Already Running

**Check ports and processes:**

```powershell
# Check backend (port 8000)
$backendRunning = (netstat -ano | Select-String ":8000 .*LISTEN") -ne $null

# Check frontend dev server (port 5173 only — port 4173 is preview mode, not dev mode)
$frontendDevRunning = (netstat -ano | Select-String ":5173 .*LISTEN") -ne $null
$frontendPreviewRunning = (netstat -ano | Select-String ":4173 .*LISTEN") -ne $null
$frontendRunning = $frontendDevRunning

# Check docker containers
$dockerRunning = (docker ps --format "{{.Names}}" 2>$null | Select-String "parthenon") -ne $null
```

**Report what is already running** before proceeding. If a component is already running, skip starting it and note "already running".

**If `$frontendPreviewRunning` is true but `$frontendDevRunning` is false**: the preview server (port 4173) is running instead of the dev server. Stop it before starting the dev server:
```powershell
$pid = (netstat -ano | Select-String ":4173 .*LISTEN" | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -First 1)
Stop-Process -Id $pid -Force
```

---

## Step 3: Start Infrastructure (postgres + redis + keycloak)

**Skip if: `--frontend` only, or docker containers already running.**

Check if docker is available:
```powershell
docker info 2>&1 | Select-String "Server Version"
```

Start infra containers (including Keycloak):
```powershell
cd <project_root>
docker compose up postgres redis keycloak -d
```

Wait for healthy status:
```powershell
docker compose ps postgres redis keycloak
```

**Wait for Keycloak to be healthy** (it has a 60 s start_period — poll `/health/ready`):
```powershell
$maxWait = 90
$elapsed = 0
do {
    Start-Sleep -Seconds 5
    $elapsed += 5
    $kc = try { Invoke-WebRequest -Uri "http://localhost:8082/health/ready" -UseBasicParsing -TimeoutSec 3 } catch { $null }
} while (($kc -eq $null -or $kc.StatusCode -ne 200) -and $elapsed -lt $maxWait)
if ($kc -eq $null -or $kc.StatusCode -ne 200) {
    Write-Warning "Keycloak did not become healthy within ${maxWait}s — check logs with: docker compose logs keycloak"
}
```

---

## Step 4: Start Backend (if not --frontend only)

**Skip if already running on port 8000 or `--frontend` flag.**

**Start backend in IDE terminal with reusable name "Parthenon Backend":**

1. Check if "Parthenon Backend" terminal already exists and is running the server:
   - If it exists and server is responding on port 8000, reuse it (no action needed)
   - If it exists but not running server, reuse it to start the server
   - If it doesn't exist, create it

2. Start backend using `run_in_terminal` with `mode=async`:
   ```powershell
   cd backend
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   
   **Terminal will remain visible in IDE** and can be reused across sessions.
   The terminal ID returned can be used with `get_terminal_output` to check output.

3. Wait up to 20 seconds for the backend to be ready:
   ```powershell
   $maxWait = 20
   $waited = 0
   $backendOk = $false
   
   while (-not $backendOk -and $waited -lt $maxWait) {
       Start-Sleep -Seconds 2
       $waited += 2
       try {
           $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
           if ($response.StatusCode -eq 200) {
               Write-Host "✅ Backend ready on port 8000"
               $backendOk = $true
           }
       } catch {
           # Still starting, keep waiting
       }
   }
   
   if (-not $backendOk) {
       Write-Host "❌ Backend failed to start within ${maxWait}s"
       Write-Host "Check the 'Parthenon Backend' terminal for errors"
   }
```
```

---

## Step 5: Start Frontend (if not --backend or --infra only)

**Skip if already running on port 5173 (dev server). Do NOT treat port 4173 (preview server) as the frontend being ready — always start the dev server on 5173.**

**Start frontend in IDE terminal with reusable name "Parthenon Frontend":**

1. Check if "Parthenon Frontend" terminal already exists and is running the dev server:
   - If it exists and server is responding on port 5173, reuse it (no action needed)
   - If it exists but not running server, reuse it to start the server
   - If it doesn't exist, create it

2. Start frontend using `run_in_terminal` with `mode=async`:
   ```powershell
   cd frontend
   npm run dev
   ```
   
   **Terminal will remain visible in IDE** and can be reused across sessions.

3. Wait up to 15 seconds for port 5173 to be listening:
   ```powershell
   $maxWait = 15
   $waited = 0
   $frontendOk = $false
   
   while (-not $frontendOk -and $waited -lt $maxWait) {
       Start-Sleep -Seconds 2
       $waited += 2
       $port = netstat -ano | Select-String ":5173 .*LISTEN"
       if ($port) {
           Write-Host "✅ Frontend dev server ready on port 5173"
           $frontendOk = $true
       }
   }
   
   if (-not $frontendOk) {
       Write-Host "❌ Frontend failed to start within ${maxWait}s"
       Write-Host "Check the 'Parthenon Frontend' terminal for errors"
   }
```

---

## Step 6: Verify All Started Services

Before reporting to the user, probe every service that was started or was already running in this session. Use HTTP requests — do **not** skip this step even if the process appeared to start cleanly.

```powershell
# Backend health check
try {
    $be = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 5
    $backendOk = $be.StatusCode -eq 200
} catch { $backendOk = $false }

# Frontend dev server check
try {
    $fe = Invoke-WebRequest -Uri "http://localhost:5173" -UseBasicParsing -TimeoutSec 5
    $frontendOk = $fe.StatusCode -lt 500
} catch { $frontendOk = $false }
```

**If any check fails**: report the failure clearly, show the last log lines for that process, and do NOT show the "✅ Application Started" summary. Instead show:

```
⚠️ Startup Incomplete

| Service   | Status  | URL                        |
|-----------|---------|----------------------------|
| Backend   | ❌ FAIL | http://localhost:8000/health |
| Frontend  | ✅ OK   | http://localhost:5173        |

Check the process logs above for errors.
```

Only proceed to Step 7 if all started services respond successfully.

---

## Step 6b: Docker Mode (--docker flag)

**Instead of Steps 3–5**, run the full compose stack:

```powershell
cd <project_root>
docker compose up -d
```

Wait for all services to be healthy:
```powershell
docker compose ps
```

---

## Step 7: Report Access Endpoints

Once all verification checks pass (Step 6), display the access information:

```
## ✅ Parthenon Application Started

### Access Endpoints
| Service       | URL                                      |
|---------------|------------------------------------------|
| Frontend App  | http://localhost:5173 (dev server)       |
| Backend API   | http://localhost:8000/api/v1             |
| API Docs      | http://localhost:8000/docs               |
| Keycloak      | http://localhost:8082 (admin: /admin)    |

> Docker mode: App available at http://localhost (nginx proxy on port 80)
> API at http://localhost/api/v1
```

List each component and its status: ✅ Started / ⏭️ Already running / ⏭️ Skipped.
