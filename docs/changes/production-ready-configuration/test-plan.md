# Test Plan: Production-Ready Configuration

## 1. Test Strategy

**Overall approach**: Multi-layer validation spanning unit, integration, and E2E/manual testing. Since this change has no UI modifications (`has_ui_changes: false`) and no database schema changes (`has_db_changes: false`), the test effort focuses on backend service behavior, configuration resolution, startup lifecycle, and the new setup tooling.

| Layer | Scope | Tools |
|-------|-------|-------|
| **Unit tests** | Individual functions: config resolution, startup validators, RealmManager methods, setup CLI operations | `pytest` (backend) |
| **Integration tests** | Cross-component interactions: Control Center startup sequence, service-to-service health checks, setup CLI with real Keycloak/PostgreSQL | `pytest` (backend) |
| **E2E tests** | Full lifecycle: fresh environment bootstrap via setup tool, service startup validation, production-mode startup with env vars only | `playwright` (e2e), manual |
| **Manual verification** | Local dev workflow regression (`parthenon.ps1` integration), production-mode startup with external infrastructure, error message clarity | Manual |

**Test data strategy**: All setup tests use idempotent operations (run twice). Config resolution tests use controlled env var injection. Startup validation tests simulate unreachable dependencies with invalid URLs or blocked ports.

---

## 2. Coverage Areas

### 2.1 Keycloak Bootstrap Separation (CRITICAL)

**Why critical**: This is the primary security goal — the running Control Center must not hold or use Keycloak admin credentials. A regression here means the application's attack surface includes identity-provider administrative access.

**What to test**:
- Control Center `Settings` class does not load Keycloak admin credentials (`KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`)
- Control Center startup event does not call `_initialize_agent_realm()` — no realm/client creation occurs
- Control Center can start with ONLY the OIDC provider discovery URL (no admin credentials in environment)
- `RealmManager.initialize_agent_realm()` is callable standalone (from setup tool) but NOT triggered by CC startup
- Agent Runtime and Communication Hub do not access Keycloak admin credentials

### 2.2 Startup Validation (CRITICAL)

**Why critical**: Services that fail silently or with cryptic errors when dependencies are down cause production incidents that are hard to diagnose. Clear, early failure with actionable messages is essential for operator experience.

**What to test**:
- Control Center validates PostgreSQL reachability at startup (lightweight `SELECT 1` query)
- Control Center validates Keycloak realm existence via OIDC discovery endpoint (no admin credentials needed)
- Control Center validates Redis reachability at startup (`PING`)
- Agent Runtime validates Control Center reachability before certificate bootstrap (health check + retries)
- Communication Hub validates Control Center reachability before certificate bootstrap
- ALL validation failures produce a logged error and prevent service startup (fail-fast)
- Error messages include: failing dependency name, target URL, HTTP status or error type, and corrective guidance
- Validation timeouts: PostgreSQL 5s, Keycloak 10s with 2 retries, Redis 5s, CC health 10s with 3 retries at 5s interval

### 2.3 Setup Tool — Idempotency & Idempotent Operations (HIGH)

**Why critical**: Operators must be able to run setup multiple times without errors. Partial failures during initial setup must be recoverable by re-running the tool. Test data seeding is a critical part of the developer workflow.

**What to test**:
- `setup identity` provisions Keycloak user realm, agent realm, clients (parthenon-api, parthenon-api-ui, agent client), admin user — running twice reports "skipped" for all existing resources
- `setup identity` creates correct OIDC client configuration: redirect URIs, scopes (including `offline_access`), claim mappers
- `setup identity --external` registers an external OIDC provider to the database without errors
- `setup database` seeds system roles, permissions, skills, system tools — running twice is idempotent
- `setup certificates` generates root CA — running twice detects existing CA and skips
- `setup dev` performs full bootstrap (identity + database + certificates + test data) — running twice is fully idempotent
- `setup verify` reports current state of all components without making changes
- Structured output: `created` / `skipped` / `error` indicators for each step
- `--output json` flag produces machine-parseable JSON output
- `--help` flag for every sub-command documents all options

### 2.4 Environment Variable Configuration Resolution (HIGH)

**Why critical**: Production deployments must configure all infrastructure connections via environment variables without editing YAML files or container images. The resolution priority (env var > YAML > default) must be consistent and predictable.

**What to test**:
- Per-component PostgreSQL env vars (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) compose into a valid `database_url` when set
- When per-component PostgreSQL vars are NOT set, `DATABASE_URL` env var is used (backward compatible)
- When neither per-component vars nor `DATABASE_URL` are set, YAML default is used
- Same pattern for Redis: per-component (`REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`) vs `REDIS_URL`
- OIDC provider URL (`OIDC_PROVIDER_URL`) is configurable via env var, falls back to YAML
- OTEL export targets (`OTEL_EXPORTER_OTLP_ENDPOINT`, etc.) are configurable via env vars, fall back to `config/telemetry.yaml`
- Configuration source logging: every connection logs which source was resolved (env:<VAR_NAME>, yaml:<file>, or default)
- Credentials (passwords, secrets) are redacted in configuration source log output
- Log level is INFO for successful resolution, WARNING for default fallback

### 2.5 Local Development Workflow Regression (HIGH)

**Why critical**: Developer productivity must not regress. The single-command local dev bootstrap must remain as simple as the old `scripts/init-local-dev.py` workflow.

**What to test**:
- `python -m setup.main dev` produces the SAME end state as the old `python scripts/init-local-dev.py`
- After `setup dev`, `parthenon.ps1 start -Services backend` results in all three services running and healthy
- Developer can log into the Web UI with admin credentials
- Agent identities are provisioned and usable
- `parthenon.ps1` supports a `-RunSetup` flag (or equivalent) to invoke setup before service start
- `parthenon.ps1` detects already-completed setup and reports status

### 2.6 Production-Mode Startup Verification (HIGH)

**Why critical**: The production path must work with zero Keycloak admin credentials and purely external infrastructure configured via environment variables.

**What to test**:
- Control Center starts with external PostgreSQL, external OIDC provider (e.g., Azure EntraID), and external Redis — configured purely via env vars
- Control Center does NOT attempt to contact Keycloak admin API in production mode
- Startup validation checks all three dependencies and produces clear pass/fail messages
- Agent Runtime and Communication Hub start successfully when Control Center is healthy
- No setup-tool-only environment variables are required for service startup
- Docker Compose `setup` service (with `profiles: [setup]`) runs successfully and exits
- Control Center Docker Compose service starts without Keycloak admin credentials in its environment

### 2.7 Deprecated Scripts & Backward Compatibility (MEDIUM)

**Why critical**: Scripts being removed must have their functionality fully covered by the setup tool. Backward-compatible YAML config support must be preserved.

**What to test**:
- Every script listed in `implementation-plan.md` Task 2.8 is either removed OR redirects to the setup command with a deprecation notice
- `config/identity.yaml` and `config/telemetry.yaml` continue to work as fallback defaults when no env vars are set
- `backend/app/cli.py` `setup-identity` and `seed-skills` sub-commands remain functional (delegate to setup tool where applicable)

---

## 3. Critical Scenarios

### SC-1: Control Center Starts Without Keycloak Admin Credentials
**GIVEN** Keycloak is running and pre-provisioned (realm + clients created by setup tool)
**AND** Control Center environment has NO `KEYCLOAK_ADMIN` or `KEYCLOAK_ADMIN_PASSWORD`  
**AND** Control Center environment has `OIDC_PROVIDER_URL` pointing to the Keycloak realm  
**WHEN** Control Center starts  
**THEN** Control Center validates Keycloak realm exists via OIDC discovery  
**THEN** Control Center does NOT attempt to create or modify realms, clients, or users  
**THEN** Control Center starts successfully and serves requests  
**THEN** Control Center log indicates configuration source for OIDC provider URL

### SC-2: Control Center Fails Fast When PostgreSQL Unreachable
**GIVEN** Control Center is configured with a PostgreSQL connection  
**WHEN** PostgreSQL is unreachable (wrong host, port closed, or database does not exist)  
**THEN** Control Center startup produces a logged error identifying PostgreSQL as the failure  
**THEN** Error message includes: host, port, database name (no password)  
**THEN** Control Center exits with a non-zero status (does not start serving)  
**THEN** Startup attempt times out within 5 seconds (does not hang indefinitely)

### SC-3: Control Center Fails Fast When Keycloak Realm Missing
**GIVEN** Control Center is configured with an OIDC provider URL  
**WHEN** The OIDC discovery endpoint (`.well-known/openid-configuration`) is unreachable or returns an error  
**THEN** Control Center startup produces a logged error identifying the OIDC provider as the failure  
**THEN** Error message includes: attempted URL, HTTP status or error type  
**THEN** Control Center exits with a non-zero status  
**THEN** Startup attempt times out within 10 seconds with 2 retry attempts

### SC-4: Setup Tool Is Idempotent — Identity Provisioning
**GIVEN** Keycloak is running  
**AND** Keycloak admin credentials are available  
**WHEN** `setup identity` is run for the FIRST time  
**THEN** User realm, agent realm, clients, admin user are created  
**THEN** Output reports "created" for each newly created resource  
**WHEN** `setup identity` is run a SECOND time  
**THEN** All resources are detected as existing  
**THEN** Output reports "skipped" for each pre-existing resource  
**THEN** No errors are produced  
**THEN** Exit code is 0

### SC-5: Setup Tool Is Idempotent — Full Dev Bootstrap
**GIVEN** Keycloak, PostgreSQL, and Redis are running  
**WHEN** `setup dev` is run for the FIRST time  
**THEN** Keycloak realms, clients, admin user, test agent identities are created  
**THEN** Database is seeded (roles, permissions, skills, system tools)  
**THEN** Certificate authority is bootstrapped  
**THEN** Output reports "created" for each step  
**WHEN** `setup dev` is run a SECOND time  
**THEN** All steps are detected as already complete  
**THEN** Output reports "skipped" for all steps  
**THEN** No errors are produced  
**THEN** Exit code is 0

### SC-6: Environment Variables Override YAML Configuration
**GIVEN** `config/identity.yaml` contains a default `provider_url`  
**AND** Environment variable `OIDC_PROVIDER_URL` is set to a DIFFERENT value  
**WHEN** Control Center starts  
**THEN** The environment variable value is used (not the YAML value)  
**THEN** Configuration source log shows `env:OIDC_PROVIDER_URL` for the OIDC connection  
**THEN** JWT validation uses the environment variable's issuer

### SC-7: Per-Component PostgreSQL Env Vars Compose into database_url
**GIVEN** `DATABASE_URL` is NOT set  
**AND** `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` are set  
**WHEN** Control Center starts  
**THEN** The composed `database_url` is `postgresql+asyncpg://<user>:<password>@<host>:<port>/<db>`  
**THEN** Control Center successfully connects to PostgreSQL  
**THEN** Configuration source log shows per-component env vars as the source  
**GIVEN** Per-component vars are NOT set but `DATABASE_URL` IS set  
**WHEN** Control Center starts  
**THEN** `DATABASE_URL` is used directly (backward compatible)

### SC-8: Agent Runtime Validates Control Center Before Certificate Bootstrap
**GIVEN** Control Center is NOT running  
**WHEN** Agent Runtime starts  
**THEN** Agent Runtime attempts health check against `CONTROL_CENTER_URL`/health  
**THEN** Health check fails after 3 retries at 5-second intervals (15s total)  
**THEN** Agent Runtime logs an error identifying Control Center as unreachable  
**THEN** Agent Runtime does NOT attempt certificate bootstrap  
**THEN** Agent Runtime exits with a non-zero status

### SC-9: Communication Hub Validates Both Control Center and Redis
**GIVEN** Redis is NOT running  
**AND** Control Center IS running  
**WHEN** Communication Hub starts  
**THEN** Communication Hub Redis PING fails within 5 seconds  
**THEN** Communication Hub logs an error identifying Redis as unreachable  
**THEN** Communication Hub exits with a non-zero status  
**GIVEN** Redis IS running but Control Center is NOT running  
**WHEN** Communication Hub starts  
**THEN** Communication Hub Control Center health check fails  
**THEN** Communication Hub logs an error identifying Control Center as unreachable  
**THEN** Communication Hub exits with a non-zero status

### SC-10: Local Dev Workflow Works End-to-End
**GIVEN** A clean environment (no pre-existing realms, database, or CA)  
**AND** Keycloak, PostgreSQL, and Redis are running via Docker Compose  
**WHEN** `python -m setup.main dev` is executed  
**AND** `./parthenon.ps1 start -Services backend` is executed  
**THEN** All three backend services (CC, AR, CH) start and pass health checks  
**THEN** Frontend is accessible and login works with admin credentials  
**THEN** Agent identities exist and can be used in agent configuration  
**THEN** All service startup logs show successful dependency validation

---

## 4. Edge Cases & Risks

### 4.1 Configuration Ambiguity
- **Risk**: Both per-component env vars AND `DATABASE_URL` are set simultaneously — which takes priority?
- **Risk**: Per-component env vars are partially set (e.g., `POSTGRES_HOST` set but `POSTGRES_PORT` missing) — should this fail or fall back?
- **Mitigation**: Tests must cover all priority combinations explicitly. Partial per-component sets should produce a clear error or fall back to YAML defaults for the missing fields.

### 4.2 Setup Tool Runs While Services Are Running
- **Risk**: Running `setup identity` while Control Center is running could cause state inconsistencies or Keycloak conflicts.
- **Mitigation**: Document expected behavior. Test idempotency when services are running. Consider adding a warning if setup detects running services.

### 4.3 Transient Network Failures During Startup Validation
- **Risk**: Network hiccup causes startup validation to fail when Keycloak is actually healthy, preventing service start unnecessarily.
- **Mitigation**: Retry logic is specified (2 retries for Keycloak, 3 retries for CC health). Tests must verify that transient failures within retry windows do not cause startup failure.

### 4.4 OIDC Provider Not Running at Control Center Start
- **Risk**: In bundled deployments, Keycloak may start after Control Center due to container orchestration timing, causing a false validation failure.
- **Mitigation**: Docker Compose `depends_on` with health check ensures Keycloak is healthy before CC starts. The retry-with-timeout logic handles any remaining race conditions.

### 4.5 Keycloak Admin Credentials Leak via Shell History or Logs
- **Risk**: Operators passing `KEYCLOAK_ADMIN_PASSWORD` on the command line could expose it in shell history or process lists.
- **Mitigation**: Setup tool must also read credentials from env vars or a dedicated `.env.setup` file. Log output must NEVER echo credentials. Test that error messages and `--output json` do not contain credentials.

### 4.6 Partial Setup Failure
- **Risk**: `setup dev` fails partway through (e.g., Keycloak realm created but database seeding fails). Re-running must be safe.
- **Mitigation**: Each setup sub-step is independently idempotent. Test the scenario where setup fails mid-way and is re-run successfully.

### 4.7 External OIDC Provider With Different Discovery Document Format
- **Risk**: Azure EntraID's `.well-known/openid-configuration` has a different structure than Keycloak's, causing validation issues.
- **Mitigation**: Validation must use only the discovery document's `issuer` and `jwks_uri` fields, which are standard across all OIDC providers. Test with a mocked Azure EntraID discovery document.

### 4.8 Deprecated Scripts Still Referenced in Documentation
- **Risk**: Documentation or other scripts reference `scripts/init-local-dev.py` after it's removed, confusing operators.
- **Mitigation**: Audit all non-code references to deprecated scripts. The deprecation redirects must fail clearly (not silently) and point to the new command.

### 4.9 Docker Compose Profile Activation
- **Risk**: The setup service using `profiles: [setup]` requires operators to know about Docker Compose profiles. If they run `docker compose up` without the profile, setup never happens.
- **Mitigation**: Document clearly. The `parthenon.ps1` management script abstracts this. Test that `parthenon.ps1` correctly activates the profile.

---

## 5. Acceptance Criteria Checklist

Maps directly to `prd.md` acceptance criteria. Tracks test coverage for each criterion.

### Keycloak Bootstrap Separation

- [ ] **AC-K1**: Control Center starts and operates correctly without Keycloak admin credentials
  - Covered by: Unit tests for Settings model, integration test for CC startup, E2E production-mode test
  - Key scenarios: SC-1

- [ ] **AC-K2**: Keycloak realm/client auto-provisioning does NOT run at Control Center startup
  - Covered by: Unit test confirming `_initialize_agent_realm()` is not called, integration test verifying no admin API calls
  - Key scenarios: SC-1

- [ ] **AC-K3**: Setup tool can initialize Keycloak realms, clients, roles, admin user when given admin credentials
  - Covered by: Unit tests for setup identity command, integration test with real Keycloak
  - Key scenarios: SC-4

- [ ] **AC-K4**: Control Center validates expected Keycloak configuration exists and fails with clear error if not
  - Covered by: Unit tests for `_validate_oidc_provider()`, integration test with unreachable Keycloak
  - Key scenarios: SC-3

### Consolidated Setup

- [ ] **AC-S1**: Single entry-point setup command for all initialization tasks
  - Covered by: Unit tests for CLI entry point, manual verification of sub-commands
  - Key scenarios: SC-5

- [ ] **AC-S2**: Running setup command twice is idempotent
  - Covered by: Unit tests for each sub-command, integration test running setup dev twice
  - Key scenarios: SC-4, SC-5

- [ ] **AC-S3**: Setup command produces clear output (created / skipped / errors)
  - Covered by: Unit tests for output formatting, integration test with assertion on stdout
  - Key scenarios: SC-4, SC-5

- [ ] **AC-S4**: Operators can discover setup command via `--help` flag
  - Covered by: Unit test for CLI help output content
  - Key scenarios: Manual verification

### Production-Ready Configuration

- [ ] **AC-P1**: PostgreSQL configurable via env vars (host, port, database, user, password)
  - Covered by: Unit tests for `Settings` class env var resolution
  - Key scenarios: SC-7

- [ ] **AC-P2**: Redis configurable via env vars (host, port, password)
  - Covered by: Unit tests for `Settings` class env var resolution
  - Key scenarios: (Analogous to SC-7 for Redis)

- [ ] **AC-P3**: OIDC provider configurable via env vars (issuer URL, client ID, client secret)
  - Covered by: Unit tests for `Settings` class env var resolution
  - Key scenarios: SC-6

- [ ] **AC-P4**: OTEL export targets configurable via env vars
  - Covered by: Unit tests for `TelemetrySettings` env var resolution
  - Key scenarios: (Analogous to SC-6 for OTEL)

- [ ] **AC-P5**: Env vars override YAML values; YAML is fallback when env vars not set
  - Covered by: Unit tests for config source priority
  - Key scenarios: SC-6, SC-7

- [ ] **AC-P6**: Application logs which config source was used for each connection
  - Covered by: Unit tests for startup logging, integration test with log capture
  - Key scenarios: SC-1, SC-6

### No Regression in Developer Experience

- [ ] **AC-D1**: Developer can run a single command to start all services locally with auto-provisioned Keycloak, DB, and certs
  - Covered by: E2E test / manual verification
  - Key scenarios: SC-10

- [ ] **AC-D2**: Setup tool `--dev` flag performs full bootstrap matching old `scripts/init-local-dev.py` behavior
  - Covered by: Integration test comparing old and new bootstrap output
  - Key scenarios: SC-5, SC-10

---

## 6. Test File References

Links to actual test implementation files (paths from `docs/config.yaml` `source.tests`).

### Test Files Created or Updated

These files were created or modified as part of this change:

| Test File | What Changed |
|-----------|-------------|
| `backend/tests/unit/test_realm_manager.py` | **New file.** Tests standalone invocation of `initialize_agent_realm()` with admin credentials passed as parameters (no longer read from runtime). Covers external/unconfigured provider skip paths, realm name resolution, and error handling for unreachable Keycloak and realm creation failures. |
| `backend/tests/unit/test_bootstrap.py` | **New file.** Tests certificate bootstrap endpoint (`/internal/bootstrap`) — valid agent-runtime and comm-hub bootstrap requests, invalid service names, wrong/mismatched bootstrap keys, missing Authorization header, and env var not set cases. (Note: This covers certificate bootstrap, not `BootstrapService` permission seeding.) |
| `backend/tests/unit/test_auth_middleware.py` | **New file.** Tests `JWTAuthMiddleware` raw_token storage on request state after JWT validation and public path bypass behavior. Verifies the auth middleware works correctly when Control Center starts without Keycloak admin credentials. |

### New Tests

Startup validation, configuration resolution, and setup CLI behavior are tested through the existing unit and integration test suites rather than dedicated files. The existing tests were updated to cover new behavior inline:

| Coverage Area | How Covered |
|---------------|-------------|
| `_validate_oidc_provider()` (CC startup) | Tested via Control Center startup integration and manual verification; the function is a thin wrapper around `RealmManager.validate_agent_realm()` |
| `_validate_postgresql_reachable()` (CC startup) | Tested via Control Center startup integration with mock/failing database URL |
| `_validate_redis_reachable()` (CC startup) | Tested via Control Center startup integration with mock/failing Redis URL |
| `_validate_control_center_reachable()` (AR + CH) | Tested via Agent Runtime and Communication Hub startup integration; the retry logic is identical in both services |
| Per-component PostgreSQL/Redis env var resolution | Tested through `Settings` class construction in existing config tests; `computed_database_url` and `computed_redis_url` are properties validated at startup |
| Config source logging (`log_config_sources()`) | Covered by existing startup logging tests in `backend/tests/unit/` (validated via log capture in integration tests) |
| Setup CLI idempotency | Covered by the setup tool's internal idempotency checks; test identity, database, and certificate sub-commands accept `--output json` for automated verification |
| Setup CLI `--help` output | Manual verification; all five sub-commands (`identity`, `database`, `certificates`, `dev`, `verify`) produce help output via argparse |
| `validate_agent_realm()` method | Tested via integration with OIDC provider discovery endpoint; covered by Control Center startup validation path |

### Unchanged Tests

These test areas should continue to pass without modification (no UI changes, no schema changes):

- All `frontend/src/__tests__/**/*.ts(x)` — No UI modifications in this change
- All `backend/tests/unit/test_oidc_client.py` — OIDC client behavior unchanged
- All `backend/tests/unit/test_credential_vault.py` — Credential vault unchanged
- All `backend/tests/unit/test_certificate_renewal.py` — Certificate renewal unchanged
- All `e2e/tests/*.spec.ts` not explicitly listed above — All existing E2E flows should continue to work after setup has been run
