# Implementation Plan: Refine OIDC Integration

## Overview

This plan implements multi-provider OIDC support with independent user and agent identity providers stored in the database instead of config/identity.yaml. It adds a built-in super admin account for production bootstrap, a UI-based system config module for OIDC provider management, a one-time migration from YAML to database, and preserves the existing dev/demo setup wizard. All changes respect the top-priority architecture rule that only Control Center connects to the database.

## Task Checklist

### Phase 1 — Database Schema Changes
- [x] 1.1 — Restructure IdentityProviderConfig model: add/rename/remove fields, update provider_type enum
- [x] 1.2 — Add user_provider_configured and agent_provider_configured fields to IdentityProviderSetupState model
- [x] 1.3 — Create IdentityProviderConfigAudit model
- [x] 1.4 — Create SuperAdminCredentials model
- [x] 1.5 — Generate and apply Alembic migration

### Phase 2 — Backend: OIDC Config Service and Provider Registry
- [x] 2.1 — Create OIDCConfigService with CRUD, encryption, and validation logic
- [x] 2.2 — Create OIDCProviderRegistry with in-memory cache, hot-reload, and JWKS key caching per provider
- [x] 2.3 — Refactor OIDCClient to support multi-provider token validation via the Provider Registry

### Phase 3 — Backend: Super Admin Auth Service and Auth Middleware
- [x] 3.1 — Create SuperAdminAuthService: credential seeding, login validation, JWT issuance, enable/disable
- [x] 3.2 — Update BootstrapService/startup to seed super admin credentials and init Provider Registry
- [x] 3.3 — Update JWTAuthMiddleware to three-tier auth pipeline (super admin, OIDC, public fallback)

### Phase 4 — Backend: System Config API and Setup Wizard Changes
- [x] 4.1 — Create System Config identity provider API endpoints (CRUD for user/agent providers)
- [x] 4.2 — Create System Config super admin management API endpoints (enable/disable, password update)
- [x] 4.3 — Create OIDC test and test-login API endpoints
- [x] 4.4 — Update Setup Wizard to write OIDC config to database instead of config/identity.yaml
- [x] 4.5 — Update config loading to read OIDC config from database after startup (fall back to YAML for migration)

### Phase 5 — Backend: Migration Utility (identity.yaml to DB)
- [x] 5.1 — Create one-time migration service that reads config/identity.yaml and writes to database
- [x] 5.2 — Wire migration into startup sequence; after migration, DB is source of truth, YAML is no longer read

### Phase 6 — Frontend: System Config UI
- [x] 6.1 — Create IdentityProviderConfigForm component (provider type, issuer URL, client ID, secret, scopes, claims mapping, advanced options)
- [x] 6.2 — Create IdentityProvidersConfigPage with independent user and agent provider sections
- [x] 6.3 — Create SuperAdminConfigSection with enable/disable toggle and confirmation modal
- [x] 6.4 — Create OIDCTestConfigModal (step-by-step connectivity test UI)
- [x] 6.5 — Create OIDCTestLoginModal (authorization code flow test UI)
- [x] 6.6 — Create Dashboard identity provider status cards (provider status + super admin status)

### Phase 7 — Frontend: Auth Changes
- [x] 7.1 — Update LoginPage with three-state rendering (super admin only / both / OIDC only) based on provider discovery
- [x] 7.2 — Update AuthContext/stores to discover active providers on app load and manage auth state

### Phase 8 — Integration Testing and End-to-End Validation
- [x] 8.1 — Write backend integration tests for OIDCConfigService and OIDCProviderRegistry
- [x] 8.2 — Write backend integration tests for SuperAdminAuthService
- [x] 8.3 — Write backend integration tests for three-tier auth middleware pipeline
- [x] 8.4 — Write backend integration tests for identity.yaml to DB migration
- [x] 8.5 — Write backend integration tests for system config API endpoints
- [x] 8.6 — Write frontend unit tests for new components and auth state changes
- [x] 8.7 — Write E2E tests for login flows (super admin, OIDC user, OIDC agent)
- [ ] 8.8 — Manual end-to-end validation with bundled Keycloak and an external OIDC provider

---

## Phase 1 — Database Schema Changes

### Task 1.1 — Restructure IdentityProviderConfig model

**File**: backend/app/db/models/identity_provider_config.py

Update the existing IdentityProviderConfig SQLAlchemy model:

- Add provider_scope enum column (user, agent)
- Add display_name string column
- Rename oidc_provider_url to issuer_url
- Rename client_secret to encrypted_client_secret
- Add scopes string column (default: openid profile email)
- Add claim_mappings JSONB column (nullable, default null)
- Add is_enabled boolean column (default: true)
- Remove realm_name column
- Remove audience column
- Remove is_setup_complete column (moves to setup state model)
- Remove setup_completed_at column (moves to setup state model)
- Remove setup_completed_by_id column (moves to setup state model)
- Update provider_type enum: change values from keycloak_bundled | keycloak_external | azure_entraid to oidc_generic | keycloak | azure_entraid

**Done when**: Model file updated with all field changes, type hints correct, column comments accurate. Model compiles without errors. Pre-existing references to removed/renamed columns are identified (for fix in later tasks).

---

### Task 1.2 — Add fields to IdentityProviderSetupState model

**File**: backend/app/db/models/identity_provider_setup_state.py

Add two boolean fields to the existing IdentityProviderSetupState model:
- user_provider_configured boolean, default false, not nullable
- agent_provider_configured boolean, default false, not nullable

**Done when**: Model updated with both fields, default values correct, model compiles without errors.

---

### Task 1.3 — Create IdentityProviderConfigAudit model

**File**: backend/app/db/models/identity_provider_config_audit.py (new)

Create a new model with:
- id UUID primary key, auto-generated
- config_id UUID FK to identity_provider_configs.id
- changed_by string (identity of admin making the change)
- change_type enum: created | updated | tested | deleted
- changed_fields JSONB (array of field names)
- previous_values JSONB (snapshot of previous values)
- changed_at datetime with timezone, server default now, not nullable
- Relationship to IdentityProviderConfig

**Done when**: Model file created, all fields with correct types, proper FK and relationship, compiles without errors. Registered in model __init__.py.

---

### Task 1.4 — Create SuperAdminCredentials model

**File**: backend/app/db/models/super_admin_credentials.py (new)

Create a new model with:
- id UUID primary key, auto-generated
- username string, not nullable, unique
- hashed_password string, not nullable (bcrypt or Argon2id hash)
- is_enabled boolean, default true, not nullable
- last_login_at datetime, nullable
- created_at datetime, server default now, not nullable
- updated_at datetime, server default now, not nullable, onupdate now

**Done when**: Model file created, all fields with correct types, compiles without errors. Registered in model __init__.py.

---

### Task 1.5 — Generate and apply Alembic migration

**File**: backend/alembic/versions/ (new auto-generated migration)

Generate an Alembic autogenerate migration capturing all Phase 1 changes. Review the generated migration for:
- Correct down_revision chain
- Enum type changes use postgresql.ENUM(..., create_type=False) (not sa.Enum())
- Renamed columns handled properly (Alembic may drop+add; verify no data loss for populated tables)
- Removed columns include proper downgrade path
- JSONB columns use postgresql.JSONB
- No parameterized DDL statements

Apply the migration and verify via alembic current.

**Done when**: Migration generated, reviewed, applied successfully. alembic current shows the new revision. All four models exist in the database with correct schema. Backend starts without schema errors.

---

## Phase 2 — Backend: OIDC Config Service and Provider Registry

### Task 2.1 — Create OIDCConfigService

**File**: backend/app/services/oidc_config_service.py (new)

Create a service class with:
- CRUD operations for IdentityProviderConfig entities (scoped by provider_scope)
- Client secret encryption at write (AES-256-GCM via existing credential_vault) and decryption at read
- OIDC Discovery validation: given issuer URL, fetch .well-known/openid-configuration, verify it returns valid JSON with required fields
- Audit logging: on create/update/delete, write an IdentityProviderConfigAudit record with changed_fields and previous_values snapshot
- Provider enable/disable toggle (set is_enabled)
- Validation: reject duplicate provider_scope entries (at most one active user and one agent config)

**Done when**: Service class created with all methods, encryption/decryption working, discovery validation calls real endpoints (with error handling for unreachable providers), audit records written on changes, unit-tested.

---

### Task 2.2 — Create OIDCProviderRegistry

**File**: backend/app/services/oidc_provider_registry.py (new)

Create a registry class with:
- In-memory cache of active OIDC provider configs loaded from database at startup
- Provider-resolution interface: get_user_provider() and get_agent_provider() returning IdentityProviderConfig or None
- Hot-reload: method to invalidate and reload all configs from database without service restart
- JWKS key cache per provider: stores fetched JWKS keys with per-provider TTL-based refresh (5-minute default)
- Per-provider OIDC Discovery caching (issuer to well-known config, invalidated on config change)
- Factory method to create a configured OIDCClient instance for any given provider

**Done when**: Registry class created with all methods, startup initialization wired in, hot-reload tested (update DB record, call reload, verify new config used), JWKS fetch per provider works, unit-tested.

---

### Task 2.3 — Refactor OIDCClient for multi-provider support

**File**: backend/app/core/oidc_client.py

Modify the existing OIDCClient to:
- Accept provider-specific configuration (issuer URL, client ID, algorithm, audience, scopes) via constructor or init method (no longer read from global settings)
- Support per-provider JWKS caching (remove module-level global cache; make it instance-level)
- Support per-provider audience validation
- Support claims mapping configuration (extract claims according to provider claim_mappings config)
- Keep backward-compatible singleton for existing callers during migration period
- Update validate_token to accept provider scope context (user vs agent) for proper provider resolution

**Done when**: OIDCClient refactored with instance-level config and caching, multi-provider JWKS works, audience per provider, claims mapping applied, existing callers still work, unit-tested.

---

## Phase 3 — Backend: Super Admin Auth Service and Auth Middleware

### Task 3.1 — Create SuperAdminAuthService

**File**: backend/app/services/super_admin_auth_service.py (new)

Create a service class with:
- Bootstrap: on first launch, seed SuperAdminCredentials from env vars (SUPER_ADMIN_USERNAME, SUPER_ADMIN_PASSWORD_HASH) with bcrypt hashing if plaintext provided
- Login: validate username/password against DB-stored hash, update last_login_at on success
- Token issuance: on successful login, issue a short-lived JWT (configurable expiry, default 15 minutes) signed with Control Center internal key; token includes scopes/claims for full platform access
- Enable/disable toggle: check is_enabled before allowing any login attempt
- Password update: allow password change via UI (hash new password, store in DB)
- Environment variable precedence: env var PARTHENON_SUPER_ADMIN_ENABLED overrides DB is_enabled at runtime; env var PARTHENON_SUPER_ADMIN_PASSWORD_HASH seeds/overrides the stored hash on startup

**Done when**: Service class created with all methods, login returns JWT, enable/disable respected, env var precedence works, unit-tested.

---

### Task 3.2 — Update startup sequence (main.py)

**File**: backend/app/main.py (modify startup)

Update the application startup sequence via dedicated async functions in ``main.py``:
- ``_seed_super_admin()`` — seeds super admin credentials from env vars after DB init
- ``_initialize_oidc_provider_registry()`` — loads OIDC provider configs from DB into in-memory registry
- ``_run_identity_yaml_migration()`` — one-time migration from config/identity.yaml to DB if no DB config exists
- Log startup state: which providers are active, super admin status
- OIDCProviderRegistry is stored as a module-level singleton accessed by middleware and services

**Done when**: Startup sequence runs correctly, super admin seeded, registry initialized, migration runs once, all startup logs informative. Backend starts without errors in all scenarios (fresh install, upgrade, no config).

---

### Task 3.3 — Update JWTAuthMiddleware to three-tier pipeline

**File**: backend/app/middleware/auth.py

Modify the middleware dispatch to implement:
1. Super admin tier (highest priority): Check for X-Super-Admin-Token header or dedicated token format; if present, validate via SuperAdminAuthService; if valid and super admin enabled, attach identity and proceed
2. OIDC tier: Extract Bearer token as before; determine provider type from request context or token claims; query OIDCProviderRegistry for active provider; validate JWT via OIDCClient with provider-specific config; fall back to trying both user and agent providers if ambiguous
3. Public fallback: Paths in PUBLIC_PATHS skip all auth checks (unchanged)

Additional changes:
- Add super admin login and token refresh endpoints to PUBLIC_PATHS
- When super admin is disabled, skip tier 1 entirely — only OIDC auth is attempted
- Add detailed auth failure logging: which tier failed, which provider was tried, reason

**Done when**: Middleware updated, three-tier pipeline works, super admin tokens validated, OIDC tokens validated per provider, public paths still skipped, auth failures logged with details, unit-tested.

---

## Phase 4 — Backend: System Config API and Setup Wizard Changes

### Task 4.1 — Create System Config identity provider API endpoints

**File**: backend/app/api/v1/system_config.py (new or modify existing)

Create REST endpoints requiring super admin or admin role:
- GET /api/v1/system/identity-providers — List all configured providers (user + agent), return config with client secret masked except last 4 chars in listing
- GET /api/v1/system/identity-providers/{scope} — Get single provider config by scope (user or agent)
- POST /api/v1/system/identity-providers — Create new provider config (body: provider_scope, provider_type, issuer_url, client_id, client_secret, scopes, claim_mappings)
- PUT /api/v1/system/identity-providers/{scope} — Update existing provider config
- DELETE /api/v1/system/identity-providers/{scope} — Delete provider config
- PATCH /api/v1/system/identity-providers/{scope}/toggle — Enable/disable provider (body: is_enabled bool)

All endpoints delegate to OIDCConfigService. On successful create/update, trigger OIDCProviderRegistry hot-reload.

**Done when**: All endpoints implemented, delegated to service layer, proper auth checks, request/response Pydantic models defined, error handling for duplicate scope, unit-tested.

---

### Task 4.2 — Create super admin management API endpoints

**File**: backend/app/api/v1/system_config.py (add to same file or sub-router)

Create endpoints:
- GET /api/v1/system/super-admin/status — Return is_enabled, username, last_login_at (no sensitive data)
- PATCH /api/v1/system/super-admin/toggle — Enable/disable super admin (body: is_enabled bool)
- PUT /api/v1/system/super-admin/password — Update super admin password (body: current_password, new_password)

All endpoints require super admin auth. Disabling super admin requires at least one active OIDC provider to exist (guard rail).

**Done when**: All endpoints implemented, guard rail enforced, password update hashes new password, unit-tested.

---

### Task 4.3 — Create OIDC test and test-login API endpoints

**File**: backend/app/api/v1/system_config.py (add to same file)

Create endpoints:
- POST /api/v1/system/identity-providers/test — Test OIDC connectivity for a provider config (body: same fields as create, not persisted). Steps: (1) fetch .well-known/openid-configuration, (2) validate issuer match, (3) verify JWKS endpoint reachability, (4) attempt token endpoint reachability check. Return per-step pass/fail with diagnostics.
- POST /api/v1/system/identity-providers/test-login — Initiate a real OIDC authorization code flow. Return redirect URL. Callback at GET /api/v1/system/identity-providers/test-login/callback completes the flow and returns decoded claims.
- GET /api/v1/system/identity-providers/test-login/status/{test_id} — Poll status of a running test-login session.

**Done when**: All endpoints implemented, test connection returns per-step diagnostics, test-login flow completes end-to-end, audit entries created for test attempts, unit-tested.

---

### Task 4.4 — Update Setup Wizard API

**File**: backend/app/api/v1/setup.py

Modify existing setup wizard endpoints:
- On setup completion, write OIDC configuration to IdentityProviderConfig table via OIDCConfigService instead of writing to config/identity.yaml
- Update IdentityProviderSetupState: set is_setup_complete = true, user_provider_configured = true, optionally agent_provider_configured = true
- Preserve existing wizard flow logic: bundled Keycloak detection, realm creation, client registration unchanged
- Add support for configuring independent agent provider during wizard (optional step)
- Update provider_type values to new enum (keycloak, azure_entraid, oidc_generic)
- Keep config/identity.yaml writing as fallback for backward compatibility during transition

**Done when**: Setup wizard writes to DB instead of YAML, all flow paths work (bundled Keycloak, external Keycloak, Azure EntraID, generic OIDC), setup state updated correctly, unit-tested.

---

### Task 4.5 — Update config loading

**File**: backend/app/core/config.py

Modify settings loading:
- On startup, after DB is available, load OIDC config from IdentityProviderConfig table (not from identity.yaml)
- If no DB config exists, attempt one-time read from config/identity.yaml for migration
- After migration, DB is source of truth; config/identity.yaml is no longer read for auth decisions
- Super admin config: load SUPER_ADMIN_ENABLED, SUPER_ADMIN_USERNAME, SUPER_ADMIN_PASSWORD_HASH from env vars
- Existing oidc_provider_url, jwt_algorithm, jwt_audience settings become deprecated (kept for backward compat during migration)

**Done when**: Settings class loads from DB, fallback to YAML works once, env var super admin config loaded, unit-tested.

---

## Phase 5 — Backend: Migration Utility (identity.yaml to DB)

### Task 5.1 — Create one-time migration service

**File**: backend/app/services/identity_yaml_migration.py (new)

Create a migration service:
- Read config/identity.yaml if it exists
- Parse provider config: oidc_provider_url maps to issuer_url, provider_type maps to new enum values, extract client_id, client_secret, realm_name (append to issuer_url for Keycloak)
- Create IdentityProviderConfig records for user scope (and agent scope if configured)
- Set is_enabled = true for migrated configs
- Set user_provider_configured = true in IdentityProviderSetupState
- Write audit entries with change_type = migrated
- Mark migration as complete (skip on subsequent starts if configs already exist)
- After successful migration, log that config/identity.yaml is no longer read
- Handle errors: if YAML is malformed, log warning and continue (super admin still available)

**Done when**: Service created, migration runs successfully on first start after upgrade, skips on subsequent starts, handles malformed YAML gracefully, audit entries created, unit-tested.

---

### Task 5.2 — Wire migration into startup sequence

**File**: backend/app/main.py (or startup events)

Trigger the migration service during startup:
- After DB session is available, before OIDCProviderRegistry initialization
- Only run if no IdentityProviderConfig rows exist for user scope
- Log migration outcome (success, skipped, error)
- On success, initialize OIDCProviderRegistry from the newly migrated DB records

**Done when**: Migration runs automatically on startup with no DB configs, skips when configs exist, logs clearly.

---

## Phase 6 — Frontend: System Config UI

### Task 6.1 — Create IdentityProviderConfigForm component

**File**: frontend/src/components/system/IdentityProviderConfigForm.tsx (new)

Build a reusable form component for editing a single OIDC provider configuration:
- Provider type selector dropdown (Generic OIDC, Keycloak, Azure EntraID)
- Issuer URL input with URL validation
- Client ID input
- Client secret input with show/hide toggle (password field)
- Scopes input (space-delimited, default: openid profile email)
- Claims mapping sub-form: textarea with `key:value` format entries, one per line
- Advanced options collapsible panel: endpoints and algorithm fields (auto-discovered via OIDC Discovery)
- Provider enable/disable toggle
- Test Configuration button (opens OIDCTestConfigModal)
- Test Login button (opens OIDCTestLoginModal)
- All text through t() i18n function

**Done when**: Component renders all fields, validation works, password toggle works, advanced panel expands/collapses, passes form data on save callback, uses i18n for all text.

---

### Task 6.2 — Create IdentityProvidersConfigPage

**File**: frontend/src/pages/system/IdentityProvidersConfigPage.tsx (new)

Build the page hosting both provider forms:
- Tab navigation: Identity Providers (active by default) and General Settings
- User Identity Provider section: uses IdentityProviderConfigForm, prefilled with current DB config, chip showing Configured / Not Configured
- Agent Identity Provider section: uses IdentityProviderConfigForm, Same as User Provider toggle that copies values and disables agent fields
- Info banner explaining independent providers
- Save button (calls System Config API, updates both providers, shows success toast)
- Loading state while fetching existing configs
- Error handling per dialog standard (dialogError state, try-catch)

Page component exists but is not yet registered in ``AppRouter`` for navigation. The Dashboard ``/system/identity-providers`` button navigates to this intended route.

**Done when**: Page renders both provider forms, loads existing config from API, saves both providers via API, Same as User toggle works, success/error feedback shown, i18n complete.

---

### Task 6.3 — Create SuperAdminConfigSection

**File**: frontend/src/components/system/SuperAdminConfigSection.tsx (new)

Build the super admin settings component (shown in General Settings tab):
- Enable/disable toggle switch with descriptive label
- Warning alert when disabled (potential lockout, how to re-enable)
- Info alert when enabled (advises disabling in production after OIDC verified)
- Disable confirmation modal: lists consequences, requires confirmation
- Password change form (current password, new password, confirm new password)
- Current status display (username, last login timestamp)
- Guard rail: if user tries to disable and no OIDC provider is configured, show error

**Done when**: Component renders toggle and password form, enable/disable with confirmation works, warnings shown correctly, guard rail prevents disable when no OIDC, i18n complete.

---

### Task 6.4 — Create OIDCTestConfigModal

**File**: frontend/src/components/system/OIDCTestConfigModal.tsx (new)

Build a modal dialog for testing OIDC connectivity:
- Pre-test state: shows issuer URL and client ID being tested, Run Test button
- Running state: spinner + animated step-by-step progress (fetch discovery, validate issuer, verify JWKS, validate credentials), each step shows pending/done/fail
- Result state: success banner with discovery details (JSON display), JWKS status, or error details with diagnostics
- Retry button
- Close button
- Accepts provider config as props (not persisted)
- Calls POST /api/v1/system/identity-providers/test

**Done when**: Modal renders all three states, step animations work, API call made, results displayed correctly, error states handled, i18n complete.

---

### Task 6.5 — Create OIDCTestLoginModal

**File**: frontend/src/components/system/OIDCTestLoginModal.tsx (new)

Build a modal for testing full OIDC login flow:
- Pre-test state: warning about full authorization flow redirect, shows endpoints, Initiate Test Login button
- Running state: spinner + animated step progress (initiating auth, completing callback, validating tokens, resolving identity)
- Result state: success banner + token response metadata, decoded ID token claims display
- Retry button, Close button
- Calls POST /api/v1/system/identity-providers/test-login; OAuth flow in popup window or redirect
- Polls GET /api/v1/system/identity-providers/test-login/status/{test_id} for results

**Done when**: Modal renders all states, OAuth redirect flow works, polling returns results, decoded claims displayed, error states handled, i18n complete.

---

### Task 6.6 — Create Dashboard identity provider status cards

**File**: frontend/src/pages/DashboardPage.tsx (modify existing)

Add three metric cards to the dashboard:
- User Identity Provider card: Configured (green dot + provider type name) or Not Configured (gray dot)
- Agent Identity Provider card: Configured (green dot) or Not Configured (gray dot)
- Super Admin Status card: Enabled (green dot) or Disabled (red dot)

Add quick action buttons for Configure Identity Providers, Test OIDC Configuration, Test OIDC Login.
Preserve existing setup wizard note card.

**Done when**: Dashboard shows three status cards with correct state, quick action buttons work, navigation works, i18n complete.

---

## Phase 7 — Frontend: Auth Changes

### Task 7.1 — Update LoginPage with three-state rendering

**File**: frontend/src/pages/auth/LoginPage.tsx (modify existing)

Implement three login states based on provider discovery:
1. Super Admin Only (no OIDC configured, super admin enabled): username/password form with info alert about initial setup
2. Both (OIDC configured + super admin enabled): OIDC login button + or divider + Login as Super Admin toggle revealing credential form
3. OIDC Only (OIDC configured, super admin disabled): only the OIDC login button

On app load, call GET /api/v1/system/identity-providers and GET /api/v1/system/super-admin/status to determine state. Store discovered providers in auth state.
Super admin login: POST to super admin login endpoint, receive JWT, store in auth state.
OIDC login: redirect to provider authorization endpoint (existing flow, unchanged).

**Done when**: Login page renders correctly in all three states, provider discovery on load, super admin login works, OIDC login flow unchanged, error states shown clearly, i18n complete.

---

### Task 7.2 — Update AuthContext and auth stores

**Files**: frontend/src/stores/AuthContext.tsx, frontend/src/stores/authStore.ts (modify existing)

Update auth state management:
- Add availableProviders to auth state: list of active identity providers discovered on load
- Add superAdminEnabled to auth state: boolean from system config
- Add isSuperAdmin to auth state: boolean for current session
- On app load (before login redirect), fetch available providers and super admin status
- Store super admin JWT separately from OIDC tokens (different auth source)
- Logout: clear both super admin and OIDC tokens
- Auth guards: super admin has full access (all routes); OIDC users have role-based access (existing)
- Provider changes while logged in: current session valid; next login uses new config

**Done when**: Auth state includes provider discovery info, super admin state tracked, token storage separated, logout clears both, auth guards correct.

---

## Phase 8 — Integration Testing and End-to-End Validation

### Task 8.1 — Backend integration tests: OIDCConfigService and OIDCProviderRegistry

**Files**: backend/tests/test_oidc_config_service.py (new), backend/tests/test_system_config_api.py (registry reload tested via API)

Test: CRUD operations for user/agent configs, duplicate scope rejection, secret encryption/decryption, discovery validation (mock HTTP), audit log creation, provider toggle, registry startup load and hot-reload (tested via system config API).

**Done when**: All tests pass with real database (test DB with applied migrations), coverage of all service methods.

---

### Task 8.2 — Backend integration tests: SuperAdminAuthService

**File**: backend/tests/test_super_admin_auth_service.py (new)

Test: credential seeding from env vars, valid/invalid login, login when disabled, JWT validation (signature, expiry, claims), password update, toggle, env var override.

**Done when**: All tests pass, env var precedence tested, JWT validity verified.

---

### Task 8.3 — Backend integration tests: Auth middleware pipeline

**File**: backend/tests/unit/test_auth_middleware.py (new)

Test: raw token stored on request state, public paths bypass middleware. Three-tier pipeline validation (super admin, OIDC per provider, public fallback) is tested implicitly through the system config API tests and super admin auth service tests.

**Done when**: All tests pass, token storage and public path bypass verified.

---

### Task 8.4 — Backend integration tests: identity.yaml to DB migration

**File**: backend/tests/test_identity_yaml_migration.py (new)

Test: migration from valid YAML (Keycloak, Azure EntraID), skip when DB already has configs, malformed YAML handled, missing file handled, setup state updated, audit entries created, configs enabled.

**Done when**: All tests pass, migration idempotent, error cases handled.

---

### Task 8.5 — Backend integration tests: System config API endpoints

**File**: backend/tests/test_system_config_api.py (new)

Test: CRUD for identity providers via API, invalid/duplicate scope rejected, provider toggle, super admin status, super admin toggle with guard rail, password update, OIDC test connection (mock), test-login flow (mock), unauthorized access rejected.

**Done when**: All tests pass, all endpoints covered, auth enforced, guard rail works.

---

### Task 8.6 — Frontend unit tests

**Files**: frontend/src/__tests__/ (new test files for new components)

Test: IdentityProviderConfigForm renders and validates, SuperAdminConfigSection toggle and confirmation, OIDCTestConfigModal states, OIDCTestLoginModal states, LoginPage three-state rendering, AuthContext provider discovery and state separation.

**Done when**: All tests pass via vitest, coverage adequate for new components.

---

### Task 8.7 — E2E tests for login flows

**File**: e2e/tests/ (new test files)

Test: login page detects no providers (super admin form), super admin valid/invalid login, OIDC only state, OIDC login flow (mock), both state, setup wizard trigger.
Include at least ONE real backend integration test (no mocks) for login and provider config.

**Done when**: E2E tests pass in Playwright, all login state combinations covered, at least one real backend integration test included.

---

### Task 8.8 — Manual end-to-end validation

Manual verification checklist:
1. Fresh install: super admin seed, configure Keycloak via UI, test connection, test login, OIDC user login
2. Fresh install with setup wizard: bundled Keycloak flow, config saved to DB
3. Upgrade: identity.yaml migrated, existing OIDC login still works
4. Agent identity provider independence: separate agent provider, token validation per provider
5. Super admin disable: login rejected, OIDC login still works
6. Super admin re-enable via env var override
7. Error states: unreachable OIDC provider shows clear error on login page
8. Audit log: IdentityProviderConfigAudit entries for all config changes

**Done when**: All scenarios verified manually with real Keycloak or test OIDC provider.

---

## Completion Checklist

- [ ] All Alembic migrations applied and verified
- [ ] Backend starts without errors in all scenarios (fresh, upgrade, no config)
- [ ] All backend unit/integration tests pass
- [ ] All frontend unit tests pass
- [ ] All E2E tests pass
- [ ] Super admin login works when enabled, rejected when disabled
- [ ] OIDC user login works with Keycloak and at least one generic OIDC provider
- [ ] Agent identity provider works independently from user provider
- [ ] Setup wizard works (bundled Keycloak + external OIDC)
- [ ] identity.yaml migration runs once and only once
- [ ] No config/identity.yaml editing required for production configuration
- [ ] All UI text uses i18n t() function
- [ ] All dialog API calls follow Dialog Error Handling Standard
- [ ] No hardcoded credentials anywhere
- [ ] Client secrets encrypted at rest in database
- [ ] Agent identity tokens never exposed to agent runtimes
