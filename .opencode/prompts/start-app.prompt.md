---
description: Start Parthenon services using parthenon.ps1. Defaults to all services. Supports --infra, --backend, --frontend, --control-center, --agent-runtime, --communication-hub, --docker, and --force.
---

Start the Parthenon application.

**Usage**: `/start-app [--infra] [--backend] [--frontend] [--control-center] [--agent-runtime] [--communication-hub] [--docker] [--force] [--setup]`

- No flags -> start all services (`infra,control-center,agent-runtime,communication-hub,frontend`)
- `--infra` -> start infrastructure only (Keycloak, Postgres, Redis, OTEL)
- `--backend` -> start backend stack (control-center, agent-runtime, communication-hub, frontend)
- `--frontend` -> start frontend dev server only
- `--control-center` -> start Control Center only (port 8000)
- `--agent-runtime` -> start Agent Runtime only (port 8001)
- `--communication-hub` -> start Communication Hub only (port 8002)
- `--docker` -> start dockerized stack services supported by `parthenon.ps1` (equivalent service target in script)
- `--force` -> pass `-Force` to `parthenon.ps1`
- `--setup` -> run `python -m setup.main dev` first to bootstrap Keycloak realms, DB seeding, and CA before starting services

---

## Step 1: Parse Input

Read the user's message and map flags to `-Services` values.

Service mapping:
- `--infra` -> `infra`
- `--backend` -> `backend`
- `--frontend` -> `frontend`
- `--control-center` -> `control-center`
- `--agent-runtime` -> `agent-runtime`
- `--communication-hub` -> `communication-hub`
- `--docker` -> `docker`

If no service flags are provided, use `all`.

If multiple service flags are present, combine as comma-separated values in dependency-safe order:
`infra,control-center,agent-runtime,communication-hub,frontend`.

If `--backend` is present with other backend-service flags, prefer `backend` (do not duplicate).

---

## Step 2: Prerequisite Checks

If requested services include `infra`, `backend`, `all`, or `docker`, verify Docker engine availability before starting:

```powershell
$dockerReady = $false
try {
  docker info | Out-Null
  $dockerReady = $true
} catch {
  $dockerReady = $false
}

if (-not $dockerReady) {
  Write-Host "Docker engine is not ready. Start Docker Desktop, then retry when `docker info` succeeds."
  return
}
```

If frontend is requested, prevent stale preview confusion:
- Frontend dev server must be `http://localhost:5173`
- Port 4173 is Vite preview and should not be treated as frontend-ready for `/start-app`

If `:4173` is listening and `:5173` is not, stop the stale preview process before start:

```powershell
$previewPid = (netstat -ano | Select-String ":4173 .*LISTEN" | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -First 1)
$devPid = (netstat -ano | Select-String ":5173 .*LISTEN" | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -First 1)

if ($previewPid -and -not $devPid) {
  Stop-Process -Id [int]$previewPid -Force -ErrorAction SilentlyContinue
  Write-Host "Stopped stale preview process on port 4173 (PID $previewPid)."
}
```

## Step 3: Run Stack Command

From the project root, execute the management script:

```powershell
.\parthenon.ps1 start -Services <resolved_services> <optional_force>
```

Examples:

```powershell
.\parthenon.ps1 start -Services all
.\parthenon.ps1 start -Services infra
.\parthenon.ps1 start -Services backend -Force
.\parthenon.ps1 start -Services control-center,agent-runtime
```

If script execution is blocked, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Then retry once.

**If `--setup` was specified**, run the consolidated setup tool before starting services:

```powershell
python -m setup.main dev
```

This bootstraps Keycloak realms, database seeding, and certificate authority. Uses a `.setup-complete.marker` file to detect if setup has already been run and skip re-running.

The `-RunSetup` flag on `parthenon.ps1` handles this automatically — prefer using the management script.

---

## Step 4: Verify Service Health

Always run status after start:

```powershell
.\parthenon.ps1 status
```

Probe only services requested (or implied by `all` / `backend`):

```powershell
# Infra / Keycloak
Invoke-WebRequest -Uri "http://localhost:8082/health/ready" -UseBasicParsing -TimeoutSec 5

# Control Center
Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 5

# Agent Runtime
Invoke-WebRequest -Uri "http://localhost:8001/health" -UseBasicParsing -TimeoutSec 5

# Communication Hub
Invoke-WebRequest -Uri "http://localhost:8002/health" -UseBasicParsing -TimeoutSec 5

# Frontend
Invoke-WebRequest -Uri "http://localhost:5173" -UseBasicParsing -TimeoutSec 5
```

If any requested service fails health checks, report startup as incomplete and include the failed endpoint(s). Do not print a success summary until all requested probes pass.

---

## Step 5: Report Outcome

Provide a concise result with:

- Executed command
- Resolved service set
- Status per requested service: Started / Already running / Failed / Skipped
- Access URLs:
  - Frontend: http://localhost:5173
  - Control Center API: http://localhost:8000/api/v1
  - Agent Runtime health: http://localhost:8001/health
  - Communication Hub health: http://localhost:8002/health
  - Keycloak: http://localhost:8082
