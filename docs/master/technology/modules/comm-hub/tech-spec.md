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
| `WebSocketServer` | FastAPI WebSocket endpoint handler that authenticates the incoming connection using the bearer token, subscribes to the session channel via `MessageBroker`, and bridges bidirectional traffic between the browser client and the message broker |
| `AgentRouter` | Service class that routes inter-agent messages from a source agent instance to a target instance's pub/sub channel via `MessageBroker`; enables agent-to-agent communication |
| `SessionContextManager` | Service class that stores and retrieves active session state — including participants, turn count, and current status — in Redis with a configurable TTL; context is flushed to PostgreSQL when the session closes |
| `CertificateAuthorizationMiddleware` | Starlette middleware intercepting all agent tool call requests; extracts the client certificate from the TLS handshake, validates it with the Control Center, and fetches the authorised identity token; tool execution proceeds with the Control Center-provided token; returns `403 Forbidden` with reason on any validation or authorisation failure; all decisions written to `certificate_validation_log` |
| `NameResolver` | Routes all tool calls from Agent Runtime to the correct handler using the unified `server____tool` naming convention. `system____*` calls are dispatched to internal system tool handlers (e.g., Notification Service); `<server>____*` calls are forwarded to the MCP Hub for external server proxying. No tool-type branching exists in Agent Runtime code — all routing decisions are made here. |

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

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `MessageBroker` | class | Redis pub/sub broker with per-session typed message channels | `backend/app/services/comm_hub/broker.py` |
| `create_app` | function | Communication Hub application bootstrap and middleware composition entry point | `backend/app/communication_hub/main.py` |
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
| `check_revocation_status` | method | Uses Control Center revocation endpoint contract `revoked/{serial_number}` and fail-closed behavior by default | `backend/app/communication_hub/data_client.py` |
| `route_tool_call` | endpoint | Internal tool routing endpoint that dispatches runtime tool calls to system-tools or MCP proxy pathways | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `_route_to_system_tool` | function | Forwards `system____*` calls to Control Center system-tools internal endpoints with service-certificate authentication | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `_route_to_mcp_tool` | function | Forwards `<server>____*` calls to Control Center MCP proxy internal endpoint | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `_build_control_center_auth` | function | Builds authenticated CH->CC internal call transport for tool routing and policy checks | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `trigger_agent_execution` | endpoint | Triggers Agent Runtime execution for queued or conversation work units and preserves guardrail stop metadata in forwarded payloads | `backend/app/communication_hub/api/internal/agent_execute.py` |
| `request_a2a` | endpoint | Creates agent-to-agent delegation requests through Control Center orchestration APIs while preserving delegated guardrail outcome metadata | `backend/app/communication_hub/api/a2a.py` |
| `disconnect_a2a` | endpoint | Closes linked A2A sessions and updates orchestration state via Control Center | `backend/app/communication_hub/api/a2a.py` |
| `ChatPage` | component | Real-time user-to-agent chat interface backed by WebSocket connection | `frontend/src/pages/chat/ChatPage.tsx` |
| `useChatSession` | hook | Manages WebSocket connection lifecycle, inbound message queue, pending question state, and reconnection | `frontend/src/hooks/useChatSession.ts` |

### Segregation Audit Coverage

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `service-segregation-security-audit` | e2e test | Verifies internal service-certificate enforcement and revocation endpoint contract against real backend routes | `e2e/tests/service-segregation-security-audit.spec.ts` |
