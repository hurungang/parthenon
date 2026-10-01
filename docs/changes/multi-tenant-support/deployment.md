# Deployment Notes: Multi-Tenant Support

Multi-tenancy ships as an **opt-in platform mode**. Deploying this change does **not** turn on tenancy: the platform switch (`multi_tenancy_enabled`) is a database platform setting seeded as `false` at startup, and every new code path is inert until it is deliberately enabled. Single-tenant behavior is preserved byte-for-byte.

Key sources: [tech-spec.md](tech-spec.md) (API changes, platform switch), [architecture.md](architecture.md) (tenant resolution, signed propagation), [implementation-plan.md](implementation-plan.md) (migration/adoption tasks 1.8, 1.9, 5.3, 5.4).

---

## 1. Environment Variables

**Primary switch is NOT an environment variable.** `multi_tenancy_enabled` is a row in the new `PlatformSetting` table (`backend/app/db/models/platform_setting.py`), seeded `false` at Control Center startup and toggled at runtime via the platform settings API / Platform Settings page. There is no env override — do not attempt to enable tenancy via env vars.

### New variables

| Variable | Services | Description | Secret |
|----------|----------|-------------|--------|
| `TENANT_CONTEXT_SIGNING_KEY` | CC, AR, CH | HMAC secret used to sign and verify the tenant context headers propagated over the existing mTLS channels. Must be a high-entropy random string (min 32 chars) with the **identical value on all three services** (CC signs; AR/CH verify only). Follows the same operational pattern as `AGENT_RUNTIME_BOOTSTRAP_KEY` / `SERVICE_BOOTSTRAP_KEY`. Changing it invalidates in-flight signed headers — rotate only in a maintenance window. | ✓ |
| `TENANT_ADDRESS_BASE_DOMAIN` | CC | Base domain used by subdomain tenant resolution: the Host-header label immediately left of this base is taken as the tenant slug (e.g. `acme.parthenon.example.com` → slug `acme`). Required only when tenant-address (subdomain) resolution is used; tenant-header resolution for API/MCP clients works without it. Must match the wildcard DNS/TLS domain configured in §2. | |

Supply the signing key via Docker secrets or Kubernetes Secrets — never plain-text config files or source control.

### Existing variables to review when enabling subdomain addressing

| Variable | Change required |
|----------|-----------------|
| `PLATFORM_API_BASE_URL` | Must resolve through the wildcard tenant domain so OIDC redirect URIs stay valid per tenant subdomain. |
| `AGENT_GATEWAY_BASE_URL` | Same wildcard-domain reachability when tenant-address mode is enabled. |
| Frontend OIDC settings (`VITE_OIDC_AUTHORITY`, `VITE_API_BASE_URL` in `frontend/.env.local` for local dev) | No new variables; verify the configured authority and API base are reachable from tenant subdomains (per-tenant OIDC providers are database-configured via `IdentityProviderConfig`, not env). |

No variables are removed. No changes to database, Redis, OTEL, certificate/mTLS, or guardrail variables.

---

## 2. Infrastructure Changes

**No new services or containers.** The same shared deployment serves all tenants: PostgreSQL, Redis, OTEL Collector, Keycloak (if bundled), Control Center, Agent Runtime, Communication Hub, frontend, and nginx are unchanged in topology. Multi-tenancy is a runtime mode of the existing three services.

Required infrastructure work **before** enabling subdomain tenant resolution:

- **Wildcard DNS** — add a wildcard record for the tenant address base domain (e.g. `*.parthenon.example.com`) pointing at the platform entry point (nginx host / Kubernetes ingress). The platform's own hostname must also resolve (directly or via the same wildcard).
- **Wildcard TLS certificate** — obtain a certificate covering the wildcard domain (e.g. `*.parthenon.example.com`) and install it:
  - Docker Compose (self-hosted): reference the wildcard certificate and key paths in the nginx TLS configuration; mount the files into the nginx container.
  - Kubernetes/Helm (production): store the wildcard certificate as a TLS secret on the ingress resource for the tenant domain.
  - This certificate is separate from the internal mTLS CA certificates — the existing service/agent-instance certificate chain is untouched.
- **nginx subdomain routing** — configure a wildcard server entry so **any** tenant subdomain routes to the same frontend and API upstreams (no per-tenant server blocks). Preserve the `Host` header end-to-end (no rewriting) — Control Center resolves the tenant slug from it. Tenant resolution for API/MCP clients via tenant header requires no nginx change.
- **Health/setup paths** — public health and first-run setup paths bypass tenant resolution in Control Center; confirm nginx routing to them is unchanged.
- **Platform admin console** — served by the existing frontend at the `/platform/*` route section; no separate deployment or host needed.

---

## 3. Migration Steps

Ordered and verifiable. The Alembic migration is **backward compatible**: it only adds new tables and nullable tenant reference columns with indexes — it drops nothing and makes nothing non-nullable.

### Phase A — Pre-deploy

- Confirm `docs/changes/multi-tenant-support/.change.yaml` has `has_db_changes: true` and review the generated migration in `backend/alembic/versions/`: correct `down_revision` chain, additive-only changes, reversible downgrade.
- Take a full PostgreSQL backup and verify it restores into a scratch database.
- Record the current database revision (run Alembic `current`) and note the latest revision file under `backend/alembic/versions/`.

### Phase B — Migrate and deploy

- Apply pending migrations to head (run Alembic `upgrade head`); verify with Alembic `current` that the database now shows the new revision.
- Verify the schema result on the live database: new tenant/platform tables exist; existing tables gained nullable tenant reference columns with indexes; no existing column was dropped or made non-nullable.
- Set `TENANT_CONTEXT_SIGNING_KEY` (identical value) on Control Center, Agent Runtime, and Communication Hub; set `TENANT_ADDRESS_BASE_DOMAIN` on Control Center if subdomain addressing is planned. Use the secrets mechanism for the signing key.
- Restart the stack in the mandatory order via `parthenon.ps1`: infra → control-center → agent-runtime → communication-hub → frontend (e.g. restart the backend services with `-Services backend`; use `-Force` to avoid prompts). Do not run dev servers directly.
- Verify startup: all three services healthy (`parthenon.ps1 status`); check `backend/logs/control-center.log` for configuration source logging and fail-fast validation success; confirm the `multi_tenancy_enabled` platform setting was seeded as `false` (platform settings read via the platform settings API once logged in as platform admin).

### Phase C — Verify single-tenant mode unchanged (switch off)

- Sign in through the normal OIDC flow; exercise the main domains (agents, MCP hub, skills, SOPs, scheduling, conversations, outputs) and confirm behavior and data are unchanged.
- Confirm API requests **without** any tenant headers succeed — resolution middleware, tenant-claim validation, and signed-header checks must be fully inert.
- Run the existing regression suites unmodified (backend, frontend with the JSON reporter per project convention, E2E) and confirm all pass; treat `backend/tests/test_auth_middleware_full.py` as the canary.

### Phase D — Enable multi-tenancy (only when ready — one-time adoption)

- **Prerequisite:** wildcard DNS and wildcard TLS are in place and verified (a test subdomain resolves, serves the valid certificate, and reaches the platform) **before** enabling subdomain resolution.
- Announce/plan the enablement: enabling triggers the **irreversible system-tenant adoption** — all existing rows are backfilled to the implicit system tenant, the existing administrator is granted platform-admin membership, and the existing identity provider becomes the system tenant's provider (no manual reconfiguration). The enable action itself is audited.
- As platform admin, enable `multi_tenancy_enabled` via the Platform Settings page (or the platform settings API with explicit confirmation); verify the settings cache invalidates across workers.
- Verify adoption: existing data remains fully accessible under the system tenant; platform admin console lists the system tenant; sign-in works; a second tenant can be created, onboarded, and isolated from system-tenant data.
- Configure per-tenant OIDC providers as tenants are created (tenant settings / identity-provider configuration UI); verify tenant-A credentials are rejected for tenant-B and unresolvable tenants fail closed.

---

## 4. Rollback Procedure

Rollback is **data-preserving by design** — the switch can be turned off and back on repeatedly without data loss.

### If the deployment fails before enabling multi-tenancy

- The switch is still `false` — no tenancy state exists. Roll back the code/images of Control Center, Agent Runtime, Communication Hub, and frontend **together** (the middleware and signed-header changes span all three services; mixed versions are unsupported).
- The applied migration does **not** need to be rolled back: it is additive and backward compatible with the previous code. Only downgrade if the tenant tables must be removed — see the irreversible-items note below.
- Restart via `parthenon.ps1` in the standard order (infra → control-center → agent-runtime → communication-hub → frontend) and re-run the single-tenant verification from §3 Phase C.

### If multi-tenancy was enabled and must be reverted

- **First** disable `multi_tenancy_enabled` via the Platform Settings page/API. This restores exact single-tenant behavior (middleware inert, registry platform-wide), keeps all data, and is audited. Do **not** roll back images while the switch is on.
- Then roll back code/images for all three services and frontend together; restart via `parthenon.ps1` in the standard order.
- Verify single-tenant smoke checks pass and Alembic `current` matches the expected revision.

### What cannot be rolled back

- **Tenant data created after enabling**: tenants, memberships, invitations, tenant audit events, per-tenant OIDC configurations, and any rows written while tenancy was on. Disabling the switch does not delete them, but rolling back the migration (downgrade) **drops** the tenant tables/columns — export/backup this data before any downgrade.
- The system-tenant adoption backfill itself: existing rows keep their system-tenant references after switch-off (data-preserving; harmless in single-tenant mode, reused if tenancy is re-enabled).
- Tenant deletions performed while enabled: tenant delete cascades are permanent; the slug becomes reusable and prior data is unrecoverable except from backup.
- General safety net: restore the Phase A PostgreSQL backup only as a last resort — it reverts **all** data to the backup point, not just tenancy state.

---

## 5. Master Deployment Update Instructions

Update `docs/master/deployment/` when this change is applied to master:

- **`environment-variables.md`** — add a "Multi-Tenancy" section with `TENANT_CONTEXT_SIGNING_KEY` (secret; CC/AR/CH, identical values) and `TENANT_ADDRESS_BASE_DOMAIN` (CC; subdomain mode only); state explicitly that the tenancy switch is the database platform setting `multi_tenancy_enabled` (seeded `false`), not an environment variable; note the wildcard-domain review items for `PLATFORM_API_BASE_URL` and `AGENT_GATEWAY_BASE_URL`.
- **`database-migrations.md`** — append the new Alembic revision from `backend/alembic/versions/` (revision id, description "multi-tenant support schema", date, additive/backward-compatible, reversible) to the chronological migration log.
- **`services.md`** — confirm no new containers; add a note that multi-tenancy is a runtime mode of the existing three services and that `TENANT_CONTEXT_SIGNING_KEY` must be set identically on CC, AR, and CH.
- **`first-time-deployment.md`** — add an optional "Enable Multi-Tenancy (SaaS mode)" step after initial single-tenant verification: wildcard DNS/TLS prerequisites (§2), the pre-enable adoption warning, the enable action via Platform Settings, and post-enable verification.
- **`rollback.md`** — add a multi-tenancy rollback section: disable the platform switch first (data-preserving), then roll back all services together; never roll back images while the switch is on; list the irreversible items (tenant data created post-enable, migration downgrade dropping tenant tables).
- **`configuration-files.md`** — no changes expected (no new config files; tenant OIDC config is database-backed).
- **`operational-runbooks.md`** — add a cross-reference to the enable/disable tenancy runbook and cross-tenant audit triage (details owned by the operations notes from this change).
- **`README.md`** — update the contents table entries above and add a "Multi-Tenancy Rollout Order" section mirroring §3: prerequisites → migrate → deploy → single-tenant verification → wildcard DNS/TLS → enable switch → adopt/verify.
