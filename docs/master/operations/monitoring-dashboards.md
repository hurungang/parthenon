# Monitoring — Dashboards

Dashboard definitions and panel groups to build. Metric definitions live in [monitoring-metrics.md](monitoring-metrics.md); thresholds live in [monitoring-alerts.md](monitoring-alerts.md).

Hub: [monitoring.md](monitoring.md) · Operations index: [README.md](README.md)

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

### Control Center Assistant
Conversational management surface plus the OAuth MCP plane it shares. Panels:

- **Delegated Action Volume** — `internal_management_tool_calls_total` stacked by `outcome`; separate `cc____` management calls from meta-tool dispatch (`invoke_management_tool`, `list_management_tools`, `get_management_tool_schema`, `search_assistant_knowledge`).
- **Permission Denial Rate by Resource Type** — `internal_management_tool_permission_denials_total` grouped by `resource_type`; annotate the expected zero-line for a healthy, correctly granted workspace.
- **Delete / Out-of-Scope Rejections** — `internal_management_tool_delete_rejections_total` and `internal_management_tool_scope_rejections_total` as two lines; both should sit at zero outside attempted misuse.
- **Management Tool Latency p99** — `internal_management_tool_duration_seconds` p99 by `tool_name`.
- **Identity Resolution Failures** — `internal_management_tool_identity_resolution_failures_total` rate; any non-zero value is a hard failure of fail-closed enforcement.
- **MCP OAuth Auth Rejection Rate** — `mcp_oauth_auth_rejections_total` split by `reason`.
- **Assistant Availability / Seed Health** — `assistant_seed_result_total` by `outcome`, per tenant; plus a stat panel for the last startup result.
- **Turn Watchdog and LLM Timeouts** — `assistant_turn_watchdog_fires_total` by `kind` overlaid with `assistant_turn_llm_timeout_total`.
- **Iteration-Limit Stops (conversational)** — `guardrail_iteration_limit_hit_total` filtered to the seeded assistant agent type.
- **Interventions** — `assistant_intervention_total` by `outcome` with `assistant_intervention_pending` as a gauge; annotate the configured `conversation_intervention_timeout_seconds`.
- **WebSocket Health** — `chat_ws_active_connections` gauge and `chat_ws_disconnect_total` by `code`.
- **Catalog Anomalies** — `assistant_catalog_anomalies_total` by `kind`, with a table panel listing the offending tool names.

### Conversational Turn Resume
Panel group on the Control Center Assistant dashboard (or its own dashboard), covering the durable pause/resume lifecycle for conversational turns. Panels:

- **Pause → Resume Funnel** — pauses persisted → answered → resume dispatched → resolved; the drop between stages is the operator-visible failure count.
- **Resume Success Rate** — `succeeded / (succeeded + failed)` with the answerable window annotated (platform default `CONVERSATION_TURN_RESUME_TTL_SECONDS`; per-tenant overrides noted separately). Healthy: ≥ 0.99 for turns answered inside the window.
- **Orphaned / Unresumable Split** — orphaned turns as one line (target zero) and terminal resolutions stacked by `reason_code` (`expired`, `superseded`, `cancelled`, `checkpoint_unavailable`, `checkpoint_consumed`, `resume_failed`, `unexpectedly_terminated`) so genuine expiry never masks a durability defect.
- **Claim Contention** — claim results by `result`, annotated with the configured claim TTL and how many `expired_reacquired` events occurred (failover path).
- **Checkpoint Payload Size** — p50/p99 histogram with the configured byte cap drawn as a threshold line.
- **Checkpoint Storage** — stored bytes and row count over time with purge rate overlaid; a monotonic rise with a flat purge means the sweep is not running.
- **Resume Latency p99** — by result, split by segment (CC claim, CH dispatch, AR checkpoint load) where trace data allows.
- **Activity Staleness & Reaper Health** — non-terminal working rows past the staleness bound, reaper sweep outcomes (`swept`/`protected`/`resolved`/`purged`/`error`), and seconds since the last sweep.
- **Per-tenant view** — pause/resume/terminal counts by `tenant_id` for noisy-neighbour and isolation checks (tenancy on only).

### Third-Party Integration Gateway
Public `/integrate/*` surface health and abuse view. Panels:

- **Request Volume by Outcome** — `integration.request_total` split by `outcome`; edge rejections (`origin_denied`, `rate_limited`, `invalid_credential`, `revoked_credential`) stacked separately from `success`/`error`.
- **Per-Client Rate-Limit Pressure** — `rate_limited` outcomes by `client_id`; a single client tripping its limit repeatedly is the triage target.
- **Credential Rejections** — `invalid_credential` + `revoked_credential` rate; sustained non-zero rates indicate stale consumer credentials or probing.
- **Latency p99 by Endpoint** — `integration.response_ms` p99 per `/integrate/*` endpoint.
- **Public Exposure Posture** — publishable-client exposure count over time; alert on unexpected growth.

---

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
