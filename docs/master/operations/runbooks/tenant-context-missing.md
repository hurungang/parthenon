# Runbook: Tenant Context Missing (Agent Runtime / Communication Hub)

Applies when the tenancy platform switch (`multi_tenancy_enabled`) is **on** and internal service calls are rejected for missing or invalid tenant context.

## Symptoms

- Agent Runtime and/or Communication Hub reject every internal call after the switch was enabled
- `agent-runtime.log` or `communication-hub.log` shows `tenant context` and `rejected` entries
- `tenant.signature.*` WARN entries in AR/CH logs (`missing` / `tampered` / `stale` / `unsigned`)
- Agent executions cannot start; sessions queue but never run

## Resolution Steps

### 1. Stale service after enabling the switch

**Log indicator:** rejections begin immediately after the switch was enabled; AR/CH instances started before enablement do not accept signed tenant headers.

1. Confirm which services are stale: check AR/CH startup times against the switch-enable timestamp (`platform.settings` event in `control-center.log`).
2. Restart in enforced order via `parthenon.ps1`: backend services — Control Center first, then Agent Runtime, then Communication Hub. CC must be running before AR/CH so certificate bootstrap succeeds.
3. Verify signed-header acceptance appears in both AR and CH logs and `parthenon.ps1 status` reports all services healthy.

### 2. Signature failures after restart

**Log indicator:** persistent `tenant.signature` with reason `signature_invalid` in AR/CH logs.

1. A persistent `signature_invalid` means the `TENANT_CONTEXT_SIGNING_KEY` configuration differs between Control Center and the downstream service.
2. Align the key configuration — the identical value must be set on CC, AR, and CH (see the deployment [environment-variables.md](../../deployment/environment-variables.md) §Multi-Tenancy).
3. Restart CC first, then AR/CH, via `parthenon.ps1`.
4. Do not rotate the key during business hours: changing it invalidates in-flight signed headers; rotate only in a maintenance window.

### 3. Missing context from individual clients

**Log indicator:** `tenant.rejections_total` with reason `missing_context` in Control Center metrics/logs; only specific API/MCP clients fail.

1. Confirm the client sends the tenant header (API/MCP clients use tenant-header resolution; browser traffic uses subdomain resolution via `TENANT_ADDRESS_BASE_DOMAIN`).
2. Verify the request reaches the platform through a tenant subdomain that resolves, or with the tenant header set — otherwise resolution fails closed (HTTP 403). Fail-closed is correct behavior; fix the client, not the middleware.
3. If `stale_timestamp` dominates, check for clock skew between services.

## Recovery Validation

- AR/CH logs show signed-header acceptance with no `tenant context` rejections for 15 minutes.
- `parthenon.ps1 status` reports all backend services healthy.
- A test agent execution completes end-to-end with a `tenant_id`-attributed trace.

## Notes

- Signed tenant-header verification is an additional internal-boundary check layered on mTLS — triage `tenant.signature.*` denials alongside certificate denials per [service-segregation-boundary-enforcement.md](service-segregation-boundary-enforcement.md).
- Never disable signature verification to restore traffic; fix the key alignment instead.
- All three backend services must be deployed together; mixed pre/post-tenant versions are unsupported.
