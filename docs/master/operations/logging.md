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
| **Control Center Internal Policy** | Full boundary event model: allowlist allowed and denied outcomes, unknown caller denials, caller-certificate mismatch denials, endpoint-not-allowlisted denials, revocation check failures, and system-tools unauthenticated rejections |
| **API Key Auth (Communication Hub)** | Authentication validation (`api_key.auth.success`, `api_key.auth.failed`); skill loading (`api_key.load_skills`); tool call proxying (`api_key.tool_call`) |
| **API Key Management (Control Center)** | Key lifecycle events (`api_key.created`, `api_key.revoked`); internal validation lookups (`api_key.validation`) |
| **All components** | Service startup and shutdown with configuration summary; health check results; unhandled exceptions with full stack trace |
| **Startup Validation** | `startup.validation.*` events — dependency reachability checks at service boot (PostgreSQL, Keycloak, Redis, Control Center); pass/fail with latency and error detail |
| **Configuration Source** | `config.*.resolved` events — infrastructure connection source resolution (database, redis, OIDC, telemetry); emitted at INFO on every startup |
| **Security Guardrails** | `config.keycloak_admin_detected_in_runtime` WARNING — Keycloak admin credentials detected in runtime service environment; ignored by service but represents security risk |

### OIDC Identity Log Events

#### Super Admin Auth Events

All super admin events are in `backend/logs/control-center.log`. Search for `superadmin.`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `superadmin.login.success` | INFO | `username`, `remote_ip`, `token_expires_at` | Super admin authenticated successfully |
| `superadmin.login.failure` | WARN | `username`, `remote_ip`, `reason` | Failed super admin login; `reason` is `invalid_credentials`, `disabled`, or `expired` |
| `superadmin.logout` | INFO | `username`, `session_duration_s` | Super admin session ended (logout or token expiry) |
| `superadmin.disabled` | INFO | `changed_by`, `previous_state` | Super admin account was disabled via config or API |
| `superadmin.enabled` | INFO | `changed_by`, `previous_state` | Super admin account was enabled via config or API |
| `superadmin.bootstrap` | INFO | `username`, `source` | Super admin credentials seeded on first launch; `source` is `env_var` or `config_default` |

#### OIDC Config Service Events

All config events are in `backend/logs/control-center.log`. Search for `oidc.config.`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `oidc.config.created` | INFO | `provider_type`, `provider_name`, `issuer_url`, `actor` | New OIDC provider config created via UI or API |
| `oidc.config.updated` | INFO | `provider_type`, `provider_name`, `changed_fields[]`, `actor` | Existing provider config modified; `changed_fields` lists what was changed (never logs secret values) |
| `oidc.config.deleted` | WARN | `provider_type`, `provider_name`, `actor` | Provider config deleted; active sessions using this provider will fail on next validation |
| `oidc.config.test_connection` | INFO | `provider_type`, `provider_name`, `issuer_url`, `result` | Operator triggered OIDC connectivity test from UI |
| `oidc.config.test_login` | INFO | `provider_type`, `provider_name`, `result`, `claims_summary` | Operator triggered OIDC test login; `claims_summary` includes claim keys only (no values) |
| `oidc.config.migration` | INFO | `source_file`, `entries_migrated`, `result` | One-time migration from `config/identity.yaml` to database |

#### OIDC Provider Connectivity Events

All connectivity events are in `backend/logs/control-center.log`. Search for `oidc.discovery.` or `oidc.jwks.`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `oidc.discovery.success` | DEBUG | `provider_type`, `provider_name`, `issuer_url`, `duration_ms` | OIDC Discovery endpoint fetched successfully |
| `oidc.discovery.failure` | ERROR | `provider_type`, `provider_name`, `issuer_url`, `error`, `status_code` | OIDC Discovery endpoint unreachable or returned error |
| `oidc.jwks.fetch_success` | DEBUG | `provider_type`, `provider_name`, `keys_count` | JWKS keys fetched and cached |
| `oidc.jwks.fetch_failure` | ERROR | `provider_type`, `provider_name`, `jwks_uri`, `error` | JWKS endpoint unreachable; JWT validation will fail |
| `oidc.jwks.cache_expired` | INFO | `provider_type`, `provider_name`, `cache_age_s` | JWKS cache TTL expired; next request triggers refresh |
| `oidc.registry.initialized` | INFO | `provider_count`, `providers[]` | OIDC Provider Registry initialized at startup with provider summary |
| `oidc.registry.reloaded` | INFO | `trigger`, `provider_count_before`, `provider_count_after` | Registry cache invalidated and reloaded from database |
| `oidc.registry.reload_failed` | ERROR | `trigger`, `error` | Registry reload from database failed; stale config remains in use |

#### Auth Middleware Decision Events

All auth middleware events are in `backend/logs/control-center.log`. Search for `auth.pipeline.` and `auth.oidc.`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `auth.pipeline.decision` | INFO | `tier`, `outcome`, `user_identity`, `provider_type`, `request_path` | Auth decision logged per request; `tier` is `super_admin`, `oidc_user`, `oidc_agent`, or `public` |
| `auth.pipeline.superadmin_skipped` | INFO | `remote_ip`, `reason` | Super admin tier skipped; `reason` is `disabled` or `no_superadmin_token` |
| `auth.pipeline.oidc_provider_not_found` | ERROR | `provider_type` | No active provider config found for the requested provider type in registry |
| `auth.oidc.jwt_invalid` | WARN | `provider_type`, `reason`, `token_hint` (first 8 chars) | JWT validation rejected; `reason` is `signature`, `expired`, `audience`, `issuer`, `claims`, or `unknown` |
| `auth.oidc.jwt_valid` | DEBUG | `provider_type`, `sub`, `expires_at` | JWT validated successfully (debug level to avoid logging every request in production) |

#### OIDC Sensitive Data Exclusions

- Never log client secrets, OIDC client credentials, JWT payload bodies, or access/refresh token values
- Never log full super admin password hashes
- Log only the first 8 characters of JWT tokens as a `token_hint` for correlation
- Log claim key names for test login events but never claim values
- Use `changed_fields[]` for config mutations — list field names only, never values

---

## Startup Validation Log Events

Startup validation checks emit structured log events under the namespace `parthenon.startup`. All events include the `service_name` field. These are distinct from normal runtime health check logs.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `startup.validation.begin` | INFO | `service_name`, `dependencies` | Startup validation phase begins; lists which dependencies will be checked |
| `startup.validation.database_ok` | INFO | `host`, `port`, `latency_ms` | PostgreSQL reachability confirmed |
| `startup.validation.database_failed` | ERROR | `host`, `port`, `error` | PostgreSQL unreachable; includes connection error detail |
| `startup.validation.keycloak_ok` | INFO | `issuer_url`, `realm_found` | Keycloak realm confirmed to exist |
| `startup.validation.keycloak_not_found` | ERROR | `issuer_url`, `expected_realm`, `error_detail` | Expected Keycloak realm does not exist or OIDC discovery endpoint unreachable |
| `startup.validation.redis_ok` | INFO | `host`, `port`, `latency_ms` | Redis PING successful |
| `startup.validation.redis_failed` | ERROR | `host`, `port`, `error` | Redis PING failed; includes connection error detail |
| `startup.validation.control_center_ok` | INFO | `url`, `latency_ms` | Control Center health check successful (logged by AR and CH) |
| `startup.validation.control_center_unreachable` | ERROR | `url`, `error`, `retries_exhausted` | Control Center health check failed after all retries |
| `startup.validation.complete` | INFO | `service_name`, `all_passed` | All validations complete; service proceeding to operational state |

---

## Configuration Source Log Events

Every infrastructure connection is logged at startup with the resolved configuration source. These log events use the namespace `parthenon.config` and are emitted at `INFO` level.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `config.database.resolved` | INFO | `host`, `port`, `database`, `source`, `source_detail` | After PostgreSQL connection parameters are resolved |
| `config.redis.resolved` | INFO | `host`, `port`, `source`, `source_detail` | After Redis connection parameters are resolved |
| `config.oidc.resolved` | INFO | `issuer_url`, `client_id`, `provider_type`, `source`, `source_detail` | After OIDC configuration parameters are resolved |
| `config.telemetry.resolved` | INFO | `exporter_type`, `source`, `source_detail` | After telemetry configuration is resolved |

**`source_detail` values**:
- `env_var:POSTGRES_HOST` — resolved from a specific environment variable
- `yaml:config/telemetry.yaml` — resolved from a YAML configuration file
- `default` — using the built-in default value

**Production monitoring**: In production, the source should consistently be `env var` for all infrastructure connections. If any connection resolves from `YAML file` or `built-in default`, the corresponding environment variable is likely missing.

---

## Security Guardrail Log Events

Security guardrail events detect potentially unsafe configuration practices at runtime. These are emitted at startup when configuration anomalies are detected.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `config.keycloak_admin_detected_in_runtime` | WARNING | `service_name` | `KEYCLOAK_ADMIN` or `KEYCLOAK_ADMIN_PASSWORD` found in CC environment; credentials are ignored by runtime but represent a security risk |

**Action**: Remove `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` from the Control Center service environment immediately. These variables should only be present on the setup tool/service environment.

---

### Agent Execution Guardrail Events

| Event | Level | Description |
|-------|-------|-------------|
| `guardrail.precheck.allowed` | INFO | Pre-execution guardrail checks passed |
| `guardrail.precheck.blocked_cycle` | WARN | Recursive delegation cycle detected and blocked before execution |
| `guardrail.runtime.iteration_limit_exceeded` | WARN | Cumulative iteration ceiling reached |
| `guardrail.runtime.timeout_exceeded` | WARN | Per-agent wall-clock timeout reached |
| `guardrail.runtime.delegation_depth_exceeded` | WARN | Delegation depth limit reached |
| `guardrail.runtime.delegated_steps_exceeded` | WARN | Delegated-step budget reached |
| `guardrail.runtime.token_budget_exceeded_non_conversational` | WARN | Non-conversational or automated execution exceeded hard token budget |
| `guardrail.runtime.conversational_token_threshold_observed` | INFO | Conversational token threshold reached, continuation still allowed |
| `guardrail.runtime.conversational_token_usage_snapshot` | INFO | Conversational current-session token usage snapshot emitted |
| `guardrail.runtime.token_fallback_applied` | INFO | Fallback mode activated where strict token enforcement is unavailable |
| `guardrail.session.terminal` | INFO | Session ended by guardrail with canonical stop reason |

### Guardrail Reason Taxonomy (Canonical)

Use a stable `guardrail_reason` value set for metrics and logs:

- `cycle_blocked`
- `iteration_limit_exceeded`
- `timeout_exceeded`
- `delegation_depth_exceeded`
- `delegated_steps_exceeded`
- `token_budget_exceeded_non_conversational`
- `conversational_token_threshold_observed`
- `token_fallback_applied`

### Required Fields for Guardrail Events

All guardrail events must include the following fields.

| Field | Requirement |
|-------|-------------|
| `timestamp` | ISO 8601 UTC with millisecond precision |
| `service_name` | Emitting service identifier |
| `trace_id` | Correlates to distributed trace |
| `span_id` | Correlates to specific trace span |
| `session_id` | Agent session identifier |
| `agent_type_id` | Agent type associated with the guardrail decision |
| `guardrail_reason` | Canonical reason from the taxonomy above |
| `execution_mode` | Mode used for policy resolution |
| `current_value` | Observed value at decision time |
| `threshold_value` | Policy threshold value used in the decision |
| `policy_snapshot_id` | Policy/version snapshot used to evaluate the guardrail |

Conditional fields:
- `token_usage_current_session` and `continuation_allowed` for conversational token events.
- `fallback_mode` for fallback events.
- `delegation_chain_depth` for delegation-depth and delegated-step events.

### Sensitive Data Exclusions for Guardrail Events

- Never log identity tokens, refresh tokens, JWT payload bodies, API keys, decrypted secrets, or credential material.
- Never log full prompt or tool payload contents in guardrail events.
- Log operational identifiers and counters only; keep guardrail analytics fields stable and non-secret.

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

## Agent Runtime Log Events

### Log Sources

| Component | Log Source | Access |
|-----------|-----------|--------|
| `SessionDispatcher` | `control-center` container stdout | `docker compose logs control-center` or Loki: `{service="control-center"} |= "session_dispatcher"` |
| `AgentRuntimeExecutor` | `control-center` container stdout | `docker compose logs control-center` or Loki: `{service="control-center"} |= "runtime_executor"` |
| `AgentPermissionManager` | `control-center` container stdout | Loki: `{service="control-center"} |= "permission_manager"` |
| `AgentSessionService` | `control-center` container stdout | Loki: `{service="control-center"} |= "agent_session_service"` |
| `LifecycleHandler` (Gateway) | `control-center` container stdout | Loki: `{service="control-center"} |= "lifecycle_handler"` |

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
| `CertificateManager` | `control-center` container stdout | `docker compose logs control-center` or Loki: `{service="control-center"} \|= "cert."` |
| `CertificateAuthority` | `control-center` container stdout | Loki: `{service="control-center"} \|= "ca.init"` |

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
| `internal.allowlist.allowed` | INFO | `caller_type`, `caller_identity`, `certificate_type`, `method`, `endpoint`, `policy_version`, `trace_id` | Internal request is allowlisted for the caller profile |
| `internal.allowlist.denied` | WARN | `caller_type`, `caller_identity`, `certificate_type`, `method`, `endpoint`, `deny_reason`, `policy_version`, `trace_id` | Internal request denied by default policy before handler execution |
| `internal.allowlist.unknown_caller` | WARN | `caller_identity`, `method`, `endpoint`, `deny_reason`, `trace_id` | Caller identity missing, malformed, or unrecognized during policy evaluation |
| `internal.allowlist.certificate_mismatch` | WARN | `caller_type`, `certificate_type`, `method`, `endpoint`, `deny_reason`, `trace_id` | Presented certificate type does not match caller profile |
| `internal.allowlist.endpoint_not_allowlisted` | WARN | `caller_type`, `method`, `endpoint`, `deny_reason`, `policy_version`, `trace_id` | Caller attempted an endpoint outside the caller-scoped allowlist |
| `internal.revocation.check_failed` | ERROR | `caller_type`, `caller_identity`, `certificate_type`, `failure_mode`, `method`, `endpoint`, `trace_id` | Revocation status could not be validated for an internal request |
| `internal.system_tools.unauthenticated_rejected` | WARN | `endpoint`, `method`, `deny_reason`, `trace_id` | Internal system-tools route rejected due to missing or invalid service certificate |

### Required Fields for Boundary Events

All internal boundary events must include the following fields.

| Field | Requirement |
|-------|-------------|
| `timestamp` | ISO 8601 UTC with millisecond precision |
| `service_name` | Emitting service identifier |
| `trace_id` | Correlates to distributed trace |
| `span_id` | Correlates to specific trace span |
| `caller_type` | Normalized caller class (`agent_runtime`, `communication_hub`, or `unknown`) |
| `caller_identity` | Operational caller identity value used by policy |
| `certificate_type` | Presented certificate class used in evaluation |
| `endpoint` | Canonical internal route path |
| `method` | HTTP method |
| `decision` | `allowed` or `denied` |
| `deny_reason` | Required when denied; set to `none` when allowed |
| `policy_version` | Active allowlist policy version |
| `environment` | Deployment environment label |

### Sensitive Data Exclusions for Boundary Events

- Never log access tokens, refresh tokens, JWT bodies, decrypted secrets, private keys, or certificate private material.
- Never log raw system-tools request payloads.
- Use operational identifiers only for `caller_identity` (service name, mapped principal, or equivalent non-secret identifier).

### Boundary Incident Query Guide

- Filter by `caller_type` and `decision` first to isolate affected internal caller flows.
- Group denied events by `deny_reason` and `endpoint` to separate contract drift from identity failures.
- Use `trace_id` to pivot from deny events to distributed traces for cross-service timeline analysis.
- Correlate `internal.revocation.check_failed` with deny spikes to identify fail-closed impact.

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

## API Key Log Events

### Communication Hub — API Key Auth Events

**Log source**: `backend/logs/communication-hub.log`

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `api_key.auth.success` | INFO | `key_prefix`, `identity_id`, `role_id`, `ip_address`, `action` | API key validated successfully; `action` is one of `validate`, `load_skills`, or `tool_call` |
| `api_key.auth.failed` | WARN | `key_prefix`, `failure_reason`, `ip_address`, `action` | Authentication rejected; `failure_reason` is `invalid_key`, `revoked`, or `expired` |
| `api_key.load_skills` | INFO | `key_prefix`, `skill_count`, `sync_mode`, `since` | `load_skills` completed; `sync_mode` is `full` or `incremental` |
| `api_key.tool_call` | INFO | `key_prefix`, `tool_name`, `outcome` | Tool call proxied via API key auth; `outcome` is `success` or `permission_denied` |

### Control Center — API Key Management Events

**Log source**: `backend/logs/control-center.log`

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `api_key.created` | INFO | `key_id`, `key_prefix`, `identity_id`, `role_id`, `created_by` | New API key issued by Platform Administrator |
| `api_key.revoked` | WARN | `key_id`, `key_prefix`, `revoked_by`, `reason` | API key manually revoked |
| `api_key.validation` | DEBUG | `key_prefix`, `outcome`, `duration_ms` | Internal key validation against CC database; `outcome` is `valid`, `invalid`, or `revoked` |

### Required Fields for All API Key Log Events

| Field | Requirement |
|-------|-------------|
| `key_prefix` | First 8 characters of the key (e.g. `phn_sk_a1b2c3`); never log the full key value |
| `ip_address` | Client IP address that submitted the key |
| `action` | Operation type: `validate`, `load_skills`, or `tool_call` |
| `success` | Boolean outcome of the operation |
| `trace_id` | OTEL trace ID for cross-service correlation |
| `timestamp` | ISO 8601 UTC with millisecond precision |

### Sensitive Data Exclusions

- Never log the full API key value, key hash, or any part of the key beyond the 8-character prefix.
- Never log the resolved identity token — CH holds it internally in-memory only.

### Audit Table: `ApiKeyUsageLog`

The `ApiKeyUsageLog` database table provides an immutable, append-only audit trail for every API key operation. It is the authoritative source for compliance reporting and long-term security analysis.

| Column | Description |
|--------|-------------|
| `api_key_id` | Reference to the `AgentApiKey` row; enables per-key audit queries |
| `action` | `validate`, `load_skills`, or `tool_call` |
| `tool_name` | Qualified tool name for `tool_call` actions; `NULL` otherwise |
| `ip_address` | Client IP that submitted the request |
| `timestamp` | UTC timestamp of the operation |
| `success` | `true` if the operation completed successfully; `false` for auth failures or permission denials |

**Retention**: 90 days in the active database; archive to cold storage for longer-term compliance.

### Where to Find API Key Logs

| Concern | Source | Access |
|---------|--------|--------|
| API key authentication decisions | Communication Hub | `backend/logs/communication-hub.log` — search for `api_key.auth` |
| Key management CRUD operations | Control Center | `backend/logs/control-center.log` — search for `api_key.created` or `api_key.revoked` |
| Per-key usage audit trail | Database | Query `api_key_usage_logs` table, filter by `api_key_id` or date range |
| Skill resolution failures | Communication Hub / Control Center | `backend/logs/communication-hub.log` for `api_key.load_skills` errors; `backend/logs/control-center.log` for permission resolution errors |
| Identity token refresh failures | Control Center | `backend/logs/control-center.log` — search for `identity.token_refresh_failed` |
| Distributed trace correlation | All services | Use `trace_id` from any log line to jump to the full trace in Jaeger |

---

## Setup Tool Log Events

The consolidated setup command emits its own structured log events, separate from the runtime service logs. These are written to stdout when the setup tool is run and are not shipped to Loki (setup is a one-shot operation).

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `setup.identity.realm_created` | INFO | `realm_name` | New Keycloak realm provisioned |
| `setup.identity.realm_exists` | INFO | `realm_name` | Realm already exists; skipped (idempotent) |
| `setup.identity.client_created` | INFO | `client_id`, `realm` | New OIDC client registered |
| `setup.identity.client_exists` | INFO | `client_id` | Client already registered; skipped |
| `setup.identity.admin_created` | INFO | `username`, `realm` | Admin user created in Keycloak |
| `setup.identity.admin_exists` | INFO | `username` | Admin user already exists; skipped |
| `setup.database.verified` | INFO | `host`, `port`, `database` | Database schema and connectivity confirmed |
| `setup.database.seeded` | INFO | `entity_type`, `count` | Default data seeded (roles, permissions, skills, system tools) |
| `setup.certificates.ca_created` | INFO | `serial_number`, `expires_at` | New certificate authority generated |
| `setup.certificates.ca_exists` | INFO | `serial_number` | CA already exists; skipped |
| `setup.verify.all_ok` | INFO | — | All components in expected state |
| `setup.verify.issues_found` | WARNING | `issues` | One or more components need attention; lists specific issues |
| `setup.error` | ERROR | `operation`, `error` | Setup operation failed; includes full error detail |

### Setup Tool Log Access

| Source | Access Method |
|--------|---------------|
| Setup tool stdout | stdout of the `setup` command or setup Job pod — not shipped to Loki |

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
