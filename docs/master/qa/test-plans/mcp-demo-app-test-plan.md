# MCP Demo App Test Plan

## What to Test

### Configuration & Startup
- `AppSettings` loads all required environment variables correctly
- Defaults applied for optional settings
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

### JWT Validation (`verify_agent_jwt`)
- Valid agent JWT signed by configured realm returns decoded claims
- JWT with invalid signature rejected (401)
- Expired JWT rejected (401)
- JWT with mismatched issuer rejected (401)
- Missing `Authorization` header on protected endpoints returns 401

### Health Endpoint
- `GET /health` returns HTTP 200 with `{"status": "ok", "slug": "demo"}` without authentication

### MCP JSON-RPC Dispatcher
- `initialize` returns `serverInfo`, `capabilities`, and negotiated `protocolVersion`; no auth required
- `tools/list` returns exactly one tool descriptor (`helloWorld`) with correct name, description, and input schema; no auth required
- `tools/call` with `helloWorld` and valid JWT returns message, `agent_sub`, and full `agent_claims`
- `tools/call` without `Authorization` header returns HTTP 401
- `tools/call` with invalid JWT returns HTTP 401
- `tools/call` with unknown tool name returns JSON-RPC error code `-32601`
- Unknown JSON-RPC method returns error code `-32601` with request `id` echoed correctly
- Request with no `id` field echoes `null` for `id` in response (JSON-RPC spec compliance)

### Hub Registration (`register_with_hub`)
- First startup registers the app with slug `demo` via `POST /api/v1/mcp/servers` then syncs tools
- Restart with existing hub record (409 response) handles idempotency — looks up existing record and proceeds without error
- Hub unreachable at startup — app fails with a clear error
- Tool sync called after successful registration

## Critical Scenarios
- All required env vars present → app starts, obtains token, completes hub registration before serving traffic
- Valid agent JWT → `tools/call` → response includes correct `agent_sub` claim
- Invalid JWT → `tools/call` → HTTP 401
- No auth header → `tools/call` → HTTP 401
- `tools/list` returns exactly one tool (`helloWorld`), not zero and not more
- App restarts against already-registered hub → 409 handled gracefully, no duplicate registration
- JWKS TTL expires mid-operation → re-fetch succeeds and validation resumes
- Token nearing expiry → refresh happens before call is made

## Edge Cases
- JWKS key rotation: cache expires, re-fetch succeeds, validation resumes
- Token expiry race condition: ~30 s pre-expiry refresh window covers gap between check and use
- Malformed JSON-RPC body: dispatcher returns well-formed JSON-RPC parse error
- Missing `id` in JSON-RPC request: response echoes `null` for `id`
- Agent JWT missing `sub` claim: `hello_world_tool` handles gracefully
- `HUB_URL` points to non-existent service: startup fails with clear error, not silent hang
- Network timeout on JWKS fetch: httpx timeout configured and surfaced as clear error

## Known Limitations / Notes
- No UI; no E2E browser tests required.
- No database; no migration tests required.
- Integration tests require a running Keycloak instance and Parthenon MCP Hub. They are skipped automatically when those services are unreachable (3-second connect timeout for Keycloak; 401/403 check for Hub token validity).
- Test files live in `mcp-demo-app/tests/` — this module has its own test root separate from the standard `backend/tests/`, `frontend/src/__tests__/`, and `e2e/tests/` paths in `docs/config.yaml`.

## Test File References

### Unit
- `mcp-demo-app/tests/unit/test_config.py` — `AppSettings` env-var loading, defaults, missing required fields (6 tests)
- `mcp-demo-app/tests/unit/test_auth.py` — `KeycloakClient` JWKS/token caching, `verify_agent_jwt` valid/expired/wrong-issuer/bad-sig, `get_agent_identity` (12 tests)
- `mcp-demo-app/tests/unit/test_tools.py` — `hello_world_tool`, `tool_registry`, `TOOL_MANIFEST` content and schema (14 tests)
- `mcp-demo-app/tests/unit/test_mcp_router.py` — JSON-RPC dispatch: `initialize`, `tools/list`, `tools/call` (auth/no-auth/unknown-tool), unknown method, id echo, null id (17 tests)
- `mcp-demo-app/tests/unit/test_registration.py` — `register_with_hub`: success, 409 (list + paginated), slug-missing error, 500 error, sync failure (7 tests)
- `mcp-demo-app/tests/unit/test_health.py` — `GET /health`: status 200, body fields, slug value, no auth required (5 tests)

### Integration (skip when services unavailable)
- `mcp-demo-app/tests/integration/test_startup.py` — real Keycloak client credentials grant, JWKS retrieval, full lifespan startup (3 tests)
- `mcp-demo-app/tests/integration/test_agent_flow.py` — obtain real JWT → `tools/call` → verify `agent_sub`; no-auth 401 (4 tests)
- `mcp-demo-app/tests/integration/test_hub_registration.py` — hub registration, server list check, idempotent re-registration (3 tests)

## Acceptance Criteria Coverage

| AC | Criterion | Coverage |
|----|-----------|----------|
| AC-1 | App authenticates using Keycloak agent identity (client credentials) | `test_startup.py`; `test_auth.py` (client credentials grant) |
| AC-2 | Single `helloWorld` tool visible and callable after authentication | `test_tools.py`; `test_mcp_router.py`; `test_agent_flow.py` |
| AC-3 | Agent identity passed through and accessible in tool execution | `test_auth.py` (`verify_agent_jwt`); `test_mcp_router.py` (`tools/call` response contains `agent_sub`/`agent_claims`) |
| AC-4 | App registers with Parthenon MCP Hub under unique slug; tool appears under correct namespace | `test_registration.py`; `test_hub_registration.py` |
| AC-5 | Documentation provided for registration and integration | Manual review of README (out of automated test scope) |
| AC-6 | No out-of-scope features (no user realm auth, no extra tools) | `test_mcp_router.py` (`tools/list` returns exactly one tool); no user realm endpoints present |
