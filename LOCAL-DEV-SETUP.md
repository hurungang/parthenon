# Local Development Setup

## Overview

This guide explains how to run Parthenon services locally with fast-reload development workflow.

**Architecture:**
- **Infrastructure (Docker):** PostgreSQL, Redis, Keycloak, OTEL Collector, Jaeger, Prometheus, Loki
- **Services (Local Python):** Control Center, Agent Runtime, Communication Hub

## Prerequisites

Before starting development, ensure you have:
- Docker Desktop installed and running
- Python 3.11+ with venv activated
- Node.js 18+ (for frontend development)

## First-Time Setup

### 1. Install Dependencies

```powershell
# Backend
cd backend
pip install -e .

# Frontend
cd ../frontend
npm install
```

### 2. Start Infrastructure

```powershell
# Start PostgreSQL, Redis, Keycloak, OTEL components
.\parthenon.ps1 start -Services infra
```

**Wait for Keycloak to be ready** (usually 30-60 seconds). The script will check health automatically.

### 3. Initialize Local Environment

**⚠️ IMPORTANT:** Run this initialization script to set up the development environment:

```powershell
# Initialize Keycloak realm, admin user, and database
.\parthenon.ps1 init
```

This will:
- ✅ Create the `parthenon` realm in Keycloak (human users)
- ✅ Configure OIDC clients (`parthenon-api`, `parthenon-api-ui`) in human realm
- ✅ Create the `ai_agents` realm in Keycloak (agent identities)
- ✅ Configure OIDC client (`parthenon-api`) in agent realm
- ✅ Create default admin user: `admin@parthenon.local` / `admin`
- ✅ Seed system roles and permissions in the database
- ✅ Assign system_admin role to the admin user

**This is idempotent** — safe to run multiple times if something goes wrong.

### 4. Run Database Migrations

```powershell
cd backend
alembic upgrade head
```

## Quick Start

**After completing First-Time Setup above:**

### 1. Start Infrastructure (if not running)

```powershell
.\parthenon.ps1 start -Services infra
```

### 2. Start Services

```powershell
# Option A: Start all backend services
.\parthenon.ps1 start -Services backend

# Option B: Start individual services for debugging
.\start-service.ps1 -Service control-center
.\start-service.ps1 -Service agent-runtime
.\start-service.ps1 -Service communication-hub
```

### 3. Access the Application

- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs
- **Keycloak Admin:** http://localhost:8082 (admin/admin)

**Admin Login:**
- Email: `admin@parthenon.local`
- Password: `admin`

---

## Development Workflow

### Starting Services Individually

```powershell
docker compose -f docker-compose-infra.yml up -d
```

This starts all infrastructure components without the Python services.

### 2. Start Services Individually

Use the helper script for manual control and fast reload:

```powershell
# Control Center (port 8000)
.\start-service.ps1 -Service control-center

# Agent Runtime (port 8001)
.\start-service.ps1 -Service agent-runtime

# Communication Hub (port 8002)
.\start-service.ps1 -Service communication-hub
```

**Benefits:**
- ✅ Auto-reload on code changes (--reload flag)
- ✅ Separate terminal windows for each service
- ✅ Full console output visibility
- ✅ Easy debugging with breakpoints
- ✅ Environment variables loaded from .env file

### 3. Or Use Orchestration Script

For automated startup:

```powershell
# Start everything
.\parthenon.ps1 start

# Start just infrastructure
.\parthenon.ps1 start -Services infra

# Start backend (Control Center)
.\parthenon.ps1 start -Services backend

# Stop everything
.\parthenon.ps1 stop -Force

# Check status
.\parthenon.ps1 status
```

## Environment Configuration

All services load environment variables from `.env` file:

```env
# Database
DATABASE_URL=postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon

# Redis
REDIS_URL=redis://localhost:6379/0

# OIDC
OIDC_PROVIDER_URL=http://localhost:8082/realms/ai_agents

# Security
SECRET_KEY=<48-char-key>
CREDENTIAL_VAULT_KEY=<32-char-key>

# Service Bootstrap Keys (for mutual TLS)
AGENT_RUNTIME_BOOTSTRAP_KEY=<48-char-key>
COMM_HUB_BOOTSTRAP_KEY=<48-char-key>

# Control Center URLs
CONTROL_CENTER_URL=http://localhost:8000
```

## Service-Specific Configuration

The `start-service.ps1` helper automatically configures each service:

### Control Center
- Port: 8000
- Log: `backend/logs/control-center.log`
- Bootstrap keys: Sets AGENT_RUNTIME_BOOTSTRAP_KEY and COMM_HUB_BOOTSTRAP_KEY
- Entry: `uvicorn app.main:app --reload`

### Agent Runtime
- Port: 8001
- Log: `backend/logs/agent-runtime.log`
- Bootstrap key: Sets SERVICE_BOOTSTRAP_KEY (must match AGENT_RUNTIME_BOOTSTRAP_KEY)
- Entry: `uvicorn app.agent_runtime.main:app --reload`

### Communication Hub
- Port: 8002
- Log: `backend/logs/communication-hub.log`
- Bootstrap key: Sets SERVICE_BOOTSTRAP_KEY (must match COMM_HUB_BOOTSTRAP_KEY)
- Entry: `uvicorn app.communication_hub.main:app --reload`

## Fast Reload Development

**Why local execution?**
- Edit Python code → Uvicorn auto-reloads (1-2 seconds)
- No container rebuild required
- Direct console output for debugging
- Breakpoints work with debugger

**Example workflow:**
1. Start infrastructure: `docker compose -f docker-compose-infra.yml up -d`
2. Start Control Center: `.\start-service.ps1 -Service control-center`
3. Edit `backend/app/routers/agents.py`
4. See auto-reload in terminal: `INFO: Reloading...`
5. Test changes immediately

## Certificate Management

**Bootstrap Flow:**
1. Service starts with SERVICE_BOOTSTRAP_KEY from .env
2. Calls Control Center: `POST /api/v1/internal/bootstrap`
3. Receives 24-hour service certificate
4. Auto-renews at 80% lifetime (19.2 hours)
5. Retry every 5 minutes on failure

**Certificate Types:**
- `service:<name>`: 30-day validity (Control Center self-issues)
- `agent-instance:<type>:<id>`: 24-hour validity (issued by CA)

## Monitoring & Observability

**Infrastructure Services (Docker):**
- Jaeger UI: http://localhost:16686 (traces)
- Prometheus: http://localhost:9090 (metrics)
- Grafana: http://localhost:3000 (dashboards) — *if configured*
- Loki: http://localhost:3100 (logs)

**Service Logs (Local Files):**
- Control Center: `backend/logs/control-center.log`
- Agent Runtime: `backend/logs/agent-runtime.log`
- Communication Hub: `backend/logs/communication-hub.log`

**OTEL Configuration:**
- Exporters: `["file", "otlp"]`
- OTLP Endpoint: `http://localhost:4317`
- Service Names: `parthenon-control-center`, `parthenon-agent-runtime`, `parthenon-communication-hub`

## Troubleshooting

### Service won't start
1. Check .env file exists and has all required keys
2. Verify infrastructure is running: `docker ps`
3. Check port availability: `netstat -ano | findstr ":<port>"`
4. Review service logs in `backend/logs/`

### Certificate errors
1. Verify bootstrap keys match in .env:
   - AGENT_RUNTIME_BOOTSTRAP_KEY = SERVICE_BOOTSTRAP_KEY (Agent Runtime)
   - COMM_HUB_BOOTSTRAP_KEY = SERVICE_BOOTSTRAP_KEY (Communication Hub)
2. Check Control Center is running (required for bootstrap)
3. Review certificate renewal logs in control-center.log

### Database connection issues
1. Verify Postgres container: `docker ps | findstr postgres`
2. Test connection: `psql postgresql://parthenon:parthenon@localhost:5432/parthenon`
3. Check DATABASE_URL in .env matches connection details

### Redis connection issues
1. Verify Redis container: `docker ps | findstr redis`
2. Test connection: `redis-cli -h localhost -p 6379 ping`
3. Check REDIS_URL in .env

## Production Deployment

For production, use the full `docker-compose.yml` which includes all services in containers:

```powershell
docker compose up -d
```

**Differences from local dev:**
- Services run in containers (not local Python)
- No auto-reload (requires rebuild)
- Production-ready networking and security
- Environment passed via docker-compose.yml

## Files Reference

- `.env` — Environment variables for all services
- `docker-compose-infra.yml` — Infrastructure-only Docker Compose
- `docker-compose.yml` — Full production Docker Compose (includes services)
- `start-service.ps1` — Helper to start services locally with .env loading
- `parthenon.ps1` — Orchestration script for full stack management
- `SERVICE-MONITORING.md` — Comprehensive monitoring and observability guide
