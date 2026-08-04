# Runbook: API Key Authentication Failures

## Symptoms

- External agent receives authentication errors or connection refused after API key provisioning
- `api_key.auth_failed` WARN entries in `backend/logs/communication-hub.log`
- `ApiKeyAuthFailureSpike` or `ApiKeyAuthFailureSustained` alert firing
- `load_skills` returns empty or fewer skills than expected
- Revoked key continues to work for a short period after revocation
- Tool calls fail with proxy errors; `identity.token_refresh_failed` in `backend/logs/control-center.log`

---

## Resolution Steps

### 1. Key Created But External Agent Cannot Connect

**Log indicator:** No `api_key.auth` entries in `communication-hub.log` (request not reaching CH), or `api_key.auth.failed` with `failure_reason=invalid_key`

1. Verify Communication Hub is running and reachable. Check `backend/logs/communication-hub.log` for startup confirmation. Confirm the external agent is targeting the CH MCP endpoint (port 8002), not the Control Center or Agent Runtime.

2. Confirm the agent's request format: must use `Authorization: Bearer <api_key>` header or `?apiKey=<api_key>` query parameter with the full key value (e.g. `phn_sk_a1b2c3d4e5f6...`) — not just the prefix.

3. Test basic connectivity from the external agent's network to the CH health endpoint. If no auth attempts appear in CH logs at all, focus on network/firewall/routing.

4. Verify the API key auth middleware is loaded in the CH startup sequence. If CH was deployed before the API key feature, a restart may be needed.

5. Check `backend/logs/communication-hub.log` for `api_key.auth.failed` with the key's prefix. If `failure_reason=invalid_key`, confirm the key was not mistyped or truncated when shared with the external agent.

### 2. load_skills Returns Empty or Missing Skills

**Log indicator:** `api_key.load_skills` events with `skill_count=0`

1. Verify the role bound to the API key has skills assigned. Navigate to the role management page in the Web UI, select the role, and confirm skills are listed.

2. If using the `since` parameter for incremental sync, verify assigned skills have `updated_at` values newer than the timestamp. Call `load_skills` without `since` to retrieve all skills as a baseline.

3. Check the `agent_role_skills` join table contains expected rows for the bound role. If the role was recently modified, check whether cache invalidation occurred.

4. Review `backend/logs/communication-hub.log` for `api_key.load_skills` events — the `skill_count` field confirms how many skills were resolved. Also check `backend/logs/control-center.log` for permission resolution errors.

5. If skills were recently assigned, the Hub's permission cache may be stale. Wait for the cache TTL to expire, or restart the Communication Hub to force a fresh cache load.

### 3. Revoked Key Still Works Briefly After Revocation

**Log indicator:** `api_key.auth.success` entries for a key after it was revoked in the UI/API

1. Confirm the key status is `revoked` in the database: `SELECT status FROM agent_api_keys WHERE key_prefix = '<prefix>'`. If the database shows `revoked`, the change is committed.

2. Check the API key validation cache TTL in the Communication Hub configuration. The revocation takes effect no later than the cache entry expiry — this is expected behavior, not a bug. The cache TTL bounds the maximum window between revocation and enforcement.

3. The authenticating session may have been established before revocation. Disconnect the session from the external agent side, then reconnect — the new connection triggers a fresh validation.

4. If the key continues to work beyond the expected cache TTL, check for read-replica lag in the database layer. Query the primary database directly to confirm the revocation was written.

5. To force immediate invalidation, restart the Communication Hub process. This clears all in-memory caches and forces fresh validation on the next request.

**Design note:** Revocation is effective on the *next authentication attempt* after the cache entry expires. It is not an instant session-kill. For immediate effect, combine revocation with a CH restart or cache flush.

### 4. Identity Token Refresh Failure Causes MCP Proxy Errors

**Log indicator:** `identity.token_refresh_failed` in `backend/logs/control-center.log` for the identity bound to the API key; tool calls fail with proxy authentication errors

1. Check the `token_status` of the bound agent identity: `SELECT token_status FROM agent_identities WHERE id = '<identity_id>'`. If `refresh_failed`, the OIDC refresh token has expired or been invalidated.

2. Verify the OIDC provider (Keycloak or external IdP) is reachable from the Control Center host. Test network connectivity and DNS resolution to the identity provider's token endpoint.

3. Re-authorize the agent identity: Admin UI → Agent Identities → select the affected identity → Re-authorize. This initiates a fresh OAuth flow and stores a new refresh token.

4. After re-authorization, confirm `token_status` resets to `active` in the database and `identity.token_acquired` appears in `backend/logs/control-center.log`.

5. Test a tool call from the external agent to confirm the proxy layer now receives a valid identity token.

**Prevention:** Monitor the `AgentIdentityRefreshFailed` alert proactively. Schedule periodic audits of `agent_identities.token_status` to catch refresh failures before they impact external agent operations.

---

## Notes

- Never log or expose the full API key value, key hash, or resolved identity tokens. Only the 8-character `key_prefix` should appear in logs and diagnostics.
- When investigating auth failures, correlate `trace_id` across Communication Hub and Control Center logs to reconstruct the full request path.
- Use `ApiKeyUsageLog` table queries for per-key audit trails and compliance reporting. Retention is 90 days in the active database.
