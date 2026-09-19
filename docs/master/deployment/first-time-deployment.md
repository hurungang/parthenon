# First-Time Deployment Runbook

This is the canonical ordered runbook for deploying a fresh Parthenon instance. There is no prior state — all infrastructure, services, and configuration are created from scratch.

Follow each step in order. Do not proceed to the next step until the current step is verified.

Applies to both deployment targets:
- **Docker Compose** — use `docker compose up` commands and Docker secrets
- **Kubernetes / Helm** — use `helm install` with a prepared `values.yaml` and Kubernetes Secrets

---

## Step 1 — Provision Infrastructure

Start PostgreSQL, Redis, and (when using bundled Keycloak) the Keycloak container.

**Before starting services**, ensure:
- `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` are set in the environment configuration if `IDENTITY_PROVIDER_TYPE=keycloak_bundled`
- Host port `8082` is free (required by the bundled Keycloak container; the container internally uses port 8080 but Docker maps it to host port 8082)

In Docker Compose, bring up the `postgres`, `redis`, and `keycloak` services first. In Kubernetes, apply or install the `postgres`, `redis`, and `keycloak` Helm components. If using an external identity provider (`keycloak_external` or `azure_entraid`), omit the Keycloak service.

Confirm connectivity:
- PostgreSQL is accepting connections on the configured host and port
- Redis is accepting connections on the configured host and port
- When using bundled Keycloak: Keycloak admin console is reachable at `http://localhost:8082` and the `/health/ready` endpoint returns healthy
- All are reachable from the network namespace that backend services will use

Do not proceed until all relevant health checks pass.

---

## Step 2 — Initialise the Database

Create the target database and the schema owner role in PostgreSQL if they do not already exist. Set the schema owner role as the owner of the target database.

The database name, user, and password must match the values that will be set in `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`.

---

## Step 3 — Run Alembic Migrations

Execute all Alembic migrations from `backend/alembic/` against the freshly initialised database using the `DATABASE_URL` connection string.

Run the migration using the `alembic upgrade head` command. Verify that the `alembic_version` table is present in the target database and contains a version row corresponding to the latest migration revision.

The Platform API will refuse to start if it cannot reach the database with the expected schema.

---

## Step 4 — Prepare Identity Provider Dependencies

Identity provider configuration is now stored in the database (`IdentityProviderConfig` table) and managed via the System Config UI after super admin login. The platform follows a three-tier bootstrap: (1) super admin login, (2) configure OIDC providers via UI, (3) optionally disable super admin.

**Bundled Keycloak (dev/demo)**

If using the bundled Keycloak for dev/demo, start the Keycloak container along with PostgreSQL and Redis in Step 1. The bundled Keycloak is provisioned by the consolidated setup tool in Step 6 — no manual client registration is needed. Confirm that the JWKS endpoint (`http://keycloak:8082/realms/parthenon/protocol/openid-connect/certs`) will be accessible from the Control Center container's network.

> **Note:** Keycloak is optional in production — only start it for dev/demo deployments or when the platform bootstraps without external OIDC providers.

**External OIDC providers (production)**

If using external OIDC providers (Keycloak external, Azure EntraID, or any OIDC-compliant provider), ensure they are running and accessible from the Control Center container's network. You will need:
- The provider's issuer URL (for `.well-known/openid-configuration` discovery)
- A registered OAuth2 client ID and client secret with `{PLATFORM_API_BASE_URL}/api/v1/auth/callback` as the allowed redirect URI
- The client must support `authorization_code` grant type

These values are entered via the System Config UI after super admin login in Step 11 — no environment variables are needed for OIDC at launch.

**Deployments migrating from pre-refinement (existing `config/identity.yaml`)**

If you are upgrading an existing deployment that used `config/identity.yaml`, ensure the file is still accessible from the Control Center container. The Bootstrap Service will automatically migrate its contents to the database on first startup. Keep the deprecated `OIDC_*` environment variables set for the migration — they are read only during this one-time migration. After migration is verified, remove the `OIDC_*` vars and the `config/identity.yaml` mount.

---

## Step 5 — Set Environment Variables

Populate all environment variables listed in [environment-variables.md](environment-variables.md) for every service.

For sensitive values (all variables marked **secret** in the reference), use:
- **Docker Compose**: Docker secrets or a `.env` file excluded from source control
- **Kubernetes**: Kubernetes Secrets referenced by the `secrets.yaml` Helm template

Pay special attention to:
- **`SUPER_ADMIN_ENABLED`, `SUPER_ADMIN_USERNAME`, `SUPER_ADMIN_PASSWORD_HASH`** — required for the super admin bootstrap login path. Set `SUPER_ADMIN_ENABLED=true` during initial deployment, then set to `false` after OIDC is verified working. `SUPER_ADMIN_PASSWORD_HASH` must be a pre-computed Argon2id or bcrypt hash — never set a plaintext password. Generate with: `python -m app.cli hash-password`.
- **`OIDC_*` variables** — **Migration only.** All `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_PROVIDER_URL`, `OIDC_REALM`, `OIDC_AUDIENCE`, `IDENTITY_PROVIDER_TYPE`, and `OIDC_AGENT_CLIENT_PREFIX` variables are only read during the one-time `config/identity.yaml` → DB migration. They are ignored at runtime after the migration completes. New deployments that have never used `config/identity.yaml` do not need any `OIDC_*` variables — OIDC providers are configured via the System Config UI.
- `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` — must be set before the first MCP session is created; changing this key after credentials are stored requires re-encrypting all stored credentials
- `API_KEY_HASH_SECRET` — must be set before the first API key is created. Generate a cryptographically random 32+ character string and store it in your secrets manager. Changing this value later invalidates all previously issued API keys.
- `OTEL_SERVICE_NAME` — set uniquely per container so telemetry can be filtered per service

> **Critical — Setup-only variables:** `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` must **NOT** be set on the Control Center runtime service. These are consumed exclusively by the consolidated setup tool (Step 6). The Control Center no longer receives or uses Keycloak admin credentials — set them only in the setup tool's environment or a one-shot setup Job.

> **Note on `config/identity.yaml`:** For bundled Keycloak deployments, `config/identity.yaml` is written automatically by the consolidated setup tool in Step 6. For external provider deployments, all OIDC configuration is provided via environment variables — the YAML file can be omitted entirely. Environment variables always take precedence over YAML values. Operators should NOT hand-edit this file for settings managed by the setup tool. See [configuration-files.md](configuration-files.md) for the full reference.

---

## Step 6 — Run the Consolidated Setup Command

Run the consolidated setup command BEFORE deploying backend services. The setup tool handles all bootstrapping that was previously done at CC startup.

**For bundled Keycloak deployments:**

Run the following sub-commands in order:

- `python -m setup.main identity` — provision the Keycloak realm, clients, roles, and admin user
- `python setup/main.py database` — verify the database is reachable and seed roles, permissions, and skills
- `python setup/main.py certificates` — bootstrap the certificate authority for mTLS
- `python setup/main.py verify` — read-only check to confirm all components are in the expected state

All operations are idempotent — safe to run on an already-initialized environment.

**For external provider deployments (`keycloak_external` or `azure_entraid`):**

- Ensure the external OIDC client is registered in the identity provider (Step 4)
- All OIDC configuration is provided via environment variables (Step 5)
- Run `setup verify` to confirm the new configuration is valid — this does not attempt to provision anything in the external provider

**Docker Compose:** The setup tool can be run as a one-shot service with `profiles: [setup]`:

Run `docker compose --profile setup run --rm setup` to execute the setup tool as a one-shot service.

This service requires the Keycloak admin environment variables but runs independently of the runtime services and exits after completing.

**Kubernetes / Helm:** Run the setup command as a Kubernetes Job (with `helm.sh/hook: post-install` or a pre-deployment Job). The setup Job requires Keycloak admin credentials via Kubernetes Secrets.

> **Verification:** After running the setup command, confirm `setup verify` reports all components as configured. If any service reports `NOT_CONFIGURED`, resolve the missing configuration before proceeding to Step 8.

---

## Step 7 — Deploy the OTEL Collector

Start the OTEL Collector with the pipeline configuration defined in `infra/otel-collector-config.yaml`.

Confirm:
- Collector is listening on gRPC port 4317 and HTTP port 4318 for OTLP input
- Prometheus exporter is active on port 8889
- Jaeger exporter is reaching the configured Jaeger backend
- Loki exporter is reaching the configured Loki backend
- Collector health endpoint (port 13133) returns healthy

Backend services will attempt to connect to the OTEL Collector on startup. If the collector is not reachable, services will log a warning but continue to start — telemetry will be dropped until the collector is available.

### Telemetry configuration (optional)

The backend telemetry pipeline is configurable via `TELEMETRY_*` environment variables (see [environment-variables.md](environment-variables.md)). All variables are optional — the backend defaults to a console exporter with all signals enabled when none are set.

For deployments that use a declarative config file instead of individual env vars, see [configuration-files.md](configuration-files.md) for the full `config/telemetry.yaml` reference.

**Docker Compose**: To use file-based config, bind-mount `./config/telemetry.yaml` into the `backend` service and set `TELEMETRY_CONFIG_FILE` to the in-container path. To use only env vars, add the required `TELEMETRY_*` entries to the `.env` file. To match prior-version behaviour, set `TELEMETRY_EXPORTER_TYPE=otlp` and `TELEMETRY_OTLP_ENDPOINT` to the Collector address.

**Kubernetes**: To share a single telemetry configuration across all backend replicas, create a ConfigMap from `config/telemetry.yaml`, mount it as a volume in the backend Deployment, and set `TELEMETRY_CONFIG_FILE` to the mount path. Prefer env vars (backed by Kubernetes Secrets) for any secret values such as `TELEMETRY_LOGFIRE_TOKEN`. See [configuration-files.md](configuration-files.md) for the full guidance on when to use file-based vs env-var-based config for multi-pod deployments.

---

## Step 8 — Deploy Backend Services

Start backend services in the following strict order. Each service must reach a healthy state before the next is started.

1. **`control-center`** (port 8000) — Verify the `/health` endpoint responds before proceeding. After the health check passes, confirm that the Certificate Authority has initialised by calling `GET /api/v1/certificates/ca` — the response should include a `certificate_pem` field. The CA is generated automatically on first startup and logged with the serial number and expiry.

   **Startup validation:** Review the Control Center startup log to confirm:
   - **Configuration source logging** is emitted for every infrastructure connection (e.g., `config: database_host resolved from env var POSTGRES_HOST` or `config: database_host resolved from YAML`)
   - **Super admin credentials seeded** — if `SUPER_ADMIN_ENABLED=true`, the log should show "Super admin credentials seeded" confirming the `super_admin_credentials` table is populated
   - **OIDC Provider Registry initialized** — the log should show "OIDC Provider Registry initialized" with either discovered providers from the database or an empty cache
   - The log does **NOT** contain `KEYCLOAK_ADMIN` or any admin credential reference

   If the startup log shows a validation failure for any infrastructure dependency (PostgreSQL, Keycloak, Redis), resolve the configuration issue before proceeding — do NOT revert to the old auto-provisioning behaviour.

   **Bundled Keycloak startup:** Bundled Keycloak is now conditional — only required for dev/demo deployments or when `SUPER_ADMIN_ENABLED=true` with no OIDC config in the database. For production deployments with external OIDC providers, the Keycloak container can be omitted entirely.

2. **`agent-runtime`** (port 8001) — Depends on `control-center` and `communication-hub` for certificate bootstrap. Agent instances present mTLS certificates to Communication Hub for tool calls. Ensure `CONTROL_CENTER_URL` is set.

3. **`communication-hub`** (port 8002) — Depends on `redis` and `control-center`. Ensure `CONTROL_CENTER_URL` is set to the `control-center` base URL before starting. Note: `CH_API_KEY_AUTH_ENABLED` defaults to `false` on first deployment — API key authentication is disabled by default. Enable it by setting `CH_API_KEY_AUTH_ENABLED=true` only after verifying the platform is operational and the API key creation flow works end-to-end.

All MCP Hub, Skill Engine, Agent Engine, Scheduling Engine, and Notification Engine logic runs within `control-center` and `agent-runtime` — there are no separate services for these components. Agent-to-agent communication and MCP tool proxy routing is handled by `communication-hub`.

**Agent instance certificate provisioning** — Before starting any agent instance, provision a TLS certificate for each agent type:
1. Obtain an admin JWT token.
2. Call `POST /api/v1/certificates/issue` with the `agent_type_id` and a unique `instance_id` (hostname or job ID).
3. Save the returned `certificate_pem` to the path set in `AGENT_CERT_PATH` and `private_key_pem` to `AGENT_KEY_PATH` (set permissions to `600`).
4. Download the CA certificate: `GET /api/v1/certificates/ca` → save `certificate_pem` to `CA_CERT_PATH`.
5. Set `CONTROL_CENTER_URL` to the `control-center` base URL on the agent runtime container.

If any service fails to start, check its logs for connection errors to PostgreSQL, Redis, or the OIDC JWKS endpoint before attempting to restart it.

---

## Step 9 — Deploy the API Gateway

Start the `nginx` reverse proxy with routing rules configured to point to the deployed backend services.

Confirm:
- Health endpoints for `control-center` and `agent-runtime` respond through the nginx proxy
- WebSocket path `/ws/` is proxied to `communication-hub` with appropriate timeout settings (`proxy_read_timeout` must be set high enough for long-lived connections)
- `/api/` is proxied to `control-center`
- `/gateway/` is proxied to `agent-gateway`
- TLS is terminated at nginx in production deployments

---

## Step 10 — Deploy the Web UI

Start the `web-ui` container with the API Gateway base URL configured.

Confirm:
- The frontend application loads in a browser
- The frontend resolves the Platform API via the configured base URL
- The OIDC login flow initiates correctly (redirect to identity provider)

---

## Step 11 — Seed Platform Configuration

Perform initial platform setup using the three-tier bootstrap: super admin login → configure OIDC providers via UI → verify OIDC login → optionally disable super admin.

### Tier 1 — Super Admin Login

1. Navigate to the Web UI login page. Confirm the page shows both a username/password form (super admin) and OIDC login buttons (if OIDC providers are discovered from auto-migration).
2. Log in using the super admin credentials set in Step 5 (`SUPER_ADMIN_USERNAME` and the password for `SUPER_ADMIN_PASSWORD_HASH`).
3. Confirm the System Config admin page is accessible from the super admin session.

**Verification:** Super admin can access all admin pages. Control Center logs show "super admin authentication successful."

### Tier 2 — Configure OIDC Providers via System Config UI

Using the super admin session:

1. Navigate to **System Config → Identity Providers**.
2. For each identity provider (user-scoped and optionally agent-scoped):
   - Enter the **issuer URL**, **client ID**, **client secret**, **scopes**, and optional **claims mapping**.
   - Use the **"Test Connection"** button to validate OIDC discovery reachability before saving.
   - Use the **"Test Login"** button to perform a full authentication flow and verify claims response.
   - Save each provider configuration.
3. Confirm each provider is persisted with `is_enabled=true`.

> **For bundled Keycloak dev/demo.** The bundled Keycloak is auto-configured by the setup tool in Step 6. Its config is automatically migrated to the database on first startup. The System Config UI shows it as an imported provider — use "Test Connection" to verify, then enable it.

**Verification:** `identity_provider_config_audits` table contains audit entries for each operation. OIDC discovery logs show "OIDC discovery successful" for each enabled provider.

### Tier 3 — Verify OIDC Login & Optionally Disable Super Admin

1. Log out of the super admin session.
2. From the login page, click the OIDC login button for the configured user identity provider.
3. Complete the OIDC authentication flow and confirm successful login with the appropriate role/permissions.
4. If an agent identity provider is configured separately, trigger an agent execution and confirm the agent identity token is resolved correctly.

**Verification:** OIDC-authenticated user can access all permitted features. Agent execution uses the correct identity token.

5. Once OIDC is confirmed working: set `SUPER_ADMIN_ENABLED=false`, restart the Control Center, and verify the super admin login form no longer appears. OIDC login continues to work.

### Post-Bootstrap Configuration

After the three-tier bootstrap:

6. Call `POST /api/v1/setup/init` (public endpoint) to create the first administrator role and identity — this only needs to be done once
7. **Seed the Permission Engine.** Execute the role-seeding script (or CLI command) against the database. The seed creates the built-in `platform_admin` role with unrestricted policy statements, a `PlatformUser` record for the designated administrator, and assigns the `platform_admin` role via a `UserRole` record. Optionally set `PERMISSION_ENGINE_SEED_ADMIN_EMAIL` before running the script to pre-select the admin email without interactive prompting — remove the variable afterwards. Verify by querying the `roles`, `platform_users`, and `user_roles` tables. See [operational-runbooks.md](operational-runbooks.md) §3 for full details.
8. Register at least one MCP server via the MCP Hub admin page
9. Trigger a tool sync for the registered MCP server to populate the tool catalogue
10. Define initial roles and permissions appropriate for the deployment
11. Configure at least one notification channel if notifications are required

---

## Step 12 — Smoke Test

Execute a complete end-to-end test to confirm all components are functioning:

1. Create an agent type via the admin UI bound to an available skill or SOP
2. Initiate a conversation with the agent through the Web UI Chat page
3. Submit a test prompt and confirm a response is received
4. Verify that an OTEL trace for the interaction appears in the configured Jaeger backend
5. Verify that structured log entries for the interaction appear in the Loki log aggregation backend
6. Confirm the conversation record is visible in the Conversation History page

If all six checks pass, the deployment is complete.

> **Optional: API key MCP verification.** If API key authentication is enabled (`CH_API_KEY_AUTH_ENABLED=true`), create an API key for an agent identity and verify external MCP connectivity: call `load_skills` via the Communication Hub MCP endpoint using the API key as a Bearer token, confirm skills are returned with `updated_at` timestamps, and verify tool calls execute correctly through the proxy.

> **Permission Engine latency baseline:** Before switching the Permission Engine from audit mode to enforce mode, record the median and P95 backend response times for authenticated endpoints. The auth middleware adds two async database calls per request (user cache upsert and group claim mapping). If median response time increases by more than 20% after enabling enforce mode, scale `control-center` replicas before proceeding. See [operational-runbooks.md](operational-runbooks.md) §4 for full monitoring guidance.
