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
| `AGENT_ENGINE_DEFAULT_MAX_INSTANCES` | Platform-wide default cap on concurrent instances per agent type (overridable per type) | |
| `AGENT_ENGINE_RESULT_STORE_TOOL_NAME` | Name of the default result-persistence MCP tool exposed to all agents (typically `save_result`) | |
| `LLM_REQUEST_TIMEOUT_SECONDS` | Timeout in seconds applied to all outbound LLM provider API calls | |

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
