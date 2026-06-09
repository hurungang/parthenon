# Parthenon — Agent Instructions

## Mandatory Pre-Change Check

Before making any code or documentation change, first review `docs/config.yaml` to understand the highlevel folder structure, and ensure the change complies with every `top_priority_rules` entry; if any conflict exists, stop and escalate for clarification.

**If the change involves database schema changes (or you're unsure), verify `.change.yaml` for `has_db_changes: true` and apply pending migrations with `alembic upgrade head` before testing.**

## Debugging 500 Errors

If the backend returns 500 errors during testing, the most likely cause is **unapplied database migrations**. Run `python -m alembic current` and compare against the latest file in `backend/alembic/versions/`. If out of date, run `python -m alembic upgrade head` and restart the backend.

## Managing Dev Servers (Windows)

**Do NOT run dev servers directly in the bash tool.** Always use `parthenon.ps1` (project root) to manage the stack — it handles startup order, health checks, and certificate bootstrapping correctly.

### Common Commands

```powershell
# Start all backend services (CC first, then AR, then CH)
.\parthenon.ps1 start -Services backend

# Start/restart everything (including infra)
.\parthenon.ps1 restart

# Start a single service (useful after code changes to that service only)
.\parthenon.ps1 restart -Services control-center -Force

# Force restart without prompts
.\parthenon.ps1 restart -Services backend -Force

# Check service status
.\parthenon.ps1 status

# View logs
.\parthenon.ps1 logs -Services control-center
.\parthenon.ps1 logs -Services agent-runtime -Lines 100
.\parthenon.ps1 logs -Services communication-hub -Follow
```

### Important

- **Always restart `backend` services** after code changes to ensure certificates are bootstrapped correctly (uvicorn `--reload` can restart CH/AR during CC downtime, leaving them without certs).
- **Start order matters**: CH and AR need CC running first for certificate bootstrap. `parthenon.ps1` enforces: infra → control-center → agent-runtime → communication-hub → frontend.
- If CH or AR logs show "no certificate manager available", run `.\parthenon.ps1 restart -Services communication-hub,agent-runtime -Force` to rebootstrap.

## Port Conflicts

Port 8080 is already occupied on this machine (Node.js / Docker backend process).
**Keycloak must use port 8082** (`docker-compose.yml` maps `8082:8080`).

Env defaults for local dev (`frontend/.env.local`):
- `VITE_OIDC_AUTHORITY=http://localhost:8082/realms/parthenon`
- `VITE_OIDC_CLIENT_ID=parthenon-api-ui`
- `VITE_API_BASE_URL=http://localhost:8000/api/v1`

## Database Migrations

**CRITICAL: Always verify that database migrations have been applied before testing backend changes.**

When a change involves `has_db_changes: true` in `.change.yaml` or modifies files under `backend/app/db/models/`, the migration must be applied to the database before the backend will work correctly.

### Before Starting the Backend

1. **Check current migration status:**
   ```powershell
   cd backend
   python -m alembic current
   ```

2. **Apply pending migrations:**
   ```powershell
   python -m alembic upgrade head
   ```

3. **Verify the migration succeeded:**
   ```powershell
   python -m alembic current
   ```
   The output should show the latest revision ID (check `backend/alembic/versions/` for the most recent file).

### Common Migration Issues

- **"column does not exist" errors**: The migration wasn't applied. Run `alembic upgrade head`.
- **"type already exists" errors**: The enum was created by model import. Use `postgresql.ENUM(..., create_type=False)` in migrations instead of `sa.Enum()`.
- **Parameterized DDL errors**: PostgreSQL doesn't support parameterized queries for DDL. Use string formatting (f-strings) instead of `.bindparams()` for `ALTER TYPE`, `CREATE TYPE`, etc.
- **Transaction aborted errors**: A previous statement failed and aborted the transaction. Use separate `op.execute()` calls or check for existence before creating objects.

### After Creating a New Migration

1. Generate the migration:
   ```powershell
   cd backend
   python -m alembic revision --autogenerate -m "description_of_change"
   ```

2. **Review the generated migration file** in `backend/alembic/versions/` for:
   - Correct `down_revision` chain
   - Proper handling of enum types (use `postgresql.ENUM` with `create_type=False`)
   - No parameterized DDL statements
   - Reversible `downgrade()` function

3. Apply the migration:
   ```powershell
   python -m alembic upgrade head
   ```

4. **Restart the backend** after applying migrations (the ORM models are cached at startup).

### Migration Best Practices

- **Enum types**: Always use `postgresql.ENUM(..., create_type=False)` in migrations. The enum will be created automatically when the model is imported.
- **Unique constraints**: Include all columns that identify a unique row (e.g., `(model_id, model_name, period)` not just `(model_id, period)`).
- **Data backfill**: When restructuring tables, handle `NULL` values explicitly (e.g., `COALESCE(details, '{}'::json)` or `row.details if row.details is not None else {}`).
- **JSON serialization**: When inserting JSON data via raw SQL, serialize to string and use `CAST(:details AS jsonb)` in the SQL.

## Running Frontend Tests

When running Vitest tests in the frontend, use the JSON reporter to avoid potential stdout issues and get structured results:

```powershell
cd frontend
npx vitest run --reporter=json --outputFile=vitest_results.json
```

Then read the results:
```powershell
$j = Get-Content frontend/vitest_results.json | ConvertFrom-Json
Write-Host "Passed: $($j.numPassedTests) / $($j.numTotalTests)  Failed: $($j.numFailedTests)"
```

To see which tests failed:
```powershell
$j.testResults | Where-Object { $_.status -eq 'failed' } | ForEach-Object {
    Write-Host $_.testFilePath
    $_.assertionResults | Where-Object { $_.status -eq 'failed' } | ForEach-Object { Write-Host "  x $($_.fullName)" }
}
```

## Backend Logs

Backend logs are located at `backend/logs/`. Key log files:
- `control-center.log` — main backend (CC API) logs
- `agent-runtime.log` — agent runtime execution logs
- `communication-hub.log` — Communication Hub logs

These are rotated with numeric suffixes (.1, .2, etc.). Always check the most recent file (no suffix) for current issues.

## Temporary Files

Temporary test scripts for quick local testing of auth flows, etc. must be saved under `scripts/` and should be named descriptively (e.g. `test-auth-flows.ps1`) to avoid confusion with production scripts. These are not intended for long-term use and can be deleted after testing is complete.

Temporary output files generated during testing (e.g. token dumps, test logs) should be saved under `tmp/` with descriptive names (e.g. `auth-flow-test-output.txt`) and can be deleted after review. This keeps the project organized and prevents clutter in the main directories.
