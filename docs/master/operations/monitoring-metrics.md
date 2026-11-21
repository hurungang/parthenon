# Monitoring — Key Metrics by Component

The instrumented series (and the ones still marked *proposed*) for every component, with why each matters.

Hub: [monitoring.md](monitoring.md) · Operations index: [README.md](README.md)

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
| **Integration Gateway** | `integration.request_total` (labels: `client_id`, `endpoint`, `outcome` = `success`/`rate_limited`/`invalid_credential`/`revoked_credential`/`origin_denied`/`error`) | Per-client `/integrate/*` request volume and edge-rejection outcomes; primary abuse signal |
| **Integration Gateway** | `integration.response_ms` (p50, p99, labels: `client_id`, `endpoint`) | Gateway latency per client and endpoint; rising p99 indicates CH or downstream agent pressure |
| **Integration Gateway** | Publishable-client exposure count (gauge) | Number of agent types exposed through `publishable` clients (publicly reachable); use to audit the public surface |
| **Integration Gateway** | Client-invoked agent executions (rate) | Client-invoked turns reuse existing agent-runtime health/guardrail metrics (timeouts, guardrail breaches); visible alongside first-party traffic |
| **Control Center** | `parthenon_cc_api_request_total` (labels: `endpoint`, `status`) | Total API requests to Control Center REST endpoints |
| **Control Center** | `parthenon_cc_cert_issue_total` (labels: `service`) | Certificates issued to Agent Runtime and Communication Hub; tracks bootstrap and renewal events |
| **Control Center** | `parthenon_cc_cert_renewal_failures_total` (labels: `service`) | Failed certificate renewal requests; any sustained non-zero rate is critical |
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
| **Control Center Assistant** | `internal_management_tool_calls_total` (labels: `tool_name`, `outcome` = `success`/`permission_denied`/`scope_rejected`/`delete_rejected`/`error`) — *proposed* | Delegated-action volume per `cc____` management tool; the primary usage/outcome signal for the assistant and external OAuth MCP clients |
| **Control Center Assistant** | `internal_management_tool_permission_denials_total` (labels: `tool_name`, `resource_type`, `reason`) — *proposed* | Assistant attempts the user's own scope cannot authorize; sustained non-zero rate signals mis-scoped roles/grants or parity drift vs the REST `require_permission` |
| **Control Center Assistant** | `internal_management_tool_delete_rejections_total` (labels: `tool_name`) — *proposed* | In-band delete attempts declined (`deletion_not_supported`); deletion is never supported, so a spike is misuse or an instruction regression |
| **Control Center Assistant** | `internal_management_tool_scope_rejections_total` (labels: `tool_name`, `requested_scope`) — *proposed* | Requests outside the Agents-menu / MCP Hub management scope (`out_of_scope`) |
| **Control Center Assistant** | `internal_management_tool_duration_seconds` (p99, labels: `tool_name`) — *proposed* | End-to-end handler time (authorize + persist) on `POST /internal/management-tools/*`; rising p99 indicates CC/DB pressure |
| **Control Center Assistant** | `internal_management_tool_identity_resolution_failures_total` — *proposed* | Fail-closed cases where the OAuth `sub` could not resolve to a `PlatformUser` (CC `/resolve` 403); any non-zero rate needs triage |
| **Control Center Assistant** | `mcp_oauth_auth_rejections_total` (labels: `reason` = `missing_token`/`invalid_token`/`expired_token`/`missing_subject`/`identity_unresolvable`/`tenant_unresolvable`) — *proposed* | OAuth/OIDC Bearer-token rejections at the Communication Hub `/mcp*` OAuth middleware; currently observable only as WARN log lines |
| **Control Center Assistant** | `assistant_seed_result_total` (labels: `outcome` = `success`/`partial`/`failed`, `tenant_id`) — *proposed* (log-derived today) | Idempotent `AssistantSeeder` outcome at CC startup; `failed` means that tenant's assistant is unavailable |
| **Control Center Assistant** | `assistant_turn_watchdog_fires_total` (labels: `kind` = `timeout`/`persistence_timeout`/`cancelled`) — *proposed* | Whole-turn watchdog fires in the Communication Hub chat socket; distinguishes a hung AR turn from a hung persistence tail |
| **Control Center Assistant** | `assistant_turn_llm_timeout_total` (labels: `agent_type`) — *proposed* | Agent Runtime `conversation_llm_timeout_seconds` (and post-resume) turn timeouts |
| **Control Center Assistant** | `guardrail_iteration_limit_hit_total` (labels: `agent_type`, `parent_session`) | Existing guardrail counter — filter to the seeded assistant agent type to detect conversational step-limit stops surfaced as an `iteration_limit` turn error |
| **Control Center Assistant** | `assistant_intervention_total` (labels: `outcome` = `created`/`approved`/`denied`/`timeout`/`cancelled`) — *proposed* | Confirmation/HITL lifecycle for assistant writes; `timeout` means the turn aborted WITHOUT executing the operation |
| **Control Center Assistant** | `assistant_intervention_pending` (gauge) — *proposed* | Pending `InterveneRequest` rows that block new chat messages for the session |
| **Control Center Assistant** | `chat_ws_disconnect_total` (labels: `code`) / `chat_ws_active_connections` (gauge) — *proposed* | WebSocket disconnect causes (idle-proxy closes vs auth/tenant rejections) and live connection count for reply-delivery health |
| **Control Center Assistant** | `assistant_catalog_anomalies_total` (labels: `kind` = `page_truncated`/`empty_catalog`/`cc_entity_leak`/`unknown_tool_requested`) — *proposed* | Sanity signal for the permission-filtered tool catalog: unexpected empty `tools/list`, page-cap truncation mistaken for missing tools, leak of the protected `cc` entity, or calls to unregistered tools |
| **Conversational Activity & Resume** | Non-terminal activity rows older than the staleness bound (gauge, labels: `state`) — *proposed* | Primary staleness signal. Working rows (`thinking`/`using_tool`/`delegating`) are refreshed by the CH heartbeat touch every ~15 s, so a growing count past `CONVERSATION_ACTIVITY_STALE_SECONDS` (default 180 s) means dead turns are not being resolved. Paused (`waiting_for_human`) rows are excluded — their resume record decides |
| **Conversational Activity & Resume** | Reaper sweep outcomes (labels: `outcome` = `swept`/`protected`/`resolved`/`purged`/`error`) — *proposed* | `protected` counts waiting rows correctly left alone; `swept` is emitted only when a pass resolved or purged something, so silence on an idle system is normal. Healthy = no `error` outcomes, waiting rows untouched, and stale working rows resolved within a few minutes of the bound |
| **Conversational Activity & Resume** | Terminal resolutions (labels: `state` = `finished`/`failed`/`timed_out`, `reason_code`) — *proposed* | Distinguishes genuine expiry (`expired`) from supersede/cancel from failure-to-resume; also confirms dead working turns resolve as `failed` + `unexpectedly_terminated` rather than as a pause timeout |
| **Conversational Activity & Resume** | Activity forward failures (`PUT …/activity` non-2xx) — *proposed* | A dropped forward makes the persisted state lag the live transition; the indicator goes stale and a reconnect hydrates the wrong state |
| **Conversational Activity & Resume** | Activity hydration failures (`GET …/activity` non-2xx, or empty on connect) — *proposed* | Hydration failure = a blank gap on reload/reconnect. Sustained non-zero points at the internal allowlist, signed tenant headers, or an unapplied migration |
| **Conversational Activity & Resume** | Pause persisted vs failed (labels: `outcome` = `persisted`/`failed`/`failed_payload_too_large`/`failed_transport`) — *proposed* | A pause that cannot be persisted is an operator-visible dead end: the assistant cannot safely ask for confirmation. `failed` rate > 0 is critical |
| **Conversational Activity & Resume** | Resume dispatch events (labels: `event` = `dispatched`/`deduplicated`/`succeeded`/`failed`) — *proposed* | Primary resume success ratio; `deduplicated` confirms the single-dispatch guard is absorbing repeat answers |
| **Conversational Activity & Resume** | Resume failures by reason (labels: `reason` = `checkpoint_missing`/`checkpoint_consumed`/`checkpoint_unavailable`/`deserialisation_failed`/`claim_held`/`dispatch_failed`/`instance_unreachable`) — *proposed* | Separates "our durable state is wrong" (checkpoint reasons) from "our transport or routing is wrong" (dispatch/instance reasons) |
| **Conversational Activity & Resume** | Orphaned turns — shown as waiting but not answerable (labels: `reason`) — *proposed* | **Invariant violation, target zero.** Any value is a defect signal, not routine expiry |
| **Conversational Activity & Resume** | Claim contention (labels: `result` = `acquired`/`held_by_other`/`expired_reacquired`/`terminal`/`not_found`) — *proposed* | `held_by_other` in steady state means duplicate answers are correctly serialised; sustained contention means a stale claim or a duplicate dispatch loop. `expired_reacquired` is the failover path |
| **Conversational Activity & Resume** | Checkpoint payload size (histogram, labels: `payload_kind`) and rejections (`rejected_too_large`) — *proposed* | A histogram pinned at `CONVERSATION_TURN_CHECKPOINT_MAX_BYTES` means pauses will start failing; any rejection is a capacity signal |
| **Conversational Activity & Resume** | Checkpoint lifecycle (labels: `event` = `written`/`consumed`/`purged`) and stored bytes/row count — *proposed* | `written` growing with a flat `purged` is a storage leak; healthy = payloads consumed once and purged after `CONVERSATION_TURN_CHECKPOINT_PURGE_AFTER_SECONDS` |
| **Conversational Activity & Resume** | Resume latency (histogram, labels: `result`) — *proposed* | Time from answer acceptance to first streamed status; a p99 regression points at checkpoint load or agent rebuild, not at the model |
| **Conversational Activity & Resume** | Confirmed-write outcome (labels: `result` = `applied`/`replayed`/`denied`/`expired_skipped`) — *proposed* | Proves exactly-once: `replayed` is correct (idempotency key short-circuited a duplicate); more than one `applied` per pause is a data-integrity incident |

> **Instrumentation status**: the Control Center Assistant emits **structured logs only** — no dedicated assistant OTel counters exist yet (the guardrail counter is the one pre-existing series reused above). Rows marked *proposed* must be derived from the log events in [logging-control-center-assistant.md](logging-control-center-assistant.md) until counters are instrumented. Alert names below are stable and safe to pre-create against log-derived series.
>
> The **Conversational Activity & Resume** rows are in the same position: the activity reaper, resume dispatch, checkpoint store, and Terminal Resolver emit structured log lines only. Derive these series from [logging-conversation-turns.md](logging-conversation-turns.md) (Conversation Activity and Resumable Turn Events) until counters ship; the alert names below are stable.
