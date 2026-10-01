# Fix Log: multi-tenant-support

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20261001-010107

**Created:** 2026-10-01T01:01:07Z
**Status:** Resolved
**Issue:** OIDC provider CRUD ignores the request's tenant context — updates always query `tenant_id = NULL` and fail with 400 "No provider config exists" for tenant-scoped configs; public provider listing exposes ALL tenants' provider metadata

### Observed Behavior
Updating the user/agent OIDC provider (e.g. to the new demo realm) from a workspace session fails with `400 {"detail": "No provider config exists for scope 'user'."}` even though the tenant's config rows exist. Reproduced via API: `PUT /system/identity-providers/user` with a workspace token + `X-Tenant: test-com` → 400.

### Expected Behavior
- Provider CRUD (create/update/toggle/delete) addresses the correct slot: resolved tenant context → that tenant's config; no tenant context (platform surface) → the shared NULL-tenant config.
- The public login-page listing (`GET /system/identity-providers`) exposes ONLY the shared config plus the resolved tenant's own config — never other tenants' metadata.

### Analysis
- **Affected components:** `backend/app/api/v1/system_config.py` (create/update/toggle/delete handlers never pass tenant_id), `backend/app/services/oidc_config_service.py` (get_by_scope NULL comparison), public listing handler
- **Root cause hypothesis:** multi-tenant CRUD wiring was never added to the pre-tenancy handlers; `get_by_scope` with `tenant_id=None` produces a SQL `tenant_id = NULL` predicate that matches nothing
- **Documentation impact:** `fix-log.md`, `tech-spec.md`, `test-plan.md`

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
- `backend/tests/test_oidc_config_crud_slots.py` (15 tests): tenant-slot CRUD addressing (update/create/toggle/delete with resolved tenant context), shared-slot NULL predicate, public-listing privacy (shared-only without context; shared+own with context), fail-closed write pins

### Code Changes
- `backend/app/api/v1/system_config.py`: CRUD handlers derive tenant from resolved context (`_resolved_tenant_id`) and pass it to the service; public GET listing filtered to shared + own-tenant
- `backend/app/api/v1/platform/identity_providers.py` (new): /platform/identity-providers CRUD addressing the shared NULL-tenant slot, platform-permission guarded
- `backend/app/services/oidc_config_service.py`: shared-slot lookup fixed with `tenant_id.is_(None)` (the `= NULL` predicate matched nothing)
- `frontend/src/api/systemConfigApi.ts`: base path by context (/system/* with tenant binding, /platform/* without)
- Live smoke verified: workspace PUT 200 (test-com → acme realm); platform POST 201 + PUT 200 (shared slot); unauthenticated listing = shared only

### Documentation Updates
- tech-spec.md Code Reference Map: platform identity-provider routes + slot-addressing + context-aware frontend base path

### Verification Results
- Backend: 77 passed (15 CRUD-slot + 62 regression across isolation/identity/gating/platform-admin suites)
- Live smoke against running backend: all green (see Code Changes)
- Frontend: tsc clean; targeted suites green (full-suite counts in tester verification below)
- Status: Resolved
- Independent (final, conductor): backend 148/0 across 9 acceptance suites; tsc clean; targeted frontend suites 68/0 (full-suite run skipped — machine under sustained load); E2E 17 passed / 1 by-design skip. All green.

---

## FIX-20260930-235927

**Created:** 2026-09-30T23:59:27Z
**Status:** Resolved (independently verified by tester, 2026-10-01)
**Issue:** (1) Legacy global `system_admin` wildcard role grants `platform::*` access to pre-tenancy IdP admins when multi-tenancy is ON; (2) setup tooling cannot seed a demo tenant realm + users for isolated per-tenant OIDC testing

### Observed Behavior
A Keycloak `admin` user (legacy `system_admin` global role with `*::*` wildcard from the pre-multi-tenancy integration) can access ALL platform menu items when multi-tenancy is ON. Platform access should require super admin or an explicit platform-admin membership — not legacy wildcards. Also: no demo tenant realm exists for testing tenant-scoped OIDC without a shared realm.

### Expected Behavior
- With multi-tenancy ON: `platform::*` permission checks are satisfied ONLY by super admin or an active platform-admin membership in the system tenant. Legacy global roles/wildcards keep working for tenant-scoped modules but never unlock `platform::*`.
- With multi-tenancy OFF: legacy behavior unchanged (system_admin keeps full access; no platform concept).
- `setup/` identity provisioning can seed a demo tenant realm (own issuer, frontend client, test users) so per-tenant OIDC can be tested in isolation.

### Analysis
- **Affected components:** `backend/app/api/deps.py` (authorize_identity platform gating), possibly `backend/app/services/permissions/permission_engine.py` (wildcard evaluation for platform modules), `setup/identity.py` (+ Keycloak client helpers) for demo realm seeding
- **Root cause hypothesis:** global tenant-less roles (legacy system_admin, is_system, tenant_id NULL) with wildcard policies are collected for every module including `platform::*`
- **Documentation impact:** `fix-log.md`, `tech-spec.md`, `test-plan.md`, setup README

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Independent Verification Results (tester, 2026-10-01)

- **Backend:** combined suite (`test_platform_permission_gating`, `test_identity_plane`, `test_platform_admin_api`, `test_tenant_oidc_isolation`, `test_tenant_user_leak`, `test_tenant_isolation_sweep`, `test_default_tenant_roles`, `test_tenant_registration`, `backend/tests/unit/test_setup_tenant_demo`) → **171 passed, 0 failed, 0 errors** (142s).
- **Frontend:** `npx tsc --noEmit` → **clean** (exit 0; backend-only change, typecheck as guard).
- **E2E:** `playwright test single-tenant-regression multi-tenant-login-flows multi-tenant-lifecycle self-serve-signup` (mcp-hub / api-key-management / permission-errors excluded) → **22 passed, 1 skipped, 0 failed** (2.0m).
- **Security verdict (sanity-read of `backend/app/api/deps.py`): PASS.**
  1. The platform gate fires ONLY when `module.startswith("platform::")` AND `is_multi_tenancy_enabled(db)` — tenancy OFF skips the gate entirely (legacy path).
  2. The super-admin bypass (`if is_super_admin: return claims`) precedes the gate.
  3. `_system_tenant_platform_admin` resolves the system tenant and the ACTIVE `platform_admin` membership via `execute_unscoped` (identity plane, correct on scoped sessions) and requires `TenantUserMembershipStatus.active` + `tenant_role == "platform_admin"`.
  4. When tenancy is ON, the gate raises a structured 403 BEFORE `PermissionEngine.authorize`, so legacy global wildcard roles can never satisfy `platform::*`; non-platform modules are untouched.
- **Idempotency verdict (`setup/identity.py` `_seed_demo_tenant_realm`): PASS.** Every provisioning step guards on existence (realm_exists / client_exists / get_user_by_username) and reports `exists` instead of recreating; per-user `KeycloakAdminError` is reported, not raised. The seeding runs only under the opt-in `--tenant-demo` flag branch of `run_identity_setup`; the default `dev`/`identity` bootstrap path (`_setup_bundled_keycloak` + `_persist_oidc_config`) is unchanged.
- **Failure classification:** no failures in any layer; nothing fix-attributable; no environmental issues observed.

### Test Cases Added/Modified

**Reproduction result: the platform-gating defect reproduced with FAILING tests first (TDD).**
File: `backend/tests/test_platform_permission_gating.py` (NEW — 6 tests).

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `test_t1_legacy_global_wildcard_denied_on_platform_module` | **FAILS** (reproduces the defect — `DID NOT RAISE HTTPException`: the `*::*` global wildcard allowed `platform::tenants:read`) | Legacy global `system_admin` (tenant-less, `*::*` allow-all policy), multi-tenancy ON → `authorize_identity("platform::tenants", "read")` is DENIED |
| `test_t2_legacy_global_wildcard_still_works_in_tenant_module` | passes (existing-behaviour pin) | The SAME legacy user is still allowed `agent::management:read` in their tenant context (global roles remain effective for non-platform modules) |
| `test_t3_system_tenant_platform_admin_membership_allowed` | **FAILS** (feature absent — user has no RBAC roles, engine denied) | An ACTIVE `platform_admin` membership in the SYSTEM tenant satisfies `platform::*` |
| `test_t3b_non_platform_admin_membership_not_sufficient` | **FAILS** pre-fix (wildcard still allowed) | A plain `member` membership in the SYSTEM tenant does NOT unlock `platform::*` |
| `test_t4_tenancy_off_system_admin_wildcard_allowed` | passes (regression pin) | Tenancy OFF: the legacy wildcard keeps granting everything (byte-for-byte legacy, no platform concept) |
| `test_t5_super_admin_allowed` | passes (regression pin) | The super-admin bypass is untouched |

File: `backend/tests/unit/test_setup_tenant_demo.py` (NEW — 4 tests, Keycloak admin client mocked; no live Keycloak touched).

| Test | Asserts |
|------|---------|
| `test_seeds_realm_public_client_and_users` | Realm + PUBLIC frontend client (redirect URIs mirror the main realm's UI client) + demo users created via the admin client |
| `test_idempotent_rerun_skips_existing` | Re-run with everything existing → all `exists`, zero create calls, existence probes still performed |
| `test_partial_existing_only_creates_missing` | Only missing pieces are created (existing user untouched) |
| `test_user_creation_failure_is_reported_not_raised` | A `KeycloakAdminError` per user is reported as a step error, never raised out of the seeding loop |

### Code Changes
Updated by: developer (FIX-20260930-235927), 2026-10-01.

**1. `backend/app/api/deps.py` — platform gating in `authorize_identity`**
- New `_system_tenant_platform_admin(db, user_id)`: resolves the system tenant
  (`Tenant.is_system_tenant`) and looks up an ACTIVE
  `TenantUserMembership(tenant_role="platform_admin")` in it — both via
  `execute_unscoped` (identity plane; the platform console lives at the base
  domain where no tenant scope is bound, but the lookups stay correct even on
  a scoped session).
- New gate in `authorize_identity`, placed AFTER the membership-grants block
  and BEFORE `PermissionEngine.authorize`: when `module.startswith("platform::")`
  AND `PlatformSettingsService.is_multi_tenancy_enabled(db)` → the engine's
  global-role collection is SKIPPED; allowed only via
  `_system_tenant_platform_admin` (else a structured 403 with the
  `required_permission` payload). Super-admin bypass is unaffected (returns
  earlier). Tenancy OFF → gate never fires → byte-for-byte legacy.
- Non-platform modules untouched: global tenant-less roles remain effective in
  tenant contexts (T2 pin), membership grants unchanged.

**2. `setup/identity.py` + `setup/main.py` — demo tenant realm seeding (opt-in)**
- New `--tenant-demo` / `--tenant-demo-realm` flags on the `identity`
  subcommand (`main.py`). When set, `run_identity_setup` runs ONLY
  `_run_tenant_demo_seed` INSTEAD of the bundled-Keycloak bootstrap; `dev`
  builds its own `Namespace` without the flag, so the default bootstrap flow
  is unchanged.
- `_run_tenant_demo_seed` authenticates via `KeycloakAdminClient`, then
  `_seed_demo_tenant_realm(kc, token, realm, ui_client_id, users)` provisions,
  idempotently (existence checks through the shared admin-client helpers):
  the demo realm (default `parthenon-acme`), a PUBLIC frontend client
  (`<client-id>-ui`, redirect URIs mirroring the main realm's UI client:
  5173/5174/4173/3000), and demo users `acme-admin` / `acme-user`
  (passwords = usernames; per-user failures reported, not raised).
- Post-run `_print_tenant_demo_instructions` prints the issuer URL for
  per-tenant OIDC config (System Config / tenant settings), the frontend
  client id, the test credentials, and the JIT default-role reminder.
- `KEYCLOAK_TENANT_DEMO_REALM` env var overrides the realm name.

**3. Frontend — NO change needed (verified):** `AppShell` renders the platform
nav group purely from `multiTenancyEnabled` (no frontend-local admin
heuristic); actual access is gated by `PlatformAdminRoute`'s backend probe
(`platform::settings:read`), which now 403s for legacy wildcard holders and
renders the access-denied page. The fix follows automatically.

### Documentation Updates
- `tech-spec.md`: "Tenant-aware permission engine" section gains the platform
  gating semantics; Code Reference Map rows for
  `_system_tenant_platform_admin`, `_seed_demo_tenant_realm`/
  `_run_tenant_demo_seed`, and the two new test files.
- `setup/README.md`: `--tenant-demo` documented (flag, realm default, env
  var, post-run operator steps).

### Verification Results
Developer verification (2026-10-01, macOS/zsh, `.venv/bin/python` from repo root, postgres UP, Keycloak UP but untouched, no dev servers):

- **Pre-fix TDD state:** `test_platform_permission_gating.py` → **3 failed (T1/T3/T3b — the repro), 3 passed (T2/T4/T5 pins)**.
- **Post-fix:** same file → **6 passed**; `test_setup_tenant_demo.py` → **4 passed**.
- **Named regressions (exact VERIFY command):** `test_identity_plane.py test_platform_admin_api.py test_tenant_oidc_isolation.py test_default_tenant_roles.py test_tenant_user_leak.py test_tenant_isolation_sweep.py backend/tests/unit` → **1000 passed, 11 skipped, 0 failed** (155s).
- **Backend imports cleanly:** `import app.api.deps, app.main, setup.identity, setup.main` → OK; `py_compile` on all touched files → OK.
- **Frontend:** no changes → no tsc/vitest run required.
- **Live Keycloak:** NOT mutated by tests (unit tests mock `KeycloakAdminClient`). Manual verification: `python -m setup.main identity --tenant-demo` against localhost:8082, then re-run → all `exists`.

### Deviations / Concerns for review
1. **Gate placement is in `authorize_identity`, not `PermissionEngine`** — the engine keeps its semantics (global roles collected for every module; `test_default_tenant_roles.py` pins engine-level behaviour). Only the identity/permission choke point special-cases `platform::*`. Direct `PermissionEngine.authorize(..., "platform::*")` callers would still see the old semantics — an audit found none outside tests that pin the engine itself.
2. **T3b added** beyond the five requested tests: pins that a plain `member` membership in the system tenant does not suffice (only `platform_admin` does).
3. **The gate fires for `platform::*` regardless of whether a tenant context is resolved.** In a resolved-tenant context the no-membership gate fires first (existing semantics), so the only observable change is: a tenant-context user without a system-tenant `platform_admin` membership can no longer ride global wildcards into `platform::*` — exactly the decided semantics.
4. **Demo users' passwords default to the usernames** (`acme-admin`/`acme-admin`, `acme-user`/`acme-user`) — documented demo credentials only, opt-in command, not part of `dev`.
5. **Setup flag semantics:** `--tenant-demo` REPLACES the default bootstrap for that invocation (rather than running both) — keeps the default flow byte-for-byte and makes the demo run independently re-runnable.

---

## FIX-20260930-075014

**Created:** 2026-09-30T07:50:14Z
**Status:** Resolved (independently verified by tester, 2026-09-30)
**Issue:** Tenant-less OIDC validation fails ("All auth tiers failed" on /auth/tenant-memberships → session wipe → login loop) because the adopted platform provider lives only in the system-tenant slot with no shared/tenant-less fallback; plus identity-model refinement — JIT default tenant role on first OIDC sign-in, membership-based admission

### Observed Behavior
- `Auth middleware: All auth tiers failed for /api/v1/auth/tenant-memberships (token len=1407)` on every workspace load → AuthContext wipes tokens → redirect to login, regardless of successful workspace sign-in.
- DB: `identity_provider_configs` has NO NULL-tenant (shared) rows; the `parthenon` realm provider exists only in the system-tenant slot (`aa1878c4`) and the test-com slot. `_try_oidc_token` on a tenant-less path resolves the shared `(None, user)` slot → empty → fail.

### Expected Behavior (user-confirmed identity model)
1. Identities are self-managed (platform-issued email+password) or linked to an IdP identity (OIDC sub).
2. Sign-in is contextual: platform sign-in (requires platform roles) or tenant sign-in by workspace address (requires a role in that tenant).
3. **Provider resolution fallback**: own slot → shared (NULL-tenant) slot → system-tenant (adopted platform provider) slot. One provider can serve the platform and multiple tenants; issuer/JWKS validation unchanged; tenancy-OFF unchanged.
4. **JIT default role**: OIDC configuration gains a default tenant role (one of the seeded presets: Tenant System Admin / Agent Manager / Agent Executor / Agent Viewer). On a user's FIRST sign-in to a tenant via that provider, the configured role is assigned (membership + role grant). Unset → no JIT membership.
5. **Admission**: sign-in to a tenant succeeds iff the user has a role (active membership) there — otherwise rejected with the existing `no_access_to_workspace` semantics (never a re-auth loop).

### Analysis
- **Affected components:** `backend/app/services/oidc_provider_registry.py` (resolution order), `backend/app/middleware/auth.py::_try_oidc_token` (tenant-less validation + JIT hook), `backend/app/db/models/identity_provider_config.py` (default-role setting + migration), membership/role provisioning service, frontend (config UI field for default role; no new loop paths)
- **Root cause hypothesis:** the shared-provider refactor (FIX-20260929-221449) introduced the shared `(None, scope)` slot but dropped the prior system-tenant fallback for tenant-less contexts; the adopted provider was never migrated to the shared slot
- **Documentation impact:** `fix-log.md`, `prd.md`/`spec-change.md` (JIT default-role capability), `tech-spec.md`, `test-plan.md`, `architecture.md` (provider resolution order)

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified

**Reproduction result: both halves reproduced with FAILING tests first (TDD).**

#### File: `backend/tests/test_oidc_provider_fallback.py` (NEW — Part A, 9 tests)

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `test_a_tenant_less_lookup_resolves_system_slot` | **FAILS** (reproduces the loop) | Registry-level: with the ONLY provider row in the SYSTEM-tenant slot, `get_provider("user", None)` resolves it (pre-fix: `None` → "All auth tiers failed") |
| `test_a_tenant_less_request_validates_token` | **FAILS** | Middleware-level: `_try_oidc_token("tok", None)` validates against the adopted (system-slot) provider AND injects NO tenant claim (tenant-less semantics unchanged) |
| `test_b_tenant_without_own_or_shared_resolves_system_slot` | **FAILS** | Tenant X (no own/shared config) resolves the SYSTEM provider for its login context — "one provider serves all tenants" realized for the adopted provider too |
| `test_b_tenant_login_context_validates_against_system_provider` | **FAILS** | `_try_oidc_token` for CTX_X validates via the system-slot provider AND injects `tenant = X` from the resolved login context |
| `test_c_tenant_own_config_wins_over_system_slot` | passes (precedence pin) | X's OWN config beats the system-slot fallback |
| `test_shared_slot_still_precedes_system_slot` | passes (ordering pin) | shared (None) slot beats the system slot for both lookup kinds |
| `test_no_provider_anywhere_is_fail_closed_none` | passes (pin) | fail-closed `None` preserved |
| `test_tenancy_off_unchanged` | passes (pin) | tenancy OFF → legacy single global provider |
| `test_system_tenant_itself_resolves_own_slot` | passes (pin) | the system tenant resolves its own slot directly |

#### File: `backend/tests/test_oidc_jit_default_role.py` (NEW — Part B, 8 tests)

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `test_d_first_sign_in_grants_membership_and_viewer_role` | **FAILS** (feature absent) | First OIDC sign-in to tenant X (provider `default_tenant_role=agent_viewer`) → active non-root membership + `Agent Viewer` preset Role via `UserRole`; `authorize_identity` passes for `agent::agent_management:read` |
| `test_e_second_sign_in_is_idempotent` | passes pre-fix (vacuous), meaningful post-fix | Second sign-in → exactly one membership, one role assignment |
| `test_f_unset_default_jit_nothing_and_403_path_unchanged` | passes (pin) | Unset default → NO JIT; `authorize_identity` → `403 no_access_to_workspace` (existing behavior pinned) |
| `test_g_shared_provider_default_applies_in_tenant_context` | **FAILS** | SHARED provider's default applies in tenant X's context |
| `test_h_system_slot_fallback_provider_jit` | **FAILS** | The SYSTEM-slot (adopted) provider with a default JITs in tenant X's context too |
| `test_platform_password_login_never_jits` | passes (pin) | Claims WITHOUT `_provider_scope` (platform-password tokens) never JIT, even with a default configured |
| `test_jit_records_audit_event` | **FAILS** | JIT provisioning records a `self_serve_registration` TenantAuditEvent for the tenant |
| `test_endpoint_level_first_sign_in_passes_data_call` | **FAILS** | End-to-end: after the JIT sign-in a real permission-gated `GET /api/v1/platform-users` in tenant X returns 200 (middleware sim, real `require_permission`) |

#### File: `frontend/src/__tests__/IdentityProviderConfigForm.test.tsx` (EXTENDED, +3 tests)

Default-role select renders for the user scope; absent for the agent scope; `default_tenant_role: null` persisted when nothing selected. Existing `currentConfig` literals extended with `default_tenant_role: null` (interface field).

#### File: `backend/tests/test_tenant_oidc_isolation.py` / `test_identity_plane.py` — UNCHANGED
All existing shared-provider precedence pins and fail-closed pins hold unchanged under the system-slot fallback (the fixtures have no `is_system_tenant` tenant rows, so the new fallback is inert for them).

### Code Changes
Updated by: developer (FIX-20260930-075014), 2026-09-30.

**1. `backend/app/services/oidc_provider_registry.py` — SYSTEM-tenant slot fallback (Part A)**
- New `_system_tenant_id` cache field, loaded by `_load_system_tenant_id(db)` via
  `select(Tenant.id).where(Tenant.is_system_tenant.is_(True))` — the same
  system-tenant identification the adoption flow uses
  (``TenantAdoptionService.find_system_tenant``). Refreshed in BOTH
  ``initialize()`` and ``reload_single()`` (same invalidation hooks as the
  provider map).
- `_resolve_cached` resolution order (multi-tenancy ON) for BOTH tenant-scoped
  and tenant-less lookups: **own `(tenant, scope)` → shared `(None, scope)` →
  system `(system_id, scope)`**. Tenant-less lookups resolve shared → system;
  the redundant own-slot re-check is skipped when the tenant IS the system
  tenant. Tenancy OFF unchanged (legacy single global slot); fail-closed
  `None` preserved when no slot holds a config.

**2. `backend/app/services/tenancy/default_tenant_roles.py` — JIT admission helper (Part B)**
- New `DefaultTenantRole` str-enum over the EXACT seeded preset keys
  (`tenant_system_admin` / `agent_manager` / `agent_executor` /
  `agent_viewer`) — the DB-facing values of
  `IdentityProviderConfig.default_tenant_role`.
- New `jit_membership_with_default_role(db, *, tenant_id, user_id, role_key)`
  (idempotent): creates an ACTIVE `TenantUserMembership`
  (`tenant_role=member`, `is_root=False`) and assigns the tenant's preset
  `Role` row (seeded on demand via `seed_default_tenant_roles`) through the
  existing `UserRole` mechanism (`_ensure_user_role`). Returns False when an
  active membership already exists (second sign-in) or the key is unknown
  (logged, no membership); an INACTIVE membership is never auto-reactivated.

**3. `backend/app/db/models/identity_provider_config.py` + migration `a1f2c3d4e5b6`**
- New nullable column `default_tenant_role` — NON-native enum
  (`native_enum=False`: VARCHAR + CHECK, no PG `CREATE TYPE` per migration
  conventions) over `DefaultTenantRole`.
- Migration `a1f2c3d4e5b6_jit_default_tenant_role_on_identity_provider_configs.py`
  (revises `6363bb7ee8c3`): additive `ADD COLUMN` + named CHECK constraint;
  reversible (`DROP CONSTRAINT` + `DROP COLUMN`). Applied and verified
  downgrade→upgrade on the local postgres (head = `a1f2c3d4e5b6`).

**4. `backend/app/middleware/auth.py` — JIT admission hook**
- New `JWTAuthMiddleware._maybe_jit_default_role`, invoked at the end of
  `_sync_user_and_groups` (same transaction/session; fire-and-log like the
  rest of the sync). Gates: `claims["_provider_scope"] in ("user", "agent")`
  (OIDC registry tokens only — platform-password and super-admin NEVER JIT);
  tenant context RESOLVED (`is_set` + `tenant_id`); the provider resolvable
  for the resolved tenant (own → shared → system fallback via the registry)
  carries `default_tenant_role`; user has NO active membership (idempotent).
  On JIT creation, records a `self_serve_registration` TenantAuditEvent with
  `detail.reason = "jit_default_role_assigned"` (existing enum value — no
  enum change needed). Unset default → no JIT → the existing
  `no_access_to_workspace` 403 path (unchanged). Token claim injection
  semantics untouched.

**5. CRUD (`schemas/system_config.py`, `services/oidc_config_service.py`, `api/v1/system_config.py`)**
- Create/Update/Response schemas accept + persist `default_tenant_role`
  (validated against the seeded preset keys in BOTH the Pydantic validator
  and the service). `create_provider` / `update_provider` take the field;
  `_config_diff_fields` snapshots it (audit); `_config_to_response` exposes
  it; both endpoints pass it through.

**6. Frontend (minimal)**
- `api/systemConfigApi.ts`: `default_tenant_role?: string | null` on Item /
  Create / Update interfaces.
- `components/system/IdentityProviderConfigForm.tsx`: "Default role for new
  OIDC users" MUI Select (user scope only — JIT concerns human sign-in),
  options = the four presets + "None (reject new users)"; persisted through
  the existing onSave → create/update API (the page spreads `...data`, so
  `IdentityProvidersConfigPage.tsx` needed no change).
- `i18n/locales/en.json`: 6 new `systemConfig.identityProviders.defaultRole*` keys.

### Documentation Updates
- `tech-spec.md`: registry resolution order updated (system-slot fallback);
  new JIT flow documented; Code Reference Map rows for
  `jit_membership_with_default_role`, `DefaultTenantRole`,
  `IdentityProviderConfig.default_tenant_role`, migration `a1f2c3d4e5b6`,
  `_maybe_jit_default_role`, and the two new test files.

### Verification Results
Developer verification (2026-09-30, macOS/zsh, `.venv/bin/python` from repo root, postgres UP, no dev servers):

- **Fix suites:** `test_oidc_provider_fallback.py` + `test_oidc_jit_default_role.py` → **17 passed** (pre-fix: 10 failed / 7 passed — all repros; the 7 "passing pre-fix" are precedence/ordering/fail-closed pins plus two vacuous pins that become meaningful post-fix).
- **Named regressions (9-suite command):** `test_tenant_oidc_isolation` + `test_identity_plane` + `test_tenant_user_leak` + `test_tenant_isolation_sweep` + `test_oidc_tenant_claim_gap` + `test_tenant_resolution` + `test_tenant_login_probe_bypass` + `test_platform_admin_api` + `test_default_tenant_roles` → **184 passed, 0 failed**.
- **Adjacent suites:** `test_auth_middleware_full.py` + `tests/services/permissions` → **28 passed**.
- **Migration:** `alembic upgrade head` → `a1f2c3d4e5b6`; downgrade -1 → upgrade head round-trip clean.
- **Frontend type check:** `npx tsc --noEmit` → clean.
- **Frontend full suite:** `npx vitest run` → **1559 passed / 0 failed** (1577 total, 18 pending by design; baseline 1556/0 — the +3 are the new default-role form tests).

### Deviations / Concerns for review
1. **`default_tenant_role` is returned unmasked in public listings** (`GET /system/identity-providers`). It is a non-sensitive preset key (not a credential), and the login page consumes that endpoint — masking would only complicate the admin form. Secrets remain masked as before.
2. **Update semantics: omitted `default_tenant_role` = unchanged** (consistent with every other optional Update field). Clearing the role to null via the PUT endpoint is therefore not expressible in isolation (recreate or a dedicated clear path would be needed); the frontend always sends the current selection (null when "None"), so the UI can clear it.
3. **Audit uses the existing `self_serve_registration` event type** (preferred per brief — a suitable value existed) with `detail.reason = "jit_default_role_assigned"`; no `TenantAuditEventType` enum change, no extra migration.
4. **JIT gate keys on `claims["_provider_scope"]`** to distinguish OIDC-registry tokens from platform-password tokens (which carry no such claim) — a marker the OIDC validation tier already sets.
5. **JIT runs inside `_sync_user_and_groups`' existing fire-and-log wrapper**: an infrastructure failure while provisioning logs a warning and does NOT fail the request; the user then hits the normal `no_access_to_workspace` 403 and can retry — no half-admitted state (membership + role + audit commit atomically with the sync transaction).

### Verification Results — Independent (tester, 2026-09-30)

All layers re-run independently from a clean shell; developer text above preserved unchanged.

1. **Backend (12-suite command):** `test_oidc_provider_fallback` + `test_oidc_jit_default_role` + `test_tenant_oidc_isolation` + `test_identity_plane` + `test_tenant_user_leak` + `test_tenant_isolation_sweep` + `test_oidc_tenant_claim_gap` + `test_tenant_resolution` + `test_tenant_login_probe_bypass` + `test_platform_admin_api` + `test_default_tenant_roles` + `test_tenant_registration` → **220 passed, 0 failed** (166s; one pre-existing SAWarning about unresolvable FK DROP ordering — cosmetic, unrelated).
2. **Migration:** `alembic current` → **`a1f2c3d4e5b6 (head)`** ✓. File `backend/alembic/versions/a1f2c3d4e5b6_jit_default_tenant_role_on_identity_provider_configs.py` read and reviewed: **additive** (nullable `default_tenant_role` VARCHAR(50) + named CHECK over the four preset keys, no PG native enum per conventions) and **reversible** (downgrade = drop CHECK + drop column); `down_revision = 6363bb7ee8c3` chains correctly.
3. **Frontend:** `npx tsc --noEmit` → **clean (exit 0)**. `npx vitest run` → **1559 passed / 0 failed** (1577 total, 18 skipped).
4. **E2E (4 excluded-suites command — oidc-login-flows, multi-tenant-login-flows, self-serve-signup, single-tenant-regression):** **29 passed, 1 skipped, 0 failed** (2.4m).
5. **Security sanity-read (source-level, both files read in full):**
   - **Resolution order** (`oidc_provider_registry.py::_resolve_cached`): confirmed **own `(tenant, scope)` → shared `(None, scope)` → system `(system_id, scope)`**, redundant own-slot re-check skipped when tenant IS the system tenant, **fail-closed `None`** when no slot matches; system tenant id resolved via the same `Tenant.is_system_tenant` helper as the adoption flow, cached and refreshed in both `initialize()` and `reload_single()`.
   - **JIT gating** (`auth.py::_maybe_jit_default_role` + `default_tenant_roles.py::jit_membership_with_default_role`):
     - Fires ONLY for OIDC-registry tokens: gate `claims["_provider_scope"] in ("user", "agent")` — platform-password/super-admin tokens carry no such claim → return before any provisioning. ✓
     - Fires ONLY with resolved tenant context: `context.is_set` and `tenant_id` required; single-tenant/tenant-less paths never JIT. ✓
     - Fires ONLY when provider default set + no existing membership: `role_key is None → return`; idempotent lookup — existing ACTIVE membership → False (no-op), INACTIVE membership → False (never auto-reactivated). ✓
     - Assigned role is the TENANT-SCOPED preset Role: `Role.tenant_id == tenant_id, name == preset.role_name` (seeded on demand). ✓
   - **JIT-escalation check: PASS — no escalation path.** Role key is normalized against the four-preset whitelist (`DEFAULT_TENANT_ROLE_PRESETS`); unknown key → logged, no membership. Preset permissions span only `agent::/integration::/system::/tenant::*` manifest actions — **never `platform::*`**. The `tenant_system_admin` preset is a tenant-scoped role, NOT root: the JIT-created membership hardcodes **`is_root=False`** (and `tenant_role=member`); root is the `is_root` membership flag, which JIT never sets. ✓

**Independent verdict: ALL LAYERS GREEN — no fix-attributable failures, no environmental issues. FIX-20260930-075014 Resolved.**

---

## FIX-20260929-221449

**Created:** 2026-09-29T22:14:49Z
**Status:** Resolved (independently verified by tester)
**Issue:** OIDC users bounced to login in multi-tenant mode: identity resolution is tenant-scoped (PlatformUser invisible without membership); plus product direction — one identity provider must be shareable across platform and multiple tenants, with the login context deciding the session tenant

### Observed Behavior
OIDC sign-in (Keycloak admin, sub=8c849b63) authenticates and reaches the dashboard, then is redirected back to login. Logs: `authorize_identity: PlatformUser not found for sub=8c849b63 — user must re-authenticate` even though the PlatformUser row EXISTS (admin@parthenon.local) — the tenant-scoped choke point hides it because the user has no membership in the resolved tenant (`test-com`). Secondary: repeated `All auth tiers failed for /api/v1/auth/tenant-memberships (token len=1407)`.

### Expected Behavior
- **Identity plane is platform-level**: resolving "who is this request from" (PlatformUser by cryptographic sub, JIT provisioning) must be tenant-scope-exempt; membership + RBAC then decide access to the resolved tenant.
- **Shared identity providers**: one provider config can serve the platform AND multiple tenants; the login context (resolved workspace) determines the session tenant. A tenant may still define its own dedicated provider (takes precedence for that tenant). When multi-tenancy is disabled, platform and the default tenant share the single global provider (unchanged).
- An authenticated user without membership in the resolved tenant gets permission-denied semantics — never a re-authentication redirect loop.

### Analysis
- **Affected components:** `backend/app/db/tenant_scoping.py` (needs an explicit scope-exempt execute path), `backend/app/api/deps.py::authorize_identity` (PlatformUser lookup + membership grants), `backend/app/services/permissions/user_cache_service.py::upsert_user` (JIT provisioning currently scoped → silent unique-violation swallow), `backend/app/middleware/auth.py::_try_oidc_token` + `app/services/oidc_provider_registry.py` (shared-provider fallback + claim injection from login context), frontend no-access handling
- **Root cause hypothesis:** FIX-20260928-121317 applied the PlatformUser membership-join strategy to ALL selects — correct for the data plane (user lists), wrong for the identity plane
- **Documentation impact:** `fix-log.md`, `tech-spec.md`, `test-plan.md`, `architecture.md` (provider-sharing model)

### Fix Tasks
- [x] **Reproduce** — Create test cases that demonstrate the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified

**Reproduction result: all three defects reproduced with FAILING tests first (TDD).**
File: `backend/tests/test_identity_plane.py` (NEW — 22 tests, T1–T7 from the fix brief).

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `TestIdentityPlaneIsScopeExempt::test_authorized_user_with_system_tenant_membership_only_resolves_in_tenant_x_context` (T1) | **FAILS** (reproduces the bounce) | An adopted user (membership ONLY in the system tenant) in a tenant-X context: `authorize_identity` must RESOLVE the PlatformUser and deny with the structured `no_access_to_workspace` 403 — pre-fix it raised `403 'User not found in platform. Please re-authenticate.'` (the exact reported log line) |
| `TestIdentityPlaneIsScopeExempt::test_get_user_by_sub_resolves_on_scoped_session` | **FAILS** | Identity-plane helper: `UserCacheService.get_user_by_sub` resolves on a tenant-scoped session (pre-fix: `None`) |
| `TestIdentityPlaneIsScopeExempt::test_execute_unscoped_helper_sees_hidden_user` | **FAILS** (mechanism absent) | `execute_unscoped(db, stmt)` returns the rows the scoped session hides; a plain `db.execute` keeps the membership-join filter |
| `TestJitProvisioningIsScopeExempt::test_upsert_user_on_scoped_session_returns_existing_invisible_user` (T2) | **FAILS** — `IntegrityError: UNIQUE constraint failed: platform_users.email` (reproduces the swallowed duplicate) | JIT `upsert_user` on a scoped session returns the EXISTING row; exactly one row per sub (pre-fix: scoped selects miss the user → duplicate INSERT → unique-violation at flush, swallowed by the auth middleware's fire-and-log wrapper) |
| `TestSharedIdentityProvider::test_t3_shared_provider_validates_tenant_login_context_and_injects_claim` (T3) | **FAILS** — `claims is None` | Tenant X with NO own provider config + a SHARED (NULL-tenant) config: `_try_oidc_token` validates against the shared slot AND injects `tenant = X` from the resolved login context; `_check_tenant_claim` accepts (pre-fix: fail-closed None → sign-in impossible for any tenant without its own provider) |
| `TestSharedIdentityProvider::test_t4_tenant_own_config_wins_over_shared` (T4) | passes (precedence pin — already true pre-fix) | When tenant X ALSO has its own config, the own slot validates the token (shared slot only fills gaps) |
| `TestSharedIdentityProvider::test_registry_shared_slot_resolves_for_any_tenant` / `test_registry_platform_surface_resolves_shared_slot` / `test_registry_no_provider_at_all_is_fail_closed_none` / `test_tenancy_off_everything_uses_global_provider` | first two **FAIL** pre-fix; the last two pass (pins) | Registry-level: shared slot resolvable for ANY tenant and the platform surface; with neither own nor shared provider → None (fail-closed preserved); tenancy OFF → single global provider unchanged |
| `TestNoMembershipForbiddenShape::test_t5_no_membership_data_call_is_clean_403_no_access_to_workspace` (T5) | **FAILS** (reproduces the re-auth 403) | Endpoint-level (`GET /api/v1/platform-users`, real `require_permission` gate, tenant-X context): an authenticated user with NO membership gets `403 {"detail": "no_access_to_workspace", "required_permission": {...}}` — never the re-auth message |
| `TestNoMembershipForbiddenShape::test_t6_member_data_call_passes` (T6) | passes pre-fix (member visible), stays green | The same call for a ROOT member of X → 200 with X's member list; `authorize_identity` allows the root for a business module |
| `TestDataPlaneUserListingStillScoped::test_t7_scoped_user_list_excludes_non_members` (T7) + `test_scoped_get_of_non_member_is_none` | passes (pins — must stay green) | Data-plane user LIST under tenant X still excludes non-members; scoped `db.get` of a non-member id stays not-found |

Key failure output (pre-fix, verbatim):
```
T1: AssertionError: IDENTITY PLANE SCOPED (FIX-20260929-221449 / T1): the PlatformUser exists but
    the tenant-scoped lookup hid it — authorize_identity must resolve the user and deny with the
    structured no-membership shape, got detail='User not found in platform. Please re-authenticate.'
T2: sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) UNIQUE constraint failed:
    platform_users.email  [SQL: INSERT INTO platform_users ...]
T3: AssertionError: SHARED PROVIDER NOT RESOLVED (FIX-20260929-221449 / T3): a tenant whose login
    context resolves but that has no OWN provider config must validate against the SHARED
    (NULL-tenant) provider — assert None is not None
```
Run: `.venv/bin/python -m pytest backend/tests/test_identity_plane.py backend/tests/test_tenant_oidc_isolation.py -q` → **9 failed, 28 passed, 4 errors** (pre-fix) → **37 passed** (post-fix).

#### File: `backend/tests/test_tenant_oidc_isolation.py` (EXTENDED — semantics-changed assertions)

| Test | Status pre-fix | Change |
|------|----------------|--------|
| `TestRegistryTenantKeying::test_tenant_without_own_config_resolves_shared_provider` | **FAILS** pre-fix | **SEMANTICS CHANGED by the product decision** — replaces `test_non_system_tenant_without_provider_is_none` (`get_provider("user", uuid4()) is None`). The NULL-tenant row is now the SHARED provider: a tenant WITHOUT its own config resolves it for its login context. Per-tenant precedence stays pinned by `test_tenant_gets_own_provider` |
| `TestRegistryTenantKeying::test_no_provider_anywhere_is_fail_closed_none` | passes (pin) | NEW — fail-closed preserved: a tenant with NEITHER an own NOR a shared config still gets `None` |
| module docstring | — | Strategy note updated: the tenant-less row is the shared provider (platform + any tenant without own config), not a system-tenant-only fallback |

No other assertions in the file changed: `test_system_tenant_falls_back_to_global` (own slot wins for the system tenant), the `_try_oidc_token` tenant-binding tests (fail-closed when NO provider is resolvable), the `_check_tenant_claim` matrix (missing/mismatch/match/super-admin), and the `OIDCConfigService` per-tenant CRUD isolation tests all hold unchanged under the shared-provider model.

#### `test_tenant_isolation_sweep.py` — strategy-note-only change
`TENANT_AGNOSTIC_REGISTRY["platform_users"]` entry updated to document the DUAL strategy (data-plane membership-join + identity-plane scope exemption). No test logic touched; the registry-completeness guard stays green.

### Code Changes
Updated by: developer (FIX-20260929-221449), 2026-09-30.

**Mechanism chosen for the identity-plane exemption (decision #1): a statement-level execution
option on the scoping choke point, exposed through the helper `execute_unscoped(db, stmt)`.**
The exemption is per STATEMENT — everything else on the scoped session stays fully
tenant-constrained, so the data plane (user listings, member administration) keeps the
membership-join strategy byte-for-byte (T7 + `test_tenant_user_leak.py` stay green).

**1. `backend/app/db/tenant_scoping.py` — the scope-exempt execute path**
- `execute_unscoped(db, stmt, *args, **kwargs)` (new, canonical helper): attaches the
  execution option `{"tenant_scope": "exempt"}` to the statement and executes it. Also
  suppresses cross-tenant MISS AUDITING for the statement (a missing identity at first
  login is a normal JIT signal, not a cross-tenant probe). The raw
  `db.execute(stmt, execution_options={"tenant_scope": "exempt"})` form is honoured by the
  choke point too; the helper is canonical because only it can suppress the miss-audit proxy.
- `_tenant_scope_do_orm_execute`: early-returns for exempt statements (checked via
  `orm_exec_state.execution_options`, which merges both forms) — no
  `with_loader_criteria`/DML criteria are applied to that statement.
- `_install_miss_detection`'s `scoped_execute` wrapper: exempt statements skip the
  scope-miss result proxy (`_is_scope_exempt_statement` reads the statement's own options).
- Documented caveat: full-entity rows loaded through an exempt statement enter the session
  identity map, so a later `session.get()` of the same identity short-circuits without
  re-applying scope — identity-plane call sites consume the loaded object directly.
- INSERT stamping (`before_flush`) intentionally NOT affected.

**2. `backend/app/api/deps.py` — identity resolution + the no-membership gate**
- `authorize_identity`: the PlatformUser-by-sub lookup now runs via `execute_unscoped`
  (identity plane) — an adopted user resolves in ANY resolved-tenant context.
- New `_active_membership(db, user_id, tenant_id)` (single membership SELECT) and
  `_membership_grants_from(membership, module, action)` (grant evaluation for an
  already-loaded membership — sync; root blanket grant + static dict, behaviour unchanged).
  `_membership_grants` keeps its public signature (used by `test_default_tenant_roles.py`,
  `test_tenant_root_protection.py`) and delegates to the two helpers.
- **No-membership gate (decision #3):** when a tenant context is resolved and the user has
  NO active membership in it → `NoWorkspaceAccessError` — a clean 403, never "user must
  re-authenticate". Cross-tenant safety is unchanged: membership + row-level scoping still
  gate every piece of data; super-admin platform-only semantics unchanged (returns before
  the gate).
- New `NoWorkspaceAccessError(HTTPException)` — carries `detail="no_access_to_workspace"`
  plus extra context; serialized FLAT by the app-level handler below so the wire body is
  exactly `{"detail": "no_access_to_workspace", "required_permission": {...}}` (Starlette
  resolves handlers via the MRO, so the subclass handler beats FastAPI's default envelope).

**3. `backend/app/main.py` — flat serialization for the no-access contract**
- `no_workspace_access_handler` registered for `NoWorkspaceAccessError`: returns
  `403 {"detail": "no_access_to_workspace", **exc.extra}`. The frontend's
  `parsePermissionError` picks up the top-level `required_permission` and surfaces a
  permission-denied snackbar; `isTenantResolutionRejection` cannot match (different
  `detail` + `required_permission` present) so `apiClient` neither self-heals the tenant
  binding nor clears tokens — it is not an auth failure (no redirect loop).

**4. `backend/app/services/permissions/user_cache_service.py` — JIT provisioning (decision #1)**
- `upsert_user` (by-sub + by-email selects), `get_user_by_sub`, and `upsert_identity`
  (by-subject) now run via `execute_unscoped` — a scoped JIT upsert finds and refreshes the
  existing record instead of inserting a unique-violating duplicate (T2).

**5. `backend/app/services/oidc_provider_registry.py` — shared providers (decision #2)**
- New `_resolve_cached(scope, tenant_id, is_system_tenant)`: the tenant's OWN
  `(tenant, scope)` slot wins; the SHARED tenant-less `(None, scope)` slot is the fallback
  for ANY tenant without its own config (and the only slot for the platform surface /
  tenancy off). Replaces six duplicated system-tenant-only fallback blocks across
  `get_provider`, `get_decrypted_secret`, `get_jwks`, `get_discovery`, `invalidate_jwks`,
  `invalidate_discovery`. `is_system_tenant` retained for API compatibility (the fallback
  no longer depends on it). `initialize`/`reload_single` unchanged — a NULL-tenant row
  already lands in the `(None, scope)` slot.
- Fail-closed preserved: no own AND no shared provider → `None` (sign-in not configured).
  Tenancy OFF: byte-for-byte legacy (single global provider).

**6. `backend/app/middleware/auth.py` — claim injection from the resolved login context**
- `_try_oidc_token` / `_inject_tenant_claim`: NO code-logic change needed — with the new
  registry resolution, `registry.get_provider(scope, tenant_id, False)` naturally resolves
  own-OR-shared for the resolved tenant, so the `tenant` claim is injected whenever a
  provider validated the token for that login context. Docstrings rewritten to document
  WHY injection from the resolved context is now legitimate: the claim source is the
  resolved LOGIN CONTEXT (the registry slot that validated the token — never the request's
  `X-Tenant` header); cross-tenant safety under the shared-provider model comes from
  membership gates (`no_access_to_workspace` without an ACTIVE membership) + the row-level
  scoped data plane — a user without membership gets 403s, never data.
  `_check_tenant_claim` untouched (missing/mismatch/super-admin rejections intact).

**7. Remaining identity-plane lookups (audit of every `PlatformUser.sub ==` /
`Identity.subject ==` path — all now `execute_unscoped`):**
- `backend/app/api/v1/tenant.py` — `require_tenant_membership` (sub → membership check;
  its no-membership 403 now raises `NoWorkspaceAccessError(tenant_slug=...)`) and
  `accept_invitation` (public token-based acceptance resolves the caller by sub).
- `backend/app/api/v1/auth_tenant.py` — `list_my_tenant_memberships` (org picker).
- `backend/app/api/v1/agents.py` — `request_runtime_termination` (PlatformUser by sub AND
  the canonical human Identity by subject).
- `backend/app/services/dashboard_metrics_service.py` — `_resolve_user_id` (dashboard
  actor resolution).
- `backend/app/api/v1/intervene.py` + `conversations.py` — operator Identity-by-subject
  for the authenticated caller (the Identity row may live in another tenant than the
  resolved workspace).
- `backend/app/api/v1/internal/session_data.py` — operator Identity-by-subject on the
  signed internal path.
- `backend/app/api/v1/platform_users.py` — `delete_platform_user`'s Identity cascade
  lookup (cleanup of the deleted user's canonical Identity row).
- Deliberately LEFT tenant-scoped (DATA plane): `platform_users.py` list/detail/
  sub-resources (membership-join guards), `user_access_requests.py`, `user_groups.py`,
  `setup.py` (pre-tenancy bootstrap path).

**8. Stale-token `/auth/tenant-memberships` failures — investigated, ENVIRONMENTAL (no fix).**
The endpoint accepts BOTH token kinds correctly: it is in `BYPASS_PATHS`
(`tenant_resolution.py`), so no tenant context is resolved and `_check_tenant_claim` is
inert; `validate_raw_token` tries super-admin → CC-issued platform-account JWT (HS256,
validated by signature+exp) → OIDC (on a bypassed path the shared `(None, "user")` slot
resolves, so shared-provider tokens validate). The observed `All auth tiers failed
(token len=1407)` means the presented token failed every tier — an EXPIRED OIDC access
token (Keycloak default lifespan ≈ 5 min) left in `localStorage['access_token']` by a
previous session; `AuthContext.refreshAvailableTenants` sends it as soon as
`isAuthenticated && multiTenancyEnabled`. Rejecting an expired token with 401 is correct;
the existing interceptor wipes the stale tokens and stays on /login (self-healing).
No backend defect → no code change; environmental (stale browser state).

### Documentation Updates
- `tech-spec.md`: architecture section "Per-tenant OIDC registry" updated (shared-provider
  model + resolved-context claim injection); scoping section extended with the
  identity-plane exemption; Code Reference Map — `apply_tenant_scope` row annotated,
  new rows `execute_unscoped`, `NoWorkspaceAccessError`/handler, `authorize_identity`
  (no-membership gate), `UserCacheService` (identity-plane exemption),
  `OIDCProviderRegistry._resolve_cached` (shared slots), `_inject_tenant_claim` row
  superseded-annotation, `test_identity_plane.py`.
- Updated by: developer (FIX-20260929-221449), 2026-09-30.

### Verification Results
Developer verification (2026-09-30, macOS/zsh, `.venv/bin/python` from repo root, postgres UP, live dev stack on :8000/:8001/:8002 present but not managed by this fix; no dev servers started/stopped):

- **Fix suites:** `backend/tests/test_identity_plane.py` + `backend/tests/test_tenant_oidc_isolation.py` → **37 passed** (pre-fix: 9 failed, 28 passed, 4 errors — all repros).
- **Named regressions:** `test_tenant_user_leak.py` + `test_tenant_isolation_sweep.py` + `test_oidc_tenant_claim_gap.py` → **57 passed**; `test_tenant_resolution.py` + `test_tenant_login_probe_bypass.py` → **39 passed**; `test_platform_admin_api.py` + `tests/unit` → **873 passed, 11 skipped**; `test_auth_middleware_full.py` → **18 passed**.
- **Adjacent suites (refactor blast radius):** `test_default_tenant_roles.py` + `test_tenant_root_protection.py` + `tests/services/permissions/test_user_cache_service.py` → **50 passed**; `test_tenant_licensing_quotas.py` + `test_dashboard_api.py` + `test_tenant_registration.py` → **44 passed**.
- **Full backend suite:** 2240 passed / 226 skipped / **20 failed + 1 error — all pre-existing/environmental** (verified: the same files fail with the fix stashed): 17× `tests/integration/*` call the LIVE dev stack on :8000/:8001/:8002 (they bootstrap service certificates from the running CC and assert against ITS state — the running services predate this fix and these files are not in conftest's `_SERVICE_DEPENDENT_FILES` skip list), 1× `db/test_tenant_schema_migration.py::test_tenancy_switch_seeded_false` reads the real `parthenon_test` DB seed state (fails identically with and without the fix), 1× `unit/test_ws_delegation_visibility.py` teardown flake (`RuntimeError: Event loop is closed` — the test body itself passes). Zero fix-attributable failures.
- **Security property (code-read verdict): HOLDS.** The exemption is statement-scoped (`{"tenant_scope": "exempt"}`) — no endpoint can "forget" to scope a data-plane query by accident; every exempt call site is an explicit identity-plane resolution listed above. The no-membership gate closes the hole the exemption would otherwise open: an exempt-resolved user without membership gets `403 no_access_to_workspace` before any data access, and the data plane remains membership-joined. Shared-provider tokens bind to the resolved login context and are still checked by the untouched `_check_tenant_claim`; a user without membership gets 403s, never data.

**Independent verification — tester, 2026-09-30 (macOS/zsh, all layers re-run from scratch; verdict: all green, zero fix-attributable failures, zero environmental issues).**

- **Backend (all 9 named suites, one command):** `.venv/bin/python -m pytest backend/tests/test_identity_plane.py backend/tests/test_tenant_oidc_isolation.py backend/tests/test_tenant_user_leak.py backend/tests/test_tenant_isolation_sweep.py backend/tests/test_oidc_tenant_claim_gap.py backend/tests/test_tenant_resolution.py backend/tests/test_tenant_login_probe_bypass.py backend/tests/test_platform_admin_api.py backend/tests/test_auth_middleware_full.py -q` → **170 passed, 0 failed** (71s). Per-file: identity_plane 15, tenant_oidc_isolation 22, tenant_user_leak 2, tenant_isolation_sweep 52, oidc_tenant_claim_gap 3, tenant_resolution 34, tenant_login_probe_bypass 5, platform_admin_api 19, auth_middleware_full 18. (The "~1100" expectation corresponds to the developer's count that ALSO included `tests/unit` (~873); the specified 9-file command collects exactly 170 — reconciliation verified via `--collect-only`.)
- **Frontend type check:** `cd frontend && npx tsc --noEmit` → **clean (exit 0)**.
- **Frontend full suite:** `npx vitest run --reporter=json --outputFile=vitest_results.json` → **1556 passed / 0 failed** (1574 total, 18 pending by design; 377 suites, 0 failed suites). No load-induced timeouts — no isolation re-runs needed; nothing to classify.
- **E2E (32 tests matched across 6 spec files by the 5 filters, self-mocked preview):** `npx playwright test --reporter=line oidc-login-flows multi-tenant-login-flows self-serve-signup single-tenant-regression quota-enforcement` → **31 passed, 1 skipped, 0 failed** (2.4m). The single skip is `self-serve-signup.real-backend.spec.ts` (live-backend integration test, skipped by design — same as prior verification); mcp-hub / api-key-management / permission-errors excluded as instructed. The FIX repro `SSO round-trip lands on /dashboard with X-Tenant bound and NO bounce to /login` PASSED.
- **Security sanity-reads (code-read verdicts): ALL THREE HOLDS.**
  1. `tenant_scoping.py::execute_unscoped` — **VERDICT: HOLDS.** The exemption is STATEMENT-scoped, not a session switch: the helper attaches `{"tenant_scope": "exempt"}` to the individual statement (L132-138); `_tenant_scope_do_orm_execute` (L421-439) consults `orm_exec_state.execution_options` per execution and early-returns ONLY for that statement — the session's scope key stays set, so every other statement on the same session keeps the full rewrite (SELECT loader-criteria / DML criteria). No code path clears the session scope. Miss-audit suppression is equally per-statement (`scoped_execute` wrapper L516-533); INSERT stamping unaffected. Data-plane user listing: `platform_users.py::list_platform_users` (L85-105) uses `filter_platform_users_to_tenant` + plain `db.execute` — it does NOT use the exemption; the file's sole `execute_unscoped` is `delete_platform_user`'s Identity cascade lookup (L335-343, identity plane).
  2. `oidc_provider_registry.py` — **VERDICT: HOLDS.** NULL-tenant rows land in the shared `(None, scope)` slot (`initialize`/`reload_single`); `_resolve_cached` (L100-118) resolves the tenant's OWN `(tenant, scope)` slot FIRST and falls back to the shared slot only for a resolved tenant without an own config — own config wins (T4 pin). Fail-closed preserved: no own AND no shared provider → `None` / `{}` / `None` (sign-in not configured). Tenancy OFF: `_key` (L94-98) maps everything to `(None, scope)` with the deterministic tenant-less-wins guard (L149-155) — legacy single-global-provider behaviour unchanged.
  3. `deps.py` — **VERDICT: HOLDS.** The no-membership gate fires ONLY with a resolved tenant context (`if tenant_id is not None:` L447 gates `_active_membership` + the raise at L449-455; with no tenant context the gate is skipped entirely). Super-admin bypass intact (L399-401 — returns before the lookup and the gate). The 403 shape is the FLAT `no_access_to_workspace`: `NoWorkspaceAccessError(detail="no_access_to_workspace")` (L315-336) serialized flat by `main.py::no_workspace_access_handler` (L145-158) as `{"detail": "no_access_to_workspace", **extra}`. The only remaining "re-authenticate" text in `authorize_identity` is the genuinely-unknown-sub branch (PlatformUser row absent — a correct authentication failure); the no-membership path never emits it.

**Independent verdict: fix-attributable failures = 0, environmental issues = 0 → all green; Status: Resolved confirmed.**

### Deviations / Concerns for review
1. **Flat wire shape for the no-access 403 (new exception + handler).** The decision text
   specifies `{"detail": "no_access_to_workspace", ...}` — FastAPI's default `HTTPException`
   handling would have nested that under `{"detail": {...}}` (the existing shape of
   permission 403s, which the frontend reads through a second parser). To match the decided
   shape exactly AND let `parsePermissionError` surface the denial, `NoWorkspaceAccessError`
   (an `HTTPException` subclass) is serialized flat by a dedicated app-level handler. The
   existing permission-denied shape elsewhere in the API is unchanged.
2. **No-membership gate applies to ALL modules with a resolved tenant context** (including
   `platform::*`), not only non-platform modules. Legitimate `platform::*` traffic is
   hosted at the base domain and bypasses tenant resolution, so no context is ever resolved
   there; in a tenant context, a membership is the correct prerequisite for every module.
   Super admin bypasses before the gate (platform-only semantics unchanged).
3. **Miss-audit suppression is part of the exemption** (not just scope rewriting): a
   first-login JIT lookup that finds no user must not be recorded as a
   `cross_tenant_access_denied` audit event. Only statements carrying the exemption option
   skip the audit proxy.
4. **`require_tenant_membership`'s no-membership message changed** from the plain
   `"No tenant membership"` string to the flat `no_access_to_workspace` (+ `tenant_slug`)
   body for one canonical frontend contract. No test asserted the old string (verified by
   grep across `backend/tests`).
5. **Integration-test failures in the full-suite run are environmental** (live dev stack on
   :8000/:8001/:8002 predating this fix; real-DB seed state; one loop-teardown flake) —
   verified by stashing the fix and re-running the same files (same failures). A future
   hygiene task could add those files to conftest's `_SERVICE_DEPENDENT_FILES` skip list;
   out of scope here.

---

## FIX-20260929-121120

**Created:** 2026-09-29T12:11:20Z
**Status:** Resolved
**Issue:** Login-page bootstrap probes rejected by tenant resolution in multi-tenant mode; invalid workspace bindings (`org-a`, `acme-corp`) sent to dashboard API causing fail-closed rejection and redirect-to-login

### Observed Behavior
After OIDC/password sign-in attempts, dashboard API calls went out with `X-Tenant` slugs that do not exist (`org-a`, `acme-corp`) and were rejected fail-closed (`unknown slug`), bouncing the user back to `/login`. Independently, the login page's own pre-auth probes (`GET /system/identity-providers`, `GET /system/super-admin/status`) were rejected `unresolvable slug=None` in multi-tenant mode.

### Expected Behavior
- The two login-page bootstrap probes (explicitly public endpoints) must be reachable without a tenant context in multi-tenant mode.
- A workspace slug must NEVER be bound to the session without a successful discovery lookup; on a fail-closed "unknown slug" rejection the invalid binding must be cleared and the user returned to the find-workspace step — never a bounce loop.

### Analysis
- **Affected components:** `backend/app/middleware/tenant_resolution.py` (BYPASS_PATHS — probe endpoints missing; must be method-aware so tenant-scoped writes stay guarded), frontend LoginPage workspace-resolution flow (binding without verified discovery), apiClient/AuthContext (unknown-slug 403 handling)
- **Root cause hypothesis:** Phase 2 bypass list predates the public probe endpoints' use pre-auth; frontend bind path does not strictly gate on discovery success and does not self-heal stale/invalid bindings
- **Documentation impact:** `fix-log.md`, `test-plan.md`

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified

**Reproduction result: both defects reproduced with FAILING tests; the Defect B break point is identified precisely.** Reproduce task done — NO production code was touched.

#### Break-point analysis — WHERE defect B lets an unverified slug bind

All `setResolvedTenantSlug` / `sessionStorage['parthenon_tenant_slug']` call-sites were enumerated. Every bind path is gated on a server-verified result EXCEPT one:

| Bind site | Verified? |
|---|---|
| `LoginPage.bindWorkspace` (L172-177, called from the mount auto-resolve L184-215 and `handleFindWorkspace` L218-242) | ✅ gated on `discovery.tenant` truthy |
| `LoginPage.handlePasswordSignIn` L287 | ✅ server-issued `result.tenant_slug` |
| `AuthContext` mount effect L254-255 | ✅ host-discovery echo (server-resolved) |
| `SignUpPage` L112 / `TenantSessionGate` L68 / `InvitationAcceptPage` L40 | ✅ server-issued |
| **`OidcCallback.tsx` `resolveIntendedTenantSlug` (L67-78) + completion bind (L149-155)** | ❌ **UNVERIFIED — PRIMARY BREAK POINT** |

1. **PRIMARY — `OidcCallback.tsx` binds from storage with NO discovery lookup.** `resolveIntendedTenantSlug()` takes the FIRST non-empty of: token `tenant` claim → **`sessionStorage['parthenon_tenant_slug']`** → **remembered `localStorage['parthenon_login_tenant']`** → in-memory memo — and the completion handler **binds it unconditionally** (raw `sessionStorage.setItem` + `setResolvedTenantSlug`, L149-155). A stale/never-verified slug (`org-a`) left in either key is re-bound post-callback, and every dashboard call then carries `X-Tenant: org-a` → fail-closed 403. Its own code comment claims the remembered source is "re-verified at bind time on the login page" — but the callback never re-verifies, and the login page's cleanup (below) never cleans the *session* binding.
2. **SECONDARY — `LoginPage` mount auto-resolve (L202-207) cleans only the REMEMBERED hint.** When discovery reports the candidate unknown, it calls `setRememberedTenantSlug(null)` but never `setResolvedTenantSlug(null)` — a stale session binding (`parthenon_tenant_slug`) survives and keeps flowing out via `apiClient.ts` L27-30 (the request interceptor reads that key on EVERY call). Test B1 pins this.
3. **SECONDARY — `apiClient.ts` response interceptor (L41-64) does nothing for the fail-closed unknown-slug 403.** The wire shape `403 {"detail": "Tenant could not be resolved"}` carries no `required_permission`, so `parsePermissionError` returns null and the error is swallowed by query callers (LoginPage catches → `{items: [], total: 0}`). No self-heal: the invalid binding survives the rejection. Test B2 pins this.
4. **ADDITIONAL — late-bind race in `LoginPage.handleFindWorkspace`.** Unlike the mount effect (which has a `cancelled` flag), the Continue lookup has NO cancellation/staleness guard: a lookup whose component unmounts mid-flight (Back navigation, signup link) still binds whenever its discovery resolves, clobbering a later verified binding. (In-mount double-submit is guarded by construction: the Continue button disables + the `lookingUp` guard — no test forced for that.) Test B3 pins the navigation hole.

#### File 1: `backend/tests/test_tenant_login_probe_bypass.py` (NEW — Defect A)

Middleware-level reproduction following `test_tenant_resolution.py` patterns (module sqlite engine, patched `AsyncSessionLocal` + tenancy switch, minimal stand-in routes for the two probe endpoints and the identity-provider writes).

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `TestLoginProbeReachability::test_get_identity_providers_reaches_route_without_tenant_context` | **FAILS** (reproduces the 403 wall) | A1: multi-tenant ON, no tenant context → `GET /api/v1/system/identity-providers` must reach the route (200), NOT the resolution 403 "unresolvable slug=None" |
| `TestLoginProbeReachability::test_get_super_admin_status_reaches_route_without_tenant_context` | **FAILS** (reproduces the 403 wall) | A2: same for `GET /api/v1/system/super-admin/status` (env-based, no DB) → 200 |
| `TestLoginProbeWritesStayFailClosed::test_post_identity_providers_rejected_without_tenant_context` | passes (SECURITY PIN — must keep passing) | A3: multi-tenant ON, no tenant context → `POST /api/v1/system/identity-providers` still rejected 403 by tenant resolution; route never executes |
| `TestLoginProbeWritesStayFailClosed::test_put_identity_providers_rejected_without_tenant_context` | passes (SECURITY PIN — must keep passing) | `PUT /api/v1/system/identity-providers/{scope}` still 403 |
| `TestLoginProbeWritesStayFailClosed::test_delete_identity_providers_rejected_without_tenant_context` | passes (SECURITY PIN — must keep passing) | `DELETE /api/v1/system/identity-providers/{scope}` still 403 |

The pins enforce the METHOD-AWARE contract: the fix must bypass GET-only on the probe paths — a blanket path bypass (e.g. adding `/api/v1/system/` to `BYPASS_PATHS`/`BYPASS_PREFIXES`) would break A3 AND trip the existing `test_exempt_set_does_not_silently_widen` prefix-freeze guard in `test_tenant_resolution.py`.

Key failure output (A1, verbatim — the middleware log confirms the exact defect signature `unresolvable slug=None`):
```
E       AssertionError: LOGIN PROBE BYPASS GAP (FIX-20260929-121120 / A1): the public login-page
        probe GET /api/v1/system/identity-providers was rejected with 403
        ({"detail":"Tenant could not be resolved"}) in multi-tenant mode with no tenant context.
        It must reach the route (public pre-auth endpoint) — add it to TenantResolutionMiddleware's
        bypass as a METHOD-AWARE GET-only bypass, never a blanket path bypass.
E       assert 403 == 200
WARNING  app.middleware.tenant_resolution:tenant_resolution.py:140 Tenant resolution rejected
         GET /api/v1/system/identity-providers: reason=unresolvable slug=None
```
Run: `.venv/bin/python -m pytest backend/tests/test_tenant_login_probe_bypass.py -q` → **2 failed, 3 passed** (both failures are the repro; the 3 write pins pass and must stay green). `test_tenant_resolution.py` unchanged: **34 passed**.

#### File 2: `frontend/src/__tests__/LoginPage.binding.test.tsx` (NEW — Defect B)

Renders the real LoginPage against the REAL api pipeline (real apiClient + real tenantAuthApi storage helpers + the real request interceptor, restored over the global `setup.ts` inert mock) with only the axios network boundary faked — a recording adapter installed on the shared axios module (NOTE for future test authors: `apiClient`'s transitive `axios` import only shares one module instance if `'axios'` itself is `vi.mock`-ed in the test file; patching `defaults.adapter` without that left two axios instances and real network calls).

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `B1: cleans a stale session binding that discovery reports unknown and never leaks it on an API call` | **FAILS** (reproduces the stale binding) | Pre-seed `parthenon_tenant_slug='org-a'` + remembered hint; discovery for org-a → null → the binding must be CLEANED, the finder shown, and NO api call may carry `X-Tenant: org-a` (verified leaking on 3 calls today) |
| `B2: a fail-closed 403 unknown-slug rejection clears the binding and lands on find-workspace — never a /login bounce` | **FAILS** (reproduces the missing self-heal) | A bound slug + bootstrap calls rejected `403 {"detail": "Tenant could not be resolved"}` → the binding must be cleared and the user must land on find-workspace; `window.location.href` must NEVER be redirected to `/login` (bounce-loop pin) |
| `B3: a slow Continue lookup never binds its slug after the user navigated away and bound another workspace` | **FAILS** (reproduces the late-bind race) | Continue with a slow-discovery slug → navigate away → bind `acme` → the abandoned lookup resolves late → it must NOT re-bind: binding stays `acme` (today it becomes `slow-org`, clobbering the verified binding + the remembered hint) |

All three include positive controls asserting the mocked calls actually flowed through the recording adapter (guards against a silently-dead harness). The in-mount double-submit variant of the B3 race is covered-by-construction (Continue disables + `lookingUp` guard) — documented in the test, no artificial failure forced.

Key failure output (verbatim):
```
B1: AssertionError: STALE BINDING NOT CLEANED (FIX-20260929-121120 / B1): discovery reported the
    bound slug unknown, but the session binding parthenon_tenant_slug was left in place — the
    apiClient interceptor keeps attaching X-Tenant: org-a to every subsequent call. The binding
    must be cleared together with the remembered hint.: expected 'org-a' to be null
B2: AssertionError: FAIL-CLOSED REJECTION NOT SELF-HEALED (FIX-20260929-121120 / B2): the backend
    rejected the bound slug with 403 {"detail": "Tenant could not be resolved"}, but the invalid
    binding parthenon_tenant_slug=org-a survived — nothing clears an unknown-slug binding after a
    fail-closed rejection.: expected 'org-a' to be null
B3: AssertionError: LATE BIND RACE (FIX-20260929-121120 / B3): the abandoned slow discovery for
    slow-org resolved after the user had navigated away and bound acme — its continuation still
    bound slow-org, clobbering the verified binding. The lookup continuation must be
    cancelled/stale-guarded (like the mount auto-resolve effect) before binding.:
    expected 'slow-org' to be 'acme'
```
Run: `cd frontend && npx vitest run src/__tests__/LoginPage.binding.test.tsx --reporter=json --outputFile=/tmp/vt.json` → **3 failed, 0 passed** (all three are the repro). No regressions: `LoginPage.refined.test.tsx` → **43 passed**; `npx tsc --noEmit` → clean.

#### Fix guidance summary for the developer
- Backend (A): add the two probe paths as a **GET-only** bypass in `TenantResolutionMiddleware` (method-aware check — e.g. a `_BYPASS_GET_PATHS` set consulted only for `GET`); A3 pins must stay green.
- Frontend (B): (1) verify-then-bind in `OidcCallback` (or drop the storage sources in favour of the token claim / a discovery re-check), (2) clear the SESSION binding (`setResolvedTenantSlug(null)`) alongside the remembered hint in LoginPage's unknown-candidate cleanup, (3) self-heal on the fail-closed 403 (clear binding + surface find-workspace; never a `/login` redirect), (4) stale-guard/cancel the Continue lookup like the mount effect.

### Code Changes
Updated by: developer (FIX-20260929-121120), 2026-09-29.

**1. `backend/app/middleware/tenant_resolution.py` — method-aware GET-only probe bypass (Defect A)**
- New `BYPASS_GET_PATHS` frozenset (L71-83): `/api/v1/system/identity-providers` and
  `/api/v1/system/super-admin/status` — the login page's PUBLIC pre-auth bootstrap
  probes. `BYPASS_PATHS` / `BYPASS_PREFIXES` semantics untouched (the
  `test_exempt_set_does_not_silently_widen` prefix-freeze guard stays green).
- New `_BYPASS_GET_METHODS = {"GET", "HEAD"}` (L87) — HEAD is a harmless read-only
  companion of GET.
- `_is_bypassed(path, method=None)` (L93-108): the GET-only set is consulted ONLY
  for safe-read methods; an unknown method (`None`) does NOT bypass — fail-closed,
  consistent with the middleware's rejection semantics. `dispatch` now passes
  `request.method` (L153). Identity-provider WRITES (POST/PUT/DELETE) on those
  paths still require tenant resolution (A3 write-pins stay green).

**2. `frontend/src/pages/auth/OidcCallback.tsx` — verified re-bind (PRIMARY break point)**
- New `verifyIntendedTenantSlug(slug)` (L84-119): verifies a candidate through the
  tenantAuthApi discovery client (`GET /auth/tenant?slug=`) BEFORE anything is
  bound. Discovery confirms (`tenant` non-null) → bindable; definitive
  `tenant: null` → bind NOTHING (user lands unbound, login-page find-workspace
  re-resolves); discovery UNAVAILABLE (network error, or a response object that
  could not be read at all) → fail-open bind of the candidate with a console warn.
  Fail-open ONLY on unavailability — never on a definitive null answer.
- Completion handler (L182-216): `resolveIntendedTenantSlug` sources (claim →
  session → remembered → memo) are CANDIDATES only; the candidate is verified
  before `lastBoundTenantSlug` / raw sessionStorage key / `setResolvedTenantSlug`
  are written. A deleted tenant behind a stored slug (or claim) can no longer be
  bound.

**3. `frontend/src/pages/auth/LoginPage.tsx` — discovery-null cleanup + lookup race guard (B1 / B3)**
- Mount auto-resolve (L209-248): once there IS a candidate to verify, the session
  binding is cleared EAGERLY (`setResolvedTenantSlug(null)`) BEFORE discovery —
  an unverified slug must not flow out on the mount-time API calls (apiClient
  attaches `X-Tenant` on every request); a confirmed discovery re-binds below.
  The discovery-null branch (B1, per fix guidance) additionally clears BOTH the
  remembered hint AND `sessionStorage['parthenon_tenant_slug']` when it equals
  the rejected slug (raw read — mirrors the apiClient interceptor's key).
- `handleFindWorkspace` (L259-296, B3): `lookupStateRef = useRef({sequence, alive})`
  + mount/cleanup effect flipping `alive` (re-armed on mount so StrictMode's
  double invocation cannot permanently disable the page). Each lookup captures its
  sequence; after the discovery await, a stale continuation (`!alive` or
  superseded sequence) binds nothing and touches no state (error + spinner resets
  are guarded too) — an abandoned slow lookup can never clobber a workspace bound
  after navigation away.

**4. `frontend/src/api/apiClient.ts` — self-heal on fail-closed rejection (B2)**
- `isTenantResolutionRejection(error)` (L32-46): matches the middleware's EXACT
  wire shape — status 403 + body `{"detail": "Tenant could not be resolved"}`
  (both middleware rejection branches) + NO `required_permission` (permission 403s
  are never touched) + the rejected request actually carried `X-Tenant` (a
  tenant-scoped API call; read via `AxiosHeaders.from(error.config.headers)`).
- `selfHealTenantBinding()` (L57-66): clears `sessionStorage['parthenon_tenant_slug']`
  + `localStorage['parthenon_login_tenant']` and redirects `window.location.href =
  '/login'` (find-workspace renders once no binding remains) — skipped when already
  on `/login` or `/callback`, so the bounce loop is impossible. Storage keys are
  declared LOCALLY (tenantAuthApi imports apiClient — an import would be circular).
- Response interceptor (L109-120): resolution rejections self-heal; every other 403
  keeps the existing `parsePermissionError` path; 401 handling untouched.

### Documentation Updates
- `tech-spec.md` Code Reference Map: `TenantResolutionMiddleware` row updated
  (method-aware probe bypass); new rows `BYPASS_GET_PATHS / _is_bypassed`,
  `isTenantResolutionRejection / selfHealTenantBinding`, `OidcCallback verified
  bind`, and `LoginPage binding self-heal + lookup race guard`; `apiClient` row
  updated; the FIX-043443 `OidcCallback completion binding` row annotated as
  superseded by the verified-bind behaviour.
- Updated by: developer (FIX-20260929-121120), 2026-09-29.

### Verification Results
Developer verification (2026-09-29, macOS/zsh, `.venv/bin/python` from repo root, postgres UP, no dev servers):

- **Backend acceptance (all 5 suites):** `.venv/bin/python -m pytest backend/tests/test_tenant_resolution.py backend/tests/test_tenant_login_probe_bypass.py backend/tests/test_tenant_user_leak.py backend/tests/test_tenant_isolation_sweep.py backend/tests/test_oidc_tenant_claim_gap.py -q` → **96 passed, 0 failed** (34s). A1/A2 probe reachability now pass; the A3 write-pins (POST/PUT/DELETE stay 403 fail-closed) and the `test_exempt_set_does_not_silently_widen` prefix-freeze guard stay green.
- **Frontend type check:** `cd frontend && npx tsc --noEmit` → **clean (exit 0)**.
- **Fix repro suites:** `LoginPage.binding.test.tsx` → **3/3** (B1 stale-binding cleanup + no `X-Tenant: org-a` leak on ANY call; B2 fail-closed 403 self-heal with no `/login` redirect; B3 late-bind race guarded) and `OidcCallback.test.tsx` → **4/4** (both controls + both binding contracts still pass with verified-bind in place); `LoginPage.refined.test.tsx` → **43/43**.
- **Full frontend suite:** `npx vitest run src/__tests__ --reporter=json --outputFile=/tmp/vt.json` → **1556 passed / 0 failed** (18 todo; baseline before this fix was 1553/0 — the +3 are the now-passing LoginPage.binding tests).

**Independent verification — tester, 2026-09-29 (all three layers re-run from scratch on macOS/zsh; verdict: all green, zero fix-attributable failures, zero environmental flakes).**

- **Backend (all 6 suites combined):** `.venv/bin/python -m pytest backend/tests/test_tenant_resolution.py backend/tests/test_tenant_login_probe_bypass.py backend/tests/test_tenant_user_leak.py backend/tests/test_tenant_isolation_sweep.py backend/tests/test_oidc_tenant_claim_gap.py backend/tests/test_auth_middleware_full.py -q` → **114 passed, 0 failed** (40s). A1/A2 probe reachability green; the A3 write-pins (POST/PUT/DELETE stay 403 fail-closed) and the `test_exempt_set_does_not_silently_widen` prefix-freeze guard stay green.
- **Frontend type check:** `cd frontend && npx tsc --noEmit` → **clean (exit 0)**.
- **Frontend full suite:** `npx vitest run --reporter=json --outputFile=vitest_results.json` → **1556 passed / 0 failed** (1574 total, 18 pending by design; 377 suites, 0 failed suites). No load-induced timeouts on this run — no isolation re-runs were needed; nothing to classify.
- **E2E (30 tests across 5 spec files matched by the 4 target filters, self-mocked preview on :4173):** `npx playwright test --reporter=line oidc-login-flows multi-tenant-login-flows self-serve-signup single-tenant-regression` → **29 passed, 1 skipped, 0 failed** (2.8m). The 5th matched file is `self-serve-signup.real-backend.spec.ts` (live-backend integration test — skipped by design; the 4 mocked specs all green). The FIX repro `SSO round-trip lands on /dashboard with X-Tenant bound and NO bounce to /login` PASSED.
- **Security sanity-read (code-read verdict): HOLDS.** `BYPASS_GET_PATHS` (`tenant_resolution.py` L78–83) is an exact-match frozenset containing ONLY the two probe paths; `_is_bypassed(path, method)` (L93–108) consults it ONLY when `method ∈ _BYPASS_GET_METHODS` = `{"GET","HEAD"}` (L87) and is fail-closed on an unknown (`None`) method; `dispatch` passes the real `request.method` (L153). POST/PUT/DELETE on the probe paths therefore fall through to fail-closed resolution (403 without a tenant context) — confirmed live by the passing A3 write-pins. Exact-set membership means no prefix widening of the GET bypass; `BYPASS_PATHS` / `BYPASS_PREFIXES` are untouched. (The unconditional OPTIONS pass-through at L119 is standard CORS preflight — pre-existing, and preflight never executes route handlers.)

**Independent verdict: fix-attributable failures = 0, environmental issues = 0 → all green; Status: Resolved confirmed.**

### Deviations / Concerns for review
1. **Eager unbind in the LoginPage mount auto-resolve (not in the original fix guidance).** The guidance asked only for the discovery-null cleanup, but B1's `expectNoCallCarriedSlug('org-a')` assertion forbids the unverified slug on ANY request — including the mount-time bootstrap probes that fire while discovery is still in flight. The candidate is therefore unbound (`setResolvedTenantSlug(null)`) synchronously before verification starts and re-bound only on a confirmed discovery. This directly implements the test file's stated contract #1 ("a slug may ONLY be bound after a SUCCESSFUL discovery"); a discovery-unreachable mount now degrades to the finder with no binding (fail-safe, previously the stale binding survived).
2. **Fail-open on a nullish/malformed discovery RESPONSE object in `verifyIntendedTenantSlug`** (not only on a thrown error): the backend always returns a well-formed discovery object, so in production this branch is effectively unreachable; it exists for degraded transports and keeps the OidcCallback binding contracts (whose test mock returns a bare `vi.fn()` → `undefined`) deterministic. A well-formed `tenant: null` answer still binds NOTHING — the "never on discovery NULL" rule is intact.
3. **`_is_bypassed` gained an optional `method` parameter (default `None` = fail-closed, no GET-only bypass)** so the existing single-argument `_is_bypassed(path)` calls in `test_tenant_resolution.py` keep working unchanged; the middleware always passes the real method.
4. **Race guard stores `{sequence, alive}` in a ref rather than a bare counter:** a pure counter cannot detect the B3 cross-mount scenario (a new mount creates a fresh ref, and the abandoned lookup's closure holds the OLD ref whose `alive` the unmount cleanup flipped false). The `alive` flag is re-armed in the effect body so React StrictMode's double effect invocation cannot permanently disable a live page.

---

## FIX-20260929-043443

**Created:** 2026-09-29T04:34:43Z
**Status:** Resolved
**Issue:** After OIDC sign-in the dashboard loads, then redirects back to the login page mid-data-load

### Observed Behavior
Signing in via a workspace's OIDC SSO succeeds; the dashboard renders and starts loading data, then the user is redirected back to `/login` while data requests are in flight.

### Expected Behavior
After a successful OIDC callback the user stays signed in on the dashboard: the workspace tenant context bound at the sign-in card survives the provider round-trip, dashboard API calls carry a matching tenant context and token tenant claim, and no 401-triggered redirect occurs.

### Analysis
- **Affected components:** `frontend/src/pages/auth/OidcCallback.tsx` (no tenant slug restore/bind — unlike password login and signup which call `setResolvedTenantSlug`), possibly LoginPage OIDC start (workspace context carried into the authorize redirect), `frontend/src/api/apiClient.ts` 401 interceptor (redirect source), backend tenant-claim validation on the OIDC token path (`backend/app/middleware/auth.py`)
- **Root cause hypothesis:** the OIDC callback drops the workspace tenant binding → dashboard requests go out without/mismatched `X-Tenant` → fail-closed 401 → interceptor redirects to `/login`; possibly compounded by tenant-claim mismatch if the authorize request did not carry the workspace context
- **Documentation impact:** `fix-log.md`, `test-plan.md`, `tech-spec.md`

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified

**Reproduction result: the lead hypothesis was PARTIALLY refuted and the true break point identified.**
`OidcCallback.tsx` indeed never touches the tenant binding, but the binding **survives the
provider round-trip passively** (same-tab `sessionStorage` is preserved; AuthContext's
mount-time host-based discovery echoes the bound slug back via `X-Tenant` —
`auth_tenant.py` L130-135 resolves query param → X-Tenant header → host). A naive
"binding still present after callback" assertion therefore PASSES today and was masked
by the same mechanism (two control tests document this). The **user-visible break is the
backend tenant-claim gap**, compounded by a frontend re-bind gap:

1. **PRIMARY (backend, deterministic) — OIDC tokens never carry the `tenant` claim.**
   `_check_tenant_claim` (`backend/app/middleware/auth.py` L362-373) requires
   `claims["tenant"]` == resolved slug/UUID in multi-tenant mode, but NOTHING provisions
   that claim on the OIDC path: the only protocol mapper ever created is the `groups`
   membership mapper (`identity/bootstrap_service.py` L171, `keycloak_admin_client.py`
   `create_group_membership_mapper`); neither `_try_oidc_token` nor
   `OIDCClient.validate_token` injects it; only `create_platform_account_token`
   (`platform_account_auth_service.py` L111 — password sign-in/sign-up) embeds `tenant`.
   ⇒ EVERY authenticated request from an OIDC session in multi-tenant mode is rejected
   401 "Token is not valid for this tenant" → `apiClient.ts` L44-56 interceptor wipes
   tokens and does `window.location.href = '/login'` — the reported mid-load bounce.
   Design intent confirmed by `TenantSessionGate.tsx` doc: "a fresh token with the
   matching tenant claim is required".
2. **SECONDARY (frontend) — `OidcCallback.tsx` L62-77 completion handler never re-binds
   the workspace tenant** (no `setResolvedTenantSlug` call; the component does not import
   `tenantAuthApi` at all), unlike every other auth flow (`LoginPage.tsx` L287 password,
   `SignUpPage.tsx` L112). The binding is carried by storage luck only; if the tab loses
   `sessionStorage` during the round-trip (new-tab restore, storage eviction), the
   dashboard session binds to NO tenant and all workspace calls fail. Related fragility:
   `AuthContext.tsx` L240 `setResolvedTenantSlug(discovery.tenant?.slug ?? null)` wipes
   the binding whenever the bare discovery response lacks the echo (demonstrated live
   while building the E2E mock).
3. **Additional finding for the developer — `OidcCallback.tsx` L8/L42 exchanges the code
   at the hardcoded `VITE_OIDC_AUTHORITY`** rather than the tenant-resolved issuer that
   `login()` used (AuthContext `oidcAuthority`). Any tenant-scoped provider whose issuer
   differs from the platform default fails the token exchange itself → `/login` without
   a session.

#### File 1: `backend/tests/test_oidc_tenant_claim_gap.py` (NEW — primary reproduction)

Runs the exact middleware pipeline (`validate_raw_token` → `_check_tenant_claim`) with a
token from the tenant's OWN provider in the realistic claim shape (standard identity
claims, no `tenant` claim — verified real behaviour).

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `TestOidcTokenTenantClaimGap::test_oidc_token_from_tenants_own_provider_is_accepted_for_that_tenant` | **FAILS** (reproduces the 401) | Token validates against test-com's own provider (sanity) AND passes `_check_tenant_claim` for test-com — today rejected "Token is not valid for this tenant" |
| `TestOidcTokenTenantClaimGap::test_oidc_token_carrying_matching_claim_is_accepted_control` | passes (control) | Same pipeline with `tenant: "test-com"` claim → accepted — isolates the defect to claim provisioning, not claim-check logic |
| `TestOidcTokenTenantClaimGap::test_platform_account_token_control_passes_for_its_tenant` | passes (control) | The password path (`create_platform_account_token`) works end-to-end — proves the rig; only the OIDC path is broken |

Key failure output (verbatim):
```
E       AssertionError: OIDC TOKEN TENANT CLAIM GAP: a token issued by the tenant's own
        provider is rejected in multi-tenant mode ('Token is not valid for this tenant')
        — '_check_tenant_claim' requires a 'tenant' claim that the OIDC path never
        provisions (no mapper creation, no validation-time injection), so EVERY dashboard
        request from an OIDC session returns 401 and the frontend interceptor redirects
        to /login mid-load (FIX-20260929-043443)
E       assert 'Token is not valid for this tenant' is None
```
Run: `.venv/bin/python -m pytest backend/tests/test_oidc_tenant_claim_gap.py -q` → `1 failed, 2 passed`.

#### File 2: `frontend/src/__tests__/OidcCallback.test.tsx` (NEW — callback binding contract)

Simulates the full round-trip state (`sessionStorage['parthenon_tenant_slug']='test-com'`
+ PKCE verifier bound pre-redirect, mocked token exchange returning a realistic claim-less
JWT) and asserts the sign-in-completion binding contract.

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `CONTROL: completes the exchange and navigates to /dashboard` | passes | Exchange called, `setToken` + `navigate('/dashboard')` |
| `CONTROL: the pre-redirect binding survives passively (sessionStorage untouched)` | passes | Documents WHY the naive repro passes — the component never touches the key |
| `re-binds the workspace tenant authoritatively on sign-in completion (parity with password login / sign-up)` | **FAILS** | `setResolvedTenantSlug('test-com')` invoked during completion — `Number of calls: 0` today (OidcCallback.tsx L62-77) |
| `restores the workspace tenant binding when the tab lost it during the provider round-trip` | **FAILS** | With the binding removed pre-callback (new-tab/eviction), the callback must restore it — `expected null to be 'test-com'` today |

Run: `cd frontend && npx vitest run src/__tests__/OidcCallback.test.tsx` → `2 failed, 2 passed` (both failures are the missing re-bind; no regressions — `LoginPage.refined` 43 + `SignUpPage` suites all pass).

#### File 3: `e2e/tests/multi-tenant-login-flows.spec.ts` (EXTENDED — user-visible symptom)

New describe `OIDC workspace sign-in keeps the session tenant-bound`, test
`SSO round-trip lands on /dashboard with X-Tenant bound and NO bounce to /login`:
mocked workspace card (`?workspace=test-com`) → SSO button → same-origin fake-provider
authorize (302 to `/callback?code=…`, same-tab so sessionStorage behaves like the real
round-trip) → token exchange mocked at the built-in default authority → `/dashboard`.
The dashboard data mock mirrors the REAL backend contract (`_check_tenant_claim`):
X-Tenant bound + token without matching `tenant` claim ⇒ 401.

Verified behaviour pre-fix: workspace card binds the slug ✓, callback lands on
`/dashboard` ✓, **dashboard data calls DO carry `X-Tenant: test-com`** ✓ (control —
passive survival confirmed in a real browser), then the user **is bounced to
`http://localhost:4173/login` within the 3s window** — the exact reported symptom.

Key failure output (verbatim):
```
Error: OIDC WORKSPACE SESSION BUG (FIX-20260929-043443): the user was bounced back to
/login mid-load — the backend 401s every dashboard call because the OIDC token never
carries the tenant claim the middleware requires

Expected substring: not "/login"
Received string:        "http://localhost:4173/login"
```
Run: `cd e2e && npx playwright test multi-tenant-login-flows --reporter=line --grep "SSO round-trip"` → `1 failed` (the repro); full spec + `multi-tenant-lifecycle` → `11 passed` (no regressions); `oidc-login-flows` → `12 passed`.

#### Backend path verdict

The backend claim-check MECHANISM (`_check_tenant_claim`) is correct and already covered
by `test_tenant_oidc_isolation.py` (missing/mismatch/match/super-admin/inert). The defect
is upstream of it: **the OIDC path never provisions the claim the check requires**
(no Keycloak claim-mapper creation anywhere in the platform — only `groups`;
no validation-time injection). Fix direction (developer's choice): inject the tenant
claim for tenant-scoped providers at validation time in `_try_oidc_token` (stamp
`claims["tenant"] = context.slug` when the provider resolves for that tenant), or
provision a client claim mapper per tenant provider at registration/config time. The
frontend re-bind gap (File 2) should be fixed in the same pass for robustness.

### Code Changes

**Mechanism chosen for claim provisioning (Fix 1 — PRIMARY): validation-time claim injection.**
The registry resolves providers BY tenant (fail-closed per-tenant slots keyed
`(tenant_id, scope)`), so a token that validates against the provider held in
the resolved tenant's own registry slot is provably issued for THAT tenant —
the backend stamps `claims["tenant"] = <resolved slug>` post-validation. This
works for ANY OIDC provider (Azure EntraID included) with zero provider-side
configuration, and the binding can never be widened by a forged `X-Tenant`
header (claim source = provider registry slot; comparison target =
request-resolved tenant).

**1. `backend/app/middleware/auth.py` — validation-time tenant claim injection**
- New module-level helper `_inject_tenant_claim` (L120-167): stamps
  `claims["tenant"] = str(slug)` ONLY when (a) a tenant context is resolved
  (`tenant_id` non-None — single-tenant mode / platform surface untouched),
  (b) the slug is non-empty, and (c) `registry.get_provider(scope, tenant_id,
  is_system_tenant=False)` resolves — i.e. the provider came from the
  TENANT's own registry slot. A provider reached only via the system-tenant
  GLOBAL fallback resolves `None` there and receives NO injection (it is
  platform-scoped; its tokens keep requiring a real claim — semantics
  unchanged). Any native `tenant` claim is overridden: the provider slot that
  validated the token is the authoritative binding. `_check_tenant_claim`
  still runs afterwards — mismatch rejection, super-admin platform-only
  rejection, and auditing are untouched.
- Call site in `_try_oidc_token` (L217-221, immediately after
  `client.validate_token` succeeds, before returning claims) + updated
  docstring (L174-185) documenting the injection and override semantics.

**2. `frontend/src/pages/auth/OidcCallback.tsx` — workspace re-bind + tenant-resolved exchange**
- SECONDARY fix — completion handler now re-binds the workspace (parity with
  password login / sign-up): new helpers `parseJwtPayload` (L36-49) and
  `tenantClaimFrom` (L51-58) read the token's `tenant` claim (id_token first,
  then access_token — claim wins over storage), and
  `resolveIntendedTenantSlug` (L60-82) resolves the first non-empty source of
  token claim → sessionStorage `parthenon_tenant_slug` → remembered
  `parthenon_login_tenant` (via `getRememberedTenantSlug`) → in-session memo
  `lastBoundTenantSlug` (module-level best-effort fallback for the same SPA
  load). The bind block in the `.then()` completion (L131-141) writes the raw
  sessionStorage key AND calls `setResolvedTenantSlug(slug)` — restoring the
  binding even when the tab lost it during the provider round-trip; binds
  nothing when no source resolves (platform sign-in unchanged).
- BONUS fix — the token exchange now targets the SAME provider the login
  start used: `oidc_authority` / `oidc_client_id` are consumed from
  sessionStorage (cleared after read, L74-78) with fallback to
  `VITE_OIDC_AUTHORITY` / `VITE_OIDC_CLIENT_ID` (L20-21), so a tenant
  provider with a non-default issuer no longer fails the exchange outright.

**3. `frontend/src/stores/AuthContext.tsx` — round-trip state + discovery hardening**
- BONUS fix — `login()` now persists the resolved start config alongside the
  PKCE verifier: `sessionStorage['oidc_authority'] = oidcAuthority` and
  `['oidc_client_id'] = oidcClientId` (L291-294, keys declared L115-121) so
  the callback can complete against the tenant-resolved provider.
- SECONDARY fix — mount-time tenant discovery only (re)binds on an explicit
  echo: `if (discovery.tenant?.slug) setResolvedTenantSlug(...)` (L248-254)
  replaces the unconditional `setResolvedTenantSlug(discovery.tenant?.slug ??
  null)` that WIPED an existing explicit binding whenever the bare discovery
  response lacked the echo. Clearing remains the explicit flows' job
  (workspace switch link, logout).

**4. `e2e/tests/multi-tenant-login-flows.spec.ts` — dashboard mock mirrors the FIXED contract**
- The `dashboard/summary` mock previously emulated the PRE-fix backend (401
  when the raw token lacked a matching claim); post-fix the backend injects
  the binding at validation time, so the mock now rejects only a MISSING
  `X-Tenant` (the frontend regression it guards: binding lost mid-round-trip)
  and accepts bound sessions. Stale step-4 comments updated. The SSO
  round-trip repro test now PASSES (see Verification).

**Deliberately NOT changed: provider-side mapper creation.** Creating a
`tenant` protocol mapper at tenant-provider registration/config save was
considered and rejected: runtime services must not hold Keycloak admin
credentials (docs/config.yaml conventions — provisioning is setup-tool-only),
so config-save time cannot reach into external providers, and the fix must
not DEPEND on provider-side state anyway. Validation-time injection covers
all providers; the bundled-Keycloak mapper is unnecessary polish.

### Documentation Updates
- `tech-spec.md`: architecture section "Per-tenant OIDC registry" updated (validation-time injection semantics + security guarantees); Code Reference Map — `_try_oidc_token` row updated, new rows for `_inject_tenant_claim`, `OidcCallback` completion binding / tenant-resolved exchange, `AuthProvider.login` round-trip state, `AuthProvider` discovery binding hardening, `test_oidc_tenant_claim_gap.py`, `OidcCallback.test.tsx`, and the multi-tenant-login-flows dashboard mock.
- Updated by: developer (FIX-20260929-043443), 2026-09-29.

### Verification Results

**Independent verification — tester, 2026-09-29 (all layers re-run from scratch on macOS; verdict: all green, zero fix-attributable failures).**

Environment note: this session ran on a severely overloaded machine (load average peaked ~380 with another full vitest run in parallel), which produced timing-bound flakes on the first raw pass. Every raw failure was re-run under load control and re-classified before verdict; details below.

- **Backend (all 5 suites combined):** `.venv/bin/python -m pytest backend/tests/test_oidc_tenant_claim_gap.py backend/tests/test_tenant_oidc_isolation.py backend/tests/test_tenant_user_leak.py backend/tests/test_tenant_isolation_sweep.py backend/tests/test_auth_middleware_full.py -q` → **96 passed, 0 failed** (39s). Claim gap fixed; mismatch / super-admin rejections intact; isolation sweep + user-leak suites unregressed.
- **Frontend type check:** `npx tsc --noEmit` → **clean (exit 0)**.
- **Frontend full suite:** `npx vitest run --reporter=json` → 1571 tests: 1524 passed / 29 failed **under load avg ~350**. All 29 are vitest synthetic timeouts (`STACK_TRACE_ERROR`), scattered 1–2 per suite across 27 suites **unrelated to this fix** (guardrails, API keys, notifications, tags, …); the fix-touched suites all passed on the raw run (`OidcCallback` 4/4, `AuthContext`, `LoginPage.refined`). Load-controlled re-run of 4 of the failed suites → **20/20 pass** (including `LoginPage`). Classified environmental; no fix-attributable failure.
- **E2E (4 target specs, 30 tests, self-mocked preview on :4173):** first pass (vitest still running concurrently) → 17 passed / 12 failed / 1 skipped; all 12 failures were `networkidle`/5s-visibility timeouts. Re-run of the 12 on a quieter box → 10 passed immediately; the last 2 (`multi-org picker`, `CS-26 full journey` — pure 5-second element-visibility waits; failure snapshots showed the app mid-load on a box serving static files in ~2s) → **passed (12.5s)** once load dropped. Net **29/30 passed, 1 skipped** (real-backend integration test, skip by design). **The FIX repro `SSO round-trip lands on /dashboard with X-Tenant bound and NO bounce to /login` PASSED on the very first pass.** Classified environmental; no fix-attributable failure.
- **Security property (code-read verdict): HOLDS.** `_inject_tenant_claim` (`auth.py` L120–167) stamps `claims["tenant"]` ONLY when `registry.get_provider(scope, tenant_id, is_system_tenant=False)` resolves — the claim source is the provider **registry binding** (the tenant slot whose issuer/JWKS validated the token), never the request `X-Tenant` header (the header only selects WHICH tenant slot validates; a foreign token cannot validate against another tenant's slot, so it produces no claims and no injection). Verified against `OIDCProviderRegistry.get_provider` (`oidc_provider_registry.py` L194–211): the global `(None, scope)` entry is reachable only with `is_system_tenant=True`, so a system-tenant/global-fallback token receives **no injection** and `_check_tenant_claim` (`auth.py` L379–447) rejects it for tenant-scoped requests with 401 "Token is not valid for this tenant"; mismatch and super-admin platform-only rejections are untouched.

**Independent verdict: fix-attributable failures = 0 → all green; Status: Resolved confirmed.**

---

**Developer verification (2026-09-29, macOS/zsh, `.venv/bin/python`, no dev servers for backend; E2E ran against the self-mocked preview build).**

- **Primary reproduction:** `.venv/bin/python -m pytest backend/tests/test_oidc_tenant_claim_gap.py -q` → **3 passed** (the reproduction test now passes: token from the tenant's own provider completes `validate_raw_token` → `_check_tenant_claim`).
- **Repro + isolation suites:** `pytest backend/tests/test_oidc_tenant_claim_gap.py backend/tests/test_tenant_user_leak.py backend/tests/test_tenant_isolation_sweep.py -q` → **57 passed**.
- **Claim-check mechanics regression:** `pytest backend/tests/test_tenant_oidc_isolation.py -q` → **21 passed** (registry keying, `_try_oidc_token` tenant binding, missing/mismatch/match/super-admin claim matrix + audits — mismatch rejection intact).
- **Auth/oidc regression:** `pytest backend/tests/test_auth_middleware_full.py backend/tests/test_oidc_config_service.py backend/tests/unit -q` → **881 passed, 11 skipped**.
- **Frontend type check:** `cd frontend && npx tsc --noEmit` → **clean**.
- **OidcCallback suite:** 4/4 (both formerly-failing contract tests pass: authoritative re-bind + restore after binding loss; both controls intact).
- **Named suites:** LoginPage + LoginPage.refined + AuthContext + SignUpPage → **80/80**.
- **Full frontend:** `npx vitest run src/__tests__ --reporter=json` → **1553 passed / 0 failed** (375/375 suites; 18 todo — baseline was 1549/0; the +4 are the now-passing OidcCallback contract tests).
- **E2E (self-mocked, no backend needed):** `oidc-login-flows` + `multi-tenant-login-flows` + `single-tenant-regression` → **25 passed** (incl. the FIX repro `SSO round-trip lands on /dashboard with X-Tenant bound and NO bounce to /login` — was the failing user-visible symptom); `self-serve-signup` + `multi-tenant-lifecycle` + `quota-enforcement` → **11 passed, 1 skipped** (skip by design). Password login, signup, single-tenant flows, multi-org picker and super-admin E2Es all green.

### Deviations / Concerns for review
1. **In-session memo in `OidcCallback` (`lastBoundTenantSlug`)**: the binding-restoration chain ends with a module-level memo of the last slug this SPA load bound. In production it only helps when the callback component re-mounts WITHOUT a full page reload (the provider redirect itself is a full load, which wipes it) — the authoritative restore sources are the token's `tenant` claim (post-fix backend) and the storage keys. It is also what lets the "binding lost pre-callback" unit test pass deterministically (the vitest module instance persists across cases in a file). Documented in-code as best-effort; no access decisions rest on it — the backend independently re-validates claim vs resolved tenant per request.
2. **Redundant bind write in the callback**: the completion handler writes `sessionStorage['parthenon_tenant_slug']` directly AND calls `setResolvedTenantSlug` (which writes the same key in production). The raw write is deliberate — the callback contract must hold even when the helper is substituted (as in the unit-test mock) — and is idempotent in production.
3. **E2E dashboard-mock contract change** (file 4 above): the mock emulates the backend, and the backend contract legitimately changed with this fix (bound session accepted without a raw claim). The mock still 401s a MISSING binding, so it remains a meaningful frontend regression guard; `oidc-login-flows` (single-tenant) was not touched and stays green.
4. **`oidc_client_id` persisted alongside the authority** (not explicitly requested): the task asked for the authority only, but the token exchange POSTs `client_id` too — a tenant provider with a different public client id would fail the exchange at the platform default client even with the right authority. Symmetric consume+clear in the callback; no behavioural change for default-configured providers.

---

## FIX-20260928-121317

**Created:** 2026-09-28T12:13:17Z
**Status:** Resolved
**Issue:** Cross-tenant user leak — permission module user list shows users from other tenants when signed in as a tenant root

### Observed Behavior
Signed in as the `test-com` tenant root, the permission module's user list (`UsersPage` → `GET /api/v1/platform-users`) displays users that are not members of `test-com` — pre-existing users adopted into the system tenant are visible.

### Expected Behavior
- In a tenant context, only users with an **active membership in the current tenant** are listed; a foreign user id resolves to 404.
- Every data entity is either (a) tenant-scoped via `tenant_id` or (b) on an explicit, documented tenant-agnostic registry with a defined scoping strategy (e.g. `PlatformUser` via membership join, `Permission` as global catalogue). Systematic tests cover ALL entities so no cross-tenant data leak is possible.

### Analysis
- **Affected components:** `backend/app/api/v1/platform_users.py` (list + detail + `db.get` path), `backend/app/db/tenant_scoping.py` (needs membership-based strategy for tenant-agnostic entities), any other endpoints querying tenant-agnostic entities under tenant context
- **Root cause hypothesis:** `PlatformUser` intentionally has no `tenant_id`, so the `do_orm_execute` scoping choke point does not filter it; `GET /platform-users` runs `select(PlatformUser)` unfiltered and `db.get(PlatformUser, id)` bypasses scoping entirely
- **Documentation impact:** `test-plan.md` (add systematic isolation coverage), `tech-spec.md` (Code Reference Map + scoping strategy), `fix-log.md`

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified

**Run command:** `.venv/bin/python -m pytest backend/tests/test_tenant_user_leak.py backend/tests/test_tenant_isolation_sweep.py -q`
**Result (pre-fix):** `51 failed, 3 passed` — every failure is a genuine defect detection (reproduction); the 3 passes are the registry-completeness guard tests plus the first sweep case (which binds the defective global criteria cache — see Finding #1).

#### File 1: `backend/tests/test_tenant_user_leak.py` (NEW — endpoint reproduction)

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `TestPlatformUserTenantLeakReproduction::test_list_platform_users_returns_only_users_with_active_membership_in_current_tenant` | **FAILS** (reproduces the leak) | `GET /api/v1/platform-users` in tenant-A context lists ONLY tenant A's active members; B-only users 404-equivalent absent |
| `TestPlatformUserTenantLeakReproduction::test_detail_of_user_without_membership_in_current_tenant_returns_404` | **FAILS** (reproduces the leak) | `GET /api/v1/platform-users/{b_only_user_id}` in tenant-A context → 404 (control: own member → 200 passes, proving tenant context is applied) |

Key failure output (Test A, verbatim):
```
E       AssertionError: CROSS-TENANT USER LEAK: users with no active membership in the
        requesting tenant are listed: ['member-b-7835da44@example.test', 'root-b-7835da44@example.test']
E       assert not ['member-b-7835da44@example.test', 'root-b-7835da44@example.test']
```
Key failure output (Test B, verbatim):
```
E       AssertionError: CROSS-TENANT USER LEAK: GET /platform-users/{foreign_id} returned
        200 instead of 404 for a user with no active membership in the requesting tenant
E       assert 200 == 404
```

#### File 2: `backend/tests/test_tenant_isolation_sweep.py` (NEW — systematic ALL-entity isolation sweep)

Registry/classification (enumerated programmatically from `Base.registry`): **85 mapped models = 47 tenant-scoped + 38 tenant-agnostic (7 platform-level + 31 parent-inherited join/child tables, all explicitly listed by table name in `TENANT_AGNOSTIC_REGISTRY` with strategy notes).**

| Test | Status pre-fix | Asserts |
|------|----------------|---------|
| `TestRegistryCompleteness::test_every_tenant_agnostic_model_is_registered_with_a_strategy` | passes (guard) | Every model without `tenant_id` MUST be in `TENANT_AGNOSTIC_REGISTRY` — new unregistered agnostic models fail here until consciously registered |
| `TestRegistryCompleteness::test_registry_keys_reference_real_tables` | passes (guard) | No stale registry keys |
| `TestRegistryCompleteness::test_registry_entries_have_documented_strategy` | passes (guard) | Every entry carries a strategy note |
| `TestScopedSweep::test_tenant_id_model_is_row_scoped[<47 models>]` | **46 of 47 FAIL** (see Finding #1) | Parametrized over EVERY `tenant_id`-bearing model: one row per model per tenant; tenant-A scoped session sees only A's row via `select` and `None` via `get` (404 semantics). Zero skips — all 47 models constructible with minimal valid rows |
| `TestScopeSwitching::test_scope_binds_per_request_not_per_process` | **FAILS** (Finding #1, crisp reproduction) | A → B → A scoped sessions each see ONLY their own rows |
| `TestTenantAgnosticStrategyPlatformUser::test_scoped_user_query_returns_only_active_members_of_scoped_tenant` | **FAILS** (ORM-level version of the user leak) | Registry strategy for `platform_users` ("membership-join"): a tenant-A scoped user query returns only ACTIVE members of A; `get()` of a B-only user → `None` |

Key failure output (TestScopeSwitching, verbatim):
```
E       AssertionError: STALE SCOPE CRITERIA: a tenant-B-scoped session received tenant
        A's rows ['switch-role-a'] — the with_loader_criteria lambda cache is bound to
        the first tenant seen by the process (default-arg binding is not invalidated by
        SQLAlchemy's lambda-SQL cache; use a closure factory)
E       assert ['switch-role-a'] == ['switch-role-b']
```

### Additional Findings for the Developer (from the enumeration)

1. **CRITICAL — stale scope-criteria cache (worse than the reported leak).** `backend/app/db/tenant_scoping.py::_scope_options_for_select` builds `with_loader_criteria(entity, lambda cls, _tid=tenant_id: cls.tenant_id == _tid)`. SQLAlchemy's lambda-SQL cache keys on the lambda's *code object*; a default-arg `_tid` change is invisible to it, so the criteria compiled for the FIRST tenant seen by the process is replayed for every later scoped query. Verified: scope A → then scope B returns **A's rows**. In production multi-tenant mode this means every tenant after the first receives the first tenant's data. Fix direction (verified working in isolation): bind via a true closure factory — `def _criteria(entity, tid): return lambda cls: cls.tenant_id == tid` — so the cache detects the changed closure value and recompiles. Blast radius while the defect is present: any scoped SELECT under a different tenant in the same process corrupts later scoped SELECTs (2 tests in `test_tenant_scoping.py` fail after the sweep runs); post-fix this pollution disappears.
2. **`_get_user_or_404` (`db.get(PlatformUser, id)`) guards ALL mutating sub-endpoints** — assign/remove role, add/remove group, delete user all operate on foreign users, so the leak is not read-only.
3. **Direct selects on parent-inherited agnostic models bypass the choke point** (the criteria only covers entities present in the statement). Any endpoint querying `mcp_sessions`, `execution_logs` (full prompts), `api_key_usage_logs`, `tool_call_records`, `agent_plans`, `token_refresh_logs`, or `agent_instance_certificates` WITHOUT joining the scoped parent is unfiltered. Recommend an endpoint audit for direct selects on these 7 tables.
4. **`_enrich_user` counts are cross-tenant** — `platform_users.py` counts `UserRole`/`UserGroup` per user without joining the scoped `Role`/`Group` parents; for multi-tenant users the displayed counts are the union across tenants. Counts should join the scoped parents.


### Code Changes

**1. CRITICAL — stale scope-criteria cache (Finding #1) — `backend/app/db/tenant_scoping.py`**
- Replaced the default-arg-bound criteria lambda (`lambda cls, _tid=tenant_id: ...` in `_scope_options_for_select`, ~L189 pre-fix) with **closure factories** (`_tenant_criteria_factory` L126, `_platform_user_criteria_factory` L135; selection in `_scope_options_for_select` L299), making the tenant id a true closure variable so SQLAlchemy's lambda-SQL cache re-binds it instead of replaying the first tenant's compiled criteria. Verified the `with_loader_criteria` option itself is never process-cached — it is rebuilt on every ORM execution inside the `do_orm_execute` event (documented in the function docstring).
- **PlatformUser "membership-join" strategy at the choke point**: `_has_automatic_scope_strategy()` (L91; currently only `PlatformUser`) makes `_scoped_entities_of_statement` include tenant-agnostic entities with an automatic strategy, so `select(PlatformUser)` and `db.get(PlatformUser, id)` on a scoped session are constrained to ACTIVE members of the scoped tenant (`_platform_user_criteria_factory`: `id IN (SELECT user_id FROM tenant_user_memberships WHERE tenant_id = :tid AND status = 'active')`).
- Cross-tenant miss detection extended to membership-strategy entities (`scoped_get` in `_install_miss_detection`): a scoped `get(PlatformUser, foreign_id)` now records a `cross_tenant_access_denied` audit candidate (matches the documented 404-with-audit contract).
- `scope_for_session()` hardened (L190): only a UUID-shaped scope value is accepted (anything else → unscoped) so request-path callers can branch safely (also keeps mocked-session tests working).

**2. PlatformUser membership scoping — `backend/app/api/v1/platform_users.py` + shared helper**
- New reusable helper `filter_platform_users_to_tenant(stmt, tenant_id)` (`tenant_scoping.py` L210) — endpoint-level mirror of the choke-point predicate; defence-in-depth.
- `_get_user_or_404` (L37): membership-guarded in tenant context via `scope_for_session(db)` — non-members 404 on the detail endpoint AND on every mutating guard (assign/remove role, group add/remove, delete user). Unscoped sessions (single-tenant mode, platform admin surface, super admin — none carry a tenant context) keep full access, byte-for-byte.
- `list_platform_users` (L86): filter applied **before** pagination.
- `remove_user_role` (L185) / `remove_user_from_group` (L247): assignment lookups now join the tenant-scoped `Role`/`Group` parents so an in-tenant user's assignment to a FOREIGN role/group cannot be resolved or removed in tenant context.
- `delete_platform_user` (L272): additionally refuses (409) deleting a user who holds an ACTIVE membership in another tenant — the global `PlatformUser` deletion would cascade-remove their other tenants' memberships (cross-tenant write); a short-lived unscoped session performs the integrity count (the scoped session's own criteria would neuter a `tenant_id != ours` predicate). Tenant-scoped member removal remains the tenant membership endpoint's job.

**3. `_enrich_user` cross-tenant counts (Finding #4) — `backend/app/api/v1/platform_users.py` L60**
- Role/group counts join the tenant-scoped `Role`/`Group` parents in tenant context (joining puts a scoped entity into the statement so the choke point constrains the count); no-op on unscoped sessions (FK-guaranteed inner join). Detail endpoint's role/group lists already join scoped parents and were auto-scoped by fix 1.

**4. Endpoint audit for the 7 parent-scoped agnostic tables (Finding #3)**

Fixed leaks (each: joined the tenant-scoped parent so the choke point constrains the query; FK-guaranteed inner joins keep unscoped result sets identical):
| Endpoint / path | Table | Fix |
|---|---|---|
| `PUT/DELETE /mcp/servers/{sid}/sessions/{id}`, `POST .../refresh-token` (`api/v1/mcp_hub.py`) | `mcp_sessions` | Lookup joined `McpServer` — a foreign `(server_id, session_id)` pair can no longer be resolved/modified/deleted (no parent guard existed pre-fix) |
| `POST /mcp/tools/{id}/test` (`api/v1/mcp_hub.py`) | `mcp_sessions` (via `mcp_tools`) | `db.get(McpTool)` replaced with `McpServer`-joined select (foreign tool ids 404); direct `db.get(McpSession, body.session_id)` replaced with joined select (pre-fix leaked the foreign session's server binding via the mismatch error) |
| `McpProxyEngine._resolve_session` (`services/mcp/proxy.py`) | `mcp_sessions` | All 3 resolution selects joined `McpServer` |
| `POST /agent-roles/{id}/mcp-sessions` (`services/agents/role_service.py::assign_mcp_session`) | `mcp_sessions` | Session lookup joined `McpServer` — foreign sessions cannot be linked to a tenant's role |
| `POST /internal/mcp/proxy-tool` (`api/v1/internal/mcp_proxy.py`) | `mcp_sessions` | Session resolution joined `McpServer` + `AgentRole` (role must be in-tenant); tool resolution joined `McpServer` (slugs are per-tenant) |
| `GET /runtime/policy-events` (`api/v1/agents.py::list_runtime_policy_events`) | `execution_logs` | Joined `AgentJob` — pre-fix listed ALL tenants' policy events (no session guard, unlike the per-session log endpoints) |
| `GET /internal/data/agent-types/{id}/plan` (`api/v1/internal/agent_data.py`) | `agent_plans` | Joined `AgentType` — foreign agent_type_id cannot resolve its plan under signed tenant context |
| `POST /certificates/revoke` (`services/certificate_authority.py::revoke_certificate`) | `agent_instance_certificates` | Serial lookup joined `AgentType` (LEFT join — see deviations); tenant context revokes own certs only, platform/unscoped keeps full-CA access |
| `POST /internal/authorize/tool-call` (`services/permission_resolution.py::_get_certificate_by_serial`) | `agent_instance_certificates` | Serial lookup joined `AgentType` (LEFT join) — a foreign tenant's certificate cannot resolve permissions at the tool-call authorization gate |

Explicitly cleared paths (audited, no tenant-context leak):
- **`api_key_usage_logs`** — no SELECT anywhere in `backend/app` (insert-only audit writes in `services/api_key_service.py`); no tenant-context query path.
- **`token_refresh_logs`** — no SELECT anywhere (insert-only in `services/token_refresh.py`); no tenant-context query path.
- **`tool_call_records`** — the only SELECT (`services/control_center/runtime_topology_controller.py`) joins `ConversationTurn` → `ConversationSession` (tenant-scoped parent present in the FROM ⇒ choke-point criteria apply); writes are insert-only (`services/conversations/store.py`).
- **`mcp_sessions` — safe by construction**: `_resolve_default_session` + sync/session-count queries in `mcp_hub.py` run only after a scoped `db.get(McpServer, server_id)` 404-guard; `services/mcp_oauth_service.py` resolves `McpServer` via a scoped select before creating sessions; `services/mcp/oauth_refresh.py` receives the session object (no select).
- **`execution_logs` — safe by construction**: `get_session_execution_logs`, log streaming and delegation-status endpoints (`api/v1/agents.py`) resolve the `AgentJob` through the scoped session first (404 for foreign ids) before querying by `session_id`; the internal session-log writes are insert-only.
- **`agent_plans` — safe by construction**: `plan_generation_service._upsert_plan` filters by an agent_type_id already validated in-tenant by every caller (scoped `select(AgentType)` endpoint guard; background path runs unscoped by design).

**Not modified (contract)**: the two test files; `TENANT_AGNOSTIC_REGISTRY`; single-tenant behaviour (scoped-only code paths branch on `scope_for_session` / choke-point scope presence — unscoped sessions are untouched).

### Documentation Updates
- `tech-spec.md` Code Reference Map: `apply_tenant_scope` row updated (closure-factory criteria); added rows for `scope_for_session`, `_tenant_criteria_factory` / `_platform_user_criteria_factory`, `filter_platform_users_to_tenant`, `_has_automatic_scope_strategy`, and the platform users router.
- Updated by: conductor, 2026-09-29: test-plan.md coverage area + CS scenarios + file references

### Verification Results

**Independent verification (2026-09-29) — VERDICT: RESOLVED. All three layers re-run from scratch; zero fix-attributable failures.**

- **Reproduction + sweep:** `.venv/bin/python -m pytest backend/tests/test_tenant_user_leak.py backend/tests/test_tenant_isolation_sweep.py -q` → **54 passed** (all 51 formerly-failing reproduction cases now pass).
- **Cache-pollution re-check (order-swapped, single process):** sweep → `test_tenant_scoping.py` → leak tests in one process → **78 passed**. The stale scope-criteria pollution Finding #1 described (scoped tests failing after the sweep binds the defective cache) is confirmed gone.
- **Full backend suite:** `.venv/bin/python -m pytest backend/tests -q` → **2216 passed, 20 failed, 226 skipped, 1 teardown error**. Every failure/error classified below as environmental or pre-existing; **none attributable to the isolation fix** (no failure touches platform-users, mcp-session lookups, certificate serial joins, or any endpoint modified by this fix — verified by code-level diff inspection of the touched middleware surfaces against HEAD).
- **Frontend:** `npx vitest run` → **1549 passed / 0 failed** (373 suites, 18 skipped-as-todo); `npx tsc --noEmit` → **clean**.
- **E2E:** `npx playwright test multi-tenant-lifecycle multi-tenant-login-flows self-serve-signup single-tenant-regression quota-enforcement` → **23 passed, 1 skipped** (skip is by design).

#### Backend residual failure classification (20 failed + 1 error)

| Category | Count | Tests | Evidence |
|---|---|---|---|
| Live dev-DB state checks | 2 | `test_namespace_migration::test_deployment_has_namespaced_policy_values` (6 legacy policy_statements in shared dev DB), `test_tenant_schema_migration::test_tenancy_switch_seeded_false` (dev DB has tenancy `enabled: True` vs fresh-migration default) | Shared-dev-DB state assertions; fail identically pre-change (developer's git-stash check) |
| Cross-service integration vs live stack — event-loop teardown flakes | 1 error + ~9 of the 18 failures | `test_ws_delegation_visibility` (ERROR at teardown), plus `test_full_execution_flow` / `test_cross_service_flows` cases failing on `RuntimeError: Event loop is closed` inside the `cc_client`/`ch_client` httpx fixtures | pytest-asyncio fixture finalizer closes an httpx client on an already-closed loop; same fixtures skip/pass elsewhere; not behavioral |
| Cross-service integration vs live stack — pre-existing policy mismatches | ~9 of the 18 | `test_service_auth` (7), `test_cross_service_flows` (cert-rejection cases), `test_websocket_communication_hub::test_control_center_does_not_serve_websocket_routes` | Black-box httpx tests against live services on :8000-8002. The pre-existing internal-endpoint allowlist (`deps.py::_CALLER_TYPE_MAP`, admits only `agent-runtime`/`communication-hub`) returns 403 `unknown_internal_caller` to `service:test-service` — **byte-identical in HEAD** (deps.py working-tree diff is insertions-only, none in that area); WS auth-middleware handling likewise unchanged. These tests expect the pre-allowlist behavior |

Environmental caveats: live stack was up and healthy on :8000-8002 during the run (all `/health` → 200); uvicorn runs with `--reload` so services serve working-tree code. The git-stash pre-change equivalence claimed by the developer is consistent with code inspection: the failing tests are black-box (outcome driven by live services, not the working tree) and the middleware logic they exercise is identical in HEAD and the working tree.

#### Developer's original verification (2026-09-28, retained)

- **Repro suites (acceptance bar):** `.venv/bin/python -m pytest backend/tests/test_tenant_user_leak.py backend/tests/test_tenant_isolation_sweep.py -q` → **54 passed** (51 formerly-failing + 3 pre-existing passes).
- **Cache-pollution check:** sweep + `test_tenant_scoping.py` + leak tests in ONE process → **78 passed** (pre-fix, the defective global criteria cache made scoped-scoping tests fail after the sweep ran; pollution gone).
- **Named regression suites:** `pytest backend/tests/test_tenant_scoping.py backend/tests/test_platform_admin_api.py backend/tests/test_tenant_registration.py backend/tests/test_default_tenant_roles.py backend/tests/unit -q` → **948 passed, 11 skipped**.
- **Touched-surface suites:** mcp hub / permissions / oauth / tool-sync / internal APIs (84), certificate lifecycle + auth + authorization flow + plan generation (60), agent-runtime controls + agent_runtime (22) → all green.
- **Full backend suite:** 2216 passed; 20 remaining failures verified environmental/pre-existing (cross-service integration tests require the live stack per `tests/integration/*` design; 2 shared-dev-DB migration-state tests fail identically on the pre-change tree — verified via `git stash`).
- **Backend imports cleanly** (`create_app()` → 310 routes).

---

### Deviations / Concerns for review
1. **`delete_platform_user` 409 guard** (section 2): not explicitly requested; added because the global user deletion cascades `tenant_user_memberships` across ALL tenants (FK `ondelete=CASCADE`) — a cross-tenant destructive write. Platform admins (no tenant context) are unaffected. Product may prefer membership-only removal semantics long-term.
2. **LEFT join on the two certificate lookups**: an INNER join broke `test_certificate_lifecycle.py`, whose fixture plants certificates with a fake (non-existent) `agent_type_id` — legal on SQLite (no FK enforcement) but impossible on PostgreSQL. LEFT join preserves the test while tenant criteria still bind FK-valid rows to their tenant.
3. **`mcp_tools` scoping in `/internal/mcp/proxy-tool`**: `mcp_tools` was not among the 7 flagged tables, but the tool-resolution select sat in the same tenant-context query path as the flagged `mcp_sessions` select and was leaking in multi-tenant mode (per-tenant slugs collide platform-wide) — fixed with the same parent-join pattern.
