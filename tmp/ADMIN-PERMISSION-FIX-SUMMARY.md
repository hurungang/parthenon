# Admin Permission Fix & Local Dev Initialization

## Problem Summary

The default admin user lost all permissions except tags and groups after a restructuring. Investigation revealed:

1. **Duplicate Admin Users**: Two `admin@parthenon.local` users existed in the database with different `sub` (Keycloak UUID) claims:
   - Original admin (April 26): Had `system_admin` role ✓
   - New duplicate (May 16 - TODAY): No roles assigned ✗

2. **Root Cause**: When logging in, Keycloak issued a NEW UUID (`sub` claim) for the admin user, creating a second platform_user record without any roles/permissions.

3. **Why This Happened**: 
   - The system had no proper initialization script
   - Runtime bootstrap relied on `BOOTSTRAP_ADMIN_EMAIL` env var (not set)
   - Keycloak realm might have been reset/recreated, issuing new UUIDs
   - No safeguard against duplicate users with different subs

## Immediate Fix Applied

✓ Assigned `system_admin` role to the duplicate admin user
✓ Both admin accounts now have full permissions

**Script used**: `scripts/fix-admin-permissions.py`

## Long-Term Solution Implemented

### 1. Local Development Initialization Script

**File**: `scripts/init-local-dev.py`

Comprehensive, idempotent initialization script that:
- ✅ Authenticates with Keycloak admin API
- ✅ Creates `parthenon` realm if not exists
- ✅ Creates OIDC clients (`parthenon-api`, `parthenon-api-ui`)
- ✅ Creates admin user in Keycloak with consistent UUID
- ✅ Seeds database with `system_admin` role and wildcard policy
- ✅ Creates platform_user entry with correct `sub` from Keycloak
- ✅ Assigns `system_admin` role to admin user
- ✅ Detects and warns about duplicate admin users
- ✅ **Safe to run multiple times** - all operations are idempotent

**Default admin credentials**:
- Email: `admin@parthenon.local`
- Password: `admin`

### 2. Slash Command Added

**Command**: `.\parthenon.ps1 init`

Added new `init` action to the parthenon.ps1 management script:
- Validates prerequisites (Keycloak running, database accessible)
- Runs the initialization script
- Provides clear success/failure feedback

**Usage**:
```powershell
# Start infrastructure first
.\parthenon.ps1 start -Services infra

# Initialize environment
.\parthenon.ps1 init

# Start services
.\parthenon.ps1 start -Services backend
```

### 3. Documentation Updated

**Files Updated**:
- `README.md`: Added First-Time Setup section with init command
- `LOCAL-DEV-SETUP.md`: Comprehensive setup guide with prerequisites and initialization steps
- `backend/app/services/permissions/bootstrap_service.py`: Added note about init script being the recommended approach

### 4. Diagnostic Scripts Created

**Files**: 
- `scripts/check-admin-permissions.py`: Diagnoses admin permission issues
- `scripts/check-duplicate-admins.py`: Lists duplicate admin users
- `scripts/fix-admin-permissions.py`: Emergency fix for missing permissions

## What Was NOT Changed

✓ **Runtime Bootstrap Service**: Kept as-is (fallback mechanism)
✓ **Agent Realm Initialization**: Still runs at startup (operational infrastructure)
✓ **Certificate Authority Init**: Still runs at startup (security infrastructure)
✓ **MCP Servers Seeding**: Still runs at startup (operational data)

The init script is **only for local development setup**, not production deployment.

## Testing Checklist

- [ ] Start infrastructure: `.\parthenon.ps1 start -Services infra`
- [ ] Run init script: `.\parthenon.ps1 init`
- [ ] Verify output shows all steps succeeded
- [ ] Run migrations: `cd backend; alembic upgrade head`
- [ ] Start backend: `.\parthenon.ps1 start -Services backend`
- [ ] Access frontend: http://localhost:5173
- [ ] Login with: `admin@parthenon.local` / `admin`
- [ ] Verify admin has access to all features (not just tags/groups)
- [ ] Run init again: `.\parthenon.ps1 init` (should skip existing items)

## Prevention of Future Issues

1. **Consistent UUIDs**: Init script uses Keycloak's UUID as the source of truth
2. **Duplicate Detection**: Script warns about duplicate admin users with same email
3. **Idempotent Operations**: Safe to re-run if Keycloak is reset
4. **Clear Documentation**: New developers have a clear setup path
5. **No Runtime Guessing**: Services don't try to "figure out" the admin user at startup

## Migration Notes

**For existing developers**:

1. If you already have a working environment, you DON'T need to run init
2. If you've reset Keycloak or lost permissions:
   - Stop services
   - Run `.\parthenon.ps1 init`
   - Restart services

**For new developers**:
- Just follow README.md First-Time Setup section

## Files Changed

- ✅ `scripts/init-local-dev.py` (NEW)
- ✅ `parthenon.ps1` (added `init` command)
- ✅ `README.md` (added First-Time Setup)
- ✅ `LOCAL-DEV-SETUP.md` (comprehensive update)
- ✅ `backend/app/services/permissions/bootstrap_service.py` (doc update)

## Files Created for Diagnostics

- `scripts/check-admin-permissions.py`
- `scripts/check-duplicate-admins.py`
- `scripts/fix-admin-permissions.py`

---

## Next Steps

1. **Test the init script** in your environment
2. **Clean up duplicate admin users** (optional, but recommended)
3. **Consider adding init to CI/CD** for test environments
4. **Document production deployment** separately (should NOT use init script)
