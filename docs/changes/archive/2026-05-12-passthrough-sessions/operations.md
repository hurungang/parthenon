# Operations Guide: Passthrough Sessions

## Overview

This document provides operational guidance for managing the passthrough-sessions feature in production. It covers routine operations, monitoring, troubleshooting, and maintenance procedures.

## Feature Description

The passthrough-sessions feature allows MCP sessions to authenticate using the requesting agent's JWT identity instead of stored credentials. This eliminates the need for credential management when MCP servers support agent-based authentication.

## Architecture Overview

**Key Components:**
- **MCP Session Manager**: Manages session types including passthrough
- **Communication Hub**: Detects passthrough sessions and routes agent JWT
- **MCP Proxy Engine**: Forwards agent JWT in Authorization header
- **Auth Middleware**: Extracts and stores raw JWT from incoming requests

**Data Flow:**
1. Agent makes tool call request with JWT
2. Middleware extracts JWT and stores in `request.state.raw_token`
3. Communication Hub checks if session is passthrough type
4. MCP Proxy Engine uses agent JWT instead of session credentials
5. MCP server validates agent JWT and executes tool
6. Response returns to agent with agent identity included

## Operational Responsibilities

### Daily Operations

#### Session Management

**Monitor Passthrough Sessions:**
```sql
-- Count active passthrough sessions
SELECT COUNT(*) FROM mcp_session WHERE auth_type = 'passthrough';

-- List passthrough sessions by server
SELECT 
    ms.id, 
    ms.name, 
    server.name as server_name,
    ms.created_at
FROM mcp_session ms
JOIN mcp_server server ON ms.server_id = server.id
WHERE ms.auth_type = 'passthrough'
ORDER BY ms.created_at DESC;
```

**Check Session Health:**
- Verify no orphaned passthrough sessions (server deleted but session exists)
- Monitor session creation rate for anomalies
- Review session access patterns

#### Agent Identity Management

**Verify Agent Identities:**
```sql
-- List agents using passthrough sessions
SELECT DISTINCT 
    ur.email,
    COUNT(ms.id) as passthrough_session_count
FROM mcp_session ms
JOIN user_role ur ON ms.created_by = ur.id
WHERE ms.auth_type = 'passthrough'
GROUP BY ur.email
ORDER BY passthrough_session_count DESC;
```

### Weekly Operations

#### Performance Review

**Session Performance:**
- Review tool execution times for passthrough sessions
- Compare passthrough vs. credential-based session performance
- Identify slow MCP servers or JWT validation bottlenecks

**JWT Validation:**
- Check Keycloak JWKS cache hit rate
- Monitor JWT validation failures
- Review JWT expiry and refresh patterns

#### Security Audit

**Access Control:**
- Review which agents are using passthrough sessions
- Verify RLS policies are enforcing session access restrictions
- Check for unauthorized session access attempts

**JWT Security:**
- Verify Keycloak JWT signing keys are valid
- Check for JWT tampering attempts
- Review JWT claim validation logs

### Monthly Operations

#### Capacity Planning

**Session Growth:**
- Analyze passthrough session growth trends
- Project capacity needs for session storage
- Plan for increased JWT validation load

**MCP Server Integration:**
- Identify new MCP servers that could benefit from passthrough
- Review existing credential-based sessions for passthrough migration
- Plan MCP server upgrades for JWT support

#### Compliance & Audit

**Audit Logging:**
- Review tool execution logs for passthrough sessions
- Generate compliance reports showing agent identity usage
- Archive old session records per retention policy

## Monitoring

### Key Metrics

#### Session Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| Passthrough session count | Total active passthrough sessions | N/A (trend monitoring) |
| Session creation rate | New passthrough sessions per hour | > 100/hour (potential abuse) |
| Session creation failures | Failed passthrough session creates | > 10/hour |
| Orphaned sessions | Sessions with deleted servers | > 0 |

#### Tool Execution Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| Passthrough tool call count | Total tool calls via passthrough | N/A (trend monitoring) |
| Tool call success rate | Successful vs. failed tool calls | < 95% |
| JWT validation failures | Failed JWT validations | > 5% |
| Average tool execution time | Time to execute passthrough tools | > 5 seconds |

#### Authentication Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| JWT extraction rate | Successful JWT extractions | < 99% |
| JWKS cache hit rate | Keycloak JWKS cache hits | < 90% |
| JWT expiry rate | JWTs rejected as expired | > 5% |
| Agent identity resolution | Successful agent identity lookups | < 99% |

### Monitoring Queries

#### Session Health Check

```sql
-- Passthrough sessions without valid server
SELECT 
    ms.id, 
    ms.name,
    ms.server_id
FROM mcp_session ms
LEFT JOIN mcp_server server ON ms.server_id = server.id
WHERE ms.auth_type = 'passthrough'
  AND server.id IS NULL;
```

#### Tool Execution Health

```sql
-- Recent passthrough tool execution failures
SELECT 
    tl.tool_name,
    tl.error_message,
    tl.created_at,
    ms.name as session_name
FROM tool_log tl
JOIN mcp_session ms ON tl.session_id = ms.id
WHERE ms.auth_type = 'passthrough'
  AND tl.status = 'failed'
  AND tl.created_at > NOW() - INTERVAL '1 hour'
ORDER BY tl.created_at DESC
LIMIT 50;
```

### Alerting

#### Critical Alerts

**JWT Validation Failure Spike:**
- **Trigger**: JWT validation failures > 10% over 5 minutes
- **Action**: Check Keycloak JWKS endpoint availability
- **Impact**: All passthrough tool calls will fail

**Session Creation Failure Spike:**
- **Trigger**: Session creation failures > 20/hour
- **Action**: Check database constraints and backend logs
- **Impact**: Users cannot create new passthrough sessions

#### Warning Alerts

**High Tool Execution Latency:**
- **Trigger**: Average passthrough tool execution time > 5 seconds
- **Action**: Check MCP server performance and network latency
- **Impact**: Degraded user experience

**JWKS Cache Miss Rate:**
- **Trigger**: JWKS cache hit rate < 80%
- **Action**: Review cache TTL configuration
- **Impact**: Increased latency for JWT validation

## Troubleshooting

### Common Issues

#### Issue: Passthrough Session Creation Fails

**Symptoms:**
- HTTP 400 Bad Request on session creation
- Error: "Credentials not allowed for passthrough sessions"

**Diagnosis:**
```python
# Check session creation payload
# Should NOT include encrypted_credentials field
{
    "server_id": "uuid",
    "name": "My Passthrough Session",
    "auth_type": "passthrough"
}
```

**Resolution:**
1. Verify frontend is not sending credentials for passthrough type
2. Check `mcpSessionService.ts` implementation
3. Review session creation validation logic in backend

#### Issue: JWT Not Forwarded to MCP Server

**Symptoms:**
- MCP server returns 401 Unauthorized
- Backend logs show "No agent JWT available for passthrough session"

**Diagnosis:**
```python
# Check middleware logs for JWT extraction
# Expected: "Extracted raw token for user: {user_id}"

# Check proxy logs for JWT forwarding
# Expected: "Using agent JWT for passthrough session"
```

**Resolution:**
1. Verify `request.state.raw_token` is set by middleware
2. Check MCP proxy `_build_auth_headers` logic
3. Verify agent identity is selected in frontend
4. Check Keycloak token endpoint is accessible

#### Issue: Agent Identity Not Available in Tool Test

**Symptoms:**
- Agent identity dropdown is empty
- Error: "No agent identity provided for passthrough session"

**Diagnosis:**
```typescript
// Check frontend state for agent identity
// Should have: { sub: "agent-uuid", email: "agent@example.com" }

// Check backend endpoint: GET /api/v1/agent-identities
// Should return list of available agents
```

**Resolution:**
1. Verify user has access to agent identities
2. Check RLS policies on agent identity table
3. Verify Keycloak ai_agents realm is accessible
4. Check frontend service `getAgentIdentities()` method

#### Issue: Passthrough Option Not Visible in UI

**Symptoms:**
- Passthrough auth type not appearing in session creation form
- Only api-key, oauth2 auth types visible

**Diagnosis:**
```sql
-- Verify passthrough enum exists
SELECT enum_range(NULL::mcp_session_auth_type);

-- Should include: api_key, oauth2, passthrough
```

**Resolution:**
1. Check database migration applied: `alembic current`
2. Verify backend API returns passthrough in auth types
3. Clear browser cache and reload
4. Check frontend TypeScript enum includes passthrough

### Debugging Tools

#### Enable Debug Logging

**Backend:**
```python
# In backend/app/core/logging.py
# Set log level to DEBUG for MCP proxy
logging.getLogger("app.core.mcp_proxy").setLevel(logging.DEBUG)
```

**Frontend:**
```typescript
// In browser console
localStorage.setItem('DEBUG_MCP', 'true');
// Reload page to enable debug logs
```

#### Inspect JWT Token

```powershell
# Decode JWT to inspect claims (for debugging only)
.\decode-jwt.ps1 -Token "eyJhbGc..."

# Expected claims:
# - sub: agent UUID
# - email: agent email
# - iss: Keycloak issuer URL
# - exp: expiration timestamp
```

#### Test Passthrough Flow Manually

```powershell
# Test tool call with passthrough session
$token = "Bearer eyJhbGc..."
$body = @{
    tool_name = "helloWorld"
    server_slug = "demo"
    session_id = $null  # Optional for passthrough
    agent_subject = "agent-uuid"
    arguments = @{}
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:8000/api/v1/communication-hub/test-tool" `
    -Method POST `
    -Headers @{ "Authorization" = $token } `
    -Body $body `
    -ContentType "application/json"
```

## Maintenance Procedures

### Session Cleanup

**Remove Orphaned Passthrough Sessions:**
```sql
-- Find orphaned sessions
SELECT ms.id, ms.name
FROM mcp_session ms
LEFT JOIN mcp_server server ON ms.server_id = server.id
WHERE ms.auth_type = 'passthrough'
  AND server.id IS NULL;

-- Delete orphaned sessions (after review)
DELETE FROM mcp_session
WHERE id IN (
    SELECT ms.id
    FROM mcp_session ms
    LEFT JOIN mcp_server server ON ms.server_id = server.id
    WHERE ms.auth_type = 'passthrough'
      AND server.id IS NULL
);
```

### Performance Optimization

**JWKS Cache Tuning:**
```python
# In backend/app/auth.py
# Adjust cache TTL if needed (default: 10 minutes)
JWKS_CACHE_TTL = 600  # seconds

# Increase for more stable environments
# Decrease for rapidly rotating keys
```

**Database Indexing:**
```sql
-- Add index for passthrough session queries
CREATE INDEX IF NOT EXISTS idx_mcp_session_auth_type 
ON mcp_session(auth_type) 
WHERE auth_type = 'passthrough';
```

### Security Hardening

**JWT Validation:**
- Verify Keycloak JWKS endpoint uses HTTPS
- Enable strict issuer validation
- Set appropriate JWT expiry times (15-30 minutes)

**Access Control:**
- Review and update RLS policies regularly
- Audit agent identity access logs
- Implement rate limiting on tool execution

## Runbooks

### Runbook: High JWT Validation Failure Rate

**Scenario**: JWT validation failures exceed 10% over 5 minutes

**Steps:**
1. Check Keycloak JWKS endpoint availability
2. Verify Keycloak is running and accessible
3. Check network connectivity to Keycloak
4. Review Keycloak logs for signing key rotation
5. If Keycloak is down, escalate to infrastructure team
6. If keys rotated, restart backend to refresh JWKS cache

### Runbook: Passthrough Tool Calls Failing

**Scenario**: All passthrough tool calls returning 401 Unauthorized

**Steps:**
1. Verify agent JWT is being extracted by middleware
2. Check MCP proxy logs for JWT forwarding
3. Test MCP server JWT validation directly
4. Verify Keycloak ai_agents realm is accessible
5. Check MCP server logs for JWT rejection reason
6. If MCP server issue, contact MCP server admin
7. If Parthenon issue, escalate to development team

### Runbook: Session Creation Failures

**Scenario**: Users unable to create passthrough sessions

**Steps:**
1. Check database migration status: `alembic current`
2. Verify passthrough enum exists in database
3. Check backend API for errors in session creation endpoint
4. Review database constraints on mcp_session table
5. Test session creation with Postman/curl
6. If database issue, run migration repair
7. If backend issue, escalate to development team

## Backup and Recovery

### Backup Procedures

**Session Data Backup:**
```bash
# Backup mcp_session table
pg_dump -h localhost -U parthenon -t mcp_session parthenon_db > mcp_session_backup.sql
```

**Configuration Backup:**
```powershell
# Backup passthrough-related configuration
Copy-Item backend\.env backend\.env.backup
Copy-Item frontend\.env.local frontend\.env.local.backup
```

### Recovery Procedures

**Restore Session Data:**
```bash
# Restore from backup
psql -h localhost -U parthenon parthenon_db < mcp_session_backup.sql
```

**Rollback Migration:**
```powershell
cd backend
alembic downgrade -1
```

## Change Management

### Adding New Passthrough-Compatible MCP Servers

**Checklist:**
1. Verify MCP server supports JWT authentication
2. Test JWT validation with demo token
3. Configure MCP server with Keycloak JWKS URL
4. Register MCP server in Parthenon Hub
5. Mark server as passthrough-compatible in metadata
6. Test tool execution with passthrough session
7. Document MCP server JWT requirements

### Migrating Existing Sessions to Passthrough

**Process:**
1. Identify credential-based sessions that could use passthrough
2. Verify MCP servers support JWT authentication
3. Create passthrough sessions for migrated servers
4. Update role configurations to use passthrough
5. Test tool execution with new passthrough sessions
6. Decommission old credential-based sessions
7. Delete stored credentials from old sessions

## Support Escalation

### Level 1 Support

**Responsibilities:**
- Handle user inquiries about passthrough sessions
- Verify basic functionality (session creation, tool test)
- Check service availability (Keycloak, backend, frontend)

**Escalation Criteria:**
- JWT validation failures persist for > 15 minutes
- Session creation failures affect multiple users
- Tool execution failures across all passthrough sessions

### Level 2 Support

**Responsibilities:**
- Investigate backend logs for errors
- Check database for data integrity issues
- Perform basic troubleshooting (restart services, clear caches)

**Escalation Criteria:**
- Root cause requires code changes
- Database corruption detected
- Security incident suspected

### Level 3 Support (Development Team)

**Responsibilities:**
- Fix bugs in passthrough implementation
- Apply emergency patches
- Perform database repairs
- Investigate security incidents

## Documentation Links

- [PRD](./prd.md) - Product requirements
- [Architecture](./architecture.md) - System architecture
- [Tech Spec](./tech-spec.md) - Technical specifications
- [Test Plan](./test-plan.md) - Testing strategy
- [Deployment Guide](./deployment.md) - Deployment procedures
