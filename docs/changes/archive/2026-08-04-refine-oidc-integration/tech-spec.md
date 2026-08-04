# Technical Specification: Refine OIDC Integration

## 1. Technical Overview

This change moves OIDC identity provider configuration from a static YAML file into a database-backed system with a web UI. The Control Center gains a three-tier authentication pipeline (super admin credentials, OIDC per-provider JWT validation, public fallback), an OIDC Provider Registry that hot-reloads configs and caches JWKS per provider, and a multi-provider OIDC client that validates tokens against independent user and agent identity providers. A built-in super admin account bootstrapped from environment variables provides guaranteed access for disaster recovery. The frontend adds a System Config UI for managing identity providers and super admin settings, and the login page dynamically adapts to show/hide the super admin credential form based on discovered provider state. A one-time migration service reads existing config/identity.yaml into the database on upgrade.

## 2. Component Breakdown

### Backend Components

| Component | Responsibility |
|-----------|---------------|
| **OIDCConfigService** | Full CRUD for IdentityProviderConfig entities; client secret encryption/decryption via credential_vault; OIDC Discovery endpoint validation; audit log creation on every change |
| **OIDCProviderRegistry** | In-memory cache of all active OIDC provider configs loaded from DB at startup; per-provider JWKS key caching with TTL refresh; hot-reload on config changes; factory for creating configured OIDCClient instances |
| **SuperAdminAuthService** | Seeds super admin credentials from env vars on first launch; validates username/password against DB-stored hash; issues short-lived internal JWT for UI access; supports enable/disable with env var override |
| **OIDCClient** (refactored) | Per-provider JWT validation with instance-level config (issuer, audience, algorithm, claims mapping); per-provider JWKS and discovery caching; claim extraction with configurable mapping |
| **JWTAuthMiddleware** (updated) | Three-tier pipeline: (1) super admin token validation, (2) per-provider OIDC JWT validation via registry, (3) public path bypass; detailed auth failure logging |
| **IdentityYamlMigration** | One-time service that reads config/identity.yaml, maps fields to the new model, writes IdentityProviderConfig records and audit entries, updates setup state |
| **BootstrapService / startup** | Seeds super admin credentials, initializes OIDCProviderRegistry, triggers one-time YAML migration, logs startup state |

### Frontend Components

| Component | Responsibility |
|-----------|---------------|
| **IdentityProviderConfigForm** | Reusable form for editing a single OIDC provider config (user or agent): provider type, issuer URL, client ID/secret, scopes, claims mapping, advanced options, test buttons |
| **IdentityProvidersConfigPage** | System Config page hosting both user and agent provider forms with independent configuration and a Same as User shortcut toggle |
| **SuperAdminConfigSection** | Enable/disable toggle with confirmation modal and guard rail; password change form; status display |
| **OIDCTestConfigModal** | Step-by-step connectivity test: discovery fetch, issuer validation, JWKS verification, credential check |
| **OIDCTestLoginModal** | Full OIDC authorization code flow test: redirect, callback, token validation, claims display |
| **LoginPage** (updated) | Three-state rendering based on provider discovery; super admin credential form; OIDC provider button |
| **AuthContext / authStore** (updated) | Provider discovery on load; super admin state tracking; separate token storage for super admin and OIDC |
| **DashboardPage** (updated) | Identity provider status cards and quick action buttons |

## 3. API Changes

### New Endpoints — System Config: Identity Providers

All under `/api/v1/system/identity-providers`, require super admin or admin role:

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/v1/system/identity-providers` | List all configured providers (user + agent), masked secrets in list |
| GET | `/api/v1/system/identity-providers/{scope}` | Get single provider by scope (user or agent) |
| POST | `/api/v1/system/identity-providers` | Create a new provider config; validates OIDC Discovery on save |
| PUT | `/api/v1/system/identity-providers/{scope}` | Update existing provider config |
| DELETE | `/api/v1/system/identity-providers/{scope}` | Delete a provider config |
| PATCH | `/api/v1/system/identity-providers/{scope}/toggle` | Enable or disable a provider without deleting config |

### New Endpoints — System Config: OIDC Testing

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/api/v1/system/identity-providers/test` | Test OIDC connectivity (discovery, JWKS, credentials); not persisted; returns per-step diagnostics |
| POST | `/api/v1/system/identity-providers/test-login` | Initiate OIDC authorization code flow for testing; returns redirect URL |
| GET | `/api/v1/system/identity-providers/test-login/callback` | OIDC callback for test login; exchanges code for tokens, validates claims |
| GET | `/api/v1/system/identity-providers/test-login/status/{test_id}` | Poll test-login session status and results |

### New Endpoints — System Config: Super Admin

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/v1/system/super-admin/status` | Returns is_enabled, username, last_login_at (no password) |
| PATCH | `/api/v1/system/super-admin/toggle` | Enable or disable super admin; guard rail requires at least one active OIDC provider |
| PUT | `/api/v1/system/super-admin/password` | Update super admin password (current + new password) |

### New Endpoints — Auth

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/api/v1/auth/super-admin/login` | Super admin credential login; returns short-lived internal JWT; public path |
| POST | `/api/v1/auth/super-admin/refresh` | Refresh a super admin JWT before expiry; public path |

### Modified Endpoints

| Method | Route | Change |
|--------|-------|--------|
| POST | `/api/v1/setup/identity` | Now writes to DB via OIDCConfigService instead of config/identity.yaml |
| GET | `/api/v1/setup/identity-status` | Now checks DB IdentityProviderConfig and IdentityProviderSetupState instead of YAML |
| POST | `/api/v1/setup/init` | Detection logic updated to check DB configs |

## 4. State Management

### Auth State Changes (authStore / AuthContext)

The auth state model gains three new properties:

| State Property | Type | Source | Description |
|---------------|------|--------|-------------|
| `availableProviders` | `Array<{scope, providerType, displayName}>` | `GET /api/v1/system/identity-providers` on app load | List of active OIDC providers; null/empty before discovery or if none configured |
| `superAdminEnabled` | `boolean` | `GET /api/v1/system/super-admin/status` on app load | Whether super admin login is currently permitted |
| `isSuperAdmin` | `boolean` | Set on super admin login; cleared on logout | Whether the current session is a super admin session |

### Token Storage

- Super admin JWT stored separately from OIDC tokens (different auth source, different expiry)
- On logout, both tokens are cleared
- Token storage mechanism remains the same (localStorage or memory as currently implemented)

### Login Page State Machine

The login page renders one of three states determined by the provider discovery results:

- **Super Admin Only**: availableProviders is empty AND superAdminEnabled is true
- **OIDC Only**: availableProviders has at least one entry AND superAdminEnabled is false
- **Both**: availableProviders has at least one entry AND superAdminEnabled is true
- **Setup Wizard Redirect**: availableProviders is empty AND superAdminEnabled is false

## 5. Data Access Patterns

### Client-Side (Frontend)

| Data | Access Pattern | Reason |
|------|---------------|--------|
| Available identity providers | `GET /api/v1/system/identity-providers` on app load (no auth required; public for login page) | The login page needs to know which providers to show before user is authenticated |
| Super admin status | `GET /api/v1/system/super-admin/status` on app load (no auth required; public for login page) | The login page needs to know whether to show super admin form |
| Provider config CRUD | `GET/POST/PUT/DELETE /api/v1/system/identity-providers/{scope}` — requires super admin or admin auth | Provider configuration is an administrative operation |
| Super admin management | `PATCH/PUT /api/v1/system/super-admin/*` — requires super admin auth | Only the super admin can manage the super admin account |
| OIDC test | `POST /api/v1/system/identity-providers/test*` — requires super admin or admin auth | Testing provider connectivity is an administrative validation step |
| User/agent login | `POST /api/v1/auth/*` — public endpoints | Authentication endpoints must be accessible before any auth state exists |

### Server-Side (Backend)

| Data | Access Pattern | Reason |
|------|---------------|--------|
| IdentityProviderConfig CRUD | Via OIDCConfigService (wraps SQLAlchemy session) | Only Control Center connects to DB; service layer handles encryption, validation, auditing |
| OIDCProviderRegistry | In-memory cache populated from DB at startup; hot-reloaded on config change | Per-request DB queries for provider config would add unacceptable latency to auth path |
| SuperAdminCredentials | Via SuperAdminAuthService (wraps SQLAlchemy session) | Credential validation, hashing, and env var seeding are auth-sensitive operations |
| JWKS keys | Cached per provider in OIDCProviderRegistry with TTL refresh | Prevents excessive external HTTP calls to identity providers |
| OIDC Discovery documents | Cached per issuer URL in OIDCProviderRegistry | Avoids fetching .well-known/openid-configuration on every token validation |
| Auth middleware | Stateless for OIDC path (token self-contained); stateful for super admin path (DB check) | Super admin JWT is short-lived internal token; DB check validates enable/disable state per request |

## 6. Code Reference Map

### Backend — Models

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `IdentityProviderConfig` | model | OIDC provider configuration entity (restructured) | backend/app/db/models/identity_provider_config.py |
| `IdentityProviderSetupState` | model | Platform bootstrap state sentinel (modified) | backend/app/db/models/identity_provider_setup_state.py |
| `IdentityProviderConfigAudit` | model | Immutable audit log for provider config changes (new) | backend/app/db/models/identity_provider_config_audit.py |
| `SuperAdminCredentials` | model | Built-in super admin credential store (new) | backend/app/db/models/super_admin_credentials.py |

### Backend — Core

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OIDCClient` | class | Multi-provider JWT validation with per-provider config and caching | backend/app/core/oidc_client.py |
| `OIDCError` | class | Exception raised on OIDC validation failure | backend/app/core/oidc_client.py |
| `get_oidc_client` | function | Factory returning configured OIDCClient for a given provider | backend/app/core/oidc_client.py |
| `get_settings` | function | Application settings (updated to load OIDC from DB) | backend/app/core/config.py |
| `CredentialVault` | class | AES-256-GCM encryption for client secrets | backend/app/core/credential_vault.py |

### Backend — Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OIDCConfigService` | class | CRUD, encryption, discovery validation, and audit logging for identity provider configs (new) | backend/app/services/oidc_config_service.py |
| `OIDCProviderRegistry` | class | In-memory cache of provider configs, JWKS keys, and discovery docs with hot-reload (new) | backend/app/services/oidc_provider_registry.py |
| `SuperAdminAuthService` | class | Super admin credential seeding, login, JWT issuance, enable/disable (new) | backend/app/services/super_admin_auth_service.py |
| `IdentityYamlMigration` | class | One-time migration from config/identity.yaml to database (new) | backend/app/services/identity_yaml_migration.py |
| (startup functions) | function | OIDC startup orchestration: `_seed_super_admin()`, `_run_identity_yaml_migration()`, `_initialize_oidc_provider_registry()` | backend/app/main.py |

### Backend — Middleware

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `JWTAuthMiddleware` | class | Three-tier auth pipeline (super admin, OIDC per provider, public fallback) | backend/app/middleware/auth.py |

### Backend — API Endpoints

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SystemConfigRouter` | router | System config API: identity providers CRUD, super admin management, OIDC testing (new) | backend/app/api/v1/system_config.py |
| `AuthRouter` | router | Super admin login + refresh endpoints (new) | backend/app/api/v1/system_config.py |
| `SetupRouter` | router | Setup wizard (modified: writes to DB instead of YAML) | backend/app/api/v1/setup.py |
| `IdentityBootstrapService` | service | Setup wizard backend (refactored to use OIDCConfigService and new model fields) | backend/app/services/identity/bootstrap_service.py |

### Backend — Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| (system config schemas) | module | Pydantic v2 request/response models for system config API: IdentityProviderConfigCreate/Update/Response, OIDCTestRequest/Response, SuperAdminStatusResponse, SuperAdminLoginRequest/Response, etc. | backend/app/schemas/system_config.py |

### Backend — Application Entry

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `app` | FastAPI | Application instance (startup event modified) | backend/app/main.py |

### Frontend — Components (New)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `IdentityProviderConfigForm` | component | Reusable OIDC provider config form | frontend/src/components/system/IdentityProviderConfigForm.tsx |
| `SuperAdminConfigSection` | component | Super admin enable/disable toggle and password form | frontend/src/components/system/SuperAdminConfigSection.tsx |
| `OIDCTestConfigModal` | component | Step-by-step OIDC connectivity test modal | frontend/src/components/system/OIDCTestConfigModal.tsx |
| `OIDCTestLoginModal` | component | Full OIDC authorization code flow test modal | frontend/src/components/system/OIDCTestLoginModal.tsx |

### Frontend — Pages (New/Modified)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `IdentityProvidersConfigPage` | page | System Config page hosting both provider forms (new; not yet wired into AppRouter) | frontend/src/pages/system/IdentityProvidersConfigPage.tsx |
| `LoginPage` | page | Login page with three-state rendering (modified) | frontend/src/pages/auth/LoginPage.tsx |
| `DashboardPage` | page | Dashboard with identity provider status cards (modified) | frontend/src/pages/DashboardPage.tsx |
| `SetupWizard` | page | Dev/demo setup wizard (modified: saves to DB) | frontend/src/pages/setup/SetupWizard.tsx |
| `OidcCallback` | page | OIDC callback handler (may need provider context) | frontend/src/pages/auth/OidcCallback.tsx |

### Frontend — State

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AuthContext` | context | Auth state provider (modified: provider discovery, super admin tracking) | frontend/src/stores/AuthContext.tsx |
| `authStore` | store | Auth state management (modified: separate token storage) | frontend/src/stores/authStore.ts |
| `useDialogErrorHandler` | hook | Dialog API error handling (used by new dialogs) | frontend/src/hooks/useDialogErrorHandler.ts |
| `systemConfigApi` | module | Typed API client for all system config + auth endpoints (new) | frontend/src/api/systemConfigApi.ts |
| `i18n/en.json` | locale | English translations for all new UI text (modified) | frontend/src/i18n/locales/en.json |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_oidc_config_service` | test | OIDCConfigService integration tests (new) | backend/tests/test_oidc_config_service.py |
| `test_super_admin_auth_service` | test | SuperAdminAuthService tests (new) | backend/tests/test_super_admin_auth_service.py |
| `test_auth_middleware` | test | Auth middleware basic tests (token storage, public path bypass) | backend/tests/unit/test_auth_middleware.py |
| `test_identity_yaml_migration` | test | YAML migration tests (new) | backend/tests/test_identity_yaml_migration.py |
| `test_system_config_api` | test | System config API tests (new) | backend/tests/test_system_config_api.py |
| (various) | test | Frontend component and auth state unit tests (new) | frontend/src/__tests__/ |
| (various) | test | E2E login flow tests (new) | e2e/tests/ |
