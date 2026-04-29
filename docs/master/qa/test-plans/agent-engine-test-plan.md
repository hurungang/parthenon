# Agent Engine Test Plan

## What to Test
- AgentType CRUD operations
- sop-agent execution
- skillful-agent skill selection
- Agent instance lifecycle management

## Critical Scenarios
- sop-agent follows SOP and asks clarifying question
- skillful-agent selects appropriate skill
- Gateway enforces max-instance limit

## Edge Cases
- Race condition at max limit
- Stuck agent instances

## Test File References
- `backend/tests/unit/test_agent_gateway.py`
- `backend/tests/unit/test_agent_instance_manager.py`
- `e2e/tests/agent-management.spec.ts`
