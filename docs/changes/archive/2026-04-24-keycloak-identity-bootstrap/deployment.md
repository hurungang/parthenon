# Deployment Changes — keycloak-identity-bootstrap

This document describes all deployment-facing changes introduced by the `keycloak-identity-bootstrap` change, and provides ordered runbooks for upgrading an existing Parthenon instance, performing a fresh installation, and rolling back if the upgrade fails.

---

## 1. New Environment Variables

All new variables are optional. When `config/identity.yaml` is present, values written to that file take precedence over hard-coded defaults; environment variables always take precedence over both. Sensitive variables must be supplied via Docker secrets or a `.env` file that is excluded from source control — they must never appear in plain-text configuration files committed to a repository.

| Variable | Purpose | Required | Sensitive | Default |
|---|---|---|---|---|
| `IDENTITY_PROVIDER_TYPE` | Selects the active identity provider mode. Accepted values: `keycloak_bundled`, `keycloak_external`, `azure_entraid`. | Optional | No | None — setup wizard or CLI prompts on first run |
| `OIDC_PROVIDER_URL` | Base URL of the OIDC provider (e.g., the Keycloak realm URL). Previously used only by the API; now also readable from `config/identity.yaml`. | Optional | No | `http://keycloak:8080/realms/parthenon` when bundled Keycloak is active |
| `OIDC_CLIENT_ID` | OAuth2 client ID for the Parthenon Platform API as registered in the identity provider. | Optional | No | Resolved and written to `config/identity.yaml` by the setup wizard or CLI |
| `OIDC_CLIENT_SECRET` | OAuth2 client secret for the Parthenon Platform API. | Optional | **Yes** | Resolved and stored encrypted in the database by the setup wizard or CLI |
| `OIDC_REALM` | Keycloak realm name. Relevant for `keycloak_bundled` and `keycloak_external` provider types only. | Optional | No | Resolved and written to `config/identity.yaml` by the setup wizard or CLI |
| `OIDC_AUDIENCE` | Expected `aud` claim value used during JWT token validation. Previously set via `JWT_AUDIENCE`; that name continues to work as a fallback. | Optional | No | Resolved from the identity provider configuration during provisioning |
| `KEYCLOAK_ADMIN` | Username for the bundled Keycloak admin account. Only relevant when `IDENTITY_PROVIDER_TYPE=keycloak_bundled`. | Optional | No | None — must be supplied before the bundled Keycloak container first starts |
| `KEYCLOAK_ADMIN_PASSWORD` | Password for the bundled Keycloak admin account. Only relevant when `IDENTITY_PROVIDER_TYPE=keycloak_bundled`. | Optional | **Yes** | None — must be supplied before the bundled Keycloak container first starts |

### Notes on Configuration Precedence

The Platform API resolves OIDC settings in the following priority order (highest to lowest):

1. Environment variable
2. Value in `config/identity.yaml`
3. Hard-coded default

This means that if `OIDC_CLIENT_ID` is set in the environment it overrides any value the setup wizard wrote to the YAML file. Teams that manage configuration through environment variables exclusively can leave `config/identity.yaml` absent — the Platform API treats a missing YAML file as an empty configuration and does not raise an error.

---

## 2. Infrastructure Changes

### 2.1 New Docker Compose Service — `keycloak`

| Attribute | Value |
|---|---|
| Image | `quay.io/keycloak/keycloak:24` |
| Container name | `parthenon-keycloak` |
| Internal port | `8080` (HTTP) |
| Host-mapped port | `8080` → `8080` (accessible at `http://localhost:8080` from the host) |
| Admin credentials | Read from `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` environment variables |
| Health check | Polls the Keycloak `/health/ready` HTTP endpoint |
| Network | `parthenon` (same bridge network as all other services) |

The `api` service gains a `depends_on` health-check dependency on `keycloak` so that the Platform API does not start until Keycloak is ready.

### 2.2 New Docker Compose Volume — `keycloak_data`

| Attribute | Value |
|---|---|
| Volume name | `keycloak_data` |
| Mount point inside container | `/opt/keycloak/data` |
| Purpose | Persists Keycloak realm, client, and user data across container restarts |

This volume is declared alongside the existing `postgres_data`, `redis_data`, `prometheus_data`, and `loki_data` volumes in `docker-compose.yml`.

### 2.3 New File — `infra/keycloak/parthenon-realm.json`

A Keycloak realm export file used for development-time realm pre-import. When present, it is mounted into the Keycloak container at startup and Keycloak imports it automatically. It is not used in production — the Bootstrap Service provisions the realm via the Keycloak Admin REST API instead.

### 2.4 New File — `config/identity.yaml`

A YAML configuration file at the repository root that stores resolved, non-sensitive OIDC settings (provider type, realm, provider URL, client ID, audience). This file is written automatically by the setup wizard and by the CLI. It is safe to commit to source control. Client secrets are never written to this file — they are stored encrypted in the database.

### 2.5 Updated Start and Stop Scripts

The platform start and stop scripts are updated to include the `keycloak` service in their lifecycle operations. When `IDENTITY_PROVIDER_TYPE` is not `keycloak_bundled`, the scripts skip starting the Keycloak container automatically.

### 2.6 Port Allocation Summary

The following host port is newly consumed by this change and must be free before the stack starts:

| Port | Protocol | Service | Purpose |
|---|---|---|---|
| `8080` | HTTP | `parthenon-keycloak` | Keycloak admin console and OIDC endpoints |

---

## 3. Ordered Migration Steps (Existing Installation)

Follow these steps in order when upgrading an existing Parthenon instance. Do not proceed to the next step until the current step is verified. Take a full database backup before beginning.

**Step 1 — Take a pre-deployment database backup.**
Export a full logical backup of the Parthenon PostgreSQL database. Record the current Alembic revision from the `alembic_version` table — you will need this revision identifier if a rollback is required.

**Step 2 — Stop all Parthenon application services.**
Bring down the Platform API and all dependent backend services. Leave PostgreSQL, Redis, and the observability stack (OTEL Collector, Jaeger, Prometheus, Loki) running. Stopping application services before applying schema changes prevents concurrent writes from encountering a partially migrated schema.

**Step 3 — Pull the new container images.**
Pull the updated Platform API and frontend images, and pull `quay.io/keycloak/keycloak:24`. Verify the image digests match the release artifacts before proceeding.

**Step 4 — Add the new environment variables.**
Add `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` to the Docker secrets or `.env` file. Do not set `IDENTITY_PROVIDER_TYPE`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REALM`, or `OIDC_AUDIENCE` at this stage — the setup wizard will populate them. If you are integrating an external provider (Keycloak or Azure EntraID) and already know all values, you may set them now.

**Step 5 — Run the Alembic migration.**
Apply the new database migrations using `alembic upgrade head` against the running PostgreSQL instance. This migration adds the `IdentityProviderConfig` table, the `IdentityProviderSetupState` table, and the `idp_subject` column to the `User` table. After the migration completes, verify that the `alembic_version` table reflects the new revision and that all three schema objects are present.

**Step 6 — Start the Keycloak service.**
Bring up only the `keycloak` container. Wait for its health check to report healthy before proceeding. Confirm the Keycloak admin console is reachable at `http://localhost:8080` from the host. Confirm that the `keycloak_data` volume has been created.

**Step 7 — Start the Platform API.**
Bring up the `api` container. Confirm its `/health` endpoint responds. At this point, because no identity provider has been provisioned yet, the Platform API will return a `NOT_CONFIGURED` setup state from `GET /api/v1/setup/identity-status`. This is expected.

**Step 8 — Run the identity provider setup.**
Complete setup using one of the two supported paths:

- **Setup Wizard (UI):** Start the frontend service and open the application in a browser. The first-run redirect guard will redirect all navigation to `/setup`. Follow the wizard to select a provider, enter credentials, and complete provisioning. The wizard calls the Platform API, which provisions the Keycloak realm and client automatically, then writes resolved settings to `config/identity.yaml` and the database.

- **CLI (headless):** Invoke `python -m app.cli` inside the `api` container, passing all required provisioning parameters as flags. The CLI delegates to the same Bootstrap Service that the wizard uses. On success it prints a summary and exits with code 0.

After this step, `GET /api/v1/setup/identity-status` must return a `CONFIGURED` state.

**Step 9 — Start all remaining services.**
Bring up all other backend services (in the order defined in the First-Time Deployment runbook: `mcp-hub`, `skill-engine`, `agent-engine`, `scheduling-engine`, `notification-engine`, `communication-hub`, `agent-gateway`), then the nginx gateway, then the frontend. Confirm all health checks pass.

**Step 10 — Verify the OIDC login flow.**
Open the application in a browser. Confirm the login page redirects to Keycloak (or the configured external provider). Log in with a valid account and confirm the session is established and the dashboard loads.

**Step 11 — Run the smoke test.**
Execute the standard smoke test from Step 11 of the First-Time Deployment runbook to confirm all components are functioning end-to-end.

---

## 4. First-Time Setup Steps (New Installation)

Follow the updated First-Time Deployment runbook in `docs/master/deployment/first-time-deployment.md`. The keycloak-identity-bootstrap change adds the following modifications to that runbook:

**Before Step 1:** Set `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` in the environment configuration. Confirm that host port `8080` is free.

**Between Step 1 and Step 2 (new step):** Start the Keycloak container alongside PostgreSQL and Redis. Wait for all three health checks to pass before proceeding to run Alembic migrations.

**After Step 3 (migrations) and before the original Step 4:** Confirm that the `IdentityProviderConfig` table, `IdentityProviderSetupState` table, and the `idp_subject` column on `User` are all present in the database.

**Replace original Step 4 (Configure the OIDC Provider):** For bundled Keycloak, do not manually register a client. Instead, start the Platform API, then use the setup wizard or CLI (as described in Migration Step 8 above) to drive automated provisioning. The Bootstrap Service creates the realm and client automatically. For external providers (Keycloak or Azure EntraID), manual registration in the external provider is still required before running the wizard or CLI — note the issued `client_id` and `client_secret` and have them ready to enter during setup.

All other steps in the First-Time Deployment runbook remain unchanged.

---

## 5. Rollback Procedure

Use this procedure if the upgrade fails and the platform must be restored to the state before the `keycloak-identity-bootstrap` change was applied.

**Step 1 — Identify the failure point.**
Determine at which migration step the failure occurred. Check service health endpoints, container logs, and the `alembic_version` table to establish what was and was not applied.

**Step 2 — Stop all application services.**
Bring down the Platform API and all dependent backend services. Stop and remove the Keycloak container. Leave PostgreSQL and Redis running.

**Step 3 — Revert the database schema.**
Run `alembic downgrade` to the revision that was recorded in the pre-deployment backup step. This removes the `IdentityProviderConfig` table, the `IdentityProviderSetupState` table, and the `idp_subject` column from the `User` table. Verify that the `alembic_version` table reflects the pre-deployment revision after the downgrade completes.

**Step 4 — Remove the YAML config file.**
Delete `config/identity.yaml` if it was written during the failed upgrade. Leaving the file in place would cause the previous API version to encounter an unrecognised configuration file on startup.

**Step 5 — Remove new environment variables.**
Remove `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`, and any of `IDENTITY_PROVIDER_TYPE`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REALM` from the Docker secrets or `.env` file. Retain `OIDC_PROVIDER_URL` and `OIDC_AUDIENCE` if they were set before this change — restore their pre-change values if they were modified.

**Step 6 — Remove the Keycloak volume.**
Remove the `keycloak_data` Docker volume. Because no production traffic has passed through the bundled Keycloak at this stage, there is no data to preserve. If the installation was partially used and users were created in Keycloak, assess whether their accounts need to be retained before removing the volume.

**Step 7 — Restore and start the previous images.**
Redeploy the previous Platform API and frontend image tags. Start services in the standard order defined in the First-Time Deployment runbook and confirm all health checks pass.

**Step 8 — Validate rollback.**
Re-run the standard smoke test to confirm the platform is operating correctly at the pre-upgrade state. Confirm the database schema version and confirm the OIDC login flow completes successfully using the previous provider configuration.

**Step 9 — Post-mortem.**
Document the failure point, root cause, and any data or state changes made during the failed upgrade and rollback before re-attempting the upgrade.

---

## 6. What to Update in `docs/master/deployment/`

The following master deployment documents must be updated after this change is merged:

| Document | Required Updates |
|---|---|
| `environment-variables.md` | Add the eight new variables (`IDENTITY_PROVIDER_TYPE`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REALM`, `OIDC_AUDIENCE` updated entry, `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`) to the **OIDC / Identity** section. Mark `OIDC_CLIENT_SECRET`, `KEYCLOAK_ADMIN_PASSWORD` as sensitive. Add a note that `OIDC_AUDIENCE` supersedes the legacy `JWT_AUDIENCE` name. |
| `services.md` | Add a row for the `keycloak` service (`parthenon-keycloak`) to the Service Inventory table with its role described as "Bundled OpenID Connect identity provider; manages the Parthenon realm, clients, and user accounts; Admin REST API used by the Bootstrap Service during provisioning". Update the Service Dependencies diagram to show that `api` depends on `keycloak`. |
| `first-time-deployment.md` | Insert a new sub-step in Step 1 to start the Keycloak container alongside PostgreSQL and Redis. Replace Step 4 (Configure the OIDC Provider) with a step that distinguishes bundled Keycloak provisioning (fully automated via wizard or CLI) from external provider registration (manual). Add a note after Step 5 (Set Environment Variables) that `config/identity.yaml` is written automatically and should not be hand-edited for OIDC settings managed by the Bootstrap Service. |
| `rollback.md` | Insert a new consideration in Step 3 (Restore Database State) noting that `alembic downgrade` for this change removes the `IdentityProviderConfig` and `IdentityProviderSetupState` tables and the `idp_subject` column. Insert a new consideration in Step 4 (Revert Environment Changes) to remove Keycloak-specific variables and delete `config/identity.yaml`. Add a note in Step 2 (Stop Failed Services) to stop and remove the Keycloak container before restoring. |
| `README.md` | Update the Quick Reference section to note that Keycloak is now an infrastructure dependency alongside PostgreSQL and Redis when `IDENTITY_PROVIDER_TYPE=keycloak_bundled`, and that host port `8080` must be free. Add a note that `config/identity.yaml` is the secondary configuration source for identity settings, with environment variables taking highest precedence. |
