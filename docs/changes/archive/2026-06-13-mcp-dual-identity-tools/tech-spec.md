# MCP Dual-Identity Tools — Technical Specification

## 1. Technical Overview

The MCP Demo App is extended from one MCP tool (`helloWorld`) to three tools (`helloWorld`, `helloAgent`, `helloUser`) to prove end-to-end dual-identity passthrough from the Communication Hub. Each new tool validates a different identity JWT — `helloAgent` validates the agent identity (from `Authorization: Bearer`), `helloUser` validates the user identity (from `X-User-Identity` header) — and enforces per-identity `mcp_role` claim-based access control. The `KeycloakClient` is extended with a second instance for the user realm to independently cache JWKS and avoid cross-realm token confusion. No database changes, no new services, and no modifications to the Communication Hub or Control Center.

---

## 2. Component Breakdown

### New Components

| Component | Responsibility |
|-----------|----------------|
| `hello_agent_tool` | Tool handler accepting agent identity claims. Checks agent's `mcp_role` claim equals `demo_agent`. Returns greeting with agent claims on success; returns access-denied result when the required role is absent. |
| `hello_user_tool` | Tool handler accepting user identity claims. Checks user's `mcp_role` claim equals `demo_user`. Returns greeting with user claims on success; returns access-denied result when the required role is absent. |
| `verify_user_jwt` | Validates a user identity JWT against the user realm's Keycloak JWKS. Follows the same pattern as `verify_agent_jwt` but uses `KEYCLOAK_USER_REALM` (falling back to `KEYCLOAK_REALM` when not configured) to compute the expected issuer. |
| `get_user_identity` | FastAPI dependency extracting the user identity JWT from the `X-User-Identity` request header. Strips the `Bearer ` prefix if present, then delegates to `verify_user_jwt` for validation. |
| `user_keycloak_client` | Second module-level `KeycloakClient` singleton dedicated to the user realm. Uses `KEYCLOAK_USER_REALM` for JWKS and token URL construction, with independent caches from the agent realm client. |

### Modified Components

| Component | Change |
|-----------|--------|
| `AppSettings` | Gains optional fields `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID`. When unset, the app defaults to using the agent realm config for user identity validation (backward-compatible single-realm mode). |
| `tool_registry` | Extended from 1 entry to 3: `helloWorld` → `hello_world_tool`, `helloAgent` → `hello_agent_tool`, `helloUser` → `hello_user_tool`. |
| `TOOL_MANIFEST` | Extended from 1 descriptor to 3. Each descriptor includes `name`, `description`, and `inputSchema`. New tool descriptions document the required identity and role. |
| `mcp_endpoint` | The `tools/call` branch now determines the required identity type from the tool name. For `helloUser`, it calls `get_user_identity`; for `helloAgent` and `helloWorld`, it calls `get_agent_identity`. The resulting identity dict is passed to the tool handler. Access-denied results from tool handlers are returned as HTTP 200 JSON-RPC success responses. |
| `init.ps1` | Gains `-UserRealm` parameter. When provided, verifies the user realm exists and writes `KEYCLOAK_USER_REALM`/`KEYCLOAK_USER_CLIENT_ID` to `.env`. Optionally creates realm roles `demo_agent` (in agent realm) and `demo_user` (in user realm). |

### Unchanged Components

| Component | Notes |
|-----------|-------|
| `hello_world_tool` | No changes. Continues to surface agent identity without role gating. |
| `KeycloakClient` | Constructor accepts optional `realm_name` parameter for multi-realm support. |
| `verify_agent_jwt` / `get_agent_identity` | Unchanged. |
| `health_router` | Unchanged. |
| `register_with_hub` | Unchanged. Hub registration at startup still syncs all tools. |
| Communication Hub | Out of scope. No changes needed. |
| Control Center | Out of scope. No changes needed. |

---

## 3. API Changes

### MCP Demo App Endpoints (mcp-demo-app/)

| Method | Path | Auth | Change |
|--------|------|------|--------|
| `POST` | `/mcp` | `Authorization: Bearer <agent JWT>` for `helloAgent`/`helloWorld`; `X-User-Identity: Bearer <user JWT>` for `helloUser` | **Modified** — new tool dispatch logic, dual identity extraction. |
| `GET` | `/health` | None | Unchanged. |

### MCP JSON-RPC Methods

| Method | Change |
|--------|--------|
| `initialize` | Unchanged. |
| `tools/list` | **Modified** — now returns three tool descriptors instead of one. |
| `tools/call` (helloWorld) | **Unchanged** — validates agent JWT only, no role gating. |
| `tools/call` (helloAgent) | **New** — validates agent JWT, gates on `mcp_role: demo_agent`. |
| `tools/call` (helloUser) | **New** — validates user JWT from `X-User-Identity` header, gates on `mcp_role: demo_user`. |

### Tool Descriptors Added

| Tool Name | Description | Required Identity | Required Role |
|-----------|-------------|-------------------|---------------|
| `helloAgent` | Greets the calling agent identity. Requires the agent to have `mcp_role` claim `demo_agent`. | Agent JWT (`Authorization: Bearer`) | `demo_agent` |
| `helloUser` | Greets the calling user identity. Requires the user to have `mcp_role` claim `demo_user`. | User JWT (`X-User-Identity: Bearer`) | `demo_user` |

### Access-Denied Response Pattern

When a tool handler detects that the required `mcp_role` claim is absent, it returns a dict with `access_denied: true` and a `reason` string. The MCP router wraps this in a normal JSON-RPC success response (HTTP 200):

- Result contains `content` with a human-readable message
- Result contains `result` with `{"access_denied": true, "reason": "..."}`
- This pattern lets callers distinguish access-denied from authentication failures (401) or server errors

### Success Response Pattern (helloAgent example)

- Result contains `content` with the serialized tool result
- Result contains `result` with `{"message": "Hello Agent!", "agent_sub": "...", "agent_realm": "...", "agent_mcp_role": "demo_agent", "agent_claims": {...}}`

---

## 4. Data Access Patterns

### Request-Scoped State

| Data | Source | Access Pattern | Used By |
|------|--------|----------------|---------|
| Agent identity claims | `Authorization: Bearer` header → `get_agent_identity` | Extracted and validated per `tools/call` request | `helloAgent`, `helloWorld` |
| User identity claims | `X-User-Identity` header → `get_user_identity` | Extracted and validated per `tools/call` request (only for `helloUser`) | `helloUser` |

### In-Memory Caches

| Data | Cache Location | TTL | Notes |
|------|---------------|-----|-------|
| Agent realm JWKS | `keycloak_client._jwks` (singleton) | 10 minutes | Unchanged from current implementation |
| User realm JWKS | `user_keycloak_client._jwks` (singleton) | 10 minutes | Independent cache from agent realm JWKS. If user realm is same as agent realm (single-realm mode), both caches may hold the same JWKS, but this is harmless. |
| Agent realm access token | `keycloak_client._access_token` | Token expiry minus 30 s buffer | Used for Hub registration at startup |
| User realm access token | `user_keycloak_client._access_token` | Token expiry minus 30 s buffer | Only used if user realm client credentials are configured |

### No Persistent State

The demo app continues to have no database or persistent storage. All tool state is derived from the incoming identity JWTs and in-memory caches.

---

## 5. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AppSettings` | class | Pydantic BaseSettings; gains `KEYCLOAK_USER_REALM`, `KEYCLOAK_USER_CLIENT_ID` | `mcp-demo-app/app/config.py` |
| `settings` | instance | Module-level `AppSettings` singleton | `mcp-demo-app/app/config.py` |
| `KeycloakClient` | class | Keycloak client credentials grant + JWKS cache (unchanged class) | `mcp-demo-app/app/auth.py` |
| `keycloak_client` | instance | Module-level KeycloakClient singleton for agent realm | `mcp-demo-app/app/auth.py` |
| `user_keycloak_client` | instance | Module-level KeycloakClient singleton for user realm (new) | `mcp-demo-app/app/auth.py` |
| `verify_agent_jwt` | function | Validates agent JWT against agent realm JWKS (unchanged) | `mcp-demo-app/app/auth.py` |
| `verify_user_jwt` | function | Validates user JWT against user realm JWKS (new) | `mcp-demo-app/app/auth.py` |
| `get_agent_identity` | function | FastAPI dependency extracting agent JWT from Authorization header (unchanged) | `mcp-demo-app/app/auth.py` |
| `get_user_identity` | function | FastAPI dependency extracting user JWT from X-User-Identity header (new) | `mcp-demo-app/app/auth.py` |
| `hello_world_tool` | function | helloWorld handler; no role gating (unchanged) | `mcp-demo-app/app/tools.py` |
| `hello_agent_tool` | function | helloAgent handler; requires mcp_role: demo_agent on agent identity (new) | `mcp-demo-app/app/tools.py` |
| `hello_user_tool` | function | helloUser handler; requires mcp_role: demo_user on user identity (new) | `mcp-demo-app/app/tools.py` |
| `tool_registry` | dict | Maps 3 tool names to handler functions (modified) | `mcp-demo-app/app/tools.py` |
| `TOOL_MANIFEST` | list | Static tool descriptor list with 3 entries (modified) | `mcp-demo-app/app/tools.py` |
| `mcp_router` | APIRouter | FastAPI router for POST /mcp (unchanged router, updated handler) | `mcp-demo-app/app/routes/mcp.py` |
| `mcp_endpoint` | function | JSON-RPC dispatcher; now extracts dual identities and routes to correct tool (modified) | `mcp-demo-app/app/routes/mcp.py` |
| `init.ps1` | script | Gains -UserRealm parameter and role creation (modified) | `mcp-demo-app/init.ps1` |
| `README.md` | document | Dual-identity setup docs, env var table, curl examples (modified) | `mcp-demo-app/README.md` |
| `test_tools.py` | test file | Unit tests for new tool handlers and updated registry/manifest (modified) | `mcp-demo-app/tests/unit/test_tools.py` |
| `test_auth.py` | test file | Unit tests for verify_user_jwt and get_user_identity (modified) | `mcp-demo-app/tests/unit/test_auth.py` |
| `test_mcp_router.py` | test file | Unit tests for dual-identity dispatch and access-denied responses (modified) | `mcp-demo-app/tests/unit/test_mcp_router.py` |
| `test_agent_flow.py` | test file | Integration tests for end-to-end dual-identity flow (modified) | `mcp-demo-app/tests/integration/test_agent_flow.py` |
| `test_hub_registration.py` | test file | Integration tests for Hub registration syncing 3 tools (modified) | `mcp-demo-app/tests/integration/test_hub_registration.py` |
| `test_startup.py` | test file | Integration tests for app startup with dual-realm config (modified) | `mcp-demo-app/tests/integration/test_startup.py` |
| `test_config.py` | test file | Unit tests for AppSettings new optional fields and fallback (modified) | `mcp-demo-app/tests/unit/test_config.py` |
| `conftest.py` | test config | Pytest configuration with env var defaults for tests (modified) | `mcp-demo-app/tests/conftest.py` |
| `.env.example` | config template | Gains commented entries for KEYCLOAK_USER_REALM, KEYCLOAK_USER_CLIENT_ID (modified) | `mcp-demo-app/.env.example` |
| `ToolCallRequest.user_jwt` | field | User identity JWT forwarded to CH tool routing (new) | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `cache_user_jwt` | function | Stores user JWT by session ID for dual-identity forwarding (new) | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `get_user_jwt` | function | Retrieves cached user JWT by session ID (new) | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `McpProxyRequest.user_jwt` | field | User JWT forwarded to Control Center proxy (new) | `backend/app/api/v1/internal/mcp_proxy.py` |
| `McpProxyEngine.call_tool` | method | Gains `user_jwt` parameter for dual-identity forwarding (modified) | `backend/app/services/mcp/proxy.py` |
| `_build_auth_headers` | method | Sets `X-User-Identity` header for user JWT on passthrough sessions (modified) | `backend/app/services/mcp/proxy.py` |
| `websocket_chat` | function | Caches user JWT from WebSocket query param for tool calls (modified) | `backend/app/api/ws/chat.py` |
| `require_permission` | function | Added debug logging for permission check diagnostics (modified) | `backend/app/api/deps.py` |
| `init-local-dev.py` | script | Test agent identities, `mcp_role` claim mappers, user profile, offline_access, volume persistence (modified) | `scripts/init-local-dev.py` |
| `docker-compose.yml` | config | Keycloak data persistence volume (modified) | `docker-compose.yml` |
| `toDelegationSnippetLine` | function | Removed `using_tool` from delegation snippets (modified) | `frontend/src/hooks/useChatSession.ts` |
