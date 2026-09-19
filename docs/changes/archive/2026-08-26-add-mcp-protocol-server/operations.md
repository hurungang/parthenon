# Operations: MCP Protocol Server

> Runtime operation of the Communication Hub's standard MCP protocol endpoint (SSE + Streamable HTTP), authenticated by the existing API keys. No database schema change; all data access still routes through Control Center.

## 1. Monitoring

### New Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `mcp.connections_active` | Gauge | `transport` | Currently open MCP sessions/connections, by transport (`sse`, `streamable_http`) |
| `mcp.connections_total` | Counter | `transport`, `outcome` | Connection attempts/opens by outcome (`opened`, `closed`, `rejected`) |
| `mcp.initialize_total` | Counter | `outcome` | MCP `initialize` handshakes by outcome (`success`, `error`) |
| `mcp.tools_list_total` | Counter | `outcome` | `tools/list` calls by outcome (`success`, `error`) |
| `mcp.tools_call_total` | Counter | `tool_name`, `outcome` | `tools/call` invocations by canonical tool name and outcome (`success`, `permission_denied`, `error`) |
| `mcp.auth_failure_total` | Counter | `failure_reason`, `key_prefix` | MCP handshake authentication failures by reason (`invalid_key`, `revoked_key`, `control_center_unavailable`) |
| `mcp.tool_count` | Histogram | — | Number of tools returned per `tools/list` response |
| `mcp.session_ttl_seconds` | Gauge | — | Age/remaining TTL of the oldest idle session (drives idle-cleanup visibility) |
| `mcp.call_latency_seconds` | Histogram | `route` | `tools/call` end-to-end latency by route (`system`, `proxied`) |

### Dashboards to Create

Add a **MCP Protocol** panel group within the existing **MCP Hub** dashboard:

- **Active MCP Connections** — `mcp.connections_active` by `transport`; line chart.
- **Handshake / List / Call Rate** — `mcp.initialize_total`, `mcp.tools_list_total`, `mcp.tools_call_total` rates overlaid.
- **Auth Failure Breakdown** — `mcp.auth_failure_total` by `failure_reason`; stacked bar.
- **Tool Call Outcome** — `mcp.tools_call_total` by `outcome`; success vs `permission_denied` vs `error`.
- **Tools Listed per Session** — `mcp.tool_count` histogram p50/p99.
- **Call Latency p99** — `mcp.call_latency_seconds` p99 split by `route`.

### Alerts to Configure

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `McpAuthFailureSpike` | `rate(mcp.auth_failure_total) > 10/min` for 5 min | Warning | Review `failure_reason` breakdown; check key validity and CH→CC connectivity |
| `McpAuthFailureSustained` | `rate(mcp.auth_failure_total) > 50/min` for 2 min | Critical | Possible brute-force; consider IP-level rate limiting |
| `McpPermissionDenialSpike` | `rate(mcp.tools_call_total{outcome="permission_denied"}) > 5/min` for 5 min | Warning | Tools requested outside bound role; review agent/role config |
| `McpCallLatencyHigh` | `mcp.call_latency_seconds` p99 > 2 s for 5 min | Warning | Check CC DB + external MCP server health |
| `McpEmptyToolList` | `mcp.tool_count` p50 = 0 sustained for 10 min | Warning | Role has no permitted tools; verify role assignments |
| `McpConnectionDrop` | `mcp.connections_active` drops to 0 while clients report connected | Warning | Check session TTL/idle cleanup and transport stability |

---

## 2. Logging

### Structured Logs

**Log source**: `backend/logs/communication-hub.log` (CH). Reuses the `api_key.*` log event conventions from `docs/changes/archive/2026-07-31-api-key-mcp-hub/operations.md`.

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `api_key.auth.success` | INFO | `key_name`, `identity_id`, `role_id`, `transport` | API key validated for an MCP session; `transport` is `sse` or `streamable_http` |
| `api_key.auth.failed` | WARN | `key_prefix`, `failure_reason` | MCP handshake rejected (`invalid_key`, `revoked`, `expired`, or CC-unavailable) |
| `mcp.initialize` | INFO | `key_name`, `protocol_version`, `transport` | MCP `initialize` completed |
| `mcp.tools_list` | INFO | `key_name`, `tool_count` | `tools/list` served; `tool_count` is the number of permitted tools returned |
| `mcp.tools_call` | INFO | `key_name`, `tool_name`, `route`, `outcome` | `tools/call` dispatched; `route` is `system` or `proxied`, `outcome` is `success` / `permission_denied` / `error` |
| `mcp.session.expired` | DEBUG | `session_id`, `reason` | Session cleaned up by TTL/idle reaper (`idle`, `ttl`) |

**Required fields for all MCP log events:**

| Field | Requirement |
|-------|-------------|
| `key_name` / `key_prefix` | Key name or first 8 characters only — **never log the full key value or hash** |
| `trace_id` | OTEL trace ID for cross-service correlation |
| `timestamp` | ISO 8601 UTC with millisecond precision |

**Sensitive data exclusions:**
- Never log the full API key value, key hash, or the resolved identity token.
- Tool-call arguments/results may contain sensitive business data — log only the canonical `tool_name` and `outcome`, not the payloads.

### Where to Find Logs

| Concern | Source | Access |
|---------|--------|--------|
| MCP auth success/failure | Communication Hub | `backend/logs/communication-hub.log` — search `api_key.auth` |
| MCP handshake / list / call events | Communication Hub | `backend/logs/communication-hub.log` — search `mcp.initialize`, `mcp.tools_list`, `mcp.tools_call` |
| Session TTL / idle cleanup | Communication Hub | `backend/logs/communication-hub.log` — search `mcp.session.expired` |
| API-key validation internals | Control Center | `backend/logs/control-center.log` — search `api_key.validation` |
| Proxied tool-call errors | Control Center | `backend/logs/control-center.log` — search `mcp_proxy` |
| Distributed trace correlation | All services | Use `trace_id` from any log line to jump to the full trace in Jaeger |

---

## 3. Common Issues

### 3.1 External MCP Client Cannot Connect

**Symptoms**: Client gets a connection error or immediate rejection when pointing at the CH MCP endpoint.

**Likely Causes**:
- `CH_MCP_PROTOCOL_SERVER_ENABLED` is `false` — the endpoint is not registered (404/connection refused).
- `CH_API_KEY_AUTH_ENABLED` is `false` — the API-key middleware rejects the request.
- Wrong endpoint URL/port — must target the Communication Hub (port 8002), not Control Center or Agent Runtime.
- Client sends the key incorrectly (missing `Bearer` prefix, or `?apiKey=` not URL-encoded).

**Resolution**:
1. Check CH startup logs for the flag values (`CH_MCP_PROTOCOL_SERVER_ENABLED`, `CH_API_KEY_AUTH_ENABLED`).
2. Confirm the endpoint path (`/mcp` or `/mcp/sse`) matches the transport the client uses.
3. Search `backend/logs/communication-hub.log` for `api_key.auth.failed`; if no auth entries appear, the request isn't reaching CH — check network/firewall.
4. Verify the client sends the full key value (`phn_sk_…`), not just a prefix.

### 3.2 `tools/list` Returns Empty or Missing Expected Tools

**Symptoms**: Handshake succeeds but the client sees zero or fewer tools than expected.

**Likely Causes**:
- The role bound to the API key has no permitted tools/skills.
- Permission resolution returned a filtered set (expected behavior) — the client only sees permitted tools.
- The tool catalog was built from a stale session context created before a role/skill change.

**Resolution**:
1. Verify the bound role's assigned skills/tools in the Web UI.
2. Check `mcp.tools_list` log events for `tool_count` to see what was actually resolved.
3. Reconnect to establish a fresh session (permission changes apply on next session, not mid-session).
4. Check `backend/logs/control-center.log` for permission-resolution errors.

### 3.3 `tools/call` Returns Permission Denied

**Symptoms**: A tool appears callable but the call returns a permission-denied error.

**Likely Causes**:
- The tool is not in the bound role's permission set (session context drift or a stale catalog).
- The client invoked a canonical tool name that differs from the permitted name.

**Resolution**:
1. Confirm the tool is actually permitted to the bound role (Web UI role management).
2. Compare the invoked canonical name with the exact name from `tools/list`.
3. Check `mcp.tools_call` events with `outcome=permission_denied` to confirm the denied tool name.
4. Reconnect to refresh the session permission context.

### 3.4 Tool Call Fails Because the External MCP Server Is Down

**Symptoms**: `tools/call` for a **proxied** MCP tool returns an error; system tools still work.

**Likely Causes**:
- The registered external MCP server is unreachable or down.
- The MCP session/credentials on the external server have expired or been revoked.

**Resolution**:
1. Check the external MCP server's health directly.
2. Check `backend/logs/control-center.log` for `mcp_proxy` errors.
3. Re-sync/reconnect the MCP server session in the Web UI (MCP Hub management).
4. Verify the bound identity token can be refreshed (see `identity.token_refresh_failed` in `control-center.log`); re-authorize the identity if needed.

### 3.5 Session Times Out Mid-Conversation

**Symptoms**: A long-lived client's calls start failing after a period of inactivity.

**Likely Causes**:
- The MCP session manager's TTL/idle cleanup expired the session.

**Resolution**:
1. Confirm `mcp.session.expired` entries in `communication-hub.log`.
2. Reconnect from the client to establish a new session.
3. If idle timeouts are too aggressive for legitimate clients, review the session TTL/idle configuration (config-owned, not a schema change).

### 3.6 Authentication Fails but the Key Is Valid

**Symptoms**: A known-good API key is rejected with a CC-unavailable or validation error.

**Likely Causes**:
- Control Center is unreachable from CH (certificate bootstrap failed or CC is down).
- `API_KEY_HASH_SECRET` was rotated, invalidating all previously issued keys.

**Resolution**:
1. Check CH startup logs for certificate-bootstrap failures; run `parthenon.ps1 restart -Services communication-hub -Force` to rebootstrap certs.
2. Confirm CC `/health` is reachable from CH.
3. If `API_KEY_HASH_SECRET` was rotated, reissue the affected API keys (existing keys are invalidated).

---

## 4. Master Operations Update Instructions

After this change is implemented and verified, update `docs/master/operations/`:

### `docs/master/operations/monitoring.md`

- Add the new metrics from **Section 1** to the **Key Metrics by Component** table, grouped under **MCP Protocol** (or under the existing MCP Hub group).
- Add the **MCP Protocol** dashboard panel group description to the **Dashboards** section.
- Add the six MCP alerts to the **Alerts to Configure** section.

### `docs/master/operations/logging.md`

- Add the MCP log events table (and the `api_key.auth` transport extension) to the **Per-Component Log Events** section under Communication Hub.
- Add the MCP entries to the **Where to Find Logs** source reference.

### `docs/master/operations/README.md`

- Add a row to the **Dashboards** table for the MCP Protocol panel group.
- Add a row to the **Runbooks** table for the new runbook (below).

### `docs/master/operations/runbooks/` — New File

Create `docs/master/operations/runbooks/mcp-protocol-server.md`:

- **Trigger symptoms**: Client connect/handshake failures; empty `tools/list`; `tools/call` permission denials; proxied tool-call failures; `McpAuthFailureSpike` / `McpPermissionDenialSpike` alerts firing.
- **Content**: Merge and adapt the six common-issue resolution procedures from **Section 3** into a single runbook, following the existing runbook format (Symptoms / Likely Causes / Resolution).
- **Reference**: Link this runbook from the **Runbooks** table in `README.md`.
