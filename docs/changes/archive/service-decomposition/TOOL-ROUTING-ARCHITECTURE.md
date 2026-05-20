# Tool Routing Architecture Fix

## Problem

Agent execution is failing because:
1. Agent Runtime is calling MCP tools directly via McpProxyEngine (wrong)
2. Wrong method signature - using `tool_name=` instead of passing `McpTool` object
3. Agent Runtime and Communication Hub both have database dependencies
4. No proper tool routing through Communication Hub

## Correct Architecture

### Control Center (Database Owner)
- **Owns**: Database, integrations, MCP sessions, permissions
- **Provides**:
  - Internal API for session/tool data
  - System tools as MCP-like endpoints (save_result, send_notification)
  - Permission resolution
  - MCP session/credential management

### Agent Runtime (Stateless Executor)
- **Does**: LangChain observe-reason-act loop
- **No**: Database access, direct tool calls, MCP proxy
- **Tool calling flow**:
  1. LLM wants to call tool → sends to Communication Hub
  2. Waits for result from Communication Hub
  3. Continues LangChain loop

### Communication Hub (Tool Router)
- **Routes**: ALL tool calls (external MCP + system tools)
- **Gets from Control Center**:
  - MCP session data and credentials
  - Permission validation
  - System tool execution
- **Flow**:
  ```
  Agent Runtime
    ↓ (tool call request)
  Communication Hub
    ↓ (validate + get credentials)
  Control Center Internal API
    ↓ (session data)
  Communication Hub
    ↓ (execute with credentials)
  External MCP Server OR Control Center System Tools
    ↓ (result)
  Communication Hub
    ↓ (result)
  Agent Runtime
  ```

## Implementation Plan

### Phase 1: Communication Hub Tool Routing Endpoint
- [ ] Create `/internal/tools/call` endpoint in Communication Hub
- [ ] Accepts: tool_name, tool_args, session_id, agent_cert
- [ ] Validates certificate (mTLS)
- [ ] Calls Control Center for:
  - Permission check
  - MCP session/credential retrieval
- [ ] Routes to external MCP OR Control Center system tools
- [ ] Returns result

### Phase 2: Control Center System Tool Endpoints
- [ ] Create `/internal/system-tools/save-result` endpoint
- [ ] Create `/internal/system-tools/send-notification` endpoint
- [ ] Create `/internal/system-tools/get-recipient-group` endpoint
- [ ] All require mTLS certificate validation
- [ ] Return MCP-like JSON-RPC responses

### Phase 3: Agent Runtime Tool Call Client
- [ ] Remove direct McpProxyEngine usage
- [ ] Create CommHubToolClient
- [ ] Calls Communication Hub `/internal/tools/call` with mTLS cert
- [ ] Handles responses and errors

### Phase 4: Remove Database Dependencies
- [ ] Agent Runtime: Remove all AsyncSession parameters
- [ ] Communication Hub tool routing: No direct DB access
- [ ] All data flows through Control Center APIs

### Phase 5: Integration Tests
- [ ] Test: Agent calls external MCP tool (hello-world)
- [ ] Test: Agent calls system tool (save_result)
- [ ] Test: Permission denied for unauthorized tool
- [ ] Test: OAuth token refresh for MCP session
- [ ] Test: Certificate validation failures
- [ ] E2E: Full agent execution with tool calling

## Security Requirements

1. **mTLS everywhere**: AR ↔ CH, CH ↔ CC
2. **No credential exposure**: CH gets credentials from CC, never stores them
3. **Permission validation**: CH asks CC before each tool call
4. **Certificate validation**: All internal endpoints validate cert signatures
5. **Audit logging**: All tool calls logged with agent cert identity

## Test Cases

### Unit Tests

**Test: Communication Hub tool routing**
```python
async def test_comm_hub_tool_call_external_mcp():
    # Given: Valid agent cert, hello-world tool permission
    # When: POST /internal/tools/call with tool_name="hello-world/helloWorld"
    # Then: Returns greeting from MCP server
```

**Test: System tool routing**
```python
async def test_comm_hub_tool_call_system_save_result():
    # Given: Valid agent cert, save_result permission
    # When: POST /internal/tools/call with tool_name="save_result"
    # Then: Calls CC /internal/system-tools/save-result
    # And: Returns success status
```

**Test: Permission denied**
```python
async def test_comm_hub_tool_call_permission_denied():
    # Given: Valid agent cert, NO permission for tool
    # When: POST /internal/tools/call
    # Then: Returns 403 with permission error
```

### Integration Tests

**Test: Full agent execution with tools**
```python
async def test_agent_execution_with_mcp_tools():
    # Given: hello_world_agent with hello-world MCP permission
    # When: Launch session
    # Then: Agent calls hello-world/helloWorld via CH
    # And: CH gets credentials from CC
    # And: CH calls external MCP server
    # And: Agent receives result and completes
```

**Test: Agent execution with system tools**
```python
async def test_agent_execution_with_system_tools():
    # Given: Agent with save_result permission
    # When: Agent calls save_result
    # Then: CH routes to CC /internal/system-tools/save-result
    # And: Result saved to database
    # And: Session marked completed
```

## Current Code Locations

### Files to Modify
- `backend/app/services/agents/runtime_executor.py` - Remove McpProxyEngine, add CommHubToolClient
- `backend/app/communication_hub/main.py` - Add tool routing endpoint
- `backend/app/api/v1/internal/system_tools.py` - NEW: System tool endpoints in CC
- `backend/app/agent_runtime/comm_hub_client.py` - NEW: Tool call client for AR

### Files for Tests
- `backend/tests/integration/test_tool_routing.py` - NEW
- `e2e/tests/agent-execution-tools.spec.ts` - NEW

## Success Criteria

- [ ] Agent can call external MCP tools (hello-world)
- [ ] Agent can call system tools (save_result, send_notification)
- [ ] All tool calls flow through Communication Hub
- [ ] No database access in Agent Runtime
- [ ] No database access in Communication Hub tool routing
- [ ] Certificate validation works end-to-end
- [ ] Permission checks prevent unauthorized tool access
- [ ] All tests pass (unit + integration + E2E)
