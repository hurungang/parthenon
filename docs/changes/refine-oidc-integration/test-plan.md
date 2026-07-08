# Test Plan: Refine OIDC Integration

## 1. Test Strategy

### Overall Approach

This change touches the authentication backbone of Parthenon — every authenticated request flows through the modified auth pipeline and every login experience depends on the new provider configuration system. Testing must be layered, thorough, and include both positive and negative paths.

**Layers and their responsibilities:**

| Layer | Scope | Tooling | Purpose |
|-------|-------|---------|---------|
| **Backend Unit Tests** | Individual services, models, and utilities in isolation | pytest + SQLite in-memory | Validate business logic correctness: super admin credential hashing, OIDC discovery parsing, JWT validation, config encryption/decryption, provider registry cache invalidation |
| **Backend Integration Tests** | Full service + DB layer (real PostgreSQL or SQLite in-memory) with external HTTP mocked | pytest + respx | Validate end-to-end API behavior: auth middleware pipeline, setup wizard flow, system config CRUD, migration from identity.yaml, error responses |
| **Backend API Tests** | REST endpoint contracts at the HTTP boundary | pytest + httpx async client | Validate API contracts: request/response schemas, status codes, content types, authorization enforcement, public vs protected routes |
| **Frontend Component Tests** | UI components in isolation with mocked APIs | Vitest + React Testing Library + MSW or vi.mock | Validate rendering logic: login page state variants, system config forms, setup wizard UI, super admin toggle |
| **E2E Tests** | Real browser against running stack | Playwright | Validate complete user journeys: super admin login + OIDC config + test login + disable super admin + OIDC login flow; setup wizard flow; independent provider configuration |

### Data Flow Coverage

The three-tier auth pipeline must be tested at every branch:
1. Super admin token path (valid credentials, invalid credentials, disabled state)
2. OIDC JWT path (user provider active, agent provider active, both active, neither active, provider disabled)
3. Public fallback path (setup endpoints, OIDC callback, health check)

### Database Change Testing (CRITICAL)

Because `has_db_changes: true`, all backend integration tests MUST:
- **Verify schema changes took effect**: Query `information_schema` to confirm new tables (`super_admin_credentials`, `identity_provider_config_audit`) exist, new columns exist on existing tables, removed columns (`realm_name`, `audience`, `is_setup_complete`, `setup_completed_at`, `setup_completed_by_id`) are truly gone, enum types have the correct values (`oidc_generic`, `keycloak`, `azure_entraid` for provider_type; `user`, `agent` for provider_scope)
- **Include negative tests**: Attempt to insert a `provider_scope` value not in the enum; attempt to insert NULL into `provider_scope` if NOT NULL; attempt to insert a duplicate provider scope (only one `user` and one `agent` allowed)
- **Include CRUD lifecycle tests** for all new and modified entities

### Pre-Test Checklist for Database Changes
1. Check `.change.yaml` confirms `has_db_changes: true`
2. Verify the latest Alembic migration exists for the schema changes
3. Run `alembic upgrade head` against the test database
4. Verify migration applied: confirm new tables/columns from `information_schema`
5. Confirm removed fields (realm_name, audience, setup tracking fields) are truly absent

---

## 2. Coverage Areas

### 2.1 Super Admin Authentication (CRITICAL)
**Why critical**: This is the emergency backdoor for platform operators. If it fails, a misconfigured OIDC provider can lock everyone out of the platform permanently.

- Credential seeding from environment variables on first launch
- Credential validation (hash comparison, timing-safe)
- Token issuance (format, expiry, signing key)
- Token validation in auth middleware (valid token, expired token, tampered token)
- Enable/disable toggle behavior (disabled → login refused even with correct credentials)
- Last login timestamp update
- Guard rail: cannot disable super admin if no OIDC provider is configured

### 2.2 OIDC Provider Configuration (CRITICAL)
**Why critical**: This replaces the static YAML config — the single source of truth for all authentication. Configuration errors break all platform access.

- Full CRUD lifecycle: create, read, update, delete provider configs
- Independent user and agent provider entries (separate scopes, separate clients)
- Configuration persistence to database (verify DB is source of truth)
- Field validation: issuer URL format, client ID required, client secret required, scopes format
- Encryption at rest for client secret (verify DB stores ciphertext, not plaintext)
- OIDC Discovery validation on save (issuer reachability, `.well-known/openid-configuration` fetch)
- Provider registry hot-reload after config change (no restart needed)
- Audit trail: every config change logged to `IdentityProviderConfigAudit`

### 2.3 Authentication Flow — Three-Tier Pipeline
**Why critical**: Every API request flows through this pipeline. A single regression can break all platform access.

- Super admin token path: valid token → resolved identity; expired token → 401; disabled → skip path, fall through to OIDC
- OIDC JWT path: valid user JWT → resolved identity; valid agent JWT → resolved agent identity; invalid signature → 401; expired JWT → 401; wrong audience → 401
- Public path: setup wizard endpoints accessible without auth; OIDC callback accessible without auth; health check accessible without auth
- Mixed state: super admin enabled + one OIDC provider active → both paths work
- Mixed state: super admin disabled + two OIDC providers active → only OIDC paths work
- Error path: no providers configured + super admin disabled → platform inaccessible (expected), clear error displayed

### 2.4 Setup Wizard (Preserved & Modified)
**Why critical**: This is the first-run experience. Must continue working for dev/demo users while adapting to database-backed config.

- Existing flow preserved: bundled Keycloak setup, external OIDC setup, Azure EntraID setup
- New behavior: writes to database system config instead of `config/identity.yaml`
- Trigger condition: no OIDC config in DB and no super admin enabled
- Optional: configure separate user and agent identity providers during wizard
- Setup state tracking: `user_provider_configured` and `agent_provider_configured` flags updated correctly
- Wizard still publicly accessible (no auth required)

### 2.5 Backward Compatibility — identity.yaml Migration
**Why critical**: Existing deployments must upgrade seamlessly. Data loss during migration locks users out.

- One-time migration: `config/identity.yaml` values read and written to database on startup
- Migration idempotent: running twice does not duplicate or corrupt data
- After migration: database takes precedence; YAML file is no longer read
- Migration handles all legacy field names: `oidc_provider_url` → `issuer_url`, `client_secret` → `encrypted_client_secret`, `keycloak_bundled`|`keycloak_external` → `keycloak`
- Migration handles missing YAML file gracefully (fresh deployment scenario)

### 2.6 Login Page Rendering
**Why critical**: Users must see the correct login options based on system state.

- Super admin enabled + no OIDC configured: shows username/password form only
- Super admin enabled + OIDC configured: shows both super admin form and OIDC login button(s)
- Super admin disabled + OIDC configured: shows OIDC login button(s) only, no super admin form
- No OIDC configured + super admin disabled: redirects to setup wizard
- Multiple providers configured: shows distinct login buttons for each active identity domain (user identity, agent identity if applicable)

### 2.7 OIDC Test & Login (New Capability)
**Why critical**: Operators need confidence before switching production authentication. A failed test should never affect active users.

- Test connection: validates provider reachability + client credentials without full login
- Test login: initiates real OIDC authorization code flow, returns claims response
- Test results displayed inline with pass/fail indicators
- Test operations logged to `IdentityProviderConfigAudit` (change_type: `tested`)
- Neither test operation affects the active provider config or existing user sessions

### 2.8 Error Handling & Resilience
**Why critical**: Authentication failures MUST be informative, not cryptic. Operators need actionable guidance.

- Unreachable OIDC provider → clear error on login page (not generic 500)
- OIDC misconfigured + super admin disabled → guidance on login page + in logs about re-enabling super admin
- Client secret decryption failure → logged with context, returns config error (not crash)
- OIDC Discovery endpoint returns non-200 → graceful error in system config UI
- Super admin credentials not configured → clear startup log message, does not crash

### 2.9 Agent Identity Provider Independence
**Why critical**: Agent-to-agent communication and tool calling depend on agent identity tokens being valid from the correct provider.

- Agent identity provider configured independently from user provider
- Agent tokens validated against the agent-specific provider (not the user provider)
- Changing user provider does not affect agent token validation
- Changing agent provider does not affect user token validation
- Control Center correctly resolves which provider to use based on token audience/claims

---

## 3. Critical Scenarios

### Scenario 1: Super Admin Bootstrap — First Launch
**WHEN** Parthenon starts for the first time with `SUPER_ADMIN_ENABLED=true` and valid `SUPER_ADMIN_USERNAME` / `SUPER_ADMIN_PASSWORD_HASH` env vars  
**THEN** the super admin credentials are seeded to the database, appear in the `super_admin_credentials` table, and the super admin can log in and access the full platform UI

### Scenario 2: Super Admin Disabled After OIDC Confirmed Working
**WHEN** the super admin has configured a working OIDC provider and verified login works, then disables the super admin via the config toggle (with at least one enabled OIDC provider present)  
**THEN** super admin login is refused with a clear message; only OIDC-authenticated users can access the platform; the `is_enabled` flag is `false` in the database

### Scenario 3: Super Admin Disabled — Guard Rail Blocks Without OIDC
**WHEN** an operator attempts to disable the super admin while no OIDC provider is configured and enabled  
**THEN** the system rejects the operation with a clear error indicating that at least one enabled OIDC provider is required before disabling the super admin

### Scenario 4: Independent User and Agent Providers
**WHEN** the super admin configures a user identity provider (e.g., Azure EntraID at `login.microsoftonline.com/tenant-a`) and a separate agent identity provider (e.g., Keycloak at `keycloak.internal:8080/realms/ai_agents`)  
**THEN** human users can log in through Azure EntraID, agent identities authenticate through the Keycloak realm, and changing one provider's config does not affect the other

### Scenario 5: OIDC Test Login Validates Full Flow Before Commit
**WHEN** the super admin enters a new OIDC provider configuration (issuer URL, client ID, client secret) and clicks "Test Login"  
**THEN** the system initiates a real OIDC authorization code flow, the operator completes login at the provider, the system displays the returned claims, and the operator can confirm correctness before saving/enabling the provider

### Scenario 6: Backward Compatible Migration — identity.yaml to Database
**WHEN** an existing deployment with a valid `config/identity.yaml` is upgraded to the new version  
**THEN** on first startup, the system reads the YAML file, creates corresponding `IdentityProviderConfig` rows in the database (one for user scope, one for agent scope if configured), marks migration as complete, and from that point forward reads only from the database — the YAML file is ignored

### Scenario 7: Full E2E — Super Admin Configures Provider Then Logs In via OIDC
**WHEN** a super admin (1) logs in with credentials, (2) navigates to system config, (3) creates a new user identity provider config with a real OIDC provider, (4) tests the connection, (5) enables the provider, (6) logs out, (7) logs back in via the OIDC login button on the login page  
**THEN** the OIDC login succeeds, the user is redirected to the dashboard with the correct identity mapped from OIDC claims, and the super admin stays disabled until explicitly re-enabled

### Scenario 8: Setup Wizard — Bundled Keycloak via Database Config
**WHEN** a fresh deployment with no OIDC config in the database and no super admin enabled launches, and the user completes the setup wizard with bundled Keycloak  
**THEN** the wizard provisions Keycloak, writes the provider configuration to the database (not identity.yaml), the setup state tracks both user and agent providers as configured, and the platform proceeds to the login page

### Scenario 9: OIDC Provider Unreachable — Login Page Error
**WHEN** a configured OIDC provider is unreachable (network down, service stopped) and a user attempts to log in  
**THEN** the login page displays a clear, non-technical error message indicating the identity provider is temporarily unavailable (not a generic 500), and if the super admin is enabled, the super admin login form remains available for emergency access

### Scenario 10: Provider Registry Hot-Reload Without Restart
**WHEN** an operator updates an OIDC provider configuration (e.g., changes the issuer URL) via the system config API  
**THEN** the OIDC Provider Registry detects the change, invalidates its cache, reloads the config from the database, and subsequent authentication requests use the updated configuration — all without restarting the Control Center service

---

## 4. Edge Cases & Risks

### Edge Cases

| Edge Case | Risk Level | Mitigation |
|-----------|------------|------------|
| Super admin password hash env var is empty or unset on first launch | HIGH | System must log a clear warning and either refuse to start or operate without super admin (graceful degradation). Never fall back to a hardcoded password. |
| Both user and agent OIDC providers point to the same issuer URL but with different client IDs | MEDIUM | Must handle correctly; the provider scope (`user` vs `agent`) disambiguates. JWKS cache should be shared or scoped correctly to avoid key conflicts. |
| OIDC provider returns a well-known configuration with unexpected fields or missing optional endpoints | MEDIUM | Discovery parser must be tolerant — only required fields (issuer, authorization_endpoint, token_endpoint, jwks_uri) are mandatory; extras are ignored. |
| Client secret encryption key is rotated or lost | HIGH | Document recovery procedure: re-enter client secret via UI. Encrypted secrets that cannot be decrypted return a config error, not a crash. |
| Setup wizard completes but the database write fails mid-transaction | HIGH | Wizard must use a transactional boundary; if it fails, the setup state must roll back. User sees an error and can retry. |
| Migration from identity.yaml encounters a malformed YAML file | MEDIUM | Migration logs the error with file path and line, signals migration as failed without crashing, and leaves existing DB config (if any) intact. |
| Super admin JWT token is used after the super admin is disabled | MEDIUM | Token validation must check the `is_enabled` flag at validation time (not just at issue time). Disabling super admin should invalidate active tokens or reject them on next request. |
| Agent identity token is presented to a user-scoped endpoint (or vice versa) | MEDIUM | Auth middleware must verify that the token's provider scope matches the request context. Agent tokens should not grant access to user-only resources. |
| Two operators simultaneously update the same provider config | LOW | Last-write-wins is acceptable for now; audit trail records both changes. Add optimistic locking if concurrent edits become a problem. |
| OIDC Discovery URL is a redirect (HTTP 302) | LOW | HTTP client should follow redirects for discovery. If it hangs or times out, provide a clear timeout error message. |

### Risk Areas

1. **Auth Middleware Complexity** — The three-tier pipeline introduces more branches than the previous single-path design. Every branch needs coverage. The risk of an unhandled state causing a 500 or auth bypass is elevated.

2. **Provider Registry Cache Coherence** — The in-memory cache must stay synchronized with the database. A stale cache could mean an operator fixes a broken OIDC config but the system still rejects logins until the next restart.

3. **Encryption Key Management** — Client secrets are encrypted at rest. If the encryption key (derived from the Control Center's internal key) changes or is lost, all stored secrets become unreadable. This is a data loss scenario.

4. **Setup Wizard → Database Transition** — The setup wizard previously wrote to a file. The transition to database writes introduces a new failure mode: if the database is unavailable at setup time, the wizard cannot complete. This is a chicken-and-egg problem if the database itself requires authentication.

5. **One-Time Migration Reliability** — If the migration from identity.yaml to the database partially succeeds (e.g., user scope migrated, agent scope failed), the system may end up in an inconsistent state without clear recovery instructions.

---

## 5. Acceptance Criteria Checklist

### Super Admin Bootstrap
- [ ] On first launch with env vars set, super admin credentials appear in `super_admin_credentials` table
- [ ] Super admin can log in with username/password from env vars
- [ ] Super admin receives a valid JWT token that grants full platform access
- [ ] Super admin token has configurable short expiry (default 15 minutes)
- [ ] Super admin credentials are never hardcoded in source code
- [ ] Empty/missing env vars produce a clear startup log warning (no crash)

### OIDC Provider Configuration in UI
- [ ] Super admin can navigate to system config and see identity provider management section
- [ ] User identity provider and agent identity provider are separate configurable entries
- [ ] Form fields: issuer URL, client ID, client secret (masked), scopes, claims mapping
- [ ] On save, config is persisted to `identity_provider_configs` table in database
- [ ] Client secret is encrypted in the database (verify via direct DB query)
- [ ] Provider registry reloads config from DB without service restart
- [ ] Audit entry written to `identity_provider_config_audit` on every save

### Independent Identity Providers
- [ ] Both providers can be configured independently (different issuers, different clients)
- [ ] Changing user provider does not invalidate agent tokens and vice versa
- [ ] A single deployment can use the same provider for both (same issuer, different client IDs)
- [ ] Agent identity tokens managed centrally by Control Center, never exposed to agent runtimes
- [ ] Agent tokens validated against the agent-scoped provider config

### OIDC Test & Login
- [ ] "Test Connection" validates issuer reachability and returns inline pass/fail
- [ ] "Test Login" initiates real OIDC flow and displays returned claims
- [ ] Test results do not affect active provider configuration
- [ ] Test operations are audited in `IdentityProviderConfigAudit`

### Super Admin Disablement
- [ ] Super admin `is_enabled` toggle works via config API
- [ ] Environment variable `PARTHENON_SUPER_ADMIN_ENABLED=false` overrides UI toggle
- [ ] When disabled, super admin login is refused with clear message
- [ ] When disabled, active super admin tokens are rejected on next validation
- [ ] Guard rail: cannot disable super admin if no enabled OIDC provider exists

### Dev/Demo Setup Wizard (Preserved)
- [ ] First launch with no DB config + no super admin enabled → setup wizard appears
- [ ] Bundled Keycloak flow works and writes config to database
- [ ] External OIDC flow works and writes config to database
- [ ] `user_provider_configured` and `agent_provider_configured` flags set correctly
- [ ] `config/identity.yaml` is NOT created during wizard (DB is the target)

### Backward Compatibility
- [ ] Existing `config/identity.yaml` is migrated to database on upgrade startup
- [ ] Migration maps old field names to new field names correctly
- [ ] After migration, database config takes precedence; YAML file is no longer read
- [ ] Migration does not run if database already has config (idempotent)
- [ ] Missing YAML file on fresh deployment is handled gracefully (no migration needed)

### Error Handling
- [ ] Unreachable OIDC provider → login page shows clear error (not 500)
- [ ] OIDC broken + super admin disabled → login page shows guidance for re-enabling
- [ ] OIDC broken + super admin disabled → logs contain actionable recovery instructions
- [ ] Decryption failure → config error response, not a crash
- [ ] Discovery endpoint failure → graceful error in system config UI with provider details

### Database Schema Changes (CRITICAL)
- [ ] `super_admin_credentials` table exists with correct columns and constraints
- [ ] `identity_provider_config_audit` table exists with correct columns and FK to config
- [ ] `identity_provider_configs` has new columns: `provider_scope`, `display_name`, `issuer_url`, `encrypted_client_secret`, `scopes`, `claim_mappings`, `is_enabled`
- [ ] `identity_provider_configs` no longer has: `realm_name`, `audience`, `is_setup_complete`, `setup_completed_at`, `setup_completed_by_id`
- [ ] `identity_provider_setup_state` has new columns: `user_provider_configured`, `agent_provider_configured`
- [ ] `provider_type` enum values are `oidc_generic`, `keycloak`, `azure_entraid` (not `keycloak_bundled`, `keycloak_external`)
- [ ] `provider_scope` enum type exists with values `user`, `agent`
- [ ] `provider_scope` has a unique constraint (only one config per scope)

---

## 6. Test File References

### Backend Unit Tests
> Path: `backend/tests/` (from `docs/config.yaml` `source.tests`)

| Test File | Coverage |
|-----------|----------|
| `backend/tests/unit/test_oidc_client.py` | OIDC Client: multi-provider support, standard OIDC Discovery parsing, per-provider JWT validation, claims mapping |
| `backend/tests/unit/test_super_admin_auth.py` | Super Admin Auth Service: credential validation (bcrypt), token issuance, enable/disable check |
| `backend/tests/unit/test_oidc_provider_registry.py` | OIDC Provider Registry: cache load/reload, hot-reload on config change, JWKS caching with TTL |
| `backend/tests/unit/test_oidc_config_service.py` | OIDC Config Service: CRUD operations, field validation, secret encryption/decryption, discovery validation |
| `backend/tests/unit/test_config_migration.py` | identity.yaml → database migration: field mapping, idempotency, error handling for malformed YAML |

### Backend Integration Tests
> Path: `backend/tests/` (from `docs/config.yaml` `source.tests`)

| Test File | Coverage |
|-----------|----------|
| `backend/tests/integration/test_super_admin_flow.py` | Full super admin lifecycle: bootstrap, login, token validation, disable/enable toggle, disable guard rail |
| `backend/tests/integration/test_oidc_config_crud.py` | Full CRUD for identity provider configs via API: create user provider, create agent provider, update, delete, duplicate-prevention, field validation errors |
| `backend/tests/integration/test_oidc_test_connection.py` | OIDC test connection and test login endpoints: success cases, unreachable provider, bad credentials, audit trail |
| `backend/tests/integration/test_auth_pipeline.py` | Three-tier auth middleware: super admin path, OIDC user path, OIDC agent path, public path, mixed states, error states |
| `backend/tests/integration/test_identity_setup_flow.py` | **MODIFY EXISTING** — Update to verify setup writes to DB instead of YAML; add tests for `user_provider_configured` / `agent_provider_configured` flags; add tests for generic OIDC provider support |
| `backend/tests/integration/test_provider_independence.py` | Independent user and agent providers: token validation scoped to correct provider, provider change isolation |
| `backend/tests/integration/test_migration_identity_yaml.py` | One-time migration: verifies migration runs, field mapping correct, idempotent, database takes precedence after migration |
| `backend/tests/integration/test_database_schema.py` | **DATABASE CHANGE VERIFICATION** — Query `information_schema` to verify all new tables/columns exist, removed columns are absent, enum types have correct values, unique constraints enforced |

### Backend API Tests
> Path: `backend/tests/` (from `docs/config.yaml` `source.tests`)

| Test File | Coverage |
|-----------|----------|
| `backend/tests/api/v1/test_system_config_api.py` | System Config API endpoints: identity provider CRUD, super admin enable/disable, test connection, test login |
| `backend/tests/api/v1/test_setup_identity.py` | **MODIFY EXISTING** — Update setup identity endpoint tests for DB-backed config, generic OIDC provider types |
| `backend/tests/api/v1/test_auth_endpoints.py` | Login endpoint, OIDC callback, token validation, public path access control |

### Frontend Component Tests
> Path: `frontend/src/__tests__/` (from `docs/config.yaml` `source.tests`)

| Test File | Coverage |
|-----------|----------|
| `frontend/src/__tests__/IdentityProviderConfigForm.test.tsx` | **NEW** — Provider form component: render fields, password toggle, enable toggle, save with data, configured/not-configured chips, test modal opening, advanced options expand, disabled state |
| `frontend/src/__tests__/SuperAdminConfigSection.test.tsx` | **NEW** — Super admin config section: toggle states, status display, disable confirmation modal, guard rail modal, password change dialog |
| `frontend/src/__tests__/OIDCTestConfigModal.test.tsx` | **NEW** — OIDC test config modal: open/close, pre-test state, client ID display, close button |
| `frontend/src/__tests__/OIDCTestLoginModal.test.tsx` | **NEW** — OIDC test login modal: open/close, pre-test warning, issuer/client display, initiate button, testing state |
| `frontend/src/__tests__/IdentityProvidersConfigPage.test.tsx` | **NEW** — Identity providers config page: tabs, user/agent provider forms, Same as User toggle, General Settings tab switching, save callback |
| `frontend/src/__tests__/LoginPage.refined.test.tsx` | **NEW** — Login page three-state rendering: super admin only (form with username/password), OIDC only (login button), both (OIDC button + super admin toggle with back), setup wizard redirect state |
| `frontend/src/__tests__/AuthContext.test.tsx` | **NEW** — Auth context: initial state (isAuthenticated, providers, superAdminEnabled, isSuperAdmin), setToken updates, logout clears storage, provider discovery, graceful error handling |
| `frontend/src/__tests__/LoginPage.test.tsx` | **EXISTING** — Basic login page rendering tests (unchanged) |
| `frontend/src/__tests__/SetupWizard.test.tsx` | **EXISTING** — Setup wizard rendering tests (unchanged) |

### E2E Tests
> Path: `e2e/tests/` (from `docs/config.yaml` `source.tests`)

| Test File | Coverage |
|-----------|----------|
| `e2e/tests/oidc-login-flows.spec.ts` | **NEW** — Login page rendering in all states (super admin only, OIDC only, both, setup wizard), OIDC login button presence, super admin form fields, system config page navigation with tabs |

### Test Files to Modify (Existing)

| Existing File | Change Required |
|---------------|-----------------|
| `backend/tests/integration/test_identity_setup_flow.py` | Update payloads for new provider type enum values (`oidc_generic`/`keycloak`); add `provider_scope` to test data; verify writes go to DB, not YAML; update field names (`issuer_url` not `oidc_provider_url`) |
| `backend/tests/api/v1/test_setup_identity.py` | Update for new provider type enum, new field names, dual provider scope support |
| `frontend/src/__tests__/LoginPage.test.tsx` | Add super admin login form rendering tests, multi-provider OIDC button rendering |
| `frontend/src/__tests__/SetupWizard.test.tsx` | Add generic OIDC provider option, dual-provider configuration step tests |
| `e2e/tests/setup-wizard.spec.ts` | Update API mock payloads for new field names and provider type values; verify DB-backed persistence |
| `e2e/tests/auth-required/oidc-callback.spec.ts` | Update for database-backed provider config resolution |

---

## 7. Test Execution Order

Recommended order to minimize wasted effort chasing cascading failures:

1. **Database Schema Verification** — Confirm all schema changes applied correctly before anything else
2. **Backend Unit Tests** — OIDC client, super admin auth, provider registry (no DB dependency)
3. **Backend Integration: Migration** — Verify identity.yaml → DB migration works (foundational)
4. **Backend Integration: Schema CRUD** — Verify all new/modified tables work correctly
5. **Backend Integration: Super Admin Flow** — Bootstrap, login, token validation, toggle
6. **Backend Integration: OIDC Config CRUD** — Provider configuration lifecycle
7. **Backend Integration: Auth Pipeline** — Three-tier pipeline validation
8. **Backend Integration: Provider Independence** — User vs agent isolation
9. **Backend API Tests** — Endpoint contracts
10. **Frontend Component Tests** — UI rendering logic
11. **E2E Tests** — Full user journeys against running stack
