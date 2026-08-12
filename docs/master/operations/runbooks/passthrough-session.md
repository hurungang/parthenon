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

1. Run the orphan detection query: Query the `mcp_session` table joined with `mcp_server` where `auth_type = 'passthrough'` and `server.id IS NULL` to identify orphaned sessions referencing deleted servers.
2. Review the results and confirm the server deletions were intentional.
3. Delete orphaned sessions after review: Delete from `mcp_session` where the session's server no longer exists.

---

## Debugging Tools

**Decode a JWT to inspect claims:**
Use the `decode-jwt.ps1` script with the token to verify claims: sub (agent UUID), email, iss (Keycloak issuer URL), exp (not in the past).

**Test passthrough tool call manually:**
Send a POST request to `/api/v1/communication-hub/test-tool` with a valid Bearer token, setting `tool_name`, `server_slug`, `agent_subject`, and `arguments` fields. The `agent_subject` must be the UUID of the agent identity whose JWT should be forwarded.

**Enable debug logging for MCP proxy:**
Temporarily set the `app.core.mcp_proxy` logger to DEBUG level in the logging configuration to trace auth header construction and passthrough JWT forwarding decisions.

---

## Notes

- Passthrough sessions do not store credentials; there is no credential to rotate. If JWT forwarding is broken, the fix is always in middleware, proxy logic, or Keycloak connectivity — not in credential management.
- The `mcp-credential-error.md` runbook covers credential-based session failures and does not apply to passthrough sessions.
- After resolving a JWT validation spike, trigger a test tool call via the MCP Hub admin UI to confirm passthrough is working before closing the incident.
