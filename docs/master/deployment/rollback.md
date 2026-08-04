# Rollback Runbook

Use this runbook when a deployment fails and the platform must be restored to its last known-good state. Follow each step in order. Document all actions taken for the post-mortem in Step 7.

---

## Step 1 — Identify the Failure Point

Before taking any action, determine exactly where the deployment failed.

Check the following in order:
- Service health endpoints for all deployed services — identify which service is unhealthy or unreachable
- OTEL traces for any requests that were processed — trace data may reveal which component produced errors
- Container or pod logs for the most recently deployed services — look for startup failures, connection errors, or unhandled exceptions
- Database state — confirm whether Alembic migrations ran successfully (check `alembic_version` table)

Record the failure point before proceeding. This informs which of the following steps are needed.

---

## Step 2 — Stop Failed Services

Bring down only the services involved in or affected by the failure. Leave PostgreSQL and Redis running unless the failure is in the data layer itself.

For Docker Compose: stop the affected containers individually rather than bringing down the entire stack. If the `keycloak` container was started as part of this deployment, stop and remove it as well before proceeding — do not leave it running against a partially migrated database.

For Kubernetes: scale down the affected Deployments to zero replicas. Do not delete the Deployments unless the entire release needs to be rolled back.

Stopping services cleanly prevents active connections from leaving orphaned state in Redis or PostgreSQL.

---

## Step 3 — Restore Database State

This step is only required if Alembic migrations were applied during the failed deployment and caused schema issues or data integrity problems.

Run `alembic downgrade` to the migration revision that was in place before the deployment began. The target revision identifier should be taken from the pre-deployment `alembic_version` record, which should have been noted before starting the deployment.

> **Keycloak identity bootstrap migrations:** If the `keycloak-identity-bootstrap` change was the deployment being rolled back, `alembic downgrade` will remove the `IdentityProviderConfig` table, the `IdentityProviderSetupState` table, and the `idp_subject` column from the `User` table. Verify that all three schema objects are absent after the downgrade completes.

> **Passthrough sessions migration (`5c2910c238a8`):** If this is the deployment being rolled back, note that `alembic downgrade -1` will **not** remove the `passthrough` value from the `mcp_session_auth_type_enum` type — PostgreSQL does not support removing enum values. The enum value will remain in the database, which is harmless: the rolled-back application code will simply not expose or accept `passthrough` as a valid auth type. No additional cleanup is required for this migration.

> **Agent Runtime Security Segregation migration (`385c4ae051f6`):** If this is the deployment being rolled back, **do not roll back the migration** — the new columns on `agent_identities` (`encrypted_refresh_token`, `last_token_refresh_at`, `token_status`) are nullable, so the previous code version operates correctly without them. The four new tables (`agent_instance_certificates`, `certificate_revocation_entries`, `token_refresh_logs`, `certificate_validation_logs`) can remain; they cause no harm. If a full schema rollback is required anyway, `alembic downgrade -1` drops all four tables and the three columns; any agent instance certificates and CA state stored in those tables will be lost and must be re-provisioned after re-deploying.

If data was corrupted and downgrade alone is insufficient, restore from the most recent database backup taken before the deployment. Confirm the restored schema revision matches the target revision.

If no schema changes were made during the failed deployment, skip this step.

---

## Step 4 — Revert Environment Changes

Review any environment variable or secret changes made during the failed deployment:

- If new OIDC client credentials were created in the identity provider for this deployment, decide whether to retain or delete them based on whether they were partially used
- Do not leave orphaned OIDC clients in the identity provider — they represent unused credential exposure
- If the `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` was changed, restore the previous value — changing the key invalidates all previously encrypted MCP session credentials
- Remove any Keycloak-specific variables added during this deployment: `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`, `IDENTITY_PROVIDER_TYPE`, `OIDC_REALM`. Restore `OIDC_PROVIDER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and `OIDC_AUDIENCE` to their pre-deployment values if they were modified.
- Delete `config/identity.yaml` if it was written during the failed deployment. Leaving this file in place would cause the previous API version to encounter an unrecognised configuration source on startup.
- Remove the `keycloak_data` Docker volume if the Keycloak container was started during this deployment. If no production traffic passed through the bundled Keycloak and no user accounts were created, the volume contains no data worth preserving.
- Revert all service environment variables and secrets to the values used by the last known-good image tags

---

## Step 5 — Redeploy Previous Image Tags

Roll all services back to the last known-good container image tags.

For Docker Compose: update the `image` values in the compose file (or override file) to the previous tags and bring the services back up.

For Kubernetes/Helm: run `helm rollback` to the previous release revision, or re-run `helm upgrade` with `--reuse-values` and explicitly set `image.tag` to the previous values in `values.yaml`.

Start services in the same order defined in the First-Time Deployment runbook (Step 8), waiting for each to reach a healthy state before starting the next.

---

## Step 6 — Validate Rollback

Re-run the smoke test from Step 12 of the First-Time Deployment runbook to confirm the platform is operating correctly at the previous state:

1. Confirm all service health endpoints respond
2. Confirm the database schema version matches the expected pre-deployment revision
3. Initiate a test agent interaction end-to-end and confirm a response is received
4. Confirm telemetry (OTEL trace) is visible for the test interaction

If all checks pass, the rollback is complete. Do not re-attempt the new deployment until Step 7 is complete.

---

## Step 7 — Post-Mortem

Document the following before re-attempting the deployment:

- The step at which the failure occurred (from Step 1 analysis)
- The root cause of the failure
- Any data changes or state modifications made during the failed deployment and rollback
- Changes required to the deployment procedure or configuration to prevent recurrence

Update the relevant deployment documentation if the runbook or environment variable reference contributed to the failure.

Only re-attempt the deployment after the root cause is understood and the fix is in place.

---

## Change-Specific Rollback: Agent Runtime with Gateway

Use this section when rolling back the **Implement Agent Runtime with Gateway** deployment. Execute steps R1–R5 in order after completing Steps 1–2 of the general procedure above.

### Trigger Conditions

Initiate this rollback if any of the following occur after deploying this change:

- Platform API health check fails and cannot be restored by restart
- `agent-session-worker` fails to dequeue sessions and the Redis queue (`AGENT_SESSION_QUEUE_NAME`) length grows unbounded
- LangGraph dependency issues or state machine errors prevent session execution
- Database migration `df2225d787c5` caused unexpected constraint violations or data loss
- The Agent Gateway (Communication Hub) returns 5xx errors for all inbound lifecycle requests

### Step R1 — Revert Communication Hub

Deploy the previous `communication-hub` image. Remove `AGENT_GATEWAY_BASE_URL` and `AGENT_GATEWAY_REQUEST_TIMEOUT_SECONDS` from its environment.

**Completion condition:** Communication Hub health check passes; WebSocket messaging for existing conversations is restored.

### Step R2 — Stop Agent Session Worker

Stop and remove the `agent-session-worker` container.

**Completion condition:** No worker containers are running. Sessions remaining in the Redis list at `AGENT_SESSION_QUEUE_NAME` will stay queued; discard or replay them after the incident is resolved.

### Step R3 — Revert Platform API

Deploy the previous `control-center` image. Remove all `AGENT_RUNTIME_*`, `AGENT_SESSION_*`, `AGENT_PERMISSION_*`, and `AGENT_GATEWAY_*` environment variables.

**Completion condition:** Platform API health check passes; existing endpoints respond normally.

### Step R4 — Database Rollback (conditional)

Run only if migration `df2225d787c5` must be reversed:

Run `alembic downgrade -1` to revert the last migration.

> **Warning — data loss:** This will drop the `agent_role`, `agent_role_sop`, `agent_role_skill`, `agent_identity`, and `agent_session` tables and revert `agent_type` column changes. Any data entered via the new agent admin UI will be permanently lost. Confirm with the team before executing.

**Completion condition:** `alembic current` reports the previous migration ID. The `agent_role` table does not exist. The `agent_type` table has its original columns (`sop_id`, `identity_subject`, `system_prompt`, `mode`).

### Step R5 — Flush Permission Cache

Remove all Agent Permission Manager cache keys from Redis to prevent stale data from affecting a subsequent redeployment attempt:

Use `redis-cli --scan --pattern 'agentperm:*'` to list matching keys, then delete each key. Confirm afterwards that no keys matching `agentperm:*` exist in Redis.

**Completion condition:** No keys matching `agentperm:*` exist in Redis.

---

## Stateless Services

Stateless MCP servers (such as `mcp-demo-app`) can be rolled back without a database downgrade. The full rollback procedure is:

1. **Stop and remove the container** — Bring down the stateless service container. All in-memory state (token cache, JWKS cache) is discarded on shutdown.
2. **Remove the Hub server record** — Delete the service's slug entry from the MCP Hub via the Hub admin API or directly in the database. This removes any registered tools from the Hub's tool registry.
3. **Remove the docker-compose.yml service block** — Revert the compose file change that added the service.
4. **Remove environment variables** — Delete all service-specific variables from the deployment environment.
5. **Optionally remove the Keycloak client** — If the rollback is permanent, delete the service's client from the relevant Keycloak realm to eliminate unused credential exposure. If a future retry is planned, the client may be retained.
6. **Verify no impact on remaining services** — Confirm all remaining services are healthy and that the Hub no longer lists the removed server or its tools.

No database downgrade is required for stateless MCP servers. No other services are affected.

---

## Change-Specific Rollback: Service Segregation Security Audit

Use this section when rolling back the caller-specific Control Center internal API allowlist deployment. Execute steps S1–S5 after completing Steps 1–2 of the general procedure above.

### Trigger Conditions

Initiate this rollback if any of the following occur during or after enforce activation:

- sustained failures on legitimate agent execution or communication workflows
- persistent mTLS handshake failures across internal service calls
- high deny-event volume on expected allowlisted routes
- revocation-check instability causing broad fail-closed call rejection

### Step S1 — Downgrade Policy Mode to Audit

Set `INTERNAL_API_POLICY_MODE` from `enforce` to `audit` on Control Center while keeping deny-event logging enabled.

**Completion condition:** Internal workflows recover and deny telemetry continues.

### Step S2 — Revert Caller Service Images (if needed)

Roll Agent Runtime and Communication Hub back to last known-good image tags that match the previous allowlist contract.

**Completion condition:** Service health is stable and known-good call patterns resume.

### Step S3 — Roll Back Allowlist Version

Revert Control Center to the previous approved allowlist policy bundle version.

**Completion condition:** Deny rates normalize for legitimate internal traffic while non-contract traffic remains denied.

### Step S4 — Repair Certificate and Identity State (conditional)

If certificate mismatch, renewal failure, or identity mapping regression is confirmed:

1. rotate affected service certificates
2. re-bootstrap caller service identity
3. validate revocation checks and trust chain health

**Completion condition:** mTLS and identity validation pass consistently for both caller services.

### Step S5 — Stabilize and Re-qualify

Run in audit mode until a clean validation window is completed, then re-attempt enforce cutover using the operational runbook.

**Completion condition:** Zero unresolved allowlist drift and acceptable deny-event baseline.

### Rollback Guardrails

- do not disable service certificate validation
- do not disable deny-event telemetry during rollback
- do not grant direct database access to Agent Runtime or Communication Hub

---

## Change-Specific Rollback: Agent Execution Guardrails

Use this section when rolling back the `add-agent-execution-guardrails` deployment. Execute steps G1-G5 after completing Steps 1-2 of the general procedure above.

### Trigger Conditions

Initiate this rollback if any of the following occur after guardrail rollout:

- unexpected guardrail stops on known-good workloads
- conversational sessions hard-stop solely because token threshold is reached
- missing or corrupted guardrail stop metadata in status or log paths
- missing or corrupted conversational token-usage or continuation metadata
- cross-service contract mismatch causing execution failures

### Step G1 — Disable Runtime Guardrail Enforcement Flags

Disable newly introduced Agent Runtime guardrail enforcement flags while keeping baseline execution available.

**Completion condition:** New guardrail-triggered stops cease and baseline execution paths recover.

### Step G2 — Revert Communication Hub Guardrail Forwarding Flags

Revert Communication Hub guardrail forwarding and passthrough toggles to the last known-good behavior.

**Completion condition:** Session outcome routing is stable and metadata forwarding no longer regresses traffic.

### Step G3 — Revert Control Center Guardrail Policy and Persistence Toggles

Revert Control Center guardrail policy-enforcement and persistence toggles to the previous stable mode.

**Completion condition:** Policy payloads and persistence paths match last known-good expectations.

### Step G4 — Redeploy Last Known-Good Versions in Reverse Rollout Order

Redeploy services in this order:
1. Agent Runtime
2. Communication Hub
3. Control Center

**Completion condition:** All three services are healthy and contract-compatible at prior stable versions.

### Step G5 — Stabilization Validation

Run direct and delegated smoke sessions and verify:

- guardrail stop metadata is present and parseable where expected
- conversational sessions no longer hard-stop due to token threshold alone
- no service acquires direct database access during rollback

### Rollback Guardrails

- do not grant direct database access to Agent Runtime or Communication Hub
- do not remove stop-outcome visibility needed for audit and triage
- keep stop-reason field compatibility stable to prevent downstream parsing regressions

---

## Change-Specific Rollback: API Key MCP Hub Access

Use this section when rolling back the **API Key MCP Hub Access** deployment. Execute steps R1–R6 after completing Steps 1–2 of the general procedure above.

### Trigger Conditions

Initiate this rollback if any of the following occur after deploying this change:

- Control Center fails to start due to `API_KEY_HASH_SECRET` issues or database migration errors
- Communication Hub fails to start with new middleware errors
- Existing internal agent (mTLS cert) authentication is broken or degraded
- MCP tool calls from internal agents return unexpected 403/401 errors
- The `agent_api_keys` table migration caused constraint violations or data issues
- API key authentication is failing for valid keys or accepting revoked keys

### Step R1 — Stop Affected Services

Stop the Communication Hub and Control Center. Leave PostgreSQL, Redis, Agent Runtime, and any other services running.

**Completion condition:** Communication Hub and Control Center containers/Deployments are stopped.

### Step R2 — Roll Back Database Migrations (Conditional)

Only execute this step if the `agent_api_keys` migration must be reversed. If the issue is only in the application layer (e.g., `CH_API_KEY_AUTH_ENABLED=false` resolves the problem), skip to Step R4 — the new tables can safely remain.

Run from the `backend/` directory: `alembic downgrade -1`

> **Migration reversal behaviour:** The `downgrade()` function drops the `agent_api_keys` and `api_key_usage_logs` tables and removes the two new enum types (`agent_api_key_status_enum`, `api_key_usage_action_enum`). Any API keys created during the deployment window will be permanently lost.

**Completion condition:** `alembic current` reports the previous revision ID (pre-deployment head).

### Step R3 — Revert `skills.updated_at` Backfill (Conditional)

Only needed if the backfill itself caused issues. The backfill sets `updated_at = created_at` for skills with `NULL` timestamps — this is non-destructive and typically does not need reversal. If reversal is required, the previous `NULL` values cannot be recovered without a backup. Skip this step in most cases.

### Step R4 — Remove New Environment Variables

Remove the following from the deployment environment:
- `API_KEY_HASH_SECRET` from Control Center
- `CH_API_KEY_AUTH_ENABLED` from Communication Hub
- `API_KEY_PREFIX` from Control Center (if set)

**Completion condition:** None of the three variables remain in the environment for any service.

### Step R5 — Redeploy Previous Service Images

Roll back to the last known-good image tags in strict order:

1. **Control Center** — Deploy the previous image. Remove `API_KEY_HASH_SECRET` and `API_KEY_PREFIX` from its environment. Confirm the `/health` endpoint responds.
2. **Communication Hub** — Deploy the previous image. Remove `CH_API_KEY_AUTH_ENABLED` from its environment. Confirm the `/health` endpoint responds.
3. **Agent Runtime** — Confirm the `/health` endpoint responds (no changes needed, but verify no drift).
4. **Web UI** — Deploy the previous Web UI image (if an updated frontend was deployed).

**Completion condition:** All services report healthy at previous image versions.

### Step R6 — Validate Rollback

1. Confirm all service health endpoints respond.
2. Confirm the database schema version matches the expected pre-deployment revision (if migration was rolled back).
3. Verify internal agent (mTLS cert) MCP connections work — connect, discover skills, invoke a tool.
4. Verify the Web UI loads and existing admin pages function normally.
5. Verify API Key management pages are no longer accessible or return appropriate errors.
6. Run the standard smoke test from the first-time deployment runbook to confirm full platform functionality.

**Completion condition:** All six checks pass.

### Rollback Guardrails

- Do NOT leave `API_KEY_HASH_SECRET` set on Control Center after rollback — the previous version does not expect it.
- Do NOT leave `CH_API_KEY_AUTH_ENABLED=true` after rollback — the previous CH image does not have the API key middleware and will ignore the flag, but leaving it set creates confusion for future deployments.
- Do NOT downgrade the database migration if any API keys were created during the deployment window that need to be preserved (e.g., for testing). Consider keeping the tables and just rolling back the application code.
- Do NOT grant direct database access to Communication Hub or Agent Runtime during rollback — all database operations go through Control Center.
- If rollback was triggered by a `skills.updated_at` backfill issue, restore the `skills` table from the most recent pre-deployment backup.

---

## Change-Specific Rollback: Production-Ready Configuration

Use this section when rolling back the **production-ready-configuration** deployment. Execute steps R1–R5 after completing Steps 1–2 of the general procedure above.

### Trigger Conditions

Initiate this rollback if any of the following occur after deploying this change:

- Control Center fails to start with a validation error because Keycloak admin credentials (`KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`) are missing from the runtime environment
- Control Center startup log shows `Keycloak configuration invalid` or a validation failure for an unreachable infrastructure dependency (PostgreSQL, Redis, Keycloak)
- The consolidated setup command was run incorrectly or skipped entirely, leaving the identity provider unprovisioned
- Agent Runtime or Communication Hub fail to start due to Control Center reachability validation failures
- Configuration source logging (`SERVICE_BOOTSTRAP_SOURCE_LOG`) reveals a misconfigured infrastructure connection

### Step R1 — Stop Failed Services

Stop all three backend services (Control Center, Agent Runtime, Communication Hub). Leave PostgreSQL, Redis, and Keycloak running.

**Completion condition:** All three backend service containers/Deployments are stopped.

### Step R2 — Revert to Previous Service Images

Roll all three backend services back to the last known-good image tags. Start them in standard order (Control Center → Agent Runtime → Communication Hub).

**Completion condition:** All three services report healthy at previous image versions.

### Step R3 — Restore Keycloak Admin Credentials to Control Center

The previous version expects `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` to be present in the Control Center environment and will auto-provision the Keycloak realm at startup. Restore these variables to the Control Center's environment or Secrets references.

**Completion condition:** The Control Center startup log shows `provisioning Keycloak realm` (not `validating Keycloak configuration`) and the service starts successfully.

### Step R4 — Remove New Environment Variables (Optional)

If the rollback is clean, remove the new per-component infrastructure variables that are specific to this change from the deployment environment:
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (revert to `DATABASE_URL` only)
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB_INDEX` (revert to `REDIS_URL` only)
- `OIDC_ISSUER_URL`, `OIDC_CLIENT_SECRET` (if newly added)
- `SERVICE_BOOTSTRAP_SOURCE_LOG` (if set)

These variables are harmless if left in place — the previous version ignores them — but removing them keeps the environment clean for future deployments.

### Step R5 — Validate Rollback

Re-run the standard smoke test from Step 12 of the First-Time Deployment runbook to confirm the platform is operating correctly at the previous state. Verify:

1. All service health endpoints respond
2. The Keycloak realm and client are accessible
3. Authentication and authorization flows work correctly
4. A test agent interaction completes end-to-end

**Completion condition:** All four checks pass.

### Rollback Guardrails

- Do NOT leave Keycloak admin credentials on the Control Center after a successful deployment — this defeats the security purpose of this change. Remove them after confirming the new version is stable.
- Do NOT revert to individual ad-hoc scripts (`scripts/init-local-dev.py`, `scripts/fix-agent-client.py`, etc.) after the consolidated setup tool has been deployed — maintain the setup tool as the single entry point.
- Do NOT re-enable Keycloak auto-provisioning at CC startup as a permanent workaround — fix the setup command flow instead.

---

## Change-Specific Rollback: Namespaced Resource Types

Use this section when rolling back the **namespace-resource-types** deployment. Execute steps R1–R5 after completing Steps 1–2 of the general procedure above.

### Trigger Conditions

Initiate this rollback if any of the following occur after deploying this change:

- Permission Engine returns 403 for legitimate requests that previously succeeded
- Wildcard policy evaluation (`*::*`, `module::*`) fails to match expected modules
- Policy CRUD endpoints reject valid namespaced resource types with validation errors
- Legacy flat values appear unmigrated in `policy_statements` or `policy_resources` after the upgrade ran

### Step R1 — Stop Control Center

Stop the Control Center container or scale its Deployment to zero replicas. Leave PostgreSQL, Redis, Agent Runtime, Communication Hub, and all other services running.

**Completion condition:** Control Center is stopped, preventing any writes against a partially migrated dataset.

### Step R2 — Roll Back the Database Migration

Run the Alembic downgrade to revert the data migration from the `backend/` directory:

```
python -m alembic downgrade -1
```

> **Downgrade behaviour:** The `downgrade()` function reverses all 1:1 renames and transforms `*::*` back to `*`. For consolidation reversals, `agent::trails` maps back to `conversation` (not `result`) and `system::permissions` maps back to `permissions` (not the other four consolidated types). Any policy statements or resources created after the migration using the new namespaced format will be **left unchanged** — these were not present before the upgrade and the downgrade is a best-effort reversal, not a magical undo.

Verify the downgrade:

```
python -m alembic current
```

**Completion condition:** Output shows the previous revision (the pre-upgrade head).

### Step R3 — Deploy Previous Backend and Frontend Images

Redeploy the previous Control Center, Agent Runtime, Communication Hub, and Web UI images (the versions in use before this change was deployed).

For Docker Compose: update image tags to the previous versions and bring services up.
For Kubernetes: run `helm rollback` or re-apply with the previous image tags.

**Completion condition:** All four service images are at their pre-deployment versions.

### Step R4 — Restart Services

Start services in the standard dependency order: Control Center → Agent Runtime → Communication Hub → Web UI. Wait for each health check to pass before starting the next.

**Completion condition:** All services report healthy with `/health` endpoints responding.

### Step R5 — Verify Legacy Compatibility

1. Log in as `system_admin` and confirm all `/permissions` pages load without 403 errors.
2. Navigate to role policy statements — confirm flat resource types display correctly (e.g., `agent`, `mcp_server`, `role`).
3. Create a policy statement using a legacy flat type — confirm it persists and the legacy validation logic accepts it.
4. Run the standard smoke test to confirm end-to-end platform functionality.

**Completion condition:** All four checks pass. The platform operates correctly with legacy flat resource types.

### Rollback Guardrails

- Do NOT leave the updated backend running against downgraded data — stop Control Center before running the downgrade.
- Do NOT grant direct database access to Agent Runtime or Communication Hub during rollback.
- Do NOT skip the legacy compatibility verification in Step R5 — flat resource types must work after the rollback.

---

## Change-Specific Rollback: Refine OIDC Integration

Use this section when rolling back the **refine-oidc-integration** deployment. Execute steps after completing Steps 1–2 of the general procedure above. Identify the failure point before choosing which steps to execute — not all steps are needed for every failure.

### Trigger Conditions

Initiate this rollback if any of the following occur after deploying this change:

- Database migration `49ab45b8226e` caused schema issues, data loss, or constraint violations
- Control Center fails to start due to super admin credential errors (`SUPER_ADMIN_PASSWORD_HASH` is not a valid hash)
- OIDC Provider Registry cannot initialize or OIDC discovery fails for all configured providers
- The one-time `config/identity.yaml` → DB migration fails (MCP_HUB_CREDENTIAL_ENCRYPTION_KEY missing, invalid YAML, partial DB rows)
- OIDC login fails for all users after configuration and super admin is already disabled
- Super admin login is broken (wrong credentials, disabled flag, or hash mismatch)

### Failure Point: Database Migration (Step 1 of Deployment)

If the Alembic migration fails before completing:

1. Run `alembic downgrade` to the last known-good revision to clean up partial schema changes
2. Fix the migration issue (enum conflicts, constraint violations, data type mismatches)
3. Re-run `alembic upgrade head`
4. If the migration failed due to unrecoverable data corruption, restore the database from the pre-deployment backup and re-run

### Failure Point: Backend Startup (Step 2 of Deployment)

If Control Center fails to start after deployment:

1. Check logs for "super admin credentials" errors — ensure `SUPER_ADMIN_PASSWORD_HASH` is a valid bcrypt/argon2id hash, not a plaintext password
2. Check logs for "OIDC Provider Registry" errors — the registry should initialize with an empty cache if no DB config exists
3. If the failure is a code-level bug, roll back to the previous `control-center` image and fix before retrying

### Failure Point: Identity.YAML Migration (Step 3 of Deployment)

If the one-time migration from `config/identity.yaml` to database fails:

1. Check that `config/identity.yaml` is valid and readable by the Control Center process
2. Check that `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` is set (needed for client secret encryption)
3. The migration is idempotent — if it fails after creating partial DB rows, delete the affected `IdentityProviderConfig` rows and restart Control Center to retry
4. If the migration cannot complete, the system falls back to reading `config/identity.yaml` directly — the rollback is partial and the platform remains operational

### Failure Point: OIDC Login (Step 8 of Deployment)

If OIDC login fails after configuration:

1. **Do not disable the super admin** until OIDC is confirmed working
2. Use super admin access to correct the OIDC provider configuration via the System Config UI
3. Use "Test Connection" and "Test Login" buttons to validate without affecting other users
4. If OIDC is misconfigured and super admin is already disabled, follow the operational runbook to re-enable super admin via setting `SUPER_ADMIN_ENABLED=true` and restarting Control Center

### Full Rollback Steps

If a full rollback to pre-refinement state is required:

**Step R1 — Stop affected services.** Bring down `control-center` and `web-ui` containers/pods. Leave PostgreSQL and Redis running.

**Completion condition:** Control Center and Web UI are stopped.

**Step R2 — Revert database migrations.** Run `alembic downgrade` to the pre-deployment revision. This will:
- Drop the `super_admin_credentials` table — super admin bootstrap data is lost; it will be re-seeded if the change is re-deployed
- Drop the `identity_provider_config_audits` table — all audit history is lost
- Revert `identity_provider_configs` to its pre-change schema (restore removed columns, drop new columns, rename columns back, revert enum values)
- Drop `user_provider_configured` and `agent_provider_configured` from `identity_provider_setup_state`
- Any DB-stored OIDC configs created via the UI or migration are lost; `config/identity.yaml` is the restoration source

**Completion condition:** `alembic current` reports the pre-deployment revision.

**Step R3 — Restore `config/identity.yaml` usage.** If the YAML file or its mount was removed:
- Ensure `config/identity.yaml` is present and accessible from the Control Center container
- Re-add the bind mount (Docker Compose) or ConfigMap volume mount (Kubernetes) for `config/identity.yaml`
- Restore the deprecated `OIDC_*` environment variables to their pre-deployment values

**Completion condition:** `config/identity.yaml` is accessible and `OIDC_*` variables are set.

**Step R4 — Redeploy previous image tags.** Roll `control-center` and `web-ui` back to the last known-good images. Remove the `SUPER_ADMIN_*` environment variables.

**Completion condition:** Both services report healthy at previous image versions.

**Step R5 — Validate rollback.** Confirm:
- Control Center `/health` responds
- OIDC login works using `config/identity.yaml` as the config source
- The setup wizard appears if `config/identity.yaml` is absent and no DB config exists

**Completion condition:** All three checks pass. Platform operates correctly at pre-refinement state.

### Rollback Guardrails

- Do NOT disable super admin (set `SUPER_ADMIN_ENABLED=false`) during a partial rollback — keep the escape path open
- Do NOT delete `config/identity.yaml` before confirming the database migration completed successfully and OIDC login works
- Do NOT leave deprecated `OIDC_*` environment variables set after confirming the new system is stable — their presence may cause confusion about which config source is authoritative
- Do NOT grant direct database access to Agent Runtime or Communication Hub during rollback — all database operations go through Control Center
