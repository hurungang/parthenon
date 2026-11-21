# Multi-Tenancy — Tenancy and Scoping

> Part of the [multi-tenancy hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

This page covers the tenancy mechanism itself: the platform switch, per-request tenant resolution and context, signed context propagation across services, row-level data scoping, permission containment, the root tenant, per-tenant identity providers with JIT admission, and the frontend sign-in/workspace binding flow.

**Resolution.** `TenantResolutionMiddleware` (registered after `JWTAuthMiddleware` so it executes first) resolves slug/header/subdomain → active tenant and is fail-closed when the switch is on. Public health/setup/auth paths, method-aware GET-only login probes, internal service-to-service paths and the platform admin surface are bypassed. When the switch is off it binds the **root tenant** as the default context and stamps `tenancy_enabled = false`.

**Containment.** Permission evaluation collects only roles whose `tenant_id` equals the resolved tenant (global tenant-less role collection was removed; legacy globals were re-homed into the root tenant by migration `b8e4f2a6c9d1`). Platform administration lives in the root tenant's `Platform Admin` role; the root blanket grant applies to customer tenants; the super-admin bypass is unchanged.

**Scoping.** `apply_tenant_scope` on `get_db` rewrites SELECT/UPDATE/DELETE, stamps INSERTs, audits cross-tenant misses and verifies signed headers on internal traffic. Identity-plane statements opt out through the statement-scoped `execute_unscoped` exemption. An authenticated user without an ACTIVE membership in the resolved tenant receives `403 no_access_to_workspace` (never a re-auth redirect).

---

## Key Components

| Component | Description |
|-----------|-------------|
| Tenancy switch | `PlatformSetting` + `PlatformSettingsService`: cached key/value store, switch row seeded false at startup with write-through invalidation |
| Tenant context | Immutable `TenantContext` on `request.state`, `TENANT_UNSET` sentinel, `get/set/require_tenant_context`; `is_tenancy_enabled` distinguishes "tenancy features apply" from "a context exists" |
| Resolution service + middleware | Slug/header → active tenant, fail-closed, short-TTL cache; root default when off; audited rejections |
| Signed propagation | CC signs the `X-Internal-Tenant-*` set on internal clients; AR (`ControlCenterCertificateMiddleware`) and CH (`ControlPlaneMiddleware`) verify but never sign; forwarders re-emit |
| Row-level scoping | Closure-factory criteria (lambda-SQL cache safe), INSERT stamping, miss auditing, identity-plane exemption |
| Permission containment | Tenant-scoped role collection/policy lookup; root blanket grant; no-membership gate |
| Per-tenant OIDC registry | `(tenant, scope)` cache with own → shared → root resolution; validation-time tenant-claim injection; per-tenant scope uniqueness |
| JIT default role | `DefaultTenantRole` presets + admission hook on first OIDC sign-in |
| Tenant lifecycle services | `TenantService`, `TenantProvisioningService`, `TenantAdoptionService`, `TenantAuditService`, root-tenant helpers |

### Root tenant

The root tenant is the platform's own workspace (`root` / `Root`, `is_system_tenant`). The design's rename to `is_root_tenant` was recorded but not applied (119 occurrences across 58 files exceeds the 30-file threshold); the column is the alias. Exactly one row carries the flag. Root membership holders receive the tenant-wide blanket grant except `platform::*`, which comes from the root `Platform Admin` role.

---

## Data Access Patterns

- **One session = one tenant.** Every `get_db` session carries the resolved tenant scope; there is no cross-tenant read path in application code.
- **Identity plane exemption is statement-scoped.** `execute_unscoped` executes one statement outside the scope (PlatformUser-by-sub, JIT upserts, operator Identity-by-subject). Caveat: exempt-loaded entities enter the identity map; consume the loaded object rather than re-`get()`ing it.
- **Internal traffic verifies at the gateway.** `/api/v1/internal/*` requests verify the signed header set before any query runs; `require_internal_tenant_context` fails closed on data-plane routers.
- **The tenant claim is never taken from a request header.** It is injected at validation time from the resolved login context.
- **Provider resolution never widens.** Own slot → shared (tenant-less) slot → root slot; none of the three fails closed.

---

## Code Reference Map

### Tenancy entities and scoping

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `Tenant` | model | Tenant entity: unique name/slug, status, system-tenant flag, admin contact | `backend/app/db/models/tenant.py` |
| `Tenant.is_system_tenant` | column | Retained flag identifying the root tenant (alias of `is_root_tenant`) | `backend/app/db/models/tenant.py` |
| `TenantUserMembership` | model | User membership with tenant-scoped role; `is_root` immutable | `backend/app/db/models/tenant_membership.py` |
| `TenantAuditEvent` / `TenantAuditEventType` | model / enum | Tenant lifecycle/security audit events | `backend/app/db/models/tenant_audit_event.py` |
| `PlatformUser` / `PlatformUser.password_credential` | model / field | Tenant-agnostic platform account; hashed password for self-managed accounts | `backend/app/db/models/platform_user.py` |
| `Role` / `Identity` | models | Tenant references; per-tenant name uniqueness (`uq_roles_tenant_name` + partial global index) | `backend/app/db/models/identity.py` |
| `AgentType`, `AgentIdentity`, `AgentJob`, `AgentA2ASession`, `McpServer`, `Skill`, `Sop`, `ScheduledJob`, `ConversationSession`, `ResultRecord`, `NotificationChannel`, `AgentApiKey`, `IdentityProviderConfig` | models | Data-plane entities carrying `tenant_id` | `backend/app/db/models/` |
| models `__init__` | module | Exports tenant models for autogenerate | `backend/app/db/models/__init__.py` |
| `apply_tenant_scope` | function | Gateway scoping: ORM rewriting, INSERT stamping, miss audits, internal header verification | `backend/app/db/tenant_scoping.py` |
| `execute_unscoped` | function | One-statement identity-plane exemption (`{"tenant_scope": "exempt"}`) | `backend/app/db/tenant_scoping.py` |
| `flush_scope_miss_audits` / `scope_for_session` | functions | Probe audit persistence; session tenant read | `backend/app/db/tenant_scoping.py` |
| `_tenant_criteria_factory` / `_platform_user_criteria_factory` / `filter_platform_users_to_tenant` / `_has_automatic_scope_strategy` | functions | Closure criteria factories and PlatformUser membership-join isolation | `backend/app/db/tenant_scoping.py` |
| platform users router | router | Tenant-context isolation for platform-user list/detail/mutation | `backend/app/api/v1/platform_users.py` |
| `TenantContext` / `TENANT_UNSET` / `set_tenant_span_attributes` / `is_tenancy_enabled` | module | Context, accessors and OTEL attribution | `backend/app/core/tenant_context.py` |

### Propagation and middleware

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `build_tenant_signature_headers` / `verify_tenant_signature_headers` / `tenant_context_headers` / `forward_tenant_headers` / `verify_request_tenant_context` | functions | Signed header set lifecycle | `backend/app/core/tenant_signature.py` |
| `tenant_address_base_domain` / `tenant_context_signing_key` | settings | Resolution base domain and HMAC key | `backend/app/core/config.py` |
| `PlatformSettingsService` | class | Cached platform setting reads/writes, switch bootstrap | `backend/app/services/tenancy/platform_settings_service.py` |
| `TenantResolutionService` | class | Slug/header → active tenant, fail-closed, TTL cache, `TENANT_HEADER` | `backend/app/services/tenancy/tenant_resolution_service.py` |
| `TenantResolutionMiddleware` / `BYPASS_GET_PATHS` / `_is_bypassed` | middleware / constant / function | Once-per-request resolution, method-aware GET-only bypasses, root default when off | `backend/app/middleware/tenant_resolution.py` |
| `JWTAuthMiddleware` / `_check_tenant_claim` / `_audit_claim_mismatch` | middleware / functions | Tenant-claim mismatch rejection | `backend/app/middleware/auth.py` |
| `validate_raw_token` / `_try_oidc_token` / `_inject_tenant_claim` | functions | Token validation with per-tenant provider resolution and claim injection | `backend/app/middleware/auth.py` |
| `_try_platform_account_token` | function | Auth tier validating platform-account JWTs outside the OIDC registry | `backend/app/middleware/auth.py` |
| `create_app` | function | Registers the resolution middleware after auth (so it runs first) | `backend/app/main.py` |
| `authorize_identity` / `_membership_grants` | functions | Tenant-bound authorisation, membership grants, no-workspace-access gate | `backend/app/api/deps.py` |
| `NoWorkspaceAccessError` / `no_workspace_access_handler` | exception / handler | Flat `403 no_access_to_workspace` (an authorization denial, not an auth failure) | `backend/app/api/deps.py`, `backend/app/main.py` |
| `require_permission` | function | Tenant-bound RBAC dependency factory | `backend/app/api/deps.py` |
| `PermissionEngine` / `PermissionEngine.authorize` / `PermissionEngine._get_effective_role_ids` | class / methods | Tenant-scoped role collection and policy lookup (containment) | `backend/app/services/permissions/permission_engine.py` |
| `UserCacheService` identity-plane exemption | behaviour | By-sub/by-email/by-subject lookups use `execute_unscoped` | `backend/app/services/permissions/user_cache_service.py` |
| `ResourceTypeManifest` / `MODULE_GROUPS` | constants | `platform::*` / `tenant::*` resource types | `backend/app/core/resource_types.py` |

### Root tenant and adoption

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ROOT_TENANT_SLUG` / `ROOT_TENANT_NAME` / `PLATFORM_ADMIN_ROLE_NAME` | constants | Canonical root identity and platform role name | `backend/app/services/tenancy/root_tenant.py` |
| `ensure_root_tenant` / `rehome_global_roles` / `seed_root_platform_admin_role` / `get_root_tenant` / `get_root_tenant_id` / `get_root_tenant_context` / `invalidate_root_tenant_cache` | functions | Idempotent root-tenant helpers (short-TTL cached) | `backend/app/services/tenancy/root_tenant.py` |
| `TenantService` / `TenantProvisioningService` / `TenantAdoptionService` / `TenantAuditService` | classes | Tenant lifecycle, onboarding, adoption (`ensure_root_tenant`, `validate_disable`), audit | `backend/app/services/tenancy/` |
| `BootstrapService._ensure_system_admin_role` | method | Bootstrap system-admin role created root-scoped | `backend/app/services/permissions/bootstrap_service.py` |
| `_sweep_root_tenant` | function | Startup ensure/rename/re-home/seed sweep | `backend/app/main.py` |
| migration `b8e4f2a6c9d1` | migration | Root rename, global role re-homing, root Platform Admin seeding/assignment | `backend/alembic/versions/b8e4f2a6c9d1_phase11_root_tenant_and_global_role_rehoming.py` |

### Strict tenant isolation (as built)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `require_internal_tenant_context` | dependency | Mandatory signed context on internal data-plane routers (401 fail-closed; root-default when off) | `backend/app/api/deps.py` |
| `internal_httpx_client` / `attach_forwarded_tenant_headers` | functions | Global CH/AR→CC egress hook stamping the forwarded signed set | `backend/app/core/internal_http.py` |
| `sign_context_for_authenticated_session` | function | Signs the WS-chat loopback context for an authenticated session | `backend/app/core/tenant_signature.py` |
| websocket chat auth + tenant binding | endpoint behaviour | WS chat accepts both token kinds, binds the connection tenant and signs the CC loopback | `backend/app/api/ws/chat.py` |
| Adoption migration `b8c9d0e1f2a3` | migration | NULL-tenant → root adoption, `tenant_id` NOT NULL on data-plane tables, per-tenant MCP slug scoping | `backend/alembic/versions/b8c9d0e1f2a3_per_tenant_entity_adoption_and_mcp_slug_scoping.py` |
| Per-tenant IdP scope uniqueness `c9d0e1f2a3b4` | migration | Unique tenant scope on `identity_provider_configs` | `backend/alembic/versions/c9d0e1f2a3b4_unique_tenant_scope_on_identity_provider_configs.py` |
| `_seed_demo_tenant_realm` / `_run_tenant_demo_seed` | functions | Opt-in demo tenant realm seeding (`identity --tenant-demo`), idempotent | `setup/identity.py` |

### Identity providers and JIT

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OIDCProviderRegistry` / `.initialize` / `.get_provider` / `._load_root_tenant_id` / `._resolve_cached` | class / methods | Per-tenant cache; own → shared → root resolution across provider/secret/JWKS/discovery | `backend/app/services/oidc_provider_registry.py` |
| `IdentityProviderConfig` / `IdentityProviderConfig.default_tenant_role` | model / column | Per-tenant provider binding and JIT default role | `backend/app/db/models/identity_provider_config.py` |
| `OIDCConfigService` / `OIDCClient` | classes | Per-tenant provider CRUD (scope uniqueness) and tenant-claim-aware validation | `backend/app/services/oidc_config_service.py`, `backend/app/core/oidc_client.py` |
| `DefaultTenantRole` / `DefaultTenantRolePreset` / `DEFAULT_TENANT_ROLE_PRESETS` | enum / class / constant | The four seeded preset keys and their permissions | `backend/app/services/tenancy/default_tenant_roles.py` |
| `jit_membership_with_default_role` / `JWTAuthMiddleware._maybe_jit_default_role` | function / method | Idempotent JIT admission on first OIDC sign-in (never root, never platform-password) | `backend/app/services/tenancy/default_tenant_roles.py`, `backend/app/middleware/auth.py` |

### Service binding (CH / AR)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ControlPlaneMiddleware` / `ApiKeyAuthMiddleware` | middlewares | CH verifies inbound signed context; API-key sessions bind the key's tenant | `backend/app/communication_hub/middleware/control_plane.py`, `api_key_auth.py` |
| `ControlCenterDataClient` (CH / AR) | classes | Forward signed headers on every internal call | `backend/app/communication_hub/data_client.py`, `backend/app/agent_runtime/data_client.py` |
| `ControlCenterCertificateMiddleware` | middleware | AR verifies signed context on execution requests (fail-closed) | `backend/app/agent_runtime/middleware.py` |
| `CommunicationHubClient` / `AgentRuntimeClient` | classes | CC clients attaching the signed context on dispatch | `backend/app/services/control_center/comm_hub_client.py`, `agent_runtime_client.py` |
| `SessionDispatcher` / scheduler / gateway lifecycle handler | components | Adopt the owning tenant's context before dispatch | `backend/app/services/agents/session_dispatcher.py`, `backend/app/services/scheduling/scheduler.py`, `backend/app/services/gateway/lifecycle_handler.py` |
| `validate_api_key_internal` / api-key schema | endpoint / schema | Returns the key's tenant binding | `backend/app/api/v1/internal/validate_api_key.py`, `backend/app/schemas/api_key.py` |

### Frontend sign-in and binding

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AuthProvider` | store | Active/available tenant state, tri-state tenancy flag, `refreshProviders` | `frontend/src/stores/AuthContext.tsx` |
| `LoginPage` | component | Workspace-address finder, `?workspace=` deep link, password card, non-gating OIDC button, root-only super-admin entry | `frontend/src/pages/auth/LoginPage.tsx` |
| `extractSlugCandidate` / `bindWorkspace` | functions | Slug derivation and single binding choke point | `frontend/src/pages/auth/LoginPage.tsx` |
| `OidcCallback` | component | Verify-then-bind completion, tenant-resolved exchange | `frontend/src/pages/auth/OidcCallback.tsx` |
| `tenantAuthApi` | module | Discovery, memberships, login/register, per-tab slug storage, remember hint | `frontend/src/api/tenantAuthApi.ts` |
| `getRememberedTenantSlug` / `setRememberedTenantSlug` | functions | Non-authoritative returning-visitor hint (always re-verified) | `frontend/src/api/tenantAuthApi.ts` |
| `apiClient` / `isTenantResolutionRejection` / `selfHealTenantBinding` | module / functions | `X-Tenant` header and unknown-slug self-heal | `frontend/src/api/apiClient.ts` |
| `TenantPicker` / `TenantSessionGate` | components | One-session-one-tenant gate | `frontend/src/components/auth/TenantPicker.tsx`, `TenantSessionGate.tsx` |
| `RESOURCE_TYPE_MANIFEST` / `MODULE_GROUPS` (frontend) | constants | Mirrored resource types | `frontend/src/constants/resourceTypes.ts` |
| tenant TypeScript types | module | Discovery/membership/platform contracts | `frontend/src/types/index.ts` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_identity_plane` | test | Identity-plane exemption, JIT upsert reuse, claim injection, no-membership 403 shape, data-plane join | `backend/tests/test_identity_plane.py` |
| `test_oidc_tenant_claim_gap` | test | Tenant-provider token passes the full validation pipeline | `backend/tests/test_oidc_tenant_claim_gap.py` |
| `test_oidc_provider_fallback` / `test_oidc_jit_default_role` | tests | Slot fallback ordering and JIT admission | `backend/tests/test_oidc_provider_fallback.py`, `backend/tests/test_oidc_jit_default_role.py` |
| `test_platform_permission_gating` | test | Containment semantics, root role, platform wildcard crossing | `backend/tests/test_platform_permission_gating.py` |
| `test_auth_middleware_full` / `test_oidc_config_service` | tests | Tenant-claim cases and per-tenant CRUD isolation | `backend/tests/test_auth_middleware_full.py`, `backend/tests/test_oidc_config_service.py` |
| `OidcCallback.test.tsx` / `LoginPage.refined.test.tsx` | frontend tests | Verified binding, workspace finder flows | `frontend/src/__tests__/OidcCallback.test.tsx`, `LoginPage.refined.test.tsx` |
| `ResourceTypeManifestMirror.test.ts` | test | Backend/frontend manifest parity | `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` |
| `multi-tenant-login-flows.spec.ts` | E2E test | SSO round-trip with the fixed claim contract | `e2e/tests/multi-tenant-login-flows.spec.ts` |
