# Service Decomposition — Test Plan

## Test Strategy

Validation focuses on enforcing trust boundaries between the three services: Control Center must be the sole database owner; Agent Runtime and Communication Hub must have no direct database access; all service-to-service calls must use mTLS with certificate validation; agent-instance certificates must be blocked from `/internal/*` endpoints; and per-call token resolution must work correctly. Testing spans three layers: backend integration tests (pytest) verify data isolation and certificate enforcement using authenticated test service certificates — tests bootstrap with Control Center and make real mTLS calls to all three services without mocking service auth; frontend component tests (Vitest) remain largely unchanged (UI not affected); E2E tests (Playwright) verify full workflows across the three-service architecture with at least one real backend test variant.

---

## Coverage Areas

### Critical: Trust Boundary Enforcement
**Why critical**: Core security requirement. Agent Runtime and Communication Hub must not bypass Control Center data APIs.

**Test approach**: Negative tests — attempt direct database connections from AR/CH and verify they fail; attempt to call `/internal/*` endpoints with agent-instance certs and verify 403 responses.

### Critical: Certificate Infrastructure
**Why critical**: All service-to-service auth depends on certificate issuance, validation, and renewal.

**Test approach**: Integration tests for bootstrap flow, certificate renewal, revocation, and mTLS validation middleware in all three services.

### Critical: Data Service Layer
**Why critical**: Agent Runtime and Communication Hub depend entirely on Control Center data APIs for all context.

**Test approach**: Integration tests for each internal data API endpoint; verify agent execution and message routing succeed using API-only data access.

### Critical: Service-to-Service Authentication
**Why critical**: Services must validate each other's certificates to prevent unauthorized access.

**Test approach**: Integration tests with valid and invalid certificates; verify 401/403 responses; verify agent-instance certs are blocked from `/internal/*`.

### Critical: Test Service Authentication
**Why critical**: Test automation depends on the test suite being able to authenticate as a trusted service; without this, integration tests must mock service auth and cannot validate real cross-service flows.

**Test approach**: Integration tests for test service bootstrap, authenticated client fixtures (`cc_client`, `ar_client`, `ch_client`), and full agent execution flow validation with real service calls and no mocking.

### Important: Control Flow
**Why important**: Control Center must be able to trigger agent execution and message dispatch via network calls.

**Test approach**: Integration tests for Control Center → Agent Runtime trigger endpoint and Control Center → Communication Hub dispatch endpoint.

### Important: Dev Environment
**Why important**: Developers need a working local setup with all three services.

**Test approach**: Manual verification of docker-compose setup, parthenon.ps1 script, health checks, and full workflow in local dev.

### Standard: E2E Workflows
**Why standard**: User-facing flows should work the same as before service decomposition.

**Test approach**: Existing Playwright E2E test suite with at least one real backend test variant (no mocks) to catch integration issues.

### Critical: Unified Tool Naming Convention
**Why critical**: All tool names must follow `server____tool` (4-underscore separator) so names are globally unique, routing is deterministic, and the `system` reservation is enforced platform-wide. Violations cause silent routing failures or collisions.

**Test approach**: Unit tests for the central `tool_naming` module — parse, build, validate, and classify functions; negative tests for malformed names, reserved-prefix violations, and names containing `____` in the server segment.

### Critical: Uniform Tool Routing via CommHub
**Why critical**: Agent Runtime must not contain any branching logic that distinguishes system tools from MCP tools. All tool calls go to CommHub; CommHub owns routing. Any AR-side branching reintroduces the tight coupling this decomposition removes.

**Test approach**: Integration tests that inspect the AR task loop — verify no system-tool-specific code paths exist; verify every tool call (system and MCP alike) is forwarded to CommHub's tool-call endpoint; verify CommHub routes `system____*` calls to internal system handlers and `<mcp-server>____*` calls to the appropriate MCP connector.

### Important: Explicit save_result Invocation
**Why important**: The runtime previously auto-saved results at agent completion. Removing this auto-invocation changes observable behavior: results are only persisted when the agent's SOP explicitly instructs it to call `save_result`. Tests must validate both the positive path (agent calls it → record created) and the negative path (agent skips it → no record created).

**Test approach**: Integration tests that run an agent to completion and query the `result_records` table and `/results` endpoint; one test with an agent instructed to call `save_result`, one without.

---

## Critical Scenarios

### WHEN Agent Runtime attempts direct database connection
**THEN** Connection fails with "database not configured" or "connection refused" error  
**AND** Agent Runtime logs show no database connection attempts  
**AND** Agent execution succeeds using Control Center API only

### WHEN Communication Hub attempts direct database connection
**THEN** Connection fails with "database not configured" or "connection refused" error  
**AND** Communication Hub logs show no database connection attempts  
**AND** Message routing succeeds using Control Center API only

### WHEN Agent Runtime starts without valid certificate
**THEN** Agent Runtime calls Control Center `/internal/bootstrap` endpoint  
**AND** Control Center issues agent-instance certificate (24 h validity)  
**AND** Agent Runtime stores certificate in memory  
**AND** Agent Runtime health check shows "certificate loaded"

### WHEN Communication Hub starts without valid certificate
**THEN** Communication Hub calls Control Center `/internal/bootstrap` endpoint  
**AND** Control Center issues service certificate (30 d validity)  
**AND** Communication Hub stores certificate in memory  
**AND** Communication Hub health check shows "certificate loaded"

### WHEN Agent Runtime bootstrap with wrong bootstrap key
**THEN** Agent Runtime calls Control Center `/internal/bootstrap` with incorrect key
**AND** Control Center rejects request with 401 Unauthorized
**AND** Response message indicates "invalid bootstrap key"
**AND** Agent Runtime logs show authentication failure
**AND** Agent Runtime fails to start (no certificate loaded)

### WHEN Communication Hub bootstrap with Agent Runtime's key
**THEN** Communication Hub calls Control Center `/internal/bootstrap` with Agent Runtime's bootstrap key
**AND** Control Center rejects request with 401 Unauthorized
**AND** Response message indicates "bootstrap key does not match service identity"
**AND** Communication Hub fails to start (no certificate loaded)

### WHEN Agent Runtime calls Control Center `/internal/agents/{id}/plan` with agent-instance certificate
**THEN** Control Center validates certificate signature and expiry  
**AND** Control Center accepts request (agent-instance certs are allowed for this endpoint)  
**AND** Response contains agent plan data

### WHEN Agent Runtime calls Control Center `/internal/bootstrap` with agent-instance certificate
**THEN** Control Center blocks request with 403  
**AND** Response message indicates "agent-instance certificates not allowed for bootstrap"

### WHEN Communication Hub calls Control Center `/internal/sessions/{id}` with service certificate
**THEN** Control Center validates certificate signature and expiry  
**AND** Control Center accepts request (service certs are allowed)  
**AND** Response contains session data

### WHEN Agent Runtime certificate expires
**THEN** Agent Runtime renews certificate 1 hour before expiry  
**AND** New certificate has 24 h validity  
**AND** Old certificate is atomically replaced with no downtime  
**AND** Agent execution continues without interruption

### WHEN Control Center restarts and generates new CA
**THEN** Agent Runtime detects CA expiry mismatch on next startup  
**AND** Agent Runtime queries Control Center `/health` to get current CA expiry  
**AND** Agent Runtime detects expiry time difference (more than 1 second tolerance)  
**AND** Agent Runtime deletes old cert/key/CA files  
**AND** Agent Runtime triggers re-bootstrap automatically  
**AND** Agent Runtime obtains new certificate signed by new CA  
**AND** Agent Runtime starts successfully with new certificate

### WHEN Communication Hub certificate signature invalid against current CA
**THEN** Communication Hub validates local certificate signature on startup  
**AND** Signature validation fails (cert not signed by current CA)  
**AND** Communication Hub triggers re-bootstrap automatically  
**AND** Communication Hub obtains new certificate  
**AND** Communication Hub starts successfully with new certificate

### WHEN test service bootstraps with Control Center
**THEN** Control Center validates test service bootstrap key  
**AND** Control Center issues 30-day service certificate with CN `service:test-service`  
**AND** Test service stores certificate for use in authenticated client fixtures

### WHEN test service uses invalid bootstrap key
**THEN** Control Center rejects request with 401 Unauthorized  
**AND** Response message indicates "invalid bootstrap key"  
**AND** Test service receives no certificate

### WHEN integration test uses authenticated client fixture
**THEN** Test suite presents test service certificate to Control Center  
**AND** All `/internal/*` data API endpoints accept the test service certificate  
**AND** No mocking of service auth is required in any integration test

### WHEN integration test triggers full execution flow
**THEN** Test suite calls Control Center to trigger agent execution  
**AND** Control Center calls Agent Runtime `/execute` with mTLS  
**AND** Agent Runtime fetches plan and context from Control Center  
**AND** Agent Runtime returns result to Control Center  
**AND** Control Center dispatches result to Communication Hub  
**AND** Full CC → AR → CC → CH flow completes without mocking

### WHEN user attempts to delete agent identity referenced by AgentType
**THEN** Backend returns 409 Conflict error  
**AND** Error detail indicates identity is referenced by AgentType  
**AND** Frontend catches 409 error  
**AND** Frontend displays user-friendly message: "Cannot delete identity {name} because it is referenced by one or more agent types"  
**AND** Identity is not deleted

### WHEN user refreshes agent identity token and refresh fails
**THEN** Backend attempts token refresh with exponential backoff (max 3 attempts)  
**AND** All refresh attempts fail (e.g., refresh token expired, Keycloak unreachable)  
**AND** Backend sets identity `token_status` to `refresh_failed`  
**AND** Backend returns error response with detail message  
**AND** Frontend catches error  
**AND** Frontend displays user-friendly error message: "Failed to refresh token for {name}: {error detail}"  
**AND** User sees option to re-authenticate
**AND** Agent Runtime calls `/internal/bootstrap` to get new certificate  
**AND** Agent Runtime atomically swaps in-memory certificate  
**AND** Agent Runtime continues processing requests without downtime

### WHEN certificate is revoked
**THEN** Control Center marks certificate as revoked in database  
**AND** All three services check revocation status on inbound connections  
**AND** Requests with revoked certificate return 401  
**AND** Logs show "certificate revoked" error message

### WHEN Control Center triggers agent execution on Agent Runtime
**THEN** Control Center calls Agent Runtime `/execute` endpoint with mTLS  
**AND** Agent Runtime validates Control Center certificate  
**AND** Agent Runtime fetches agent plan from Control Center  
**AND** Agent Runtime executes agent and returns result

### WHEN Control Center dispatches message via Communication Hub
**THEN** Control Center calls Communication Hub `/dispatch` endpoint with mTLS  
**AND** Communication Hub validates Control Center certificate  
**AND** Communication Hub routes message to active WebSocket connections  
**AND** Message delivered to Web UI client

### WHEN Communication Hub resolves token for agent tool call
**THEN** Communication Hub extracts agent-instance certificate from request  
**AND** Communication Hub calls Control Center `/internal/tokens/resolve`  
**AND** Control Center returns short-lived token (5 min) + permission list  
**AND** Communication Hub validates tool against permissions  
**AND** Communication Hub injects token into MCP tool call context

### WHEN tool_naming.parse_tool_name is called with valid names
**THEN** `parse_tool_name("system____save_result")` returns `("system", "save_result")`  
**AND** `parse_tool_name("hello-world____helloWorld")` returns `("hello-world", "helloWorld")`  
**AND** `is_system_tool("system____save_result")` returns `True`  
**AND** `is_system_tool("hello-world____helloWorld")` returns `False`  
**AND** `build_tool_name("system", "save_result")` returns `"system____save_result"`  
**AND** `build_tool_name("hello-world", "helloWorld")` returns `"hello-world____helloWorld"`

### WHEN tool_naming functions receive invalid or reserved inputs
**THEN** `parse_tool_name("save_result")` (no separator) raises `ValueError`  
**AND** `parse_tool_name("a____b____c")` (ambiguous separator) raises `ValueError`  
**AND** `parse_tool_name("")` raises `ValueError`  
**AND** `build_tool_name("my____server", "tool")` (server contains `____`) raises `ValueError`  
**AND** All error messages are descriptive enough to identify the offending input

### WHEN Control Center assembles agent context and skill has no system tool assignment
**THEN** Agent context returned to Agent Runtime does not include any `system____*` tools  
**AND** System tools appear in agent context only for skills that explicitly list them  
**AND** No system tools are auto-injected regardless of agent type or skill

### WHEN agent executes and explicitly calls system____save_result
**THEN** Communication Hub receives the tool call with name `system____save_result`  
**AND** Communication Hub routes call to the system handler (not an MCP server)  
**AND** System handler creates a `ResultRecord` entry in the `result_records` table  
**AND** `GET /results` endpoint returns the new result record  
**AND** ResultRecord contains correct agent session ID, content, and timestamp

### WHEN agent execution completes without calling system____save_result
**THEN** No new `ResultRecord` row is created in the `result_records` table  
**AND** `GET /results` returns zero new records for that session  
**AND** Agent session status is marked complete without error

### WHEN Communication Hub receives tool call system____save_result
**THEN** CommHub identifies server segment as `system` (reserved)  
**AND** CommHub routes call to internal system handler — no MCP server lookup performed  
**AND** System handler executes and returns result to Agent Runtime

### WHEN Communication Hub receives tool call hello-world____helloWorld
**THEN** CommHub identifies server segment as `hello-world` (MCP server slug)  
**AND** CommHub looks up the `hello-world` MCP connector in Control Center  
**AND** CommHub forwards call to the `hello-world` MCP server  
**AND** MCP server returns result and CommHub relays it to Agent Runtime

### WHEN Agent Runtime task loop processes any tool call
**THEN** Agent Runtime forwards the tool call to CommHub without inspecting the tool name  
**AND** No conditional branching exists in AR task loop based on tool name prefix or server name  
**AND** Source inspection of `runtime_executor` shows zero references to system-tool-specific handling  
**AND** AR task loop behavior is identical for `system____*` and `<mcp-server>____*` calls

### WHEN user triggers agent execution via Web UI
**THEN** Web UI sends message to Communication Hub (WebSocket)  
**AND** Communication Hub validates user JWT  
**AND** Communication Hub calls Control Center to resolve agent context  
**AND** Control Center triggers Agent Runtime `/execute` endpoint  
**AND** Agent Runtime fetches plan and context from Control Center  
**AND** Agent Runtime executes agent  
**AND** Agent Runtime returns result to Control Center  
**AND** Control Center dispatches result to Communication Hub  
**AND** Communication Hub delivers result to Web UI WebSocket

---

## Edge Cases & Risks

### Edge Case: Certificate renewal fails
**Risk**: Service continues running with expired certificate; all requests fail with 401.  
**Mitigation**: Agent Runtime and Communication Hub retry renewal every 5 minutes on failure; logs show clear warning; monitoring alerts on repeated renewal failures.

### Edge Case: Control Center becomes unavailable
**Risk**: Agent Runtime and Communication Hub cannot fetch data; all operations fail.  
**Mitigation**: Agent Runtime and Communication Hub retry requests with exponential backoff (max 3 attempts); return 503 to clients; health checks reflect upstream unavailability.

### Edge Case: Bootstrap endpoint fails during startup
**Risk**: Agent Runtime or Communication Hub cannot start without valid certificate.  
**Mitigation**: Services exit with clear error message; orchestrator (docker-compose, Kubernetes) restarts service; logs show bootstrap failure reason.

### Edge Case: Agent-instance certificate used for `/internal/*` endpoint
**Risk**: Agent Runtime bypasses access controls by calling internal endpoints directly.  
**Mitigation**: Control Center middleware checks certificate CN; agent-instance certs (`agent-type:instance-id`) return 403 on `/internal/*` endpoints; only service certs (`service:name`) are allowed.

### Edge Case: Token resolution call fails in Communication Hub
**Risk**: MCP tool call cannot proceed without identity token.  
**Mitigation**: Communication Hub retries token resolution up to 3 times; returns 503 if all attempts fail; logs show token resolution failure with agent-instance ID.

### Edge Case: Service-to-service call times out
**Risk**: Control Center → Agent Runtime trigger call times out; agent execution never starts.  
**Mitigation**: Control Center sets 30s timeout on trigger calls; logs timeout as error; returns 504 to client; user can retry.

### Edge Case: Multiple services start simultaneously
**Risk**: Agent Runtime and Communication Hub attempt bootstrap before Control Center is ready.  
**Mitigation**: docker-compose and Kubernetes manifests enforce service startup order (Control Center first); health checks prevent premature routing; bootstrap retries until Control Center is available.

### Risk: Database migration not applied before service starts
**Risk**: Services expect schema changes that don't exist; queries fail.  
**Mitigation**: Control Center runs Alembic migrations on startup (existing pattern); Agent Runtime and Communication Hub have no database access (no migration risk).

---

## Acceptance Criteria Checklist

Maps to PRD acceptance criteria:

- [ ] Agent Runtime and Communication Hub cannot connect to PostgreSQL directly (verified by negative tests)
- [ ] All service-to-service communication uses mTLS with certificate validation (verified by integration tests and network traffic capture)
- [ ] Communication Hub and Agent Runtime bootstrap by requesting certificates from Control Center using unique per-service bootstrap keys (verified by startup integration tests and key validation tests)
- [ ] Control Center can call Agent Runtime to trigger execution and Communication Hub to send messages (verified by control flow integration tests)
- [ ] Communication Hub and Agent Runtime validate Control Center certificates for all incoming calls (verified by certificate validation integration tests)
- [ ] After decomposition, each service can be deployed, scaled, and restarted independently (verified by docker-compose and Kubernetes deployment tests)
- [ ] No user or agent can bypass Control Center to access or modify data (verified by trust boundary negative tests)
- [ ] All inter-service calls are logged for auditability (verified by log inspection in integration tests)
- [ ] Test suite can bootstrap with Control Center using a test service bootstrap key and obtain a 30-day service certificate (verified by test service auth integration tests)
- [ ] All integration tests can make authenticated calls to Control Center, Agent Runtime, and Communication Hub without mocking (verified by authenticated client fixture tests)
- [ ] Test suite validates full agent execution flow (CC → AR → CC → CH) with real service calls and no mocking (verified by full execution flow integration test)
- [ ] All tool names follow `server____tool` format; `system` is a reserved server name; MCP server slugs cannot contain `____` (verified by tool_naming unit tests and CommHub routing integration tests)
- [ ] Agent Runtime treats all tool calls uniformly — no system-tool-specific branches in the AR task loop (verified by source inspection test and CommHub routing integration tests)
- [ ] Runtime does not auto-call `save_result` at agent completion; ResultRecord is created only when agent explicitly invokes `system____save_result` (verified by explicit-call and no-call integration tests)
- [ ] CommHub correctly routes `system____*` tool calls to internal system handlers and `<mcp-server>____*` calls to MCP connectors (verified by CommHub routing integration tests)
- [ ] Agent context assembled by Control Center includes system tools only when explicitly assigned to the skill — no auto-injection (verified by context assembly unit/integration tests)

---

## Test File References

### Backend Integration Tests (`backend/tests/`)

**Service Isolation Tests**:
- `backend/tests/integration/test_service_isolation.py` — Verify Agent Runtime and Communication Hub have no direct database access

**Certificate Infrastructure Tests**:
- `backend/tests/integration/test_certificate_bootstrap.py` — Bootstrap flow for Agent Runtime and Communication Hub
- `backend/tests/integration/test_certificate_renewal.py` — Automatic certificate renewal before expiry
- `backend/tests/integration/test_certificate_revocation.py` — Certificate revocation and validation
- `backend/tests/integration/test_ca_expiry_detection.py` — CA expiry detection and automatic re-bootstrap on Control Center restart

**Data Service Layer Tests**:
- `backend/tests/integration/test_control_center_data_api.py` — Internal data API endpoints for Agent Runtime and Communication Hub
- `backend/tests/integration/test_agent_runtime_data_client.py` — Agent Runtime HTTP client for Control Center APIs
- `backend/tests/integration/test_comm_hub_data_client.py` — Communication Hub HTTP client for Control Center APIs

**Service-to-Service Auth Tests**:
- `backend/tests/integration/test_mtls_validation.py` — mTLS certificate validation in all three services
- `backend/tests/integration/test_agent_instance_cert_block.py` — Block agent-instance certs from `/internal/*` endpoints

**Control Flow Tests**:
- `backend/tests/integration/test_control_center_trigger.py` — Control Center → Agent Runtime trigger endpoint
- `backend/tests/integration/test_control_center_dispatch.py` — Control Center → Communication Hub dispatch endpoint

**Test Service Authentication Tests**:
- `backend/tests/fixtures/test_service_certificate.py` — `TestServiceCertificateManager` class; bootstraps with Control Center, manages 30-day cert lifecycle
- `backend/tests/fixtures/authenticated_clients.py` — `cc_client`, `ar_client`, `ch_client` pytest fixtures providing mTLS-authenticated clients to all three services
- `backend/tests/integration/test_service_auth.py` — Validates test service bootstrap, 30-day cert issuance, and authenticated access to all three services

**Tool Naming Unit Tests**:
- `backend/tests/unit/test_tool_naming.py` — Unit tests for the central `tool_naming` module: `parse_tool_name`, `build_tool_name`, `is_system_tool`; valid inputs, invalid inputs, reserved-prefix enforcement

**Tool Routing and save_result Integration Tests**:
- `backend/tests/integration/test_tool_routing.py` — CommHub routes `system____save_result` to system handler; CommHub routes `hello-world____helloWorld` to MCP server; AR task loop sends all tool calls to CommHub with no system-tool-specific branching
- `backend/tests/integration/test_save_result_behavior.py` — Agent calls `save_result` → ResultRecord created and visible at `/results`; agent completes without `save_result` → no ResultRecord created
- `backend/tests/integration/test_agent_context_assembly.py` — System tools appear in agent context only when explicitly assigned to the skill; no system tools auto-injected for skills without explicit assignment

### Frontend Component Tests (`frontend/src/__tests__/`)

**Agent Identity Error Display Tests**:
- `frontend/src/__tests__/AgentIdentityListPage.test.tsx` — Verify delete conflict error (409) displays user-friendly message
- `frontend/src/__tests__/AgentIdentityListPage.test.tsx` — Verify refresh token error displays error detail to user

**No other changes expected** — UI is unaffected by backend service decomposition.

### E2E Tests (`e2e/tests/`)

**Real Backend Integration Tests** (at least one required):
- `e2e/tests/real-backend/test_agent_execution_three_services.spec.ts` — Full agent execution flow across Control Center, Agent Runtime, and Communication Hub without mocks

**Standard E2E Tests** (can use mocks):
- Existing E2E test suite runs against three-service architecture; most tests can continue using `page.route()` mocks for speed

---

## Test Execution Notes

### Pre-Test Checklist
- Verify all three services are running: `docker-compose ps` or `./parthenon.ps1 status backend`
- Verify health checks pass for all services: `curl http://localhost:8000/health`, `curl http://localhost:8001/health`, `curl http://localhost:8002/health`
- Verify certificate bootstrap succeeded: check logs for "certificate loaded" message
- Verify database migrations applied: `alembic current` in Control Center container

### Running Backend Tests
```powershell
cd backend
poetry run pytest tests/integration/test_service_isolation.py -v
poetry run pytest tests/integration/test_certificate_*.py -v
poetry run pytest tests/integration/test_control_center_data_api.py -v
poetry run pytest tests/integration/test_mtls_validation.py -v
```

### Running E2E Tests
```powershell
cd e2e
npm test -- tests/real-backend/test_agent_execution_three_services.spec.ts
```

### Debugging Tips
- Check service logs: `docker-compose logs control-center`, `docker-compose logs agent-runtime`, `docker-compose logs communication-hub`
- Verify certificate validity: Check `/health` endpoint response includes certificate expiry time
- Capture network traffic: Use tcpdump or Wireshark to verify mTLS is used for all service-to-service calls
- Check database connections: `docker-compose exec control-center psql -U parthenon -c "SELECT count(*) FROM pg_stat_activity"` — only Control Center should have connections
