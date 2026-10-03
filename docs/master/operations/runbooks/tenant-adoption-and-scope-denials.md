# Runbook: Tenant Adoption and Scope Denials

Applies when the tenancy platform switch (`multi_tenancy_enabled`) is **on**, typically shortly after enabling it.

## Symptoms

- 403/404 spikes after enabling the tenancy switch
- `control-center.log` shows `tenant.adoption.*` ERROR (incomplete root-tenant adoption)
- `control-center.log` shows `oidc.registry.reload_failed` or a missing `oidc.registry.reloaded` after provider edits or tenant onboarding
- Existing data appears "missing" (404) or forbidden (403) for legacy records
- Sustained non-zero `tenant.cross_tenant_attempts_total` (possible isolation probing)

## Resolution Steps

### 1. Unadopted legacy data (403/404 spikes)

**Log indicator:** `tenant.adoption` ERROR in `control-center.log`.

1. Confirm the ERROR entry — it means the one-time adoption backfill (all existing rows → root tenant, workspace `root`) was incomplete.
2. Re-run adoption via the platform settings/admin surface.
3. Compare pre/post record counts for the affected resource types to confirm every legacy row now carries a tenant reference.
4. If adoption reports success but denials persist, check for rows created during the adoption window (race) and re-run once more.

### 2. Provider registry cache staleness

**Log indicator:** `oidc.registry.reload_failed` in `control-center.log`, or no `oidc.registry.reloaded` event after a provider change.

1. Verify the per-tenant OIDC registry is serving the edited config — stale config causes validation failures for the affected tenant only.
2. Force a registry reload from the System Config UI (save any provider config to trigger reload).
3. If reloads keep failing, restart Control Center via `parthenon.ps1` (backend services order: CC first, then AR, then CH).

### 3. Cross-tenant scope denials / isolation probing

**Log indicator:** `tenant.scope.violation` or `tenant.claim.mismatch` WARN in `control-center.log`; `tenant.cross_tenant_attempts_total` growing.

1. Treat sustained cross-tenant attempts as a **security signal**; triage by `surface` (`api`/`scope`/`internal`/`a2a`/`mcp`) and `tenant_id`.
2. Filter platform audit events by `tenant_id` — cross-tenant attempts and quota-exhaustion events are recorded as tenant audit events.
3. Fail-closed behavior is correct: cross-tenant direct addressing returns not-found plus an audit event; do not loosen scoping to "fix" denials.
4. If a source tenant is probing, suspend it via the platform tenant API after confirming with the tenant admin.
5. If the source is a misconfigured client of a legitimate tenant, correct the client's tenant header/addressing configuration instead.

### 4. Deleted-tenant slug reuse confusion

**Log indicator:** `tenant.lifecycle` shows a delete + create pair on the same slug; `tenant.claim.mismatch` clusters afterwards.

1. Old user tokens carry the deleted tenant and fail with `tenant.claim.mismatch` — expected; direct users to sign in fresh at the tenant address.
2. Sessions of the deleted tenant were ended at delete time; do not attempt to restore them.
3. If slug reuse is not desired, treat slugs as reserved after deletion (platform admin process).

## Recovery Validation

- `tenant.adoption` shows no ERROR entries; legacy record counts match post-adoption tenant-bound counts.
- `oidc.registry.reloaded` appears after provider changes; no `reload_failed` for 15 minutes.
- `tenant.cross_tenant_attempts_total` returns to baseline; audit events show no new probing.

## Notes

- The root-tenant adoption itself cannot be rolled back row-by-row; disabling the switch keeps the root-tenant references (data-preserving, reused on re-enable).
- For rollback of the whole feature, follow the disable-first procedure in [rollback.md](../../deployment/rollback.md) (Change-Specific Rollback: Multi-Tenant Support).
