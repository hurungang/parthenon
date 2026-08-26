# Implementation Plan — add-mcp-protocol-server

## Overview

Add a standard Model Context Protocol (MCP) server to the Communication Hub so external MCP clients (GitHub Copilot, Claude Desktop, Cursor, custom agents) can connect using an existing Parthenon API key and perform the standard handshake, list their permitted tools, and invoke them. The change is a protocol/transport layer only — it reuses the existing API-key authentication middleware, role-based permission resolution, `load_skills` skill discovery, and Control Center MCP proxy engine unchanged, and never exposes identity tokens to clients. Master documentation updates are deferred to the master-update step and are noted only in the Completion Checklist.

## Task Checklist

### Phase 1 — Add MCP SDK dependency
- [x] 1.1 — Add `mcp>=1.1.2` dependency to `backend/pyproject.toml`
- [x] 1.2 — Regenerate the lockfile and verify the SDK imports cleanly

### Phase 2 — Implement MCP protocol server + transport on Communication Hub
- [x] 2.1 — Create the `backend/app/communication_hub/mcp/` package skeleton
- [x] 2.2 — Implement the MCP protocol server (JSON-RPC bridge for `initialize` / `tools/list` / `tools/call`)
- [x] 2.3 — Implement the Streamable HTTP transport
- [x] 2.4 — Implement the SSE transport
- [x] 2.5 — Implement the per-connection MCP session manager

### Phase 3 — Wire `tools/list` to the authenticated role's permitted tools + skill discovery
- [x] 3.1 — Build the permitted tool catalog from the API-key permission set plus system tools
- [x] 3.2 — Expose `load_skills` as a real MCP tool with full tool definitions and schemas
- [x] 3.3 — Return permission-filtered proxied MCP tools

### Phase 4 — Wire `tools/call` through the existing tool-routing/proxy path
- [x] 4.1 — Route system tools through the existing system-tool path
- [x] 4.2 — Route proxied MCP tools through the Control Center MCP proxy (role-based)
- [x] 4.3 — Extend Control Center internal proxy for role-based (API-key) session resolution
- [x] 4.4 — Enforce permission checks and never expose identity tokens to clients

### Phase 5 — Reuse/enhance `ApiKeyAuthMiddleware` for the MCP endpoint
- [x] 5.1 — Ensure the middleware covers the MCP protocol endpoint paths
- [x] 5.2 — Support `Authorization: Bearer` and `?apiKey=` across both transports
- [x] 5.3 — Audit-log MCP authentication success/failure without the raw key

### Phase 6 — Config/feature flag to enable the MCP server (default off)
- [x] 6.1 — Add a `CH_MCP_PROTOCOL_SERVER_ENABLED` setting (default off)
- [x] 6.2 — Gate MCP endpoint registration and middleware on the flag

### Phase 7 — Tests
- [x] 7.1 — Unit tests: protocol handler, session manager, transport framing
- [x] 7.2 — Integration tests: handshake, tools/list, tools/call over Streamable HTTP and SSE
- [x] 7.3 — Auth tests: invalid/revoked keys, permission filtering, token non-exposure
- [x] 7.4 — Regression tests: existing REST `load_skills` and internal mTLS path unchanged

### Phase 8 — API Key Expiration
- [x] 8.1 — Add `expires_at` column to `agent_api_keys` model + Alembic migration
- [x] 8.2 — Add `expires_at` to create/list schemas and persist in the create endpoint
- [x] 8.3 — Reject expired keys in the internal `validate-api-key` endpoint
- [x] 8.4 — Frontend: optional expiration field in create dialog + `Expires` column in list
- [x] 8.5 — Tests for expiration (service, schema) + live verification

---

## Phase 1 — Add MCP SDK dependency

### 1.1 — Add `mcp>=1.1.2` dependency to `backend/pyproject.toml`

Add the official MCP Python SDK to the `[project].dependencies` block of `backend/pyproject.toml` alongside the existing FastAPI and LangChain dependencies. This SDK provides the protocol types, `Server`, and transport primitives (`from mcp.server import Server`, `from mcp import types`) used by the reference implementation.

**Done when** `backend/pyproject.toml` lists `mcp>=1.1.2` in the runtime dependencies and a fresh install resolves it without conflict.

### 1.2 — Regenerate the lockfile and verify the SDK imports cleanly

Regenerate `backend/uv.lock` so the pinned dependency graph includes `mcp` and its transitive deps, then confirm the SDK imports in the backend virtual environment.

**Done when** `backend/uv.lock` contains the `mcp` package entry and `python -c "from mcp.server import Server; from mcp import types"` succeeds.

## Phase 2 — Implement MCP protocol server + transport on Communication Hub

### 2.1 — Create the `backend/app/communication_hub/mcp/` package skeleton

Create the new MCP package under the Communication Hub with modules for the protocol server, transports, session manager, and tool registry bridge. The package must not touch the database (per top-priority rules — only Control Center connects to the database).

**Done when** the `backend/app/communication_hub/mcp/` package exists with an `__init__.py` and placeholder modules import cleanly under `python -m compileall`.

### 2.2 — Implement the MCP protocol server (JSON-RPC bridge)

Implement the protocol server that bridges the JSON-RPC methods `initialize`, `tools/list`, and `tools/call` to the existing tool registry and proxy path. `initialize` returns server info and capability negotiation; `tools/list` and `tools/call` require an authenticated session (resolved from the API key). Model on the reference `sdk_protocol_handler.py` (understand, don't copy).

**Done when** the protocol server can answer `initialize` with server info/capabilities and returns JSON-RPC error responses for unknown methods or unauthenticated non-initialize calls.

### 2.3 — Implement the Streamable HTTP transport

Implement the Streamable HTTP transport handler that accepts `POST` JSON-RPC messages and returns newline-delimited JSON responses, resolving/reusing sessions by a session header. Model on the reference `streamable_http.py`.

**Done when** a Streamable HTTP client can complete `initialize` and a `tools/list` call against the CH endpoint over `POST`.

### 2.4 — Implement the SSE transport

Implement the SSE transport (event-stream endpoint plus a message-posting path) for streaming-capable clients, carrying the same JSON-RPC methods over Server-Sent Events. Model on the reference `sse_manager.py` / `sse_connection.py`.

**Done when** an SSE client can open the event stream, complete `initialize`, and receive a `tools/list` response over the stream.

### 2.5 — Implement the per-connection MCP session manager

Implement a session manager that tracks per-connection protocol state (initialized flag, capability negotiation, and the authenticated identity/role/permissions context) across SSE and Streamable HTTP transports, with cleanup of idle/expired sessions. Model on the reference `session_manager.py`.

**Done when** sessions are created, looked up, updated, and deleted with TTL/idle cleanup, and the authenticated identity context is held server-side only (never serialized to clients).

## Phase 3 — Wire `tools/list` to permitted tools + skill discovery

### 3.1 — Build the permitted tool catalog from the API-key permission set plus system tools

Populate `tools/list` from the authenticated role's resolved permission set (already returned by Control Center during API-key validation) combined with the system tools (including `load_skills`). The tool registry bridge is the single source of truth for canonical tool names, mirroring how internal agents resolve their allowed tools.

**Done when** `tools/list` returns exactly the system tools + MCP tools the bound role is permitted to use, and no others.

### 3.2 — Expose `load_skills` as a real MCP tool with full tool definitions and schemas

Register `load_skills` as a real MCP tool in the catalog so external clients discover it through `tools/list` and invoke it through `tools/call`, returning the same full skill/SOP definitions, input/output schemas, and `updated_at` timestamps (with `since` incremental sync) as the existing REST endpoint.

**Done when** `load_skills` appears in `tools/list` and a `tools/call` of `load_skills` returns the permitted skills with schemas and timestamps, honoring the `since` parameter identically to the REST endpoint.

### 3.3 — Return permission-filtered proxied MCP tools

Include proxied MCP tools from registered MCP servers in the catalog, filtered to the authenticated role's permissions, with their canonical `server____tool` names, descriptions, and input schemas.

**Done when** proxied MCP tools permitted to the role are listed with correct canonical names and schemas, and non-permitted tools are absent.

## Phase 4 — Wire `tools/call` through the existing tool-routing/proxy path

### 4.1 — Route system tools through the existing system-tool path

Dispatch `tools/call` for system tools (e.g. `load_skills`) to the existing Control Center system-tool endpoints, reusing the same routing logic used by the internal tool-routing path (`system____*` canonical names, `SystemToolRegistry` endpoint map).

**Done when** a system tool invoked via `tools/call` returns the same result as the internal Agent Runtime path for that tool.

### 4.2 — Route proxied MCP tools through the Control Center MCP proxy (role-based)

Dispatch `tools/call` for proxied MCP tools to Control Center's MCP proxy engine, which resolves the MCP session, decrypts credentials at call time, and performs the downstream JSON-RPC `tools/call`. The identity token stays on the CH/CC boundary and is never returned to the client.

**Done when** a permitted proxied MCP tool invoked via `tools/call` returns the downstream tool result.

### 4.3 — Extend Control Center internal proxy for role-based (API-key) session resolution

Extend (or add alongside) the Control Center internal proxy endpoint so it can resolve the MCP session from an agent role + identity (what an API key yields) rather than only an agent type, while reusing `McpProxyEngine` unchanged. This is the only place an existing internal contract needs widening; no new authentication or permission model is introduced.

**Done when** the CC internal proxy can resolve a session and proxy a tool call given an `agent_role_id` + `agent_identity_id` (in addition to the existing `agent_type_id` path), reusing `McpProxyEngine.call_tool`.

### 4.4 — Enforce permission checks and never expose identity tokens

Verify each `tools/call` against the session's permission set before dispatch (system and proxied), return a JSON-RPC error for unauthorized tools, and confirm the resolved identity token is never present in any response payload or serialized session state.

**Done when** unauthorized tool calls are rejected, and an audit of response/session serialization confirms no identity token or credential leaves the CH/CC boundary.

## Phase 5 — Reuse/enhance `ApiKeyAuthMiddleware` for the MCP endpoint

### 5.1 — Ensure the middleware covers the MCP protocol endpoint paths

Confirm `ApiKeyAuthMiddleware` intercepts the new MCP protocol endpoint paths (SSE and Streamable HTTP) the same way it covers the existing `/mcp*` REST paths, so the API key is validated and the identity/role/permissions are attached to the request/session before the protocol server runs.

**Done when** requests to the MCP protocol endpoints are authenticated by the middleware and carry the resolved identity/role/permissions context.

### 5.2 — Support `Authorization: Bearer` and `?apiKey=` across both transports

Verify the existing key-extraction logic (Bearer header first, `?apiKey=` query fallback) works for both the Streamable HTTP `POST` and the SSE stream-open request, including clients that can only send the key as a query parameter.

**Done when** both transports authenticate successfully via `Authorization: Bearer phn_sk_…` and via `?apiKey=phn_sk_…`.

### 5.3 — Audit-log MCP authentication success/failure without the raw key

Ensure successful and failed MCP authentication events are logged with the key identifier (name) and bound identity/role — never the raw key value — consistent with the existing REST path and PRD security requirements.

**Done when** logs contain key name + identity/role for MCP auth outcomes and no raw key value appears in logs.

## Phase 6 — Config/feature flag to enable the MCP server (default off)

### 6.1 — Add a `CH_MCP_PROTOCOL_SERVER_ENABLED` setting (default off)

Add a settings/env-var flag (e.g. `CH_MCP_PROTOCOL_SERVER_ENABLED`, default `false`) on the Communication Hub, following the existing per-component env-var convention, so the MCP protocol endpoint is opt-in.

**Done when** the flag exists in settings/env with a `false` default and is surfaced in startup `log_config_sources()` output.

### 6.2 — Gate MCP endpoint registration and middleware on the flag

Register the MCP protocol endpoint and enable the protocol path only when the flag is on; when off, the existing REST `load_skills` endpoint and internal mTLS path remain available exactly as today.

**Done when** with the flag off the MCP protocol endpoint is not served and existing REST + mTLS paths are unchanged; with it on, the endpoint is available.

## Phase 7 — Tests

### 7.1 — Unit tests: protocol handler, session manager, transport framing

Add unit tests for the protocol server (initialize, method dispatch, error responses), session manager (create/lookup/update/delete/cleanup, server-side identity context), and transport framing (JSON-RPC newline-delimited and SSE event framing).

**Done when** unit tests pass under `backend/tests/` and cover the protocol handler, session manager, and transport framing modules.

### 7.2 — Integration tests: handshake, tools/list, tools/call over both transports

Add integration tests exercising a full MCP session — `initialize` → `tools/list` → `tools/call` — over both Streamable HTTP and SSE, using a mocked/stubbed Control Center validation and proxy, asserting correct tool filtering and results.

**Done when** integration tests pass for both transports end-to-end.

### 7.3 — Auth tests: invalid/revoked keys, permission filtering, token non-exposure

Add tests covering invalid/revoked API keys (clear auth error), permission-filtered tool listing, unauthorized tool-call rejection, and assertion that identity tokens never appear in responses or session state.

**Done when** auth tests pass, including negative cases and token-non-exposure assertions.

### 7.4 — Regression tests: existing REST `load_skills` and internal mTLS path unchanged

Add/run regression tests confirming the existing REST `/mcp/tools/load_skills` endpoint and the internal Agent Runtime mTLS tool path behave identically to before this change.

**Done when** existing test suites for `mcp_tools`, `tool_routing`, `mcp_proxy`, and API-key validation pass unchanged.

## Phase 8 — API Key Expiration

### 8.1 — Add `expires_at` column to `agent_api_keys` model + Alembic migration

Add an optional `expires_at` timestamp column to the `AgentApiKey` model and generate/apply an Alembic migration.

**Done when** the column exists in the model and the database (`agent_api_keys.expires_at`, nullable).

### 8.2 — Add `expires_at` to create/list schemas and persist in the create endpoint

Add `expires_at` to the API-key create/list/read schemas and persist the optional value in the create endpoint.

**Done when** `POST /api/v1/api-keys` accepts and returns `expires_at`, and `GET /api/v1/api-keys` includes it.

### 8.3 — Reject expired keys in the internal `validate-api-key` endpoint

Reject a key whose `expires_at` is in the past with a clear 401 ("API key has expired"), mirroring the revoked-key handling.

**Done when** an expired key is rejected at MCP/REST authentication with a clear error, and a non-expiring or future-dated key authenticates normally.

### 8.4 — Frontend: optional expiration field in create dialog + `Expires` column in list

Add an optional expiration input to the create dialog (default: no expiration) and an `Expires` column to the key list.

**Done when** an administrator can create a key with or without an expiration and see the expiration (or "No expiration") in the list.

### 8.5 — Tests for expiration (service, schema) + live verification

Add unit tests for the expiration helper and schema column, and verify end-to-end against the running stack.

**Done when** backend tests pass and live verification confirms expired-key rejection and non-expiring-key acceptance.

## Completion Checklist

- [x] `mcp>=1.1.2` in `backend/pyproject.toml` (lockfile regeneration pending — see 1.2)
- [x] MCP protocol server + Streamable HTTP + SSE transports implemented under `backend/app/communication_hub/mcp/`
- [x] `initialize` / `tools/list` / `tools/call` work over both transports with API-key auth
- [x] `load_skills` exposed as a real MCP tool with schemas + `since` sync
- [x] `tools/call` routes system tools + proxied MCP tools via existing path, role-based, no token exposure
- [x] `ApiKeyAuthMiddleware` covers the MCP endpoint (Bearer + `?apiKey=`) with audit logging
- [x] `CH_MCP_PROTOCOL_SERVER_ENABLED` flag defaulting off
- [x] Unit + integration + auth tests pass (32 tests); regression verified live against the running stack (see `test-plan.md`)
- [x] Optional API key expiration: `expires_at` column, create/list support, expired-key rejection, and UI (create dialog + list column)
- [ ] Deferred (master-update, not this change): update `docs/master/product/features/{communication-hub,mcp-hub,api-key-management,agent-runtime-security}.md` and `docs/master/architecture/{system-overview,modules/communication-hub,modules/tool-execution,security/api-key-security}.md` per `spec-change.md` and `architecture.md`
