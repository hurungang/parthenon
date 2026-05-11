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

## Critical Scenarios
- Full gateway session launch via HTTP: enqueue → session ID returned → session proceeds asynchronously
- Authenticated hub connection (mocked): valid token → 200 and tool list → tool list has no description or schema fields → unlisted tool call → permission denied → allowed tool call → success
- Unauthenticated rejection: no header → 401; invalid token → 401; valid token, unrecognized role → 403

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
- `e2e/tests/communication-hub-auth.spec.ts`
