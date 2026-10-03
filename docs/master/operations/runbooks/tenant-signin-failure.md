# Runbook: Tenant Sign-In Failure

Applies when the tenancy platform switch (`multi_tenancy_enabled`) is **on**. When off, single-tenant sign-in applies — see [oidc-token-failure.md](oidc-token-failure.md) instead.

## Symptoms

- One tenant (or all tenants) cannot sign in while other tenants can
- `control-center.log` shows `tenant.resolution` outcome `suspended` (or `unknown`/`deleted`)
- `control-center.log` shows `tenant.oidc.*` discovery/JWKS/validation failures for one tenant only
- Browser cannot reach `https://<slug>.<base-domain>` at all — TLS warning or DNS failure, with **no** backend log entries
- Root workspace users: sign-in succeeds but the workspace resolves to the root tenant (workspace `root`); users without root membership get `no_access_to_workspace` and HTTP 403

## Resolution Steps

### 1. Triage by scope

1. All tenants fail → suspect platform-level cause (edge/DNS, root-tenant adoption, signing key); continue below.
2. One tenant fails only → suspect that tenant's status or its identity provider; go to step 3 or 4.

### 2. DNS / wildcard certificate missing (fails at the edge)

**Log indicator:** none — the request never reaches a backend service.

1. Verify the wildcard DNS record for the tenant address base domain (e.g. `*.parthenon.example.com`) resolves for the affected subdomain.
2. Verify the wildcard TLS certificate covers tenant subdomains and is correctly installed (nginx TLS config in Docker Compose; ingress TLS secret in Kubernetes).
3. Verify nginx routes any tenant subdomain to the same frontend/API upstreams with the `Host` header preserved (no rewriting).
4. Retry sign-in after the fix — backend logs will start showing `tenant.resolution` entries once traffic reaches Control Center.

### 3. Suspended tenant

**Log indicator:** `tenant.resolution` outcome `suspended` in `control-center.log` (active sessions were ended at suspend time).

1. Check tenant status in the platform admin console.
2. Confirm with the tenant admin that suspension is expected.
3. Resume via the platform tenant API; confirm `tenant.lifecycle` shows the resume action.
4. Have users sign in fresh — old sessions were terminated at suspend time and cannot be restored.

### 4. Per-tenant OIDC misconfiguration

**Log indicator:** `tenant.oidc.*` discovery, JWKS, or token validation failures for that tenant only in `control-center.log`.

1. Verify the tenant's provider config (issuer URL character-exact, client, scope uniqueness) via tenant settings — per-tenant providers are configured via `/system/identity-providers` with workspace binding; shared/platform-wide config lives under `/platform/identity-providers`.
2. Use the provider test-connection action.
3. If a JIT default role is set on the provider config, verify the role exists in that tenant (missing role blocks just-in-time users).
4. The registry reloads without restart — confirm `oidc.registry.reloaded` appears after the change; if `oidc.registry.reload_failed` appears, force a reload from the System Config UI or restart Control Center via `parthenon.ps1`.

### 5. Root workspace sign-in denials

**Log indicator:** `no_access_to_workspace` WARN with HTTP 403.

1. This is a final authorization denial (the user is authenticated but has no membership in the resolved workspace) — **do not** direct the user to re-authenticate; it will fail identically.
2. Grant the user membership in the workspace (or the correct workspace) via the platform admin console.
3. Platform routes resolve the root-tenant binding; if unbound platform requests return 403, verify the deployment completed the root-tenant adoption (see [tenant-adoption-and-scope-denials.md](tenant-adoption-and-scope-denials.md)).

## Recovery Validation

- Sign-in succeeds for the affected tenant/workspace.
- `control-center.log` shows `tenant.resolution` outcome `resolved` for the tenant slug.
- No new `tenant.oidc.*` ERROR entries for that tenant for 15 minutes.

## Notes

- A deleted tenant's slug is reusable; users with cached links from the old tenant may see `tenant.claim.mismatch` — see [tenant-adoption-and-scope-denials.md](tenant-adoption-and-scope-denials.md) for slug-reuse triage.
- Never log OIDC secrets or full token values while triaging.
- Enablement prerequisites (wildcard DNS/TLS) are documented in the deployment [first-time-deployment.md](../../deployment/first-time-deployment.md) Step 13.
