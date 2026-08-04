# Operations — API Key MCP Hub Access

## 1. Monitoring

### New Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `api_key.auth_total` | Counter | `action`, `outcome`, `key_prefix` | Total API key authentication attempts by action type (`validate`, `load_skills`, `tool_call`) and outcome (`success`, `failure`) |
| `api_key.auth_failure_total` | Counter | `failure_reason`, `key_prefix` | Authentication failures by reason (`invalid_key`, `revoked_key`, `unknown`) |
| `api_key.revoked_key_attempt_total` | Counter | `key_prefix` | Authentication attempts using a revoked key — separate counter to detect attack patterns |
| `api_key.auth_latency_seconds` | Histogram | `action` | End-to-end latency for API key validation calls (CH → CC → DB round-trip) |
| `api_key.load_skills_total` | Counter | `sync_mode` | `load_skills` calls by sync mode (`full` when no `since` parameter, `incremental` when `since` is provided) |
| `api_key.load_skills_skill_count` | Histogram | — | Number of skills returned per `load_skills` response; tracks response size |
| `api_key.tool_call_total` | Counter | `outcome`, `tool_name` | Tool calls made via API key auth, by outcome (`success`, `permission_denied`, `error`) |
| `api_key.tool_call_auth_method` | Gauge (always 1 when sampling) | `method` | Ratio of tool calls by auth method (`api_key` vs `certificate`); used to derive API key vs cert volume |

### Dashboards to Create

#### API Key Access Dashboard

Add as a new panel group within the existing **MCP Hub** dashboard, or as a standalone dashboard if panel count exceeds practical limits. Panels:

- **API Key Auth Rate** — `api_key.auth_total` rate split by `action` and `outcome`; success (green) and failure (red) stacked area.
- **Auth Failure Breakdown** — `api_key.auth_failure_total` by `failure_reason` (invalid_key, revoked_key, unknown); pie or stacked bar.
- **Revoked Key Attempts** — `api_key.revoked_key_attempt_total` rate as a line chart; any sustained non-zero rate is a security concern.
- **load_skills Call Rate** — `api_key.load_skills_total` rate split by `sync_mode`; shows full sync vs incremental sync ratio.
- **load_skills Response Size** — `api_key.load_skills_skill_count` histogram; p50/p99 to track response payload growth.
- **Tool Call Volume: API Key vs Certificate** — Ratio derived from `api_key.tool_call_auth_method`; shows external agent usage relative to internal agents.
- **Auth Latency p99** — `api_key.auth_latency_seconds` p99 time series; rising latency indicates CC or DB pressure.

### Alerts to Configure

| Alert Name | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `ApiKeyAuthFailureSpike` | `rate(api_key.auth_failure_total) > 10/min` for 5 min | Warning | Check key validity and CH → CC connectivity; review `failure_reason` breakdown |
| `ApiKeyAuthFailureSustained` | `rate(api_key.auth_failure_total) > 50/min` for 2 min | Critical | Possible brute-force attack; consider temporary IP-level rate limiting |
| `RevokedKeyAttemptDetected` | `rate(api_key.revoked_key_attempt_total) > 0` sustained for 5 min | Warning | Investigate source IP and key prefix; may indicate compromised key or misconfigured agent |
| `ApiKeyAuthLatencyHigh` | `api_key.auth_latency_seconds` p99 > 2 s for 5 min | Warning | Check CC database query performance; verify `api_keys` table indexes are in place |
| `ApiKeyLoadSkillsEmpty` | `api_key.load_skills_skill_count` p50 = 0 sustained for 10 min | Warning | Load skills returning empty for most callers; verify role-to-skill assignments |
| `ApiKeyPermissionDenialSpike` | `rate(api_key.tool_call_total{outcome="permission_denied"}) > 5/min` for 5 min | Warning | Tools requested outside bound role permissions; review agent configuration |

---

## 2. Logging

### Structured Logs

#### Communication Hub — API Key Auth Events

**Log source**: `backend/logs/communication-hub.log`

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `api_key.auth.success` | INFO | `key_prefix`, `identity_id`, `role_id`, `ip_address`, `action` | API key validated successfully; `action` is one of `validate`, `load_skills`, `tool_call` |
| `api_key.auth.failed` | WARN | `key_prefix`, `failure_reason`, `ip_address`, `action` | Authentication rejected; `failure_reason` is `invalid_key`, `revoked`, or `expired` |
| `api_key.load_skills` | INFO | `key_prefix`, `skill_count`, `sync_mode`, `since` | `load_skills` completed; `sync_mode` is `full` or `incremental` |
| `api_key.tool_call` | INFO | `key_prefix`, `tool_name`, `outcome` | Tool call proxied via API key auth; `outcome` is `success` or `permission_denied` |

**Required fields for all API key log events:**

| Field | Requirement |
|-------|-------------|
| `key_prefix` | First 8 characters of the key (e.g. `phn_sk_a1b2c3`); never log the full key value |
| `ip_address` | Client IP address that submitted the key |
| `action` | Operation type: `validate`, `load_skills`, or `tool_call` |
| `success` | Boolean outcome of the operation |
| `trace_id` | OTEL trace ID for cross-service correlation |
| `timestamp` | ISO 8601 UTC with millisecond precision |

**Sensitive data exclusions:**
- Never log the full API key value, key hash, or any part of the key beyond the 8-character prefix.
- Never log the resolved identity token — CH holds it internally and it must never appear in logs.

#### Control Center — API Key Management Events

**Log source**: `backend/logs/control-center.log`

| Event | Level | Key Fields | When Logged |
|-------|-------|-----------|-------------|
| `api_key.created` | INFO | `key_id`, `key_prefix`, `identity_id`, `role_id`, `created_by` | New API key issued by Platform Administrator |
| `api_key.revoked` | WARN | `key_id`, `key_prefix`, `revoked_by`, `reason` | API key manually revoked |
| `api_key.validation` | DEBUG | `key_prefix`, `outcome`, `duration_ms` | Internal key validation lookup against CC database; `outcome` is `valid`, `invalid`, or `revoked` |

### Structured Audit Data (`ApiKeyUsageLog` Table)

The `ApiKeyUsageLog` database table provides an immutable, append-only audit trail for every API key operation. It is the authoritative source for compliance reporting and long-term security analysis.

| Column | Description |
|--------|-------------|
| `api_key_id` | Reference to the `AgentApiKey` row; enables per-key audit queries |
| `action` | `validate` (authentication), `load_skills` (skill discovery), or `tool_call` (individual tool invocation) |
| `tool_name` | The qualified tool name for `tool_call` actions; `NULL` otherwise |
| `ip_address` | Client IP that submitted the request |
| `timestamp` | UTC timestamp of the operation |
| `success` | `true` if the operation completed successfully; `false` for auth failures or permission denials |

**Usage log retention**: 90 days in the active database; archive to cold storage for longer-term compliance needs.

### Where to Find Logs

| Concern | Source | Access |
|---------|--------|--------|
| API key authentication decisions | Communication Hub | `backend/logs/communication-hub.log` — search for `api_key.auth` |
| Key management CRUD operations | Control Center | `backend/logs/control-center.log` — search for `api_key.created` or `api_key.revoked` |
| Per-key usage audit trail | Database | Query `api_key_usage_logs` table, filter by `api_key_id` or date range |
| Skill resolution failures | Communication Hub / Control Center | `backend/logs/communication-hub.log` for `api_key.load_skills` errors; `backend/logs/control-center.log` for permission resolution errors |
| Identity token refresh failures | Control Center | `backend/logs/control-center.log` — search for `identity.token_refresh_failed` |
| Distributed trace correlation | All services | Use `trace_id` from any log line to jump to the full trace in Jaeger |

---

## 3. Common Issues

### 3.1 Key Created But External Agent Cannot Connect

**Symptoms**: Platform Administrator creates an API key successfully, but the external agent receives authentication errors or a connection refused response.

**Likely Causes**:

- Communication Hub is not running or not reachable at the configured MCP endpoint URL.
- External agent is sending the key in the wrong format — must use `Authorization: Bearer <api_key>` header or `?apiKey=<api_key>` query parameter.
- Network firewall or reverse proxy blocks the external agent's IP from reaching the Communication Hub (port 8002).
- The Communication Hub has not been restarted after API key feature deployment; the API key auth middleware has not been loaded.

**Resolution**:

1. Verify the Communication Hub is running and reachable: check `backend/logs/communication-hub.log` for startup confirmation.
2. Confirm the external agent is using the correct endpoint URL and port (the MCP endpoint exposed by the Communication Hub, not the Control Center or Agent Runtime).
3. Test connectivity from the external agent's network using a basic HTTP request to the Communication Hub's health endpoint (if exposed).
4. Verify the key format: the agent must send the full key value (e.g. `phn_sk_a1b2c3d4e5f6...`) — not just the prefix.
5. Check `backend/logs/communication-hub.log` for `api_key.auth.failed` entries with the key's prefix. If no entries appear, the request is not reaching CH at all — focus on network/routing.
6. If CH is running and logs show no auth attempts, ensure the API key feature is enabled on CH. Check that the API key validator middleware is registered in the CH startup sequence.

### 3.2 load_skills Returns Empty or Missing Expected Skills

**Symptoms**: External agent calls `load_skills` successfully (authenticated) but receives zero skills or fewer skills than expected.

**Likely Causes**:

- The role bound to the API key has no skills assigned. API keys inherit the full permission set of the bound role — if the role has no skills, `load_skills` returns empty.
- The `since` parameter is set to a timestamp that matches or exceeds the `updated_at` of all accessible skills, causing the incremental sync to return nothing. Verify that skills have been updated since the provided timestamp.
- The role's skills exist but are not mapped correctly in the `agent_role_skills` join table.
- The Communication Hub is resolving permissions using a stale cache that predates the skill assignment.

**Resolution**:

1. Verify that the bound role has skills assigned: navigate to the role management page in the Web UI, select the role, and confirm skills are listed.
2. If using the `since` parameter, check the `updated_at` values of the assigned skills and confirm they are newer than the provided timestamp. Call `load_skills` without the `since` parameter to retrieve all skills as a baseline.
3. Verify the `agent_role_skills` join table contains the expected rows for the bound role. If the role was recently modified, check whether a cache invalidation occurred.
4. Check `backend/logs/communication-hub.log` for `api_key.load_skills` events — the `skill_count` field confirms how many skills were resolved.
5. Check `backend/logs/control-center.log` for permission resolution errors related to the bound role.
6. If skills were recently assigned to the role, the Hub's permission cache may be stale. Wait for the cache TTL to expire (default: check configuration), or restart the Communication Hub to force a fresh cache.

### 3.3 Revoked Key Still Works Briefly After Revocation

**Symptoms**: Platform Administrator revokes an API key, but the external agent continues to make successful tool calls for a short period afterward (typically seconds to minutes).

**Likely Causes**:

- The Communication Hub caches API key validation results for the duration of a request or session. If the key was validated before revocation during a long-running session, subsequent calls within that session may not re-validate.
- The `status` column in `api_keys` was updated to `revoked` in the database, but a transient database replication lag delays the change from being visible to a different database reader.
- The Control Center's key validation endpoint caches the previous "valid" result and has not yet expired the cache entry.

**Resolution**:

1. Confirm the key status is `revoked` in the database: query `SELECT status FROM agent_api_keys WHERE key_prefix = '<prefix>'`. If the database shows `revoked`, the change has been committed.
2. Check the cache TTL for API key validation in the Communication Hub configuration. The revocation takes effect no later than the cache entry expiry — this is expected behavior, not a bug.
3. The authenticating session may have been established before revocation. Disconnect the session from the external agent side, then reconnect — the new connection will trigger a fresh validation.
4. If the key continues to work beyond the expected cache TTL, check for read-replica lag in the database layer. Query the primary database directly to confirm the revocation was written.
5. To force immediate invalidation, restart the Communication Hub process. This clears all in-memory caches and forces fresh validation on the next request.

**Design note**: Revocation is effective on the *next authentication attempt* after the cache entry expires. It is not an instant session-kill. For immediate effect, combine revocation with a CH restart or cache flush.

### 3.4 Identity Token Refresh Failure Causes MCP Proxy Errors

**Symptoms**: External agent authenticates successfully but tool calls to MCP servers fail with authentication errors. `backend/logs/control-center.log` contains `identity.token_refresh_failed` errors for the identity bound to the API key. The Communication Hub cannot obtain a valid identity token to proxy the MCP request.

**Likely Causes**:

- The agent identity bound to the API key has a `token_status` of `refresh_failed`, meaning its OIDC refresh token has expired or been invalidated.
- The OIDC provider (Keycloak or external IdP) is unreachable from the Control Center, preventing token refresh.
- The agent identity's client credentials (client ID / client secret) have been rotated or revoked in the identity provider without updating the Control Center.

**Resolution**:

1. Check the `token_status` of the bound agent identity in Control Center: `SELECT token_status FROM agent_identities WHERE id = '<identity_id>'`. If `refresh_failed`, proceed to re-authorization.
2. Verify the OIDC provider is reachable from the Control Center host. Test network connectivity and DNS resolution to the identity provider's token endpoint.
3. Re-authorize the agent identity: Admin UI → Agent Identities → select the affected identity → Re-authorize. This initiates a fresh OAuth flow and stores a new refresh token.
4. After re-authorization, confirm `token_status` resets to `active` in the database and `identity.token_acquired` appears in `backend/logs/control-center.log`.
5. Test a tool call from the external agent to confirm the proxy layer now receives a valid identity token.

**Prevention**: Monitor the `AgentIdentityRefreshFailed` alert proactively. Schedule periodic audits of `agent_identities.token_status` to catch refresh failures before they impact external agent operations.

---

## 4. Master Operations Update Instructions

After this change is implemented and verified, update the following files in `docs/master/operations/`:

### `docs/master/operations/monitoring.md`

- Add all new metrics from **Section 1 (Monitoring)** to the **Key Metrics by Component** table. Use the component name **API Key Access** or group them under **MCP Hub**.
- Add the **API Key Access Dashboard** panel group description to the **Dashboards to Create** section, either as a new panel group within the MCP Hub dashboard entry or as a standalone entry.
- Add the API key alerts table to the **Alerts to Configure** section.

### `docs/master/operations/logging.md`

- Add the **API Key Auth Events** (Communication Hub) and **API Key Management Events** (Control Center) tables to the **Per-Component Log Events** section.
- Add the `ApiKeyUsageLog` table reference with its columns to a new **Audit Tables** subsection (or under an existing audit section if one exists).
- Add the **Where to Find Logs** table entry for API key concerns to the log source reference.

### `docs/master/operations/README.md`

- Add a row to the **Dashboards** table for the **API Key Access** dashboard.
- Add a row to the **Runbooks** table for the new runbook (see below).

### `docs/master/operations/runbooks/` — New File

Create `docs/master/operations/runbooks/api-key-auth.md`:

- **Trigger symptoms**: External agents receive authentication errors after key provisioning; `api_key.auth_failed` WARN entries in Communication Hub logs; `ApiKeyAuthFailureSpike` alert firing.
- **Content**: Merge and adapt the four common-issue resolution procedures from **Section 3** into a single runbook, following the existing runbook format (Symptoms, Likely Causes, Resolution steps for each failure mode).
- **Reference**: Link this runbook from the **Runbooks** table in `README.md`.
