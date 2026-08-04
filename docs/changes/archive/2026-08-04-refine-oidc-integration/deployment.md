# Deployment: Refine OIDC Integration

## 1. Environment Variables

### New Variables

| Variable | Description | Secret | Default |
|----------|-------------|--------|---------|
| `SUPER_ADMIN_ENABLED` | Enables super admin login path. Must be `true` for the super admin auth pipeline to be active. In production, start `true` during bootstrap, then set `false` after OIDC is verified. | | `false` |
| `SUPER_ADMIN_USERNAME` | Super admin username. Bootstrapped into the `super_admin_credentials` table on first launch. Immutable after initial seeding — changing the env var after bootstrap requires a direct DB update. Production must override the default. | | `admin` |
| `SUPER_ADMIN_PASSWORD_HASH` | Argon2id or bcrypt hash of the super admin password. Bootstrapped into `super_admin_credentials` on first launch. Production must override. Never set a plaintext password — always supply a pre-computed hash. Generate with: `python -m app.cli hash-password`. | ✓ | _(none — required for super admin)_ |

### Deprecated Variables

| Variable | Status | Replacement |
|----------|--------|-------------|
| `OIDC_PROVIDER_URL` | Deprecated | DB-stored `issuer_url` in `IdentityProviderConfig`. Only read during the one-time `identity.yaml` → DB migration. |
| `IDENTITY_PROVIDER_TYPE` | Deprecated | DB-stored `provider_type` in `IdentityProviderConfig`. Only read during the one-time migration. |
| `OIDC_ISSUER_URL` | Deprecated | DB-stored `issuer_url`. Only read during the one-time migration. |
| `OIDC_JWKS_URI` | Deprecated | Discovered automatically via `.well-known/openid-configuration` at the configured `issuer_url`. |
| `OIDC_CLIENT_ID` | Deprecated | DB-stored `client_id` in `IdentityProviderConfig`. Only read during the one-time migration. |
| `OIDC_CLIENT_SECRET` | Deprecated | DB-stored `encrypted_client_secret` in `IdentityProviderConfig`. Only read during the one-time migration. |
| `OIDC_REALM` | Deprecated | Absorbed into `issuer_url` path. Only read during the one-time migration. |
| `OIDC_AUDIENCE` | Deprecated | Absorbed into `scopes` / `claim_mappings` JSON configuration. Only read during the one-time migration. |
| `OIDC_AGENT_CLIENT_PREFIX` | Deprecated — Keycloak-specific | No direct replacement. Agent identity provider is configured as a separate DB entry with its own `issuer_url` and `client_id`. |

### Configuration Precedence (Post-Change)

After this change, the resolution order for identity provider settings is:

1. Database (`IdentityProviderConfig` rows) — **source of truth**
2. Environment variables — only read during the one-time migration; ignored at runtime after migration completes
3. `config/identity.yaml` — only read during the one-time migration; **not read at runtime after migration completes**

A missing `config/identity.yaml` after the migration has run is expected and does not cause an error.

---

## 2. Infrastructure Changes

### Docker Compose

- **Keycloak dependency made optional.** The `control-center` service no longer hard-depends on `keycloak` for production deployments. The `depends_on` block for `keycloak` should be removed or made conditional based on whether the deployment uses bundled Keycloak.
- **Dev/demo flow unchanged.** When `SUPER_ADMIN_ENABLED=true` and no OIDC config exists in the database, the setup wizard still provisions the bundled Keycloak and writes its config to the database. The `keycloak` service remains required for dev/demo and bundled deployments.
- Add the three super admin environment variables to the `control-center` service definition.
- Remove the `config/identity.yaml` bind mount from the `control-center` service — the file is no longer read at runtime after migration.

### Kubernetes / Helm

- Add `SUPER_ADMIN_ENABLED`, `SUPER_ADMIN_USERNAME`, and `SUPER_ADMIN_PASSWORD_HASH` to the Control Center Deployment env block. Source `SUPER_ADMIN_PASSWORD_HASH` from a Kubernetes Secret — never from a ConfigMap.
- Remove the `OIDC_*` environment variables from the Control Center Deployment after the one-time migration is verified. They serve no purpose post-migration and their presence may cause confusion about which config source is authoritative.
- If `config/identity.yaml` was mounted as a ConfigMap volume, remove the volume and volume mount after the migration is verified.
- The bundled Keycloak StatefulSet/Deployment may be omitted for production deployments that use external OIDC providers exclusively. Retain it only for dev/demo environments.

---

## 3. Migration Steps

Execute these steps in order. Do not proceed to the next step until the current step is verified. All steps apply to both Docker Compose and Kubernetes/Helm deployments.

### Step 1 — Apply Database Migrations

Run `alembic upgrade head` against the target database using the `DATABASE_URL` connection string from the `backend/` directory.

This migration will:
- Restructure the `identity_provider_configs` table: add `provider_scope`, `display_name`, `issuer_url`, `encrypted_client_secret`, `scopes`, `claim_mappings`, `is_enabled` columns; rename `oidc_provider_url` → `issuer_url` and `client_secret` → `encrypted_client_secret`; remove `realm_name`, `audience`, `is_setup_complete`, `setup_completed_at`, `setup_completed_by_id` columns; update `provider_type` enum from `keycloak_bundled | keycloak_external | azure_entraid` to `oidc_generic | keycloak | azure_entraid`
- Add `user_provider_configured` and `agent_provider_configured` columns to `identity_provider_setup_state`
- Create the `identity_provider_config_audits` table
- Create the `super_admin_credentials` table

**Verification:** Query `alembic_version` to confirm the latest revision is active. Query `information_schema.columns` to confirm the new columns exist in `identity_provider_configs` and `identity_provider_setup_state`, and the `super_admin_credentials` table exists.

### Step 2 — Deploy New Backend Code

Deploy the updated `control-center` container image (and any other backend service images that changed).

**Before starting, ensure:**
- `SUPER_ADMIN_ENABLED`, `SUPER_ADMIN_USERNAME`, and `SUPER_ADMIN_PASSWORD_HASH` are set in the Control Center environment
- All deprecated `OIDC_*` variables are still present — they are needed for the one-time migration in Step 3
- `config/identity.yaml` is accessible from the Control Center container — needed for the one-time migration in Step 3

Start services in the standard order (Control Center first). The Bootstrap Service will:
- Seed the `super_admin_credentials` table from `SUPER_ADMIN_USERNAME` and `SUPER_ADMIN_PASSWORD_HASH` on first launch
- Initialize the OIDC Provider Registry with an empty cache if no DB config exists yet

**Verification:** Control Center `/health` endpoint responds. Check logs for "Super admin credentials seeded" and "OIDC Provider Registry initialized" messages.

### Step 3 — Run One-Time Identity.YAML → DB Migration

The Bootstrap Service detects the presence of `config/identity.yaml` at startup and automatically migrates its contents to the database. No manual command is needed — the migration runs once when the Control Center starts with the YAML file present.

The migration:
- Reads the existing provider config from `config/identity.yaml`
- Creates one or two `IdentityProviderConfig` rows in the database (user scope and optionally agent scope)
- Encrypts the client secret using `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` before storing
- Sets `user_provider_configured=true` (and `agent_provider_configured=true` if an agent provider was configured) in `IdentityProviderSetupState`
- Logs a completion message indicating the number of provider configs migrated
- Does **not** delete `config/identity.yaml` — the file remains as a backup

**Verification:** Query the `identity_provider_configs` table — at least one row should exist with `provider_scope='user'`. Confirm `encrypted_client_secret` is populated (not plaintext). Check Control Center logs for "identity.yaml migration complete" message.

### Step 4 — Verify Migrations

Confirm all migrated data is correct:

- Query `identity_provider_configs` and verify `issuer_url`, `client_id`, and `is_enabled=true` match the pre-migration values
- Query `super_admin_credentials` and verify `username` matches `SUPER_ADMIN_USERNAME` and `is_enabled=true`
- Query `identity_provider_setup_state` and verify `user_provider_configured=true`
- Check that the Control Center can reach the configured OIDC provider's `.well-known/openid-configuration` endpoint (logs show "OIDC discovery successful" for each enabled provider)

### Step 5 — Deploy Frontend

Deploy the updated `web-ui` container image. The new frontend:
- Reads available identity providers from `GET /api/v1/system/identity-providers`
- Renders the super admin login form alongside OIDC login buttons when super admin is enabled
- Provides the System Config admin page for managing identity provider configurations
- Includes OIDC test and test-login UI elements

**Verification:** Frontend application loads in a browser. The login page should show both a username/password form (super admin) and OIDC login buttons (if OIDC providers are configured).

### Step 6 — Verify Super Admin Login

Log in to the platform using the super admin credentials:

- Navigate to the login page
- Enter the super admin username and password
- Confirm successful login and access to the full platform UI
- Verify the System Config page is accessible and shows the identity provider configuration section

**Verification:** Super admin can access all admin pages. Check Control Center logs for "super admin authentication successful" message with `last_login_at` timestamp updated.

### Step 7 — Configure OIDC Providers via UI

Using the super admin session, configure identity providers through the System Config UI:

- Navigate to System Config → Identity Providers
- For each provider (user and/or agent), enter the issuer URL, client ID, client secret, scopes, and optional claims mapping
- Use the "Test Connection" button to validate OIDC discovery reachability before saving
- Use the "Test Login" button to perform a full authentication flow and verify claims response
- Save each provider configuration

**Verification:** Each provider config is persisted with `is_enabled=true`. OIDC discovery and test login complete without errors. `identity_provider_config_audits` table contains audit entries for each create/update/test operation.

### Step 8 — Verify OIDC Login

Log out of the super admin session and verify OIDC authentication:

- From the login page, click the OIDC login button for the configured user identity provider
- Complete the OIDC authentication flow (redirect to provider, authenticate, redirect back)
- Confirm successful login and access to the platform with the appropriate role/permissions
- If an agent identity provider is configured separately, verify agent token exchange works (trigger an agent execution and confirm the agent identity token is resolved correctly)

**Verification:** OIDC-authenticated user can access all permitted platform features. Agent execution completes with the correct identity token injection. Control Center logs show "OIDC authentication successful" with the correct provider and claims.

### Step 9 — Disable Super Admin (Optional)

Once OIDC authentication is confirmed working for all required identity paths:

- Set `SUPER_ADMIN_ENABLED=false` in the Control Center environment (or toggle via the System Config UI if supported)
- Restart the Control Center service
- Confirm the super admin login form no longer appears on the login page
- Confirm that attempting super admin credentials on the login endpoint returns a clear rejection message
- Confirm OIDC login continues to work

**Verification:** Only OIDC login buttons appear on the login page. Super admin credentials are rejected even when correct. All OIDC-authenticated users can still access the platform.

---

## 4. Rollback Procedure

Use this procedure if the deployment fails and the platform must be restored to its pre-change state. Identify the failure point before taking action — not all steps are needed for every failure.

### General Rollback Steps

1. **Stop affected services.** Bring down the `control-center` and `web-ui` containers/pods. Leave PostgreSQL and Redis running.

2. **Restore `config/identity.yaml` usage.** If the YAML file was removed or its mount was removed:
   - Ensure `config/identity.yaml` is present and accessible from the Control Center container
   - Re-add the bind mount (Docker Compose) or ConfigMap volume mount (Kubernetes) for `config/identity.yaml`
   - Restore the deprecated `OIDC_*` environment variables to their pre-deployment values

3. **Revert database migrations.** Run `alembic downgrade` to the pre-deployment revision. This will:
   - Drop the `super_admin_credentials` table — the super admin bootstrap data is lost; it will be re-seeded if the change is re-deployed
   - Drop the `identity_provider_config_audits` table — all audit history is lost
   - Revert `identity_provider_configs` to its pre-change schema (restore removed columns, drop new columns, rename columns back, revert enum values)
   - Drop `user_provider_configured` and `agent_provider_configured` from `identity_provider_setup_state`
   - Any DB-stored OIDC configs created via the UI or migration are lost; the `config/identity.yaml` file is the restoration source

4. **Redeploy previous image tags.** Roll `control-center` and `web-ui` back to the last known-good images. Remove the `SUPER_ADMIN_*` environment variables.

5. **Validate rollback.** Confirm:
   - Control Center `/health` responds
   - OIDC login works using `config/identity.yaml` as the config source
   - The setup wizard appears if `config/identity.yaml` is absent and no DB config exists

### Failure Point: Database Migration (Step 1)

If the Alembic migration fails before completing:
- Run `alembic downgrade` to the last known-good revision to clean up partial schema changes
- Fix the migration issue (check for enum conflicts, constraint violations, or data type mismatches)
- Re-run `alembic upgrade head`
- If the migration failed due to unrecoverable data corruption, restore the database from the pre-deployment backup and re-run the migration

### Failure Point: Backend Startup (Step 2)

If the Control Center fails to start after deployment:
- Check logs for "super admin credentials" errors — ensure `SUPER_ADMIN_PASSWORD_HASH` is a valid bcrypt/argon2id hash, not a plaintext password
- Check logs for "OIDC Provider Registry" errors — the registry should initialize with an empty cache if no DB config exists
- If the failure is a code-level bug, roll back to the previous `control-center` image and fix the issue before retrying

### Failure Point: Identity.YAML Migration (Step 3)

If the one-time migration from `config/identity.yaml` to database fails:
- Check that `config/identity.yaml` is valid and readable by the Control Center process
- Check that `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` is set (needed for client secret encryption)
- The migration is idempotent — if it fails after creating partial DB rows, delete the affected `IdentityProviderConfig` rows and restart the Control Center to retry
- If the migration cannot complete, the system falls back to reading `config/identity.yaml` directly — the rollback is partial and the platform remains operational

### Failure Point: OIDC Login (Step 8)

If OIDC login fails after configuration:
- Do not disable the super admin (Step 9) until OIDC is confirmed working
- Use super admin access to correct the OIDC provider configuration via the System Config UI
- Use the "Test Connection" and "Test Login" buttons to validate without affecting other users
- If the OIDC provider is unreachable, the system shows a clear error on the login page (not a 500)
- If OIDC is misconfigured and the super admin is already disabled, follow the operational runbook to re-enable super admin via environment variable

---

## 5. Master Deployment Update Instructions

After this change is implemented and deployed, update the following master deployment documents:

| File | Update |
|------|--------|
| `docs/master/deployment/environment-variables.md` | **OIDC / Identity section:** Replace with new **Super Admin Bootstrap** section listing `SUPER_ADMIN_ENABLED`, `SUPER_ADMIN_USERNAME`, `SUPER_ADMIN_PASSWORD_HASH`. Mark the entire OIDC / Identity section as deprecated — all OIDC vars are now sourced from the database. Add a note about the one-time migration only reading these vars during bootstrap. Update the configuration precedence section: Database → Environment (migration only) → YAML (migration only). |
| `docs/master/deployment/services.md` | **Service Inventory table:** Update Control Center role description to mention OIDC Provider Registry and super admin auth. **Keycloak entry:** Note that Keycloak is optional in production — only required for bundled/dev deployments. **Data Access Boundaries:** No change (Control Center remains sole DB owner). |
| `docs/master/deployment/configuration-files.md` | Mark `config/identity.yaml` as deprecated for runtime. Add a note that after the one-time DB migration, this file is no longer read. It remains useful as a migration source and disaster-recovery reference. |
| `docs/master/deployment/first-time-deployment.md` | **Step 4 (Configure the Identity Provider):** Restructure. Add guidance for the three-tier bootstrap: super admin first, then configure OIDC via UI, then disable super admin. **Step 5 (Set Environment Variables):** Add the three `SUPER_ADMIN_*` variables to the list of required variables. Mark `OIDC_*` variables as "migration only" — needed for the one-time identity.yaml migration, not for ongoing operation. **Step 7 (Deploy Backend Services):** Note that bundled Keycloak startup is now conditional — only needed for dev/demo or when `SUPER_ADMIN_ENABLED=true` with no OIDC DB config. **Step 10 (Seed Platform Configuration):** Replace the identity provider provisioning step with: super admin login → configure OIDC providers via System Config UI → verify OIDC login → optionally disable super admin. |
| `docs/master/deployment/rollback.md` | Add a new **Change-Specific Rollback: Refine OIDC Integration** section following the existing pattern. Reference the four failure-point scenarios from Section 4 above. |
| `docs/master/deployment/database-migrations.md` | Add a new row to the Migration History table for the `refine-oidc-integration` migration revision. Note the destructive nature (column renames, drops, enum value changes on `identity_provider_configs`) and the prerequisites (config/identity.yaml must be present for the one-time data migration). |
