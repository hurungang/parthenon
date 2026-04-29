# Parthenon — Enterprise AI Harness Framework

Parthenon is a full-stack Enterprise AI Harness that provides a unified platform for managing AI agents, MCP tool servers, skills, SOPs, and observability.

## Architecture

- **Backend**: Python 3.11+ / FastAPI / SQLAlchemy 2 (async) / PostgreSQL 16 / Redis
- **Frontend**: React 19 / TypeScript / MUI 7 / React Router 7 / Vite
- **Auth**: OIDC/OAuth2 (Keycloak / EntraID)
- **Infra**: Docker Compose + Kubernetes/Helm + nginx + OTEL Collector

## Getting Started

### Using the Management Script (Recommended)

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
