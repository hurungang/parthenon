# Runbook: Passthrough Session Failures

## Symptoms

- MCP tool calls fail with 401 Unauthorized from the upstream MCP server
- Backend logs contain `No agent JWT available for passthrough session`
- Agent identity dropdown is empty in the session creation form
- Sessions fail to create with `Credentials not allowed for passthrough sessions`
- Passthrough JWT validation failure alert is firing (`PassthroughJWTValidationFailureSpike`)

---

## Resolution Steps

### 1. JWT Not Forwarded to MCP Server

**Log indicator:** `No agent JWT available for passthrough session` or `Using agent JWT for passthrough session` absent from proxy logs

1. Verify that the auth middleware is extracting the JWT. Look for `Extracted raw token for user: <user_id>` in the backend logs. If absent, the auth middleware is not setting `request.state.raw_token`.
2. Confirm the MCP proxy `_build_auth_headers` method is selecting the passthrough path. Set backend log level to DEBUG for `app.core.mcp_proxy` to trace the auth header construction.
3. Verify the frontend is sending an `agent_subject` in the tool call payload. An empty or missing `agent_subject` causes the proxy to skip JWT forwarding.
4. Check Keycloak JWKS endpoint reachability from the backend container. A JWKS fetch failure will prevent JWT validation and forwarding.

---

### 2. Passthrough Session Creation Fails

**Log indicator:** HTTP 400 on session creation; error message `Credentials not allowed for passthrough sessions`

1. Verify the session creation request body does **not** include an `encrypted_credentials` field. Passthrough sessions must be created with only `server_id`, `name`, and `auth_type = "passthrough"`.
2. Confirm the `passthrough` enum value is present in the database: run `SELECT enum_range(NULL::mcp_session_auth_type);` and verify the output includes `passthrough`.
3. If the enum value is missing, the migration was not applied. Run `alembic current` to check the applied migration version and `alembic upgrade head` to apply outstanding migrations.

---

### 3. Agent Identity Not Available

**Log indicator:** Frontend console shows empty agent identity list; `GET /api/v1/agent-identities` returns an empty array or 403

1. Verify the user has access to agent identities. Check RLS policies on the agent identity table: the requesting user must satisfy the row-level security policy.
2. Confirm the Keycloak `ai_agents` realm is accessible and the backend can reach the realm's JWKS endpoint.
3. Call `GET /api/v1/agent-identities` directly with the user's token to isolate whether the issue is frontend state or a backend/RLS problem.

---

### 4. JWT Validation Failures Spike

**Alert:** `PassthroughJWTValidationFailureSpike` — JWT validation failures > 10% over 5 minutes

1. Check the Keycloak JWKS endpoint: `GET <KEYCLOAK_URL>/realms/<realm>/protocol/openid-connect/certs`. A non-200 response means all passthrough tool calls will fail until JWKS is reachable.
2. Review the JWKS cache TTL in `backend/app/auth.py` (default: `JWKS_CACHE_TTL = 600` seconds). If Keycloak recently rotated signing keys, the cache may be serving a stale JWKS; reduce TTL temporarily or restart the backend to flush the cache.
3. Check whether forwarded JWTs are consistently expired. A spike in JWT expiry rejections indicates the calling agent is not refreshing tokens before tool calls. Review the agent's token refresh logic.

---

### 5. Orphaned Passthrough Sessions

**Symptom:** Sessions referencing deleted MCP servers; monitoring query returns non-zero rows

1. Run the orphan detection query:
   ```sql
   SELECT ms.id, ms.name, ms.server_id
   FROM mcp_session ms
   LEFT JOIN mcp_server server ON ms.server_id = server.id
   WHERE ms.auth_type = 'passthrough'
     AND server.id IS NULL;
   ```
2. Review the results and confirm the server deletions were intentional.
3. Delete orphaned sessions after review:
   ```sql
   DELETE FROM mcp_session
   WHERE id IN (
       SELECT ms.id
       FROM mcp_session ms
       LEFT JOIN mcp_server server ON ms.server_id = server.id
       WHERE ms.auth_type = 'passthrough'
         AND server.id IS NULL
   );
   ```

---

## Debugging Tools

**Decode a JWT to inspect claims:**
```powershell
.\decode-jwt.ps1 -Token "eyJhbGc..."
# Verify: sub (agent UUID), email, iss (Keycloak issuer URL), exp (not in the past)
```

**Test passthrough tool call manually:**
```powershell
$token = "Bearer eyJhbGc..."
$body = @{
    tool_name    = "helloWorld"
    server_slug  = "demo"
    session_id   = $null
    agent_subject = "agent-uuid"
    arguments    = @{}
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:8000/api/v1/communication-hub/test-tool" `
    -Method POST `
    -Headers @{ "Authorization" = $token } `
    -Body $body `
    -ContentType "application/json"
```

**Enable debug logging for MCP proxy:**
```python
# backend/app/core/logging.py — temporary change for diagnostics only
import logging
logging.getLogger("app.core.mcp_proxy").setLevel(logging.DEBUG)
```

---

## Notes

- Passthrough sessions do not store credentials; there is no credential to rotate. If JWT forwarding is broken, the fix is always in middleware, proxy logic, or Keycloak connectivity — not in credential management.
- The `mcp-credential-error.md` runbook covers credential-based session failures and does not apply to passthrough sessions.
- After resolving a JWT validation spike, trigger a test tool call via the MCP Hub admin UI to confirm passthrough is working before closing the incident.
