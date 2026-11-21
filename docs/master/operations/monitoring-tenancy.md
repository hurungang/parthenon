# Monitoring — Multi-Tenancy and Isolation Boundaries

Tenant-gated series and OTEL dimensions, the tenancy alerts, and the internal caller-segregation boundary signals (dashboard, trust alerts, metrics). Tenancy content applies only while the tenancy platform switch (`multi_tenancy_enabled`) is **on**; the boundary-enforcement signals are always active.

Hub: [monitoring.md](monitoring.md) · Operations index: [README.md](README.md)

## Multi-Tenancy

Applies only while the tenancy platform switch (`multi_tenancy_enabled`) is **on**. When off, no tenant resolution, scoping, signed headers, or tenant telemetry exist — single-tenant monitoring applies unchanged.

### Metrics

| Component | Metric | Why It Matters |
|-----------|--------|----------------|
| Control Center | `tenant.resolution_total` (labels: `outcome` = `resolved`/`unknown`/`suspended`/`deleted`, `tenant_slug`) | Core health of tenant resolution; any non-`resolved` outcome is a fail-closed rejection in multi-tenant mode |
| Control Center | `tenant.rejections_total` (labels: `reason` = `missing_context`/`claim_mismatch`/`unresolvable`/`signature_invalid`/`stale_timestamp`) | Fail-closed rejections before feature logic; sustained growth means clients or services are misconfigured |
| Control Center | `tenant.cross_tenant_attempts_total` (labels: `tenant_id`, `surface` = `api`/`scope`/`internal`/`a2a`/`mcp`) | **Security signal** — every attempt to address another tenant's data or route across tenants; isolated to the DB gateway, A2A broker, MCP server, and internal endpoints |
| Control Center | `tenant.oidc.validation_failures_total` (labels: `tenant_id`, `provider_name`, `reason` = `discovery`/`jwks`/`signature`/`claim_mismatch`) | Per-tenant OIDC health; a failing tenant provider blocks that tenant's sign-in and token validation only |
| Control Center | `tenant.lifecycle_events_total` (labels: `action` = `created`/`suspended`/`resumed`/`deleted`/`adopted`, `actor`) | Tenant lifecycle activity; unexpected suspend/resume/delete outside a change window requires review |
| Platform-wide | `tenant.resource_usage` (labels: `tenant_id`, `resource` = `active_sessions`/`scheduled_jobs`/`mcp_calls`) | Per-tenant consumption of sessions, schedules, and MCP calls for capacity planning and noisy-neighbor detection |

### OTEL dimensions

- When the switch is on, all three services add a `tenant_id` attribute to spans, metrics, and logs; traces for agent executions carry the owning tenant end to end.
- Dashboards and alerts should break down by `tenant_id`; keep a "no tenant attribute" panel — after enabling, any traffic in it is either the root tenant (workspace `root`), pre-adoption leftovers, or a bypass that must be investigated.
- When the switch is off, no tenant attributes are emitted; do not build tenant dashboards until it is enabled.

---

## Multi-Tenancy Alerts

Emitted only while the tenancy platform switch (`multi_tenancy_enabled`) is on. When off, none of these metrics exist — see the metrics table above.

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `CrossTenantAccessAttempt` | Any sustained non-zero rate on `tenant.cross_tenant_attempts_total` | Critical | **Security alert — treat as a possible isolation probe.** Triage by `surface` and `tenant_id`; check tenant audit events and decide whether to suspend the source tenant; see [runbooks/tenant-adoption-and-scope-denials.md](runbooks/tenant-adoption-and-scope-denials.md) |
| `TenantResolutionFailureSpike` | Fail-closed rejections (`tenant.rejections_total`) above baseline for 5 min | Warning | Usually a client missing the tenant header, DNS/wildcard issues, or a suspended/deleted tenant still sending traffic; see [runbooks/tenant-signin-failure.md](runbooks/tenant-signin-failure.md) |
| `TenantOidcValidationFailureSpike` | `tenant.oidc.validation_failures_total` for one tenant above baseline | Warning | Tenant's identity provider is unreachable or misconfigured; affects only that tenant; see [runbooks/tenant-signin-failure.md](runbooks/tenant-signin-failure.md) |
| `TenantLifecycleActivity` | Any `suspend`/`delete`/`adopted` event outside a maintenance window | Warning | Confirm the actor on the tenant lifecycle audit event is expected |
| `TenantNoisyNeighbor` | One tenant's share of `tenant.resource_usage` (sessions, schedules, MCP calls) exceeds the agreed threshold | Warning | Capacity/fairness review; consider per-tenant limits; watch for quota-exhaustion audit events |

---

## Service Segregation Boundary Enforcement
Dedicated dashboard panel group for internal caller boundary controls. Panels:

- **Allowed vs Denied Internal Calls** — `internal_allowlist_decisions_total` split by `caller_type` and `decision`.
- **Top Denied Endpoints** — `internal_allowlist_denied_total` grouped by `caller_type`, `endpoint`, and `reason`.
- **Unknown Caller and Certificate Mismatch Trends** — `internal_unknown_caller_denied_total` and `internal_caller_certificate_mismatch_denied_total` as separate time series.
- **Revocation Health** — `internal_revocation_check_failures_total` rate and `internal_revocation_check_latency_seconds` p99 for AR and CH.
- **Internal Authorization Latency** — `internal_authorization_duration_seconds` p99 by `caller_type` and `endpoint_group`.
- **Allowlisted Path 403 Regression** — `internal_http_403_total` for known allowlisted endpoint groups.
- **System Tools Unauthenticated Rejects** — `internal_system_tools_unauthenticated_rejected_total` by endpoint.

---

## Service-to-Service Trust Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `AgentRuntimeCertExpiringSoon` | Control Center reports AR cert expiring < 1 hour | Warning | Trigger manual cert renewal; check AR service health |
| `CommHubCertExpiringSoon` | Control Center reports CommHub cert expiring < 1 hour | Warning | Trigger manual cert renewal; check CommHub service health |
| `CertRenewalFailure` | `rate(parthenon_cc_cert_renewal_failures_total) > 0` for 2 min | Critical | AR or CommHub cannot renew cert; service will shut down after expiry |
| `CommHubNameResolverErrors` | `rate(parthenon_ch_name_resolver_errors_total) > 0` for 5 min | Warning | Agents sending malformed tool names or unknown server IDs; check agent code |
| `CommHubCertValidationFailures` | `rate(parthenon_ch_cert_validation_failures_total) > 0` for 5 min | Critical | Potential unauthorized tool calls; check for compromised agent certs |
| `InternalDenySpike` | `rate(internal_allowlist_denied_total) > baseline` for 5 min | Warning | Start deny spike triage in [runbooks/service-segregation-boundary-enforcement.md](runbooks/service-segregation-boundary-enforcement.md) |
| `NonAllowlistedEndpointAttemptDetected` | `rate(internal_endpoint_not_allowlisted_total) > 0` for 2 min | Critical | Treat as contract drift or privilege-overreach; follow boundary runbook |
| `UnknownCallerDenied` | `rate(internal_unknown_caller_denied_total) > 0` for 2 min | Critical | Validate identity extraction and caller normalization immediately; follow boundary runbook |
| `CallerCertificateMismatch` | `rate(internal_caller_certificate_mismatch_denied_total) > 0` for 2 min | Critical | Validate certificate class assignment and rotation state; follow boundary runbook and [runbooks/certificate-security.md](runbooks/certificate-security.md) |
| `RevocationCheckFailureSustained` | `rate(internal_revocation_check_failures_total) > 0` for 2 min | Critical | Keep fail-closed mode; restore revocation dependency and follow boundary runbook |
| `InternalAuthorizationLatencyHigh` | `internal_authorization_duration_seconds` p99 above threshold for 10 min | Warning | Investigate policy dependency and Control Center saturation |
| `Internal403RegressionAllowedPath` | `rate(internal_http_403_total{endpoint_group=~"allowlisted.*"})` above baseline for 5 min | Warning | Investigate allowlist regression on valid paths; follow boundary runbook |
| `SystemToolsUnauthenticatedAccessAttempt` | `rate(internal_system_tools_unauthenticated_rejected_total) > 0` for 2 min | Critical | Treat as security event; validate source and network path; follow boundary runbook |

---

## Boundary Enforcement Metrics

| Component | Metric | Why It Matters |
|-----------|--------|----------------|
| **Control Center Internal Policy** | `internal_allowlist_decisions_total` (labels: `caller_type`, `endpoint`, `method`, `decision`) | Shows allowed vs denied internal calls by caller profile |
| **Control Center Internal Policy** | `internal_allowlist_denied_total` (labels: `caller_type`, `endpoint`, `method`, `reason`) | Primary signal for deny-by-default enforcement and contract drift |
| **Control Center Internal Policy** | `internal_unknown_caller_denied_total` (labels: `endpoint`, `method`) | Detects missing or malformed caller identity mapping and spoofed internal identities |
| **Control Center Internal Policy** | `internal_caller_certificate_mismatch_denied_total` (labels: `caller_type`, `presented_cert_type`) | Detects wrong certificate class usage by internal callers |
| **Control Center Internal Policy** | `internal_endpoint_not_allowlisted_total` (labels: `caller_type`, `endpoint`, `method`) | Detects privilege-overreach attempts and stale client behavior |
| **Internal Callers (AR and CH)** | `internal_revocation_check_failures_total` (labels: `caller_service`, `failure_mode`) | Detects trust-chain instability that can force fail-closed internal traffic |
| **Internal Callers (AR and CH)** | `internal_revocation_check_latency_seconds` p99 (labels: `caller_service`) | Detects revocation dependency slowness before widespread request failures |
| **Control Center Internal API** | `internal_authorization_duration_seconds` p99 (labels: `caller_type`, `endpoint_group`) | Detects authorization gate regressions and dependency slowdown |
| **Control Center Internal API** | `internal_http_403_total` (labels: `caller_type`, `endpoint_group`) | Distinguishes expected deny-by-default events from allowlisted-path regressions |
| **Control Center System Tools** | `internal_system_tools_unauthenticated_rejected_total` (labels: `endpoint`) | Confirms service-certificate enforcement on sensitive system-tools paths |
