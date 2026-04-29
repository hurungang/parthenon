# Logging — Reference

## Per-Component Log Events

Update this table whenever new components are added or new log events are instrumented.

| Component | Log Events |
|-----------|------------|
| **Platform API** | Auth token validation pass/fail; admin configuration mutations (create, update, delete); OIDC client provisioning calls; inbound request errors (4xx, 5xx) |
| **Agent Engine** | Instance creation and destruction; instance limit rejection (max_instances reached); LLM provider call start, end, and error; skill dispatch start and end |
| **Skill Engine** | Skill resolution success and failure; SOP step execution (each step start and result); agent delegation events |
| **MCP Hub** | Tool server registration; tool sync results (tools added, updated, removed); session credential resolution (no credential values logged); tool call dispatch and result (error details only, never payload data) |
| **Agent Gateway** | Lifecycle protocol events (init, request, question, answer, close); session handle issuance; consumer authentication failures |
| **Communication Hub** | WebSocket connect and disconnect (with session ID and client identifier); message routing events; delivery failures |
| **Scheduling Engine** | Job trigger events (job ID, target agent type, cron expression); job completion (duration, status); missed or skipped executions (with reason); job store errors |
| **Notification Engine** | Notification dispatch attempt (channel type, recipient summary); delivery success and failure per channel (failure includes error detail) |
| **Telemetry System** (`parthenon.telemetry`) | Config file loaded, missing, or parse error; each exporter initialised; signals disabled (no-op provider); exporter runtime failures; telemetry fully initialised (`Telemetry initialised`); frontend config endpoint calls |
| **All components** | Service startup and shutdown with configuration summary; health check results; unhandled exceptions with full stack trace |

---

## Log Levels

| Level | When Used |
|-------|-----------|
| `ERROR` | Unhandled exceptions; failed external calls (LLM, MCP server, OIDC JWKS); authentication rejections; data integrity failures |
| `WARNING` | Degraded behaviour that does not halt execution — instance limit approaching, upstream retry triggered, slow external call, cache miss on expected hit |
| `INFO` | Normal operational events — instance created, tool call dispatched, job triggered, notification sent, WebSocket connected |
| `DEBUG` | Verbose request and response details for development and troubleshooting; disabled in production by default; never include credential values at any level |

---

## Correlation Fields

Every structured log line must include the following fields to enable cross-component and cross-system tracing.

| Field | Description |
|-------|-------------|
| `trace_id` | OTEL trace ID — links this log line to the distributed trace for the same operation in Jaeger |
| `span_id` | OTEL span ID — identifies the specific span within the distributed trace |
| `agent_instance_id` | Unique ID of the active agent instance; present when the log line is emitted within an agent execution context |
| `session_id` | Communication Hub or Agent Gateway session identifier; links log lines from multiple components involved in the same session |
| `service_name` | Name of the emitting service; matches the value of `OTEL_SERVICE_NAME` for this container |
| `timestamp` | ISO 8601 UTC timestamp with millisecond precision |

---

## Where to Find Logs

### Local / Docker Compose

Container standard output and standard error streams are the primary log source. Logs are also shipped to Loki via the OTEL Collector's OTLP log pipeline when the collector is running.

Use `docker compose logs -f <service-name>` to tail logs from a specific service in real time.

### Kubernetes

Pod logs are available via `kubectl logs <pod-name> -n <namespace>`. For multi-replica services, use `-l app=<service-name>` to aggregate logs across all replicas of a service.

Pod logs are also forwarded to Loki by the OTEL Collector daemonset, enabling persistent log retention beyond the pod lifecycle.

### Loki (Aggregated Log Store)

The primary log aggregation backend for all environments. Query using LogQL in the Grafana Explore view or via the Loki HTTP API.

Useful LogQL queries:
- Filter by service: `{service_name="platform-api"}`
- Filter by session: `{session_id="<id>"}`
- Filter by trace: `{trace_id="<id>"}`
- Filter by error level: `{service_name="agent-engine"} |= "ERROR"`

### Jaeger (Distributed Traces)

Use the `trace_id` from any log line to jump directly to the correlated distributed trace in the Jaeger UI. This cross-reference is the primary tool for debugging multi-component failures where a single request spans several services.

---

## Telemetry System Log Events (`parthenon.telemetry`)

All telemetry-related log entries use the `parthenon.telemetry` logger namespace. These events are emitted by the backend and can be used to verify the telemetry pipeline is functioning correctly.

| Event | Level | Message Pattern |
|-------|-------|-----------------|
| Config file loaded | `INFO` | `Telemetry config loaded from <path>` |
| Config file missing — using defaults | `INFO` | `Telemetry config file not found, using defaults` |
| Config file parse error | `ERROR` | `[TELEMETRY ERROR] Failed to parse telemetry config: <reason>` |
| Exporter initialised | `INFO` | `Telemetry exporter registered: <type>` (one line per exporter) |
| Signal disabled (no-op provider) | `INFO` | `Telemetry signal disabled: <traces\|metrics\|logs>` |
| Exporter runtime failure | `ERROR` | `[TELEMETRY ERROR] Exporter <type> failed: <reason>` |
| Telemetry fully initialised | `INFO` | `Telemetry initialised` |
| Frontend config endpoint called | `DEBUG` | Standard FastAPI access log for `GET /api/v1/telemetry/config` |

### Log Level Control

The log level for the telemetry system is set once at startup and cannot be changed at runtime without a restart. To change it:

- Set the `TELEMETRY_LOG_LEVEL` environment variable, **or**
- Update the `log_level` key in `config/telemetry.yaml`
- Perform a rolling restart of the backend

Component-level overrides (e.g., setting `sqlalchemy` to `WARNING` while keeping the rest at `DEBUG`) are specified as sub-keys under `log_levels` in `config/telemetry.yaml`. See `config/telemetry.yaml` for the annotated sample.
