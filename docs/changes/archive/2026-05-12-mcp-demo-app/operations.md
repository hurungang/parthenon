# Operations: MCP Demo App

## 1. Monitoring

### New Metrics

The demo app emits metrics via OpenTelemetry, consistent with all other Parthenon services.

| Metric | Type | Description | Alert Threshold |
|--------|------|-------------|----------------|
| `mcp_demo.startup.registration_success` | Gauge | 1 if Hub registration succeeded at startup, 0 if failed | Any non-1 value after container start |
| `mcp_demo.auth.token_refresh_failures_total` | Counter | Failed Keycloak client credentials grant attempts | Any sustained non-zero rate |
| `mcp_demo.auth.jwks_fetch_failures_total` | Counter | Failed Keycloak JWKS endpoint fetches | Any sustained non-zero rate |
| `mcp_demo.auth.jwt_validation_failures_total` | Counter | Incoming agent JWTs that failed signature/expiry/issuer check | Any sustained non-zero rate |
| `mcp_demo.tool.calls_total` | Counter | Total `helloWorld` tool invocations (label: `status=success|error`) | Error rate > 10% sustained for 5 min |
| `mcp_demo.http.request_duration` | Histogram | HTTP request latency for `/mcp` and `/health` endpoints (p99) | p99 > 5 s |

### Dashboards to Add

Add a **MCP Demo App** panel group to the existing **MCP Hub** Grafana dashboard:

- **Startup Registration Status** — `mcp_demo.startup.registration_success` as a status indicator
- **Tool Call Rate** — `mcp_demo.tool.calls_total` success and error rates as stacked bars
- **JWT Validation Failures** — `mcp_demo.auth.jwt_validation_failures_total` rate; alert annotation on non-zero
- **JWKS Fetch Failures** — `mcp_demo.auth.jwks_fetch_failures_total` rate
- **Token Refresh Failures** — `mcp_demo.auth.token_refresh_failures_total` rate

### Alerts to Create

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `MCPDemoRegistrationFailed` | `mcp_demo.startup.registration_success == 0` at startup | Critical | Check Hub connectivity and API key; see Hub registration runbook |
| `MCPDemoJWTValidationFailures` | `rate(mcp_demo.auth.jwt_validation_failures_total) > 0` for 5 min | Warning | Verify calling agent is using `ai_agents` realm tokens; check JWKS cache |
| `MCPDemoKeycloakTokenFailure` | `rate(mcp_demo.auth.token_refresh_failures_total) > 0` for 2 min | Critical | Verify Keycloak `ai_agents` realm is reachable; check client secret rotation |
| `MCPDemoHighToolErrorRate` | Tool call error rate > 10% for 5 min | Warning | Inspect tool invocation logs; correlate with JWT validation failures |

### Health Check Target

Add to production readiness checklists and uptime monitoring:

| Target | URL | Expected Response |
|--------|-----|-------------------|
| MCP Demo App | `http://mcp-demo-app:9000/health` | `{"status": "ok", "slug": "demo"}` with HTTP 200 |

---

## 2. Logging

All log entries are structured JSON and include `trace_id` and `span_id` for correlation with Jaeger traces.

**Log access:**
- Docker Compose: `docker compose logs mcp-demo-app`
- Loki: `{service="mcp-demo-app"}`

### Key Log Events

#### Startup Sequence

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `keycloak.token_grant.success` | INFO | `realm`, `client_id`, `expires_in` | Successful client credentials grant at startup |
| `keycloak.token_grant.failure` | ERROR | `realm`, `client_id`, `error`, `status_code` | Failed client credentials grant; container will not serve requests |
| `hub.registration.success` | INFO | `slug`, `server_id` | Demo app registered with Hub; `server_id` is the assigned Hub record ID |
| `hub.registration.conflict` | INFO | `slug`, `existing_server_id` | 409 returned by Hub; existing record looked up and reused (idempotent) |
| `hub.registration.failure` | ERROR | `slug`, `error`, `status_code` | Hub unreachable or rejected registration; tool calls will not be routed |
| `hub.sync.success` | INFO | `slug`, `tools_synced` | Tool manifest synced to Hub after registration |
| `hub.sync.failure` | ERROR | `slug`, `error` | Tool sync failed; Hub tool list may be stale |

#### Request Handling

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `mcp.tools_call.received` | INFO | `tool_name`, `agent_sub`, `trace_id` | Incoming `tools/call` request with valid JWT |
| `mcp.tools_call.completed` | INFO | `tool_name`, `agent_sub`, `duration_ms` | Tool handler returned successfully |
| `mcp.jwt_validation.failure` | WARN | `error`, `token_hint` (first 8 chars of JWT), `trace_id` | Bearer token failed validation; 401 returned to caller |
| `mcp.method_not_found` | WARN | `method`, `trace_id` | JSON-RPC method not implemented; -32601 returned |
| `keycloak.jwks.refreshed` | DEBUG | `keys_count`, `cache_age_s` | JWKS cache refreshed (every 10 min) |
| `keycloak.token.refreshed` | DEBUG | `expires_in`, `refreshed_at` | Access token refreshed (~30 s before expiry) |

---

## 3. Common Issues

### 3.1 Container Fails to Start — Keycloak Not Ready

**Symptom:** Container exits immediately with `keycloak.token_grant.failure`; `KEYCLOAK_URL` unreachable or returns non-2xx.

**Resolution:**
1. Confirm `keycloak` service is healthy: `docker compose ps keycloak`
2. Verify `KEYCLOAK_URL` resolves correctly from inside the container (Docker network alias, not `localhost`)
3. Confirm the `mcp-demo-app` client exists in the `ai_agents` realm with Client Credentials grant enabled
4. Confirm `KEYCLOAK_CLIENT_SECRET` matches the current client secret in Keycloak admin console

### 3.2 Container Fails to Start — Hub Registration Failure

**Symptom:** `hub.registration.failure` in startup logs; container may stay up but the `helloWorld` tool is not visible in the Hub.

**Resolution:**
1. Confirm `api` service is healthy: `docker compose ps api`
2. Verify `HUB_URL` is reachable from the container and includes the correct path prefix (e.g., `http://api:8000/api/v1`)
3. Confirm `HUB_API_KEY` is valid and has permission to create MCP servers
4. If a stale `demo` slug record exists in the Hub with a different configuration, delete it via the Hub admin API and restart the container

### 3.3 `helloWorld` Tool Calls Return 401

**Symptom:** Callers receive HTTP 401; `mcp.jwt_validation.failure` logged with `error` field.

**Common causes and checks:**
- **Wrong realm** — JWT was issued by the `users` realm, not `ai_agents`. Verify the calling agent is using a token from the `ai_agents` realm.
- **Expired token** — JWT `exp` claim is in the past. Calling agent must refresh its token before invoking the tool.
- **Wrong issuer** — `iss` claim does not match `KEYCLOAK_URL/realms/KEYCLOAK_REALM`. Confirm both values are consistent between Keycloak and the demo app's environment variables.
- **Stale JWKS cache** — If a Keycloak key rotation occurred in the last 10 minutes, the JWKS cache may hold an outdated key set. Restart the container to force an immediate JWKS refresh.

### 3.4 `helloWorld` Tool Not Visible in MCP Hub

**Symptom:** Hub's tool list does not include `helloWorld` under the `demo` slug.

**Resolution:**
1. Check `hub.sync.failure` in startup logs; if present, the tool manifest was not delivered to the Hub.
2. Re-trigger tool sync by restarting the container (sync runs on every startup).
3. If sync continues to fail, verify the Hub `/api/v1/mcp/servers/{id}/sync` endpoint is reachable and `HUB_API_KEY` is authorised.

### 3.5 `helloWorld` Response Contains Wrong or Missing `agent_sub`

**Symptom:** Tool response includes an unexpected or empty `agent_sub`.

**Resolution:**
- Confirm the calling agent is presenting its own JWT in the `Authorization: Bearer` header, not a delegated or service-to-service token.
- The `sub` claim in the response always reflects the identity in the forwarded JWT; ensure the JWT belongs to the intended agent identity in the `ai_agents` realm.

---

## 4. Master Operations Update Instructions

Apply the following changes to `docs/master/operations/` after this change is merged.

### `docs/master/operations/README.md`

- **Dashboards table** — Add `MCP Demo App` row: "Tool call rate, JWT validation failures, startup registration status, JWKS/token refresh failures."
- **Production Health Check Targets table** — Add `MCP Demo App` row pointing to `http://mcp-demo-app:9000/health` with expected response `{"status": "ok", "slug": "demo"}`.

### `docs/master/operations/monitoring.md`

- Add a **MCP Demo App** section listing the six new metrics, their alert thresholds, and a reference to the MCP Hub Grafana dashboard panel group.

### `docs/master/operations/logging.md`

- Add a **MCP Demo App** section referencing the `{service="mcp-demo-app"}` Loki query and documenting the key log event fields from Section 2 above.

### New Runbook (if Hub registration failures become recurring)

- If Hub registration failures prove operationally recurring, create `docs/master/operations/runbooks/mcp-demo-registration-failure.md` following the pattern established in `runbooks/oidc-token-failure.md`.
