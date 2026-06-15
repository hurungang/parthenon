# MCP Dual-Identity Tools — Implementation Plan

## Overview

Add two new MCP tools (`helloAgent`, `helloUser`) to the MCP Demo App alongside the existing `helloWorld` tool. Each new tool validates a different identity JWT forwarded by the Communication Hub — `helloAgent` validates the agent identity and gates on the `mcp_role` claim `demo_agent`, while `helloUser` validates the user identity from the `X-User-Identity` header and gates on `demo_user`. All changes are confined to the `mcp-demo-app/` directory.

---

## Task Checklist

### Phase 1 — Configuration
- [x] 1.1 — Add user-realm Keycloak config to AppSettings
- [x] 1.2 — Add `KEYCLOAK_USER_REALM` and related vars to `.env.example`

### Phase 2 — Auth Layer
- [x] 2.1 — Add `verify_user_jwt` function to auth.py
- [x] 2.2 — Add `get_user_identity` FastAPI dependency to auth.py
- [x] 2.3 — Add second `KeycloakClient` instance for the user realm

### Phase 3 — New Tool Handlers
- [x] 3.1 — Add `hello_agent_tool(agent_identity)` handler to tools.py
- [x] 3.2 — Add `hello_user_tool(user_identity)` handler to tools.py
- [x] 3.3 — Update `tool_registry` and `TOOL_MANIFEST` with all three tools

### Phase 4 — MCP Router Update
- [x] 4.1 — Extract user identity in `tools/call` handler
- [x] 4.2 — Pass correct identity to each tool based on tool name
- [x] 4.3 — Return access-denied result when required `mcp_role` claim is absent

### Phase 5 — Initialization Scripts
- [x] 5.1 — Update init.ps1 to support dual-realm setup
- [x] 5.2 — Add realm role creation for `demo_agent` and `demo_user`

### Phase 6 — Documentation
- [x] 6.1 — Update README.md with dual-identity setup instructions
- [x] 6.2 — Document new environment variables and tool API

### Phase 7 — Tests
- [x] 7.1 — Add unit tests for `hello_agent_tool` and `hello_user_tool`
- [x] 7.2 — Add unit tests for `verify_user_jwt` and `get_user_identity`
- [x] 7.3 — Add unit tests for updated `tool_registry` and `TOOL_MANIFEST`
- [x] 7.4 — Add MCP router tests for new tools and dual-identity extraction
- [x] 7.5 — Add integration tests for end-to-end dual-identity flow

### Phase 8 — Master Docs Update
- [x] 8.1 — Update `docs/master/technology/modules/mcp-demo-app/tech-spec.md`
- [x] 8.2 — Update `docs/master/qa/test-plans/mcp-demo-app-test-plan.md`
- [x] 8.3 — Update `docs/master/product/features/mcp-demo-app.md`

### Phase 9 — X-User-Identity Pipeline
- [x] 9.1 — Add `user_jwt` to `ToolCallRequest` and forward through CH tool routing
- [x] 9.2 — Add `user_jwt` to `McpProxyRequest` and pass to `McpProxyEngine`
- [x] 9.3 — Set `X-User-Identity` header in `_build_auth_headers` for passthrough sessions
- [x] 9.4 — Cache user JWT from WebSocket by session ID in CH

### Phase 10 — Keycloak mcp_role Claim
- [x] 10.1 — Register `mcp_role` attribute in Keycloak user profile (both realms)
- [x] 10.2 — Add `oidc-usermodel-attribute-mapper` to `parthenon-api` client (both realms)
- [x] 10.3 — Add mapper to `parthenon-api-ui` client (user realm) for frontend JWTs
- [x] 10.4 — Set user attribute `mcp_role` on test identities with GET-then-PUT
- [x] 10.5 — Restore wiped profile fields (email, firstName, lastName)

### Phase 11 — Init Script Hardenings
- [x] 11.1 — Add Keycloak data volume persistence to Docker Compose
- [x] 11.2 — Fix Unicode encoding crash on Windows terminals
- [x] 11.3 — Handle duplicate PlatformUser records during admin setup
- [x] 11.4 — Add offline_access scope assignment for agent OAuth refresh tokens
- [x] 11.5 — Avoid unnecessary user PUTs (skip when attribute already correct)
- [x] 11.6 — Auto-clear expired tokens for test identities

### Phase 12 — Diagnostics & UI
- [x] 12.1 — Add debug logging to `require_permission` in CC deps
- [x] 12.2 — Add tool call and identity logging to MCP demo app
- [x] 12.3 — Fix delegation progress UI: only show for `delegating`/`waiting`, not `using_tool`
- [x] 12.4 — Fix integration test skips: mock-based tests run without Keycloak

---

## Detailed Task Descriptions

### Phase 1 — Configuration

#### Task 1.1 — Add user-realm Keycloak config to AppSettings
Read `mcp-demo-app/app/config.py`. Add optional `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID` fields to the `AppSettings` class. When `KEYCLOAK_USER_REALM` is not set, the app falls back to using the agent realm for user identity validation (single-realm mode). This ensures backward compatibility with existing single-realm deployments.

**Done when**: `AppSettings` has `KEYCLOAK_USER_REALM: str = ""` and `KEYCLOAK_USER_CLIENT_ID: str = ""` fields that are read from environment.

---

#### Task 1.2 — Add user-realm env vars to .env.example
Read `mcp-demo-app/.env.example`. Add commented-out entries for `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID` with descriptions explaining that these are needed for the user identity realm and default to the agent realm values when unset.

**Done when**: `.env.example` has entries for all new environment variables with documentation comments.

---

### Phase 2 — Auth Layer

#### Task 2.1 — Add `verify_user_jwt` function to auth.py
Read `mcp-demo-app/app/auth.py`. Add a `verify_user_jwt(token: str) -> dict[str, Any]` async function. This function validates a JWT against the user realm's Keycloak JWKS. It follows the same pattern as `verify_agent_jwt` but reads `KEYCLOAK_URL` and `KEYCLOAK_USER_REALM` (falling back to `KEYCLOAK_REALM`) to compute the expected issuer. The function raises `HTTPException(401)` on validation failure. A separate `KeycloakClient` instance dedicated to the user realm handles JWKS caching independently from the agent realm client.

**Done when**: `verify_user_jwt` is callable, validates JWTs against the correct user realm issuer, and raises HTTPException(401) on failure.

---

#### Task 2.2 — Add `get_user_identity` FastAPI dependency to auth.py
Read `mcp-demo-app/app/auth.py`. Add a `get_user_identity(request: Request) -> dict[str, Any]` async function. This FastAPI dependency extracts the user identity JWT from the `X-User-Identity` request header (not the `Authorization` header). It strips the `Bearer ` prefix if present, then delegates to `verify_user_jwt` for validation. Returns the decoded claims dict on success.

**Done when**: `get_user_identity` extracts bearer token from `X-User-Identity` header, validates it with `verify_user_jwt`, and raises HTTPException(401) on missing header or validation failure.

---

#### Task 2.3 — Add second `KeycloakClient` instance for the user realm
Read `mcp-demo-app/app/auth.py`. Create a second module-level `KeycloakClient` singleton (`user_keycloak_client`) for the user realm. This instance uses `KEYCLOAK_USER_REALM` (falling back to `KEYCLOAK_REALM`) for its JWKS and token URLs. The two client instances cache JWKS and access tokens independently, avoiding cache collisions when the user realm and agent realm are on the same Keycloak instance.

**Done when**: `user_keycloak_client` is a module-level `KeycloakClient` singleton that can independently fetch JWKS from the user realm.

---

### Phase 3 — New Tool Handlers

#### Task 3.1 — Add `hello_agent_tool(agent_identity)` handler to tools.py
Read `mcp-demo-app/app/tools.py`. Add a `hello_agent_tool(agent_identity: dict[str, Any]) -> dict[str, Any]` function. The function:
- Extracts the `mcp_role` claim from `agent_identity`
- If `mcp_role` does not equal `demo_agent`, returns `{"access_denied": True, "reason": "Agent identity lacks required mcp_role: demo_agent"}`
- If `mcp_role` equals `demo_agent`, returns `{"message": "Hello Agent!", "agent_sub": agent_identity.get("sub"), "agent_realm": agent_identity.get("iss"), "agent_mcp_role": agent_identity.get("mcp_role"), "agent_claims": agent_identity}`

**Done when**: `hello_agent_tool` returns access-denied when `mcp_role` is missing or wrong, and returns a greeting with agent identity claims when `mcp_role` is `demo_agent`.

---

#### Task 3.2 — Add `hello_user_tool(user_identity)` handler to tools.py
Read `mcp-demo-app/app/tools.py`. Add a `hello_user_tool(user_identity: dict[str, Any]) -> dict[str, Any]` function. The function:
- Extracts the `mcp_role` claim from `user_identity`
- If `mcp_role` does not equal `demo_user`, returns `{"access_denied": True, "reason": "User identity lacks required mcp_role: demo_user"}`
- If `mcp_role` equals `demo_user`, returns `{"message": "Hello User!", "user_sub": user_identity.get("sub"), "user_realm": user_identity.get("iss"), "user_mcp_role": user_identity.get("mcp_role"), "user_claims": user_identity}`

**Done when**: `hello_user_tool` returns access-denied when `mcp_role` is missing or wrong, and returns a greeting with user identity claims when `mcp_role` is `demo_user`.

---

#### Task 3.3 — Update `tool_registry` and `TOOL_MANIFEST` with all three tools
Read `mcp-demo-app/app/tools.py`. Update the `tool_registry` dictionary to include `helloAgent` mapped to `hello_agent_tool` and `helloUser` mapped to `hello_user_tool`. Update the `TOOL_MANIFEST` list to include three tool descriptors:
- `helloWorld` — unchanged
- `helloAgent` — description: "Greets the calling agent identity. Requires the agent to have mcp_role 'demo_agent'."
- `helloUser` — description: "Greets the calling user identity. Requires the user to have mcp_role 'demo_user'."

All three tools have the same input schema: empty properties, empty required list.

**Done when**: `tool_registry` has 3 entries, `TOOL_MANIFEST` has 3 entries with correct names, descriptions, and input schemas.

---

### Phase 4 — MCP Router Update

#### Task 4.1 — Extract user identity in `tools/call` handler
Read `mcp-demo-app/app/routes/mcp.py`. In the `tools/call` branch of `mcp_endpoint`, after extracting the tool name, determine whether the tool is user-identity-gated (`helloUser`) or agent-identity-gated (`helloAgent`, `helloWorld`). For user-identity-gated tools, call `get_user_identity(request)` to extract the user JWT. For agent-identity-gated tools, call `get_agent_identity(request)` as before.

**Done when**: The router extracts the correct identity based on which tool is being called, and returns 401 if the required identity header is missing.

---

#### Task 4.2 — Pass correct identity to each tool based on tool name
Read `mcp-demo-app/app/routes/mcp.py`. Update the handler invocation: for `helloAgent`, pass `agent_identity`; for `helloUser`, pass `user_identity`; for `helloWorld`, pass `agent_identity` as before. Each tool handler receives only the identity it needs for its access control decision.

**Done when**: Each tool handler receives the correct identity dict — agent identity for `helloAgent` and `helloWorld`, user identity for `helloUser`.

---

#### Task 4.3 — Return access-denied result when required `mcp_role` claim is absent
Read `mcp-demo-app/app/routes/mcp.py`. Ensure that when a tool handler returns a dict containing `access_denied: True`, the router returns a normal JSON-RPC success response (HTTP 200) with the access-denied result in the response body. This allows callers to programmatically distinguish access-denied from authentication failures (401) or other errors. The access-denied result is placed in the `result` field of the JSON-RPC response alongside the `content` field.

**Done when**: Access-denied tool results are returned as HTTP 200 with the access-denied payload in the JSON-RPC result, not as HTTP errors.

---

### Phase 5 — Initialization Scripts

#### Task 5.1 — Update init.ps1 to support dual-realm setup
Read `mcp-demo-app/init.ps1`. Add a `-UserRealm` parameter (default: empty string) that signals the script to also set up the user realm. When `-UserRealm` is provided, the script:
- Checks the user realm exists in Keycloak
- Creates a client in the user realm (or notes that one is needed)
- Writes `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID` to `.env`

**Done when**: `init.ps1` accepts `-UserRealm`, verifies the realm exists, and writes user realm config to `.env`.

---

#### Task 5.2 — Add realm role creation for `demo_agent` and `demo_user`
Read `mcp-demo-app/init.ps1`. After creating the client in each realm, optionally create realm-level roles `demo_agent` in the agent realm and `demo_user` in the user realm. This step is idempotent — if the roles already exist, the script skips creation. The roles serve as the `mcp_role` claim values that the new tools check.

**Done when**: `init.ps1` creates or verifies the `demo_agent` role in the agent realm and the `demo_user` role in the user realm.

---

### Phase 6 — Documentation

#### Task 6.1 — Update README.md with dual-identity setup instructions
Read `mcp-demo-app/README.md`. Add a new section "Dual-Identity Setup" covering:
- Overview of the three tools and their identity requirements
- Steps to configure the user realm in Keycloak alongside the agent realm
- How to assign `mcp_role` claims (`demo_agent`, `demo_user`) as realm roles on test identities
- How to verify each tool's behavior using curl commands for both successful and access-denied scenarios

Update the environment variables table to include `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID`. Update the "Verifying Agent Identity" section to cover all three tools.

**Done when**: README has a complete dual-identity setup section, updated env var table, and verification instructions for all three tools.

---

#### Task 6.2 — Document new environment variables and tool API
Read `mcp-demo-app/README.md`. Update the endpoint documentation to list all three tools with their descriptions and required identities. Document the `X-User-Identity` header for user identity propagation. Add example curl commands for `helloAgent` and `helloUser` with both success and access-denied responses.

**Done when**: README documents all three tools, the user identity header, and has curl examples for each tool.

---

### Phase 7 — Tests

#### Task 7.1 — Add unit tests for `hello_agent_tool` and `hello_user_tool`
Read `mcp-demo-app/tests/unit/test_tools.py`. Add test functions for:
- `hello_agent_tool` returns greeting with agent claims when `mcp_role` is `demo_agent`
- `hello_agent_tool` returns access-denied when `mcp_role` is absent
- `hello_agent_tool` returns access-denied when `mcp_role` is a different value
- `hello_agent_tool` handles empty identity dict gracefully
- `hello_user_tool` returns greeting with user claims when `mcp_role` is `demo_user`
- `hello_user_tool` returns access-denied when `mcp_role` is absent
- `hello_user_tool` returns access-denied when `mcp_role` is a different value
- `hello_user_tool` handles empty identity dict gracefully

**Done when**: All new unit test functions pass, covering both success and access-denied paths for each new tool.

---

#### Task 7.2 — Add unit tests for `verify_user_jwt` and `get_user_identity`
Read `mcp-demo-app/tests/unit/test_auth.py`. Add test functions for:
- `verify_user_jwt` validates a valid user JWT against the user realm
- `verify_user_jwt` raises 401 on expired user JWT
- `verify_user_jwt` raises 401 on wrong issuer
- `verify_user_jwt` raises 401 on invalid signature
- `get_user_identity` extracts token from `X-User-Identity` header
- `get_user_identity` raises 401 when `X-User-Identity` header is missing
- `get_user_identity` raises 401 when `X-User-Identity` header is malformed

Follow the existing test patterns: use the RSA key pair fixture, `_make_token` helper, and mock `keycloak_client` for JWKS.

**Done when**: All new auth test functions pass.

---

#### Task 7.3 — Add unit tests for updated `tool_registry` and `TOOL_MANIFEST`
Read `mcp-demo-app/tests/unit/test_tools.py`. Update existing tests:
- `test_tool_registry_has_exactly_one_tool` → assert exactly three tools
- `test_tool_manifest_has_exactly_one_entry` → assert exactly three entries

Add new tests:
- `tool_registry` contains `helloAgent` and `helloUser` keys
- `TOOL_MANIFEST` entry for `helloAgent` has correct name and description
- `TOOL_MANIFEST` entry for `helloUser` has correct name and description
- Each manifest entry has an `inputSchema` with type `object`

**Done when**: All registry and manifest tests pass reflecting the three-tool state.

---

#### Task 7.4 — Add MCP router tests for new tools and dual-identity extraction
Read `mcp-demo-app/tests/unit/test_mcp_router.py`. Update the test for `tools/list` returning one tool to expect three tools. Add test functions:
- `tools/call` with `helloAgent` uses agent identity and returns greeting
- `tools/call` with `helloUser` uses user identity from `X-User-Identity` and returns greeting
- `tools/call` with `helloAgent` without `mcp_role` returns access-denied (HTTP 200)
- `tools/call` with `helloUser` without `mcp_role` returns access-denied (HTTP 200)
- `tools/call` with `helloUser` without `X-User-Identity` header returns 401

Mock the new identity extraction functions as needed.

**Done when**: All MCP router tests pass covering all three tools with success and access-denied paths.

---

#### Task 7.5 — Add integration tests for end-to-end dual-identity flow
Read `mcp-demo-app/tests/integration/test_agent_flow.py`. Add integration test scenarios that use the test app with realistic identity mocks:
- Call `helloAgent` with a mock agent identity that has `mcp_role: demo_agent` and verify greeting response
- Call `helloUser` with a mock user identity that has `mcp_role: demo_user` and verify greeting response
- Call `helloAgent` without the required role and verify access-denied
- Call `helloUser` without the required role and verify access-denied

**Done when**: Integration tests pass verifying the full MCP endpoint flow for all three tools.

---

### Phase 8 — Master Docs Update

#### Task 8.1 — Update master tech spec
Read `docs/master/technology/modules/mcp-demo-app/tech-spec.md`. Update per `spec-change.md` instructions:
- Add `hello_agent_tool`, `hello_user_tool` to component breakdown
- Add `verify_user_jwt`, `get_user_identity` to component breakdown
- Update TOOL_MANIFEST description to three tools
- Update MCP JSON-RPC methods table for new tools
- Add user identity JWT extraction to data access patterns
- Update code reference map with all new symbols

**Done when**: Master tech spec reflects all new components and the code reference map is accurate.

---

#### Task 8.2 — Update master test plan
Read `docs/master/qa/test-plans/mcp-demo-app-test-plan.md`. Update per `spec-change.md` instructions:
- Add unit test coverage descriptions for `hello_agent_tool` and `hello_user_tool`
- Update `tools/list` test assertions for three tools
- Add integration test scenario descriptions for dual-identity
- Update acceptance criteria coverage matrix

**Done when**: Master test plan includes coverage for all new test scenarios.

---

#### Task 8.3 — Update master product feature doc
Read `docs/master/product/features/mcp-demo-app.md`. Update per `spec-change.md` instructions:
- Extend Epic Overview to mention dual-identity validation
- Add user stories for `helloAgent` and `helloUser`
- Expand Acceptance Criteria with new tool-specific criteria
- Update Dependencies & Constraints for dual-realm requirements

**Done when**: Master product feature doc reflects the expanded tool set and dual-identity validation capability.

---

## Completion Checklist

- [x] All three tools (`helloWorld`, `helloAgent`, `helloUser`) are callable via POST /mcp
- [x] `tools/list` returns exactly three tool descriptors
- [x] `helloAgent` requires agent identity with `mcp_role: demo_agent`
- [x] `helloUser` requires user identity from `X-User-Identity` header with `mcp_role: demo_user`
- [x] Access-denied returns HTTP 200 with structured result (not HTTP error)
- [x] Missing/invalid JWTs return HTTP 401
- [x] `helloWorld` behavior is unchanged (no regression)
- [x] init.ps1 supports dual-realm setup
- [x] README has dual-identity setup and verification instructions
- [x] All unit tests pass (new tests in test_tools.py, test_auth.py, test_mcp_router.py, test_config.py)
- [x] All integration tests pass
- [x] Master docs updated (tech spec, test plan, product feature)
- [x] `.change.yaml` `agents_complete.developer` set to `true`
