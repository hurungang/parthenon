# Parthenon Management Script Guide

The `parthenon.ps1` script provides a unified interface for managing all Parthenon services (infrastructure, backend, and frontend).

## Quick Start

```powershell
# Check status of all services
.\parthenon.ps1 status

# Start all services (in order: infra → backend → frontend)
.\parthenon.ps1 start

# Stop all services (in reverse order)
.\parthenon.ps1 stop

# Restart all services
.\parthenon.ps1 restart
```

## Command Reference

### Actions

| Action | Description |
|--------|-------------|
| `start` | Start specified services (checks if already running) |
| `stop` | Stop specified services |
| `restart` | Stop then start specified services |
| `status` | Show current status of all services |

### Service Selection

Use the `-Services` parameter to target specific components:

```powershell
# Start only infrastructure (Keycloak, PostgreSQL, Redis)
.\parthenon.ps1 start -Services infra

# Start backend API only
.\parthenon.ps1 start -Services backend

# Start frontend dev server only
.\parthenon.ps1 start -Services frontend

# Start all services (default)
.\parthenon.ps1 start -Services all
```

### Force Mode

Use `-Force` to skip confirmation prompts when services are already running:

```powershell
# Restart backend without confirmation
.\parthenon.ps1 restart -Services backend -Force

# Start all services, restarting any that are already running
.\parthenon.ps1 start -Force
```

## Service Details

### Infrastructure Services

**Keycloak** (Port 8082)
- Identity and access management
- Runs in Docker container
- Health check: `http://localhost:8082/health/ready`

**PostgreSQL** (Port 5432)
- Database server
- Runs in Docker container

**Redis** (Port 6379)
- Cache and session store
- Runs in Docker container

### Backend Service

**FastAPI Application** (Port 8000)
- Python backend API
- Runs via uvicorn
- Health check: `http://localhost:8000/health`
- Working directory: `backend/`

### Frontend Service

**Vite Dev Server** (Port 5173)
- React frontend
- Hot module replacement enabled
- Health check: `http://localhost:5173/`
- Working directory: `frontend/`

## Examples

### Development Workflow

```powershell
# Morning: Start everything
.\parthenon.ps1 start

# Restart backend after code changes (keeps frontend running)
.\parthenon.ps1 restart -Services backend

# Check what's running
.\parthenon.ps1 status

# Evening: Stop everything
.\parthenon.ps1 stop
```

### Troubleshooting

```powershell
# If a service is stuck, force restart it
.\parthenon.ps1 restart -Services backend -Force

# Start services one by one to isolate issues
.\parthenon.ps1 start -Services infra
.\parthenon.ps1 start -Services backend
.\parthenon.ps1 start -Services frontend
```

### Working on Specific Components

```powershell
# Frontend development only (assumes backend/infra already running)
.\parthenon.ps1 start -Services frontend

# Backend API development (needs infrastructure)
.\parthenon.ps1 start -Services infra,backend

# Full stack development
.\parthenon.ps1 start  # or: -Services all
```

## Port Reference

| Service | Port | URL |
|---------|------|-----|
| Keycloak | 8082 | http://localhost:8082 |
| PostgreSQL | 5432 | localhost:5432 |
| Redis | 6379 | localhost:6379 |
| Backend API | 8000 | http://localhost:8000 |
| Backend Docs | 8000 | http://localhost:8000/docs |
| Frontend Dev | 5173 | http://localhost:5173 |

## Credentials

### Keycloak Admin Console
- URL: http://localhost:8082/admin
- Username: `admin`
- Password: `admin123`

### Application Users
- Admin user: `admin` / `admin`
- Test user: `testuser` / `testuser`

## Health Checks

The script automatically performs health checks after starting each service:

- **Infra**: Retries Keycloak health endpoint for up to 60 seconds
- **Backend**: Retries `/health` endpoint for up to 30 seconds
- **Frontend**: Retries root URL for up to 20 seconds

If health checks fail, the script will display an error and continue (or stop if `-Force` not used).

## Notes

- Services start in dependency order: infrastructure → backend → frontend
- Services stop in reverse order: frontend → backend → infrastructure
- The script checks for already-running services before starting
- Use `-Force` to automatically restart services that are already running
- PowerShell windows stay open for backend/frontend to show logs
- Docker containers run detached in the background

## Troubleshooting

### "Service already running" prompts

If you see confirmation prompts when you expect services to start fresh:

```powershell
# Use -Force to skip prompts and restart automatically
.\parthenon.ps1 start -Force
```

### Port conflicts

If ports are in use by other applications:

```powershell
# Check what's using a port
netstat -ano | findstr :8000

# Kill process by PID (from netstat output)
Stop-Process -Id <PID> -Force
```

### Docker containers won't start

```powershell
# Check Docker status
docker ps -a

# Remove stuck containers
docker compose down
.\parthenon.ps1 start -Services infra
```

### Backend/Frontend won't start

Check that Python/Node dependencies are installed:

```powershell
# Backend dependencies
cd backend
pip install -e .

# Frontend dependencies
cd frontend
npm install
```
