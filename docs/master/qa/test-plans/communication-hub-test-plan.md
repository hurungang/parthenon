# Communication Hub Test Plan

## What to Test

### Message Routing
- Route messages from Web UI clients to the correct agent session
- Route agent-to-agent messages to the correct recipient agent
- Session context consistency: messages delivered in correct order within a session
- Dead-letter handling: undeliverable messages logged, not silently dropped

### WebSocket Delivery
- Two WebSocket clients both receive broadcasts correctly
- Client reconnect after disconnect: missed messages replayed from session context
- Hub restart: existing WebSocket connections gracefully disconnected with reconnect signal

### Agent-to-Agent Relay
- Inter-agent message delivery routed via Communication Hub (not direct)
- SOP delegation: parent agent delivers sub-task to child agent; result relayed back
- Relay preserves message integrity (no content modification)

### Session Context Consistency
- Conversation history appended correctly for each message turn
- Session context retrieved correctly for resumed sessions
- Concurrent sessions do not bleed context across session boundaries

### Tool Authorization Flow (Security Segregation)
- Communication Hub requests authorization from Control Center for every tool call (no bypass or caching of auth decisions)
- Tool call with valid agent certificate and sufficient permissions: Control Center returns `authorized=true` with identity token; Hub executes tool using Control Center-provided token
- Tool call with valid certificate but insufficient permissions: Control Center returns 403; Hub returns 403 to Agent Runtime with reason `insufficient_permissions`; tool NOT executed
- Tool call with invalid or expired certificate: Control Center returns 401/403; Hub returns error to Agent Runtime; tool NOT executed
- Tool call with revoked certificate: Control Center returns 403 with "Certificate revoked: {reason}"; Hub returns 403; tool NOT executed
- All authorization outcomes logged before tool execution (authorization decision audit trail)

### Security Routing Guarantee
- Communication Hub forwards identity tokens to MCP tool servers (from Control Center), NOT to Agent Runtime
- Communication Hub does NOT accept identity tokens from Agent Runtime for tool calls; token must come from Control Center authorization response
- Metadata responses routed from Control Center to Agent Runtime do NOT contain identity tokens (hub validates before forwarding)

### Authorization Failure Handling
- Authorization failure produces explicit error with actionable message; no silent failure
- Token refresh failure (503 from Control Center): Hub returns 503 to Agent Runtime with "Identity token refresh failed: {reason}"
- All 4xx/5xx responses from Control Center propagated with correct status code and message

### Tool Routing (Name Resolver)
- `system____send_notification` routed to internal Notification Service handler, not to MCP Hub
- `system____save_result` routed to internal ResultStore handler
- `system____get_recipient_group` routed to internal Notification Service handler
- `<server>____<tool>` where server is a registered MCP server → routed to MCP Hub for proxying
- Unknown server name → 404 response to Agent Runtime with "Unknown tool server: {server}"
- Name with invalid format (wrong separator count) → 400 response
- `system____*` calls are not forwarded to any MCP server
- Routing decision logic is entirely within Communication Hub; no routing code exists in Agent Runtime

### Service Trust Boundaries (Communication Hub)
- Communication Hub attempts direct PostgreSQL connection → connection refused (no `DATABASE_URL` configured)
- Communication Hub fetches session data via Control Center data APIs only
- CommHub bootstrap: certificate issued by Control Center; subsequent requests use mTLS
- Certificate renewal: CommHub renews before expiry without connection interruption

## Critical Scenarios

### Scenario: Authorized Tool Execution
- Agent Runtime sends tool call with valid client certificate
- Communication Hub forwards to Control Center for authorization
- Control Center validates cert, resolves permissions, refreshes token if needed, returns authorized=true with token
- Hub executes tool with Control Center-provided token
- Result returned to Agent Runtime

### Scenario: Unauthorized Tool Call Blocked
- Agent Runtime requests tool not in its permission set
- Communication Hub requests authorization; Control Center returns 403
- Hub returns 403 to Agent Runtime; tool NOT executed; outcome logged

### Scenario: Certificate Revocation in Flight
- Agent Runtime calls tool with valid cert
- Admin revokes cert while call is in-flight (before Communication Hub validates)
- Communication Hub validates cert, detects revocation, returns 403
- Tool NOT executed

## Edge Cases
- Hub restart during active tool call: in-flight tool call fails with clear error; agent session transitions to failed
- Redis pub/sub failure: Hub logs error, attempts reconnect, active sessions surfaced as degraded
- Concurrent authorization requests: Hub handles concurrent cert validation + permission resolution without race conditions

## Test File References

### Backend — Unit Tests
- `backend/tests/unit/test_communication_hub.py` — message routing, WebSocket delivery, relay logic

### Backend — Integration Tests
- `backend/tests/integration/test_communication_hub.py` — integration-level routing, session context consistency, concurrent session isolation
- `backend/tests/integration/test_authorization_flow.py` — full authorization chain exercised through Communication Hub: certificate validation + permission resolution + token provision; `certificate_validation_log` population; denied and authorized outcomes

### E2E Tests
- `e2e/tests/agent-security-segregation.spec.ts` — **Real Backend Integration**: tool call authorization with certificate, permission denial (403), revocation enforcement; verifies hub correctly routes authorization decisions
- `e2e/tests/conversations.spec.ts` — message routing and conversation history
