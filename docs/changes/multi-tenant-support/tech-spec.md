# Technical Spec: Multi-Tenant Support

## Technical Overview

Multi-tenancy is implemented as an opt-in platform mode controlled by a `multi_tenancy_enabled` row in a new `PlatformSetting` entity (default false). When off, every new code path is inert and the product behaves exactly as today. When on, Control Center resolves the tenant exactly once per request (tenant address subdomain or tenant header) into an immutable Tenant Context, validates that the JWT's tenant claim matches, and enforces row-level tenant scoping at the database gateway — Control Center remains the only service that touches PostgreSQL. The context is propagated read-only to Agent Runtime and Communication Hub as signed headers on the existing mTLS channels; neither service can widen it. The global OIDC provider registry becomes a per-tenant registry so credentials are tenant-bound, and a new platform admin API plus two frontend surfaces (platform admin console, tenant workspace) complete the feature. New resource types (`platform::*`, `tenant::*`) are registered in both the backend and frontend manifests per the project's CRITICAL manifest registration rule.

The Phase 10 refinement adds the SaaS growth layer on top of these extension points. **Self-serve registration** is account-first and public: a visitor signs up with a platform-issued email + password (stored on `PlatformUser`, deliberately outside the per-tenant OIDC registry), and the platform atomically creates the tenant, the owner account, and the owner's root membership — one owned tenant per user, basic throttling, gated by the tenancy switch. **Tenant root** (`is_root` on `TenantUserMembership`, exactly one per tenant) is immutable — no actor, including the platform admin, can demote, suspend or remove it; attempts are audited as `root_protection_rejected`. The root holds ALL tenant permissions, edits the tenant alias (`Tenant.name`) while the slug (address) stays immutable, and platform-created tenants make their primary admin contact the root. **Licensing & quotas**: `TenantLicense` rows (tier free / team / enterprise with max_users, max_agent_types, monthly_agent_executions; latest active wins, history retained) govern growth; a tenant without an active license falls back to free-tier default limits owned by Control Center's licensing service. Quotas are enforced at exactly three CC decision points — user invitation/creation, agent type creation, and execution submission (the scheduler consults the quota again at dispatch time) — with refusal always happening at CC before any dispatch to CH/AR, and every block returning a structured tier/limit/usage/upgrade payload. New audit event types cover registration, root protection, license changes, and quota exhaustion.

## Component Breakdown

**Tenancy platform switch (`PlatformSetting` + `PlatformSettingsService`)**
- Tenant-agnostic key/value store; the switch row is seeded as false at startup and cached with invalidation on write. Every tenant feature branches on this cached read — no feature reads the flag directly from the database per request.

**Tenant Context (`TenantContext` accessor)**
- Frozen per-request object (tenant id, slug, name) attached to `request.state` by the resolution middleware; a single accessor returns an "unset" sentinel in single-tenant mode so feature code never branches on null.

**Tenant Resolution Service (`TenantResolutionService`)**
- Resolves slug → active tenant from the Host subdomain or an explicit tenant header; reads only tenant metadata (never business data); caches briefly; treats unknown, suspended, and deleted tenants as unresolvable. Single resolution point — never re-derived from callers.

**Tenant Resolution Middleware (`TenantResolutionMiddleware`)**
- Registered in Control Center's `create_app()` after `JWTAuthMiddleware` so it executes before it (Starlette runs last-registered middleware first). Inert when the switch is off. In multi-tenant mode it is fail-closed: any request without a resolvable tenant is rejected before reaching any feature logic; public health/setup/auth paths, internal service-to-service paths (signed headers verified downstream), and the platform admin surface are bypassed.

**Signed propagation (`sign_tenant_context` / `verify_tenant_context`)**
- HMAC-signed, timestamped headers produced by Control Center's internal clients (`CommunicationHubClient`, `AgentRuntimeClient`) and verified by `ControlCenterCertificateMiddleware` (AR) and `ControlPlaneMiddleware` (CH). Signing key is configuration-managed and never leaves the services; AR/CH can verify but never sign.

**Row-level scoping (`apply_tenant_scope` + session dependency)**
- The single choke point at the DB gateway: queries executed through the `get_db` session dependency are automatically constrained to the request's tenant when the switch is on. Join/child tables inherit scope via parents. Cross-tenant direct addressing yields not-found responses plus a `TenantAuditEvent`.
- **Identity-plane exemption (FIX-20260929-221449):** individual statements may opt out via `execute_unscoped(db, stmt)` (execution option `{"tenant_scope": "exempt"}`) — reserved for platform-level IDENTITY resolution (PlatformUser-by-sub, JIT provisioning upserts, operator Identity-by-subject), which must see the user record regardless of memberships in the resolved tenant. The exemption is statement-scoped and also suppresses cross-tenant miss auditing (a missing identity at first login is a JIT signal, not a probe). Data-plane reads/writes keep the full scope; the freed identity is gated by the `no_access_to_workspace` rule: an authenticated user without an ACTIVE membership in the resolved tenant gets a clean structured 403 — never a re-authentication prompt.

**Tenant-aware permission engine (`PermissionEngine.authorize` binding)**
- Role collection and policy lookup are scoped to the request's tenant (plus the platform-admin role); identical role names in different tenants don't collide; wildcards continue to work within the tenant. `authorize_identity` and `require_permission` pass the context through, so every endpoint inherits tenant RBAC unchanged.
- **Platform gating (FIX-20260930-235927):** with multi-tenancy ON, `platform::*` module checks in `authorize_identity` NEVER consult global tenant-less roles/wildcards (the engine collects them for every module — the defect that let pre-tenancy Keycloak `system_admin` admins into the platform console). They pass ONLY via (a) the super-admin bypass or (b) an ACTIVE `platform_admin` membership in the SYSTEM tenant (`_system_tenant_platform_admin`, identity-plane `execute_unscoped` lookups). All non-platform modules (`agent::*`, `integration::*`, `system::*`, `tenant::*`) keep current behaviour — global roles remain effective in tenant contexts. With the switch OFF the gate is skipped entirely (byte-for-byte legacy; no platform concept). Frontend needs no change: the sidebar renders the platform group purely on `multiTenancyEnabled` and the console itself is gated by `PlatformAdminRoute`'s backend probe (`platform::settings:read`), which now correctly 403s for legacy wildcard holders.

**Per-tenant OIDC registry (`OIDCProviderRegistry` extension)**
- Cache keyed by (tenant, scope); `OIDCConfigService` enforces per-tenant provider scope uniqueness when the switch is on. Token validation in `_try_oidc_token` validates against the provider resolvable for the resolved LOGIN CONTEXT. **Resolution order (FIX-20260930-075014, both tenant-scoped AND tenant-less lookups): own `(tenant, scope)` slot → SHARED `(None, scope)` slot → SYSTEM tenant's `(system_id, scope)` slot** — the adopted platform provider (identified via `Tenant.is_system_tenant`, the same helper the adoption flow uses; its id is cached with the same initialize/reload invalidation hooks as the provider map). A tenant-less lookup (platform surfaces, `/auth/tenant-memberships`) resolves shared → system; one provider can therefore serve the platform AND every tenant without own/shared config; a tenant with none of the three still fails closed. A tenant-less `IdentityProviderConfig` IS the shared provider. On successful validation the `tenant` claim (slug) is INJECTED from the resolved login context (`_inject_tenant_claim` — FIX-20260929-043443; tenant-scoped context only, none on tenant-less validation — semantics unchanged). Under the shared-provider model the claim source is the resolved CONTEXT (never the request's `X-Tenant` header); cross-tenant safety comes from membership gates + the row-level scoped data plane — a user without membership gets 403s, never data. `_check_tenant_claim` still compares the (injected or native) claim against the request-resolved tenant — mismatch rejection is unchanged. With the tenancy switch off everything uses the single global provider (unchanged).

**JIT default tenant role (FIX-20260930-075014)**
- `IdentityProviderConfig.default_tenant_role` — nullable non-native enum over the four seeded preset keys (`DefaultTenantRole`: tenant_system_admin / agent_manager / agent_executor / agent_viewer; migration `a1f2c3d4e5b6`, additive + reversible). Set via the provider CRUD (`OIDCConfigService` create/update + `IdentityProviderConfigForm` select on the System Config page).
- Admission hook `JWTAuthMiddleware._maybe_jit_default_role` (end of `_sync_user_and_groups`, same transaction, fire-and-log): when multi-tenancy is ON, a tenant context is RESOLVED, the token is an OIDC-registry token (`_provider_scope` present — platform-password tokens never JIT), the provider resolvable for that context (own → shared → system fallback) carries a default role, and the user has NO active membership → `jit_membership_with_default_role` creates an ACTIVE `TenantUserMembership` (member, non-root) and assigns the tenant's preset `Role` via `UserRole` — idempotent (existing membership → no-op). Audited as `self_serve_registration` with `detail.reason = "jit_default_role_assigned"`. Unset default → no JIT → the existing `no_access_to_workspace` 403 path (unchanged).

**Tenant lifecycle services (`TenantService`, `TenantProvisioningService`, `TenantAdoptionService`)**
- Lifecycle (create/suspend/resume/delete with slug uniqueness and true deletion), guided onboarding and self-service organization creation, and the system-tenant adoption path that backfills an existing deployment's data into one implicit system tenant when the switch is first enabled. `TenantAuditService` writes lifecycle and security events.

**Tenant Registration Service (`TenantRegistrationService` — Phase 10)**
- Account-first self-serve signup in ONE transaction: the `PlatformUser` (email + password credential stored hashed, platform-issued `sub`, independent of per-tenant OIDC), the `Tenant` (slug + alias), and the owner's root `TenantUserMembership`. Validates duplicate email, one-owned-tenant-per-user (existing root membership), and slug conflicts BEFORE any write — zero partial data on failure. Switch-gated and throttled. Reuses the provisioning/onboarding internals; supersedes the authenticated `register-organization` creation path.

**Licensing Service (`TenantLicensingService` — Phase 10)**
- Owns `TenantLicense`: tier enum (free / team / enterprise) with max_users, max_agent_types, monthly_agent_executions. Supersede semantics — assigning a new license deactivates the previous one (`unassigned_at` set, history retained; latest active wins); removal falls the tenant back to the built-in free-tier default limits immediately (defaults are constants owned by this service). Every change audited.

**Quota Service (`TenantQuotaService` — Phase 10)**
- Resolves effective limits (active license, else free-tier defaults) and evaluates the three quotas: users (live count of active memberships), agent types (live count of tenant agent-type records), monthly executions (maintained `TenantQuotaUsage` counter — one calendar-month bucket per tenant, incremented once per accepted execution at the CC enforcement point; a new month starts a fresh bucket so reset is implicit; never refunded on completion/failure). Emits `quota_exhausted` audit events.

**Structured quota error contract (`QuotaExceededError` + quota block schema — Phase 10; HTTP 403, recorded decision)**
- One shared exception and one Pydantic payload (tier, quota type, limit, current usage, upgrade path) mapped to a single HTTP status, produced identically by all three enforcement gates; the frontend renders the payload as-is.

**Tenant root protection (authorization guard — Phase 10)**
- Shared guard on the membership update/remove endpoints and platform-admin mutation paths: any mutation targeting the root membership is rejected for EVERY actor (delegated tenant admin or platform admin) and audited as `root_protection_rejected`. Root membership grants ALL tenant permissions via the membership grant path in `backend/app/api/deps.py`; alias editing is restricted to the root.

**Platform license & usage APIs (Phase 10)**
- License assign/change/remove endpoints on the platform tenants router (guarded by the existing `platform::tenants` manage action) plus tier/limits/usage in tenant list/detail; tenant-side tier/limits/usage read on the tenant self-service router (existing `tenant::settings` read action). No new resource types are required.

**Platform Admin APIs**
- Routers under `backend/app/api/v1/platform/` expose tenant metadata, platform settings, and cross-tenant security audit — never tenant business data. Tenant self-service router (`backend/app/api/v1/tenant.py`) exposes the tenant's own settings, members, and invitations.

**Agent Runtime (tenant-bound execution)**
- `ControlCenterCertificateMiddleware` additionally verifies signed tenant headers; execute/resume/terminate/intervene endpoints bind the verified context; the AR-side `ControlCenterDataClient` forwards it. The runtime loader resolves configuration only within the tenant; no widening path exists and agents still hold no tokens or credentials.

**Communication Hub (tenant-bound routing)**
- `ControlPlaneMiddleware` verifies signed headers; session dispatch, A2A broker (`request_a2a`), MCP protocol server and tool registry are scoped to the session's tenant. `ApiKeyAuthMiddleware` binds MCP client API keys to the tenant returned by `validate_api_key_internal`; tool listing/calls are filtered by tenant-scoped permissions.

**Frontend — two surfaces**
- Platform admin console (`/platform/*`): tenant management, platform settings, security audit; gated by a dedicated route guard; renders no tenant business data.
- Tenant workspace: the existing product UI with active tenant state in `AuthProvider`/`useAuthStore`, organization branding in `AppShell`, tenant-aware `LoginPage` with a picker for multi-organization users, and new tenant admin pages (settings, onboarding, members). All strings via i18next `t()`.

**Frontend — public sign-up and licensing surfaces (Phase 10)**
- Public `SignUpPage` (email + password + organization name/address) linked from `LoginPage`; shown only when the tenancy switch is on; successful registration lands in guided onboarding as the root.
- Tenant settings: root-only alias editor (address shown immutable) and a license & usage panel component (tier, per-limit usage meters).
- Shared blocked-action alert consuming the structured quota contract, wired into invitation creation, agent type creation, and execution launch UIs.
- Platform console: license assignment dialog plus tier/usage columns in tenant management.

**Observability & audit**
- `TenantAuditService` persists `TenantAuditEvent` records; OTEL setup gains a tenant attribute on spans/logs in all three services when the switch is on. Cross-tenant denials and boundary violations are flagged security-relevant for the platform admin view.

## API Changes

**New — platform admin (guarded by `platform::tenants` / `platform::settings` / `platform::audit`)**
- `GET /api/v1/platform/tenants` — tenant overview: status, created date, admin contact, aggregate user/agent counts; no business rows.
- `POST /api/v1/platform/tenants` — create tenant (name, unique slug, primary admin contact).
- `GET /api/v1/platform/tenants/{tenant_id}` — tenant detail.
- `PATCH /api/v1/platform/tenants/{tenant_id}` — update name/contact.
- `POST /api/v1/platform/tenants/{tenant_id}/suspend` — suspend; blocks sign-in, ends active sessions.
- `POST /api/v1/platform/tenants/{tenant_id}/resume` — restore access.
- `DELETE /api/v1/platform/tenants/{tenant_id}` — delete with explicit confirmation; slug becomes reusable.
- `GET /api/v1/platform/settings` — read platform settings including the tenancy switch.
- `GET /api/v1/platform/settings/{key}` — read a single setting.
- `PUT /api/v1/platform/settings/{key}` — update a setting; toggling the switch triggers system-tenant adoption and cache invalidation.
- `GET /api/v1/platform/audit-events` — filterable security/audit events across tenants with tenant attribution.

**New — tenant self-service (guarded by `tenant::settings` / `tenant::members`)**
- `GET /api/v1/tenant/settings` / `PATCH /api/v1/tenant/settings` — the caller's tenant name, contact, onboarding state.
- `GET /api/v1/tenant/onboarding` / `POST /api/v1/tenant/onboarding/complete` — guided onboarding state and completion.
- `GET /api/v1/tenant/members` — list memberships.
- `PATCH /api/v1/tenant/members/{membership_id}` — change tenant role / suspend / remove member.
- `POST /api/v1/tenant/invitations` — create single-use invitation with role and expiry.
- `GET /api/v1/tenant/invitations` — list the tenant's pending invitations.
- `POST /api/v1/tenant/invitations/{invitation_id}/revoke` — revoke a pending invitation.

**New — licensing & quota (Phase 10)**
- `PUT /api/v1/platform/tenants/{tenant_id}/license` — assign or change the tenant license (tier + limits); supersedes the previous active license (history retained). Guarded by `platform::tenants` manage.
- `DELETE /api/v1/platform/tenants/{tenant_id}/license` — remove the active license; immediate free-tier fallback. Guarded by `platform::tenants` manage.
- `GET /api/v1/platform/tenants` / `GET /api/v1/platform/tenants/{tenant_id}` (modified) — list/detail responses extended with tier, effective limits, and current usage (live counts for users/agent types, counter read for monthly executions).
- `GET /api/v1/tenant/usage` — the caller's tenant tier (free default when unlicensed), effective limits, and current usage — users, agent types, executions this month. Guarded by `tenant::settings` read.
- `PATCH /api/v1/tenant/settings` (modified) — the name (alias) update is now accepted from the tenant root only; the slug is immutable; other tenant admins receive a clear rejection.

**New — public registration & platform credential sign-in (Phase 10; rate-limited, switch-gated)**
- `POST /api/v1/auth/register` — public account-first self-serve registration: email, password, organization name and unique address; atomically creates the platform account, the tenant, and the root membership; returns the new tenant identity plus an authenticated session for guided onboarding; rejects duplicate emails, existing owners (one tenant per user), and invalid input before writing anything. Replaces `POST /api/v1/auth/register-organization`.
- `POST /api/v1/auth/login-password` — public sign-in for platform-issued accounts; issues a tenant-bound token validated by the existing tenant-claim machinery (outside the per-tenant OIDC registry); generic failures, no user enumeration.

**New — authentication & public (rate-limited, minimal data)**
- `GET /api/v1/auth/tenant` — public tenant discovery by host: name, slug, sign-in readiness only.
- `GET /api/v1/auth/tenant-memberships` — the authenticated user's tenant memberships (powers the sign-in org picker).
- `POST /api/v1/auth/register-organization` — public self-service organization creation; creator becomes first tenant admin. **Superseded in Phase 10** by `POST /api/v1/auth/register` (account-first, root membership) — removed/replaced at implementation.
- `POST /api/v1/invitations/accept` — public token-based invitation acceptance.

Tenant selection happens at sign-in: the picker drives the OIDC redirect, the chosen slug is stored per-tab, and the resulting session token is bound to that tenant (validated by the tenant-claim check); there is no separate tenant-selection endpoint.

**Modified — existing routes**
- `/api/v1/system/identity-providers*` — provider CRUD becomes tenant-bound when the switch is on (system tenant's config in single-tenant mode); per-tenant scope uniqueness replaces platform-wide uniqueness.
- `/api/v1/internal/validate-api-key` — response extended with the key's tenant binding for MCP session binding.
- All `/api/v1/internal/*` routes — require and honor signed tenant headers in multi-tenant mode (no route changes; certificate auth unchanged).
- All business endpoints — unchanged routes, tenant-scoped results (driven by the DB gateway choke point, not per-route edits).
- WebSocket/SSE endpoints — tenant context comes from the handshake request; no route changes.

## State Management

- **Auth store (`AuthProvider`)** — gains `activeTenant` (id, slug, name, tenant role), `availableTenants`, and a tri-state `multiTenancyEnabled` (null while discovery resolves, so the platform route guard doesn't bounce platform admins deep-linking `/platform/*`); set once at sign-in, immutable for the session (one session = one tenant), cleared on sign-out. Single-tenant mode leaves the shape inert.
- **Server state (TanStack Query)** — tenant and platform pages query the REST API directly via the existing TanStack Query pattern (no new hooks files); reads never bypass the REST API.
- **No persisted tenant state** — the active tenant is not written to durable client storage; switching tenants requires a fresh sign-in by design.
- **Platform console state** — page-level query state only (filters, selections); no cross-page tenant cache, since the console never handles tenant business data.
- **Sign-in flow state** — `LoginPage` holds transient resolution result (tenant discovery) and picker selection; selection drives the OIDC redirect via `AuthProvider`, and the resulting session is tenant-bound (validated by the tenant-claim check).
- **Tenant alias (Phase 10)** — a successful root alias edit updates `activeTenant.name` in place in the auth store, so header branding and tenant labels refresh without a reload; the slug never changes at runtime.
- **License tier & quota usage (Phase 10)** — pure server state: the tenant settings license/usage panel and the platform console fetch tier, limits and usage via the REST APIs through the existing TanStack Query pattern, and invalidate/refetch after license mutations; no duplicated or persisted client-side quota cache.
- **Quota blocks (Phase 10)** — no dedicated state: the structured quota payload flows through the existing dialog error handling into the shared blocked-action alert at the point of failure.

## Data Access Patterns

- **All data access is server-side** — the frontend calls REST APIs only (no direct database access, per project conventions).
- **Control Center is the sole DB gateway** — tenant scoping is applied centrally at the session dependency (`apply_tenant_scope` via `get_db`), not per endpoint; services in AR/CH never receive rows outside the tenant because CC scopes every internal resolve.
- **Join and child tables inherit scope** — queries filter through parent tenant references (per data-model.md); only direct-scoped entities carry tenant columns.
- **Platform settings are cached** — read through an in-memory cache with write-through invalidation; the switch is never read per-request from the database.
- **Tenant overview counts are aggregates** — the platform API returns counts (users, agents) via aggregate queries, never tenant business rows.
- **MCP/API-key validation resolves tenant at CC** — the CH middleware caches the per-session tenant binding after `validate-api-key`; subsequent tool calls are authorized within that tenant.
- **Audit writes are fire-and-forget-safe** — audit events are persisted within the same request where possible, and always for security-relevant denials.
- **Quota usage: derived counts vs maintained counter (Phase 10)** — `users` (active membership count) and `agent_types` (tenant agent-type record count) are derived live at check time, so they can never drift from the records; `monthly_executions` uses the `TenantQuotaUsage` counter — one row per tenant per calendar-month bucket, incremented once per accepted execution at the CC enforcement point, implicitly reset by each new bucket, and never refunded on completion/failure — so high-volume execution metering never scans execution history. Only `monthly_executions` persists counter rows in this epic.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `Tenant` | model (new) | Tenant entity: unique name/slug, status, system-tenant flag, admin contact (migration `31c0e0bc9990` creates the five tenancy entities) | `backend/app/db/models/tenant.py` |
| `TenantUserMembership` | model (new) | User membership in a tenant with tenant-scoped role | `backend/app/db/models/tenant_membership.py` |
| `TenantInvitation` | model (new) | Single-use tenant invitation with role, expiry, and SHA-256 `token_hash` (migration `d9f3a6c2e7b1`) | `backend/app/db/models/tenant_invitation.py` |
| `TenantAuditEvent` | model (new) | Tenant lifecycle and security-relevant audit events | `backend/app/db/models/tenant_audit_event.py` |
| `PlatformSetting` | model (new) | Tenant-agnostic platform settings (`multi_tenancy_enabled`) | `backend/app/db/models/platform_setting.py` |
| `TenantAuditEventType.platform_setting_updated` | enum value (new) | Audits platform settings writes (incl. the tenancy switch); added by migration `b4d7e1a90c2f` | `backend/app/db/models/tenant_audit_event.py` |
| `PlatformUser` | model (modified) | Gains tenant-membership relationship (stays tenant-agnostic) | `backend/app/db/models/platform_user.py` |
| `Role`, `Identity` | model (modified) | Gain tenant references; `Role.name` uniqueness is per-tenant (`uq_roles_tenant_name` + partial `uq_roles_global_name`, migration `c8e2f5b17a93`) | `backend/app/db/models/identity.py` |
| `AgentApiKey` | model (modified) | Gains tenant reference — keys are tenant-bound | `backend/app/db/models/agent_api_key.py` |
| `IdentityProviderConfig` | model (modified) | Gains tenant reference — per-tenant OIDC binding | `backend/app/db/models/identity_provider_config.py` |
| `AgentType`, `AgentIdentity`, `AgentJob`, `AgentA2ASession` | models (modified) | Gain tenant references | `backend/app/db/models/agents.py` |
| `McpServer` | model (modified) | Gains tenant reference; slug uniqueness becomes per-tenant | `backend/app/db/models/mcp_hub.py` |
| `Skill`, `Sop` | models (modified) | Gain tenant references | `backend/app/db/models/skills.py` |
| `ScheduledJob` | model (modified) | Gains tenant reference | `backend/app/db/models/scheduling.py` |
| `ConversationSession` | model (modified) | Gains tenant reference | `backend/app/db/models/conversations.py` |
| `ResultRecord` | model (modified) | Gains tenant reference | `backend/app/db/models/results.py` |
| `NotificationChannel` | model (modified) | Gains tenant reference | `backend/app/db/models/notifications.py` |
| models `__init__` | module (modified) | Exports new tenant models for autogenerate detection | `backend/app/db/models/__init__.py` |
| `get_db` | function (modified) | Session dependency; applies tenant scope via choke point | `backend/app/db/session.py` |
| `apply_tenant_scope` | function (new) | Binds tenant scope to gateway sessions; ORM SELECT/DELETE/UPDATE rewriting + INSERT auto-stamping (`before_flush`) + cross-tenant miss detection (audited). Internal paths verify signed headers here. Criteria lambdas are built by closure factories (never default-arg bound) so the lambda-SQL cache re-binds the tenant per execution — FIX-20260928-121317. Individual statements may opt out via `execute_unscoped` (identity plane — FIX-20260929-221449) | `backend/app/db/tenant_scoping.py` |
| `execute_unscoped` | function (new) | IDENTITY-PLANE exemption (FIX-20260929-221449): executes ONE statement exempt from the session's tenant scope (execution option `{"tenant_scope": "exempt"}`) and suppresses scope-miss auditing for it — reserved for PlatformUser-by-sub resolution, JIT provisioning upserts and operator Identity-by-subject lookups; data-plane queries keep the full scope. Caveat: exempt-loaded entities enter the identity map (a later `get()` of the same identity short-circuits) — consume the loaded object directly | `backend/app/db/tenant_scoping.py` |
| `flush_scope_miss_audits` | function (new) | Persists cross-tenant probe audits at request completion | `backend/app/db/tenant_scoping.py` |
| `scope_for_session` | function (new) | Reads a session's scoped tenant id (None when unscoped); tolerant of non-UUID values so request paths can branch scoped/legacy | `backend/app/db/tenant_scoping.py` |
| `_tenant_criteria_factory` / `_platform_user_criteria_factory` | functions (new) | Closure factories building the per-execution `with_loader_criteria` callables — direct `tenant_id` criteria and the PlatformUser "membership-join" criteria respectively | `backend/app/db/tenant_scoping.py` |
| `filter_platform_users_to_tenant` | function (new) | Endpoint-level PlatformUser isolation helper: constrains a user statement to ACTIVE members of the tenant (membership-join strategy); used by the platform-users list/detail/mutation guards | `backend/app/db/tenant_scoping.py` |
| `_has_automatic_scope_strategy` | function (new) | Registers tenant-agnostic entities whose strategy the choke point applies automatically (currently PlatformUser) | `backend/app/db/tenant_scoping.py` |
| platform users router | router (modified) | Tenant-context isolation for `GET/DELETE /platform-users` and all sub-resources: list filtered by active membership, detail/mutations 404 non-members, counts join scoped Role/Group parents, delete refuses users with other active memberships (409); unscoped (single-tenant / platform admin / super admin) behaviour unchanged | `backend/app/api/v1/platform_users.py` |
| `set_tenant_span_attributes` | function (new) | OTEL span tenant attribution (tenant attrs / platform sentinel / silent when off) | `backend/app/core/tenant_context.py` |
| `TenantContext` | class (new) | Immutable per-request tenant context + `TENANT_UNSET` sentinel, `get/set/require_tenant_context` accessors | `backend/app/core/tenant_context.py` |
| `build_tenant_signature_headers` | function (new) | HMAC-signs tenant context headers (`X-Internal-Tenant-*` set) | `backend/app/core/tenant_signature.py` |
| `verify_tenant_signature_headers` | function (new) | Verifies signed headers (tamper/stale/unsigned rejection) | `backend/app/core/tenant_signature.py` |
| `tenant_context_headers` | function (new) | Client helper: signed headers for a context, `{}` when unset | `backend/app/core/tenant_signature.py` |
| `forward_tenant_headers` | function (new) | AR/CH helper: re-emit the CC-signed headers received on the request (never re-sign) | `backend/app/core/tenant_signature.py` |
| `verify_request_tenant_context` | function (new) | AR/CH middleware helper: verify-if-present; returns None for headerless (single-tenant) traffic | `backend/app/core/tenant_signature.py` |
| `tenant_address_base_domain` / `tenant_context_signing_key` | settings (new) | Tenancy resolution base domain and HMAC signing key (dev default) on `Settings` | `backend/app/core/config.py` |
| `PlatformSettingsService` | class (new) | Cached platform setting reads/writes; switch bootstrap. Singleton via `get_platform_settings_service()` | `backend/app/services/tenancy/platform_settings_service.py` |
| `TenantResolutionService` | class (new) | Resolves slug/header → active tenant; fail-closed semantics; short-TTL cache; singleton via `get_tenant_resolution_service()`; `TENANT_HEADER` = `X-Tenant` | `backend/app/services/tenancy/tenant_resolution_service.py` |
| `TenantService` | class (new) | Tenant lifecycle: create/suspend/resume/delete | `backend/app/services/tenancy/tenant_service.py` |
| `TenantProvisioningService` | class (new) | Guided onboarding and self-service organization creation | `backend/app/services/tenancy/tenant_provisioning_service.py` |
| `TenantAdoptionService` | class (new) | System-tenant adoption/backfill when the switch is enabled | `backend/app/services/tenancy/tenant_adoption_service.py` |
| `TenantAuditService` | class (new) | Writes tenant audit events, flags security-relevant denials | `backend/app/services/tenancy/tenant_audit_service.py` |
| `TenantResolutionMiddleware` | middleware (new) | Resolves tenant once per request in CC; inert when off; bypasses public/internal/platform paths (incl. the method-aware GET-only login-probe bypass, FIX-20260929-121120); audits rejections | `backend/app/middleware/tenant_resolution.py` |
| `BYPASS_GET_PATHS` / `_is_bypassed` | constant + function (new) | METHOD-AWARE GET-only bypass (FIX-20260929-121120 / Defect A) for the login page's public pre-auth bootstrap probes — `GET /api/v1/system/identity-providers`, `GET /api/v1/system/super-admin/status` (HEAD harmless). Only safe reads bypass; identity-provider WRITES (POST/PUT/DELETE) on the same paths stay fail-closed tenant-resolved (never a blanket path bypass). `_is_bypassed(path, method)` treats an unknown method as fail-closed (no bypass) | `backend/app/middleware/tenant_resolution.py` |
| `JWTAuthMiddleware` | middleware (modified) | Adds tenant-claim vs resolved-tenant mismatch rejection (`_check_tenant_claim` + `_audit_claim_mismatch`) | `backend/app/middleware/auth.py` |
| `validate_raw_token` | function (modified) | Token validation pipeline; per-tenant provider resolution | `backend/app/middleware/auth.py` |
| `_try_oidc_token` | function (modified) | Validates via the resolved tenant's provider only; after successful validation against a TENANT-scoped provider slot, injects the `tenant` claim (slug) from the provider's registry binding (FIX-20260929-043443) | `backend/app/middleware/auth.py` |
| `_inject_tenant_claim` | function (new) | Validation-time tenant claim injection for OIDC tokens: stamp `claims["tenant"]` = resolved slug whenever a provider is resolvable for the resolved login context (the tenant's OWN registry slot, or the SHARED tenant-less slot — FIX-20260929-221449; never from the request's `X-Tenant` header); overrides any native claim — the resolved login context is the authoritative binding and cross-tenant safety comes from membership gates + the scoped data plane; no-op without a tenant context (single-tenant unchanged) | `backend/app/middleware/auth.py` |
| `create_app` | function (modified) | Registers `TenantResolutionMiddleware` after the auth middleware so it executes first (Starlette order) | `backend/app/main.py` |
| `authorize_identity` | function (modified) | Passes tenant context into permission checks; grants `tenant::*` permissions via active membership roles (`_TENANT_MEMBERSHIP_GRANTS`). FIX-20260929-221449: the PlatformUser-by-sub lookup is tenant-scope-exempt (`execute_unscoped`) and a user WITHOUT an active membership in the resolved tenant is denied with the flat `no_access_to_workspace` 403 (`NoWorkspaceAccessError`) — never "user must re-authenticate" | `backend/app/api/deps.py` |
| `require_permission` | function (modified) | Dependency factory; tenant-bound RBAC for all endpoints | `backend/app/api/deps.py` |
| `PermissionEngine` | class (modified) | Authorization evaluated within the resolved tenant | `backend/app/services/permissions/permission_engine.py` |
| `PermissionEngine.authorize` | method (modified) | Role collection and policy lookup tenant-scoped | `backend/app/services/permissions/permission_engine.py` |
| `ResourceTypeManifest` | constant (modified) | Adds `platform::*` / `tenant::*` resource types | `backend/app/core/resource_types.py` |
| `MODULE_GROUPS` | constant (modified) | Adds platform/tenant module group entries | `backend/app/core/resource_types.py` |
| `OIDCProviderRegistry` | class (modified) | Per-tenant provider cache keyed by (tenant, scope) | `backend/app/services/oidc_provider_registry.py` |
| `OIDCProviderRegistry.initialize` | method (modified) | Loads all tenants' enabled providers | `backend/app/services/oidc_provider_registry.py` |
| `OIDCProviderRegistry.get_provider` | method (modified) | Tenant-aware provider lookup — resolution order (FIX-20260930-075014, both tenant-scoped AND tenant-less lookups): own `(tenant, scope)` slot → SHARED tenant-less `(None, scope)` slot → SYSTEM tenant's `(system_id, scope)` slot (the adopted platform provider); none of the three → None (fail-closed). `is_system_tenant` retained for compatibility. Applied consistently across `get_provider` / `get_decrypted_secret` / `get_jwks` / `get_discovery` / `invalidate_*` via `_resolve_cached` | `backend/app/services/oidc_provider_registry.py` |
| `OIDCProviderRegistry._load_system_tenant_id` | method (new, FIX-20260930-075014) | Caches the system tenant id (`Tenant.is_system_tenant`) for the third resolution slot; refreshed in `initialize` / `reload_single` | `backend/app/services/oidc_provider_registry.py` |
| `IdentityProviderConfig.default_tenant_role` | column (new, FIX-20260930-075014) | Nullable non-native enum over the four seeded preset role keys; NULL = no JIT (migration `a1f2c3d4e5b6`, additive + reversible) | `backend/app/db/models/identity_provider_config.py`, `backend/alembic/versions/a1f2c3d4e5b6_*.py` |
| `DefaultTenantRole` | enum (new, FIX-20260930-075014) | The four seeded preset keys as a str enum; DB-facing values of `default_tenant_role` | `backend/app/services/tenancy/default_tenant_roles.py` |
| `jit_membership_with_default_role` | function (new, FIX-20260930-075014) | Idempotent JIT admission: active non-root `TenantUserMembership` + preset `Role` via `UserRole` (seeds roles on demand); no-op on an existing active membership | `backend/app/services/tenancy/default_tenant_roles.py` |
| `_system_tenant_platform_admin` | function (new, FIX-20260930-235927) | Platform gating: True only with an ACTIVE `platform_admin` membership in the system tenant (identity-plane `execute_unscoped` lookups); consulted by `authorize_identity` for `platform::*` when multi-tenancy is ON | `backend/app/api/deps.py` |
| `_seed_demo_tenant_realm` / `_run_tenant_demo_seed` | function (new, FIX-20260930-235927) | Opt-in demo tenant realm seeding (`identity --tenant-demo`): idempotent realm + public frontend client (main-realm redirect URIs mirrored) + demo users via the shared Keycloak admin client | `setup/identity.py` |
| `test_platform_permission_gating.py` | test (new, FIX-20260930-235927) | T1 legacy global wildcard denied on `platform::*` (tenancy ON), T2 same user still allowed on `agent::*` in their tenant, T3 system-tenant `platform_admin` membership allowed (+T3b plain member denied), T4 tenancy-OFF wildcard pin, T5 super-admin pin | `backend/tests/test_platform_permission_gating.py` |
| `test_setup_tenant_demo.py` | test (new, FIX-20260930-235927) | Demo realm seeding against a mocked admin client: realm/client/users created with mirrored redirect URIs; full/partial idempotency; user-creation failure reported not raised | `backend/tests/unit/test_setup_tenant_demo.py` |
| `JWTAuthMiddleware._maybe_jit_default_role` | method (new, FIX-20260930-075014) | Sign-in admission hook at the end of `_sync_user_and_groups`: gated on OIDC-registry tokens only (no platform-password JIT), resolved tenant context, provider default set, no active membership; audited as `self_serve_registration` (`reason=jit_default_role_assigned`) | `backend/app/middleware/auth.py` |
| `OIDCConfigService` | class (modified) | Per-tenant provider CRUD with per-tenant scope uniqueness | `backend/app/services/oidc_config_service.py` |
| `OIDCClient` | class (modified) | Token validation with tenant claim requirement | `backend/app/core/oidc_client.py` |
| `SuperAdminAuthService` | class (modified) | Platform-admin semantics for super admin tokens | `backend/app/services/super_admin_auth_service.py` |
| platform tenants router | router (new) | Tenant overview/lifecycle API for platform admin | `backend/app/api/v1/platform/tenants.py` |
| platform settings router | router (new) | Platform settings incl. tenancy switch API | `backend/app/api/v1/platform/settings.py` |
| platform audit router | router (new) | Cross-tenant security audit read API | `backend/app/api/v1/platform/audit.py` |
| tenant self-service router | router (new) | Tenant settings, onboarding, members, invitations | `backend/app/api/v1/tenant.py` |
| tenant auth router | router (new) | Tenant discovery, memberships, org registration | `backend/app/api/v1/auth_tenant.py` |
| `validate_api_key_internal` | function (modified) | Returns the API key's tenant binding | `backend/app/api/v1/internal/validate_api_key.py` |
| internal routers (authorization, bootstrap, session data, outputs, system tools) | routers (reference) | Unchanged — inherit tenant scoping via the `get_db` gateway, which verifies signed headers on `/api/v1/internal/*` traffic before any query runs | `backend/app/api/v1/internal/authorization.py` (+ `bootstrap.py`, `session_data.py`, `outputs.py`, `system_tools.py`) |
| API v1 router registry | module (modified) | Registers the tenant auth, platform admin, and tenant self-service routers | `backend/app/api/v1/__init__.py` |
| gateway lifecycle handler | module (modified) | Triggered job executions adopt the owning tenant's context before dispatch | `backend/app/services/gateway/lifecycle_handler.py` |
| api key schema | schema (modified) | Validate-api-key response carries the key's tenant binding | `backend/app/schemas/api_key.py` |
| `CommunicationHubClient` | class (modified) | Attaches signed tenant headers on dispatch/execution calls (`tenant_context` parameter) | `backend/app/services/control_center/comm_hub_client.py` |
| `AgentRuntimeClient` | class (modified) | Attaches signed tenant headers on execute/resume/terminate (`tenant_context` parameter) | `backend/app/services/control_center/agent_runtime_client.py` |
| `SessionDispatcher` | class (reference) | AR dispatch loop unchanged — owning-tenant context is adopted upstream (CC scheduler/lifecycle handler) and forwarded via signed headers | `backend/app/services/agents/session_dispatcher.py` |
| scheduler | class (modified) | Triggered jobs adopt the owning tenant's context | `backend/app/services/scheduling/scheduler.py` |
| `ControlPlaneMiddleware` | middleware (modified) | Verifies signed tenant headers (verify-if-present); binds CH request tenant | `backend/app/communication_hub/middleware/control_plane.py` |
| `ApiKeyAuthMiddleware` | middleware (modified) | Binds MCP sessions to the API key's tenant | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `request_a2a` | function (reference) | Unchanged — cross-tenant refusal is decided by CC's tenant-scoped `prepare_a2a_request` (404/403) and surfaced through the existing error path; CH forwards the signed context to CC | `backend/app/communication_hub/api/a2a.py` |
| MCP protocol server | module (reference) | Unchanged — tool listing/calls are filtered by the middleware-bound session tenant + CC-scoped resolves | `backend/app/communication_hub/mcp/protocol_server.py` |
| MCP session manager | module (reference) | Unchanged — sessions carry the immutable tenant binding applied by `ApiKeyAuthMiddleware` / `ControlPlaneMiddleware` | `backend/app/communication_hub/mcp/session_manager.py` |
| tool registry bridge | module (reference) | Unchanged — tenant filtering flows from the bound session tenant and tenant-scoped permissions | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `ControlCenterDataClient` (CH) | class (modified) | Forwards signed tenant headers to CC (`_get`/`_post`) | `backend/app/communication_hub/data_client.py` |
| `ControlCenterCertificateMiddleware` | middleware (modified) | AR verifies signed tenant headers from CC (verify-if-present) | `backend/app/agent_runtime/middleware.py` |
| execute endpoint | router (reference) | Unchanged — tenant context verified and bound to executions by `ControlCenterCertificateMiddleware` | `backend/app/agent_runtime/api/execute.py` |
| terminate endpoint | router (reference) | Unchanged — termination scoped via the middleware-bound tenant context | `backend/app/agent_runtime/api/terminate.py` |
| internal execute/resume/terminate forwarders | routers (modified) | CH forwards CC's original signed headers to AR so execution binds to the tenant (`forward_tenant_headers`) | `backend/app/communication_hub/api/internal/agent_execute.py` (+ `agent_resume.py`, `agent_terminate.py`) |
| `ControlCenterDataClient` (AR) | class (modified) | Forwards signed tenant headers to CC (`_get`/`_post`/`_patch`) | `backend/app/agent_runtime/data_client.py` |
| security payload review | review (new) | Cross-tenant payload isolation review for 8.7 (CC→CH→AR) | `docs/changes/multi-tenant-support/security-review.md` |
| telemetry attribution | function (new usage) | CC/AR/CH middlewares call `set_tenant_span_attributes` for tenant attribution; `telemetry.py` itself unchanged | `backend/app/core/telemetry.py` |
| `RESOURCE_TYPE_MANIFEST` | constant (modified) | Mirrors new `platform::*` / `tenant::*` types | `frontend/src/constants/resourceTypes.ts` |
| `MODULE_GROUPS` (frontend) | constant (modified) | Mirrors new module group entries | `frontend/src/constants/resourceTypes.ts` |
| `AppRouter` | component (modified) | Adds `/platform/*` and tenant workspace routes | `frontend/src/app/AppRouter.tsx` |
| `AppShell` | component (modified) | Shows organization branding in header | `frontend/src/app/AppShell.tsx` |
| `ProtectedRoute` | component (reference) | Existing guard pattern reused by new guards | `frontend/src/app/ProtectedRoute.tsx` |
| `AuthProvider` | component (modified) | Sign-in resolves tenant; active/available tenant + tri-state tenancy flag state for the session | `frontend/src/stores/AuthContext.tsx` |
| `useAuthStore` | hook (reference) | Existing token store consumed by tenant-aware pages; tenant state lives in `AuthProvider` | `frontend/src/stores/authStore.ts` |
| tenant TypeScript types | module (modified) | `TenantDiscovery`, `TenantMembership`, platform admin request/response interfaces | `frontend/src/types/index.ts` |
| `LoginPage` | component (modified) | Tenancy-aware sign-in: discovery probe, tenant blocked / sign-in-unavailable guards, sign-up entry link; password + OIDC + discreet platform-admin entry (see task 10.22) | `frontend/src/pages/auth/LoginPage.tsx` |
| `TenantPicker` | component (new) | Organization chooser for multi-org users | `frontend/src/components/auth/TenantPicker.tsx` |
| `TenantSessionGate` | component (new) | One-session-one-tenant gate hosting the picker in the authenticated shell | `frontend/src/components/auth/TenantSessionGate.tsx` |
| `tenantAuthApi` | module (new) | Public tenant discovery + membership listing client; per-tab resolved-slug storage | `frontend/src/api/tenantAuthApi.ts` |
| `PlatformAdminRoute` | component (new) | Guard: platform-admin membership only; routes absent when tenancy off | `frontend/src/app/PlatformAdminRoute.tsx` |
| `PlatformRoutes` | component (new) | `/platform/*` sub-routes (tenants, settings, audit) | `frontend/src/app/PlatformRoutes.tsx` |
| `TenantManagementPage` | component (new) | Tenant CRUD, suspend/resume/delete console | `frontend/src/pages/platform/TenantManagementPage.tsx` |
| `PlatformSettingsPage` | component (new) | Tenancy switch and platform settings | `frontend/src/pages/platform/PlatformSettingsPage.tsx` |
| `PlatformAuditPage` | component (new) | Cross-tenant attempt security view | `frontend/src/pages/platform/PlatformAuditPage.tsx` |
| `TenantSettingsPage` | component (new) | Tenant admin settings — tenant name and admin contact | `frontend/src/pages/tenant/TenantSettingsPage.tsx` |
| `OnboardingPage` | component (new) | Guided tenant onboarding flow | `frontend/src/pages/tenant/OnboardingPage.tsx` |
| `MembersPage` | component (new) | Members and invitations management | `frontend/src/pages/tenant/MembersPage.tsx` |
| `InvitationAcceptPage` | component (new) | Public token-based invitation acceptance flow | `frontend/src/pages/tenant/InvitationAcceptPage.tsx` |
| `platformAdminApi` | module (new) | Typed platform admin API client | `frontend/src/api/platformAdminApi.ts` |
| `tenantApi` | module (new) | Typed tenant self-service API client | `frontend/src/api/tenantApi.ts` |
| `apiClient` | module (modified) | Shared HTTP client; attaches the `X-Tenant` header from the per-tab resolved slug when a tenant is active; response interceptor self-heals a fail-closed unknown-slug rejection (see `isTenantResolutionRejection`) | `frontend/src/api/apiClient.ts` |
| `isTenantResolutionRejection` / `selfHealTenantBinding` | functions (new) | apiClient self-heal (FIX-20260929-121120 / B2): recognizes the middleware's exact fail-closed wire shape (`403 {"detail": "Tenant could not be resolved"}`, no `required_permission`, request carried `X-Tenant`) and clears the invalid binding (`sessionStorage['parthenon_tenant_slug']` + `localStorage['parthenon_login_tenant']`), redirecting to `/login` (find-workspace) unless already on `/login`/`/callback` — never a bounce loop. Permission 403s (with `required_permission`) and 401 handling untouched; storage keys declared locally (tenantAuthApi imports apiClient — no circular import) | `frontend/src/api/apiClient.ts` |
| `OidcCallback` verified bind | behaviour (modified) | Sign-in-completion binding now VERIFY-THEN-BIND (FIX-20260929-121120): `resolveIntendedTenantSlug` sources (claim → session → remembered → memo) are CANDIDATES only; `verifyIntendedTenantSlug` confirms each candidate through public discovery (`GET /auth/tenant?slug=`) before anything is bound. Discovery `tenant: null` → bind nothing (user lands unbound, login-page find-workspace re-resolves); discovery UNAVAILABLE (network error / unreadable response) → fail-open bind of the candidate with a console warn — fail-open only on unavailability, never on a definitive null | `frontend/src/pages/auth/OidcCallback.tsx` |
| LoginPage binding self-heal + lookup race guard | behaviour (modified) | Mount auto-resolve (FIX-20260929-121120 / B1): an unverified candidate is UNBOUND (`setResolvedTenantSlug(null)`) while discovery re-verifies it — a stale slug can no longer flow out on API calls; a definitive unknown answer clears BOTH the remembered hint and the session binding (when it matches the rejected slug). `handleFindWorkspace` (B3): lookup sequence counter + unmount `alive` flag (StrictMode-safe) — a late discovery resolution never binds/clobbers after a newer lookup or unmount | `frontend/src/pages/auth/LoginPage.tsx` |
| `IdentityProvidersConfigPage` | component (reference) | Existing system OIDC provider config page — unchanged; per-tenant provider CRUD lives in `OIDCConfigService` | `frontend/src/pages/system/IdentityProvidersConfigPage.tsx` |
| `usePermissions` | hook (reference) | Permission gating pattern for tenant pages | `frontend/src/hooks/usePermissions.ts` |
| i18n config | module (reference) | i18next initialization for new translation keys | `frontend/src/i18n/config.ts` |
| English locale | resource (modified) | New keys for platform console and tenant workspace | `frontend/src/i18n/locales/en.json` |
| manifest mirror test | test (modified) | Asserts frontend/backend manifest parity incl. new types | `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` |
| auth middleware tests | test (modified) | Extends with tenant-claim and switch-off cases | `backend/tests/test_auth_middleware_full.py` |
| OIDC config tests | test (modified) | Extends with per-tenant CRUD isolation cases | `backend/tests/test_oidc_config_service.py` |
| backend test fixtures | fixture (modified) | Tenant/membership fixtures and multi-tenant DB setup | `backend/tests/conftest.py` |

Rows below are the **Phase 10 refinement additions (implemented)**. Existing rows above are unchanged.

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TenantLicense` | model (new) | Tier (free / team / enterprise) + limits; latest-active-wins history (`is_active`, `assigned_at`, `unassigned_at`); at-most-one-active partial unique index; migration `6363bb7ee8c3` | `backend/app/db/models/tenant_license.py` |
| `LicenseTier` | enum (new) | free / team / enterprise | `backend/app/db/models/tenant_license.py` |
| `TenantQuotaUsage` | model (new) | Per-tenant quota counter; unique per (tenant, quota_type, calendar-month bucket); only `monthly_executions` persists rows | `backend/app/db/models/tenant_quota_usage.py` |
| `TenantUserMembership.is_root` | field (new) | Immutable root/owner membership; at most one per tenant (partial unique index `uq_tenant_membership_single_root`) | `backend/app/db/models/tenant_membership.py` |
| `PlatformUser.password_credential` | field (new) | Platform-issued password secret (stored hashed, bcrypt) for self-serve accounts — independent of per-tenant OIDC; NULL for OIDC users | `backend/app/db/models/platform_user.py` |
| `TenantAuditEventType.self_serve_registration` (+ `root_protection_rejected`, `license_assigned`, `license_changed`, `license_removed`, `quota_exhausted`) | enum values (new) | Registration, root-protection, license-change and quota-exhaustion audit events; added by migration `6363bb7ee8c3` | `backend/app/db/models/tenant_audit_event.py` |
| `TenantRegistrationService` | class (new) | Atomic account-first registration: PlatformUser + Tenant + root membership; one-owned-tenant rule; zero partial data on failure | `backend/app/services/tenancy/tenant_registration_service.py` |
| platform account auth helpers | module (new) | bcrypt password hash/verify (same scheme as the super admin), email/password validation, platform-issued `sub`, HS256 tenant-bound platform JWTs (`create_platform_account_token` / `validate_platform_account_token`) | `backend/app/services/tenancy/platform_account_auth_service.py` |
| `_try_platform_account_token` | function (new) | Auth tier 1b: validates platform-account JWTs outside the per-tenant OIDC registry | `backend/app/middleware/auth.py` |
| `TenantLicensingService` | class (new) | License assign/change/remove with supersede semantics; owns the free-tier default limits (10 users / 5 agent types / 100 monthly executions); effective-limits resolution; singleton `get_tenant_licensing_service()` | `backend/app/services/tenancy/licensing_service.py` |
| `TenantQuotaService` | class (new) | Three quota checks (users/agent types derived live; monthly executions via counter) + counter bucket maintenance (`increment_executions` once per accepted execution); inert when the switch is off; singleton `get_tenant_quota_service()` | `backend/app/services/tenancy/quota_service.py` |
| `QuotaExceededError` | exception (new) | Shared refusal raised by all three enforcement gates; carries the structured payload; mapped to a single HTTP 403 by the app-level exception handler in `create_app()` | `backend/app/services/tenancy/quota_service.py` |
| quota block schema (`QuotaBlockedPayload`, `TenantUsageRead`) | schema (new) | Structured quota feedback payload: code, tier, quota type, limit, current usage, upgrade path; HTTP 403 (recorded decision — entitlement limit, not traffic throttling) | `backend/app/schemas/tenant_quota.py` |
| `guard_non_root_membership` | function (new) | Rejects membership mutations targeting `is_root` for any actor (403); audits `root_protection_rejected`; shared by tenant + platform paths | `backend/app/api/deps.py` |
| `authorize_identity` / `_membership_grants` | function (modified) | Root membership grants ALL tenant permissions | `backend/app/api/deps.py` |
| `register_account` | endpoint (new) | Public account-first registration (switch-gated, throttled `10/hour`); replaces the removed `register_organization` | `backend/app/api/v1/auth_tenant.py` |
| `login_password` | endpoint (new) | Public sign-in for platform-issued accounts (throttled `30/minute`); tenant-bound token outside per-tenant OIDC | `backend/app/api/v1/auth_tenant.py` |
| `assign_tenant_license` / `remove_tenant_license` | endpoints (new) | Platform license assign/change and remove (supersede via licensing service; `platform::tenants` manage) | `backend/app/api/v1/platform/tenants.py` |
| `get_tenant_usage` | endpoint (new) | Tenant-side tier/limits/usage read (users, agent types, executions this month; `tenant::settings` read) | `backend/app/api/v1/tenant.py` |
| `create_invitation` | function (modified) | Consults the users quota at invitation creation; structured block on exhaustion | `backend/app/api/v1/tenant.py` |
| `create_agent_type` | function (modified) | Consults the agent-types quota; structured block on exhaustion | `backend/app/api/v1/agents.py` |
| `launch_agent_session` | function (modified) | Consults the monthly executions quota; increments the counter once on acceptance, before any dispatch | `backend/app/api/v1/agents.py` |
| `SchedulingEngine._dispatch` | method (modified) | Dispatch-time quota consultation for schedule-triggered executions; skips + audits on exhaustion (job stays scheduled) | `backend/app/services/scheduling/scheduler.py` |
| `TenantProvisioningService.provision_tenant` | method (modified) | Platform-created tenants mark the primary admin contact's membership `is_root` | `backend/app/services/tenancy/tenant_provisioning_service.py` |
| `SignUpPage` | component (new) | Public sign-up (email + password + organization name/address); switch-aware; routes to onboarding; public `/signup` route in `AppRouter` | `frontend/src/pages/auth/SignUpPage.tsx` |
| `LicenseUsagePanel` | component (new) | Tier, effective limits and usage meters in tenant settings (self-fetching via `['tenant','usage']` React Query key) | `frontend/src/components/tenant/LicenseUsagePanel.tsx` |
| `QuotaBlockedAlert` | component (new) | Renders the structured quota payload on blocked actions; non-quota errors fall through to PermissionDeniedAlert | `frontend/src/components/tenant/QuotaBlockedAlert.tsx` |
| `extractQuotaBlocked` | function (new) | Recognizes the 403 quota contract shape in API errors | `frontend/src/utils/quotaErrorUtils.ts` |
| `LoginPage` | component (modified) | Sign-up entry link when the tenancy switch is on; task 10.22 redesigns it into a tenancy-aware page with the primary email + password card (`loginPassword`), a non-gating OIDC button and a discreet platform-admin entry | `frontend/src/pages/auth/LoginPage.tsx` |
| `TenantSettingsPage` | component (modified) | Root-only alias editing; address shown immutable; embeds `LicenseUsagePanel` | `frontend/src/pages/tenant/TenantSettingsPage.tsx` |
| `MembersPage` | component (modified) | Invitation creation surfaces the blocked-action alert on user-quota exhaustion | `frontend/src/pages/tenant/MembersPage.tsx` |
| `AgentManagementPage` / `AgentJobLaunchDialog` | components (modified) | Agent type creation and execution launch surface the blocked-action alert | `frontend/src/pages/agents/AgentManagementPage.tsx` (+ `AgentJobLaunchDialog.tsx`) |
| `TenantManagementPage` | component (modified) | License assignment/change/remove dialog (tier presets, editable limits, free-fallback confirmation); tier + usage columns | `frontend/src/pages/platform/TenantManagementPage.tsx` |
| `tenantAuthApi` | module (modified) | `registerAccount` and `loginPassword` API calls | `frontend/src/api/tenantAuthApi.ts` |
| `platformAdminApi` / `tenantApi` | modules (modified) | `assignTenantLicense` / `removeTenantLicense`; `getTenantUsage` | `frontend/src/api/platformAdminApi.ts` / `frontend/src/api/tenantApi.ts` |
| tenant TypeScript types | module (modified) | `LicenseRead`, `LicenseTier`, `TenantUsageRead`, `QuotaBlockedPayload` interfaces mirroring the backend contract | `frontend/src/types/index.ts` |

Rows below are the **default tenant roles / root blanket grant additions (tasks 10.19–10.21, implemented)**. Existing rows above are unchanged.

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DefaultTenantRolePreset` | class (new) | Frozen preset: stable key, DB-facing role name, description, `permissions` (resource_type → action set) | `backend/app/services/tenancy/default_tenant_roles.py` |
| `DEFAULT_TENANT_ROLE_PRESETS` | constant (new) | The 4 presets: `Tenant System Admin` (every tenant-relevant type incl. bare `agent`, full manifest actions, never `platform::*`), `Agent Manager` (full agent domain + mcp_hub/permissions reads), `Agent Executor` (launch/control/intervene + read views), `Agent Viewer` (read-only agent/integration/system) | `backend/app/services/tenancy/default_tenant_roles.py` |
| `validate_presets_against_manifest` | function (new) | Raises `ValueError` on any preset resource type missing from the manifest or action outside the type's allowed set (runs at seed time; unit-tested) | `backend/app/services/tenancy/default_tenant_roles.py` |
| `seed_default_tenant_roles` | function (new) | Idempotent seeding: creates the 4 tenant-scoped `is_system` Roles (`tenant_id`-scoped, per-tenant unique names) and attaches permission policies in the BootstrapService layout — one `PolicyStatement` per resource type (`effect=allow`) with `PolicyAction` rows and a wildcard `PolicyResource`, all tenant-stamped; optional `root_user_id` assigns the tenant's system-admin role via `UserRole`; caller owns the commit | `backend/app/services/tenancy/default_tenant_roles.py` |
| `assign_tenant_system_admin_role` | function (new) | Idempotent `UserRole` assignment of the tenant's system-admin role (seeds roles first if absent) | `backend/app/services/tenancy/default_tenant_roles.py` |
| `sweep_missing_tenant_default_roles` | function (new) | Startup self-healing scan: seeds missing default roles per active tenant and assigns the system-admin role to every active root membership holder lacking it; constant number of indexed queries + writes only where missing; returns a summary for logging | `backend/app/services/tenancy/default_tenant_roles.py` |
| `TenantService.create` | method (modified) | Seeds the 4 default tenant roles in-transaction — the lowest choke point shared by self-serve registration, platform-console creation and self-service orgs | `backend/app/services/tenancy/tenant_service.py` |
| `TenantProvisioningService.provision_tenant` | method (modified) | After stamping the ROOT membership, assigns the tenant system-admin role to the root (admin contact) user | `backend/app/services/tenancy/tenant_provisioning_service.py` |
| `TenantAdoptionService.adopt_system_tenant` | method (modified) | Seeds the 4 default roles for the adopted system tenant; nobody force-assigned (existing users keep their global roles) | `backend/app/services/tenancy/tenant_adoption_service.py` |
| `_sweep_default_tenant_roles` | function (new) | CC startup task next to `_seed_platform_settings`: runs the default-role sweep in its own session; failures logged, never block startup | `backend/app/main.py` |
| `_membership_grants` | function (modified) | ROOT blanket grant: active root membership → True for ANY module except `platform::*` (explicit exclusion), checked BEFORE the legacy `_TENANT_MEMBERSHIP_GRANTS` dict; the dict keeps governing only non-root membership roles | `backend/app/api/deps.py` |
| `authorize_identity` | function (modified) | Consults the membership grant path for every non-platform module (was `tenant::*`-only, which made the root grant unreachable for business modules); non-root users fall through to the permission engine unchanged | `backend/app/api/deps.py` |
| `RT_AGENT` manifest entry | constant (modified) | Bare `agent` declared actions widen to `create/read/update/delete/execute` matching real `require_permission(RT_AGENT, …)` endpoint usage so manifest-validated presets can grant agent-type CRUD (backend-only — the frontend manifest intentionally mirrors namespaced types only) | `backend/app/core/resource_types.py` |
| `uq_roles_global_name` | index (modified) | Partial unique index on BOTH dialects (`sqlite_where` added beside `postgresql_where`, mirroring the `tenant_membership` precedent); PostgreSQL DDL unchanged — no migration | `backend/app/db/models/identity.py` |
| `test_default_tenant_roles.py` | test (new) | Preset↔manifest consistency, seeding layout/idempotency/cross-tenant names, engine authorization through seeded roles, creation-path wiring, sweep backfill + idempotency, root blanket grant vs `platform::*` | `backend/tests/test_default_tenant_roles.py` |

Rows below are the **login-experience redesign additions (tasks 10.22–10.23, implemented)**. Existing rows above are unchanged.

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `LoginPage` | component (modified) | Tenancy-aware redesign: primary email + password card (`loginPassword`, available whenever the tenancy switch is on — self-registered platform accounts can sign back in) with inline error handling; success stores the token (established `access_token`/`setToken` pattern) + `setResolvedTenantSlug` and lands on `/dashboard`; OIDC button kept as a non-gating option (outlined beside the password form, contained alone); discreet platform-admin entry (`auth.platformAdminSignIn`) toggling the super-admin form whenever super admin is enabled; `setup_wizard` state removed; `tenantBlocked` / `tenantSignInUnavailable` guards preserved; tenancy-off behaviour unchanged minus the wizard state | `frontend/src/pages/auth/LoginPage.tsx` |
| `extractLoginErrorMessage` | function (new) | Shared error extraction for both sign-in forms (Error message → axios `response.data.detail` → i18n fallback `auth.loginFailed`) | `frontend/src/pages/auth/LoginPage.tsx` |
| `/setup` route + `SetupWizard` feature | route + feature (removed) | Public pre-auth setup wizard REMOVED (obsolete — OIDC is configured post-sign-in via System Config / Tenant Settings; the wizard must not be reachable pre-auth). Deleted: `frontend/src/pages/setup/SetupWizard.tsx`, `frontend/src/features/setup/*`, dead support modules `frontend/src/api/setupApi.ts` + `frontend/src/types/setup.ts`, their test files, and the stale wizard mock in `AppRouter.test.tsx`. Backend `/setup/*` endpoints and the `setup/` CLI tool are intentionally untouched | `frontend/src/app/AppRouter.tsx` (+ deleted files) |
| login i18n keys | resource (modified) | Added `auth.email`, `auth.platformAdminSignIn`, `auth.loginFailed`, `auth.noSignInAvailable`; removed dead `auth.setupWizard`, `auth.goToSetup`, `auth.loginAsSuperAdmin` and the wizard `setup` section (en.json is the only locale file) | `frontend/src/i18n/locales/en.json` |
| LoginPage tests | test (modified) | `LoginPage.refined.test.tsx` rewritten for the new state model (password sign-in incl. token storage/tenant-slug binding/inline errors, discreet super-admin entry, no-wizard negative assertions); `LoginPage.test.tsx` authStore mock completed | `frontend/src/__tests__/LoginPage.refined.test.tsx` (+ `LoginPage.test.tsx`) |

Rows below are the **workspace-address sign-in additions (task 10.24, implemented)**. Existing rows above are unchanged.

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `LoginPage` workspace-address flow | component (modified) | AWS-style sign-in when the tenancy switch is on and no tenant is in context: `WorkspacePhase` state machine (`idle`/`resolving`/`find`/`card` — legacy rendering on `idle`); "find your workspace" card (address input + "Remember this workspace" checkbox + Continue) resolving via public `discoverTenant(slug)`; active tenant binds the per-tab slug (`setResolvedTenantSlug` → `X-Tenant` everywhere) and renders the tenant-branded card (password form + context-scoped OIDC button); unknown slug → neutral `auth.findWorkspace.notFound` error; suspended address → existing `tenantBlocked` guard; host-derived flow, tenancy-off behaviour, `TenantPicker`, signup link and platform-admin entry untouched | `frontend/src/pages/auth/LoginPage.tsx` |
| `extractSlugCandidate` | function (new) | Slug derivation for the finder: bare slug accepted; pasted host/URL (`acme.example.com`, `https://acme.example.com/login`) reduced to its first DNS label with a `auth.findWorkspace.slugHint` helper text | `frontend/src/pages/auth/LoginPage.tsx` |
| `bindWorkspace` | function (new) | Single choke point binding an address-resolved tenant: sets page branding state + `setResolvedTenantSlug` before any tenant-scoped call | `frontend/src/pages/auth/LoginPage.tsx` |
| `?workspace=` deep link | behaviour (new) | `useSearchParams`-driven auto-resolve on /login — pre-resolves and lands on that tenant's card without implicit remembering (bookmarkable per-workspace sign-in URL); `?workspace=` beats the remembered hint | `frontend/src/pages/auth/LoginPage.tsx` |
| "Not your workspace?" switch link | behaviour (new) | Shown on the address-resolved card; clears the localStorage remember hint AND the sessionStorage tab binding and returns to the finder | `frontend/src/pages/auth/LoginPage.tsx` |
| `getRememberedTenantSlug` / `setRememberedTenantSlug` | functions (new) | localStorage `parthenon_login_tenant` convenience hint for returning visitors ("Remember this workspace"); always re-verified through public discovery before binding — never an access decision | `frontend/src/api/tenantAuthApi.ts` |
| `AuthProvider.refreshProviders` | method (new) | Provider/super-admin discovery extracted into an exposed callback; the login page re-runs it after binding a workspace so the OIDC start config (issuer/client) resolves for the tenant's provider (fetch reads `X-Tenant` at call time) | `frontend/src/stores/AuthContext.tsx` |
| providers query context key | behaviour (modified) | LoginPage providers React Query keyed by the bound workspace slug (`['system', 'identity-providers', slug]`) so the provider list re-resolves for the tenant context right after binding | `frontend/src/pages/auth/LoginPage.tsx` |
| workspace-address i18n keys | resource (modified) | Added `auth.findWorkspace.{subtitle,addressLabel,addressPlaceholder,slugHint,remember,continue,lookup,notFound,lookupFailed,notYourWorkspace}` (en.json is the only locale file) | `frontend/src/i18n/locales/en.json` |
| workspace-address LoginPage tests | test (modified) | 11 new cases in `LoginPage.refined.test.tsx`: finder-first rendering (remember default-checked, Continue gating), bare-slug + host-slug resolution → branded card (binding, remember, refreshProviders), neutral unknown-slug error, unchecked remember, remembered-skip, stale-hint fallback, `?workspace=` deep link (no implicit remember), switch-link storage clearing, suspended blocked state, signup/super-admin preserved on the finder | `frontend/src/__tests__/LoginPage.refined.test.tsx` |

Rows below are the **FIX-20260929-043443 additions (OIDC workspace session / tenant-claim provisioning, implemented)**. Existing rows above are unchanged.

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `_inject_tenant_claim` | function (new) | PRIMARY FIX — validation-time tenant claim injection (see auth middleware rows above) | `backend/app/middleware/auth.py` |
| `OidcCallback` completion binding | behaviour (modified) | SECONDARY FIX — after a successful token exchange the callback RE-BINDS the workspace tenant (parity with password login / sign-up): resolves the slug as token `tenant` claim (id_token, then access_token; claim wins over storage) → sessionStorage `parthenon_tenant_slug` → remembered `parthenon_login_tenant` → in-session memo; binds via the raw sessionStorage key + `setResolvedTenantSlug` (restores the binding even when the tab lost it during the provider round-trip); binds nothing when no source resolves (platform sign-in unchanged). Superseded by FIX-20260929-121120: the resolved source is now verified through public discovery before binding (see "OidcCallback verified bind" in the Code Reference Map) | `frontend/src/pages/auth/OidcCallback.tsx` |
| `OidcCallback` tenant-resolved exchange | behaviour (modified) | BONUS FIX — consumes the authority/client persisted by `login()` (sessionStorage `oidc_authority` / `oidc_client_id`, cleared after read) so the code is exchanged against the SAME tenant-resolved provider the authorize redirect started from; falls back to `VITE_OIDC_AUTHORITY`/`VITE_OIDC_CLIENT_ID` for legacy flows | `frontend/src/pages/auth/OidcCallback.tsx` |
| `AuthProvider.login` OIDC round-trip state | behaviour (modified) | Persists the resolved start config alongside the PKCE verifier (sessionStorage `oidc_authority` + `oidc_client_id`) so the callback can complete the exchange against a tenant provider whose issuer differs from the platform default | `frontend/src/stores/AuthContext.tsx` |
| `AuthProvider` discovery binding hardening | behaviour (modified) | Mount-time tenant discovery only (re)binds on an explicit echo (`discovery.tenant.slug` present) — a bare response no longer WIPES an existing explicit binding (clearing remains the explicit flows' job: workspace switch, logout) | `frontend/src/stores/AuthContext.tsx` |
| `test_oidc_tenant_claim_gap.py` | test (new) | Primary reproduction: token from the tenant's OWN provider must pass the full `validate_raw_token` → `_check_tenant_claim` pipeline in multi-tenant mode (claim-less realistic shape); controls isolate the defect to claim provisioning | `backend/tests/test_oidc_tenant_claim_gap.py` |
| `OidcCallback.test.tsx` | test (new) | Callback binding contract: authoritative re-bind on completion + restore when the tab lost the binding during the round-trip (plus passive-survival controls) | `frontend/src/__tests__/OidcCallback.test.tsx` |
| multi-tenant-login-flows dashboard mock | test (modified) | E2E dashboard mock mirrors the FIXED backend contract (bound session accepted — the claim is injected at validation time; missing X-Tenant → 401) so the SSO round-trip test guards the fixed behaviour | `e2e/tests/multi-tenant-login-flows.spec.ts` |

Rows below are the **FIX-20260929-221449 additions (identity plane is platform-level / shared identity providers / no-membership UX, implemented)**. Existing rows above are unchanged.

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `execute_unscoped` | function (new) | PRIMARY FIX (decision #1) — statement-scoped identity-plane exemption at the scoping choke point (see scoping section + row above) | `backend/app/db/tenant_scoping.py` |
| `NoWorkspaceAccessError` + `no_workspace_access_handler` | exception + handler (new) | No-membership UX (decision #3) — an authenticated user without an ACTIVE membership in the resolved tenant gets a clean `403 {"detail": "no_access_to_workspace", ...}` serialized FLAT by the app-level handler (an `HTTPException` subclass so the handler wins over FastAPI's default envelope). An authorization denial, NOT an auth failure: `apiClient` neither clears tokens nor self-heals the binding — the structured `required_permission` rides the top-level body so the permission snackbar surfaces it | `backend/app/api/deps.py`, `backend/app/main.py` |
| `authorize_identity` no-membership gate | behaviour (modified) | Resolves the PlatformUser tenant-scope-exempt, then REQUIRES an active membership in the resolved tenant (single `_active_membership` SELECT shared with `_membership_grants_from`); without one → `NoWorkspaceAccessError(required_permission=...)` before any data access. Super-admin platform-only semantics unchanged (returns before the gate) | `backend/app/api/deps.py` |
| `UserCacheService` identity-plane exemption | behaviour (modified) | `upsert_user` (by-sub + by-email), `get_user_by_sub`, `upsert_identity` (by-subject) resolve via `execute_unscoped` — JIT provisioning finds and refreshes the existing record on a scoped session instead of inserting a unique-violating duplicate | `backend/app/services/permissions/user_cache_service.py` |
| `OIDCProviderRegistry` shared slots | behaviour (modified) | SHARED identity providers (decision #2) — a NULL-tenant `IdentityProviderConfig` serves the platform AND any tenant without its own config; per-tenant slots take precedence; neither → fail-closed None; tenancy OFF unchanged. Superseded/extended by FIX-20260930-075014: the SYSTEM tenant's (adopted platform provider) slot is the final fallback for both tenant-scoped and tenant-less lookups. `_resolve_cached` applies the resolution consistently across provider/secret/JWKS/discovery/invalidation lookups | `backend/app/services/oidc_provider_registry.py` |
| `test_oidc_provider_fallback.py` | tests (new, FIX-20260930-075014) | Part A pins: system-slot fallback for tenant-less and tenant-scoped lookups (a/b), own-config precedence (c), shared-beats-system ordering, fail-closed + tenancy-OFF pins | `backend/tests/test_oidc_provider_fallback.py` |
| `test_oidc_jit_default_role.py` | tests (new, FIX-20260930-075014) | Part B pins: JIT membership + preset role on first OIDC sign-in (d), idempotency (e), unset-default → `no_access_to_workspace` (f), shared-provider default (g), system-slot default (h), platform-password no-JIT, audit event, endpoint-level admission | `backend/tests/test_oidc_jit_default_role.py` |
| Identity-plane lookup exemptions | behaviour (modified) | Every PlatformUser-by-sub / Identity-by-subject IDENTITY resolution runs tenant-scope-exempt: `require_tenant_membership` + `accept_invitation` (`tenant.py`), `list_my_tenant_memberships` (`auth_tenant.py`), `request_runtime_termination` (`agents.py`), `_resolve_user_id` (`dashboard_metrics_service.py`), operator Identity lookups (`intervene.py`, `conversations.py`, `internal/session_data.py`), Identity cascade on user deletion (`platform_users.py`). `require_tenant_membership`'s no-membership 403 now raises `NoWorkspaceAccessError(tenant_slug=...)`. Data-plane user listing/mutation guards stay membership-joined | various (see fix-log Code Changes §7) |
| `test_identity_plane.py` | test (new) | T1–T7: identity resolution exempt (T1), JIT upsert returns the existing row (T2), shared provider validates + injects the resolved-context claim (T3), own-slot precedence (T4), no-membership clean 403 shape (T5), member authorize passes (T6), data-plane listing stays membership-joined (T7) + registry-level shared/fail-closed/tenancy-off pins | `backend/tests/test_identity_plane.py` |
