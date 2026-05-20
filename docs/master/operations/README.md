# Operations Documentation — Parthenon Enterprise AI Harness

This section contains all operational reference material for running and maintaining a deployed Parthenon instance. It covers monitoring, logging, and step-by-step runbooks for the most common operational issues.

---

## Dashboards

| Dashboard | Purpose |
|-----------|---------|
| **Platform Overview** | One-glance system health: HTTP error rate, active agent instances, active WebSocket connections, scheduler queue depth |
| **Agent Engine** | Instance count per agent type, creation and destruction rate, response latency histogram |
| **MCP Hub** | Tool call rate heatmap by tool and session, error rate, latency p99 |
| **MCP Hub — Passthrough Sessions** | Active passthrough session count, passthrough tool call rate and success rate, JWT extraction rate, JWKS cache hit rate, passthrough tool latency p99 |
| **MCP Demo App** | Tool call rate, JWT validation failures, startup registration status, JWKS/token refresh failures |
| **Scheduling Engine** | Triggered vs. completed job counts over time, scheduler queue depth trend |
| **Infrastructure** | PostgreSQL connection count and query latency, Redis memory and eviction rate, OTEL Collector throughput |
| **Agent Runtime** | Session queue depth, session throughput and failure rate, dispatch latency, active runtime sessions, execution duration, LangGraph node transitions, permission cache hit rate, permission denials |

For metric definitions and alert thresholds, see [monitoring.md](monitoring.md).

---

## Log Sources

| Source | Access Method |
|--------|---------------|
| Container stdout/stderr (Docker Compose) | `docker compose logs <service>` or via Loki |
| Pod logs (Kubernetes) | `kubectl logs <pod-name>` or via Loki |
| Loki (aggregated) | Query via LogQL in Grafana or Loki API; all services ship structured logs via OTEL Collector |
| Jaeger (distributed traces) | Use `trace_id` from a log line to jump to the correlated trace in Jaeger UI |

For structured log fields and per-component event reference, see [logging.md](logging.md).

---

## Production Health Check Targets

The following endpoints must be included in production readiness checklists and uptime monitoring:

| Target | URL | Expected Response |
|--------|-----|-------------------|
| Platform API | `http://<backend-host>:8000/health` | `200 OK` |
| OTEL Collector | `http://otel-collector:13133/` | `200 OK` — any non-200 means telemetry data is being dropped |
| MCP Demo App | `http://mcp-demo-app:9000/health` | `{"status": "ok", "slug": "demo"}` with HTTP 200 |
| Certificate Authority | `http://<backend-host>:8000/api/v1/certificates/ca` | `200 OK` with `expires_at` field — any non-200 means CA is not initialized |

---

## Runbooks

| Runbook | Trigger Symptoms |
|---------|-----------------|
| [oidc-token-failure.md](runbooks/oidc-token-failure.md) | All API endpoints return 401; logs show `JWT validation error` or `JWKS fetch failed` |
| [mcp-credential-error.md](runbooks/mcp-credential-error.md) | MCP tool calls fail with auth errors; logs show `credential decryption failed` or `session not found` |
| [passthrough-session.md](runbooks/passthrough-session.md) | Passthrough tool calls fail with 401; logs show `No agent JWT available for passthrough session`; JWT validation failure alert firing; agent identity list empty |
| [agent-instance-limit.md](runbooks/agent-instance-limit.md) | New requests rejected with 429; logs show `max_instances reached for agent_type_id=<id>` |
| [scheduling-job-stuck.md](runbooks/scheduling-job-stuck.md) | Scheduled job triggered but never completes; scheduler queue depth growing |
| [communication-hub-disconnect.md](runbooks/communication-hub-disconnect.md) | Web UI shows disconnected state; agent responses stop; repeated `WebSocket disconnect` in logs |
| [telemetry.md](runbooks/telemetry.md) | Telemetry init failure at startup; no spans in Jaeger; frontend OTEL not initialising; file exporter disk pressure; Logfire or custom exporter credential errors; log level not applying |
| [agent-runtime.md](runbooks/agent-runtime.md) | Resolving stuck sessions, permission failures, OAuth expiry, timeouts, and queue backlogs in the Agent Runtime with LangGraph |
| [certificate-security.md](runbooks/certificate-security.md) | CA initialization failures, certificate expiry and renewal failures, certificate compromise response, agent identity token refresh failures, and token leakage investigation |
