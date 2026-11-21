# Module: mcp-demo-app — Tech Spec

> Part of the [technology documentation](../../README.md).

## Overview

The MCP Demo App is a standalone Python FastAPI service (`mcp-demo-app/`) that lives outside the main Parthenon codebase. It authenticates with the Keycloak `ai_agents` realm using the OAuth2 client credentials grant, registers itself with the Parthenon MCP Hub under the slug `demo`, and exposes ten MCP tools over a JSON-RPC 2.0 endpoint. On every tool invocation it validates the forwarded identity JWT against the appropriate Keycloak realm's JWKS and enforces per-identity `mcp_role`-based access control — proving the end-to-end dual-identity propagation pattern where both agent and user identities are forwarded by the Communication Hub.

The app runs in **two demo modes that coexist**:

1. **Identity propagation** — the three greeting tools (`helloWorld`, `helloAgent`, `helloUser`) exercise the agent/user JWT split unchanged.
2. **Airline booking scenario** — seven fictional booking tools (search flights, book ticket, generate payment link, check ticket status, check in passenger, select seat, cancel booking) implement a realistic multi-step business workflow over a deterministic, in-memory, seed-backed booking store. The scenario is designed to drive platform capabilities end to end: confirm-before-write approval on booking/cancellation, a scripted (optimized) check-in plan executed zero-LLM in Agent Runtime, and a second client surface through the agent-client demo app.

There are no database dependencies and no Parthenon schema changes. The only integration with the main codebase is a service entry in `docker-compose.yml`, calls to the existing Hub registration endpoints at startup, and ordinary admin/seeding configuration (skills, role grants, one conversational agent type, one scripted plan).

---

## Key Components

| Component | Responsibility |
|-----------|----------------|
| `AppSettings` | Reads all configuration from environment variables (Keycloak URL, realm, client credentials, Hub URL, app URL, slug, and optional user realm config). Single source of truth for runtime config. |
| `KeycloakClient` | Encapsulates all Keycloak HTTP interactions: client credentials token grant (with expiry-aware cache), and JWKS fetch (with 10-minute cache). Accepts an optional `realm_name` to support multiple realm instances. |
| `keycloak_client` | Module-level `KeycloakClient` singleton for the agent realm. Used for agent JWT validation and obtaining the app's own access token. |
| `user_keycloak_client` | Second module-level `KeycloakClient` singleton for the user realm. Maintains independent JWKS and token caches. Falls back to the agent realm when `KEYCLOAK_USER_REALM` is not configured (single-realm backward compatibility). |
| `verify_agent_jwt` | Validates a forwarded agent JWT against the agent realm's JWKS. Checks signature, expiry, and issuer. Returns decoded claims on success. |
| `verify_user_jwt` | Validates a forwarded user JWT against the user realm's JWKS. Follows the same pattern as `verify_agent_jwt` but uses `user_keycloak_client` and computes the expected issuer from `KEYCLOAK_USER_REALM` (falling back to `KEYCLOAK_REALM`). |
| `get_agent_identity` | FastAPI dependency that extracts and validates the `Authorization: Bearer` token from each request. |
| `get_user_identity` | FastAPI dependency that extracts and validates the user JWT from the `X-User-Identity: Bearer` header. |
| `hello_world_tool` / `hello_agent_tool` / `hello_user_tool` | Greeting tool handlers. `helloWorld` echoes the agent `sub` with no role gate; `helloAgent` requires `mcp_role == "demo_agent"`; `helloUser` requires `mcp_role == "demo_user"`. Access failures return a structured `access_denied` result. |
| `tool_registry` | In-memory mapping of all ten MCP tool name strings to their handler functions. |
| `TOOL_MANIFEST` | Static list of tool descriptors (name, description, input JSON schema) published via `tools/list`. |
| `BookingStore` | Seed-backed in-memory store for the airline scenario: flights, PNR-keyed bookings with passengers, seat map, payment links, booking-level status lifecycle, and seat availability. |
| `booking_store` | Module-level store singleton, rebuilt from deterministic seed data on every app startup. |
| `search_flights_tool` / `book_ticket_tool` / `generate_payment_link_tool` / `check_ticket_status_tool` / `check_in_passenger_tool` / `select_seat_tool` / `cancel_booking_tool` | The seven booking tool handlers. Booking tools receive the caller identity plus an `arguments` dict; greeting handlers keep the identity-only signature. |
| `BOOKING_TOOL_NAMES` | Set of the seven booking tool names — the MCP route uses it to decide whether to pass the `arguments` dict. |
| `register_with_hub` | Startup function that registers the demo app with the Parthenon Hub (`POST /api/v1/mcp/servers`) and triggers a tool sync (`POST .../sync`). Handles 409 idempotently; discovers all ten tools. |
| `mcp_router` | FastAPI `APIRouter` handling `POST /mcp`. Dispatches JSON-RPC method calls to `initialize`, `tools/list`, and `tools/call` handlers. For `tools/call`, determines whether to extract agent identity or user identity based on the tool name. |
| `health_router` | FastAPI `APIRouter` handling `GET /health`. Returns `{"status": "ok", "slug": "demo"}`. No auth required. |
| `create_app` | FastAPI application factory. Configures the lifespan handler (Keycloak token validation + Hub registration + booking-store seeding) and mounts routers. |
| `lifespan` | Async context manager. Validates Keycloak connectivity, seeds the booking store, and triggers Hub registration on startup; exits the process on failure. |

### Backend Pipeline Components (Communication Hub / Control Center / Frontend)

These are changes in the main Parthenon codebase that support the dual-identity propagation pattern end-to-end. The Communication Hub caches and forwards the user JWT alongside the agent JWT during tool calls. The Control Center proxy engine passes dual identities through to the MCP Demo App. The frontend WebSocket chat sends the user JWT as a query parameter for the Hub to cache.

| Component | Responsibility |
|-----------|----------------|
| `ToolCallRequest.user_jwt` | Field on the CH tool routing request model carrying the user identity JWT alongside the agent JWT. |
| `cache_user_jwt` / `get_user_jwt` | Stores/retrieves the user JWT by WebSocket session ID for dual-identity forwarding. |
| `McpProxyRequest.user_jwt` | Field on the CC internal proxy request carrying the user JWT to the MCP Hub proxy engine. |
| `McpProxyEngine.call_tool` | Accepts a `user_jwt` parameter forwarded from CH through the CC proxy layer. |
| `_build_auth_headers` | Sets the `X-User-Identity` HTTP header with the user JWT when the session is a user-passthrough session. |
| `websocket_chat` | WebSocket endpoint handler that extracts and caches the user JWT from the `?user_token=` query parameter. |
| `require_permission` | Permission check dependency (debug logging added for tool-call diagnostics). |
| `toDelegationSnippetLine` | Delegation summary snippet builder (no `using_tool` line). |

---

## API Endpoints

These endpoints are served by the standalone `mcp-demo-app` service, not the Parthenon backend.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/mcp` | `Authorization: Bearer <agent JWT>` required for agent-identity tools; `X-User-Identity: Bearer <user JWT>` required for `helloUser`; optional for `initialize` and `tools/list` | MCP JSON-RPC 2.0 endpoint. Dispatches `initialize`, `tools/list`, and `tools/call`. |
| `GET` | `/health` | None | Health check. Returns `{"status": "ok", "slug": "demo"}` with HTTP 200. |

### MCP JSON-RPC Methods

| Method | Description |
|--------|-------------|
| `initialize` | Returns server capabilities, protocol version, and server info (dual demo mode). |
| `tools/list` | Returns the ten tool descriptors from `TOOL_MANIFEST` (3 greeting + 7 booking). |
| `tools/call` | Dispatches to a registry handler; unknown tool names return a structured error. |

Unknown methods return JSON-RPC error code `-32601` (Method not found).

### Booking tools (agent identity; `arguments` dict)

| Tool | Behaviour |
|------|-----------|
| `search_flights` | Read-only flight search by origin, destination, and date; returns seeded fictional flights. |
| `book_ticket` | Creates a PNR-keyed booking for one or more passengers (name, type `adult`/`child`/`infant`, bag count). Rejects a booking with a child or infant but no adult (structured error). Gated platform-side by confirm-before-write. |
| `generate_payment_link` | Returns a fictional payment URL for a booked ticket and completes the simulated payment (booking `booked → paid`), so check-in is reachable with exactly seven tools. Always succeeds once a link is generated. |
| `check_ticket_status` | Read-only status by PNR plus flight and per-passenger seat/bag detail. |
| `check_in_passenger` | Transitions the whole booking `paid → checked-in` by PNR (all passengers are checked in together). Target of the scripted check-in plan. |
| `select_seat` | Per-passenger seat assignment (PNR + passenger name + seat) with availability validation; marks the seat occupied. |
| `cancel_booking` | Destructive cancellation by PNR; frees the seats of all passengers on the booking. Gated platform-side by confirm-before-write. |

Booking-level lifecycle: `booked → paid → checked-in → cancelled`. Seats are `free ↔ occupied` (occupied seats reference the holding PNR). All tools return the established structured error shape (`{"error": true, "message": ...}`) rather than HTTP failures.

### Existing Parthenon Backend — No Changes

No new endpoints are added to or removed from the Parthenon backend API. Hub registration is performed by the demo app calling the existing `POST /api/v1/mcp/servers` and `POST /api/v1/mcp/servers/{id}/sync` endpoints at startup.

---

## Data Access Patterns

The demo app has no persistent data store. All state is held in memory for the lifetime of the process.

| Data | Access Pattern | Notes |
|------|----------------|-------|
| Own access token | In-memory cache in `keycloak_client` | Refreshed automatically ~30 s before expiry via client credentials grant against the agent realm |
| Agent realm JWKS | In-memory cache in `keycloak_client` | Re-fetched every 10 minutes |
| User realm JWKS | In-memory cache in `user_keycloak_client` | Independent cache; falls back to the agent realm when `KEYCLOAK_USER_REALM` is not configured |
| Hub server record | Written once at startup via `POST /api/v1/mcp/servers` | Idempotent — 409 is handled by looking up the existing record |
| Tool manifest | Static in-process constant (`TOOL_MANIFEST`) — ten tools | Published to the Hub via the standard MCP `tools/list` response during tool sync |
| Booking state | Process-local collections inside `BookingStore` | Flights, PNR-keyed bookings, passengers, seat map, payment links; access is sequential per tool call |
| Reset semantics | Store rebuilt from deterministic seed data on every startup (`lifespan`) | Restart = predictable reset; PNRs are deterministically generated so restarts reproduce identical data |

Write tools mutate the store only when invoked; the platform's confirm-before-write approval gates invocation itself, so rejection or timeout leaves the store untouched. No client-side booking state exists: the agent-client demo app and the Parthenon chat UI only relay/display conversation turns. All outbound HTTP calls use `httpx.AsyncClient`.

### Platform demo configuration (config only — no schema change)

The scenario is wired through existing admin/seeding paths: one skill per booking capability (or a small set of skills), demo role grants (plus a deliberately restricted variant to demonstrate denial), one conversational agent type, and a scripted/optimized check-in plan that AR executes sandboxed with zero LLM. Nothing is seeded by Parthenon migrations and no new tables exist.

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AppSettings` | class | Pydantic BaseSettings for all env-var configuration including optional `KEYCLOAK_USER_REALM` / `KEYCLOAK_USER_CLIENT_ID` | `mcp-demo-app/app/config.py` |
| `settings` | instance | Module-level `AppSettings` singleton | `mcp-demo-app/app/config.py` |
| `KeycloakClient` | class | Keycloak client credentials grant + JWKS cache; optional `realm_name` for multi-realm support | `mcp-demo-app/app/auth.py` |
| `keycloak_client` | instance | Agent-realm `KeycloakClient` singleton; connectivity validated at startup | `mcp-demo-app/app/auth.py` |
| `user_keycloak_client` | instance | User-realm `KeycloakClient` singleton with independent caches | `mcp-demo-app/app/auth.py` |
| `verify_agent_jwt` | function | Validates an agent JWT against the agent-realm JWKS | `mcp-demo-app/app/auth.py` |
| `verify_user_jwt` | function | Validates a user JWT against the user-realm JWKS (401 on failure) | `mcp-demo-app/app/auth.py` |
| `get_agent_identity` / `get_user_identity` | functions | FastAPI dependencies extracting/validating the `Authorization` / `X-User-Identity` bearer tokens | `mcp-demo-app/app/auth.py` |
| `hello_world_tool` / `hello_agent_tool` / `hello_user_tool` | functions | Greeting handlers (`helloWorld` no gate; `helloAgent` `demo_agent`; `helloUser` `demo_user`) | `mcp-demo-app/app/tools.py` |
| `tool_registry` | dict | Name → handler dispatch map for all ten tools | `mcp-demo-app/app/tools.py` |
| `TOOL_MANIFEST` | list | Static MCP tool descriptors (3 greeting + 7 booking) published via `tools/list` | `mcp-demo-app/app/tools.py` |
| `BOOKING_TOOL_NAMES` | set | Names of the seven booking tools; the MCP route passes them an `arguments` dict | `mcp-demo-app/app/tools.py` |
| `search_flights_tool` | function | Flights by origin/destination/date (read-only) | `mcp-demo-app/app/tools.py` |
| `book_ticket_tool` | function | Creates a PNR booking for one or more passengers; rejects child/infant-only bookings | `mcp-demo-app/app/tools.py` |
| `generate_payment_link_tool` | function | Fictional payment URL; completes the simulated payment (`booked → paid`) | `mcp-demo-app/app/tools.py` |
| `check_ticket_status_tool` | function | Booking status + flight/seat/bag detail by PNR | `mcp-demo-app/app/tools.py` |
| `check_in_passenger_tool` | function | Checks in the whole booking by PNR (`paid → checked-in`); target of the scripted plan | `mcp-demo-app/app/tools.py` |
| `select_seat_tool` | function | Per-passenger seat assignment with availability validation | `mcp-demo-app/app/tools.py` |
| `cancel_booking_tool` | function | Cancels a booking and frees all its seats | `mcp-demo-app/app/tools.py` |
| `_error_result` / `_require_str` | functions | Structured error shape and argument-extraction helpers for booking tools | `mcp-demo-app/app/tools.py` |
| `BookingStore` | class | Seed-backed in-memory store: flights, PNR bookings/passengers, seat map, payment links, status lifecycle | `mcp-demo-app/app/booking_store.py` |
| `Flight` / `Booking` / `Passenger` | dataclasses | Typed store records; a booking owns one or more passengers (name, type, bags, seat) | `mcp-demo-app/app/booking_store.py` |
| `BookingError` | exception | Raised on invalid references or illegal transitions; converted to structured tool errors | `mcp-demo-app/app/booking_store.py` |
| `BookingStore.reset` / `reset_booking_store` | methods/function | Deterministic seed loader (fictional flights, seat map, empty bookings); reseed on startup | `mcp-demo-app/app/booking_store.py` |
| `booking_store` | instance | Module-level store singleton seeded in the app lifespan | `mcp-demo-app/app/booking_store.py` |
| `register_with_hub` | function | Registers the demo app with the Parthenon Hub and triggers tool sync (all ten tools) | `mcp-demo-app/app/registration.py` |
| `health_router` | APIRouter | FastAPI router for `GET /health` | `mcp-demo-app/app/routes/health.py` |
| `mcp_router` | APIRouter | FastAPI router for `POST /mcp` (JSON-RPC dispatcher with identity selection) | `mcp-demo-app/app/routes/mcp.py` |
| `mcp_endpoint` | function | `POST /mcp` handler: parses the JSON-RPC envelope, selects identity source by tool name, dispatches | `mcp-demo-app/app/routes/mcp.py` |
| `_SERVER_INFO` | constant | MCP server info metadata (dual demo mode) | `mcp-demo-app/app/routes/mcp.py` |
| `create_app` | function | FastAPI app factory; configures lifespan and mounts routers | `mcp-demo-app/app/main.py` |
| `lifespan` | async context manager | Validates Keycloak connectivity, seeds the booking store, triggers Hub registration | `mcp-demo-app/app/main.py` |
| `app` | instance | Module-level FastAPI application instance | `mcp-demo-app/app/main.py` |
| `init.ps1` / `start.ps1` / `stop.ps1` | scripts | Idempotent dual-realm initialisation (roles `demo_agent`, `demo_user`) and local run control on port 7001 | `mcp-demo-app/init.ps1`, `start.ps1`, `stop.ps1` |
| `setup-keycloak.ps1` | script | Legacy Keycloak setup (use `init.ps1` for new setups) | `mcp-demo-app/setup-keycloak.ps1` |
| `test_config.py` / `test_auth.py` / `test_tools.py` / `test_mcp_router.py` | test files | Settings fallback, JWT validation, greeting handlers + registry/manifest, dual-identity dispatch | `mcp-demo-app/tests/unit/` |
| `test_booking_store.py` / `test_booking_tools.py` / `test_mcp_router_booking.py` | test files | Store lifecycle and seed determinism; per-tool happy/error paths; booking tools in `tools/list` + `tools/call` dispatch | `mcp-demo-app/tests/unit/` |
| `test_agent_flow.py` / `test_hub_registration.py` / `test_startup.py` | test files | End-to-end dual-identity flow, Hub registration tool sync, startup with dual-realm config | `mcp-demo-app/tests/integration/` |
| `ToolCallRequest.user_jwt` | field | User identity JWT forwarded to CH tool routing | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `cache_user_jwt` / `get_user_jwt` | functions | Per-session user-JWT cache for dual-identity forwarding | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `McpProxyRequest.user_jwt` | field | User JWT forwarded to the Control Center proxy | `backend/app/api/v1/internal/mcp_proxy.py` |
| `McpProxyEngine.call_tool` / `_build_auth_headers` | method | Dual-identity forwarding into the MCP proxy and `X-User-Identity` header injection | `backend/app/services/mcp/proxy.py` |
| `websocket_chat` | function | Caches the user JWT from the WebSocket query param | `backend/app/api/ws/chat.py` |
| `require_permission` | function | Permission check dependency (debug diagnostics) | `backend/app/api/deps.py` |
| `init-local-dev.py` | script | Local Keycloak bootstrap (test agent identities, claim mappers, user profile, volume persistence) | `scripts/init-local-dev.py` |
| `docker-compose.yml` | config | Demo app service entry and Keycloak data volume | `docker-compose.yml` |
| `toDelegationSnippetLine` | function | Delegation snippet line builder | `frontend/src/hooks/useChatSession.ts` |
| Demo client server | module | Unchanged client demo app: secret → CH integration gateway → conversation start/message/end, session poll | `agent-client-demo-app/demo_app/main.py` |
| Client demo UI | static page | Chat surface for the scenario's second demo surface | `agent-client-demo-app/static/index.html` |

---

## Tests

| Suite | Coverage |
|-------|----------|
| `mcp-demo-app/tests/unit/` | Settings/JWT/greeting contracts, booking store lifecycle + seed determinism, per-booking-tool happy/error paths, booking dispatch through the MCP route |
| `mcp-demo-app/tests/integration/` | Dual-identity end-to-end flow, Hub registration and ten-tool sync, startup with dual-realm configuration |

The demo app has no Parthenon test dependencies; its suites run against the in-process FastAPI app.
