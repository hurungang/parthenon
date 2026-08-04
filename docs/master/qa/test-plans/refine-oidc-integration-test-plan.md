# Refine OIDC Integration Test Plan

## Scope

Covers the refined OIDC integration: super admin credential bootstrap and authentication, database-backed identity provider configuration (replacing `config/identity.yaml`), the three-tier auth pipeline (super admin → OIDC user → OIDC agent → public), independent user and agent identity providers, the setup wizard transition to database writes, OIDC test connection/login capabilities, and the backward-compatible migration from `identity.yaml` to database.

---

## Coverage Areas

### 1. Super Admin Authentication

**What is tested:**
- Credential seeding from `SUPER_ADMIN_USERNAME`/`SUPER_ADMIN_PASSWORD_HASH` env vars on first launch
- Credential validation with bcrypt hash comparison (timing-safe)
- JWT token issuance with configurable short expiry (default 15 minutes)
- Token validation in auth middleware: valid token, expired token, tampered token
- Enable/disable toggle: disabled → login refused even with correct credentials
- Last login timestamp update
- Guard rail: cannot disable super admin if no OIDC provider is configured

**Acceptance criteria:**
- Super admin credentials appear in `super_admin_credentials` table on first launch
- Super admin can log in and access full platform
- Disabled super admin login is refused with clear message
- Empty/missing env vars produce clear startup log warning (no crash)

**Test files:**
- [backend/tests/test_super_admin_auth_service.py](../../../../backend/tests/test_super_admin_auth_service.py) — Super Admin Auth Service: credential validation (bcrypt), token issuance, enable/disable check
- [backend/tests/test_super_admin_login_flow.py](../../../../backend/tests/test_super_admin_login_flow.py) — Full super admin lifecycle: bootstrap, login, token validation, disable/enable toggle, disable guard rail
- [frontend/src/__tests__/SuperAdminConfigSection.test.tsx](../../../../frontend/src/__tests__/SuperAdminConfigSection.test.tsx) — Super admin config section: toggle states, status display, disable confirmation modal, guard rail modal, password change dialog

---

### 2. OIDC Provider Configuration (DB-Backed)

**What is tested:**
- Full CRUD lifecycle: create, read, update, delete provider configs via system config API
- Independent user (`provider_scope=user`) and agent (`provider_scope=agent`) provider entries
- Field validation: issuer URL format, client ID required, client secret required, scopes format
- Encryption at rest for client secret (DB stores ciphertext)
- OIDC Discovery validation on save (issuer reachability, `.well-known/openid-configuration`)
- Provider registry hot-reload after config change (no restart)
- Audit trail: every config change logged to `IdentityProviderConfigAudit`
- `provider_type` enum: `oidc_generic`, `keycloak`, `azure_entraid`

**Acceptance criteria:**
- User and agent identity providers are separate configurable entries in system config UI
- Client secret is encrypted in database (verify via direct DB query)
- Provider registry reloads from DB without service restart
- Audit entries written on every save and test operation

**Test files:**
- [backend/tests/test_oidc_config_service.py](../../../../backend/tests/test_oidc_config_service.py) — OIDC Config Service: CRUD operations, field validation, secret encryption/decryption, discovery validation
- [backend/tests/test_system_config_api.py](../../../../backend/tests/test_system_config_api.py) — System Config API endpoints: identity provider CRUD, super admin enable/disable, test connection
- [frontend/src/__tests__/IdentityProviderConfigForm.test.tsx](../../../../frontend/src/__tests__/IdentityProviderConfigForm.test.tsx) — Provider form: render fields, password toggle, enable toggle, save with data, configured/not-configured chips, test modal opening, advanced options
- [frontend/src/__tests__/IdentityProvidersConfigPage.test.tsx](../../../../frontend/src/__tests__/IdentityProvidersConfigPage.test.tsx) — Config page: tabs, user/agent provider forms, Same as User toggle, General Settings tab switching, save callback

---

### 3. Authentication Flow — Three-Tier Pipeline

**What is tested:**
- Super admin token path: valid token → resolved identity; expired token → 401; disabled → skip, fall through to OIDC
- OIDC JWT path: valid user JWT → resolved identity; valid agent JWT → resolved agent identity; invalid signature → 401; expired JWT → 401; wrong audience → 401
- Public path: setup endpoints, OIDC callback, health check accessible without auth
- Mixed states: super admin enabled + one OIDC active → both paths work; super admin disabled + two OIDC active → only OIDC paths work
- Error path: no providers + super admin disabled → platform inaccessible, clear error displayed

**Acceptance criteria:**
- Super admin token validated against bcrypt hash at validation time (not just issue time)
- OIDC JWT validated per-provider (user tokens against user provider, agent tokens against agent provider)
- Public endpoints accessible without auth
- Middleware never crashes on unhandled state — returns 401 or allows through

**Test files:**
- [backend/tests/unit/test_auth_middleware.py](../../../../backend/tests/unit/test_auth_middleware.py) — JWT auth middleware: raw_token storage, public path bypass
- [backend/tests/test_auth_middleware_full.py](../../../../backend/tests/test_auth_middleware_full.py) — Full auth middleware pipeline integration tests
- [backend/tests/unit/test_oidc_client.py](../../../../backend/tests/unit/test_oidc_client.py) — OIDC Client: multi-provider support, standard OIDC Discovery parsing, per-provider JWT validation, claims mapping

---

### 4. Setup Wizard (Preserved & Modified)

**What is tested:**
- Bundled Keycloak setup, external OIDC setup, Azure Entra ID setup flows preserved
- New behavior: writes to database system config instead of `config/identity.yaml`
- Trigger condition: no OIDC config in DB and no super admin enabled
- Optional: configure separate user and agent identity providers during wizard
- `user_provider_configured` and `agent_provider_configured` flags updated correctly
- Wizard still publicly accessible (no auth required)

**Acceptance criteria:**
- Setup wizard writes provider config to database, not identity.yaml
- `config/identity.yaml` is NOT created during wizard
- Setup state flags correctly track configuration status
- Existing bundled/external flows work unchanged

**Test files:**
- [backend/tests/api/v1/test_setup_identity.py](../../../../backend/tests/api/v1/test_setup_identity.py) — Setup identity endpoint tests: DB-backed config, generic OIDC provider types, dual provider scope support
- [frontend/src/__tests__/AuthContext.test.tsx](../../../../frontend/src/__tests__/AuthContext.test.tsx) — Auth context: initial state (providers, superAdminEnabled), setToken, logout, provider discovery

---

### 5. Backward Compatibility — identity.yaml Migration

**What is tested:**
- One-time migration: `config/identity.yaml` values read and written to database on startup
- Migration idempotent: running twice does not duplicate or corrupt data
- After migration: database takes precedence; YAML file no longer read
- Migration handles legacy field names: `oidc_provider_url` → `issuer_url`, `client_secret` → `encrypted_client_secret`, `keycloak_bundled`/`keycloak_external` → `keycloak`
- Migration handles missing YAML file gracefully (fresh deployment)

**Acceptance criteria:**
- Existing deployments upgrade seamlessly — no data loss
- Migration only runs if database has no config (idempotent)
- Malformed YAML produces clear error log with file path and line, does not crash

**Test files:**
- Backward compatibility tested through existing integration and API tests
- Migration path validated during upgrade testing (manual or CI)

---

### 6. OIDC Test & Login

**What is tested:**
- Test connection: validates provider reachability + client credentials without full login
- Test login: initiates real OIDC authorization code flow, returns claims response
- Test results displayed inline with pass/fail indicators
- Test operations logged to `IdentityProviderConfigAudit` (change_type: `tested`)
- Neither test operation affects active provider config or existing user sessions

**Acceptance criteria:**
- "Test Connection" button validates issuer reachability, returns inline pass/fail
- "Test Login" initiates real OIDC flow, displays returned claims
- Test operations are audited but do not alter active provider state

**Test files:**
- [frontend/src/__tests__/OIDCTestConfigModal.test.tsx](../../../../frontend/src/__tests__/OIDCTestConfigModal.test.tsx) — Test config modal: open/close, pre-test state, client ID display
- [frontend/src/__tests__/OIDCTestLoginModal.test.tsx](../../../../frontend/src/__tests__/OIDCTestLoginModal.test.tsx) — Test login modal: open/close, pre-test warning, issuer/client display, initiate button, testing state

---

### 7. Login Page Rendering

**What is tested:**
- Super admin enabled + no OIDC: shows username/password form only
- Super admin enabled + OIDC configured: shows both super admin form and OIDC login button(s)
- Super admin disabled + OIDC configured: shows OIDC login button(s) only, no super admin form
- No OIDC + super admin disabled: redirects to setup wizard
- Multiple providers: distinct login buttons for each active identity domain

**Acceptance criteria:**
- Correct login options displayed for every system state
- Transition between states (enable OIDC, disable super admin) reflects immediately
- Setup wizard redirect when no authentication methods available

**Test files:**
- [frontend/src/__tests__/LoginPage.refined.test.tsx](../../../../frontend/src/__tests__/LoginPage.refined.test.tsx) — Three-state rendering: super admin only (form with username/password), OIDC only (login button), both (OIDC button + super admin toggle), setup wizard redirect state

---

### 8. Agent Identity Provider Independence

**What is tested:**
- Agent identity provider configured independently from user provider
- Agent tokens validated against agent-specific provider (not user provider)
- Changing user provider does not affect agent token validation
- Changing agent provider does not affect user token validation
- Control Center resolves which provider to use based on token audience/claims

**Acceptance criteria:**
- User and agent providers fully isolated — changing one never impacts the other
- Both providers can use same issuer URL with different client IDs

**Test files:**
- [backend/tests/unit/test_oidc_client.py](../../../../backend/tests/unit/test_oidc_client.py) — Per-provider JWT validation with correct provider scope isolation

---

### 9. Database Schema Changes

**What is tested:**
- `super_admin_credentials` table exists with correct columns and constraints
- `identity_provider_config_audit` table exists with FK to config
- `identity_provider_configs` has new columns: `provider_scope`, `display_name`, `issuer_url`, `encrypted_client_secret`, `scopes`, `claim_mappings`, `is_enabled`
- `identity_provider_configs` removed columns: `realm_name`, `audience`, `is_setup_complete`, `setup_completed_at`, `setup_completed_by_id`
- `identity_provider_setup_state` has new columns: `user_provider_configured`, `agent_provider_configured`
- `provider_type` enum: `oidc_generic`, `keycloak`, `azure_entraid` (not `keycloak_bundled`, `keycloak_external`)
- `provider_scope` enum: `user`, `agent` with unique constraint (only one config per scope)
- Negative tests: reject invalid provider_scope values, reject duplicate provider scopes

**Acceptance criteria:**
- All schema changes applied correctly (verify via `information_schema`)
- Removed columns truly absent
- Enum constraints enforced
- `alembic upgrade head` and `alembic downgrade -1` work correctly

**Test files:**
- Schema verification tested via integration tests querying `information_schema`
- Covered by existing database migration test infrastructure

---

## E2E Test Coverage

| Test File | Coverage |
|-----------|----------|
| [e2e/tests/oidc-login-flows.spec.ts](../../../../e2e/tests/oidc-login-flows.spec.ts) | Login page rendering in all states (super admin only, OIDC only, both, setup wizard); OIDC login button presence; super admin form fields; system config page navigation with tabs |
| [e2e/tests/auth-required/oidc-callback.spec.ts](../../../../e2e/tests/auth-required/oidc-callback.spec.ts) | OIDC callback flow with database-backed provider config resolution |

---

## Critical Edge Cases & Risks

| Risk | Mitigation |
|------|------------|
| Super admin password hash env var is empty or unset on first launch | System logs clear warning; operates without super admin (graceful degradation). Never fall back to hardcoded password. |
| Both user and agent OIDC providers point to same issuer URL with different client IDs | Provider scope (`user` vs `agent`) disambiguates; JWKS cache scoped correctly to avoid key conflicts |
| OIDC provider returns unexpected fields in discovery document | Parser tolerant — only required fields mandatory; extras ignored |
| Client secret encryption key rotated or lost | Document recovery: re-enter secret via UI. Decryption failure returns config error, not crash. |
| Setup wizard DB write fails mid-transaction | Wizard uses transactional boundary; failure rolls back; user sees error and can retry |
| Migration from identity.yaml encounters malformed YAML | Migration logs error with file path and line; signals migration failed without crash; leaves existing DB config intact |
| Super admin JWT used after super admin disabled | Token validation checks `is_enabled` flag at validation time (not just issue time) |
| Agent identity token presented to user-scoped endpoint (or vice versa) | Auth middleware verifies token's provider scope matches request context |
| Two operators simultaneously update same provider config | Last-write-wins acceptable; audit trail records both changes |
| OIDC Discovery URL is a redirect (HTTP 302) | HTTP client follows redirects; timeout provides clear error message |
| Provider registry cache stale after config change | Hot-reload invalidates cache on config change; no restart required |
| No providers configured + super admin disabled = platform inaccessible | Login page shows guidance for re-enabling super admin; logs contain actionable recovery instructions |

---

## Test Execution Summary

| Layer | Files | Status |
|-------|-------|--------|
| Backend — Unit | `test_super_admin_auth_service.py`, `test_oidc_client.py`, `test_oidc_config_service.py`, `test_auth_middleware.py` | ✅ CREATED |
| Backend — Integration | `test_super_admin_login_flow.py`, `test_system_config_api.py`, `test_auth_middleware_full.py` | ✅ CREATED |
| Backend — API | `test_setup_identity.py` | ✅ UPDATED |
| Frontend (Vitest) | `IdentityProviderConfigForm.test.tsx`, `IdentityProvidersConfigPage.test.tsx`, `SuperAdminConfigSection.test.tsx`, `OIDCTestConfigModal.test.tsx`, `OIDCTestLoginModal.test.tsx`, `LoginPage.refined.test.tsx`, `AuthContext.test.tsx` | ✅ CREATED |
| E2E (Playwright) | `oidc-login-flows.spec.ts`, `auth-required/oidc-callback.spec.ts` | ✅ CREATED/UPDATED |
