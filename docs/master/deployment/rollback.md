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
