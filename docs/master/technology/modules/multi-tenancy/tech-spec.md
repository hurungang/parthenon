# Multi-Tenancy — Technical Spec

> Part of the [technology documentation](../../README.md).

## Overview

Multi-tenancy is an opt-in platform mode controlled by a `multi_tenancy_enabled` row in `PlatformSetting` (default false). When off, every multi-tenant code path is inert and the product behaves as a single-tenant deployment against an implicit **root tenant** (`Root`/`root`, flagged `is_system_tenant`; the design's `is_root_tenant` rename was recorded but not applied). When on, Control Center resolves the tenant exactly once per request into an immutable `TenantContext`, validates the JWT's tenant claim, and enforces row-level tenant scoping at the database gateway.

Key properties:

- **Control Center is the tenant authority and sole DB gateway.** Agent Runtime and Communication Hub are tenant-bound virtually: they verify and forward the signed context and never widen it.
- **Strict identity plane.** Every tenant uses only its own identity provider (own slot → shared → root slot for resolution, with no tenant-less widening); with multi-tenancy off only the root tenant's providers are used and non-root login is rejected.
- **Containment.** Permission grants — including wildcards — apply only within the session's resolved tenant. Platform modules are reachable only through root-tenant platform roles.
- **Strict signed propagation.** All CH/AR → CC internal calls carry HMAC-signed `X-Internal-Tenant-*` headers minted by CC; a missing/stale/invalid set fails closed (401) when tenancy is enabled.
- **Per-tenant configuration** lives in `TenantSetting` (workspace-scoped), separate from the tenant-agnostic `PlatformSetting`.

---

## Where the detail lives

| Page | Covers |
|------|--------|
| [tenancy-and-scoping.md](tenancy-and-scoping.md) | Tenancy switch, `TenantContext`, resolution middleware, signed propagation, row-level scoping, permission containment, root-tenant adoption, per-tenant OIDC registry and JIT admission, sign-in/workspace binding |
| [licensing-and-quotas.md](licensing-and-quotas.md) | Account-first registration, platform password accounts, licenses, quotas and the structured refusal contract, root membership protection, platform admin APIs and console, tenant workspace, default tenant-role presets, tenant audit |
| [tenant-settings.md](tenant-settings.md) | `TenantSetting` store and every tenant-scoped preference (workflow-generation/authoring model, optimizer model, resume TTL, assistant model pointer), plus the distinction from `PlatformSetting` |

Related modules: [identity](../identity/tech-spec.md) (RBAC and resource types), [control-center](../control-center/tech-spec.md) (data plane), [frontend](../frontend/tech-spec.md) (workspace surfaces), [conversations](../conversations/tech-spec.md) (resume TTL consumer).

---

## Component summary

| Area | Responsibility | Page |
|------|----------------|------|
| Switch + context | Platform switch, immutable `TenantContext`, `TENANT_UNSET`, `is_tenancy_enabled` | tenancy & scoping |
| Resolution middleware | Slug/header/subdomain → active tenant, fail-closed, method-aware bypasses, root default when off | tenancy & scoping |
| Signed propagation | HMAC header build/verify/forward; global egress hook | tenancy & scoping |
| Row-level scoping | `apply_tenant_scope` on `get_db`: SELECT/UPDATE/DELETE rewrite, INSERT stamping, miss audit, identity-plane exemption | tenancy & scoping |
| Permission containment | Tenant-scoped role collection, root blanket grant, no-membership gate | tenancy & scoping |
| OIDC registry + JIT | Per-tenant/shared/root provider slots, claim injection, default-tenant-role admission | tenancy & scoping |
| Registration & accounts | Atomic account-first signup, bcrypt platform accounts, tenant-bound JWTs | licensing & quotas |
| Licensing | Tiers, supersede semantics, free-tier defaults, effective limits | licensing & quotas |
| Quotas | Three enforcement points + calendar-month counter + structured 403 | licensing & quotas |
| Root protection | Immutable root membership, root-only alias edits, slug immutability | licensing & quotas |
| Platform / tenant APIs + UI | Platform console, tenant workspace, quota alerts, license panel | licensing & quotas |
| Default role presets | Four seeded presets, backfill sweep, root assignment | licensing & quotas |
| Tenant settings | Per-tenant key/value store and its consumers | tenant settings |

---

## Invariants

- **One session = one tenant.** There is no workspace switcher; root is the default workspace. The tenant claim is injected from the resolved login context, never from a request header.
- **Strict isolation.** No shared/NULL tenant data plane: every data-plane row is tenant-stamped, and internal data-plane calls without a valid signed context fail closed.
- **Containment.** Wildcard grants (even `*::*`) apply only inside the session tenant. Platform modules require a root-tenant platform role.
- **Fail closed, never re-authenticate.** An authenticated user without an active membership gets `403 no_access_to_workspace`; the frontend never bounces to login for that error.
- **Switch off means root.** Disabling tenancy returns the deployment to the root tenant with data preserved; enabling adopts existing data into root.
- **Settings are split by scope.** Deployment configuration is `PlatformSetting`; workspace preferences are `TenantSetting`.

## Recent capability highlights

- **Tenant settings expanded** — the resume-TTL window and the optimizer model now live in the per-tenant store; the authoring model remains the single source for plan generation (see [tenant-settings.md](tenant-settings.md)).
- **Durable paused turns respect tenant policy** — CC owns the resume window end to end, including checkpoint payload expiry (see [conversations](../conversations/tech-spec.md)).
- **Plan/optimization model selection is tenant-scoped** — no global fallback and no cross-tenant option leakage (see [agents — plans & optimization](../agents/plans-optimization.md)).

---

## Code Reference Map — cross-cutting

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TenantContext` / `TENANT_UNSET` | class / sentinel | Immutable per-request tenant context and accessors | `backend/app/core/tenant_context.py` |
| `is_tenancy_enabled` | function | Authority for "tenancy features apply" (root default context when off) | `backend/app/core/tenant_context.py` |
| `set_tenant_span_attributes` | function | Tenant attribution on spans/logs | `backend/app/core/tenant_context.py` |
| `build_tenant_signature_headers` / `verify_tenant_signature_headers` / `tenant_context_headers` | functions | HMAC sign/verify/emit (`X-Internal-Tenant-*`) | `backend/app/core/tenant_signature.py` |
| `forward_tenant_headers` / `verify_request_tenant_context` / `extract_tenant_signature_headers` / `reset_forwarded_tenant_headers` / `sign_context_for_authenticated_session` | functions | AR/CH re-emit (never sign), verify-if-present, header extraction, WS loopback signing | `backend/app/core/tenant_signature.py` |
| `internal_httpx_client` / `attach_forwarded_tenant_headers` | functions | Global CH/AR→CC egress hook stamping the forwarded signed set | `backend/app/core/internal_http.py` |
| `get_db` / `apply_tenant_scope` / `execute_unscoped` / `flush_scope_miss_audits` / `scope_for_session` | gateway | Row-level scoping choke point and identity-plane exemption | `backend/app/db/session.py`, `backend/app/db/tenant_scoping.py` |
| `require_internal_tenant_context` | dependency | Mandatory signed context on internal data-plane routers (401 fail-closed) | `backend/app/api/deps.py` |
| `TenantResolutionMiddleware` | middleware | Resolves/binds the tenant once per request | `backend/app/middleware/tenant_resolution.py` |
| `PlatformSetting` / `TenantSetting` | models | Tenant-agnostic vs tenant-scoped settings | `backend/app/db/models/platform_setting.py`, `tenant_setting.py` |
