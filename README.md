# Parthenon — Enterprise AI Harness Framework

Parthenon is a self-hosted framework for running enterprise AI agents with strong control, security, and observability.

## Why Parthenon

- **Secure by design**: three isolated backend services, Agent Runtime-only execution, Control Center-only database access, and no sensitive token exposure to agents.
- **Governed MCP access**: permissions resolve through `Role -> SOP -> Skill -> Tool`, enforcing least privilege at tool level.
- **Dual identity model**: separate human and agent identities with clear audit boundaries.
- **Flexible agent modes**: conversational, trigger-only, and argument-based execution patterns.
- **Operational confidence**: built-in execution logs plus OpenTelemetry traces, metrics, and logs.
- **Enterprise-ready deployment**: local Docker Compose workflow and production Kubernetes/Helm path.

## Tech Stack

- **Backend**: Python 3.11+ / FastAPI / SQLAlchemy 2 (async) / PostgreSQL 16 / Redis
- **Frontend**: React 19 / TypeScript / MUI 7 / React Router 7 / Vite
- **Auth**: OIDC/OAuth2 (Keycloak / EntraID)
- **Infra**: Docker Compose + Kubernetes/Helm + nginx + OTEL Collector

## Getting Started

### First-Time Setup

1. **Start infrastructure** (PostgreSQL, Redis, Keycloak):
   ```powershell
   .\parthenon.ps1 start -Services infra
   ```

2. **Initialize local development environment**:
   ```powershell
   .\parthenon.ps1 init
   ```
   This creates:
   - Keycloak realms (human users + agents)
   - OIDC clients in both realms
   - Admin user and database roles
   
   Safe to run multiple times.

3. **Run database migrations**:
   ```powershell
   cd backend
   alembic upgrade head
   ```

4. **Start all services**:
   ```powershell
   .\parthenon.ps1 start
   ```

5. **Access the application**:
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:8000/docs
   - Login: `admin@parthenon.local` / `admin`

### Using the Management Script

```powershell
# Check status of all services
.\parthenon.ps1 status

# Start all services (infra → backend → frontend)
.\parthenon.ps1 start

# Start specific services
.\parthenon.ps1 start -Services backend

# Stop all services
.\parthenon.ps1 stop

# Restart with force (skip prompts)
.\parthenon.ps1 restart -Force
```

See [PARTHENON-SCRIPT-GUIDE.md](PARTHENON-SCRIPT-GUIDE.md) for detailed usage.

### Manual Start

```bash
# Start infrastructure only
docker compose up -d

# Backend dev
cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload

# Frontend dev
cd frontend && npm install && npm run dev
```

## Project Structure

```
Parthenon/
├── backend/        # FastAPI application
├── frontend/       # React SPA
├── e2e/            # End-to-end tests
├── infra/          # Docker Compose, Helm, nginx config
└── docs/           # Documentation
```

## License

Parthenon is licensed under the GNU Affero General Public License v3.0 or any
later version. See [LICENSE](LICENSE).

For organizations that need to use Parthenon under proprietary or other
commercial terms, separate commercial licensing may be available. See
[LICENSE-COMMERCIAL.md](LICENSE-COMMERCIAL.md).

## Contributing

Community contributions are welcome. By contributing, you agree that your
contribution is provided under AGPL-3.0-or-later and may also be relicensed by
the maintainers under separate commercial terms. Pull requests are gated by an
explicit CLA acceptance check; if the bot asks you to sign, reply on the pull
request with the exact acceptance text from [CLA.md](CLA.md). See
[CONTRIBUTING.md](CONTRIBUTING.md).
