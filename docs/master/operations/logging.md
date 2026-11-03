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
| **API Key Management (Control Center)** | Key lifecycle events (`api_key.created`, `api_key.revoked`, `api_key.deleted`); internal validation lookups (`api_key.validation`) |
| **MCP Protocol Server (Communication Hub)** | MCP handshake and tool activity (`mcp.initialize`, `mcp.tools_list`, `mcp.tools_call`); expired-key rejections (`api_key.auth.failed` with reason `expired`) |
| **MCP OAuth Bearer Auth (Communication Hub)** | OAuth/OIDC user-token validation on `/mcp*`: authenticated user, bound tenant, invalid/expired token, missing `sub`, and Control Center `/resolve` failures (`OAuth middleware:*` lines) |
| **Control Center Assistant (Control Center)** | Management-tool session resolution and dispatch (`Management resolve:*`), permission denials and in-band scopes/deletes (returned to the caller, logged as request outcomes), assistant seeding (`AssistantSeeder:*`) |
| **All components** | Service startup and shutdown with configuration summary; health check results; unhandled exceptions with full stack trace |
| **Startup Validation** | `startup.validation.*` events — dependency reachability checks at service boot (PostgreSQL, Keycloak, Redis, Control Center); pass/fail with latency and error detail |
| **Configuration Source** | `config.*.resolved` events — infrastructure connection source resolution (database, redis, OIDC, telemetry); emitted at INFO on every startup |
| **Security Guardrails** | `config.keycloak_admin_detected_in_runtime` WARNING — Keycloak admin credentials detected in runtime service environment; ignored by service but represents security risk |
| **Tenant Resolution Middleware (Control Center)** | Per-request resolution decisions and fail-closed rejections (`tenant.resolution.*`); JWT tenant-claim mismatches (`tenant.claim.mismatch`); platform switch toggles and adoption runs (`platform.settings.*`, `tenant.adoption.*`) |
| **Tenant Scoping / DB Gateway (Control Center)** | Cross-tenant direct-addressing stops (`tenant.scope.violation`); tenant audit-event writes (cross-tenant attempts, lifecycle actions, quota exhaustion) |
| **Per-Tenant OIDC Registry (Control Center)** | Per-tenant discovery, JWKS, and token validation failures (`tenant.oidc.*`), tenant-attributed mirrors of the `oidc.discovery.*` / `oidc.jwks.*` events |
| **Tenant Lifecycle (Control Center)** | Create / suspend / resume / delete events (`tenant.lifecycle.*`) with `actor` and `tenant_slug` |
| **Tenant Signed-Header Verification (Agent Runtime, Communication Hub)** | Signing failures on CC outbound clients and verification failures (missing / tampered / stale / unsigned) in the AR `ControlCenterCertificateMiddleware` and CH `ControlPlaneMiddleware` (`tenant.signature.*`) |
| **Tenant Routing Denials (Communication Hub)** | Cross-tenant A2A refusals (`tenant.a2a.refused`); MCP session tenant-binding failures and API-key/tenant mismatches (`tenant.api_key.mismatch`); tenant-filtered tool listing/calls (`tenant.denied`) |

### Multi-Tenancy Log Events

Emitted only while the tenancy platform switch (`multi_tenancy_enabled`) is **on**. When off, no tenant events exist. Unless noted, events are in `backend/logs/control-center.log`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `tenant.resolution.*` | INFO/WARN | `outcome` (`resolved`/`unknown`/`suspended`/`deleted`), `tenant_slug` | Per-request resolution outcome; WARN entries are fail-closed rejections |
| `tenant.claim.mismatch` | WARN | `tenant_id`, `subject` | Validated JWT tenant claim does not equal the resolved tenant; request rejected |
| `tenant.scope.violation` | WARN | `tenant_id`, `resource`, `surface` | Cross-tenant direct addressing stopped at the DB gateway; returned as not-found plus a `TenantAuditEvent` |
| `tenant.oidc.*` | ERROR/WARN | `tenant_id`, `provider_name`, `reason` | Per-tenant discovery, JWKS, or token validation failure (tenant-attributed `oidc.discovery.*` / `oidc.jwks.*` mirror) |
| `tenant.lifecycle.*` | INFO | `action`, `actor`, `tenant_slug` | Tenant create / suspend / resume / delete |
| `tenant.adoption.*` | INFO/ERROR | `rows_backfilled`, `tenant_slug` | Root-tenant (workspace `root`) adoption/backfill when the switch is first enabled; ERROR means incomplete adoption |
| `platform.settings.*` | INFO | `setting`, `value`, `actor` | Tenancy switch toggled; cache invalidation recorded |
| `tenant.signature.*` (CC, AR, CH) | WARN | `direction` (`sign`/`verify`), `reason` (`missing`/`tampered`/`stale`/`unsigned`) | Signing failure on CC outbound clients; verification failure in AR `ControlCenterCertificateMiddleware` and CH `ControlPlaneMiddleware` |
| `tenant.a2a.refused` (communication-hub.log) | WARN | `source_tenant_id`, `target_tenant_id` | A2A pair does not share a tenant; message not routed |
| `tenant.api_key.mismatch` (communication-hub.log) | WARN | `key_prefix`, `expected_tenant_id`, `actual_tenant_id` | MCP API key validated against a different tenant than the session context |
| `no_access_to_workspace` | WARN | `subject`, `workspace` | Authenticated user has no membership in the resolved workspace; returns HTTP 403 — this is a final authorization denial, **not** a re-auth loop trigger |

Troubleshooting quick patterns:

- Requests rejected before feature logic: search `control-center.log` for `tenant.resolution` and `tenant.rejected`
- Suspected isolation probing: search `control-center.log` for `tenant.scope` and `tenant.claim`, then filter platform audit events by `tenant_id`
- Executions rejected downstream: search `agent-runtime.log` for `tenant context` and `rejected`
- Routing/tool-call denials: search `communication-hub.log` for `tenant.denied` and `cross-tenant`
- A single tenant locked out: search `control-center.log` for `tenant.oidc` plus the tenant slug/id

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

## Control Center Assistant Events

The Control Center Assistant is a **delegated actor**: it acts as the signed-in OAuth user, never elevated, never deleting. Management tools are `cc____<bare>` tools on the Communication Hub MCP protocol server; both the in-app chatbot and external MCP clients use the same OAuth identity plane and the same permission resolution.

**Log files** (from `docs/config.yaml`): `backend/logs/control-center.log`, `backend/logs/communication-hub.log`, `backend/logs/agent-runtime.log`, `backend/logs/otel.log`. Files rotate at ~10 MB with `.1`/`.2` retained.

> **Instrumentation note**: the assistant emits **plain structured log lines today** — there are no dedicated `management_tool.*` OTel counters or JSON event names yet. The *Proposed event* column is the stable taxonomy to adopt when counters/events are instrumented; use the *Observed message* column for live greps.

### Management Tool Execution and Permission Decisions

**Log source**: `backend/logs/control-center.log`

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `Management resolve: sub=… user=… tenant=… permitted=…` | `management_tool.session_resolved` | INFO | `sub`, `platform_user_id`, `tenant_id`, `permitted_count` | OAuth MCP session creation; `permitted=0` means the user holds no management grants in the resolved tenant |
| `authorize_identity DENIED: user_id=… module=… action=… reason=…` | `management_tool.permission_denied` | WARN | `user_id`, `resource_type` (`module`), `action`, `reason` | Parity authorization failed for the user's own scope on `/{tool_name}` or the `invoke_management_tool` wrapper; the HTTP response carries `PermissionDeniedDetail` |
| `authorize_identity ALLOWED: user_id=… module=… action=…` / `ALLOWED via membership: …` | `management_tool.call_allowed` | DEBUG | `user_id`, `module`, `action` | Successful per-call re-authorization (debug level; enable temporarily when tracing a denial) |
| `authorize_identity: user_id=… has no active membership in resolved tenant=… — no_access_to_workspace` | `management_tool.tenant_membership_denied` | WARN | `user_id`, `tenant_id` | Identity is valid but holds no membership in the resolved tenant; returns the structured `no_access_to_workspace` 403 |
| Tool result body `{"error":"out_of_scope"}` returned by the Communication Hub (no CC write attempted) | `management_tool.scope_rejected` | WARN | `tool_name`, `requested_scope` | Request outside the Agents-menu / MCP Hub management surface |
| Tool result body `{"error":"deletion_not_supported"}` | `management_tool.delete_rejected` | WARN | `tool_name` | Any delete-shaped `cc____delete_*` attempt; deliberately non-mutating |
| Tool result body `{"error":"permission_denied"}` returned by the Communication Hub | `management_tool.permission_denied` (CH-side) | WARN | `tool_name` | Canonical name is not in the OAuth session's permitted set; denied before the CC call |
| HTTP 404 `Unknown or out-of-scope management tool` / `Unknown management verb` | `management_tool.unknown_tool` | WARN | `tool_name`, `verb` | Unregistered tool or delete-verb backstop at the CC dispatch layer |
| `authorize_identity: PlatformUser not found for sub=… — user must re-authenticate` | `management_tool.identity_resolution_failed` | WARN | `sub` | OAuth identity could not resolve to a `PlatformUser`; fail-closed, no write performed |
| `Created intervene request …` / `Submitted response …` from the intervene service | see Intervention lifecycle below | INFO | `request_id`, `session_id`, `operator` | Confirmation/HITL lifecycle |

**Dispatch path**: Communication Hub `tools/call` → `POST /api/v1/internal/management-tools/{tool_name}` (or the meta wrapper `invoke_management_tool`) → re-authorization against the user's own `(resource_type, action)` → handler. The per-call denial is returned in-band (assistant relays it) — there is no elevated fallback path.

### MCP OAuth Identity Plane (Communication Hub)

**Log source**: `backend/logs/communication-hub.log`

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `OAuth middleware: authenticated user <sub> on <path>` | `mcp.oauth.authenticated` | INFO | `sub`, `path` | OIDC (or platform-account) Bearer token validated on `/mcp*` |
| `OAuth middleware: bound tenant <tenant_id> for user <sub>` | `mcp.oauth.tenant_bound` | INFO | `tenant_id`, `sub` | Multi-tenant mode: CC-signed header set bound for downstream calls |
| `OAuth middleware: invalid user token on <path>` | `mcp.oauth.rejected` (reason `invalid_token`) | WARN | `path` | Signature/expiry/issuer failure → HTTP 401, `auth_type=oauth` |
| `OAuth middleware: token missing sub claim on <path>` | `mcp.oauth.rejected` (reason `missing_subject`) | WARN | `path` | Valid signature but unusable identity → HTTP 401 |
| `OAuth middleware: CC resolve returned HTTP <n> for sub <sub>` | `mcp.oauth.rejected` (reason `identity_unresolvable` / `tenant_unresolvable`) | WARN | `sub`, `status_code` | CC `/resolve` denied (unknown user or unresolvable tenant) → HTTP 401 |
| `OAuth middleware: failed to resolve user via CC: <exc>` | `mcp.oauth.resolve_error` | ERROR | `sub`, `error` | Transport/CC failure during resolve; also fail-closed 401 |
| `OAuth middleware: unexpected OIDC error` / `platform token validation failed` | `mcp.oauth.validation_error` | WARN | `path` | Validation exceptions (JWKS fetch, clock skew, malformed token) |

Non-JWT (opaque `phn_sk_*`) tokens fall through untouched to the API-key middleware — see [API Key Log Events](#api-key-log-events).

### Control Center (cc) Entity Guards

**Log source**: `backend/logs/control-center.log` (MCP Hub REST surface)

| Response code | Proposed event | Level | Key fields | When returned |
|---------------|----------------|-------|-----------|---------------|
| `403` with `code = system_managed_integration` (detail: "system-managed and cannot be modified") | `cc.entity.system_managed_rejected` | WARN | `actor`, `operation` (`update`/`delete`/`sync`/`oauth`) | Any attempt to mutate/lifecycle the `cc` entity — locked for everyone; the seeder is the only writer |
| `403` with `code = system_managed_integration` (detail: "Sessions are not supported") | `cc.entity.sessions_unsupported` | WARN | `actor`, `operation` | Session operations against `cc`; access flows through role/skill grants only |
| `403` with `required_permission.resource_type = integration::control_center` | `cc.entity.permission_gated` | WARN | `actor`, `action` (`read`/`manage`) | Tool-grant operations on `cc` tools without the entity grant |
| `404 MCP server not found` (while the `cc` row exists) | `cc.entity.hidden` | DEBUG | `actor` | Read-visibility gate: the entity is hidden from callers lacking `integration::control_center:read` |
| `403 System agent types cannot be modified` / `cannot be deleted` | `assistant.agent_type.protected` | WARN | `agent_type_id`, `actor` | Direct REST mutation of the seeded `is_system=true` assistant agent type |

### Conversation Turn Lifecycle

**Log sources**: `backend/logs/communication-hub.log` (socket, watchdog, heartbeat) and `backend/logs/agent-runtime.log` (agent loop, LLM timeout, guardrail stops)

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `WebSocket connected: session=… subject=…` | `chat.ws.connected` | INFO | `session_id`, `subject` | Authenticated conversation socket (also the point where the user JWT is cached for dual-identity tool calls) |
| `WebSocket rejected: invalid token for session …` | `chat.ws.rejected` (reason `invalid_token`) | WARN | `session_id` | Close `1008` — no valid OIDC or platform token |
| `WebSocket rejected: <reason> for session … (subject=…)` | `chat.ws.rejected` (reason `tenant_context`) | WARN | `session_id`, `subject`, `reason` | Close `4003` — tenant context could not be bound (fail-closed) |
| `WebSocket disconnected: session=… code=… reason=…` | `chat.ws.disconnected` | INFO | `session_id`, `code`, `reason` | Every socket close, including idle-proxy closes — correlate `code` with the disconnect alert |
| `Conversation turn watchdog fired for session … after …s` | `chat.turn.watchdog` (kind `timeout`) | WARN | `session_id`, `timeout_seconds` | Whole-turn bound (`agent_question_timeout_seconds`) fired before any reply |
| `Conversation turn persistence exceeded the watchdog for session …` | `chat.turn.watchdog` (kind `persistence_timeout`) | WARN | `session_id`, `timeout_seconds` | Reply already reached the user; only the CC persistence tail hung (no duplicate error emitted) |
| `Cancelled pending conversation turn for session … (session ended)` | `chat.turn.cancelled` | INFO | `session_id` | End-session termination canceled the in-flight CH turn |
| `Conversation turn blocked for session …: code=…` | `chat.turn.blocked` | WARN | `session_id`, `code` (`assistant_model_not_configured`, `iteration_limit`, `guardrail_<reason>`) | Structured turn error surfaced to the UI with typed guidance |
| `Background conversation turn failed for session …` | `chat.turn.failed` | ERROR | `session_id`, `error` (stack) | Unexpected exception in the turn pipeline |
| `WebSocket send failed for session … (socket=…)` | `chat.ws.send_failed` | WARN | `session_id`, `socket_state` | Dead socket during reply delivery; persistence is unaffected and the live-socket lookup retries on the next send |
| `Conversation turn … paused on human_intervene — waiting up to …s for operator response` | `chat.turn.waiting_for_human` | INFO | `conv_session_id`, `timeout_seconds` | Assistant called `human_intervene` (confirmation before a write) |
| `Conversation turn … still paused on human_intervene (…s) — extending wait` | `chat.turn.intervention_wait_extended` | INFO | `conv_session_id`, `elapsed_seconds` | LLM timeout re-armed while an intervention is legitimately pending |
| `Conversation turn timed out after …s (session=…, bound=…)` | `chat.turn.llm_timeout` | WARN | `conv_session_id`, `bound` | AR `conversation_llm_timeout_seconds` expired → `timeout_or_failed` |
| `Conversation guardrail stop (LangGraph[ , post-resume]): session=… reason=…` | `chat.turn.guardrail_stop` | WARN | `conv_session_id`, `reason` | Guardrail stop forwarded to CH; `iteration_limit` becomes the user-facing step-limit message |

The `thinking_heartbeat` status event is emitted every 15 s while a turn is in flight (keeps idle proxies open and the UI spinner alive); it is a WS status payload, not a log line — absence of heartbeats alongside a live socket is itself the signal.

### Intervention Lifecycle (Confirmation / HITL)

**Log sources**: `backend/logs/agent-runtime.log` (graph pause/resume) and `backend/logs/control-center.log` (request state); OTEL spans `intervene.create_request`, `intervene.submit_response`, `intervene.cancel_request`

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `Created intervene request … for session … (type=…)` | `intervention.created` | INFO | `request_id`, `agent_session_id`, `intervention_type` | Assistant requested approval/choice/text before a mutating action |
| `Received intervention response for request … from session …` | `intervention.response_received` | INFO | `request_id`, `session_id` | WS `intervene_response` arrived |
| `Intervention response … persisted via CC` | `intervention.approved` / `intervention.denied` | INFO | `request_id` | Response persisted; approve/deny is carried in the response payload (`approval_value`) |
| `Resumed agent session … after human response to request …` | `intervention.session_resumed` | INFO | `request_id`, `session_id` | Non-conversational session resumed from `waiting_for_human` |
| `Conversation turn … resuming deep-agent loop after operator response (approval=…)` | `intervention.resumed` | INFO | `conv_session_id`, `approval_value` | Same conversational graph resumed via `Command(resume=…)` |
| `The confirmation request timed out without a response` (user-facing) + `timeout_or_failed` status | `intervention.timeout` | WARN | `conv_session_id`, `timeout_seconds` | No response within `conversation_intervention_timeout_seconds`; **the operation was not executed** |
| `Failed to persist intervention response …: …` | `intervention.persist_failed` | ERROR | `request_id`, `error` | CC submit failed; UI shows an intervention error and stays blocked |
| `Cancelled intervene request …` | `intervention.cancelled` | INFO | `request_id` | Operator or session-end canceled the pending request |

While an intervention is pending, further chat messages are rejected with a `chat_blocked` payload (`reason=intervention_pending`) rather than queued — a user reporting "the assistant stopped accepting messages" is usually an unanswered confirmation.

### Assistant Seed Events

**Log source**: `backend/logs/control-center.log` (startup)

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `AssistantSeeder complete: {summary}` | `assistant.seed.success` | INFO | `tenants`, `per_tenant` (created/updated) | Idempotent per-tenant seed finished |
| `AssistantSeeder failed; the assistant may be unavailable.` | `assistant.seed.failed` | ERROR | `error` (stack) | Seeder raised; assistant agent type/tools may be missing |
| `AssistantSeeder: provisioning failed for tenant … — rolling back this tenant only and continuing.` | `assistant.seed.tenant_failed` | ERROR | `tenant_id` | Per-tenant failure (other tenants unaffected) |
| `AssistantSeeder: management tool '…' could not be provisioned for tenant … — binding skipped.` | `assistant.seed.binding_skipped` | ERROR | `tool_name`, `tenant_id` | Registry/tool row mismatch; that management tool is unreachable through the skill |
| `AssistantSeeder: created management skill '…'` / `updated management skill '…'` | `assistant.seed.skill` | INFO | `skill_name`, `tenant_id` | Management skill upsert |
| `AssistantSeeder: provisioned management tool '…' for tenant …` | `assistant.seed.tool` | INFO | `tool_name` (`cc____…`), `tenant_id` | New `cc____` tool row created |
| `AssistantSeeder: provisioned/refreshed per-tenant Control Center (cc) server for tenant …` | `assistant.seed.cc_server` | INFO | `tenant_id` | Protected `cc` MCP entity upserted/drift-corrected |
| `AssistantSeeder: retired N legacy system____ management rows for tenant …` | `assistant.seed.legacy_retired` | INFO | `tenant_id`, `rows` | One-time `system____` → `cc____` namespace migration |
| `AssistantSeeder: created/updated assistant agent type '…'` | `assistant.seed.agent_type` | INFO | `agent_type`, `tenant_id` | Seeded `is_system=true` assistant agent type |
| `SkillSeeder complete: {summary}` / `SkillSeeder failed; …` | `skill.seed.*` | INFO / ERROR | `summary` | Companion seeder; a failure degrades default skills, not the assistant |

A seeded assistant with **no model bound** is valid: the first turn returns the structured `assistant_model_not_configured` error until an administrator picks a model per workspace (System Config → Assistant model).

### Knowledge and Meta-Tool Dispatch

**Log sources**: `backend/logs/communication-hub.log` (`MCP tool call: tool=…`), `backend/logs/control-center.log` (meta endpoints)

| Observed message | Proposed event | Level | Key fields | When logged |
|------------------|----------------|-------|-----------|-------------|
| `MCP tool call: tool=… session=… key=…` | `mcp.tools_call` | INFO | `tool_name` (canonical `cc____…`), `session_id`, `api_key_name` | Every `tools/call` reaching the protocol server (OAuth sessions show the session, not a key) |
| Meta dispatch of `invoke_management_tool` / `list_management_tools` / `get_management_tool_schema` / `search_assistant_knowledge` | `assistant.meta.dispatch` | INFO (proposed) | `meta_tool`, `target_tool`, `count` | Progressive tool disclosure: the assistant context carries only the constant meta tools, never the ~36 management schemas |
| `MCP method <m> failed` | `mcp.method.failed` | ERROR | `method`, `error` | Unhandled exception inside a JSON-RPC method (also covers catalog build failures) |

`list_management_tools` returns the cheap catalog (name + one-line description + `requires_permission`); `get_management_tool_schema` returns one full schema on demand. A `404 Unknown management tool` from either is a registry/parity mismatch, not a permission problem.

### Catalog Listing Anomalies

**Log source**: `backend/logs/communication-hub.log` (`tools/list`) and `backend/logs/control-center.log` (MCP Hub REST listing)

| Signal | Proposed event | Level | Key fields | Meaning |
|--------|----------------|-------|-----------|---------|
| OAuth `tools/list` returns an empty array while `/resolve` reported `permitted>0` | `assistant.catalog.empty` | WARN | `sub`, `permitted_count` | Bridge filtering dropped every permitted name (registration vs canonical-name drift) |
| REST list returns exactly `limit` rows (default 50, hard cap 100) | `assistant.catalog.page_truncated` | INFO | `resource`, `limit`, `offset` | Normal pagination — the assistant must page with `offset`; a "missing record" report is usually this |
| `cc` server visible to an identity without `integration::control_center:read` | `assistant.catalog.cc_entity_leak` | WARN | `actor` | Visibility-gate regression on the protected entity |
| `404 Unknown or out-of-scope management tool` at dispatch | `assistant.catalog.unknown_tool` | WARN | `tool_name` | Model called a tool that was never in its catalog (stale schema/instruction drift) |

### Audit Attribution and Sensitive Data

Audit attribution is **database-backed, not log-derived**: every management action is attributed to the OAuth-authenticated user and recorded in `ToolCallRecord` (`tool_name`, `tool_input`, `tool_output`, `error`) plus `RuntimeToolCall`. Query the conversation/tool-call store for compliance review; logs are the operational signal only.

Sensitive-data exclusion (reinforces the existing logging conventions):

- Never log identity tokens, refresh tokens, JWT bodies, DB credentials, API keys, or decrypted MCP/provider credentials.
- Read handlers omit credential material and write handlers never echo it back into tool results; no new assistant log field may carry credential material.
- Log operational identifiers only: `tool_name`, `resource_type`, `action`, `sub`/`tenant_id`, `session_id`, `request_id`, `code`/`reason`.

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
