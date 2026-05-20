# Environment Variables — Master Reference

All environment variables required to run the Parthenon platform. Variables marked **secret** must be supplied via a secrets management mechanism (Docker secrets or Kubernetes Secrets) — never stored in plain-text configuration files or committed to source control.

Update this file whenever a new service is added or a variable is changed or removed.

---

## Platform API

| Variable | Description | Secret |
|----------|-------------|--------|
| `PLATFORM_API_SECRET_KEY` | Secret key used for internal token signing | ✓ |
| `PLATFORM_API_ALLOWED_ORIGINS` | Comma-separated list of permitted CORS origins | |
| `PLATFORM_API_BASE_URL` | Public base URL of the Platform API; used when constructing OIDC redirect URIs | |
| `DATABASE_URL` | PostgreSQL async connection string (e.g., `postgresql+asyncpg://user:pass@host/db`) | ✓ |
| `REDIS_URL` | Redis connection string for cache and pub/sub | ✓ |
| `PERMISSION_ENGINE_MODE` | Permission Engine operating mode: `audit` (log decisions, never reject) or `enforce` (reject unauthorized requests with HTTP 403). Defaults to `audit` on first deploy. Switch to `enforce` only after audit-mode verification — see [operational-runbooks.md](operational-runbooks.md) §1. | |
| `PERMISSION_ENGINE_SEED_ADMIN_EMAIL` | OIDC email address to assign the built-in `platform_admin` role during the one-time role-seeding step. Consumed only by the seed script; not used by the running application. Remove after seeding is complete. | |
| `CREDENTIAL_VAULT_KEY` | AES-256 key used by the Certificate Authority to encrypt the CA private key at rest and to seal agent identity tokens. Must be set before the Platform API first starts. Changing this key after certificates have been issued requires re-generating the CA and re-issuing all agent instance certificates. | ✓ |
| `CA_PRIVATE_KEY_ENCRYPTED` | Optional. Pre-encrypted CA private key PEM (encrypted with `CREDENTIAL_VAULT_KEY`). When set, the Platform API loads this key on startup instead of generating a new CA. Use to persist the CA across container restarts without storing the plaintext key. If absent, a new 4096-bit RSA CA is generated and logged on first startup. | ✓ |

---

## MCP Hub

| Variable | Description | Secret |
|----------|-------------|--------|
| `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` | AES-256 key used to encrypt all stored MCP session credentials at rest | ✓ |
| `MCP_HUB_SYNC_INTERVAL_SECONDS` | Interval in seconds for polling registered MCP servers to refresh tool manifests | |

---

## Agent Engine

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_ENGINE_DEFAULT_MAX_INSTANCES` | Platform-wide default cap on concurrent instances per agent type (overridable per type). **Superseded** by `AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS` for overall session concurrency; retain for per-type cap enforcement via the Agent Runtime until fully migrated. | |
| `AGENT_ENGINE_RESULT_STORE_TOOL_NAME` | Name of the default result-persistence MCP tool exposed to all agents (typically `save_result`) | |
| `LLM_REQUEST_TIMEOUT_SECONDS` | Timeout in seconds applied to all outbound LLM provider API calls | |

---

## Agent Runtime

Variables that control the Agent Runtime subsystem. Session-level variables (`AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS`, `AGENT_RUNTIME_SESSION_TIMEOUT_SECONDS`, `AGENT_RUNTIME_OIDC_TOKEN_ENDPOINT`) apply to the `platform-api` container. Certificate identity variables (`AGENT_CERT_PATH`, `AGENT_KEY_PATH`, `CA_CERT_PATH`, `CONTROL_CENTER_URL`) apply to each isolated agent runtime instance (`agent-session-worker` or a dedicated agent container).

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS` | Maximum number of agent sessions that can execute simultaneously across all agent types; limits resource saturation at the runtime level | |
| `AGENT_RUNTIME_SESSION_TIMEOUT_SECONDS` | Wall-clock timeout applied to a single agent session execution; sessions exceeding this are marked `failed` and their runtime instances are reclaimed | |
| `AGENT_RUNTIME_OIDC_TOKEN_ENDPOINT` | Token endpoint used by the Agent Runtime to exchange agent client credentials for access tokens before executing OIDC-authenticated tool calls | |
| `AGENT_CERT_PATH` | Filesystem path to the agent instance certificate PEM file issued by the Control Center CA. Required for certificate-based tool authentication. When absent, the agent runtime falls back to OIDC-only authentication. | |
| `AGENT_KEY_PATH` | Filesystem path to the agent instance private key PEM file corresponding to `AGENT_CERT_PATH`. Must be readable only by the agent runtime process (`chmod 600`). | ✓ |
| `CA_CERT_PATH` | Filesystem path to the CA public certificate PEM file used to verify the Control Center's identity and mutual TLS trust. Download from `GET /api/v1/certificates/ca`. | |
| `CONTROL_CENTER_URL` | Base URL of the Control Center (Platform API), e.g. `http://platform-api:8000`. Used by the Agent Runtime to reach internal certificate and token endpoints. | |

---

## Agent Session Queue

Variables that govern the Redis session dispatch queue shared between the `platform-api` and the `agent-session-worker` background process. Set identically on both containers.

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_SESSION_QUEUE_NAME` | Redis list key used as the primary session dispatch queue between the Platform API and the Agent Runtime worker; must be consistent across all horizontally scaled worker instances | |
| `AGENT_SESSION_QUEUE_RESULT_TTL_SECONDS` | Time-to-live for persisted session results in Redis before they are evicted; results are also stored in PostgreSQL for long-term audit | |
| `AGENT_SESSION_WORKER_CONCURRENCY` | Number of parallel session consumer threads (or async tasks) within a single `agent-session-worker` container; tune with `AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS` to avoid over-scheduling | |

> **LangGraph dependency:** The `agent-session-worker` container requires the **LangGraph** Python package (`pip install langgraph`) for agent state machine execution. Ensure this package is installed in the worker container image before deploying.

---

## Agent Permission Manager

Variables for the Permission Manager's Redis permission cache. Apply to the `platform-api` container.

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_PERMISSION_CACHE_TTL_SECONDS` | TTL for cached permission calculations (role → SOP → Skill → MCP tool resolution) stored in Redis; lower values increase consistency at the cost of more frequent recalculation | |
| `AGENT_PERMISSION_CACHE_ENABLED` | Set to `false` to disable Redis caching of permission decisions; intended only for debugging — always `true` in production | |

---

## Communication Hub

Variables for the `communication-hub` container, including the Agent Gateway lifecycle protocol extension.

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_GATEWAY_BASE_URL` | Public base URL at which the Agent Gateway lifecycle endpoints are reachable; used when constructing callback URIs returned to callers | |
| `AGENT_GATEWAY_REQUEST_TIMEOUT_SECONDS` | Timeout for inbound agent execution requests before the gateway returns a timeout error; should be greater than `AGENT_RUNTIME_SESSION_TIMEOUT_SECONDS` | |
| `CONTROL_CENTER_URL` | Base URL of the Control Center (Platform API), e.g. `http://platform-api:8000`. Used by the Communication Hub to call internal certificate validation endpoints when forwarding tool-call requests from agent instances. | |

---

## OIDC / Identity

| Variable | Description | Secret |
|----------|-------------|--------|
| `IDENTITY_PROVIDER_TYPE` | Selects the active identity provider mode. Accepted values: `keycloak_bundled`, `keycloak_external`, `azure_entraid`. When not set, the setup wizard or CLI prompts on first run. | |
| `OIDC_PROVIDER_URL` | Base URL of the OIDC provider (e.g., the Keycloak realm URL). Also readable from `config/identity.yaml`; defaults to `http://keycloak:8080/realms/parthenon` when `IDENTITY_PROVIDER_TYPE=keycloak_bundled`. | |
| `OIDC_ISSUER_URL` | Issuer URL of the configured identity provider used for strict JWT `iss` claim validation (Keycloak realm URL or Azure EntraID tenant URL). Must exactly match the `iss` claim in issued tokens, including any trailing slash. | |
| `OIDC_JWKS_URI` | JWKS endpoint URL for JWT signature verification; must be reachable from the Platform API container. | |
| `OIDC_CLIENT_ID` | OAuth2 client ID for the Platform API as registered in the identity provider. For bundled Keycloak, resolved and written to `config/identity.yaml` automatically by the setup wizard or CLI. | |
| `OIDC_CLIENT_SECRET` | OAuth2 client secret for the Platform API. For bundled Keycloak, resolved and stored encrypted in the database by the setup wizard or CLI — do not set manually when using the wizard. | ✓ |
| `OIDC_REALM` | Keycloak realm name. Relevant for `keycloak_bundled` and `keycloak_external` provider types only. Resolved and written to `config/identity.yaml` by the setup wizard or CLI. | |
| `OIDC_AUDIENCE` | Expected `aud` claim value for token validation; must match the client configuration in the identity provider. Supersedes the legacy `JWT_AUDIENCE` variable name — `JWT_AUDIENCE` continues to work as a fallback. | |
| `OIDC_AGENT_CLIENT_PREFIX` | Prefix string applied when generating OIDC client IDs for agent types (e.g., `agent-`). | |
| `KEYCLOAK_ADMIN` | Username for the bundled Keycloak admin account. Only required when `IDENTITY_PROVIDER_TYPE=keycloak_bundled`. Must be set before the Keycloak container first starts. | |
| `KEYCLOAK_ADMIN_PASSWORD` | Password for the bundled Keycloak admin account. Only required when `IDENTITY_PROVIDER_TYPE=keycloak_bundled`. Must be set before the Keycloak container first starts. | ✓ |

### Configuration Precedence

The Platform API resolves OIDC settings in the following priority order (highest to lowest):

1. Environment variable
2. Value in `config/identity.yaml` (written automatically by the setup wizard or CLI)
3. Hard-coded default

A missing `config/identity.yaml` is treated as an empty configuration and does not cause an error. Teams that manage all configuration through environment variables can omit the YAML file entirely.

---

## Notification Service

All variables are optional. Defaults are suitable for development. Production deployments should set all variables corresponding to active channel types. Per-channel credentials are configured via the admin UI and stored encrypted in the database — these environment variables are fallback defaults only; per-channel values always take precedence.

| Variable | Default | Description | Secret |
|----------|---------|-------------|--------|
| `NOTIFICATION_SMTP_HOST` | `localhost` | SMTP relay server hostname for the SMTP channel provider | |
| `NOTIFICATION_SMTP_PORT` | `587` | SMTP relay server port (`587` = STARTTLS, `465` = SMTPS) | |
| `NOTIFICATION_EMAIL_API_KEY` | — | Default API key for email API providers (SendGrid, Mailgun); used when no per-channel credential is configured | ✓ |
| `NOTIFICATION_WEBHOOK_SECRET` | — | Default HMAC-SHA256 signing secret for webhook channels without a per-channel secret | ✓ |
| `NOTIFICATION_RETRY_MAX_ATTEMPTS` | `3` | Maximum delivery attempts per channel before recording a `FAILED` status | |
| `NOTIFICATION_RETRY_DELAY_SECONDS` | `60` | Wait time in seconds between retry attempts | |

---

## Service-to-Service Authentication (Control Center / Agent Runtime / Communication Hub)

These variables control certificate bootstrapping and mTLS for the three-service deployment. They are required only when running the services in decomposed mode.

### Control Center (additional vars for decomposed mode)

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_RUNTIME_URL` | Agent Runtime service base URL (e.g., `http://agent-runtime:8001`) | |
| `COMMUNICATION_HUB_URL` | Communication Hub service base URL (e.g., `http://communication-hub:8002`) | |
| `SERVICE_CERT_VALIDITY_DAYS` | Service certificate validity period (default: `30`) | |
| `AGENT_INSTANCE_CERT_VALIDITY_HOURS` | Agent-instance certificate validity period (default: `24`) | |
| `AGENT_RUNTIME_BOOTSTRAP_KEY` | Unique bootstrap secret for Agent Runtime (min 32 chars, random) | ✓ |
| `COMM_HUB_BOOTSTRAP_KEY` | Unique bootstrap secret for Communication Hub (min 32 chars, random) | ✓ |

### Agent Runtime (decomposed mode)

| Variable | Description | Secret |
|----------|-------------|--------|
| `SERVICE_IDENTITY` | Service identity name for certificate bootstrap (default: `agent-runtime`) | |
| `SERVICE_BOOTSTRAP_KEY` | Bootstrap secret matching `AGENT_RUNTIME_BOOTSTRAP_KEY` in Control Center | ✓ |
| `CERT_RENEWAL_THRESHOLD_HOURS` | Hours before expiry to trigger certificate renewal (default: `1`) | |

> **Removed in decomposed mode**: `DATABASE_URL` and `REDIS_URL` are no longer set on Agent Runtime — it has no direct database access.

### Communication Hub (decomposed mode)

| Variable | Description | Secret |
|----------|-------------|--------|
| `SERVICE_IDENTITY` | Service identity name for certificate bootstrap (default: `communication-hub`) | |
| `SERVICE_BOOTSTRAP_KEY` | Bootstrap secret matching `COMM_HUB_BOOTSTRAP_KEY` in Control Center | ✓ |
| `CERT_RENEWAL_THRESHOLD_HOURS` | Hours before expiry to trigger certificate renewal (default: `1`) | |
| `TOKEN_RESOLUTION_CACHE_TTL_SECONDS` | TTL for per-tool-call permission cache (default: `60`) | |

> **Removed in decomposed mode**: `DATABASE_URL` is no longer set on Communication Hub — it has no direct database access.

---

## OpenTelemetry (OTEL)

Set per container; `OTEL_SERVICE_NAME` should be unique per service to enable per-service filtering in telemetry backends.

| Variable | Description | Secret |
|----------|-------------|--------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint of the OTEL Collector; used by all services to ship traces, metrics, and logs | |
| `OTEL_SERVICE_NAME` | Service name tag embedded in all telemetry emitted by this container | |
| `OTEL_TRACES_SAMPLER` | Trace sampling strategy (e.g., `parentbased_traceidratio`) | |
| `OTEL_TRACES_SAMPLER_ARG` | Sampling rate argument for the selected sampler (e.g., `1.0` for 100% sampling) | |

---

## Telemetry Configuration (Parthenon-specific)

All variables below are **optional**. The backend starts with safe defaults (console exporter, all signals enabled, `INFO` log level) when none are set. Environment variables always take precedence over values in `config/telemetry.yaml`. See [configuration-files.md](configuration-files.md) for the file-based config option.

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEMETRY_EXPORTER_TYPE` | `console` | Active exporter(s): `console`, `file`, `otlp`, `logfire`, `custom`. Comma-separate multiple values for multi-target output. |
| `TELEMETRY_TRACES_ENABLED` | `true` | Enable or disable trace collection. |
| `TELEMETRY_METRICS_ENABLED` | `true` | Enable or disable metrics collection. |
| `TELEMETRY_LOGS_ENABLED` | `true` | Enable or disable log collection via OTEL. |
| `TELEMETRY_LOG_LEVEL` | `INFO` | Default log level applied to all components. |
| `TELEMETRY_OTLP_ENDPOINT` | `http://otel-collector:4317` | OTLP Collector endpoint. Required when `TELEMETRY_EXPORTER_TYPE` includes `otlp`. |
| `TELEMETRY_OTLP_PROTOCOL` | `grpc` | OTLP transport protocol: `grpc` or `http`. |
| `TELEMETRY_OTLP_INSECURE` | `true` | Skip TLS verification for OTLP. Set to `false` in production with TLS enabled. |
| `TELEMETRY_FILE_PATH` | _(none)_ | File path for the `file` exporter output. Required when `TELEMETRY_EXPORTER_TYPE` includes `file`. |
| `TELEMETRY_FILE_MAX_BYTES` | `10485760` | Maximum log/trace file size in bytes before rotation. |
| `TELEMETRY_FILE_BACKUP_COUNT` | `5` | Number of rotated backup files to retain. |
| `TELEMETRY_LOGFIRE_TOKEN` | _(none)_ | Logfire ingest token. Required when `TELEMETRY_EXPORTER_TYPE` includes `logfire`. | ✓ |
| `TELEMETRY_CUSTOM_ENDPOINT` | _(none)_ | Custom HTTP endpoint URL. Required when `TELEMETRY_EXPORTER_TYPE` includes `custom`. |
| `TELEMETRY_CONFIG_FILE` | _(none)_ | Path to an optional `telemetry.yaml` declarative config file. When set, values in the file fill any gaps not covered by the env vars above. |

---

## Database (PostgreSQL)

Used when constructing the database connection independently of `DATABASE_URL`.

| Variable | Description | Secret |
|----------|-------------|--------|
| `POSTGRES_HOST` | PostgreSQL server hostname or IP address | |
| `POSTGRES_PORT` | PostgreSQL server port (default: `5432`) | |
| `POSTGRES_DB` | Target database name | |
| `POSTGRES_USER` | Database user with read/write access to `POSTGRES_DB` | |
| `POSTGRES_PASSWORD` | Password for `POSTGRES_USER` | ✓ |

---

## Redis

| Variable | Description | Secret |
|----------|-------------|--------|
| `REDIS_HOST` | Redis server hostname or IP address | |
| `REDIS_PORT` | Redis server port (default: `6379`) | |
| `REDIS_PASSWORD` | Redis authentication password; leave empty if Redis AUTH is disabled | ✓ |
| `REDIS_DB_INDEX` | Redis logical database index (default: `0`) | |

---

## Notification Channels

Required only when the corresponding notification channel type is configured.

| Variable | Description | Secret |
|----------|-------------|--------|
| `NOTIFY_SMTP_HOST` | SMTP server hostname for email notification delivery | |
| `NOTIFY_SMTP_PORT` | SMTP server port (e.g., `587` for STARTTLS) | |
| `NOTIFY_SMTP_USER` | SMTP authentication username | |
| `NOTIFY_SMTP_PASSWORD` | SMTP authentication password | ✓ |
| `NOTIFY_SLACK_WEBHOOK_URL` | Default Slack incoming webhook URL for Slack notification channels | ✓ |
| `NOTIFY_TEAMS_WEBHOOK_URL` | Default Microsoft Teams incoming webhook URL for Teams notification channels | ✓ |
| `NOTIFY_WEBHOOK_DEFAULT_TIMEOUT_SECONDS` | HTTP timeout in seconds applied to generic outbound webhook notification calls | |

---

## MCP Demo App

Variables required exclusively by the `mcp-demo-app` service. No existing Parthenon services require changes.

| Variable | Description | Secret |
|----------|-------------|--------|
| `KEYCLOAK_URL` | Base URL of the Keycloak instance reachable from the container (e.g., `http://keycloak:8080` inside Docker; public URL in production) | |
| `KEYCLOAK_REALM` | Keycloak realm for agent identities. Must be set to `ai_agents`. | |
| `KEYCLOAK_CLIENT_ID` | Client ID of the demo app's Keycloak client in the `ai_agents` realm | |
| `KEYCLOAK_CLIENT_SECRET` | Client secret for the demo app's Keycloak client | ✓ |
| `HUB_URL` | Internal base URL of the Parthenon MCP Hub (e.g., `http://api:8000/api/v1`) | |
| `HUB_API_KEY` | API key or bearer token used to authenticate registration calls to the MCP Hub | ✓ |
| `APP_URL` | Externally reachable base URL of the demo app that the Hub will use to proxy tool calls (e.g., `http://mcp-demo-app:9000`) | |
| `APP_SLUG` | Unique slug used when registering with the MCP Hub. Must be set to `demo`. | |
| `APP_PORT` | Port the FastAPI application listens on. Defaults to `9000`. | |
