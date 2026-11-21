# Multi-Tenancy — Licensing, Registration and Quotas

> Part of the [multi-tenancy hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

This page covers how tenants are created, admitted, licensed and limited: account-first self-serve registration, platform-issued password accounts, license tiers with supersede semantics, three-point quota enforcement with a structured refusal contract, immutable root membership, the platform admin/tenant self-service APIs, the default tenant-role presets, and the corresponding frontend surfaces.

**Registration.** Self-serve signup is public and account-first: `POST /api/v1/auth/register` atomically creates the `PlatformUser` (bcrypt password, platform-issued `sub`, outside the per-tenant OIDC registry), the tenant, and the owner's root membership — switch-gated and throttled, with duplicate-email, one-owned-tenant-per-user and slug validation before any write. Platform accounts sign back in via `POST /api/v1/auth/login-password`. This replaces the removed authenticated `register-organization` endpoint.

**Licensing.** `TenantLicense` (free / team / enterprise with `max_users`, `max_agent_types`, `monthly_agent_executions`) uses supersede semantics (latest active wins, history retained). An unlicensed tenant falls back to the built-in free-tier defaults (10 users / 5 agent types / 100 monthly executions).

**Quotas.** Enforced at exactly three CC decision points — user invitation/creation, agent-type creation, execution submission (the scheduler re-consults at dispatch time). Refusal always happens at CC before any dispatch, returning the structured `QuotaBlockedPayload` (HTTP 403). `monthly_executions` uses a maintained calendar-month bucket counter (never refunded); users and agent types are derived live.

**Root protection.** The root membership (`is_root`, exactly one per tenant, partial unique index) is immutable: every mutation against it is rejected by `guard_non_root_membership` and audited as `root_protection_rejected`. Only the root may edit the tenant alias; the slug (address) is immutable.

---

## Key Components

| Component | Description |
|-----------|-------------|
| `TenantRegistrationService` | Atomic account-first registration (PlatformUser + Tenant + root membership); one-owned-tenant rule; zero partial data on failure |
| Platform account auth | bcrypt hash/verify, email/password validation, platform-issued `sub`, HS256 tenant-bound JWTs |
| `TenantLicensingService` | License assign/change/remove with supersede semantics; free-tier defaults; effective-limit resolution |
| `TenantQuotaService` | Three quota checks plus the calendar-month execution counter; inert when the switch is off |
| `QuotaExceededError` / `QuotaBlockedPayload` | Shared refusal and its single HTTP 403 mapping |
| `guard_non_root_membership` | Shared root-membership mutation guard (tenant + platform paths) |
| Default tenant roles | Four presets seeded per tenant, validated against the resource manifest, backfilled by a startup sweep, assigned to the tenant root |
| Platform admin APIs | Tenant metadata/lifecycle, platform settings, cross-tenant audit, license endpoints — never tenant business data |
| Tenant self-service APIs | Settings, onboarding, members, invitations, usage |
| Audit | Registration, root protection, license changes, quota exhaustion |

---

## API Endpoints

### Public auth

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/auth/register` | Account-first registration (switch-gated, throttled) |
| `POST` | `/api/v1/auth/login-password` | Sign-in for platform-issued accounts (tenant-bound token) |

### Platform admin (`platform::*`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET`/`POST`/`PATCH`/`DELETE` | `/api/v1/platform/tenants[/{id}]` | Tenant metadata and lifecycle (create, suspend, resume, delete) |
| `POST` | `/api/v1/platform/tenants/{id}/license` / `DELETE …/license` | Assign/change or remove a license |
| `GET`/`PUT` | `/api/v1/platform/settings` | Platform settings incl. the tenancy switch |
| `GET` | `/api/v1/platform/audit` | Cross-tenant security audit |

### Tenant self-service (`tenant::*`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET`/`PATCH` | `/api/v1/tenant/settings` | Tenant settings (incl. the resume TTL — see [tenant-settings.md](tenant-settings.md)) |
| `GET` | `/api/v1/tenant/usage` | Tier, effective limits, current usage |
| `GET`/`POST` | `/api/v1/tenant/members` / `/invitations` | Members and invitations (quota-checked) |
| `POST` | `/api/v1/tenant/onboarding` | Guided onboarding |
| `POST` | `/api/v1/auth/tenant/invitations/{token}/accept` | Public invitation acceptance |

### Quota-enforced decision points

| Action | Enforcement |
|--------|-------------|
| Invitation creation | Users quota (structured block on exhaustion) |
| Agent type creation | Agent-types quota |
| Execution submission | Monthly-executions quota; counter incremented once on acceptance, before dispatch |
| Scheduled execution | Re-consulted at dispatch; skipped + audited on exhaustion (job stays scheduled) |

---

## Data Access Patterns

- Every quota decision and every license write happens in Control Center within the tenant-scoped session; CH/AR never evaluate quotas.
- The quota counter is upserted per `(tenant, quota_type, calendar-month bucket)`; only `monthly_executions` persists rows.
- Registration is one transaction: any failure leaves no partial PlatformUser/tenant/membership.
- License history is append-only (`is_active`, `assigned_at`, `unassigned_at`) with an at-most-one-active partial unique index.

---

## Code Reference Map

### Models and services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TenantLicense` / `LicenseTier` | model / enum | Tier + limits; latest-active-wins history | `backend/app/db/models/tenant_license.py` |
| `TenantQuotaUsage` | model | Per-tenant quota counter (unique per tenant/type/month bucket) | `backend/app/db/models/tenant_quota_usage.py` |
| `TenantUserMembership.is_root` | field | Immutable root membership (partial unique index) | `backend/app/db/models/tenant_membership.py` |
| `TenantInvitation` | model | Single-use invitation with role, expiry and SHA-256 token hash | `backend/app/db/models/tenant_invitation.py` |
| `TenantAuditEventType` additions (`self_serve_registration`, `root_protection_rejected`, `license_assigned`, `license_changed`, `license_removed`, `quota_exhausted`) | enum values | Registration/root/license/quota audit events | `backend/app/db/models/tenant_audit_event.py` |
| `TenantRegistrationService` | class | Atomic account-first registration; one-owned-tenant rule | `backend/app/services/tenancy/tenant_registration_service.py` |
| `platform_account_auth_service` | module | bcrypt credentials, platform-issued `sub`, tenant-bound platform JWTs | `backend/app/services/tenancy/platform_account_auth_service.py` |
| `TenantLicensingService` | class | License lifecycle, free-tier defaults, effective limits | `backend/app/services/tenancy/licensing_service.py` |
| `TenantQuotaService` / `QuotaExceededError` / `increment_executions` | class / exception / method | Quota checks, refusal and counter maintenance | `backend/app/services/tenancy/quota_service.py` |
| `guard_non_root_membership` | function | Rejects root-membership mutation; audits the rejection | `backend/app/api/deps.py` |
| `_membership_grants` / `authorize_identity` (root blanket) | functions | Root membership grants all tenant permissions except `platform::*` | `backend/app/api/deps.py` |
| `validate_presets_against_manifest` / `seed_default_tenant_roles` / `assign_tenant_system_admin_role` / `sweep_missing_tenant_default_roles` | functions | Preset validation, seeding, assignment and backfill | `backend/app/services/tenancy/default_tenant_roles.py` |
| `TenantService.create` / `TenantProvisioningService.provision_tenant` / `TenantAdoptionService.adopt_system_tenant` | methods | Seed presets in-transaction; mark/stamp the root membership | `backend/app/services/tenancy/tenant_service.py`, `tenant_provisioning_service.py`, `tenant_adoption_service.py` |
| `_sweep_default_tenant_roles` | function | Startup self-healing sweep | `backend/app/main.py` |

### Schemas and endpoints

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `QuotaBlockedPayload` / `TenantUsageRead` | schemas | Structured quota refusal and usage contract | `backend/app/schemas/tenant_quota.py` |
| `register_account` / `login_password` | endpoints | Public registration and platform-account sign-in | `backend/app/api/v1/auth_tenant.py` |
| `assign_tenant_license` / `remove_tenant_license` | endpoints | Platform license assign/change and remove | `backend/app/api/v1/platform/tenants.py` |
| `get_tenant_usage` / `create_invitation` | endpoints | Usage read and quota-checked invitation creation | `backend/app/api/v1/tenant.py` |
| `create_agent_type` (quota) / `launch_agent_session` (quota) | endpoints | Agent-type and execution quota gates | `backend/app/api/v1/agents.py` |
| `SchedulingEngine._dispatch` | method | Dispatch-time quota consultation | `backend/app/services/scheduling/scheduler.py` |
| platform tenants / settings / audit routers | routers | Platform admin surface | `backend/app/api/v1/platform/tenants.py`, `settings.py`, `audit.py` |
| tenant self-service router | router | Tenant settings/onboarding/members/invitations/usage | `backend/app/api/v1/tenant.py` |
| tenant auth router | router | Tenant discovery, memberships, registration | `backend/app/api/v1/auth_tenant.py` |
| `RT_AGENT` manifest entry | constant | Bare `agent` actions widened to `create/read/update/delete/execute` so presets validate | `backend/app/core/resource_types.py` |

### Frontend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PlatformAdminRoute` / `PlatformRoutes` / `usePlatformAccess` | guard / routes / hook | Platform console gated by real permission probe | `frontend/src/app/PlatformAdminRoute.tsx`, `PlatformRoutes.tsx`, `frontend/src/hooks/usePlatformAccess.ts` |
| `TenantManagementPage` | component | Tenant CRUD/lifecycle + license dialog, tier/usage columns | `frontend/src/pages/platform/TenantManagementPage.tsx` |
| `PlatformSettingsPage` / `PlatformAuditPage` | components | Tenancy switch/settings and cross-tenant audit | `frontend/src/pages/platform/PlatformSettingsPage.tsx`, `PlatformAuditPage.tsx` |
| `TenantSettingsPage` / `OnboardingPage` / `MembersPage` / `InvitationAcceptPage` | components | Tenant workspace surfaces | `frontend/src/pages/tenant/` |
| `LicenseUsagePanel` | component | Tier, limits and usage meters | `frontend/src/components/tenant/LicenseUsagePanel.tsx` |
| `QuotaBlockedAlert` / `extractQuotaBlocked` | component / function | Structured quota block rendering | `frontend/src/components/tenant/QuotaBlockedAlert.tsx`, `frontend/src/utils/quotaErrorUtils.ts` |
| `SignUpPage` | component | Public account-first sign-up | `frontend/src/pages/auth/SignUpPage.tsx` |
| `platformAdminApi` / `tenantApi` / `tenantAuthApi` | modules | License, usage, registration/login clients | `frontend/src/api/platformAdminApi.ts`, `tenantApi.ts`, `tenantAuthApi.ts` |
| tenant TypeScript types | module | `LicenseRead`, `LicenseTier`, `TenantUsageRead`, `QuotaBlockedPayload` | `frontend/src/types/index.ts` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_default_tenant_roles` | test | Preset↔manifest consistency, seeding, engine authorisation, sweep, root grant | `backend/tests/test_default_tenant_roles.py` |
| `test_platform_permission_gating` | test | Root role / containment / platform wildcard crossing | `backend/tests/test_platform_permission_gating.py` |
| `test_setup_tenant_demo` | test | Opt-in demo realm seeding idempotency | `backend/tests/unit/test_setup_tenant_demo.py` |
| `TenantWorkspacePages` / `LicenseUsagePanel` / `QuotaBlockedAlert` suites | frontend tests | Workspace pages, license meters, quota rendering | `frontend/src/__tests__/` |
| multi-tenant E2E specs | E2E tests | Platform console, tenant workspace, sign-up/invite flows | `e2e/tests/` |
