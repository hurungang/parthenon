# Module: agent-runtime — Tech Spec

## Overview

The Agent Runtime is the execution-time security layer that runs alongside each agent instance. It operates under mutual TLS (mTLS): on startup, it loads an X.509 certificate issued by the Control Center CA, configures all outbound HTTP clients to present that certificate on every request, and monitors the certificate for expiration. When the certificate approaches its 80% lifetime threshold (approximately 19 hours into a 24-hour cert), a background task requests a renewal from the Control Center and performs an atomic in-memory swap with no downtime.

Metadata requests to the Control Center no longer return identity tokens. The runtime receives only non-sensitive configuration (agent type, SOPs, skills, model config, system instruction). All identity tokens are resolved on demand by the Control Center at the point of each tool call, proxied through the Communication Hub.

**Dependency on Control Center:** `POST /certificates/issue` for issuance, `GET /certificates/ca` for CA verification, and mutual TLS on all subsequent requests.

---

## Key Components

| Component | Description |
|-----------|-------------|
| `CertificateManager` | Startup: loads certificate and private key from files (`AGENT_CERT_PATH`, `AGENT_KEY_PATH`, `AGENT_CA_CERT_PATH` env vars); validates cert signature against CA public cert; configures all HTTP clients for mTLS. Background task (`run_renewal_task`): polls every hour; triggers renewal at 80% lifetime; atomically swaps to the new cert; shuts down gracefully if cert expires without renewal |
| `MetadataClient` | Calls `GET /agent/metadata` on the Control Center using the mTLS-configured HTTP client; asserts that the response does NOT contain `identity_token` or `access_token` fields via `verify_no_identity_tokens`; returns validated agent configuration |

---

## Security Properties

- Certificate and private key are read from the file system at startup only — paths are set by the orchestrator (Docker, Kubernetes) and never hardcoded
- `verify_no_identity_tokens` is a mandatory security assertion: if the Control Center response ever inadvertently includes a token, the runtime raises an error and does not proceed
- Certificate renewal is atomic: the old cert remains active until the new cert is fully validated; no window of uncertified operation
- Graceful shutdown on cert expiry prevents the agent from operating without a valid identity

## Tool Naming and Uniform Routing

All tool calls from the Agent Runtime use the unified `server____tool_name` convention (four underscores). The executor forwards **all** tool calls to the Communication Hub without distinction between system tools and MCP server tools — no branching logic by tool type exists in executor code.

The Communication Hub's Name Resolver routes calls:
- `system____*` → internal system tool handlers (e.g., Notification Service for `system____send_notification`)
- `<server>____*` → MCP Hub for proxying to the registered MCP server

**`tool_naming` module** (`backend/app/services/agents/tool_naming.py`):

| Symbol | Type | Description |
|--------|------|-------------|
| `parse_tool_name(name)` | function | Splits `server____tool` into `(server, tool)` tuple; handles legacy bare names for backward compat |
| `build_tool_name(server, tool)` | function | Constructs canonical `server____tool` string |
| `is_system_tool(name)` | function | Returns `True` if server segment equals `"system"` |

**Reserved names**: `system` is the reserved server prefix for built-in platform tools. MCP server names must not contain `____`.

## Explicit Result Saving

The Agent Runtime does **not** automatically call `save_result` at agent completion. Results are persisted only when the agent explicitly calls `system____save_result` as instructed by its SOP. This ensures result records are intentional and traceable to a specific SOP step.

**`ResultStore`** (`backend/app/services/results/store.py`): Single persistence point for result records. Called by the `system____save_result` tool handler and by the AR result-submit path.

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `AGENT_CERT_PATH` | File path to agent instance certificate PEM |
| `AGENT_KEY_PATH` | File path to agent instance private key PEM |
| `AGENT_CA_CERT_PATH` | File path to Control Center CA public certificate PEM |

---

## Code Reference Map

### Certificate Manager (`backend/app/agent_runtime/certificate_manager.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `CertificateManager` | class | Manages agent instance certificate lifecycle: load, validate, configure mTLS, monitor expiration, renew | `backend/app/agent_runtime/certificate_manager.py` |
| `load_certificate` | method | Load certificate and private key PEM files from paths in env vars on startup | `backend/app/agent_runtime/certificate_manager.py` |
| `validate_certificate_against_ca` | method | Verify certificate signature against the CA public cert; raise on failure | `backend/app/agent_runtime/certificate_manager.py` |
| `configure_mtls_client` | method | Configure the shared HTTP client to present the agent certificate on every outbound TLS handshake | `backend/app/agent_runtime/certificate_manager.py` |
| `check_certificate_expiration` | method | One-shot check: return `True` if certificate is within 20% of expiry window | `backend/app/agent_runtime/certificate_manager.py` |
| `renew_certificate` | method | Call Control Center `POST /certificates/issue`; receive new cert and key | `backend/app/agent_runtime/certificate_manager.py` |
| `switch_certificate` | method | Atomically replace in-memory cert and key; reconfigure mTLS client; no connection interruption | `backend/app/agent_runtime/certificate_manager.py` |
| `run_renewal_task` | method | Async background coroutine; polls `check_certificate_expiration()` every hour; calls `renew_certificate()` and `switch_certificate()` when approaching expiry | `backend/app/agent_runtime/certificate_manager.py` |

### Metadata Client (`backend/app/agent_runtime/metadata_client.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `MetadataClient` | class | Fetches agent configuration from Control Center using mTLS-configured HTTP client; enforces zero-token response contract | `backend/app/agent_runtime/metadata_client.py` |
| `request_metadata` | method | Call `GET /agent/metadata` with client certificate; return parsed agent configuration dict | `backend/app/agent_runtime/metadata_client.py` |
| `verify_no_identity_tokens` | function | Assert that response body contains no `identity_token` or `access_token` keys; raise `SecurityViolationError` if found | `backend/app/agent_runtime/metadata_client.py` |
