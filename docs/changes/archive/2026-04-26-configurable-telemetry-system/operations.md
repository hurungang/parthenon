# Operations Notes — Configurable Telemetry System

## Monitoring

### What to Monitor

| Signal | Source | What to Watch |
|---|---|---|
| OTEL Collector health | `http://otel-collector:13133/` (health_check extension) | Returns `200` when healthy; alert on any non-200 |
| Backend telemetry init | Backend startup logs | Look for `Telemetry initialised` at process start; absence indicates init failure |
| Exporter error rate | Backend application logs (component: `telemetry`) | Log lines with `[TELEMETRY ERROR]` or exporter-specific SDK errors |
| File exporter disk usage | Host / container volume metrics | Monitor disk fill rate when `file` exporter is active; `TELEMETRY_FILE_MAX_BYTES` and backup count control rotation |
| Frontend config fetch | Backend API logs for `GET /api/v1/telemetry/config` | `4xx`/`5xx` responses mean the browser will fall back to a no-op OTEL provider |
| Trace throughput | Jaeger UI / Prometheus `parthenon_*` metrics | Sudden drop to zero may indicate exporter misconfiguration or Collector unavailability |
| Metrics delivery | Prometheus scrape target `otel-collector:8889` | Check `up` metric; gaps indicate Collector pipeline stall |

### Recommended Alerts

| Condition | Severity | Action |
|---|---|---|
| OTEL Collector health endpoint non-200 for > 2 minutes | Warning | Investigate Collector container; check logs for OOM or config errors |
| No traces ingested in Jaeger for > 10 minutes (production) | Warning | Check backend exporter config; verify Collector is running |
| Backend log contains `[TELEMETRY ERROR]` at startup | Critical | Telemetry init failed; operator action required (see Common Issues) |
| Disk usage on file exporter volume > 80% | Warning | Increase rotation settings or switch to OTLP exporter |
| `GET /api/v1/telemetry/config` returning `5xx` for > 5 minutes | Warning | Frontend OTEL degraded; investigate backend health |

---

## Logging

### What Gets Logged

All telemetry-related log entries use the `parthenon.telemetry` logger namespace.

| Event | Level | Message pattern | Location |
|---|---|---|---|
| Config file loaded | `INFO` | `Telemetry config loaded from <path>` | Backend startup |
| Config file missing (using defaults) | `INFO` | `Telemetry config file not found, using defaults` | Backend startup |
| Config file parse error | `ERROR` | `[TELEMETRY ERROR] Failed to parse telemetry config: <reason>` | Backend startup |
| Exporter initialised | `INFO` | `Telemetry exporter registered: <type>` | Backend startup (one line per exporter) |
| Signal disabled (no-op provider) | `INFO` | `Telemetry signal disabled: <traces|metrics|logs>` | Backend startup |
| Exporter runtime failure | `ERROR` | `[TELEMETRY ERROR] Exporter <type> failed: <reason>` | Backend runtime |
| Telemetry fully initialised | `INFO` | `Telemetry initialised` | Backend startup (final line) |
| Frontend config endpoint called | `DEBUG` | Standard FastAPI access log for `GET /api/v1/telemetry/config` | Backend API logs |

### Log Level Control

Log levels for individual components are set once at startup via `TELEMETRY_LOG_LEVEL` (or the `log_level` key in `config/telemetry.yaml`). Changing the level requires a backend restart. There is no runtime API to mutate log levels.

Component-level overrides (e.g., setting `sqlalchemy` to `WARNING` while keeping the rest at `DEBUG`) can be specified as sub-keys under `log_levels` in `config/telemetry.yaml` — see the annotated sample at `config/telemetry.yaml`.

---

## Common Issues

### 1. Telemetry init fails at startup — `[TELEMETRY ERROR] Failed to parse telemetry config`

**Cause**: `config/telemetry.yaml` contains invalid YAML or an unrecognised field.  
**Fix**: Validate the file against the schema defined in `TelemetrySettings` (`backend/app/core/config.py`). Check for typos in exporter type names (valid: `console`, `file`, `otlp`, `logfire`, `custom`). Temporarily unset `TELEMETRY_CONFIG_FILE` to fall back to env-var / default config.

---

### 2. No spans visible in Jaeger after deployment

**Possible causes and checks** (in order):

1. `TELEMETRY_TRACES_ENABLED` is `false` — check the backend startup log for `Telemetry signal disabled: traces`.
2. `TELEMETRY_EXPORTER_TYPE` does not include `otlp` — check that exporter list contains `otlp` for collector-bound export.
3. OTLP endpoint unreachable — check `TELEMETRY_OTLP_ENDPOINT` and `TELEMETRY_OTLP_PROTOCOL`; verify the Collector container is running and accepting on the configured port (`4317` for gRPC, `4318` for HTTP).
4. OTEL Collector pipeline stalled — check the Collector's own logs for errors; verify Jaeger is reachable from the Collector.

---

### 3. Frontend OTEL not initialising (no browser spans in Jaeger)

**Cause A**: `GET /api/v1/telemetry/config` is failing (network error, 401, 5xx).  
**Check**: Open browser devtools → Network → filter by `telemetry/config`. If `401`, the session token has expired. If `5xx`, investigate backend health.  
**Behaviour**: `fetchTelemetryConfig()` in `frontend/src/api/telemetryApi.ts` returns a safe default on failure — browser OTEL initialises in no-op mode; application continues normally.

**Cause B**: `traces_enabled` or `metrics_enabled` returned as `false` from the config endpoint.  
**Check**: Inspect the raw response from `GET /api/v1/telemetry/config`. If both signals are `false`, update `TELEMETRY_TRACES_ENABLED` / `TELEMETRY_METRICS_ENABLED` env vars and restart the backend.

---

### 4. File exporter disk fills up unexpectedly

**Cause**: Rotation settings too permissive for the export volume.  
**Fix**: Reduce `TELEMETRY_FILE_MAX_BYTES` or `TELEMETRY_FILE_BACKUP_COUNT`. Consider switching to `otlp` exporter and letting the Collector handle persistence. The file exporter path is defined by `TELEMETRY_FILE_PATH` — ensure it points to a volume with sufficient capacity and is mounted correctly in Kubernetes.

---

### 5. Logfire or custom endpoint exporter errors

**Cause**: Invalid or expired credentials / unreachable endpoint.  
**Check**: Look for `[TELEMETRY ERROR] Exporter logfire failed` or `[TELEMETRY ERROR] Exporter custom failed` in backend logs. Verify `TELEMETRY_LOGFIRE_TOKEN` or `TELEMETRY_CUSTOM_ENDPOINT` is set correctly. Test reachability from inside the backend container.  
**Mitigation**: Add `console` or `otlp` alongside the failing exporter as a fallback (`TELEMETRY_EXPORTER_TYPE=otlp,logfire`) so production data is not lost while the issue is resolved.

---

### 6. Telemetry config loaded but log level not changing

**Cause**: Log level is applied once at startup. Runtime changes have no effect until restart.  
**Fix**: Update `TELEMETRY_LOG_LEVEL` (or the `log_level` key in `config/telemetry.yaml`) and perform a rolling restart of the backend.

---

## Master Operations Update Instructions

Update `docs/master/operations/` as follows after this change ships:

- **`docs/master/operations/monitoring.md`** (or equivalent) — Add the monitoring table and recommended alerts from this document. Reference the OTEL Collector health endpoint and the telemetry-specific log patterns.
- **`docs/master/operations/logging.md`** (or equivalent) — Add the `parthenon.telemetry` logger namespace and the log event table. Document how to adjust log levels via `TELEMETRY_LOG_LEVEL` and when a restart is required.
- **`docs/master/operations/runbooks.md`** (or equivalent) — Add runbook entries for each Common Issue above: no spans in Jaeger, frontend OTEL not initialising, file exporter disk pressure, and exporter credential failures.
- **`docs/master/operations/health-checks.md`** (or equivalent) — Document the OTEL Collector health endpoint (`http://otel-collector:13133/`) as a required health check target in production readiness checklists.
