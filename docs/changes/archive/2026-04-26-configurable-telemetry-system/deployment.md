# Deployment Notes — Configurable Telemetry System

## Environment Variables

All new variables are optional. The system starts with safe defaults (console exporter, traces and metrics enabled, INFO log level) when none are set.

### Backend (`backend/app/core/config.py` — `TelemetrySettings`)

| Variable | Default | Description |
|---|---|---|
| `TELEMETRY_EXPORTER_TYPE` | `console` | Active exporter(s): `console`, `file`, `otlp`, `logfire`, `custom` (comma-separated for multi-target) |
| `TELEMETRY_TRACES_ENABLED` | `true` | Enable/disable trace collection |
| `TELEMETRY_METRICS_ENABLED` | `true` | Enable/disable metrics collection |
| `TELEMETRY_LOGS_ENABLED` | `true` | Enable/disable log collection via OTEL |
| `TELEMETRY_LOG_LEVEL` | `INFO` | Default log level applied to all components |
| `TELEMETRY_OTLP_ENDPOINT` | `http://otel-collector:4317` | OTLP Collector endpoint (used when exporter includes `otlp`) |
| `TELEMETRY_OTLP_PROTOCOL` | `grpc` | OTLP protocol: `grpc` or `http` |
| `TELEMETRY_OTLP_INSECURE` | `true` | Skip TLS for OTLP (set `false` in production with TLS) |
| `TELEMETRY_FILE_PATH` | _(none)_ | Log/trace output file path (required when exporter includes `file`) |
| `TELEMETRY_FILE_MAX_BYTES` | `10485760` | Max file size before rotation (bytes) |
| `TELEMETRY_FILE_BACKUP_COUNT` | `5` | Number of rotated backup files to keep |
| `TELEMETRY_LOGFIRE_TOKEN` | _(none)_ | Logfire ingest token (required when exporter includes `logfire`) |
| `TELEMETRY_CUSTOM_ENDPOINT` | _(none)_ | Custom HTTP endpoint URL (required when exporter includes `custom`) |
| `TELEMETRY_CONFIG_FILE` | _(none)_ | Path to optional `telemetry.yaml` config file override |

### Frontend

The frontend has no new environment variables. It fetches its telemetry config at startup from `GET /api/v1/telemetry/config` (see `frontend/src/api/telemetryApi.ts`). The only frontend OTEL env var that remains is the existing `VITE_OTEL_SERVICE_NAME` if present.

---

## New Configuration File

`config/telemetry.yaml` is an **optional** declarative override file. Environment variables always take precedence over values in this file (12-factor pattern). When absent, defaults from `TelemetrySettings` apply.

The file follows the structure defined by `TelemetrySettings` in `backend/app/core/config.py`. Key top-level keys:

| Key | Purpose |
|---|---|
| `exporter_type` | Same values as `TELEMETRY_EXPORTER_TYPE` |
| `traces_enabled` / `metrics_enabled` / `logs_enabled` | Signal enable flags |
| `log_level` | Default log level |
| `otlp` | Sub-object matching `OtlpExporterOptions` fields |
| `file` | Sub-object matching `FileExporterOptions` fields |
| `logfire` | Sub-object matching `LogfireExporterOptions` fields |
| `custom` | Sub-object matching `CustomExporterOptions` fields |

The annotated sample is at `config/telemetry.yaml` (committed to the repository). For Kubernetes, mount this file as a ConfigMap at the path specified by `TELEMETRY_CONFIG_FILE`.

---

## Infrastructure Changes

### OTEL Collector (`infra/otel-collector-config.yaml`)

No breaking changes to the existing Collector configuration. The Collector continues to accept OTLP on ports `4317` (gRPC) and `4318` (HTTP).

**If adding new export targets that bypass the Collector** (e.g., `logfire` or `custom`), those exporters push directly from the backend process — no Collector changes needed.

**Optional Collector updates** (not required for rollout, but recommended for production):

- Add a `logfile` exporter to archive raw OTLP data locally if the `file` exporter is enabled at the application level and you want Collector-level persistence as well.
- Adjust `memory_limiter.limit_mib` if throughput increases significantly after enabling previously-disabled signals.

### Kubernetes (Helm — `infra/helm/parthenon/`)

- Add `TELEMETRY_CONFIG_FILE` to the backend deployment env vars and mount `config/telemetry.yaml` as a ConfigMap volume if file-based config is preferred over per-pod env vars.
- No new services or sidecars required.

---

## Migration Steps

Perform these steps in order during rollout. No downtime is required.

1. **Merge and build** — Confirm the feature branch is merged and a new image is built. Verify `TelemetrySettings` loads without errors in a staging environment before touching production.

2. **Set environment variables** — Add any new telemetry env vars to the deployment config (Docker Compose `.env` or Kubernetes `Secret`/`ConfigMap`). Start conservatively: `TELEMETRY_EXPORTER_TYPE=otlp` with existing Collector endpoint to match prior behaviour.

3. **Deploy optional config file** — If using `config/telemetry.yaml` rather than env vars, place the file and set `TELEMETRY_CONFIG_FILE` to point to it. Confirm the file is readable by the backend process.

4. **Deploy backend** — Rolling restart (Kubernetes) or `docker compose up -d --no-deps backend` (Docker Compose). Watch startup logs for `Telemetry initialised` and exporter setup messages.

5. **Verify telemetry pipeline** — Confirm the OTEL Collector is receiving spans and metrics from the backend. Check Jaeger/Prometheus/Loki for fresh data. Look for any exporter error logs.

6. **Deploy frontend** (if a new frontend build is part of this release) — The frontend fetches telemetry config on load; no additional deployment steps needed.

7. **Validate frontend telemetry** — Open the browser devtools network tab and confirm the `GET /api/v1/telemetry/config` request returns `200` with the expected payload. Confirm browser spans appear in Jaeger.

8. **Enable additional signals or exporters** (optional, can be done post-deployment without restart) — Update env vars or the config file, then restart the backend to pick up changes. Log-level adjustments require a restart.

---

## Rollback Procedure

This change is backward-compatible. If rollback is needed:

1. **Revert to previous image** — Roll back the backend container to the previous image. The previous image ignores all new `TELEMETRY_*` env vars, so leaving them in place does not cause errors.

2. **Remove new env vars** (optional cleanup) — Remove any new `TELEMETRY_*` variables from the deployment config. Not required for rollback correctness, but avoids clutter.

3. **Remove config file** (optional) — Remove `config/telemetry.yaml` or unset `TELEMETRY_CONFIG_FILE`. Not required if the image is already rolled back.

4. **Verify prior telemetry** — Confirm the OTEL Collector is receiving spans/metrics/logs from the rolled-back backend. Behaviour should match pre-change state (hardcoded OTLP gRPC exporter).

There are no database migrations, schema changes, or persistent state changes in this feature. Rollback risk is low.

---

## Master Deployment Update Instructions

Update `docs/master/deployment/` as follows after this change ships:

- **`docs/master/deployment/environment-variables.md`** (or equivalent) — Add the new `TELEMETRY_*` env var table. Mark all as optional with their defaults. Note that env vars override file-based config.
- **`docs/master/deployment/configuration-files.md`** (or equivalent) — Add a section for `config/telemetry.yaml`: describe its purpose, the resolution order (env vars → file → defaults), and how to mount it in Kubernetes as a ConfigMap.
- **`docs/master/deployment/docker-compose.md`** (or equivalent) — Add a note about the optional `TELEMETRY_CONFIG_FILE` volume mount in the backend service definition.
- **`docs/master/deployment/kubernetes.md`** (or equivalent) — Document the ConfigMap pattern for `telemetry.yaml` and when to prefer file-based vs env-var-based config for multi-pod deployments.
