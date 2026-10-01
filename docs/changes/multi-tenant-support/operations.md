# Operations Notes: Multi-Tenant Support

Applies when the tenancy platform switch (`multi_tenancy_enabled`) is **on**. When off, no tenant resolution, scoping, signed headers, or tenant telemetry exist — all items below are inert and single-tenant operations apply unchanged.

---

## 1. Monitoring

### New metrics (labels in parentheses)

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
- Dashboards and alerts should break down by `tenant_id`; keep a "no tenant attribute" panel — after enabling, any traffic in it is either the system tenant, pre-adoption leftovers, or a bypass that must be investigated.
- When the switch is off, no tenant attributes are emitted; do not build tenant dashboards until it is enabled.

### New alerts

| Alert | Trigger | Response |
|-------|---------|----------|
| `CrossTenantAccessAttempt` | Any sustained non-zero rate on `tenant.cross_tenant_attempts_total` | **Security alert — treat as a possible isolation probe.** Triage by `surface` and `tenant_id`; check audit events and decide whether to suspend the source tenant |
| `TenantResolutionFailureSpike` | Fail-closed rejections (`tenant.rejections_total`) above baseline for 5 min | Usually a client missing the tenant header, DNS/wildcard issues, or a suspended/deleted tenant still sending traffic |
| `TenantOidcValidationFailureSpike` | `tenant.oidc.validation_failures_total` for one tenant above baseline | Tenant's identity provider is unreachable or misconfigured; affects only that tenant |
| `TenantLifecycleActivity` | Any `suspend`/`delete`/`adopted` event outside a maintenance window | Confirm the actor on the lifecycle audit event is expected |
| `TenantNoisyNeighbor` | One tenant's share of `tenant.resource_usage` (sessions, schedules, MCP calls) exceeds agreed threshold | Capacity/fairness review; consider per-tenant limits |

---

## 2. Logging

All files live in `backend/logs/` (rotated at ~10 MB; `.1` and `.2` are the two most recent rolls). `otel.log` covers export diagnostics only.

| File | What to expect | Search keywords |
|------|----------------|-----------------|
| `control-center.log` | Tenant resolution decisions and fail-closed rejections; JWT tenant-claim mismatches; row-level scope violations; per-tenant OIDC discovery/JWKS/token validation errors; tenant lifecycle actions; platform switch toggles and adoption runs; audit-event writes; signed-header signing on outbound internal calls | `tenant.resolution`, `tenant.rejected`, `tenant.claim`, `tenant.scope`, `tenant.oidc`, `tenant.lifecycle`, `tenant.adoption`, `platform.settings` |
| `agent-runtime.log` | Signed tenant-header verification rejections on execute/resume/terminate/intervene; execution bound to (or refused for lack of) verified tenant context | `tenant context`, `rejected`, `tenant.signature` |
| `communication-hub.log` | Tenant routing denials: cross-tenant A2A refusals, MCP session tenant-binding failures, API-key/tenant mismatches, tenant-filtered tool listing/calls | `tenant.denied`, `cross-tenant`, `tenant.context`, `api_key.auth.failed` |
| `otel.log` | Export diagnostics for tenant-attributed telemetry; errors shipping spans/logs that carry `tenant_id` | `tenant`, export errors |

### Event prefixes (control-center.log unless noted)

| Prefix | Level | Meaning |
|--------|-------|---------|
| `tenant.resolution.*` | INFO/WARN | Per-request resolution outcome (resolved / unknown / suspended / deleted); WARN entries are fail-closed rejections |
| `tenant.claim.mismatch` | WARN | Validated JWT tenant claim does not equal the resolved tenant; request rejected |
| `tenant.scope.violation` | WARN | Cross-tenant direct addressing stopped at the DB gateway; returned as not-found plus a `TenantAuditEvent` |
| `tenant.oidc.*` | ERROR/WARN | Per-tenant discovery, JWKS, or token validation failure (mirrors existing `oidc.discovery.*` / `oidc.jwks.*` events, tenant-attributed) |
| `tenant.lifecycle.*` | INFO | Create / suspend / resume / delete; `actor` and `tenant_slug` included |
| `tenant.adoption.*` | INFO/ERROR | System-tenant adoption/backfill when the switch is first enabled; ERROR means incomplete adoption |
| `platform.settings.*` | INFO | Tenancy switch toggled; cache invalidation recorded |
| `tenant.signature.*` (CC, AR, CH) | WARN | Signing failure on CC outbound clients; verification failure (missing / tampered / stale / unsigned) on AR `ControlCenterCertificateMiddleware` and CH `ControlPlaneMiddleware` |
| `tenant.a2a.refused` (communication-hub.log) | WARN | A2A pair does not share a tenant; message not routed |
| `tenant.api_key.mismatch` (communication-hub.log) | WARN | MCP API key validated against a different tenant than the session context |

### Troubleshooting quick patterns (config.yaml style)

- Requests rejected before feature logic: search `control-center.log` for `tenant.resolution` and `tenant.rejected`
- Suspected isolation probing: search `control-center.log` for `tenant.scope` and `tenant.claim`, then filter platform audit events by `tenant_id`
- Executions rejected downstream: search `agent-runtime.log` for `tenant context` and `rejected`
- Routing/tool-call denials: search `communication-hub.log` for `tenant.denied` and `cross-tenant`
- A single tenant locked out: search `control-center.log` for `tenant.oidc` plus the tenant slug/id

---

## 3. Common Issues

### Tenant cannot sign in

- **Suspended tenant** — resolution resolves but sign-in is blocked; `control-center.log` shows `tenant.resolution` outcome `suspended` (or active sessions ended at suspend time). Check tenant status in the platform admin console; resume via the platform tenant API after confirming with the tenant admin.
- **Per-tenant OIDC misconfiguration** — `control-center.log` shows `tenant.oidc.*` discovery or JWKS failures for that tenant only. Verify the tenant's provider config (issuer URL, client, scope uniqueness) via tenant settings; use the provider test-connection action; the registry reloads without restart.
- **DNS / wildcard certificate missing** — the browser cannot reach `https://<slug>.<base-domain>` (TLS warning or DNS failure) before any backend log appears. Verify the wildcard DNS record for the base domain and that the wildcard certificate covers tenant subdomains; check nginx routing. Backend logs will show nothing — this fails at the edge.

### 403/404 spikes after enabling the switch

- **Unadopted legacy data** — rows created before the switch that were never bound to the system tenant appear "missing" (404) or forbidden (403). Search `control-center.log` for `tenant.adoption`; an ERROR there means adoption was incomplete. Re-run adoption, then compare pre/post record counts for affected resource types.
- **Provider registry cache staleness** — the per-tenant OIDC registry serves stale provider config after provider edits or tenant onboarding, causing validation failures. Search `control-center.log` for `oidc.registry.reload_failed` or a missing `oidc.registry.reloaded` event after the change; force a registry reload from the System Config UI. If reloads keep failing, restart Control Center via `parthenon.ps1`.

### Agent Runtime / Communication Hub "tenant context missing" rejections

- **Stale service after enabling the switch** — AR/CH instances started before the switch was enabled do not accept signed tenant headers (or run pre-tenant code), so every internal call is rejected. Search `agent-runtime.log` and `communication-hub.log` for `tenant context` and `rejected`.
- **Resolution** — restart in enforced order with `parthenon.ps1`: backend services (Control Center first, then Agent Runtime, then Communication Hub). CC must be running before AR/CH so certificate bootstrap succeeds. Verify by confirming signed-header acceptance in both logs and a healthy `parthenon.ps1 status`.
- **Signature failures after restart** — search for `tenant.signature` in AR/CH logs; a persistent `signature_invalid` means the signing key configuration differs between CC and the downstream service; align the key configuration and restart CC first.

### Deleted tenant address reuse confusion

- **Slug reuse** — a deleted tenant's slug becomes reusable; a new tenant on the same subdomain inherits old bookmarks. Old user tokens fail with `tenant.claim.mismatch` (they carry the old tenant); search `control-center.log` for `tenant.lifecycle` to see the delete + create pair.
- **User impact** — users with cached links see rejections or the new tenant's discovery page; direct them to sign in fresh at the tenant address. Sessions of the deleted tenant were ended at delete time; do not attempt to "restore" old sessions.
- **Guardrail** — if reuse is not desired, treat slugs as reserved after deletion (platform admin process); monitor for `tenant.claim.mismatch` clusters on a recently reused slug as the tell-tale sign.

---

## 4. Master Operations Update Instructions

Update `docs/master/operations/` when this change is applied:

- **`monitoring.md`** — add a "Multi-Tenancy" section: the six metrics above (with labels), the five alerts (`CrossTenantAccessAttempt` flagged security-critical, `TenantResolutionFailureSpike`, `TenantOidcValidationFailureSpike`, `TenantLifecycleActivity`, `TenantNoisyNeighbor`), and the `tenant_id` OTEL dimension note (emitted only when the switch is on).
- **`logging.md`** — extend the Per-Component Log Events table with rows for Tenant Resolution Middleware, Tenant Scoping/DB Gateway, Per-Tenant OIDC Registry, Tenant Lifecycle/Audit, signed-header verification on Agent Runtime and Communication Hub, and tenant-denied A2A/MCP/API-key events in CH; add the event prefixes from section 2 with levels and key fields.
- **`README.md`** — add a "Tenancy" dashboard row to Dashboards; add tenant log-source keywords to the Log Sources section; append the new runbooks to the Runbooks table.
- **`runbooks/`** — create three runbooks following existing format:
  - `tenant-signin-failure.md` — suspended tenant vs per-tenant OIDC failure vs DNS/wildcard cert triage (symptom: one or all tenants cannot sign in; `tenant.resolution` / `tenant.oidc.*` in `control-center.log`).
  - `tenant-adoption-and-scope-denials.md` — 403/404 spikes after enabling: adoption completeness, registry cache staleness, re-run/reload procedures (symptom: `tenant.adoption.*` ERROR or `oidc.registry.*` in `control-center.log`).
  - `tenant-context-missing.md` — AR/CH rejections after enabling the switch; restart order via `parthenon.ps1`; signature-key alignment (symptom: `tenant context` / `rejected` in `agent-runtime.log` / `communication-hub.log`).
- **`runbooks/oidc-token-failure.md`** — update: validation is per-tenant when the switch is on; add the `tenant.oidc.*` search pattern and the note that one tenant's provider failure does not affect others.
- **`runbooks/api-key-auth.md`** — update: API keys are tenant-bound in multi-tenant mode; add `tenant.api_key.mismatch` as a failure reason and per-tenant filtering of `load_skills`/tool calls.
- **`runbooks/service-segregation-boundary-enforcement.md`** — add cross-reference: signed tenant-header verification is an additional internal-boundary check; `tenant.signature.*` denials are triaged alongside certificate denials.
- Do **not** modify runbooks that tenancy does not touch (certificates lifecycle, guardrails, scheduling mechanics) beyond a one-line note where a tenant dimension now appears in their logs.
