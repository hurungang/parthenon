# Communication Hub Test Plan

## What to Test
- Message routing
- WebSocket delivery
- Agent-to-agent relay
- Session context consistency

## Critical Scenarios
- Two WebSocket clients both receive messages
- Inter-agent message delivery

## Edge Cases
- Hub restart causing mass disconnections
- Redis pub/sub failure

## Test File References
- `backend/tests/unit/test_communication_hub.py`
- `e2e/tests/chat.spec.ts`
