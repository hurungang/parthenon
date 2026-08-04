# Deployment: API Key MCP Hub Access

## 1. Environment Variables

This change introduces three new environment variables to support API key authentication on the Communication Hub and secure key storage on Control Center. No existing variables are removed or changed.

### New Environment Variables

| Variable | Service | Description | Secret | Default |
|----------|---------|-------------|--------|---------|
| `API_KEY_HASH_SECRET` | CC | Application-level pepper/secret mixed into the API key hash to prevent precomputed hash attacks. Must be a high-entropy random string (min 32 chars). Changing this value invalidates all previously issued API keys — they will fail authentication and must be reissued. | ✓ | — |
| `CH_API_KEY_AUTH_ENABLED` | CH | Feature flag to enable or disable API key authentication on the Communication Hub. When `false`, only existing mTLS certificate authentication is accepted; API key requests are rejected with a 403. Set to `true` to enable the dual authentication path. | — | `false` |
| `API_KEY_PREFIX` | CC | Configurable prefix string prepended to generated API keys for visual identification. The prefix is stored in `agent_api_keys.key_prefix` and returned in the clear-text key at creation time. | — | `phn_sk_` |

### Variables Used but Unchanged

These existing variables are relevant to the API key authentication flow but require no modification:

| Variable | Service | Role in API Key Flow |
|----------|---------|---------------------|
| `CONTROL_CENTER_URL` | CH | Already set; CH uses this to call CC's `POST /internal/auth/validate-api-key` endpoint (mTLS-secured via existing service certificate) |
| `SERVICE_BOOTSTRAP_KEY` | CH | Already set; used for CH→CC mTLS certificate bootstrapping — no change |
| `CREDENTIAL_VAULT_KEY` | CC | Already set; used to decrypt the bound agent identity's OAuth token during key validation — no change |

### Deployment Checklist

Before deploying:
- Generate a cryptographically random `API_KEY_HASH_SECRET` (at least 32 characters) and store it in your secrets manager
- Set `CH_API_KEY_AUTH_ENABLED=true` on the Communication Hub (start with `false` if you want to deploy the middleware in audit mode first)
- `API_KEY_PREFIX` is optional — omit to use the default `phn_sk_`

---

## 2. Infrastructure Changes

### No New Services

No new containers, pods, volumes, networks, or ports are introduced. This change extends existing services only.

### Communication Hub Changes

The Communication Hub (`communication-hub`) gains:
- **API Key Validator middleware** — Intercepts requests bearing `Authorization: Bearer <key>` or `?apiKey=<key>` query parameter. Calls CC `POST /internal/auth/validate-api-key` via existing mTLS channel to validate the key and resolve identity/permissions. External agents never receive identity tokens — CH holds them internally for MCP request proxying only.
- **`load_skills` system tool** — New entry in the system tool router (`system____load_skills`). Resolves accessible skills from the bound role, including full tool definitions with input/output schemas and `updated_at` timestamps. Supports optional `since` parameter for incremental sync.
- **Modified MCP endpoint** — The existing MCP endpoint now accepts two authentication methods: mTLS certificate (internal agents, unchanged) and API key (external agents, new). Both paths converge at the same proxy layer with identical permission enforcement.

### Control Center Changes

The Control Center (`control-center`) gains:
- **API Key Management Service** — CRUD endpoints for Platform Administrators to create, list, and revoke API keys. Create returns the clear-text key once; the key is hashed before storage.
- **Internal validation endpoint** `POST /internal/auth/validate-api-key` — mTLS-secured, caller-scoped to `communication_hub` only. Validates the key hash, resolves the bound identity → role → permissions chain, decrypts the identity token, and returns the full resolved context to CH.
- **Audit logging** — API key creation and revocation events are logged to the existing audit service. Authentication events (success/failure) are logged via `ApiKeyUsageLog` records.

### Database Changes

- **New table**: `agent_api_keys` — stores hashed key values, bound identity/role, status, timestamps
- **New table**: `api_key_usage_logs` — append-only audit log of key usage events
- **Data backfill**: `skills.updated_at` — one-time backfill for existing skills with `NULL` or default timestamps

---

## 3. Migration Steps

Deploy this change in the following order. Each step must complete successfully before proceeding to the next.

### Step 1 — Prepare Environment Variables

Before deploying any new service images:

- **Generate `API_KEY_HASH_SECRET`**: Create a cryptographically random 32+ character string. Store it securely (Docker secret or Kubernetes Secret). This must be in place before the Control Center starts with the updated code — the first API key creation will fail if this secret is missing.
- **Set `CH_API_KEY_AUTH_ENABLED`**: Start with `false` for the initial deployment to verify middleware loads correctly without affecting production traffic. Set to `true` only after verifying the API key creation flow works end-to-end (Step 5).
- **Set `API_KEY_PREFIX`** (optional): If you want a custom prefix, set it now. The prefix cannot be changed for existing keys after deployment — only newly created keys will use the new prefix.

### Step 2 — Run the Alembic Migration

Stop the Control Center (or scale its Deployment to zero replicas in Kubernetes) to prevent concurrent writes during migration. Leave PostgreSQL, Redis, Agent Runtime, and Communication Hub running.

Execute the migration from the `backend/` directory:

```
python -m alembic upgrade head
```

The migration:
- Creates the `agent_api_keys` table with columns: `id`, `name`, `key_hash`, `key_prefix`, `agent_identity_id`, `agent_role_id`, `status` (active/revoked enum), `created_at`, `last_used_at`, `created_by`
- Creates the `api_key_usage_logs` table with columns: `id`, `api_key_id`, `action` (validate/load_skills/tool_call enum), `tool_name`, `ip_address`, `timestamp`, `success`
- Creates the `agent_api_key_status_enum` and `api_key_usage_action_enum` PostgreSQL enum types
- Creates a unique constraint on `(agent_identity_id, agent_role_id, status)` for active keys — prevents duplicate active keys per identity-role pair

Verify the migration completed:

```
python -m alembic current
```

Confirm the output shows the latest revision containing the API key migration.

### Step 3 — Backfill `skills.updated_at`

Run the one-time data backfill for existing skills with `NULL` or default `updated_at` values. The backfill sets `updated_at = created_at` for any skill where `updated_at IS NULL` or `updated_at < created_at`:

```
python -m app.scripts.backfill_skill_updated_at
```

If no backfill script exists, execute the SQL directly against the database:

```sql
UPDATE skills SET updated_at = created_at WHERE updated_at IS NULL OR updated_at < created_at;
```

Verify the backfill:

```sql
SELECT COUNT(*) FROM skills WHERE updated_at IS NULL;
```

The result must be `0`. This backfill is critical — the `since` parameter on `load_skills` will not correctly filter skills with `NULL` timestamps.

### Step 4 — Deploy Updated Backend Services

Deploy the updated service images **in strict dependency order**. Each service must reach a healthy state before the next is started:

1. **Control Center** — Deploy the updated CC image. Confirm the `/health` endpoint responds. Verify the startup log shows:
   - `API_KEY_HASH_SECRET` is set (log: `API key hash secret configured` or similar)
   - New `agent_api_keys` table is accessible (no `relation does not exist` errors)
   - Certificate Authority is healthy (existing functionality — no change)

   After health check passes, verify the new internal endpoint is accessible from the CH's network namespace (but do not expose it externally — it must be mTLS-only).

2. **Communication Hub** — Deploy the updated CH image. Confirm the `/health` endpoint responds. Verify the startup log shows:
   - `CH_API_KEY_AUTH_ENABLED` value (should be `false` for now)
   - API Key Validator middleware loaded (log: `API key validator registered` or similar)
   - `load_skills` system tool registered (log: `system tool 'load_skills' registered` or similar)
   - Certificate bootstrap completed successfully to Control Center
   - No errors from the new middleware on startup

3. **Agent Runtime** — No code changes. Confirm the `/health` endpoint responds. Certificate bootstrap completes as normal.

If any service fails to start with a validation or connection error, resolve the issue before proceeding — do NOT skip to later steps.

### Step 5 — Verify API Key Creation Flow

With services running and `CH_API_KEY_AUTH_ENABLED=false`:

1. Log in to the Web UI as a Platform Administrator.
2. Navigate to the API Key management page.
3. Create a new API key: select an existing agent identity and agent role.
4. Confirm the clear-text key is displayed once (for copy). Verify the key starts with `phn_sk_` (or your custom prefix).
5. Close the dialog. Confirm the key appears in the API key list with status `active`.
6. Verify the key value is NOT visible in the list (only the prefix and masked remainder should be shown).
7. Verify the `agent_api_keys` table contains a row with the correct `key_hash`, `key_prefix`, `agent_identity_id`, and `agent_role_id`.

### Step 6 — Enable API Key Authentication

After verifying the creation flow works:

1. Set `CH_API_KEY_AUTH_ENABLED=true` on the Communication Hub.
2. Restart the Communication Hub to pick up the flag change.
3. Verify CH startup shows `CH_API_KEY_AUTH_ENABLED=true` and the middleware is active.
4. Test external agent authentication:
   - Use the API key created in Step 5 with an MCP client or `curl`
   - Call `load_skills` to verify skill discovery works
   - Verify the response includes `updated_at` timestamps on each skill
   - Call a permitted tool to verify proxy execution works
5. Test rejection of invalid keys:
   - Use a malformed key (wrong prefix or wrong format) — expect 401
   - Use a revoked key (revoke the key from Step 5, then attempt auth) — expect 401
6. Verify existing internal agent (mTLS cert) authentication still works — agent runtime can connect, discover skills, and invoke tools as before.

### Step 7 — Deploy Updated Frontend

Deploy the updated Web UI containing the API Key management pages. Verify:
- The frontend application loads in a browser
- The OIDC login flow completes successfully
- The API Key management page is accessible under the admin area
- Create, list, and revoke operations work through the UI

### Step 8 — Smoke Test

1. Create an API key for a known agent identity with a role that has skill permissions.
2. Use an MCP client to connect to the Communication Hub MCP endpoint with the API key.
3. Call `load_skills` — confirm skills are returned with `updated_at` timestamps.
4. Call `load_skills` with a `since` parameter set to a future timestamp — confirm an empty list is returned.
5. Call a permitted tool through the MCP client — confirm the tool executes and returns results.
6. Revoke the API key from the Web UI.
7. Attempt to connect with the revoked key — confirm 401 authentication error.
8. Verify existing internal agent workflows continue to function (no regression).

---

## 4. Rollback Procedure

Use this procedure if the deployment fails and the platform must be restored to its pre-deployment state.

### Trigger Conditions

Initiate rollback if any of the following occur after deploying this change:

- Control Center fails to start due to `API_KEY_HASH_SECRET` issues or database migration errors
- Communication Hub fails to start with new middleware errors
- Existing internal agent (mTLS cert) authentication is broken or degraded
- MCP tool calls from internal agents return unexpected 403/401 errors
- The `agent_api_keys` table migration caused constraint violations or data issues
- API key authentication is failing for valid keys or accepting revoked keys

### Step R1 — Stop Affected Services

Stop the Communication Hub and Control Center. Leave PostgreSQL, Redis, Agent Runtime, and any other services running.

For Docker Compose: stop the `communication-hub` and `control-center` containers individually.  
For Kubernetes: scale down the Communication Hub and Control Center Deployments to zero replicas.

### Step R2 — Roll Back Database Migrations (Conditional)

Only execute this step if the `agent_api_keys` migration must be reversed.

Run from the `backend/` directory:

```
python -m alembic downgrade -1
```

> **Migration reversal behaviour**: The `downgrade()` function drops the `agent_api_keys` and `api_key_usage_logs` tables and removes the two new enum types (`agent_api_key_status_enum`, `api_key_usage_action_enum`). Any API keys created during the deployment window will be permanently lost. PostgreSQL enum types cannot be dropped if any column references them — the downgrade handles column drops before enum drops.

If the downgrade fails due to dependent objects, manually confirm that only the tables and enums from this migration are affected before retrying.

**Do not downgrade if the issue is only with the application layer** (e.g., `CH_API_KEY_AUTH_ENABLED=false` resolves the problem). The new tables can safely remain with no active code referencing them.

Verify:

```
python -m alembic current
```

Confirm the output shows the previous revision ID (the pre-deployment head).

### Step R3 — Revert `skills.updated_at` Backfill (Conditional)

Only needed if the backfill itself caused issues. The backfill sets `updated_at = created_at` for skills with `NULL` timestamps — this is non-destructive and typically does not need reversal. If reversal is required, the previous `NULL` values cannot be recovered without a backup.

Skip this step in most cases.

### Step R4 — Remove New Environment Variables

Remove the following from the deployment environment:
- `API_KEY_HASH_SECRET` from Control Center
- `CH_API_KEY_AUTH_ENABLED` from Communication Hub
- `API_KEY_PREFIX` from Control Center (if set)

### Step R5 — Redeploy Previous Service Images

Roll back to the last known-good image tags:

1. **Control Center** — Deploy the previous image. Remove `API_KEY_HASH_SECRET` and `API_KEY_PREFIX` from its environment. Confirm the `/health` endpoint responds.
2. **Communication Hub** — Deploy the previous image. Remove `CH_API_KEY_AUTH_ENABLED` from its environment. Confirm the `/health` endpoint responds.
3. **Agent Runtime** — Confirm the `/health` endpoint responds (no changes needed, but verify no drift).
4. **Web UI** — Deploy the previous Web UI image (if an updated frontend was deployed).

Start services in standard order: Control Center → Agent Runtime → Communication Hub → Web UI. Wait for each health check to pass before starting the next.

### Step R6 — Validate Rollback

1. Confirm all service health endpoints respond.
2. Confirm the database schema version matches the expected pre-deployment revision (if migration was rolled back).
3. Verify internal agent (mTLS cert) MCP connections work — connect, discover skills, invoke a tool.
4. Verify the Web UI loads and existing admin pages function normally.
5. Verify API Key management pages are no longer accessible (no UI for them) or return appropriate errors.
6. Run the standard smoke test from the first-time deployment runbook to confirm full platform functionality.

### Rollback Guardrails

- Do NOT leave `API_KEY_HASH_SECRET` set on Control Center after rollback — the previous version does not expect it and may fail on unexpected environment variables (though typical behavior is to ignore unknown vars).
- Do NOT leave `CH_API_KEY_AUTH_ENABLED=true` after rollback — the previous CH image does not have the API key middleware and will ignore the flag, but leaving it set creates confusion for future deployments.
- Do NOT downgrade the database migration if any API keys were created during the deployment window that need to be preserved (e.g., for testing). Consider keeping the tables and just rolling back the application code.
- Do NOT grant direct database access to Communication Hub or Agent Runtime during rollback — all database operations go through Control Center.
- If rollback was triggered by a `skills.updated_at` backfill issue, restore the `skills` table from the most recent pre-deployment backup.

---

## 5. Master Deployment Update Instructions

After this change is implemented and verified, update the following files in `docs/master/deployment/`:

### `docs/master/deployment/environment-variables.md`

**New section: "API Key Authentication"** — Add after the existing Communication Hub section:

- `API_KEY_HASH_SECRET` (CC, secret) — Application-level pepper for API key hashing. Min 32 chars. Changing invalidates all existing keys.
- `CH_API_KEY_AUTH_ENABLED` (CH) — Feature flag to enable/disable API key auth on Communication Hub. Default `false`. Set to `true` only after verifying the key creation flow.
- `API_KEY_PREFIX` (CC) — Configurable prefix for generated API keys. Default `phn_sk_`. Prefix is shown in clear-text at creation and stored in `agent_api_keys.key_prefix`.

**Update Communication Hub section** — Add `CH_API_KEY_AUTH_ENABLED` to the existing Communication Hub variable table. Document that CH now supports dual authentication paths (mTLS certs and API keys) and serves `load_skills` as a system tool for external agents.

### `docs/master/deployment/database-migrations.md`

Add a new row to the Migration History table:

- **Revision**: The generated Alembic revision ID
- **File**: The migration filename
- **Description**: "API Key MCP Hub Access — creates `agent_api_keys` and `api_key_usage_logs` tables for API key management and audit logging. Creates `agent_api_key_status_enum` and `api_key_usage_action_enum` PostgreSQL enum types. Unique constraint on `(agent_identity_id, agent_role_id)` for active keys."
- **Tables Added / Modified**: `agent_api_keys` (created), `api_key_usage_logs` (created), `skills` (no schema change; `updated_at` data backfill applied separately)

Add a note to the Notes section:
- Migration is **additive** — no existing tables, columns, or constraints are modified or removed.
- The `downgrade()` drops both new tables and enum types. Any API keys created during the deployment window are permanently lost on downgrade.
- A separate one-time data backfill is required for `skills.updated_at` (sets `NULL` values to `created_at`). This is a data operation, not a schema migration — it must be verified before enabling the `since` parameter on `load_skills`.
- Only Control Center connects to the database; Communication Hub and Agent Runtime consume API key validation results via the Control Center internal API and are unaffected by the schema changes.

### `docs/master/deployment/services.md`

**Update Communication Hub row** in the Service Inventory table:
- Extend the role description to include: "Accepts MCP connections from external third-party agents authenticated via API key (Bearer token or query parameter) in addition to internal Agent Runtime agents authenticated via mTLS certificates. Hosts the `load_skills` system tool for external agent skill discovery with incremental sync support."

**Add API Key Authentication row** to the Data Access Boundaries table:
- Communication Hub still has no direct database access; API key validation is performed by calling Control Center's internal API via existing mTLS channel.

**Add to Control Center Internal API Boundary Model** — Under "Caller-specific deployment notes" table:
- Communication Hub's allowed internal API surface is extended to include `POST /internal/auth/validate-api-key` — this allows CH to validate API keys against Control Center. The endpoint is caller-scoped to `communication_hub` only.

### `docs/master/deployment/rollback.md`

Add a new "Change-Specific Rollback: API Key MCP Hub Access" section following the existing pattern. Include:
- Trigger conditions: CC startup failure, CH middleware errors, internal agent auth regression, invalid/revoked key handling failure
- Steps R1–R6 as documented in Section 4 above
- Conditional downgrade note: migration is additive — tables can safely remain if only application code is rolled back
- Rollback guardrails: do not leave env vars set, do not grant DB access to CH/AR, restore `skills` from backup if backfill caused issues

### `docs/master/deployment/first-time-deployment.md`

- **Step 5 (Set Environment Variables)**: Add `API_KEY_HASH_SECRET` to the "Pay special attention to" list — note that it must be set before the first API key is created.
- **Step 7 (Deploy Backend Services)**: In the Communication Hub startup description, add a note that `CH_API_KEY_AUTH_ENABLED` defaults to `false` on first deployment and can be enabled after verifying the platform is operational.
- **Step 10 (Seed Platform Configuration)**: No change needed — API key creation is part of ongoing administration, not initial provisioning.
- **Step 11 (Smoke Test)**: Add an optional verification: "If API key authentication is enabled, create an API key for an agent identity and verify external MCP connectivity."

### No updates needed for

- `configuration-files.md` — No new configuration files introduced
- `operational-runbooks.md` — Addressed in `docs/changes/api-key-mcp-hub/operations.md` (separate change doc)
- `github-pages-showcase.md` — No changes to the showcase site
