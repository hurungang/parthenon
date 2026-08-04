# Configuration Files — Master Reference

Parthenon supports file-based configuration as an alternative (or complement) to environment variables for settings that are verbose or need to be shared across multiple pods. This document covers all platform-managed configuration files and how to deploy them.

---

## Services With No Configuration Files

**`mcp-demo-app`** — The MCP Demo App reads all configuration from environment variables. A template file at `mcp-demo-app/.env.example` documents all supported variables with defaults and commentary. The `.env.example` file includes the optional `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID` variables for dual-realm mode. See [environment-variables.md](environment-variables.md) for the full variable reference.

---

## Resolution Order

For all settings that support both environment variables and a configuration file, the resolution order is:

1. **Environment variables** — highest precedence; always override file values
2. **Configuration file values** — applied when the corresponding env var is not set
3. **Built-in defaults** — applied when neither an env var nor a file value is present

This follows the [12-factor app](https://12factor.net/) principle: environment variables are the authoritative override mechanism.

> **Scope:** This env-var-first resolution order now applies to **all** infrastructure connections — PostgreSQL (`POSTGRES_*` / `DATABASE_URL`), Redis (`REDIS_*` / `REDIS_URL`), OIDC identity provider (`OIDC_*`), and telemetry (`TELEMETRY_*`). Previously this was limited to telemetry configuration only. The `SERVICE_BOOTSTRAP_SOURCE_LOG` variable (always enabled at INFO level) logs the resolved configuration source for every infrastructure connection on startup.

---

## `config/telemetry.yaml`

**Purpose**: Declarative override file for backend telemetry configuration. Allows operators to express the full telemetry setup in a single versioned file rather than managing a large set of individual environment variables. Particularly useful for Kubernetes deployments where the same settings apply to all replicas.

**Status**: Optional. The backend starts with safe defaults when the file is absent.

**Source file**: `config/telemetry.yaml` (committed to the repository as an annotated sample)

**Loaded by**: `backend/app/core/config.py` (`TelemetrySettings`). The file path is supplied via `TELEMETRY_CONFIG_FILE`.

### Top-level keys

| Key | Purpose |
|-----|---------|
| `exporter_type` | Active exporter(s); comma-separated string. Matches `TELEMETRY_EXPORTER_TYPE`. |
| `traces_enabled` | Boolean; enable or disable trace collection. |
| `metrics_enabled` | Boolean; enable or disable metrics collection. |
| `logs_enabled` | Boolean; enable or disable log collection via OTEL. |
| `log_level` | Default log level string (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `otlp` | Sub-object matching `OtlpExporterOptions` fields (`endpoint`, `protocol`, `insecure`). |
| `file` | Sub-object matching `FileExporterOptions` fields (`path`, `max_bytes`, `backup_count`). |
| `logfire` | Sub-object matching `LogfireExporterOptions` fields (`token`). |
| `custom` | Sub-object matching `CustomExporterOptions` fields (`endpoint`). |

### Docker Compose

In Docker Compose deployments, mount the file as a bind mount in the `backend` service definition and set `TELEMETRY_CONFIG_FILE` to the in-container path.

The file should be placed outside the image (not baked in) so it can be updated without rebuilding. The compose service definition in `docker-compose.yml` should bind-mount `./config/telemetry.yaml` to a path such as `/app/config/telemetry.yaml` and set `TELEMETRY_CONFIG_FILE=/app/config/telemetry.yaml`.

If per-environment overrides are needed, keep a base file at `config/telemetry.yaml` and layer environment-specific values with env vars — no need for multiple file variants.

### Kubernetes

In Kubernetes, create a ConfigMap from `config/telemetry.yaml` and mount it into the backend Deployment as a volume. The Helm chart (`infra/helm/parthenon/`) should define:

- A `ConfigMap` resource containing the telemetry.yaml content
- A `volume` in the backend Deployment spec referencing the ConfigMap
- A `volumeMount` in the backend container mounting the ConfigMap at a deterministic path (e.g., `/app/config/telemetry.yaml`)
- `TELEMETRY_CONFIG_FILE=/app/config/telemetry.yaml` in the container env block

**When to prefer file-based config over env vars in Kubernetes**: Use the ConfigMap approach when:
- The same telemetry settings apply to all replicas of the backend pod
- You want to version-control the full telemetry configuration as a single artifact
- The configuration involves nested options (OTLP sub-object, file rotation settings) that become unwieldy as individual env vars

**When to prefer env vars**: Use env vars when:
- Settings differ per pod or per namespace (inject at deploy time without touching the ConfigMap)
- A secret value is involved (Logfire token — use a Kubernetes Secret, not a ConfigMap)
- Making a quick targeted override without redeploying the config volume

> **Security note**: `config/telemetry.yaml` must not contain secret values (e.g., `logfire.token`). Supply secrets via environment variables backed by Kubernetes Secrets. The ConfigMap is not encrypted at rest by default.

---

## `config/identity.yaml`

**Purpose**: File-based identity provider configuration for deployments that use the bundled Keycloak provider. Written automatically by the consolidated setup tool (`setup identity`) — operators should NOT hand-edit this file.

**Status**: Relevant for bundled Keycloak deployments (`IDENTITY_PROVIDER_TYPE=keycloak_bundled`). For greenfield deployments using external OIDC providers (non-bundled Keycloak), `config/identity.yaml` is not needed — all identity provider configuration is managed through the System Config UI and stored in the database. For existing deployments that previously used this file, migration to database-backed config is available.

**Source file**: `config/identity.yaml` (generated at deploy time by the setup tool — not committed to the repository)

**Loaded by**: `backend/app/core/config.py` (OIDC settings resolution). Environment variables always take precedence over file values.

### When it is written

The consolidated setup tool writes `config/identity.yaml` when running `setup identity` for bundled Keycloak deployments. The file contains:

- `OIDC_CLIENT_ID` — the OAuth2 client ID provisioned in the Keycloak realm
- `OIDC_CLIENT_SECRET` — stored encrypted in the database; the YAML file records the client ID for reference
- `OIDC_REALM` — the Keycloak realm name (defaults to `parthenon`)
- `OIDC_PROVIDER_URL` — the Keycloak realm base URL
- `OIDC_AUDIENCE` — the token audience value

### Resolution order (OIDC settings)

1. **Environment variable** (`OIDC_*`) — highest precedence; always overrides file values
2. **Value in `config/identity.yaml`** — applied when the corresponding env var is not set
3. **Built-in default** — applied when neither source is present (e.g., Keycloak URL defaults to `http://keycloak:8080/realms/parthenon`)

A missing `config/identity.yaml` is treated as an empty configuration and does not cause an error. Teams that manage all OIDC configuration through environment variables (typical for external providers) can omit the file entirely.

> **Note on identity provider registration:** The `config/identity.yaml` file covers connection-level settings. Identity provider registration and discovery (OIDC Provider Registry) is managed in the database via the `IdentityProviderConfig` table and the System Config UI. The `config/identity.yaml` file is a separate concern — it provides the initial connection configuration that the Control Center uses during startup validation.
