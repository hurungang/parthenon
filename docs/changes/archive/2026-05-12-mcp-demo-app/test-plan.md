# Test Plan: mcp-demo-app

## 1. Test Strategy

The MCP Demo App is a standalone Python FastAPI service with no database and no frontend. Testing focuses on three layers:

- **Unit tests** — Isolate and validate individual components: `KeycloakClient`, `verify_agent_jwt`, `get_agent_identity`, `hello_world_tool`, `register_with_hub`, and MCP JSON-RPC dispatch logic. External HTTP calls are mocked.
- **Integration tests** — Validate the app against a real (or containerised) Keycloak instance and the Parthenon MCP Hub. Covers the client credentials grant flow, JWKS retrieval, hub registration, and tool sync end-to-end.
- **Manual / smoke tests** — Confirm the running service behaves correctly in the local Docker Compose environment: health check, `tools/list`, and a full `tools/call` round-trip with a live agent JWT.

No E2E browser tests are required (no UI). No database migration tests are required (no persistent data store).

---

## 2. Coverage Areas

| Area | Why Critical |
|------|--------------|
| **AppSettings / config loading** | Misconfigured env vars cause silent startup failures; all runtime behaviour depends on correct settings |
| **KeycloakClient — client credentials grant** | The app cannot obtain its own access token without this; required for hub registration |
| **KeycloakClient — JWKS cache** | Stale or missing JWKS causes all tool calls to fail with 401; cache expiry logic must be correct |
| **`verify_agent_jwt`** | Core security boundary — invalid, expired, or wrong-issuer tokens must be rejected; valid tokens must return decoded claims |
| **`get_agent_identity` dependency** | FastAPI dependency that guards all `tools/call` requests; must propagate validated claims to handlers |
| **`hello_world_tool`** | Only tool in the app; must surface the agent `sub` claim in its response |
| **MCP JSON-RPC dispatcher** | Correct routing of `initialize`, `tools/list`, `tools/call`; correct error code for unknown methods |
| **Hub registration (`register_with_hub`)** | App must register itself and sync tools on startup; 409 idempotency must be handled gracefully |
| **Health endpoint** | Health check must be unauthenticated and always return the correct slug |
| **Startup lifespan** | Keycloak token validation and hub registration happen before the app accepts traffic; failures must surface clearly |

---

## 3. Critical Scenarios

### 3.1 Configuration & Startup

**WHEN** all required environment variables are present and Keycloak is reachable  
**THEN** the app starts successfully, obtains a client credentials token, and completes hub registration before accepting requests

**WHEN** a required environment variable is missing (e.g. `KEYCLOAK_URL`)  
**THEN** the app fails at startup with a clear configuration error and does not serve traffic

**WHEN** Keycloak is unreachable at startup  
**THEN** the app fails to start and logs the connection error

---

### 3.2 Health Endpoint

**WHEN** `GET /health` is called with no `Authorization` header  
**THEN** the response is HTTP 200 with body `{"status": "ok", "slug": "demo"}`

---

### 3.3 JWT Validation

**WHEN** a valid agent JWT signed by the configured Keycloak realm is provided  
**THEN** `verify_agent_jwt` returns the decoded claims without error

**WHEN** a JWT with an invalid signature is provided  
**THEN** `verify_agent_jwt` raises an authentication error

**WHEN** an expired JWT is provided  
**THEN** `verify_agent_jwt` raises an authentication error indicating token expiry

**WHEN** a JWT with a mismatched issuer (wrong realm or wrong Keycloak instance) is provided  
**THEN** `verify_agent_jwt` raises an authentication error

**WHEN** no `Authorization` header is present on a `tools/call` request  
**THEN** the endpoint returns HTTP 401

---

### 3.4 JWKS Cache

**WHEN** the JWKS was last fetched more than 10 minutes ago  
**THEN** `KeycloakClient` re-fetches the JWKS from Keycloak before the next validation

**WHEN** the JWKS is still within its 10-minute TTL  
**THEN** `KeycloakClient` uses the cached JWKS without making an outbound HTTP call

---

### 3.5 Client Credentials Token Cache

**WHEN** the cached access token has more than ~30 seconds remaining  
**THEN** `KeycloakClient` returns the cached token without re-requesting

**WHEN** the cached access token is within ~30 seconds of expiry  
**THEN** `KeycloakClient` automatically refreshes the token before returning it

---

### 3.6 MCP `initialize`

**WHEN** a `POST /mcp` request with method `initialize` and valid `protocolVersion`, `capabilities`, and `clientInfo` is sent  
**THEN** the response contains `serverInfo`, `capabilities`, and the negotiated `protocolVersion`

**WHEN** `initialize` is called without an `Authorization` header  
**THEN** the request succeeds (auth is not required for `initialize`)

---

### 3.7 MCP `tools/list`

**WHEN** a `POST /mcp` request with method `tools/list` is sent  
**THEN** the response contains an array with exactly one tool descriptor: `helloWorld`, with its name, description, and input JSON schema

**WHEN** `tools/list` is called without an `Authorization` header  
**THEN** the request succeeds (auth is not required for `tools/list`)

---

### 3.8 MCP `tools/call` — `helloWorld`

**WHEN** `tools/call` is sent with `name: "helloWorld"` and a valid agent JWT  
**THEN** the response contains `"message": "Hello from MCP Demo App!"`, the agent's `sub` claim, and the full decoded agent claims

**WHEN** `tools/call` is sent with `name: "helloWorld"` and no `Authorization` header  
**THEN** the endpoint returns HTTP 401

**WHEN** `tools/call` is sent with `name: "helloWorld"` and an invalid JWT  
**THEN** the endpoint returns HTTP 401

**WHEN** `tools/call` is sent with an unknown tool name  
**THEN** the response is a JSON-RPC error (code `-32601`, method not found)

---

### 3.9 Unknown JSON-RPC Method

**WHEN** a `POST /mcp` request is sent with an unrecognised method name  
**THEN** the response is a JSON-RPC error with code `-32601` and the request `id` is echoed back correctly

---

### 3.10 Hub Registration

**WHEN** the app starts for the first time and no hub record exists  
**THEN** `register_with_hub` calls `POST /api/v1/mcp/servers` and the demo app is registered with slug `demo`, followed by a successful tool sync call

**WHEN** the app restarts and the hub record already exists (409 response)  
**THEN** `register_with_hub` handles the 409 by looking up the existing record and proceeds without error

**WHEN** the hub is unreachable during startup registration  
**THEN** the app logs the failure and does not start successfully

---

### 3.11 Tool Manifest Accuracy (Integration)

**WHEN** the MCP Hub calls `tools/list` during tool sync  
**THEN** the tool manifest matches `TOOL_MANIFEST` exactly — one tool, correct name (`helloWorld`), correct description, correct input schema

---

## 4. Edge Cases & Risks

| Risk | Scenario | Mitigation to Test |
|------|----------|--------------------|
| **JWKS key rotation** | Keycloak rotates signing keys; cached JWKS becomes stale | Force cache expiry and verify re-fetch succeeds and validation resumes |
| **Token expiry race condition** | Access token expires between cache check and use | Verify the ~30 s pre-expiry refresh window handles this correctly |
| **Hub 409 not handled** | Restarting the app creates duplicate registrations or crashes | Verify 409 is caught, existing record is looked up, and registration completes |
| **Malformed JSON-RPC body** | Non-JSON or incomplete JSON-RPC envelope sent to `/mcp` | Verify the dispatcher returns a well-formed JSON-RPC parse error |
| **Missing `id` in JSON-RPC request** | Client omits the `id` field | Verify the response echoes `null` for `id` as per JSON-RPC spec |
| **Agent `sub` claim absent from JWT** | JWT is valid but has no `sub` claim | Verify `hello_world_tool` handles missing `sub` gracefully |
| **Hub URL misconfigured** | `HUB_URL` points to a non-existent service | Verify startup fails with a clear error, not a silent hang |
| **Network timeout on JWKS fetch** | Keycloak JWKS endpoint is slow | Verify httpx timeout is configured and surfaced as a clear error |

---

## 5. Acceptance Criteria Checklist

Maps directly to PRD Section 5 acceptance criteria.

| # | PRD Acceptance Criterion | Test Coverage |
|---|--------------------------|---------------|
| AC-1 | App can be launched and authenticates using a Keycloak agent identity (ai_agent realm) | Startup integration test; client credentials grant flow |
| AC-2 | App exposes a single `helloWorld` tool, visible and callable after authentication | `tools/list` unit + integration test; `tools/call` unit + integration test |
| AC-3 | Agent identity is passed and accessible throughout the app's flow (login → tool execution) | `verify_agent_jwt` unit tests; `tools/call` response contains `agent_sub` and `agent_claims` |
| AC-4 | Demo app can be registered with the Parthenon MCP Hub using a unique slug, and the tool appears under the correct namespace | Hub registration integration test; tool sync verification |
| AC-5 | Documentation is provided to guide registration and integration steps | Manual review of README / deployment docs (out of automated test scope) |
| AC-6 | Out-of-scope features are not present (no user realm auth, no extra tools, no production hardening) | Verified by absence: `tools/list` returns exactly one tool; no user realm endpoints exposed |

---

## 6. Test File References

The demo app is a new standalone service. All tests live under its own test directory, separate from the main Parthenon test paths in `docs/config.yaml`.

| Layer | File | Tests | Status |
|-------|------|-------|--------|
| Unit | `mcp-demo-app/tests/unit/test_config.py` | `AppSettings` env-var loading, defaults, missing required fields (6 tests) | ✅ Implemented |
| Unit | `mcp-demo-app/tests/unit/test_auth.py` | `KeycloakClient` JWKS/token caching, `verify_agent_jwt` (valid/expired/wrong-issuer/bad-sig), `get_agent_identity` (12 tests) | ✅ Implemented |
| Unit | `mcp-demo-app/tests/unit/test_tools.py` | `hello_world_tool`, `tool_registry`, `TOOL_MANIFEST` content and schema (14 tests) | ✅ Implemented |
| Unit | `mcp-demo-app/tests/unit/test_mcp_router.py` | JSON-RPC dispatch: `initialize`, `tools/list`, `tools/call` (auth/no-auth/unknown-tool), unknown method, id echo, null id (17 tests) | ✅ Implemented |
| Unit | `mcp-demo-app/tests/unit/test_registration.py` | `register_with_hub`: success, 409 (list + paginated), slug-missing error, 500 error, sync failure (7 tests) | ✅ Implemented |
| Unit | `mcp-demo-app/tests/unit/test_health.py` | `GET /health`: status 200, body fields, slug value, no auth required (5 tests) | ✅ Implemented |
| Integration | `mcp-demo-app/tests/integration/test_startup.py` | Real Keycloak client credentials grant, JWKS retrieval, full lifespan startup (3 tests — skip if Keycloak unreachable) | ✅ Implemented |
| Integration | `mcp-demo-app/tests/integration/test_agent_flow.py` | End-to-end: obtain real JWT → `tools/call` → verify `agent_sub`; no-auth 401 (4 tests — skip if Keycloak unreachable) | ✅ Implemented |
| Integration | `mcp-demo-app/tests/integration/test_hub_registration.py` | Hub registration, server list check, idempotent re-registration (3 tests — skip if Hub unreachable or token invalid) | ✅ Implemented |

**Run results (services not running in CI):**
- Unit tests: **65 passed** (includes pre-existing `tests/test_auth.py`)
- Integration tests: **10 skipped** (Keycloak and Hub not running in local test environment — expected)
- Total: **65 passed, 10 skipped, 0 failed**

**Skip conditions:**
- `test_startup.py` and `test_agent_flow.py`: skip when `KEYCLOAK_URL` host is not reachable (3-second connect timeout)
- `test_hub_registration.py`: skip when Hub is not reachable OR the `HUB_API_TOKEN` returns 401/403 on an authenticated request
