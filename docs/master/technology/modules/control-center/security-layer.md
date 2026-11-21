# Module: control-center — Security Layer

> Part of the [control-center hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

The security layer is the zero-trust PKI and authorisation core of the Control Center: certificate lifecycle, OAuth token refresh/health, permission resolution from certificate or API key, and API key management. It is the only component that issues identity tokens to the Communication Hub.

**Security model:** agent instances hold certificates, never tokens. On every tool call the hub presents the client certificate (or an API key) and CC returns a fresh identity token only when the resolved tool set permits the call. Agent-instance certificates are blocked from `/internal/*` endpoints; service certificates are allowlisted per caller.

---

## Components

### Certificate Authority

| Component | Description |
|-----------|-------------|
| `CertificateAuthorityService` | Root CA lifecycle management; generates the CA on first startup (if absent), signs agent instance certificates with an AES-256-GCM encrypted CA key, validates signatures and revocation status, maintains monotonically increasing serial numbers |
| `CertificateValidationResult` | NamedTuple: `valid`, `reason`, `agent_type_id`, `instance_id`, `serial_number`, `expires_at` |
| `IssuedCertificate` | NamedTuple: `certificate_pem`, `private_key_pem`, `serial_number`, `expires_at` |

### Token refresh and health

| Component | Description |
|-----------|-------------|
| `TokenRefreshServiceV2` | On-demand refresh triggered by permission checks; 5-minute expiry buffer; provider refresh endpoint; exponential backoff (1 s, 5 s, 15 s, max 3); respects HTTP 429; stores the new access token AES-256 encrypted on `agent_identity`; logs every attempt |
| `TokenHealthService` | Computes/persists health for identities and sessions (7-day constant). Refresh-token expiry is authoritative when a refresh token exists; access-token expiry is only the fallback. `refresh_failed` and MCP `requires_reauth` force `expired`; an unknown refresh expiry is `healthy` |
| `TokenRefreshError` | Raised when refresh fails after all retries |

> `TokenRefreshServiceV2` (`backend/app/services/token_refresh.py`) is the segregation-era implementation used by permission resolution. The background proactive service (`backend/app/services/agents/token_refresh_service.py`) is documented in the [agents execution page](../agents/execution.md).

### Permission resolution

| Component | Description |
|-----------|-------------|
| `PermissionResolutionService` | Main authorisation entry point for the hub: cert serial → agent type → identity → roles → tools; resolves the agent's **role** (permission) and the **agent type's own bindings** (visibility) — the intersection is the allowed set; refreshes an expiring token; returns an identity token or an explicit denial reason. Also resolves from an API key (key → identity → role → policy) |
| `AuthorizationResult` | NamedTuple: `authorized`, `identity_token`, `identity_id`, `agent_type_id`, `reason` |

### API key management

| Component | Description |
|-----------|-------------|
| `ApiKeyService` | Cryptographically random keys (`phn_sk_` prefix), SHA-256 hashing, hash lookup, status management (activate/revoke), usage logs, identity-token decryption for bound identities |
| `AdminApiKeyRouter` | JWT-protected admin API key CRUD and identity-with-roles listing |

**Files**: `backend/app/services/api_key_service.py` (service), `backend/app/api/v1/api_keys.py` (router).

### Models (`backend/app/db/models/agent_security.py`)

| Component | Description |
|-----------|-------------|
| `AgentInstanceCertificate` | Issued certificates: `serial_number` (unique), `agent_type_id`, `instance_id`, `certificate_pem`, `issued_at`, `expires_at`, `revoked` |
| `CertificateRevocationEntry` | CRL entries (`serial_number`, `revoked_at`, `reason`); queried on every validation |
| `TokenRefreshLog` | Refresh audit: `agent_identity_id` (nullable), `mcp_session_id` (nullable), `outcome`, `error`, `attempted_at`; exactly-one-target constraint |
| `CertificateValidationLog` | Validation audit: `serial_number`, `tool_name`, `outcome`, `validated_at` |

---

## API Endpoints

### Certificates (admin-facing)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/certificates/ca` | Public | CA public certificate PEM for distribution to Agent Runtime |
| `POST` | `/api/v1/certificates/issue` | Admin JWT | Issue a new agent instance or service certificate |
| `POST` | `/api/v1/certificates/revoke` | Admin JWT | Revoke by serial; adds a CRL entry |

### API keys (admin-facing)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1/api-keys` | Admin JWT | List keys with optional `?status=active\|revoked` |
| `POST` | `/api/v1/api-keys` | Admin JWT | Create a key bound to an identity and role; returns the clear-text key once |
| `POST` | `/api/v1/api-keys/{key_id}/revoke` | Admin JWT | Revoke (idempotent) |
| `GET` | `/api/v1/api-keys/identities-with-roles` | Admin JWT | Identities and their available roles |

### Internal (service-to-service)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/internal/certificates/validate` | Validate a certificate PEM from the hub; returns agent type/instance |
| `GET` | `/internal/certificates/revoked/{serial_number}` | Revocation status (fail-closed client contract) |
| `POST` | `/internal/authorize/tool-call` | Authorise a tool call for a cert serial; returns identity token + decision |
| `POST` | `/internal/auth/validate-api-key` | Validate a hashed API key; returns identity, role, token and permission set |
| `POST` | `/internal/token-health/preflight` | Signed internal calls only; PROCEED / PROCEED+WARN / BLOCKED |

---

## Data Access Patterns

**Certificate lifecycle:** the CA private key is loaded encrypted from `ENCRYPTION_MASTER_KEY` at startup and kept in memory. Certificates are written on issuance and validated from the DB on every inbound request; CRL is checked inline.

**Permission resolution:** per-call DB query (no caching) so revocations and role changes take effect immediately. Token refresh is inline — if the token expires within 5 minutes, refresh runs before the response returns.

**Audit:** every certificate validation and token-refresh attempt is written synchronously before the response.

---

## Code Reference Map

### `backend/app/services/certificate_authority.py`

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `CertificateAuthorityService` | class | Root CA management: generate, sign, validate, revoke | `backend/app/services/certificate_authority.py` |
| `CertificateValidationResult` / `IssuedCertificate` | NamedTuples | Validation and issuance result carriers | `backend/app/services/certificate_authority.py` |
| `generate_ca_certificate` / `initialize_ca` | functions | Generate the root CA and load/create it at startup | `backend/app/services/certificate_authority.py` |
| `issue_agent_certificate` / `revoke_certificate` | functions | Sign+persist a certificate; add a CRL entry | `backend/app/services/certificate_authority.py` |
| `validate_certificate` | function | Verify signature, expiration and CRL status | `backend/app/services/certificate_authority.py` |
| `extract_cn_components` / `get_ca_certificate_pem` | functions | Parse `agent_type_id:instance_id` from CN; return the CA PEM | `backend/app/services/certificate_authority.py` |

### `backend/app/services/token_refresh.py` and `token_health.py`

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TokenRefreshServiceV2` | class | On-demand refresh with exponential backoff and health propagation | `backend/app/services/token_refresh.py` |
| `TokenRefreshError` | exception | Raised after all retries fail | `backend/app/services/token_refresh.py` |
| `check_token_expiration` | function | True when expired or within 5 minutes (also evaluates the refresh-token window) | `backend/app/services/token_refresh.py` |
| `refresh_oauth_token` | function | Provider refresh with backoff; persists health and outcome | `backend/app/services/token_refresh.py` |
| `store_refreshed_token` | function | Persist the encrypted access token and provider-reported refresh expiry | `backend/app/services/token_refresh.py` |
| `log_refresh_attempt` | function | Write the attempt outcome to `token_refresh_log` | `backend/app/services/token_refresh.py` |
| `TokenHealthService` | class | Health classification/persistence and preflight evaluation | `backend/app/services/token_health.py` |

### `backend/app/services/permission_resolution.py`

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PermissionResolutionService` | class | Cert/API-key → agent type → identity → role ∩ agent-type visibility → tools | `backend/app/services/permission_resolution.py` |
| `AuthorizationResult` | NamedTuple | `authorized`, `identity_token`, `identity_id`, `agent_type_id`, `reason` | `backend/app/services/permission_resolution.py` |
| `resolve_permissions` | function | Entry point for the hub (cert serial + tool name) | `backend/app/services/permission_resolution.py` |
| `get_agent_type_from_certificate` / `get_agent_identity` | functions | Certificate → agent type; agent type → identity | `backend/app/services/permission_resolution.py` |
| `get_allowed_tools` / `check_tool_permission` | functions | Resolve the allowed tool set and test membership | `backend/app/services/permission_resolution.py` |
| `resolve_permissions_from_api_key` | function | Key → identity → role → permissions | `backend/app/services/permission_resolution.py` |

### Endpoints and schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `get_ca_certificate_endpoint` / `issue_certificate` / `revoke_certificate` | endpoints | Certificate admin and distribution routes | `backend/app/api/v1/certificates.py` |
| `validate_certificate_internal` / `check_certificate_revoked` | endpoints | Internal validation and revocation-status routes | `backend/app/api/v1/internal/certificates.py` |
| `authorize_tool_call_internal` | endpoint | Internal authoriser returning the identity token on success | `backend/app/api/v1/internal/authorization.py` |
| `InternalTokenHealthRouter` | router | `POST /internal/token-health/preflight` (signed internal calls, fail-closed 401) | `backend/app/api/v1/internal/token_health.py` |
| Token health dashboard endpoint | endpoint | `GET /dashboard/token-health` expired/expiring counts + itemized detail | `backend/app/api/v1/dashboard.py` |
| `refresh_token` (identity) | endpoint | `POST /agents/identities/{identity_id}/refresh-token` | `backend/app/api/v1/agents.py` |
| `refresh_token` (MCP session) | endpoint | `POST /mcp/servers/{server_id}/sessions/{session_id}/refresh-token` | `backend/app/api/v1/mcp_hub.py` |
| `CertificateIssueRequest` / `CertificateRevokeRequest` / `CertificateValidateRequest` / `AuthorizeToolCallRequest` / `CACertificateResponse` / `CertificateIssueResponse` / `AuthorizeToolCallResponse` | schemas | Certificate and authorisation wire contracts | `backend/app/schemas/certificates.py` |
| Token health schemas | Pydantic models | Dashboard summary/items + preflight request/result | `backend/app/schemas/token_health.py` |
| `AgentInstanceCertificate` / `CertificateRevocationEntry` / `TokenRefreshLog` / `CertificateValidationLog` | models | Security audit and certificate records | `backend/app/db/models/agent_security.py` |

### API keys

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `api_key_service` | module | Key generation, hashing, validation, lifecycle | `backend/app/services/api_key_service.py` |
| `generate_api_key` / `hash_api_key` / `validate_api_key_from_hash` | functions | `phn_sk_` key creation, SHA-256 hashing, hash lookup | `backend/app/services/api_key_service.py` |
| `create_api_key_usage_log` / `update_last_used_at` / `check_duplicate_active_key` | functions | Usage audit, last-used tracking, duplicate guard | `backend/app/services/api_key_service.py` |
| `resolve_identity_token` / `resolve_allowed_tools` | functions | Decrypt the bound identity token; resolve the role's tools | `backend/app/services/api_key_service.py` |
| `AdminApiKeyRouter` | router | Admin API key CRUD routes | `backend/app/api/v1/api_keys.py` |
| `list_api_keys` / `create_api_key` / `revoke_api_key` / `list_identities_with_roles` | endpoints | Admin API key surface | `backend/app/api/v1/api_keys.py` |
| `validate_api_key_internal` / `InternalAuthRouter` | endpoint / router | Internal API-key validation (service-cert gated) | `backend/app/api/v1/internal/validate_api_key.py` |
| `ApiKeyCreate` / `ApiKeyCreateResponse` / `ApiKeyRead` / `ApiKeyListItem` / `ApiKeyRevokeResponse` / `RoleItem` / `ToolDefinition` / `ApiKeyValidateRequest` / `ApiKeyValidateResponse` / `SkillWithVersion` | schemas | API key wire contracts (never expose secrets) | `backend/app/schemas/api_key.py` |
| `resolve_skills_internal` | endpoint | Resolve skills for a role with optional `since` | `backend/app/api/v1/internal/system_tools.py` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_certificate_lifecycle` | integration test | Issuance, validation, revocation; CRL takes effect on next validation | `backend/tests/integration/test_certificate_lifecycle.py` |
| `test_token_refresh_security` | integration test | Refresh backoff, 429 handling, audit writes | `backend/tests/integration/test_token_refresh_security.py` |
| `test_authorization_flow` | integration test | Cert → permission → tool authorisation (permit, tool-denied, cert-revoked) | `backend/tests/integration/test_authorization_flow.py` |
| `test_token_refresh_service` | unit test | `TokenRefreshServiceV2` with mocked provider/DB | `backend/tests/unit/test_token_refresh_service.py` |
| `test_remote_revocation_check_fails_closed_on_transport_error` / `..._allows_dev_opt_in_fallback` | integration tests | Revocation fail-closed contract | `backend/tests/integration/test_internal_revocation_fail_closed.py` |
| `test_check_revocation_status_calls_correct_url` / `..._fail_closed_on_error` | integration tests | Client URL contract and fail-closed behaviour | `backend/tests/integration/test_data_clients.py` |
| `test_token_health_service` / `test_token_health_api` | unit / API tests | Health classification, dashboard and preflight | `backend/tests/services/test_token_health_service.py`, `backend/tests/api/v1/test_token_health_api.py` |
