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
| **Agent Execution Guardrails** | `guardrail_stop_total` (labels: `reason`, `agent_type`, `execution_mode`) | Primary signal for policy-enforced session stops by stop reason and execution mode |
| **Agent Execution Guardrails** | `guardrail_cycle_block_total` (labels: `agent_type`, `root_session`) | Detects recursive delegation cycle blocks before runtime begins |
| **Agent Execution Guardrails** | `guardrail_iteration_limit_hit_total` (labels: `agent_type`, `parent_session`) | Detects cumulative iteration ceiling pressure including delegated work |
| **Agent Execution Guardrails** | `guardrail_timeout_limit_hit_total` (labels: `agent_type`) | Detects per-agent wall-clock timeout saturation |
| **Agent Execution Guardrails** | `guardrail_delegation_budget_hit_total` (labels: `limit_type`, `agent_type`) | Detects delegation depth or delegated-step budget exhaustion |
| **Agent Execution Guardrails** | `guardrail_token_budget_hit_total` (labels: `provider`, `model`, `agent_type`, `execution_mode`) | Detects hard token budget stops in non-conversational and automated executions |
| **Agent Execution Guardrails** | `guardrail_conversational_token_usage_snapshot_total` (labels: `provider`, `model`, `agent_type`) | Confirms conversational token-usage visibility events are being emitted |
| **Agent Execution Guardrails** | `guardrail_conversational_token_threshold_reached_total` (labels: `provider`, `model`, `agent_type`) | Tracks conversational threshold events where continuation remains allowed |
| **Agent Execution Guardrails** | `guardrail_token_fallback_applied_total` (labels: `provider`, `fallback_mode`, `agent_type`) | Detects fallback-mode activation when strict token enforcement is unsupported |
| **Agent Execution Guardrails** | `session_terminal_state_total` (labels: `state`, `stop_category`) | Validates guardrail terminal states are classified separately from functional failures |
| **Model-Usage Guardrails** | `model_guardrail_breach_total` (labels: `vendor`, `model`, `period`, `enforcement_posture`) | Detects guardrail breach events; `terminate` posture should map to execution block, `observe_only` should map to alert |
| **Model-Usage Guardrails** | `model_disabled_block_total` (labels: `vendor`, `model`, `disabled_reason`) | Detects blocks from disabled models or vendor-cascaded disables |
| **Model-Usage Guardrails** | `model_usage_posture_transitions_total` (labels: `vendor`, `model`, `period`, `from_state`, `to_state`) | Tracks posture state changes (`within_limit` → `approaching_limit` → `breached`) |
| **Runtime Control** | `runtime_topology_nodes_total` (labels: `kind`, `status`) | Active nodes in the runtime topology by kind (`agent` / `conversation` / `instance`) and status |
| **Runtime Control** | `runtime_topology_polling_requests_total` (labels: `endpoint`, `status`) | Operator topology polling rate and HTTP outcomes |
| **Runtime Control** | `runtime_termination_requests_total` (labels: `outcome`, `cascade_complete`) | Operator-initiated termination requests and cascade completion rate |
| **Runtime Control** | `runtime_terminated_sessions_total` (labels: `cascade_depth`, `node_kind`) | Sessions transitioning to `terminated` status; distinct from `failed` |
| **Recursion Validation** | `recursion_validation_total` (labels: `trigger`, `result`) | Recursion/dead-loop validation outcomes at create, update, and run entry points |
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
| **Control Center Internal Policy** | `internal_unknown_caller_denied_total` (labels: `endpoint`, `method`) | Detects missing or malformed caller identity mapping and spoofed internal identities |
| **Control Center Internal Policy** | `internal_caller_certificate_mismatch_denied_total` (labels: `caller_type`, `presented_cert_type`) | Detects wrong certificate class usage by internal callers |
| **Control Center Internal Policy** | `internal_endpoint_not_allowlisted_total` (labels: `caller_type`, `endpoint`, `method`) | Detects privilege-overreach attempts and stale client behavior |
| **Internal Callers (AR and CH)** | `internal_revocation_check_failures_total` (labels: `caller_service`, `failure_mode`) | Detects trust-chain instability that can force fail-closed internal traffic |
| **Internal Callers (AR and CH)** | `internal_revocation_check_latency_seconds` p99 (labels: `caller_service`) | Detects revocation dependency slowness before widespread request failures |
| **Control Center Internal API** | `internal_authorization_duration_seconds` p99 (labels: `caller_type`, `endpoint_group`) | Detects authorization gate regressions and dependency slowdown |
| **Control Center Internal API** | `internal_http_403_total` (labels: `caller_type`, `endpoint_group`) | Distinguishes expected deny-by-default events from allowlisted-path regressions |
| **Control Center System Tools** | `internal_system_tools_unauthenticated_rejected_total` (labels: `endpoint`) | Confirms service-certificate enforcement on sensitive system-tools paths |
| **Agent Runtime** | `parthenon_ar_session_total` (labels: `status`) | Agent sessions completed per status (`completed`, `failed`, `timeout`) |
| **Agent Runtime** | `parthenon_ar_tool_call_total` (labels: `server`, `tool`, `status`) | Tool calls forwarded to CommHub by the Agent Runtime executor |
| **Communication Hub** | `parthenon_ch_tool_routed_total` (labels: `routing` = `system` or `mcp`) | Tool calls routed by NameResolver; tracks system vs MCP routing split |
| **Communication Hub** | `parthenon_ch_name_resolver_errors_total` | NameResolver failures (unknown server, malformed name) |
| **Communication Hub** | `parthenon_ch_cert_validation_failures_total` | Agent certificates that failed validation at CommHub; any non-zero rate requires investigation |
| **Agent Identities (Security Segregation)** | `token_status = 'refresh_failed'` count | Count of agent identities with `token_status = 'refresh_failed'`; any non-zero value pages on-call immediately |
| **API Key Access** | `api_key.auth_total` by `action`, `outcome`, `key_prefix` | Total API key authentication attempts; tracks validate, load_skills, and tool_call operations |
| **API Key Access** | `api_key.auth_failure_total` by `failure_reason`, `key_prefix` | Authentication failures broken down by reason (invalid_key, revoked_key, unknown) |
| **API Key Access** | `api_key.revoked_key_attempt_total` by `key_prefix` | Authentication attempts using a revoked key; any sustained rate is a security concern |
| **API Key Access** | `api_key.auth_latency_seconds` by `action` | End-to-end latency for API key validation (CH → CC → DB round-trip); rising latency indicates CC/DB pressure |
| **API Key Access** | `api_key.load_skills_total` by `sync_mode` | `load_skills` call volume split by full vs incremental sync |
| **API Key Access** | `api_key.load_skills_skill_count` histogram | Number of skills returned per `load_skills` response; tracks payload size growth |
| **API Key Access** | `api_key.tool_call_total` by `outcome`, `tool_name` | Tool call volume via API key auth; tracks success, permission_denied, and error outcomes |
| **API Key Access** | `api_key.tool_call_auth_method` by `method` | Ratio of tool calls by auth method (api_key vs certificate); used for volume comparison |
| **MCP Protocol Server** | `mcp.connections_total` / active connections | External MCP client connections (SSE + Streamable HTTP) to the Communication Hub; tracks external agent adoption |
| **MCP Protocol Server** | `mcp.initialize_total` | MCP `initialize` handshake volume; a drop to zero with active clients signals a transport regression |
| **MCP Protocol Server** | `mcp.tools_list_total` | `tools/list` call volume; spikes indicate client re-discovery storms |
| **MCP Protocol Server** | `mcp.tools_call_total` by `outcome`, `tool_name` | `tools/call` volume by outcome (success, permission_denied, error) |
| **Startup Validation — Control Center** | `startup.validation.database_ok` / `startup.validation.database_failed` | PostgreSQL reachability at startup; failure prevents CC from starting |
| **Startup Validation — Control Center** | `startup.validation.keycloak_ok` / `startup.validation.keycloak_not_found` | Keycloak realm existence at startup; failure means operator must run `setup identity` or fix OIDC config |
| **Startup Validation — Control Center** | `startup.validation.redis_ok` / `startup.validation.redis_failed` | Redis reachability at startup; failure prevents CC from starting |
| **Startup Validation — Agent Runtime** | `startup.validation.control_center_ok` / `startup.validation.control_center_unreachable` | Control Center reachability at AR startup; failure prevents certificate bootstrap |
| **Startup Validation — Communication Hub** | `startup.validation.control_center_ok` / `startup.validation.control_center_unreachable` | Control Center reachability at CH startup; failure prevents certificate bootstrap |
| **Startup Validation — Communication Hub** | `startup.validation.redis_ok` / `startup.validation.redis_failed` | Redis reachability at CH startup; failure prevents message brokering |
| **Configuration Source** | `config:*:resolved from <source>` | Source of each infrastructure connection (env var, YAML, or default); in production, should always be `env var` |
| **Service Restarts** | Restart count per service within rolling window | > 2 restarts in 5 minutes indicates intermittent infrastructure issue |
| **OIDC Provider Registry** | `oidc.provider.reachability` (gauge, labels: `provider_type`, `provider_name`) | 1 = provider reachable via OIDC Discovery; 0 = unreachable. Per-provider health signal for both user and agent identity providers. |
| **OIDC Provider Registry** | `oidc.provider.discovery_latency` (p99, labels: `provider_type`, `provider_name`) | Time to complete `.well-known/openid-configuration` fetch. High p99 indicates provider-side latency or network issues. |
| **OIDC Provider Registry** | `oidc.jwks.fetch_failures_total` (labels: `provider_type`, `provider_name`) | Failed JWKS endpoint fetches per provider. Any sustained non-zero rate is critical — JWTs will fail validation. |
| **OIDC Provider Registry** | `oidc.jwks.cache_hits_total` | JWKS keys served from in-memory cache. |
| **OIDC Provider Registry** | `oidc.jwks.cache_misses_total` | JWKS cache misses requiring a fetch from the provider. |
| **OIDC Provider Registry** | `oidc.jwks.cache_hit_rate` (derived) | `cache_hits / (cache_hits + cache_misses)`; below 90% indicates excessive key rotation or undersized TTL. |
| **OIDC Provider Registry** | `oidc.registry.reload_total` (labels: `trigger`) | Registry reload events; `trigger` is one of `config_update`, `manual`, `startup`. Spikes indicate frequent operator-driven config changes. |
| **OIDC Provider Registry** | `oidc.registry.reload_errors_total` | Failed registry reload attempts. Any non-zero rate means config is stale and new provider settings are not taking effect. |
| **Super Admin Auth** | `superadmin.login_attempts_total` (labels: `outcome`) | Super admin login attempts; `outcome` is `success` or `failure`. |
| **Super Admin Auth** | `superadmin.login_failures_total` (labels: `reason`) | Failed super admin attempts; `reason` is `invalid_credentials`, `disabled`, or `expired`. |
| **Super Admin Auth** | `superadmin.token_issued_total` | Short-lived JWT tokens issued to super admin sessions. |
| **Auth Middleware** | `auth.pipeline.decision_total` (labels: `tier`, `outcome`) | Which tier resolved the request; `tier` is `super_admin`, `oidc_user`, `oidc_agent`, or `public`. `outcome` is `allowed` or `denied`. |
| **Auth Middleware** | `auth.pipeline.latency` (p99, labels: `tier`) | Time spent in each auth tier. High p99 for `oidc_*` tiers indicates provider-side latency. |
| **Auth Middleware** | `auth.oidc.validation_failures_total` (labels: `provider_type`, `reason`) | OIDC JWT validation failures; `reason` is `signature`, `expired`, `audience`, `issuer`, `claims`, or `unknown`. |
| **OIDC Config Service** | `oidc.config.test_success_total` (labels: `provider_type`, `test_type`) | Successful OIDC test connections and test logins from the UI. |
| **OIDC Config Service** | `oidc.config.test_failure_total` (labels: `provider_type`, `test_type`, `reason`) | Failed OIDC tests with failure reason (connectivity, auth, claims mapping). |
| **OIDC Config Service** | `oidc.config.change_total` (labels: `action`, `provider_type`) | Provider config mutations; `action` is `create`, `update`, or `delete`. Used for audit trail. |
| **OIDC Config Service** | `oidc.config.secret_encryption_errors_total` | Client secret encryption failures at rest. Any non-zero rate indicates crypto subsystem issue. |

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

### API Key Access
Add as a panel group within the MCP Hub dashboard, or as a standalone dashboard. Panels:

- **API Key Auth Rate** — `api_key.auth_total` rate split by `action` and `outcome`; success (green) and failure (red) stacked area.
- **Auth Failure Breakdown** — `api_key.auth_failure_total` by `failure_reason`; pie or stacked bar.
- **Revoked Key Attempts** — `api_key.revoked_key_attempt_total` rate line chart; any sustained non-zero rate is a security concern.
- **load_skills Call Rate** — `api_key.load_skills_total` rate split by `sync_mode`; shows full vs incremental sync ratio.
- **load_skills Response Size** — `api_key.load_skills_skill_count` histogram; p50/p99 to track response payload growth.
- **Tool Call Volume: API Key vs Certificate** — Ratio derived from `api_key.tool_call_auth_method`; shows external agent vs internal agent usage.
- **Auth Latency p99** — `api_key.auth_latency_seconds` p99 time series; rising latency indicates CC or DB pressure.

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

### Agent Execution Guardrails Dashboard
Guardrail policy behavior and stop-classification view. Add as a dedicated panel group in operations dashboards. Panels:

- **Guardrail Stops by Reason** — `guardrail_stop_total` split by `reason` and `execution_mode`.
- **Cycle Blocks** — `guardrail_cycle_block_total` trend with agent-type breakdown.
- **Iteration and Timeout Limit Hits** — `guardrail_iteration_limit_hit_total` and `guardrail_timeout_limit_hit_total` overlay.
- **Delegation Budget Exhaustion** — `guardrail_delegation_budget_hit_total` split by `limit_type` (`depth`, `delegated_steps`).
- **Conversational Token Visibility** — `guardrail_conversational_token_usage_snapshot_total` with active conversational session count.
- **Conversational Threshold Continuation** — `guardrail_conversational_token_threshold_reached_total` trend (should not map to hard-stop outcomes).
- **Non-Conversational Token Budget Stops** — `guardrail_token_budget_hit_total` split by provider/model.
- **Token Fallback Activation** — `guardrail_token_fallback_applied_total` by `provider` and `fallback_mode`.
- **Terminal State Classification Integrity** — `session_terminal_state_total` split by `state` and `stop_category`.

### Service Segregation Boundary Enforcement
Dedicated dashboard panel group for internal caller boundary controls. Panels:

- **Allowed vs Denied Internal Calls** — `internal_allowlist_decisions_total` split by `caller_type` and `decision`.
- **Top Denied Endpoints** — `internal_allowlist_denied_total` grouped by `caller_type`, `endpoint`, and `reason`.
- **Unknown Caller and Certificate Mismatch Trends** — `internal_unknown_caller_denied_total` and `internal_caller_certificate_mismatch_denied_total` as separate time series.
- **Revocation Health** — `internal_revocation_check_failures_total` rate and `internal_revocation_check_latency_seconds` p99 for AR and CH.
- **Internal Authorization Latency** — `internal_authorization_duration_seconds` p99 by `caller_type` and `endpoint_group`.
- **Allowlisted Path 403 Regression** — `internal_http_403_total` for known allowlisted endpoint groups.
- **System Tools Unauthenticated Rejects** — `internal_system_tools_unauthenticated_rejected_total` by endpoint.

### Startup Health Dashboard
Operations dashboard for detecting configuration regressions across service restarts. Panels:

- **Last Startup Status per Service** — Panel showing the last startup status (success or failed) for each service, with the failure reason extracted from the `startup.validation.*_failed` log event.
- **Configuration Source Summary** — Aggregation of `config:<connection> resolved from <source>` log events across all services, colour-coded by source: env var (green), YAML (yellow), default (red).
- **Service Restart Count** — Restart count per service within a rolling 10-minute window; colours thresholded at > 3 restarts.

### Configuration Source Dashboard
At-a-glance visibility into which services are using which configuration model. Panels:

- **Configuration Source by Connection** — For each infrastructure connection (database, redis, oidc), show which source was resolved per service.
- **Configuration Drift Detection** — If any service changes its resolved source between restarts, highlight the transition.
- **Production Configuration Compliance** — All connections should resolve from `env var` in production; any `yaml` or `default` source is flagged.

### OIDC Provider Health
Single-pane view of identity provider connectivity. Include: per-provider reachability gauges (user and agent), OIDC Discovery latency p99 per provider, JWKS cache hit rate per provider, JWKS fetch failure rate per provider, and registry reload event count. Use red/green colour coding for reachability.

### Super Admin & Auth Pipeline
Authentication decision overview. Include: auth pipeline tier distribution (stacked bar: super_admin, oidc_user, oidc_agent, public), super admin login success/failure rate as a time series, OIDC JWT validation failure rate by reason, and auth pipeline p99 latency per tier.

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

### Agent Execution Guardrail Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `GuardrailStopRateSpike` | `guardrail_stop_total` above baseline for 5 min | Warning | Check stop reasons by `agent_type` and `execution_mode`; confirm no workflow rollout regression |
| `CycleBlockSurge` | `guardrail_cycle_block_total` above baseline for 5 min | Warning | Follow [runbooks/agent-execution-guardrails.md](runbooks/agent-execution-guardrails.md) cycle triage and isolate recursive delegation paths |
| `TimeoutRegression` | `guardrail_timeout_limit_hit_total` above baseline for 10 min | Warning | Correlate with LLM and MCP latency; validate timeout policy thresholds |
| `DelegationBudgetExhaustion` | `guardrail_delegation_budget_hit_total` above baseline for 5 min | Warning | Validate delegation depth and delegated-step budgets for affected agent types |
| `ConversationalTokenVisibilityGap` | `guardrail_conversational_token_usage_snapshot_total = 0` while conversational sessions are active for 5 min | Critical | Treat as observability gap; verify conversational token snapshot event flow immediately |
| `ConversationalTokenHardStopDetected` | conversational terminal sessions classified with token-budget stop reason for 2 min | Critical | Treat as policy regression; validate execution-mode branch and continuation behavior |
| `TokenFallbackOveruse` | `guardrail_token_fallback_applied_total` above baseline for 15 min | Warning | Review provider capability mapping and fallback policy usage |
| `StopReasonMissing` | terminal sessions without stop reason classification for 2 min | Critical | Validate stop metadata forwarding and persistence fields end-to-end |

### Model-Usage Guardrail Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `GuardrailBreachSurge` | `rate(model_guardrail_breach_total{enforcement_posture="terminate"}) > baseline` for 5 min | Critical | Expect execution blocks; check operator posture intent and model usage |
| `ObserveOnlyGuardrailAlertSurge` | `rate(model_guardrail_breach_total{enforcement_posture="observe_only"}) > baseline` for 5 min | Warning | Review observe-only threshold alerts in execution logs |
| `ModelDisabledSurge` | `rate(model_disabled_block_total{disabled_reason="model_disabled"}) > baseline` for 5 min | Warning | Verify operator-driven disables; expect execution blocks |
| `VendorDisabledSurge` | `rate(model_disabled_block_total{disabled_reason="vendor_cascaded"}) > baseline` for 5 min | Warning | Verify vendor disable; check cascade transaction completed |
| `ApproachingLimitSurge` | `rate(model_usage_posture_transitions_total{to_state="approaching_limit"}) > baseline` for 10 min | Warning | Notify FinOps / Platform Governance Lead before breach |
| `RuntimeTopologyPollingFailure` | `rate(runtime_topology_polling_requests_total{status=~"5.."}) > 0` for 2 min | Warning | Verify topology endpoint health; check operator permission |
| `RuntimeTerminateCascadeIncomplete` | `rate(runtime_termination_requests_total{outcome="cascade_incomplete"}) > 0` for 2 min | Critical | Follow [runbooks/agent-execution-guardrails.md](runbooks/agent-execution-guardrails.md) operator termination triage |
| `RecursionValidationFailureSurge` | `rate(recursion_validation_total{result="fail"}) > baseline` for 5 min | Warning | Follow recursion triage in [runbooks/agent-execution-guardrails.md](runbooks/agent-execution-guardrails.md) section 1 |

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
| `InternalDenySpike` | `rate(internal_allowlist_denied_total) > baseline` for 5 min | Warning | Start deny spike triage in [runbooks/service-segregation-boundary-enforcement.md](runbooks/service-segregation-boundary-enforcement.md) |
| `NonAllowlistedEndpointAttemptDetected` | `rate(internal_endpoint_not_allowlisted_total) > 0` for 2 min | Critical | Treat as contract drift or privilege-overreach; follow boundary runbook |
| `UnknownCallerDenied` | `rate(internal_unknown_caller_denied_total) > 0` for 2 min | Critical | Validate identity extraction and caller normalization immediately; follow boundary runbook |
| `CallerCertificateMismatch` | `rate(internal_caller_certificate_mismatch_denied_total) > 0` for 2 min | Critical | Validate certificate class assignment and rotation state; follow boundary runbook and [runbooks/certificate-security.md](runbooks/certificate-security.md) |
| `RevocationCheckFailureSustained` | `rate(internal_revocation_check_failures_total) > 0` for 2 min | Critical | Keep fail-closed mode; restore revocation dependency and follow boundary runbook |
| `InternalAuthorizationLatencyHigh` | `internal_authorization_duration_seconds` p99 above threshold for 10 min | Warning | Investigate policy dependency and Control Center saturation |
| `Internal403RegressionAllowedPath` | `rate(internal_http_403_total{endpoint_group=~"allowlisted.*"})` above baseline for 5 min | Warning | Investigate allowlist regression on valid paths; follow boundary runbook |
| `SystemToolsUnauthenticatedAccessAttempt` | `rate(internal_system_tools_unauthenticated_rejected_total) > 0` for 2 min | Critical | Treat as security event; validate source and network path; follow boundary runbook |

### OIDC Identity Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `OIDCProviderUnreachable` | `oidc.provider.reachability == 0` for 5 min | Critical | OIDC login is broken for affected provider; check network, DNS, and provider health |
| `OIDCJWKSFetchFailureSustained` | `rate(oidc.jwks.fetch_failures_total) > 0` for 2 min | Critical | All JWT validation is failing; JWT signatures cannot be verified |
| `OIDCJWKSCacheDegraded` | `oidc.jwks.cache_hit_rate < 0.90` for 10 min | Warning | Excessive JWKS key rotation or undersized cache TTL |
| `OIDCRegistryReloadError` | `rate(oidc.registry.reload_errors_total) > 0` for 2 min | Critical | Registry reload failed; OIDC config is stale and provider changes are not reflected |
| `AuthPipelineOIDCLatencyHigh` | `auth.pipeline.latency` p99 > 5 s for `oidc_user` or `oidc_agent` tier for 5 min | Warning | OIDC provider or network is slow; user login experience degraded |
| `OIDCTestFailureSustained` | `rate(oidc.config.test_failure_total) > 0` for 10 min | Warning | Operator repeatedly unable to validate OIDC connectivity; check provider configuration |
| `OIDCSecretEncryptionError` | `rate(oidc.config.secret_encryption_errors_total) > 0` | Critical | Client secret encryption/decryption failing; OIDC authentication may not function |

### Super Admin Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `SuperAdminBruteForce` | `rate(superadmin.login_failures_total) > 10/min` for 5 min | Critical | Potential brute-force attack on super admin credentials; consider disabling super admin or rotating credentials |
| `SuperAdminDisabledLoginAttempt` | `rate(superadmin.login_failures_total{reason="disabled"}) > 0` for 5 min | Warning | Login attempts to a disabled super admin; may indicate misconfiguration or unauthorized access attempt |

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

### API Key Access Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `ApiKeyAuthFailureSpike` | `rate(api_key.auth_failure_total) > 10/min` for 5 min | Warning | Check key validity and CH → CC connectivity; review `failure_reason` breakdown |
| `ApiKeyAuthFailureSustained` | `rate(api_key.auth_failure_total) > 50/min` for 2 min | Critical | Possible brute-force attack; consider temporary IP-level rate limiting |
| `RevokedKeyAttemptDetected` | `rate(api_key.revoked_key_attempt_total) > 0` sustained for 5 min | Warning | Investigate source IP and key prefix; may indicate compromised key or misconfigured agent; see [api-key-auth.md](runbooks/api-key-auth.md) |
| `ApiKeyAuthLatencyHigh` | `api_key.auth_latency_seconds` p99 > 2 s for 5 min | Warning | Check CC database query performance; verify `api_keys` table indexes |
| `ApiKeyLoadSkillsEmpty` | `api_key.load_skills_skill_count` p50 = 0 sustained for 10 min | Warning | Load skills returning empty for most callers; verify role-to-skill assignments |
| `ApiKeyPermissionDenialSpike` | `rate(api_key.tool_call_total{outcome="permission_denied"}) > 5/min` for 5 min | Warning | Tools requested outside bound role permissions; review agent configuration |

### Certificate Security Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `CACertificateExpirySoon` | CA certificate expires within 6 months | Warning | Begin CA rotation planning; check `GET /api/v1/certificates/ca` `expires_at` field |
| `AgentCertRenewalFailure` | `cert.renewal_failed` ERROR log present | Critical | Certificate will expire without intervention; re-provision immediately; see [certificate-security.md](runbooks/certificate-security.md) |
| `AgentCertExpired` | `cert.validation.failed` WARN with `outcome = expired` sustained | Critical | Agent runtime shutting down; manually issue replacement certificate; see [certificate-security.md](runbooks/certificate-security.md) |
| `AgentIdentityRefreshFailed` | Count of `agent_identities.token_status = 'refresh_failed'` > 0 | Critical | Agent identity requires manual re-authorization via Admin UI → Agent Identities; see [certificate-security.md](runbooks/certificate-security.md) |

### Startup Validation and Configuration Alerts

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `StartupValidationFailed` | `startup.validation.*_failed` log event present | Critical | Page on-call; service cannot start; check the specific dependency in the log event |
| `ConfigurationFromDefault` | Any `resolved from built-in default` log event in production | Warning | Operator review: ensure all production infrastructure env vars are set |
| `KeycloakConfigNotFound` | `startup.validation.keycloak_not_found` log event present | Critical | Operator must run `setup identity` or verify OIDC environment variables |
| `KeycloakAdminCredsInRuntime` | `KEYCLOAK_ADMIN` detected in CC environment at startup | Critical | Security violation: admin credentials exposed to runtime; remove immediately |
| `ServiceRestartLoop` | Any service restarts > 3 times in 10 minutes | Critical | Page on-call; intermittent infrastructure connectivity likely |
