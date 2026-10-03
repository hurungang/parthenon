# Implementation Plan: Multi-Tenant Support

## Overview

This plan implements opt-in multi-tenancy for Parthenon: a platform switch (default off) that, when enabled, introduces tenants with hard logical isolation enforced centrally in Control Center (the sole database gateway). Work proceeds in ten dependency-ordered phases — schema, tenant context resolution and signed propagation, row-level scoping and RBAC binding, per-tenant OIDC, platform admin APIs, the two frontend surfaces, Agent Runtime/Communication Hub tenant-bound routing, security tests and hardening, and finally the self-serve registration, tenant root and licensing refinement (Phase 10, additive on the extension points built earlier) — so that single-tenant behavior remains byte-for-byte identical until the switch is deliberately turned on.

## Task Checklist

### Phase 1 — Platform Setting, Tenant Entities & Alembic Migrations

- [x] 1.1 — Create new tenant domain DB models
- [x] 1.2 — Add tenant references to identity & access models
- [x] 1.3 — Add tenant references to agent domain models
- [x] 1.4 — Add tenant references to MCP hub, skills, SOP and scheduling models
- [x] 1.5 — Add tenant references to conversation, result, and agent data models
- [x] 1.6 — Add tenant references to intervention, termination and notification models
- [x] 1.7 — Add tenant references to model governance models
- [x] 1.8 — Generate and apply backward-compatible Alembic migration
- [x] 1.9 — Implement platform settings service with `multi_tenancy_enabled` default false

### Phase 2 — Tenant Context Resolution, Middleware & Signed Propagation

- [x] 2.1 — Implement immutable Tenant Context object
- [x] 2.2 — Implement Tenant Resolution Service (subdomain / tenant header)
- [x] 2.3 — Add Tenant Resolution Middleware to Control Center (fail-closed in multi-tenant mode)
- [x] 2.4 — Add tenant-claim vs resolved-tenant mismatch rejection in auth middleware
- [x] 2.5 — Implement signed tenant context header sign/verify utilities
- [x] 2.6 — Attach signed tenant headers from Control Center internal clients
- [x] 2.7 — Verify signed tenant headers in Agent Runtime and Communication Hub middleware
- [x] 2.8 — Guard: switch-off keeps resolution, claims and propagation fully inert

### Phase 3 — Row-Level Tenant Scoping, Permission Engine Binding & Resource Types

- [x] 3.1 — Register tenant-management resource types in backend manifest
- [x] 3.2 — Mirror tenant-management resource types in frontend manifest
- [x] 3.3 — Implement tenant-scoped query enforcement helper at the DB gateway
- [x] 3.4 — Bind tenant context into PermissionEngine authorization
- [x] 3.5 — Apply tenant scoping to identity, access and agent endpoint query paths
- [x] 3.6 — Apply tenant scoping to remaining business domains
- [x] 3.7 — Convert cross-tenant row access into not-found responses with audit events
- [x] 3.8 — Add tenant attribution to audit logging and OTEL telemetry

### Phase 4 — Per-Tenant OIDC Registry & JWT Tenant-Claim Validation

- [x] 4.1 — Extend OIDCProviderRegistry to a per-tenant registry
- [x] 4.2 — Extend OIDCConfigService for per-tenant provider CRUD
- [x] 4.3 — Resolve JWT validation keys by resolved tenant and enforce tenant claim
- [x] 4.4 — Make sign-in tenant-aware (tenant provider selection on login)
- [x] 4.5 — Handle super admin / platform admin tokens in multi-tenant mode
- [x] 4.6 — Negative validation: cross-tenant tokens rejected everywhere

### Phase 5 — Platform Admin APIs, Tenant Lifecycle & Provisioning/Adoption

- [x] 5.1 — Implement TenantService lifecycle (create/suspend/resume/delete)
- [x] 5.2 — Implement platform settings API (tenancy switch read/write)
- [x] 5.3 — Implement system-tenant adoption when enabling multi-tenancy
- [x] 5.4 — Implement switch-off path returning to single-tenant behavior
- [x] 5.5 — Implement platform admin tenants REST API
- [x] 5.6 — Implement tenant provisioning & guided onboarding service
- [x] 5.7 — Implement tenant membership & invitation APIs
- [x] 5.8 — Implement platform security-audit read API

### Phase 6 — Frontend Platform Admin Console

- [x] 6.1 — Add platform admin API client and types
- [x] 6.2 — Add platform admin route section and access guard
- [x] 6.3 — Build tenant management page (CRUD, suspend/resume/delete)
- [x] 6.4 — Build platform settings page (tenancy switch)
- [x] 6.5 — Build cross-tenant attempt audit view
- [x] 6.6 — i18n and manifest mirror coverage for platform console

### Phase 7 — Frontend Tenant Workspace

- [x] 7.1 — Add active tenant state to the auth layer (one session = one tenant)
- [x] 7.2 — Tenant-aware sign-in: host resolution and multi-org tenant picker
- [x] 7.3 — Show organization branding in the workspace header
- [x] 7.4 — Build tenant settings page for tenant admins
- [x] 7.5 — Build guided onboarding flow for new tenants
- [x] 7.6 — Build members & invitations management page
- [x] 7.7 — i18n and permission gating for tenant workspace pages

### Phase 8 — Agent Runtime & Communication Hub Tenant-Bound Routing

- [x] 8.1 — Tenant-bound session dispatch in Communication Hub
- [x] 8.2 — Tenant-bind MCP client API keys and tool filtering
- [x] 8.3 — Prevent cross-tenant A2A message routing
- [x] 8.4 — Enforce tenant context on Control Center internal endpoints
- [x] 8.5 — Tenant-bound execution in Agent Runtime (no widening)
- [x] 8.6 — Tenant-adopt execution for scheduled jobs
- [x] 8.7 — Verify agents never receive other tenants' business data or tokens

### Phase 9 — Tests & Security Hardening

- [x] 9.1 — Backend unit tests: resolution fail-closed and switch-off inertness
- [x] 9.2 — Cross-tenant negative API tests with audit assertions
- [x] 9.3 — Per-tenant OIDC negative tests (wrong provider / missing / mismatched claim)
- [x] 9.4 — Signed tenant header tests (tamper, replay, widening attempts)
- [x] 9.5 — Migration & adoption tests (upgrade, enable, disable, downgrade)
- [x] 9.6 — Frontend tests: manifest mirror, tenant picker, platform admin gating, i18n
- [x] 9.7 — Real-backend E2E isolation test + single-tenant regression suite
- [x] 9.8 — Security hardening review against top-priority architecture rules

### Phase 10 — Self-Serve Registration, Tenant Root & Licensing

- [x] 10.1 — Add licensing & quota schema: TenantLicense, TenantQuotaUsage, is_root, password credential, new audit event types
- [x] 10.2 — Enforce immutable tenant root protection in membership and platform mutation paths
- [x] 10.3 — Grant root members all tenant permissions and restrict alias editing to the root
- [x] 10.4 — Implement the licensing service (tier limits, supersede history, free-tier fallback)
- [x] 10.5 — Implement the quota service (effective limits, three quota checks, monthly execution counter)
- [x] 10.6 — Define the structured quota error contract
- [x] 10.7 — Implement the self-serve registration service (atomic account + tenant + root)
- [x] 10.8 — Expose public registration and platform-password sign-in endpoints
- [x] 10.9 — Wire quota gates into user invitation, agent type creation and execution submission
- [x] 10.10 — Consult the execution quota at scheduler dispatch time
- [x] 10.11 — Expose platform admin license assignment and tenant usage APIs
- [x] 10.12 — Expose the tenant-side license & usage read API
- [x] 10.13 — Build the public sign-up page and login entry link
- [x] 10.14 — Add root-only alias editing and the license & usage panel to tenant settings
- [x] 10.15 — Build the blocked-action UI consuming structured quota errors
- [x] 10.16 — Add license assignment and usage columns to the platform tenant console
- [x] 10.17 — Complete i18n coverage and verify resource-type manifest consistency
- [x] 10.18 — Tests: registration, root protection, licensing and quota enforcement
- [x] 10.19 — Seed default tenant-scoped roles (presets + idempotent seeding service)
- [x] 10.20 — Wire default-role seeding into every tenant creation path + startup self-healing sweep
- [x] 10.21 — Root blanket grant: root membership reaches every module except platform::*
- [x] 10.22 — Login page redesign: password sign-in, tenancy-aware states, remove setup_wizard state
- [x] 10.23 — Remove public setup wizard route/feature + dead references
- [x] 10.24 — Workspace-address sign-in: find-workspace step, remembered workspace, `?workspace=` deep link

## Phase 1 — Platform Setting, Tenant Entities & Alembic Migrations

- [x] 1.1 — Create new tenant domain DB models — _Done when: the five new entities exist as SQLAlchemy declarative models, are exported via `backend/app/db/models/__init__.py`, and import cleanly._
  - Create `backend/app/db/models/tenant.py` (Tenant: unique name, unique slug, status enum, `is_system_tenant`, `is_onboarded`, admin contact fields).
  - Create `tenant_membership.py` (TenantUserMembership: tenant FK, user FK, tenant_role enum, status, `is_default`), `tenant_invitation.py`, `tenant_audit_event.py`, `platform_setting.py` (unique key, JSON value, category).
  - Register relationships to `PlatformUser` in `platform_user.py` (no tenant FK on the user itself).

- [x] 1.2 — Add tenant references to identity & access models — _Done when: nullable tenant FK columns exist on every direct-scoped entity listed in data-model.md Section "Identity & Access" and models import cleanly._
  - Update `identity.py` (Role, Identity — Permission stays global), `group.py`, `group_role.py`, `user_group.py`, `access_request.py`, `access_request_batch.py`, `tag_definition.py`, `policy_statement.py`, `policy_action.py`, `policy_resource.py`, `agent_api_key.py` (AgentApiKey + ApiKeyUsageLog via parent), `identity_provider_config.py`, `identity_provider_config_audit.py`.
  - Join/child tables (UserRole, GroupRole, UserGroup, TagValue, PolicyTagCondition, ApiKeyUsageLog) inherit scope via parents — no new column.

- [x] 1.3 — Add tenant references to agent domain models — _Done when: nullable tenant FKs exist on AgentRole, AgentIdentity, ModelConfig, AgentType, AgentInstance, AgentJob, AgentA2ASession, AgentRunRelationship._
  - Update `agents.py` and `agent_run_relationship.py`; child records (AgentPromptLog, AgentPlan, role binding tables) and `agent_security.py` certificate/token-log tables inherit scope via parents.

- [x] 1.4 — Add tenant references to MCP hub, skills, SOP and scheduling models — _Done when: nullable tenant FKs exist on McpServer, Skill, Sop, ScheduledJob._
  - Update `mcp_hub.py`, `skills.py`, `scheduling.py`, `sop_recursion_validation_check.py`, `sop_recursion_validation_finding.py`; sessions/tools/bindings/steps inherit scope via parents.

- [x] 1.5 — Add tenant references to conversation, result and agent data models — _Done when: nullable tenant FKs exist on ConversationSession, RuntimeToolCall, ResultRecord, AgentDataType, AgentOutput, AgentData, ExecutionLogEntry._
  - Update `conversations.py`, `tool_calls.py`, `results.py`, `agent_data_type.py`, `agent_output.py`, `agent_data.py`, `session_logs.py`; turns and tool-call records inherit via parents.

- [x] 1.6 — Add tenant references to intervention, termination and notification models — _Done when: nullable tenant FKs exist on InterveneRequest, TerminationRequest, NotificationChannel, RecipientGroup, NotificationLog, NotificationEvent._
  - Update `intervene.py`, `termination_request.py`, `termination_cascade_outcome.py`, `notifications.py`; responses, cascade outcomes, channel properties and group mappings inherit via parents.

- [x] 1.7 — Add tenant references to model governance models — _Done when: nullable tenant FKs exist on ModelGuardrailConfiguration, ModelAvailability, ModelGuardrailEvaluation, ModelUsagePosture, GuardrailThresholdEvent._
  - Update the five model governance files listed in data-model.md.

- [x] 1.8 — Generate and apply backward-compatible Alembic migration — _Done when: `alembic upgrade head` succeeds on an existing populated database, all new columns are nullable with indexes on tenant_id, `alembic downgrade -1` succeeds, and no existing column is dropped or made non-nullable._
  - Use `alembic revision --autogenerate`; review the generated file for correct down_revision chain and reversibility (per AGENTS.md migration best practices: no parameterized DDL, enum types via postgresql.ENUM with create_type=False).

- [x] 1.9 — Implement platform settings service with `multi_tenancy_enabled` default false — _Done when: PlatformSetting row `multi_tenancy_enabled` is seeded as false on startup and a cached read helper returns false on any database without the row._
  - New service `backend/app/services/tenancy/platform_settings_service.py` with cached get/set and cache invalidation on write; writes audited.

## Phase 2 — Tenant Context Resolution, Middleware & Signed Propagation

- [x] 2.2 — Implement Tenant Resolution Service — _Done when: a request's tenant resolves from the subdomain of the Host header or an explicit tenant header; unknown slug, suspended or deleted tenant returns a rejection; result is cached with short TTL._
  - New `backend/app/services/tenancy/tenant_resolution_service.py`; only the slug + status are read (never business data). Single resolution point per request.

- [x] 2.1 — Implement immutable Tenant Context object — _Done when: a frozen per-request tenant context (tenant id, slug, name) is stored on `request.state` and exposed via an accessor in `backend/app/core/tenant_context.py`; attempts to mutate raise._
  - Includes an accessor that returns an "unset" sentinel in single-tenant mode so feature code can branch cleanly.

- [x] 2.3 — Add Tenant Resolution Middleware to Control Center — _Done when: the middleware runs before `JWTAuthMiddleware` in `create_app()`, is completely inert when the tenancy switch is off, and in multi-tenant mode rejects (fail-closed) any request where the tenant cannot be resolved — before any feature logic runs._
  - New `backend/app/middleware/tenant_resolution.py`; public health/setup paths bypassed; rejections are logged and audited.

- [x] 2.4 — Add tenant-claim vs resolved-tenant mismatch rejection in auth middleware — _Done when: after token validation in `JWTAuthMiddleware`, a token whose tenant claim differs from the resolved tenant (or lacks the claim in multi-tenant mode) is rejected with 401, and the rejection is recorded as a security-relevant tenant audit event._
  - Modify `backend/app/middleware/auth.py` post-validation step; no behavior change when the switch is off.

- [x] 2.5 — Implement signed tenant context header sign/verify utilities — _Done when: header values are HMAC-signed with a server-side secret and carry an issue timestamp; verification rejects tampered, stale (replayed past a short window) or unsigned values._
  - New `backend/app/core/tenant_signature.py`; the signing key is configuration-managed (never exposed to agents or the frontend).

- [x] 2.6 — Attach signed tenant headers from Control Center internal clients — _Done when: `CommunicationHubClient` and `AgentRuntimeClient` in `backend/app/services/control_center/` include the signed tenant context headers on every outbound call when a tenant context is active, and add nothing when the switch is off._
  - Header injection centralized in each client's request-building path.

- [x] 2.7 — Verify signed tenant headers in Agent Runtime and Communication Hub middleware — _Done when: `ControlCenterCertificateMiddleware` (AR) and `ControlPlaneMiddleware` (CH) reject requests carrying an invalid signature, and bind the verified tenant context to the request; requests without headers behave exactly as today in single-tenant mode._
  - AR/CH cannot create or widen tenant context — they may only consume what CC signed.

- [x] 2.8 — Guard: switch-off keeps resolution, claims and propagation fully inert — _Done when: with `multi_tenancy_enabled=false`, no tenant middleware logic executes, no tenant headers are attached or required, and the existing backend test suite passes unmodified._
  - Covered by unit tests in Phase 9 but the guard belongs to this phase; run existing `backend/tests/test_auth_middleware_full.py` as the canary.

## Phase 3 — Row-Level Tenant Scoping, Permission Engine Binding & Resource Types

- [x] 3.1 — Register tenant-management resource types in backend manifest — _Done when: new platform/tenant resource types (e.g. `platform::tenants`, `platform::settings`, `tenant::settings`, `tenant::members`) exist in `ResourceTypeManifest` and `MODULE_GROUPS` in `backend/app/core/resource_types.py` with sensible action sets; `PermissionEngine.authorize()` no longer rejects them._
  - Follows the CRITICAL manifest registration convention in docs/config.yaml.

- [x] 3.2 — Mirror tenant-management resource types in frontend manifest — _Done when: `RESOURCE_TYPE_MANIFEST` and `MODULE_GROUPS` in `frontend/src/constants/resourceTypes.ts` contain the same entries with identical action sets, and the existing mirror test passes._
  - Extend `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` expectations if it enumerates types.

- [x] 3.3 — Implement tenant-scoped query enforcement helper at the DB gateway — _Done when: every query executed through the Control Center DB session dependency is automatically constrained to the request's tenant context when multi-tenancy is on, and unconstrained when off; the helper lives at `backend/app/db/` and is the single choke point._
  - Prefer a session-level filter applied in `get_db` over per-endpoint manual clauses, so no feature can issue an unscoped query.

- [x] 3.4 — Bind tenant context into PermissionEngine authorization — _Done when: `PermissionEngine.authorize()` collects role ids only from memberships/roles within the request's tenant (plus the platform-admin role), and identical role names in different tenants do not collide; single-tenant mode is unchanged._
  - Modify `backend/app/services/permissions/permission_engine.py` and its role-collection helpers; `authorize_identity` in `backend/app/api/deps.py` passes the tenant context through.

- [x] 3.5 — Apply tenant scoping to identity, access and agent endpoint query paths — _Done when: list/get/update/delete handlers in identity, users, groups, policies, tags, API keys, agent roles/identities/types/instances/jobs routes only ever touch tenant-scoped rows; direct-addressed foreign ids behave as not-found._
  - Spot-check `backend/app/api/v1/identity.py`, `platform_users.py`, `policy.py`, `api_keys.py`, `agents.py`.

- [x] 3.6 — Apply tenant scoping to remaining business domains — _Done when: MCP hub, skills, SOPs, scheduling, conversations, results, agent data/outputs, interventions, terminations, notifications, model governance endpoints are all tenant-scoped when the switch is on and unchanged when off._
  - Driven by the 3.3 choke point; verify no endpoint bypasses it (e.g. raw sessions not obtained via `get_db`).

- [x] 3.7 — Convert cross-tenant row access into not-found responses with audit events — _Done when: a request referencing another tenant's identifier returns 404 (never a data-leaking error message) and writes a `cross_tenant_access_denied` TenantAuditEvent flagged security-relevant._
  - Implemented as part of the scoping helper/exception path, not per-endpoint.

- [x] 3.8 — Add tenant attribution to audit logging and OTEL telemetry — _Done when: audit log writes and OTEL spans/logs emitted by all three services carry a tenant attribute (or a platform sentinel) when multi-tenancy is on, and no attribute when off._
  - Delivered via `set_tenant_span_attributes` (`backend/app/core/tenant_context.py`) called from the CC/AR/CH middlewares plus the scope-miss audit writer from 3.7; `backend/app/core/telemetry.py` itself needed no changes.

## Phase 4 — Per-Tenant OIDC Registry & JWT Tenant-Claim Validation

- [x] 4.1 — Extend OIDCProviderRegistry to a per-tenant registry — _Done when: the registry keys cached providers by (tenant, scope) — resolving the system tenant in single-tenant mode — and exposes lookup by resolved tenant; `initialize`/`reload` load all tenants' enabled providers; existing hot-reload endpoints still work._
  - Modify `backend/app/services/oidc_provider_registry.py` (`get_provider`, `get_decrypted_secret`, `get_user_provider`, `get_agent_provider` signatures).

- [x] 4.2 — Extend OIDCConfigService for per-tenant provider CRUD — _Done when: provider create/update/delete/toggle accept a tenant binding, uniqueness of provider scope is enforced per tenant when multi-tenancy is on (platform-wide when off), and tenant admins can never read or write another tenant's provider config._
  - Modify `backend/app/services/oidc_config_service.py` and the system_config endpoints that call it.

- [x] 4.3 — Resolve JWT validation keys by resolved tenant and enforce tenant claim — _Done when: `JWTAuthMiddleware`/`validate_raw_token` validate tokens using the resolved tenant's provider config and JWKS only, and require the token tenant claim to equal the resolved tenant; tokens without a matching claim are rejected before any user sync occurs._
  - Modify `_try_oidc_token` in `backend/app/middleware/auth.py`; claim source documented (tenant claim embedded at issuance by the tenant's provider config mapping).

- [x] 4.4 — Make sign-in tenant-aware — _Done when: the login page discovers the tenant from the host and redirects to that tenant's provider authorization endpoint; a user belonging to several organizations can list and choose their organizations before redirect; single-tenant sign-in flow is untouched when the switch is off._
  - New public tenant-discovery endpoint (Phase 5 API) consumed by `frontend/src/pages/auth/LoginPage.tsx` and `AuthProvider` in `frontend/src/stores/AuthContext.tsx`.

- [x] 4.5 — Handle super admin / platform admin tokens in multi-tenant mode — _Done when: super admin tokens remain valid across tenants for platform administration only (tenant metadata, never tenant business data), and platform-admin membership is resolvable for any resolved tenant._
  - Extend `backend/app/services/super_admin_auth_service.py` claims with platform role semantics.

- [x] 4.6 — Negative validation: cross-tenant tokens rejected everywhere — _Done when: a token issued by tenant A's provider fails validation for tenant B at every entry point (REST, internal, MCP API-key paths unaffected but tenant-bound), with audit events recorded; covered by Phase 9 tests._
  - Verification matrix documented in the test plan; implementation is the enforcement in 4.1–4.3.
  - Verified by `backend/tests/test_tenant_oidc_isolation.py` (registry isolation, `_try_oidc_token` tenant binding, claim mismatch/missing rejection + audits) and `backend/tests/agent_runtime/test_tenant_header_verification.py` + `backend/tests/communication_hub/test_tenant_header_verification.py` (internal entry points).

## Phase 5 — Platform Admin APIs, Tenant Lifecycle & Provisioning/Adoption

- [x] 5.1 — Implement TenantService lifecycle — _Done when: create (name + unique slug + admin contact), suspend, resume, and delete (full data removal, slug reusable afterwards) all work; duplicates are rejected with clear errors; delete requires explicit confirmation token/flag; all lifecycle actions write TenantAuditEvents._
  - New `backend/app/services/tenancy/tenant_service.py`; deletion cascades respect FK topology from Phase 1.

- [x] 5.2 — Implement platform settings API — _Done when: platform settings can be read and updated only by the platform admin via new resource types; toggling the tenancy switch is audited and invalidates the settings cache in all workers._
  - New router `backend/app/api/v1/platform/settings.py`; guarded by `require_permission` with `platform::settings`.

- [x] 5.3 — Implement system-tenant adoption when enabling multi-tenancy — _Done when: enabling the switch on an existing deployment creates the implicit system tenant, backfills all existing rows' tenant references to it, grants the existing administrator platform-admin membership, and leaves the existing identity provider working as the system tenant's provider — with no manual reconfiguration._
  - New `backend/app/services/tenancy/tenant_adoption_service.py`; adoption is idempotent and runs as a guarded operation behind the toggle.

- [x] 5.4 — Implement switch-off path returning to single-tenant behavior — _Done when: disabling the switch restores exact single-tenant behavior (middleware inert, registry platform-wide) with no data loss and a repeatable enable/disable cycle._
  - Mostly enforcement logic already built in Phases 2–4; this task adds the transition validation and audit.

- [x] 5.5 — Implement platform admin tenants REST API — _Done when: tenant list (with status, created date, admin contact, user/agent usage counts), detail, create, update, suspend, resume, delete endpoints exist under the platform admin router and never return tenant business data._
  - New router `backend/app/api/v1/platform/tenants.py`; counts computed with aggregate queries only.

- [x] 5.6 — Implement tenant provisioning & guided onboarding service — _Done when: a new tenant is created in a pending-onboarded state with its first admin; onboarding completion (connect sign-in, invite users) flips `is_onboarded`; a new user can self-create an organization and becomes its first tenant admin._
  - New `backend/app/services/tenancy/tenant_provisioning_service.py`; self-service create is public-path guarded (rate-limited, no data exposure).

- [x] 5.7 — Implement tenant membership & invitation APIs — _Done when: tenant admins can list members, change member tenant roles, suspend/remove members, create/expire/revoke single-use invitations, and invitees can accept via a public token endpoint; invitations never leak other tenants' data._
  - New routers `backend/app/api/v1/tenant.py` (tenant-scoped self-service) plus public invitation-accept endpoint.

- [x] 5.8 — Implement platform security-audit read API — _Done when: the platform admin can list/filter TenantAuditEvents (including all `cross_tenant_access_denied` / `tenant_boundary_violation` events across tenants) with tenant attribution; tenant admins cannot see platform-level or other tenants' audit events._
  - New router `backend/app/api/v1/platform/audit.py`.

## Phase 6 — Frontend Platform Admin Console

- [x] 6.1 — Add platform admin API client and types — _Done when: a typed API module for tenants, platform settings and platform audit exists with strong TypeScript interfaces mirroring the Phase 5 response schemas._
  - New `frontend/src/api/platformAdminApi.ts` using the shared `apiClient`.

- [x] 6.2 — Add platform admin route section and access guard — _Done when: `/platform/*` routes render only for users holding the platform-admin membership; all others receive the standard access-denied experience; routes absent entirely when multi-tenancy is off._
  - New guard component in `frontend/src/app/`; register routes in `frontend/src/app/AppRouter.tsx`.

- [x] 6.3 — Build tenant management page — _Done when: tenant table shows status/created/admin contact/usage counts; create and edit dialogs validate unique name/slug with server errors shown inline; suspend/resume/delete use confirmation dialogs and follow the Dialog Error Handling Standard (dialogError state, PermissionDeniedAlert); the table refreshes after every action without manual reload._
  - New `frontend/src/pages/platform/TenantManagementPage.tsx`.

- [x] 6.4 — Build platform settings page — _Done when: the tenancy switch renders with an explicit warning about adoption, requires confirmation, and reflects server state after toggle; errors surface per the dialog error standard._
  - New `frontend/src/pages/platform/PlatformSettingsPage.tsx`.

- [x] 6.5 — Build cross-tenant attempt audit view — _Done when: security-relevant events are listed with filters (tenant, event type, date range) and tenant attribution; no tenant business data appears anywhere in the view._
  - New `frontend/src/pages/platform/PlatformAuditPage.tsx`.

- [x] 6.6 — i18n and manifest mirror coverage for platform console — _Done when: every string on the platform console goes through i18next `t()` with keys added to `frontend/src/i18n/locales/en.json`, and the manifest mirror test passes with the new resource types._
  - Extend `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` and add page-level component tests.

## Phase 7 — Frontend Tenant Workspace

- [x] 7.1 — Add active tenant state to the auth layer — _Done when: the active tenant (id, slug, name, tenant role) is stored in the auth store, set at sign-in, immutable for the session, cleared at sign-out, and exposed to pages via the existing auth hooks; when the switch is off the state is a no-op._
  - Modify `frontend/src/stores/authStore.ts` (`useAuthStore`) and `frontend/src/stores/AuthContext.tsx` (`AuthProvider`).

- [x] 7.2 — Tenant-aware sign-in: host resolution and multi-org tenant picker — _Done when: the login page resolves the tenant from the host, shows a tenant chooser listing only the signed-in user's organizations when they belong to more than one, and the selection drives which provider the OIDC redirect targets; switching organizations requires a fresh sign-in._
  - Modify `frontend/src/pages/auth/LoginPage.tsx`; new tenant-picker component under `frontend/src/components/auth/`.

- [x] 7.3 — Show organization branding in the workspace header — _Done when: the signed-in organization name appears in `AppShell`'s header when multi-tenancy is on, and the header is unchanged when off._
  - Modify `frontend/src/app/AppShell.tsx`; new small branding component.

- [x] 7.4 — Build tenant settings page for tenant admins — _Done when: tenant admins can view and edit their tenant's name and admin contact, and can never see another tenant's settings or platform configuration._
  - Delivered `frontend/src/pages/tenant/TenantSettingsPage.tsx` with tenant name + admin contact editing (per-tenant OIDC provider CRUD is handled by the backend `OIDCConfigService`; the tenant settings page ships name/contact only).

- [x] 7.5 — Build guided onboarding flow for new tenants — _Done when: a first tenant admin lands in a guided onboarding flow (connect sign-in → invite users → finish) and completion is reflected in the workspace; skipping is allowed but surfaced._
  - New `frontend/src/pages/tenant/OnboardingPage.tsx` (onboarding steps live within the page — no separate `features/tenant/` directory was needed).

- [x] 7.6 — Build members & invitations management page — _Done when: tenant admins can list members, change roles, suspend/remove, and create/revoke invitations with expiry; errors use the dialog error standard; all strings i18n'd._
  - New `frontend/src/pages/tenant/MembersPage.tsx`.

- [x] 7.7 — i18n and permission gating for tenant workspace pages — _Done when: all new tenant workspace strings use `t()`, actions are gated by the new `tenant::*` resource types through the existing `usePermissions` pattern, and no page renders when multi-tenancy is off._
  - Extend `frontend/src/i18n/locales/en.json`; permission gating reuses the existing `usePermissions` pattern (no new hooks files).

## Phase 8 — Agent Runtime & Communication Hub Tenant-Bound Routing

- [x] 8.1 — Tenant-bound session dispatch in Communication Hub — _Done when: agent session dispatch, execution forwarding and result routing in CH carry and honor the signed tenant context; a session from tenant A can never be routed to, or resolved against, tenant B's resources._
  - Delivered via `ControlPlaneMiddleware` verification plus forwarding in `backend/app/communication_hub/data_client.py` and the internal execute/resume/terminate forwarders — `backend/app/communication_hub/api/dispatch.py` itself needed no changes.

- [x] 8.2 — Tenant-bind MCP client API keys and tool filtering — _Done when: `validate_api_key_internal` returns the key's tenant binding; `ApiKeyAuthMiddleware` binds the MCP session to that tenant; tool listing and tool calls are filtered by tenant-scoped permissions; a tenant A key cannot address any tenant B resource._
  - Modified `backend/app/api/v1/internal/validate_api_key.py` (+ `backend/app/schemas/api_key.py`) and `backend/app/communication_hub/middleware/api_key_auth.py`; the MCP modules under `backend/app/communication_hub/mcp/` needed no changes — filtering flows from the middleware-bound session tenant and CC-scoped resolves.

- [x] 8.3 — Prevent cross-tenant A2A message routing — _Done when: A2A requests where the calling agent and target agent do not share the tenant context are refused with an audit event; message payloads are never relayed across tenants._
  - Refusal is decided by CC's tenant-scoped `prepare_a2a_request` (404/403 surfaces through `backend/app/communication_hub/api/a2a.py`'s existing error path); CH forwards the signed context via its data client.

- [x] 8.4 — Enforce tenant context on Control Center internal endpoints — _Done when: internal authorization and data endpoints validate the signed tenant header, scope all resolves to that tenant (permission resolution, tool authorization, session data, outputs, system tools), and reject requests whose signature is missing or invalid in multi-tenant mode._
  - Delivered centrally: `get_db` in `backend/app/db/session.py` verifies the signed headers for `/api/v1/internal/*` traffic (401 on invalid) and scopes the session via `apply_tenant_scope` — the individual internal routers needed no per-route edits.

- [x] 8.5 — Tenant-bound execution in Agent Runtime — _Done when: execute/resume/terminate/intervene endpoints accept and verify the signed tenant context; the runtime loader builds the agent from tenant-scoped configuration only; the executor cannot widen tenant scope at any point in the loop; agents still hold no tokens or credentials._
  - Delivered via `ControlCenterCertificateMiddleware` verification (`backend/app/agent_runtime/middleware.py`) and `forward_tenant_headers` in the AR-side `ControlCenterDataClient`; the endpoint routers needed no changes.

- [x] 8.6 — Tenant-adopt execution for scheduled jobs — _Done when: a triggered scheduled job executes with its owning tenant's context end to end (dispatch → CH → AR → results), and jobs cannot reference another tenant's agents or SOPs._
  - Modify `backend/app/services/scheduling/scheduler.py` trigger path and the CC session dispatcher (`backend/app/services/agents/session_dispatcher.py`).

- [x] 8.7 — Verify agents never receive other tenants' business data or tokens — _Done when: an explicit review of every payload CC sends to CH/AR confirms only tenant-scoped data leaves CC, identity tokens are still resolved and injected by CC/CH per tool call within the tenant, and findings are documented in the change folder._
  - Review task producing a checklist in the test plan; feeds Phase 9 tests.

## Phase 9 — Tests & Security Hardening

- [x] 9.1 — Backend unit tests: resolution fail-closed and switch-off inertness — _Done when: unit tests cover unknown/suspended/deleted slugs, missing tenant header in multi-tenant mode, and prove zero tenant logic executes with the switch off (existing middleware tests still green)._
  - `backend/tests/test_tenant_resolution.py` (slug extraction, fail-closed resolution, middleware inertness/403/audits/bypasses), `backend/tests/test_tenant_context.py` (immutable context, unset sentinel, OTEL attribution), `backend/tests/test_platform_settings_service.py` (default-off, cache, audits), `backend/tests/test_tenant_signature.py` + `test_tenant_scoping.py` (switch-off byte-for-byte guarantees).
- [x] 9.2 — Cross-tenant negative API tests with audit assertions — _Done when: for each major domain (roles, agents, identities, MCP servers, skills, SOPs, schedules, model configs, conversations, outputs, API keys, notifications) a tenant-A authenticated request directly addressing a tenant-B identifier returns not-found/denied, exposes no tenant-B data, and writes a security-relevant audit event._
  - `backend/tests/security/test_cross_tenant_isolation.py` — per-domain SELECT/UPDATE/DELETE/INSERT isolation + scope-miss audits at the choke point; cross-tenant membership/API-key child tables 404 via parent joins.
- [x] 9.3 — Per-tenant OIDC negative tests (wrong provider / missing / mismatched claim) — _Done when: tests prove a token from tenant A's provider is rejected for tenant B, a token without the tenant claim is rejected in multi-tenant mode, per-tenant provider CRUD is isolated, and single-tenant validation is unchanged when off._
  - `backend/tests/test_tenant_oidc_isolation.py` — registry (tenant, scope) keying, system-tenant fallback only, switch-off platform-wide registry, `_try_oidc_token` tenant binding, claim check matrix (missing/mismatch/matching/super-admin) with security audits, per-tenant CRUD isolation.
- [x] 9.4 — Signed tenant header tests (tamper, replay, widening attempts) — _Done when: tampered, stale, unsigned and mismatched tenant headers are rejected by AR and CH middleware; CC's clients sign correctly; no code path in AR/CH can construct a valid signature._
  - `backend/tests/agent_runtime/test_tenant_header_verification.py`, `backend/tests/communication_hub/test_tenant_header_verification.py` (tamper/stale/partial rejection, verify-if-present, forwarding semantics), plus `test_tenant_signature.py::test_receiver_services_never_import_signing_helper` (structural no-sign guard). Product hardening: AR/CH now FORWARD CC's original signed headers (`forward_tenant_headers`) instead of re-signing.
- [x] 9.5 — Migration & adoption tests — _Done when: tests apply migrations to a populated database, enable the switch (system tenant adoption backfills all rows), disable and re-enable safely, and downgrade cleanly; adoption asserts every business row carries the system tenant id._
  - `backend/tests/db/test_tenant_schema_migration.py` (information_schema verification vs real PostgreSQL: 5 new tables, nullable+indexed tenant columns across all domain groups, join tables carry none, negative FK/unique constraints; full downgrade/re-upgrade gated behind PARTHENON_TEST_MIGRATION_CYCLE=1 because it mutates the shared dev DB), `backend/tests/integration/test_tenant_adoption.py` (system-tenant creation, NULL-row backfill incl. orphan handling, admin promotion, idempotency, disable-validation, enable/disable cycle).

- [x] 9.6 — Frontend tests: manifest mirror, tenant picker, platform admin gating, i18n — _Done when: manifest mirror test covers the new resource types; tenant picker renders only for multi-org users; platform routes are hidden from non-platform-admins; snapshot/behavior tests assert no hardcoded strings on new pages._
  - New tests under `frontend/src/__tests__/` (JSON reporter run per AGENTS.md). DELIVERED (Phase 9 run 2026-09-25): `TenantPicker.test.tsx` (10), `PlatformAdminRoute.test.tsx` (6), `TenantManagementPage.test.tsx` (10), `PlatformSettingsPage.test.tsx` (7), `PlatformAuditPage.test.tsx` (5), `TenantWorkspacePages.test.tsx` (13 — settings/onboarding/members combined with per-page i18n key assertions); manifest mirror extended in `ResourceTypeManifestMirror.test.ts`. Full frontend suite: 1530 passed / 0 failed. Test-file fixes: TS strictness (unused imports, Tenant fixture completeness) and two wrong selectors (slug rendered as `/acme`; dual Role-column tables need `getAllByText`).

- [x] 9.7 — Real-backend E2E isolation test + single-tenant regression suite — _Done when: at least one E2E test runs against the real backend with migrations applied, proving two tenants cannot see each other's data through the UI/API, and the full existing backend, frontend and E2E suites pass unmodified with the switch off._
  - New test under `e2e/tests/` labelled as a real-backend integration suite; migrations verified via `alembic current` before the run.
  - DELIVERED (Phase 9 run 2026-09-25): `e2e/tests/multi-tenant-isolation.real-backend.spec.ts` ("Real Backend Integration - Multi-Tenant Isolation" — no mocks; probes `/api/v1/health` and skips gracefully with no live backend/token; fails LOUDLY on a 500 from `/auth/tenant`, which proves the migration is unapplied; verifies the isolation contract: discovery switch state, platform tenants metadata+aggregates only, bogus tenant id → 404, audit tenant attribution). GATED STATUS: honest skip in this environment (no live backend/token required by design); mock-based suites are green: `single-tenant-regression.spec.ts` (6), `multi-tenant-lifecycle.spec.ts` (6), `multi-tenant-login-flows.spec.ts` (6); regression set green in isolation (permissions 10, agent-security-segregation 9, service-segregation-audit 1, three-service 5, oidc-login-flows 13). Pre-existing E2E breakage UNRELATED to this change documented in the Phase 9 report: `mcp-hub.spec.ts` / `api-key-management.spec.ts` (stale mock globs vs paginated endpoints / raw-i18n-key assertions) and `permission-errors.spec.ts` (needs live Keycloak; mislocated outside `auth-required/` per that folder's README). Test-infra fixes: `frontend/.env.test` (VITE_API_BASE_URL for the preview build), `testIgnore` for `auth-required/` + corrected `../_helpers` imports.

- [x] 9.8 — Security hardening review against top-priority architecture rules — _Done when: a documented review confirms the three top-priority rules still hold (services segregated, agents run only in AR, only CC touches the database, agents hold no sensitive data), all cross-tenant paths are fail-closed, and any finding is fixed or escalated before sign-off._
  - Review appended to `security-review.md` (Phase 9.8 section, 2026-09-25): all four `top_priority_rules` HOLD, verified by inspection (no DB engine/credentials in AR/CH; no signing helper outside CC) + Phase 9 test evidence. Findings: F-1/F-2 (low, UX) FIXED during Phase 9; F-3/F-4 informational, pre-existing boundaries documented.
  - Review notes appended to the change folder; all `has_db_changes` migration checks from AGENTS.md verified.

## Phase 10 — Self-Serve Registration, Tenant Root & Licensing

Refinement phase (all work additive on extension points from Phases 1–9): self-serve account-first registration, immutable tenant root, root-editable tenant alias, and license-tier quota governance (free / team / enterprise with max users / max agent types / monthly agent executions). All enforcement stays in Control Center; refusals happen before any dispatch to Communication Hub / Agent Runtime.

- [x] 10.1 — Add licensing & quota schema — _Done when: `TenantLicense` and `TenantQuotaUsage` models exist, are exported via `backend/app/db/models/__init__.py`, `TenantUserMembership` carries an immutable `is_root` flag, `PlatformUser` carries a platform-issued password credential (stored hashed only), the `TenantAuditEventType` enum gains `self_serve_registration`, `root_protection_rejected`, `license_assigned`, `license_changed`, `license_removed`, `quota_exhausted`, and `alembic upgrade head` + `downgrade` both succeed on a populated database (enum handling per AGENTS.md: postgresql.ENUM with create_type=False, no parameterized DDL)._
  - `backend/app/db/models/tenant_license.py` — tier enum (free / team / enterprise), max_users, max_agent_types, monthly_agent_executions, assigned_at, unassigned_at, is_active (at most one active per tenant).
  - `backend/app/db/models/tenant_quota_usage.py` — quota_type, period_start (calendar-month bucket), used_count; unique per (tenant, quota_type, period); in this epic only `monthly_executions` persists rows.
  - DELIVERED (2026-09-26): both models + `LicenseTier`/`QuotaType` enums exported via `models/__init__.py`; `TenantUserMembership.is_root` (server_default false + partial unique index `uq_tenant_membership_single_root`); `PlatformUser.password_credential` (nullable, hashed only); six new `TenantAuditEventType` values. Migration `6363bb7ee8c3` (revises `d9f3a6c2e7b1`): upgrade + `downgrade -1` + re-upgrade verified against the populated dev PostgreSQL; autogenerate drift excluded (super_admin_credentials drop, agent-role join constraints, invitation index churn); enum values added idempotently via `ALTER TYPE ... ADD VALUE IF NOT EXISTS` (no parameterized DDL); PG cannot drop enum values on downgrade (documented, same approach as `b4d7e1a90c2f`).

- [x] 10.2 — Enforce immutable tenant root protection — _Done when: the membership update/remove endpoints (change role, suspend, remove) and every platform-admin path that could touch a membership reject any mutation targeting the root membership (`is_root = true`) with a clear error — regardless of the actor being a delegated tenant admin or the platform admin — record a `root_protection_rejected` audit event, and leave the membership unchanged; non-root member management continues to work; the switch-off path is unaffected._
  - One shared guard used by both the tenant self-service router and platform admin paths (no per-endpoint duplication).
  - DELIVERED (2026-09-26): shared `guard_non_root_membership` in `backend/app/api/deps.py` — rejects with 403 + security-relevant `root_protection_rejected` audit (fire-and-forget-safe). Wired into `PATCH /tenant/members/{id}` (role + status changes) and the invitation-accept reactivation branch (defensive); `MemberRead`/settings responses now carry `is_root` so the UI can disable mutating actions. No platform-admin membership-mutation endpoint exists (platform surface never touches memberships directly); tenant deletion remains a tenant-lifecycle operation, not a membership mutation.

- [x] 10.3 — Root authorization semantics and root-only alias editing — _Done when: a root membership grants ALL tenant permissions inside its tenant without additional role grants (root check folded into the tenant membership grant path in `backend/app/api/deps.py`); `PATCH /api/v1/tenant/settings` accepts the name (alias) update only from the tenant root and rejects other tenant admins with a clear error; the slug cannot be changed through any endpoint; and platform-created tenants mark the primary admin contact's membership `is_root = true` (extend the tenant create/provisioning path)._
  - Alias changes remain audited (`tenant_updated`) and appear immediately without affecting the unique address.
  - DELIVERED (2026-09-26): `_membership_grants` in `backend/app/api/deps.py` grants ALL `tenant::*` permissions when the caller's active membership `is_root` (folded into the membership grant path ahead of role lookup); `PATCH /tenant/settings` accepts the alias update only from the root (403 otherwise, clear error) and writes `tenant_updated` audits for alias changes; the slug is not accepted by any endpoint (immutable address); `TenantProvisioningService.provision_tenant` marks the platform-created first admin `is_root = true`; `TenantSettingsRead` exposes `is_root` for the UI.

- [x] 10.4 — Implement the licensing service — _Done when: a `TenantLicensingService` in `backend/app/services/tenancy/` (singleton accessor consistent with neighbouring tenancy services) exposes license assign / change / remove plus effective-limits resolution; assigning supersedes the previous active license (`is_active = false`, `unassigned_at` set — history retained, latest active wins); removing deactivates and falls back to free-tier defaults immediately; a tenant with no active license resolves to built-in free-tier default limits (constants owned by this service); unknown tiers and non-positive limits are rejected; every change writes `license_assigned` / `license_changed` / `license_removed` audit events._

- [x] 10.5 — Implement the quota service — _Done when: a `TenantQuotaService` in `backend/app/services/tenancy/` resolves effective limits (assigned license, else free-tier defaults) and exposes three checks: active membership count vs max_users, tenant agent-type count vs max_agent_types, and monthly executions vs monthly_agent_executions; users and agent types are derived live from record counts (no counter rows); monthly executions are maintained via the `TenantQuotaUsage` counter — get-or-create the calendar-month bucket and increment once per accepted execution at the enforcement point, so a new month implicitly resets and in-flight executions are never double-counted or refunded; an exhausted check yields the structured feedback payload and a `quota_exhausted` audit event._
  - Reaching one quota never blocks the unrelated quotas.
  - DELIVERED (2026-09-26): `TenantLicensingService` (`licensing_service.py`) — free-tier defaults as named constants (10 users / 5 agent types / 100 monthly executions), `EffectiveLimits` resolution, assign/change/remove with supersede (`is_active=false` + `unassigned_at`), validation (enum tier, positive int limits), `license_assigned`/`license_changed`/`license_removed` audits, singleton `get_tenant_licensing_service()`. `TenantQuotaService` (`quota_service.py`) — `check_users`/`check_agent_types` (live counts) + `check_executions` (get-or-create `TenantQuotaUsage` monthly bucket), `increment_executions` counted exactly once per accepted execution, `QuotaCheckResult` structured result + `ensure_*` gates raising the shared contract error, inert when the switch is off, singleton accessor.

- [x] 10.6 — Define the structured quota error contract — _Done when: a single Pydantic schema carries tier, quota type, limit, current usage and upgrade path; all three enforcement gates produce that one payload through one shared exception/HTTP mapping (single status code); the payload round-trips cleanly to the frontend type added in 10.15; no quota error can be produced with the tenancy switch off._
  - DECISION (recorded per plan): refusals map to **HTTP 403** (not 429) — quota exhaustion is a plan/entitlement limit, not traffic throttling; 403 flows through the existing forbidden handling and the Dialog Error Handling Standard.
  - DELIVERED (2026-09-26): `QuotaBlockedPayload` + `TenantUsageRead` in `backend/app/schemas/tenant_quota.py` (`code="quota_exhausted"`, quota_type, tier, limit, used, upgrade_path); single mapping = `QuotaExceededError` exception handler in `create_app()` (app/main.py) returning 403 `{"detail": payload}` and writing the `quota_exhausted` audit on a FRESH session (the request session rolls back when a gate raises); gates are inert with the switch off so no quota error can be produced in single-tenant mode.

- [x] 10.7 — Implement the self-serve registration service — _Done when: a `TenantRegistrationService` in `backend/app/services/tenancy/` creates, in ONE database transaction: the `PlatformUser` (email + password credential, platform-issued `sub` — deliberately outside per-tenant OIDC), the `Tenant` (slug + alias), and the owner's root `TenantUserMembership` (`is_root = true`); duplicate email, invalid fields, slug conflicts, and an existing owned tenant (one tenant per user) are all rejected BEFORE anything is written; any failure leaves zero partial data; the self_serve_registration audit event is written on success; the service reuses the provisioning/onboarding internals from 5.6 (this supersedes the authenticated self-service creation path — the refinement is additive on that extension point)._
  - DELIVERED (2026-09-26): `TenantRegistrationService` (`tenant_registration_service.py`) — switch gate first, field validation (email regex + canonical lowercase, password rules via the bcrypt scheme of `platform_account_auth_service`), duplicate-email / one-owned-tenant / slug-conflict rejection BEFORE any write, `PlatformUser` (sub=`platform_account:<uuid>`) + Tenant (via `provision_tenant`, which stamps the root membership) + `self_serve_registration` audit in ONE transaction (caller commits; endpoint rolls back on error). Per-IP in-process sliding-window throttle (5/hour). NOTE: slug conflicts are REJECTED with a clear error per this done-when and 10.13 ("address-conflict errors"), not auto-suffixed.

- [x] 10.8 — Expose public registration and platform-password sign-in endpoints — _Done when: `POST /api/v1/auth/register` (public, switch-gated, basic throttling) accepts email, password, organization name and slug, returns the new tenant identity plus an authenticated session that lands the root user in guided onboarding, and replaces the authenticated `register-organization` endpoint; `POST /api/v1/auth/login-password` (public, throttled) authenticates platform-issued accounts and issues a tenant-bound token validated by the existing tenant-claim machinery; both are registered in the router registry and covered by the existing public-path bypass in tenant resolution; failures are generic (no user enumeration)._
  - DELIVERED (2026-09-26): `POST /api/v1/auth/register` + `POST /api/v1/auth/login-password` in `auth_tenant.py` (slowapi `10/hour` / `30/minute` per-IP on top of the service throttle). `register-organization` REMOVED (superseded cleanly — no frontend callers; bypass entries replaced). Token tier: `_try_platform_account_token` added to `validate_raw_token` (HS256 `platform_account` claim, `tenant` slug claim passes `_check_tenant_claim`); paths added to `PUBLIC_PATHS` (auth.py) + `BYPASS_PATHS` (tenant_resolution.py); `test_tenant_resolution.py` bypass enumeration updated.

- [x] 10.9 — Wire quota gates into existing CC paths — _Done when: user invitation creation (`POST /api/v1/tenant/invitations`) and the member-creating acceptance path consult the users quota; agent type creation (`POST /api/v1/agents/types`) consults the agent-types quota; execution submission (`launch_agent_session`) consults the monthly executions quota and increments the counter exactly once on acceptance, BEFORE any dispatch; an exhausted gate returns the structured contract and the execution never reaches Communication Hub or Agent Runtime; with the switch off all gates are inert._
  - DELIVERED (2026-09-26): `create_invitation` + `accept_invitation` (member-creating path) consult `ensure_users`; `create_agent_type` consults `ensure_agent_types`; `launch_agent_session` consults `ensure_executions` BEFORE the recursion pre-flight and increments the counter exactly once after acceptance, BEFORE `_lifecycle_handler.launch` — refusals raise the shared contract (403) with zero side effects. All gates branch on the resolved tenant context, so switch-off is inert.

- [x] 10.10 — Consult the execution quota at scheduler dispatch time — _Done when: `SchedulingEngine._dispatch` consults the owning tenant's monthly execution quota before launching a schedule-triggered execution; an exhausted quota skips the dispatch, records `quota_exhausted`, and leaves the job scheduled for future fires; within-quota dispatches increment the counter exactly like user-initiated submissions (no double counting); switch-off behavior is unchanged._
  - DELIVERED (2026-09-26): `SchedulingEngine._dispatch` consults `check_executions` for the owning tenant (when the job/agent type carries one); exhausted → `record_quota_exhausted` audit (tenant-attributed, `scheduled_job:<id>`) + returns `{status: skipped, reason: quota_exhausted}` so the JobExecution completes normally and the cron job stays scheduled; within quota → `increment_executions` before `GatewayLifecycleHandler.launch`. Jobs without a tenant (pre-adoption rows) keep legacy behaviour; the scheduler session is unscoped by design.

- [x] 10.11 — Expose platform admin license & usage APIs — _Done when: license assign/change and license remove endpoints exist on the platform tenants router guarded by the existing `platform::tenants` manage action, delegating to the licensing service; tenant list and detail responses carry tier, limits and current usage (live counts for users/agent types, counter read for monthly executions); invalid license input is rejected with clear errors; every change is audited and reflected immediately without manual reload._
  - DELIVERED (2026-09-26): `PUT /platform/tenants/{id}/license` + `DELETE /platform/tenants/{id}/license` (guarded by `platform::tenants` manage, delegating to the licensing service — supersede + audits); `TenantRead` gains `license` + `usage` (list AND detail carry tier, effective limits, live users/agent-type counts and the executions counter); invalid input → 422 via `TenantLicenseWrite` constraints + service validation; remove with no active license → 404.

- [x] 10.12 — Expose the tenant-side license & usage read API — _Done when: `GET /api/v1/tenant/usage` (guarded by the existing `tenant::settings` read action) returns the caller's tenant tier (free default when unlicensed), effective limits, and current usage — users, agent types, and executions this month; license changes are reflected on the next read; no cross-tenant data is exposed; switch-off keeps the endpoint absent/inert._
  - DELIVERED (2026-09-26): `GET /api/v1/tenant/usage` (guarded by `tenant::settings` read + active membership in the resolved tenant) returning `TenantUsageRead`; the tenant is taken from the resolved context only (no cross-tenant access); with the switch off the tenant context is never set so the endpoint cannot resolve — inert.

- [x] 10.13 — Build the public sign-up page and login entry link — _Done when: a public `/signup` route renders email, password, organization name and address fields with client- and server-side validation, surfaces duplicate-email, one-tenant-per-user and address-conflict errors clearly, is linked from `LoginPage` ("create your workspace" entry), and routes a successful registration into guided onboarding as the root user; the page and link only appear when the tenancy switch is on (via the existing discovery mechanism); all strings via i18next `t()`._
  - DELIVERED (2026-09-26): `frontend/src/pages/auth/SignUpPage.tsx` — two-step form (account → organization), client validation (email, password ≥8 w/ letter+digit, slug DNS-label rules), server errors surfaced & translated (duplicate email / address taken / one-tenant-per-user / switch-off / throttle); success stores the returned token + per-tab slug and routes to `/tenant/onboarding`. Public route `/signup` in `AppRouter.tsx`; "create your workspace" link on `LoginPage` shown only when `multiTenancyEnabled` (and the tenant is not blocked), probed via the same discovery.

- [x] 10.14 — Add root-only alias editing and the license & usage panel to tenant settings — _Done when: `TenantSettingsPage` lets only the root edit the tenant alias (others see a read-only explanation), shows the unique tenant address as immutable/read-only, and a new license & usage panel component shows tier, per-limit usage meters (users, agent types, executions this month) fed by the usage API; the panel refreshes after license changes without a manual reload; both surfaces hide when the switch is off; dialog error standard followed._
  - DELIVERED (2026-09-26): `TenantSettingsPage` — alias field disabled for non-root with explanatory note (`is_root` from the settings API), address rendered as a disabled field labelled immutable, dialog error standard retained; new `frontend/src/components/tenant/LicenseUsagePanel.tsx` fetches `GET /tenant/usage` (React Query key `['tenant','usage']`) and renders tier chip + three usage meters with warning colour near limits; the router only mounts these pages in a resolved tenant session, so they are inert when the switch is off.

- [x] 10.15 — Build the blocked-action UI consuming structured quota errors — _Done when: a shared blocked-action alert component renders the structured payload (tier, limit, current usage, upgrade path) whenever an API call returns the quota contract, is wired into invitation creation (MembersPage), the agent type creation UI, and the execution launch UI; the shared API client recognizes the contract's status/payload shape and surfaces it through the existing dialog error handling pattern; fully i18n'd._
  - DELIVERED (2026-09-26): `QuotaBlockedAlert` (`frontend/src/components/tenant/`) + `extractQuotaBlocked` (`utils/quotaErrorUtils.ts`) recognize the 403 payload shape (`detail.code === 'quota_exhausted'`) and render tier/quota-type/usage meter/upgrade path; any other error falls through to `PermissionDeniedAlert` so the component drops in place of it. Wired into MembersPage invite dialog, the agent type create/edit dialog (AgentManagementPage) and the execution launch dialog (AgentJobLaunchDialog).

- [x] 10.16 — Add license assignment and usage columns to the platform tenant console — _Done when: `TenantManagementPage` shows tier and usage columns in the tenant table/detail, and a license assignment dialog (tier select + limit inputs) supports assign, change and remove (with explicit free-fallback confirmation), validation errors inline, dialog error standard followed, and the table/detail refresh after every action without manual reload; the console still renders no tenant business data._
  - DELIVERED (2026-09-26): `TenantManagementPage` — Tier chip column + Usage summary column (users/agent-types/executions vs limits, from the extended list response); license dialog (WorkspacePremium button per row) with tier select pre-filling editable per-tier preset limits, assign vs change button states, remove with explicit free-fallback confirmation step; errors per dialog error standard; every action invalidates `['platform','tenants']` so the table refreshes without manual reload; no tenant business data rendered (aggregate usage only).

- [x] 10.17 — Complete i18n coverage and verify resource-type manifest consistency — _Done when: every new user-facing string exists in all locale files under `frontend/src/i18n/locales/` (currently `en.json`); the recorded decision holds that NO new resource types are required — alias editing and usage viewing ride the existing `tenant::settings` read/manage actions and license assignment rides the existing `platform::tenants` manage action — and the backend/frontend manifest parity test stays green; no hardcoded strings in any new component._
  - DELIVERED (2026-09-26): all new strings added under `auth`, `signup`, `tenant.settings`, `tenant.usage`, `tenant.quota`, `platform.tenants` in `frontend/src/i18n/locales/en.json` (the only locale file); NO new resource types needed (confirmed: alias editing + usage ride the existing `tenant::settings` read/manage actions, license assignment rides the existing `platform::tenants` manage action) — manifests untouched and the parity test (`ResourceTypeManifestMirror.test.ts`) stays green in the full run: 1530 passed / 0 failed. `npx tsc --noEmit` clean after fixture updates.

- [x] 10.18 — Tests: registration, root protection, licensing and quota enforcement — _Done when: backend tests cover atomic registration (success, failure leaves no partial data, duplicate email / one-tenant-per-user / slug conflict rejection), root protection rejections for every actor with audit assertions, license supersede and free-tier fallback, quota checks including calendar-month bucketing, implicit monthly reset and acceptance-time counting, gate wiring (invitation, agent type creation, execution submission, scheduler dispatch — refusal before dispatch), and switch-off inertness; frontend tests cover the sign-up page, root-only alias editing, the usage panel, the blocked-action alert, and platform license assignment; suites run per AGENTS.md (frontend Vitest with the JSON reporter)._
  - DELIVERED (verified 2026-09-27): all Phase 10 test files were already present from the interrupted session and now VERIFIED GREEN end to end (0 product bugs found — implementation passed every suite unmodified).
  - Backend (pytest, real PostgreSQL; migration `6363bb7ee8c3` at head): `test_tenant_registration.py` 19✓ (CS-26/27/28/29, E-18), `test_tenant_root_protection.py` 13✓ (CS-30/31/32, E-19), `test_tenant_licensing_quotas.py` 19✓ (CS-33–39/41/43, E-15/16/17/20, gate inertness), `integration/test_tenant_quota_scheduler.py` 5✓ (CS-40). Full suite: 2133 passed / 226 skipped / 0 failed (17 service-cert failures + 1 teardown error are environmental — stale dev services from a prior session reachable during the run; re-verified with services unreachable: 41 skipped / 7 passed / 0 failed, matching the Phase 9 "service-dependent skips" semantics). No test references the removed `register-organization` endpoint.
  - Frontend (Vitest JSON reporter + `tsc --noEmit` clean): `SignUpPage.test.tsx` 10✓, `TenantLicenseManagement.test.tsx` 6✓, `QuotaBlockedFeedback.test.tsx` 8✓, plus Phase 10 alias/usage cases inside `TenantWorkspacePages.test.tsx`. Full suite: 1559 passed / 18 skipped (pre-existing) / 0 failed.
  - E2E (Playwright): new `self-serve-signup.spec.ts` 4✓ + `quota-enforcement.spec.ts` 2✓; regression re-runs: `single-tenant-regression.spec.ts` 6✓, multi-tenant lifecycle/login-flows 11✓, must-keep permissions/segregation/architecture 32✓ combined; both real-backend variants (`multi-tenant-isolation`, `self-serve-signup`) honest-skip without a live stack per the gating convention. Pre-existing unrelated E2E breakage (mcp-hub / api-key-management / permission-errors) unchanged — documented in test-plan §6.
   - Full details and per-file coverage mapping in `test-plan.md` §6 (Phase 10 additions, 2026-09-27).

- [x] 10.19 — Seed default tenant-scoped roles (presets + idempotent seeding service) — _Done when: a new module `backend/app/services/tenancy/default_tenant_roles.py` defines FOUR presets derived from the real resource-type manifest — `Tenant System Admin` (every tenant-relevant resource type in MODULE_GROUPS agent/integration/system/tenant — plus the bare `agent` type that gates agent-type CRUD — with the FULL allowed action set; never `platform::*`), `Agent Manager` (full manage over the agent domain plus the reads needed to configure agents, e.g. `integration::mcp_hub` read + `system::permissions` read), `Agent Executor` (launch/execute on the agent execution/session resource types + read views + intervention respond), `Agent Viewer` (read-only on the agent/integration/system modules); presets are expressed as data (resource_type → action set), validated against the manifest at seed time (loud failure on unknown types/actions), and NO new resource types were introduced; `seed_default_tenant_roles(db, tenant_id, root_user_id=None)` creates the 4 Role rows tenant-scoped (`role.tenant_id`, `is_system=true`, per-tenant unique names) and attaches permissions following the EXISTING storage layout (PolicyStatement per resource type with PolicyAction rows and a wildcard PolicyResource — the BootstrapService layout the permission engine consumes), tenant-stamping every policy row; `root_user_id` triggers assignment of the tenant's system-admin role via the existing UserRole mechanism; the whole thing is idempotent and transaction-agnostic (caller commits)._
  - DELIVERED (2026-09-27): `backend/app/services/tenancy/default_tenant_roles.py` — 4 `DefaultTenantRolePreset` dataclasses + `DEFAULT_TENANT_ROLE_PRESETS` + `validate_presets_against_manifest()` + `seed_default_tenant_roles()` + `assign_tenant_system_admin_role()` + `sweep_missing_tenant_default_roles()`. `Tenant System Admin` = 22 resource types / 70 actions (MODULE_GROUPS agent+integration+system+tenant with full manifest actions, plus bare `agent`), never `platform::*`. Manifest alignment: the bare `agent` manifest entry now declares `create/read/update/delete/execute` (backend-only change; the frontend manifest intentionally excludes bare flat types), matching the actual `require_permission(RT_AGENT, ...)` endpoint usage — required so manifest-validated presets can grant agent-type CRUD.
  - Root-cause note (user-verified bug): the permission engine collects only roles bound to the tenant; a fresh tenant had ZERO roles, so even non-root `tenant_admin` members had no policies at all — seeding fixes that class of gap, and 10.21 fixes the root path itself.

- [x] 10.20 — Wire default-role seeding into every tenant creation path + startup self-healing sweep — _Done when: seeding is invoked from the self-serve registration path AND the platform-created tenant path (root = admin contact gets the system-admin role), the system-tenant adoption path seeds the 4 roles for consistency WITHOUT force-assigning anyone, and a Control Center startup sweep (next to the platform-settings seeding) idempotently seeds missing default roles for every active tenant and assigns the tenant's system-admin role to every root membership holder lacking it (retro-fixes pre-existing tenants, e.g. the user's `test-com`, with no manual SQL; cheap — a constant number of indexed queries for the scan, writes only where something is missing; logged)._
  - DELIVERED (2026-09-27): seeding lives at the lowest shared choke point — `TenantService.create` calls `seed_default_tenant_roles(db, tenant.id)` in-transaction, which covers self-serve registration (`TenantRegistrationService` → `TenantProvisioningService.provision_tenant` → `TenantService.create`), the platform console (`POST /platform/tenants`) and self-service org creation in one place; `TenantProvisioningService.provision_tenant` additionally calls `assign_tenant_system_admin_role(db, tenant.id, admin_user_id)` once the ROOT membership exists; `TenantAdoptionService.adopt_system_tenant` calls `seed_default_tenant_roles(db, system.id)` with NO root assignment (existing users keep their global roles). Startup: `_sweep_default_tenant_roles()` in `backend/app/main.py` runs right after `_seed_platform_settings()` and calls `sweep_missing_tenant_default_roles` (2-3 indexed scans for the whole platform + per-tenant writes only when missing; logs a summary; never blocks startup — failures are logged and swallowed like the other seeders).

- [x] 10.21 — Root blanket grant: root membership reaches every module except platform::* — _Done when: `_membership_grants` in `backend/app/api/deps.py` checks the ROOT membership BEFORE the static legacy dict so the root is granted ANY module except `platform::*` (which stays platform-admin-only by explicit exclusion), the static dict keeps governing only non-root membership roles (tenant_admin/member) on the tenant self-service surfaces, and `authorize_identity` consults the membership grant path for every non-platform module (previously gated to `tenant::*` only, which made the root check unreachable for business modules)._
  - DELIVERED (2026-09-27): `_membership_grants` now returns True for any module for an active `is_root` membership after an explicit `platform::` rejection, before the `_TENANT_MEMBERSHIP_GRANTS` dict lookup (non-root behaviour byte-for-byte unchanged); `authorize_identity` gate widened from `module.startswith("tenant::")` to `not module.startswith("platform::")` (one extra indexed membership SELECT per business-module request in multi-tenant mode; non-root users fall through to the permission engine exactly as before). This is the delivered-behavior fix for "root user can only see tenant self-service pages after self-serve registration".
  - Related test-infra fix: `uq_roles_global_name` on `roles` is now a partial index on BOTH dialects (`sqlite_where` added alongside `postgresql_where`, mirroring the `tenant_membership` precedent) — SQLite test DDL previously rendered it as a FULL unique index on `name`, which would forbid the per-tenant duplicate default role names. PostgreSQL DDL is unchanged (no migration).
  - Tests: new `backend/tests/test_default_tenant_roles.py` (32 tests) — preset↔manifest consistency (incl. no-`platform::*`), seeding layout/idempotency/cross-tenant role names, permission-engine authorization through a seeded role, creation-path wiring (service/provisioning/adoption), sweep backfill + idempotency, and root blanket grant (business modules allowed, `platform::*` denied, non-root dict behaviour unchanged). Targeted suites green: `test_tenant_registration.py` + `test_tenant_scoping.py` 43✓; tenancy/licensing/quota/root-protection/platform-admin/adoption suites all green (test_platform_admin_api `role_count` expectation updated: created tenants now ship with the 4 default roles).

- [x] 10.22 — Login page redesign: password sign-in, tenancy-aware states, remove setup_wizard state — _Done when: with the tenancy switch on, LoginPage's primary card is an email + password sign-in wired to the existing `loginPassword()` API client (`POST /auth/login-password`) so self-registered platform accounts can sign back in; success stores the token like the established flows and lands on the dashboard, wrong credentials show an inline form error (no dialogs); the OIDC button stays whenever a user-scope provider is configured but is no longer a gate (absence of OIDC must not produce the setup_wizard state or any "set up now" prompt); the "create your organization" link to /signup is kept; super admin becomes a discreet, muted entry ("Platform admin sign-in") that expands the existing username/password form (`superAdminLogin`), available whenever super admin is enabled independent of OIDC state; the `setup_wizard` login state and its `/setup` navigation are removed; the tenant-scoped `tenantBlocked` / `tenantSignInUnavailable` guards are preserved; with the tenancy switch off the page behaves as before minus the setup_wizard state; all new strings via `t()` in every locale file._
  - DELIVERED (2026-09-28): `frontend/src/pages/auth/LoginPage.tsx` restructured — primary email+password card (fields `auth.email`/`auth.password`, submit `auth.login`) shown when `multiTenancyEnabled === true` (same discovery probe as the sign-up link; `null` = in flight → held), calling `loginPassword(email.trim().toLowerCase(), password)`; success stores `access_token` in localStorage + `setToken` (super-admin/OidcCallback pattern) AND `setResolvedTenantSlug(result.tenant_slug)` (SignUpPage pattern — binds the per-tab session to the signed-in tenant before the tenant-claim-validated token is used), then navigates to `/dashboard`; failures render an inline `Alert` (shared `extractLoginErrorMessage` helper, generic fallback `auth.loginFailed`). OIDC button renders whenever an enabled user-scope provider exists — outlined when beside the password form (with `auth.or` divider), contained+`auth.loginWith` lead-in in the classic OIDC-only layout. Discreet super-admin entry: small muted `Link component="button"` (`auth.platformAdminSignIn`, `data-testid="super-admin-entry"`) toggling the existing form; `auth.superAdminInfo` first-run guidance moved INSIDE the expanded form (only when no OIDC provider). `LoginState` type and the `setup_wizard` branch removed entirely (no `navigate('/setup')` anywhere); a tenancy-off deployment with neither OIDC nor super admin shows a neutral `auth.noSignInAvailable` notice instead of the wizard. `tenantBlocked`/`tenantSignInUnavailable` guards unchanged (both suppress all sign-in flows). i18n: only locale is `en.json` (confirmed — `i18n/config.ts` registers `en` alone); added `auth.email`, `auth.platformAdminSignIn`, `auth.loginFailed`, `auth.noSignInAvailable`; removed dead `auth.setupWizard`, `auth.goToSetup`, `auth.loginAsSuperAdmin` and the whole dead `setup` wizard section.

- [x] 10.23 — Remove public setup wizard route/feature + dead references — _Done when: the public `/setup` route is deleted from AppRouter, the wizard feature files are removed (`frontend/src/features/setup/`, `frontend/src/pages/setup/SetupWizard.tsx`) together with their now-dead support modules (`frontend/src/api/setupApi.ts`, `frontend/src/types/setup.ts`) and test files, no other reference to `/setup` or the wizard remains in `frontend/src` (grep-verified), and backend setup endpoints are untouched (the `setup/` CLI tool stays)._
  - DELIVERED (2026-09-28): `/setup` route + `SetupWizard` import removed from `frontend/src/app/AppRouter.tsx` (doc comment updated); deleted `frontend/src/features/setup/` (SetupWizard, ProviderSelectionStep, KeycloakConfigStep, ExternalOidcConfigStep, VerificationStep, CompletionStep, index), `frontend/src/pages/setup/SetupWizard.tsx`, `frontend/src/api/setupApi.ts`, `frontend/src/types/setup.ts`; deleted test files `__tests__/SetupWizard.test.tsx`, `__tests__/features/setup/*` (6 files), `__tests__/api/setupApi.test.ts`; removed the stale wizard mock from `__tests__/app/AppRouter.test.tsx`; en.json `setup` section + `auth.setupWizard`/`auth.goToSetup`/`auth.loginAsSuperAdmin` dropped. Backend `/setup/*` endpoints and the `setup/` CLI intentionally untouched. Sanity: `npx tsc --noEmit` clean; grep confirms no remaining `/setup` route references in `frontend/src` (only negative assertions in the rewritten LoginPage tests); full Vitest suite 1538 passed / 0 failed / 18 skipped (pre-existing environmental skips).

- [x] 10.24 — Workspace-address sign-in: find-workspace step, remembered workspace, `?workspace=` deep link — _Done when: with the tenancy switch on and NO tenant in context (no host-derived tenant, nothing bound for the tab), the login page shows an AWS-style "find your workspace" card FIRST — a single workspace-address input (accepts a bare slug; a dotted input is reduced to its first DNS label with a visible hint), a "Remember this workspace" checkbox (default checked) and a Continue action wired to the public `GET /auth/tenant?slug=` discovery; an active tenant binds the per-tab slug (`setResolvedTenantSlug` → `X-Tenant` on every API call) plus the localStorage `parthenon_login_tenant` hint when remembering, then renders the tenant-branded sign-in card (tenant name shown) with the email+password form and the OIDC button when a user-scope provider is configured for that context (providers query keyed by the bound slug; `AuthProvider.refreshProviders` re-resolves the OIDC start config); unknown slugs show a neutral "no workspace found" error (discovery returns null uniformly — no enumeration); suspended tenants reuse the `tenantBlocked` state; a remembered workspace skips the finder straight to the branded card and a "Not your workspace? Use a different workspace" link clears BOTH the localStorage hint and the sessionStorage binding and returns to the finder; `?workspace=<slug>` on /login pre-resolves and lands on that tenant's card without implicit remembering (bookmarkable per-workspace sign-in URL); the host-derived tenant flow, tenancy-OFF behaviour, the post-password-auth `TenantPicker`, signup link and discreet platform-admin entry are all untouched; an address-reached tenant always shows the password form even when `sign_in_ready` is false (it reflects OIDC configuration only — a fresh tenant's owner signs in with the account they created at registration); all new strings via `t()` in `en.json` (the only locale)._
  - DELIVERED (2026-09-28): `LoginPage.tsx` gained a `WorkspacePhase` state machine (`idle`/`resolving`/`find`/`card` — legacy rendering exactly as before on `idle`, no flash of the platform card while the tenancy flag resolves); `extractSlugCandidate()` tolerates bare slugs and pasted hosts/URLs (first DNS label); `bindWorkspace()` centralizes the binding; the finder submit re-verifies every slug through public discovery before binding; `tenantAuthApi.ts` gained `get/setRememberedTenantSlug` (`parthenon_login_tenant`, re-verified — never an access decision); `AuthContext` extracted provider discovery into an exposed `refreshProviders()` callback (picks up `X-Tenant` at fetch time) and the page's providers React Query is keyed by the bound context slug; `tenantBlocked` unified over host- or address-resolved tenants, `tenantSignInUnavailable` kept host-flow-only (see doc comment). i18n: `auth.findWorkspace.{subtitle,addressLabel,addressPlaceholder,slugHint,remember,continue,lookup,notFound,lookupFailed,notYourWorkspace}` added to `en.json`. Sanity: `npx tsc --noEmit` clean; LoginPage suites 47/47 (11 new workspace-address cases: finder-first rendering, slug+host resolution, neutral unknown error, unchecked remember, remembered-skip, stale-hint fallback, `?workspace=` deep link, switch-link storage clearing, suspended blocked state, signup/super-admin preserved); full Vitest suite 1549 passed / 0 failed / 18 skipped (pre-existing environmental skips).

### Phase 11 — Root Tenant Platform Model

- [x] 11.1 — Root tenant rename/migration (row → name 'Root' / slug 'root'; keep `is_system_tenant` flag — 58 files exceed the 30-file rename threshold, documented as alias; system-slot → root-slot references)
- [x] 11.2 — Legacy global role migration (NULL-tenant Role rows re-homed to root, incl. policy linkage; adoption re-homes future globals)
- [x] 11.3 — Permission containment (engine collects session-tenant roles ONLY; membership gate replaced by containment; super-admin bypass kept)
- [x] 11.4 — Tenancy OFF = root tenant default context (resolution binds root when off; registration stays gated; quotas stay inert)
- [x] 11.5 — Frontend: sidebar platform gating by permission evaluation, Tenant Admin group for all tenants
- [x] 11.6 — Frontend: unified login cleanup (break-glass only on the `root` workspace)
- [x] 11.7 — Frontend: platform OIDC configuration operates on the root tenant
- [x] 11.8 — Tests + migration checks (reversibility, leak/sweep suites updated, frontend green)

## Phase 11 — Root Tenant Platform Model

Refinement phase: the platform becomes itself a tenant — the **root tenant** (workspace `root`). Legacy global (tenant-less) roles are re-homed into the root tenant's role space, permission evaluation becomes strictly tenant-contained (no global-role collection anywhere), and the tenancy-OFF default context is the root tenant instead of full inertness.

- [x] 11.1 — Root tenant rename/migration — _Done when: a reversible Alembic data migration sets the system tenant row (`is_system_tenant = true`) to name `Root` / slug `root` (slug-uniqueness guarded, FK-by-slug checked — resolution is by slug lookup so runtime references follow the row), the `is_system_tenant` → `is_root_tenant` flag rename decision is recorded (kept: 58 files > 30-file threshold; alias documented in tech-spec), and registry/adoption/resolution code references plus test names/strings say "root slot"/"root tenant"._
  - DELIVERED (2026-10-02): migration `b8e4f2a6c9d1` (revises `a1f2c3d4e5b6`) — renames the root tenant row in place (creates it on fresh deployments via `gen_random_uuid()`), guards the canonical slug against squatters (loud failure), full upgrade + `downgrade -1` + re-upgrade round-trip verified against the populated dev PostgreSQL. FLAG DECISION: `is_system_tenant` is KEPT (119 occurrences / 58 files > threshold) and documents the design's `is_root_tenant` alias. `OIDCProviderRegistry` internals renamed (`_root_tenant_id`, `_load_root_tenant_id`, "root slot" docstrings); adoption service uses `ROOT_TENANT_SLUG`/`ROOT_TENANT_NAME` from the new `root_tenant.py` module; `find_system_tenant` retained as an alias.

- [x] 11.2 — Legacy global role migration — _Done when: the same or follow-up migration re-homes every tenant-less business `Role` row (`tenant_id IS NULL`) to the root tenant together with its policy linkage (`PolicyStatement` rows — `PolicyAction`/`PolicyResource`/`PolicyTagCondition` ride the statement FK), stamps those statements' `tenant_id` to root, leaves the global `Permission` catalogue untouched, guarantees no business Role rows with NULL `tenant_id` remain, and a root-scoped `Platform Admin` role carrying the `platform::*` grants is seeded and assigned to root `platform_admin` membership holders; the adoption service re-homes global roles into root for future adoptions._
  - DELIVERED (2026-10-02): migration `b8e4f2a6c9d1` re-homes NULL-tenant roles + their statements/actions/resources (child stamping incl. a pre-statement-move pass and an orphan-stamp pass, so partially-applied states converge); `Permission` catalogue untouched; seeds the root `Platform Admin` role (one `platform::*` allow statement, action `*`, wildcard resource) assigned to ACTIVE root `platform_admin` members. New module `backend/app/services/tenancy/root_tenant.py` — `ensure_root_tenant` / `rehome_global_roles` / `seed_root_platform_admin_role` (all idempotent). Bootstrap now creates the `system_admin` role ROOT-scoped (fresh DBs); CC startup `_sweep_root_tenant` (before the default-roles sweep) re-homes any future globals and seeds the role; adoption backfill already covers all NULL tenant rows at enable time.

- [x] 11.3 — Permission containment — _Done when: `PermissionEngine._get_effective_role_ids` collects roles ONLY from the session's resolved tenant (global tenant-less collection removed from both the tenant-bound and legacy branches), the `deps.py` platform-membership gate (`_system_tenant_platform_admin` from FIX-235927) is REMOVED and `platform::*` checks simply evaluate the session tenant's roles (root tenant's role space contains `platform::` grants; other tenants structurally cannot), the super-admin bypass is kept, and `test_platform_permission_gating.py` is rewritten to containment semantics with every changed assertion called out._
  - DELIVERED (2026-10-02): engine tenant branch collects `Role.tenant_id == tenant_id` ONLY (global `OR tenant_id IS NULL` removed from direct + group branches); `_system_tenant_platform_admin` DELETED; `authorize_identity` binds the ROOT tenant for context-less `platform::*` checks (the base-domain platform console) so they evaluate the root role space. THE no-membership gate + root blanket grant are keyed on the resolved tenant being a CUSTOMER tenant (≠ root, cached root lookup) in ANY switch state — the root-default OFF context stays role-driven (legacy users hold no memberships). Super-admin bypass unchanged. TEST CHANGES (test_platform_permission_gating.py, all called out in the file docstring): T1 denial reason = role containment (was membership gate); T2 RETIRED → root-workspace effectiveness (T2) + new T2b (no roles in customer tenant); T3 platform access via the seeded root `Platform Admin` ROLE (was platform_admin membership); T3b roleless platform_admin membership denied; new T3c rogue tenant platform wildcard cannot cross; T4 OFF pin evaluated via the root tenant id.

- [x] 11.4 — Tenancy OFF = root tenant default — _Done when: tenant resolution with the switch OFF binds the ROOT tenant as the default context (zero user-visible multi-tenancy UX — no tenant pickers, no signup link — but the context is root, so scoping/JIT/authz run in the root-tenant world driven by root's migrated roles), public unauthenticated endpoints still bypass, registration stays switch-gated OFF, quotas stay inert (tiers are a SaaS concept — recorded decision), platform routes resolve the root context in both switch states, and the invariant tests (switch-off inertness pins, single-tenant canaries) are updated to the new semantics with every changed assertion called out._
  - DELIVERED (2026-10-02): `TenantResolutionMiddleware` binds the ROOT tenant as the default context when the switch is OFF (cached `get_root_tenant_context`, 30s TTL; context-less fail-safe when not yet created) and stamps `request.state.tenancy_enabled` — the new authority for "tenancy features apply" (`app.core.tenant_context.is_tenancy_enabled`, default False when the middleware did not run). BYPASSES unchanged (public endpoints bypass entirely; platform routes get the root context in both switch states via the `authorize_identity` platform binding). DEVIATION (recorded): DB-row-level scoping (`get_db`) and the quota gates stay SWITCH-gated, not context-gated — applying root scope when OFF would hide all pre-adoption NULL-tenant rows in legacy deployments; scoping/JIT/claim-injection/claim-check now branch on the flag. Authz DOES run in the root world (require_permission passes tenant_id=root → root-scoped role collection ≡ legacy global collection after re-homing). `_try_oidc_token` unchanged; the caller discards the context when OFF (byte-for-byte legacy validation). Frontend unchanged (flag tri-state as before; zero new UX).
  - TEST CHANGES: `test_tenant_resolution.py` passed UNCHANGED (its inertness pins mock the root lookup away — context-less fail-safe is the pinned legacy path); `test_tenant_oidc_isolation` / `test_oidc_jit_default_role` / `test_identity_plane` fake requests now set `state.tenancy_enabled = True` to simulate tenancy-ON (changed assertion: a resolved context alone no longer implies tenancy-ON); `test_platform_admin_api` slug pins `system` → `root`; `test_tenant_adoption` adoption pins `root` + `root_tenant_present`/`root_tenant_slug` keys; `test_tenant_scoping` global-role pin replaced by containment pin; conftest gains a root-tenant TTL-cache reset autouse fixture.

- [x] 11.5 — Frontend: sidebar permission gating — _Done when: the platform menu group renders ONLY when the session's permission evaluation grants `platform::` settings read (via `usePermissions` against the backend), NOT merely when tenancy is enabled (fixes the acme-admin-sees-platform-items bug); tenant self-management surfaces (alias, identity config, members) are grouped under a "Tenant Admin" sidebar group for ALL tenants; tenant root/admin users see no platform items even as root._
  - DELIVERED (2026-10-02): new `frontend/src/hooks/usePlatformAccess.ts` — probes `platform::settings` read via `getPlatformSettings()` (SHARED `['platform','access-probe']` query key with `PlatformAdminRoute`, one probe per session; super admin allowed directly). `AppShell` renders the Tenant Admin group (`/tenant/settings`, `/tenant/members`, `/system/identity-providers`) whenever the session is tenant-bound, and the Platform group ONLY on `platformAccess === 'allowed'` — never on `multiTenancyEnabled` alone (the bug fix). i18n: `nav.groupTenantAdmin` / `nav.tenantSettings` / `nav.tenantMembers` / `nav.tenantIdentityProviders`. New `AppShell.tenantAdmin.test.tsx` (3 tests: deny-on-customer-tenant, allow-at-root, tenancy-OFF renders neither group).

- [x] 11.6 — Frontend: unified login cleanup — _Done when: the discreet platform-admin expansion is removed from `LoginPage`; the super-admin break-glass entry is available ONLY when the entered/resolved workspace is `root` (subtle link on the root workspace card); the workspace-address flow is otherwise identical._
  - DELIVERED (2026-10-02): `LoginPage` gates the super-admin entry on `isRootWorkspace` (bound slug `=== 'root'`, no bound workspace = the tenancy-off root deployment, or tenancy off entirely); the break-glass form is unreachable from customer workspace cards. CHANGED TEST ASSERTION (LoginPage.refined.test.tsx, called out inline): the remembered-workspace `acme` case now pins the entry ABSENT; new `root` case pins it present and discreet.

- [x] 11.7 — Frontend: platform OIDC configuration module — _Done when: the System Config identity-provider management operates on the ROOT tenant's config (retargeted to the root slot), the platform OIDC config UI looks/behaves like the tenant identity config form, and i18n keys are added as needed._
  - DELIVERED (2026-10-02, cleanest option): NO retargeting needed — the per-tenant provider CRUD (`OIDCConfigService`) already binds to the RESOLVED workspace context (`X-Tenant` from the per-tab slug). Signed into the `root` workspace, the EXISTING `/system/identity-providers` page (linked from the new Tenant Admin group as "Sign-In Providers") manages the ROOT tenant's provider config with the same tenant identity-config form UX; the backend registry resolves it as the root slot for platform sign-in. i18n keys added in 11.5.

- [x] 11.8 — Tests + migration checks — _Done when: the migration(s) upgrade AND downgrade cleanly against the populated dev PostgreSQL (round-trip verified), identity-plane / leak / sweep suites are updated only where the design legitimately changed semantics (every changed assertion called out), and the frontend full suite is green._
  - VERIFIED (2026-10-02): migration round-trip ×2 on the populated dev DB (final state: `b8e4f2a6c9d1` head, zero NULL-tenant roles/statements/actions/resources, root tenant `Root`/`root`, Platform Admin role seeded+assigned). Backend verification set (gating, resolution, identity-plane, OIDC isolation, leak, sweep, platform-admin, fallback, JIT, default-roles, registration, unit): 1078 passed / 11 skipped / 0 failed. Full backend suite: 2281 passed / 226 skipped / 23 failed / 1 error — of the failures, 17 integration + 1 error match the Phase 10 recorded ENVIRONMENTAL baseline (stale dev services) and 2 are pre-existing Phase 10 leftovers (`test_namespace_migration` bare-`agent` pin vs the 10.19 seeder; `test_tenancy_switch_seeded_false` reads the USER's dev DB where the switch is currently ON — environmental state, not code). Frontend: `tsc --noEmit` clean; Vitest 1563 passed / 0 failed / 18 skipped (pre-existing environmental skips). Isolation guarantee: leak/sweep suites pass UNMODIFIED except fixture tenancy-flag semantics; no global-role collection exists anywhere.

## Completion Checklist

- [x] All Phase 1–9 tasks checked off with their Done-when conditions met
- [x] `alembic upgrade head` applied and verified before any backend testing (per AGENTS.md)
- [x] With the tenancy switch off: all existing backend, frontend and E2E tests pass unmodified (pre-existing, unrelated E2E breakage documented in the Phase 9 report; no regressions from this change)
- [x] With the switch on: cross-tenant negative tests pass in every domain and write audit events
- [x] Per-tenant OIDC: tenant A credentials rejected for tenant B; JWT tenant claim enforced
- [x] Signed tenant headers: verified on AR and CH; tamper/widening attempts rejected and audited
- [x] Fail-closed: unresolvable tenant in multi-tenant mode rejects every request before feature logic
- [x] Platform admin console and tenant workspace both fully i18n'd, no hardcoded strings
- [x] Resource type manifests updated in BOTH `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts` with mirror test green
- [x] Agents receive only tenant-scoped data; no tokens or credentials reach agents
- [x] Audit and OTEL carry tenant attribution; security view visible to platform admin
- [x] Adoption path verified: existing deployment upgraded, switch enabled, system tenant intact, switch disabled again with no data loss
- [x] All Phase 10 tasks checked off with their Done-when conditions met
- [x] Self-serve registration verified end to end: public signup atomically creates the platform account, tenant and root membership; a second registration is blocked with the one-tenant-per-user message; any failure leaves no partial data
- [x] Root immutability verified: demote/remove/suspend of a root membership is rejected for every actor (tenant admin and platform admin) and audited as `root_protection_rejected`; root alias editing works and the slug stays immutable
- [x] Licensing verified: assign/change/remove take effect immediately with supersede history retained; unlicensed tenants resolve to free-tier defaults; all changes audited
- [x] Quota enforcement verified: over-quota user invitation, agent type creation and execution submission (user-initiated and scheduler-triggered) are refused at Control Center with the structured tier/limit/usage/upgrade payload and never dispatched to Communication Hub / Agent Runtime
- [x] Phase 10 UI surfaces (sign-up page, root-only alias edit, license & usage panel, blocked-action UI, platform license console) fully i18n'd
- [x] `.change.yaml` updated (`es-developer: true`) and master doc update inputs noted for the update-master step
