# Configuration Files — Master Reference

Parthenon supports file-based configuration as an alternative (or complement) to environment variables for settings that are verbose or need to be shared across multiple pods. This document covers all platform-managed configuration files and how to deploy them.

---

## Resolution Order

For all settings that support both environment variables and a configuration file, the resolution order is:

1. **Environment variables** — highest precedence; always override file values
2. **Configuration file values** — applied when the corresponding env var is not set
3. **Built-in defaults** — applied when neither an env var nor a file value is present

This follows the [12-factor app](https://12factor.net/) principle: environment variables are the authoritative override mechanism.

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
