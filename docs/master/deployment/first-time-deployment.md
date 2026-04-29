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
- Host port `8080` is free (required by the bundled Keycloak container)

In Docker Compose, bring up the `postgres`, `redis`, and `keycloak` services first. In Kubernetes, apply or install the `postgres`, `redis`, and `keycloak` Helm components. If using an external identity provider (`keycloak_external` or `azure_entraid`), omit the Keycloak service.

Confirm connectivity:
- PostgreSQL is accepting connections on the configured host and port
- Redis is accepting connections on the configured host and port
- When using bundled Keycloak: Keycloak admin console is reachable at `http://localhost:8080` and the `/health/ready` endpoint returns healthy
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

## Step 4 — Configure the Identity Provider

How this step is completed depends on the selected identity provider type.

**Bundled Keycloak (`IDENTITY_PROVIDER_TYPE=keycloak_bundled`)**

Do not manually register a client. The Bootstrap Service provisions the Keycloak realm and client automatically during the setup wizard or CLI run in Step 10. Proceed to Step 5 without setting `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REALM`, or `OIDC_AUDIENCE` — the wizard or CLI will populate these. Confirm that the JWKS endpoint (`http://keycloak:8080/realms/parthenon/protocol/openid-connect/certs`) will be accessible from the Platform API container's network.

**External Keycloak (`IDENTITY_PROVIDER_TYPE=keycloak_external`)**

Manually register the Parthenon Platform API as a confidential OAuth2 client in the external Keycloak instance:
- Set the allowed redirect URI to `{PLATFORM_API_BASE_URL}/api/v1/auth/callback`
- Enable the `client_credentials` and `authorization_code` grant types
- Set the token audience to the intended value for `OIDC_AUDIENCE`
- Note the issued `client_id` and `client_secret` — these will be required when running the setup wizard or CLI in Step 10

Confirm that the JWKS endpoint (`OIDC_JWKS_URI`) is accessible from the Platform API container's network.

**Azure EntraID (`IDENTITY_PROVIDER_TYPE=azure_entraid`)**

Register the application in the Azure portal and follow the same pattern as External Keycloak above: note the `client_id`, `client_secret`, and tenant-specific OIDC/JWKS URLs before proceeding.

---

## Step 5 — Set Environment Variables

Populate all environment variables listed in [environment-variables.md](environment-variables.md) for every service.

For sensitive values (all variables marked **secret** in the reference), use:
- **Docker Compose**: Docker secrets or a `.env` file excluded from source control
- **Kubernetes**: Kubernetes Secrets referenced by the `secrets.yaml` Helm template

Pay special attention to:
- `OIDC_ISSUER_URL` — must exactly match the `iss` claim in issued tokens, including any trailing slash
- `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` — must be set before the first MCP session is created; changing this key after credentials are stored requires re-encrypting all stored credentials
- `OTEL_SERVICE_NAME` — set uniquely per container so telemetry can be filtered per service

> **Note on `config/identity.yaml`:** For bundled Keycloak, OIDC settings (`OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REALM`, `OIDC_AUDIENCE`, `OIDC_PROVIDER_URL`) are written automatically to `config/identity.yaml` by the setup wizard or CLI (Step 10). Do not hand-edit this file for settings managed by the Bootstrap Service. Environment variables always take precedence over `config/identity.yaml` values — teams managing configuration exclusively via environment variables can omit the YAML file.

---

## Step 6 — Deploy the OTEL Collector

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

## Step 7 — Deploy Backend Services

Start backend services in the following strict order. Each service must reach a healthy state before the next is started.

1. `platform-api` — Verify the `/health` endpoint responds through its port before proceeding
2. `mcp-hub` — Depends on `platform-api` for internal API calls
3. `skill-engine` — Depends on `platform-api` and `mcp-hub`
4. `agent-engine` — Depends on `platform-api`, `mcp-hub`, and `skill-engine`
5. `scheduling-engine` — Depends on `platform-api` and `agent-engine`
6. `notification-engine` — Depends on `platform-api` and `mcp-hub` (for MCP tool registration)
7. `communication-hub` — Depends on `redis` and `platform-api`
8. `agent-gateway` — Depends on `agent-engine` and `communication-hub`

If any service fails to start, check its logs for connection errors to PostgreSQL, Redis, or the OIDC JWKS endpoint before attempting to restart it.

---

## Step 8 — Deploy the API Gateway

Start the `nginx` reverse proxy with routing rules configured to point to the deployed backend services.

Confirm:
- Health endpoints for `platform-api` and `agent-gateway` respond through the nginx proxy
- WebSocket path `/ws/` is proxied to `communication-hub` with appropriate timeout settings (`proxy_read_timeout` must be set high enough for long-lived connections)
- `/api/` is proxied to `platform-api`
- `/gateway/` is proxied to `agent-gateway`
- TLS is terminated at nginx in production deployments

---

## Step 9 — Deploy the Web UI

Start the `web-ui` container with the API Gateway base URL configured.

Confirm:
- The frontend application loads in a browser
- The frontend resolves the Platform API via the configured base URL
- The OIDC login flow initiates correctly (redirect to identity provider)

---

## Step 10 — Seed Platform Configuration

Perform initial platform setup via the admin UI or the Platform API directly:

1. **Complete identity provider provisioning.** After the Platform API starts, it will return a `NOT_CONFIGURED` state from `GET /api/v1/setup/identity-status`. Use one of the two supported paths to provision the identity provider:
   - **Setup Wizard (UI):** Start the frontend service. The first-run redirect guard redirects all navigation to `/setup`. Follow the wizard to select a provider, enter credentials, and complete provisioning. On success, `GET /api/v1/setup/identity-status` returns `CONFIGURED`.
   - **CLI (headless):** Run `python -m app.cli` inside the `api` container, passing all required provisioning parameters as flags. Exits with code 0 on success.
2. Call `POST /api/v1/setup/init` (public endpoint) to create the first administrator role and identity — this only needs to be done once
3. **Seed the Permission Engine.** Execute the role-seeding script (or CLI command) against the database. The seed creates the built-in `platform_admin` role with unrestricted policy statements, a `PlatformUser` record for the designated administrator, and assigns the `platform_admin` role via a `UserRole` record. Optionally set `PERMISSION_ENGINE_SEED_ADMIN_EMAIL` before running the script to pre-select the admin email without interactive prompting — remove the variable afterwards. Verify by querying the `roles`, `platform_users`, and `user_roles` tables. See [operational-runbooks.md](operational-runbooks.md) §3 for full details.
4. Log in to the Web UI using the administrator identity
5. Register at least one MCP server via the MCP Hub admin page
6. Trigger a tool sync for the registered MCP server to populate the tool catalogue
7. Define initial roles and permissions appropriate for the deployment
8. Configure at least one notification channel if notifications are required

---

## Step 11 — Smoke Test

Execute a complete end-to-end test to confirm all components are functioning:

1. Create an agent type via the admin UI bound to an available skill or SOP
2. Initiate a conversation with the agent through the Web UI Chat page
3. Submit a test prompt and confirm a response is received
4. Verify that an OTEL trace for the interaction appears in the configured Jaeger backend
5. Verify that structured log entries for the interaction appear in the Loki log aggregation backend
6. Confirm the conversation record is visible in the Conversation History page

If all six checks pass, the deployment is complete.

> **Permission Engine latency baseline:** Before switching the Permission Engine from audit mode to enforce mode, record the median and P95 backend response times for authenticated endpoints. The auth middleware adds two async database calls per request (user cache upsert and group claim mapping). If median response time increases by more than 20% after enabling enforce mode, scale `platform-api` replicas before proceeding. See [operational-runbooks.md](operational-runbooks.md) §4 for full monitoring guidance.
