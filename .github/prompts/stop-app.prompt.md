# /stop-app

Stop the Parthenon full-stack application.

## Steps

1. **Frontend**: Kill the Vite dev server (process on port 5173)
2. **Backend services**: Stop Control Center (8000), Agent Runtime (8001), Communication Hub (8002)
   - On Windows, use: `.\parthenon.ps1 stop -Services backend -Force`
   - On macOS/Linux: `kill $(lsof -ti:8000,8001,8002)`
3. **Infrastructure** (optional): `docker compose down` from project root
4. **Verify**: All ports 5173, 8000, 8001, 8002, 8082, 5432 are free

## Flags

- `--frontend` — Stop only the frontend
- `--backend` — Stop only the backend services
- `--infra` or `--docker` — Stop Docker services
- `--all` — Stop everything (default)
