---
description: Initialize the Parthenon local development environment in dev mode: infrastructure in Docker and application services started locally via parthenon script.
---

Initialize the Parthenon local development environment (dev-focused).

**Usage**: `/init-app`

## OS-Specific Command Notes

- Windows PowerShell: use `./parthenon.ps1 ...`
- macOS (zsh/bash): use shell-native commands for Python/venv/migrations.
- On macOS, prefer slash commands to start app services (`/start-app --infra`, `/start-app --backend`).
- `parthenon.ps1` is fully optimized for Windows service orchestration; use it on macOS only where explicitly noted.

This command performs a complete local development setup and startup:
- ✅ Creates Keycloak **human user realm** (`parthenon`)
- ✅ Configures OIDC clients in human realm (`parthenon-api`, `parthenon-api-ui`)
- ✅ Creates Keycloak **agent realm** (`ai_agents`)
- ✅ Configures OIDC client in agent realm (`parthenon-api`)
- ✅ Creates default admin user with consistent UUID
- ✅ Seeds database with `system_admin` role and wildcard policy
- ✅ Assigns system_admin role to admin user
- ✅ Auto-provisions required local env vars in both `.env` and `backend/.env` (bootstrap keys, cert paths, control-center URL)
- ✅ Uses Docker only for infrastructure
- ✅ Starts app services locally via `./parthenon.ps1 start -Services backend`
- ✅ Provides login instructions
- ✅ Prevents local OIDC redirect mismatch (`localhost` vs `127.0.0.1`) by seeding both URI variants

**Safe to run multiple times** — all operations are idempotent and will skip steps already completed.

**Default admin credentials**:
- Email: `admin@parthenon.local`
- Password: `admin`

---

## Step 0: Confirm Dev Setup Mode (Required)

Start by asking via VS Code Generative UI question cards (not freeform terminal prompts):

```text
Development mode uses:
1) Infrastructure in Docker Compose
2) Application services in local terminals via parthenon script

Proceed with this mode?
```

Implementation note:
- Use VS Code Generative UI input collection for user-required choices in this command.
- If user confirms dev setup mode, proceed immediately (do not ask for a second confirmation).

After confirmation, continue with Steps 1-6 below.

## Step 0.1: Start Infra (Docker Only)

Report progress in phases:

```text
Phase 1/3: Starting infra containers
Phase 2/3: Waiting for infra health checks
Phase 3/3: Running initialization bootstrap
```

Start infrastructure automatically:

```powershell
./parthenon.ps1 start -Services infra
```

macOS equivalent:

```bash
/start-app --infra
```

If you prefer slash commands, this is equivalent:

```powershell
/start-app --infra
```

If startup fails, provide immediate next actions:

```text
Infra startup failed.
Recommended checks:
1) docker compose ps
2) docker compose logs keycloak
3) docker compose logs postgres
4) Re-run /init-app
```

Then continue with Steps 1-6 below.

---

## Step 1: Validate Prerequisites

Before initialization, ensure the environment is ready.

### Infra Checks (Docker)

**Check A1: Keycloak Container Running**

```powershell
$keycloakRunning = docker ps --filter "name=parthenon-keycloak" --format "{{.Names}}"
```

**If Keycloak is NOT running:**
- Display error: "✗ Keycloak is not running. Start infrastructure with `/start-app --infra` or `./parthenon.ps1 start -Services infra`"
- **STOP HERE** — do not proceed with initialization

**Check A2: Database Container Running**

```powershell
$dbCheck = docker ps --filter "name=parthenon-postgres" --filter "status=running" --format "{{.Names}}"
```

**If database is NOT running:**
- Display error: "✗ PostgreSQL is not running. Start infrastructure with `/start-app --infra` or `./parthenon.ps1 start -Services infra`"
- **STOP HERE**

**Check 3: Python Virtual Environment**

```powershell
(Test-Path ".venv\Scripts\Activate.ps1") -or (Test-Path ".venv/bin/activate")
```

macOS equivalent:

```bash
[[ -f .venv/bin/activate || -f .venv/Scripts/Activate.ps1 ]]
```

**If venv doesn't exist:**
- Auto-fix by creating the venv, then continue:

```powershell
python -m venv .venv
```

macOS equivalent:

```bash
python -m venv .venv
```

**Check 4: Backend package installed in venv**

```powershell
pip show parthenon | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Backend package not installed" }
```

macOS equivalent:

```bash
pip show parthenon >/dev/null || echo "Backend package not installed"
```

If missing, auto-fix by installing the editable backend package:

```powershell
pip install -e backend/
```

macOS equivalent:

```bash
pip install -e backend/
```

Then continue automatically.

---

## Step 2: Wait for Keycloak to be Fully Ready

Keycloak takes time to start up. Verify it's ready to accept API calls.

### Keycloak Readiness Check (Docker Infra)

```powershell
Write-Host "Waiting for Keycloak to be ready..." -ForegroundColor Cyan

$maxWait = 90
$elapsed = 0
$ready = $false

do {
    Start-Sleep -Seconds 3
    $elapsed += 3
    
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8082/health/ready" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $ready = $true
            Write-Host "✓ Keycloak is ready" -ForegroundColor Green
            break
        }
    } catch {
        # Still warming up, continue waiting
    }
    
    Write-Host "." -NoNewline
} while ($elapsed -lt $maxWait)

if (-not $ready) {
    Write-Host ""
    Write-Host "✗ Keycloak did not become ready within ${maxWait}s" -ForegroundColor Red
    Write-Host "  Check logs with: docker compose logs keycloak" -ForegroundColor Yellow
    # STOP HERE
}
```

---

## Step 3: Run Initialization Script

Execute the initialization script that performs all setup steps.

This step now also ensures required local service env vars exist in both `.env` and `backend/.env`, including:
- `AGENT_RUNTIME_BOOTSTRAP_KEY`
- `COMM_HUB_BOOTSTRAP_KEY`
- `SERVICE_BOOTSTRAP_KEY`
- `CONTROL_CENTER_URL`
- `AGENT_CERT_PATH`, `AGENT_KEY_PATH`, `COMM_HUB_CERT_PATH`, `COMM_HUB_KEY_PATH`, `CA_CERT_PATH`

```powershell
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Parthenon Local Development Initialization" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment
if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .venv\Scripts\Activate.ps1
} elseif (Test-Path ".venv/bin/activate") {
    . .venv/bin/activate
} else {
    Write-Host "✗ Virtual environment activation script not found" -ForegroundColor Red
    exit 1
}

# Run initialization script
python scripts\init-local-dev.py

$exitCode = $LASTEXITCODE
```

macOS equivalent:

```bash
source .venv/bin/activate
python scripts/init-local-dev.py
exitCode=$?
```

---

## Step 4: Check Initialization Results and Start App Services

**If exit code is 0 (success):**

Run database migrations before starting app services:

```powershell
Push-Location backend
alembic upgrade head
$migrationExitCode = $LASTEXITCODE
Pop-Location

if ($migrationExitCode -ne 0) {
    Write-Host "✗ Database migration failed. Fix migration issues before starting app services." -ForegroundColor Red
    exit $migrationExitCode
}
```

Start backend services locally via the management script:

```powershell
./parthenon.ps1 start -Services backend
```

macOS equivalent:

```bash
/start-app --backend
```

If you prefer explicit service list, use:

```powershell
./parthenon.ps1 start -Services control-center,agent-runtime,communication-hub,frontend
```

macOS equivalent:

```bash
# Use local terminal commands or /start-app --backend
```

Then display:

```powershell
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✓ Initialization Complete!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Open the frontend and complete sign-in" -ForegroundColor White
Write-Host "  2. Optionally run system verification: /test-app" -ForegroundColor White
Write-Host ""
Write-Host "Admin credentials:" -ForegroundColor Cyan
Write-Host "  Email:    admin@parthenon.local" -ForegroundColor White
Write-Host "  Password: admin" -ForegroundColor White
Write-Host ""
Write-Host "Access the application at:" -ForegroundColor Cyan
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor White
Write-Host "  Backend:  http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Keycloak: http://localhost:8082 (admin/admin)" -ForegroundColor White
Write-Host ""
Write-Host "Login flow:" -ForegroundColor Cyan
Write-Host "  1. Open frontend URL" -ForegroundColor White
Write-Host "  2. Click Sign In" -ForegroundColor White
Write-Host "  3. Use admin@parthenon.local / admin" -ForegroundColor White
Write-Host "  4. After redirect, confirm access to admin UI" -ForegroundColor White
Write-Host ""
```

**If exit code is NOT 0 (failure):**

```powershell
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Red
Write-Host "  ✗ Initialization Failed!" -ForegroundColor Red
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Red
Write-Host ""
Write-Host "Common issues:" -ForegroundColor Yellow
Write-Host "  1. Keycloak not fully started — wait 30s and try again" -ForegroundColor White
Write-Host "  2. Database not accessible — check postgres container" -ForegroundColor White
Write-Host "  3. Network issues — verify docker networking" -ForegroundColor White
Write-Host ""
Write-Host "For diagnostics:" -ForegroundColor Yellow
Write-Host "  docker compose logs keycloak" -ForegroundColor White
Write-Host "  docker compose logs postgres" -ForegroundColor White
Write-Host "  python scripts\check-admin-permissions.py" -ForegroundColor White
Write-Host ""
```

---

## Step 5: Optional — Verify Initialization

Offer to run diagnostic checks to verify everything is set up correctly.

```powershell
$verify = Read-Host "Run verification checks? (y/n)"

if ($verify -eq 'y') {
    Write-Host ""
    Write-Host "Running verification..." -ForegroundColor Cyan
    
    # Activate venv if not already active
    if (Test-Path ".venv\Scripts\Activate.ps1") {
        & .venv\Scripts\Activate.ps1
    } elseif (Test-Path ".venv/bin/activate") {
        . .venv/bin/activate
    }
    
    # Run diagnostic script
    python scripts\check-admin-permissions.py
    
    Write-Host ""
    Write-Host "Verification complete. Check output above for any issues." -ForegroundColor Cyan
}
```

macOS equivalent:

```bash
read -r -p "Run verification checks? (y/n) " verify
if [[ "$verify" == "y" ]]; then
    source .venv/bin/activate
    python scripts/check-admin-permissions.py
fi
```

---

## Step 6: Post-Setup Checklist

Run this quick confirmation checklist:

1. Confirm OIDC discovery endpoint returns 200.
2. Confirm realms exist (`parthenon`, `ai_agents`).
3. Confirm OIDC clients exist:
    - `parthenon-api` (human realm)
    - `parthenon-api-ui` (human realm)
    - `parthenon-api` (agent realm)
4. Confirm database has `system_admin` role and wildcard policy seeded.
5. Confirm local services are healthy on ports 8000, 8001, 8002, and 5173.
6. Confirm admin user can authenticate and reach frontend.

Additional OIDC callback validation (required):
7. Confirm Keycloak UI client `parthenon-api-ui` has redirect URIs for both hostname variants:
    - `http://localhost:5173/*`
    - `http://127.0.0.1:5173/*`
8. Confirm Keycloak UI client web origins include both:
    - `http://localhost:5173`
    - `http://127.0.0.1:5173`
9. Confirm `backend/.env` exists and contains non-placeholder bootstrap/env values:
    - `AGENT_RUNTIME_BOOTSTRAP_KEY`
    - `COMM_HUB_BOOTSTRAP_KEY`
    - `SERVICE_BOOTSTRAP_KEY`
    - `CONTROL_CENTER_URL`

If any item fails, surface the exact failed component and recommended fix.

---

## Alternative: Use Parthenon Management Script

If the user prefers, they can also use the built-in management script:

```powershell
.\parthenon.ps1 init
```

macOS equivalent:

```bash
# Recommended flow on macOS:
/start-app --infra
source .venv/bin/activate
python scripts/init-local-dev.py
cd backend && alembic upgrade head
/start-app --backend
```

This is equivalent but doesn't provide the interactive verification step.

---

## Troubleshooting

**Issue: "Keycloak is not running"**
- Solution: Start infrastructure first: `./parthenon.ps1 start -Services infra`

**Issue: "Admin authentication failed"**
- Possible cause: Default Keycloak admin password changed
- Solution: Check docker-compose-infra.yml for Keycloak admin credentials
- Default is: `admin` / `admin`

**Issue: "Duplicate admin users found"**
- This is a warning, not an error
- Indicates previous initialization attempts with different Keycloak UUIDs
- Old duplicate entries won't affect functionality but can be cleaned up manually

**Issue: "User not found in platform. Please re-authenticate"**
- Cause: Admin user hasn't logged in yet to create platform_user entry
- Solution: The init script creates the entry automatically, but if you see this:
  1. Log in to the frontend once: http://localhost:5173
  2. Re-run initialization: `/init-app`

**Issue: "Connection refused" errors during initialization**
- Keycloak is still starting up — wait 30-60 seconds and retry
- Check Keycloak logs: `docker compose logs keycloak`

**Issue: "Invalid parameter: redirect_uri" on Keycloak login page**
- Cause: frontend opened with `127.0.0.1` but Keycloak client allows only `localhost` (or vice versa)
- Solution:
    1. Re-run `/init-app` to reseed OIDC clients with both hostname variants
    2. Or use a consistent frontend URL (`http://localhost:5173`)

---

## Notes

- **This command is for LOCAL DEVELOPMENT ONLY** — do not use in production
- **Idempotent**: Safe to run multiple times if setup fails or Keycloak is reset
- **Dev-first workflow**: Docker for infra, local terminals for app services
- **Persistent Data**: Uses Keycloak's assigned UUIDs to maintain consistency
- **Duplicate Detection**: Script will warn about duplicate admin users with different UUIDs
- **Manual Cleanup**: If you have duplicate admin users, use the diagnostic scripts in `scripts/` to identify and clean them up

---

## Related Commands

- `/start-app` — Start the application after initialization
- `/stop-app` — Stop all services
- `/test-app` — Run tests after initialization
