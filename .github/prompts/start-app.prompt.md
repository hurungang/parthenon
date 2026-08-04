# /start-app

Start the Parthenon full-stack application for local development.

## Port Reference

| Component | Port | Health Check |
|-----------|------|-------------|
| Control Center (CC) | 8000 | `GET http://localhost:8000/api/v1/health` |
| Agent Runtime (AR) | 8001 | `GET http://localhost:8001/health` |
| Communication Hub (CH) | 8002 | `GET http://localhost:8002/health` |
| Frontend (Vite dev) | 5173 | `GET http://localhost:5173` |
| Keycloak | 8082 | `GET http://localhost:8082` |
| PostgreSQL | 5432 | TCP connect |

⚠️ Port 5173 = Vite dev server. Port 4173 = Vite preview server (do NOT use for development).

## Flags

- `--frontend` — Start only the React/Vite frontend (port 5173)
- `--backend` — Start all three backend services (CC→AR→CH)
- `--infra` — Start Docker services (PostgreSQL, Keycloak, Redis)
- `--docker` — Same as `--infra`

No flag = start everything (infra → backend → frontend).

## Prerequisites

- Docker Desktop must be running for infra
- Python 3.11+ with `.venv` at project root
- Node.js 18+ in `frontend/`

## Startup Order

1. **Infrastructure**: `docker compose up -d` (from project root). Wait for healthy.
2. **Control Center**: Start via `parthenon.ps1 start -Services control-center` or directly via `.venv/bin/python3 -m uvicorn app.main:app --port 8000` (workdir: `backend/`). Wait for `/api/v1/health` to return 200.
3. **Agent Runtime**: Start via `parthenon.ps1 start -Services agent-runtime` or directly. Wait for `/health` to return 200.
4. **Communication Hub**: Start via `parthenon.ps1 start -Services communication-hub` or directly. Wait for `/health` to return 200.
5. **Frontend**: `npm run dev` in `frontend/`. Wait for port 5173.

## Important

- CH and AR need CC running first for certificate bootstrap
- On Windows, use `parthenon.ps1` to manage services
- If CH/AR logs show "no certificate manager available", restart those services
- Kill any stale preview server on port 4173 before starting dev server on 5173
- Verify each service with HTTP probe before confirming ready — do NOT report started until all probes pass

## After Startup

Report all endpoints with status:
```
✅ Application Started
  Infra:      ⏭️ Already running
  CC (8000):  ✅ Started
  AR (8001):  ✅ Started
  CH (8002):  ✅ Started
  Frontend:   ✅ http://localhost:5173
```
