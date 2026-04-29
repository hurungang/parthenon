# Deployment Notes: User Permission Management

**Change:** user-permission-management  
**Date:** 2026-04-25  
**Risk Level:** High — auth middleware is modified; phased rollout required

---

## 1. Environment Variables

No new environment variables are required for this change. The Permission Engine resolves authorization data exclusively from the existing PostgreSQL database and evaluates identity context from the JWT already validated by the existing auth middleware. The existing `DATABASE_URL` and JWT configuration in `backend/app/core/config.py` are sufficient.

Optional: A `PERMISSION_ENGINE_SEED_ADMIN_EMAIL` variable may be set at first deployment to designate which OIDC email address should be granted the built-in admin role during the seeding step (Step 3). This variable is consumed only once by the seed script and is not required by the running application.

---

## 2. Infrastructure Changes

No new services, containers, or external dependencies are introduced by this change. The Permission Engine, Tag Registry, User Cache Service, Group Claim Mapper, and Access Request Service all run in-process within the existing FastAPI backend. No scaling changes are required.

The auth middleware extension adds two lightweight async calls (user cache upsert and group claim mapping) to every authenticated request. Both calls are exception-safe and will not increase error rates, but they do add a small amount of database latency per request. Monitor the existing backend latency metrics after deployment and scale the backend replicas if median response time increases by more than 20%.

---

## 3. Migration Steps

Steps must be executed in the order listed. Do not proceed to the next step until the current step is verified.

### Step 1 — Generate and Review the Alembic Migration

From the `backend/` directory, run the Alembic autogenerate command targeting the current database to produce a new migration script. Review the generated file in `backend/alembic/versions/` before applying it.

Verify the generated migration includes `CREATE TABLE` statements for all thirteen new tables: `tag_definitions`, `tag_values`, `roles`, `policy_statements`, `policy_actions`, `policy_resources`, `policy_tag_conditions`, `platform_users`, `user_roles`, `groups`, `group_roles`, `user_groups`, and `access_requests`. Confirm that no existing tables appear in `op.drop_table` or `op.drop_column` calls — this migration is purely additive.

### Step 2 — Apply the Migration to Staging and Verify Tables

Apply the migration against the staging database using the Alembic upgrade command. After the upgrade completes, connect to the staging database and confirm that all thirteen tables exist with the expected columns and foreign key constraints as described in `docs/changes/user-permission-management/data-model.md`. Verify that the Alembic version table reflects the new head revision. Run the existing backend test suite against staging to confirm no regressions.

### Step 3 — Seed the Initial Admin Role and Assign to the Platform Admin

Execute the role-seeding script (or CLI command provided in the change implementation) against the staging database. The seed creates a built-in `platform_admin` role with unrestricted policy statements covering all modules and actions. It then creates a `PlatformUser` record for the designated platform administrator (identified by OIDC email or subject) and assigns that user the `platform_admin` role via a `UserRole` record.

Verify by querying the `roles`, `policy_statements`, `platform_users`, and `user_roles` tables to confirm the expected records are present. The admin user should be able to log in and see the `/permissions` routes without receiving 403 errors before enforcement is activated. Repeat this step against production immediately before Step 4.

### Step 4 — Deploy Backend with Permission Engine in Audit Mode

Deploy the updated backend image (or restart the backend service) with the Permission Engine configured to run in **audit mode**. In audit mode, the engine evaluates every authorization request and logs the decision (allow or deny) to the application log and telemetry pipeline, but does **not** reject requests — all requests proceed regardless of the decision. This ensures that no existing user workflows are disrupted while the correctness of the policy configuration is confirmed.

Confirm audit mode is active by checking the startup log for a message indicating `permission_engine_mode=audit`. All authorization evaluation log entries should appear under a structured log key that distinguishes audit-mode decisions from enforcement-mode decisions.

### Step 5 — Verify All Existing Users Pass Audit-Mode Checks

With audit mode active in production (or staging pre-production), monitor the permission audit logs for a period covering representative user activity across all existing platform roles. For each user and action observed, verify that the audit log records an **allow** decision. A deny decision in audit mode indicates either a missing role assignment or a policy misconfiguration that must be corrected before switching to enforce mode.

If deny decisions are observed, investigate and resolve by either assigning the affected users to appropriate roles (via the `/permissions` UI or the seeding script) or by updating the relevant policy statements. Re-verify after each correction. Do not proceed to Step 6 until the audit log shows exclusively allow decisions for all known user types over a representative activity window (recommended minimum: 30 minutes of normal traffic in production, or a full regression test run in staging).

### Step 6 — Switch the Permission Engine to Enforce Mode

Update the Permission Engine configuration to **enforce mode**. In enforce mode, requests that do not match an allow policy are rejected with an HTTP 403 response. Apply the configuration change via the standard deployment mechanism (environment variable, config map update, or rolling restart — per the active environment's deployment runbook in `docs/master/deployment/`).

After switching, immediately verify that:

- The platform admin can log in and access all `/permissions` sub-pages.
- A non-admin user can access their permitted modules and receives 403 on modules outside their role.
- The backend health check endpoint (`/health`) continues to return 200.
- No elevated error rates appear in the observability dashboard.

Monitor for at least 15 minutes after enforce mode is active before considering the deployment complete.

---

## 4. Rollback Procedure

The rollback procedure depends on which step has been reached.

**If rollback is required before Step 4 (before the new backend is deployed):** Apply the Alembic downgrade command to reverse the migration. Because the migration is purely additive, the downgrade drops only the thirteen new tables and does not affect existing data. The previous backend version can then be redeployed without changes.

**If rollback is required during Step 4 or Step 5 (audit mode active):** Redeploy the previous backend image. The new tables will remain in the database but are harmless to the previous version since no existing code references them. When ready to retry, the migration does not need to be re-applied.

**If rollback is required after Step 6 (enforce mode active):** Immediately redeploy the backend in audit mode (or the previous backend image) to restore service. Investigate the root cause of the failure using the audit logs captured in Step 5. Do not attempt to re-enable enforce mode until the root cause is understood and the policy configuration is corrected.

Under no circumstances should the Alembic downgrade be applied while the enforce-mode backend is serving live traffic. Always revert to audit mode or the previous image first, then assess whether a database rollback is necessary.

---

## 5. Master Deployment Update Instructions

After this change is successfully deployed to production, update the master deployment documentation at `docs/master/deployment/` as follows:

- **Database migrations:** Add an entry in the migrations reference document noting that migration version `XXX` (replace with the actual Alembic revision ID) introduced the thirteen permission-management tables. Record the date of production deployment.

- **Permission Engine rollout pattern:** Add a new section describing the audit-mode → enforce-mode rollout pattern as the standard procedure for any future change that modifies the auth middleware or the Permission Engine. Reference this change as the precedent.

- **Role seeding:** Document the role-seeding step as a required one-time operation for new environment bootstraps. Note the optional `PERMISSION_ENGINE_SEED_ADMIN_EMAIL` environment variable and when to use it.

- **Operational runbook:** Add a runbook entry for toggling the Permission Engine between audit and enforce modes, including how to identify the current mode from the startup log and how to apply a mode change without a full redeployment if the deployment environment supports live config map updates.

- **Latency monitoring:** Add a note to the operational monitoring section to baseline backend response times before any future Permission Engine policy expansion, given the per-request database calls introduced by the User Cache and Group Claim Mapper.
