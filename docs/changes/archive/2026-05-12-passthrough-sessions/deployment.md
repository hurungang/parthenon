# Deployment Guide: Passthrough Sessions

## Overview

This document describes the deployment steps for the passthrough-sessions feature, which adds a new "passthrough" authentication type to MCP sessions in the Parthenon platform.

## Prerequisites

- Parthenon backend and frontend must be stopped
- Database backup recommended before applying migrations
- Keycloak ai_agents realm must be configured
- Test MCP server (e.g., mcp-demo-app) with JWT authentication support

## Deployment Steps

### 1. Backend Deployment

#### 1.1 Apply Database Migration

```powershell
# Navigate to backend directory
cd backend

# Apply migration to add passthrough auth type
alembic upgrade head

# Verify migration applied
alembic current
```

#### 1.2 Restart Backend

```powershell
# Using parthenon.ps1 script
.\parthenon.ps1 start backend

# Or direct uvicorn
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

#### 1.3 Verify Backend Health

```powershell
# Check health endpoint
Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing

# Expected: {"status":"ok"}
```

### 2. Frontend Deployment

#### 2.1 Install Dependencies (if needed)

```powershell
cd frontend
npm install
```

#### 2.2 Build and Start Frontend

```powershell
# Development mode
npm run dev

# Production build
npm run build
```

#### 2.3 Verify Frontend Health

- Navigate to http://localhost:5173
- Verify login page loads
- Log in with test user credentials

### 3. Verification Steps

#### 3.1 Verify Database Schema

```sql
-- Check that passthrough enum value exists
SELECT enum_range(NULL::mcp_session_auth_type);

-- Expected output includes: ..., oauth2, passthrough
```

#### 3.2 Verify Passthrough Session Creation

1. Navigate to MCP Hub → Sessions
2. Create new session with passthrough auth type
3. Verify no credential fields are required
4. Verify session is created successfully

#### 3.3 Verify Tool Test with Agent Identity

1. Navigate to Communication Hub → Test Tool
2. Select a passthrough-compatible MCP server
3. Select tool to test
4. Verify agent identity dropdown appears
5. Select agent identity and test tool
6. Verify tool call succeeds with agent JWT

#### 3.4 Verify Role Configuration

1. Navigate to Agent Management → Roles
2. Create or edit a role
3. In MCP server configuration, select a passthrough-compatible server
4. Verify "Agent Identity Passthrough" option appears
5. Enable passthrough option
6. Save role configuration

## Rollback Procedure

If issues are encountered, rollback using the following steps:

### 1. Database Rollback

```powershell
cd backend

# Rollback to previous migration
alembic downgrade -1

# Verify rollback
alembic current
```

### 2. Code Rollback

```powershell
# Revert to previous git commit
git log --oneline -10  # Find previous commit hash
git checkout <previous-commit-hash>

# Rebuild and restart
cd frontend
npm install
npm run build

cd ../backend
.\parthenon.ps1 start backend
```

## Post-Deployment Validation

### Smoke Tests

Run the following smoke tests after deployment:

1. **Session Creation Test**
   - Create passthrough session
   - Verify no errors in browser console
   - Verify session appears in session list

2. **Tool Test**
   - Test tool with passthrough session
   - Verify agent identity is passed to MCP server
   - Verify tool response includes agent claims

3. **Role Configuration Test**
   - Configure role with passthrough option
   - Assign role to agent
   - Verify agent can execute tools with passthrough session

### Monitoring

Monitor the following after deployment:

- Backend logs: `backend/logs/app.log`
- Frontend console: Browser developer tools
- Database: Check for any constraint violations
- Keycloak: Verify JWT token validation is working

## Troubleshooting

### Issue: Migration Fails

**Symptom**: `alembic upgrade head` fails with constraint error

**Solution**:
1. Check existing mcp_session records
2. Ensure no invalid auth_type values exist
3. Run migration repair script if needed

### Issue: Passthrough Option Not Visible

**Symptom**: Passthrough auth type not appearing in UI

**Solution**:
1. Verify database migration applied: `alembic current`
2. Clear browser cache and reload
3. Check browser console for errors
4. Verify backend API returns passthrough in auth types list

### Issue: JWT Not Forwarded

**Symptom**: MCP server rejects tool call with 401 Unauthorized

**Solution**:
1. Verify agent identity is selected in tool test
2. Check backend logs for JWT extraction errors
3. Verify `request.state.raw_token` is populated in middleware
4. Verify MCP proxy engine is using passthrough branch in `_build_auth_headers`

## Security Considerations

- **JWT Validation**: Verify Keycloak JWKS endpoint is accessible
- **Agent Identity**: Ensure only valid agent identities can be selected
- **Session Access**: Verify RLS policies prevent unauthorized session access
- **Credential Security**: Confirm no credentials are stored for passthrough sessions

## Performance Considerations

- **JWT Extraction**: Minimal overhead (middleware extracts once per request)
- **Session Creation**: Faster than credential-based sessions (no encryption)
- **Tool Execution**: No additional latency (JWT already available in request)

## Monitoring and Alerts

### Metrics to Monitor

- Passthrough session creation rate
- Tool test success/failure rate with passthrough sessions
- JWT validation errors
- MCP server response times

### Recommended Alerts

- Alert if JWT validation failures exceed threshold
- Alert if passthrough tool calls fail consistently
- Alert if Keycloak JWKS endpoint becomes unavailable

## Support

For issues or questions:
- Check backend logs: `backend/logs/app.log`
- Check E2E test results: `e2e/test-results/`
- Review test plan: `docs/changes/passthrough-sessions/test-plan.md`
- Contact development team
