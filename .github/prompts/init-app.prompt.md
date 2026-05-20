---
description: Initialize the Parthenon local development environment. Sets up Keycloak realm, OIDC clients, admin user, and database roles/permissions. Idempotent - safe to run multiple times. This is a first-time setup command for new developers or when resetting the local environment.
---

Initialize the Parthenon local development environment.

**Usage**: `/init-app`

This command performs a complete local development environment initialization:
- ✅ Creates Keycloak **human user realm** (`parthenon`)
- ✅ Configures OIDC clients in human realm (`parthenon-api`, `parthenon-api-ui`)
- ✅ Creates Keycloak **agent realm** (`ai_agents`)
- ✅ Configures OIDC client in agent realm (`parthenon-api`)
- ✅ Creates default admin user with consistent UUID
- ✅ Seeds database with `system_admin` role and wildcard policy
- ✅ Assigns system_admin role to admin user

**Safe to run multiple times** — all operations are idempotent and will skip steps already completed.

**Default admin credentials**:
- Email: `admin@parthenon.local`
- Password: `admin`

---

## Step 1: Validate Prerequisites

Before initialization, ensure the environment is ready.

**Check 1: Keycloak Container Running**

```powershell
$keycloakRunning = docker ps --filter "name=parthenon-keycloak" --format "{{.Names}}"
```

**If Keycloak is NOT running:**
- Display error: "✗ Keycloak is not running. Start infrastructure first with: `/start-app --infra` or `./parthenon.ps1 start -Services infra`"
- **STOP HERE** — do not proceed with initialization

**Check 2: Database Accessible**

```powershell
$dbCheck = docker ps --filter "name=parthenon-postgres" --filter "status=running" --format "{{.Names}}"
```

**If database is NOT running:**
- Display error: "✗ PostgreSQL is not running. Start infrastructure first with: `/start-app --infra` or `./parthenon.ps1 start -Services infra`"
- **STOP HERE**

**Check 3: Python Virtual Environment**

```powershell
Test-Path ".venv\Scripts\Activate.ps1"
```

**If venv doesn't exist:**
- Display warning: "⚠ Virtual environment not found. Run: `python -m venv .venv` and `pip install -e backend/` first"
- **STOP HERE**

---

## Step 2: Wait for Keycloak to be Fully Ready

Keycloak takes time to start up. Verify it's ready to accept API calls.

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

```powershell
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Parthenon Local Development Initialization" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment
& .venv\Scripts\Activate.ps1

# Run initialization script
python scripts\init-local-dev.py

$exitCode = $LASTEXITCODE
```

---

## Step 4: Check Initialization Results

**If exit code is 0 (success):**

```powershell
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✓ Initialization Complete!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Run database migrations: cd backend; alembic upgrade head" -ForegroundColor White
Write-Host "  2. Start the application: /start-app" -ForegroundColor White
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
    & .venv\Scripts\Activate.ps1
    
    # Run diagnostic script
    python scripts\check-admin-permissions.py
    
    Write-Host ""
    Write-Host "Verification complete. Check output above for any issues." -ForegroundColor Cyan
}
```

---

## Alternative: Use Parthenon Management Script

If the user prefers, they can also use the built-in management script:

```powershell
.\parthenon.ps1 init
```

This is equivalent but doesn't provide the interactive verification step.

---

## Troubleshooting

**Issue: "Keycloak is not running"**
- Solution: Start infrastructure first: `/start-app --infra`

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

---

## Notes

- **This command is for LOCAL DEVELOPMENT ONLY** — do not use in production
- **Idempotent**: Safe to run multiple times if setup fails or Keycloak is reset
- **Persistent Data**: Uses Keycloak's assigned UUIDs to maintain consistency
- **Duplicate Detection**: Script will warn about duplicate admin users with different UUIDs
- **Manual Cleanup**: If you have duplicate admin users, use the diagnostic scripts in `scripts/` to identify and clean them up

---

## Related Commands

- `/start-app` — Start the application after initialization
- `/stop-app` — Stop all services
- `/test-app` — Run tests after initialization
