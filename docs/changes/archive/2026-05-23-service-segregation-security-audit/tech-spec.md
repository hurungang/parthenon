## Technical Overview
This specification documents the current service-segregation state for UI, Communication Hub, Control Center, Agent Runtime, and database interaction boundaries, then defines concrete controls to enforce least privilege with deny-by-default behavior. The current architecture already centralizes database access in Control Center and routes agent execution through Agent Runtime, but the code audit found critical internal API authorization gaps that can allow over-privileged lateral movement. The target state introduces explicit caller-scoped Control Center API allowlists, fail-closed enforcement, and auditable deny events.

Current-state audit findings
- Confirmed: UI reaches backend through REST and WebSocket paths, with no direct database client in frontend.
- Confirmed: Agent Runtime and Communication Hub modules do not import SQLAlchemy session or database-layer modules; they use HTTP clients to call Control Center.
- Confirmed: Control Center owns ORM access and internal data/session orchestration APIs.
- Gap (critical): Internal system-tools endpoints are exposed under internal routes without service-certificate dependency, while JWT middleware bypasses all internal paths.
- Gap (high): Control Center internal routes currently accept any valid service certificate via shared dependency and do not enforce caller-specific endpoint scope.
- Gap (high): Internal callers use fail-open revocation checks when Control Center revocation API is unreachable.
- Gap (medium): Communication Hub revocation client contains a non-existent revocation-status path while Control Center exposes revoked/{serial_number}.
- Gap (medium): Multiple internal clients allow insecure fallback behavior (plain HTTP or no cert), weakening boundary assumptions outside tightly controlled local development.
- Gap (medium): In-code route comments and caller assumptions are inconsistent in some runtime execution paths, increasing misconfiguration risk.

Security gap summary
- Unauthorized internal access risk on internal system-tools routes.
- Privilege overlap risk between Communication Hub and Agent Runtime for Control Center internal APIs.
- Boundary bypass risk when certificate revocation checks fail open.
- Contract drift risk from endpoint/path mismatches between callers and Control Center.

## Component Breakdown
UI
- Current role: Human interaction layer using REST API calls and WebSocket sessions.
- Current boundary posture: No direct data-store integration observed.
- Required hardening: Preserve API-only access and avoid introducing direct persistence clients.

Communication Hub
- Current role: Message broker and transport gateway for tool routing, A2A orchestration, and execution forwarding.
- Current boundary posture: No direct database access; relies on Control Center APIs for state and authorization data.
- Required hardening: Restrict Control Center calls to explicit Communication Hub allowlist; enforce authenticated internal calls for system-tool forwarding; remove endpoint mismatches and fail-open behavior.

Control Center
- Current role: Control plane authority, policy evaluation, certificate authority, token/permission resolution, and sole database access layer.
- Current boundary posture: Database ownership is correct, but internal API authorization remains coarse and not caller-scoped.
- Required hardening: Introduce caller-type-aware policy gate with explicit allowlists and default deny.

Agent Runtime
- Current role: Agent execution engine and tool-call initiator through Communication Hub.
- Current boundary posture: No direct database access; uses Control Center data APIs and Communication Hub internal APIs.
- Required hardening: Restrict Control Center access to runtime-essential allowlist only; remove insecure fallback behavior and align endpoint semantics.

Database
- Current role: Persistent state and audit store owned by Control Center.
- Current boundary posture: No direct connectivity observed from UI, Communication Hub, or Agent Runtime code paths.
- Required hardening: Preserve this rule with regression checks that fail CI on new non-Control-Center DB access patterns.

## API Changes
Control Center API allowlist for Agent Runtime
- GET /api/v1/internal/data/agent-types/{agent_type_id}/plan
- GET /api/v1/internal/data/agent-types/{agent_type_id}/context
- GET /api/v1/internal/data/model-configs/{model_config_id}
- GET /api/v1/internal/data/sessions/{session_id}
- POST /api/v1/internal/data/sessions/claim-queued
- PATCH /api/v1/internal/data/sessions/{session_id}/status
- POST /api/v1/internal/data/sessions/{session_id}/result
- POST /api/v1/internal/data/sessions/{session_id}/log
- GET /api/v1/internal/data/mcp-sessions/{server_slug}

Related internal endpoints outside caller allowlist policy gate
- POST /api/v1/internal/bootstrap (service bootstrap key policy)
- GET /api/v1/internal/certificates/revoked/{serial_number} (network-isolated revocation check)

Control Center API allowlist for Communication Hub
- POST /api/v1/internal/certificates/validate
- POST /api/v1/internal/authorize/tool-call
- GET /api/v1/internal/data/sessions/{session_id}
- GET /api/v1/internal/data/sessions/{session_id}/history
- GET /api/v1/internal/data/users/{user_id}/permissions
- POST /api/v1/internal/data/conversations/{conv_session_id}/prepare-turn
- POST /api/v1/internal/data/conversations/{conv_session_id}/append-turn
- POST /api/v1/internal/data/conversations/{conv_session_id}/auto-name
- POST /api/v1/internal/data/a2a/request
- POST /api/v1/internal/data/a2a/sessions/{session_link_id}/disconnect
- POST /api/v1/internal/system-tools/save-result
- POST /api/v1/internal/system-tools/send-notification
- POST /api/v1/internal/system-tools/get-recipient-group
- POST /api/v1/internal/mcp/proxy-tool

Endpoints explicitly denied by default
- Any internal Control Center endpoint not present in the caller-specific allowlist.
- Any internal call with unknown caller type, missing caller identity, or certificate type mismatch.
- Any internal call blocked by certificate revocation policy when revocation status cannot be validated under target fail-closed mode.

Required policy and routing adjustments
- Add caller-aware policy guard to internal Control Center routing before handler execution.
- Add service-certificate dependency to internal system-tools endpoints.
- Align Communication Hub revocation check path to revoked/{serial_number}.
- Remove invalid revocation-status path usage.

## State Management
Service identity state
- Current: Internal requests depend on validated certificate type and service name in request context, but authorization does not consistently use caller identity to constrain endpoint access.
- Target: Internal policy state includes normalized caller type and endpoint identity, evaluated against caller-specific allowlist map.

Authorization decision state
- Current: Binary certificate-valid and service-cert checks are present but endpoint-level privilege partitioning is not enforced by caller.
- Target: Authorization state includes allowlisted boolean, deny reason code, and audit correlation fields for every internal request.

Audit state
- Current: Certificate validation and some authorization decisions are logged, but blocked non-allowlisted endpoint attempts are not uniformly captured as structured deny events.
- Target: Every deny-by-default decision writes a structured event with caller type, endpoint, method, reason, and timestamp.

## Data Access Patterns
Current-state data access patterns
- UI accesses backend APIs via axios base URL and WebSocket session endpoint.
- Communication Hub and Agent Runtime call Control Center through HTTP clients and do not directly manage ORM sessions.
- Control Center performs all database reads/writes for session state, permissions, token management, certificates, and system tools.

Proposed deny-by-default controls and enforcement points
- Enforcement point 1: Control Center internal API dependency layer.
  - Validate certificate and caller type.
  - Resolve canonical endpoint signature (method + route template).
  - Check caller-specific allowlist.
  - Deny by default when not allowlisted.
- Enforcement point 2: Control Center router composition.
  - Apply internal policy guard consistently to all internal routers.
  - Prevent route-level bypass by requiring centralized dependency for internal groups.
- Enforcement point 3: Communication Hub and Agent Runtime outbound clients.
  - Fail closed for missing/invalid certificate identity in non-development modes.
  - Use only supported Control Center revocation path contract.
- Enforcement point 4: Internal endpoint hardening.
  - Require service-certificate dependency on system-tools internal routes.
  - Reject unauthenticated internal requests even when JWT middleware is bypassed.
- Enforcement point 5: Audit pipeline.
  - Emit structured deny events for blocked calls.
  - Track repeated denial patterns by caller and endpoint.

## Code Reference Map
| Domain | File | Symbol or Entry Point | Current Role | Segregation Relevance | Audit Note |
| --- | --- | --- | --- | --- | --- |
| Governance | docs/config.yaml | top_priority_rules | Defines mandatory service segregation constraints | Source of audit criteria | Confirms DB ownership and runtime-only agent execution constraints |
| UI | frontend/src/api/API_CONFIG.ts | API_CONFIG | Defines REST and WebSocket base URLs | UI boundary to backend services | No direct DB client reference |
| UI | frontend/src/api/apiClient.ts | apiClient axios instance | Injects bearer token and sends REST calls | UI to Control Center REST boundary | Uses API endpoints only |
| UI | frontend/src/hooks/useChatSession.ts | useChatSession | Opens WebSocket session and sends chat turns | UI to Communication Hub boundary | WebSocket only, no DB path |
| Control Center | backend/app/main.py | create_app, _register_routers | Builds Control Center API app and router set | Central control plane composition | Internal routes mounted under /api/v1/internal |
| Control Center | backend/app/api/v1/__init__.py | router includes Internal* routers | Registers internal and public routers | Internal API exposure point | Internal groups currently share coarse auth dependency model |
| Control Center | backend/app/middleware/auth.py | JWTAuthMiddleware._is_public | Bypasses JWT for /api/v1/internal/* | Internal auth pipeline behavior | Increases importance of strict service-certificate enforcement on all internal routes |
| Control Center | backend/app/api/deps.py | require_service_certificate, _normalize_internal_caller, _resolve_route_template, _raise_internal_policy_deny | Validates service certificate, normalizes caller identity, applies caller-specific endpoint allowlists, and emits structured deny events | Primary internal policy enforcement point | Enforces separate AR/CH allowlists with deterministic deny-by-default behavior |
| Control Center | backend/app/api/v1/internal/agent_data.py | InternalAgentDataRouter endpoints | Serves runtime context and model references | AR/CH internal data plane | Should be caller-allowlisted per endpoint |
| Control Center | backend/app/api/v1/internal/session_data.py | InternalSessionDataRouter endpoints | Handles sessions, logs, permissions, A2A, conversation prep | AR/CH internal data plane | Broad internal surface needs caller partitioning |
| Control Center | backend/app/api/v1/internal/authorization.py | authorize_tool_call_internal | Returns permission decision and identity token | CH authorization dependency | Must be CH-only allowlist endpoint |
| Control Center | backend/app/api/v1/internal/certificates.py | validate_certificate_internal, check_certificate_revoked | Certificate validation and revocation check | Internal trust boundary | Revocation endpoint contract is revoked/{serial_number} |
| Control Center | backend/app/api/v1/internal/bootstrap.py | bootstrap_service_certificate | Issues bootstrap certificates | Service identity onboarding | Must remain tightly scoped by service name and key policy |
| Control Center | backend/app/api/v1/internal/system_tools.py | router (with require_service_certificate), save_result_tool, send_notification_tool, get_recipient_group_tool | Executes system tools through internal API with service-certificate dependency | CH-to-CC privileged path | Internal system-tools path now enforces authenticated service caller identity |
| Control Center | backend/app/api/v1/internal/mcp_proxy.py | proxy_mcp_tool | Proxies MCP tool calls with credential/token resolution | CH-to-CC privileged path | Must be CH allowlist only |
| Control Center | backend/app/services/control_center/comm_hub_client.py | CommunicationHubClient, _allow_insecure_internal_fallback | Dispatches and triggers execution via CH; enforces certificate requirement outside explicit development opt-in | CC to CH control-plane client | Fail-closed by default with explicit development-only fallback |
| Communication Hub | backend/app/communication_hub/main.py | create_app, _register_routers | Composes CH app, middleware, and routes | Communication boundary enforcement | No direct DB imports |
| Communication Hub | backend/app/communication_hub/middleware/control_plane.py | ControlPlaneMiddleware | Validates service certificates on /internal/* | CH inbound trust gate | Path-specific caller logic exists, but depends on revocation check behavior |
| Communication Hub | backend/app/communication_hub/middleware/authorization.py | CertificateAuthorizationMiddleware, validate_certificate_with_control_center, authorize_tool_call, _build_control_center_auth | Validates certs and authorizes tool calls via CC using CH service identity on internal calls | CH runtime authorization path | CC internal auth/authorize calls now include CH certificate and fail closed when unavailable |
| Communication Hub | backend/app/communication_hub/data_client.py | ControlCenterDataClient, check_revocation_status, _allow_insecure_internal_fallback | Reads session and conversation data from CC and checks revocation via supported endpoint | CH to CC data path | Revocation path aligned to revoked/{serial}; fail-closed on errors unless explicit dev opt-in |
| Communication Hub | backend/app/communication_hub/api/internal/tool_routing.py | route_tool_call, _route_to_system_tool, _route_to_mcp_tool, _build_control_center_auth | Routes AR tool calls to CC system-tools or MCP proxy with service-certificate-authenticated internal calls | CH privileged forwarding path | Removed unauthenticated system-tools call path; insecure fallback is explicit dev-only opt-in |
| Communication Hub | backend/app/communication_hub/api/internal/agent_execute.py | trigger_agent_execution | Forwards execute trigger to AR | CH to AR control flow | Boundary-critical execution relay |
| Communication Hub | backend/app/communication_hub/api/a2a.py | request_a2a, disconnect_a2a | Handles A2A orchestration via CC data APIs | CH orchestration boundary | Uses CC data client; no DB usage |
| Communication Hub | backend/app/api/ws/chat.py | websocket_chat, _delegate_conversation_turn_to_agent_runtime | WebSocket transport and runtime delegation | UI-CH-AR conversational boundary | Delegates execution to AR, persistence to CC |
| Agent Runtime | backend/app/agent_runtime/main.py | create_app, startup_event | Composes AR app and clients | Runtime execution boundary | No direct DB imports |
| Agent Runtime | backend/app/agent_runtime/middleware.py | ControlCenterCertificateMiddleware | Validates inbound service certs | AR inbound trust gate | Must fail closed with revocation policy hardening |
| Agent Runtime | backend/app/agent_runtime/data_client.py | ControlCenterDataClient, _allow_insecure_internal_fallback | Fetches context/model/session data and updates status in CC | AR to CC data/control path | Internal calls now fail closed by default when certificate identity is unavailable |
| Agent Runtime | backend/app/agent_runtime/comm_hub_client.py | CommHubToolClient | Routes tool and A2A calls to CH | AR to CH privileged path | Uses certificate/header identity for internal calls |
| Agent Runtime | backend/app/agent_runtime/api/execute.py | trigger_execution, _execute_session | Receives execution trigger and runs session | Runtime-only execution rule | Core proof that agents execute in AR service |
| Agent Runtime | backend/app/agent_runtime/api/conversation.py | execute_conversation_turn | Executes conversation turns in AR | Runtime-only execution rule | Conversation execution remains in runtime boundary |
| Shared Security | backend/app/services/certificates/revocation_service.py | RevocationService.check_remote, _allow_insecure_internal_fallback | Remote revocation validation for AR and CH | Certificate trust chain behavior | Fail-closed by default with explicit development-only opt-in for insecure fallback |
| Database | backend/app/db/session.py | engine, AsyncSessionLocal, get_db | ORM engine and session factory | DB ownership boundary | DB session layer remains in Control Center service tree |
| Verification | backend/tests/integration/test_internal_allowlist_partitioning.py | test_agent_runtime_denied_for_communication_hub_only_endpoint, test_communication_hub_denied_for_agent_runtime_only_endpoint, test_policy_denial_emits_structured_audit_event | Verifies caller-specific allowlist partitioning and structured deny evidence | Segregation regression coverage | Confirms deny-by-default behavior and deny log emission for blocked internal paths |
| Verification | backend/tests/integration/test_internal_deny_audit_events.py | test_unknown_internal_service_is_denied_by_default, test_unknown_internal_service_denial_emits_structured_event, test_internal_system_tools_rejects_missing_service_certificate | Verifies unknown-caller deny behavior and system-tools service-cert enforcement | Segregation regression coverage | Confirms deny reason integrity and required structured audit fields |
| Verification | backend/tests/integration/test_internal_revocation_fail_closed.py | test_remote_revocation_check_fails_closed_on_transport_error, test_remote_revocation_check_allows_dev_opt_in_fallback | Verifies revocation fail-closed default and development-only opt-in fallback | Trust boundary regression coverage | Prevents fail-open reintroduction in remote revocation checks |
| Verification | backend/tests/integration/test_data_clients.py | test_check_revocation_status_calls_correct_url, test_check_revocation_status_fail_closed_on_error | Verifies CH revocation path contract and fail-closed behavior in data client | Trust boundary regression coverage | Confirms revoked/{serial} contract and fail-closed default on client error |
| Verification | backend/tests/unit/test_control_center_comm_hub_client.py | test_make_client_without_cert_fails_closed_outside_dev_opt_in | Verifies Control Center -> Communication Hub client rejects missing cert outside development opt-in | Internal-call hardening | Prevents silent insecure fallback in non-development profiles |
| Verification | backend/tests/integration/test_database_isolation.py | test_agent_runtime_has_no_ast_db_or_sqlalchemy_imports, test_communication_hub_has_no_ast_db_or_sqlalchemy_imports | Enforces no direct DB/session imports in AR and CH module trees | Segregation architecture guardrail | CI-level regression protection for "only Control Center accesses DB" rule |
| Verification | frontend/src/__tests__/service-segregation-security-audit.test.ts | uses API-only base URL configuration, uses websocket endpoint config, builds websocket URL from configured ws base path and auth token only | Verifies UI boundary remains API/WS-only without DB transport hints | UI segregation guardrail | Prevents accidental frontend direct-db transport regressions |
| Verification | e2e/tests/service-segregation-security-audit.spec.ts | internal authorize endpoint rejects missing service certificate, internal system-tools endpoint rejects missing service certificate, revocation contract endpoint uses revoked path | Verifies boundary enforcement on real backend internal routes | End-to-end security contract checks | Confirms endpoint wiring and deny behavior at runtime boundary |
