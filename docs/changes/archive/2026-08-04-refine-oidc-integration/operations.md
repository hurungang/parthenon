# Operations: Refine OIDC Integration

## 1. Monitoring

### New Metrics

| Component | Metric | Why It Matters |
|-----------|--------|----------------|
| **OIDC Provider Registry** | `oidc.provider.reachability` (gauge, labels: `provider_type`, `provider_name`) | 1 = provider reachable via OIDC Discovery; 0 = unreachable. Per-provider health signal for both user and agent identity providers. |
| **OIDC Provider Registry** | `oidc.provider.discovery_latency` (p99, labels: `provider_type`, `provider_name`) | Time to complete `.well-known/openid-configuration` fetch. High p99 indicates provider-side latency or network issues. |
| **OIDC Provider Registry** | `oidc.jwks.fetch_failures_total` (labels: `provider_type`, `provider_name`) | Failed JWKS endpoint fetches per provider. Any sustained non-zero rate is critical — JWTs will fail validation. |
| **OIDC Provider Registry** | `oidc.jwks.cache_hits_total` | JWKS keys served from in-memory cache. |
| **OIDC Provider Registry** | `oidc.jwks.cache_misses_total` | JWKS cache misses requiring a fetch from the provider. |
| **OIDC Provider Registry** | `oidc.jwks.cache_hit_rate` (derived) | `cache_hits / (cache_hits + cache_misses)`; below 90% indicates excessive key rotation or undersized TTL. |
| **OIDC Provider Registry** | `oidc.registry.reload_total` (labels: `trigger`) | Registry reload events; `trigger` is one of `config_update`, `manual`, `startup`. Spikes indicate frequent operator-driven config changes. |
| **OIDC Provider Registry** | `oidc.registry.reload_errors_total` | Failed registry reload attempts. Any non-zero rate means config is stale and new provider settings are not taking effect. |
| **Super Admin Auth** | `superadmin.login_attempts_total` (labels: `outcome`) | Super admin login attempts; `outcome` is `success` or `failure`. |
| **Super Admin Auth** | `superadmin.login_failures_total` (labels: `reason`) | Failed super admin attempts; `reason` is `invalid_credentials`, `disabled`, or `expired`. |
| **Super Admin Auth** | `superadmin.token_issued_total` | Short-lived JWT tokens issued to super admin sessions. |
| **Auth Middleware** | `auth.pipeline.decision_total` (labels: `tier`, `outcome`) | Which tier resolved the request; `tier` is `super_admin`, `oidc_user`, `oidc_agent`, or `public`. `outcome` is `allowed` or `denied`. |
| **Auth Middleware** | `auth.pipeline.latency` (p99, labels: `tier`) | Time spent in each auth tier. High p99 for `oidc_*` tiers indicates provider-side latency. |
| **Auth Middleware** | `auth.oidc.validation_failures_total` (labels: `provider_type`, `reason`) | OIDC JWT validation failures; `reason` is `signature`, `expired`, `audience`, `issuer`, `claims`, or `unknown`. |
| **OIDC Config Service** | `oidc.config.test_success_total` (labels: `provider_type`, `test_type`) | Successful OIDC test connections and test logins from the UI. |
| **OIDC Config Service** | `oidc.config.test_failure_total` (labels: `provider_type`, `test_type`, `reason`) | Failed OIDC tests with failure reason (connectivity, auth, claims mapping). |
| **OIDC Config Service** | `oidc.config.change_total` (labels: `action`, `provider_type`) | Provider config mutations; `action` is `create`, `update`, or `delete`. Used for audit trail. |
| **OIDC Config Service** | `oidc.config.secret_encryption_errors_total` | Client secret encryption failures at rest. Any non-zero rate indicates crypto subsystem issue. |

### New Dashboards

#### OIDC Provider Health
Single-pane view of identity provider connectivity. Include: per-provider reachability gauges (user and agent), OIDC Discovery latency p99 per provider, JWKS cache hit rate per provider, JWKS fetch failure rate per provider, and registry reload event count. Use red/green colour coding for reachability.

#### Super Admin & Auth Pipeline
Authentication decision overview. Include: auth pipeline tier distribution (stacked bar: super_admin, oidc_user, oidc_agent, public), super admin login success/failure rate as a time series, OIDC JWT validation failure rate by reason, and auth pipeline p99 latency per tier.

### New Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `OIDCProviderUnreachable` | `oidc.provider.reachability == 0` for 5 min | Critical | OIDC login is broken for affected provider; check network, DNS, and provider health |
| `OIDCJWKSFetchFailureSustained` | `rate(oidc.jwks.fetch_failures_total) > 0` for 2 min | Critical | All JWT validation is failing; JWT signatures cannot be verified |
| `OIDCJWKSCacheDegraded` | `oidc.jwks.cache_hit_rate < 0.90` for 10 min | Warning | Excessive JWKS key rotation or undersized cache TTL |
| `OIDCRegistryReloadError` | `rate(oidc.registry.reload_errors_total) > 0` for 2 min | Critical | Registry reload failed; OIDC config is stale and provider changes are not reflected |
| `SuperAdminBruteForce` | `rate(superadmin.login_failures_total) > 10/min` for 5 min | Critical | Potential brute-force attack on super admin credentials; consider disabling super admin or rotating credentials |
| `SuperAdminDisabledLoginAttempt` | `rate(superadmin.login_failures_total{reason="disabled"}) > 0` for 5 min | Warning | Login attempts to a disabled super admin; may indicate misconfiguration or unauthorized access attempt |
| `OIDCTestFailureSustained` | `rate(oidc.config.test_failure_total) > 0` for 10 min | Warning | Operator repeatedly unable to validate OIDC connectivity; check provider configuration |
| `OIDCSecretEncryptionError` | `rate(oidc.config.secret_encryption_errors_total) > 0` | Critical | Client secret encryption/decryption failing; OIDC authentication may not function |
| `AuthPipelineOIDCLatencyHigh` | `auth.pipeline.latency` p99 > 5 s for `oidc_user` or `oidc_agent` tier for 5 min | Warning | OIDC provider or network is slow; user login experience degraded |

---

## 2. Logging

### New Log Events

#### Super Admin Auth Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `superadmin.login.success` | INFO | `username`, `remote_ip`, `token_expires_at` | Super admin authenticated successfully |
| `superadmin.login.failure` | WARN | `username`, `remote_ip`, `reason` | Failed super admin login; `reason` is `invalid_credentials`, `disabled`, or `expired` |
| `superadmin.logout` | INFO | `username`, `session_duration_s` | Super admin session ended (logout or token expiry) |
| `superadmin.disabled` | INFO | `changed_by`, `previous_state` | Super admin account was disabled via config or API |
| `superadmin.enabled` | INFO | `changed_by`, `previous_state` | Super admin account was enabled via config or API |
| `superadmin.bootstrap` | INFO | `username`, `source` | Super admin credentials seeded on first launch; `source` is `env_var` or `config_default` |

#### OIDC Provider Config Change Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `oidc.config.created` | INFO | `provider_type`, `provider_name`, `issuer_url`, `actor` | New OIDC provider config created via UI or API |
| `oidc.config.updated` | INFO | `provider_type`, `provider_name`, `changed_fields[]`, `actor` | Existing provider config modified; `changed_fields` lists what was changed (never logs secret values) |
| `oidc.config.deleted` | WARN | `provider_type`, `provider_name`, `actor` | Provider config deleted; active sessions using this provider will fail on next validation |
| `oidc.config.test_connection` | INFO | `provider_type`, `provider_name`, `issuer_url`, `result` | Operator triggered OIDC connectivity test from UI |
| `oidc.config.test_login` | INFO | `provider_type`, `provider_name`, `result`, `claims_summary` | Operator triggered OIDC test login; `claims_summary` includes claim keys only (no values) |
| `oidc.config.migration` | INFO | `source_file`, `entries_migrated`, `result` | One-time migration from `config/identity.yaml` to database |

#### OIDC Provider Connectivity Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `oidc.discovery.success` | DEBUG | `provider_type`, `provider_name`, `issuer_url`, `duration_ms` | OIDC Discovery endpoint fetched successfully |
| `oidc.discovery.failure` | ERROR | `provider_type`, `provider_name`, `issuer_url`, `error`, `status_code` | OIDC Discovery endpoint unreachable or returned error |
| `oidc.jwks.fetch_success` | DEBUG | `provider_type`, `provider_name`, `keys_count` | JWKS keys fetched and cached |
| `oidc.jwks.fetch_failure` | ERROR | `provider_type`, `provider_name`, `jwks_uri`, `error` | JWKS endpoint unreachable; JWT validation will fail |
| `oidc.jwks.cache_expired` | INFO | `provider_type`, `provider_name`, `cache_age_s` | JWKS cache TTL expired; next request triggers refresh |
| `oidc.registry.initialized` | INFO | `provider_count`, `providers[]` | OIDC Provider Registry initialized at startup with provider summary |
| `oidc.registry.reloaded` | INFO | `trigger`, `provider_count_before`, `provider_count_after` | Registry cache invalidated and reloaded from database |
| `oidc.registry.reload_failed` | ERROR | `trigger`, `error` | Registry reload from database failed; stale config remains in use |

#### Auth Middleware Decision Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `auth.pipeline.decision` | INFO | `tier`, `outcome`, `user_identity`, `provider_type`, `request_path` | Auth decision logged per request; `tier` is `super_admin`, `oidc_user`, `oidc_agent`, or `public` |
| `auth.pipeline.superadmin_skipped` | INFO | `remote_ip`, `reason` | Super admin tier skipped; `reason` is `disabled` or `no_superadmin_token` |
| `auth.pipeline.oidc_provider_not_found` | ERROR | `provider_type` | No active provider config found for the requested provider type in registry |
| `auth.oidc.jwt_invalid` | WARN | `provider_type`, `reason`, `token_hint` (first 8 chars) | JWT validation rejected; `reason` is `signature`, `expired`, `audience`, `issuer`, `claims`, or `unknown` |
| `auth.oidc.jwt_valid` | DEBUG | `provider_type`, `sub`, `expires_at` | JWT validated successfully (debug level to avoid logging every request in production) |

#### Sensitive Data Exclusions
- Never log client secrets, OIDC client credentials, JWT payload bodies, or access/refresh token values
- Never log full super admin password hashes
- Log only the first 8 characters of JWT tokens as a `token_hint` for correlation
- Log claim key names for test login events but never claim values
- Use `changed_fields[]` for config mutations — list field names only, never values

### Where to Find Logs

All OIDC-related log events are emitted by the Control Center service and written to:

| Log File | Service | Purpose |
|----------|---------|---------|
| `backend/logs/control-center.log` | Control Center (port 8000) | Super admin login events, auth middleware decisions, OIDC Discovery/JWKS fetch, provider config changes, registry reload events |

Filtering tips:
- Search for `superadmin.` to find super admin auth events
- Search for `oidc.config.` to find provider configuration changes
- Search for `oidc.discovery.` or `oidc.jwks.` to find provider connectivity issues
- Search for `auth.pipeline.` to find which auth tier handled each request
- Search for `oidc.registry.` to find registry initialization and reload events

Logs rotate at ~10 MB with `.1` and `.2` suffixes kept as the two most recent rolls.

---

## 3. Common Issues

### OIDC Provider Unreachable

**Symptoms**: Login page shows "Unable to connect to identity provider" error. Logs contain `oidc.discovery.failure` events. `oidc.provider.reachability` gauge is 0.

**Root causes**:
- Network partition between Parthenon and the OIDC provider
- Provider is down or undergoing maintenance
- DNS resolution failure for the issuer URL
- Firewall blocking egress from Control Center to the provider

**Resolution**:
1. From the Control Center container network, verify connectivity to the issuer URL: `curl -v <issuer_url>/.well-known/openid-configuration`
2. Confirm the provider service is running and accessible from the deployment environment
3. Check DNS resolution for the issuer hostname from within the Control Center container
4. Verify firewall rules allow outbound HTTPS from Control Center to the provider
5. If using a self-signed or internal CA certificate on the OIDC provider, ensure the CA cert is trusted by the Control Center container
6. Once connectivity is restored, the registry will pick up the provider on the next JWT validation request (no restart needed)

### JWKS Endpoint Unreachable

**Symptoms**: All API requests return 401. Logs contain `oidc.jwks.fetch_failure` or `auth.oidc.jwt_invalid` with `reason=signature`. `oidc.jwks.fetch_failures_total` counter is incrementing.

**Root causes**:
- JWKS URI resolved from OIDC Discovery is unreachable (different host than issuer)
- Provider rotated signing keys and old keys are cached
- Network path to JWKS endpoint is blocked separately from Discovery endpoint

**Resolution**:
1. Verify the JWKS URI from the provider's `.well-known/openid-configuration` is reachable from the Control Center container
2. If the JWKS URI is on a different host/port than the issuer, check that firewall rules cover both endpoints
3. If the provider recently rotated keys, the registry cache may have stale keys. Trigger a manual registry reload via the System Config UI (Test Connection button) or restart the Control Center
4. Check that the JWKS cache TTL is appropriate for the provider's key rotation frequency (default: 1 hour)
5. If the provider uses infrequent key rotation, consider increasing the JWKS cache TTL

### Super Admin Locked Out

**Symptoms**: Cannot log in as super admin. Login page shows "Super admin authentication failed" or "Super admin is disabled". Super admin login attempt logs show `reason=disabled` or `reason=invalid_credentials`.

**Root causes**:
- Super admin was disabled via System Config UI while OIDC is also misconfigured or unavailable
- Super admin credentials were changed and the new credentials are unknown
- Environment variables for super admin bootstrap were removed or misconfigured

**Resolution**:
1. **If super admin is disabled and OIDC is broken**: Set the environment variable `SUPER_ADMIN_ENABLED=true` in the Control Center service configuration and restart. This re-enables the super admin tier regardless of the database setting. This is the escape hatch when both OIDC and the UI-based super admin toggle are unavailable.
2. **If super admin credentials are unknown**: Set `SUPER_ADMIN_USERNAME` and `SUPER_ADMIN_PASSWORD_HASH` environment variables with fresh bcrypt-hashed credentials. On restart, the BootstrapService will seed these into the database, overwriting existing credentials. Generate a bcrypt hash using any standard tool — the Control Center expects bcrypt format.
3. **If the super admin credentials are correct but login fails**: Check `superadmin.login_failure` log events for the specific `reason`. If `reason=expired`, the session token expired — re-authenticate (super admin tokens have a configurable expiry, default 15 minutes).
4. **Once OIDC is working again**: Disable the super admin via the System Config UI to ensure all authentication flows through the identity provider in production.

### Config Migration Failure

**Symptoms**: After upgrade, OIDC authentication is not working. Logs contain `oidc.config.migration` with `result=failed`. No provider configs appear in the database `identity_provider_configs` table.

**Root causes**:
- `config/identity.yaml` is missing, unreadable, or has invalid YAML syntax
- `config/identity.yaml` contains values that fail validation against the new provider schema (e.g., missing required fields, invalid issuer URL format)
- Database is unreachable during startup migration

**Resolution**:
1. Check `control-center.log` for `oidc.config.migration` events to identify the specific migration error
2. Verify `config/identity.yaml` exists in the expected location and is valid YAML
3. Ensure all required fields are present: `issuer_url`, `client_id`, `client_secret`. Optional fields (scopes, claims mapping) will use sensible defaults if missing
4. If `config/identity.yaml` is corrupted, manually configure the provider via the System Config UI after starting with super admin credentials
5. If the migration was partially applied (some entries migrated, some failed), review and correct the database entries via the System Config UI
6. After the migration succeeds, the `config/identity.yaml` file is no longer read — it can be archived

### Token Validation Failures After Provider Change

**Symptoms**: After updating an OIDC provider config via the System Config UI, existing sessions start failing with 401. Logs show `auth.oidc.jwt_invalid` with various reasons. Users must re-authenticate.

**Root causes**:
- Issuer URL change means existing tokens' `iss` claim no longer matches
- Client ID change means tokens' `aud` claim no longer matches the expected audience
- Claims mapping change means required claims are missing or have unexpected values
- Provider change means JWKS keys are from a different provider entirely

**Resolution**:
1. **Expected behaviour**: Token validation uses the current active provider config at the time of each request. After a provider change, existing tokens from the old provider will fail validation. Users and agents will need to re-authenticate to obtain new tokens from the current provider. This is by design — provider configuration is the source of truth.
2. **If failure is unexpected** (same provider, minor config change): Verify the issuer URL is character-exact — trailing slashes matter (`https://idp.example.com` vs `https://idp.example.com/`). Check that the audience (`aud` claim) in issued tokens matches the expected audience in the provider config.
3. **If the registry is serving stale config**: Trigger a manual registry reload via the System Config UI (save any provider config to trigger a reload event) or check `oidc.registry.reload_failed` log events for errors.
4. **To minimize disruption during provider changes**: Schedule provider changes during maintenance windows. Communicate to users that re-authentication will be required. Agent identities with client credentials will automatically refresh tokens on next execution — no manual intervention needed for agents.

### Frontend Login Page Shows Wrong State

**Symptoms**: Login page shows super admin login form when it should show OIDC buttons, or shows OIDC buttons when super admin is expected, or shows setup wizard when OIDC is configured.

**Root causes**:
- AuthContext cached a stale provider list and has not refreshed
- Provider config exists in the database but is not marked as the active provider for the correct type (`user` or `agent`)
- Super admin enable/disable toggle was changed but the frontend has not fetched the updated state
- CORS or network issue prevents the frontend from calling `GET /api/v1/system/identity-providers`

**Resolution**:
1. **Verify the database state**: Check the `identity_provider_configs` table for active providers. Each provider entry has a `provider_type` (`user` or `agent`) and an `enabled` flag. The login page uses the `user` provider for human login.
2. **Check the AuthContext API call**: Open browser developer tools and verify `GET /api/v1/system/identity-providers` returns the expected active providers and super admin enabled state. Check for CORS errors or 5xx responses.
3. **Force a frontend refresh**: Hard-refresh the browser (Ctrl+Shift+R) to force AuthContext to re-fetch provider state on next app load.
4. **If setup wizard appears instead of login**: This means the API reported no active OIDC providers and super admin is not enabled. Verify the database entries exist and are `enabled=true`.
5. **If login page shows both super admin and OIDC**: This is correct when super admin is enabled AND an OIDC user provider is configured. If you want only OIDC, disable the super admin via the System Config UI.

---

## 4. Master Operations Update Instructions

After implementing this change, update the following master operations documents:

### Update `docs/master/operations/monitoring.md`

- **Key Metrics table**: Add all new metrics from Section 1 above under a new **OIDC Identity** component group and a new **Super Admin Auth** component group. Follow the existing table format with Component, Metric, and Why It Matters columns.
- **Dashboards to Create**: Add entries for **OIDC Provider Health** (per-provider reachability, Discovery latency, JWKS cache hit rate, JWKS fetch failures, registry reload events) and **Super Admin & Auth Pipeline** (auth tier distribution, super admin login rate, JWT validation failures by reason, auth pipeline latency per tier).
- **Alerts to Configure**: Add all new alerts from Section 1 under new **OIDC Identity Alerts** and **Super Admin Alerts** subsections. Follow the existing four-column format (Alert Name, Condition, Severity, Action).

### Update `docs/master/operations/logging.md`

- **Per-Component Log Events** table: Add entries for **OIDC Provider Registry** (JWKS caching, discovery, registry lifecycle), **Super Admin Auth** (login success/failure, enable/disable, bootstrap), **OIDC Config Service** (provider CRUD, test connections, migration), and **Auth Middleware** (pipeline tier decisions, JWT validation outcomes).
- **Log Levels** table: No changes needed — existing levels apply to new events.
- **Correlation Fields** table: No changes needed — existing fields apply.
- **Where to Find Logs**: Add a note that all OIDC and super admin log events are in `backend/logs/control-center.log` with grep patterns for `superadmin.`, `oidc.`, and `auth.pipeline.`.

### Create `docs/master/operations/runbooks/super-admin-lockout.md`

- **Trigger symptoms**: Cannot log in as super admin; login page shows "Super admin disabled" or "Invalid credentials"; OIDC also unavailable.
- **Resolution**: Document the environment variable override escape hatch (`SUPER_ADMIN_ENABLED=true`), credential re-seeding via `SUPER_ADMIN_USERNAME` / `SUPER_ADMIN_PASSWORD_HASH` env vars, and how to disable super admin again once OIDC is restored.

### Update `docs/master/operations/runbooks/oidc-token-failure.md`

- **Symptoms**: Add OIDC provider unreachable cases (Discovery failure, JWKS fetch failure) alongside existing JWT validation errors. Reference the `oidc.provider.reachability` gauge.
- **Resolution Steps**: Add steps for:
  - Checking OIDC Discovery endpoint reachability from the Control Center container
  - Triggering a manual registry reload (via System Config UI Test Connection) instead of restarting the Control Center
  - Verifying per-provider configuration in the database when multiple providers are configured
  - Distinguishing user provider failures from agent provider failures using `provider_type` labels in logs

### Update `docs/master/operations/README.md`

- **Dashboards** table: Add **OIDC Provider Health** and **Super Admin & Auth Pipeline** dashboards.
- **Runbooks** table: Add entry for `super-admin-lockout.md` with trigger symptom "Cannot log in with super admin; OIDC also unavailable; need emergency access."
