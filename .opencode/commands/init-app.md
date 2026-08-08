---
description: Initialize the Parthenon local development environment. Supports full docker-compose setup or selective external-service configuration. Provisions Keycloak realms, OIDC clients, admin user, database roles/permissions, and certificate authority. Uses the consolidated setup CLI (setup/). Idempotent — safe to run multiple times.
---

Initialize the Parthenon local development environment.

**Usage**: `/init-app [--external-postgres] [--external-redis] [--external-oidc] [--external-all]`

- No flags → full docker-compose setup (infrastructure in Docker, services run locally via parthenon.ps1)
- `--external-postgres` → use an external PostgreSQL instance (configure via `POSTGRES_*` env vars)
- `--external-redis` → use an external Redis instance (configure via `REDIS_*` env vars)
- `--external-oidc` → use an external OIDC provider like Azure EntraID (configure via `OIDC_*` env vars)
- `--external-all` → all infrastructure from external providers

This command performs environment initialization using the consolidated `setup/` CLI:
- Creates Keycloak **user realm** (`parthenon`) and **agent realm** (`ai_agents`) — skipped if `--external-oidc`
- Configures OIDC clients (`parthenon-api`, `parthenon-api-ui`, agent client, `mcp-demo-app`)
- Creates default admin user
- Creates test agent identities (`test_agent`, `test_agent_2`) with MCP role support for mcp-demo-app
- Registers `mcp_role` claim mappers and user profile attributes
- Seeds database with `system_admin` role, wildcard policy, system tools
- Bootstraps certificate authority for inter-service mTLS
- Initializes the `mcp-demo-app` Keycloak client in the agent realm

**Safe to run multiple times** — all operations are idempotent and skip already-completed steps.

**Default admin credentials**:
- Email: `admin@parthenon.local`
- Password: `admin`

---

## Step 1: Ask the User What Kind of Setup

If the user has **not specified flags** (no `--external-*`), ask them before proceeding:

```
## 🔧 Environment Setup

What kind of local development environment do you need?

1. **Full Docker Compose** (recommended for new developers)
   → External infrastructure (PostgreSQL, Redis, Keycloak) runs in Docker Compose
   → Parthenon services run locally via `parthenon.ps1`
   → One command bootstraps everything
   → No external dependencies

2. **External PostgreSQL** — I'll provide my own Postgres
3. **External Redis** — I'll provide my own Redis
4. **External OIDC** — I'll use Azure EntraID or another OIDC provider
5. **Hybrid** — Let me pick which services are external
6. **All External** — Everything from external providers (production-like)

Type the number(s) or describe your setup.
```

Parse the user's answer and set the appropriate flags. If they choose hybrid, ask which specific services they want external.

---

## Step 2: Validate Prerequisites

**If using Docker for any component** (no external flags for that component):

```powershell
# Check Docker
try { docker info | Out-Null; $dockerReady = $true } catch { $dockerReady = $false }

if (-not $dockerReady) {
    Write-Host "✗ Docker engine is not ready. Start Docker Desktop and retry."
    return
}
```

**If using --external-postgres**, verify the env vars are set:
```powershell
$pgHost = $env:POSTGRES_HOST
$pgPort = $env:POSTGRES_PORT
$pgUser = $env:POSTGRES_USER
$pgPassword = $env:POSTGRES_PASSWORD
$pgDb = $env:POSTGRES_DB

if (-not $pgHost -and -not $env:DATABASE_URL) {
    Write-Host "✗ --external-postgres specified but no connection configured."
    Write-Host "  Set POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB"
    Write-Host "  Or set DATABASE_URL directly."
    Write-Host ""
    # Ask user for values
}
```

**If using --external-redis**, verify:
```powershell
if (-not $env:REDIS_HOST -and -not $env:REDIS_URL) {
    Write-Host "✗ --external-redis specified but no connection configured."
    Write-Host "  Set REDIS_HOST, REDIS_PORT or REDIS_URL directly."
}
```

**If using --external-oidc**, verify:
```powershell
if (-not $env:OIDC_PROVIDER_URL) {
    Write-Host "✗ --external-oidc specified but OIDC_PROVIDER_URL not set."
}
```

**Python virtual environment**:
```powershell
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "⚠ Virtual environment not found. Creating..."
    python -m venv .venv
    & .venv\Scripts\Activate.ps1
    pip install -e backend/
}
```

---

## Step 3: Start Required Infrastructure

**If using Docker for any component** (not `--external-all`):

```powershell
Write-Host "Starting Docker infrastructure..." -ForegroundColor Cyan
.\parthenon.ps1 start -Services infra

# Wait for all infra services to be healthy
Write-Host "Waiting for infrastructure to be ready..." -ForegroundColor Cyan

$maxWait = 120
$elapsed = 0
$keycloakUp = $false
$postgresUp = $false
$redisUp = $false

do {
    Start-Sleep -Seconds 5
    $elapsed += 5

    # Keycloak
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8082/health/ready" -UseBasicParsing -TimeoutSec 3
        $keycloakUp = ($r.StatusCode -eq 200)
    } catch {}

    # PostgreSQL
    try {
        docker exec parthenon-postgres-1 pg_isready -U parthenon 2>&1 | Out-Null
        $postgresUp = $?
    } catch {}

    # Redis
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:6379" -UseBasicParsing -TimeoutSec 2
        $redisUp = $true
    } catch {}

} while ($elapsed -lt $maxWait -and (-not $keycloakUp -or -not $postgresUp -or -not $redisUp))

if ($keycloakUp) { Write-Host "  ✓ Keycloak ready" -ForegroundColor Green } else { Write-Host "  ✗ Keycloak not ready" -ForegroundColor Red; return }
if ($postgresUp) { Write-Host "  ✓ PostgreSQL ready" -ForegroundColor Green }
if ($redisUp) { Write-Host "  ✓ Redis ready" -ForegroundColor Green }
```

---

## Step 4: Write Environment Configuration

Based on the user's choices, write a `.env` file with the appropriate configuration:

**If `--external-postgres`**: Ask for and write `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.

**If `--external-redis`**: Ask for and write `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`.

**If `--external-oidc`**: Ask for and write `OIDC_PROVIDER_URL`, client ID, client secret.

For locally provisioned components, ensure the corresponding env vars are set to local defaults.

**If no external flags**, use the default `.env` template with local Docker values:
```powershell
# Use default .env or copy .env.example if .env doesn't exist
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "Created .env from template" -ForegroundColor Green
}
```

---

## Step 5: Run Setup Command

Activate the virtual environment and run the consolidated setup tool:

```powershell
# Activate venv
& .venv\Scripts\Activate.ps1

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Parthenon Environment Initialization" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# For full docker setup:
if ($fullDockerSetup) {
    python -m setup.main dev
}
# For setups with external OIDC (skip identity provisioning):
elseif ($externalOidc) {
    python -m setup.main database
    python -m setup.main certificates
}
# For selective external — run only needed sub-commands:
else {
    if (-not $externalPostgres) {
        # DB will be seeded after infra is confirmed
    }
    python -m setup.main dev
}

$exitCode = $LASTEXITCODE
```

The `setup.main dev` command runs:
1. `setup identity` — Keycloak realms, OIDC clients, admin user, test agents, mcp-demo-app client
2. `setup database` — Roles, permissions, skills, system tools
3. `setup certificates` — Certificate authority

Each sub-command is individually idempotent.

---

## Step 6: Run Database Migrations

```powershell
Write-Host "Applying database migrations..." -ForegroundColor Cyan
cd backend
python -m alembic upgrade head
cd ..
```

---

## Step 7: Check Results

**If all steps succeeded:**

```powershell
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✓ Environment Initialized!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "Setup summary:" -ForegroundColor Cyan
Write-Host "  PostgreSQL:   $(if ($externalPostgres) {'External'} else {'Docker (localhost:5432)'})"
Write-Host "  Redis:        $(if ($externalRedis) {'External'} else {'Docker (localhost:6379)'})"
Write-Host "  OIDC Provider: $(if ($externalOidc) {'External'} else {'Docker Keycloak (localhost:8082)'})"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  /start-app" -ForegroundColor White
Write-Host ""
Write-Host "Admin credentials:" -ForegroundColor Cyan
Write-Host "  Email:    admin@parthenon.local" -ForegroundColor White
Write-Host "  Password: admin" -ForegroundColor White
Write-Host ""
Write-Host "Access the application at:" -ForegroundColor Cyan
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor White
Write-Host "  Backend:  http://localhost:8000/docs" -ForegroundColor White
if (-not $externalOidc) {
    Write-Host "  Keycloak: http://localhost:8082 (admin/admin)" -ForegroundColor White
}
Write-Host ""
```

**If any step failed:**

```powershell
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Red
Write-Host "  ✗ Initialization Failed!" -ForegroundColor Red
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Red
Write-Host ""
Write-Host "Common issues:" -ForegroundColor Yellow
Write-Host "  1. Keycloak not fully started — Docker may still be initializing, retry in 30s"
Write-Host "  2. Database not accessible — check PostgreSQL is running and credentials are correct"
Write-Host "  3. Network issues — verify Docker networking or external service connectivity"
Write-Host "  4. Check setup logs for specific sub-command failures"
Write-Host ""
Write-Host "For diagnostics:" -ForegroundColor Yellow
if (-not $externalOidc) {
    Write-Host "  docker compose logs keycloak" -ForegroundColor White
}
Write-Host "  docker compose logs postgres" -ForegroundColor White
Write-Host "  python -m setup.main verify" -ForegroundColor White
Write-Host "  python -m setup.main identity --output json" -ForegroundColor White
Write-Host ""
```

---

## Step 8: Offer to Verify

```powershell
$verify = Read-Host "Run verification checks? (y/n)"

if ($verify -eq 'y') {
    Write-Host ""
    Write-Host "Running verification..." -ForegroundColor Cyan
    & .venv\Scripts\Activate.ps1
    python -m setup.main verify
    Write-Host ""
}
```

---

## Step 9: Offer to Start the Application

```powershell
$start = Read-Host "Start the application now? (y/n)"

if ($start -eq 'y') {
    Write-Host "Starting application..." -ForegroundColor Cyan
    if ($fullDockerSetup) {
        .\parthenon.ps1 start -Services backend
    } else {
        .\parthenon.ps1 start -Services backend
    }
}
```

---

## Environment Variable Reference

For external service configuration, set these environment variables (in `.env` or directly):

### PostgreSQL
```env
# Option A: Full URL
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname

# Option B: Per-component (composed at runtime)
POSTGRES_HOST=your-postgres-host
POSTGRES_PORT=5432
POSTGRES_USER=parthenon
POSTGRES_PASSWORD=your-password
POSTGRES_DB=parthenon
```

### Redis
```env
# Option A: Full URL
REDIS_URL=redis://host:6379/0

# Option B: Per-component (composed at runtime)
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_PASSWORD=your-password
REDIS_DB=0
```

### OIDC Provider
```env
OIDC_PROVIDER_URL=https://your-oidc-provider/realms/your-realm
```

### Keycloak Admin (setup tool only — NOT needed at runtime)
```env
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD=admin
```

---

## Troubleshooting

**Issue: "Keycloak is not running"**
- Solution: Docker may need more time. `docker compose logs keycloak` to check.

**Issue: "Admin authentication failed"**
- Default Keycloak admin credentials: `admin` / `admin`
- Check `docker-compose-infra.yml` if password was changed.

**Issue: "Realm already exists" errors**
- This is normal — setup is idempotent. Look for "skipped" messages.

**Issue: "Duplicate admin users"**
- Old initialization attempts may leave duplicate records.
- Run `python -m setup.main verify` to check state.

**Issue: "Cannot connect to external service"**
- Verify the service is reachable from your machine.
- Check firewall rules and network connectivity.
- Try: `Test-NetConnection -ComputerName <host> -Port <port>`

---

## Related Commands

- `/start-app` — Start the application after initialization
- `/stop-app` — Stop all services
- `/test-app` — Run tests after initialization

## Notes

- The old `scripts/init-local-dev.py` is **deprecated** — use `python -m setup.main dev` instead
- The setup tool supports `--output json` for machine-readable output
- For production deployment, all infrastructure comes from external providers — configure via env vars only
- Configuration priority: environment variables → YAML files → built-in defaults
- The Control Center no longer auto-provisions Keycloak realms at startup
