# Test Plan — add-mcp-protocol-server

## Test Strategy

This is a backend-only, protocol/transport change (`has_ui_changes: false`, `has_db_changes: false`). Testing spans four layers, mirroring the existing test pyramid in `backend/tests/` and `e2e/tests/`:

- **Unit** — Isolate the new MCP protocol components (protocol server, session manager, tool registry bridge, both transports) with mocked Control Center (CC) and mocked MCP proxy. Verify JSON-RPC method dispatch, canonical tool naming, permission filtering, and session state transitions in isolation.
- **Integration** — Exercise the full request path through the Communication Hub (CH) FastAPI app with a mocked CC (via mTLS-certificate dependency override), covering the real middleware, router, transport, and bridge wiring end-to-end. Verify handshake → list → call against a mock CC proxy.
- **E2E** — Drive the CH over real HTTP using an MCP client/library (or an MCP-protocol harness) with a real API key against a running stack; verify the standard `initialize` / `tools/list` / `tools/call` sequence and cross-check REST `load_skills` parity. At least one E2E variant hits the real backend (no `page.route`-style mocking) to catch middleware/transport regressions.
- **Manual** — Confirm real third-party clients (Copilot, Claude Desktop, Cursor) can connect, because client-specific transport/negotiation quirks are not fully reproducible in automated harnesses.

Because there is no database schema change, the DB-specific test-plan rules (constraint verification via `information_schema`, migration pre-checks) do **not** apply. No migration gate is required before test execution.

## Coverage Areas

### 1. MCP Protocol Handshake & Negotiation (critical)
- Verify `initialize` completes the standard MCP handshake and returns server capabilities/version per the negotiated protocol version.
- Verify capability negotiation is honored (declared capabilities constrain what the server advertises and accepts).
- Verify methods other than `initialize` are rejected when no session is initialized (protocol ordering enforced).
- **Why critical:** A broken handshake is the first thing every MCP client does; failure here blocks all downstream usage.

### 2. `tools/list` Permission Filtering (critical)
- Verify the tool catalog returned by `tools/list` is filtered to exactly the tools permitted by the API key's bound role — no more, no less.
- Verify both system tools (e.g., `load_skills`) and proxied MCP tools (registered MCP servers under the slug namespace) appear in the list when permitted.
- Verify a role with no MCP-tool grants sees only the system tools it is permitted (and none of the unpermitted proxied tools).
- **Why critical:** `tools/list` is the client's visibility boundary — leaking unpermitted tool names is an information-disclosure defect even if `tools/call` blocks them.

### 3. `tools/call` Routing & Authorization (critical)
- Verify a permitted system tool call routes to the CC system-tool endpoint and returns the result.
- Verify a permitted proxied MCP tool call routes to the CC MCP proxy and returns the external server's result.
- Verify canonical tool-name mapping (bare system-tool names vs. `slug____tool` namespaced proxied names) is resolved correctly in both directions.
- Verify a call to a tool not in the permitted set is rejected with an authorization error.
- **Why critical:** Correct routing proves reuse of the existing proxy engine; authorization enforcement proves the security posture is preserved, not weakened.

### 4. API-key Authentication (critical)
- Verify valid, active API keys authenticate and populate the session's bound identity, role, permissions, and skills.
- Verify invalid / unknown / expired / revoked keys receive a clear authentication error (not a 500).
- Verify keys supplied via both `Authorization: Bearer` and `?apiKey=` query parameter are accepted; verify missing key yields a clear error.
- Verify the raw key is hashed (SHA-256) before transmission to CC and is never logged or echoed.
- **Why critical:** This is the sole authentication mechanism for the new surface; failure modes must be explicit and unambiguous for clients.

### 4.1 API Key Expiration
- Verify an administrator can create a key with an optional `expires_at` (or none for a non-expiring key).
- Verify a key with a past `expires_at` is rejected at authentication with a clear error (not a 500).
- Verify a key with a future `expires_at` or no `expires_at` authenticates normally.
- Verify the create flow surfaces the optional expiration field and the key list shows the expiration date (or "No expiration").
- **Why critical:** expiration is time-based access control; a missed check leaves access open past the intended window.

### 5. Identity-token & Secret Non-exposure (critical, top-priority rule)
- Verify the resolved identity token is held server-side only and never serialized into any client-visible response (initialize result, `tools/list`, `tools/call` result, session objects, or error bodies).
- Verify no database credentials, credential-vault material, or decrypted MCP-server credentials are exposed to the external client at any point in the flow.
- Verify sensitive tool arguments are sanitized/redacted in logs and in any echoed error output.
- **Why critical:** This is an explicit top-priority architecture rule ("agents can not get any sensitive data like identity tokens") and a PRD security acceptance criterion.

### 6. `load_skills` via MCP Protocol (critical)
- Verify `load_skills` is available through the MCP protocol as a system tool and returns full skill/SOP definitions with input/output schemas and `updated_at`.
- Verify results are filtered to the permitted set and the `since` incremental-sync parameter returns only skills updated after the given timestamp, matching REST behavior.
- **Why critical:** Skill discovery is the entry point for external clients to discover what they can invoke.

### 7. Regression of Existing Paths (critical)
- Verify the existing internal mTLS certificate path for Agent Runtime (`/tools/*`, `/internal/*`) is unchanged.
- Verify the existing REST `GET`/`POST` `/mcp/tools/load_skills` endpoint continues to work for current consumers.
- Verify API-key management, role management, and MCP-server management Web UI flows are unaffected (no frontend change; no regressions in existing E2E suites).
- **Why critical:** The PRD explicitly scopes this as additive; regressions violate the "zero regression" business goal.

### 8. Security & Audit Logging
- Verify successful and failed MCP authentication events are logged with the key identifier (name) and bound identity — never the raw key value.
- Verify tool invocations via the MCP protocol are auditable/traceable, consistent with existing tool-call logging.
- **Why critical:** Security/Compliance Officer persona requires inherited audit posture.

## Critical Scenarios

- **WHEN** a client sends `initialize` with a supported protocol version **THEN** the server returns a successful result with the negotiated server capabilities and version.
- **WHEN** a client sends `tools/list` before `initialize` **THEN** the server rejects the request (protocol ordering error).
- **WHEN** a client completes `initialize` with a valid API key and requests `tools/list` **THEN** the response contains exactly the permitted system tools and proxied MCP tools and nothing else.
- **WHEN** a client invokes a permitted system tool via `tools/call` **THEN** the call routes to the CC system-tool endpoint and returns the tool result.
- **WHEN** a client invokes a permitted proxied MCP tool via `tools/call` **THEN** the call routes through the CC MCP proxy to the external server and returns its result.
- **WHEN** a client invokes a tool outside its permitted set **THEN** the server returns an authorization error and the tool is not executed.
- **WHEN** a client authenticates with a revoked or expired API key **THEN** the server returns a clear authentication error and no session is established.
- **WHEN** an administrator creates an API key with a past `expires_at` **THEN** the key is stored with that timestamp and is rejected at authentication with a clear "expired" error.
- **WHEN** an administrator creates an API key without an `expires_at` **THEN** the key is stored with `NULL` and authenticates indefinitely.
- **WHEN** the key list is displayed **THEN** each key shows its expiration date, or "No expiration" when unset.
- **WHEN** a client authenticates with a valid key **THEN** the resolved identity token and credentials remain server-side and appear nowhere in the response.
- **WHEN** a client calls `load_skills` with a `since` timestamp **THEN** only skills updated after that timestamp are returned.
- **WHEN** an existing Agent Runtime agent connects via its mTLS certificate **THEN** the certificate path behaves exactly as before this change.
- **WHEN** an existing consumer calls REST `GET /mcp/tools/load_skills` **THEN** the response is unchanged.

## Edge Cases & Risks

- **Session expiry / idle timeout** — Long-lived MCP sessions may exceed TTL; verify a stale session is cleaned up and that a re-initialize or new session recovers cleanly without leaking the previous identity context.
- **Missing API key** — Requests to `/mcp` without any key must fail with a clear 401, not a silent pass-through or 500.
- **Revoked key mid-session** — A key revoked after a session is established must cause subsequent `tools/call` to be rejected (fail-closed) rather than continuing to serve on the stale session.
- **Expired key mid-session** — A key that expires after a session is established must be rejected on subsequent requests (the middleware re-validates per request, so expiry is enforced fail-closed).
- **Timezone handling** — A naive or timezone-aware `expires_at` must compare correctly against the current UTC time.
- **Key with no bound identity/role** — A valid key that yields no resolvable agent role must produce a clear error, not an internal 500.
- **Tool not permitted** — Unauthorized `tools/call` must be rejected at authorization time, before any downstream routing.
- **External MCP server down / unreachable** — A proxied `tools/call` where the external server is offline must surface a clean, non-leaking error to the client (no internal credentials or stack traces).
- **Streaming transport disconnects** — Mid-stream SSE/Streamable-HTTP disconnects must not corrupt session state; session cleanup must reclaim resources.
- **Protocol version negotiation** — Unsupported protocol versions must be rejected or negotiated per spec, not assumed.
- **Malformed JSON-RPC** — Malformed or non-JSON-RPC payloads must return a proper JSON-RPC error, not crash the handler or leak tracebacks.
- **Cross-transport session reuse** — A session header replayed across requests must resolve the same session consistently; an unknown/invalid session header must be rejected.
- **Concurrent tool calls** — Parallel `tools/call` on one session must not corrupt the shared identity context (race safety).
- **Dual-transport consistency** — SSE and Streamable HTTP must expose identical method semantics and permission filtering (no drift between transports).
- **Risk: transport/negotiation quirks of real clients** — Some MCP clients behave differently around SSE vs. Streamable HTTP; mitigated by manual client testing in addition to automated harnesses.

## Acceptance Criteria Checklist

Maps to `prd.md` acceptance criteria.

- [ ] External client completes `initialize` handshake over the CH MCP endpoint using an existing API key. *(MCP Protocol Connection)*
- [ ] After handshake, client lists only its permitted tools — system tools and proxied MCP tools included. *(MCP Protocol Connection)*
- [ ] Client invokes a permitted tool and receives its result. *(MCP Protocol Connection)*
- [ ] Valid, active API keys authenticate; invalid, expired, and revoked keys receive a clear error. *(Authentication & Authorization)*
- [ ] Permission set is resolved from the key's bound identity and role, identically to internal agents. *(Authentication & Authorization)*
- [ ] Client sees and calls only role-permitted tools; unauthorized calls rejected. *(Authentication & Authorization)*
- [ ] Identity token is never returned to the client; only CH/CC hold it. *(Authentication & Authorization)*
- [ ] Administrator can create a key with an optional `expires_at`; omitting it yields a non-expiring key. *(API Key Expiration)*
- [ ] A key with a past `expires_at` is rejected at authentication with a clear error. *(API Key Expiration)*
- [ ] The key list shows each key's expiration date (or "No expiration"). *(API Key Expiration)*
- [ ] `load_skills` is available over the protocol and returns full definitions, schemas, and `updated_at`. *(Skill Discovery)*
- [ ] `since` incremental sync matches existing REST behavior. *(Skill Discovery)*
- [ ] Internal mTLS certificate path for Agent Runtime is unchanged. *(No Regression)*
- [ ] REST `GET`/`POST` `/mcp/tools/load_skills` continues to work. *(No Regression)*
- [ ] API-key, role, and MCP-server management UI flows are unaffected. *(No Regression)*
- [ ] Auth events logged with key identifier + bound identity, never the key value. *(Security & Audit)*
- [ ] MCP-protocol tool invocations are auditable/traceable. *(Security & Audit)*

## Test File References

Proposed test implementation files (paths under `backend/tests/` per `docs/config.yaml` `source.tests`):

| File | Layer | Covers |
|------|-------|--------|
| `backend/tests/unit/test_mcp_protocol_server.py` | Unit | `initialize`/`tools/list`/`tools/call` JSON-RPC dispatch, capability negotiation, protocol ordering |
| `backend/tests/unit/test_mcp_session_manager.py` | Unit | Session state transitions, TTL/idle cleanup, identity-context isolation |
| `backend/tests/unit/test_tool_registry_bridge.py` | Unit | Permission-filtered catalog build, canonical name mapping, system vs. proxy dispatch authorization |
| `backend/tests/unit/test_mcp_streamable_http.py` | Unit | `POST` JSON-RPC handling, session header resolution, newline-delimited responses |
| `backend/tests/unit/test_mcp_sse_transport.py` | Unit | Event-stream `endpoint` announcement + message-posting path |
| `backend/tests/communication_hub/api/internal/test_mcp_protocol_router.py` | Integration | Router wiring for `/mcp`, `/mcp/sse`, `/mcp/sse/messages` with mocked CC |
| `backend/tests/integration/test_mcp_protocol_server.py` | Integration | Full handshake → list → call through the CH app with mocked CC proxy (system + proxied tools) |
| `backend/tests/integration/test_mcp_api_key_auth.py` | Integration | Valid/invalid/expired/revoked key handling, missing key, bearer vs. query param, token non-exposure |
| `backend/tests/integration/test_mcp_load_skills.py` | Integration | `load_skills` over the protocol, permission filtering, `since` incremental sync, REST parity |
| `e2e/tests/mcp-protocol-server.spec.ts` | E2E | Real-HTTP MCP client sequence; at least one variant against the real backend (no mocks) |

API key expiration test files (added by the expiration refinement):

| File | Layer | Covers |
|------|-------|--------|
| `backend/tests/test_api_key_service.py` | Unit | `is_key_expired` (none/future/past/naive-datetime cases) |
| `backend/tests/integration/test_api_key_schema.py` | Integration | `expires_at` column presence + nullability |

### Implementation Status

Files implemented in this task (6 of 10 proposed; no live DB or Control Center required):

- `backend/tests/unit/test_mcp_protocol_server.py` — ✅ created
- `backend/tests/unit/test_mcp_session_manager.py` — ✅ created
- `backend/tests/unit/test_tool_registry_bridge.py` — ✅ created
- `backend/tests/unit/test_mcp_streamable_http.py` — ✅ created (named `test_mcp_streamable_http.py`)
- `backend/tests/unit/test_mcp_sse_transport.py` — ✅ created (named `test_mcp_sse_transport.py`)
- `backend/tests/integration/test_mcp_protocol_server.py` — ✅ created (CC transport stubbed via `_post_cc`)

Not implemented in this task (deferred — require a running CC/Postgres or a full stack, which is out of scope per the "no live services" constraint):

- `backend/tests/communication_hub/api/internal/test_mcp_protocol_router.py` — requires a running Control Center for the mTLS-certificate dependency override.
- `backend/tests/integration/test_mcp_api_key_auth.py` — API-key validation resolves against Control Center.
- `backend/tests/integration/test_mcp_load_skills.py` — REST `load_skills` parity requires a running Control Center.
- `e2e/tests/mcp-protocol-server.spec.ts` — E2E requires a running stack.
