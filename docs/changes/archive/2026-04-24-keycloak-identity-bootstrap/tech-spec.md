# Keycloak Identity Bootstrap — Technical Specification

> **Config system note**: The `YamlSettingsSource` pattern introduced by this change becomes the **platform-wide configuration standard**. It is documented as the authoritative design in [`docs/master/technology/modules/foundation/tech-spec.md` — Configuration System](../../master/technology/modules/foundation/tech-spec.md#configuration-system). All future modules requiring configuration must follow that design.

## 1. Component Breakdown

### 1.1 YAML Settings Source (New)

| Attribute | Detail |
|---|---|
| **Location** | `backend/app/core/config.py` (inner class, not a separate module) |
| **Responsibility** | Load `config/identity.yaml` and feed its values into `Settings` as one layer in the pydantic-settings source chain — no separate loader module required. |
| **Key Behaviours** | Implemented as a `YamlSettingsSource(PydanticBaseSettingsSource)` inner class and wired in via `Settings.settings_customise_sources()`. Silent no-op when the file is absent (returns an empty dict). Raises `SettingsError` when the file exists but cannot be parsed. Field names in the YAML match `Settings` field names exactly, so no key-mapping layer is needed. Pydantic validates all loaded values against the `Settings` field types automatically — no manual validation code required. Secrets are never written to the YAML; only non-sensitive resolved settings (URLs, realm, client ID, provider type) are present. |

### 1.2 Config Layer — `Settings` (Changed)

| Attribute | Detail |
|---|---|
| **Location** | `backend/app/core/config.py` |
| **Responsibility** | Single source of truth for all runtime configuration. Merges YAML-derived OIDC values as defaults, then applies env-var overrides, using pydantic-settings' built-in source-priority mechanism. |
| **Key Behaviours** | Priority order (highest to lowest): environment variable → `config/identity.yaml` value → hard-coded default. Implemented by overriding `settings_customise_sources()` to insert `YamlSettingsSource` between env and init sources — no custom merge code required. Adds three new fields: `identity_provider_type` (using a new `ProviderType` enum shared with the identity schemas), `identity_realm` (string), and `identity_setup_complete` (bool). The `get_settings()` cache is invalidated by the Bootstrap Service after provisioning so subsequent reads see updated values. The `IdentityYamlConfig` type used for writing is a lightweight `BaseModel` whose fields are a subset of `Settings` fields — the same Pydantic field types and validators apply to both, eliminating duplication. |

### 1.3 Identity Bootstrap Service (New)

| Attribute | Detail |
|---|---|
| **Location** | `backend/app/services/identity/bootstrap_service.py` |
| **Responsibility** | Orchestrate the full identity provider setup lifecycle: detect setup state, provision Keycloak (or register an external OIDC provider), persist resolved settings to both the DB and YAML, and trigger an OIDC client reload. |
| **Key Behaviours** | Setup state is read from `IdentityProviderSetupState` (DB) first; YAML flag is the fallback for cases where the DB has not yet been reached. Provisioning is transactional: the DB commit and YAML write are co-ordinated so that a failure in either leaves the system in a consistent, un-configured state. Idempotent: re-running provisioning on an already-provisioned realm or OIDC client does not raise an error. Exposes three entry points: `check_setup_state()`, `provision_bundled_keycloak()`, and `provision_external_oidc()`. |

### 1.4 Keycloak Admin Client (New)

| Attribute | Detail |
|---|---|
| **Location** | `backend/app/services/identity/keycloak_admin_client.py` |
| **Responsibility** | Encapsulate all calls to the Keycloak Admin REST API behind typed async methods, hiding authentication, retry, and error mapping from the Bootstrap Service. |
| **Key Behaviours** | Authenticates to `POST /realms/master/protocol/openid-connect/token` using admin credentials to obtain an admin bearer token before any provisioning call. Retries on HTTP 503 with exponential back-off (up to 3 attempts). Raises a typed `KeycloakAdminError` with a machine-readable `error_code` field for all unrecoverable failures. Checks for existence before creation (idempotent helpers: `realm_exists`, `client_exists`). All HTTP I/O uses `httpx.AsyncClient`. |

### 1.5 YAML Config Writer (New — helper function, not a separate module)

| Attribute | Detail |
|---|---|
| **Location** | `backend/app/services/identity/bootstrap_service.py` (private helper) |
| **Responsibility** | Write resolved, non-sensitive OIDC settings to `config/identity.yaml` atomically after a successful provisioning run. |
| **Key Behaviours** | Accepts a typed `IdentityYamlConfig` (a `BaseModel` subclass) and calls `.model_dump(exclude_none=True)` to produce the YAML payload — Pydantic's serialization replaces a hand-written serializer. Writes to a `.tmp` sibling file then renames to the target path so a crash mid-write never corrupts the live file. `client_secret` is excluded from `IdentityYamlConfig` by design (field not present on the model) so no runtime filtering is needed. No separate `yaml_writer.py` module is created — the helper lives inside the Bootstrap Service where it is the only consumer. |

### 1.6 OIDC Client (Changed)

| Attribute | Detail |
|---|---|
| **Location** | `backend/app/core/oidc_client.py` |
| **Responsibility** | Fetch JWKS from the configured provider and validate JWT bearer tokens on every authenticated request. |
| **Key Behaviours** | Gains a `reload(provider_url, algorithm, audience)` method that updates internal state and clears the JWKS cache, enabling the Bootstrap Service to switch the active provider without restarting the process. A companion `reset_singleton()` function clears the module-level singleton so `get_oidc_client()` returns a freshly configured instance after reload. Provider URL is now resolved from `get_settings()` at call time rather than once at module import. |

### 1.7 Setup API Endpoints (New — added to existing setup router)

| Attribute | Detail |
|---|---|
| **Location** | `backend/app/api/v1/setup.py` |
| **Responsibility** | Expose unauthenticated REST endpoints that the frontend wizard and external tooling use to query setup state and trigger provisioning. |
| **Key Behaviours** | Both routes are outside the JWT authentication boundary (no `Depends(get_current_user)`). Guard against accidental re-provisioning: `POST /setup/identity` returns HTTP 409 if setup is already complete and no explicit re-configure flag is supplied. Errors from `KeycloakAdminError` are mapped to HTTP 502 with a structured body; Pydantic validation errors produce HTTP 422. |

### 1.8 CLI Entrypoint (New)

| Attribute | Detail |
|---|---|
| **Location** | `backend/app/cli.py` (invoked as `python -m app.cli`) |
| **Responsibility** | Provide a headless command-line path to run the full identity bootstrap without a browser or running frontend. |
| **Key Behaviours** | Accepts all provisioning parameters as CLI flags. Bootstraps its own async event loop and database session. Delegates all business logic to `IdentityBootstrapService` — no duplicated provisioning code. Prints a human-readable summary to stdout and exits with code 0 on success, 1 on any error. |

### 1.9 Setup Wizard UI (New)

| Attribute | Detail |
|---|---|
| **Location** | `frontend/src/features/setup/` and `frontend/src/pages/setup/SetupPage.tsx` |
| **Responsibility** | Guide an admin through provider selection and credential entry on first run, call the Setup API, and hand off to the login screen on success. |
| **Key Behaviours** | Wizard progression is controlled by a local step-index state machine; no global store is written during setup. All user-visible strings are i18next keys under the `setup` namespace (full key list in §5 below). The wizard is unreachable if setup is already complete (the redirect guard in `AppRouter` prevents this). Form validation happens client-side before the API call is made. |

### 1.10 First-Run Redirect Guard (New)

| Attribute | Detail |
|---|---|
| **Location** | `frontend/src/app/AppRouter.tsx` |
| **Responsibility** | On application mount, check identity status and redirect to `/setup` if the identity provider is not yet configured. |
| **Key Behaviours** | Calls `GET /api/v1/setup/identity-status` once at startup. If `setup_state === "NOT_CONFIGURED"`, all navigation resolves to `/setup` until the wizard completes. Once configured, normal auth flow resumes with no additional overhead (status is checked once and cached in component state). |

### 1.11 Docker Compose — Keycloak Service (Changed)

| Attribute | Detail |
|---|---|
| **Location** | `docker-compose.yml` |
| **Responsibility** | Run the bundled Keycloak container as a first-class compose service alongside Postgres, Redis, and the OTEL stack. |
| **Key Behaviours** | Uses the official `quay.io/keycloak/keycloak` image with a pinned version. Health check polls Keycloak's `/health/ready` HTTP endpoint. Backend service `depends_on` Keycloak being healthy. Mounts `infra/keycloak/realm-import/` for optional dev-time realm pre-import. Admin credentials read from `.env`. |

---

## 2. API Changes

### New Endpoint — Query Identity Status

| Field | Value |
|---|---|
| **Method** | GET |
| **Path** | `/api/v1/setup/identity-status` |
| **Authentication** | None — publicly accessible |
| **Request body** | None |
| **Success response (200)** | JSON object with three fields: `setup_state` (string enum — `"NOT_CONFIGURED"`, `"CONFIGURED"`, or `"IN_PROGRESS"`), `provider_type` (string or null — provider type when configured, otherwise null), `oidc_provider_url` (string or null — the active OIDC discovery base URL, null when unconfigured) |
| **Error responses** | 500 if the DB is unreachable |
| **Notes** | The frontend calls this on every app mount to decide whether to show the wizard or the normal login flow. It is intentionally read-only and stateless. |

### New Endpoint — Provision Identity Provider

| Field | Value |
|---|---|
| **Method** | POST |
| **Path** | `/api/v1/setup/identity` |
| **Authentication** | None — publicly accessible (guarded by setup-complete check inside the handler) |
| **Request body** | JSON object: `provider_type` (required string enum — `"keycloak_bundled"`, `"keycloak_external"`, or `"azure_entraid"`); `keycloak_url` (string, required for Keycloak types — base URL of the Keycloak instance); `realm_name` (string, required for Keycloak types); `client_id` (string, required); `admin_user` (string, required for bundled Keycloak — Keycloak master-realm admin username); `admin_password` (string, required for bundled Keycloak — Keycloak master-realm admin password); `initial_admin_password` (string, required for bundled Keycloak — password to set for the Parthenon admin user created in the realm); `client_secret` (string, required for external types — pre-existing OIDC client secret); `oidc_discovery_url` (string, required for external OIDC — the full `/.well-known/openid-configuration` URL); `force_reconfigure` (boolean, optional, default false — must be true to overwrite an existing configuration) |
| **Success response (200)** | JSON object: `success` (boolean true), `provider_type` (string), `oidc_provider_url` (string — the resolved OIDC base URL that the backend will now use), `realm_name` (string or null), `client_id` (string) |
| **Error response (409)** | Returned when setup is already complete and `force_reconfigure` is false. Body includes `detail` string explaining the conflict. |
| **Error response (502)** | Returned when Keycloak Admin API is unreachable or returns an unrecoverable error. Body includes `error_code` (string) and `detail` (human-readable explanation). |
| **Error response (422)** | Returned for request body validation failures (missing required field for the chosen provider type, malformed URL, etc.). |
| **Notes** | This endpoint performs real provisioning work that may take several seconds. The frontend should display a loading/progress indicator while the request is in flight. The response contains the fully resolved OIDC URL so the frontend can immediately redirect to the Keycloak login page without an extra status poll. |

### Existing Endpoint — No Change

`POST /api/v1/setup/init` (admin role and identity seeding) is unchanged. It remains in the same router file but is unrelated to identity provider provisioning.

---

## 3. Data Access Patterns

### YAML Settings Source

- **Reads** `config/identity.yaml` at Python process startup as part of the pydantic-settings source chain — no separate import or call needed; `Settings.settings_customise_sources()` orchestrates this automatically.
- **Does not write** — writing is the sole responsibility of the YAML write helper inside the Bootstrap Service.
- File path is resolved relative to the repository root; configurable via the `IDENTITY_YAML_PATH` environment variable for container deployments where the config directory is mounted at a different path.

### Config Layer (`Settings`)

- **Reads** YAML (via loader) + environment variables at startup.
- **Refreshes** when the Bootstrap Service calls `get_settings.cache_clear()` after provisioning — the next call to `get_settings()` re-reads both sources.
- **Does not write** to any persistence store.

### Identity Bootstrap Service

- **Reads** from `IdentityProviderSetupState` (single-row DB table) to determine setup state.
- **Reads** from `IdentityProviderConfig` (DB) to retrieve the active provider configuration for status reporting.
- **Writes** to `IdentityProviderConfig` (insert on first run, update on re-configure) within a SQLAlchemy async transaction.
- **Writes** to `IdentityProviderSetupState` (upsert) within the same transaction.
- **Writes** `config/identity.yaml` via the private YAML write helper (using `IdentityYamlConfig.model_dump()`) after the DB transaction commits successfully.
- **Calls** `credential_vault.encrypt()` to encrypt `client_secret` before inserting into the DB; the YAML file never contains the secret (`client_secret` is not a field on `IdentityYamlConfig`).

### Keycloak Admin Client

- **Reads** nothing from the application DB or YAML — operates solely against the Keycloak Admin REST API over HTTP.
- **Writes** to Keycloak: creates realm, OIDC clients, and initial admin user via Admin REST API calls authenticated with the Keycloak master-realm admin token.

### Setup API Endpoints

- **Reads** via `IdentityBootstrapService.check_setup_state()` and `get_current_config()` — both DB reads.
- **Writes** via `IdentityBootstrapService.provision_*()` — delegates all persistence to the service.
- No direct SQLAlchemy usage in the route handlers; all DB access is mediated by the service.

### Frontend Wizard

- **Reads** `GET /api/v1/setup/identity-status` — one HTTP call on mount to determine whether to show the wizard.
- **Writes** `POST /api/v1/setup/identity` — one HTTP call when the admin submits the final wizard step.
- No direct database or file access from the frontend.

### CLI Entrypoint

- **Reads** CLI flags passed by the operator; reads nothing from files or DB before provisioning begins.
- **Writes** via the same `IdentityBootstrapService` methods used by the API — identical persistence outcome.
- Prints the `ProviderSetupResult` summary to stdout; no file output of its own.

---

## 4. Config Schema — `config/identity.yaml`

The file lives at `config/identity.yaml` relative to the repository root. In container deployments the path is overridden with the `IDENTITY_YAML_PATH` environment variable.

All fields are optional: the file may be absent or partially populated; any missing field falls back to the corresponding environment variable or hard-coded default. Env-var values always win over YAML values when both are present.

The file intentionally contains **no secrets**. `client_secret` is encrypted and stored only in the database.

| Field | Type | Purpose |
|---|---|---|
| `provider_type` | String (enum) | Identifies the active identity provider. Accepted values: `keycloak_bundled`, `keycloak_external`, `azure_entraid`, `unconfigured`. |
| `oidc_provider_url` | String (URL) | Base URL of the OIDC provider, without a trailing slash. For Keycloak this is the realm URL (e.g., `http://localhost:8080/realms/parthenon`). Used by the OIDC client to build the JWKS URI. |
| `realm_name` | String | Keycloak realm name. Ignored for non-Keycloak providers. |
| `client_id` | String | OIDC client ID registered in the provider. Used by the frontend for the Authorization Code + PKCE flow. |
| `audience` | String | Expected `aud` claim value for JWT validation. Defaults to `parthenon` if absent. |
| `jwt_algorithm` | String | JWT signing algorithm. Defaults to `RS256`. |
| `setup_complete` | Boolean | `true` once the Bootstrap Service has successfully completed provisioning. Checked by the Config Layer on startup to populate `Settings.identity_setup_complete`. |
| `completed_at` | ISO-8601 datetime string | Timestamp when setup was last completed. Informational only; not used for access control. |

---

## 5. i18n Keys Reference

All frontend UI text introduced by this change must be defined in the `setup` namespace within the i18next translation files. No hardcoded strings are permitted in components.

| Key | Context / Surface |
|---|---|
| `setup.title` | Page title of the setup wizard |
| `setup.step.providerSelection.label` | Step label in the wizard stepper |
| `setup.step.keycloakConfig.label` | Step label — Keycloak configuration form |
| `setup.step.externalOidc.label` | Step label — external OIDC configuration form |
| `setup.step.verification.label` | Step label — in-progress provisioning |
| `setup.step.completion.label` | Step label — success confirmation |
| `setup.provider.bundledKeycloak` | Radio option label |
| `setup.provider.externalKeycloak` | Radio option label |
| `setup.provider.azureEntraId` | Radio option label |
| `setup.field.keycloakUrl` | Input field label |
| `setup.field.realm` | Input field label |
| `setup.field.clientId` | Input field label |
| `setup.field.adminUser` | Input field label |
| `setup.field.adminPassword` | Input field label |
| `setup.field.initialAdminPassword` | Input field label |
| `setup.field.oidcDiscoveryUrl` | Input field label |
| `setup.field.clientSecret` | Input field label |
| `setup.action.next` | Button label — advance to next step |
| `setup.action.back` | Button label — return to previous step |
| `setup.action.submit` | Button label — submit final step |
| `setup.action.retry` | Button label — retry after error |
| `setup.action.goToLogin` | Button label — navigate to login after success |
| `setup.status.configuring` | Status message shown during API call |
| `setup.status.success` | Success message on completion step |
| `setup.status.error` | Error heading on verification step |
| `setup.error.keycloakUnreachable` | Error detail when Keycloak cannot be reached (maps to HTTP 502) |
| `setup.error.alreadyConfigured` | Error detail when setup is already complete (maps to HTTP 409) |

---

## 6. Code Reference Map

### Files to Create

| File Path | Type | Purpose |
|---|---|---|
| `config/identity.yaml` | Config template | YAML config file for OIDC/identity settings; git-ignored for real deployments |
| `backend/app/services/identity/__init__.py` | Python package init | Makes `identity` a Python package |
| `backend/app/services/identity/bootstrap_service.py` | Python module | Identity Bootstrap Service — orchestrates first-run detection and provisioning |
| `backend/app/services/identity/keycloak_admin_client.py` | Python module | Keycloak Admin REST API client |
| `backend/app/db/models/identity_provider_config.py` | SQLAlchemy model | `IdentityProviderConfig` DB model |
| `backend/app/db/models/identity_provider_setup_state.py` | SQLAlchemy model | `IdentityProviderSetupState` DB model |
| `backend/app/schemas/identity_bootstrap.py` | Pydantic schemas | `ProviderSetupRequest`, `ProviderSetupResult`, `IdentityStatusResponse`, `SetupState` enum, `IdentityYamlConfig` (BaseModel used for YAML write serialization); `ProviderType` enum shared with `Settings` |
| `backend/app/cli.py` | Python CLI module | CLI entrypoint — `python -m app.cli setup-identity` |
| `backend/alembic/versions/<timestamp>_identity_bootstrap_models.py` | Alembic migration | Schema migration for all new DB models and the `idp_subject` column |
| `backend/tests/core/test_config.py` | Python unit test | `Settings` merge behaviour tests — YAML source, env override, absent file |
| `backend/tests/services/identity/test_bootstrap_service.py` | Python unit test | Bootstrap service tests |
| `backend/tests/services/identity/test_keycloak_admin_client.py` | Python unit test | Keycloak admin client tests |
| `backend/tests/api/v1/test_setup_identity.py` | Python unit test | Setup API endpoint tests |
| `backend/tests/integration/test_identity_setup_flow.py` | Python integration test | End-to-end API-layer setup flow |
| `frontend/src/api/setupApi.ts` | TypeScript module | Typed API client functions for Setup endpoints |
| `frontend/src/types/setup.ts` | TypeScript types | Interfaces and enums for Setup API request/response shapes |
| `frontend/src/features/setup/ProviderSelectionStep.tsx` | React component | Wizard step — provider type selection |
| `frontend/src/features/setup/KeycloakConfigStep.tsx` | React component | Wizard step — Keycloak configuration form |
| `frontend/src/features/setup/ExternalOidcConfigStep.tsx` | React component | Wizard step — external OIDC configuration form |
| `frontend/src/features/setup/VerificationStep.tsx` | React component | Wizard step — provisioning in progress / error |
| `frontend/src/features/setup/CompletionStep.tsx` | React component | Wizard step — success confirmation and login redirect |
| `frontend/src/features/setup/SetupWizard.tsx` | React component | Wizard container — step orchestration and API call |
| `frontend/src/features/setup/index.ts` | TypeScript barrel | Re-exports public wizard components |
| `frontend/src/pages/setup/SetupPage.tsx` | React page | Thin page wrapper rendering `SetupWizard` |
| `frontend/src/__tests__/api/setupApi.test.ts` | TypeScript unit test | `setupApi` function tests |
| `frontend/src/__tests__/features/setup/ProviderSelectionStep.test.tsx` | TypeScript unit test | Component test |
| `frontend/src/__tests__/features/setup/KeycloakConfigStep.test.tsx` | TypeScript unit test | Component test |
| `frontend/src/__tests__/features/setup/ExternalOidcConfigStep.test.tsx` | TypeScript unit test | Component test |
| `frontend/src/__tests__/features/setup/VerificationStep.test.tsx` | TypeScript unit test | Component test |
| `frontend/src/__tests__/features/setup/CompletionStep.test.tsx` | TypeScript unit test | Component test |
| `frontend/src/__tests__/features/setup/SetupWizard.test.tsx` | TypeScript unit test | Wizard container test |
| `infra/keycloak/realm-import/parthenon-realm.json` | Keycloak realm export | Minimal realm definition for dev-time import |
| `e2e/tests/setup-wizard.spec.ts` | Playwright E2E test | Full browser setup wizard flow |

### Files to Modify

| File Path | Type | What Changes |
|---|---|---|
| `backend/app/core/config.py` | Python module | Add `YamlSettingsSource` inner class; override `settings_customise_sources()` to insert it; add `identity_provider_type` (reuses `ProviderType` enum from schemas), `identity_realm`, `identity_setup_complete` fields |
| `backend/app/core/oidc_client.py` | Python module | Add `reload()` method and `reset_singleton()` function; resolve provider URL from `get_settings()` at call time rather than at import |
| `backend/app/db/models/__init__.py` | Python package init | Import and register the two new DB models |
| `backend/app/db/models/identity.py` | SQLAlchemy model | Add `idp_subject` column (nullable string, indexed) |
| `backend/app/api/v1/setup.py` | FastAPI router | Add `GET /setup/identity-status` and `POST /setup/identity` route handlers |
| `backend/app/main.py` | FastAPI app | Confirm `SetupRouter` is mounted; no change expected if already included |
| `frontend/src/app/AppRouter.tsx` | React router | Add `/setup` route (unauthenticated); add first-run redirect guard logic |
| `docker-compose.yml` | Docker Compose | Add `keycloak` service with health check, env config, and realm-import volume |
| `.github/prompts/start-app.prompt.md` | Prompt / runbook | Add Keycloak start and health-check wait steps |
| `.github/prompts/stop-app.prompt.md` | Prompt / runbook | Add Keycloak stop step |
