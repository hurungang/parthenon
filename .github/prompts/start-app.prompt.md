---
description: Start Parthenon services using parthenon.ps1. Defaults to all services. Supports --infra, --backend, --frontend, --control-center, --agent-runtime, --communication-hub, and --force.
---

Start the Parthenon application.

**Usage**: `/start-app [--infra] [--backend] [--frontend] [--control-center] [--agent-runtime] [--communication-hub] [--force]`

- No flags -> start all services (`infra,control-center,agent-runtime,communication-hub,frontend`)
- `--infra` -> start infrastructure only (Keycloak, Postgres, Redis, OTEL)
- `--backend` -> start backend stack (control-center, agent-runtime, communication-hub, frontend)
- `--frontend` -> start frontend dev server only
- `--control-center` -> start Control Center only (port 8000)
- `--agent-runtime` -> start Agent Runtime only (port 8001)
- `--communication-hub` -> start Communication Hub only (port 8002)
- `--force` -> pass `-Force` to `parthenon.ps1`

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

If no service flags are provided, use `all`.

If multiple service flags are present, combine as comma-separated values in dependency-safe order:
`infra,control-center,agent-runtime,communication-hub,frontend`.

If `--backend` is present with other backend-service flags, prefer `backend` (do not duplicate).

---

## Step 2: Run Stack Command

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

---

## Step 3: Verify Service Health

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

If any requested service fails health checks, report startup as incomplete and include the failed endpoint(s).

---

## Step 4: Report Outcome

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
