# Technical Specification: Agent Runtime Security Segregation

**Created by:** Developer Agent  
**Date:** 2026-05-13  
**Status:** Ready for implementation

---

## 1. Technical Overview

This change implements a zero-trust security model for agent execution by segregating identity management from runtime execution. Three primary technical components are modified:

1. **Control Center** — Extended with Certificate Authority (CA) functionality for issuing and validating X.509 certificates; implements automatic OAuth token refresh; serves as identity authority
2. **Agent Runtime** — Modified to use certificate-based authentication instead of direct identity token access; requests non-sensitive metadata only
3. **Communication Hub** — Extended with certificate validation and Control Center authorization checks before every tool execution

**Key Technical Approach:**
- Mutual TLS (mTLS) for all agent-to-service communication
- Certificate CN format encodes agent type and instance ID for authorization
- Token refresh is automatic and transparent to agent execution
- All identity operations are centralized and logged for audit

---

## 2. Component Breakdown

### Certificate Authority (CA) Module
**Location:** Control Center  
**Responsibility:** PKI operations for agent instance certificates

**Technical Design:**
- Uses `cryptography` library (Python) for certificate generation and validation
- Root CA certificate generated on first Control Center startup (if not exists)
- CA private key stored encrypted using `ENCRYPTION_MASTER_KEY` (AES-256-GCM)
- Certificates issued with 24-hour validity period
- Certificate serial numbers are unique and monotonically increasing
- CRL (Certificate Revocation List) stored in database for fast validation

**Key Functions:**
- `initialize_ca()` — Initialize or load CA on startup (creates root CA cert and private key if not present)
- `issue_agent_certificate(agent_type_id, instance_id)` — Issue new agent instance certificate
- `validate_certificate(cert_pem)` — Validate signature, expiration, and revocation status
- `revoke_certificate(serial_number, reason)` — Add certificate to revocation list
- `extract_cn_components(cert_pem)` — Parse agent-type:instance-id from CN field

### Token Refresh Service
**Location:** Control Center  
**Responsibility:** Automatic OAuth token lifecycle management

**Technical Design:**
- Checks token expiration on every permission request (before returning identity)
- Uses stored refresh token to obtain new access token from OAuth provider
- Implements retry with exponential backoff: 1s, 5s, 15s (max 3 attempts)
- Respects OAuth provider rate limits (checks HTTP 429 responses)
- Logs all refresh attempts with outcome for audit trail
- Updates `agent_identity` table with new token and expiration

**Key Functions:**
- `check_token_expiration(identity_id)` — Returns True if token expired or expires within 5 minutes
- `refresh_oauth_token(identity_id)` — Call OAuth provider with refresh token grant
- `store_refreshed_token(identity_id, access_token, expires_at)` — Update database
- `log_refresh_attempt(identity_id, outcome, error)` — Log to `token_refresh_log` table

### Permission Resolution Service
**Location:** Control Center  
**Responsibility:** Map agent certificates to current permissions and identity tokens

**Technical Design:**
- Receives certificate serial number and tool name from Communication Hub
- Looks up certificate in database to get agent_type_id and instance_id
- Looks up agent type configuration to get assigned identity and roles
- Resolves roles to complete permission set: SOPs → Skills → Tools
- Checks if requested tool is in allowed set
- Checks/refreshes identity token if needed
- Returns identity token and permission decision OR explicit error

**Key Functions:**
- `resolve_permissions(cert_serial_number, tool_name)` — Main entry point
- `get_agent_type_from_certificate(cert_serial_number)` — Lookup agent type
- `get_agent_identity(agent_type_id)` — Retrieve assigned identity
- `get_allowed_tools(agent_type_id)` — Resolve roles to tool permissions
- `check_tool_permission(tool_name, allowed_tools)` — Authorization decision

### Agent Runtime Certificate Manager
**Location:** Agent Runtime  
**Responsibility:** Load, validate, and renew agent instance certificates

**Technical Design:**
- Reads certificate and private key from file paths on startup (environment variables)
- Validates certificate against CA public certificate
- Configures HTTP clients for mutual TLS with certificate and private key
- Background task checks expiration every 1 hour
- Triggers renewal at 80% lifetime (19 hours for 24-hour cert)
- Requests new certificate from Control Center `POST /certificates/issue`
- Atomic switch to new certificate (no downtime)
- Graceful shutdown if certificate expires without renewal

**Key Functions:**
- `load_certificate()` — Load cert and key from files on startup
- `validate_certificate_against_ca()` — Verify signature and expiration
- `configure_mtls_client(cert, key)` — Set up HTTP client with mutual TLS
- `check_certificate_expiration()` — Background task to monitor expiration
- `renew_certificate()` — Request new certificate from Control Center
- `switch_certificate(new_cert, new_key)` — Atomic cert replacement

### Communication Hub Authorization Middleware
**Location:** Communication Hub  
**Responsibility:** Validate certificates and check permissions before tool execution

**Technical Design:**
- Extracts client certificate from TLS handshake on tool call requests
- Validates certificate by calling Control Center validation service
- Requests permission and identity from Control Center authorization service
- Uses Control Center-provided identity token for tool execution (NOT agent-provided)
- Returns explicit authorization errors: 403 Forbidden with reason
- Logs all authorization decisions with certificate details

**Key Functions:**
- `extract_client_certificate(request)` — Get cert from TLS handshake
- `validate_certificate_with_control_center(cert)` — Call Control Center validation API
- `authorize_tool_call(cert_serial_number, tool_name)` — Call Control Center authorization API
- `execute_tool_with_identity(tool_name, params, identity_token)` — Tool execution
- `log_authorization_decision(cert, tool, outcome)` — Audit logging

---

## 3. API Changes

### New Control Center Endpoints

#### `GET /certificates/ca`
**Purpose:** Retrieve CA public certificate for distribution to Agent Runtime instances  
**Authentication:** Public (no auth required — CA cert is public)  
**Request:** None  
**Response:** 
```json
{
  "certificate_pem": "-----BEGIN CERTIFICATE-----\n...",
  "expires_at": "2036-05-13T12:00:00Z",
  "serial_number": "1"
}
```

#### `POST /certificates/issue`
**Purpose:** Issue new agent instance certificate  
**Authentication:** Admin user JWT (requires `admin` role)  
**Request:**
```json
{
  "agent_type_id": "uuid",
  "instance_id": "string"
}
```
**Response:**
```json
{
  "certificate_pem": "-----BEGIN CERTIFICATE-----\n...",
  "private_key_pem": "-----BEGIN PRIVATE KEY-----\n...",
  "serial_number": "12345",
  "expires_at": "2026-05-14T12:00:00Z"
}
```

#### `POST /certificates/revoke`
**Purpose:** Revoke agent instance certificate  
**Authentication:** Admin user JWT (requires `admin` role)  
**Request:**
```json
{
  "serial_number": "12345",
  "reason": "Security incident - compromised instance"
}
```
**Response:**
```json
{
  "revoked_at": "2026-05-13T13:30:00Z",
  "serial_number": "12345"
}
```

#### `POST /internal/certificates/validate`
**Purpose:** Validate agent certificate (internal service-to-service call)  
**Authentication:** Service-to-service (Communication Hub to Control Center)  
**Request:**
```json
{
  "certificate_pem": "-----BEGIN CERTIFICATE-----\n..."
}
```
**Response:**
```json
{
  "valid": true,
  "agent_type_id": "uuid",
  "instance_id": "string",
  "serial_number": "12345",
  "expires_at": "2026-05-14T12:00:00Z"
}
```
OR on failure:
```json
{
  "valid": false,
  "reason": "expired",
  "serial_number": "12345"
}
```

#### `POST /internal/authorize/tool-call`
**Purpose:** Authorize tool call and return identity token (internal service-to-service call)  
**Authentication:** Service-to-service (Communication Hub to Control Center)  
**Request:**
```json
{
  "certificate_serial_number": "12345",
  "tool_name": "mcp_hub.search",
  "tool_params": {"query": "example"}
}
```
**Response:**
```json
{
  "authorized": true,
  "identity_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "identity_id": "uuid",
  "agent_type_id": "uuid"
}
```
OR on failure:
```json
{
  "authorized": false,
  "reason": "insufficient_permissions",
  "required_permission": "mcp_hub.search",
  "agent_type": "research-agent"
}
```

### Modified Agent Runtime Endpoints

#### `GET /agent/metadata` (Modified)
**Before:** Accepted JWT authentication, returned config with identity tokens  
**After:** Requires mutual TLS (client certificate), returns config WITHOUT identity tokens

**Authentication:** Mutual TLS (client certificate validated by Control Center)  
**Request:** Certificate in TLS handshake  
**Response:**
```json
{
  "agent_type_id": "uuid",
  "sops": [...],
  "skills": [...],
  "instructions": "string",
  "model_config": {...}
}
```
**NOTE:** Response explicitly does NOT include `identity_token` or `access_token` fields

### Modified Communication Hub Endpoints

#### `POST /tools/{tool_name}` (Modified)
**Before:** Accepted JWT authentication, trusted agent-provided token  
**After:** Requires mutual TLS (client certificate), validates cert with Control Center, uses Control Center-provided token

**Authentication:** Mutual TLS (client certificate)  
**Request:** Certificate in TLS handshake + tool parameters in JSON body  
**Response:** Tool execution result (same as before)  
**Authorization:** Certificate validated and authorized by Control Center before execution

---

## 4. State Management

No frontend state management changes (this is a backend architecture change).

---

## 5. Data Access Patterns

### Certificate Lifecycle
**Pattern:** Database-backed PKI with in-memory CA key  
**Why:** CA private key must be protected but accessible for signing; certificates stored in DB for audit

**Flow:**
1. Control Center loads CA private key from encrypted secrets on startup
2. Admin requests certificate issuance via API
3. Control Center generates certificate, signs with CA key, stores in `agent_instance_certificate` table
4. Agent Runtime loads certificate from file, validates against CA public cert
5. Certificate expires after 24 hours, triggers renewal
6. Old certificate deleted from Agent Runtime memory, new certificate loaded

### Token Refresh
**Pattern:** Automatic refresh on permission check, not on schedule  
**Why:** Token refresh only when needed (agent is active); reduces unnecessary OAuth calls

**Flow:**
1. Communication Hub requests authorization from Control Center
2. Control Center checks token expiration for agent identity
3. If expired, Control Center calls OAuth provider refresh endpoint
4. Control Center stores new access token encrypted in `agent_identity` table
5. Control Center returns fresh token to Communication Hub
6. Communication Hub uses fresh token for tool call
7. All refresh attempts logged in `token_refresh_log` for audit

### Authorization Decision
**Pattern:** Per-call authorization check (no caching)  
**Why:** Ensures current permissions enforced; certificate revocation takes effect immediately

**Flow:**
1. Agent Runtime calls Communication Hub with client certificate
2. Communication Hub extracts certificate from TLS handshake
3. Communication Hub validates certificate with Control Center
4. Communication Hub requests permission and identity from Control Center
5. Control Center resolves agent type → roles → permissions → allowed tools
6. Control Center checks requested tool is in allowed set
7. Control Center returns authorization decision + identity token (if authorized)
8. Communication Hub executes tool with Control Center-provided token OR returns 403
9. All steps logged in `certificate_validation_log` for audit

---

## 6. Code Reference Map

| Symbol | Type | Description | File | Status |
|--------|------|-------------|------|--------|
| **Certificate Authority Module** | | | | |
| `generate_ca_certificate` | function | Generate root CA certificate and private key | `backend/app/services/certificate_authority.py` | ✅ |
| `issue_agent_certificate` | function | Issue new agent instance certificate | `backend/app/services/certificate_authority.py` | ✅ |
| `validate_certificate` | function | Validate certificate signature, expiration, revocation | `backend/app/services/certificate_authority.py` | ✅ |
| `revoke_certificate` | function | Add certificate to revocation list | `backend/app/services/certificate_authority.py` | ✅ |
| `extract_cn_components` | function | Parse agent-type-id:instance-id from CN | `backend/app/services/certificate_authority.py` | ✅ |
| `initialize_ca` | function | Initialize or load CA on startup | `backend/app/services/certificate_authority.py` | ✅ |
| `get_ca_certificate_pem` | function | Return CA cert in PEM format | `backend/app/services/certificate_authority.py` | ✅ |
| `CertificateAuthorityService` | class | Main CA service class | `backend/app/services/certificate_authority.py` | ✅ |
| `CertificateValidationResult` | NamedTuple | Validation result type | `backend/app/services/certificate_authority.py` | ✅ |
| `IssuedCertificate` | NamedTuple | Certificate issuance result type | `backend/app/services/certificate_authority.py` | ✅ |
| **Token Refresh Service** | | | | |
| `check_token_expiration` | function | Check if identity token needs refresh | `backend/app/services/token_refresh.py` | ✅ |
| `refresh_oauth_token` | function | Call OAuth provider to refresh token | `backend/app/services/token_refresh.py` | ✅ |
| `store_refreshed_token` | function | Update agent_identity with new token | `backend/app/services/token_refresh.py` | ✅ |
| `log_refresh_attempt` | function | Log refresh attempt to audit table | `backend/app/services/token_refresh.py` | ✅ |
| `TokenRefreshServiceV2` | class | Security-segregation token refresh service | `backend/app/services/token_refresh.py` | ✅ |
| `TokenRefreshError` | exception | Token refresh failure exception | `backend/app/services/token_refresh.py` | ✅ |
| **Permission Resolution Service** | | | | |
| `resolve_permissions` | function | Main entry point for permission resolution | `backend/app/services/permission_resolution.py` | ✅ |
| `get_agent_type_from_certificate` | function | Lookup agent type from certificate serial | `backend/app/services/permission_resolution.py` | ✅ |
| `get_agent_identity` | function | Retrieve assigned identity for agent type | `backend/app/services/permission_resolution.py` | ✅ |
| `get_allowed_tools` | function | Resolve roles to allowed tool set | `backend/app/services/permission_resolution.py` | ✅ |
| `check_tool_permission` | function | Check if tool is in allowed set | `backend/app/services/permission_resolution.py` | ✅ |
| `PermissionResolutionService` | class | Main permission resolution service class | `backend/app/services/permission_resolution.py` | ✅ |
| `AuthorizationResult` | NamedTuple | Permission resolution result type | `backend/app/services/permission_resolution.py` | ✅ |
| **Control Center API Endpoints** | | | | |
| `get_ca_certificate_endpoint` | endpoint | GET /certificates/ca | `backend/app/api/v1/certificates.py` | ✅ |
| `issue_certificate` | endpoint | POST /certificates/issue | `backend/app/api/v1/certificates.py` | ✅ |
| `revoke_certificate` | endpoint | POST /certificates/revoke | `backend/app/api/v1/certificates.py` | ✅ |
| `validate_certificate_internal` | endpoint | POST /internal/certificates/validate | `backend/app/api/v1/internal/certificates.py` | ✅ |
| `authorize_tool_call_internal` | endpoint | POST /internal/authorize/tool-call | `backend/app/api/v1/internal/authorization.py` | ✅ |
| **Schemas** | | | | |
| `CertificateIssueRequest` | schema | Request for POST /certificates/issue | `backend/app/schemas/certificates.py` | ✅ |
| `CertificateRevokeRequest` | schema | Request for POST /certificates/revoke | `backend/app/schemas/certificates.py` | ✅ |
| `CertificateValidateRequest` | schema | Request for POST /internal/certificates/validate | `backend/app/schemas/certificates.py` | ✅ |
| `AuthorizeToolCallRequest` | schema | Request for POST /internal/authorize/tool-call | `backend/app/schemas/certificates.py` | ✅ |
| `CACertificateResponse` | schema | Response for GET /certificates/ca | `backend/app/schemas/certificates.py` | ✅ |
| `CertificateIssueResponse` | schema | Response for POST /certificates/issue | `backend/app/schemas/certificates.py` | ✅ |
| `AuthorizeToolCallResponse` | schema | Response for POST /internal/authorize/tool-call | `backend/app/schemas/certificates.py` | ✅ |
| **Database Models** | | | | |
| `AgentInstanceCertificate` | model | Agent instance certificate storage | `backend/app/db/models/agent_security.py` | ✅ |
| `CertificateRevocationEntry` | model | Certificate revocation list | `backend/app/db/models/agent_security.py` | ✅ |
| `TokenRefreshLog` | model | Token refresh audit log | `backend/app/db/models/agent_security.py` | ✅ |
| `CertificateValidationLog` | model | Certificate validation audit log | `backend/app/db/models/agent_security.py` | ✅ |
| `AgentIdentity` | model | Updated with refresh token fields | `backend/app/db/models/agents.py` | ✅ |
| **Agent Runtime Certificate Manager** | | | | |
| `load_certificate` | method | Load cert and key from files on startup | `backend/app/agent_runtime/certificate_manager.py` | ✅ |
| `validate_certificate_against_ca` | method | Verify cert signature and expiration | `backend/app/agent_runtime/certificate_manager.py` | ✅ |
| `configure_mtls_client` | method | Set up HTTP client with mutual TLS | `backend/app/agent_runtime/certificate_manager.py` | ✅ |
| `check_certificate_expiration` | method | Background task to monitor expiration | `backend/app/agent_runtime/certificate_manager.py` | ✅ |
| `renew_certificate` | method | Request new certificate from Control Center | `backend/app/agent_runtime/certificate_manager.py` | ✅ |
| `switch_certificate` | method | Atomic cert replacement | `backend/app/agent_runtime/certificate_manager.py` | ✅ |
| `run_renewal_task` | method | Background coroutine for renewal monitoring | `backend/app/agent_runtime/certificate_manager.py` | ✅ |
| `CertificateManager` | class | Main certificate manager class | `backend/app/agent_runtime/certificate_manager.py` | ✅ |
| **Agent Runtime Metadata Client** | | | | |
| `request_metadata` | method | Request metadata from Control Center with cert | `backend/app/agent_runtime/metadata_client.py` | ✅ |
| `verify_no_identity_tokens` | function | Security check: response has no tokens | `backend/app/agent_runtime/metadata_client.py` | ✅ |
| `MetadataClient` | class | Metadata client with mTLS and security checks | `backend/app/agent_runtime/metadata_client.py` | ✅ |
| **Communication Hub Authorization Middleware** | | | | |
| `extract_client_certificate` | function | Get cert from request (header or TLS state) | `backend/app/communication_hub/middleware/authorization.py` | ✅ |
| `validate_certificate_with_control_center` | function | Call Control Center validation API | `backend/app/communication_hub/middleware/authorization.py` | ✅ |
| `authorize_tool_call` | function | Call Control Center authorization API | `backend/app/communication_hub/middleware/authorization.py` | ✅ |
| `execute_tool_with_identity` | function | Tool execution with CC-provided token | `backend/app/communication_hub/middleware/authorization.py` | ✅ |
| `log_authorization_decision` | function | Audit logging | `backend/app/communication_hub/middleware/authorization.py` | ✅ |
| `CertificateAuthorizationMiddleware` | class | Starlette middleware for tool call authorization | `backend/app/communication_hub/middleware/authorization.py` | ✅ |
| **Application Startup** | | | | |
| `_initialize_certificate_authority` | function | Startup hook for CA initialization | `backend/app/main.py` | ✅ |
| **Tests** | | | | |
| `test_certificate_lifecycle` | tests | Certificate issuance, validation, revocation | `backend/tests/integration/test_certificate_lifecycle.py` | ✅ |
| `test_token_refresh_security` | tests | Token refresh with mocked OAuth provider | `backend/tests/integration/test_token_refresh_security.py` | ✅ |
| `test_authorization_flow` | tests | Full authorization flow integration tests | `backend/tests/integration/test_authorization_flow.py` | ✅ |
| **Documentation** | | | | |
| `deployment.md` | doc | Deployment guide with steps and rollback | `docs/changes/agent-runtime-security-segregation/deployment.md` | ✅ |
| `operations.md` | doc | Operations runbook: monitoring, revocation, audit | `docs/changes/agent-runtime-security-segregation/operations.md` | ✅ |
| **Configuration** | | | | |
| `AGENT_CERT_PATH` | env var | Path to agent instance certificate PEM | Environment variable | ✅ |
| `AGENT_KEY_PATH` | env var | Path to agent instance private key PEM | Environment variable | ✅ |
| `CA_CERT_PATH` | env var | Path to CA public certificate PEM | Environment variable | ✅ |
| `CONTROL_CENTER_URL` | env var | Base URL for Control Center API | Environment variable | ✅ |
| `ENCRYPTION_MASTER_KEY` | env var | AES-256 key — maps to `CREDENTIAL_VAULT_KEY` in settings | Environment variable (existing) | ✅ |

---

## Security Considerations

### Certificate Security
- CA private key stored encrypted at rest (AES-256-GCM with ENCRYPTION_MASTER_KEY)
- CA private key loaded into memory only on Control Center startup
- Agent instance certificates have short validity (24 hours) to limit exposure window
- Certificate revocation takes effect immediately (checked on every validation)
- Certificate serial numbers are unique and monotonically increasing to prevent collisions

### Identity Token Security
- Identity tokens never transmitted to Agent Runtime (only to Communication Hub)
- Tokens stored encrypted at rest in `agent_identity` table
- Tokens decrypted only when needed for tool execution
- Token refresh happens automatically before expiration (no manual management)
- If token refresh fails, agent execution is blocked (fail-safe)

### Transport Security
- All agent-to-service communication uses mutual TLS (mTLS)
- Certificate validation on every request (no caching)
- TLS 1.3 recommended for all connections
- Cipher suites: AES-256-GCM preferred

### Audit Logging
- All certificate validations logged with outcome (valid, expired, revoked)
- All token refresh attempts logged with outcome (success, failure, rate_limited)
- All authorization decisions logged with agent cert, tool name, outcome
- Logs include sufficient detail for security investigations
- Log retention: 90 days minimum for compliance

---

**Next Steps:**
- Tester agent: Create test-plan.md with coverage for all components and integration scenarios
- After testing phase: Create deployment.md and operations.md
