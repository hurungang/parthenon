# Logging — Security, Identity, and Boundary Events

Tenant isolation, super-admin and OIDC identity, configuration guardrails, certificate lifecycle, and internal API boundary events.

Hub: [logging.md](logging.md) · Operations index: [README.md](README.md)

## Multi-Tenancy Log Events

Emitted only while the tenancy platform switch (`multi_tenancy_enabled`) is **on**. When off, no tenant events exist. Unless noted, events are in `backend/logs/control-center.log`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `tenant.resolution.*` | INFO/WARN | `outcome` (`resolved`/`unknown`/`suspended`/`deleted`), `tenant_slug` | Per-request resolution outcome; WARN entries are fail-closed rejections |
| `tenant.claim.mismatch` | WARN | `tenant_id`, `subject` | Validated JWT tenant claim does not equal the resolved tenant; request rejected |
| `tenant.scope.violation` | WARN | `tenant_id`, `resource`, `surface` | Cross-tenant direct addressing stopped at the DB gateway; returned as not-found plus a `TenantAuditEvent` |
| `tenant.oidc.*` | ERROR/WARN | `tenant_id`, `provider_name`, `reason` | Per-tenant discovery, JWKS, or token validation failure (tenant-attributed `oidc.discovery.*` / `oidc.jwks.*` mirror) |
| `tenant.lifecycle.*` | INFO | `action`, `actor`, `tenant_slug` | Tenant create / suspend / resume / delete |
| `tenant.adoption.*` | INFO/ERROR | `rows_backfilled`, `tenant_slug` | Root-tenant (workspace `root`) adoption/backfill when the switch is first enabled; ERROR means incomplete adoption |
| `platform.settings.*` | INFO | `setting`, `value`, `actor` | Tenancy switch toggled; cache invalidation recorded |
| `tenant.signature.*` (CC, AR, CH) | WARN | `direction` (`sign`/`verify`), `reason` (`missing`/`tampered`/`stale`/`unsigned`) | Signing failure on CC outbound clients; verification failure in AR `ControlCenterCertificateMiddleware` and CH `ControlPlaneMiddleware` |
| `tenant.a2a.refused` (communication-hub.log) | WARN | `source_tenant_id`, `target_tenant_id` | A2A pair does not share a tenant; message not routed |
| `tenant.api_key.mismatch` (communication-hub.log) | WARN | `key_prefix`, `expected_tenant_id`, `actual_tenant_id` | MCP API key validated against a different tenant than the session context |
| `no_access_to_workspace` | WARN | `subject`, `workspace` | Authenticated user has no membership in the resolved workspace; returns HTTP 403 — this is a final authorization denial, **not** a re-auth loop trigger |

Troubleshooting quick patterns:

- Requests rejected before feature logic: search `control-center.log` for `tenant.resolution` and `tenant.rejected`
- Suspected isolation probing: search `control-center.log` for `tenant.scope` and `tenant.claim`, then filter platform audit events by `tenant_id`
- Executions rejected downstream: search `agent-runtime.log` for `tenant context` and `rejected`
- Routing/tool-call denials: search `communication-hub.log` for `tenant.denied` and `cross-tenant`
- A single tenant locked out: search `control-center.log` for `tenant.oidc` plus the tenant slug/id

---

## OIDC Identity Log Events

### Super Admin Auth Events

All super admin events are in `backend/logs/control-center.log`. Search for `superadmin.`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `superadmin.login.success` | INFO | `username`, `remote_ip`, `token_expires_at` | Super admin authenticated successfully |
| `superadmin.login.failure` | WARN | `username`, `remote_ip`, `reason` | Failed super admin login; `reason` is `invalid_credentials`, `disabled`, or `expired` |
| `superadmin.logout` | INFO | `username`, `session_duration_s` | Super admin session ended (logout or token expiry) |
| `superadmin.disabled` | INFO | `changed_by`, `previous_state` | Super admin account was disabled via config or API |
| `superadmin.enabled` | INFO | `changed_by`, `previous_state` | Super admin account was enabled via config or API |
| `superadmin.bootstrap` | INFO | `username`, `source` | Super admin credentials seeded on first launch; `source` is `env_var` or `config_default` |

### OIDC Config Service Events

All config events are in `backend/logs/control-center.log`. Search for `oidc.config.`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `oidc.config.created` | INFO | `provider_type`, `provider_name`, `issuer_url`, `actor` | New OIDC provider config created via UI or API |
| `oidc.config.updated` | INFO | `provider_type`, `provider_name`, `changed_fields[]`, `actor` | Existing provider config modified; `changed_fields` lists what was changed (never logs secret values) |
| `oidc.config.deleted` | WARN | `provider_type`, `provider_name`, `actor` | Provider config deleted; active sessions using this provider will fail on next validation |
| `oidc.config.test_connection` | INFO | `provider_type`, `provider_name`, `issuer_url`, `result` | Operator triggered OIDC connectivity test from UI |
| `oidc.config.test_login` | INFO | `provider_type`, `provider_name`, `result`, `claims_summary` | Operator triggered OIDC test login; `claims_summary` includes claim keys only (no values) |
| `oidc.config.migration` | INFO | `source_file`, `entries_migrated`, `result` | One-time migration from `config/identity.yaml` to database |

### OIDC Provider Connectivity Events

All connectivity events are in `backend/logs/control-center.log`. Search for `oidc.discovery.` or `oidc.jwks.`.

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

### Auth Middleware Decision Events

All auth middleware events are in `backend/logs/control-center.log`. Search for `auth.pipeline.` and `auth.oidc.`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `auth.pipeline.decision` | INFO | `tier`, `outcome`, `user_identity`, `provider_type`, `request_path` | Auth decision logged per request; `tier` is `super_admin`, `oidc_user`, `oidc_agent`, or `public` |
| `auth.pipeline.superadmin_skipped` | INFO | `remote_ip`, `reason` | Super admin tier skipped; `reason` is `disabled` or `no_superadmin_token` |
| `auth.pipeline.oidc_provider_not_found` | ERROR | `provider_type` | No active provider config found for the requested provider type in registry |
| `auth.oidc.jwt_invalid` | WARN | `provider_type`, `reason`, `token_hint` (first 8 chars) | JWT validation rejected; `reason` is `signature`, `expired`, `audience`, `issuer`, `claims`, or `unknown` |
| `auth.oidc.jwt_valid` | DEBUG | `provider_type`, `sub`, `expires_at` | JWT validated successfully (debug level to avoid logging every request in production) |

### OIDC Sensitive Data Exclusions

- Never log client secrets, OIDC client credentials, JWT payload bodies, or access/refresh token values
- Never log full super admin password hashes
- Log only the first 8 characters of JWT tokens as a `token_hint` for correlation
- Log claim key names for test login events but never claim values
- Use `changed_fields[]` for config mutations — list field names only, never values

---

## Security Guardrail Log Events

Security guardrail events detect potentially unsafe configuration practices at runtime. These are emitted at startup when configuration anomalies are detected.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `config.keycloak_admin_detected_in_runtime` | WARNING | `service_name` | `KEYCLOAK_ADMIN` or `KEYCLOAK_ADMIN_PASSWORD` found in CC environment; credentials are ignored by runtime but represent a security risk |

**Action**: Remove `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` from the Control Center service environment immediately. These variables should only be present on the setup tool/service environment.

---

## Certificate Security Log Events

### Log Sources

| Component | Log Source | Access |
|-----------|-----------|--------|
| `CertificateManager` | `control-center` container stdout | `docker compose logs control-center` or Loki: `{service="control-center"} \|= "cert."` |
| `CertificateAuthority` | `control-center` container stdout | Loki: `{service="control-center"} \|= "ca.init"` |

### Certificate Lifecycle Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `ca.initialized` | INFO | `ca_serial`, `expires_at` | CA certificate loaded or generated at backend startup |
| `ca.initialization_failed` | ERROR | `error` | CA failed to initialize; certificate issuance and validation unavailable until backend restarts |
| `cert.issued` | INFO | `instance_id`, `serial_number`, `expires_at`, `agent_type_id` | New certificate issued to an agent instance |
| `cert.renewed` | INFO | `instance_id`, `old_serial`, `new_serial`, `expires_at` | Certificate automatically renewed before expiry |
| `cert.renewal_failed` | ERROR | `instance_id`, `serial_number`, `error`, `attempt` | Certificate renewal attempt failed; agent runtime shuts down gracefully after expiry if unresolved |
| `cert.revoked` | INFO | `serial_number`, `reason`, `revoked_by` | Certificate revoked via API; rejection is effective immediately on all subsequent validation calls |
| `cert.validation.valid` | DEBUG | `serial_number`, `cn`, `requested_operation`, `validated_by_service` | Certificate validated successfully; logged per validation call |
| `cert.validation.failed` | WARN | `serial_number`, `cn`, `outcome`, `failure_reason`, `validated_by_service` | Certificate validation rejected; `outcome` is one of `expired`, `revoked`, `invalid_signature`, or `unknown` |

---

## Internal API Boundary Log Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `internal.allowlist.allowed` | INFO | `caller_type`, `caller_identity`, `certificate_type`, `method`, `endpoint`, `policy_version`, `trace_id` | Internal request is allowlisted for the caller profile |
| `internal.allowlist.denied` | WARN | `caller_type`, `caller_identity`, `certificate_type`, `method`, `endpoint`, `deny_reason`, `policy_version`, `trace_id` | Internal request denied by default policy before handler execution |
| `internal.allowlist.unknown_caller` | WARN | `caller_identity`, `method`, `endpoint`, `deny_reason`, `trace_id` | Caller identity missing, malformed, or unrecognized during policy evaluation |
| `internal.allowlist.certificate_mismatch` | WARN | `caller_type`, `certificate_type`, `method`, `endpoint`, `deny_reason`, `trace_id` | Presented certificate type does not match caller profile |
| `internal.allowlist.endpoint_not_allowlisted` | WARN | `caller_type`, `method`, `endpoint`, `deny_reason`, `policy_version`, `trace_id` | Caller attempted an endpoint outside the caller-scoped allowlist |
| `internal.revocation.check_failed` | ERROR | `caller_type`, `caller_identity`, `certificate_type`, `failure_mode`, `method`, `endpoint`, `trace_id` | Revocation status could not be validated for an internal request |
| `internal.system_tools.unauthenticated_rejected` | WARN | `endpoint`, `method`, `deny_reason`, `trace_id` | Internal system-tools route rejected due to missing or invalid service certificate |

### Required Fields for Boundary Events

All internal boundary events must include the following fields.

| Field | Requirement |
|-------|-------------|
| `timestamp` | ISO 8601 UTC with millisecond precision |
| `service_name` | Emitting service identifier |
| `trace_id` | Correlates to distributed trace |
| `span_id` | Correlates to specific trace span |
| `caller_type` | Normalized caller class (`agent_runtime`, `communication_hub`, or `unknown`) |
| `caller_identity` | Operational caller identity value used by policy |
| `certificate_type` | Presented certificate class used in evaluation |
| `endpoint` | Canonical internal route path |
| `method` | HTTP method |
| `decision` | `allowed` or `denied` |
| `deny_reason` | Required when denied; set to `none` when allowed |
| `policy_version` | Active allowlist policy version |
| `environment` | Deployment environment label |

### Sensitive Data Exclusions for Boundary Events

- Never log access tokens, refresh tokens, JWT bodies, decrypted secrets, private keys, or certificate private material.
- Never log raw system-tools request payloads.
- Use operational identifiers only for `caller_identity` (service name, mapped principal, or equivalent non-secret identifier).

### Boundary Incident Query Guide

- Filter by `caller_type` and `decision` first to isolate affected internal caller flows.
- Group denied events by `deny_reason` and `endpoint` to separate contract drift from identity failures.
- Use `trace_id` to pivot from deny events to distributed traces for cross-service timeline analysis.
- Correlate `internal.revocation.check_failed` with deny spikes to identify fail-closed impact.
