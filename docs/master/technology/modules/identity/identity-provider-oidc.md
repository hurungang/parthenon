# Identity — Identity Providers & OIDC

[← Identity tech spec hub](tech-spec.md) · [RBAC, permissions & resource types](rbac-and-permissions.md)

Identity-provider bootstrap, the database-backed OIDC provider registry, the
three-tier authentication pipeline, and super admin.

## Components

### Backend — OIDC Configuration & Auth Pipeline

| Component | Description |
|-----------|-------------|
| `OIDCConfigService` | Full CRUD for `IdentityProviderConfig` entities; client secret encryption/decryption via `CredentialVault`; OIDC Discovery endpoint validation; audit log creation on every config change |
| `OIDCProviderRegistry` | In-memory cache of all active OIDC provider configs loaded from DB at startup; per-provider JWKS key caching with TTL refresh; hot-reload on config change; factory for creating configured `OIDCClient` instances |
| `Super Admin Auth` (functions) | Reads super admin credentials from environment variables; validates username/password against bcrypt-hashed password via `super_admin_login()`; issues short-lived internal JWT via `super_admin_reissue()` for UI access; `super_admin_enabled()` reads enable/disable state from env var |
| `OIDCClient` (refactored) | Multi-provider JWT validation with per-provider config (issuer, audience, algorithm, claims mapping); per-provider JWKS and discovery caching; claim extraction with configurable mapping |
| `JWTAuthMiddleware` (updated) | Three-tier pipeline: (1) super admin token validation, (2) per-provider OIDC JWT validation via registry, (3) public path bypass; detailed auth failure logging; also syncs user/groups after OIDC validation |
| `CredentialVault` | AES-256-GCM encryption for OIDC client secrets stored in the database |

### Frontend — System Config OIDC UI

| Component | Description |
|-----------|-------------|
| `IdentityProviderConfigForm` | Reusable form for editing a single OIDC provider config (user or agent): provider type, issuer URL, client ID/secret, scopes, claims mapping, advanced options, test buttons |
| `IdentityProvidersConfigPage` | System Config page hosting both user and agent provider forms with independent configuration and a "Same as User" shortcut toggle (not yet wired into `AppRouter`) |
| `SuperAdminConfigSection` | Enable/disable toggle with confirmation modal and guard rail; password change form; status display |
| `OIDCTestConfigModal` | Step-by-step connectivity test modal: discovery fetch, issuer validation, JWKS verification, credential check |
| `OIDCTestLoginModal` | Full OIDC authorization code flow test: redirect, callback, token validation, claims display |
| `LoginPage` (updated) | Provider-discovery-driven rendering: password sign-in card, OIDC button, and discreet super-admin entry — the removed setup-wizard redirect state is gone (see the multi-tenancy module for the current tenancy-aware sign-in flow) |
| `AuthContext` / `authStore` (updated) | Provider discovery on app load (`availableProviders`, `superAdminEnabled`); super admin state tracking (`isSuperAdmin`); separate token storage for super admin and OIDC sessions |
| `DashboardPage` (updated) | Identity provider status cards and quick action buttons |
| `systemConfigApi` | Typed API client module for all system config endpoints (identity providers CRUD, super admin management, OIDC testing) and auth endpoints (super admin login/refresh) |

---

---

## API Endpoints

### System Config — Identity Providers (`/api/v1/system/identity-providers`)
All require super admin or admin role:

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/system/identity-providers` | JWT (admin) | List all configured providers (user + agent), masked secrets |
| `GET` | `/api/v1/system/identity-providers/{scope}` | JWT (admin) | Get single provider by scope (user or agent) |
| `POST` | `/api/v1/system/identity-providers` | JWT (admin) | Create a new provider config; validates OIDC Discovery on save |
| `PUT` | `/api/v1/system/identity-providers/{scope}` | JWT (admin) | Update existing provider config |
| `DELETE` | `/api/v1/system/identity-providers/{scope}` | JWT (admin) | Delete a provider config |
| `PATCH` | `/api/v1/system/identity-providers/{scope}/toggle` | JWT (admin) | Enable or disable a provider without deleting config |

### System Config — OIDC Testing

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/v1/system/identity-providers/test` | JWT (admin) | Test OIDC connectivity (discovery, JWKS, credentials); not persisted; returns per-step diagnostics |
| `POST` | `/api/v1/system/identity-providers/test-login` | JWT (admin) | Initiate OIDC authorization code flow for testing; returns redirect URL |
| `GET` | `/api/v1/system/identity-providers/test-login/callback` | None | OIDC callback for test login; exchanges code for tokens, validates claims |
| `GET` | `/api/v1/system/identity-providers/test-login/status/{test_id}` | JWT (admin) | Poll test-login session status and results |

### System Config — Super Admin

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/system/super-admin/status` | JWT (admin) | Returns `is_enabled`, `username`, `last_login_at` (no password) |
| `PATCH` | `/api/v1/system/super-admin/toggle` | JWT (admin) | Enable or disable super admin; guard rail requires at least one active OIDC provider before disabling |
| `PUT` | `/api/v1/system/super-admin/password` | JWT (admin) | Update super admin password (current + new password) |

### Auth — Super Admin Login
Public endpoints for super admin credential-based access:

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/v1/auth/super-admin/login` | None | Super admin credential login; returns short-lived internal JWT |
| `POST` | `/api/v1/auth/super-admin/refresh` | None | Refresh a super admin JWT before expiry |

### Setup (Modified)

| Method | Path | Auth | Change |
|--------|------|------|--------|
| `POST` | `/api/v1/setup/identity` | None | Now writes to DB via `OIDCConfigService` instead of `config/identity.yaml` |
| `GET` | `/api/v1/setup/identity-status` | None | Now checks DB `IdentityProviderConfig` and `IdentityProviderSetupState` instead of YAML |
| `POST` | `/api/v1/setup/init` | None | Detection logic updated to check DB configs |

---

---

## Legacy `config/identity.yaml` (removed)
OIDC provider configuration is database-backed (`identity_provider_configs`, managed via System Config / Tenant Settings). The former `config/identity.yaml` file no longer exists and is not written or read at runtime; a one-time migration path exists only for upgrades from releases that shipped it. Environment variables always override any file-based value (see [foundation tech-spec — Configuration System](../foundation/tech-spec.md#configuration-system)).

---

---

## Code Reference Map

### Identity Bootstrap — Backend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SetupRouter` | router | Public setup endpoints: `POST /setup/init`, `GET /setup/identity-status`, `POST /setup/identity` | `backend/app/api/v1/setup.py` |
| `IdentityBootstrapService` | service | Orchestrates provider detection, provisioning, DB+YAML persistence, and OIDC client reload | `backend/app/services/identity/bootstrap_service.py` |
| `IdentityBootstrapService.provision_bundled_keycloak` | method | Provisions bundled Keycloak: validate reachability, create realm, create clients, create admin user, persist to DB | `backend/app/services/identity/bootstrap_service.py` |
| `IdentityBootstrapService.provision_external_oidc` | method | Registers external OIDC provider: fetch discovery doc, persist to DB, mark setup complete | `backend/app/services/identity/bootstrap_service.py` |
| `IdentityBootstrapService.check_setup_state` | method | Determines current setup state from DB or YAML fallback | `backend/app/services/identity/bootstrap_service.py` |
| `RealmManager` | class | Manages agent realm lifecycle in Keycloak — create, validate, apply token policies; `initialize_agent_realm` is now called exclusively by the setup tool, not at runtime startup | `backend/app/services/identity/realm_manager.py` |
| `RealmManager.initialize_agent_realm` | method | Creates agent realm, applies token policies, registers OIDC client — called only by setup tool | `backend/app/services/identity/realm_manager.py` |
| `RealmManager.validate_agent_realm` | method | **NEW** — checks if agent realm exists via OIDC discovery endpoint; used by Control Center startup validation | `backend/app/services/identity/realm_manager.py` |
| `RealmManager.realm_exists` | method | Checks if a specific realm exists in Keycloak (existing, retained) | `backend/app/services/identity/realm_manager.py` |
| `RealmManagerError` | exception | Typed exception raised when realm operations fail | `backend/app/services/identity/realm_manager.py` |
| `KeycloakAdminClient` | service | Typed async wrapper for Keycloak Admin REST API with auth, retry, and idempotent helpers; admin credentials restricted to setup-time invocation | `backend/app/services/identity/keycloak_admin_client.py` |
| `KeycloakAdminError` | exception | Typed exception with `error_code` field raised on unrecoverable Keycloak Admin API failures | `backend/app/services/identity/keycloak_admin_client.py` |
| `IdentityProviderConfig` | model | SQLAlchemy model for active provider config (type, OIDC URL, realm, client ID, encrypted secret) | `backend/app/db/models/identity_provider_config.py` |
| `IdentityProviderSetupState` | model | SQLAlchemy single-row model tracking setup state enum | `backend/app/db/models/identity_provider_setup_state.py` |
| `ProviderSetupRequest` | schema | Pydantic request for `POST /setup/identity`; includes `provider_type`, URLs, credentials, `force_reconfigure` | `backend/app/schemas/identity_bootstrap.py` |
| `ProviderSetupResult` | schema | Pydantic response for `POST /setup/identity`; resolved OIDC URL, provider type, realm, client ID | `backend/app/schemas/identity_bootstrap.py` |
| `IdentityStatusResponse` | schema | Pydantic response for `GET /setup/identity-status`; `setup_state`, `provider_type`, `oidc_provider_url` | `backend/app/schemas/identity_bootstrap.py` |
| `SetupState` | enum | String enum: `NOT_CONFIGURED`, `IN_PROGRESS`, `CONFIGURED` | `backend/app/schemas/identity_bootstrap.py` |
| `ProviderType` | enum | String enum: `keycloak_bundled`, `keycloak_external`, `azure_entraid`, `unconfigured`; shared with `Settings` | `backend/app/schemas/identity_bootstrap.py` |
| `setup-identity` CLI command | CLI | Headless bootstrap via `python -m app.cli setup-identity`; delegates to `IdentityBootstrapService` | `backend/app/cli.py` |
| identity bootstrap migration | migration | Alembic migration creating `IdentityProviderConfig`, `IdentityProviderSetupState` tables and `idp_subject` column | `backend/alembic/versions/002_identity_bootstrap_models.py` |

### Identity Bootstrap — Frontend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AppRouter` | component | The removed pre-auth setup wizard route and first-run `/setup` redirect guard; OIDC is configured post-sign-in via System Config / Tenant Settings | `frontend/src/app/AppRouter.tsx` |

### Identity Bootstrap — Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_config` | unit test | `Settings` merge behaviour: YAML source, env override, absent file | `backend/tests/core/test_config.py` |
| `test_bootstrap_service` | unit test | `IdentityBootstrapService` provisioning paths and idempotency | `backend/tests/services/identity/test_bootstrap_service.py` |
| `test_keycloak_admin_client` | unit test | `KeycloakAdminClient` auth, retry, and error-mapping behaviour | `backend/tests/services/identity/test_keycloak_admin_client.py` |
| `test_setup_identity` | unit test | Setup API endpoint success, 409, 502, and 422 response paths | `backend/tests/api/v1/test_setup_identity.py` |

### OIDC Configuration & Auth Pipeline — Database Models

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `IdentityProviderConfig` | model | OIDC provider configuration entity (restructured for multi-provider support) | `backend/app/db/models/identity_provider_config.py` |
| `IdentityProviderSetupState` | model | Platform bootstrap state sentinel (modified for DB-backed checks) | `backend/app/db/models/identity_provider_setup_state.py` |
| `IdentityProviderConfigAudit` | model | Immutable audit log for provider config changes | `backend/app/db/models/identity_provider_config_audit.py` |
| `_resolve_credentials` | function | Resolves the built-in super admin credential pair from environment variables (`SUPER_ADMIN_USERNAME`, `SUPER_ADMIN_PASSWORD`/`SUPER_ADMIN_PASSWORD_HASH`, `PARTHENON_SUPER_ADMIN_ENABLED`); no DB model exists | `backend/app/services/super_admin_auth_service.py` |

### OIDC Configuration & Auth Pipeline — Core

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OIDCClient` | class | Multi-provider JWT validation with per-provider config and caching | `backend/app/core/oidc_client.py` |
| `OIDCError` | class | Exception raised on OIDC validation failure | `backend/app/core/oidc_client.py` |
| `get_oidc_client` | function | Factory returning configured `OIDCClient` for a given provider | `backend/app/core/oidc_client.py` |
| `get_settings` | function | Application settings (updated to load OIDC from DB) | `backend/app/core/config.py` |
| `CredentialVault` | class | AES-256-GCM encryption for OIDC client secrets | `backend/app/core/credential_vault.py` |

### OIDC Configuration & Auth Pipeline — Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OIDCConfigService` | class | CRUD, encryption, discovery validation, and audit logging for identity provider configs | `backend/app/services/oidc_config_service.py` |
| `OIDCProviderRegistry` | class | In-memory cache of provider configs, JWKS keys, and discovery docs with hot-reload | `backend/app/services/oidc_provider_registry.py` |
| `super_admin_login` | function | Authenticates super admin via username + bcrypt-hashed password; returns JWT | `backend/app/services/super_admin_auth_service.py` |
| `validate_super_admin_token` | function | Validates super admin JWT token; returns decoded claims dict | `backend/app/services/super_admin_auth_service.py` |
| `super_admin_enabled` | function | Returns whether super admin auth is enabled via env var | `backend/app/services/super_admin_auth_service.py` |
| `super_admin_reissue` | function | Re-issues JWT for an existing super admin session | `backend/app/services/super_admin_auth_service.py` |
| (startup functions) | function | OIDC startup orchestration: `_seed_super_admin()`, `_run_identity_yaml_migration()`, `_initialize_oidc_provider_registry()` | `backend/app/main.py` |

### OIDC Configuration & Auth Pipeline — Middleware

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `JWTAuthMiddleware` | class | Three-tier auth pipeline: super admin token → per-provider OIDC JWT → public fallback; also syncs user/groups after OIDC validation | `backend/app/middleware/auth.py` |

### OIDC Configuration & Auth Pipeline — API Routes

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SystemConfigRouter` | router | System config API: identity providers CRUD, super admin management, OIDC testing | `backend/app/api/v1/system_config.py` |
| `AuthRouter` | router | Super admin login + refresh endpoints | `backend/app/api/v1/system_config.py` |
| `SetupRouter` (modified) | router | Setup wizard endpoints (modified: writes to DB instead of YAML) | `backend/app/api/v1/setup.py` |
| `IdentityBootstrapService` (refactored) | service | Setup wizard backend (refactored to use `OIDCConfigService` and new model fields) | `backend/app/services/identity/bootstrap_service.py` |

### OIDC Configuration & Auth Pipeline — Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| (system config schemas) | module | Pydantic v2 request/response models for system config API: `IdentityProviderConfigCreate`/`Update`/`Response`, `OIDCTestRequest`/`Response`, `SuperAdminStatusResponse`, `SuperAdminLoginRequest`/`Response`, etc. | `backend/app/schemas/system_config.py` |

### OIDC Configuration & Auth Pipeline — Frontend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `IdentityProviderConfigForm` | component | Reusable OIDC provider config form | `frontend/src/components/system/IdentityProviderConfigForm.tsx` |
| `SuperAdminConfigSection` | component | Super admin enable/disable toggle and password form | `frontend/src/components/system/SuperAdminConfigSection.tsx` |
| `OIDCTestConfigModal` | component | Step-by-step OIDC connectivity test modal | `frontend/src/components/system/OIDCTestConfigModal.tsx` |
| `OIDCTestLoginModal` | component | Full OIDC authorization code flow test modal | `frontend/src/components/system/OIDCTestLoginModal.tsx` |
| `IdentityProvidersConfigPage` | page | System Config page hosting both provider forms; with multi-tenancy it manages the ROOT tenant's provider when signed into the root workspace | `frontend/src/pages/system/IdentityProvidersConfigPage.tsx` |
| `IdentityProviderConfigForm` (default role) | component (modified) | Gains the `default_tenant_role` select — the JIT default tenant role applied on first sign-in via this provider | `frontend/src/components/system/IdentityProviderConfigForm.tsx` |
| `LoginPage` | page | Login page with provider-discovery-driven rendering (password sign-in card, OIDC button, discreet super-admin entry); tenancy-aware workspace flows live in the multi-tenancy module | `frontend/src/pages/auth/LoginPage.tsx` |
| `DashboardPage` | page | Dashboard with identity provider status cards | `frontend/src/pages/DashboardPage.tsx` |
| `OidcCallback` | page | OIDC callback handler; with multi-tenancy it performs verify-then-bind tenant binding and a tenant-resolved token exchange (see multi-tenancy module) | `frontend/src/pages/auth/OidcCallback.tsx` |
| `AuthContext` | context | Auth state provider (modified: provider discovery, super admin tracking) | `frontend/src/stores/AuthContext.tsx` |
| `authStore` | store | Auth state management (modified: separate token storage for super admin and OIDC) | `frontend/src/stores/authStore.ts` |
| `useDialogErrorHandler` | hook | Dialog API error handling (used by new dialogs) | `frontend/src/hooks/useDialogErrorHandler.ts` |
| `systemConfigApi` | module | Typed API client for all system config + auth endpoints | `frontend/src/api/systemConfigApi.ts` |
| `en.json` (system config + auth UI text) | locale | English translations for all new UI text in identity provider config, super admin, and OIDC test modals | `frontend/src/i18n/locales/en.json` |

### OIDC Configuration & Auth Pipeline — Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_oidc_config_service` | test | `OIDCConfigService` integration tests | `backend/tests/test_oidc_config_service.py` |
| `test_super_admin_auth_service` | test | Super admin auth function tests | `backend/tests/test_super_admin_auth_service.py` |
| `test_auth_middleware` | test | Auth middleware tests (token storage, public path bypass) | `backend/tests/unit/test_auth_middleware.py` |
| `test_system_config_api` | test | System config API tests | `backend/tests/test_system_config_api.py` |
| (various) | test | Frontend component and auth state unit tests | `frontend/src/__tests__/` |
| (various) | test | E2E login flow tests | `e2e/tests/` |
