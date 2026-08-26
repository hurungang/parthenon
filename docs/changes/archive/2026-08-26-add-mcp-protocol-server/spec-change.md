# Spec Change: MCP Protocol Server

This delta extends the capability delivered in `docs/changes/archive/2026-07-31-api-key-mcp-hub/` (API key MCP hub access), which introduced API-key authentication but left external access as a REST-only `/mcp/tools/load_skills` endpoint that does not speak the Model Context Protocol.

## Affected Spec Areas

- `docs/master/product/features/communication-hub.md` — External MCP access changes from REST-only skill discovery to a full MCP protocol server.
- `docs/master/product/features/mcp-hub.md` — MCP Hub tools become reachable by external MCP clients over the standard MCP protocol.
- `docs/master/product/features/api-key-management.md` — API keys now grant MCP protocol access, not only REST skill discovery.
- `docs/master/product/features/agent-runtime-security.md` — Security model note for MCP protocol sessions (token isolation, permission inheritance).

## New Capabilities

- **MCP Protocol Server (Communication Hub)** — The Communication Hub exposes a standard MCP protocol server that external clients can connect to with an existing API key. Clients can complete an MCP handshake (initialize), list permitted tools (tools/list), and invoke them (tools/call).

- **Unified Tool Exposure Over MCP** — System tools (including `load_skills`) and MCP tools proxied from registered MCP servers are both exposed through the single MCP protocol interface, so external clients see one coherent tool surface governed by the same permission resolution used internally.

- **API Key Expiration** — API keys carry an optional `expires_at` timestamp. A key with no timestamp never expires; a key whose timestamp has passed is rejected at authentication with a clear error. The API key management UI lets administrators set or omit the expiration when creating a key and shows the expiration in the key list.

## Modified Capabilities

- **Communication Hub External MCP Access** — Before: external agents authenticated by API key could call only the REST `/mcp/tools/load_skills` endpoint for skill discovery; the hub did not speak the MCP protocol. After: the hub also exposes a full MCP protocol server (initialize / tools/list / tools/call) authenticated by the same API keys. The existing REST endpoint is retained for backward compatibility.

- **API Key Authentication Scope** — Before: API keys authenticated only the REST skill-discovery endpoint and were valid until manually revoked. After: the same API keys authenticate a full MCP protocol session (resolving the bound agent identity, role, and permitted tools), and each key may optionally carry an expiration timestamp; expired keys are rejected at authentication with a clear error.

- **MCP Hub Tool Proxy Reach** — Before: proxied MCP server tools were reachable only by internal Agent Runtime tool calls. After: those same proxied tools are reachable by external MCP clients through the protocol interface, subject to identical role-based permission resolution.

## Removed Capabilities

_None._ This change is purely additive. No existing capabilities are removed or deprecated.

## Spec Update Instructions

- Update `docs/master/product/features/communication-hub.md`:
  - Change the external MCP access description from "REST `/mcp/tools/load_skills`" to "full MCP protocol server (initialize / tools/list / tools/call)".
  - Add the MCP protocol server as a Key Concept alongside the existing `load_skills` system tool and API key authentication.
  - Add acceptance criteria for MCP handshake, tool listing, and tool invocation by external clients.
  - Note that the REST endpoint is retained for backward compatibility and that internal mTLS is unchanged.

- Update `docs/master/product/features/mcp-hub.md`:
  - Note that registered MCP server tools are now reachable by external MCP clients over the standard protocol, in addition to internal Agent Runtime calls.

- Update `docs/master/product/features/api-key-management.md`:
  - Update the overview and "What It Does" to state that API keys authenticate full MCP protocol sessions, not only REST skill discovery.
  - Add the optional `expires_at` field: keys may carry an expiration timestamp (or none for non-expiring keys), and expired keys are rejected at authentication.

- Update `docs/master/product/features/agent-runtime-security.md`:
  - Add an MCP protocol session note: external sessions inherit role-based permissions, keep identity tokens inside the protected boundary, and are authenticated by the existing API keys.
