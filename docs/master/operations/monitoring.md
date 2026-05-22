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
| **MCP Demo App** | `mcp_demo.startup.registration_success` | 1 if Hub registration succeeded at startup, 0 if failed; alert on any non-1 value after container start |
| **MCP Demo App** | `mcp_demo.auth.token_refresh_failures_total` | Failed Keycloak client credentials grant attempts; alert on any sustained non-zero rate |
| **MCP Demo App** | `mcp_demo.auth.jwks_fetch_failures_total` | Failed Keycloak JWKS endpoint fetches; alert on any sustained non-zero rate |
| **MCP Demo App** | `mcp_demo.auth.jwt_validation_failures_total` | Incoming agent JWTs that failed signature/expiry/issuer check; alert on any sustained non-zero rate |
| **MCP Demo App** | `mcp_demo.tool.calls_total` | Total `helloWorld` tool invocations (label: `status=success\|error`); alert if error rate > 10% sustained for 5 min |
| **MCP Demo App** | `mcp_demo.http.request_duration` | HTTP request latency for `/mcp` and `/health` endpoints (p99); alert if p99 > 5 s |
| **MCP Hub — Passthrough Sessions** | Active passthrough session count | Number of `mcp_session` rows with `auth_type = 'passthrough'`; used for trend monitoring and capacity planning |
| **MCP Hub — Passthrough Sessions** | Passthrough session creation rate | New passthrough sessions per hour; spike > 100/hour may indicate abuse |
| **MCP Hub — Passthrough Sessions** | Passthrough session creation failures | Failed passthrough session creates per hour; > 10/hour warrants investigation |
| **MCP Hub — Passthrough Sessions** | Passthrough tool call success rate | Successful vs. failed tool calls for passthrough sessions; alert if < 95% |
| **MCP Hub — Passthrough Sessions** | JWT extraction rate | Percentage of incoming requests where middleware successfully extracts `raw_token`; < 99% indicates middleware regression |
| **MCP Hub — Passthrough Sessions** | JWKS cache hit rate | Keycloak JWKS cache hits for passthrough JWT validation; < 90% indicates cache misconfiguration or excessive key rotation |
| **MCP Hub — Passthrough Sessions** | JWT expiry rate | Percentage of passthrough tool calls rejected because the forwarded JWT is expired; > 5% warrants investigation |
| **MCP Hub — Passthrough Sessions** | Passthrough tool call latency p99 | End-to-end time for tool calls via passthrough sessions; alert if p99 > 5 s |
| **Certificate Authority** | CA certificate expiration date | Alert 6 months before expiry; CA cert is valid for 10 years; check via `GET /api/v1/certificates/ca` response field `expires_at` |
| **Certificate Authority** | Active agent instance certificate count by status | Count of `agent_instance_certificates` rows grouped by `status` (active, revoked, expired); used for capacity and health overview |
| **Certificate Authority** | Certificates expiring within 6 hours | Count of `active` agent certificates with `expires_at` within 6 hours; non-zero count indicates imminent renewal risk |
| **Certificate Authority** | Certificate renewal failure rate | Log-based counter on `cert.renewal_failed` events; any non-zero rate is critical — agent runtime shuts down gracefully after expiry |
| **Certificate Authority** | Certificate validation failure rate | Rate of `cert.validation.failed` WARN log events labelled by `outcome` (expired, revoked, invalid); non-zero rate requires investigation |
| **Notification Service** | `notification_sent_total` (labels: `channel_type`, `status`) | Total notification delivery attempts per channel type; use to track delivery volume and per-channel error rates |
| **Notification Service** | `notification_delivery_duration_seconds` (p99, labels: `channel_type`) | End-to-end delivery time per channel type; high p99 for `SMTP` indicates relay latency; high p99 for `WEBHOOK` indicates target server slowness |
| **Notification Service** | `notification_retry_total` (labels: `channel_type`) | Cumulative retries per channel; elevated rate indicates unstable downstream channel provider |
| **Notification Service** | `notification_channel_health` (gauge, labels: `channel_id`, `channel_type`) | 1 = channel last delivery successful; 0 = channel last delivery failed; use for per-channel health dashboard |
| **Notification Service** | `notification_partial_failure_total` | Notifications where at least one (but not all) channels failed; non-zero rate indicates multi-channel reliability issues |
| **Control Center** | `parthenon_cc_api_request_total` (labels: `endpoint`, `status`) | Total API requests to Control Center REST endpoints |
| **Control Center** | `parthenon_cc_cert_issue_total` (labels: `service`) | Certificates issued to Agent Runtime and Communication Hub; tracks bootstrap and renewal events |
| **Control Center** | `parthenon_cc_cert_renewal_failures_total` (labels: `service`) | Failed certificate renewal requests; any sustained non-zero rate is critical |
| **Control Center Internal Policy** | `internal_allowlist_decisions_total` (labels: `caller_type`, `endpoint`, `method`, `decision`) | Shows allowed vs denied internal calls by caller profile |
| **Control Center Internal Policy** | `internal_allowlist_denied_total` (labels: `caller_type`, `endpoint`, `method`, `reason`) | Primary signal for deny-by-default enforcement and contract drift |
| **Control Center Internal Policy** | `internal_unknown_caller_denied_total` | Detects missing or malformed caller identity mapping |
| **Control Center Internal Policy** | `internal_endpoint_not_allowlisted_total` (labels: `caller_type`, `endpoint`) | Detects privilege-overreach attempts and stale client behavior |
| **Agent Runtime** | `parthenon_ar_session_total` (labels: `status`) | Agent sessions completed per status (`completed`, `failed`, `timeout`) |
| **Agent Runtime** | `parthenon_ar_tool_call_total` (labels: `server`, `tool`, `status`) | Tool calls forwarded to CommHub by the Agent Runtime executor |
| **Communication Hub** | `parthenon_ch_tool_routed_total` (labels: `routing` = `system` or `mcp`) | Tool calls routed by NameResolver; tracks system vs MCP routing split |
| **Communication Hub** | `parthenon_ch_name_resolver_errors_total` | NameResolver failures (unknown server, malformed name) |
| **Communication Hub** | `parthenon_ch_cert_validation_failures_total` | Agent certificates that failed validation at CommHub; any non-zero rate requires investigation |
| **Agent Identities (Security Segregation)** | `token_status = 'refresh_failed'` count | Count of agent identities with `token_status = 'refresh_failed'`; any non-zero value pages on-call immediately |

---

## Dashboards to Create

### Platform Overview
Single-pane health summary intended for on-call operators. Include: Platform API HTTP error rate (4xx/5xx), total active agent instances across all types, active WebSocket connection count, and scheduler queue depth. Use thresholds and colour coding to make alarm states immediately visible.

### Agent Engine
Detailed agent execution view. Include: instance count per agent type as a stacked time series, instance creation and destruction rates, and an agent response latency histogram showing p50 and p99 percentiles.

### MCP Hub
Tool call analysis view. Include: tool call rate as a heatmap bucketed by tool name and session, tool call error rate as a percentage, tool call latency p99 as a time series, and a passthrough session panel group (see below).

### MCP Hub — Passthrough Sessions
Add as a panel group within the MCP Hub dashboard. Panels:

- **Active Passthrough Sessions** — Count of `mcp_session` rows with `auth_type = 'passthrough'`; time-series trend for capacity planning.
- **Passthrough Tool Call Rate** — Rate of tool calls for passthrough sessions; stacked by `success`/`error` status.
- **Passthrough Tool Success Rate** — `success / total` percentage; alert annotation at < 95%.
- **JWT Extraction Rate** — Percentage of requests where middleware successfully extracts `raw_token`; alert annotation at < 99%.
- **JWKS Cache Hit Rate** — Gauge showing Keycloak JWKS cache hit percentage; alert annotation at < 80%.
- **Passthrough Tool Latency** — p99 time series for end-to-end passthrough tool call duration; alert annotation at > 5 s.

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

### Notification Service Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `NotificationChannelFailureSpike` | `rate(notification_sent_total{status="failed"}) / rate(notification_sent_total) > 0.10` for 5 min | Warning | Check individual channel logs; test connectivity to external provider |
| `NotificationDeliveryLatencyHigh` | `notification_delivery_duration_seconds{quantile="0.99"} > 10` for 5 min | Warning | Identify slow channel type; check provider rate limits or network latency |
| `NotificationChannelDown` | `notification_channel_health == 0` for 10 min | Critical | Channel consistently failing; check channel credentials and external provider status |
| `NotificationRetryStorm` | `rate(notification_retry_total) > 50/min` for 5 min | Warning | High retry rate across channels; check provider availability and backoff configuration |

### Service-to-Service Trust Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `AgentRuntimeCertExpiringSoon` | Control Center reports AR cert expiring < 1 hour | Warning | Trigger manual cert renewal; check AR service health |
| `CommHubCertExpiringSoon` | Control Center reports CommHub cert expiring < 1 hour | Warning | Trigger manual cert renewal; check CommHub service health |
| `CertRenewalFailure` | `rate(parthenon_cc_cert_renewal_failures_total) > 0` for 2 min | Critical | AR or CommHub cannot renew cert; service will shut down after expiry |
| `CommHubNameResolverErrors` | `rate(parthenon_ch_name_resolver_errors_total) > 0` for 5 min | Warning | Agents sending malformed tool names or unknown server IDs; check agent code |
| `CommHubCertValidationFailures` | `rate(parthenon_ch_cert_validation_failures_total) > 0` for 5 min | Critical | Potential unauthorized tool calls; check for compromised agent certs |
| `InternalDenySpike` | `rate(internal_allowlist_denied_total) > baseline` for 5 min | Warning | Check recent deployments and allowlist contract drift |
| `UnknownInternalCallerDetected` | `rate(internal_unknown_caller_denied_total) > 0` for 2 min | Critical | Validate certificate identity propagation and caller normalization |
| `InternalAllowlistContractDrift` | `rate(internal_endpoint_not_allowlisted_total) > 0` for 2 min | Critical | Verify caller endpoint contract and roll back mismatched deployments if needed |

### MCP Demo App Alerts

Metrics are emitted via OpenTelemetry; panels live in the **MCP Demo App** panel group on the MCP Hub Grafana dashboard.

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|---------|
| `MCPDemoRegistrationFailed` | `mcp_demo.startup.registration_success == 0` at startup | Critical | Check Hub connectivity and API key; see Hub registration runbook |
| `MCPDemoJWTValidationFailures` | `rate(mcp_demo.auth.jwt_validation_failures_total) > 0` for 5 min | Warning | Verify calling agent is using `ai_agents` realm tokens; check JWKS cache |
| `MCPDemoKeycloakTokenFailure` | `rate(mcp_demo.auth.token_refresh_failures_total) > 0` for 2 min | Critical | Verify Keycloak `ai_agents` realm is reachable; check client secret rotation |
| `MCPDemoHighToolErrorRate` | Tool call error rate > 10% for 5 min | Warning | Inspect tool invocation logs; correlate with JWT validation failures |

### Passthrough Session Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `PassthroughJWTValidationFailureSpike` | JWT validation failures > 10% over 5 minutes | Critical | Check Keycloak JWKS endpoint availability; see [passthrough-session.md](runbooks/passthrough-session.md) |
| `PassthroughSessionCreationFailures` | Session creation failures > 20/hour | Warning | Check database constraints and backend logs; verify `auth_type = 'passthrough'` enum migration is applied |
| `PassthroughHighToolLatency` | Passthrough tool call latency p99 > 5 s | Warning | Check MCP server performance and network latency to upstream MCP server |
| `PassthroughJWKSCacheDegraded` | JWKS cache hit rate < 80% over 10 min | Warning | Review JWKS cache TTL configuration in `backend/app/auth.py` |
| `PassthroughSessionCreationRateAnomaly` | New passthrough sessions > 100/hour | Warning | Review session creation logs for potential abuse patterns |

### Certificate Security Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `CACertificateExpirySoon` | CA certificate expires within 6 months | Warning | Begin CA rotation planning; check `GET /api/v1/certificates/ca` `expires_at` field |
| `AgentCertRenewalFailure` | `cert.renewal_failed` ERROR log present | Critical | Certificate will expire without intervention; re-provision immediately; see [certificate-security.md](runbooks/certificate-security.md) |
| `AgentCertExpired` | `cert.validation.failed` WARN with `outcome = expired` sustained | Critical | Agent runtime shutting down; manually issue replacement certificate; see [certificate-security.md](runbooks/certificate-security.md) |
| `AgentIdentityRefreshFailed` | Count of `agent_identities.token_status = 'refresh_failed'` > 0 | Critical | Agent identity requires manual re-authorization via Admin UI → Agent Identities; see [certificate-security.md](runbooks/certificate-security.md) |
