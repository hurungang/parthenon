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

Variables that control the Agent Runtime subsystem. Session-level variables (`AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS`, `AGENT_RUNTIME_SESSION_TIMEOUT_SECONDS`, `AGENT_RUNTIME_OIDC_TOKEN_ENDPOINT`) apply to the `control-center` container. Certificate identity variables (`AGENT_CERT_PATH`, `AGENT_KEY_PATH`, `CA_CERT_PATH`, `CONTROL_CENTER_URL`) apply to each isolated agent runtime instance (`agent-session-worker` or a dedicated agent container).

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS` | Maximum number of agent sessions that can execute simultaneously across all agent types; limits resource saturation at the runtime level | |
| `AGENT_RUNTIME_SESSION_TIMEOUT_SECONDS` | Wall-clock timeout applied to a single agent session execution; sessions exceeding this are marked `failed` and their runtime instances are reclaimed | |
| `AGENT_RUNTIME_OIDC_TOKEN_ENDPOINT` | Token endpoint used by the Agent Runtime to exchange agent client credentials for access tokens before executing OIDC-authenticated tool calls | |
| `AGENT_CERT_PATH` | Filesystem path to the agent instance certificate PEM file issued by the Control Center CA. Required for certificate-based tool authentication. When absent, the agent runtime falls back to OIDC-only authentication. | |
| `AGENT_KEY_PATH` | Filesystem path to the agent instance private key PEM file corresponding to `AGENT_CERT_PATH`. Must be readable only by the agent runtime process (`chmod 600`). | ✓ |
| `CA_CERT_PATH` | Filesystem path to the CA public certificate PEM file used to verify the Control Center's identity and mutual TLS trust. Download from `GET /api/v1/certificates/ca`. | |
| `CONTROL_CENTER_URL` | Base URL of the Control Center (Platform API), e.g. `http://control-center:8000`. Used by the Agent Runtime to reach internal certificate and token endpoints. | |

---

## Agent Session Queue

Variables that govern the Redis session dispatch queue shared between the `control-center` and the `agent-session-worker` background process. Set identically on both containers.

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_SESSION_QUEUE_NAME` | Redis list key used as the primary session dispatch queue between the Platform API and the Agent Runtime worker; must be consistent across all horizontally scaled worker instances | |
| `AGENT_SESSION_QUEUE_RESULT_TTL_SECONDS` | Time-to-live for persisted session results in Redis before they are evicted; results are also stored in PostgreSQL for long-term audit | |
| `AGENT_SESSION_WORKER_CONCURRENCY` | Number of parallel session consumer threads (or async tasks) within a single `agent-session-worker` container; tune with `AGENT_RUNTIME_MAX_CONCURRENT_SESSIONS` to avoid over-scheduling | |

> **LangGraph dependency:** The `agent-session-worker` container requires the **LangGraph** Python package (`pip install langgraph`) for agent state machine execution. Ensure this package is installed in the worker container image before deploying.

---

## Agent Permission Manager

Variables for the Permission Manager's Redis permission cache. Apply to the `control-center` container.

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_PERMISSION_CACHE_TTL_SECONDS` | TTL for cached permission calculations (role → SOP → Skill → MCP tool resolution) stored in Redis; lower values increase consistency at the cost of more frequent recalculation | |
| `AGENT_PERMISSION_CACHE_ENABLED` | Set to `false` to disable Redis caching of permission decisions; intended only for debugging — always `true` in production | |

---

## Communication Hub

Variables for the `communication-hub` container, including the Agent Gateway lifecycle protocol extension. The Communication Hub supports dual authentication paths: mTLS certificates (internal Agent Runtime agents) and API keys (external third-party agents). The `load_skills` system tool is hosted for external agent skill discovery with incremental sync support via the `since` parameter.

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_GATEWAY_BASE_URL` | Public base URL at which the Agent Gateway lifecycle endpoints are reachable; used when constructing callback URIs returned to callers | |
| `AGENT_GATEWAY_REQUEST_TIMEOUT_SECONDS` | Timeout for inbound agent execution requests before the gateway returns a timeout error; should be greater than `AGENT_RUNTIME_SESSION_TIMEOUT_SECONDS` | |
| `CONTROL_CENTER_URL` | Base URL of the Control Center (Platform API), e.g. `http://control-center:8000`. Used by the Communication Hub to call internal certificate validation endpoints when forwarding tool-call requests from agent instances, and to call `POST /internal/auth/validate-api-key` for API key validation. | |
| `CH_API_KEY_AUTH_ENABLED` | Feature flag to enable or disable API key authentication on the Communication Hub. When `false`, only mTLS certificate authentication is accepted. Default `false`. Set to `true` only after verifying the API key creation flow works end-to-end. | |

---

## API Key Authentication

Variables for API key-based external agent access to the Communication Hub via MCP. API key hashing uses `API_KEY_HASH_SECRET` as an application-level pepper to prevent precomputed hash attacks. API keys are validated by the Communication Hub calling Control Center's internal `POST /internal/auth/validate-api-key` endpoint over existing mTLS.

| Variable | Service | Description | Secret | Default |
|----------|---------|-------------|--------|---------|
| `API_KEY_HASH_SECRET` | CC | Application-level pepper/secret mixed into the API key hash. Must be a high-entropy random string (min 32 chars). Changing this value invalidates all previously issued API keys. | ✓ | — |
| `API_KEY_PREFIX` | CC | Configurable prefix string prepended to generated API keys for visual identification. Prefix is stored in `agent_api_keys.key_prefix` and shown in clear-text at creation time. | | `phn_sk_` |

---

## Agent Execution Guardrails

Guardrail rollout introduces service-specific variables for policy enforcement, forwarding, and persistence. Keep policy ownership in Control Center, runtime enforcement in Agent Runtime, and metadata forwarding in Communication Hub.

### Agent Runtime Guardrail Variables

| Variable | Required for rollout | Default / behavior when unset | Secret |
|----------|----------------------|--------------------------------|--------|
| `AGENT_GUARDRAIL_MAX_ITERATIONS` | Yes | Uses service-level default cumulative iteration ceiling when agent policy does not override | |
| `AGENT_GUARDRAIL_EXEC_TIMEOUT_SECONDS` | Yes | Uses service-level default wall-clock timeout when agent policy does not override | |
| `AGENT_GUARDRAIL_MAX_DELEGATION_DEPTH` | Yes | Uses service-level default maximum delegation depth | |
| `AGENT_GUARDRAIL_MAX_DELEGATED_STEPS` | Yes | Uses service-level default delegated-step budget | |
| `AGENT_GUARDRAIL_TOKEN_BUDGET_ENABLED` | Yes | Enables token-budget evaluation for non-conversational and automated runs | |
| `AGENT_GUARDRAIL_TOKEN_BUDGET_DEFAULT` | No | Optional default token cap when no policy-specific token budget is present | |
| `AGENT_GUARDRAIL_TOKEN_FALLBACK_MODE` | Yes | Defines fallback behavior when hard token enforcement is not supported | |
| `AGENT_GUARDRAIL_CONVERSATIONAL_TOKEN_VISIBILITY_ENABLED` | Yes | Enables continuous current-session token usage visibility for conversational runs | |
| `AGENT_GUARDRAIL_CONVERSATIONAL_TOKEN_CONTINUE_ENABLED` | Yes | Allows conversational continuation after token threshold unless another hard guardrail is triggered | |
| `AGENT_GUARDRAIL_CYCLE_DETECTION_ENABLED` | Yes | Enables pre-execution recursive delegation cycle detection and hard block | |

### Control Center Guardrail Variables

| Variable | Required for rollout | Default / behavior when unset | Secret |
|----------|----------------------|--------------------------------|--------|
| `AGENT_GUARDRAIL_POLICY_ENFORCEMENT` | Yes | Enables policy resolution and validation for guardrail payload fields | |
| `AGENT_GUARDRAIL_STOP_REASON_PERSISTENCE` | Yes | Persists structured guardrail stop reasons in session state and logs | |
| `AGENT_GUARDRAIL_CONVERSATIONAL_TOKEN_TELEMETRY_PERSISTENCE` | Yes | Persists conversational token-usage visibility and continuation metadata | |
| `AGENT_GUARDRAIL_POLICY_VERSION` | No | Optional rollout marker for version tracking and rollback coordination | |

### Communication Hub Guardrail Variables

| Variable | Required for rollout | Default / behavior when unset | Secret |
|----------|----------------------|--------------------------------|--------|
| `AGENT_GUARDRAIL_STOP_REASON_FORWARDING` | Yes | Preserves guardrail stop metadata through direct and delegated routing paths | |
| `AGENT_GUARDRAIL_POLICY_PAYLOAD_PASSTHROUGH` | Yes | Preserves policy snapshot payload fields without remapping | |
| `AGENT_GUARDRAIL_TOKEN_TELEMETRY_FORWARDING` | Yes | Preserves conversational token-usage and continuation metadata through routing paths | |

Rollout requirement notes:
- Configure all required guardrail variables before service cutover.
- Keep Agent Runtime and Communication Hub free of direct database credentials and direct database access.
- Use consistent policy/version labels across environments for traceability.

---

## Super Admin Bootstrap

Super admin credentials provide a local authentication path that bypasses OIDC. Use this path during initial platform bootstrap, database migrations, and emergency recovery when OIDC providers are unreachable. In production, disable after OIDC is verified working.

| Variable | Description | Secret | Default |
|----------|-------------|--------|---------|
| `SUPER_ADMIN_ENABLED` | Enables super admin login path. Must be `true` for the super admin auth pipeline to be active. Start `true` during bootstrap, set `false` after OIDC is verified. | | `false` |
| `SUPER_ADMIN_USERNAME` | Super admin username. Bootstrapped into the `super_admin_credentials` table on first launch. Immutable after initial seeding — changing the env var after bootstrap requires a direct DB update. | | `admin` |
| `SUPER_ADMIN_PASSWORD_HASH` | Argon2id or bcrypt hash of the super admin password. Bootstrapped into `super_admin_credentials` on first launch. Never set a plaintext password — always supply a pre-computed hash. Generate with: `python -m app.cli hash-password`. | ✓ | _(none — required for super admin)_ |

---

## OIDC / Identity (Deprecated)

> **All OIDC configuration is now stored in the database (`IdentityProviderConfig` table).** The environment variables below are **only read during the one-time `config/identity.yaml` → DB migration** and are ignored at runtime after the migration completes. Set them only when migrating from a pre-refinement deployment that used `config/identity.yaml`. New deployments configure OIDC providers via the System Config UI after super admin login.

| Variable | Description | Replacement |
|----------|-------------|-------------|
| `IDENTITY_PROVIDER_TYPE` | Deprecated. Previously selected the active identity provider mode. | DB-stored `provider_type` in `IdentityProviderConfig`. Only read during the one-time migration. |
| `OIDC_PROVIDER_URL` | Deprecated. Previously the base URL of the OIDC provider. | DB-stored `issuer_url` in `IdentityProviderConfig`. Only read during the one-time migration. |
| `OIDC_ISSUER_URL` | Deprecated. Previously the issuer URL for JWT `iss` validation. | DB-stored `issuer_url`. Only read during the one-time migration. |
| `OIDC_JWKS_URI` | Deprecated. Previously the JWKS endpoint URL. | Discovered automatically via `.well-known/openid-configuration` at the configured `issuer_url`. |
| `OIDC_CLIENT_ID` | Deprecated. Previously the OAuth2 client ID. | DB-stored `client_id` in `IdentityProviderConfig`. Only read during the one-time migration. |
| `OIDC_CLIENT_SECRET` | Deprecated. Previously the OAuth2 client secret. | DB-stored `encrypted_client_secret` in `IdentityProviderConfig`. Only read during the one-time migration. |
| `OIDC_REALM` | Deprecated. Previously the Keycloak realm name. | Absorbed into `issuer_url` path. Only read during the one-time migration. |
| `OIDC_AUDIENCE` | Deprecated. Previously the expected `aud` claim. | Absorbed into `scopes` / `claim_mappings` JSON configuration. Only read during the one-time migration. |
| `OIDC_AGENT_CLIENT_PREFIX` | Deprecated (Keycloak-specific). Previously the agent client ID prefix. | No direct replacement. Agent identity provider is configured as a separate DB entry. |
| `SERVICE_BOOTSTRAP_SOURCE_LOG` | Auto-enabled at INFO level on every service (CC, AR, CH) startup — logs which configuration source was resolved for every infrastructure connection. No action required; always active. | — |
| `KEYCLOAK_ADMIN` | Username for the bundled Keycloak admin account. Still required when running the bundled Keycloak container for dev/demo. Set on the Keycloak service — **not on the Control Center runtime service.** | — |
| `KEYCLOAK_ADMIN_PASSWORD` | Password for the bundled Keycloak admin account. Still required when running the bundled Keycloak container for dev/demo. Set on the Keycloak service — **not on the Control Center runtime service.** | ✓ |

### Configuration Precedence (Post-Refinement)

After the OIDC refinement change, the resolution order for identity provider settings is:

1. **Database** (`IdentityProviderConfig` rows) — source of truth at runtime
2. **Environment variables** — only read during the one-time migration; ignored at runtime after migration completes
3. **`config/identity.yaml`** — only read during the one-time migration; **not read at runtime after migration completes**

A missing `config/identity.yaml` after the migration has run is expected and does not cause an error. For new deployments that have never used the YAML file, OIDC providers are configured entirely via the System Config UI.

---

## Setup Tool

These variables are consumed exclusively by the consolidated setup CLI (`setup/` directory). **Do not set any of these on runtime service containers.** The setup tool is invoked explicitly by an operator — it is never triggered by application startup.

| Variable | Description | Secret |
|----------|-------------|--------|
| `KEYCLOAK_ADMIN` | Username for the Keycloak admin account (bundled Keycloak only). Must match the value configured on the Keycloak container. | |
| `KEYCLOAK_ADMIN_PASSWORD` | Password for the Keycloak admin account (bundled Keycloak only). Must match the value configured on the Keycloak container. | ✓ |
| `KEYCLOAK_URL` | Keycloak admin API base URL; used by the setup tool to reach the Keycloak Admin REST API (e.g., `http://keycloak:8080`). | |
| `SETUP_DEV_MODE` | Set to `true` to enable dev-mode data seeding. Skips realm bootstrap if the realm already exists. | |

### Setup Sub-Commands

| Command | Responsibility |
|---------|---------------|
| `setup identity` | Keycloak realm, client, role, and admin user provisioning |
| `setup database` | Database readiness verification, seeding of roles, permissions, and skills |
| `setup certificates` | Certificate authority bootstrapping for mTLS |
| `setup dev` | Full dev bootstrap: identity + database + certificates + test data |
| `setup verify` | Read-only check of current state without making changes |

> **Important:** The Control Center no longer auto-provisions Keycloak realms, clients, or roles at startup. Run the setup command BEFORE deploying backend services. All setup operations are idempotent — safe to run on an already-initialized environment.

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

These variables control certificate bootstrapping, caller identity normalization, and mTLS policy enforcement for the three-service deployment. They are required when running the services in decomposed mode and mandatory for deny-by-default internal API enforcement.

### Control Center (additional vars for decomposed mode)

| Variable | Description | Secret |
|----------|-------------|--------|
| `AGENT_RUNTIME_URL` | Agent Runtime service base URL (e.g., `http://agent-runtime:8001`) | |
| `COMMUNICATION_HUB_URL` | Communication Hub service base URL (e.g., `http://communication-hub:8002`) | |
| `SERVICE_CERT_VALIDITY_DAYS` | Service certificate validity period (default: `30`) | |
| `AGENT_INSTANCE_CERT_VALIDITY_HOURS` | Agent-instance certificate validity period (default: `24`) | |
| `AGENT_RUNTIME_BOOTSTRAP_KEY` | Unique bootstrap secret for Agent Runtime (min 32 chars, random) | ✓ |
| `COMM_HUB_BOOTSTRAP_KEY` | Unique bootstrap secret for Communication Hub (min 32 chars, random) | ✓ |
| `INTERNAL_API_POLICY_MODE` | Internal Control Center policy mode for caller-specific allowlists. Accepted values: `audit`, `enforce`. Start in `audit`; switch to `enforce` only after validation window completion. | |
| `INTERNAL_API_DENY_AUDIT_ENABLED` | Enables structured deny-event telemetry for blocked internal calls. Keep enabled in both `audit` and `enforce`. | |
| `INTERNAL_API_ALLOWLIST_VERSION` | Optional policy bundle version marker for deployment evidence, drift triage, and rollback coordination. | |
| `INTERNAL_API_REQUIRE_SERVICE_IDENTITY` | Requires caller identity extraction from validated service certificate before any internal route evaluation. | |
| `INTERNAL_API_FAIL_CLOSED_REVOCATION` | Enforces fail-closed behavior when certificate revocation status cannot be verified. Required in production. | |

### Agent Runtime (decomposed mode)

| Variable | Description | Secret |
|----------|-------------|--------|
| `SERVICE_IDENTITY` | Service identity name for certificate bootstrap (default: `agent-runtime`) | |
| `SERVICE_BOOTSTRAP_KEY` | Bootstrap secret matching `AGENT_RUNTIME_BOOTSTRAP_KEY` in Control Center | ✓ |
| `CERT_RENEWAL_THRESHOLD_HOURS` | Hours before expiry to trigger certificate renewal (default: `1`) | |
| `INTERNAL_CALLS_REQUIRE_MTLS` | Requires mTLS for all Agent Runtime calls to Control Center internal APIs in non-local environments. | |
| `INTERNAL_ALLOWLIST_CALLER_TYPE` | Caller type asserted for allowlist policy matching. Must be `agent_runtime`. | |

> **Removed in decomposed mode**: `DATABASE_URL` and `REDIS_URL` are no longer set on Agent Runtime — it has no direct database access.

### Communication Hub (decomposed mode)

| Variable | Description | Secret |
|----------|-------------|--------|
| `SERVICE_IDENTITY` | Service identity name for certificate bootstrap (default: `communication-hub`) | |
| `SERVICE_BOOTSTRAP_KEY` | Bootstrap secret matching `COMM_HUB_BOOTSTRAP_KEY` in Control Center | ✓ |
| `CERT_RENEWAL_THRESHOLD_HOURS` | Hours before expiry to trigger certificate renewal (default: `1`) | |
| `TOKEN_RESOLUTION_CACHE_TTL_SECONDS` | TTL for per-tool-call permission cache (default: `60`) | |
| `INTERNAL_CALLS_REQUIRE_MTLS` | Requires mTLS for all Communication Hub calls to Control Center internal APIs in non-local environments. | |
| `INTERNAL_ALLOWLIST_CALLER_TYPE` | Caller type asserted for allowlist policy matching. Must be `communication_hub`. | |

> **Removed in decomposed mode**: `DATABASE_URL` is no longer set on Communication Hub — it has no direct database access.

### Rollout Requirement Notes (Service Segregation Security Audit)

- `AGENT_RUNTIME_BOOTSTRAP_KEY` and `COMM_HUB_BOOTSTRAP_KEY` are mandatory for this rollout and must be rotated if provenance is unknown.
- `CONTROL_CENTER_URL` must point to the internal TLS endpoint used for mTLS trust validation.
- `CERT_RENEWAL_THRESHOLD_HOURS` must be explicitly set on Agent Runtime and Communication Hub to prevent certificate expiry during cutover.
- `INTERNAL_API_POLICY_MODE=enforce` is allowed only after a completed audit observation window with no unresolved allowlist drift.

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
| `KEYCLOAK_USER_REALM` | Keycloak realm that issues user identities. When empty (default), the app operates in **single-realm mode**: `verify_user_jwt` falls back to `KEYCLOAK_REALM` for issuer validation. When set to a realm name (e.g., `parthenon`), the app operates in **dual-realm mode**: `verify_user_jwt` uses this realm for issuer validation and a separate `user_keycloak_client` fetches JWKS from the user realm independently. | |
| `KEYCLOAK_USER_CLIENT_ID` | Client ID registered in the user realm for the demo app. When empty (default), falls back to `KEYCLOAK_CLIENT_ID`. Only needed in dual-realm mode when the user realm uses a different client than the agent realm. | |
