# Keycloak Identity Bootstrap — Implementation Plan

## Overview

Ordered, phase-gated task list for the `keycloak-identity-bootstrap` change.  
Each task includes a **Done when** condition that makes acceptance unambiguous.  
Complete phases in order; later phases depend on earlier ones.

---

## Task Checklist

### Phase 1 — Foundation
- [x] 1.1 — Create `config/` directory and empty `identity.yaml` template
- [x] 1.2 — Add `YamlSettingsSource` to `config.py` and update `Settings`
- [x] 1.3 — Verify `get_settings()` cache invalidation behaviour
- [x] 1.4 — DB model — `IdentityProviderConfig`
- [x] 1.5 — DB model — `IdentityProviderSetupState`
- [x] 1.6 — DB model — add `idp_subject` to `User` / `Identity`
- [x] 1.7 — Generate and validate Alembic migration

### Phase 2 — Identity Bootstrap Service
- [x] 2.1 — Define Pydantic schemas (`ProviderType`, `ProviderSetupRequest`, `ProviderSetupResult`, `IdentityStatusResponse`, `IdentityYamlConfig`)
- [x] 2.2 — Create the `IdentityBootstrapService` skeleton (`check_setup_state`, `get_current_config`)
- [x] 2.3 — Implement Keycloak Admin REST API client (`keycloak_admin_client.py`)
- [x] 2.4 — Implement `provision_bundled_keycloak` in `IdentityBootstrapService`
- [x] 2.5 — Implement `provision_external_oidc` in `IdentityBootstrapService`
- [x] 2.6 — YAML write helper (`_write_identity_yaml` using `model_dump`)
- [x] 2.7 — OIDC Client reload hook (`reload()` + `reset_singleton()`)

### Phase 3 — Setup API
- [x] 3.1 — `GET /api/v1/setup/identity-status` endpoint
- [x] 3.2 — `POST /api/v1/setup/identity` endpoint
- [x] 3.3 — Wire setup router into FastAPI app

### Phase 4 — CLI Entrypoint
- [x] 4.1 — Create CLI module (`backend/app/cli.py`) with `setup-identity` sub-command
- [x] 4.2 — Document CLI usage in `tech-spec.md`

### Phase 5 — Frontend Wizard
- [x] 5.1 — API client functions for Setup endpoints (`frontend/src/api/setupApi.ts`)
- [x] 5.2 — TypeScript types for Setup API (`frontend/src/types/setup.ts`)
- [x] 5.3 — Setup wizard step components (5 steps in `frontend/src/features/setup/`)
- [x] 5.4 — `SetupWizard` container component
- [x] 5.5 — Setup page and `/setup` route in `AppRouter.tsx`
- [x] 5.6 — First-run redirect guard in `AppRouter.tsx`

### Phase 6 — Infrastructure
- [x] 6.1 — Add `keycloak` service to `docker-compose.yml`
- [x] 6.2 — Create Keycloak realm import file (`infra/keycloak/realm-import/parthenon-realm.json`)
- [x] 6.3 — Update `.github/prompts/start-app.prompt.md` with Keycloak lifecycle steps
- [x] 6.4 — Update `.github/prompts/stop-app.prompt.md` with Keycloak stop step

### Phase 7 — Testing
- [x] 7.1 — Unit tests — `Settings` with `YamlSettingsSource` (`backend/tests/core/test_config.py`)
- [x] 7.2 — Unit tests — `IdentityBootstrapService` (`backend/tests/services/identity/test_bootstrap_service.py`)
- [x] 7.3 — Unit tests — Keycloak Admin Client (`backend/tests/services/identity/test_keycloak_admin_client.py`)
- [x] 7.4 — Unit tests — Setup API endpoints (`backend/tests/api/v1/test_setup_identity.py`)
- [x] 7.5 — Unit tests — Frontend `setupApi.ts` (`frontend/src/__tests__/api/setupApi.test.ts`)
- [x] 7.6 — Unit tests — Frontend wizard components (`frontend/src/__tests__/features/setup/`)
- [x] 7.7 — Unit tests — first-run redirect guard (`frontend/src/__tests__/app/AppRouter.test.tsx`)
- [x] 7.8 — Integration test — full setup flow (`backend/tests/integration/test_identity_setup_flow.py`)
- [x] 7.9 — E2E test — setup wizard (`e2e/tests/setup-wizard.spec.ts`)

---

## Phase 1 — Foundation

> Goal: YAML config loader is wired into `Settings`, DB models exist, and an Alembic migration covers all schema additions. Nothing breaks if `config/identity.yaml` is absent.

### 1.1 — Create `config/` directory and empty `identity.yaml` template

- Add `config/` at repository root (not inside `backend/`).
- Add `config/identity.yaml` as a template with every supported key present, all values empty or commented.
- Add `config/.gitkeep` so the directory is tracked; add `config/identity.yaml` to `.gitignore` so real values are never committed.
- **Done when** `config/` exists in the repo, `identity.yaml` is git-ignored, and `git status` shows no untracked sensitive files.

### 1.2 — Add `YamlSettingsSource` to `config.py` and update `Settings`

- Inside `backend/app/core/config.py`, add a `YamlSettingsSource` class that extends `PydanticBaseSettingsSource` from `pydantic-settings`.
- The source reads `config/identity.yaml` (path configurable via `IDENTITY_YAML_PATH` env var), parses it with `yaml.safe_load`, and returns the resulting dict. When the file is absent, it returns an empty dict — no error. When the file exists but cannot be parsed, it raises `SettingsError`.
- Override `Settings.settings_customise_sources()` to insert `YamlSettingsSource` between `env_settings` and `init_settings`, giving env vars the highest priority and the YAML the second-highest. No custom merge code is needed — pydantic-settings handles the merge automatically.
- Add three new fields to `Settings`: `identity_provider_type` (a `ProviderType` enum, default `unconfigured`; the enum is defined in `backend/app/schemas/identity_bootstrap.py` and imported here), `identity_realm` (string, nullable), and `identity_setup_complete` (bool, default `False`).
- No separate `yaml_config.py` module is created; the YAML source lives entirely in `config.py`.
- **Done when** unit tests (using `tmp_path` fixtures, no real file I/O at the OS level) verify: YAML-only → fields populated; env-only → fields populated; YAML+env → env wins; neither present → defaults returned; absent YAML file → no error; invalid YAML → `SettingsError`.

### 1.3 — Ensure `get_settings()` invalidation is documented and safe

- Confirm that `get_settings.cache_clear()` (from `@lru_cache`) is the mechanism the Bootstrap Service uses to force a re-read of the merged config after writing `identity.yaml`.
- No code changes needed if the existing `@lru_cache` decorator is in place; this task is verification only.
- **Done when** a unit test confirms that calling `get_settings.cache_clear()` and then `get_settings()` with an updated `identity.yaml` returns the new values.

### 1.4 — DB model — `IdentityProviderConfig`

- Create `backend/app/db/models/identity_provider_config.py` with a SQLAlchemy 2 declarative model.
- Fields: `id` (UUID PK), `provider_type` (string enum), `oidc_provider_url` (string), `client_id` (string), `client_secret` (string, nullable — stored encrypted), `realm_name` (string, nullable), `audience` (string, nullable), `is_setup_complete` (boolean, default False), `setup_completed_at` (datetime, nullable), `setup_completed_by_id` (FK → `identities.id`, nullable), `created_at`, `updated_at`.
- Register the model in `backend/app/db/models/__init__.py`.
- **Done when** the model imports without error and `alembic check` detects it as a pending migration.

### 1.5 — DB model — `IdentityProviderSetupState`

- Create `backend/app/db/models/identity_provider_setup_state.py` with a single-row sentinel model.
- Fields: `id` (UUID PK), `is_setup_complete` (boolean, default False), `completed_at` (datetime, nullable), `completed_by_id` (FK → `identities.id`, nullable).
- Register in `__init__.py`.
- **Done when** the model imports without error and `alembic check` detects it as a pending migration.

### 1.6 — DB model — add `idp_subject` to `User` / `Identity`

- Add `idp_subject` (string, nullable, indexed) to the existing identity/user model at `backend/app/db/models/identity.py` (or `user.py` per actual file name).
- **Done when** the column is declared and `alembic check` detects the modification.

### 1.7 — Generate and validate Alembic migration

- Run `alembic revision --autogenerate -m "identity_bootstrap_models"`.
- Review the generated script: confirm all three model changes appear (new tables + new column); add `server_default` for boolean flags if autogenerate omits them.
- Run `alembic upgrade head` against a local test database.
- **Done when** `alembic upgrade head` completes without error; `alembic downgrade -1` reverses cleanly; `alembic check` reports no pending changes.

---

## Phase 2 — Identity Bootstrap Service

> Goal: A fully testable service class that detects setup state, provisions Keycloak via Admin REST API, and persists results to both the DB and `identity.yaml`.

### 2.1 — Define Pydantic schemas for bootstrap inputs, outputs, and YAML config

- Create `backend/app/schemas/identity_bootstrap.py`.
- Define a `ProviderType` enum (`keycloak_bundled`, `keycloak_external`, `azure_entraid`, `unconfigured`) — this enum is imported by `Settings` in `config.py` for the `identity_provider_type` field, so it is the single definition shared across config and API schemas.
- Define strongly-typed request and response models: `ProviderSetupRequest` (provider type using `ProviderType`, Keycloak URL, admin credentials, realm name, desired client ID, admin user password), `ProviderSetupResult` (success flag, resolved OIDC URL, client ID, realm, error message on failure), `IdentityStatusResponse` (setup state enum, provider type, OIDC URL).
- Define `IdentityYamlConfig` as a `BaseModel` whose fields are exactly the non-sensitive OIDC settings written to `identity.yaml` (`provider_type`, `oidc_provider_url`, `realm_name`, `client_id`, `audience`, `jwt_algorithm`, `setup_complete`, `completed_at`). No `client_secret` field — excluded by design, not by runtime filtering. The Bootstrap Service calls `.model_dump(exclude_none=True)` on this model to produce the YAML payload.
- **Done when** all schemas import without error, `ProviderType` is successfully imported and used in `Settings`, and `mypy` strict checks pass.

### 2.2 — Create the `IdentityBootstrapService` skeleton

- Create `backend/app/services/identity/bootstrap_service.py`.
- Implement `check_setup_state(db) -> SetupState` (enum: `NOT_CONFIGURED`, `CONFIGURED`, `IN_PROGRESS`) — queries `IdentityProviderSetupState` first, then falls back to YAML flag.
- Implement `get_current_config(db) -> IdentityProviderConfig | None` — returns the active DB row.
- **Done when** unit tests mock the DB session and confirm all three `SetupState` outcomes are returned correctly.

### 2.3 — Implement Keycloak Admin REST API client (`keycloak_admin_client.py`)

- Create `backend/app/services/identity/keycloak_admin_client.py`.
- Encapsulate all Keycloak Admin REST API calls behind typed methods: `authenticate(base_url, admin_user, admin_password) -> AdminToken`, `create_realm(token, realm_name, display_name)`, `create_oidc_client(token, realm_name, client_id, redirect_uris) -> ClientSecret`, `create_user(token, realm_name, username, password, roles)`, `realm_exists(token, realm_name) -> bool`, `client_exists(token, realm_name, client_id) -> bool`.
- All HTTP calls use `httpx.AsyncClient`; retry on 503 up to 3 times with exponential back-off.
- Raise a typed `KeycloakAdminError` (not bare `Exception`) on unrecoverable failures.
- **Done when** unit tests with `respx` (or `httpx` mock transport) verify happy-path and error-path for each method; no real Keycloak needed.

### 2.4 — Implement provisioning logic in `IdentityBootstrapService`

- Add `provision_bundled_keycloak(db, request: ProviderSetupRequest) -> ProviderSetupResult` to the service.
- Steps: validate Keycloak reachability → authenticate with admin credentials → create realm (idempotent) → create API client → create UI client → create initial admin user → write resolved values to DB (`IdentityProviderConfig`) → mark `IdentityProviderSetupState.is_setup_complete = True` → persist `identity.yaml` → reload OIDC client.
- Each step is transactionally safe: if provisioning fails mid-way, the DB transaction is rolled back and `identity.yaml` is not written.
- **Done when** unit tests cover: full happy path (all Keycloak calls succeed), Keycloak unreachable (returns error result), idempotent re-run (realm already exists, still succeeds).

### 2.5 — Implement external OIDC provider registration

- Add `provision_external_oidc(db, request: ProviderSetupRequest) -> ProviderSetupResult` to the service.
- Steps: fetch `/.well-known/openid-configuration` to validate the provider URL → store client ID + secret in `IdentityProviderConfig` (secret encrypted via `credential_vault.py`) → mark setup complete → write `identity.yaml` → reload OIDC client.
- **Done when** unit tests verify: valid OIDC discovery URL → success result; unreachable URL → error result; secret stored encrypted.

### 2.6 — YAML write helper (private, inside `bootstrap_service.py`)

- Add a private `_write_identity_yaml(config: IdentityYamlConfig) -> None` helper inside `bootstrap_service.py` — no separate module needed.
- The helper calls `config.model_dump(exclude_none=True)` to get the serializable dict, then `yaml.safe_dump()` to produce the YAML string, and writes atomically via a `.tmp` rename.
- Because `IdentityYamlConfig` has no `client_secret` field, no runtime secret filtering is required — Pydantic's model definition enforces this structurally.
- **Done when** unit tests verify atomic write behaviour (crash simulation via monkeypatching), and that no secret fields appear in the written output regardless of what the caller passes.

### 2.7 — OIDC Client reload hook

- Add a `reload(provider_url: str, algorithm: str, audience: str) -> None` method to `OIDCClient` in `backend/app/core/oidc_client.py`.
- The method updates the instance's provider URL fields and calls `clear_cache()` so the next token validation fetches fresh JWKS.
- Update `get_oidc_client()` to expose a `reset_singleton()` function for use by the bootstrap service after reload.
- **Done when** unit tests verify that `clear_cache()` is called and the new URL is reflected on the instance.

---

## Phase 3 — Setup API

> Goal: Two unauthenticated REST endpoints that the wizard calls, wired to the Bootstrap Service, with full validation and error handling.

### 3.1 — `GET /setup/identity-status` endpoint

- Add the route to `backend/app/api/v1/setup.py` (the existing setup router).
- No auth required; FastAPI dependency injection brings in `DbSession` and `IdentityBootstrapService`.
- Returns a typed response: `IdentityStatusResponse` with fields `setup_state` (enum string), `provider_type` (string or null), `oidc_provider_url` (string or null).
- **Done when** unit tests with `AsyncClient` (no auth header) confirm: unconfigured state → `setup_state: "NOT_CONFIGURED"`, configured state → `setup_state: "CONFIGURED"` with populated provider fields.

### 3.2 — `POST /setup/identity` endpoint

- Add the route to the same router.
- Accepts `ProviderSetupRequest` as request body; calls the appropriate service method based on `provider_type`.
- Returns `ProviderSetupResult` on success; maps `KeycloakAdminError` to HTTP 502 with a structured error body; maps validation errors to HTTP 422.
- Once setup completes, the endpoint must not allow re-configuration without an authenticated re-configure flag (guard against accidental overwrite).
- **Done when** unit tests cover: bundled Keycloak success → 200 with result; external OIDC success → 200; Keycloak unreachable → 502; already configured + no re-configure flag → 409 Conflict.

### 3.3 — Wire router into FastAPI app

- Confirm the `SetupRouter` is included in `backend/app/main.py` under the `/api/v1` prefix.
- Ensure the new routes appear in the OpenAPI schema at `/docs` without requiring authentication.
- **Done when** `GET /api/v1/setup/identity-status` returns 200 when the app starts with an unconfigured DB.

---

## Phase 4 — CLI Entrypoint

> Goal: `python -m app.cli setup-identity` runs the full bootstrap flow headlessly, producing the same outcome as the wizard.

### 4.1 — Create CLI module (`backend/app/cli.py`)

- Use `argparse` or `click` (whichever is already a dependency or lightest to add).
- Expose one sub-command: `setup-identity` with arguments: `--provider-type`, `--keycloak-url`, `--realm`, `--client-id`, `--admin-user`, `--admin-password`, `--initial-admin-password`, `--external-oidc-url`.
- The command bootstraps an async event loop, creates a DB session, instantiates `IdentityBootstrapService`, calls the appropriate provision method, and prints a structured summary to stdout.
- Exit code 0 on success, 1 on any provisioning error.
- **Done when** running `python -m app.cli setup-identity --help` prints usage without error; a unit test using `subprocess` or direct invocation validates exit code 0 for a mocked happy path.

### 4.2 — Document CLI usage

- Add a `## CLI Usage` section to this change's `tech-spec.md` or a separate `cli-reference.md` (whichever fits best).
- **Done when** the documentation lists all flags, their defaults, and two example invocations (bundled Keycloak, external OIDC).

---

## Phase 5 — Frontend Wizard

> Goal: The React app detects unconfigured state at startup and presents a multi-step setup wizard; once complete, it redirects to the login screen.

### 5.1 — API client functions for Setup endpoints

- Create `frontend/src/api/setupApi.ts` with two typed async functions: `getIdentityStatus() -> IdentityStatusResponse` and `postSetupIdentity(request: ProviderSetupRequest) -> ProviderSetupResult`.
- Use `fetch` or the project's existing HTTP utility; derive base URL from `API_CONFIG`.
- **Done when** unit tests with `msw` (or vitest mocks) confirm correct HTTP method, path, and typed return on success and error.

### 5.2 — TypeScript types for Setup API

- Create `frontend/src/types/setup.ts` with interfaces/enums matching the backend Pydantic schemas: `SetupState`, `ProviderType`, `IdentityStatusResponse`, `ProviderSetupRequest`, `ProviderSetupResult`.
- **Done when** all types are used (no `any`) in `setupApi.ts` and wizard components, and `tsc --noEmit` passes.

### 5.3 — Setup wizard step components

- Create `frontend/src/features/setup/` directory.
- Implement the following step components (all text via `i18next` — see i18n note below):
  - `ProviderSelectionStep` — radio group for provider type (Bundled Keycloak / External Keycloak / Azure EntraID).
  - `KeycloakConfigStep` — form fields for Keycloak URL, realm name, client ID, admin credentials, initial admin password.
  - `ExternalOidcConfigStep` — form fields for OIDC discovery URL, client ID, client secret.
  - `VerificationStep` — shows spinner during API call; success or error state with retry option.
  - `CompletionStep` — confirmation message and "Go to Login" button.
- **Done when** each step renders without console errors; Storybook stories (or vitest snapshot tests) exist for each component.
- **i18n keys required** (all under the `setup` namespace): `setup.title`, `setup.step.providerSelection.label`, `setup.step.keycloakConfig.label`, `setup.step.externalOidc.label`, `setup.step.verification.label`, `setup.step.completion.label`, `setup.provider.bundledKeycloak`, `setup.provider.externalKeycloak`, `setup.provider.azureEntraId`, `setup.field.keycloakUrl`, `setup.field.realm`, `setup.field.clientId`, `setup.field.adminUser`, `setup.field.adminPassword`, `setup.field.initialAdminPassword`, `setup.field.oidcDiscoveryUrl`, `setup.field.clientSecret`, `setup.action.next`, `setup.action.back`, `setup.action.submit`, `setup.action.retry`, `setup.action.goToLogin`, `setup.status.configuring`, `setup.status.success`, `setup.status.error`, `setup.error.keycloakUnreachable`, `setup.error.alreadyConfigured`.

### 5.4 — `SetupWizard` container component

- Create `frontend/src/features/setup/SetupWizard.tsx` — orchestrates step progression, holds wizard state, and calls `postSetupIdentity` on the final step.
- Uses a local state machine (step index + form data accumulator); no global store needed.
- **Done when** unit tests cover: step navigation forward/back; API call triggered on final submit; error state shown when API returns error; success navigates to completion step.

### 5.5 — Setup page and route

- Create `frontend/src/pages/setup/SetupPage.tsx` — thin wrapper that renders `SetupWizard`.
- Add a `/setup` route to `AppRouter.tsx` that is accessible without authentication.
- **Done when** navigating to `/setup` in the browser renders the wizard; the route does not require a JWT.

### 5.6 — First-run redirect guard

- Update `AppRouter.tsx` (or `ProtectedRoute.tsx`) to call `getIdentityStatus()` on mount.
- If `setup_state === "NOT_CONFIGURED"`, redirect any unauthenticated visit to `/setup` instead of the normal login flow.
- If already configured, behave exactly as before (no regression).
- **Done when** unit tests confirm: NOT_CONFIGURED → redirect to `/setup`; CONFIGURED → no redirect (normal flow).

---

## Phase 6 — Infrastructure

> Goal: `docker-compose up` brings up a working Keycloak instance alongside Postgres, Redis, and the OTEL stack; start/stop prompts cover Keycloak lifecycle.

### 6.1 — Add `keycloak` service to `docker-compose.yml`

- Add a `keycloak` service using the official `quay.io/keycloak/keycloak` image (pin a specific version).
- Configure: `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` from environment or `.env`; port mapping (`8080:8080`); startup command `start-dev`; health check on `/health/ready`.
- Mount `infra/keycloak/realm-import/` as a volume for optional realm pre-import.
- Add `depends_on` so the backend service waits for Keycloak's health check before starting.
- **Done when** `docker compose up keycloak` starts Keycloak and the health check passes within 60 seconds.

### 6.2 — Keycloak realm import file

- Create `infra/keycloak/realm-import/parthenon-realm.json` — a minimal Keycloak realm export defining: realm name `parthenon`, two OIDC clients (`parthenon-api`, `parthenon-ui`), standard token settings.
- This file is used for development convenience and CI; production provisioning is done by the Bootstrap Service.
- **Done when** `docker compose up keycloak` with the import volume mount auto-imports the realm and it is visible in the Keycloak admin console.

### 6.3 — Update `.github/prompts/start-app.prompt.md`

- Add a step to start the `keycloak` Docker container (or confirm it is running) before starting the backend.
- Add a health-check wait step that polls Keycloak's `/health/ready` before proceeding.
- **Done when** following the start prompt results in Keycloak running and healthy before the backend API starts.

### 6.4 — Update `.github/prompts/stop-app.prompt.md`

- Add a step to stop the `keycloak` container when tearing down the stack.
- **Done when** following the stop prompt brings down Keycloak cleanly with no orphan processes.

---

## Phase 7 — Testing

> Goal: Sufficient automated test coverage to prevent regressions and satisfy the acceptance criteria from the PRD.

### 7.1 — Unit tests — `Settings` with `YamlSettingsSource`

- File: `backend/tests/core/test_config.py`.
- Scenarios: absent YAML file → defaults returned; valid YAML all fields → fields populated; valid YAML partial fields → missing fields fall back to env or default; env var present alongside YAML → env var wins; invalid YAML syntax → `SettingsError` raised; `get_settings.cache_clear()` + updated YAML → new values reflected.
- All tests use `tmp_path` fixtures; no real `config/identity.yaml` on disk.
- **Done when** all scenarios pass with no real file I/O side effects; coverage on the `YamlSettingsSource` path ≥ 90%.

### 7.2 — Unit tests — `IdentityBootstrapService`

- File: `backend/tests/services/identity/test_bootstrap_service.py`.
- Scenarios: `check_setup_state` — all three states; `provision_bundled_keycloak` — happy path, Keycloak unreachable, idempotent re-run; `provision_external_oidc` — valid discovery URL, invalid URL.
- All external calls mocked (DB via `AsyncMock`, HTTP via `respx`).
- **Done when** all scenarios pass; coverage on `bootstrap_service.py` ≥ 85%.

### 7.3 — Unit tests — Keycloak Admin Client

- File: `backend/tests/services/identity/test_keycloak_admin_client.py`.
- Scenarios: successful auth, expired/invalid admin token, each provisioning method happy path and error path, retry logic on 503.
- HTTP mocked with `respx`.
- **Done when** all scenarios pass; coverage on `keycloak_admin_client.py` ≥ 85%.

### 7.4 — Unit tests — Setup API endpoints

- File: `backend/tests/api/v1/test_setup_identity.py`.
- Scenarios: `GET /setup/identity-status` — NOT_CONFIGURED, CONFIGURED; `POST /setup/identity` — bundled success, external success, Keycloak error → 502, already configured → 409.
- Use `AsyncClient` with app lifespan; mock `IdentityBootstrapService`.
- **Done when** all scenarios pass.

### 7.5 — Unit tests — Frontend `setupApi.ts`

- File: `frontend/src/__tests__/api/setupApi.test.ts`.
- Scenarios: `getIdentityStatus` — 200 success, network error; `postSetupIdentity` — 200 success, 502 error, 409 conflict.
- HTTP mocked with `msw` or `vi.fn()`.
- **Done when** all scenarios pass with `vitest`.

### 7.6 — Unit tests — Frontend wizard components

- Files: `frontend/src/__tests__/features/setup/` (one file per step component + `SetupWizard`).
- Scenarios per component: renders without error, form validation rejects empty fields, next/back navigation, submit triggers API call, error state displayed, success state navigates forward.
- **Done when** all scenarios pass with `vitest` + React Testing Library.

### 7.7 — Unit tests — first-run redirect guard

- File: `frontend/src/__tests__/app/AppRouter.test.tsx`.
- Scenarios: NOT_CONFIGURED status → redirects to `/setup`; CONFIGURED status → renders normal app.
- **Done when** both scenarios pass.

### 7.8 — Integration test — full setup flow (API layer)

- File: `backend/tests/integration/test_identity_setup_flow.py`.
- Starts with a clean DB (real Postgres via `pytest-asyncio` + `alembic upgrade head`).
- Mocks Keycloak Admin REST API with `respx` (no real Keycloak container).
- Calls `POST /setup/identity` end-to-end; asserts `IdentityProviderSetupState.is_setup_complete = True` in DB; asserts `identity.yaml` written with correct fields.
- **Done when** the test passes in CI without a running Keycloak container.

### 7.9 — E2E test — setup wizard (browser)

- File: `e2e/tests/setup-wizard.spec.ts`.
- Requires a running stack (Postgres + Keycloak + Backend + Frontend) with a clean DB.
- Steps: navigate to app root → wizard appears → select Bundled Keycloak → fill form → submit → success step shown → redirect to login.
- **Done when** the Playwright test passes in the CI E2E job.

---

## Completion Checklist

Before marking this change `status: complete` in `.change.yaml`:

- [ ] All Phase 1–6 tasks are done
- [ ] All Phase 7 tests pass in CI (`pytest` for backend, `vitest` for frontend, `playwright` for E2E)
- [ ] `mypy` (strict) passes on all new Python files
- [ ] `tsc --noEmit` passes on all new TypeScript files
- [ ] No hardcoded UI strings — all text uses `i18next` keys from Phase 5.3
- [ ] `docs/master/` documents updated per the list in `architecture.md`
- [ ] `.change.yaml` `status` updated to `implemented`
