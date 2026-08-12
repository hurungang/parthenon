# Parthenon — Enterprise AI Harness Framework

[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)
[![Status](https://img.shields.io/badge/status-active-success.svg)](https://github.com/hurungang/parthenon)

**Self-hosted AI agents with enterprise-grade security, observability, and governed tool access — all running on your own infrastructure.**

## Why Parthenon

- **Run AI agents on your own infrastructure.** No third-party SaaS holding your data. Parthenon deploys on Docker Compose locally or Kubernetes in production — you control everything.
- **Know exactly what your agents are doing.** Every action is logged. Every tool call is governed by Role → SOP → Skill → Tool permissions. OpenTelemetry traces, metrics, and logs out of the box.
- **Agents and humans have separate identities.** No blurred lines. Dual identity model with clear audit boundaries — you always know who (or what) did what.
- **Three isolated backend services.** Agent Runtime, Control Center, and Communication Hub run independently. Compromise the runtime, and your database stays safe.
- **Bring your own LLM.** Parthenon connects to any OpenAI-compatible API — use GPT-4, Claude, open-source models, whatever you want. No vendor lock-in.

## Demo

![Parthenon Feature Demo Teaser](docs/demo-teaser.gif)

▶️ **[Watch the Full 59-Minute Feature Walkthrough on YouTube](https://youtu.be/uW4r8Ygj15Y)** — covers architecture, IAM, MCP Hub, agents, HITL, delegation, notifications, and observability.

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

## Built with easyspec

Parthenon's documentation, architecture, and development workflow are managed using [easyspec](https://github.com/hurungang/easyspec) — an open source spec-driven development kit that orchestrates a team of AI agents (product owner, architect, developer, tester, etc.) through the full change lifecycle. Every feature in Parthenon goes through easyspec's propose → apply → update-master pipeline.

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
