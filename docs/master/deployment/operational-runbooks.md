# Operational Runbooks — Deployment

Targeted runbooks for specific operational tasks within a running Parthenon deployment. Each runbook is self-contained and references the broader deployment context in [first-time-deployment.md](first-time-deployment.md) and [rollback.md](rollback.md) where needed.

---

## 1. Permission Engine Rollout Pattern (Audit → Enforce)

This is the **standard procedure** for any future change that modifies the auth middleware or the Permission Engine. The `user-permission-management` change (2026-04-25) is the precedent.

### When to use this pattern

Apply this pattern whenever a deployment:
- Modifies `backend/app/middleware/` auth middleware
- Changes the Permission Engine evaluation logic in `backend/app/services/`
- Adds, removes, or restructures `policy_statements`, `roles`, or `groups` records
- Introduces new protected routes or changes existing route permission requirements

### Phase 1 — Audit Mode Deploy

Deploy the new backend with the Permission Engine in **audit mode**. In audit mode the engine evaluates every authorization request, logs the decision (allow or deny) to the application log and telemetry pipeline, and proceeds regardless of outcome — no requests are rejected.

Confirm audit mode is active by checking the startup log for `permission_engine_mode=audit`. Authorization evaluation log entries will appear under a structured log key that distinguishes audit decisions from enforcement decisions.

### Phase 2 — Verify Audit Decisions

Monitor the permission audit logs over a representative activity window (minimum: 30 minutes of normal production traffic, or a full regression test run in staging). Verify that every user and action observed produces an **allow** decision in the audit log.

A deny decision in audit mode indicates either a missing role assignment or a policy misconfiguration. Investigate and resolve by assigning affected users to appropriate roles (via the `/permissions` UI or the seeding script) or by correcting the relevant policy statements. Re-verify after each correction. Do not advance to Phase 3 until all known user types produce exclusively allow decisions.

### Phase 3 — Enforce Mode Activation

Switch the Permission Engine to **enforce mode** via the standard deployment mechanism for the active environment (environment variable, ConfigMap update, or rolling restart — see the runbook in §2 below). In enforce mode, requests that do not match an allow policy are rejected with HTTP 403.

Immediately after switching:
- Confirm the platform admin can log in and access all `/permissions` sub-pages
- Confirm a non-admin user can access their permitted modules and receives 403 outside their role
- Confirm the `/health` endpoint returns 200
- Confirm no elevated error rates appear in the observability dashboard

Monitor for at least 15 minutes before considering the deployment complete.

### Phase 4 — Rollback Path

- **Before enforce mode (Phases 1–2):** Redeploy the previous backend image. New permission tables remain but are harmless to the previous version.
- **During or after enforce mode (Phase 3):** Immediately redeploy in audit mode (or the previous image) to restore service. Investigate using audit logs captured in Phase 2. Do not re-enable enforce mode until the root cause is resolved.

---

## 2. Toggle Permission Engine Mode (Audit ↔ Enforce)

Use this runbook to change the Permission Engine operating mode without a full redeployment, where the environment supports live config updates.

### Identifying the current mode

Check the backend startup log for the structured entry `permission_engine_mode=<mode>`. The value is either `audit` or `enforce`. If the log is not available, query the Platform API health endpoint — the response body includes the current engine mode.

### Switching modes

**Docker Compose (self-hosted)**

Update the `PERMISSION_ENGINE_MODE` value in the `.env` file (or the relevant Docker secrets file), then restart the `platform-api` container. The mode is read at startup; a restart is required.

**Kubernetes / Helm**

Update the `PERMISSION_ENGINE_MODE` key in the relevant Kubernetes ConfigMap or Secret, then trigger a rolling restart of the `platform-api` Deployment. If the environment's Helm values support it, set the value via `helm upgrade --set` to avoid touching the base values file.

### Post-switch verification

After a mode change in either direction:
1. Check the startup log of the new pod for `permission_engine_mode=<expected-mode>`
2. Confirm the `/health` endpoint returns 200
3. If switching to enforce: run the Phase 3 verification steps from §1 above

---

## 3. Permission Engine — Role Seeding (New Environment Bootstrap)

Role seeding is a **required one-time operation** for every new Parthenon environment (including staging and production). It must be executed after the Alembic migrations are applied (see [first-time-deployment.md](first-time-deployment.md) Step 3) and before the Permission Engine is switched to enforce mode.

### What seeding does

The seed script creates:
- The built-in `platform_admin` role with unrestricted policy statements covering all modules and actions
- A `PlatformUser` record for the designated platform administrator (identified by OIDC email or subject)
- A `UserRole` record assigning the `platform_admin` role to that user

### Optional environment variable

`PERMISSION_ENGINE_SEED_ADMIN_EMAIL` may be set in the environment before running the seed script to designate which OIDC email address receives the `platform_admin` role. If not set, the seed script prompts interactively.

This variable is consumed only once by the seed operation and is not used by the running application. It should be unset or removed from the environment configuration after seeding is complete.

### Verification

After seeding, query the `roles`, `policy_statements`, `platform_users`, and `user_roles` tables to confirm the expected records exist. The designated admin user should be able to log in and reach all `/permissions` routes without receiving 403 responses (whether the engine is in audit or enforce mode).

---

## 4. Permission Engine — Latency Baseline and Monitoring

The auth middleware extension introduced by the `user-permission-management` change adds two lightweight async calls (user cache upsert and group claim mapping) to every authenticated request. Both calls are exception-safe and will not increase error rates, but they do add a small amount of database latency per request.

### Before any future Permission Engine policy expansion

Capture the following baseline metrics **before** deploying any change that expands Permission Engine policy evaluation (new modules, new conditions, additional group mappings):

- Median and P95 backend response time for authenticated endpoints (from the Prometheus / OTEL metrics dashboard)
- Database connection pool utilisation on the `postgres` service
- Per-request database query count (available from SQLAlchemy instrumentation in OTEL traces)

### Post-deployment monitoring thresholds

After deploying a Permission Engine change:
- If the median response time increases by more than 20%, scale the `platform-api` replicas before switching to enforce mode
- If database connection pool utilisation exceeds 80%, review whether the user cache TTL should be extended or whether the group claim mapping query can be cached
- Monitor for at least 15 minutes of representative traffic before considering the deployment stable
