# Technical Specification — add-mcp-protocol-server

## Technical Overview

This change adds a standard Model Context Protocol (MCP) server to the Communication Hub (CH), layered entirely on the existing API-key authentication middleware and the Control Center (CC) proxy path. The server speaks the standard MCP protocol (`initialize`, `tools/list`, `tools/call`) over two transports — Streamable HTTP and Server-Sent Events (SSE) — authenticated by the existing Parthenon API keys (`phn_sk_…`). It reuses the existing role-based permission resolution, the `load_skills` skill-discovery capability, and the `McpProxyEngine` unchanged; no Agent Runtime change and no new authentication/authorization model are introduced. API keys gain an optional `expires_at` timestamp (a single new column); a `NULL` value means the key never expires, and expired keys are rejected at authentication. The official `mcp` Python SDK (`mcp>=1.1.2`) supplies the protocol types, `Server`, and transport primitives.

## Component Breakdown

- **MCP Protocol Server** — Bridges the JSON-RPC methods `initialize`, `tools/list`, and `tools/call` to the tool registry bridge. `initialize` performs capability negotiation; the other two require an authenticated session. Modeled on the reference `sdk_protocol_handler.py`.

- **Tool Registry Bridge** — The single source of truth for canonical tool names. It builds the permission-filtered tool catalog for `tools/list` and authorizes + dispatches `tools/call`, routing system tools to CC system-tool endpoints and proxied MCP tools to the CC MCP proxy.

- **MCP Session Manager** — Tracks per-connection protocol state (initialized flag, capability negotiation, authenticated identity/role/permissions) across both transports, with TTL and idle cleanup. Holds the identity context server-side only.

- **Streamable HTTP Transport** — Accepts `POST` JSON-RPC messages and returns newline-delimited JSON responses, resolving/reusing sessions via a session header.

- **SSE Transport** — Serves the same JSON-RPC methods over an event stream plus a message-posting path, for streaming-capable clients.

- **API-key Authentication Middleware (reused/enhanced)** — Validates the client's API key against CC (mTLS, hashed key), resolves the bound identity token + role + permissions, and attaches them to the request/session. Now also fronts the MCP protocol endpoint.

- **Control Center MCP Proxy (reused, role-extended)** — Resolves the MCP session, decrypts credentials at call time, and performs the downstream JSON-RPC `tools/call` via `McpProxyEngine`; extended to resolve sessions from a role + identity (what an API key yields) as well as an agent type.

## API Changes

| Method | Path | Service | Change | Auth |
|--------|------|---------|--------|------|
| `POST` | `/mcp` (Streamable HTTP) | Communication Hub | New — MCP JSON-RPC endpoint | API key (Bearer / `?apiKey=`) |
| `GET` | `/mcp/sse` (event stream) | Communication Hub | New — MCP SSE stream | API key (Bearer / `?apiKey=`) |
| `POST` | `/mcp/sse/messages` | Communication Hub | New — SSE message posting | API key (Bearer / `?apiKey=`) |
| `GET`/`POST` | `/mcp/tools/load_skills` | Communication Hub | Unchanged (REST, retained) | API key |
| `POST` | `/api/v1/internal/mcp/proxy-tool` | Control Center | Extended — accepts role + identity resolution (in addition to agent type) | Service certificate (mTLS) |
| `POST` | `/api/v1/internal/auth/validate-api-key` | Control Center | Reused — unchanged | Service certificate (mTLS) |
| `POST` | `/api/v1/internal/skills/resolve` | Control Center | Reused — unchanged (load_skills backing) | Service certificate (mTLS) |
| `POST` | `/api/v1/api-keys` | Control Center | Extended — accepts optional `expires_at` (create returns it) | JWT (admin) |
| `GET` | `/api/v1/api-keys` | Control Center | Extended — list items now include `expires_at` | JWT (admin) |
| `POST` | `/api/v1/internal/auth/validate-api-key` | Control Center | Extended — rejects expired keys with a clear 401 | Service certificate (mTLS) |

One additive database change: an optional `expires_at` column on `agent_api_keys` (nullable; `NULL` = never expires). No public REST surface is removed or deprecated.

## State Management

The MCP server itself is backend-only; the API-key expiration refinement adds a small amount of frontend form state. Server-side state is limited to:

- **Per-connection MCP session state** — the initialized flag, negotiated capabilities, and the authenticated identity/role/permissions context, held by the MCP session manager with TTL and idle cleanup. The identity token is held exclusively on the CH/CC side and is never serialized into a client-visible response or session object.
- **Request/session auth context** — the resolved `identity_token`, `agent_identity_id`, `agent_role_id`, `permissions`, and `skills` attached by `ApiKeyAuthMiddleware`, consumed by the tool registry bridge.

## Data Access Patterns

The Communication Hub has **no direct database access** (top-priority rule). All data required by the MCP server is fetched from Control Center over mTLS:

- **API-key validation + permission/identity resolution** → CC `/internal/auth/validate-api-key` (returns identity token, role, permissions, skills).
- **Skill discovery (`load_skills`)** → CC `/internal/skills/resolve` (returns full skill definitions, schemas, `updated_at`, `since` sync).
- **Proxied MCP tool calls** → CC `/internal/mcp/proxy-tool` → `McpProxyEngine` → external MCP server (JSON-RPC `tools/call`).
- **System tool calls** → CC system-tool endpoints via `SystemToolRegistry`.

The identity token used for passthrough/dual-identity proxying is resolved and held by CC/CH and injected per tool call; it is never exposed to the external MCP client.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `create_app` | function | Builds the CH FastAPI app and registers middleware + routers | `backend/app/communication_hub/main.py` |
| `_register_routers` | function | Registers CH API routers (extend for MCP router) | `backend/app/communication_hub/main.py` |
| `ApiKeyAuthMiddleware` | class | Detects + validates API keys on `/mcp*`, attaches identity/role/permissions | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `_extract_api_key` | function | Extracts key from Bearer header / `?apiKey=` query | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `_hash_api_key` | function | SHA-256 hashes the raw key before CC transmission | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `_validate_api_key_with_cc` | function | Calls CC `validate-api-key` over mTLS with hashed key | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `load_skills` | route | Existing REST skill-discovery endpoint (GET/POST) | `backend/app/communication_hub/api/mcp_tools.py` |
| `mcp_router` | router | Existing REST MCP router (`/mcp`) | `backend/app/communication_hub/api/mcp_tools.py` |
| `route_tool_call` | route | Internal tool routing (Agent Runtime → system/MCP) | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `_route_to_system_tool` | function | Routes system tools to CC system-tool endpoints | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `_route_to_mcp_tool` | function | Routes MCP tools to CC proxy endpoint | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `McpProxyEngine` | class | Proxies a tool call to an MCP server (session resolution, credential decrypt, JSON-RPC) | `backend/app/services/mcp/proxy.py` |
| `McpProxyEngine.call_tool` | method | Invokes a tool on its MCP server via JSON-RPC `tools/call` | `backend/app/services/mcp/proxy.py` |
| `proxy_mcp_tool` | route | CC internal proxy endpoint (agent-type based session resolution) | `backend/app/api/v1/internal/mcp_proxy.py` |
| `InternalMcpProxyRouter` | router | CC internal MCP proxy router | `backend/app/api/v1/internal/mcp_proxy.py` |
| `validate_api_key_internal` | route | CC internal API-key validation + identity/permission/skill resolution | `backend/app/api/v1/internal/validate_api_key.py` |
| `InternalAuthRouter` | router | CC internal auth router | `backend/app/api/v1/internal/validate_api_key.py` |
| `resolve_skills_internal` | route | CC internal skill resolution for `load_skills` | `backend/app/api/v1/internal/system_tools.py` |
| `generate_api_key` | function | Generates `phn_sk_` API keys | `backend/app/services/api_key_service.py` |
| `hash_api_key` | function | SHA-256 hashes an API key | `backend/app/services/api_key_service.py` |
| `resolve_identity_token` | function | Resolves/decrypts an identity token (CH-side only) | `backend/app/services/api_key_service.py` |
| `resolve_allowed_tools` | function | Resolves the complete allowed-tool set for a role | `backend/app/services/api_key_service.py` |
| `is_key_expired` | function | Returns `True` when a key's `expires_at` is in the past (new) | `backend/app/services/api_key_service.py` |
| `AgentApiKey.expires_at` | field | Optional expiration timestamp; `NULL` = never expires (new) | `backend/app/db/models/agent_api_key.py` |
| `ApiKeyCreate.expires_at` | schema | Optional expiration on create (new) | `backend/app/schemas/api_key.py` |
| `create_api_key` | endpoint | Creates a key; persists optional `expires_at` (modified) | `backend/app/api/v1/api_keys.py` |
| `list_api_keys` | endpoint | Lists keys; includes `expires_at` (modified) | `backend/app/api/v1/api_keys.py` |
| `validate_api_key_internal` | endpoint | Rejects expired keys with 401 (modified) | `backend/app/api/v1/internal/validate_api_key.py` |
| `is_system_tool` | function | Identifies `system____*` canonical system tools | `backend/app/services/agents/tool_naming.py` |
| `get_bare_tool_name` | function | Strips canonical prefix to bare system-tool name | `backend/app/services/agents/tool_naming.py` |
| `SystemToolRegistry` | class | Registers system tools + maps them to CC endpoints | `backend/app/services/agents/system_tool_registry.py` |
| `require_service_certificate` | dependency | Enforces mTLS service cert on CC internal endpoints | `backend/app/api/deps.py` |
| `Settings` | class | Backend settings (add `CH_MCP_PROTOCOL_SERVER_ENABLED`) | `backend/app/core/config.py` |
| `McpProtocolServer` | class | MCP protocol server bridging JSON-RPC methods (new) | `backend/app/communication_hub/mcp/protocol_server.py` |
| `McpProtocolServer.handle` | method | Dispatches a JSON-RPC message to `initialize`/`tools/list`/`tools/call` (new) | `backend/app/communication_hub/mcp/protocol_server.py` |
| `McpSession` | class | Per-connection protocol state + server-side auth context (new) | `backend/app/communication_hub/mcp/session_manager.py` |
| `McpSessionManager` | class | In-memory session registry with TTL/idle cleanup (new) | `backend/app/communication_hub/mcp/session_manager.py` |
| `get_control_center_url` | function | Resolves the Control Center base URL from env (new) | `backend/app/communication_hub/mcp/cc_client.py` |
| `build_cc_client` | function | Builds mTLS-authenticated httpx client kwargs for CH → CC (new) | `backend/app/communication_hub/mcp/cc_client.py` |
| `ToolRegistryBridge` | class | Builds permission-filtered catalog + authorizes/dispatches `tools/call` (new) | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `handle_streamable_http` | function | Streamable HTTP `POST /mcp` handler (new) | `backend/app/communication_hub/mcp/streamable_http.py` |
| `handle_sse_open` | function | SSE `GET /mcp/sse` stream handler (new) | `backend/app/communication_hub/mcp/sse_transport.py` |
| `handle_sse_message` | function | SSE `POST /mcp/sse/messages` handler (new) | `backend/app/communication_hub/mcp/sse_transport.py` |
| `mcp_protocol_router` | router | FastAPI router mounting the MCP protocol endpoints (new) | `backend/app/communication_hub/mcp/router.py` |
| `register_mcp_protocol_server` | function | Registers the MCP router when `CH_MCP_PROTOCOL_SERVER_ENABLED` (new) | `backend/app/communication_hub/mcp/router.py` |
| `McpConnectionGuide` | component | Shows MCP endpoint, auth format, and Copilot/Claude config (new) | `frontend/src/pages/api-keys/McpConnectionGuide.tsx` |
| `CreateApiKeyDialog` | component | Create-key flow; optional expiration field (modified) | `frontend/src/pages/api-keys/CreateApiKeyDialog.tsx` |
| `ApiKeyListPage` | component | Key list; `Expires` column (modified) | `frontend/src/pages/api-keys/ApiKeyListPage.tsx` |
| `ApiKey.expires_at` | type | Optional expiration timestamp on the key type (new) | `frontend/src/types/apiKeys.ts` |
