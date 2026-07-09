# Technical Specification: Production-Ready Configuration

## 1. Technical Overview

This change separates identity provider bootstrapping from the runtime application, consolidates environment setup into a single `setup/` directory, and extends environment-variable-driven configuration to all infrastructure connections. The Control Center no longer auto-provisions Keycloak realms at startup — instead, it validates that external dependencies are reachable and fails fast with actionable error messages. A new unified setup CLI, distinct from the runtime application containers, handles all environment bootstrapping tasks (identity provider provisioning, database seeding, certificate authority initialization) as an operator-invoked operation.

Configuration resolution follows a strict priority: environment variables → YAML configuration files → built-in defaults. Every infrastructure connection (PostgreSQL, Redis, OIDC provider, OTEL exporters) is configurable via per-component environment variables, enabling production deployments that use enterprise-managed infrastructure without editing configuration files or rebuilding container images.

## 2. Component Breakdown

### 2.1 Settings Configuration (`backend/app/core/config.py`)

**Responsibility**: Central configuration model for all services. Extended with per-component environment variable fields for PostgreSQL, Redis, and OIDC provider connections. Maintains the existing priority order (env var > .env > YAML > default) and adds startup logging of which source was resolved for each connection. Keycloak admin credential fields are explicitly excluded from this model — they are only consumed by the setup tool.

### 2.2 Control Center Startup Validator (`backend/app/main.py`)

**Responsibility**: Validates external dependencies at startup instead of provisioning them. Three validation checks run in sequence: PostgreSQL reachability (lightweight query), Keycloak realm existence (OIDC discovery document fetch), and Redis reachability (PING). Each failure produces a logged error message identifying the missing dependency and the expected configuration variable. Replaces the former `_initialize_agent_realm()` auto-provisioning call.

### 2.3 Agent Runtime Startup Validator (`backend/app/agent_runtime/main.py`)

**Responsibility**: Validates Control Center reachability before attempting certificate bootstrap. Sends a health check request to the configured `CONTROL_CENTER_URL` with retry logic. Fails fast if the certificate authority is not available, preventing opaque certificate errors later in the lifecycle.

### 2.4 Communication Hub Startup Validator (`backend/app/communication_hub/main.py`)

**Responsibility**: Validates both Control Center reachability (for certificate bootstrap) and Redis reachability (for message brokering) at startup. The existing `_verify_redis_connectivity()` is retained; a new Control Center health check is added before certificate operations.

### 2.5 Realm Manager (`backend/app/services/identity/realm_manager.py`)

**Responsibility**: Manages agent realm lifecycle in the bundled Keycloak provider. Existing `initialize_agent_realm()` method (create realm, apply token policies, register OIDC client) remains intact but is invoked exclusively by the setup tool. A new `validate_agent_realm()` method checks realm existence via the OIDC discovery endpoint — used by Control Center startup validation. Admin credential access is restricted to setup-time invocation only.

### 2.6 Identity Bootstrap Service (`backend/app/services/identity/bootstrap_service.py`)

**Responsibility**: Orchestrates full identity provider setup for both bundled Keycloak and external OIDC providers. Called by the setup tool's `setup identity` sub-command. Handles realm creation, client registration, admin user provisioning, DB persistence, YAML config writing, and OIDC client reload. No changes to its internal logic; only the call site changes from startup-time to setup-time.

### 2.7 Setup CLI (`setup/main.py`, `setup/identity.py`, `setup/database.py`, `setup/certificates.py`, `setup/dev.py`)

**Responsibility**: Unified entry point for all environment bootstrapping. Provides sub-commands (`identity`, `database`, `certificates`, `dev`, `verify`) that replace the collection of ad-hoc scripts in `scripts/`. Each operation is idempotent — running it on an already-initialized environment detects existing state and reports it. Built-in help (`--help`) documents all options. The `dev` sub-command replicates the full behavior of the former `scripts/init-local-dev.py`.

### 2.8 CLI (`backend/app/cli.py`)

**Responsibility**: Existing backend CLI with `setup-identity` and `seed-skills` sub-commands. These remain available for backward compatibility but delegate to the consolidated setup tool where applicable.

### 2.9 Docker Compose Configuration (`docker-compose.yml`)

**Responsibility**: Service orchestration for bundled deployments. Updated to remove Keycloak admin credentials from the Control Center service environment and to add an optional setup service (with `profiles: [setup]`) that runs the consolidated setup command and exits. Control Center retains its Keycloak health check dependency for ordering but no longer receives or uses admin credentials.

### 2.10 Environment Variables Reference (`.env.example`)

**Responsibility**: Single source of truth for all supported environment variables. Expanded with per-component variables for PostgreSQL, Redis, OIDC, Keycloak admin (setup-only), OTEL, and service bootstrap keys. Each variable documents its purpose, default value, and which services consume it.

## 3. API Changes

No new or modified REST API endpoints are introduced by this change. The existing health check endpoints (`GET /health` on Control Center port 8000, Agent Runtime port 8001, Communication Hub port 8002) are used internally for startup validation checks between services — their response format is unchanged.

The setup tool operates as a CLI and does not expose any HTTP API. It directly accesses the Keycloak Admin REST API, PostgreSQL, and the Control Center CA storage layer during bootstrapping, but none of these are exposed as new public endpoints.

The existing Control Center API endpoint for identity provider setup (`POST /api/v1/setup/identity`) may continue to exist for wizard-based setup flows but is not modified by this change.

## 4. State Management

No frontend state changes are introduced. The `has_ui_changes` scope flag is `false`.

The only state changes are internal to the backend:
- The runtime Control Center no longer maintains Keycloak admin credential state in memory
- The setup tool reads credentials from environment variables and discards them after use
- Startup validation state (pass/fail per dependency) is logged but not persisted

## 5. Data Access Patterns

### 5.1 Runtime Services

- **Control Center**: Direct database access (PostgreSQL via SQLAlchemy async sessions) for all internal data; OIDC discovery document fetched from Keycloak at startup for validation; Redis accessed via async Redis client for caching and pub/sub.
- **Agent Runtime**: No direct database access. All data fetched from Control Center REST API over mTLS. Validates Control Center reachability via health check endpoint.
- **Communication Hub**: No direct database access. All data fetched from Control Center REST API over mTLS. Direct Redis access for message brokering (pub/sub). Validates both Control Center and Redis reachability at startup.

### 5.2 Setup Tool

- Direct Keycloak Admin REST API access for realm/client/user provisioning (authenticated with admin credentials)
- Direct PostgreSQL access for database seeding (roles, permissions, skills, system tools)
- Direct certificate authority storage access for CA bootstrapping
- No runtime service endpoints involved — setup tool operates independently of running services

### 5.3 Environment Variables vs YAML Files

- **Environment variables** are the primary configuration mechanism for production deployments. When set, they override all other sources.
- **YAML files** (`config/identity.yaml`, `config/telemetry.yaml`) serve as fallback defaults for development convenience.
- **Built-in defaults** in `Settings` class are used when neither env var nor YAML value is present.
- File editing within containers is never required for production configuration.

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `Settings` | class | Central Pydantic BaseSettings model, extended with per-component env var fields for PostgreSQL, Redis, OIDC connections, and setup-only Keycloak admin credentials | `backend/app/core/config.py` |
| `Settings.computed_database_url` | property | **NEW** — returns composed URL from POSTGRES_* env vars, falling back to DATABASE_URL | `backend/app/core/config.py` |
| `Settings.computed_redis_url` | property | **NEW** — returns composed URL from REDIS_* env vars, falling back to REDIS_URL | `backend/app/core/config.py` |
| `Settings.log_config_sources` | method | **NEW** — logs resolved configuration sources for every infrastructure connection | `backend/app/core/config.py` |
| `Settings.keycloak_admin_user` | field | **NEW** — Keycloak master-realm admin username (setup tool only) | `backend/app/core/config.py` |
| `Settings.keycloak_admin_password` | field | **NEW** — Keycloak master-realm admin password (setup tool only) | `backend/app/core/config.py` |
| `get_settings` | function | Cached singleton returning the Settings instance | `backend/app/core/config.py` |
| `TelemetrySettings` | class | Nested telemetry configuration model within Settings | `backend/app/core/config.py` |
| `_SparseYamlSource` | class | Custom YAML source that drops null/empty placeholders, ensuring env vars take priority | `backend/app/core/config.py` |
| `settings_customise_sources` | method | Settings class method defining config source priority: init → env → dotenv → YAML → secrets | `backend/app/core/config.py` |
| `create_app` | function | Control Center FastAPI application factory | `backend/app/main.py` |
| `startup_event` | coroutine | Control Center startup sequence — modified to call validation instead of provisioning | `backend/app/main.py` |
| `_initialize_agent_realm` | coroutine | **REMOVED** — former auto-provisioning of agent realm at startup; relocated to setup tool | `backend/app/main.py` |
| `_validate_oidc_provider` | coroutine | **NEW** — validates OIDC provider reachability (skipped when super-admin enabled) | `backend/app/main.py` |
| `_validate_postgresql_reachable` | coroutine | **NEW** — validates PostgreSQL connectivity with a lightweight query | `backend/app/main.py` |
| `_validate_redis_reachable` | coroutine | **NEW** — validates Redis connectivity with PING | `backend/app/main.py` |
| `_run_bootstrap` | coroutine | Seeds system roles and permissions at startup (retained — runtime seeding, not setup-time) | `backend/app/main.py` |
| `_seed_system_tools` | coroutine | Seeds system MCP server and tools at startup (retained) | `backend/app/main.py` |
| `_initialize_certificate_authority` | coroutine | Loads or generates root CA certificate at startup (retained) | `backend/app/main.py` |
| `_initialize_oidc_provider_registry` | coroutine | Loads OIDC provider configs from DB into in-memory registry (retained) | `backend/app/main.py` |
| `_cleanup_stale_sessions_on_startup` | coroutine | Closes non-terminal sessions at startup (retained) | `backend/app/main.py` |
| `create_app` (Agent Runtime) | function | Agent Runtime FastAPI application factory | `backend/app/agent_runtime/main.py` |
| `startup_event` (Agent Runtime) | coroutine | Agent Runtime startup — modified to add Control Center reachability validation | `backend/app/agent_runtime/main.py` |
| `_validate_control_center_reachable` | coroutine | **NEW** — validates CC health check before certificate bootstrap (Agent Runtime variant) | `backend/app/agent_runtime/main.py` |
| `_load_certificate` | coroutine | Loads or bootstraps agent-instance certificate from CC (retained) | `backend/app/agent_runtime/main.py` |
| `_start_certificate_renewal` | coroutine | Starts background certificate renewal task (retained) | `backend/app/agent_runtime/main.py` |
| `create_app` (Communication Hub) | function | Communication Hub FastAPI application factory | `backend/app/communication_hub/main.py` |
| `startup_event` (Communication Hub) | coroutine | Communication Hub startup — modified to add Control Center reachability validation | `backend/app/communication_hub/main.py` |
| `_validate_control_center_reachable` (CH variant) | coroutine | **NEW** — validates CC health check before certificate bootstrap (CH variant) | `backend/app/communication_hub/main.py` |
| `_verify_redis_connectivity` | coroutine | Validates Redis connectivity at startup (existing, retained) | `backend/app/communication_hub/main.py` |
| `_load_certificate` (CH) | coroutine | Loads or bootstraps service certificate from CC (retained) | `backend/app/communication_hub/main.py` |
| `RealmManager` | class | Manages agent realm lifecycle in Keycloak — create, validate, apply token policies | `backend/app/services/identity/realm_manager.py` |
| `RealmManager.initialize_agent_realm` | method | Creates agent realm, applies token policies, registers OIDC client — now called only by setup tool | `backend/app/services/identity/realm_manager.py` |
| `RealmManager.validate_agent_realm` | method | **NEW** — checks if agent realm exists via OIDC discovery endpoint | `backend/app/services/identity/realm_manager.py` |
| `RealmManager.realm_exists` | method | Checks if a specific realm exists in Keycloak (existing) | `backend/app/services/identity/realm_manager.py` |
| `RealmManagerError` | class | Exception raised when realm operations fail | `backend/app/services/identity/realm_manager.py` |
| `IdentityBootstrapService` | class | Orchestrates full identity provider setup (bundled Keycloak and external OIDC) — called by setup tool | `backend/app/services/identity/bootstrap_service.py` |
| `IdentityBootstrapService.provision_bundled_keycloak` | method | Provisions bundled Keycloak: validate reachability, create realm, create clients, create admin user, persist to DB | `backend/app/services/identity/bootstrap_service.py` |
| `IdentityBootstrapService.provision_external_oidc` | method | Registers external OIDC provider: fetch discovery doc, persist to DB, mark setup complete | `backend/app/services/identity/bootstrap_service.py` |
| `IdentityBootstrapService.check_setup_state` | method | Determines current setup state from DB or YAML fallback | `backend/app/services/identity/bootstrap_service.py` |
| `KeycloakAdminClient` | class | Low-level Keycloak Admin REST API client — authenticate, create realms/clients/users | `backend/app/services/identity/keycloak_admin_client.py` |
| `main` (CLI) | function | Backend CLI entry point — setup-identity and seed-skills sub-commands | `backend/app/cli.py` |
| `_run_setup_identity` | coroutine | Executes identity bootstrap via CLI | `backend/app/cli.py` |
| `_run_seed_skills` | coroutine | Executes skill seeder via CLI | `backend/app/cli.py` |
| `main` (setup) | function | **NEW** — consolidated setup CLI entry point with sub-commands | `setup/main.py` |
| `run_identity_setup` | coroutine | **NEW** — provisions Keycloak realms, clients, roles, admin user | `setup/identity.py` |
| `run_database_setup` | coroutine | **NEW** — verifies DB readiness, seeds roles, permissions, skills, system tools | `setup/database.py` |
| `run_certificates_setup` | coroutine | **NEW** — bootstraps certificate authority | `setup/certificates.py` |
| `run_dev_setup` | coroutine | **NEW** — full dev bootstrap: identity + database + certificates | `setup/dev.py` |
| `run_verify` | coroutine | **NEW** — checks current state of all components without making changes | `setup/verify.py` |
| `LocalDevInitializer` | class | **DEPRECATED** — replaced by `SetupDevCommand`; consolidated into setup tool | `scripts/init-local-dev.py` |
| `initialize` | method | Full initialization sequence (dev mode) — replaced by `setup dev` | `scripts/init-local-dev.py` |
| `load_identity_yaml` | function | Loads `config/identity.yaml` with Pydantic validation | `backend/app/core/yaml_config.py` |
| `write_identity_yaml` | function | Writes updated `config/identity.yaml` after provisioning | `backend/app/core/yaml_writer.py` |
| `OIDCConfigService` | class | CRUD service for `IdentityProviderConfig` DB records — used by bootstrap service | `backend/app/services/oidc_config_service.py` |
| `BootstrapService` | class | Seeds system roles and permission policies at startup | `backend/app/services/permissions/bootstrap_service.py` |
| `SkillSeeder` | class | Idempotently seeds default platform skills | `backend/app/services/skill_seeder.py` |
| `initialize_ca` | coroutine | Generates or loads root CA certificate | `backend/app/services/certificate_authority.py` |
| `CertificateManager` | class | Agent Runtime certificate lifecycle manager | `backend/app/agent_runtime/certificate_manager.py` |
| `CommHubCertificateManager` | class | Communication Hub certificate lifecycle manager | `backend/app/communication_hub/certificate_manager.py` |
