# Module: control-center — Tech Spec

## Overview

The Control Center is the authoritative security and identity hub for agent execution in the Parthenon platform. It implements a zero-trust PKI layer: a Certificate Authority issues X.509 certificates to agent instances, a Permission Resolution Service maps certificate serial numbers to allowed MCP tools and identity tokens, and a Token Refresh Service automatically renews agent OAuth tokens before expiry. All agent-to-platform communication uses mutual TLS authenticated by these certificates, ensuring that identity operations are centralised, audited, and never exposed to the agent execution layer.

**Security Model:** Agent instances receive certificates (not tokens). The Communication Hub asks the Control Center to authorise every tool call — the Control Center resolves the cert → agent type → roles → tools chain and returns a fresh identity token only if the tool is permitted.

---

## Key Components

### Certificate Authority (CA) Module

| Component | Description |
|-----------|-------------|
| `CertificateAuthorityService` | Root CA lifecycle management; generates CA on first startup (if absent), signs agent instance certificates with AES-256-GCM encrypted CA key, validates signatures and revocation status, maintains monotonically increasing serial numbers |
| `CertificateValidationResult` | NamedTuple carrying validation outcome: `valid`, `reason`, `agent_type_id`, `instance_id`, `serial_number`, `expires_at` |
| `IssuedCertificate` | NamedTuple carrying issuance result: `certificate_pem`, `private_key_pem`, `serial_number`, `expires_at` |

### Token Refresh Service

| Component | Description |
|-----------|-------------|
| `TokenRefreshServiceV2` | On-demand OAuth token refresh triggered by permission checks; checks expiration with 5-minute buffer; calls OAuth provider refresh endpoint; retries with exponential backoff (1 s, 5 s, 15 s, max 3 attempts); respects HTTP 429 rate limits; stores new access token AES-256 encrypted in `agent_identity`; logs every attempt to `token_refresh_log` |
| `TokenRefreshError` | Exception raised when refresh fails after all retries |

> **Note:** `TokenRefreshServiceV2` (in `backend/app/services/token_refresh.py`) is the security-segregation implementation used by the permission resolution flow. The earlier `TokenRefreshService` (in `backend/app/services/agents/token_refresh_service.py`) is a background proactive refresh service documented in the [agents module](../agents/tech-spec.md).

### Permission Resolution Service

| Component | Description |
|-----------|-------------|
| `PermissionResolutionService` | Main authorisation entry point for the Communication Hub; resolves cert serial → agent type → identity → roles → tools; calls `TokenRefreshServiceV2` if token is expiring; returns `AuthorizationResult` with identity token on success or explicit denial reason on failure. Extended to accept an API key as the root of the resolution chain: API Key → bound agent identity → bound agent role → policy evaluation → allowed tools/skills/SOPs. |
| `AuthorizationResult` | NamedTuple: `authorized`, `identity_token`, `identity_id`, `agent_type_id`, `reason` (on denial) |

### API Key Management

| Component | Description |
|-----------|-------------|
| `ApiKeyService` | Service layer for API key business logic: cryptographically random key generation with `phn_sk_` prefix, SHA-256 hashing, hash-based lookup, status management (activate/revoke), usage log creation, identity token decryption for bound identities |
| `AdminApiKeyRouter` | FastAPI APIRouter for JWT-protected admin-facing API key CRUD endpoints (list, create, revoke) and identity-with-roles listing |

**File**: `backend/app/services/api_key_service.py` (service), `backend/app/api/v1/api_keys.py` (router)

### Database Models (`backend/app/db/models/agent_security.py`)

| Component | Description |
|-----------|-------------|
| `AgentInstanceCertificate` | Stores issued certificates: `serial_number` (unique), `agent_type_id`, `instance_id`, `certificate_pem`, `issued_at`, `expires_at`, `revoked` |
| `CertificateRevocationEntry` | CRL entries: `serial_number`, `revoked_at`, `reason`; queried on every validation |
| `TokenRefreshLog` | Audit trail for all refresh attempts: `identity_id`, `outcome`, `error`, `attempted_at` |
| `CertificateValidationLog` | Audit trail for all validation requests from the Communication Hub: `serial_number`, `tool_name`, `outcome`, `validated_at` |

---

## API Endpoints

### Certificate Management (admin-facing)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/certificates/ca` | Public | Return CA public certificate PEM for distribution to Agent Runtime instances |
| `POST` | `/api/v1/certificates/issue` | Admin JWT | Issue new agent instance certificate; request includes `agent_type_id` and `instance_id` |
| `POST` | `/api/v1/certificates/revoke` | Admin JWT | Revoke certificate by serial number; adds CRL entry |

### Intervene Request Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/intervene/requests` | JWT + intervene:view | List intervene requests (filterable by status, intervention_type, agent_session_id, pagination) |
| `GET` | `/api/v1/intervene/requests/{id}` | JWT + intervene:view | Get single request with full context including response |
| `POST` | `/api/v1/intervene/requests/{id}/respond` | JWT + intervene:respond | Submit operator response (approval bool, choice string, or text string) |
| `POST` | `/api/v1/intervene/requests/{id}/cancel` | JWT + intervene:respond | Cancel a pending request |
| `GET` | `/api/v1/intervene/metrics` | JWT + intervene:view | Dashboard metrics: pending count, avg response time, resolution rate |

### Internal Service-to-Service Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/internal/certificates/validate` | Service-to-service | Validate cert PEM from Communication Hub; returns agent_type_id and instance_id on success |
| `POST` | `/internal/authorize/tool-call` | Service-to-service | Authorise tool call for a cert serial number; returns identity token and authorisation decision |
| `POST` | `/internal/auth/validate-api-key` | Service-to-service | Validate a hashed API key from Communication Hub; returns resolved agent identity, role, identity token, and full permission set |

### API Key Admin Endpoints (JWT-protected)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/api-keys` | Admin JWT | List all API keys with optional `?status=active\|revoked` filter |
| `POST` | `/api/v1/api-keys` | Admin JWT | Create a new API key bound to an agent identity and role; returns clear-text key once |
| `POST` | `/api/v1/api-keys/{key_id}/revoke` | Admin JWT | Revoke an API key (idempotent) |
| `GET` | `/api/v1/api-keys/identities-with-roles` | Admin JWT | List all agent identities with their available roles |

### Internal System Tool Endpoints (extended)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/internal/system-tools/skills/resolve` | Service-to-service | Resolve all skills accessible to a given agent role with optional `since` filter for incremental sync |

---

## Data Access Patterns

**Certificate lifecycle:** CA private key loaded encrypted from `ENCRYPTION_MASTER_KEY` at startup; stored in memory. Certificates written to `agent_instance_certificate` table on issuance; validated from DB on every inbound request. CRL checked inline during validation.

**Permission resolution:** Per-call DB query (no caching) to ensure revocations and role changes take effect immediately. Token refresh check is inline with permission resolution — if token expires within 5 minutes, refresh runs before the response is returned.

**Audit logging:** Every certificate validation and token refresh attempt is written to the respective audit log table synchronously before the response is returned.

---

## Code Reference Map

### Certificate Authority (`backend/app/services/certificate_authority.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `CertificateAuthorityService` | class | Root CA management: generates, signs, validates, and revokes agent instance certificates | `backend/app/services/certificate_authority.py` |
| `CertificateValidationResult` | NamedTuple | Validation outcome: `valid`, `reason`, `agent_type_id`, `instance_id`, `serial_number`, `expires_at` | `backend/app/services/certificate_authority.py` |
| `IssuedCertificate` | NamedTuple | Issuance result: `certificate_pem`, `private_key_pem`, `serial_number`, `expires_at` | `backend/app/services/certificate_authority.py` |
| `generate_ca_certificate` | function | Generate root CA certificate and encrypted private key on first startup | `backend/app/services/certificate_authority.py` |
| `issue_agent_certificate` | function | Sign and persist a new agent instance certificate | `backend/app/services/certificate_authority.py` |
| `validate_certificate` | function | Verify certificate signature, expiration, and CRL status | `backend/app/services/certificate_authority.py` |
| `revoke_certificate` | function | Add certificate serial to CRL in database | `backend/app/services/certificate_authority.py` |
| `extract_cn_components` | function | Parse `agent_type_id:instance_id` from certificate CN field | `backend/app/services/certificate_authority.py` |
| `initialize_ca` | function | Startup hook: load or create root CA cert and encrypted private key | `backend/app/services/certificate_authority.py` |
| `get_ca_certificate_pem` | function | Return CA certificate in PEM format for distribution | `backend/app/services/certificate_authority.py` |

### Token Refresh Service (`backend/app/services/token_refresh.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TokenRefreshServiceV2` | class | On-demand token refresh with exponential backoff; called by permission resolution flow | `backend/app/services/token_refresh.py` |
| `TokenRefreshError` | exception | Raised when token refresh fails after all retry attempts | `backend/app/services/token_refresh.py` |
| `check_token_expiration` | function | Return `True` if token is expired or expires within 5 minutes | `backend/app/services/token_refresh.py` |
| `refresh_oauth_token` | function | Call OAuth provider refresh endpoint; implements exponential backoff | `backend/app/services/token_refresh.py` |
| `store_refreshed_token` | function | Persist new access token (AES-256 encrypted) to `agent_identity` table | `backend/app/services/token_refresh.py` |
| `log_refresh_attempt` | function | Write refresh attempt outcome to `token_refresh_log` audit table | `backend/app/services/token_refresh.py` |

### Permission Resolution Service (`backend/app/services/permission_resolution.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PermissionResolutionService` | class | Main authorisation service: cert serial → agent type → identity → roles → allowed tools | `backend/app/services/permission_resolution.py` |
| `AuthorizationResult` | NamedTuple | Resolution result: `authorized`, `identity_token`, `identity_id`, `agent_type_id`, `reason` | `backend/app/services/permission_resolution.py` |
| `resolve_permissions` | function | Entry point: receives cert serial number and tool name; returns `AuthorizationResult` | `backend/app/services/permission_resolution.py` |
| `get_agent_type_from_certificate` | function | Look up agent type from certificate serial number in database | `backend/app/services/permission_resolution.py` |
| `get_agent_identity` | function | Retrieve assigned identity record for an agent type | `backend/app/services/permission_resolution.py` |
| `get_allowed_tools` | function | Resolve agent type roles to complete set of allowed MCP tool identifiers | `backend/app/services/permission_resolution.py` |
| `check_tool_permission` | function | Return `True` if the requested tool is in the resolved allowed set | `backend/app/services/permission_resolution.py` |
| `resolve_permissions_from_api_key` | function (async) | Resolves agent permissions starting from an API key (key → identity → role → permissions) | `backend/app/services/permission_resolution.py` |

### API Endpoints

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `get_ca_certificate_endpoint` | endpoint | `GET /certificates/ca` — returns CA PEM; public, no auth | `backend/app/api/v1/certificates.py` |
| `issue_certificate` | endpoint | `POST /certificates/issue` — admin-authenticated certificate issuance | `backend/app/api/v1/certificates.py` |
| `revoke_certificate` | endpoint | `POST /certificates/revoke` — admin-authenticated revocation | `backend/app/api/v1/certificates.py` |
| `validate_certificate_internal` | endpoint | `POST /internal/certificates/validate` — service-to-service validation | `backend/app/api/v1/internal/certificates.py` |
| `authorize_tool_call_internal` | endpoint | `POST /internal/authorize/tool-call` — service-to-service authorisation; returns identity token on success | `backend/app/api/v1/internal/authorization.py` |

### Schemas (`backend/app/schemas/certificates.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `CertificateIssueRequest` | schema | `agent_type_id: UUID`, `instance_id: str` | `backend/app/schemas/certificates.py` |
| `CertificateRevokeRequest` | schema | `serial_number: str`, `reason: str` | `backend/app/schemas/certificates.py` |
| `CertificateValidateRequest` | schema | `certificate_pem: str` | `backend/app/schemas/certificates.py` |
| `AuthorizeToolCallRequest` | schema | `certificate_serial_number: str`, `tool_name: str`, `tool_params: dict` | `backend/app/schemas/certificates.py` |
| `CACertificateResponse` | schema | `certificate_pem`, `expires_at`, `serial_number` | `backend/app/schemas/certificates.py` |
| `CertificateIssueResponse` | schema | `certificate_pem`, `private_key_pem`, `serial_number`, `expires_at` | `backend/app/schemas/certificates.py` |
| `AuthorizeToolCallResponse` | schema | `authorized: bool`, `identity_token`, `identity_id`, `agent_type_id` (on success); `reason`, `required_permission`, `agent_type` (on denial) | `backend/app/schemas/certificates.py` |

### Database Models (`backend/app/db/models/agent_security.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentInstanceCertificate` | model | Issued agent certificate record; `serial_number` unique; `agent_type_id`, `instance_id`, `certificate_pem`, `issued_at`, `expires_at`, `revoked` | `backend/app/db/models/agent_security.py` |
| `CertificateRevocationEntry` | model | CRL entry: `serial_number`, `revoked_at`, `reason`; checked on every validation | `backend/app/db/models/agent_security.py` |
| `TokenRefreshLog` | model | Refresh audit entry: `identity_id`, `outcome`, `error`, `attempted_at` | `backend/app/db/models/agent_security.py` |
| `CertificateValidationLog` | model | Validation audit entry: `serial_number`, `tool_name`, `outcome`, `validated_at` | `backend/app/db/models/agent_security.py` |

### Application Startup (`backend/app/main.py`)

**Startup sequence (revised):** The Control Center no longer auto-provisions Keycloak realms at startup. Instead, it validates that external dependencies are reachable and fails fast with actionable error messages. Identity provider provisioning is an operator-invoked operation handled exclusively by the [setup tool](../setup/tech-spec.md).

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `create_app` | function | Control Center FastAPI application factory; composes all startup event handlers | `backend/app/main.py` |
| `startup_event` | coroutine | Control Center startup sequence — validates external dependencies instead of provisioning them | `backend/app/main.py` |
| `_validate_oidc_provider` | coroutine | **NEW** — validates OIDC provider reachability via discovery document fetch; skipped when super-admin mode is enabled | `backend/app/main.py` |
| `_validate_postgresql_reachable` | coroutine | **NEW** — validates PostgreSQL connectivity with a lightweight query | `backend/app/main.py` |
| `_validate_redis_reachable` | coroutine | **NEW** — validates Redis connectivity with PING | `backend/app/main.py` |
| `_initialize_certificate_authority` | function | Loads or generates root CA certificate and encrypted private key at startup (retained) | `backend/app/main.py` |
| `_initialize_oidc_provider_registry` | function | Loads OIDC provider configs from DB into in-memory registry (retained) | `backend/app/main.py` |
| `_run_bootstrap` | function | Seeds system roles and permissions at startup — runtime seeding, not setup-time (retained) | `backend/app/main.py` |
| `_seed_system_tools` | function | Seeds system MCP server and tools at startup (retained) | `backend/app/main.py` |
| `_cleanup_stale_sessions_on_startup` | function | Closes non-terminal sessions at startup (retained) | `backend/app/main.py` |
| `_initialize_agent_realm` | coroutine | **REMOVED** — former auto-provisioning of agent realm at startup; relocated to setup tool | `backend/app/main.py` |

### API Key Management (`backend/app/services/api_key_service.py`, `backend/app/api/v1/api_keys.py`, `backend/app/schemas/api_key.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ApiKeyService` | class | Service layer for key generation, hashing, validation, and lifecycle management | `backend/app/services/api_key_service.py` |
| `generate_api_key` | function | Generates a cryptographically random API key with `phn_sk_` prefix | `backend/app/services/api_key_service.py` |
| `hash_api_key` | function | SHA-256 hashes a raw API key for storage and lookup | `backend/app/services/api_key_service.py` |
| `validate_api_key_from_hash` | function | Looks up key by hash, checks status, returns key record or raises | `backend/app/services/api_key_service.py` |
| `create_api_key_usage_log` | function | Creates an `ApiKeyUsageLog` entry for audit trail | `backend/app/services/api_key_service.py` |
| `resolve_identity_token` | function (async) | Decrypts and returns the identity token for a given agent identity | `backend/app/services/api_key_service.py` |
| `resolve_allowed_tools` | function (async) | Resolves all tool names accessible to a given agent role | `backend/app/services/api_key_service.py` |
| `update_last_used_at` | function (async) | Updates the `last_used_at` timestamp on an API key record | `backend/app/services/api_key_service.py` |
| `check_duplicate_active_key` | function (async) | Checks whether an active key already exists for an identity-role pair; raises 409 if so | `backend/app/services/api_key_service.py` |
| `AdminApiKeyRouter` | router | FastAPI APIRouter for admin-facing API key CRUD endpoints | `backend/app/api/v1/api_keys.py` |
| `list_api_keys` | endpoint | `GET /api/v1/api-keys` — list keys with optional status filter | `backend/app/api/v1/api_keys.py` |
| `create_api_key` | endpoint | `POST /api/v1/api-keys` — create key, return clear-text once | `backend/app/api/v1/api_keys.py` |
| `revoke_api_key` | endpoint | `POST /api/v1/api-keys/{key_id}/revoke` — set key status to revoked | `backend/app/api/v1/api_keys.py` |
| `list_identities_with_roles` | endpoint | `GET /api/v1/api-keys/identities-with-roles` — identities and their available roles | `backend/app/api/v1/api_keys.py` |
| `validate_api_key_internal` | endpoint | Internal POST endpoint: validates hashed key, returns identity token + permissions | `backend/app/api/v1/internal/validate_api_key.py` |
| `InternalAuthRouter` | router | FastAPI APIRouter for internal auth endpoints, protected by `require_service_certificate` | `backend/app/api/v1/internal/validate_api_key.py` |
| `resolve_skills_internal` | endpoint | Internal POST endpoint: resolves skills for a role with optional `since` filter | `backend/app/api/v1/internal/system_tools.py` |
| `ApiKeyCreate` | schema | Pydantic schema for API key creation request (name, identity_id, role_id) | `backend/app/schemas/api_key.py` |
| `ApiKeyCreateResponse` | schema | Pydantic schema for API key creation response (includes clear-text key shown once) | `backend/app/schemas/api_key.py` |
| `ApiKeyRead` | schema | Pydantic schema for API key data with optional identity/role name fields | `backend/app/schemas/api_key.py` |
| `ApiKeyListItem` | schema | Pydantic schema for API key list items with denormalized identity/role names (metadata only, never includes secret) | `backend/app/schemas/api_key.py` |
| `ApiKeyRevokeResponse` | schema | Pydantic schema for revoke response (status confirmation) | `backend/app/schemas/api_key.py` |
| `RoleItem` | schema | Pydantic schema for a role item in identity-with-roles responses | `backend/app/schemas/api_key.py` |
| `ToolDefinition` | schema | Pydantic schema for a resolved tool definition with input/output schemas | `backend/app/schemas/api_key.py` |
| `ApiKeyValidateRequest` | schema | Pydantic schema for internal validation request (hashed key) | `backend/app/schemas/api_key.py` |
| `ApiKeyValidateResponse` | schema | Pydantic schema for internal validation response (identity token + permissions) | `backend/app/schemas/api_key.py` |
| `SkillWithVersion` | schema | Pydantic schema extending skill with `updated_at` and tool definitions | `backend/app/schemas/api_key.py` |

### Internal Segregation Enforcement

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `create_app` | function | Control Center application composition entry point that mounts public and internal routers | `backend/app/main.py` |
| `_register_routers` | function | Registers internal route groups under `/api/v1/internal` and other API routers | `backend/app/main.py` |
| `router` (internal includes) | router module | Internal router registration for agent data, session data, authorization, certificates, system-tools, and MCP proxy paths | `backend/app/api/v1/__init__.py` |
| `JWTAuthMiddleware._is_public` | method | Bypasses JWT auth for `/api/v1/internal/*`; requires strict service-certificate enforcement on internal endpoints | `backend/app/middleware/auth.py` |
| `require_service_certificate` | dependency | Enforces service certificate validity and caller-specific endpoint allowlists with deny-by-default behavior | `backend/app/api/deps.py` |
| `_normalize_internal_caller` | function | Normalizes caller identity (`agent-runtime`, `communication-hub`) to policy caller types | `backend/app/api/deps.py` |
| `_resolve_route_template` | function | Resolves canonical route template used for allowlist matching and deny audit metadata | `backend/app/api/deps.py` |
| `_raise_internal_policy_deny` | function | Emits structured deny event and returns deterministic 403 error payload for blocked internal calls | `backend/app/api/deps.py` |
| `InternalAgentDataRouter` | router | Internal runtime context and model/session reference endpoints used by allowlisted internal callers | `backend/app/api/v1/internal/agent_data.py` |
| `get_agent_context` | endpoint | Internal context endpoint returning effective runtime payload including guardrail policy snapshot fields | `backend/app/api/v1/internal/agent_data.py` |
| `AgentContextResponse` | schema | Internal context response model carrying runtime context and guardrail policy metadata | `backend/app/api/v1/internal/agent_data.py` |
| `InternalSessionDataRouter` | router | Internal session, conversation, permission, and A2A coordination endpoints | `backend/app/api/v1/internal/session_data.py` |
| `update_session_status` | endpoint | Internal persistence endpoint for terminal session outcomes including guardrail stop reasons | `backend/app/api/v1/internal/session_data.py` |
| `LogExecutionEventRequest` | schema | Structured log payload model for runtime guardrail decision events and counters | `backend/app/api/v1/internal/session_data.py` |
| `post_session_result` | endpoint | Internal result persistence endpoint that stores execution completion payloads alongside guardrail metadata | `backend/app/api/v1/internal/session_data.py` |
| `prepare_a2a_request` | endpoint | Internal A2A preparation endpoint for delegated execution routing and parent/child context linkage | `backend/app/api/v1/internal/session_data.py` |
| `authorize_tool_call_internal` | endpoint | Internal authorizer endpoint for Communication Hub tool call checks | `backend/app/api/v1/internal/authorization.py` |
| `validate_certificate_internal` | endpoint | Internal certificate validation endpoint for service callers | `backend/app/api/v1/internal/certificates.py` |
| `check_certificate_revoked` | endpoint | Internal revocation status endpoint on `revoked/{serial_number}` contract | `backend/app/api/v1/internal/certificates.py` |
| `bootstrap_service_certificate` | endpoint | Internal bootstrap endpoint for service identity onboarding under bootstrap key policy | `backend/app/api/v1/internal/bootstrap.py` |
| `save_result_tool` | endpoint | Internal system tool endpoint guarded by required service-certificate dependency | `backend/app/api/v1/internal/system_tools.py` |
| `send_notification_tool` | endpoint | Internal notification system tool endpoint guarded by required service-certificate dependency | `backend/app/api/v1/internal/system_tools.py` |
| `human_intervene_tool` | endpoint | Internal system tool endpoint for `system____human_intervene`; creates `InterveneRequest` record, transitions session to `waiting_for_human`, and emits notification event; guarded by required service-certificate dependency | `backend/app/api/v1/internal/system_tools.py` |
| `get_recipient_group_tool` | endpoint | Internal recipient-group lookup endpoint guarded by required service-certificate dependency | `backend/app/api/v1/internal/system_tools.py` |
| `proxy_mcp_tool` | endpoint | Internal MCP proxy endpoint for Communication Hub forwarded tool calls | `backend/app/api/v1/internal/mcp_proxy.py` |
| `InterveneRouter` | router | FastAPI router for `/api/v1/intervene/*` endpoints (list, detail, respond, cancel, metrics) | `backend/app/api/v1/intervene.py` |
| `InterveneRequestStore` | service | CRUD + metrics for intervene requests; eager loads agent type and Identity for display names; used by both REST API and internal system tool handlers | `backend/app/services/agents/intervene_service.py` |
| `CommunicationHubClient` | class | Control Center outbound client to Communication Hub with fail-closed certificate requirements outside explicit development opt-in | `backend/app/services/control_center/comm_hub_client.py` |
| `engine` | SQLAlchemy engine | Control Center-owned database engine and session boundary | `backend/app/db/session.py` |
| `AsyncSessionLocal` | session factory | Async session factory for all persisted state access in Control Center | `backend/app/db/session.py` |
| `get_db` | dependency | DB session dependency used by Control Center route handlers and services | `backend/app/db/session.py` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_certificate_lifecycle` | integration test | Certificate issuance, validation, and revocation; verifies CRL check takes effect on next validation | `backend/tests/integration/test_certificate_lifecycle.py` |
| `test_token_refresh_security` | integration test | Token refresh with mocked OAuth provider; verifies backoff, 429 handling, and audit log writes | `backend/tests/integration/test_token_refresh_security.py` |
| `test_authorization_flow` | integration test | Full cert → permission → tool authorisation flow; covers permit, deny (tool not allowed), deny (cert revoked) | `backend/tests/integration/test_authorization_flow.py` |
| `test_token_refresh_service` | unit test | Unit tests for `TokenRefreshServiceV2`; mocked OAuth provider and DB | `backend/tests/unit/test_token_refresh_service.py` |
| `test_agent_runtime_denied_for_communication_hub_only_endpoint` | integration test | Verifies caller-specific allowlist partitioning blocks Agent Runtime from Communication Hub-only internal endpoints | `backend/tests/integration/test_internal_allowlist_partitioning.py` |
| `test_communication_hub_denied_for_agent_runtime_only_endpoint` | integration test | Verifies caller-specific allowlist partitioning blocks Communication Hub from Agent Runtime-only internal endpoints | `backend/tests/integration/test_internal_allowlist_partitioning.py` |
| `test_policy_denial_emits_structured_audit_event` | integration test | Verifies deny-by-default decisions emit structured audit events with endpoint and caller metadata | `backend/tests/integration/test_internal_allowlist_partitioning.py` |
| `test_unknown_internal_service_is_denied_by_default` | integration test | Verifies unknown caller identities are denied on internal routes | `backend/tests/integration/test_internal_deny_audit_events.py` |
| `test_unknown_internal_service_denial_emits_structured_event` | integration test | Verifies deny event payload shape for unknown internal callers | `backend/tests/integration/test_internal_deny_audit_events.py` |
| `test_internal_system_tools_rejects_missing_service_certificate` | integration test | Verifies internal system-tools routes reject missing service certificates | `backend/tests/integration/test_internal_deny_audit_events.py` |
| `test_remote_revocation_check_fails_closed_on_transport_error` | integration test | Verifies internal revocation checks fail closed on remote transport errors | `backend/tests/integration/test_internal_revocation_fail_closed.py` |
| `test_remote_revocation_check_allows_dev_opt_in_fallback` | integration test | Verifies revocation fallback is available only behind explicit development opt-in | `backend/tests/integration/test_internal_revocation_fail_closed.py` |
| `test_check_revocation_status_calls_correct_url` | integration test | Verifies client uses Control Center `revoked/{serial}` endpoint contract | `backend/tests/integration/test_data_clients.py` |
| `test_check_revocation_status_fail_closed_on_error` | integration test | Verifies data client treats revocation lookup errors as revoked by default | `backend/tests/integration/test_data_clients.py` |
