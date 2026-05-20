# Implementation Plan: Agent Runtime Security Segregation

**Created by:** Developer Agent  
**Date:** 2026-05-13  
**Status:** Implementation complete

---

## Overview

This implementation plan breaks down the certificate-based security segregation into manageable phases. Each phase can be implemented and tested independently, with clear done conditions to verify completion.

---

## Task Checklist

### Phase 1: Database Schema and Models
- [x] 1.1 — Create Certificate Management Models
- [x] 1.2 — Create Audit Log Models
- [x] 1.3 — Update Agent Identity Model

### Phase 2: Certificate Authority Module (Control Center)
- [x] 2.1 — Implement CA Initialization
- [x] 2.2 — Implement Certificate Issuance
- [x] 2.3 — Implement Certificate Validation
- [x] 2.4 — Implement Certificate Revocation

### Phase 3: Token Refresh Service (Control Center)
- [x] 3.1 — Implement Token Expiration Check
- [x] 3.2 — Implement Token Refresh with OAuth Provider
- [x] 3.3 — Integrate Token Refresh into Permission Resolution

### Phase 4: Agent Runtime Certificate Support
- [x] 4.1 — Implement Certificate Loading on Startup
- [x] 4.2 — Implement Certificate-Based Metadata Requests
- [x] 4.3 — Implement Certificate-Based Tool Calls
- [x] 4.4 — Implement Certificate Renewal

### Phase 5: Communication Hub Authorization Integration
- [x] 5.1 — Implement Certificate Validation in Communication Hub
- [x] 5.2 — Implement Control Center Permission Check
- [x] 5.3 — Implement Authorization Error Handling

### Phase 6: Testing and Validation
- [x] 6.1 — Backend Integration Tests - Certificate Lifecycle
- [x] 6.2 — Backend Integration Tests - Token Refresh
- [x] 6.3 — Backend Integration Tests - Authorization Flow
- [ ] 6.4 — E2E Tests - Agent Execution with Certificates

### Phase 7: Deployment and Operations
- [x] 7.1 — Create Deployment Documentation
- [x] 7.2 — Create Operations Documentation

---

## Phase 1: Database Schema and Models

### Task 1.1: Create Certificate Management Models
**Description:** Create SQLAlchemy models for agent instance certificates and certificate revocation list

**Done when:**
- `AgentInstanceCertificate` and `CertificateRevocationEntry` models created in `backend/app/db/models/agent_security.py`
- Models include proper relationships (AgentInstanceCertificate → agent_type)
- Models include proper indexes (serial_number unique on revocation entry)
- Alembic migration generated and applied successfully: `alembic upgrade head`
- Migration creates tables with correct columns and constraints

### Task 1.2: Create Audit Log Models
**Description:** Create SQLAlchemy models for token refresh and certificate validation audit logs

**Done when:**
- `TokenRefreshLog` and `CertificateValidationLog` models created in `backend/app/db/models/agent_security.py`
- Models include proper relationships (TokenRefreshLog → agent_identity)
- Models include proper indexes (certificate_serial_number, validated_at on validation log)
- Alembic migration generated and applied successfully
- Migration creates tables with correct columns and constraints

### Task 1.3: Update Agent Identity Model
**Description:** Add refresh token storage fields to existing agent_identity model

**Done when:**
- `backend/app/db/models/agent_identity.py` updated with three new fields: `encrypted_refresh_token`, `last_token_refresh_at`, `token_status`
- Token status enum defined with values: `active`, `expired`, `refresh_failed`
- Alembic migration generated for field additions
- Migration applied successfully without data loss
- Existing agent_identity records have NULL values for new fields (nullable during migration)

---

## Phase 2: Certificate Authority Module (Control Center)

### Task 2.1: Implement CA Initialization
**Description:** Create CA certificate generation on Control Center first startup

**Done when:**
- Control Center checks for existing CA certificate on startup
- If not found, generates new RSA key pair (4096-bit)
- Creates self-signed root CA certificate with 10-year validity
- Stores CA private key encrypted in secrets storage (using ENCRYPTION_MASTER_KEY)
- Stores CA public certificate in database for distribution
- Logs CA initialization with certificate details (subject, serial number, expiration)
- CA certificate can be retrieved via API endpoint: `GET /certificates/ca`

### Task 2.2: Implement Certificate Issuance
**Description:** Create API endpoint for issuing agent instance certificates

**Done when:**
- New endpoint: `POST /certificates/issue` accepts agent_type_id and instance_id
- Validates requester has admin permissions
- Generates certificate signing request (CSR) internally
- Signs CSR with CA private key
- Certificate CN format: `agent-type:instance-id`
- Certificate validity: 24 hours from issuance
- Stores certificate in `agent_instance_certificate` table with status `active`
- Returns certificate PEM, private key PEM, and expiration timestamp
- Logs certificate issuance with agent type, instance ID, serial number

### Task 2.3: Implement Certificate Validation
**Description:** Create certificate validation service for Control Center and Communication Hub

**Done when:**
- Certificate validation function accepts certificate PEM
- Verifies certificate signature against CA public certificate
- Checks certificate expiration (rejects if expired)
- Checks certificate revocation list (rejects if revoked)
- Extracts CN and parses agent-type:instance-id
- Logs validation attempt in `certificate_validation_log` table with outcome
- Returns validation result: valid (with agent_type_id, instance_id) or invalid (with reason)
- Validation completes in < 10ms (p95) for performance

### Task 2.4: Implement Certificate Revocation
**Description:** Create API endpoint for revoking agent instance certificates

**Done when:**
- New endpoint: `POST /certificates/revoke` accepts certificate serial number and reason
- Validates requester has admin permissions
- Looks up certificate by serial number
- Updates `agent_instance_certificate.revoked_at` and `revocation_reason`
- Updates certificate status to `revoked`
- Adds entry to `certificate_revocation_entry` table
- Returns confirmation with revocation timestamp
- Logs revocation with admin user ID and reason
- Subsequent validation attempts return `revoked` outcome

---

## Phase 3: Token Refresh Service (Control Center)

### Task 3.1: Implement Token Expiration Check
**Description:** Create function to check if identity token is expired and needs refresh

**Done when:**
- Function accepts `agent_identity_id`
- Retrieves `access_token_expires_at` from `agent_identity` table
- Compares with current timestamp
- Returns boolean: `true` if expired or expires within 5 minutes, `false` otherwise
- No database write operations (pure check function)
- Used by permission resolution before returning tokens

### Task 3.2: Implement Token Refresh with OAuth Provider
**Description:** Create service to refresh OAuth tokens using stored refresh token

**Done when:**
- Function accepts `agent_identity_id`
- Retrieves and decrypts `encrypted_refresh_token`
- Calls OAuth provider token endpoint with refresh token grant
- Handles OAuth provider responses: success, invalid_grant, rate_limit
- Implements retry with exponential backoff: 1s, 5s, 15s (max 3 attempts)
- On success: updates `encrypted_access_token`, `access_token_expires_at`, `last_token_refresh_at`, `token_status=active`
- On failure: updates `token_status=refresh_failed`
- Logs attempt in `token_refresh_log` with outcome and error message
- Returns new access token or explicit error
- Respects OAuth provider rate limits (backs off if rate-limited)

### Task 3.3: Integrate Token Refresh into Permission Resolution
**Description:** Automatically refresh expired tokens when resolving permissions

**Done when:**
- Permission resolution service checks token expiration before returning identity
- If expired, calls token refresh service automatically
- If refresh succeeds, returns fresh token with permissions
- If refresh fails, returns explicit error: "Token refresh failed: {reason}"
- Agent execution is blocked if refresh fails (no fallback to expired token)
- Logs token refresh trigger with permission request context

---

## Phase 4: Agent Runtime Certificate Support

### Task 4.1: Implement Certificate Loading on Startup
**Description:** Agent Runtime loads instance certificate and CA certificate on startup

**Done when:**
- Agent Runtime reads certificate paths from environment: `AGENT_CERT_PATH`, `AGENT_KEY_PATH`, `CA_CERT_PATH`
- Validates certificate files exist and are readable
- Loads certificate PEM and private key PEM into memory
- Validates certificate signature against CA public certificate
- Extracts agent-type:instance-id from CN and validates against expected agent type
- Fails startup with clear error if certificate is invalid or expired
- Logs certificate load success with serial number and expiration

### Task 4.2: Implement Certificate-Based Metadata Requests
**Description:** Agent Runtime requests metadata from Control Center using client certificate

**Done when:**
- Agent Runtime HTTP client configured for mutual TLS
- Client certificate and private key attached to TLS handshake
- `GET /agent/metadata` request includes client certificate
- Control Center validates certificate before processing request
- Agent Runtime receives metadata response (SOPs, skills, instructions, model configs)
- Agent Runtime verifies response does NOT contain identity tokens (security check)
- Logs metadata retrieval success/failure
- Retries on transient failures (network errors, 5xx responses) with exponential backoff

### Task 4.3: Implement Certificate-Based Tool Calls
**Description:** Agent Runtime calls tools via Communication Hub using client certificate

**Done when:**
- Agent Runtime tool call client configured for mutual TLS
- Client certificate and private key attached to TLS handshake
- `POST /tools/{tool_name}` request includes client certificate
- Agent Runtime does NOT include identity tokens in request (verified by security check)
- Communication Hub validates certificate before processing
- Agent Runtime handles authorization errors: 403 Forbidden with clear reason
- Logs tool call success/failure with certificate serial number
- Retries on transient failures (network errors, 5xx responses) but NOT on 403 (authorization failure)

### Task 4.4: Implement Certificate Renewal
**Description:** Agent Runtime automatically renews certificate before expiration

**Done when:**
- Background task checks certificate expiration every 1 hour
- If certificate expires within 5 hours (80% of 24-hour lifetime), triggers renewal
- Renewal calls `POST /certificates/issue` with current agent_type_id and instance_id
- New certificate and private key are received and stored
- Agent Runtime switches to new certificate for subsequent requests
- Old certificate is discarded after successful switch
- Logs certificate renewal success with new serial number and expiration
- If renewal fails, logs error and retries every 30 minutes until success or expiration
- If certificate expires without successful renewal, Agent Runtime shuts down gracefully

---

## Phase 5: Communication Hub Authorization Integration

### Task 5.1: Implement Certificate Validation in Communication Hub
**Description:** Communication Hub validates agent client certificates on every tool call

**Done when:**
- Communication Hub configured for mutual TLS on agent-facing endpoints
- Communication Hub extracts client certificate from TLS handshake
- Calls Control Center certificate validation service for every tool call
- If validation fails, returns 403 Forbidden with reason (expired, revoked, invalid_signature)
- If validation succeeds, extracts agent_type_id and instance_id for authorization check
- Logs certificate validation outcome with serial number and tool name
- Validation adds < 10ms latency (p95)

### Task 5.2: Implement Control Center Permission Check
**Description:** Communication Hub requests permissions from Control Center before executing tools

**Done when:**
- New endpoint in Control Center: `POST /authorize/tool-call` accepts certificate serial number, tool name
- Control Center extracts agent_type_id and instance_id from certificate
- Control Center looks up agent type configuration and assigned roles
- Control Center resolves roles to permissions (SOPs → Skills → Tools)
- Control Center checks if requested tool is in allowed tool set
- Control Center retrieves agent identity and checks/refreshes token
- Control Center returns authorization response: allowed (with identity token) or denied (with reason)
- Communication Hub calls this endpoint before EVERY tool execution
- Communication Hub uses Control Center-provided identity token for tool call (NOT agent-provided token)
- Logs authorization decision with certificate CN, tool name, outcome

### Task 5.3: Implement Authorization Error Handling
**Description:** Communication Hub returns explicit authorization errors to Agent Runtime

**Done when:**
- If certificate is invalid: returns 403 Forbidden with message "Invalid certificate: {reason}"
- If tool is not permitted: returns 403 Forbidden with message "Insufficient permissions: tool '{tool_name}' not allowed for agent type '{agent_type}'"
- If token refresh fails: returns 503 Service Unavailable with message "Identity token refresh failed: {reason}"
- Error responses include actionable details (certificate serial number, required permission, etc.)
- Logs all authorization failures with full context for audit
- Agent Runtime receives clear error messages for debugging

---

## Phase 6: Testing and Validation

### Task 6.1: Backend Integration Tests - Certificate Lifecycle
**Description:** Test certificate issuance, validation, renewal, and revocation

**Done when:**
- Test: Issue certificate for agent type → certificate created in database with correct fields
- Test: Validate valid certificate → validation succeeds, returns agent_type_id and instance_id
- Test: Validate expired certificate → validation fails with outcome `expired`
- Test: Revoke certificate → certificate marked revoked, validation fails with outcome `revoked`
- Test: Attempt to use revoked certificate for metadata request → returns 403 Forbidden
- All tests pass consistently; run against real database with migrations applied

### Task 6.2: Backend Integration Tests - Token Refresh
**Description:** Test automatic token refresh logic with mocked OAuth provider

**Done when:**
- Test: Permission check with valid token → returns token without refresh
- Test: Permission check with expired token → triggers refresh, returns new token
- Test: Token refresh success → updates access_token, expires_at, last_token_refresh_at, token_status
- Test: Token refresh failure (invalid_grant) → logs failure, returns error, sets token_status=refresh_failed
- Test: Token refresh rate-limited → respects rate limit, backs off, retries after delay
- Test: Query `token_refresh_log` table → verify all refresh attempts logged with outcome
- All tests pass consistently; mock OAuth provider responses for deterministic testing

### Task 6.3: Backend Integration Tests - Authorization Flow
**Description:** Test full authorization flow: certificate validation + permission check + token refresh

**Done when:**
- Test: Tool call with valid certificate and sufficient permissions → authorized, returns identity token
- Test: Tool call with invalid certificate → returns 403 with reason "Invalid certificate"
- Test: Tool call with insufficient permissions → returns 403 with reason "Insufficient permissions"
- Test: Tool call with expired token → triggers refresh automatically, returns fresh token
- Test: Tool call with token that cannot be refreshed → returns 503 with reason "Token refresh failed"
- Test: Query `certificate_validation_log` → verify all validations logged with outcome
- All tests pass consistently; run against real database

### Task 6.4: E2E Tests - Agent Execution with Certificates
**Description:** End-to-end test of agent execution using certificate-based auth

**Done when:**
- Test: Agent Runtime starts with valid certificate → loads certificate successfully
- Test: Agent Runtime requests metadata → receives metadata WITHOUT identity tokens
- Test: Agent Runtime calls tool via Communication Hub → tool executes successfully with certificate auth
- Test: Verify agent logs contain NO identity tokens (security check)
- Test: Revoke agent certificate → subsequent tool calls fail with 403 Forbidden
- Test: Certificate renewal before expiration → new certificate issued and used automatically
- At least ONE test hits real backend (no mocked API responses) to verify authorization flow
- All tests pass consistently; labeled clearly as "Real Backend Integration" tests

---

## Phase 7: Deployment and Operations

### Task 7.1: Create Deployment Documentation
**Description:** Document deployment steps for certificate-based auth rollout

**Done when:**
- `deployment.md` created in change directory
- Documents environment variables: `AGENT_CERT_PATH`, `AGENT_KEY_PATH`, `CA_CERT_PATH`, `CONTROL_CENTER_URL`
- Documents Control Center CA initialization steps
- Documents agent instance certificate provisioning steps
- Documents migration steps: run `alembic upgrade head` before deploying new code
- Documents rollback procedure if deployment fails
- Documents how to verify deployment success (check CA certificate, issue test certificate, validate test certificate)

### Task 7.2: Create Operations Documentation
**Description:** Document operational procedures for certificate management

**Done when:**
- `operations.md` created in change directory
- Documents certificate monitoring: check expiration dates, watch renewal failures
- Documents certificate revocation procedure for compromised instances
- Documents token refresh failure alerts and resolution steps
- Documents audit log retention policy (90 days for compliance)
- Documents how to investigate authorization failures using audit logs
- Documents troubleshooting guide for common issues (expired CA cert, invalid certificate, token refresh failures)

---

## Implementation Notes

- Each phase can be implemented and tested independently
- Database changes (Phase 1) must be completed first (all other phases depend on schema)
- Certificate Authority (Phase 2) must be complete before Agent Runtime (Phase 4) can use certificates
- Token Refresh Service (Phase 3) can be developed in parallel with Certificate Authority
- Communication Hub integration (Phase 5) requires both Certificate Authority and Token Refresh Service
- Testing (Phase 6) should be incremental after each phase completes
- Deployment and Operations docs (Phase 7) should be drafted early and updated as implementation progresses

**Estimated Timeline:**
- Phase 1: 1-2 days (database models and migrations)
- Phase 2: 3-4 days (CA implementation and certificate lifecycle)
- Phase 3: 2-3 days (token refresh logic with OAuth integration)
- Phase 4: 2-3 days (agent runtime certificate support)
- Phase 5: 2-3 days (communication hub authorization integration)
- Phase 6: 3-4 days (comprehensive testing at all layers)
- Phase 7: 1 day (documentation finalization)

**Total: ~2-3 weeks** of development effort for a single developer working full-time
