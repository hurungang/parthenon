# Implementation Plan: Production-Ready Configuration

## Overview

This plan implements the separation of Keycloak bootstrap tooling from the runtime application, consolidates environment setup scripts into a single `setup/` directory, and enables production deployments configured purely through environment variables. The change removes identity provider auto-provisioning from Control Center startup (replacing it with validation checks), centralizes all bootstrapping logic in a dedicated setup command, and extends environment-variable-driven configuration to all infrastructure connections (PostgreSQL, Redis, OIDC, OTEL).

## Task Checklist

### Phase 1 — Extract Keycloak Bootstrap from Control Center Startup
- [ ] 1.1 — Remove Keycloak admin credential fields from Control Center runtime Settings
- [ ] 1.2 — Remove `_initialize_agent_realm()` call from Control Center startup event
- [ ] 1.3 — Move `RealmManager.initialize_agent_realm()` into a standalone callable usable outside the runtime
- [ ] 1.4 — Add conditional startup validation that expected Keycloak realm exists (only when super-admin login is disabled)

### Phase 2 — Create setup/ Directory with Consolidated Init Script
- [ ] 2.1 — Create `setup/` directory structure at project root
- [ ] 2.2 — Create unified setup CLI entry point with sub-commands
- [ ] 2.3 — Port Keycloak realm and client provisioning from `scripts/init-local-dev.py` and `backend/app/services/identity/bootstrap_service.py` into setup sub-commands
- [ ] 2.4 — Port database seeding (roles, skills, system tools, admin user) into setup sub-commands
- [ ] 2.5 — Port certificate authority bootstrapping into setup sub-command
- [ ] 2.6 — Add `--dev` flag that runs full bootstrap matching old `scripts/init-local-dev.py` behavior
- [ ] 2.7 — Add idempotency checks and structured output reporting to all setup operations
- [ ] 2.8 — Deprecate or remove ad-hoc scripts replaced by the consolidated setup command

### Phase 3 — Restructure Configuration for Environment-Variable Priority
- [ ] 3.1 — Add per-component environment variable fields for PostgreSQL connection to `Settings`
- [ ] 3.2 — Add per-component environment variable fields for Redis connection to `Settings`
- [ ] 3.3 — Add environment variable fields for Keycloak admin credentials (used by setup tool only)
- [ ] 3.4 — Implement startup configuration-source logging (env var, YAML, or default) for every infrastructure connection

### Phase 4 — Add Startup Validation (Instead of Auto-Provisioning)
- [ ] 4.1 — Add PostgreSQL reachability validation to Control Center startup
- [ ] 4.2 — Add conditional Keycloak realm existence validation to Control Center startup (skipped when super-admin login enabled)
- [ ] 4.3 — Add Redis reachability validation to Control Center startup
- [ ] 4.4 — Add Control Center reachability validation to Agent Runtime startup
- [ ] 4.5 — Add Control Center reachability validation to Communication Hub startup

### Phase 5 — Update Docker Compose, .env.example, and Documentation
- [ ] 5.1 — Update `docker-compose.yml` to remove Keycloak admin credentials from Control Center environment
- [ ] 5.2 — Update `docker-compose.yml` to add optional setup service for bundled deployments
- [ ] 5.3 — Update `.env.example` with all new environment variables and their descriptions
- [ ] 5.4 — Update `parthenon.ps1` to support setup invocation before service start

### Phase 6 — Regression Testing and Cleanup
- [ ] 6.1 — Run full backend test suite and fix regressions
- [ ] 6.2 — Run frontend test suite
- [ ] 6.3 — Verify local dev workflow (single command to bootstrap and start services)
- [ ] 6.4 — Verify production-mode startup with external PostgreSQL, Redis, and OIDC provider via env vars only
- [ ] 6.5 — Clean up deprecated code paths and remove dead configuration imports

---

## Phase 1 — Extract Keycloak Bootstrap from Control Center Startup

### Task 1.1 — Remove Keycloak admin credential fields from Control Center runtime Settings

The `Settings` class in `backend/app/core/config.py` currently has no explicit Keycloak admin credential fields — `RealmManager._get_keycloak_base_url()` and `RealmManager.initialize_agent_realm()` access them via `getattr(settings, "keycloak_admin_user", "admin")`. Those attributes are set implicitly through environment variables passed in `docker-compose.yml`. This task ensures that any Keycloak admin credential environment variables used by the runtime are explicitly documented as **setup-tool-only** and are not loaded into Control Center's runtime environment. The `RealmManager` and `_initialize_agent_realm()` will be moved to the setup tool, so these credentials will not be needed at runtime.

**Done when:**
- No Keycloak admin credentials (username, password) are read or loaded by the Control Center runtime Settings
- `docker-compose.yml` no longer passes `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` to the `control-center` service
- Any remaining Keycloak-related Settings fields are documented as setup-tool-only

### Task 1.2 — Remove `_initialize_agent_realm()` call from Control Center startup event

The `startup_event()` in `backend/app/main.py` calls `_initialize_agent_realm()`, which checks if the agent provider is keycloak with a localhost issuer and auto-creates the agent realm. This call must be removed entirely from the startup sequence. In its place, a validation check will be added (see Task 1.4).

**Done when:**
- `_initialize_agent_realm()` is no longer called in `startup_event()`
- The `_initialize_agent_realm()` function implementation is either removed from `backend/app/main.py` or relocated to the setup tool module
- Control Center starts without attempting to contact Keycloak admin API

### Task 1.3 — Move `RealmManager.initialize_agent_realm()` into a standalone callable usable outside the runtime

The `RealmManager` class in `backend/app/services/identity/realm_manager.py` contains the agent realm provisioning logic (create realm, apply token policies, create OIDC client). This logic must remain intact but be refactored so it can be called from the new `setup/` CLI tool without importing the full FastAPI application. No changes to the Keycloak API interaction logic itself; only structural relocation.

**Done when:**
- `RealmManager.initialize_agent_realm()` can be invoked from a script in `setup/` without importing `backend/app/main.py` or triggering the FastAPI app creation
- The function signature and behavior are unchanged
- All existing unit tests for `RealmManager` pass in their new location

### Task 1.4 — Add conditional startup validation that expected Keycloak realm exists

Replace the auto-provisioning with a conditional validation check. On startup, Control Center checks whether super-admin login is enabled. If super-admin login is **disabled** (i.e., OIDC is the only authentication path), verify that the configured Keycloak realm is reachable by fetching the `.well-known/openid-configuration` endpoint. If unreachable, fail with a clear error. If super-admin login is **enabled**, skip the OIDC reachability check — the super admin may be performing initial setup and the OIDC provider may not be configured yet.

**Done when:**
- Control Center checks `SUPERADMIN_LOGIN_ENABLED` before performing OIDC validation
- When super-admin login is disabled and OIDC provider is unreachable: logged error and startup failure
- When super-admin login is enabled: OIDC validation is skipped (info log only)
- The error message clearly identifies which URL was checked and what failed

---

## Phase 2 — Create setup/ Directory with Consolidated Init Script

### Task 2.1 — Create `setup/` directory structure at project root

Create the `setup/` directory at the project root level with a clear module structure. This directory is separate from the runtime application (`backend/`) and is not included in any Docker container or deployed artifact.

**Done when:**
- `setup/` directory exists at project root with a `__init__.py` or equivalent entry point
- Directory structure documented in a `setup/README.md` explaining its purpose and usage
- The directory is excluded from Docker builds (`.dockerignore` updated if needed)

### Task 2.2 — Create unified setup CLI entry point with sub-commands

Build the main entry point that operators invoke. It must support sub-commands covering all bootstrapping needs, with built-in help (`--help`) for each. The CLI framework should match the existing pattern in `backend/app/cli.py` (argparse-based) or be a standalone Python script with clear usage.

Sub-commands required:
- `setup identity` — Provision Keycloak realm, clients, roles, admin user (bundled mode)
- `setup identity --external` — Register external OIDC provider
- `setup database` — Verify database readiness, seed internal data (roles, permissions, skills, system tools)
- `setup certificates` — Bootstrap the certificate authority
- `setup dev` — Full local development bootstrap (the `--dev` shortcut from Task 2.6)
- `setup verify` — Check current state of all components without making changes

**Done when:**
- Single entry-point command exists at `setup/main.py` or similar with `--help` flag
- Each sub-command has a clear description and `--help` output
- The entry point works when invoked from the project root: `python -m setup.main <sub-command>`

### Task 2.3 — Port Keycloak realm and client provisioning into setup sub-commands

Move the Keycloak provisioning logic from `scripts/init-local-dev.py` (steps 1–5: authenticate, create realm, create clients for both user and agent realms, enable offline_access scope, add claim mappers, create test agent identities) and from `backend/app/services/identity/bootstrap_service.py` (provision_bundled_keycloak) into the `setup identity` sub-command.

**Done when:**
- Running `python -m setup.main identity` provisions both the user realm and agent realm in a bundled Keycloak
- OIDC clients (`parthenon-api`, `parthenon-api-ui`, agent client) are created with correct redirect URIs and scopes
- Admin user is created with the specified password
- The operation is idempotent — running twice produces no errors and reports existing state

### Task 2.4 — Port database seeding into setup sub-commands

Move the database initialization logic from `scripts/init-local-dev.py` (steps 7–9: create system_admin role, wildcard policy, admin user in platform_users, admin role assignment) and from Control Center startup (`_run_bootstrap()`, `_seed_system_tools()`) into the `setup database` sub-command.

**Done when:**
- `setup database` verifies PostgreSQL is reachable before proceeding
- System roles, permissions, skills, and system tools are seeded idempotently
- Admin user in `platform_users` is created/linked correctly
- Control Center startup `_run_bootstrap()` and `_seed_system_tools()` continue to work for runtime seeding of internal data (these seed data that may be needed fresh on each restart, separate from setup-time operations)

### Task 2.5 — Port certificate authority bootstrapping into setup sub-command

Move the CA bootstrapping call from `_initialize_certificate_authority()` in `backend/app/main.py` into the `setup certificates` sub-command. The runtime CA initialization must remain for service startup (the CA needs to be loaded in memory), but the initial CA generation/seed should be invokable via setup.

**Done when:**
- `setup certificates` generates (or loads) the root CA certificate and stores it
- The operation is idempotent — detects existing CA and reports it
- Running `setup certificates` before `setup dev` ensures the CA is available when services start

### Task 2.6 — Add `--dev` flag for full local development bootstrap

Implement a `setup dev` sub-command (or `--dev` flag on `setup identity`) that performs every step the old `scripts/init-local-dev.py` did: Keycloak user realm, agent realm, all clients, admin user, test agent identities, database seeding, role assignments, and CA bootstrapping — in the correct dependency order.

**Done when:**
- Running `python -m setup.main dev` produces the same end state as `python scripts/init-local-dev.py` currently does
- All steps are idempotent
- Output clearly shows what was created, what was skipped, and any errors

### Task 2.7 — Add idempotency checks and structured output reporting

Every setup operation must detect existing state before making changes. When a resource already exists (realm, client, user, role, etc.), the command must report it was skipped rather than attempting to recreate it. Output must be structured and scannable.

**Done when:**
- Running any setup sub-command twice produces zero errors
- Output uses clear indicators (created/skipped/error) for each step
- JSON output mode is available for scripting (`--output json` flag)

### Task 2.8 — Deprecate or remove ad-hoc scripts replaced by the consolidated setup command

The following scripts in `scripts/` are superseded by the consolidated setup tool:
- `init-local-dev.py` — replaced by `setup dev`
- `fix-agent-client.py` — replaced by `setup identity` (idempotent client creation)
- `fix-admin-permissions.py` — replaced by `setup database`
- `check-admin-permissions.py` — replaced by `setup verify`
- `check-duplicate-admins.py` — replaced by `setup verify`
- `provision-test-user.py` — replaced by `setup identity` (test user seeding)
- `issue-service-cert.py` — replaced by `setup certificates`

**Done when:**
- Each deprecated script either redirects to the setup command or is removed
- If kept as redirects, they print a deprecation notice pointing to the new command
- The consolidated setup command covers all functionality these scripts provided

---

## Phase 3 — Restructure Configuration for Environment-Variable Priority

### Task 3.1 — Add per-component environment variable fields for PostgreSQL connection to `Settings`

The current `Settings` class has a single `database_url` field. Add per-component environment variable fields (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) that, when set, are composed into the full `database_url` at runtime. When they are not set, the existing `DATABASE_URL` env var or YAML default is used as-is.

**Done when:**
- Setting `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` individually produces a valid `database_url` without requiring the full URL to be specified
- The composed URL follows the format `postgresql+asyncpg://user:password@host:port/db`
- When per-component vars are NOT set, `DATABASE_URL` is used directly (backward compatible)
- Configuration source (env component, env full URL, YAML, or default) is logged at startup

### Task 3.2 — Add per-component environment variable fields for Redis connection to `Settings`

Similarly, add `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, and `REDIS_DB` environment variable fields that compose into the `redis_url`. When not set, the existing `REDIS_URL` env var or default is used.

**Done when:**
- Per-component Redis env vars compose into a valid `redis_url`
- Backward compatibility with `REDIS_URL` is preserved
- Configuration source is logged at startup

### Task 3.3 — Add environment variable fields for Keycloak admin credentials (used by setup tool only)

Add explicit fields to `Settings` or a separate setup configuration model for `KEYCLOAK_ADMIN_USER` and `KEYCLOAK_ADMIN_PASSWORD`. These are used exclusively by the setup tool — the Control Center runtime must not require or load them. This requires clear separation: the setup tool reads these, but the runtime application's `Settings` class does not.

**Done when:**
- `KEYCLOAK_ADMIN_USER` and `KEYCLOAK_ADMIN_PASSWORD` env vars are available to the setup tool
- The Control Center `Settings` class does not load or validate these fields
- `docker-compose.yml` passes these only to a setup service container, not to `control-center`

### Task 3.4 — Implement startup configuration-source logging for every infrastructure connection

At startup, each service must log which configuration source was resolved for each infrastructure connection it uses. The log message format should clearly indicate the connection name, the resolved value (with credentials redacted), and the source: `env:<VAR_NAME>`, `yaml:<file>`, or `default`.

**Done when:**
- Control Center logs configuration sources for: PostgreSQL, Redis, OIDC provider URL, OTEL endpoint
- Agent Runtime logs configuration source for: Control Center URL
- Communication Hub logs configuration sources for: Control Center URL, Redis
- Credentials (passwords, secrets) are redacted in log output
- Log level is INFO for successful resolution, WARNING when falling back to defaults

---

## Phase 4 — Add Startup Validation (Instead of Auto-Provisioning)

### Task 4.1 — Add PostgreSQL reachability validation to Control Center startup

Before the Control Center begins serving requests, it must verify it can connect to the configured PostgreSQL database. If the connection fails, the service logs a clear error with the host/port/database it attempted and fails to start.

**Done when:**
- Control Center attempts a lightweight DB query (e.g., `SELECT 1`) during startup
- A connection failure results in a logged error and application exit (not a warning or silent skip)
- The error message includes the host, port, and database name (no credentials)
- A 5-second timeout prevents indefinite blocking

### Task 4.2 — Add conditional Keycloak realm existence validation to Control Center startup

Validate that the OIDC provider's `.well-known/openid-configuration` endpoint is reachable, but only when super-admin login is disabled. When super-admin login is enabled, the super admin may be in the middle of initial setup (the OIDC provider may not exist yet), so the check is skipped. When skipped because the OIDC provider is not reachable, an info-level log is emitted noting that OIDC validation was bypassed due to super-admin mode.

**Done when:**
- Control Center checks `SUPERADMIN_LOGIN_ENABLED` before fetching the OIDC discovery document
- When super-admin login is enabled: OIDC validation is skipped with an info log
- When super-admin login is disabled and OIDC provider is unreachable: logged error and startup failure with context (URL attempted, HTTP status or error type)
- The check handles both bundled Keycloak and external OIDC providers
- A 10-second timeout with retry (2 attempts) prevents transient network issues from causing false failures

### Task 4.3 — Add Redis reachability validation to Control Center startup

Control Center must verify Redis connectivity at startup. This mirrors the existing `_verify_redis_connectivity()` already implemented in Communication Hub.

**Done when:**
- Control Center executes a Redis `PING` during startup
- A connection failure results in a logged error and application exit
- The error message includes the Redis URL (with password redacted)
- A 5-second timeout prevents indefinite blocking

### Task 4.4 — Add Control Center reachability validation to Agent Runtime startup

The Agent Runtime depends on Control Center for certificate bootstrapping. Before attempting certificate operations, the Agent Runtime must verify Control Center is reachable at the configured `CONTROL_CENTER_URL`.

**Done when:**
- Agent Runtime sends a GET request to `{CONTROL_CENTER_URL}/health` during startup
- A failed health check results in a logged error and startup failure
- The check runs BEFORE attempting certificate bootstrap
- A 10-second timeout with retry (3 attempts, 5-second interval) handles Control Center cold starts

### Task 4.5 — Add Control Center reachability validation to Communication Hub startup

The Communication Hub depends on Control Center for certificate bootstrapping and data access. It must verify Control Center is reachable at startup. The existing `_verify_redis_connectivity()` check is retained.

**Done when:**
- Communication Hub sends a GET request to `{CONTROL_CENTER_URL}/health` during startup
- A failed health check results in a logged error and startup failure
- The check runs BEFORE attempting certificate bootstrap
- Same retry logic as Agent Runtime (3 attempts, 5-second interval)

---

## Phase 5 — Update Docker Compose, .env.example, and Documentation

### Task 5.1 — Update `docker-compose.yml` to remove Keycloak admin credentials from Control Center environment

The `control-center` service in `docker-compose.yml` must no longer receive `KEYCLOAK_ADMIN` or `KEYCLOAK_ADMIN_PASSWORD` environment variables. It should only receive the OIDC provider URL needed for JWT validation. Keycloak admin credentials are only needed by the setup service (Task 5.2).

**Done when:**
- `control-center` service environment block does not contain Keycloak admin credentials
- Control Center starts successfully in Docker Compose (after setup has been run) using only the OIDC provider URL for JWT validation
- Keycloak `depends_on` condition on `control-center` remains for health check ordering

### Task 5.2 — Update `docker-compose.yml` to add optional setup service for bundled deployments

Add an optional `setup` service to `docker-compose.yml` that runs the consolidated setup command and exits. This service receives Keycloak admin credentials and database credentials. In production (external infrastructure), this service is omitted entirely; operators run the setup command separately.

**Done when:**
- A `setup` service exists in `docker-compose.yml` with a profile (`profiles: [setup]`) so it does not run by default
- The setup service has access to Keycloak admin credentials and database credentials
- Running `docker compose --profile setup run setup dev` performs the full bootstrap and exits
- The setup service uses the same Docker image as `control-center` with a different entry point

### Task 5.3 — Update `.env.example` with all new environment variables

Expand `.env.example` to document every new and existing environment variable, organized by connection type. Each variable must include: name, description, default value, whether it is required for production, and which service(s) use it.

**Done when:**
- `.env.example` includes sections for: PostgreSQL (full URL + per-component), Redis (full URL + per-component), OIDC provider, Keycloak admin (setup-only), OTEL, service bootstrap keys, and certificate paths
- Each variable has a comment describing its purpose, default, and when it is required
- Setup-only variables are explicitly marked as not needed at runtime

### Task 5.4 — Update `parthenon.ps1` to support setup invocation before service start

The `parthenon.ps1` management script must support an option to run the setup command before starting services. For local development, `parthenon.ps1 start` should optionally run `setup dev` first (or detect if setup has already been run and skip).

**Done when:**
- `parthenon.ps1` has a `-RunSetup` flag or equivalent that invokes the setup command before starting services
- The script detects whether setup has already been completed and reports status
- Local dev workflow (`./parthenon.ps1 start -Services backend -RunSetup`) works end-to-end

---

## Phase 6 — Regression Testing and Cleanup

### Task 6.1 — Run full backend test suite and fix regressions

Run all backend unit and integration tests. Any test that depends on the old auto-provisioning behavior (e.g., tests expecting the agent realm to be auto-created at startup) must be updated to either run setup first or mock the validation checks.

**Done when:**
- All backend tests pass (`pytest backend/tests/`)
- No test relies on the Control Center auto-provisioning Keycloak resources
- Tests that need a pre-configured Keycloak either run setup first or mock the realm validation

### Task 6.2 — Run frontend test suite

Run all frontend tests. Since this change has no UI modifications (`has_ui_changes: false`), all existing tests should pass without changes.

**Done when:**
- All frontend tests pass (`npx vitest run` in `frontend/`)
- No regressions in UI behavior related to identity provider configuration

### Task 6.3 — Verify local dev workflow

Confirm that a developer can start a fresh environment with a single command (or minimal set of commands) and get a fully working system: Keycloak, database, Redis, all three backend services, and the frontend.

**Done when:**
- Running `python -m setup.main dev` followed by `./parthenon.ps1 start -Services backend` results in a fully working local environment
- The developer can log into the Web UI with the admin credentials
- Agent identities are provisioned and can be used
- The workflow is documented clearly

### Task 6.4 — Verify production-mode startup with external infrastructure

Confirm that the Control Center starts correctly when configured with external PostgreSQL, Redis, and OIDC provider via environment variables only — no YAML file editing, no Keycloak admin credentials, no bundled Keycloak container.

**Done when:**
- Setting `DATABASE_URL`, `REDIS_URL`, and `OIDC_PROVIDER_URL` to external services (pointing to real or mocked endpoints) allows Control Center to start
- Control Center does not attempt to contact Keycloak admin API
- Startup validation checks all three services and produces clear pass/fail messages
- The service starts successfully when all validations pass

### Task 6.5 — Clean up deprecated code paths and remove dead configuration imports

Remove any code that is no longer reachable after the changes: the old `_initialize_agent_realm()` in `main.py` (if not already done), stale imports, unused configuration file references, and any references to removed scripts.

**Done when:**
- `_initialize_agent_realm()` function definition is removed from `backend/app/main.py` (or relocated)
- No unused imports remain in modified files
- `config/identity.yaml` is still supported for backward-compatible dev defaults but is clearly documented as secondary to environment variables
- All deprecated scripts are either removed or redirect to the setup command

---

## Completion Checklist

- [ ] Control Center starts without Keycloak admin credentials and without auto-provisioning the agent realm
- [ ] Control Center validates PostgreSQL, Keycloak, and Redis reachability at startup with clear error messages on failure
- [ ] Agent Runtime validates Control Center reachability at startup before certificate bootstrap
- [ ] Communication Hub validates Control Center reachability at startup before certificate bootstrap
- [ ] `setup/` directory exists with unified CLI covering identity, database, certificates, and dev bootstrap
- [ ] `python -m setup.main dev` replicates all behavior of the old `scripts/init-local-dev.py`
- [ ] All setup operations are idempotent and produce structured output
- [ ] PostgreSQL, Redis, and OIDC provider connections are configurable via per-component environment variables
- [ ] Every infrastructure connection's configuration source is logged at startup
- [ ] `docker-compose.yml` has an optional setup service, and Control Center no longer receives Keycloak admin credentials
- [ ] `.env.example` documents all new and existing environment variables
- [ ] `parthenon.ps1` supports setup invocation before service start
- [ ] All backend tests pass
- [ ] All frontend tests pass
- [ ] Local dev workflow (setup + start) works end-to-end
- [ ] Production-mode startup with external infrastructure via env vars works
