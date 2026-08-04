# Deployment: Production-Ready Configuration

## 1. Environment Variables

This change extends the environment-variable-driven configuration model to all infrastructure connections and introduces a strict separation between runtime credentials and setup-only admin credentials.

### New Environment Variables (Runtime)

The following variables are introduced for production infrastructure configuration. They follow the resolution priority: environment variable → YAML config file → built-in default. When any of these are set, they override the corresponding YAML file values.

| Variable | Service | Description | Required for Production? |
|----------|---------|-------------|--------------------------|
| `POSTGRES_HOST` | CC | PostgreSQL server hostname or IP address | Yes (when `DATABASE_URL` is not used) |
| `POSTGRES_PORT` | CC | PostgreSQL server port (default: `5432`) | No |
| `POSTGRES_DB` | CC | Target database name | Yes (when `DATABASE_URL` is not used) |
| `POSTGRES_USER` | CC | Database user with read/write access | Yes (when `DATABASE_URL` is not used) |
| `POSTGRES_PASSWORD` | CC | Password for `POSTGRES_USER` | Yes (when `DATABASE_URL` is not used) |
| `REDIS_HOST` | CC, CH | Redis server hostname or IP address | Yes (when `REDIS_URL` is not used) |
| `REDIS_PORT` | CC, CH | Redis server port (default: `6379`) | No |
| `REDIS_PASSWORD` | CC, CH | Redis authentication password | No (unless Redis requires AUTH) |
| `REDIS_DB_INDEX` | CC, CH | Redis logical database index (default: `0`) | No |
| `OIDC_ISSUER_URL` | CC, AR | OIDC issuer URL for JWT `iss` validation; must exactly match tokens | Yes (in production) |
| `OIDC_CLIENT_ID` | CC | OAuth2 client ID registered in the external identity provider | Yes (when using external OIDC) |
| `OIDC_CLIENT_SECRET` | CC | OAuth2 client secret for the external identity provider | Yes (when using external OIDC) |
| `OIDC_JWKS_URI` | CC | JWKS endpoint URL for JWT signature verification | Yes (when using external OIDC) |
| `OIDC_AUDIENCE` | CC | Expected `aud` claim value for token validation | No (defaults to `parthenon`) |
| `IDENTITY_PROVIDER_TYPE` | CC | Selects the identity provider mode: `keycloak_bundled`, `keycloak_external`, `azure_entraid` | Yes (defaults to `keycloak_bundled` for dev) |
| `OIDC_PROVIDER_URL` | CC | Base URL of the OIDC provider (e.g., Keycloak realm URL) | Yes (in production) |
| `OIDC_REALM` | CC | Keycloak realm name; only for `keycloak_bundled` and `keycloak_external` | No (defaults to `parthenon`) |
| `SERVICE_BOOTSTRAP_SOURCE_LOG` | CC, AR, CH | **Auto-enabled at INFO level** — logs which configuration source (env var, YAML, or default) was resolved for every infrastructure connection | No (always active on startup) |

### Environment Variables Removed from Runtime

These variables MUST NOT be set on runtime services. They are consumed exclusively by the consolidated setup tool (`setup/` directory).

| Variable | Previously Set On | Now Set On |
|----------|-------------------|------------|
| `KEYCLOAK_ADMIN` | CC (at startup) | Setup tool only |
| `KEYCLOAK_ADMIN_PASSWORD` | CC (at startup) | Setup tool only |

### Existing Variables with Changed Behaviour

| Variable | Change |
|----------|--------|
| `DATABASE_URL` | Still supported as the single-connection-string alternative. Per-component vars (`POSTGRES_HOST`, etc.) take precedence when set. |
| `REDIS_URL` | Still supported as the single-connection-string alternative. Per-component vars (`REDIS_HOST`, etc.) take precedence when set. |
| `OIDC_PROVIDER_URL`, `OIDC_CLIENT_ID`, `OIDC_REALM`, `OIDC_AUDIENCE` | Previously auto-populated by setup wizard/CLI at startup. Now: must be provided as environment variables (external provider) or populated by running the setup tool BEFORE starting the runtime. The Control Center validates these are present at startup and fails if not. |
| `TELEMETRY_*` | No change. Already follows the env-var-first model. Extended to ensure all `TELEMETRY_*` variables are documented in `.env.example` as the canonical reference. |

### Setup-Only Environment Variables

Set only when running the consolidated setup command. Do NOT set on any runtime service container.

| Variable | Description | Secret |
|----------|-------------|--------|
| `KEYCLOAK_ADMIN` | Username for the Keycloak admin account (bundled Keycloak only) | No |
| `KEYCLOAK_ADMIN_PASSWORD` | Password for the Keycloak admin account (bundled Keycloak only) | Yes |
| `KEYCLOAK_URL` | Keycloak admin API base URL; used by setup tool to reach the Keycloak Admin REST API | No |
| `SETUP_DEV_MODE` | Set to `true` to enable dev-mode data seeding (skips realm bootstrap if already done) | No |

---

## 2. Infrastructure Changes

### Removed: Auto-Provisioning at Runtime

The Control Center no longer auto-provisions Keycloak realms, clients, or roles at startup. All identity provider bootstrapping has been extracted from the `backend/app/main.py` startup sequence into the consolidated setup tool.

### New: `setup/` Directory

A dedicated `setup/` directory, separate from the runtime application containers, contains the consolidated setup CLI. This tool is invoked explicitly by an operator — it is never triggered by application startup.

| File | Responsibility |
|------|---------------|
| `setup/main.py` | Entry point with sub-commands |
| `setup/identity.py` | Keycloak realm/client/role provisioning (formerly in CC startup) |
| `setup/database.py` | Database readiness verification, seeding of roles/permissions/skills |
| `setup/certificates.py` | Certificate authority bootstrapping |
| `setup/dev.py` | Full dev bootstrap: identity + database + certificates + test data |
| `setup/verify.py` | Read-only check of current state without making changes |

### Docker Compose Changes

- **Control Center service**: Removed `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` from environment block. Control Center no longer receives or uses Keycloak admin credentials.
- **Optional setup service**: Added a service with `profiles: [setup]` that runs the consolidated setup command and exits. This service requires the Keycloak admin environment variables but never runs alongside the runtime services.
- **Keycloak dependency**: The Control Center's Keycloak health check dependency for ordering is retained, but the Control Center now validates the realm exists rather than creating it.

### Kubernetes / Helm Changes

- **No Keycloak admin credentials in CC Deployment**: Remove `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` from the Control Center Deployment's environment or Secrets references.
- **Setup Job**: A Kubernetes Job (or `helm.sh/hook: post-install` hook) should run the setup command before the runtime services start. The setup Job requires Keycloak admin credentials via Kubernetes Secrets.
- **Configuration migration**: For existing deployments upgrading to this version, ensure all infrastructure connection variables (`POSTGRES_*`, `REDIS_*`, `OIDC_*`) are set in the Helm values or Kubernetes Secrets BEFORE deploying.

### External Provider Support

Production deployments can now use enterprise-managed infrastructure without modifying YAML files or rebuilding containers:
- **PostgreSQL**: Azure Database for PostgreSQL, AWS RDS, or any managed PostgreSQL 16 instance — configured via `POSTGRES_HOST` and related variables
- **Redis**: Azure Cache for Redis, AWS ElastiCache, or any managed Redis instance — configured via `REDIS_HOST` and related variables
- **Identity Provider**: Azure EntraID or any OIDC-compliant provider — configured via `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_JWKS_URI`
- **Observability**: Existing Prometheus/Jaeger/Loki stacks via `TELEMETRY_OTLP_ENDPOINT` and related variables

---

## 3. Migration Steps

Deploy this change in the following order. Each step must complete successfully before proceeding to the next.

### Step 1 — Prepare Environment Variables

Before deploying any new service images, review and update environment variables in the deployment environment:

- **Production deployments**: Add per-component infrastructure variables (`POSTGRES_*`, `REDIS_*`, `OIDC_*`) matching your existing `DATABASE_URL`, `REDIS_URL`, and `config/identity.yaml` values. If you already use composite connection strings, you may continue doing so — the per-component variables are an alternative, not a replacement.
- **External OIDC providers**: If switching from bundled Keycloak to an external provider, set `IDENTITY_PROVIDER_TYPE`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and `OIDC_JWKS_URI` in the CC environment.
- **Remove from CC**: Delete `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` from the Control Center environment. These must never be present on the runtime service.
- **Keep for setup**: The Keycloak admin credentials remain needed for the setup tool. Move them to the setup service's environment or to a one-shot setup Job.

### Step 2 — Run the Consolidated Setup Command

Run the setup command BEFORE deploying the new service images. The command handles any bootstrapping that was previously done at CC startup.

For bundled Keycloak deployments:
- Run `setup identity` to provision the Keycloak realm, clients, roles, and admin user
- Run `setup verify` to confirm all components are in the expected state
- All operations are idempotent — safe to run on an already-initialized environment

For external provider deployments:
- Ensure the external OIDC client is registered in the identity provider
- Run `setup verify` to confirm the new configuration is valid

### Step 3 — Deploy Updated Backend Services

Deploy the new service images. Start in the standard order with the following validation checks:

1. **Control Center**: Verify the startup log shows configuration source logging for every infrastructure connection (e.g., `config: database_host resolved from env var POSTGRES_HOST` or `config: database_host resolved from YAML`). Verify the log shows `validating Keycloak configuration` followed by `Keycloak configuration valid` (not `provisioning Keycloak realm`). Verify the startup log does NOT contain `KEYCLOAK_ADMIN` or any admin credential reference.
2. **Agent Runtime**: Verify the startup log shows a successful Control Center reachability validation before certificate bootstrap.
3. **Communication Hub**: Verify the startup log shows successful Control Center and Redis reachability validations.

If any service fails to start with a validation error, resolve the configuration issue before proceeding — do NOT revert to the old behavior of auto-provisioning.

### Step 4 — Remove Deprecated Scripts

After confirming the new deployment is stable, remove the deprecated ad-hoc scripts from the `scripts/` directory:

- `scripts/init-local-dev.py` — replaced by `setup dev`
- `scripts/fix-agent-client.py` — replaced by `setup identity`
- `scripts/fix-admin-permissions.py` — replaced by `setup identity` or `setup verify`
- `scripts/check-admin-permissions.py` — replaced by `setup verify`
- `scripts/check-duplicate-admins.py` — replaced by `setup verify`
- `scripts/provision-test-user.py` — replaced by `setup dev`
- `scripts/issue-service-cert.py` — replaced by `setup certificates`

### Step 5 — Smoke Test

Execute the standard smoke test from the first-time deployment runbook to confirm all components function correctly after the change.

---

## 4. Rollback Procedure

If deployment fails, follow this ordered rollback sequence.

### Step R1 — Identify Failure Point

Determine which validation check failed:
- Check the CC startup log for which dependency was unreachable (PostgreSQL, Keycloak, or Redis)
- Check the AR startup log for Control Center reachability failure
- Check the CH startup log for Control Center or Redis reachability failure
- Confirm whether the setup command was run successfully before deploying

Record the failure point before proceeding.

### Step R2 — Stop Failed Services

Stop only the services affected by or involved in the failure. Leave PostgreSQL and Redis running unless the failure is in the data layer.

### Step R3 — Revert to Previous Service Images

Roll all three services back to the last known-good image tags. Start them in standard order.

### Step R4 — Restore Keycloak Admin Credentials to CC (if needed)

If rolling back to the previous version, restore `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` to the Control Center environment. The previous version expects these to be present and will auto-provision the Keycloak realm at startup.

### Step R5 — Validate Rollback

Re-run the standard smoke test to confirm the platform is operating correctly at the previous state. Do not re-attempt the new deployment until the root cause is understood and fixed.

### Rollback Guardrails

- Do not leave Keycloak admin credentials on the Control Center after a successful deployment — this defeats the security purpose of this change.
- Do not revert to individual ad-hoc scripts after the consolidated setup command has been deployed — maintain the new setup tool as the single entry point.
- Do not re-enable Keycloak auto-provisioning at CC startup as a workaround — fix the setup command flow instead.

---

## 5. Master Deployment Update Instructions

After implementation, update the following files in `docs/master/deployment/`:

### `docs/master/deployment/environment-variables.md`

- Add the new per-component PostgreSQL variables (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`) to the Database section.
- Add the new per-component Redis variables (`REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB_INDEX`) to the Redis section.
- Add the new OIDC variables (`OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_JWKS_URI`, `OIDC_AUDIENCE`, `IDENTITY_PROVIDER_TYPE`, `OIDC_PROVIDER_URL`, `OIDC_REALM`) to a new section: "OIDC / Identity — Production Configuration".
- Mark `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` as **Setup-Only** — add a note that these must NOT be set on the Control Center runtime service.
- Add a new "Setup Tool" section documenting the setup-only variables.

### `docs/master/deployment/first-time-deployment.md`

- In Step 1 (Provision Infrastructure): Add explicit instruction for external providers — when using `keycloak_external` or `azure_entraid`, omit the Keycloak service entirely.
- In Step 4 (Configure Identity Provider): Update to reference the consolidated setup command instead of the setup wizard or individual CLI commands. Clarify that the CC no longer auto-provisions the identity provider.
- In Step 5 (Set Environment Variables): Add a note that `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` must NOT be set on the CC runtime service — only on the setup tool.
- Add a new step between Step 5 and Step 7: "Step — Run Consolidated Setup Command". Document running the setup tool (identity, database, certificates sub-commands) before deploying backend services.
- In Step 7 (Deploy Backend Services): Update the CC startup description to reflect validation instead of provisioning. Add validation of the startup log for configuration source logging.
- In Step 10 (Seed Platform Configuration): Replace references to individual setup scripts and the setup wizard/CLI flow with references to the consolidated setup command. Document that the wizard-based setup flow (UI) remains available for bundled Keycloak only.

### `docs/master/deployment/rollback.md`

- Add a new "Change-Specific Rollback: Production-Ready Configuration" section following the existing pattern.
- Include trigger conditions: CC fails to start because Keycloak admin credentials are missing; validation failure for unreachable infrastructure; setup command run incorrectly.
- Include R1–R5 steps: revert images, restore Keycloak admin credentials to CC environment, re-run health checks, validate.

### `docs/master/deployment/services.md`

- Add the setup service (with `profiles: [setup]`) to the container inventory if a Docker Compose setup service definition is added.
- Update the Control Center description: remove Keycloak provisioning from the list of startup responsibilities; add startup validation.

### `docs/master/deployment/configuration-files.md`

- Update the Resolution Order section to confirm that the env-var-first priority now applies to all infrastructure connections, not just telemetry.
- Add a section for `config/identity.yaml` covering: when it is written (by setup tool), when environment variables override it, and that it can be omitted when all OIDC config is provided via environment variables.
