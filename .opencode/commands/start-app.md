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

## Step 0: Ensure PowerShell Core

`parthenon.ps1` requires PowerShell 7+. On macOS/Linux, install `pwsh` if not present:

```bash
brew install powershell   # macOS
# or: sudo apt install powershell  # Ubuntu
```

Verify with `pwsh --version`. On Windows, PowerShell 7+ (`pwsh.exe`) is assumed.

**All script invocations below use `pwsh` on macOS/Linux or `pwsh.exe` on Windows.**

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

```bash
docker info > /dev/null 2>&1 || echo "Docker not available"
```

If Docker is not ready, halt with a clear message.

If frontend is requested, prevent stale preview confusion:
- Frontend dev server must be `http://localhost:5173`
- Port 4173 is Vite preview and should not be treated as frontend-ready for `/start-app`

If `:4173` is listening and `:5173` is not, stop the stale preview process before start:

```bash
if lsof -ti :4173 -sTCP:LISTEN >/dev/null 2>&1 && ! lsof -ti :5173 -sTCP:LISTEN >/dev/null 2>&1; then
  kill $(lsof -ti :4173 -sTCP:LISTEN) 2>/dev/null
  echo "Stopped stale preview process on port 4173."
fi
```

---

## Step 3: Run Stack Command

From the project root, execute the management script via `pwsh`:

```bash
pwsh ./parthenon.ps1 start -Services <resolved_services> <optional_force_flag>
```

Examples:

```bash
pwsh ./parthenon.ps1 start -Services all
pwsh ./parthenon.ps1 start -Services infra
pwsh ./parthenon.ps1 start -Services backend -Force
pwsh ./parthenon.ps1 start -Services control-center,agent-runtime
```

`parthenon.ps1` handles:
- Platform detection (Windows/macOS/Linux)
- Dependency order (infra → control-center → agent-runtime → communication-hub → frontend)
- Health-check waiting for each service
- Port conflict detection and `-Force` restart

**If `--setup` was specified**, pass `-RunSetup` to `parthenon.ps1`:

```bash
pwsh ./parthenon.ps1 start -Services all -RunSetup
```

This bootstraps Keycloak realms, database seeding, and certificate authority before starting services.

---

## Step 4: Verify Service Health

Always run status after start:

```bash
pwsh ./parthenon.ps1 status
```

Probe only services requested (or implied by `all` / `backend`):

```bash
# Health checks via curl (works cross-platform)
curl -sf http://localhost:8082/health/ready  # Keycloak
curl -sf http://localhost:8000/health         # Control Center
curl -sf http://localhost:8001/health         # Agent Runtime
curl -sf http://localhost:8002/health         # Communication Hub
curl -sf http://localhost:5173                # Frontend
```

If any requested service fails health checks, report startup as incomplete and include the failed endpoint(s). Do not print a success summary until all requested probes pass.

---

## Step 5: Report Outcome

Provide a concise result with:

- Executed command
- Resolved service set
- Status per requested service: Started / Already running / Failed / Skipped
- Access URLs:
  - Frontend: `http://localhost:5173`
  - Control Center API: `http://localhost:8000/api/v1`
  - Agent Runtime health: `http://localhost:8001/health`
  - Communication Hub health: `http://localhost:8002/health`
  - Keycloak: `http://localhost:8082`
