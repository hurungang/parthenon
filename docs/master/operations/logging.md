# Logging — Reference

Every Parthenon service emits structured JSON log lines carrying the same correlation fields, so a single request can be followed from the Web UI through Communication Hub, Agent Runtime, and Control Center into Jaeger. This page is the operator entry point: it defines log levels, the correlation contract, and where logs live — the per-component event reference is split across the topic pages below.

---

## Topic Index

| Topic page | Covers |
|------------|--------|
| [logging-platform.md](logging-platform.md) | One row per component; startup validation events; configuration-source resolution; setup tool output; telemetry subsystem |
| [logging-agents.md](logging-agents.md) | Agent Runtime session, permission, and identity events; guardrail events, canonical reason taxonomy, required fields |
| [logging-security.md](logging-security.md) | Multi-tenancy events; super admin and OIDC identity; auth pipeline; security guardrails; certificate lifecycle; internal API boundary |
| [logging-integrations.md](logging-integrations.md) | MCP demo app; API-key auth and management; third-party client integration and its usage audit table |
| [logging-control-center-assistant.md](logging-control-center-assistant.md) | `cc____` management tools and permissions; MCP OAuth plane; `cc` entity guards; assistant seed; meta-tool dispatch; catalog anomalies |
| [logging-conversation-turns.md](logging-conversation-turns.md) | Conversation turn lifecycle; interventions (confirmation/HITL); conversation activity and resumable-turn events with grep hints |

Need a specific event name? Search the per-component table in [logging-platform.md](logging-platform.md) first; it names every emitting component and the events it produces.

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

### Log Files and Rotation

**Log files** (from `docs/config.yaml`): `backend/logs/control-center.log`, `backend/logs/communication-hub.log`, `backend/logs/agent-runtime.log`, `backend/logs/otel.log`. Files rotate at ~10 MB with `.1`/`.2` retained.

### Local / Docker Compose

Container standard output and standard error streams are the primary log source. Logs are also shipped to Loki via the OTEL Collector's OTLP log pipeline when the collector is running.

Use `docker compose logs -f <service-name>` to tail logs from a specific service in real time.

### Kubernetes

Pod logs are available via `kubectl logs <pod-name> -n <namespace>`. For multi-replica services, use `-l app=<service-name>` to aggregate logs across all replicas of a service.

Pod logs are also forwarded to Loki by the OTEL Collector daemonset, enabling persistent log retention beyond the pod lifecycle.

### Loki (Aggregated Log Store)

The primary log aggregation backend for all environments. Query using LogQL in the Grafana Explore view or via the Loki HTTP API.

Useful LogQL queries:
- Filter by service: `{service_name="control-center"}`
- Filter by session: `{session_id="<id>"}`
- Filter by trace: `{trace_id="<id>"}`
- Filter by error level: `{service_name="agent-engine"} |= "ERROR"`

### OIDC and Super Admin Logs

All OIDC-related and super admin log events are emitted by the Control Center service and written to `backend/logs/control-center.log`. This includes super admin login events, auth middleware decisions, OIDC Discovery/JWKS fetch, provider config changes, and registry reload events.

Grep patterns for troubleshooting:
- Search for `superadmin.` to find super admin auth events
- Search for `oidc.config.` to find provider configuration changes
- Search for `oidc.discovery.` or `oidc.jwks.` to find provider connectivity issues
- Search for `auth.pipeline.` to find which auth tier handled each request
- Search for `oidc.registry.` to find registry initialization and reload events

### Three-Service Architecture Log Access

| Source | Docker Compose | Kubernetes | Loki |
|--------|---------------|------------|------|
| CC startup validation | `docker compose logs control-center` | `kubectl logs <cc-pod>` | `{service_name="control-center"} \|= "startup.validation"` |
| AR startup validation | `docker compose logs agent-runtime` | `kubectl logs <ar-pod>` | `{service_name="agent-runtime"} \|= "startup.validation"` |
| CH startup validation | `docker compose logs communication-hub` | `kubectl logs <ch-pod>` | `{service_name="communication-hub"} \|= "startup.validation"` |
| Configuration source | `docker compose logs <service>` | `kubectl logs <pod>` | `{service_name=~".+"} \|= "config."` |
| Setup tool output | stdout of the setup command/job | stdout of the setup Job pod | Not shipped to Loki (setup is a one-shot operation) |

### Jaeger (Distributed Traces)

Use the `trace_id` from any log line to jump directly to the correlated distributed trace in the Jaeger UI. This cross-reference is the primary tool for debugging multi-component failures where a single request spans several services.

---

## Forwarding Pointers

These section names are referenced by other documents; their content now lives on the linked topic page.

### Agent Execution Guardrail Events

Guardrail event names, reason taxonomy, required fields, and sensitive-data exclusions → [logging-agents.md](logging-agents.md).

### Internal API Boundary Log Events

`internal.*` allow/deny events, required fields, and the boundary incident query guide → [logging-security.md](logging-security.md).

### Multi-Tenancy Log Events

`tenant.*` event prefixes, levels, key fields, and troubleshooting greps (only emitted while `multi_tenancy_enabled` is on) → [logging-security.md](logging-security.md).

### Control Center Assistant Events

Management-tool, MCP OAuth, `cc` entity, assistant seed, meta-tool, catalog, and audit-attribution events → [logging-control-center-assistant.md](logging-control-center-assistant.md).

### Conversation Activity and Resumable Turn Events

Activity upsert/hydration/touch, checkpoint, claim, resume dispatch, and terminal-resolution events with grep hints → [logging-conversation-turns.md](logging-conversation-turns.md).
