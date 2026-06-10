# Agent Gateway Test Plan

## What to Test
- Gateway routing: launch requests routed through `AgentSessionService.enqueue` (not direct executor invocation); session ID returned synchronously
- Conversational agents: `LifecycleHandler` establishes bidirectional WebSocket channel for the session
- Non-existent AgentType ID → 404; unauthorized launch → 403
- Communication Hub OAuth enforcement:
  - Agent connection without `Authorization` header → 401
  - Expired or signature-invalid token → 401
  - Valid token with unrecognized or unauthorized role claim → 403
  - Valid token with recognized role → 200 with permitted tool list
  - Tool list entries: `mcp_slug/tool_name` identifiers only; no `description` or `schema` fields
  - Agent call to unlisted tool → permission denied (not 500)
  - Agent call to allowed tool → tool executes and returns result

## Test Strategy

The Agent Gateway is tested at three layers: backend unit tests verify session enqueue/dispatch logic and OAuth enforcement; backend integration tests validate end-to-end HTTP request/response flows through the gateway; E2E tests exercise the full gateway launch path from the Web UI through the Communication Hub to Agent Runtime. Mocking is limited to external dependencies (Keycloak JWKS endpoint) in unit tests only; integration and E2E tests use real backend services.

## Critical Scenarios

- **WHEN** a valid launch request is submitted with agent type and input data, **THEN** the session is enqueued via the session service, a session ID is returned synchronously, and the session proceeds asynchronously through the Agent Runtime.
- **WHEN** an agent connects to the Communication Hub with a valid OAuth token and recognized role, **THEN** the connection succeeds with HTTP 200 and the permitted tool list is returned containing only `mcp_slug/tool_name` identifiers (no description or schema fields).
- **WHEN** an agent calls a tool that is not in its permitted tool list, **THEN** the call is rejected with a permission denied error (not a 500 server error).
- **WHEN** an agent calls an allowed tool, **THEN** the tool executes successfully and returns its result.
- **WHEN** a connection is attempted without an Authorization header, **THEN** the request is rejected with HTTP 401.
- **WHEN** a connection is attempted with an expired or invalid token, **THEN** the request is rejected with HTTP 401.
- **WHEN** a connection is attempted with a valid token but an unrecognized role, **THEN** the request is rejected with HTTP 403.
- **WHEN** a launch request references a non-existent AgentType ID, **THEN** the response is HTTP 404 (not 500).

## Edge Cases
- Invalid session handle
- Unanswered conversational questions timeout
- Gateway receives launch request for non-existent AgentType → 404 (not 500)

## Test File References
- `backend/tests/unit/test_agent_gateway.py`
- `backend/tests/unit/test_lifecycle_handler.py`
- `backend/tests/unit/test_communication_hub.py`
- `backend/tests/integration/test_communication_hub.py`
- `e2e/tests/gateway.spec.ts`
