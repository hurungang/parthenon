# MCP Demo App Test Plan

> Last updated: dual-identity tools (`mcp-dual-identity-tools` change)

## What to Test

### Configuration & Startup
- `AppSettings` loads all required environment variables correctly, including optional `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID` fields
- Defaults applied for optional settings; user-realm fields fall back to agent realm values when unset
- Missing required env vars cause startup failure with a clear error
- App performs Keycloak client credentials grant before accepting traffic
- Startup fails cleanly when Keycloak is unreachable

### Authentication — KeycloakClient
- Client credentials grant returns and caches an access token
- Cached token returned when more than ~30 s remain on expiry
- Token automatically refreshed when within ~30 s of expiry
- JWKS fetched from Keycloak and cached for 10 minutes
- Stale JWKS (beyond TTL) triggers a re-fetch before next validation
- JWKS cache hit avoids outbound HTTP call
- User realm JWKS cached independently from agent realm JWKS (separate client instances, no cross-contamination)

### JWT Validation (`verify_agent_jwt` and `verify_user_jwt`)
- Valid agent JWT signed by configured realm returns decoded claims
- Valid user JWT signed by configured user realm returns decoded claims
- User JWT validated against the user realm JWKS, not the agent realm JWKS — no cross-realm token acceptance
- User JWT rejected when signed by wrong realm's key (cross-realm rejection)
- JWT with invalid signature rejected (401)
- Expired JWT rejected (401)
- JWT with mismatched issuer rejected (401)
- Missing `Authorization` header on agent-gated tools returns 401
- Missing `X-User-Identity` header on user-gated tools returns 401
- `X-User-Identity` header present but empty → rejected as invalid
- `X-User-Identity` header with `Bearer ` prefix stripped correctly
- `verify_user_jwt` falls back to agent realm when `KEYCLOAK_USER_REALM` is not configured (single-realm backward compatibility)

### Health Endpoint
- `GET /health` returns HTTP 200 with `{"status": "ok", "slug": "demo"}` without authentication

### Tool Handler Logic — Role Gating
- **helloAgent**: returns greeting when agent identity has `mcp_role: demo_agent`; response includes `message`, `agent_sub`, `agent_realm`, `agent_mcp_role`, `agent_claims`
- **helloAgent**: returns access-denied when agent identity has wrong/missing `mcp_role` claim (JSON-RPC success, HTTP 200, not 403)
- **helloAgent**: does NOT inspect or depend on user identity claims in any way
- **helloUser**: returns greeting when user identity has `mcp_role: demo_user`; response includes `message`, `user_sub`, `user_realm`, `user_mcp_role`, `user_claims`
- **helloUser**: returns access-denied when user identity has wrong/missing `mcp_role` claim (JSON-RPC success, HTTP 200)
- **helloUser**: does NOT inspect or depend on agent identity claims in any way
- Both handlers handle edge cases: `mcp_role` as JSON array (multi-role tokens), unexpected types (integer, boolean, object), `None` identity

### Tool Registry & Manifest
- `tool_registry` maps exactly three tool names to handler functions: `helloWorld`, `helloAgent`, `helloUser`
- `TOOL_MANIFEST` returns exactly three tool descriptors with correct `name`, `description`, and `inputSchema`
- `helloAgent` and `helloUser` descriptions document the required identity and role
- `helloWorld` descriptor and handler unchanged from pre-change state

### MCP Router Dispatch Logic
- `tools/call` for `helloWorld` invokes agent identity only and passes it to handler
- `tools/call` for `helloAgent` invokes agent identity only and passes it to handler
- `tools/call` for `helloUser` invokes user identity only (from `X-User-Identity`) — does NOT validate agent JWT
- Unknown tool name → JSON-RPC error code `-32601`
- Access-denied from tool handlers is wrapped as HTTP 200 JSON-RPC success (not 403/401)

### Identity Isolation
- **helloAgent ignores user identity**: with both agent JWT (valid role) and user JWT in `X-User-Identity` → response based solely on agent claims
- **helloUser ignores agent identity**: with both user JWT (valid role) and agent JWT in `Authorization` → response based solely on user claims
- No cross-contamination between identity chains in any response

### MCP JSON-RPC Dispatcher
- `initialize` returns `serverInfo`, `capabilities`, and negotiated `protocolVersion`; no auth required
- `tools/list` returns exactly three tool descriptors; no auth required
- `tools/call` without `Authorization` header (for helloWorld/helloAgent) returns HTTP 401
- `tools/call` with invalid JWT returns HTTP 401
- Unknown JSON-RPC method returns error code `-32601` with request `id` echoed correctly
- Request with no `id` field echoes `null` for `id` in response (JSON-RPC spec compliance)

### Hub Registration (`register_with_hub`)
- First startup registers the app with slug `demo` via `POST /api/v1/mcp/servers` then syncs tools
- Restart with existing hub record (409 response) handles idempotency — looks up existing record and proceeds without error
- Hub unreachable at startup — app fails with a clear error
- Tool sync called after successful registration; three-tool manifest synced via unchanged registration logic

## Critical Scenarios

### Dual-Identity Core Flows
- Valid agent JWT with `demo_agent` role → `tools/call` (helloAgent) → greeting with agent claims
- Agent JWT without `demo_agent` role → `tools/call` (helloAgent) → access-denied (HTTP 200)
- No agent JWT → `tools/call` (helloAgent) → HTTP 401
- Valid user JWT with `demo_user` role → `tools/call` (helloUser) → greeting with user claims
- User JWT without `demo_user` role → `tools/call` (helloUser) → access-denied (HTTP 200)
- No `X-User-Identity` header → `tools/call` (helloUser) → HTTP 401

### Identity Isolation
- Both valid agent JWT (with role) AND valid user JWT present → `tools/call` (helloAgent) → only agent claims in response; user identity ignored
- Both valid user JWT (with role) AND valid agent JWT present → `tools/call` (helloUser) → only user claims in response; agent identity ignored
- `helloUser` call with valid user JWT but missing/expired agent JWT → succeeds (user-only tool does not validate agent JWT)

### Cross-Realm Security
- User JWT signed by agent realm (wrong issuer/JWKS) → JWT validation fails, token rejected
- `KEYCLOAK_USER_REALM` unset → user JWT validates against agent realm JWKS (single-realm fallback); tool proceeds with role check on that token

### Regression — helloWorld
- Valid agent JWT (any `mcp_role`, including none) → `tools/call` (helloWorld) → greeting with agent identity, no role gating
- `helloWorld` response structure unchanged from pre-change behavior
- `helloWorld` unaffected by presence or absence of user identity headers
- `tools/list` returns exactly three tools with correct schemas

### System-Level Flows
- All required env vars present → app starts, obtains token, completes hub registration before serving traffic
- App restarts against already-registered hub → 409 handled gracefully, no duplicate registration
- JWKS TTL expires mid-operation → re-fetch succeeds and validation resumes
- Token nearing expiry → refresh happens before call is made

## Edge Cases

### JWT / Auth Edge Cases
- JWKS key rotation: cache expires, re-fetch succeeds, validation resumes
- Token expiry race condition: ~30 s pre-expiry refresh window covers gap between check and use
- `mcp_role` claim is a JSON array (e.g., `["demo_agent", "other"]`) — tool checks `in`, not `==`
- `mcp_role` claim is unexpected type (integer, boolean, object) — access-denied rather than 500 error
- `X-User-Identity` header with irregular casing or whitespace in `Bearer ` prefix — stripped correctly
- User realm and agent realm are the same realm with different client IDs — JWKS cache sharing is harmless, no token confusion
- JWKS fetch failure (Keycloak unreachable or returns 500) — graceful error response, not crash

### MCP Protocol Edge Cases
- Malformed JSON-RPC body: dispatcher returns well-formed JSON-RPC parse error
- Missing `id` in JSON-RPC request: response echoes `null` for `id`
- Agent JWT missing `sub` claim: `hello_world_tool` handles gracefully

### Configuration Edge Cases
- `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID` both unset → fallback to agent realm/client (single-realm mode)
- Only `KEYCLOAK_USER_REALM` set but `KEYCLOAK_USER_CLIENT_ID` unset → client ID falls back to agent client ID
- User-specific settings do not interfere with agent-specific settings

### Service Edge Cases
- `HUB_URL` points to non-existent service: startup fails with clear error, not silent hang
- Network timeout on JWKS fetch: httpx timeout configured and surfaced as clear error
- Concurrent requests with different realms — independent cache instances, no contention

## Known Limitations / Notes
- No UI; no E2E browser tests required.
- No database; no migration tests required.
- Integration tests require a running Keycloak instance and Parthenon MCP Hub. They are skipped automatically when those services are unreachable (3-second connect timeout for Keycloak; 401/403 check for Hub token validity).
- Test files live in `mcp-demo-app/tests/` — this module has its own test root separate from the standard `backend/tests/`, `frontend/src/__tests__/`, and `e2e/tests/` paths in `docs/config.yaml`.
- No dedicated E2E suite exists for the MCP demo app; integration tests cover the full flow through the FastAPI TestClient with mocked identities.
- Access-denied is returned as JSON-RPC success (HTTP 200, `access_denied: true` in body), not as HTTP 403/401 — tests must assert on response body shape.

## Test File References

### Unit
- `mcp-demo-app/tests/unit/test_config.py` — `AppSettings` env-var loading, defaults, missing required fields, user-realm optional fields (6 tests)
- `mcp-demo-app/tests/unit/test_auth.py` — `KeycloakClient` JWKS/token caching, `verify_agent_jwt`, `verify_user_jwt` valid/expired/wrong-issuer/bad-sig, cross-realm rejection, single-realm fallback, `get_agent_identity`, `get_user_identity`, header parsing (Bearer stripping, missing/empty) (20 tests)
- `mcp-demo-app/tests/unit/test_tools.py` — `hello_world_tool`, `hello_agent_tool`, `hello_user_tool` handler functions (success, access-denied, missing identity, wrong role, edge-case claim types), `tool_registry` (3 entries), `TOOL_MANIFEST` (3 entries) content and schema (29 tests)
- `mcp-demo-app/tests/unit/test_mcp_router.py` — JSON-RPC dispatch: `initialize`, `tools/list` (3 tools), `tools/call` for all three tools with auth/role-gating/access-denied/identity-isolation, unknown method, id echo, null id, access-denied wrapping (23 tests)
- `mcp-demo-app/tests/unit/test_registration.py` — `register_with_hub`: success, 409 (list + paginated), slug-missing error, 500 error, sync failure (7 tests)
- `mcp-demo-app/tests/unit/test_health.py` — `GET /health`: status 200, body fields, slug value, no auth required (5 tests)

### Integration (skip when services unavailable)
- `mcp-demo-app/tests/integration/test_startup.py` — real Keycloak client credentials grant, JWKS retrieval, full lifespan startup (3 tests)
- `mcp-demo-app/tests/integration/test_agent_flow.py` — obtain real JWT → `tools/call` → verify `agent_sub`; no-auth 401; dual-identity flow with mocked identities (helloAgent/helloUser greeting and access-denied scenarios, identity isolation) (8 tests)
- `mcp-demo-app/tests/integration/test_hub_registration.py` — hub registration, server list check, idempotent re-registration (3 tests)

## Acceptance Criteria Coverage

| AC | Criterion | Coverage |
|----|-----------|----------|
| AC-1 | `helloAgent` callable when agent JWT has `mcp_role: demo_agent`; response includes agent claims | `test_tools.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-2 | `helloAgent` returns access-denied when agent JWT lacks `mcp_role: demo_agent` | `test_tools.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-3 | `helloAgent` returns auth error when no agent JWT forwarded | `test_mcp_router.py`; `test_agent_flow.py` |
| AC-4 | `helloUser` callable when user JWT has `mcp_role: demo_user`; response includes user claims | `test_tools.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-5 | `helloUser` returns access-denied when user JWT lacks `mcp_role: demo_user` | `test_tools.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-6 | `helloUser` returns auth error when no user JWT forwarded | `test_mcp_router.py`; `test_agent_flow.py` |
| AC-7 | `helloWorld` continues to work — surfaces agent identity, no role gating | `test_tools.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-8 | `tools/list` returns three tools with correct descriptions and input schemas | `test_tools.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-9 | Each tool validates only its required identity's claims (helloAgent ignores user, helloUser ignores agent) | `test_tools.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-10 | Identity JWTs validated for signature, expiry, issuer before claim inspection; invalid JWTs produce auth error | `test_auth.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-11 | User JWT rejected when signed by wrong realm's key (cross-realm rejection) | `test_auth.py` (cross-realm rejection) |
| AC-12 | Single-realm backward compatibility — app works when `KEYCLOAK_USER_REALM` is unset | `test_auth.py` (fallback) |
| AC-13 | App authenticates using Keycloak agent identity (client credentials) | `test_startup.py`; `test_auth.py` (client credentials grant) |
| AC-14 | App registers with Parthenon MCP Hub under unique slug; all tools synced | `test_registration.py`; `test_hub_registration.py` |
| AC-15 | All three tools available through existing MCP interface | `test_tools.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-16 | No changes to Communication Hub or Control Center | E2E regression suite (no dedicated MCP demo E2E; integration tests cover the full flow) |
| AC-17 | Documentation provided for dual-identity setup | Manual review of README (out of automated test scope) |
