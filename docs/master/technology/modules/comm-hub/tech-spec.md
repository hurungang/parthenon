# Module: comm-hub — Tech Spec

## Overview

The communication hub is the central message broker for real-time interactions in the Parthenon platform. It provides a Redis pub/sub backbone with per-session typed channels, a WebSocket server that authenticates browser clients and bridges them to the broker, an inter-agent routing layer that delivers messages to target agent instance channels, and a session context manager that stores active session state in Redis for low-latency access during agent execution.

The hub also serves as the **mTLS gateway** for agent-to-tool calls. Every inbound tool request from an Agent Runtime presents a client certificate; `CertificateAuthorizationMiddleware` extracts it, validates it with the Control Center, and fetches the authorised identity token before forwarding the call. Agents never supply their own tokens — the Control Center is the sole token issuer at call time.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `MessageBroker` | Redis pub/sub implementation with per-session typed message channels; handles publishing to session channels and delivering messages to subscribed consumers |
| `WebSocketServer` | FastAPI WebSocket endpoint handler that authenticates the incoming connection using the bearer token, subscribes to the session channel via `MessageBroker`, and bridges bidirectional traffic between the browser client and the message broker. Extended to handle four new intervention message types: `intervene_request` (server→client), `intervene_response` (client→server), `intervene_cancel` (client→server), `intervene_status` (server→client); rejects `chat` messages when session has a pending intervention. |
| `AgentRouter` | Service class that routes inter-agent messages from a source agent instance to a target instance's pub/sub channel via `MessageBroker`; enables agent-to-agent communication |
| `SessionContextManager` | Service class that stores and retrieves active session state — including participants, turn count, and current status — in Redis with a configurable TTL; context is flushed to PostgreSQL when the session closes |
| `CertificateAuthorizationMiddleware` | Starlette middleware intercepting all agent tool call requests; extracts the client certificate from the TLS handshake, validates it with the Control Center, and fetches the authorised identity token; tool execution proceeds with the Control Center-provided token; returns `403 Forbidden` with reason on any validation or authorisation failure; all decisions written to `certificate_validation_log` |
| `ApiKeyAuthMiddleware` | Middleware on the Communication Hub that detects API key authentication on incoming MCP requests. Checks `Authorization: Bearer` header first, then `?apiKey=` query parameter. Hashes the extracted key, calls Control Center's internal validation endpoint, stores the returned identity token and permission set on the request context, and rejects invalid/revoked/expired keys with 401. Coexists with existing mTLS certificate auth — detects which method is in use and routes accordingly. |
| `McpProtocolServer` | MCP protocol server that bridges JSON-RPC `initialize`, `tools/list`, and `tools/call` to the tool registry bridge. `initialize` performs capability negotiation; the other two require an authenticated API-key session. |
| `McpSessionManager` | In-memory per-connection MCP session registry that tracks protocol state (initialized flag, capability negotiation) and the authenticated identity/role/permissions context, with TTL/idle cleanup. Holds the identity token server-side only. |
| `ToolRegistryBridge` | Builds the permission-filtered tool catalog for `tools/list` and authorizes + dispatches `tools/call`, routing system tools to CC system-tool endpoints and proxied MCP tools to the CC MCP proxy. |
| MCP transports | Streamable HTTP (`POST /mcp`) and SSE (`GET /mcp/sse`, `POST /mcp/sse/messages`) handlers that share the same protocol server and session manager; gated by `CH_MCP_PROTOCOL_SERVER_ENABLED`. |
| Tool naming & routing | Utilities in `tool_naming.py` (`is_system_tool`, `get_bare_tool_name`) and `tool_routing.py` (`_route_to_system_tool`, `_route_to_mcp_tool`) that route all tool calls from Agent Runtime using the unified `server____tool` naming convention. `system____*` calls are dispatched to internal system tool handlers (e.g., Notification Service, Human Intervene persistence); `<server>____*` calls are forwarded to the MCP Hub for external server proxying. |
| `InterventionRouter` | New router that inspects suspend signals from Agent Runtime for `human_intervene` invocations containing a `conversation_session_id`. When detected, routes the intervention request to the connected WebSocket client of the parent conversation. Falls through to existing dashboard-based flow when `conversation_session_id` is absent. |
| `InterventionQueue` | Per-conversation-session FIFO queue for pending intervention requests. Backed by database state for resilience across disconnects and service restarts. Delivers queued requests to UI in order as prior interventions are resolved or cancelled. |

### Frontend

| Component | Description |
|-----------|-------------|
| `ChatPage` | Real-time user-to-agent chat interface backed by the WebSocket connection; renders message history and a question-answer input panel |
| `useChatSession` | React hook that manages the full WebSocket connection lifecycle: opening the connection, handling inbound message queuing, tracking pending question state requiring user input, and executing reconnection logic on disconnect |

---

## API Endpoints

| Protocol | Path | Purpose |
|----------|------|---------|
| `WebSocket` | `/ws/sessions/{session_id}` | Bidirectional real-time messaging for user ↔ agent chat |
| `POST` | `/internal/agent/resume/{session_id}` | Resume a suspended agent session after an intervene response; forwards resume signal from Control Center to Agent Runtime |
| `MCP` | `/mcp` (Streamable HTTP) | MCP JSON-RPC endpoint (`initialize` / `tools/list` / `tools/call`) for external MCP clients, authenticated by API key |
| `MCP` | `/mcp/sse`, `/mcp/sse/messages` | MCP Server-Sent Events transport (stream + message posting) |
| `MCP Tool` | `load_skills` | MCP system tool: discover all skills (including SOPs) accessible to the authenticated agent. Accepts optional `since` parameter (ISO 8601 timestamp) for incremental sync — only skills updated after the given timestamp are returned. |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `MessageBroker` | class | Redis pub/sub broker with per-session typed message channels | `backend/app/services/comm_hub/broker.py` |
| `create_app` | function | Communication Hub FastAPI application factory — composes middleware and startup validation | `backend/app/communication_hub/main.py` |
| `startup_event` | coroutine | Communication Hub startup sequence — validates Control Center reachability before certificate operations, then validates Redis connectivity | `backend/app/communication_hub/main.py` |
| `_validate_control_center_reachable` | coroutine | **NEW** (CH variant) — validates Control Center health check reachability before attempting certificate bootstrap; fails fast if CA is unavailable | `backend/app/communication_hub/main.py` |
| `_verify_redis_connectivity` | coroutine | Validates Redis connectivity with PING at startup (existing, retained) | `backend/app/communication_hub/main.py` |
| `_load_certificate` | coroutine | Loads or bootstraps service certificate from Control Center (retained) | `backend/app/communication_hub/main.py` |
| `_register_routers` | function | Registers API routers for internal routing, A2A, and WebSocket/chat surfaces | `backend/app/communication_hub/main.py` |
| `WebSocketServer` | class | WebSocket endpoint handler; authenticates connection and bridges to MessageBroker | `backend/app/api/ws/chat.py` |
| `_build_chat_status_event` | function | Normalizes additive `chat_status` payloads (status, tool name, delegated agent type, timestamp) before WebSocket emission | `backend/app/api/ws/chat.py` |
| `websocket_chat` | endpoint | WebSocket endpoint for browser chat sessions and streaming replies | `backend/app/api/ws/chat.py` |
| `_delegate_conversation_turn_to_agent_runtime` | function | Forwards prepared conversation turns from hub transport layer to Agent Runtime execution path | `backend/app/api/ws/chat.py` |
| `AgentRouter` | class | Routes inter-agent messages to target instance channels via MessageBroker | `backend/app/services/comm_hub/agent_router.py` |
| `SessionContextManager` | class | Stores and retrieves active session state in Redis with configurable TTL; flushed to PostgreSQL on session close | `backend/app/services/comm_hub/session_context.py` |
| `ControlPlaneMiddleware` | class | Enforces service-certificate validation for internal Communication Hub routes | `backend/app/communication_hub/middleware/control_plane.py` |
| `CertificateAuthorizationMiddleware` | class | Starlette middleware for agent tool call authorisation; extracts client cert from TLS handshake, validates with Control Center, uses Control Center-provided identity token for tool execution | `backend/app/communication_hub/middleware/authorization.py` |
| `extract_client_certificate` | function | Extract client certificate PEM from request TLS state or header | `backend/app/communication_hub/middleware/authorization.py` |
| `validate_certificate_with_control_center` | function | Call `POST /internal/certificates/validate` on Control Center; return validation result | `backend/app/communication_hub/middleware/authorization.py` |
| `authorize_tool_call` | function | Call `POST /internal/authorize/tool-call` on Control Center; return authorisation result with identity token | `backend/app/communication_hub/middleware/authorization.py` |
| `execute_tool_with_identity` | function | Execute the requested MCP tool using the Control Center-provided identity token | `backend/app/communication_hub/middleware/authorization.py` |
| `log_authorization_decision` | function | Write authorisation outcome (cert serial, tool name, result) to `certificate_validation_log` | `backend/app/communication_hub/middleware/authorization.py` |
| `ControlCenterDataClient` | class | Pulls session, permission, and conversation data from Control Center; no direct DB access in Communication Hub | `backend/app/communication_hub/data_client.py` |
| `preflight_gate` | service module (new) | CH-side gate: calls CC preflight via `internal_httpx_client`; BLOCKED raises, unreachable fails closed | `backend/app/services/gateway/preflight_gate.py` |
| `enforce_execution_preflight` | function (new) | Enforces execution preflight at CH `POST /internal/agent/execute` path | `backend/app/services/gateway/preflight_gate.py` |
| `check_revocation_status` | method | Uses Control Center revocation endpoint contract `revoked/{serial_number}` and fail-closed behavior by default | `backend/app/communication_hub/data_client.py` |
| `route_tool_call` | endpoint | Internal tool routing endpoint that dispatches runtime tool calls to system-tools or MCP proxy pathways | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `_route_to_system_tool` | function | Forwards `system____*` calls to Control Center system-tools internal endpoints with service-certificate authentication; uses `endpoint_map` dict to resolve bare tool name to CC URL; `system____human_intervene` calls are routed to Control Center for persistence and suspend signal relay | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `endpoint_map` | dict | Mapping of bare system tool names (`save_data`, `get_data`, `get_output`, `send_notification`, `human_intervene`, `get_recipient_group`) to Control Center internal endpoint URLs | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `InterventionRouter` | class | Routes conversation-scoped intervention signals (`human_intervene` with `conversation_session_id`) to the connected WebSocket client of the parent conversation; falls through to existing dashboard-based intervention flow when no `conversation_session_id` is present | `backend/app/communication_hub/intervention_router.py` |
| `InterventionQueue` | class | Per-conversation-session FIFO queue of pending intervention requests; backed by database (InterveneRequest records with `status=pending`); delivers queued requests to UI in order as prior interventions resolve or cancel | `backend/app/communication_hub/intervention_queue.py` |
| `dispatch.py` (updated) | module | Message dispatch endpoint routes `intervene_request` signals through `InterventionRouter` when `conversation_session_id` is present; blocks `chat` messages from client when session has a pending intervention | `backend/app/communication_hub/api/dispatch.py` |
| `_route_to_mcp_tool` | function | Forwards `<server>____*` calls to Control Center MCP proxy internal endpoint | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `_build_control_center_auth` | function | Builds authenticated CH->CC internal call transport for tool routing and policy checks | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `trigger_agent_execution` | endpoint (extended) | Triggers Agent Runtime execution for queued or conversation work units and preserves guardrail stop metadata in forwarded payloads; CH execution preflight enforcement added via `enforce_execution_preflight` before execution (BLOCKED returns 422), warnings returned in `AgentExecuteResponse.warnings` | `backend/app/communication_hub/api/internal/agent_execute.py` |
| `forward_resume_session` | endpoint | `POST /internal/agent/resume/{session_id}` — Forwards resume signal from Control Center to Agent Runtime with the operator's response value; restores suspended session | `backend/app/communication_hub/api/internal/agent_resume.py` |
| `request_a2a` | endpoint | Creates agent-to-agent delegation requests through Control Center orchestration APIs while preserving delegated guardrail outcome metadata | `backend/app/communication_hub/api/a2a.py` |
| `disconnect_a2a` | endpoint | Closes linked A2A sessions and updates orchestration state via Control Center | `backend/app/communication_hub/api/a2a.py` |
| `ApiKeyAuthMiddleware` | middleware | CH middleware detecting API keys (Bearer/query param), validating via CC, enriching request context | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `_extract_api_key` | function | Extracts API key from Authorization header or query parameter | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `_validate_api_key_with_cc` | function (async) | Calls CC internal validation endpoint over mTLS, returns enriched response | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `load_skills` | function (system tool) | MCP system tool: returns accessible skills with schemas, supports `since` for incremental sync | `backend/app/communication_hub/api/mcp_tools.py` |
| `mcp_router` | router | FastAPI APIRouter for MCP-facing tool endpoints on Communication Hub | `backend/app/communication_hub/api/mcp_tools.py` |
| `McpProtocolServer` | class | MCP protocol server bridging JSON-RPC `initialize`/`tools/list`/`tools/call` | `backend/app/communication_hub/mcp/protocol_server.py` |
| `McpSession` | class | Per-connection MCP protocol state + server-side auth context | `backend/app/communication_hub/mcp/session_manager.py` |
| `McpSessionManager` | class | In-memory MCP session registry with TTL/idle cleanup | `backend/app/communication_hub/mcp/session_manager.py` |
| `ToolRegistryBridge` | class | Builds permission-filtered tool catalog + authorizes/dispatches `tools/call` | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `build_cc_client` | function | Builds mTLS-authenticated httpx client kwargs for CH → CC | `backend/app/communication_hub/mcp/cc_client.py` |
| `handle_streamable_http` | function | Streamable HTTP `POST /mcp` handler | `backend/app/communication_hub/mcp/streamable_http.py` |
| `handle_sse_open` | function | SSE `GET /mcp/sse` stream handler | `backend/app/communication_hub/mcp/sse_transport.py` |
| `handle_sse_message` | function | SSE `POST /mcp/sse/messages` handler | `backend/app/communication_hub/mcp/sse_transport.py` |
| `mcp_protocol_router` | router | FastAPI router mounting the MCP protocol endpoints | `backend/app/communication_hub/mcp/router.py` |
| `register_mcp_protocol_server` | function | Registers the MCP router when `CH_MCP_PROTOCOL_SERVER_ENABLED` | `backend/app/communication_hub/mcp/router.py` |
| `ChatPage` | component | Real-time user-to-agent chat interface backed by WebSocket connection | `frontend/src/pages/chat/ChatPage.tsx` |
| `useChatSession` | hook | Manages WebSocket connection lifecycle, inbound message queue, pending question state, and reconnection | `frontend/src/hooks/useChatSession.ts` |

### Segregation Audit Coverage

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `service-segregation-security-audit` | e2e test | Verifies internal service-certificate enforcement and revocation endpoint contract against real backend routes | `e2e/tests/service-segregation-security-audit.spec.ts` |

---

## Multi-Tenancy Integration

Communication Hub is tenant-bound via signed headers since the multi-tenant support change (full details: [multi-tenancy module](../multi-tenancy/tech-spec.md)).

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ControlPlaneMiddleware` | middleware (modified) | Verifies CC-signed tenant headers (verify-if-present) and binds the request tenant; CH can verify but never sign | `backend/app/communication_hub/middleware/control_plane.py` |
| `ApiKeyAuthMiddleware` | middleware (modified) | Binds MCP sessions to the tenant returned by `validate_api_key_internal` | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `ControlCenterDataClient` (CH) | class (modified) | Forwards signed tenant headers to CC (`_get`/`_post`) | `backend/app/communication_hub/data_client.py` |
| internal execute/resume/terminate forwarders | routers (modified) | Re-emit CC's original signed headers to AR (`forward_tenant_headers`) so executions bind to the tenant | `backend/app/communication_hub/api/internal/agent_execute.py` (+ `agent_resume.py`, `agent_terminate.py`) |
| session dispatch / A2A / MCP server & tool registry | modules (reference) | Unchanged — scoped by the middleware-bound session tenant and CC's tenant-scoped resolves | `backend/app/communication_hub/` |

## Strict Tenant Isolation (as-built — strict-tenant-isolation change)

The hub is tenant-bound end to end:

- The control-plane middleware verifies and forwards the signed tenant context on `/internal/a2a` and MCP server hops; the API-key middleware binds MCP sessions to the key's tenant (CC signs the context in `validate_api_key` so the hub can forward `X-Internal-Tenant-*` on internal hops).
- Tool routing is decision-tool aware and tenant-contained: `route_tool_call` dispatches `system____*` (system tools), decision tools (routed to CC's decision toolset for the session's tenant), and `<server>____*` MCP tools — all resolved/forwarded with the session's tenant binding.
- The MCP protocol server's `tools/list` / `tools/call` are per-tenant for API-key-authenticated clients via `ToolRegistryBridge`.
- The WebSocket chat endpoint authenticates both token kinds (user JWT and platform-account JWT), binds the connection's tenant, and signs the tenant context for the CC loopback call.

### As-built Code Reference Map additions

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| CH control-plane middleware | middleware | Verifies/forwards the signed tenant context on `/internal/a2a` and MCP server hops | `backend/app/communication_hub/middleware/control_plane.py` |
| `ApiKeyAuthMiddleware` | middleware | Binds MCP sessions to the API key's tenant (context signed by CC's `validate_api_key`) | `backend/app/communication_hub/middleware/api_key_auth.py` |
| `route_tool_call` | endpoint | Unified tool-call router: system tools, decision tools (per-tenant CC decision toolset), and MCP tools; tenant-contained | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `_route_to_decision_tool` | function | Forwards decision tool calls to Control Center with the session's tenant binding | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `_route_to_system_tool` / `_route_to_mcp_tool` | functions | System/MCP tool dispatch; resolution within the bound tenant | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `ToolRegistryBridge.build_catalog` / `dispatch` | methods | Per-tenant `tools/list` filtering and tenant-contained `tools/call` dispatch for API-key MCP clients | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `websocket_chat` / `_signed_tenant_forwarding` | endpoint + function | WS chat auth for both token kinds, tenant binding, and signed CC loopback | `backend/app/api/ws/chat.py` |
| `ControlCenterDataClient` (CH) | class | CH→CC internal client; uses the global egress hook stamping forwarded tenant headers | `backend/app/communication_hub/data_client.py` |

---

## Script-Tool Routing (sandboxed-scripting-and-llm-mocking change)

Communication Hub routes `script____<name>` virtual tools to Agent Runtime sandbox execution (full details: [sandboxed-scripting module](../sandboxed-scripting/tech-spec.md)).

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `_route_to_script_tool` | function | Forwards `script____<name>` invocations to AR `POST /internal/script-tools/execute` with the session's agent identity (`session_id` + `agent_type_id` + `tool_args`); unwraps `{"result"}`/`{"error"}` into the `call_tool` contract; provenance tagging unchanged | `backend/app/communication_hub/api/internal/tool_routing.py` |
| Script forwarding hop | endpoint (new) | `POST /internal/script-tools/forward` — the CC→CH hop; forwards inline `python_source` to AR using CH's own service certificate (ControlPlaneMiddleware only accepts AR certs on `/internal/tools/`, so CC never uses that path for sandboxed execution) | `backend/app/communication_hub/api/internal/tool_routing.py` |

---

## Control Center Assistant — MCP OAuth plane, cc routing and chat hardening (control-center-chatbot change)

The hub gained a second MCP authentication plane and carried the transport-hardening work for the in-app assistant (full details: [agents module](../agents/tech-spec.md)).

**Dual identity plane on `/mcp`.** The existing API-key middleware is unchanged; a parallel OAuth/OIDC Bearer middleware validates the *user's* token, resolves identity, permission scope and tenant, and seeds the MCP session with that context. The identity token stays server-side (never returned to the client), exactly as on the API-key path. Both planes converge on one session-building helper, so both transports share identical authorization semantics.

**Why OAuth.** The same management tool surface serves the in-app assistant (the agent acts with the user's cached JWT scope) and external MCP clients presenting the user's Bearer token. Permission scope is therefore always the user's own — CH stays forward-only, performs no writes and holds no credentials.

### OAuth/OIDC Bearer authentication on `/mcp*`

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OAuthBearerAuthMiddleware` | middleware (new) | Validates the user's OIDC Bearer token on `/mcp*` (JWT-shaped tokens only — anything else falls through to the API-key plane), resolves `PlatformUser`, permissions and tenant via Control Center, and seeds `request.state` with the resolved auth context | `backend/app/communication_hub/middleware/oauth_bearer_auth.py` |
| `_extract_bearer` / `_looks_like_jwt` | functions (new) | Header extraction and JWT-shape discrimination so the two middleware planes never claim each other's credentials | `backend/app/communication_hub/middleware/oauth_bearer_auth.py` |
| `_validate_token` | function (new) | Control Center validation call returning identity, permission scope and tenant; denial leaves the request unauthenticated (the transport gate then fails closed) | `backend/app/communication_hub/middleware/oauth_bearer_auth.py` |
| `McpSession.auth_method` / `platform_user_id` / `user_sub` | fields (new) | OAuth-plane session context: which plane authenticated the connection and the resolved platform user identity forwarded to Control Center (never the token) | `backend/app/communication_hub/mcp/session_manager.py` |
| `is_request_authenticated` | function (new) | Fail-closed gate accepting `request.state.auth_method` ∈ {`api_key`, `oauth`} | `backend/app/communication_hub/mcp/session_manager.py` |
| `build_session_from_request` | function (new) | Seeds an `McpSession` from the resolved auth context on `request.state` — the single session-building path used by both transports | `backend/app/communication_hub/mcp/session_manager.py` |
| `handle_streamable_http` / `handle_sse_open` / `handle_sse_message` | functions (modified) | Use `build_session_from_request` so Streamable HTTP and SSE share the OAuth/API-key session semantics | `backend/app/communication_hub/mcp/streamable_http.py`, `backend/app/communication_hub/mcp/sse_transport.py` |
| `ApiKeyAuthMiddleware` | middleware (reference) | Unchanged API-key plane (`client_credentials` agents); the structural parallel for the OAuth plane | `backend/app/communication_hub/middleware/api_key_auth.py` |

### Tool registry bridge — OAuth catalog and `cc____` dispatch

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ToolRegistryBridge._build_oauth_catalog` | method (new) | OAuth-plane `tools/list`: emits only the permission-filtered **management** tools (`cc____<bare>`) Control Center resolved as permitted for this user; everything else is omitted entirely | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `ToolRegistryBridge.dispatch` (oauth branch) | method (modified) | OAuth connections dispatch through the management path; API-key connections keep the skill/decision/MCP paths | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `ToolRegistryBridge._call_management_tool` | method (new) | Routes a management tool to its CC endpoint forwarding the user's `sub` (and conversation session when present) — no identity token crosses the boundary | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `_management_scope_denial` | function (new) | Defense-in-depth decline of delete verbs and out-of-scope management names (handles the `cc____` prefix) before any dispatch | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `LOAD_SKILLS_TOOL_NAME` | constant | CH meta tool exposed for skill discovery; reserved and never routed as a management tool | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `SystemToolRegistry.get_cc_endpoint_map` (consumer) | integration point | Management names resolve to CC endpoint URLs from the shared registry — CH never hardcodes routes | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |
| `_route_to_system_tool` (cc acceptance) | function (modified) | Accepts both `system____` and `cc____` namespaces (`is_system_tool` handles both), so internal runtime routing treats `cc____` as a built-in system-path call | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `cache_user_jwt` / `get_user_jwt` | functions | Per-session cache of the signed-in user's JWT, enabling the assistant's tools to act with the user's identity | `backend/app/communication_hub/api/internal/tool_routing.py` |

### WebSocket chat — tenant binding, reply routing, watchdog and error surfacing

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `_bind_connection_tenant_context` / `_resolve_oidc_tenant_slug` | functions (new) | Connect-time tenant binding: the platform-token slug path is unchanged; OIDC tokens carry no `tenant` claim, so the tenant is resolved server-side from the user's active membership (the same mechanism as REST `/auth/tenant-memberships`); unresolvable under multi-tenancy fails closed with 4003 | `backend/app/api/ws/chat.py` |
| `_send_to_live_socket` | function (new) | All reply/turn sends (agent reply, `chat_status`, `title_update`, `guardrail_update`, `chat_error`, `chat_blocked`, intervene status) resolve the live socket via `ActiveSessionTracker.get_ws(session_id)` at SEND time, so a mid-turn reconnect on the same session id receives the reply; send failures are logged and swallowed — they never crash the turn pipeline | `backend/app/api/ws/chat.py` |
| `ActiveSessionTracker.unregister` | method (modified) | Identity-checked deregistration so the old connection's cleanup cannot evict a reconnect's registration | `backend/app/api/ws/chat.py` |
| `run_conversation_turn` | function (new) | Whole-turn watchdog: bounds the entire turn (including the deliberately timeout-free AR streaming delegation) with `agent_question_timeout_seconds`, runs the `thinking_heartbeat` keepalive, delivers the live reply via the `on_reply` hook BEFORE persistence, and on fire/cancellation emits `timeout_or_failed` with at most one persisted error turn (deduped against a delivered reply) | `backend/app/api/ws/chat.py` |
| `cancel_pending_conversation_turn` | function (new) | Cancels the per-session pending turn task; invoked by CH's `/internal/agent/terminate/{id}` forwarding so ending a session unblocks the WS turn immediately | `backend/app/api/ws/chat.py` |
| `ConversationTurnError` + `_conversation_turn_error_from_http_status` / `_conversation_turn_error_from_guardrail_stop` / `_persist_and_surface_turn_error` | class + functions (new) | Structured `{"type": "chat_error", "code", "message"}` surfacing: AR's pre-model 400 maps to `assistant_model_not_configured`, guardrail stops to `iteration_limit` / `guardrail_<reason>` with actionable copy, and the error turn is persisted through the structured-error pattern | `backend/app/api/ws/chat.py` |
| `conversation_sessions_default_window_days` | setting (new) | Default listing window (7 days) mirrored to the sessions API/UI | `backend/app/core/config.py` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_oauth_bearer_auth` | test | OAuth plane on `/mcp*`: JWT discrimination, identity/tenant resolution, fail-closed denial, no token leakage into the session payload | `backend/tests/unit/test_oauth_bearer_auth.py` |
| `test_cc_tool_registry_bridge` | test | `cc____` catalog listing, per-tool grant filtering, management dispatch with `user_sub`, delete/out-of-scope denial | `backend/tests/unit/test_cc_tool_registry_bridge.py` |
| `test_mcp_protocol_server` | test | JSON-RPC contract and the shared session/auth gate across both transports | `backend/tests/unit/test_mcp_protocol_server.py` |
| `conversation-intervention.spec.ts` | E2E test | Conversational HITL round-trip (approval preview → response → resume) over the WS channel | `e2e/tests/conversation-intervention.spec.ts` |
