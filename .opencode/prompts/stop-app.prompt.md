---
description: Stop Parthenon services using parthenon.ps1. Defaults to all services. Supports --infra, --backend, --frontend, --control-center, --agent-runtime, --communication-hub, and --force.
---

Stop the Parthenon application.

**Usage**: `/stop-app [--infra] [--backend] [--frontend] [--control-center] [--agent-runtime] [--communication-hub] [--force]`

- No flags -> stop all services (`frontend,communication-hub,agent-runtime,control-center,infra`)
- `--infra` -> stop infrastructure only
- `--backend` -> stop backend stack (control-center, agent-runtime, communication-hub, frontend)
- `--frontend` -> stop frontend only
- `--control-center` -> stop Control Center only
- `--agent-runtime` -> stop Agent Runtime only
- `--communication-hub` -> stop Communication Hub only
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

If multiple service flags are present, combine as comma-separated values.

If `--backend` is present with other backend-service flags, prefer `backend`.

---

## Step 2: Run Stack Command

From the project root, execute:

```powershell
.\parthenon.ps1 stop -Services <resolved_services> <optional_force>
```

Examples:

```powershell
.\parthenon.ps1 stop -Services all
.\parthenon.ps1 stop -Services backend
.\parthenon.ps1 stop -Services infra
.\parthenon.ps1 stop -Services control-center,agent-runtime
```

If script execution is blocked, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Then retry once.

---

## Step 3: Verify Services Stopped

Always run:

```powershell
.\parthenon.ps1 status
```

Optionally validate key ports are no longer listening for requested services:

```powershell
netstat -ano | Select-String ":5173 .*LISTEN|:8000 .*LISTEN|:8001 .*LISTEN|:8002 .*LISTEN"
```

For infra checks, confirm containers are stopped:

```powershell
docker ps --format "{{.Names}}"
```

---

## Step 4: Report Outcome

Provide:

- Executed command
- Resolved service set
- Status per requested service: Stopped / Not running / Failed
- Any remaining listening ports or containers if stop was incomplete
