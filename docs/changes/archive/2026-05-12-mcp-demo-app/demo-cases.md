# Demo Cases: mcp-demo-app

This change introduces a standalone MCP demo app with no UI. The demo is performed via API calls and Hub UI verification.

## Manual Demo Steps

### Prerequisites
- Keycloak running on port 8082 with `ai_agents` realm configured
- Backend running on port 8000
- MCP Demo App client created in Keycloak

### Quick Start
```powershell
# Start the demo app (from mcp-demo-app directory)
.\start.ps1

# In another terminal, run the demo steps below...

# Stop the demo app when done
.\stop.ps1
```

### Demo Flow

1. **Verify Health Endpoint (No Auth)**
   ```powershell
   Invoke-WebRequest -Uri "http://localhost:8001/health" -UseBasicParsing | Select-Object StatusCode, Content
   ```
   Expected: HTTP 200, `{"status":"ok","slug":"demo"}`

2. **Verify Hub Registration**
   - Open Parthenon UI: http://localhost:5173
   - Navigate to MCP Hub → Servers
   - Confirm `demo` server is registered with status `active`
   - View server's tool list → confirm `helloWorld` tool appears under `demo/` namespace

3. **Call helloWorld Tool with Agent JWT**
   ```powershell
   # Obtain agent JWT from Keycloak (replace with actual client credentials)
   $tokenResponse = Invoke-RestMethod -Uri "http://localhost:8082/realms/ai_agents/protocol/openid-connect/token" `
     -Method POST `
     -ContentType "application/x-www-form-urlencoded" `
     -Body "grant_type=client_credentials&client_id=demo&client_secret=<SECRET>"
   
   $jwt = $tokenResponse.access_token
   
   # Call MCP tool
   $body = @{
     jsonrpc = "2.0"
     id = 1
     method = "tools/call"
     params = @{
       name = "helloWorld"
       arguments = @{}
     }
   } | ConvertTo-Json
   
   Invoke-RestMethod -Uri "http://localhost:8001/mcp" `
     -Method POST `
     -Headers @{ Authorization = "Bearer $jwt" } `
     -ContentType "application/json" `
     -Body $body | ConvertTo-Json -Depth 10
   ```
   Expected: Response includes `"message":"Hello from MCP Demo App!"`, `agent_sub` matching JWT's `sub` claim

4. **Verify 401 on Invalid JWT**
   ```powershell
   Invoke-RestMethod -Uri "http://localhost:8001/mcp" `
     -Method POST `
     -Headers @{ Authorization = "Bearer invalid_token" } `
     -ContentType "application/json" `
     -Body $body
   ```
   Expected: HTTP 401 Unauthorized

## What This Validates

- [x] Agent authentication via Keycloak ai_agent realm
- [x] MCP tool registration with Hub under `demo/` namespace
- [x] Agent identity propagation through full flow (JWT → tool call → response)
- [x] Health check endpoint (no auth required)
- [x] Authentication guard (401 on invalid JWT)

## Integration Test Demo

To see automated test coverage:
```powershell
cd mcp-demo-app
pytest -v tests/unit/  # 65 unit tests — all pass
pytest -v tests/integration/  # 10 integration tests — skip if services not running
```
