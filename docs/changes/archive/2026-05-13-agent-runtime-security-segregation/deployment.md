# Deployment Guide: Agent Runtime Security Segregation

**Feature:** Agent Runtime Security Segregation  
**Date:** 2026-05-13  
**Status:** Ready for deployment

---

## Prerequisites

1. **Migration applied** — MUST run before deploying new code:
   ```bash
   cd backend
   alembic upgrade head
   ```
   Verify: `alembic current` shows the latest security segregation migration ID.

2. **`cryptography` package** — already in `pyproject.toml` (`cryptography>=43.0.0`).

3. **`CREDENTIAL_VAULT_KEY`** — must be set (existing env var); used to encrypt the CA private key.

---

## Environment Variables

### Control Center (backend)

| Variable | Required | Description |
|----------|----------|-------------|
| `CREDENTIAL_VAULT_KEY` | Yes (existing) | AES-256 key for encrypting CA private key and identity tokens |
| `CA_PRIVATE_KEY_ENCRYPTED` | Optional | Pre-encrypted CA private key (if persisting across restarts) |

### Agent Runtime

| Variable | Required | Description |
|----------|----------|-------------|
| `AGENT_CERT_PATH` | Yes | Filesystem path to agent instance certificate PEM file |
| `AGENT_KEY_PATH` | Yes | Filesystem path to agent instance private key PEM file |
| `CA_CERT_PATH` | Yes | Filesystem path to CA public certificate PEM file |
| `CONTROL_CENTER_URL` | Yes | Base URL of Control Center API (e.g. `http://control-center:8000`) |

### Communication Hub

| Variable | Required | Description |
|----------|----------|-------------|
| `CONTROL_CENTER_URL` | Yes | Base URL of Control Center API for internal validation calls |

---

## Deployment Steps

### Step 1: Apply Database Migration

```powershell
cd backend
# Ensure virtual environment activated
.\.venv\Scripts\Activate.ps1
alembic upgrade head
alembic current   # Verify new revision is shown
```

**Expected tables created:**
- `agent_instance_certificates`
- `certificate_revocation_entries`
- `token_refresh_logs`
- `certificate_validation_logs`

**Expected columns added to `agent_identities`:**
- `encrypted_refresh_token`
- `last_token_refresh_at`
- `token_status`

### Step 2: Deploy Control Center

Deploy the updated backend. On startup, the Control Center will:
1. Run existing bootstrap (roles, skills)
2. **Initialize Certificate Authority** — generates 4096-bit RSA CA certificate
3. Log: `Certificate Authority initialized — serial=... expires=...`

Verify CA initialization:
```bash
curl http://localhost:8000/api/v1/certificates/ca
# Should return: {"certificate_pem": "-----BEGIN CERTIFICATE-----...", ...}
```

### Step 3: Provision Agent Instance Certificates

For each agent instance being deployed:

```bash
# Get admin JWT token first
export ADMIN_TOKEN="..."

# Issue certificate for agent type
curl -X POST http://localhost:8000/api/v1/certificates/issue \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type_id": "<agent-type-uuid>",
    "instance_id": "<hostname-or-job-id>"
  }' | jq '{
    serial_number: .serial_number,
    expires_at: .expires_at,
    cert_file: .certificate_pem,
    key_file: .private_key_pem
  }'
```

Save the returned `certificate_pem` and `private_key_pem` to files:
```bash
# Save certificate
echo "$CERT_PEM" > /etc/agent/certs/agent.crt

# Save private key (secure permissions)
echo "$KEY_PEM" > /etc/agent/certs/agent.key
chmod 600 /etc/agent/certs/agent.key
```

Download CA certificate:
```bash
curl http://localhost:8000/api/v1/certificates/ca | jq -r .certificate_pem > /etc/agent/certs/ca.crt
```

### Step 4: Configure Agent Runtime Environment

```bash
export AGENT_CERT_PATH=/etc/agent/certs/agent.crt
export AGENT_KEY_PATH=/etc/agent/certs/agent.key
export CA_CERT_PATH=/etc/agent/certs/ca.crt
export CONTROL_CENTER_URL=http://control-center:8000
```

### Step 5: Configure Communication Hub

```bash
export CONTROL_CENTER_URL=http://control-center:8000
```

In nginx/reverse-proxy, configure certificate forwarding:
```nginx
# Forward client certificate to Communication Hub
proxy_set_header X-Client-Certificate $ssl_client_cert;
```

### Step 6: Verify Deployment

Test certificate validation:
```bash
# Issue a test certificate
TEST_CERT=$(curl -s -X POST http://localhost:8000/api/v1/certificates/issue \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"agent_type_id": "<uuid>", "instance_id": "smoke-test"}')

# Validate it
curl -X POST http://localhost:8000/api/v1/internal/certificates/validate \
  -d "{\"certificate_pem\": $(echo $TEST_CERT | jq .certificate_pem)}"
# Expected: {"valid": true, ...}

# Revoke the smoke test certificate
curl -X POST http://localhost:8000/api/v1/certificates/revoke \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "{\"serial_number\": $(echo $TEST_CERT | jq .serial_number), \"reason\": \"smoke-test cleanup\"}"
```

---

## Rollback Procedure

If deployment fails:

1. **Revert code** to previous version
2. **Do NOT rollback the migration** — new columns are nullable; old code works without them
3. Verify the old API endpoints are responding
4. The new tables (`agent_instance_certificates`, etc.) can remain; they cause no harm

---

## Feature Flags / Gradual Rollout

The certificate-based auth is additive:
- Existing JWT-authenticated endpoints continue to work unchanged
- New `/certificates/*` and `/internal/*` endpoints are additive
- `CertificateAuthorizationMiddleware` only activates for `/tools/*` paths
- Agent Runtime certificate loading is controlled by presence of `AGENT_CERT_PATH` env var
