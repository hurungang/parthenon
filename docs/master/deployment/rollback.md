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

Start services in the same order defined in the First-Time Deployment runbook (Step 7), waiting for each to reach a healthy state before starting the next.

---

## Step 6 — Validate Rollback

Re-run the smoke test from Step 11 of the First-Time Deployment runbook to confirm the platform is operating correctly at the previous state:

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

Deploy the previous `platform-api` image. Remove all `AGENT_RUNTIME_*`, `AGENT_SESSION_*`, `AGENT_PERMISSION_*`, and `AGENT_GATEWAY_*` environment variables.

**Completion condition:** Platform API health check passes; existing endpoints respond normally.

### Step R4 — Database Rollback (conditional)

Run only if migration `df2225d787c5` must be reversed.

```bash
alembic downgrade -1
```

> **Warning — data loss:** This will drop the `agent_role`, `agent_role_sop`, `agent_role_skill`, `agent_identity`, and `agent_session` tables and revert `agent_type` column changes. Any data entered via the new agent admin UI will be permanently lost. Confirm with the team before executing.

**Completion condition:** `alembic current` reports the previous migration ID. The `agent_role` table does not exist. The `agent_type` table has its original columns (`sop_id`, `identity_subject`, `system_prompt`, `mode`).

### Step R5 — Flush Permission Cache

Remove all Agent Permission Manager cache keys from Redis to prevent stale data from affecting a subsequent redeployment attempt.

```bash
redis-cli --scan --pattern 'agentperm:*' | xargs redis-cli del
```

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
