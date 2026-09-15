# /start-app

Start the Parthenon full-stack application for local development. Delegates to `parthenon.ps1` which handles startup order, health checks, and certificate bootstrapping.

## Port Reference

| Component | Port |
|---|---|
| Control Center (CC) | 8000 |
| Agent Runtime (AR) | 8001 |
| Communication Hub (CH) | 8002 |
| Frontend (Vite dev) | 5173 |
| Keycloak | 8082 |
| PostgreSQL | 5432 |

Port 5173 = Vite dev server. Port 4173 = Vite preview (do NOT use for development).

## Flags

| Flag | Starts |
|---|---|
| (none) | Everything (infra + CC + AR + CH + frontend) |
| `--infra` / `--docker` | Infrastructure only (PostgreSQL, Keycloak, Redis) |
| `--backend` | Backend services only (CC + AR + CH) |
| `--frontend` | Frontend dev server only |
| `--control-center` | Control Center only |
| `--agent-runtime` | Agent Runtime only |
| `--communication-hub` | Communication Hub only |
| `--force` | Skip confirmation, force restart |
| `--setup` | Run `-RunSetup` first (fresh environments only) |

## Process

1. **Parse flags** → resolve to a set of components
2. **Check Docker engine first** (only when infra is in scope): if `docker info` fails, Docker Desktop isn't running — start it (`open -a Docker` on macOS) and poll `docker info` until the engine responds (max 60s) before any `docker compose` attempt
3. **Kill stale preview server**: if port 4173 is occupied but 5173 is not, a Vite preview process is stale — kill the process on 4173 (`lsof -ti :4173 | xargs kill`) before starting `npm run dev`
4. **Check what's running**: `pwsh ./parthenon.ps1 status`
5. **Smart mapping**:
   - Infra already running → exclude it (don't restart Docker unnecessarily)
   - Backend/frontend already running → ask: restart all, start only missing, or cancel?
6. **Build explicit comma-separated list** for parthenon.ps1 (never use `all`/`backend` shortcuts)
7. **Launch detached** (macOS/Linux): `nohup pwsh ./parthenon.ps1 start -Services <list> [-Force] > /tmp/parthenon-start.log 2>&1 &`
   - CRITICAL: Use `nohup` so services survive the bash session ending. On macOS, services launched via `pwsh` inside a bash tool get killed when bash terminates.
8. **Poll until ready**: Loop `pwsh ./parthenon.ps1 status` every 5s (max 90s), count "Running" lines vs expected services
9. **Probe every in-scope service** before declaring ready — a "Running" status line is not enough; verify each HTTP endpoint actually responds:
   - CC: `Invoke-WebRequest http://localhost:8000/health` (or the documented health path)
   - AR: `http://localhost:8001/health`, CH: `http://localhost:8002/health`
   - Frontend: `http://localhost:5173` (NEVER 4173)
   - If any probe fails, report the failure WITH log context from `backend/logs/*.log` / `/tmp/parthenon-start.log` — do NOT show the "✅ Application Started" summary
10. **Report endpoints clearly** — one line per component with its actual state:
    `✅ Started` / `⏭️ Already running` / `⏭️ Skipped (flag not set)` + URL

`parthenon.ps1` handles all dependency ordering, health-check waiting, port conflict detection, and certificate bootstrapping internally — but the final HTTP probes in step 9 are still required before confirming ready.
