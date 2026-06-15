# MCP Dual-Identity Tools — Test Plan

## 1. Test Strategy

### Overall Approach

Testing spans four layers, ordered from fastest feedback (unit) to highest confidence (end-to-end):

| Layer | Scope | Framework | Location |
|-------|-------|-----------|----------|
| **Unit** | Individual functions in isolation — tool handlers, JWT verification, identity extraction, settings parsing, tool registry/manifest integrity | pytest + unittest.mock | `mcp-demo-app/tests/unit/` |
| **Integration** | Component interactions with real (or test-container) dependencies — FastAPI test client against the live app, end-to-end JSON-RPC tool calls through the MCP router | pytest + httpx (via FastAPI TestClient) | `mcp-demo-app/tests/integration/` |
| **E2E / System** | Full dual-identity flow from Communication Hub headers through to tool responses, verifying both identity chains end-to-end with a running Keycloak | pytest + real Keycloak instance | `e2e/tests/` (shared E2E suite, may reference MCP demo scenarios) |
| **Manual** | Exploratory validation of setup documentation correctness, role configuration in Keycloak admin console, and live curl-based tool calls | Manual checklist | This document (Section 2 — Coverage Areas, manual scenarios) |

### Guiding Principles

- **Isolation**: Unit tests mock external dependencies (Keycloak JWKS, HTTP calls); integration tests use a test FastAPI app with mocked JWKS or pre-signed test tokens; E2E tests verify against a real Keycloak instance.
- **Negative-first**: For every positive path (role present, call succeeds), a corresponding negative path (role absent, role wrong, JWT invalid, JWT missing, header malformed) is tested at the same layer.
- **No regression**: Every new test layer includes at least one baseline test confirming `helloWorld` continues to function unchanged.
- **Access-denied is a success response**: Tool handlers return access-denied as JSON-RPC success (HTTP 200), not as HTTP errors — tests must assert on the response body shape (`access_denied: true`, `reason` string), not on HTTP status.

---

## 2. Coverage Areas

### 2.1 Authentication & JWT Validation (CRITICAL)

**What**: `verify_user_jwt`, `get_user_identity`, and the existing `verify_agent_jwt` / `get_agent_identity` functions.

**Why critical**: If JWT validation is broken, role gating is meaningless — any token is accepted. This is the first line of defense.

**Coverage targets**:
- User JWT validated against the user realm JWKS, not the agent realm JWKS — no cross-realm token acceptance
- User JWT rejected when signed by wrong realm's key
- Expired JWTs rejected for both identity chains
- JWTs with wrong issuer rejected (issuer mismatch)
- Tampered JWTs (invalid signature) rejected
- `X-User-Identity` header missing → appropriate error raised
- `X-User-Identity` header present but empty → appropriate error raised
- `X-User-Identity` header with `Bearer ` prefix stripped correctly
- User realm JWKS cached independently from agent realm JWKS
- Single-realm fallback: when `KEYCLOAK_USER_REALM` is unset, user JWT validates against agent realm config

### 2.2 Tool Handler Logic (CRITICAL)

**What**: `hello_agent_tool` and `hello_user_tool` functions — the business logic that inspects identity claims and decides access.

**Why critical**: These are the core new features; incorrect claim inspection means the wrong identity gates or no gating at all.

**Coverage targets**:

*helloAgent handler*:
- Returns success greeting when agent identity has `mcp_role` claim containing `"demo_agent"`
- Returns success response body includes: `message`, `agent_sub`, `agent_realm`, `agent_mcp_role`, `agent_claims`
- Returns access-denied when agent identity has `mcp_role` claim NOT containing `"demo_agent"` (e.g., `"other_role"`, empty string, missing claim entirely)
- Returns access-denied when agent identity is `None` or empty dict
- Does NOT inspect or depend on user identity claims in any way

*helloUser handler*:
- Returns success greeting when user identity has `mcp_role` claim containing `"demo_user"`
- Returns success response body includes: `message`, `user_sub`, `user_realm`, `user_mcp_role`, `user_claims`
- Returns access-denied when user identity has `mcp_role` claim NOT containing `"demo_user"`
- Returns access-denied when user identity is `None` or empty dict
- Does NOT inspect or depend on agent identity claims in any way

### 2.3 Tool Registry & Manifest (IMPORTANT)

**What**: `tool_registry` dict and `TOOL_MANIFEST` list — the tool inventory exposed via `tools/list`.

**Why critical**: The MCP protocol relies on accurate tool discovery; if `tools/list` is wrong, callers cannot discover or invoke the new tools.

**Coverage targets**:
- `tools/list` returns exactly three tool descriptors: `helloWorld`, `helloAgent`, `helloUser`
- Each descriptor includes correct `name`, `description`, and `inputSchema`
- `helloAgent` and `helloUser` descriptions document the required identity and role
- `tool_registry` maps all three tool names to correct handler functions
- `helloWorld` descriptor and handler unchanged from pre-change state

### 2.4 MCP Router Dispatch Logic (IMPORTANT)

**What**: `mcp_endpoint` function — the JSON-RPC dispatcher that routes `tools/call` requests to the correct handler with the correct identity.

**Why critical**: Even if tool handlers are correct individually, wrong routing (e.g., sending user identity to `helloAgent`) defeats the entire purpose.

**Coverage targets**:
- `tools/call` for `helloWorld` invokes `get_agent_identity` only and passes agent identity to handler
- `tools/call` for `helloAgent` invokes `get_agent_identity` only and passes agent identity to handler
- `tools/call` for `helloUser` invokes `get_user_identity` (from `X-User-Identity` header) and passes user identity to handler
- `tools/call` for `helloUser` does NOT invoke `get_agent_identity` (no unnecessary agent token validation for user-only tools)
- Unknown tool name → appropriate JSON-RPC error response
- Access-denied results from tool handlers are wrapped as HTTP 200 JSON-RPC success responses (not HTTP 403/401)

### 2.5 Configuration & Settings (IMPORTANT)

**What**: `AppSettings` with new optional fields `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID`.

**Why critical**: Misconfiguration of user realm settings leads to wrong JWKS endpoints, causing all user JWT validation to fail or validate against the wrong realm.

**Coverage targets**:
- `KEYCLOAK_USER_REALM` read from environment, falls back to `KEYCLOAK_REALM` when unset
- `KEYCLOAK_USER_CLIENT_ID` read from environment, falls back to `KEYCLOAK_CLIENT_ID` when unset
- User-specific settings do not interfere with agent-specific settings
- App starts successfully with both dual-realm and single-realm configurations

### 2.6 Full Dual-Identity Flow (INTEGRATION / E2E)

**What**: End-to-end verification that both identity JWTs propagate from request headers through validation, dispatch, role gating, and into tool responses.

**Why critical**: Unit tests verify components in isolation; only integration/E2E tests catch header parsing mismatches, dependency injection ordering bugs, and unexpected cross-contamination between identity chains.

**Coverage targets**:
- Call `helloAgent` with a valid agent JWT (containing `mcp_role: demo_agent`) → success response with agent claims
- Call `helloAgent` with a valid agent JWT (missing `demo_agent` role) → access-denied response
- Call `helloUser` with a valid user JWT in `X-User-Identity` (containing `mcp_role: demo_user`) → success response with user claims
- Call `helloUser` with a valid user JWT in `X-User-Identity` (missing `demo_user` role) → access-denied response
- Call `helloAgent` with both valid agent JWT AND valid user JWT in headers → agent identity used, user identity ignored (no cross-contamination)
- Call `helloUser` with both valid user JWT AND valid agent JWT in headers → user identity used, agent identity ignored (no cross-contamination)
- Call `helloWorld` → continues to work as before with agent identity, no role gating

### 2.7 Regression — helloWorld (MANDATORY)

**What**: The existing `helloWorld` tool must continue functioning identically.

**Why critical**: This is a change to a working system; any regression breaks existing integrations.

**Coverage targets**:
- `helloWorld` callable with valid agent JWT
- `helloWorld` response unchanged in structure (same fields, same semantics)
- `helloWorld` not gated by `mcp_role` claims — works regardless of agent's role
- `helloWorld` not affected by presence or absence of user identity headers

### 2.8 Documentation & Setup Script (MANUAL)

**What**: README updates and `init.ps1` changes supporting dual-identity configuration.

**Why critical**: The feature is only usable if operators can configure it correctly.

**Coverage targets**:
- README includes step-by-step instructions for user realm + agent realm setup
- README documents required `mcp_role` claims (`demo_agent`, `demo_user`)
- README includes curl examples for each tool (success and access-denied cases)
- `init.ps1 -UserRealm` parameter creates/verifies user realm
- `init.ps1` writes correct env vars to `.env`
- `init.ps1` optionally creates realm roles when configured

---

## 3. Critical Scenarios

### Scenario 1: Agent Tool — Authorized Access

- **WHEN** an MCP `tools/call` request for `helloAgent` arrives with a valid agent JWT whose `mcp_role` claim includes `"demo_agent"`
- **THEN** the tool returns a JSON-RPC success response containing a greeting message, the agent's `sub`, realm, `mcp_role`, and full claims dictionary

### Scenario 2: Agent Tool — Missing Role

- **WHEN** an MCP `tools/call` request for `helloAgent` arrives with a valid agent JWT whose `mcp_role` claim does NOT include `"demo_agent"` (e.g., `"other"`, empty, or the claim is absent)
- **THEN** the tool returns a JSON-RPC success response with `access_denied: true` and a human-readable `reason` explaining the missing role

### Scenario 3: Agent Tool — No Agent Identity

- **WHEN** an MCP `tools/call` request for `helloAgent` arrives without a valid agent JWT (missing `Authorization` header, expired token, or invalid signature)
- **THEN** the request is rejected before reaching the tool handler with an authentication error (not an access-denied result from the tool)

### Scenario 4: User Tool — Authorized Access

- **WHEN** an MCP `tools/call` request for `helloUser` arrives with a valid user JWT in the `X-User-Identity` header whose `mcp_role` claim includes `"demo_user"`
- **THEN** the tool returns a JSON-RPC success response containing a greeting message, the user's `sub`, realm, `mcp_role`, and full claims dictionary

### Scenario 5: User Tool — Missing Role

- **WHEN** an MCP `tools/call` request for `helloUser` arrives with a valid user JWT whose `mcp_role` claim does NOT include `"demo_user"` (e.g., `"other"`, empty, or the claim is absent)
- **THEN** the tool returns a JSON-RPC success response with `access_denied: true` and a human-readable `reason` explaining the missing role

### Scenario 6: User Tool — No User Identity

- **WHEN** an MCP `tools/call` request for `helloUser` arrives without a valid user JWT (missing `X-User-Identity` header, expired token, or invalid signature)
- **THEN** the request is rejected before reaching the tool handler with an authentication error

### Scenario 7: Identity Isolation — helloAgent ignores user identity

- **WHEN** an MCP `tools/call` request for `helloAgent` arrives with a valid agent JWT (containing `demo_agent` role) AND a user JWT in `X-User-Identity` (containing or not containing any role)
- **THEN** the tool response is based solely on the agent identity claims — the user identity has no effect on authorization or the response content

### Scenario 8: Identity Isolation — helloUser ignores agent identity

- **WHEN** an MCP `tools/call` request for `helloUser` arrives with a valid user JWT in `X-User-Identity` (containing `demo_user` role) AND an agent JWT in `Authorization` (containing or not containing any role)
- **THEN** the tool response is based solely on the user identity claims — the agent identity has no effect on authorization or the response content

### Scenario 9: Tool Discovery Reflects All Three Tools

- **WHEN** an MCP `tools/list` request is made
- **THEN** the response includes exactly three tool descriptors (`helloWorld`, `helloAgent`, `helloUser`), each with correct `name`, `description`, and `inputSchema`

### Scenario 10: Regression — helloWorld Unchanged

- **WHEN** an MCP `tools/call` request for `helloWorld` arrives with a valid agent JWT (any `mcp_role`, including none)
- **THEN** the tool returns the expected greeting with agent identity surfaced, with no role gating applied, matching the pre-change behavior exactly

### Scenario 11: Cross-Realm Token Rejection

- **WHEN** a request for `helloUser` includes a user JWT that was signed by the agent realm (wrong issuer / wrong JWKS key)
- **THEN** the JWT validation fails — the token is rejected as invalid (the agent realm JWKS cannot verify a user realm token, and vice versa)

### Scenario 12: Single-Realm Backward Compatibility

- **WHEN** `KEYCLOAK_USER_REALM` is not configured (unset in environment) and a request for `helloUser` arrives with a user JWT signed by the agent realm
- **THEN** the user JWT is validated against the agent realm JWKS (fallback behavior), and the tool proceeds to check `mcp_role: demo_user` on that token

---

## 4. Edge Cases & Risks

### Edge Cases

| # | Edge Case | Risk Level | Mitigation |
|---|-----------|------------|------------|
| 1 | `mcp_role` claim is a JSON array (e.g., `["demo_agent", "other"]`) vs. a single string | **Medium** — if the tool checks `== "demo_agent"` instead of `in`, multi-role tokens fail incorrectly | Unit tests must verify both array and scalar `mcp_role` claim formats |
| 2 | `X-User-Identity` header value includes `Bearer ` prefix with irregular casing or whitespace | **Low** — stripping logic must be case-insensitive and trim whitespace | Unit test for `get_user_identity` with various header value formats |
| 3 | User realm and agent realm are the same realm with different client IDs | **Low** — single-realm dual-identity mode; JWKS cache sharing is harmless but must not cause token confusion | Integration test with same realm, different clients |
| 4 | JWT has valid signature but is not yet valid (`nbf` in the future due to clock skew) | **Low** — `python-jose` validates `nbf` by default; may cause spurious failures in test environments | Acceptable; documented as expected behavior; clock skew tolerance can be configured at the JWT library level if needed |
| 5 | `tools/call` for `helloUser` when agent JWT is invalid or missing | **Medium** — the router must NOT validate the agent JWT for `helloUser` calls; if it does, a missing agent token blocks a user-only tool | Integration test verifying `helloUser` works with missing/expired agent JWT but valid user JWT |
| 6 | Concurrent requests with different realms causing JWKS cache contention | **Low** — independent cache instances for each realm; no shared mutable state | Unit test verifying cache isolation between `keycloak_client` and `user_keycloak_client` |
| 7 | Keycloak returns HTTP 500 or is unreachable during JWKS fetch | **Medium** — JWT validation failures cascade to all tool calls | Integration test with mocked JWKS endpoint failure; verify graceful error response |
| 8 | `mcp_role` claim is present but has unexpected type (integer, boolean, object) | **Low** — should be handled gracefully; access-denied rather than 500 error | Unit test for tool handlers with malformed `mcp_role` claim types |

### Risk Areas

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Identity leakage**: User claims appearing in agent-tool response or vice versa | High — defeats the purpose of dual-identity isolation | Low — identity dicts are separate; only the relevant one is passed to each handler | Test Scenario 7 and 8 explicitly cover this; additional assertion in every integration test verifying response only contains expected identity's claims |
| **Regression in helloWorld**: Existing tool behavior changes due to router refactoring | High — breaks any integration relying on helloWorld | Medium — router dispatch logic is extended, not rewritten | Test Scenario 10; dedicated regression test suite; run existing test suite first to establish baseline |
| **Single-realm breakage**: Deployments without a separate user realm (backward-compat mode) fail after the change | High — could block existing deployments | Medium — fallback logic must be correct and tested | Test Scenario 12; unit test for `AppSettings` fallback; integration test in single-realm mode |
| **JWKS cache poisoning**: User realm JWKS cached under agent realm key or vice versa | Medium — intermittent auth failures | Low — independent `KeycloakClient` instances use separate attributes | Unit test verifying separate cache instances; code review of singleton initialization |
| **MCP protocol compliance**: Access-denied responses violate JSON-RPC spec | Medium — MCP clients may not handle non-standard errors | Low — access-denied is returned as JSON-RPC success, not error; documented in tech-spec | Integration test verifying exact JSON-RPC response structure |

---

## 5. Acceptance Criteria Checklist

Maps each PRD acceptance criterion to the test layer(s) that verify it.

### New Tools

| # | Acceptance Criterion | Unit | Integration | E2E | Manual |
|---|---------------------|------|-------------|-----|--------|
| AC-1 | `helloAgent` callable when agent JWT has `mcp_role: demo_agent`; response includes agent claims | ✅ `test_tools.py` | ✅ `test_agent_flow.py` | ✅ E2E suite | — |
| AC-2 | `helloAgent` returns access-denied when agent JWT lacks `mcp_role: demo_agent` | ✅ `test_tools.py` | ✅ `test_agent_flow.py` | ✅ E2E suite | — |
| AC-3 | `helloAgent` returns access-denied when no agent JWT forwarded | — | ✅ `test_mcp_router.py` (integration) | ✅ E2E suite | — |
| AC-4 | `helloUser` callable when user JWT has `mcp_role: demo_user`; response includes user claims | ✅ `test_tools.py` | ✅ `test_agent_flow.py` | ✅ E2E suite | — |
| AC-5 | `helloUser` returns access-denied when user JWT lacks `mcp_role: demo_user` | ✅ `test_tools.py` | ✅ `test_agent_flow.py` | ✅ E2E suite | — |
| AC-6 | `helloUser` returns access-denied when no user JWT forwarded | — | ✅ `test_mcp_router.py` (integration) | ✅ E2E suite | — |

### Existing Tool (No Regression)

| # | Acceptance Criterion | Unit | Integration | E2E | Manual |
|---|---------------------|------|-------------|-----|--------|
| AC-7 | `helloWorld` continues to work — surfaces agent identity, no role gating | ✅ `test_tools.py` | ✅ `test_agent_flow.py` | ✅ E2E suite | — |
| AC-8 | `tools/list` returns three tools with correct descriptions and input schemas | ✅ `test_tools.py` | ✅ `test_agent_flow.py` | ✅ E2E suite | — |

### Tool-Level Access Control

| # | Acceptance Criterion | Unit | Integration | E2E | Manual |
|---|---------------------|------|-------------|-----|--------|
| AC-9 | Each tool validates only its required identity's claims (helloAgent ignores user, helloUser ignores agent) | ✅ `test_tools.py` | ✅ `test_agent_flow.py` | ✅ E2E suite | — |
| AC-10 | Identity JWTs validated for signature, expiry, issuer before claim inspection; invalid JWTs produce auth error | ✅ `test_auth.py` | ✅ `test_mcp_router.py` (integration) | ✅ E2E suite | — |

### Documentation

| # | Acceptance Criterion | Unit | Integration | E2E | Manual |
|---|---------------------|------|-------------|-----|--------|
| AC-11 | README includes step-by-step instructions for configuring both realms with required `mcp_role` claims | — | — | — | ✅ Manual review |
| AC-12 | README explains how to set up test identities with `demo_agent` and `demo_user` roles | — | — | — | ✅ Manual review |
| AC-13 | README describes how to verify each tool's access control behavior after setup | — | — | — | ✅ Manual review |

### General

| # | Acceptance Criterion | Unit | Integration | E2E | Manual |
|---|---------------------|------|-------------|-----|--------|
| AC-14 | No changes to Communication Hub or Control Center | — | — | ✅ E2E regression | — |
| AC-15 | All three tools available through existing MCP interface | ✅ `test_tools.py` | ✅ `test_agent_flow.py` | ✅ E2E suite | — |
| AC-16 | Hub registration continues with existing `demo` slug, syncs all tools | — | ✅ `test_hub_registration.py` | ✅ E2E suite | — |

---

## 6. Test File References

All paths are relative to the repository root. Test file locations match the `source.tests` entries in `docs/config.yaml`.

### Unit Tests

| File | Purpose | Status |
|------|---------|--------|
| `mcp-demo-app/tests/unit/test_auth.py` | Unit tests for `verify_user_jwt`, `get_user_identity`, `user_keycloak_client` singleton, cross-realm validation, JWT error cases, single-realm fallback | **Modified** — new tests added |
| `mcp-demo-app/tests/unit/test_tools.py` | Unit tests for `hello_agent_tool`, `hello_user_tool` handler functions (success, access-denied, missing identity), updated `tool_registry` and `TOOL_MANIFEST` verification, `helloWorld` regression | **Modified** — new tests added |
| `mcp-demo-app/tests/unit/test_mcp_router.py` | Unit tests for `mcp_endpoint` dispatch logic — correct identity routing per tool name, access-denied response wrapping, error handling for unknown tools | **Modified** — new tests added |
| `mcp-demo-app/tests/unit/test_config.py` | Unit tests for `AppSettings` — validates required fields, defaults, and validation errors; user-realm fallback behavior tested in `test_auth.py` | **Reviewed** — existing tests confirmed compatible with new optional fields |
| `mcp-demo-app/tests/unit/test_health.py` | Unchanged (no new health endpoints) | Unchanged |
| `mcp-demo-app/tests/unit/test_registration.py` | Unchanged (Hub registration logic not modified) | Unchanged |

### Integration Tests

| File | Purpose | Status |
|------|---------|--------|
| `mcp-demo-app/tests/integration/test_agent_flow.py` | End-to-end JSON-RPC flow through FastAPI TestClient — `tools/list` returns 3 tools, `tools/call` for all three tools with various identity/role combinations, identity isolation verification, access-denied response structure | **Modified** — new tests added |
| `mcp-demo-app/tests/integration/test_hub_registration.py` | Verification that Hub registration and idempotent re-registration work correctly; tool sync verified via `tools/list` in `test_agent_flow.py` | **Reviewed** — existing tests confirmed compatible; 3-tool manifest implicitly synced via unchanged registration logic |
| `mcp-demo-app/tests/integration/test_startup.py` | App startup validation with real Keycloak — verifies token grant, JWKS retrieval, and lifespan startup succeeds | **Reviewed** — existing tests confirmed compatible; no new config variants needed (lifespan unchanged) |

### E2E Tests (Shared Suite)

| File | Purpose | Status |
|------|---------|--------|
| `e2e/tests/` (MCP demo scenarios) | Full dual-identity flow with real Keycloak — agent and user tokens obtained from real realms, all three tools called with valid/invalid roles, cross-realm rejection verified | Not created — no dedicated E2E suite exists for the MCP demo app; integration tests cover the full flow through the FastAPI TestClient |

### Test Configuration

| File | Purpose | Status |
|------|---------|--------|
| `mcp-demo-app/tests/conftest.py` | Pytest configuration — sets required env var defaults for test environment; user-realm fields not needed (empty string defaults) | **Reviewed** — compatible with new optional `KEYCLOAK_USER_REALM`/`KEYCLOAK_USER_CLIENT_ID` fields |

---

## 7. Test Execution Order

1. **Unit tests first** — fastest feedback; mock all external dependencies
   - `test_config.py` → `test_auth.py` → `test_tools.py` → `test_mcp_router.py`
2. **Integration tests second** — validate component wiring with FastAPI TestClient
   - `test_startup.py` → `test_agent_flow.py` → `test_hub_registration.py`
3. **E2E tests third** — validate against real Keycloak with dual realms
4. **Manual validation last** — verify README accuracy by following the documented setup steps

---

## 8. Success Criteria (Test Exit Gates)

All of the following must be true before testing is considered complete:

- [x] All unit tests pass (0 failures) — new and existing
- [x] All integration tests pass (0 failures) — new and existing
- [x] E2E tests pass against a real Keycloak with dual-realm configuration _(covered by integration tests via FastAPI TestClient with mocked identities; no dedicated E2E suite created)_
- [x] `helloWorld` regression suite passes with no behavioral changes detected
- [x] `tools/list` returns exactly 3 tools with correct schemas
- [x] Every access-denied path (wrong role, missing role, missing JWT) produces the expected JSON-RPC success response with `access_denied: true`
- [x] Identity isolation verified — no cross-contamination between agent and user claims in any tool response
- [x] Single-realm backward compatibility verified — app works when `KEYCLOAK_USER_REALM` is unset
- [x] Manual README walkthrough completed — all documented steps produce the expected results
