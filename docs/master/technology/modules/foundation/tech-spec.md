# Module: foundation — Tech Spec

## Overview

The foundation module provides the shared infrastructure on which all other backend and frontend modules depend. It covers application configuration loading via a layered config system (YAML file + environment variables + defaults, merged by pydantic-settings), the async database session factory, OIDC JWT validation against an external identity provider, the JWT authentication middleware that enforces token presence on every protected route, the AES-256 credential vault for safe storage of sensitive credentials, and the OpenTelemetry telemetry initialisation that instruments all libraries and exporters for traces, metrics, and logs.

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

### Config Files

| File | Domain | Purpose |
|---|---|---|
| `config/identity.yaml` | Identity / OIDC | Identity provider type, OIDC URL, realm, client ID, audience, setup-complete flag. Written by the Identity Bootstrap Service after first-run setup. |

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
| `Settings` | class | Pydantic `BaseSettings` subclass; declares all platform config fields; wires config sources via `settings_customise_sources()` | `backend/app/core/config.py` |
| `YamlSettingsSource` | class | `PydanticBaseSettingsSource` subclass that reads a domain-specific `config/<domain>.yaml` file and feeds its values into `Settings` as the second-priority source after env vars | `backend/app/core/config.py` |
| `get_db` | function | FastAPI dependency providing a scoped async SQLAlchemy session per request | `backend/app/db/session.py` |
| `OIDCClient` | class | Fetches and caches JWKS; validates JWT signatures, expiry, and audience claims | `backend/app/core/oidc_client.py` |
| `JWTAuthMiddleware` | class | Starlette middleware validating bearer tokens on all protected routes; attaches identity claims to request state | `backend/app/middleware/auth.py` |
| `CredentialVault` | class | AES-256 encrypt/decrypt wrapper for stored credentials; decrypt at call time only | `backend/app/core/credential_vault.py` |
| `setup_telemetry` | function | Configures TracerProvider, MeterProvider, and LoggerProvider with OTLP exporters; applies auto-instrumentation | `backend/app/core/telemetry.py` |
| `_instrument_libraries` | function | Applies OTEL auto-instrumentation patches for FastAPI, SQLAlchemy, Redis, and httpx; isolated for fault tolerance | `backend/app/core/telemetry.py` |
| `limiter` | object | Global slowapi.Limiter instance with remote-address key function; attached to app.state | `backend/app/main.py` |
| `initTelemetry` | function | Initialises browser WebTracerProvider with OTLP HTTP exporter and FetchInstrumentation; triggers Web Vitals recording | `frontend/src/telemetry.ts` |
| `_recordWebVitals` | function | Lazily imports web-vitals and records LCP, FID, FCP, CLS as OTEL histograms | `frontend/src/telemetry.ts` |
