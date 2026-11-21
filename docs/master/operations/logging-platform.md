# Logging — Platform and Per-Component Events

Per-component log-event catalog, plus the platform-level startup, setup, and telemetry events emitted before and around normal request handling.

Hub: [logging.md](logging.md) · Operations index: [README.md](README.md)

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
| **Third-Party Client Auth (Communication Hub)** | Edge-level client rejections — origin, rate limit, invalid/revoked/expired credential (`integration.client.*` lines with masked credential prefix and reason) |
| **Integration Gateway (Communication Hub)** | `/integrate/*` request routing — conversation sessions, typed submit, session polling, SDK serving (`integration.gateway.*` lines) |
| **Client Management (Control Center)** | Client lifecycle events (`client.created`, `client.credential_rotated`, `client.status_changed`, `client.deleted`); internal credential resolution (`client.validation`) |
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
