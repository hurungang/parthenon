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
| **Agent Runtime — SessionDispatcher** | Dispatcher poll cycles (`dispatcher.poll`); session dispatched to executor; stalled session warnings (`dispatcher.stalled`); max concurrency reached events |
| **Agent Runtime — AgentRuntimeExecutor** | Session status transitions (queued → running → completed/failed/timeout); LangGraph node transitions (`langgraph.node_transition`); LangGraph state machine errors |
| **Agent Runtime — AgentPermissionManager** | Permission cache hits and misses; full permission graph resolution; permission denied events; cache invalidation on role change |
| **Agent Runtime — AgentSessionService** | Session lifecycle events: enqueued, dispatched, running, completed, failed, timeout |
| **Communication Hub** | WebSocket connect and disconnect (with session ID and client identifier); message routing events; delivery failures |
| **Scheduling Engine** | Job trigger events (job ID, target agent type, cron expression); job completion (duration, status); missed or skipped executions (with reason); job store errors |
| **Notification Engine** | Notification dispatch attempt (channel type, recipient summary); delivery success and failure per channel (failure includes error detail) |
| **Telemetry System** (`parthenon.telemetry`) | Config file loaded, missing, or parse error; each exporter initialised; signals disabled (no-op provider); exporter runtime failures; telemetry fully initialised (`Telemetry initialised`); frontend config endpoint calls |
| **MCP Demo App** | Keycloak token grant success/failure at startup; Hub registration success/conflict/failure; tool manifest sync success/failure; incoming `tools/call` JWT validation pass/fail; `helloWorld` invocation completed; JWKS cache refresh; access token refresh |
| **Certificate Authority (CertificateManager)** | CA initialization success and failure; certificate issued (serial number, expiry); certificate renewed (old serial, new serial, expiry); certificate renewal failure (instance ID, error, attempt count); certificate revoked (serial number, reason, actor); certificate validation outcome (serial, CN, outcome: valid/expired/revoked/invalid) |
| **Control Center Internal Policy** | Caller normalization and internal allowlist decisions; deny-by-default events (`internal.allowlist.denied`) with reasons such as `unknown_internal_caller` and `endpoint_not_allowlisted` |
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

## Agent Runtime Log Events

### Log Sources

| Component | Log Source | Access |
|-----------|-----------|--------|
| `SessionDispatcher` | `backend` container stdout | `docker compose logs backend` or Loki: `{service="backend"} |= "session_dispatcher"` |
| `AgentRuntimeExecutor` | `backend` container stdout | `docker compose logs backend` or Loki: `{service="backend"} |= "runtime_executor"` |
| `AgentPermissionManager` | `backend` container stdout | Loki: `{service="backend"} |= "permission_manager"` |
| `AgentSessionService` | `backend` container stdout | Loki: `{service="backend"} |= "agent_session_service"` |
| `LifecycleHandler` (Gateway) | `backend` container stdout | Loki: `{service="backend"} |= "lifecycle_handler"` |

### Agent Session Lifecycle Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `session.enqueued` | INFO | `session_id`, `agent_type_id`, `triggered_by` | Session inserted with `status=queued` |
| `session.dispatched` | INFO | `session_id`, `agent_type_id`, `role_id` | `SessionDispatcher` picks up and hands to `AgentRuntimeExecutor` |
| `session.running` | INFO | `session_id`, `started_at` | Session status updated to `running` |
| `session.completed` | INFO | `session_id`, `duration_ms`, `output_size_bytes` | Session reached `completed` state |
| `session.failed` | ERROR | `session_id`, `error`, `duration_ms` | Session reached `failed` state; `error` contains the exception summary |
| `session.timeout` | WARN | `session_id`, `timeout_s`, `elapsed_ms` | Session exceeded the configured execution timeout |
| `langgraph.node_transition` | DEBUG | `session_id`, `from_node`, `to_node`, `state_snapshot` | LangGraph state machine transitions between nodes |

### Permission Evaluation Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `permission.cache_hit` | DEBUG | `role_id`, `tool_count` | Permission resolved from LRU cache |
| `permission.cache_miss` | DEBUG | `role_id` | Cache miss; DB query initiated |
| `permission.resolved` | INFO | `role_id`, `tool_count`, `duration_ms` | Full permission graph resolved from DB |
| `permission.denied` | WARN | `job_id`, `role_id`, `tool_id` | Agent attempted to call a tool not in its allowed set |
| `permission.cache_invalidated` | INFO | `role_id` | Role was updated or deleted; cache entry evicted |

### OAuth Identity Validation Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `identity.token_acquired` | DEBUG | `identity_id`, `identity_type` | Agent client credentials successfully exchanged for access token |
| `identity.token_refresh_failed` | ERROR | `identity_id`, `oidc_error` | Token refresh failed; OIDC provider error detail included |
| `identity.token_expired` | WARN | `identity_id`, `job_id` | Token discovered expired mid-execution |

---

## Certificate Security Log Events

### Log Sources

| Component | Log Source | Access |
|-----------|-----------|--------|
| `CertificateManager` | `backend` container stdout | `docker compose logs backend` or Loki: `{service="backend"} \|= "cert."` |
| `CertificateAuthority` | `backend` container stdout | Loki: `{service="backend"} \|= "ca.init"` |

### Certificate Lifecycle Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `ca.initialized` | INFO | `ca_serial`, `expires_at` | CA certificate loaded or generated at backend startup |
| `ca.initialization_failed` | ERROR | `error` | CA failed to initialize; certificate issuance and validation unavailable until backend restarts |
| `cert.issued` | INFO | `instance_id`, `serial_number`, `expires_at`, `agent_type_id` | New certificate issued to an agent instance |
| `cert.renewed` | INFO | `instance_id`, `old_serial`, `new_serial`, `expires_at` | Certificate automatically renewed before expiry |
| `cert.renewal_failed` | ERROR | `instance_id`, `serial_number`, `error`, `attempt` | Certificate renewal attempt failed; agent runtime shuts down gracefully after expiry if unresolved |
| `cert.revoked` | INFO | `serial_number`, `reason`, `revoked_by` | Certificate revoked via API; rejection is effective immediately on all subsequent validation calls |
| `cert.validation.valid` | DEBUG | `serial_number`, `cn`, `requested_operation`, `validated_by_service` | Certificate validated successfully; logged per validation call |
| `cert.validation.failed` | WARN | `serial_number`, `cn`, `outcome`, `failure_reason`, `validated_by_service` | Certificate validation rejected; `outcome` is one of `expired`, `revoked`, `invalid_signature`, or `unknown` |

---

## Internal API Boundary Log Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `internal.allowlist.denied` | WARN | `caller_type`, `caller_identity`, `method`, `endpoint`, `deny_reason`, `trace_id` | Internal request denied by caller-specific policy before handler execution |
| `internal.allowlist.allowed` | INFO | `caller_type`, `method`, `endpoint`, `trace_id` | Internal request allowed after caller-specific allowlist evaluation |

---

## MCP Demo App Log Events

All log entries are structured JSON and include `trace_id` and `span_id` for correlation with Jaeger traces.

**Log access:**
- Docker Compose: `docker compose logs mcp-demo-app`
- Loki: `{service="mcp-demo-app"}`

### Startup Sequence

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `keycloak.token_grant.success` | INFO | `realm`, `client_id`, `expires_in` | Successful client credentials grant at startup |
| `keycloak.token_grant.failure` | ERROR | `realm`, `client_id`, `error`, `status_code` | Failed client credentials grant; container will not serve requests |
| `hub.registration.success` | INFO | `slug`, `server_id` | Demo app registered with Hub; `server_id` is the assigned Hub record ID |
| `hub.registration.conflict` | INFO | `slug`, `existing_server_id` | 409 returned by Hub; existing record looked up and reused (idempotent) |
| `hub.registration.failure` | ERROR | `slug`, `error`, `status_code` | Hub unreachable or rejected registration; tool calls will not be routed |
| `hub.sync.success` | INFO | `slug`, `tools_synced` | Tool manifest synced to Hub after registration |
| `hub.sync.failure` | ERROR | `slug`, `error` | Tool sync failed; Hub tool list may be stale |

### Request Handling

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `mcp.tools_call.received` | INFO | `tool_name`, `agent_sub`, `trace_id` | Incoming `tools/call` request with valid JWT |
| `mcp.tools_call.completed` | INFO | `tool_name`, `agent_sub`, `duration_ms` | Tool handler returned successfully |
| `mcp.jwt_validation.failure` | WARN | `error`, `token_hint` (first 8 chars of JWT), `trace_id` | Bearer token failed validation; 401 returned to caller |
| `mcp.method_not_found` | WARN | `method`, `trace_id` | JSON-RPC method not implemented; -32601 returned to caller |
| `keycloak.jwks.refreshed` | DEBUG | `keys_count`, `cache_age_s` | JWKS cache refreshed (every 10 min) |
| `keycloak.token.refreshed` | DEBUG | `expires_in`, `refreshed_at` | Access token refreshed (~30 s before expiry) |
| `identity.token_refresh` | DEBUG | `identity_id` | Existing token refreshed before expiry |
| `identity.token_refresh_failed` | ERROR | `identity_id`, `oidc_error` | Token refresh failed; includes OIDC provider error detail |
| `identity.token_expired` | WARN | `identity_id`, `job_id` | Token discovered to have expired mid-execution |

### Session Queue Worker Events

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `dispatcher.poll` | DEBUG | `queued_count`, `worker_slots_available` | Each poll cycle of the `SessionDispatcher` background worker |
| `dispatcher.stalled` | WARN | `session_id`, `stalled_for_s` | A session has been `running` longer than the stall threshold |
| `dispatcher.max_concurrency_reached` | INFO | `active_sessions` | Worker skipped dispatch because concurrency limit was reached |

### Trace Correlation

All agent session operations are wrapped in an OpenTelemetry trace. The `trace_id` appears in every log line emitted during the session's execution span. Use the `trace_id` from a session failure log to locate the full distributed trace in Jaeger, which shows the complete call graph:

`LifecycleHandler → AgentSessionService → SessionDispatcher → AgentRuntimeExecutor → AgentPermissionManager → LangGraph State Graph → Skill Engine → MCP Hub`

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
