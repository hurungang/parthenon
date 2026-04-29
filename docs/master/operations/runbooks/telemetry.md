# Runbook: Telemetry System Issues

---

## 1. Telemetry Init Fails at Startup

### Symptoms

- Backend log at startup contains `[TELEMETRY ERROR] Failed to parse telemetry config`
- `Telemetry initialised` is never logged
- No spans appear in Jaeger; no metrics reach Prometheus

### Resolution Steps

1. Validate `config/telemetry.yaml` against the schema defined in `TelemetrySettings` (`backend/app/core/config.py`). Look for invalid YAML syntax, unrecognised keys, or typos in exporter type names. Valid exporter types are: `console`, `file`, `otlp`, `logfire`, `custom`.

2. If the error is hard to isolate, temporarily unset `TELEMETRY_CONFIG_FILE` and restart the backend. This causes the telemetry system to fall back to environment variable defaults, confirming whether the config file is the source of the error.

3. Once the file is corrected, restore `TELEMETRY_CONFIG_FILE` and restart the backend. Verify `Telemetry initialised` appears in the startup log.

---

## 2. No Spans Visible in Jaeger After Deployment

### Symptoms

- Jaeger shows no new traces; trace throughput drops to zero
- Application appears functional from a user perspective

### Resolution Steps

1. Check the backend startup log for `Telemetry signal disabled: traces`. If present, `TELEMETRY_TRACES_ENABLED` is `false` — update the environment variable or `config/telemetry.yaml` and restart.

2. Check that `TELEMETRY_EXPORTER_TYPE` includes `otlp`. If it does not, traces are not being forwarded to the Collector. Update the exporter list and restart the backend.

3. Verify the OTLP endpoint and protocol. Check `TELEMETRY_OTLP_ENDPOINT` and `TELEMETRY_OTLP_PROTOCOL`. The Collector must be accepting on the configured port: `4317` for gRPC, `4318` for HTTP.

4. Confirm the OTEL Collector container is running and healthy at `http://otel-collector:13133/`. If the health endpoint returns non-200, investigate the Collector's own logs for OOM errors or configuration problems.

5. Check Collector logs for export errors toward Jaeger. Verify that Jaeger is reachable from inside the Collector's network namespace.

---

## 3. Frontend OTEL Not Initialising (No Browser Spans in Jaeger)

### Symptoms

- No browser-side spans appear in Jaeger
- Backend spans are present, indicating the backend pipeline is healthy
- Browser console may show fetch errors or network warnings

### Resolution Steps

1. Open browser DevTools → Network → filter by `telemetry/config`. Check the response for `GET /api/v1/telemetry/config`:
   - **401**: The session token has expired. Ask the user to re-authenticate. `fetchTelemetryConfig()` returns a safe default on failure — the application continues normally in no-op OTEL mode.
   - **5xx**: Investigate backend health. Frontend OTEL is degraded until the backend recovers.
   - **200 with `traces_enabled: false`**: The backend has traces disabled. Update `TELEMETRY_TRACES_ENABLED` and restart the backend.

2. Inspect the full JSON response from the config endpoint. If both `traces_enabled` and `metrics_enabled` are `false`, update the relevant environment variables (`TELEMETRY_TRACES_ENABLED`, `TELEMETRY_METRICS_ENABLED`) and perform a rolling restart of the backend.

---

## 4. File Exporter Disk Fills Up

### Symptoms

- Host or container volume for the telemetry file path is reaching capacity
- Disk usage alerts firing on the `TELEMETRY_FILE_PATH` volume

### Resolution Steps

1. Reduce `TELEMETRY_FILE_MAX_BYTES` to limit the maximum size of each log file before rotation, or reduce `TELEMETRY_FILE_BACKUP_COUNT` to retain fewer rotated files. Both settings take effect on the next backend restart.

2. If the volume is already full, manually remove the oldest rotated files under `TELEMETRY_FILE_PATH` to recover space before restarting.

3. For production deployments with sustained high trace volume, switch the primary exporter from `file` to `otlp` (`TELEMETRY_EXPORTER_TYPE=otlp`) and let the OTEL Collector manage persistence. The file exporter is intended for local development and low-volume environments.

4. Confirm `TELEMETRY_FILE_PATH` is mounted to a volume with adequate capacity. In Kubernetes, verify the PersistentVolumeClaim size is appropriate for the configured rotation settings and trace throughput.

---

## 5. Logfire or Custom Endpoint Exporter Errors

### Symptoms

- Backend logs contain `[TELEMETRY ERROR] Exporter logfire failed` or `[TELEMETRY ERROR] Exporter custom failed`
- Traces or metrics are not reaching the Logfire dashboard or custom endpoint
- Other exporters in the pipeline may still be functioning

### Resolution Steps

1. Verify credentials and endpoint configuration:
   - For Logfire: confirm `TELEMETRY_LOGFIRE_TOKEN` is set and has not expired.
   - For custom endpoints: confirm `TELEMETRY_CUSTOM_ENDPOINT` is correct and reachable.

2. Test reachability from inside the backend container. Attempt an HTTP request to the exporter's endpoint from the container's network namespace to rule out DNS or firewall issues.

3. To prevent data loss while the issue is being resolved, add a fallback exporter. Set `TELEMETRY_EXPORTER_TYPE=otlp,logfire` (or `otlp,custom`) so traces continue to flow through the OTLP pipeline even if the secondary exporter fails. This ensures production data is preserved.

4. Once credentials or connectivity are restored, revert the exporter list if necessary and confirm the primary exporter begins receiving data again.

---

## 6. Log Level Not Changing After Config Update

### Symptoms

- `TELEMETRY_LOG_LEVEL` or `log_level` in `config/telemetry.yaml` has been updated
- Backend log verbosity has not changed
- No error is logged regarding the config change

### Resolution Steps

1. Log levels are applied once at startup. Runtime changes to `TELEMETRY_LOG_LEVEL` or `config/telemetry.yaml` have no effect until the backend process restarts.

2. Update the configuration and perform a rolling restart of the backend service. After restart, verify the expected log verbosity by checking for `DEBUG` lines (if increasing verbosity) or their absence (if reducing verbosity).

3. For component-level overrides (e.g., suppressing verbose `sqlalchemy` output while keeping `DEBUG` for the telemetry namespace), use the `log_levels` sub-keys in `config/telemetry.yaml`. These are also applied at startup only.
