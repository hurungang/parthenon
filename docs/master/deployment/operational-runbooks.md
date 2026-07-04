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

---

## 5. Service Segregation Allowlist Rollout (Audit → Enforce)

Use this runbook when deploying caller-specific Control Center internal API allowlists for `agent_runtime` and `communication_hub`.

### Preconditions

- mTLS is enabled for Agent Runtime and Communication Hub internal calls.
- Service certificates and revocation checks are operational.
- Control Center policy variables are configured, including `INTERNAL_API_POLICY_MODE`, `INTERNAL_API_DENY_AUDIT_ENABLED`, and `INTERNAL_API_REQUIRE_SERVICE_IDENTITY`.

### Phase A — Audit Mode

1. Deploy Control Center with `INTERNAL_API_POLICY_MODE=audit` and deny audit events enabled.
2. Deploy Agent Runtime and Communication Hub with caller identity and mTLS variables aligned.
3. Run representative workloads and verify all expected internal calls succeed.
4. Confirm denied events are emitted only for non-contract paths.

### Phase B — Contract Validation Window

- Maintain audit mode for a minimum of one representative traffic cycle.
- Resolve all allowlist drift before enforcement. Drift includes legitimate production traffic denied in audit mode.
- Record allowlist version and validation evidence in deployment records.

### Phase C — Enforce Cutover

1. Set `INTERNAL_API_POLICY_MODE=enforce`.
2. Verify normal agent execution, message routing, and tool-call workflows.
3. Confirm deny events continue for blocked calls with stable error rates.
4. Continue elevated monitoring through stabilization period.

### Exit criteria

- No unresolved allowlist drift.
- No sustained failures on legitimate internal service paths.
- Certificate renewal and revocation telemetry are healthy.

---

## 6. Deny-Event Triage and Escalation

Use this runbook when deny events increase after allowlist rollout.

### Triage steps

1. Group deny events by caller type, route, method, and policy reason.
2. Determine whether traffic is expected behavior or potential abuse.
3. For expected behavior, validate caller identity mapping and allowlist version.
4. For unexpected traffic, keep deny-by-default and open security incident review.

### Escalation thresholds

- Escalate immediately if denied calls exceed 5% of total internal calls for 5 consecutive minutes.
- Escalate immediately if any deny reason indicates missing caller identity for a known service.
- Escalate immediately if revocation-check failures are present during enforce mode.

### Containment guidance

- Do not disable mTLS or caller identity enforcement.
- If legitimate traffic is impacted, downgrade policy mode to audit while investigation continues.
- Preserve deny-event telemetry for forensic and compliance evidence.

---

## 7. Certificate and Revocation Failure Response

Use this runbook for certificate bootstrap, renewal, handshake, or revocation-check failures affecting internal service calls.

### Detection signals

- Repeated mTLS handshake failures between Agent Runtime or Communication Hub and Control Center.
- Certificate renewal failures approaching expiry threshold.
- Revocation subsystem outages when `INTERNAL_API_FAIL_CLOSED_REVOCATION=true`.

### Response sequence

1. Confirm affected service identity and certificate chain status.
2. Validate bootstrap key alignment between Control Center and caller service.
3. Rotate affected service certificate and re-bootstrap identity if compromise or mismatch is suspected.
4. Re-verify revocation-check health before restoring normal traffic expectations.

### Operational guardrails

- Do not switch revocation behavior to fail-open in production.
- Do not bypass service certificate validation to recover traffic.
- If service continuity is at risk, switch policy mode to audit and follow rollback runbook guidance.

---

## 8. Agent Execution Guardrails Rollout Verification Checklist

Use this checklist immediately after deploying the `add-agent-execution-guardrails` change.

### Preconditions

- Control Center, Communication Hub, and Agent Runtime versions are guardrail-contract compatible.
- Required guardrail environment variables are configured for all three services.
- Approved default thresholds and fallback modes are documented for the target environment.

### Verification sequence

1. Validate policy snapshot readiness
- Confirm Control Center resolves and serves effective guardrail policy snapshot fields in execution context payloads.

2. Validate forwarding integrity
- Run direct and delegated execution flows and confirm Communication Hub preserves guardrail policy snapshot and stop-reason metadata end-to-end.
- Confirm conversational token visibility and continuation metadata are preserved in forwarded payloads.

3. Validate pre-execution cycle detection
- Execute a known recursive delegation scenario and confirm the run is blocked before execution with a cycle-classified stop reason.

4. Validate cumulative iteration accounting
- Execute multi-hop delegated sessions and confirm cumulative iteration limits account for local and delegated chain activity.

5. Validate timeout and delegation limits
- Confirm wall-clock timeout behavior is enforced and classified clearly.
- Confirm delegation depth and delegated-step limits are enforced with distinct stop reasons.

6. Validate mode-aware token behavior
- Conversational mode: confirm current-session token usage is continuously visible and sessions continue at token threshold unless another hard guardrail triggers a stop.
- Non-conversational and automated modes: confirm token-budget enforcement or configured fallback behavior is applied and classified clearly.

7. Validate persistence and observability
- Confirm structured stop reasons are persisted in session state and logs.
- Confirm conversational token telemetry and continuation-path metadata are persisted and visible in observability pipelines.

### Exit criteria

- All guardrail stop classes are produced and persisted as expected.
- No metadata loss is observed across direct or delegated routing paths.
- No unexpected hard stops occur on known-good conversational workloads.

---

## 9. Keycloak Group Membership Mapper — Reprovisioning for Existing Installations

Use this runbook to add the Group Membership protocol mapper to an existing bundled Keycloak installation that was provisioned before this capability was introduced. This is a one-time operation to enable group-based permission inheritance via the JWT `groups` claim.

### When to use this runbook

Apply this runbook when:
- The Parthenon instance was provisioned before the group membership mapper was added to the provisioning flow
- Users who are members of Keycloak groups are not receiving the expected Parthenon group roles on login
- The JWT access token issued by Keycloak does not contain a `groups` claim

### Background

Prior to the addition of automatic group membership mapper creation, the `parthenon-api-ui` Keycloak client lacked a "Group Membership" protocol mapper. The `GroupClaimMapper` and `JWTAuthMiddleware` were designed to auto-assign users to Parthenon groups by matching JWT `groups` claims, but the claim was never present in tokens because the mapper was missing.

### Procedure

Reprovision the identity provider with the `force_reconfigure` flag set to `true`. This re-runs the bootstrap flow, which:
1. Detects the existing realm and client (no duplication or re-creation)
2. Adds the Group Membership protocol mapper to the `parthenon-api-ui` client
3. Is idempotent — running multiple times will not create duplicate mappers

**Via the CLI (headless):**

Run inside the `platform-api` container:
```bash
python -m app.cli provision-identity --force-reconfigure
```
The CLI uses the existing identity provider configuration stored in the database and re-provisions without prompting for credentials.

**Via the API directly:**

Call `POST /api/v1/setup/identity` with `"force_reconfigure": true` in the request body, supplying the same provider credentials used during initial provisioning.

> **Note:** The `POST /setup/identity` endpoint returns HTTP 409 when setup is already configured and `force_reconfigure` is not set to `true`. Always include the `force_reconfigure` flag when reprovisioning.

### Verification

After reprovisioning:

1. Check the Platform API logs for a confirmation message indicating the Group Membership mapper was created (or that an existing mapper was detected and skipped)
2. Log in as a user who is a member of at least one Keycloak group that has a corresponding Parthenon group with a matching `idp_claim_value`
3. Decode the user's JWT access token (e.g., via the browser developer tools or a JWT debugger) and confirm the `groups` claim is present and contains the expected Keycloak group names
4. Verify that the user's Parthenon group memberships and inherited roles are reflected in the admin UI under the user's permission profile

### Rollback

No rollback is needed for this operation. The Group Membership mapper is additive — it does not modify any existing client configuration. If the mapper should be removed for any reason, delete it manually in the Keycloak Admin Console (`Clients` → `parthenon-api-ui` → `Client scopes` → `parthenon-api-ui-dedicated` → `Mappers`).

### Compatibility

- Works with all existing Parthenon group configurations — no changes to `idp_claim_value` or group-to-role mappings are needed
- Does not affect users who are not members of any Keycloak groups — their tokens will include an empty `groups` claim
- Applies only to the bundled Keycloak provider (`IDENTITY_PROVIDER_TYPE=keycloak_bundled`). External providers must be configured separately
