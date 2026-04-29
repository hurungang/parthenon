# Module: gateway — Tech Spec

## Overview

The gateway module exposes registered agent types to external consumers through a stateful lifecycle protocol. Consumers interact with an agent instance through a five-operation sequence: initialise a session, submit a request prompt, long-poll for an agent question, provide an answer, and close the session. The protocol is available over both plain HTTP (via `HttpGatewayTransport`) and as four MCP tools (via `McpGatewayTransport`). The `GatewayLifecycleHandler` orchestrates the state machine while `GatewayEndpointRegistry` maintains the routing table of gateway paths per agent type.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `GatewayRouter` | FastAPI router exposing the five lifecycle protocol endpoints; routes are parameterised by agent type ID (for init) and session handle (for all subsequent operations) |
| `GatewayLifecycleHandler` | Service class orchestrating the gateway state machine: creates sessions via `AgentInstanceManager`, routes prompts to the appropriate executor, suspends execution when the agent raises a question, resumes on answer, and tears down the instance on close |
| `GatewayEndpointRegistry` | Service class that persists gateway route mappings per agent type to the database and resolves the correct routing path for inbound calls; supports dynamic registration when a new agent type is created |
| `HttpGatewayTransport` | HTTP adapter that marshals inbound FastAPI requests into the internal request/response model and passes them to `GatewayLifecycleHandler`; handles async long-polling for the question endpoint |
| `McpGatewayTransport` | MCP tool adapter that registers the four lifecycle operations (init, request, question, answer, close) as MCP tools on a gateway MCP server, enabling agent-to-agent invocation over the MCP protocol |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/gateway/{agent_type_id}/init` | Initialise an agent instance; returns a session handle for subsequent calls |
| `POST` | `/gateway/{session_id}/request` | Submit a user prompt to the active agent instance |
| `GET` | `/gateway/{session_id}/question` | Long-poll for an agent question awaiting user input |
| `POST` | `/gateway/{session_id}/answer` | Provide the user's answer to a pending agent question |
| `POST` | `/gateway/{session_id}/close` | Close the agent instance and end the session |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `GatewayRouter` | router | Lifecycle protocol endpoints (init/request/question/answer/close) | `backend/app/api/gateway/lifecycle.py` |
| `GatewayLifecycleHandler` | class | Orchestrates gateway state machine: session creation, prompt routing, question/answer pause-resume, and teardown | `backend/app/services/gateway/lifecycle_handler.py` |
| `GatewayEndpointRegistry` | class | Persists and resolves gateway route mappings per agent type | `backend/app/services/gateway/registry.py` |
| `HttpGatewayTransport` | class | HTTP adapter marshalling FastAPI requests to GatewayLifecycleHandler | `backend/app/services/gateway/transports/http.py` |
| `McpGatewayTransport` | class | MCP tool adapter exposing lifecycle operations as four MCP tools for agent-to-agent invocation | `backend/app/services/gateway/transports/mcp.py` |
