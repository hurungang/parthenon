# Backend Service Log Analysis - Agent Execution Issues

## Test Scenarios Analyzed

### 1. Non-Conversational Agent (Task-Based)
**Session ID**: `56b639cd-8ca0-47b8-8710-899d8cfd8328`
**Timestamp**: 2026-05-17 09:15:45 - 09:15:50
**Status**: ❌ **FAILED**

### 2. Conversational Agent (WebSocket Chat)
**Session ID**: `9d3adfea-3869-4db7-b83c-866e45d3d80e`
**Timestamp**: 2026-05-17 09:16:21 - 09:16:37
**Status**: ⚠️ **PARTIAL FAILURE** (tool execution failed, but chat worked)

---

## Issues Found

### Issue 1: Missing `communication_hub_url` Configuration ❌ CRITICAL

**Affected**: Non-conversational agents (task-based)

**Error**:
```
2026-05-17 09:15:49.643 - ERROR - Session 56b639cd-8ca0-47b8-8710-899d8cfd8328 execution error: 
'Settings' object has no attribute 'communication_hub_url'

Traceback:
  File "runtime_executor.py", line 669, in _run_task_loop_ar
    comm_hub_client = CommHubToolClient()
  File "pydantic/main.py", line 1042, in __getattr__
    raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}')
AttributeError: 'Settings' object has no attribute 'communication_hub_url'
```

**Root Cause**:
- `backend/app/agent_runtime/comm_hub_client.py` line 36 accesses `settings.communication_hub_url`
- This field does NOT exist in `backend/app/core/config.py` Settings class
- The code has a fallback `or "http://localhost:8002"` but Pydantic raises AttributeError before reaching it

**Impact**:
- **ALL non-conversational agents FAIL** when trying to execute tasks
- Agent session is marked as failed
- No tool calls can be made through Communication Hub

**Fix Required**:
Add `communication_hub_url` field to `Settings` class in `backend/app/core/config.py`:
```python
# Service URLs
communication_hub_url: str = Field(default="http://localhost:8002")
```

---

### Issue 2: Invalid Agent Identity Refresh Token ❌ CRITICAL

**Affected**: Conversational agents using MCP tools

**Error**:
```
2026-05-17 09:16:34.646 - ERROR - Token refresh failed for agent identity 394f4a58-0867-4fe6-97fa-1afb8904ec5b: 
HTTP 400: {"error":"invalid_grant","error_description":"Invalid refresh token"}

2026-05-17 09:16:34.647 - ERROR - Passthrough session for tool 'hello-world/helloWorld' 
but no agent identity JWT available
```

**Root Cause**:
- Agent identity was created with a refresh token
- When the conversational agent tries to call an MCP tool (`hello-world/helloWorld`), it attempts to refresh the JWT
- Keycloak rejects the refresh token as invalid
- Without a valid JWT, MCP tool calls via Communication Hub fail (passthrough requires agent identity JWT)

**Impact**:
- Conversational agents **cannot execute MCP tools**
- Agent can respond to chat but tool calls silently fail
- User sees agent responses but MCP tool results are missing

**Possible Causes**:
1. Refresh token expired or was revoked in Keycloak
2. Agent identity was created in a different Keycloak realm
3. Refresh token was never properly stored or was corrupted
4. Keycloak client configuration changed (client secret, redirect URIs, etc.)

**Investigation Required**:
1. Check agent_identities table for identity `394f4a58-0867-4fe6-97fa-1afb8904ec5b`
2. Verify refresh_token column has a valid value
3. Check Keycloak admin console for agent identity client sessions
4. Verify agent identity client configuration in Keycloak (ai_agents realm)

**Potential Fixes**:
1. **Short-term**: Delete and recreate the agent identity (forces new OAuth flow)
2. **Long-term**: Add refresh token validation and automatic re-authentication flow
3. **Monitoring**: Add alerting for refresh token failures

---

### Issue 3: WebSocket Disconnect/Reconnect Pattern ⚠️ UX ISSUE

**Affected**: Conversational agents (WebSocket chat)

**User Report**:
> "when I click start chat and send the first message it will show disconnected then connected, then dismissed my first message"

**Observations from Logs**:
```
2026-05-17 09:16:21.044 - INFO - WebSocket connected: 
session=9d3adfea-3869-4db7-b83c-866e45d3d80e 
subject=b2cd9869-0a6e-4303-98af-61b3bab33ec6
```

Chat session connects successfully, processes augmented instructions, loads MCP tools, and executes conversation turn.

**Likely Cause**:
- Frontend WebSocket connection experiences brief disconnect/reconnect during initial setup
- First message sent during unstable connection period gets lost
- Could be related to:
  - WebSocket authentication delay
  - Communication Hub port 8002 connection timing
  - Frontend WebSocket client not waiting for connection ready state

**Impact**:
- **First user message is lost** after starting a chat
- User must resend message
- Poor UX - appears broken to users

**Investigation Required**:
1. Check browser console for WebSocket connection state transitions
2. Verify frontend waits for WebSocket `OPEN` state before sending messages
3. Check if there's a race between connection and message send
4. Look for Connection Hub logs showing client disconnects during setup

---

## Summary

### Critical Issues (Block Agent Execution)
1. ❌ **Missing `communication_hub_url` setting** - Non-conversational agents cannot execute
2. ❌ **Invalid agent identity refresh token** - Conversational agents cannot use MCP tools

### UX Issues (Affect User Experience)
3. ⚠️ **WebSocket disconnect/reconnect** - First message lost in conversational agents

---

## Recommended Actions

### Immediate (Fix Today)
1. **Add `communication_hub_url` to Settings class** - 5 minutes
2. **Delete and recreate failing agent identity** - 10 minutes
3. **Test both agent types** - 15 minutes

### Short-term (This Week)
1. Fix WebSocket connection stability in frontend
2. Add refresh token validation before use
3. Add automatic re-authentication flow for expired tokens
4. Add health check endpoint reporting for missing configurations

### Long-term (This Month)
1. Add comprehensive configuration validation at startup
2. Implement token refresh error recovery
3. Add monitoring/alerting for agent identity authentication failures
4. Add WebSocket connection state debugging tools

---

## Test Commands

```powershell
# Check Communication Hub is accessible
curl http://localhost:8002/health

# Check agent identity in database
psql -d parthenon -c "SELECT id, agent_type_id, client_id, refresh_token_hash FROM agent_identities WHERE id = '394f4a58-0867-4fe6-97fa-1afb8904ec5b';"

# Check current settings configuration
cd backend
python -c "from app.core.config import get_settings; s = get_settings(); print(f'communication_hub_url: {getattr(s, \"communication_hub_url\", \"MISSING\")}')"

# Restart backend services after fixing
.\parthenon.ps1 restart -Services backend -Force
```
