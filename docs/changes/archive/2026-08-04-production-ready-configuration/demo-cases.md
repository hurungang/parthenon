# Demo Cases: production-ready-configuration
<!-- Curated representative scenarios for product demo -->
<!-- This is a backend configuration change. Demo scenarios are manual verification steps. -->

## Grep Patterns
<!-- No Playwright tests — backend configuration change -->
N/A

## Scenario Details
| # | Feature | What it Shows | Verification Method |
|---|---------|---------------|-------------------|
| 1 | Consolidated `setup dev` bootstrap | Single command replaces 7+ ad-hoc scripts — provisions Keycloak realms/clients, seeds database roles/permissions/skills, bootstraps certificate authority, and seeds test agent identities in one idempotent invocation | Run `python -m setup.main dev` on a fresh environment; observe structured output (`created`/`skipped` per step); verify `parthenon.ps1 start -Services backend` succeeds and Web UI login works with admin credentials |
| 2 | Control Center starts without Keycloak admin credentials | The core security improvement: running services hold zero identity-provider admin access — Control Center validates the OIDC realm exists via discovery endpoint only, never calls Keycloak admin API | After `setup dev` completes, restart Control Center with `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` removed from its environment; verify CC starts successfully, health endpoint returns 200, and no Keycloak admin API calls appear in logs |
| 3 | Environment variables override YAML config at runtime | Production deployments configure all infrastructure via env vars only — no YAML editing, no container rebuilds. Demonstrates resolution priority (env > YAML > default) and configuration source logging | Set `OIDC_PROVIDER_URL`, `POSTGRES_HOST`/`PORT`/`USER`/`PASSWORD`/`DB`, and `REDIS_HOST`/`PORT`/`PASSWORD` in environment pointing to external infrastructure; start CC; check logs for `env:OIDC_PROVIDER_URL`, `env:POSTGRES_HOST` etc. showing which source resolved each connection |
| 4 | Startup validation with fail-fast error messages | Services detect unreachable dependencies at startup and exit with clear, actionable diagnostics (dependency name, target URL, error type, corrective guidance) — no silent failures or cryptic stack traces | Stop PostgreSQL; attempt to start Control Center; verify CC logs show a clear error identifying PostgreSQL as unreachable (host, port, database name), that CC exits non-zero within 5 seconds, and that the message includes corrective guidance. Repeat for Redis (with CC running) and for OIDC provider (wrong discovery URL) |
| 5 | Setup tool full idempotency (run `setup dev` twice) | Operators can safely re-run setup without errors — all steps detect existing resources and report `skipped`, proving idempotency, recoverability from partial failures, and safe no-op behavior for CI/CD automation | Run `setup dev` to completion; run it again immediately; verify all steps report `skipped` (not `error`), exit code is 0, no duplicate resources are created in Keycloak or database, and the `setup verify` sub-command confirms all components are healthy |
