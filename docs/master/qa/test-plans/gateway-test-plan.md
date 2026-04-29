# Agent Gateway Test Plan

## What to Test
- Lifecycle protocol: init, request, question, answer, close
- Max-instance enforcement
- Session isolation

## Critical Scenarios
- Full gateway lifecycle over HTTP
- MCP tools for lifecycle operations

## Edge Cases
- Invalid session handle
- Unanswered questions timeout

## Test File References
- `backend/tests/unit/test_agent_gateway.py`
- `e2e/tests/gateway.spec.ts`
