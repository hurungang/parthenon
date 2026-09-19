---
description: Start Parthenon services using parthenon.ps1. Defaults to all services. Supports --infra, --backend, --frontend, --control-center, --agent-runtime, --communication-hub, --docker, --force, and --setup.
---

Start the Parthenon application.

**Usage**: `/start-app [--infra] [--backend] [--frontend] [--control-center] [--agent-runtime] [--communication-hub] [--docker] [--force] [--setup]`

- No flags → all services (infra + control-center + agent-runtime + communication-hub + frontend)
- `--infra` → infrastructure only (Keycloak, Postgres, Redis, OTEL)
- `--backend` → backend services: control-center + agent-runtime + communication-hub (excludes frontend)
- `--frontend` → frontend dev server only
- `--control-center` → Control Center only (port 8000)
- `--agent-runtime` → Agent Runtime only (port 8001)
- `--communication-hub` → Communication Hub only (port 8002)
- `--docker` → same as `--infra`
- `--force` → skip confirmation and force restart
- `--setup` → pass `-RunSetup` to bootstraps Keycloak, DB, and CA before starting (fresh environments only; use `/init-app` for first-time setup)

**Note**: `--backend` means backend services only. The old behavior where it included frontend was a bug — `parthenon.ps1`'s `-Services backend` alias misleadingly bundles frontend. This command always builds explicit service lists.

---

## Step 0: Ensure PowerShell Core

`parthenon.ps1` requires PowerShell 7+. Install `pwsh` if not present:

```bash
brew install powershell   # macOS
```

---

## Step 1: Parse Flags → Resolve Component Set

Read the user's message and determine which **components** are requested:

| Flag(s) | Components |
|---|---|
| (no flags) | `infra, control-center, agent-runtime, communication-hub, frontend` |
| `--infra` or `--docker` | `infra` |
| `--backend` | `control-center, agent-runtime, communication-hub` |
| `--frontend` | `frontend` |
| `--control-center` | `control-center` |
| `--agent-runtime` | `agent-runtime` |
| `--communication-hub` | `communication-hub` |

If multiple flags are present, merge the component sets (e.g., `--backend --frontend` = `control-center, agent-runtime, communication-hub, frontend`).

---

## Step 2: Check Current State

Run `pwsh ./parthenon.ps1 status` to see which services are already running.

Compare the running services against the **resolved component set** from Step 1.

### Build the Final Start List

For each component in the resolved set:

- **infra** is already running → **exclude** from start list (don't restart Docker unnecessarily)
- **infra** is stopped → keep in list
- Any backend service or frontend is already running → ask the user

If any backend/frontend components are running, present:

> `control-center` (or whatever) is already running. What would you like to do?

Options:
1. **Restart all** — force restart everything, including already-running services
2. **Start only missing** — start only stopped services (Recommended)
3. **Cancel**

- Option 1 → keep the full component set and add `-Force` when calling parthenon.ps1
- Option 2 → exclude already-running components from the start list
- Option 3 → halt

---

## Step 3: Launch Detached (macOS/Linux)

**CRITICAL**: On macOS/Linux, `parthenon.ps1 start` spawns background services. If the bash session that launched it ends, those services get killed. You must detach the start process so services survive independently.

Convert the final component list to a comma-separated `-Services` argument. **Always use an explicit comma-separated list** — never use the `all` or `backend` shortcuts from parthenon.ps1.

Append `-Force` if restarting (from user choice or `--force` flag).
Append `-RunSetup` if `--setup` was passed.

### Launch command (detached via nohup):

```bash
nohup pwsh ./parthenon.ps1 start -Services <comma,separated,list> [-Force] [-RunSetup] > /tmp/parthenon-start.log 2>&1 &
```

Examples:
```bash
# Infra already running, user typed /start-app with no flags → skip infra
nohup pwsh ./parthenon.ps1 start -Services control-center,agent-runtime,communication-hub,frontend > /tmp/parthenon-start.log 2>&1 &

# Fresh start from nothing
nohup pwsh ./parthenon.ps1 start -Services infra,control-center,agent-runtime,communication-hub,frontend > /tmp/parthenon-start.log 2>&1 &
```

---

## Step 4: Poll Until Ready

After launching detached, poll `parthenon.ps1 status` in a loop until all requested services show as running (or timeout after 90s):

```bash
# Poll status every 5s, up to 90s timeout
for i in $(seq 1 18); do
  echo "--- Poll $i ---"
  pwsh ./parthenon.ps1 status 2>/dev/null
  # Count how many of the requested services show "Running"
  RUNNING=$(pwsh ./parthenon.ps1 status 2>/dev/null | grep -c "Running" || true)
  EXPECTED=<number_of_requested_services>
  if [ "$RUNNING" -ge "$EXPECTED" ]; then
    echo "All services running."
    break
  fi
  sleep 5
done
```

Replace `<number_of_requested_services>` with the count of services being started (e.g., 4 for `control-center,agent-runtime,communication-hub,frontend`).

After the loop finishes, run one final status to confirm:

```bash
pwsh ./parthenon.ps1 status
```

Report the outcome from the status output. If `grep -c "Stopped"` returns >0 for any requested service, report startup as incomplete with the failed services. Do not add additional curl probes.
