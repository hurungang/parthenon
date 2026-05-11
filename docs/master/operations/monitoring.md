# Monitoring — Reference

## Key Metrics by Component

Update this table whenever new components are added or new metrics are instrumented.

| Component | Metric | Why It Matters |
|-----------|--------|----------------|
| **Agent Engine** | Active instance count per agent type | Detect instance saturation before new requests start being rejected |
| **Agent Engine** | Instance creation rate | A spike indicates sudden load; a sustained drop indicates scheduling or dispatch failures |
| **Agent Engine** | Agent response latency p50/p99 | SLA signal; p99 degradation typically precedes instance exhaustion |
| **MCP Hub** | Tool call rate per tool and session | Identifies hot tools and sessions that may be approaching rate limits |
| **MCP Hub** | Tool call error rate | Elevated error rate points to credential issues or upstream MCP server failures |
| **MCP Hub** | Tool call latency p99 | Upstream MCP server performance signal; affects overall agent response time |
| **Skill Engine** | Skill execution duration p99 | Detects runaway SOP chains or slow tool call sequences |
| **Communication Hub** | Active WebSocket connections | Capacity planning; an unexpected drop to near zero signals a hub restart or connection shedding event |
| **Communication Hub** | Message delivery latency | Real-time responsiveness signal for the user-to-agent chat interface |
| **Scheduling Engine** | Jobs triggered vs. jobs completed | Divergence between triggered and completed counts indicates stuck or missed scheduled runs |
| **Scheduling Engine** | Scheduler queue depth | A consistently growing queue depth signals an engine backlog |
| **Notification Engine** | Notification delivery success rate per channel | Per-channel failure rate distinguishes platform-side issues from external provider problems |
| **Platform API** | HTTP error rate (4xx and 5xx) | General API health; 5xx rate is a primary alerting threshold |
| **Platform API** | Request latency p99 | API responsiveness signal for admin configuration operations |
| **PostgreSQL** | Active connection count | Approaching connection limit can starve services of database access |
| **PostgreSQL** | Query latency p99 | Slow queries affect all dependent services |
| **PostgreSQL** | Replication lag | Signals potential data loss risk in replicated deployments |
| **Redis** | Memory usage | Approaching the memory limit triggers eviction, which disrupts session context and pub/sub |
| **Redis** | Eviction rate | Any eviction indicates cache sizing is insufficient |
| **Redis** | Connected clients | Monitors pub/sub subscriber health |
| **OTEL Collector** | Span ingestion rate | Confirms telemetry is flowing from all services |
| **OTEL Collector** | Export error rate | Indicates problems shipping telemetry to Prometheus, Jaeger, or Loki backends |
| **OTEL Collector** | Health endpoint (`http://otel-collector:13133/`) | Returns `200` when healthy; any non-200 response indicates the Collector is unavailable and telemetry data is being dropped |
| **Telemetry System** | Backend startup log — `Telemetry initialised` | Absence at process start indicates init failure; all instrumentation is inactive until this line is logged |
| **Telemetry System** | Backend application log — `[TELEMETRY ERROR]` | Exporter or config errors; may indicate data loss without operator action |
| **Telemetry System** | File exporter disk usage on `TELEMETRY_FILE_PATH` volume | Monitor fill rate when file exporter is active; rotation is controlled by `TELEMETRY_FILE_MAX_BYTES` and `TELEMETRY_FILE_BACKUP_COUNT` |
| **Telemetry System** | `GET /api/v1/telemetry/config` response code | `4xx`/`5xx` responses cause the frontend to fall back to a no-op OTEL provider — browser spans will not be sent |
| **Telemetry System** | Trace throughput in Jaeger | A sudden drop to zero may indicate exporter misconfiguration or Collector unavailability |
| **Telemetry System** | Prometheus scrape target `otel-collector:8889` (`up` metric) | Gaps indicate a Collector pipeline stall; metrics delivery is interrupted |
| **Agent Session Queue** | `agent.session.queue_depth` | Number of sessions in `queued` state; growing depth indicates dispatcher stall or concurrency saturation |
| **Agent Session Queue** | `agent.session.dispatch_latency` (p50, p99) | Time from session enqueue to first dispatch attempt; p99 > 30 s triggers alert |
| **Agent Session Queue** | `agent.session.failures_total` | Sessions reaching the `failed` terminal state; rate > 5/min is critical |
| **Agent Session Queue** | `agent.session.timeouts_total` | Sessions that exceeded the configured execution timeout; any sustained non-zero rate requires attention |
| **Agent Session Queue** | `agent.session.completed_total` | Sessions reaching `completed`; used to derive the success rate: `completed / (completed + failed)` — alert if < 0.95 |
| **Agent Runtime** | `agent.runtime.active_sessions` | Sessions currently in `running` state; alert if it exceeds the configured `max_concurrent_sessions` |
| **Agent Runtime** | `agent.runtime.execution_duration` (p50, p99) | Total wall-clock time per session from dispatch to completion; p99 > configured session timeout triggers alert |
| **Agent Runtime** | `agent.runtime.permission_denials_total` | Tool call attempts denied by the Permission Manager; any sustained non-zero rate requires role assignment review |
| **Agent Runtime** | `agent.runtime.llm_call_duration` (p99) | Time waiting for LLM inference response; p99 > 60 s indicates LLM provider latency issues |
| **Agent Runtime** | `agent.runtime.langgraph_node_transitions_total` | Total LangGraph state node transitions across all sessions; used for operational diagnostics |
| **Agent Runtime** | `agent.runtime.langgraph_errors_total` | LangGraph state machine errors (invalid transitions, missing nodes); any non-zero rate requires investigation |
| **Agent Permission Manager** | `agent.permission.cache_hits_total` | Permission resolution requests served from LRU cache |
| **Agent Permission Manager** | `agent.permission.cache_misses_total` | Permission resolution requests that required a full DB query |
| **Agent Permission Manager** | `agent.permission.cache_hit_rate` (derived) | `cache_hits / (cache_hits + cache_misses)`; below 80% indicates frequent role mutations or undersized cache |
| **Agent Permission Manager** | `agent.permission.resolution_duration` (p99) | Time to resolve the full SOP → Skill → MCP tool graph; p99 > 500 ms triggers alert |
| **Agent Identity** | `agent.identity.token_refresh_failures_total` | Failed OIDC token refresh attempts for agent client credentials; any sustained rate is critical |

---

## Dashboards to Create

### Platform Overview
Single-pane health summary intended for on-call operators. Include: Platform API HTTP error rate (4xx/5xx), total active agent instances across all types, active WebSocket connection count, and scheduler queue depth. Use thresholds and colour coding to make alarm states immediately visible.

### Agent Engine
Detailed agent execution view. Include: instance count per agent type as a stacked time series, instance creation and destruction rates, and an agent response latency histogram showing p50 and p99 percentiles.

### MCP Hub
Tool call analysis view. Include: tool call rate as a heatmap bucketed by tool name and session, tool call error rate as a percentage, and tool call latency p99 as a time series.

### Scheduling Engine
Schedule health view. Include: triggered job count and completed job count overlaid on the same time axis (divergence is immediately visible), and scheduler queue depth trend.

### Infrastructure
Low-level component health. Include: PostgreSQL active connection count, PostgreSQL query latency p99, Redis memory usage as a percentage of configured limit, Redis eviction rate, and OTEL Collector span throughput and export error count.

### Telemetry System
Telemetry pipeline health. Include: OTEL Collector health endpoint status over time, backend `[TELEMETRY ERROR]` log event count, `GET /api/v1/telemetry/config` error rate, file exporter disk usage (when file exporter is active), and trace throughput in Jaeger as a time series.

### Agent Runtime Dashboard
Agent runtime execution health. Add alongside the existing Agent Engine and MCP Hub dashboards. Panels:

- **Session Queue Depth** — `agent.session.queue_depth` as a time series with a horizontal threshold line at the alert level.
- **Session Throughput** — `agent.session.completed_total` and `agent.session.failures_total` as stacked bars; failure rate as a percentage line overlay.
- **Session Dispatch Latency** — `agent.session.dispatch_latency` p50 and p99 as a dual-line time series.
- **Active Runtime Sessions** — `agent.runtime.active_sessions` gauge with max-concurrent marker.
- **Execution Duration** — `agent.runtime.execution_duration` p99 histogram.
- **LangGraph Node Transitions** — `agent.runtime.langgraph_node_transitions_total` counter rate for operational insights.
- **Permission Cache Hit Rate** — Derived from `agent.permission.cache_hits_total` and `agent.permission.cache_misses_total`; alert annotation when below 80%.
- **Permission Denials** — `agent.runtime.permission_denials_total` rate; alert annotations when non-zero.

---

## Alerts to Configure

| Alert | Condition | Severity |
|-------|-----------|----------|
| Agent instance saturation | Active instance count for any agent type ≥ 90% of its configured `max_instances` for 5 minutes | Warning |
| MCP tool call error rate | Tool call error rate > 5% over a 5-minute window | Critical |
| Scheduler queue backlog | Scheduler queue depth growing continuously for more than 10 minutes without decreasing | Warning |
| Platform API 5xx rate | Platform API 5xx HTTP error rate > 1% over a 5-minute window | Critical |
| Redis eviction | Redis eviction rate > 0 (any eviction event) | Warning |
| OTEL Collector export errors | OTEL Collector export error rate > 0 | Warning |
| OTEL Collector health endpoint down | `http://otel-collector:13133/` returns non-200 for > 2 minutes | Warning |
| No traces ingested in Jaeger | No new spans for > 10 minutes in a production environment | Warning |
| Backend telemetry init failure | Backend log contains `[TELEMETRY ERROR]` at startup | Critical |
| File exporter disk pressure | Disk usage on the file exporter volume > 80% | Warning |
| Frontend config endpoint error | `GET /api/v1/telemetry/config` returning 5xx for > 5 minutes | Warning |

Route Warning alerts to the operations on-call channel. Route Critical alerts to the on-call engineer with immediate escalation.

### Agent Runtime Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `AgentSessionQueueBacklog` | `agent.session.queue_depth > 50` for 5 min | Warning | Check `SessionDispatcher` health; verify backend process is running |
| `AgentSessionFailureSpike` | `rate(agent.session.failures_total) > 5/min` for 2 min | Critical | Inspect session failure logs; check OIDC and MCP connectivity |
| `AgentPermissionDenialDetected` | `rate(agent.runtime.permission_denials_total) > 0` for 5 min | Warning | Review agent role assignments; check for misconfigured role |
| `AgentPermissionCacheDegraded` | `agent.permission.cache_hit_rate < 0.80` for 10 min | Warning | Check for unusual role mutation frequency; consider increasing LRU cache size |
| `AgentIdentityTokenFailure` | `rate(agent.identity.token_refresh_failures_total) > 0` for 2 min | Critical | Verify OIDC provider connectivity; check agent client credentials in identity provider |
| `AgentSessionTimeout` | `rate(agent.session.timeouts_total) > 0` for 5 min | Warning | Inspect timed-out sessions; check LLM provider latency and MCP server responsiveness |
| `LangGraphStateErrors` | `rate(agent.runtime.langgraph_errors_total) > 0` for 2 min | Critical | Inspect LangGraph state machine errors; validate agent type configurations |
