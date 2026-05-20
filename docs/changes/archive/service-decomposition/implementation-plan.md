# Implementation Plan: Service Decomposition

## Overview

This plan extracts the Parthenon monolithic backend into three independently deployable FastAPI services — Control Center (sole database owner), Agent Runtime (stateless LangChain executor), and Communication Hub (message broker and agent gateway) — with certificate-based mutual TLS authentication enforced at every service boundary. Work proceeds in seven phases ordered by dependency: service extraction and entry points first, then certificate infrastructure, data service layer, auth enforcement, control flow wiring, dev environment updates, and finally testing and validation.

---

## Task Checklist

### Phase 1 — Service Extraction
- [x] 1.1 Create Agent Runtime standalone FastAPI application entry point — _Done when: AR starts with `uvicorn app.agent_runtime.main:app` without error, serves `/health`, and imports no database session factory_
- [x] 1.2 Create Communication Hub standalone FastAPI application entry point — _Done when: CH starts with `uvicorn app.communication_hub.main:app` without error and authorization middleware runs without a DB session_
- [x] 1.3 Refactor Control Center main application to retain only platform API, CA, token/permission, and plan generation — _Done when: `backend/app/main.py` starts successfully with all `/api/v1/*` routes and no agent-execution or broker route registrations_
- [x] 1.4 Annotate all direct DB session usages in Agent Runtime and Communication Hub module trees — _Done when: every `AsyncSession`, `get_db`, and `DbSession` import in AR/CH modules is tagged with a standard replacement comment_

### Phase 2 — Certificate Infrastructure
- [x] 2.1 Create `/internal/bootstrap` endpoint in Control Center for certificate issuance to peer services — _Done when: endpoint issues agent-instance certs (24h) and service certs (30d) based on `service_type` in the request; validates per-service bootstrap keys (agent-runtime key vs comm-hub key); unit test verifies correct cert type per service and key validation_
- [x] 2.2 Wire Agent Runtime startup to call `/internal/bootstrap` and load the issued certificate — _Done when: AR requests and loads its cert before accepting traffic; `CertificateManager` is in loaded state on first health check_
- [x] 2.3 Create certificate manager for Communication Hub and wire to `/internal/bootstrap` on startup — _Done when: CH bootstraps with a valid 30d service cert and `configure_mtls_client()` returns an mTLS-configured `httpx.AsyncClient`_
- [x] 2.4 Implement certificate renewal background tasks in Agent Runtime and Communication Hub — _Done when: both services auto-renew at 80% lifetime, retry on failure, and atomically swap the in-memory certificate with no downtime_
- [x] 2.5 Implement CA expiry detection and automatic re-bootstrap in Agent Runtime and Communication Hub — _Done when: on startup, peer services query Control Center `/health` to compare CA cert expiry; if mismatch or signature invalid, delete old certs and trigger re-bootstrap automatically_

### Phase 3 — Data Service Layer
- [x] 3.1 Create Control Center internal data API for Agent Runtime — _Done when: CC exposes authenticated endpoints for agent plan, skills/SOPs, and model config; service cert required; agent-instance cert rejected_
- [x] 3.2 Create Control Center internal data API for Communication Hub — _Done when: CC exposes authenticated endpoints for session data, conversation history, and user permissions; service cert required_
- [x] 3.3 Create HTTP data client in Agent Runtime and replace all direct DB calls with CC API calls — _Done when: AR integration test resolves agent context from a live CC without any `AsyncSession` in the call stack_
- [x] 3.4 Create HTTP data client in Communication Hub and replace all direct DB calls with CC API calls — _Done when: CH integration test resolves session data and permissions from CC without direct DB access_

### Phase 4 — Service-to-Service Authentication
- [x] 4.1 Harden `require_service_certificate` in Control Center to enforce mTLS client cert on all `/internal/*` routes — _Done when: requests to any `/internal/*` route without a valid service cert return 401_
- [x] 4.2 Implement inbound certificate validation in Agent Runtime for calls from Control Center — _Done when: AR rejects requests from any cert other than CC's service cert with 401_
- [x] 4.3 Implement inbound certificate validation in Communication Hub for control plane calls from Control Center — _Done when: CH rejects unauthenticated internal route calls while still accepting JWT-authenticated WebSocket connections_
- [x] 4.4 Add certificate revocation check to inbound connection validation in all three services — _Done when: a revoked cert is rejected by all three services with 401_
- [x] 4.5 Enforce agent-instance certificate block on Control Center `/internal/*` endpoints — _Done when: a request with an agent-instance cert (CN=`agent-instance:*`) to any `/internal/*` route returns 403_

### Phase 5 — Control Flow Implementation
- [x] 5.1 Create agent execution trigger endpoint in Agent Runtime — _Done when: AR accepts an mTLS-authenticated POST from CC, enqueues an AgentJob, and `SessionDispatcher` picks it up_
- [x] 5.2 Create message dispatch endpoint in Communication Hub — _Done when: CH accepts an mTLS-authenticated POST from CC and the message appears in the correct broker channel_
- [x] 5.3 Create Control Center HTTP client for triggering Agent Runtime — _Done when: initiating agent execution from the Platform API results in an HTTP call to AR's execute endpoint rather than in-process dispatch_
- [x] 5.4 Create Control Center HTTP client for dispatching via Communication Hub — _Done when: a platform-initiated message reaches the CH broker via the HTTP client_
- [x] 5.5 Route AgentJob results back through Control Center to Communication Hub — _Done when: full cycle test — trigger → execute → persist result in CC → CH delivers result to UI WebSocket — passes_

### Phase 6 — Dev Environment
- [x] 6.1 Split `docker-compose.yml` into `control-center`, `agent-runtime`, and `communication-hub` service definitions — _Done when: `docker compose up` starts all three services with correct network configuration and health checks pass_
- [x] 6.2 Create per-service Dockerfile configuration — _Done when: each service image builds and runs independently_
- [x] 6.3 Define and document environment variables for each service — _Done when: each service starts without error using only its documented environment variables_
- [x] 6.4 Update `parthenon.ps1` to support per-service start/stop by name — _Done when: `.\parthenon.ps1 start -Services agent-runtime` starts only the AR container and the health check confirms it is up_
- [x] 6.5 Verify and update `/health` endpoints for all three services — _Done when: all three services return `{"status": "ok", "service": "<name>"}` from `/health`_

### Phase 7 — Testing & Validation
- [x] 7.1 Integration test: Agent Runtime bootstrap flow — _Done when: test passes against a real CC test instance; cert is valid X.509 with CN `agent-instance:*` and 24h validity_
- [x] 7.2 Integration test: Communication Hub bootstrap flow — _Done when: CH receives a service cert with CN `service:communication-hub` and 30d validity from CC_
- [x] 7.3 Integration test: Agent Runtime data API client — _Done when: AR resolves agent context from CC using mTLS with no direct DB calls in the AR call stack_
- [x] 7.4 Integration test: Control Center → Agent Runtime execution trigger — _Done when: AgentJob created by trigger transitions from `queued` to `running` via `SessionDispatcher`_
- [x] 7.5 Integration test: Control Center → Communication Hub message dispatch — _Done when: message dispatched by CC arrives in the broker channel within 2 seconds; CH mTLS cert validated_
- [x] 7.6 Integration test: Certificate revocation enforcement — _Done when: a revoked cert is rejected by all three services; test confirms 401 at each boundary_
- [x] 7.7 E2E test: Full user prompt flow against live 3-service stack — _Done when: E2E test completes without any `page.route()` mocking; result delivered to UI via CH WebSocket_
- [x] 7.8 Security test: DB isolation for Agent Runtime and Communication Hub — _Done when: AR and CH processes have no `DATABASE_URL` and a DB connection attempt returns an error_

### Phase 8 — Agent Identity Error Handling (Post-Implementation Fix)
- [x] 8.1 Fix agent identity delete conflict error display — _Done when: frontend displays user-friendly message when delete is blocked by AgentType reference (409 error)_
- [x] 8.2 Fix agent identity refresh token error display — _Done when: frontend displays error message when token refresh fails instead of silent catch_
- [x] 8.3 Add error logging for identity operations — _Done when: backend logs ERROR level messages with context (identity name, referencing type) for delete conflicts and token refresh failures_
- [x] 8.4 Create reusable UI components for confirmations and errors — _Done when: ConfirmDialog and ErrorSnackbar components created and used in AgentIdentityListPage_
- [x] 8.5 Enhance conflict error with agent type name and navigation link — _Done when: backend includes agent type name in error; frontend displays clickable link to navigate to agent type details_
- [x] 8.6 Add translations for new UI strings — _Done when: en.json includes goToAgentType, deleteError, deleteConfirmTitle keys_
- [x] 8.7 Add edit button to agent type details dialog — _Done when: AgentTypeDetailsDialog has edit button that navigates to agent type edit form_

### Phase 9 — Test Service Infrastructure
- [x] 9.1 Add `TEST_SERVICE_BOOTSTRAP_KEY` to Control Center configuration — _Done when: env var is defined in `.env`, `docker-compose.yml`, and `backend/app/core/config.py`; Control Center loads it on startup without error_
- [x] 9.2 Update Control Center `/internal/bootstrap` to support `service_type=test_service` — _Done when: endpoint issues a 30d service cert with CN `service:test-service` when `service_type=test_service` is submitted with a valid `TEST_SERVICE_BOOTSTRAP_KEY`; endpoint returns 401 when key is missing or wrong; unit test verifies correct cert CN and validity_
- [x] 9.3 Create test service certificate manager — _Done when: `backend/tests/fixtures/test_service_certificate.py` implements `TestServiceCertificateManager`; bootstraps via `POST /internal/bootstrap` with `service_type=test_service`; `get_mtls_client()` returns an `httpx.AsyncClient` configured with the issued cert; mirrors the AR/CH certificate manager pattern_
- [x] 9.4 Create authenticated client pytest fixtures — _Done when: `backend/tests/fixtures/authenticated_clients.py` provides `cc_client`, `ar_client`, and `ch_client` session-scoped pytest fixtures; all fixtures use the test service certificate for mTLS; fixture teardown closes the HTTP clients cleanly_
- [x] 9.5 Integration test: Test service bootstrap flow — _Done when: `backend/tests/integration/test_service_auth.py` passes against a live CC; test confirms issued cert has 30d validity; cert CN is `service:test-service`; wrong bootstrap key returns 401_
- [x] 9.6 Integration test: Authenticated data API calls — _Done when: `test_service_auth.py` uses `cc_client` to call all CC internal data API endpoints and receives valid responses; no mocking of any HTTP calls; test fails if CC is unreachable_
- [x] 9.7 Integration test: Full agent execution flow — _Done when: `backend/tests/integration/test_cross_service_flows.py` triggers CC → AR execution, validates AR fetches context from CC, validates AR posts result to CC, validates CC dispatches to CH; all three service calls use mTLS; no `unittest.mock` or `httpx` mocking in the test_
- [x] 9.8 Implement CC → CH → AR execution flow — _Done when: `GatewayLifecycleHandler` in Control Center calls `CommHubClient.trigger_agent_execution()` which POSTs to CH `/internal/agent/execute`; CH forwards to AR `/execute`; no direct CC → AR calls in execution path_
- [x] 9.9 Create comprehensive tests for CC → CH → AR flow — _Done when: `backend/tests/integration/test_full_execution_flow.py` validates: (1) CC can trigger CH, (2) CH forwards to AR, (3) AR accepts and enqueues, (4) Full flow completes end-to-end; all calls use proper mTLS certs; no mocking_
- [x] 9.10 Verify AR only accepts Communication Hub certificates — _Done when: integration test confirms AR rejects direct calls from Control Center cert; AR accepts calls from Communication Hub cert; middleware enforces CH-only access to `/execute`_

### Phase 10 — Tool Naming Refactor
- [x] 10.1 Create `tool_naming.py` unified name resolver module — _Done when: `parse_tool_name`, `build_tool_name`, and `is_system_tool` are importable from `backend.app.services.agents.tool_naming`; unit tests cover `system____save_result` round-trip, legacy bare-name fallback, and `is_system_tool` truth table_
- [x] 10.2 Update system tool DB entries to `system____*` naming in `mcp_hub.py` — _Done when: `seed_system_tools()` stores `system____save_result`, `system____send_notification`, `system____get_recipient_group` as canonical names and `original_name` stores the bare handler name; `system` slug is reserved and `create_mcp_server` rejects it with 409_
- [x] 10.3 Update `agent_data.py` `_SYSTEM_TOOL_SCHEMAS` to `system____*` names; remove auto-injection of system tools into `allowed_tools` — _Done when: `_SYSTEM_TOOL_SCHEMAS` keys are `system____*`; `allowed_tools` is built exclusively from explicitly assigned skill tools; `is_system_tool_name()` helper is removed and replaced with `tool_naming.is_system_tool()`_
- [x] 10.4 Update `runtime_executor.py` to remove system-tool special cases; route all tools through CommHub uniformly — _Done when: `_SAVE_RESULT_TOOL_DEF`, `_SEND_NOTIFICATION_TOOL_DEF`, `_GET_RECIPIENT_GROUP_TOOL_DEF` constants removed; `if original_name == "save_result"` branch removed from task loop; `_sanitize_tool_name_for_openai` converts `____` → `__`; `_restore_tool_name_from_openai` reverses `__` → `____`; all tool calls go through `CommHubToolClient.call_tool`_
- [x] 10.5 Update CommHub tool client to parse `server____tool` name for routing — _Done when: `CommHubToolClient.call_tool` calls `parse_tool_name()` and sends `server` and `tool` fields in payload; CommHub routes system tools to built-in handlers and MCP tools to MCP proxy; no agent-side tool-type distinction remains_
- [x] 10.6 Fix `save_result_tool()` in `system_tools.py` to also create a `ResultRecord` — _Done when: `save_result_tool()` calls `ResultStore.save(payload={"content": content}, title=title, agent_type_id=job.agent_type_id, content_type="text/plain")`; `ResultRecord` model and `ResultStore` service created; result appears in Result Repository_
- [x] 10.7 Fix `post_session_result()` in `session_data.py` to also create a `ResultRecord` when `output_data` has a result — _Done when: `post_session_result()` checks for `"result"` key in `output_data`; if present, calls `ResultStore.save()`; `ResultRecord` is persisted and accessible via Result Repository_
- [x] 10.8 Write unit tests for `tool_naming.py` — _Done when: tests cover `parse_tool_name` for canonical `server____tool`, legacy bare names, and `build_tool_name` round-trip; `is_system_tool` truth table tests pass for all name formats_
- [x] 10.9 Update integration tests for new naming and Result Repository persistence — _Done when: existing tool-routing integration tests updated to use `system____*` names; at least one integration test confirms a `save_result` tool call creates a `ResultRecord` in the database_

---

## Phase 1 — Service Extraction

### 1.1 Create Agent Runtime standalone FastAPI application entry point

The `backend/app/agent_runtime/` package already contains `certificate_manager.py` and `metadata_client.py`. A new `main.py` is needed to create a FastAPI app that registers only AR-specific HTTP routes: the execution trigger endpoint (added in Phase 5), and `/health`. On startup the app initialises `CertificateManager` (Phase 2), starts the certificate renewal background task, and starts `SessionDispatcher`. The app must not import `app.db.session` or any SQLAlchemy session factory anywhere in its execution path.

**Done when**: Agent Runtime starts with `uvicorn app.agent_runtime.main:app` without error, serves `/health`, and imports no database session factory.

---

### 1.2 Create Communication Hub standalone FastAPI application entry point

Create `backend/app/communication_hub/main.py` to create a FastAPI app that registers the Agent Gateway lifecycle routes, the WebSocket chat route, the inbound message dispatch endpoint (Phase 5), and `/health`. On startup, initialise the CH certificate manager (Phase 2) and verify Redis broker connectivity. The existing `authorization.py` middleware is registered here. The app has no import of any SQLAlchemy session factory.

**Done when**: Communication Hub starts with `uvicorn app.communication_hub.main:app` without error and authorization middleware runs on all tool-call routes without a DB session.

---

### 1.3 Refactor Control Center main application

`backend/app/main.py` is the current monolith entry point. Remove registrations for agent-execution routes that will move to Agent Runtime (`/execute`) and broker routes that will move to Communication Hub (`/dispatch`). Retain all `/api/v1/*` platform routes, `/internal/*` endpoints, WebSocket if CC serves a UI management stream, and all startup tasks: bootstrap, system tool seeding, skill seeding, agent realm initialisation, and CA initialisation. No behavioral change to any retained CC functionality.

**Done when**: `backend/app/main.py` starts successfully; all `/api/v1/*` platform routes respond; no agent-execution or broker routes are registered.

---

### 1.4 Annotate direct DB session usages in Agent Runtime and Communication Hub module trees

Audit all Python files under `backend/app/agent_runtime/`, `backend/app/services/agents/`, `backend/app/services/comm_hub/`, `backend/app/services/gateway/`, and `backend/app/communication_hub/` for imports of `AsyncSession`, `get_db`, or `DbSession`. Add a comment `# TODO(service-decomp): replace with CC data API call` on each occurrence. Produce a list of all tagged call sites as the deliverable.

**Done when**: Every direct DB access in the AR and CH module trees is tagged; a summary list of annotated files is documented.

---

## Phase 2 — Certificate Infrastructure

### 2.1 Create `/internal/bootstrap` endpoint in Control Center

Create `backend/app/api/v1/internal/bootstrap.py` with a `POST /internal/bootstrap` endpoint. The request payload includes `service_name` and `service_type` (`agent_instance` or `service`) plus a PEM-encoded public key or certificate signing request (CSR). The endpoint calls `CertificateAuthorityService` to sign and return a PEM certificate with the appropriate validity: 24h for `agent_instance`, 30d for `service`. Because the bootstrapping caller has no certificate yet, the endpoint is protected by per-service bootstrap keys validated in the request header: `AGENT_RUNTIME_BOOTSTRAP_KEY` for agent-runtime, `COMM_HUB_BOOTSTRAP_KEY` for communication-hub (env vars in Control Center). The endpoint validates that the `service_name` in the request matches the key provided in the `Authorization: Bearer <key>` header. The endpoint is also network-isolated in production (not routed through the public API gateway).

**Done when**: `POST /internal/bootstrap` returns a valid PEM certificate; `CertificateAuthorityService` is called with the correct CN and validity period; unit test verifies correct cert type per `service_type`.

---

### 2.2 Wire Agent Runtime startup to `/internal/bootstrap`

Update `backend/app/agent_runtime/certificate_manager.py` startup sequence (`load_certificate()`): if no certificate file exists at `AGENT_CERT_PATH`, call `POST /internal/bootstrap` on `CONTROL_CENTER_URL` with `service_type=agent_instance` and the locally generated public key. Write the returned PEM cert to `AGENT_CERT_PATH`. Validate the returned cert against the CA cert at `CA_CERT_PATH` before loading it into memory. The existing `run_renewal_task()` handles subsequent renewals.

**Done when**: On fresh startup with no cert file, AR receives a cert from CC, writes it to disk, and loads it into memory; `CertificateManager` is in loaded state before the app starts accepting traffic.

---

### 2.3 Create certificate manager for Communication Hub

Create `backend/app/communication_hub/certificate_manager.py` following the same pattern as `backend/app/agent_runtime/certificate_manager.py`. Bootstrap with `service_type=service` to receive a 30d cert. CN is `service:communication-hub`. Provide `configure_mtls_client()` returning an `httpx.AsyncClient` with the CH service cert for mTLS. Implement a `run_renewal_task()` background coroutine that renews at 80% of the 30d lifetime (approximately every 24 days).

**Done when**: CH bootstraps with a valid service certificate; `configure_mtls_client()` returns an mTLS-configured client; renewal task starts without error.

---

### 2.4 Implement certificate renewal background tasks

`backend/app/agent_runtime/certificate_manager.py` already has `run_renewal_task()`. Verify the renewal threshold (80% of 24h = ~19h), the check interval (1h), and retry-on-failure logic (`_RENEWAL_RETRY_SECONDS = 1800`) are all correct and complete. For `backend/app/communication_hub/certificate_manager.py`, implement an equivalent task with the same pattern adapted for the 30d validity (check daily, renew at ~24d elapsed). Both tasks atomically swap the in-memory certificate and reconfigure outbound clients on renewal.

**Done when**: Each service's renewal task runs on schedule, renews at the correct threshold, retries on CC unavailability, and atomically replaces the in-memory cert with no downtime.

---

## Phase 3 — Data Service Layer

### 3.1 Control Center internal data API for Agent Runtime

Create `backend/app/api/v1/internal/agent_data.py` with three endpoints, all protected by `require_service_certificate`:

- `GET /internal/data/agent-types/{agent_type_id}/plan` — queries `AgentPlan` for the given agent type and returns the active plan record
- `GET /internal/data/agent-types/{agent_type_id}/context` — returns the agent type's skills, SOPs, role, and resolved model config ID
- `GET /internal/data/model-configs/{model_config_id}` — returns model configuration with decrypted API credentials (vault decrypt at call time)

Register the new router in Control Center `main.py`. Agent-instance certs are blocked by the `require_service_certificate` dependency (Phase 4.5 enforces this).

**Done when**: All three endpoints return correct data; `require_service_certificate` blocks non-service certs; unit tests cover each endpoint.

---

### 3.2 Control Center internal data API for Communication Hub

Create `backend/app/api/v1/internal/session_data.py` with:

- `GET /internal/data/sessions/{session_id}` — returns `AgentJob` status and metadata
- `GET /internal/data/sessions/{session_id}/history` — returns conversation history rows for a session
- `POST /internal/data/sessions/{session_id}/result` — receives and persists execution results from Agent Runtime
- `GET /internal/data/users/{user_id}/permissions` — returns the resolved permission set for a user

Also add `GET /internal/certificates/revocation-status?serial={serial}` to `backend/app/api/v1/internal/revocation.py` — returns whether a certificate serial is revoked, for use by AR and CH without direct DB access.

**Done when**: All endpoints return correct data; authenticated via service certificate only; revocation status endpoint correctly queries `CertificateRevocationEntry`.

---

### 3.3 HTTP data client in Agent Runtime

Create `backend/app/agent_runtime/data_client.py`: an async HTTP client class that uses the agent-instance certificate for mTLS. Typed public methods:

- `get_agent_plan(agent_type_id)` — calls `/internal/data/agent-types/{id}/plan`
- `get_agent_context(agent_type_id)` — calls `/internal/data/agent-types/{id}/context`
- `get_model_config(model_config_id)` — calls `/internal/data/model-configs/{id}`
- `submit_result(session_id, result)` — calls `POST /internal/data/sessions/{id}/result`

Update `AgentRuntimeExecutor`, `AgentRuntimeLoader`, `AgentPermissionManager`, and `ModelBindingLayer` usages within the Agent Runtime execution path to use `ControlCenterDataClient` instead of direct DB queries. Remove `AsyncSession` from all AR service module signatures.

**Done when**: AR integration test resolves agent plan, skills, and model config from a live CC instance with no `AsyncSession` in the call stack; all Phase 1.4 tagged call sites are replaced.

---

### 3.4 HTTP data client in Communication Hub

Create `backend/app/communication_hub/data_client.py`: async HTTP client using the service certificate for mTLS. Typed methods:

- `get_session(session_id)` — calls `/internal/data/sessions/{id}`
- `get_conversation_history(session_id)` — calls `/internal/data/sessions/{id}/history`
- `get_user_permissions(user_id)` — calls `/internal/data/users/{id}/permissions`
- `check_revocation_status(serial)` — calls `/internal/certificates/revocation-status`

Update `GatewayLifecycleHandler`, `SessionContextManager`, and `authorization.py` middleware in CH to use this client. Remove `AsyncSession` from all CH service module signatures.

**Done when**: CH integration test resolves session data and permissions from CC without direct DB access; all Phase 1.4 tagged call sites in CH modules are replaced.

---

## Phase 4 — Service-to-Service Authentication

### 4.1 Harden `require_service_certificate` in Control Center

Review `backend/app/api/deps.py` `require_service_certificate`. Confirm it reads the client certificate from the TLS handshake context (not a header), validates signature against the CA cert, confirms cert is not expired, and confirms `CertificateType` is `service`. Verify this dependency is applied to every route in `backend/app/api/v1/internal/` including all routes added in Phase 3. Add the dependency to any internal route missing it.

**Done when**: Every `/internal/*` route requires a valid service cert; a request without a cert returns 401; unit tests cover the dependency.

---

### 4.2 Inbound certificate validation in Agent Runtime

Add FastAPI middleware to `backend/app/agent_runtime/main.py` that extracts the client TLS certificate from every inbound request and validates: cert is signed by the CA cert (loaded from `CA_CERT_PATH`), is not expired, and CN matches `service:control-center`. Any other cert, including agent-instance certs, is rejected with 401. The middleware calls `check_revocation_status()` on CC to confirm the cert is not revoked.

**Done when**: AR rejects requests from non-CC certs with 401; test with a self-signed cert confirms rejection.

---

### 4.3 Inbound certificate validation in Communication Hub

Add equivalent middleware to `backend/app/communication_hub/main.py` for the internal control routes (`/dispatch`, `/health`). CH also accepts inbound WebSocket connections from the Web UI (authenticated via JWT, not mTLS) and HTTP gateway routes (JWT-authenticated). Certificate validation applies only to internal control routes; JWT authentication continues for user-facing routes.

**Done when**: CH accepts JWT-authenticated WebSocket connections and rejects invalid mTLS calls to `/dispatch` with 401.

---

### 4.4 Certificate revocation check on inbound connections

`CertificateAuthorityService` already manages `CertificateRevocationEntry` records. For Control Center, add a revocation check directly in `require_service_certificate` by calling `CertificateAuthorityService.validate()` with the extracted cert serial number. For Agent Runtime and Communication Hub (no DB), the revocation check calls `ControlCenterDataClient.check_revocation_status()` from Phase 3 before accepting any inbound request.

**Done when**: Revoking a cert via CC's existing revocation API causes AR and CH to reject that cert on the next connection attempt; revocation integration test confirms 401.

---

### 4.5 Enforce agent-instance certificate block on CC `/internal/*`

Add an explicit type check in `require_service_certificate` after signature validation: if the validated cert's CN has the `agent-instance:` prefix (identifying `CertificateType.agent_instance`), raise `HTTPException(403)`. This extends the existing service-cert-only enforcement to explicitly reject agent-instance certs rather than only failing signature checks. Apply to all `/internal/*` routes.

**Done when**: A request from an AR (agent-instance cert) to `POST /internal/authorize/tool-call` or any other `/internal/*` endpoint returns 403.

---

## Phase 5 — Control Flow Implementation

### 5.1 Create agent execution trigger endpoint in Agent Runtime

Create `backend/app/api/internal/execute.py` under the Agent Runtime service. Route: `POST /execute`. Request payload contains `agent_type_id`, `session_id`, and `input_data`. The Phase 4.2 middleware validates the inbound Communication Hub cert. The handler calls `AgentSessionService.enqueue()` and returns the resulting job ID. `SessionDispatcher` (already a background task in AR) picks up the job and calls `AgentRuntimeExecutor`.

**Done when**: AR accepts a trigger POST from CH, creates an `AgentJob` with status `queued`, and `SessionDispatcher` transitions it to `running`.

---

### 5.1a Create agent execution forwarding endpoint in Communication Hub

Create `backend/app/communication_hub/api/internal/agent_execute.py` under the Communication Hub service. Route: `POST /internal/agent/execute`. Request payload contains `agent_type_id`, `session_id`, and `input_data`. The Phase 4.3 middleware validates the inbound CC cert. The handler forwards the request to Agent Runtime's `POST /execute` endpoint using Communication Hub's service certificate for mTLS.

**Why this matters**: All agent execution flows through Communication Hub, enabling future agent-to-agent communication patterns where agents can trigger other agents. Communication Hub becomes the central routing layer for all agent interactions.

**Done when**: CH accepts a trigger POST from CC, forwards it to AR with mTLS cert, and returns AR's response; integration test validates CC → CH → AR flow completes successfully.

---

### 5.2 Create message dispatch endpoint in Communication Hub

Create `backend/app/api/internal/dispatch.py` under the Communication Hub service. Route: `POST /dispatch`. Request payload contains `session_id`, `content`, and optional `metadata`. Phase 4.3 middleware validates the inbound CC cert. The handler calls `MessageBroker.publish()` to broadcast to the session channel.

**Done when**: A dispatch POST from CC results in a message appearing in the correct Redis pub/sub broker channel; a WebSocket subscriber receives it.

---

### 5.3 Create Control Center HTTP client for triggering execution via Communication Hub

Create `backend/app/services/control_center/comm_hub_client.py` (or extend existing): async HTTP client using the CC service certificate for mTLS. Provides `trigger_agent_execution(agent_type_id, session_id, input_data)` which POSTs to `COMM_HUB_URL/internal/agent/execute`. Update `GatewayLifecycleHandler` in Control Center to call this client instead of calling Agent Runtime directly.

**Architecture note**: Control Center → Communication Hub → Agent Runtime. This routing enables future agent-to-agent communication where Communication Hub acts as the central message router.

**Done when**: Agent execution initiated via the Platform API results in an HTTP POST to CH's agent execute endpoint; CH forwards to AR; full CC → CH → AR flow completes successfully.

---

### 5.4 Create Control Center HTTP client for Communication Hub

Create `backend/app/services/control_center/comm_hub_client.py`: async HTTP client using the CC service cert for mTLS. Provides `dispatch_message(session_id, content, metadata)` which POSTs to `COMM_HUB_URL/dispatch`. Update any CC code that currently publishes to the Redis broker in-process to use `CommHubClient.dispatch_message()` instead.

**Done when**: A message dispatched from the Platform API reaches the CH broker via the HTTP client; WebSocket subscriber receives it.

---

### 5.5 Route AgentJob results back through Control Center to Communication Hub

After `AgentRuntimeExecutor` completes a job, AR calls `ControlCenterDataClient.submit_result(session_id, result)` (from Phase 3.3) to persist the result in CC. CC then calls `CommHubClient.dispatch_message()` to push the result to the active WebSocket subscriber. Update `AgentRuntimeExecutor` completion handling and `SessionDispatcher` to call `submit_result` rather than writing directly to DB. Update CC's `POST /internal/data/sessions/{id}/result` handler to trigger a CH dispatch after persisting.

**Done when**: Full cycle test — CC trigger → AR execute → CC result persist → CH dispatch → UI WebSocket delivery — passes end-to-end without mocking.

---

## Phase 6 — Dev Environment

### 6.1 Split `docker-compose.yml` for three services

Add `control-center`, `agent-runtime`, and `communication-hub` service definitions to `docker-compose.yml`. `control-center` retains `postgres` and `redis` as dependencies. `agent-runtime` and `communication-hub` declare `control-center` as a dependency with a health-check condition so they wait for CC to be healthy before bootstrapping. Remove the existing `api` service definition. Set `CONTROL_CENTER_URL`, `AGENT_RUNTIME_URL`, and `COMM_HUB_URL` environment variables via the Docker network service names.

**Done when**: `docker compose up` starts all three services; health checks pass; no `api` container exists.

---

### 6.2 Create per-service Dockerfile configuration

Parametrize `backend/Dockerfile` with a `SERVICE` build argument that sets the uvicorn app target: `app.main:app` for Control Center, `app.agent_runtime.main:app` for Agent Runtime, `app.communication_hub.main:app` for Communication Hub. If parametrization adds significant complexity, create separate Dockerfiles (`Dockerfile.control-center`, `Dockerfile.agent-runtime`, `Dockerfile.communication-hub`) instead.

**Done when**: Each service image builds with `docker build --build-arg SERVICE=<name>` and the resulting container starts correctly.

---

### 6.3 Define environment variables per service

Update `backend/.env.example` with per-service variable sections:

- **Control Center**: `DATABASE_URL`, `REDIS_URL`, `OIDC_PROVIDER_URL`, `CREDENTIAL_VAULT_KEY`, `SECRET_KEY`, `CA_KEY_PATH`, `BOOTSTRAP_SECRET`, `AGENT_RUNTIME_URL`, `COMM_HUB_URL`
- **Agent Runtime**: `CONTROL_CENTER_URL`, `CA_CERT_PATH`, `AGENT_CERT_PATH`, `AGENT_KEY_PATH`, `BOOTSTRAP_SECRET`
- **Communication Hub**: `CONTROL_CENTER_URL`, `REDIS_URL`, `CA_CERT_PATH`, `SERVICE_CERT_PATH`, `SERVICE_KEY_PATH`, `BOOTSTRAP_SECRET`

**Done when**: Each service starts without error using only its documented environment variables; no unset required variable.

---

### 6.4 Update `parthenon.ps1` for per-service management

Extend `parthenon.ps1` to recognise `control-center`, `agent-runtime`, and `communication-hub` as valid service names in addition to the existing `backend` shorthand (which starts all three for backward compatibility). Start-Process invocations use the service-specific Docker Compose service name or uvicorn target based on the selected name.

**Done when**: `.\parthenon.ps1 start -Services agent-runtime` starts only the AR container; health check at `http://localhost:<ar-port>/health` confirms it is up.

---

### 6.5 Verify and update `/health` endpoints for each service

Confirm that the Agent Runtime and Communication Hub main apps expose `GET /health` returning a JSON response with at minimum `service`, `status`, and `version` fields. Update the Control Center health check to include `"service": "control-center"`. Add `depends_on` health-check conditions in `docker-compose.yml` so AR and CH containers wait for CC to be healthy before starting their bootstrap sequence.

**Done when**: All three `/health` endpoints return `{"status": "ok", "service": "<name>", "version": "<version>"}` without error.

---

## Phase 7 — Testing & Validation

### 7.1 Integration test: Agent Runtime bootstrap

Create `backend/tests/integration/test_ar_bootstrap.py`. Start a test CC instance with a seeded CA. Invoke `CertificateManager.load_certificate()` with no existing cert file, point it to the test CC's `/internal/bootstrap`. Assert the returned cert is valid X.509, CN matches `agent-instance:*`, validity is approximately 24h, and the cert validates against the CA cert.

**Done when**: Test passes against a real CC test instance; cert properties asserted.

---

### 7.2 Integration test: Communication Hub bootstrap

Create `backend/tests/integration/test_ch_bootstrap.py`. Same pattern as 7.1 but using the CH cert manager with `service_type=service`. Assert CN is `service:communication-hub` and validity is approximately 30 days.

**Done when**: Test passes; cert type and validity confirmed.

---

### 7.3 Integration test: Agent Runtime data API client

Create `backend/tests/integration/test_ar_data_client.py`. Seed a test database in CC with an agent type, plan, skills, and model config. Instantiate `ControlCenterDataClient` with a valid AR mTLS cert. Call `get_agent_context()` and `get_model_config()`. Assert the returned payload matches the seeded data. Intercept any `AsyncSession` import in the AR process to confirm zero direct DB usage.

**Done when**: Test confirms correct data returned from CC API; no direct DB session opened by any AR module.

---

### 7.4 Integration test: Control Center → Agent Runtime trigger

Create `backend/tests/integration/test_cc_ar_trigger.py`. Instantiate `AgentRuntimeClient` in CC with a valid CC cert. Call `trigger_execution()` against a running AR test instance. Poll the CC session status API and assert the `AgentJob` transitions from `queued` to `running` within 10 seconds.

**Done when**: AgentJob state transition confirmed; mTLS cert validated by AR middleware.

---

### 7.5 Integration test: Control Center → Communication Hub dispatch

Create `backend/tests/integration/test_cc_ch_dispatch.py`. Subscribe to a test Redis channel. Instantiate `CommHubClient` in CC with a valid CC cert. Call `dispatch_message()` against a running CH test instance. Assert the message arrives on the subscribed channel within 2 seconds.

**Done when**: Message received by subscriber; CH middleware validated the CC cert.

---

### 7.6 Integration test: Certificate revocation enforcement

Create `backend/tests/integration/test_cert_revocation.py`. Issue a cert via CC's bootstrap endpoint. Use it to make a successful request to AR and CH. Revoke the cert via CC's existing revocation API. Make a subsequent request from AR and CH using the revoked cert. Assert all three services (CC, AR, CH) return 401 for the revoked cert on subsequent connections.

**Done when**: Revoked cert rejected at all three service boundaries; test confirms 401 at each.

---

### 7.7 E2E test: Full user prompt flow against live 3-service stack

Create `e2e/tests/service-decomposition/full-flow.spec.ts`. Start all three services in Docker via `docker compose up`. Open the Web UI, submit a user prompt to an existing agent type, and assert the agent executes and the result is returned in the UI. No `page.route()` mocking is used — all requests hit the real service stack.

**Done when**: E2E test completes against the live 3-service Docker stack without mocking; result delivered to UI via CH WebSocket.

---

### 7.8 Security test: DB isolation for Agent Runtime and Communication Hub

Create `backend/tests/integration/test_db_isolation.py`. In the AR and CH container or process context, assert that `DATABASE_URL` is not set in the environment. Attempt to open a PostgreSQL connection directly (using psycopg2 or asyncpg with any URL) and assert a connection refused or authentication error is raised. Repeat for both services.

**Done when**: Test confirms neither AR nor CH has database credentials or connectivity; DB connection attempt raises an expected error.

---

## Completion Checklist

- [ ] All three services start independently and pass `/health` checks
- [ ] All PRD acceptance criteria verified by integration and E2E tests
- [ ] Agent Runtime has no `AsyncSession` imports in its execution path
- [ ] Communication Hub has no `AsyncSession` imports in its execution path
- [ ] All inter-service HTTP calls use mTLS with certificates issued by Control Center CA
- [ ] Agent-instance certificates are blocked from CC `/internal/*` endpoints with 403
- [ ] Certificate revocation is enforced across all three services
- [ ] `docker-compose.yml` starts all three services cleanly with no `api` service
- [ ] `parthenon.ps1` supports per-service `start`/`stop`/`status` commands
- [ ] All Phase 7 integration and E2E tests pass on the 3-service stack

---

## Phase 9 — Test Service Infrastructure

### 9.1 Add `TEST_SERVICE_BOOTSTRAP_KEY` to Control Center configuration

Add `TEST_SERVICE_BOOTSTRAP_KEY` environment variable to:
- `backend/.env` (for local development, generate a secure random key)
- `docker-compose.yml` under the `control-center` service definition
- `backend/app/core/config.py` `Settings` class as a required field

**Done when**: Environment variable is documented in all three locations; Control Center startup validates the key is set; local dev and Docker environments have the key configured.

---

### 9.2 Update Control Center `/internal/bootstrap` to support `service_type=test_service`

Update `backend/app/api/v1/internal/bootstrap.py` to accept `service_type=test_service` in addition to `agent_instance` and `service`. When `service_type=test_service`, issue a 30-day service certificate with CN `service:test-service`. Validate the request includes `Authorization: Bearer <TEST_SERVICE_BOOTSTRAP_KEY>` (similar to how AR and CH bootstrap keys are validated). Add unit tests to verify cert issuance and bootstrap key validation for test service.

**Done when**: Endpoint issues 30d service cert with CN `service:test-service` when `service_type=test_service`; validates `TEST_SERVICE_BOOTSTRAP_KEY`; unit test confirms cert issuance and key validation.

---

### 9.3 Create test service certificate manager

Create `backend/tests/fixtures/test_service_certificate.py` with a `TestServiceCertificateManager` class that:
- Bootstraps with Control Center on first invocation using `service_type=test_service`
- Stores cert/key/CA files in `backend/tests/.certs/` (gitignored)
- Provides `get_mtls_client()` method returning an `httpx.AsyncClient` configured with the test service cert for mTLS
- Mirrors the AR/CH certificate manager pattern but simplified (no background renewal task — certs can be manually regenerated if expired)

**Done when**: `TestServiceCertificateManager` implements bootstrap flow; provides `get_mtls_client()` method; test service can obtain a certificate from Control Center.

---

### 9.4 Create authenticated client pytest fixtures

Create `backend/tests/fixtures/authenticated_clients.py` with three session-scoped pytest fixtures:
- `cc_client`: Returns an authenticated `httpx.AsyncClient` targeting `CONTROL_CENTER_URL` with test service mTLS cert
- `ar_client`: Returns an authenticated `httpx.AsyncClient` targeting `AGENT_RUNTIME_URL` with test service mTLS cert
- `ch_client`: Returns an authenticated `httpx.AsyncClient` targeting `COMM_HUB_URL` with test service mTLS cert

Each fixture uses `TestServiceCertificateManager.get_mtls_client()` and includes proper teardown (close client on test session end).

**Done when**: All three fixtures are implemented; pytest session initialization bootstraps test service cert once; all fixtures provide authenticated clients ready for use in integration tests.

---

### 9.5 Integration test: Test service bootstrap flow

Create `backend/tests/integration/test_service_auth.py` with a test that:
- Calls Control Center `/internal/bootstrap` with `service_type=test_service` and `TEST_SERVICE_BOOTSTRAP_KEY`
- Validates the returned certificate has 30-day validity and CN `service:test-service`
- Validates the certificate is signed by the Control Center CA
- Tests that an invalid bootstrap key is rejected with 401

**Done when**: Test validates test service can bootstrap and receive a service certificate from Control Center; cert has 30d validity and correct CN; invalid key rejected.

---

### 9.6 Integration test: Authenticated data API calls

Create `backend/tests/integration/test_authenticated_data_apis.py` with tests that use the `cc_client` fixture to call all Control Center internal data API endpoints (`/internal/data/agent-types/{id}/plan`, `/internal/data/agent-types/{id}/context`, `/internal/data/model-configs/{id}`, `/internal/data/sessions/{id}`, etc.). Validate responses without mocking — use real database fixtures to set up test data. Confirm test service certificate is accepted for all endpoints.

**Done when**: Test uses authenticated client to call all CC data API endpoints; validates responses without mocking; confirms test service cert is accepted.

---

### 9.7 Integration test: Full agent execution flow

Create `backend/tests/integration/test_cross_service_flows.py` with a test that:
- Uses `cc_client` to trigger agent execution on Agent Runtime (via Control Center's agent runtime client or directly to AR `/execute` if accessible)
- Validates Agent Runtime fetches agent context from Control Center data API
- Validates Agent Runtime submits execution result back to Control Center
- Uses `cc_client` to dispatch a message via Communication Hub
- Validates the full CC → AR → CC → CH flow completes without errors and no mocks are used

**Done when**: Test triggers CC → AR execution; validates AR fetches data from CC; validates AR submits result to CC; validates CC dispatches to CH; no mocks used; full flow passes.

---

## Phase 10 — Tool Naming Refactor

### 10.1 Create `tool_naming.py` unified name resolver module

Create `backend/app/services/agents/tool_naming.py`. This module defines the canonical `server____tool` naming convention (four-underscore separator) for all tools — both system and MCP alike. The separator `____` avoids collisions with server or tool names that may contain single or double underscores.

Exports:
- `parse_tool_name(name: str) -> tuple[str, str]` — splits `server____tool` into `(server, tool)` tuple; for legacy bare names (e.g. `save_result`) returns `("system", name)` for backward compat during migration
- `build_tool_name(server: str, tool: str) -> str` — returns `f"{server}____{tool}"`
- `is_system_tool(name: str) -> bool` — returns `True` if `name` has `system____` prefix, matches a known bare system tool name, or has legacy `system/` prefix; `"system"` is the reserved server name for built-in tools

**Done when**: `parse_tool_name`, `build_tool_name`, and `is_system_tool` are importable from `backend.app.services.agents.tool_naming`; unit tests cover `system____save_result` round-trip, legacy bare-name fallback, and the `is_system_tool` truth table.

---

### 10.2 Update system tool DB entries to `system____*` naming in `mcp_hub.py`

Update `seed_system_tools()` in `backend/app/api/v1/mcp_hub.py` so that system tool DB entries use canonical `system____*` names: `system____save_result`, `system____send_notification`, `system____get_recipient_group`. Add an `original_name` field to each tool record storing the bare handler name (`save_result`, `send_notification`, `get_recipient_group`) for CommHub dispatch routing. The slug `system` is already reserved — `create_mcp_server` rejects it with 409 (introduced in FIX-20260518-140000).

**Done when**: `seed_system_tools()` stores `system____*` canonical names; `original_name` stores the bare handler name; the `system` slug cannot be claimed by a user-created MCP server.

---

### 10.3 Update `agent_data.py` `_SYSTEM_TOOL_SCHEMAS`; remove auto-injection of system tools

Update `backend/app/api/v1/internal/agent_data.py`:
1. Change `_SYSTEM_TOOL_SCHEMAS` dictionary keys to `system____save_result`, `system____send_notification`, `system____get_recipient_group`
2. Remove any logic that auto-initialises `allowed_tools` with all system tool names — system tools are only added to `allowed_tools` when explicitly assigned via a skill (same rules as any other tool)
3. Replace all `is_system_tool_name()` helper calls with `tool_naming.is_system_tool()` from `tool_naming.py`

**Done when**: `_SYSTEM_TOOL_SCHEMAS` keys use `system____*` format; `allowed_tools` set contains only explicitly assigned tools; `is_system_tool_name()` helper is removed.

---

### 10.4 Update `runtime_executor.py` to remove system-tool special cases

Update `backend/app/services/agents/runtime_executor.py`:
1. Remove module-level constants `_SAVE_RESULT_TOOL_DEF`, `_SEND_NOTIFICATION_TOOL_DEF`, `_GET_RECIPIENT_GROUP_TOOL_DEF`
2. Remove the `if original_name == "save_result"` (and equivalent) branch from the task loop — there is no agent-side special casing; all tool calls are routed through `CommHubToolClient.call_tool` uniformly
3. Update `_sanitize_tool_name_for_openai()`: convert `____` to `__` so OpenAI receives a valid identifier
4. Update `_restore_tool_name_from_openai()`: convert `__` back to `____` to recover the canonical name after OpenAI returns a tool call
5. Tool definitions sent to OpenAI use `system____*` names (sanitised per above)

**Done when**: No `_SAVE_RESULT_TOOL_DEF` constants remain; no `if original_name == "save_result"` branch in the task loop; sanitise/restore pair correctly round-trips `system____save_result` through OpenAI naming; all tool calls route through `CommHubToolClient.call_tool`.

---

### 10.5 Update CommHub tool client to parse `server____tool` name for routing

Update `CommHubToolClient.call_tool()` in `backend/app/agent_runtime/comm_hub_client.py` to call `parse_tool_name(name)` and include `server` and `tool` fields in the request payload to `CH /internal/tools/call`. Communication Hub uses the `server` field for routing: `server == "system"` dispatches to the built-in system tool handlers in `system_tools.py`; any other server routes to the MCP proxy. Agent Runtime has no routing logic — it only builds and passes the canonical name.

**Done when**: `CommHubToolClient.call_tool` sends `server` and `tool` in the payload; CommHub routes system tools to built-in handlers and MCP tools to the MCP proxy; no agent-side tool-type distinction remains.

---

### 10.6 Fix `save_result_tool()` to also create a `ResultRecord`

Update `backend/app/api/v1/internal/system_tools.py` `save_result_tool()` to call `ResultStore.save()` in addition to updating `AgentJob.output_data`:

```python
await ResultStore.save(
    db=db,
    payload={"content": content},
    title=title or None,
    agent_type_id=job.agent_type_id,
    content_type="text/plain",
)
```

Create `backend/app/db/models/results.py` with the `ResultRecord` SQLAlchemy model (fields: `payload` JSON, `title` optional str, `agent_type_id` UUID FK, `content_type` str). Create `backend/app/services/results/store.py` with `ResultStore.save()` as the single persistence point.

**Done when**: A `save_result` tool call creates both an `AgentJob.output_data` update and a `ResultRecord` entry; the `ResultRecord` is retrievable via the Result Repository; `ResultStore.save()` is the single persistence point.

---

### 10.7 Fix `post_session_result()` to also create a `ResultRecord`

Update `post_session_result()` in `backend/app/api/v1/internal/session_data.py`: after persisting `output_data` on the `AgentJob`, check if `output_data` contains a `"result"` key. If so, call `ResultStore.save()` with the result content so it appears in the Result Repository alongside results created by `save_result_tool()`.

**Done when**: `post_session_result()` creates a `ResultRecord` when `output_data["result"]` is present; Result Repository shows results from both code paths (direct `save_result_tool` calls and AR→CC result submissions).

---

### 10.8 Write unit tests for `tool_naming.py`

Create `backend/tests/unit/test_tool_naming.py`. Cover:
- `parse_tool_name("system____save_result")` → `("system", "save_result")`
- `parse_tool_name("my-server____my_tool")` → `("my-server", "my_tool")`
- `parse_tool_name("save_result")` → `("system", "save_result")` (legacy bare name backward compat)
- `build_tool_name("system", "save_result")` → `"system____save_result"`
- Round-trip: `build_tool_name(*parse_tool_name(name)) == name` for canonical names
- `is_system_tool("system____save_result")` → `True`
- `is_system_tool("save_result")` → `True` (legacy bare name)
- `is_system_tool("system/save_result")` → `True` (legacy slash format)
- `is_system_tool("my-server____my_tool")` → `False`

**Done when**: All test cases pass; `tool_naming` module imports without error.

---

### 10.9 Update integration tests for new naming and Result Repository persistence

Update existing integration tests that reference bare system tool names or `system/` prefix format to use `system____*` canonical names. Add at least one integration test that:
1. Triggers agent execution with a plan that calls `save_result`
2. Confirms the tool call is routed through CommHub (no special-case branch in AR)
3. Confirms a `ResultRecord` is created in the database
4. Confirms `AgentJob.output_data` is also updated

**Done when**: Updated tests pass with `system____*` names; integration test confirms `ResultRecord` is persisted by a `save_result` tool call; no test references old bare or `system/` format names for system tools.
