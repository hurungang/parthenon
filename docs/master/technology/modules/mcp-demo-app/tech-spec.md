# Tech Spec: mcp-demo-app

## 1. Technical Overview

The MCP Demo App is a standalone Python FastAPI service (`mcp-demo-app/`) that lives outside the main Parthenon codebase. It authenticates with the Keycloak `ai_agents` realm using the OAuth2 client credentials grant, registers itself with the Parthenon MCP Hub under the slug `demo`, and exposes three MCP tools (`helloWorld`, `helloAgent`, `helloUser`) via a JSON-RPC 2.0 endpoint. On every tool invocation it validates the forwarded identity JWT against the appropriate Keycloak realm's JWKS and enforces per-identity `mcp_role`-based access control — proving the end-to-end dual-identity propagation pattern where both agent and user identities are forwarded by the Communication Hub.

There are no database dependencies, no frontend changes, and no modifications to existing Parthenon backend code. The only integration with the main codebase is a service entry in `docker-compose.yml` and calls to the existing Hub registration endpoints at startup.

---

## 2. Component Breakdown

| Component | Responsibility |
|-----------|----------------|
| `AppSettings` | Reads all configuration from environment variables (Keycloak URL, realm, client credentials, Hub URL, app URL, slug, and optional user realm config). Single source of truth for runtime config. |
| `KeycloakClient` | Encapsulates all Keycloak HTTP interactions: client credentials token grant (with expiry-aware cache), and JWKS fetch (with 10-minute cache). Accepts an optional `realm_name` to support multiple realm instances. |
| `keycloak_client` | Module-level `KeycloakClient` singleton for the agent realm. Used for agent JWT validation and obtaining the app's own access token. |
| `user_keycloak_client` | Second module-level `KeycloakClient` singleton for the user realm. Maintains independent JWKS and token caches. Falls back to the agent realm when `KEYCLOAK_USER_REALM` is not configured (single-realm backward compatibility). |
| `verify_agent_jwt` | Validates a forwarded agent JWT against the agent realm's JWKS. Checks signature, expiry, and issuer. Returns decoded claims on success. |
| `verify_user_jwt` | Validates a forwarded user JWT against the user realm's JWKS. Follows the same pattern as `verify_agent_jwt` but uses `user_keycloak_client` and computes the expected issuer from `KEYCLOAK_USER_REALM` (falling back to `KEYCLOAK_REALM`). |
| `get_agent_identity` | FastAPI dependency that extracts and validates the `Authorization: Bearer` token from each request. |
| `get_user_identity` | FastAPI dependency that extracts and validates the user JWT from the `X-User-Identity: Bearer` header. |
| `hello_world_tool` | Tool handler function. Accepts the validated agent identity claims and returns a greeting response that includes the agent's `sub` claim. No role gating. |
| `hello_agent_tool` | Tool handler function. Accepts agent identity claims and checks that `mcp_role` equals `"demo_agent"`. Returns a greeting with agent claims on success; returns a structured access-denied result when the role is absent. |
| `hello_user_tool` | Tool handler function. Accepts user identity claims and checks that `mcp_role` equals `"demo_user"`. Returns a greeting with user claims on success; returns a structured access-denied result when the role is absent. |
| `tool_registry` | In-memory mapping of three MCP tool name strings to their handler functions: `helloWorld`, `helloAgent`, `helloUser`. |
| `TOOL_MANIFEST` | Static list of three MCP tool descriptors (name, description, input JSON schema). Published via `tools/list`. |
| `register_with_hub` | Startup function that registers the demo app with the Parthenon Hub (`POST /api/v1/mcp/servers`) and triggers a tool sync (`POST .../sync`). Handles 409 idempotently. |
| `mcp_router` | FastAPI `APIRouter` handling `POST /mcp`. Dispatches JSON-RPC method calls to `initialize`, `tools/list`, and `tools/call` handlers. For `tools/call`, determines whether to extract agent identity (`helloWorld`, `helloAgent`) or user identity (`helloUser`) based on the tool name. |
| `health_router` | FastAPI `APIRouter` handling `GET /health`. Returns `{"status": "ok", "slug": "demo"}`. No auth required. |
| `create_app` | FastAPI application factory. Configures the lifespan handler (Keycloak token validation + Hub registration on startup) and mounts routers. |
| `lifespan` | Async context manager. Validates Keycloak connectivity and triggers Hub registration on startup; exits the process on failure. |

### Backend Pipeline Components (Communication Hub / Control Center / Frontend)

These are changes in the main Parthenon codebase that support the dual-identity propagation pattern end-to-end. The Communication Hub caches and forwards the user JWT alongside the agent JWT during tool calls. The Control Center proxy engine passes dual identities through to the MCP Demo App. The frontend WebSocket chat sends the user JWT as a query parameter for the Hub to cache.

| Component | Responsibility |
|-----------|----------------|
| `ToolCallRequest.user_jwt` | New field on the CH tool routing request model carrying the user identity JWT alongside the agent JWT. |
| `cache_user_jwt` | Stores the user JWT by WebSocket session ID when a chat connection is established. |
| `get_user_jwt` | Retrieves the cached user JWT from the session store when a tool call is being routed. |
| `McpProxyRequest.user_jwt` | New field on the CC internal proxy request carrying the user JWT to the MCP Hub proxy engine. |
| `McpProxyEngine.call_tool` | Gains a `user_jwt` parameter forwarded from the CH through the CC proxy layer. |
| `_build_auth_headers` | Sets the `X-User-Identity` HTTP header with the user JWT when the session is a user-passthrough session. |
| `websocket_chat` | WebSocket endpoint handler that extracts and caches the user JWT from the `?user_token=` query parameter. |
| `require_permission` | Added debug logging for permission check diagnostics during tool-call authorization. |
| `toDelegationSnippetLine` | Removed `using_tool` from delegation summary snippets (frontend `useChatSession` hook). |

---

## 3. API Endpoints

These endpoints are served by the standalone `mcp-demo-app` service, not the Parthenon backend.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/mcp` | `Authorization: Bearer <agent JWT>` required for `helloWorld`/`helloAgent`; `X-User-Identity: Bearer <user JWT>` required for `helloUser`; optional for `initialize` and `tools/list` | MCP JSON-RPC 2.0 endpoint. Dispatches `initialize`, `tools/list`, and `tools/call` methods. |
| `GET` | `/health` | None | Health check. Returns `{"status": "ok", "slug": "demo"}` with HTTP 200. |

### MCP JSON-RPC Methods

| Method | Description |
|--------|-------------|
| `initialize` | Returns server capabilities, protocol version, and server info. |
| `tools/list` | Returns array of three tool descriptors from `TOOL_MANIFEST`: `helloWorld`, `helloAgent`, `helloUser`. |
| `tools/call` (`helloWorld`) | Returns `{"message": "...", "agent_sub": "<sub>", "agent_claims": {...}}`. Validates agent JWT only, no role gating. |
| `tools/call` (`helloAgent`) | Returns `{"message": "Hello Agent!", "agent_sub": "...", "agent_realm": "...", "agent_mcp_role": "demo_agent", "agent_claims": {...}}` on success. Returns `{"access_denied": true, "reason": "..."}` (HTTP 200) when the agent lacks `mcp_role: demo_agent`. |
| `tools/call` (`helloUser`) | Returns `{"message": "Hello User!", "user_sub": "...", "user_realm": "...", "user_mcp_role": "demo_user", "user_claims": {...}}` on success. Returns `{"access_denied": true, "reason": "..."}` (HTTP 200) when the user lacks `mcp_role: demo_user`. |

Unknown methods return JSON-RPC error code `-32601` (Method not found).

### Existing Parthenon Backend — No Changes

No new endpoints are added to or removed from the Parthenon backend API. The Hub registration is performed by the demo app calling the existing `POST /api/v1/mcp/servers` and `POST /api/v1/mcp/servers/{id}/sync` endpoints at startup.

---

## 4. Data Access Patterns

The demo app has no persistent data store. All state is held in-memory for the lifetime of the process.

| Data | Access Pattern | Notes |
|------|----------------|-------|
| Own access token | In-memory cache in `keycloak_client` | Refreshed automatically ~30 s before expiry via client credentials grant against the agent realm |
| Agent realm JWKS | In-memory cache in `keycloak_client` | Re-fetched every 10 minutes via `GET {KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs` |
| User realm JWKS | In-memory cache in `user_keycloak_client` | Independent cache from agent realm JWKS. Re-fetched every 10 minutes via `GET {KEYCLOAK_URL}/realms/{KEYCLOAK_USER_REALM}/protocol/openid-connect/certs`. Falls back to agent realm when `KEYCLOAK_USER_REALM` is not configured. |
| Hub server record | Written once at startup via `POST /api/v1/mcp/servers` | Idempotent — 409 is handled by looking up the existing record |
| Tool manifest | Static in-process constant (`TOOL_MANIFEST`) — three tools | Published to the Hub via the standard MCP `tools/list` response during tool sync |
| Agent identity claims | Request-scoped; extracted from `Authorization: Bearer` header | Validated per `tools/call` request for `helloWorld` and `helloAgent` |
| User identity claims | Request-scoped; extracted from `X-User-Identity: Bearer` header | Validated per `tools/call` request for `helloUser` |

All outbound HTTP calls use `httpx.AsyncClient` with async/await.

---

## 5. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AppSettings` | class | Pydantic BaseSettings for all env-var configuration including optional `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID` | `mcp-demo-app/app/config.py` |
| `settings` | instance | Module-level `AppSettings` singleton | `mcp-demo-app/app/config.py` |
| `KeycloakClient` | class | Keycloak client credentials grant + JWKS cache; accepts optional `realm_name` parameter for multi-realm support | `mcp-demo-app/app/auth.py` |
| `keycloak_client` | instance | Module-level `KeycloakClient` singleton for the agent realm; Keycloak connectivity validated during lifespan startup | `mcp-demo-app/app/auth.py` |
| `user_keycloak_client` | instance | Module-level `KeycloakClient` singleton for the user realm; maintains independent JWKS and token caches | `mcp-demo-app/app/auth.py` |
| `verify_agent_jwt` | function | Validates agent JWT against agent realm JWKS; returns decoded claims | `mcp-demo-app/app/auth.py` |
| `verify_user_jwt` | function | Validates user JWT against user realm JWKS; returns decoded claims; raises HTTPException(401) on failure | `mcp-demo-app/app/auth.py` |
| `get_agent_identity` | function | FastAPI dependency; extracts and validates bearer token from `Authorization` header | `mcp-demo-app/app/auth.py` |
| `get_user_identity` | function | FastAPI dependency; extracts and validates bearer token from `X-User-Identity` header | `mcp-demo-app/app/auth.py` |
| `hello_world_tool` | function | `helloWorld` tool handler; returns greeting with agent `sub` claim (no role gating) | `mcp-demo-app/app/tools.py` |
| `hello_agent_tool` | function | `helloAgent` tool handler; checks agent identity for `mcp_role: demo_agent` | `mcp-demo-app/app/tools.py` |
| `hello_user_tool` | function | `helloUser` tool handler; checks user identity for `mcp_role: demo_user` | `mcp-demo-app/app/tools.py` |
| `tool_registry` | dict | Maps 3 MCP tool name strings to handler functions | `mcp-demo-app/app/tools.py` |
| `TOOL_MANIFEST` | list | Static MCP tool descriptor list (3 entries) published via `tools/list` | `mcp-demo-app/app/tools.py` |
| `register_with_hub` | function | Registers demo app with Parthenon Hub; triggers tool sync | `mcp-demo-app/app/registration.py` |
| `health_router` | APIRouter | FastAPI router for `GET /health` | `mcp-demo-app/app/routes/health.py` |
| `mcp_router` | APIRouter | FastAPI router for `POST /mcp` (MCP JSON-RPC dispatcher with dual-identity extraction) | `mcp-demo-app/app/routes/mcp.py` |
| `mcp_endpoint` | function | FastAPI route handler for `POST /mcp`; parses the JSON-RPC envelope, determines identity source by tool name, and dispatches to method handlers | `mcp-demo-app/app/routes/mcp.py` |
| `create_app` | function | FastAPI app factory; configures lifespan, mounts routers | `mcp-demo-app/app/main.py` |
| `lifespan` | async context manager | Validates Keycloak connectivity and triggers Hub registration on startup; exits the process on failure | `mcp-demo-app/app/main.py` |
| `app` | instance | Module-level FastAPI application instance | `mcp-demo-app/app/main.py` |
| — | conftest | Test env-var setup so `AppSettings()` can initialise in CI | `mcp-demo-app/tests/conftest.py` |
| `init.ps1` | script | Idempotent initialization script; supports `-UserRealm` for dual-realm setup, creates realm roles `demo_agent` and `demo_user` | `mcp-demo-app/init.ps1` |
| `setup-keycloak.ps1` | script | Legacy Keycloak setup script (use init.ps1 for new setups) | `mcp-demo-app/setup-keycloak.ps1` |
| `start.ps1` | script | Starts the demo app locally; checks prerequisites, creates venv, installs deps, starts server on port 7001 | `mcp-demo-app/start.ps1` |
| `stop.ps1` | script | Stops the demo app; finds and kills process on port 7001 | `mcp-demo-app/stop.ps1` |
| `test_config.py` | test file | Unit tests for AppSettings new optional fields and fallback | `mcp-demo-app/tests/unit/test_config.py` |
| `test_tools.py` | test file | Unit tests for new tool handlers and updated registry/manifest | `mcp-demo-app/tests/unit/test_tools.py` |
| `test_auth.py` | test file | Unit tests for verify_user_jwt and get_user_identity | `mcp-demo-app/tests/unit/test_auth.py` |
| `test_mcp_router.py` | test file | Unit tests for dual-identity dispatch and access-denied responses | `mcp-demo-app/tests/unit/test_mcp_router.py` |
| `test_agent_flow.py` | test file | Integration tests for end-to-end dual-identity flow | `mcp-demo-app/tests/integration/test_agent_flow.py` |
| `test_hub_registration.py` | test file | Integration tests for Hub registration syncing 3 tools | `mcp-demo-app/tests/integration/test_hub_registration.py` |
| `test_startup.py` | test file | Integration tests for app startup with dual-realm config | `mcp-demo-app/tests/integration/test_startup.py` |
| `ToolCallRequest.user_jwt` | field | User identity JWT forwarded to CH tool routing | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `cache_user_jwt` | function | Stores user JWT by session ID for dual-identity forwarding | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `get_user_jwt` | function | Retrieves cached user JWT by session ID | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `McpProxyRequest.user_jwt` | field | User JWT forwarded to Control Center proxy | `backend/app/api/v1/internal/mcp_proxy.py` |
| `McpProxyEngine.call_tool` | method | Gains `user_jwt` parameter for dual-identity forwarding | `backend/app/services/mcp/proxy.py` |
| `_build_auth_headers` | method | Sets `X-User-Identity` header for user JWT on passthrough sessions | `backend/app/services/mcp/proxy.py` |
| `websocket_chat` | function | Caches user JWT from WebSocket query param for tool calls | `backend/app/api/ws/chat.py` |
| `require_permission` | function | Added debug logging for permission check diagnostics | `backend/app/api/deps.py` |
| `init-local-dev.py` | script | Test agent identities, `mcp_role` claim mappers, user profile, offline_access, volume persistence | `scripts/init-local-dev.py` |
| `docker-compose.yml` | config | Keycloak data persistence volume | `docker-compose.yml` |
| `toDelegationSnippetLine` | function | Removed `using_tool` from delegation snippets | `frontend/src/hooks/useChatSession.ts` |
