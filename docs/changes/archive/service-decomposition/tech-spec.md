# Technical Specification: Service Decomposition

## Technical Overview

The Parthenon backend is refactored from a single FastAPI application into three independently deployable FastAPI services: **Control Center** (sole database owner, certificate authority, and data plane), **Agent Runtime** (stateless LangChain executor), and **Communication Hub** (message broker, agent gateway, and WebSocket server). All existing service modules are reorganised under service-specific packages and their direct database access is replaced with authenticated HTTP calls over mutual TLS to Control Center data APIs. Certificate management is centralised in Control Center, which issues and revokes X.509 certificates consumed by peer services; all inter-service calls are logged for auditability.

---

## Component Breakdown

### Control Center

**Responsibility**: Sole owner of the PostgreSQL database. Issues, renews, and revokes X.509 certificates for all peer services. Resolves identity tokens and permissions for Communication Hub per-tool-call authorisation. Serves internal data APIs consumed by Agent Runtime and Communication Hub. Triggers agent execution on Agent Runtime and message dispatch on Communication Hub over mTLS. Manages the platform API (CRUD, permissions, scheduling, MCP Hub) for the Web UI.

**Retained modules** (existing, no source move required):

| Module path | Role |
|---|---|
| `backend/app/main.py` | FastAPI app factory and startup orchestration (refactored to CC only) |
| `backend/app/api/v1/` | All platform REST endpoints (users, agents, skills, MCP Hub, scheduling, etc.) |
| `backend/app/api/v1/internal/` | Existing internal endpoints: certificate validation, tool-call authorisation |
| `backend/app/services/certificate_authority.py` | CA: generates root CA, issues, validates, and revokes X.509 certs |
| `backend/app/services/permission_resolution.py` | Maps agent certs to permissions and identity tokens |
| `backend/app/services/token_refresh.py` | OAuth token refresh for agent identities |
| `backend/app/services/agents/plan_generation_service.py` | LLM-based plan generation on agent type save |
| `backend/app/services/agents/model_config_service.py` | Model config CRUD with AES-256 credential encryption |
| `backend/app/db/` | All SQLAlchemy models, session factory, Alembic migrations |
| `backend/app/core/` | Config, credential vault, telemetry, SSL context |

**New modules** (created as part of this change):

| Module path | Role |
|---|---|
| `backend/app/api/v1/internal/bootstrap.py` | Certificate issuance endpoint for bootstrapping peer services |
| `backend/app/api/v1/internal/agent_data.py` | Data API endpoints for Agent Runtime (plan, context, model config) |
| `backend/app/api/v1/internal/session_data.py` | Data API endpoints for Communication Hub (sessions, history, permissions) |
| `backend/app/api/v1/internal/revocation.py` | Revocation status endpoint for peer services (AR and CH without direct DB) |
| `backend/app/services/control_center/agent_runtime_client.py` | HTTP client to trigger execution on Agent Runtime |
| `backend/app/services/control_center/comm_hub_client.py` | HTTP client to dispatch messages to Communication Hub |
| `backend/app/db/models/results.py` | `ResultRecord` ORM model: persisted result entries (`payload`, `title`, `agent_type_id`, `content_type`) created by `save_result_tool()` and `post_session_result()` |
| `backend/app/services/results/store.py` | `ResultStore` service: `save()` persists a `ResultRecord` to the database; single persistence point for both system tool and AR result submission paths |

---

### Agent Runtime

**Responsibility**: Stateless LangChain executor. Receives execution triggers from Control Center over mTLS. Fetches all agent context (plan, skills, model config) from Control Center data APIs using an agent-instance certificate. Executes the observe-reason-act loop. Posts results back to Control Center. Never accesses PostgreSQL directly.

**Retained/updated modules** (moved or modified in place):

| Module path | Role |
|---|---|
| `backend/app/agent_runtime/certificate_manager.py` | Manages AR's agent-instance cert (24h); updated to call `/internal/bootstrap` on startup |
| `backend/app/agent_runtime/metadata_client.py` | Existing client for CC metadata requests (consolidated into data_client) |
| `backend/app/services/agents/runtime_executor.py` | LangChain observe-reason-act loop; DB calls replaced with CC data API calls |
| `backend/app/services/agents/agent_loop.py` | Loop context dataclasses (unchanged) |
| `backend/app/services/agents/session_service.py` | AgentJob lifecycle: enqueue, status transitions (unchanged) |
| `backend/app/services/agents/session_dispatcher.py` | Background job poller; updated to receive triggers from CC via `/execute` endpoint |
| `backend/app/services/agents/permission_manager.py` | Role→SOP→Skill→tool resolution; updated to fetch permissions from CC data API |
| `backend/app/services/agents/runtime_loader.py` | Loads saved plan into system context; updated to call CC data API |
| `backend/app/services/agents/model_binding.py` | LLM provider binding; updated to receive model config from CC data API |
| `backend/app/services/skills/executor.py` | Executes MCP tool bindings (unchanged) |
| `backend/app/services/mcp/proxy.py` | Routes tool calls to MCP server sessions (unchanged) |

**New modules**:

| Module path | Role | Status |
|---|---|---|
| `backend/app/agent_runtime/main.py` | Standalone FastAPI app entry point for Agent Runtime | ✅ Created (Phase 1.1) |
| `backend/app/agent_runtime/data_client.py` | Typed async HTTP client calling CC data APIs over mTLS; includes `log_execution_event(session_id, event_type, message, data, log_level)` which POSTs to `/internal/data/sessions/{id}/log` | Phase 3.3 |
| `backend/app/api/internal/execute.py` | Inbound execution trigger endpoint; receives CC → AR execution commands | Phase 5.1 |
| `backend/app/services/agents/tool_naming.py` | Unified name resolver: `parse_tool_name(name) -> (server, tool)`, `build_tool_name(server, tool) -> str`, `is_system_tool(name) -> bool`; canonical separator is `____` (four underscores); handles legacy bare names for backward compat; `"system"` is the reserved server name | Phase 10.1 |

---

### Communication Hub

**Responsibility**: Message broker and agent gateway. Accepts Web UI WebSocket connections authenticated by JWT. Receives message dispatch commands from Control Center over mTLS. Calls Control Center to validate agent-instance certificates and resolve identity tokens per tool call (existing flow). Fetches session data and user permissions from Control Center data APIs. Never accesses PostgreSQL directly.

**Retained/updated modules**:

| Module path | Role |
|---|---|
| `backend/app/services/comm_hub/broker.py` | Redis pub/sub message broker (unchanged) |
| `backend/app/services/comm_hub/agent_router.py` | Inter-agent message routing via MessageBroker (unchanged) |
| `backend/app/services/comm_hub/session_context.py` | Redis session context store with TTL (unchanged) |
| `backend/app/services/gateway/lifecycle_handler.py` | Agent gateway lifecycle state machine; DB calls replaced with CC data API calls |
| `backend/app/api/gateway/lifecycle.py` | HTTP gateway lifecycle routes (unchanged) |
| `backend/app/api/ws/chat.py` | WebSocket conversational agent endpoint (unchanged) |
| `backend/app/communication_hub/middleware/authorization.py` | Cert authorization middleware; updated to call CC for token resolution and revocation checks |

**New modules**:

| Module path | Role | Status |
|---|---|---|
| `backend/app/communication_hub/main.py` | Standalone FastAPI app entry point for Communication Hub | ✅ Created (Phase 1.2) |
| `backend/app/communication_hub/certificate_manager.py` | Manages CH's service cert (30d); mirrors AR cert manager pattern | Phase 2.3 |
| `backend/app/communication_hub/data_client.py` | Typed async HTTP client calling CC data APIs over mTLS | Phase 3.4 |
| `backend/app/api/internal/dispatch.py` | Inbound message dispatch endpoint; receives CC → CH dispatch commands |

---

### Test Service

**Responsibility**: Automated validation of service-to-service interactions. Authenticates with Control Center using test service bootstrap key. Fetches service certificate from Control Center. Provides pytest fixtures for authenticated HTTP clients to all three services. Validates full agent execution flows without mocking.

**New modules**:

| Module path | Role |
|---|---|
| `backend/tests/fixtures/test_service_certificate.py` | Certificate manager for test suite; bootstraps with `service_type=test_service`; provides mTLS client configuration |
| `backend/tests/fixtures/authenticated_clients.py` | Pytest fixtures returning authenticated `httpx.AsyncClient` instances for CC, AR, and CH |
| `backend/tests/integration/test_service_auth.py` | Validates test suite can bootstrap and authenticate to all services |
| `backend/tests/integration/test_cross_service_flows.py` | End-to-end tests: CC → AR execution, AR → CC data fetch, CC → CH dispatch |

---

## API Changes

### New endpoints — Control Center

All new internal endpoints require a valid **service certificate** validated by `require_service_certificate`. Agent-instance certs are explicitly rejected with 403. Endpoints are network-isolated (not routed through the public API gateway in production).

| Route | Method | Description |
|---|---|---|
| `/internal/bootstrap` | POST | Issues X.509 cert to a bootstrapping peer service; cert type (agent-instance 24h or service 30d) determined by `service_type` in request; protected by pre-shared `BOOTSTRAP_SECRET` header |
| `/internal/data/agent-types/{id}/plan` | GET | Returns active `AgentPlan` for the given agent type (Agent Runtime data API) |
| `/internal/data/agent-types/{id}/context` | GET | Returns skills, SOPs, role, and model config ID for an agent type (Agent Runtime data API) |
| `/internal/data/model-configs/{id}` | GET | Returns model configuration with decrypted credentials (Agent Runtime data API) |
| `/internal/data/sessions/{id}` | GET | Returns `AgentJob` status and metadata (Communication Hub data API) |
| `/internal/data/sessions/{id}/history` | GET | Returns conversation history rows for a session (Communication Hub data API) |
| `/internal/data/sessions/{id}/result` | POST | Receives and persists execution result submitted by Agent Runtime |
| `/internal/data/users/{id}/permissions` | GET | Returns resolved permission set for a user (Communication Hub data API) |
| `/internal/certificates/revocation-status` | GET | Returns revocation status for a certificate serial number; called by AR and CH for inbound cert checks |

### New endpoints — Agent Runtime

| Route | Method | Description |
|---|---|---|
| `/execute` | POST | Receives agent execution trigger from Control Center; enqueues an `AgentJob`; protected by inbound mTLS cert validation middleware (CC cert only) |
| `/health` | GET | Returns AR service name, status, and version |

### New endpoints — Communication Hub

| Route | Method | Description |
|---|---|---|
| `/dispatch` | POST | Receives message dispatch command from Control Center; publishes to broker session channel; protected by inbound mTLS cert validation middleware (CC cert only) |
| `/health` | GET | Returns CH service name, status, and version |

### Modified behavior (no new routes)

- `POST /internal/authorize/tool-call` (Control Center) — now explicitly rejects agent-instance certs (CN prefix `agent-instance:`) with 403, in addition to the existing service-cert-only requirement
- `POST /internal/certificates/validate` (Control Center) — unchanged; revocation checks for AR/CH are now served via the new `/internal/certificates/revocation-status` GET endpoint rather than requiring AR/CH to call validate directly
- `_SYSTEM_TOOL_SCHEMAS` in `agent_data.py` — system tool schema keys change from bare names to `system____save_result`, `system____send_notification`, `system____get_recipient_group`; `allowed_tools` set no longer auto-initializes with all system tool names — system tools are only included if explicitly assigned via a skill
- System tool DB entries in `mcp_hub.py` — canonical name column stores `system____*` names; new `original_name` field stores the bare handler name (`save_result`, etc.) for handler dispatch

---

## State Management

No frontend state changes are required. The Web UI continues to communicate with Communication Hub over WebSocket for agent session streaming and with Control Center's Platform API (`/api/v1/*`) for all management operations (agents, MCP Hub, skills, scheduling). The service decomposition is transparent to the frontend — all public-facing URLs and WebSocket paths remain the same.

---

## Data Access Patterns

### Control Center — sole data owner
- Owns and queries PostgreSQL directly via `AsyncSession` from `backend/app/db/session.py`
- All Platform API routes (`/api/v1/*`) continue using the `DbSession` dependency for CRUD operations
- Internal data API endpoints (`/internal/data/*`) serve AR and CH by reading the same ORM models
- Certificate operations read/write `AgentInstanceCertificate` and `CertificateRevocationEntry` models directly

### Agent Runtime — data access via Control Center API only
- Fetches agent plan and execution context via `ControlCenterDataClient` using its 24h agent-instance mTLS cert
- Fetches model configuration (with decrypted credentials) via `ControlCenterDataClient`
- Submits execution results to CC via `POST /internal/data/sessions/{id}/result`
- Has no `DATABASE_URL` environment variable; cannot open a PostgreSQL connection

### Communication Hub — data access via Control Center API only
- Fetches session state and conversation history via `CommHubDataClient` using its 30d service mTLS cert
- Fetches user permissions via `CommHubDataClient`
- Calls existing `POST /internal/authorize/tool-call` for per-tool-call identity token resolution (unchanged flow)
- Calls `GET /internal/certificates/revocation-status` to validate inbound agent-instance certs without direct DB
- Publishes and subscribes to Redis pub/sub (Redis is the message transport, not a data store for DB records)
- Has no `DATABASE_URL` environment variable; cannot open a PostgreSQL connection

---

## Code Reference Map

### Control Center — Existing symbols

| Symbol | Type | Description | File |
|---|---|---|---|
| `create_app` | function | FastAPI app factory; refactored to CC-only routes | `backend/app/main.py` |
| `_register_routers` | function | Registers all CC API routers | `backend/app/main.py` |
| `_initialize_certificate_authority` | function | Startup task: initialises CA on first run | `backend/app/main.py` |
| `CertificateAuthorityService` | class | Issues, validates, and revokes X.509 certs; manages CA key | `backend/app/services/certificate_authority.py` |
| `CertificateType` | enum | Distinguishes `agent_instance` vs. `service` cert types via CN prefix | `backend/app/services/certificate_authority.py` |
| `AgentInstanceCertificate` | model | Persisted cert record (serial, CN, status, expiry) | `backend/app/db/models/agent_security.py` |
| `CertificateRevocationEntry` | model | Persisted revocation record | `backend/app/db/models/agent_security.py` |
| `PermissionResolutionService` | class | Maps agent cert to permissions and identity tokens for tool calls | `backend/app/services/permission_resolution.py` |
| `refresh_oauth_token` | function | Refreshes OAuth tokens for agent identities with exponential backoff | `backend/app/services/token_refresh.py` |
| `PlanGenerationService` | class | Generates LLM-based agent plan on agent type save | `backend/app/services/agents/plan_generation_service.py` |
| `ModelConfigService` | class | CRUD for `ModelConfig` with AES-256 credential encryption | `backend/app/services/agents/model_config_service.py` |
| `require_service_certificate` | function | FastAPI dependency: validates inbound mTLS service cert; blocks agent-instance certs | `backend/app/api/deps.py` |
| `require_permission` | function | FastAPI dependency factory: enforces permission-engine access for platform API | `backend/app/api/deps.py` |
| `validate_certificate_internal` | function | Endpoint: validates agent client cert for CH tool-call requests | `backend/app/api/v1/internal/certificates.py` |
| `authorize_tool_call_internal` | function | Endpoint: returns identity token per tool call for CH | `backend/app/api/v1/internal/authorization.py` |
| `InternalCertificatesRouter` | router | Router for internal certificate validation endpoints | `backend/app/api/v1/internal/certificates.py` |
| `InternalAuthorizationRouter` | router | Router for internal authorisation endpoints | `backend/app/api/v1/internal/authorization.py` |
| `BootstrapService` | class | Seeds system roles and permissions on CC startup | `backend/app/services/permissions/bootstrap_service.py` |
| `seed_system_tools` | function | Idempotently seeds system MCP server and built-in tools | `backend/app/api/v1/mcp_hub.py` |
| `ToolSyncService` | class | Fetches tool list from MCP server and upserts tool records | `backend/app/services/mcp/tool_sync.py` |

### Control Center — New symbols

| Symbol | Type | Description | File |
|---|---|---|---|
| `InternalBootstrapRouter` | router | `POST /internal/bootstrap`: issues CA-signed X.509 cert to peer services; validates per-service bootstrap keys | `backend/app/api/v1/internal/bootstrap.py` |
| `bootstrap_service_certificate` | function | Endpoint handler: validates bootstrap key, builds CN, calls `CertificateAuthorityService.issue_from_public_key()` | `backend/app/api/v1/internal/bootstrap.py` |
| `issue_certificate_from_public_key` | function | CA function: signs externally-provided public key PEM with CA key; used by bootstrap endpoint | `backend/app/services/certificate_authority.py` |
| `CertificateAuthorityService.issue_from_public_key` | method | Facade method exposing `issue_certificate_from_public_key` | `backend/app/services/certificate_authority.py` |
| `BootstrapRequest` | schema | Pydantic request body for `POST /internal/bootstrap` (`service_name`, `service_type`, `public_key`); `service_type` accepts `agent_instance`, `service`, or `test_service` | `backend/app/schemas/certificates.py` |
| `BootstrapResponse` | schema | Pydantic response body: `certificate_pem`, `ca_certificate_pem`, `serial_number`, `expires_at` | `backend/app/schemas/certificates.py` |
| _(agent data API module)_ | module | `GET /internal/data/agent-types/*` and `GET /internal/data/model-configs/*` for AR | `backend/app/api/v1/internal/agent_data.py` |
| _(session data API module)_ | module | `GET /internal/data/sessions/*`, `POST .../result`, `GET /internal/data/users/*/permissions` for CH | `backend/app/api/v1/internal/session_data.py` |
| _(revocation status endpoint module)_ | module | `GET /internal/certificates/revocation-status` for AR and CH | `backend/app/api/v1/internal/revocation.py` |
| `AgentRuntimeClient` | class | CC-side mTLS client: triggers execution on Agent Runtime | `backend/app/services/control_center/agent_runtime_client.py` |
| `CommHubClient` | class | CC-side mTLS client: dispatches messages to Communication Hub | `backend/app/services/control_center/comm_hub_client.py` |
| `ConfirmDialog` | component | Reusable Material-UI confirmation dialog for destructive actions | `frontend/src/components/common/ConfirmDialog.tsx` |
| `ErrorSnackbar` | component | Reusable Material-UI snackbar for error/warning/info/success messages with optional action button | `frontend/src/components/common/ErrorSnackbar.tsx` |
| `AgentTypeDetailsDialog` | component | Agent type details dialog with tabs for details, plan preview, execution logs; includes edit button in title bar that navigates to agent type edit form | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `AgentTypeDetailsDialog.handleEdit` | method | Opens edit dialog for agent type by navigating to `/agents` with `editAgentType` state | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `AgentManagementPage` | component | Agent management page; handles navigation state to auto-open edit dialog when `editAgentType` state is provided | `frontend/src/pages/agents/AgentManagementPage.tsx` |
| `AgentIdentityListPage.parseConflictError` | method | Parses structured error format from backend: `agent_type_id:{uuid}|agent_type_name:{name}|{message}` | `frontend/src/pages/agents/AgentIdentityListPage.tsx` |
| `delete_identity` | function | Enhanced to fetch full AgentType object, include name in error message, return structured error format for frontend parsing | `backend/app/services/agents/identity_service.py` |

### FIX-20260518-140000 additions

| Symbol | Type | Description | File |
|---|---|---|---|
| `SYSTEM_TOOL_NAMES` | constant | `frozenset` of bare system tool names: `save_result`, `send_notification`, `get_recipient_group` | `backend/app/services/system_tools.py` |
| `SYSTEM_TOOL_DISPLAY_NAMES` | constant | `frozenset` of display-format names (`system/save_result`, etc.) | `backend/app/services/system_tools.py` |
| `is_system_tool` | function | Returns `True` if name matches any system tool; accepts bare, `system/`, or `system_` prefix | `backend/app/services/system_tools.py` |
| `get_canonical_name` | function | Strips `system/` or `system_` prefix; returns bare tool name | `backend/app/services/system_tools.py` |
| `get_display_name` | function | Returns `system/{bare_name}` display form | `backend/app/services/system_tools.py` |
| `list_all_tools` | function | Updated: set-based deduplication by `tool.id`; virtual system tools take precedence over seeded DB records | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_server` | function | Updated: rejects `slug == "system"` with `HTTP 409` before uniqueness check | `backend/app/api/v1/mcp_hub.py` |
| `ExecutionLogViewer` | component | Displays agent session execution logs; level filter (all/debug/info/warning/error); expandable JSON data column; refresh button | `frontend/src/components/agents/ExecutionLogViewer.tsx` |
| `ExecutionLogEntry` | interface | Log entry shape: `{ id, session_id, event_type, message, level, data?, created_at }` | `frontend/src/components/agents/ExecutionLogViewer.tsx` |
| `AgentExecutionDetailsDialog` | component | Updated: two tabs — "Session Details" (`AgentJobPage`) and "Execution Logs" (`ExecutionLogViewer`) | `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` |
| `AgentRoleDialog.lockedSkills` | state | `Set<string>` of skill IDs auto-selected by currently assigned SOPs; corresponding checkboxes are disabled | `frontend/src/pages/agents/AgentRoleDialog.tsx` |

### Agent Runtime — Existing symbols

| Symbol | Type | Description | File |
|---|---|---|---|
| `CertificateManager` | class | Manages AR agent-instance cert lifecycle; bootstraps via `/internal/bootstrap` on first startup; renews via same endpoint. On startup, detects CA rotation by comparing local CA cert expiry with Control Center's current CA expiry (from `/health` endpoint); if mismatch or signature invalid, triggers re-bootstrap automatically. | `backend/app/agent_runtime/certificate_manager.py` |
| `CertificateManager._bootstrap_certificate` | method | Generates RSA key pair, calls CC `/api/v1/internal/bootstrap`, writes cert/key/CA files to disk | `backend/app/agent_runtime/certificate_manager.py` |
| `CertificateManager.load_certificate` | method | Loads cert from disk or bootstraps if missing; validates local CA cert against Control Center's current CA by comparing expiry timestamps; triggers re-bootstrap if CA has changed | `backend/app/agent_runtime/certificate_manager.py` |
| `CertificateManager.renew_certificate` | method | Generates new key pair, calls CC bootstrap endpoint, atomically swaps cert in memory | `backend/app/agent_runtime/certificate_manager.py` |
| `AgentRuntimeExecutor` | class | LangChain observe-reason-act loop; DB calls replaced with CC data API calls | `backend/app/services/agents/runtime_executor.py` |
| `AgentLoopContext` | dataclass | Execution context (session, allowed tools, messages) carried through loop iterations | `backend/app/services/agents/agent_loop.py` |
| `TaskAgentLoop` | class | Task-mode agent loop variant | `backend/app/services/agents/agent_loop.py` |
| `ConversationalAgentLoop` | class | Conversational-mode agent loop variant | `backend/app/services/agents/agent_loop.py` |
| `AgentSessionService` | class | AgentJob lifecycle: enqueue, status transitions, persistence | `backend/app/services/agents/session_service.py` |
| `SessionDispatcher` | class | Background worker polling queued `AgentJob` records and dispatching to executor | `backend/app/services/agents/session_dispatcher.py` |
| `AgentPermissionManager` | class | Role→SOP→Skill→tool permission resolution with LRU cache; updated to use CC data API | `backend/app/services/agents/permission_manager.py` |
| `AgentRuntimeLoader` | class | Loads saved agent plan into system context; updated to use CC data API | `backend/app/services/agents/runtime_loader.py` |
| `ModelBindingLayer` | class | Resolves LLM provider config and sends prompts; updated to receive config from CC data API | `backend/app/services/agents/model_binding.py` |
| `SkillExecutor` | class | Resolves skill-to-MCP-tool bindings and executes via `McpProxyEngine` | `backend/app/services/skills/executor.py` |
| `McpProxyEngine` | class | Routes tool-call invocations to correct MCP server sessions | `backend/app/services/mcp/proxy.py` |

### Agent Runtime — New symbols

| Symbol | Type | Description | File |
|---|---|---|---|
| _(AR main module)_ | module | Standalone FastAPI app entry point; registers `/execute` and `/health` with cert expiry; initialises cert manager and dispatcher | `backend/app/agent_runtime/main.py` |
| `ControlCenterDataClient` | class | Typed async HTTP client: `get_agent_plan`, `get_agent_context`, `get_model_config`, `submit_result`; uses agent-instance mTLS cert | `backend/app/agent_runtime/data_client.py` |
| `CommHubToolClient` | class | AR-side mTLS client: routes all tool calls (external MCP + system tools) through Communication Hub `/internal/tools/call`; used by both task agents (`_run_task_loop_ar`) and conversational agents (`execute_conversation_turn`) | `backend/app/agent_runtime/comm_hub_client.py` |
| `CommHubToolClient.set_certificate` | method | Configures mTLS cert/key paths for authenticated calls to Communication Hub | `backend/app/agent_runtime/comm_hub_client.py` |
| `CommHubToolClient.call_tool` | method | POSTs tool call request to CH `/internal/tools/call`; returns result dict | `backend/app/agent_runtime/comm_hub_client.py` |
| `AgentRuntimeExecutor.execute_conversation_turn` | method | (FIX-20260518-153000) Conversational agent observe-reason-act loop; now initialises `CommHubToolClient` and routes all external MCP tool calls via `_execute_mcp_tool_ar` instead of the deprecated `_execute_mcp_tool`; ~line 1005 | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._execute_mcp_tool_ar` | method | Unified tool dispatch via `CommHubToolClient`; used by both task and conversational agents; ~line 943 | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._execute_mcp_tool` | method | **Deprecated** — direct McpProxyEngine dispatch with database access; retained only for legacy task loop; use `_execute_mcp_tool_ar` for all new code; ~line 1957 | `backend/app/services/agents/runtime_executor.py` |
| _(execute endpoint module)_ | module | `POST /execute`: receives CC trigger, calls `AgentSessionService.enqueue()` | `backend/app/api/internal/execute.py` |

### Communication Hub — Existing symbols

| Symbol | Type | Description | File |
|---|---|---|---|
| `MessageBroker` | class | Redis pub/sub broker with per-session typed channels | `backend/app/services/comm_hub/broker.py` |
| `BrokerMessage` | class | Strongly-typed message structure for broker publish/subscribe | `backend/app/services/comm_hub/broker.py` |
| `AgentRouter` | class | Routes inter-agent messages to target session channels via `MessageBroker` | `backend/app/services/comm_hub/agent_router.py` |
| `SessionContextManager` | class | Redis session context store (participants, message count, status) with TTL | `backend/app/services/comm_hub/session_context.py` |
| `GatewayLifecycleHandler` | class | Agent gateway state machine: init, request, close, launch; DB calls replaced with CC data API | `backend/app/services/gateway/lifecycle_handler.py` |
| `GatewayRouter` | router | HTTP gateway lifecycle routes (`/gateway/{id}/init`, `/request`, `/close`, etc.) | `backend/app/api/gateway/lifecycle.py` |
| `ws_router` | router | WebSocket conversational agent endpoint; JWT-authenticated | `backend/app/api/ws/chat.py` |
| `AuthorizationMiddleware` | class | Communication Hub cert authorization middleware; updated to call CC for revocation checks | `backend/app/communication_hub/middleware/authorization.py` |

### Communication Hub — New symbols

| Symbol | Type | Description | File |
|---|---|---|---|
| _(CH main module)_ | module | Standalone FastAPI app entry point; registers gateway, WebSocket, `/dispatch`, and `/health` routes with cert expiry; initialises cert manager | `backend/app/communication_hub/main.py` |
| `CommHubCertificateManager` | class | Manages CH 30-day service cert; bootstraps via `/internal/bootstrap`; provides `configure_mtls_client()` and `run_renewal_task()` | `backend/app/communication_hub/certificate_manager.py` |
| `CommHubCertificateManager._bootstrap_certificate` | method | Generates RSA key pair, calls CC bootstrap with `service_type=service`, writes cert/key/CA files | `backend/app/communication_hub/certificate_manager.py` |
| `CommHubCertificateManager.renew_certificate` | method | Generates new key pair, calls CC bootstrap endpoint, atomically swaps cert via `_switch_certificate` | `backend/app/communication_hub/certificate_manager.py` |
| `CommHubCertificateManager.run_renewal_task` | method | Background coroutine: checks expiry every 24h, renews at 80% lifetime (~day 24), retries every 5min on failure | `backend/app/communication_hub/certificate_manager.py` |
| `CommHubDataClient` | class | Typed async HTTP client: `get_session`, `get_conversation_history`, `get_user_permissions`, `check_revocation_status`; uses service mTLS cert | `backend/app/communication_hub/data_client.py` |
| _(dispatch endpoint module)_ | module | `POST /dispatch`: receives CC message command, calls `MessageBroker.publish()` | `backend/app/api/internal/dispatch.py` |

### Dev & Deployment

| Symbol | Type | Description | File |
|---|---|---|---|
| _(docker-compose config)_ | config | Docker Compose service definitions for `control-center`, `agent-runtime`, `communication-hub` | `docker-compose.yml` |
| _(management script)_ | script | PowerShell service manager; extended for per-service `start`/`stop`/`status` | `parthenon.ps1` |
| _(AR dockerfile target)_ | config | Dockerfile `SERVICE=agent-runtime` build argument target | `backend/Dockerfile` |
| _(CH dockerfile target)_ | config | Dockerfile `SERVICE=communication-hub` build argument target | `backend/Dockerfile` |

### Tests

| Symbol | Type | Description | File |
|---|---|---|---|
| _(AR bootstrap test)_ | test module | Validates AR certificate issuance via `/internal/bootstrap` | `backend/tests/integration/test_ar_bootstrap.py` |
| _(CH bootstrap test)_ | test module | Validates CH service certificate issuance via `/internal/bootstrap` | `backend/tests/integration/test_ch_bootstrap.py` |
| _(AR data client test)_ | test module | Validates AR context fetch from CC data API with no direct DB access | `backend/tests/integration/test_ar_data_client.py` |
| _(CC→AR trigger test)_ | test module | Validates CC-to-AR execution trigger flow over mTLS | `backend/tests/integration/test_cc_ar_trigger.py` |
| _(CC→CH dispatch test)_ | test module | Validates CC-to-CH message dispatch over mTLS | `backend/tests/integration/test_cc_ch_dispatch.py` |
| _(cert revocation test)_ | test module | Validates revoked certs are rejected at all three service boundaries | `backend/tests/integration/test_cert_revocation.py` |
| _(DB isolation test)_ | test module | Verifies AR and CH processes have no DB credentials or connectivity | `backend/tests/integration/test_db_isolation.py` |
| _(full flow E2E test)_ | test module | End-to-end user prompt flow against live 3-service Docker stack | `e2e/tests/service-decomposition/full-flow.spec.ts` |

### Test Service — New symbols

| Symbol | Type | Description | File |
|---|---|---|---|
| `TestServiceCertificateManager` | class | Manages test service cert lifecycle; bootstraps via `POST /api/v1/internal/bootstrap` with `service_type=test_service`; provides `get_header_client()` for HTTP header-based mTLS simulation in dev mode | `backend/tests/fixtures/test_service_certificate.py` |
| `TestServiceCertificateManager.bootstrap` | method | Generates RSA key pair, calls CC bootstrap endpoint with `service_type=test_service`, stores cert/key/CA in memory and temp files | `backend/tests/fixtures/test_service_certificate.py` |
| `TestServiceCertificateManager.get_header_client` | method | Returns an `httpx.AsyncClient` with `X-Client-Certificate` header set to the test service cert PEM; matches how `require_service_certificate` reads certs in HTTP dev mode | `backend/tests/fixtures/test_service_certificate.py` |
| `TestServiceCertificateManager.get_parsed_cert` | method | Returns parsed `x509.Certificate` object for validity and CN assertions | `backend/tests/fixtures/test_service_certificate.py` |
| `TestServiceBootstrapError` | exception | Raised when test service cannot bootstrap (CC unreachable, key missing, or request fails) | `backend/tests/fixtures/test_service_certificate.py` |
| `test_cert_manager` | pytest fixture | Session-scoped fixture that bootstraps `TestServiceCertificateManager`; skips on CC unavailability | `backend/tests/fixtures/authenticated_clients.py` |
| `cc_client` | pytest fixture | Authenticated `httpx.AsyncClient` targeting Control Center; uses test service cert via `X-Client-Certificate` header | `backend/tests/fixtures/authenticated_clients.py` |
| `ar_client` | pytest fixture | Authenticated `httpx.AsyncClient` targeting Agent Runtime; cert accepted for `/health` only (AR requires `service:control-center`) | `backend/tests/fixtures/authenticated_clients.py` |
| `ch_client` | pytest fixture | Authenticated `httpx.AsyncClient` targeting Communication Hub; cert accepted for `/health` only (CH requires `service:control-center` for `/dispatch`) | `backend/tests/fixtures/authenticated_clients.py` |
| `TestBootstrapFlow` | test class | Validates test service bootstrap: 30d validity, CN `service:test-service`, 401 on wrong key | `backend/tests/integration/test_service_auth.py` |
| `TestAuthenticatedDataAPICalls` | test class | Validates CC internal data API endpoints accept test service cert (returns 404 not 401) | `backend/tests/integration/test_service_auth.py` |
| `TestServiceConnectivity` | test class | Verifies all three services healthy and that AR/CH have bootstrapped certs from CC | `backend/tests/integration/test_cross_service_flows.py` |
| `TestAgentRuntimeToControlCenterDataPath` | test class | Validates AR → CC data API path: claim-queued, status update, result submission | `backend/tests/integration/test_cross_service_flows.py` |
| `TestControlCenterToCommHubDispatchPath` | test class | Validates CC → CH path; confirms CH rejects non-CC certs on `/dispatch` | `backend/tests/integration/test_cross_service_flows.py` |
| `TestControlCenterToAgentRuntimeTriggerPath` | test class | Validates CC → AR path; confirms AR rejects non-CC certs on `/execute` | `backend/tests/integration/test_cross_service_flows.py` |

### Phase 10 — Tool Naming Refactor additions

| Symbol | Type | Description | File |
|---|---|---|---|
| `parse_tool_name` | function | Parses `server____tool` into `(server, tool)` tuple; legacy bare names return `("system", name)` for backward compat during migration | `backend/app/services/agents/tool_naming.py` |
| `build_tool_name` | function | Joins `(server, tool)` into canonical `server____tool` string | `backend/app/services/agents/tool_naming.py` |
| `is_system_tool` | function | Returns `True` if name has `system____` prefix, matches a known bare system tool name, or has legacy `system/` prefix; replaces `is_system_tool_name()` in `agent_data.py` | `backend/app/services/agents/tool_naming.py` |
| `_SYSTEM_TOOL_SCHEMAS` | constant | Updated: tool schema definitions keyed by `system____save_result`, `system____send_notification`, `system____get_recipient_group`; no auto-injection into `allowed_tools` | `backend/app/api/v1/internal/agent_data.py` |
| `ResultRecord` | model | Persisted result entry; fields: `payload` (JSON), `title` (optional str), `agent_type_id` (UUID FK), `content_type` (str, default `"text/plain"`) | `backend/app/db/models/results.py` |
| `ResultStore` | class | `save(db, payload, title, agent_type_id, content_type)` — creates and persists a `ResultRecord`; called from both `save_result_tool()` and `post_session_result()` | `backend/app/services/results/store.py` |
| `save_result_tool` | function | Updated: also calls `ResultStore.save(payload={"content": content}, title=title, agent_type_id=job.agent_type_id, content_type="text/plain")`; continues to update `AgentJob.output_data` | `backend/app/api/v1/internal/system_tools.py` |
| `post_session_result` | function | Updated: also calls `ResultStore.save()` when `output_data` contains a `"result"` key; results appear in the Result Repository from both code paths | `backend/app/api/v1/internal/session_data.py` |
| `AgentRuntimeExecutor._sanitize_tool_name_for_openai` | method | Updated: converts `____` to `__` for OpenAI API name compatibility (OpenAI allows underscores; `____` becomes `__`) | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._restore_tool_name_from_openai` | method | Updated: converts `__` back to `____` to recover canonical `server____tool` name after OpenAI returns a tool call | `backend/app/services/agents/runtime_executor.py` |
| `seed_system_tools` | function | Updated: system tool DB entries stored with `system____*` canonical names; `original_name` field stores bare handler name (`save_result`, etc.) for CommHub dispatch routing | `backend/app/api/v1/mcp_hub.py` |
| `CommHubToolClient.call_tool` | method | Updated: calls `parse_tool_name(name)` to extract `(server, tool)`; sends `server` and `tool` fields in request payload; no agent-side tool-type distinction — all routing handled by CommHub | `backend/app/agent_runtime/comm_hub_client.py` |
