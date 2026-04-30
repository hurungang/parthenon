# Agent Engine Test Plan

## What to Test
- AgentType CRUD operations
- sop-agent execution
- skillful-agent skill selection
- Agent instance lifecycle management
- Permission enforcement on all agent endpoints (`agent:read`, `agent:create`, `agent:update`, `agent:delete`)
- 403 structured error responses with resource type, action, and resource ID
- Permission-denied UI rendering: snackbar with "Request Access" button on 403 from agent endpoints

## Critical Scenarios
- sop-agent follows SOP and asks clarifying question
- skillful-agent selects appropriate skill
- Gateway enforces max-instance limit
- User without `agent:read` receives 403 on `GET /api/v1/agents/types`; UI shows permission-denied snackbar
- User without `agent:create` receives 403 on `POST /api/v1/agents/types`; snackbar is pre-filled with resource type and action
- User with correct permission completes full agent CRUD flow without error

## Edge Cases
- Race condition at max limit
- Stuck agent instances
- Permission revoked mid-session; next request denied

## Test File References
- `backend/tests/unit/test_agent_gateway.py`
- `backend/tests/unit/test_agent_instance_manager.py`
- `backend/tests/api/v1/test_agents_api.py`
- `frontend/src/__tests__/AgentManagementPage.test.tsx`
- `e2e/tests/agent-management.spec.ts`
- `e2e/tests/access-control.spec.ts` — `Permission Denied: Snackbar` and `Permission Denied: Request Access Flow`
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering per page
