# Three-Service Architecture - Monitoring Guide

## ✅ Service Status (RUNNING)

All three services are successfully running:

| Service | Port | Container | Health |
|---------|------|-----------|--------|
| **Control Center** | 8000 | parthenon-control-center | ✓ Healthy |
| **Agent Runtime** | 8001 | parthenon-agent-runtime | ✓ Healthy |
| **Communication Hub** | 8002 | parthenon-communication-hub | ✓ Healthy |

## 📁 Log Files (Separate per Service)

Each service writes to its own log file in `backend/logs/`:

```
backend/logs/control-center.log      - Control Center logs
backend/logs/agent-runtime.log       - Agent Runtime logs
backend/logs/communication-hub.log   - Communication Hub logs
```

## 🔐 Bootstrap Keys (Configured)

Secure 48-character bootstrap keys are set in `.env`:

- **AGENT_RUNTIME_BOOTSTRAP_KEY**: ✓ Configured (used by Agent Runtime to bootstrap)
- **COMM_HUB_BOOTSTRAP_KEY**: ✓ Configured (used by Communication Hub to bootstrap)

These keys are validated by the Control Center's `/internal/bootstrap` endpoint.

## 📊 How to Monitor Logs

### Real-time log monitoring (tail -f equivalent):

```powershell
# Control Center
Get-Content backend\logs\control-center.log -Wait -Tail 20

# Agent Runtime
Get-Content backend\logs\agent-runtime.log -Wait -Tail 20

# Communication Hub
Get-Content backend\logs\communication-hub.log -Wait -Tail 20
```

### Check last N lines:

```powershell
Get-Content backend\logs\control-center.log -Tail 50
Get-Content backend\logs\agent-runtime.log -Tail 50
Get-Content backend\logs\communication-hub.log -Tail 50
```

### Search for specific patterns:

```powershell
# Search for errors in Control Center
Get-Content backend\logs\control-center.log | Select-String "ERROR"

# Search for certificate-related logs in Agent Runtime
Get-Content backend\logs\agent-runtime.log | Select-String "certificate|bootstrap"

# Search for WebSocket connections in Communication Hub
Get-Content backend\logs\communication-hub.log | Select-String "WebSocket|ws"
```

## 🔍 Health Check Endpoints

Test service health:

```powershell
# Control Center
Invoke-WebRequest http://localhost:8000/health | Select-Object Content

# Agent Runtime
Invoke-WebRequest http://localhost:8001/health | Select-Object Content

# Communication Hub
Invoke-WebRequest http://localhost:8002/health | Select-Object Content
```

Expected response for each:
```json
{
  "status": "ok",
  "service": "<service-name>",
  "version": "0.1.0",
  "cert_expires_at": "<timestamp or null>"
}
```

## 🐳 Docker Management

### Check service status:
```powershell
docker ps --filter "name=parthenon" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

### View container logs (if needed):
```powershell
docker logs parthenon-control-center -f
docker logs parthenon-agent-runtime -f
docker logs parthenon-communication-hub -f
```

### Restart a specific service:
```powershell
docker compose restart control-center
docker compose restart agent-runtime
docker compose restart communication-hub
```

### Stop all services:
```powershell
docker compose down
```

### Start all services:
```powershell
docker compose up -d
```

## 🔧 Troubleshooting

### If a service won't start:

1. Check the service-specific log file
2. Check Docker container logs: `docker logs parthenon-<service-name>`
3. Verify bootstrap keys match in `.env`
4. Ensure Control Center is healthy before starting AR/CH

### If logs aren't being written:

1. Verify `backend/logs` directory exists
2. Check telemetry configuration in docker-compose.yml
3. Ensure volume mount is correct: `./backend:/app`

### If certificate bootstrap fails:

1. Check Control Center logs for bootstrap endpoint calls
2. Verify `AGENT_RUNTIME_BOOTSTRAP_KEY` and `COMM_HUB_BOOTSTRAP_KEY` are set in `.env`
3. Verify AR/CH are using correct `CONTROL_CENTER_URL=http://control-center:8000`

## 📝 Configuration Files

- **Environment**: `.env` (root directory)
- **Docker Compose**: `docker-compose.yml`
- **Service Entry Points**:
  - Control Center: `backend/app/main.py`
  - Agent Runtime: `backend/app/agent_runtime/main.py`
  - Communication Hub: `backend/app/communication_hub/main.py`

## ✨ Key Features Verified

✅ Three independent FastAPI services running  
✅ Each service has dedicated log file  
✅ Certificate-based mTLS authentication configured  
✅ Per-service bootstrap keys validated  
✅ Health endpoints responding on all services  
✅ Database access isolated to Control Center only  
✅ All services communicate via HTTP with mTLS  

---

**Last Updated**: Service decomposition implementation complete - All phases 1-7 validated.
