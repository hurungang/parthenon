# Logging — Integrations and API Keys

External and semi-external surfaces: the MCP demo app, Communication Hub API-key access (with its audit table), and third-party agent clients.

Hub: [logging.md](logging.md) · Operations index: [README.md](README.md)

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

## Third-Party Client Integration Log Events

All client invocations (success **and** failure) are recorded in the `AgentClientUsageLog` database table, keyed to the client; the credential value is never stored.

### Audit Table: `AgentClientUsageLog`

| Column | Description |
|--------|-------------|
| `agent_client_id` | Reference to the `AgentClient` row; enables per-client audit queries |
| `action` | `conversation_turn` or `submit_request` |
| `outcome` | `success` or the failure reason (`rate_limited`, `origin_denied`, `invalid_credential`, `revoked_credential`, `error`) |
| `response_ms` | Gateway response latency for the invocation |
| `ip_address` | Caller IP that submitted the request |
| `timestamp` | UTC timestamp of the invocation |

**Retention**: 90 days in the active database; archive to cold storage for longer-term compliance.

### Communication Hub — Edge Events

**Log source**: `backend/logs/communication-hub.log`

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `integration.client.auth.success` | INFO | `key_prefix`, `client_id`, `agent_type_id`, `origin` | Client credential resolved; origin allowlisted |
| `integration.client.auth.failed` | WARN | `key_prefix`, `reason` (`origin_denied`/`invalid_credential`/`revoked_credential`/`rate_limited`), `origin` | Edge-level rejection with masked credential prefix and reason |
| `integration.gateway.request` | INFO | `client_id`, `endpoint`, `outcome`, `response_ms` | `/integrate/*` request completed (all traffic OTEL-instrumented) |

### Control Center — Resolution & Lifecycle Events

**Log source**: `backend/logs/control-center.log`

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `client.created` | INFO | `client_id`, `key_type`, `agent_type_id`, `created_by` | New client issued |
| `client.credential_rotated` | INFO | `client_id`, `rotated_by` | Credential rotated; clear-text shown once |
| `client.status_changed` | INFO | `client_id`, `status` (`active`/`inactive`/`revoked`) | Client activated/deactivated/revoked |
| `client.deleted` | WARN | `client_id`, `deleted_by` | Client hard-deleted (usage logs cascade) |
| `client.validation` | DEBUG | `key_prefix`, `outcome`, `duration_ms` | Internal mTLS credential resolution for CH |

### Sensitive Data Exclusions

- Never log the full client credential, its SHA-256 hash, or any part beyond the prefix.
- The resolved agent identity token (and optional `secret`-client end-user token) is held CH-side in-memory only and is never logged.

### Where to Find Integration Logs

| Concern | Source | Access |
|---------|--------|--------|
| Edge rejections (origin/rate/credential) | Communication Hub | `backend/logs/communication-hub.log` — search for `integration.client` |
| Gateway request outcomes | Communication Hub | `backend/logs/communication-hub.log` — search for `integration.gateway` |
| Client management CRUD | Control Center | `backend/logs/control-center.log` — search for `client.created` / `client.credential_rotated` |
| Per-client usage audit trail | Database | Query `agent_client_usage_logs`, filter by `agent_client_id` or date range |
| Distributed trace correlation | All services | Use `trace_id` from any log line to jump to the full trace in Jaeger |
