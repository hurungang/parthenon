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
2. **Check what's running**: `pwsh ./parthenon.ps1 status`
3. **Smart mapping**:
   - Infra already running → exclude it (don't restart Docker unnecessarily)
   - Backend/frontend already running → ask: restart all, start only missing, or cancel?
4. **Build explicit comma-separated list** for parthenon.ps1 (never use `all`/`backend` shortcuts)
5. **Launch detached** (macOS/Linux): `nohup pwsh ./parthenon.ps1 start -Services <list> [-Force] > /tmp/parthenon-start.log 2>&1 &`
   - CRITICAL: Use `nohup` so services survive the bash session ending. On macOS, services launched via `pwsh` inside a bash tool get killed when bash terminates.
6. **Poll until ready**: Loop `pwsh ./parthenon.ps1 status` every 5s (max 90s), count "Running" lines vs expected services
7. **Report**: Final `pwsh ./parthenon.ps1 status` output

`parthenon.ps1` handles all dependency ordering, health-check waiting, port conflict detection, and certificate bootstrapping internally.
