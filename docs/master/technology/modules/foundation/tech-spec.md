# Module: foundation — Tech Spec

## Overview

The foundation module provides the shared infrastructure on which all other backend and frontend modules depend. It covers application configuration loading via a layered config system (YAML file + environment variables + defaults, merged by pydantic-settings), the async database session factory, OIDC JWT validation against an external identity provider, the JWT authentication middleware that enforces token presence on every protected route, the AES-256 credential vault for safe storage of sensitive credentials, the OpenTelemetry telemetry initialisation that instruments all libraries and exporters for traces, metrics, and logs, shared FastAPI dependencies (`require_permission`, `get_current_claims`) used by every guarded router, and the centralised resource type registry (`ResourceTypeManifest` + RT_* constants) that acts as the authoritative source of valid module/action combinations for the permission engine.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `get_settings` | Singleton Pydantic `BaseSettings` loader that resolves configuration through a layered source chain — see **Configuration System** section below; used as a FastAPI dependency throughout the application |
| `get_db` | FastAPI dependency that provides a scoped async SQLAlchemy session per request; handles session lifecycle (begin, commit/rollback on exception, close) |
| `OIDCClient` | Fetches the JWKS document from the configured identity provider, caches the key set in memory, and performs JWT signature verification plus expiry and audience claim validation on each token |
| `JWTAuthMiddleware` | Starlette middleware applied to all non-public routes; extracts the bearer token from the `Authorization` header, delegates to `OIDCClient` for validation, and attaches the decoded identity claims to `request.state` |
| `CredentialVault` | Thin wrapper around AES-256 symmetric encryption; provides `encrypt` and `decrypt` operations for storing and retrieving sensitive values such as MCP session credentials; plaintext values are never written to logs or returned in API responses |
| `setup_telemetry` | Called once at application startup; configures the OTEL `TracerProvider`, `MeterProvider`, and `LoggerProvider` with OTLP exporters pointed at the configured collector endpoint; delegates library patching to `_instrument_libraries` |
| `_instrument_libraries` | Applies OTEL auto-instrumentation patches for FastAPI, SQLAlchemy, Redis, and httpx; isolated in a separate function so a patch failure for one library does not block application startup |
| `limiter` | Global `slowapi.Limiter` instance attached to `app.state`; provides per-route rate limiting using the remote client address as the key function |

### API Dependencies & Permission Registry

Shared FastAPI dependencies and the platform-wide resource type registry. Every guarded route imports from these two files — no module may call the permission engine or read resource types directly.

| Component | Description |
|-----------|-------------|
| `require_permission` | Cached FastAPI dependency factory keyed by `(module, action)` pair; resolves the calling user's `PlatformUser` record from the JWT `sub` claim, calls `PermissionEngine.authorize()`, and raises `HTTPException(403, PermissionDeniedDetail)` on denial; returns the decoded claims dict on success; safe for use in `dependency_overrides` in tests |
| `get_current_claims` | FastAPI dependency that extracts the decoded JWT claims dict from `request.state.identity` (populated by `JWTAuthMiddleware`); used by handlers that need raw token claims without a full permission check |
| `ResourceTypeManifest` | Centralised Python dict keyed by resource type string; maps each type to its list of allowed action strings; imported by `PermissionEngine` for fast-fail validation on unknown types or actions, and mirrored to TypeScript as `RESOURCE_TYPES` for the frontend policy builder |
| `RT_AGENT` | Resource type constant: `"agent"` — agents module |
| `RT_MCP_SERVER` | Resource type constant: `"mcp_server"` — MCP Hub module |
| `RT_SKILL` | Resource type constant: `"skill"` — skills and SOPs module |
| `RT_SCHEDULING` | Resource type constant: `"scheduling"` — scheduling module |
| `RT_NOTIFICATION` | Resource type constant: `"notification"` — notifications module |
| `RT_CONVERSATION` | Resource type constant: `"conversation"` — conversations module |
| `RT_RESULT` | Resource type constant: `"result"` — results module; registered in this change |
| `RT_ACCESS_REQUEST` | Resource type constant: `"access_request"` — user access requests module |

### Frontend

| Component | Description |
|-----------|-------------|
| `initTelemetry` | Initialises the browser `WebTracerProvider` with an OTLP HTTP exporter, enables `FetchInstrumentation` to propagate `traceparent` headers on all outbound fetch calls, and triggers async Core Web Vitals recording |
| `_recordWebVitals` | Lazily imports the `web-vitals` library and records LCP, FID, FCP, and CLS values as OTEL histograms; lazy import prevents blocking the initial page render |

---

## Configuration System

All backend configuration in the Parthenon platform flows through a single layered system rooted in `backend/app/core/config.py`. This is the **platform-wide standard** — every module that needs configuration must use `get_settings()` as its sole access point. No module should read environment variables, files, or secrets directly.

### Source Priority (highest to lowest)

| Priority | Source | Mechanism |
|---|---|---|
| 1 | Environment variables | `pydantic-settings` built-in `EnvSettingsSource` |
| 2 | `config/<domain>.yaml` | `YamlSettingsSource` — a `PydanticBaseSettingsSource` subclass wired via `Settings.settings_customise_sources()` |
| 3 | Hard-coded defaults | Pydantic field `default` / `default_factory` |

The YAML layer is inserted between env vars and defaults by overriding `settings_customise_sources()`. This gives operators the ability to manage config in version-controlled YAML files while still allowing environment variables to override any value at deploy time without changing files.

### Per-Component Environment Variables

Every infrastructure connection supports per-component environment variables for production deployments:

| Variable Pattern | Purpose | Affected Services |
|---|---|---|
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Composed PostgreSQL connection parameters. When set, override the monolithic `DATABASE_URL`. | Control Center |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB` | Composed Redis connection parameters. When set, override the monolithic `REDIS_URL`. | Control Center, Communication Hub |
| `OIDC_PROVIDER_URL`, `OIDC_REALM`, `OIDC_CLIENT_ID` | Per-component OIDC provider configuration. Override values from `config/identity.yaml`. | Control Center |
| `KEYCLOAK_ADMIN_USER`, `KEYCLOAK_ADMIN_PASSWORD` | **Setup-only** — Keycloak master-realm admin credentials. Never available to the runtime Control Center. | Setup tool only |
| `CONTROL_CENTER_URL` | Base URL of the Control Center. Used by Agent Runtime and Communication Hub for health checks and certificate bootstrap. | Agent Runtime, Communication Hub |
| `AGENT_CERT_PATH`, `AGENT_KEY_PATH`, `AGENT_CA_CERT_PATH` | File system paths to agent instance certificate materials. | Agent Runtime |
| `TELEMETRY_*` | Telemetry configuration (export targets, signal enable/disable, log levels). | All backend services |

Computed properties (`computed_database_url`, `computed_redis_url`) assemble the composed variables into connection strings, falling back to the monolithic `DATABASE_URL` / `REDIS_URL` when per-component variables are not set.

### Config Resolution Logging

At startup, `Settings.log_config_sources` logs which source resolved each infrastructure connection (env var, YAML file, or default). This aids operators in diagnosing misconfigurations without inspecting container internals.

### Config Files

| File | Domain | Purpose |
|---|---|---|
| `config/identity.yaml` | Identity / OIDC | Identity provider type, OIDC URL, realm, client ID, audience, setup-complete flag. Written by the Identity Bootstrap Service after first-run setup. |
| `config/telemetry.yaml` | Telemetry | Telemetry export targets, signal enable/disable flags, and log levels. Overridable by `TELEMETRY_*` environment variables. |

Additional `config/<domain>.yaml` files may be introduced by future modules following the same pattern — each domain owns its own YAML file and adds a corresponding `YamlSettingsSource` subclass to `config.py`.

### Adding Config for a New Module

1. Add the new settings fields to `Settings` in `backend/app/core/config.py`.
2. If the module needs file-based config (overridable by env), create `config/<domain>.yaml` and add a `YamlSettingsSource` subclass for that domain's key prefix.
3. Wire the new source into `settings_customise_sources()` — it slots in between `EnvSettingsSource` and hard-coded defaults.
4. All field types are validated by Pydantic automatically; no manual validation code is needed.
5. Consume via `get_settings()` — never import the config module directly from outside `core/`.

### Secrets Policy

The YAML config files contain **no secrets**. Sensitive values (tokens, passwords, API keys) are encrypted and stored in the database via `CredentialVault`. The YAML layer is safe to version-control.

### Config Reload

`get_settings()` is cached with `@lru_cache`. After the Identity Bootstrap Service (or any future provisioning service) writes a new YAML config, it must call `get_settings.cache_clear()` to invalidate the cache. The next call to `get_settings()` will re-read all sources and re-validate, picking up the new values without a process restart.

---

## API Endpoints

The foundation module does not expose its own HTTP endpoints. It provides the shared dependencies and middleware consumed by all other routers.

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `get_settings` | function | Returns application settings resolved through the layered config chain (env → YAML → defaults); cached with `@lru_cache`; call `get_settings.cache_clear()` to force a re-read after config changes | `backend/app/core/config.py` |
| `Settings` | class | Pydantic `BaseSettings` subclass; declares all platform config fields including per-component env var fields for PostgreSQL, Redis, and OIDC connections; wires config sources via `settings_customise_sources()` | `backend/app/core/config.py` |
| `Settings.computed_database_url` | property | Composed PostgreSQL connection URL from `POSTGRES_*` env vars; falls back to `DATABASE_URL` when per-component vars are not set | `backend/app/core/config.py` |
| `Settings.computed_redis_url` | property | Composed Redis connection URL from `REDIS_*` env vars; falls back to `REDIS_URL` when per-component vars are not set | `backend/app/core/config.py` |
| `Settings.log_config_sources` | method | Logs resolved configuration sources for every infrastructure connection at startup; aids operators in diagnosing misconfigurations | `backend/app/core/config.py` |
| `Settings.keycloak_admin_user` | field | Keycloak master-realm admin username; setup tool only — never available to runtime Control Center | `backend/app/core/config.py` |
| `Settings.keycloak_admin_password` | field | Keycloak master-realm admin password; setup tool only — never available to runtime Control Center | `backend/app/core/config.py` |
| `TelemetrySettings` | class | Nested telemetry configuration model within Settings; controls export targets, signals, and log levels | `backend/app/core/config.py` |
| `_SparseYamlSource` | class | Custom YAML source that drops null/empty placeholders, ensuring environment variables take priority over YAML | `backend/app/core/config.py` |
| `settings_customise_sources` | method | Defines config source priority: init → env → dotenv → YAML → secrets | `backend/app/core/config.py` |
| `YamlSettingsSource` | class | `PydanticBaseSettingsSource` subclass that reads a domain-specific `config/<domain>.yaml` file and feeds its values into `Settings` as the second-priority source after env vars | `backend/app/core/config.py` |
| `get_db` | function | FastAPI dependency providing a scoped async SQLAlchemy session per request | `backend/app/db/session.py` |
| `OIDCClient` | class | Fetches and caches JWKS; validates JWT signatures, expiry, and audience claims | `backend/app/core/oidc_client.py` |
| `JWTAuthMiddleware` | class | Starlette middleware validating bearer tokens on all protected routes; attaches identity claims to `request.state`; also stores the raw bearer token string on `request.state.raw_token` immediately after extraction (used by passthrough session endpoints for JWT forwarding) | `backend/app/middleware/auth.py` |
| `CredentialVault` | class | AES-256 encrypt/decrypt wrapper for stored credentials; decrypt at call time only | `backend/app/core/credential_vault.py` |
| `setup_telemetry` | function | Configures TracerProvider, MeterProvider, and LoggerProvider with OTLP exporters; applies auto-instrumentation | `backend/app/core/telemetry.py` |
| `_instrument_libraries` | function | Applies OTEL auto-instrumentation patches for FastAPI, SQLAlchemy, Redis, and httpx; isolated for fault tolerance | `backend/app/core/telemetry.py` |
| `limiter` | object | Global slowapi.Limiter instance with remote-address key function; attached to app.state | `backend/app/main.py` |
| `validation_exception_handler` | function | FastAPI exception handler for `RequestValidationError`; converts Pydantic v2 `model_validator` exception objects in `ctx` to strings before JSON serialisation; required for passthrough session credential validator responses | `backend/app/main.py` |
| `initTelemetry` | function | Initialises browser WebTracerProvider with OTLP HTTP exporter and FetchInstrumentation; triggers Web Vitals recording | `frontend/src/telemetry.ts` |
| `_recordWebVitals` | function | Lazily imports web-vitals and records LCP, FID, FCP, CLS as OTEL histograms | `frontend/src/telemetry.ts` |

### API Dependencies & Permission Registry

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `require_permission` | function | FastAPI dependency factory keyed by `(module, action)`; resolves `PlatformUser` from JWT `sub`, calls `PermissionEngine.authorize()`, raises `HTTPException(403)` with `PermissionDeniedDetail` on denial; cached for `dependency_overrides` compatibility in tests | `backend/app/api/deps.py` |
| `get_current_claims` | function | FastAPI dependency that extracts the decoded JWT claims dict from `request.state.identity`; used by handlers that need raw claims without a full permission check | `backend/app/api/deps.py` |
| `ResourceTypeManifest` | dict | Centralised registry mapping resource type strings to allowed action lists; authoritative source for `PermissionEngine` validation and the frontend `RESOURCE_TYPES` mirror | `backend/app/core/resource_types.py` |
| `RT_AGENT` | constant | Resource type identifier: `"agent"` — agents module | `backend/app/core/resource_types.py` |
| `RT_AGENT_ROLES` | constant | Resource type identifier: `"agent::roles"` — agent roles module | `backend/app/core/resource_types.py` |
| `RT_AGENT_SKILLS` | constant | Resource type identifier: `"agent::skills"` — skills and SOPs module | `backend/app/core/resource_types.py` |
| `RT_AGENT_SCHEDULES` | constant | Resource type identifier: `"agent::schedules"` — scheduling module | `backend/app/core/resource_types.py` |
| `RT_INTEGRATION_MCP_HUB` | constant | Resource type identifier: `"integration::mcp_hub"` — MCP Hub module | `backend/app/core/resource_types.py` |
| `RT_INTEGRATION_NOTIFICATIONS` | constant | Resource type identifier: `"integration::notifications"` — notifications module | `backend/app/core/resource_types.py` |
| `RT_AGENT_TRAILS` | constant | Resource type identifier: `"agent::trails"` — conversations and results module | `backend/app/core/resource_types.py` |
| `RT_AGENT_DATA_TYPES` | constant | Resource type identifier: `"agent::data_types"` — data types module | `backend/app/core/resource_types.py` |

### Test Files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_auth_middleware` | test module | Unit tests for `JWTAuthMiddleware`; 2 passthrough-related tests: `raw_token` stored on `request.state` after valid JWT extraction; `raw_token` absent on public paths that bypass auth | `backend/tests/unit/test_auth_middleware.py` |
