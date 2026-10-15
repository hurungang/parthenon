# Test Plan Summary: Multi-Tenancy (multi-tenant-support)

> Master QA record for the completed change `multi-tenant-support`.
> Full detailed plan: `docs/changes/multi-tenant-support/test-plan.md` (coverage areas 2.1–2.14, scenarios CS-01..CS-47, edge cases E-01..E-20).

## 1. Test Strategy

Multi-tenancy is a platform-mode switch (default **OFF**) with hard security requirements. The strategy is layered so that:

1. **Default-off invariant** — single-tenant behavior is proven unchanged (all existing suites pass unmodified; responses identical).
2. **Real-database schema proof** — migrations verified against real PostgreSQL via `information_schema`, not ORM metadata; negative constraint tests included.
3. **Negative-first isolation** — every cross-tenant attack path must fail closed (404/403, never leaking data) **and** write a security-relevant `cross_tenant_access_denied` audit event.

| Layer | Location | Purpose |
|-------|----------|---------|
| Backend unit (pytest) | `backend/tests/` | Scope filters (`apply_tenant_scope`), PermissionEngine tenant binding, JWT tenant-claim validation, signed header sign/verify, fail-closed resolution, default-off settings cache |
| Backend integration (pytest + real PostgreSQL) | `backend/tests/integration/`, `backend/tests/db/`, `backend/tests/security/`, `backend/tests/agent_runtime/`, `backend/tests/communication_hub/` | Migration verification, adoption idempotency, cross-tenant API flows with audit assertions, AR/CH header verification; fixtures apply `alembic upgrade head` in setup |
| Frontend component (Vitest, JSON reporter per AGENTS.md) | `frontend/src/__tests__/` | Tenant picker, platform route gating, manifest mirror parity for `platform::*`/`tenant::*`, auth store active-tenant state, i18n coverage |
| E2E (Playwright) | `e2e/tests/` | Mocked suites for speed plus **real-backend gated variants** (`.real-backend.spec.ts` convention, no mocks, skip cleanly without live stack/token) |
| Manual / prototype review | change prototype + Phase 9.8 security hardening review against `top_priority_rules` | Three segregated services, agents only in AR, only CC touches DB, agents hold no secrets |

Test data conventions: timestamp-suffixed identifiable names, per-test cleanup via platform delete API or fixture teardown, exactly two tenants (A, B) plus the system tenant.

## 2. Coverage Areas (condensed)

| Area | Summary |
|------|---------|
| 2.1 Default-off regression | No tenant middleware/claims/headers when off; existing suites pass unmodified; stray tenant headers ignored |
| 2.2 Schema & migrations | 7 new tables; nullable indexed `tenant_id` on every direct-scoped entity (~40 tables); join/child tables carry none; reversible migration |
| 2.3 Tenant lifecycle | CRUD + suspend (blocks sign-in, kills sessions) + delete (true deletion, address reusable) + audit events |
| 2.4 Resolution & fail-closed | Single resolution point; unknown/suspended/deleted slugs rejected before feature logic; enumerated exemptions only |
| 2.5 Token/claim & per-tenant OIDC | JWT validated only via resolved tenant's JWKS; claim must match; per-tenant provider registry isolation |
| 2.6 Row-level scoping | Every scoped entity group: lists exclusive, foreign IDs 404, writes contained, audits written; scope at the `get_db` choke point |
| 2.7 Signed header propagation | CC signs, AR/CH verify-only (cannot sign); tamper/replay/unsigned rejected; CH/AR surfaces tenant-bound |
| 2.8 RBAC tenant binding & new resource types | Roles resolve within tenant only; `platform::*`/`tenant::*` registered in both manifests (mirror test mandatory-green) |
| 2.9 Platform admin restrictions | Metadata + aggregates only, never business data; platform audit platform-admin-only |
| 2.10 Frontend tenant UX | Platform console guards; tenant workspace session semantics (one session = one tenant, never persisted) |
| 2.11 Audit & observability | TenantAuditEvents for lifecycle + denials; OTEL tenant attribute when on, absent when off |
| 2.12 Registration, root & licensing/quotas | Atomic registration → root; one-tenant-per-user; root immutability; license lifecycle; 3 quota types with structured feedback |
| 2.13 Systematic entity-isolation sweep | Every model classified; 47 tenant-scoped models probed; `TENANT_AGNOSTIC_REGISTRY` future-leak guard |
| 2.14 Root-tenant platform model | All grants (incl. `*::*`) evaluated within session tenant; `platform::` only in root tenant space; tenancy-off = root-tenant single-tenant behavior |

## 3. Critical Scenario Groups (CS-01..CS-47)

- **Default-off invariant / root-default** (CS-01–CS-03, 2.14 tenancy-off) — switch-off byte-for-byte unchanged behavior; stray headers inert; enable→disable→enable idempotent with no data loss; root-tenant model contains all grants per-tenant.
- **Isolation sweep + registry guard** (CS-44–CS-47, 2.13) — row-level cross-tenant probes across ALL 47 tenant-scoped models (`select` own-row only, `get` → None); every non-scoped model must be in `TENANT_AGNOSTIC_REGISTRY` with a documented strategy — a newly added unclassified model fails the suite (future-leak guard); per-request scope-criteria rebinding (A→B→A) with no stale-criteria replay; platform-user membership-join strategy (CS-44).
- **Claim validation & provider fallback** (CS-14–CS-16) — tenant A tokens rejected at tenant B everywhere; missing/mismatched claims rejected pre-sync; per-tenant OIDC isolation. Related OIDC hardening verified in `backend/tests/test_oidc_provider_fallback.py` (provider fallback chain) and `backend/tests/test_oidc_jit_default_role.py` (JIT default role assignment), plus `backend/tests/test_platform_permission_gating.py` (platform permission containment, 2.14).
- **Signed-header & agent/MCP isolation** (CS-17–CS-20) — AR/CH verify-only signatures; A2A and MCP/API-key paths tenant-bound; no widening path exists.
- **JIT default role & RBAC containment** (CS-21) — roles/wildcards resolve strictly within the request tenant; identical role names across tenants do not collide.
- **Registration / root / licensing / quotas** (CS-26–CS-43) — atomic registration, root protection against every actor (incl. platform admin, audited `root_protection_rejected`), immutable slug / root-only alias; license assign/change/remove with supersede history and immediate free fallback; three quota types enforced with structured tier/limit/usage/upgrade feedback; per-calendar-month execution counter, no double-counting, scheduler dispatch counted at dispatch time (CS-40); quota-bypass attempts rejected (CS-42).
- **Probe bypass / fail-closed** (CS-10–CS-11) — unresolvable tenants rejected before any feature logic; exemption set exact; resolution happens exactly once, conflicts rejected.
- **CRUD slots** (CS-07–CS-09, CS-22–CS-23) — tenant overview CRUD with immediate refresh, duplicate rejection, suspend/resume, delete-and-recreate (true deletion), aggregates-only platform admin surface.

## 4. Test File References (all paths verified present)

### Backend unit (`backend/tests/`)
- `backend/tests/test_tenant_scoping.py` — `apply_tenant_scope` isolation, join-table inheritance, PermissionEngine tenant binding (CS-21), tenant lifecycle service
- `backend/tests/test_tenant_resolution.py` — fail-closed resolution, middleware inertness, bypass enumeration (CS-10)
- `backend/tests/test_tenant_context.py`, `backend/tests/test_tenant_signature.py`, `backend/tests/test_platform_settings_service.py` — context immutability, sign/verify, default-off seeding
- `backend/tests/test_tenant_oidc_isolation.py` — per-tenant registry, claim matrix (CS-14/15/16)
- `backend/tests/test_oidc_provider_fallback.py` — OIDC provider fallback chain
- `backend/tests/test_oidc_jit_default_role.py` — JIT default role assignment
- `backend/tests/test_platform_permission_gating.py` — platform permission containment / root-tenant gating (2.14)
- `backend/tests/test_tenant_registration.py`, `backend/tests/test_tenant_root_protection.py`, `backend/tests/test_tenant_licensing_quotas.py` — CS-26–CS-43
- `backend/tests/test_tenant_user_leak.py` — platform-users membership-filter leak regression (CS-44)
- `backend/tests/test_tenant_isolation_sweep.py` — 52 tests: registry-completeness guard + parametrized probes over all tenant-scoped models (CS-44–CS-46)
- `backend/tests/test_tenant_memberships_invitations.py`, `backend/tests/test_platform_admin_api.py` — invitations, platform CRUD/permission guards

### Backend integration / security
- `backend/tests/db/test_tenant_schema_migration.py` — `information_schema` verification vs real PostgreSQL (downgrade cycle gated behind `PARTHENON_TEST_MIGRATION_CYCLE=1`)
- `backend/tests/integration/test_tenant_adoption.py` — adoption/backfill/idempotency (CS-05/CS-06)
- `backend/tests/integration/test_tenant_quota_scheduler.py` — scheduler dispatch quota consultation (CS-40)
- `backend/tests/security/test_cross_tenant_isolation.py` — per-domain negatives + audit assertions (CS-12/CS-13)
- `backend/tests/agent_runtime/test_tenant_header_verification.py`, `backend/tests/communication_hub/test_tenant_header_verification.py` — AR/CH signed-header verification (CS-17–CS-20)

### Frontend (`frontend/src/__tests__/`)
- `TenantPicker.test.tsx`, `PlatformAdminRoute.test.tsx`, `TenantManagementPage.test.tsx`, `PlatformSettingsPage.test.tsx`, `PlatformAuditPage.test.tsx`
- `TenantWorkspacePages.test.tsx` (settings + onboarding + members, incl. root-only alias edit and license/usage panel)
- `SignUpPage.test.tsx`, `TenantLicenseManagement.test.tsx`, `QuotaBlockedFeedback.test.tsx`
- `ResourceTypeManifestMirror.test.ts` — `platform::*`/`tenant::*` mirror parity (E-14, mandatory green)

### E2E (`e2e/tests/`)
- `single-tenant-regression.spec.ts` — switch-off canary (CS-01/CS-02, CS-29 UI)
- `multi-tenant-lifecycle.spec.ts` — CRUD lifecycle incl. alias-edit/slug-immutability (CS-07/CS-09/CS-32)
- `multi-tenant-login-flows.spec.ts` — suspended/deleted tenant sign-in, org picker, session semantics (CS-24)
- `self-serve-signup.spec.ts`, `quota-enforcement.spec.ts` — registration journey, quota feedback (CS-26–CS-28, CS-34/CS-35/CS-41)
- `multi-tenant-isolation.real-backend.spec.ts`, `self-serve-signup.real-backend.spec.ts` — **gated real-backend variants** (`Real Backend Integration - ...`, no mocks, honest skip without live stack + `E2E_REAL_BACKEND_TOKEN`)

### Verified totals (Phase 10 run, 2026-09-27)
- Backend: 2133 passed / 226 skipped / 0 failed (clean-environment re-run semantics documented in the change test plan)
- Frontend: 1559 passed / 18 skipped (pre-existing) / 0 failed; `tsc --noEmit` clean
- E2E: all mocked suites green; real-backend variants honest-skip without live stack

## 5. Execution Order (per AGENTS.md)

1. `alembic current` → `alembic upgrade head` if pending → restart backend (`parthenon.ps1 restart -Services backend`)
2. Backend unit + integration (real DB) suites
3. Frontend Vitest with JSON reporter (`npx vitest run --reporter=json --outputFile=vitest_results.json`)
4. E2E: `single-tenant-regression.spec.ts` first (canary), then mocked tenant suites, then real-backend variants last
5. Manual Phase 9.8 security hardening review against `top_priority_rules` before sign-off

---

## 6. strict-tenant-isolation Update (2026-10)

Change `strict-tenant-isolation` retired the NULL-tenant shared slot and made tenant containment strict across the data plane. Covered areas: NULL→root adoption migration with NOT NULL enforcement; fail-closed signed `X-Internal-Tenant-*` headers on all internal data-plane routers; system tools (query_result/save_data/get_data/get_output) and notification dispatch strictly tenant-stamped and tenant-filtered; per-tenant MCP slug scoping.

Test files added (all verified present, all paths relative to repo root):

- `backend/tests/integration/_strict_tenant_utils.py` — shared parthenon_test schema/fixture helpers (two-tenant builder, agent type/job builders, NULL-row counters)
- `backend/tests/integration/test_multitenant_auth_chain.py` — per-tenant OIDC provider isolation, tenant-claim binding, signed-header acceptance/fail-closed 401/stale/tampered/mismatched rejections, tenancy-off root binding
- `backend/tests/integration/test_internal_tenant_header_failclosed.py` — 401 on missing/invalid/stale/tampered/partial/mismatched signed headers on every internal data-plane router; root binding when multi-tenancy off; structural enforcement check
- `backend/tests/integration/test_system_tools_tenant_containment.py` — cross-tenant negatives with identical names for query_result/save_data/get_data/get_output/outputs; DB-level tenant stamping; service-level defense in depth
- `backend/tests/integration/test_notification_tenant_dispatch.py` — per-tenant group resolution/dispatch, shared-slot retirement, fail-closed group miss
- `backend/tests/db/test_tenant_adoption_migration.py` — runs the real Alembic chain from scratch on parthenon_test; `information_schema` NOT NULL verification, retired NULL-variant index checks, DB-level negative inserts, upgrade-twice idempotency, downgrade→replay

E2E: N/A — backend-only change, no UI changes; the real-migration-chain integration suite provides the real-backend coverage.
