# Tech Spec: airline-booking-demo

## Technical Overview

The airline booking demo extends the existing standalone MCP demo app (`mcp-demo-app/`) from three greeting tools to a dual-mode demo: the greeting tools stay untouched for identity-propagation demos, and seven new fictional booking tools (search flights, book ticket, generate payment link, check ticket status, check in passenger, select seat, cancel booking) implement a realistic multi-step business workflow. Bookings are identified by a PNR (6-character alphanumeric, deterministically generated so restarts produce identical data); every fetch-style tool keys off the PNR. A booking owns one or more passengers (name, type `adult`/`child`/`infant`, per-passenger bag count), and a child or infant cannot travel without at least one adult on the same booking. All booking state lives in a new in-memory store seeded deterministically at demo-app startup — no Parthenon database changes, no persistence, no external integrations.

The demo app keeps its existing integration model: it self-registers with the Parthenon MCP Hub under its slug (create-or-lookup + tool sync), tools are exposed over the same JSON-RPC MCP endpoint, and the Hub syncs them into the `server____tool` namespace. Agents invoke booking tools only through the Communication Hub; Control Center resolves identity and permissions per call; the confirm-before-write approval flow is applied platform-side to booking and cancellation; the check-in flow is additionally wrapped as a scripted/optimized plan executed sandboxed in Agent Runtime (AR-only, zero-LLM). The agent client demo app consumes the scenario unchanged via the CH integration gateway. Top-priority rules hold: services remain segregated, agents run only in AR, only CC touches the DB, and the demo app receives identity context only — never tokens or credentials.

## Component Breakdown

| Component | Responsibility | Change |
|---|---|---|
| Booking store (new module in `mcp-demo-app/app/`) | In-memory flights, PNR-keyed bookings with passengers, seat map, payment links; booking-level status lifecycle (booked → paid → checked-in → cancelled); seat availability; deterministic reseed on startup | New |
| Booking tools (in `mcp-demo-app/app/tools.py`) | Seven tool handlers + registry + manifest entries following the existing handler pattern (identity dict in, result dict out, `access_denied` shape preserved) | Extended |
| MCP route (`mcp-demo-app/app/routes/mcp.py`) | Unchanged protocol surface (`initialize` / `tools/list` / `tools/call`); identity extraction per tool; booking tools use agent identity; greeting tools keep user/agent split | Metadata update only |
| Hub registration (`mcp-demo-app/app/registration.py`) | Unchanged: POST `/api/v1/mcp/servers` (409 → lookup) then trigger `/sync`; discovers all ten tools | None |
| App lifespan (`mcp-demo-app/app/main.py`) | Seeds booking store at startup; Keycloak check and Hub registration (non-fatal failure) as today | Extended |
| Auth (`mcp-demo-app/app/auth.py`) | Unchanged: forwards JWT → identity dict (`sub`, `iss`, `mcp_role`) | None |
| Parthenon platform config | Skills for booking tools, demo agent role grants (+ restricted variant), conversational agent type, scripted check-in plan — all via existing admin/seeding paths; no schema changes | Config only |
| Agent client demo app (`agent-client-demo-app/demo_app/`) | Unchanged; already supports conversational agent sessions over the CH integration gateway (client secret → conversation start/poll) | None |

## API Changes

Demo app internal routes (no Parthenon REST API changes):

- `POST /mcp` (`mcp-demo-app`) — unchanged route; `tools/list` now returns the seven booking tools alongside the three greeting tools; `tools/call` dispatches booking tool names from the registry. All booking tools resolve the agent identity (Authorization header path).
- `GET /health` (`mcp-demo-app`) — unchanged.

Demo app outbound (existing, unchanged):

- `POST /api/v1/mcp/servers` and `POST /api/v1/mcp/servers/{server_id}/sync` (Control Center) — registration + tool sync at startup, per `mcp-demo-app/app/registration.py`.

Platform surfaces consumed as-is (no behavioral change): MCP Hub tool namespace `server____tool`, permission resolution by CC, confirm-before-write intervention, script registry / optimized plan lifecycle, CH integration gateway endpoints used by the agent client demo app (conversation start / message / session poll behind its own thin `/api/*` routes).

## State Management

- All booking state is process-local in the demo app: plain in-memory collections inside the new booking store module. No frontend state changes anywhere (Parthenon UI and agent client demo app are untouched).
- Lifecycle states (booking level): `booked → paid → checked-in → cancelled`; seat map `free ↔ occupied` (occupied seats reference the holding booking's PNR); payment links are records tied to a PNR; payment always succeeds once the link is generated, regardless of passenger count.
- Reset semantics: the store is rebuilt from deterministic seed data on every app startup (wired in the lifespan of `mcp-demo-app/app/main.py`), so restart = predictable reset — a stated acceptance criterion.
- Write tools (book, check-in, seat, cancel) mutate the store only after being invoked; the platform's confirm-before-write approval gates invocation itself, so rejection/timeout leaves the store untouched. Check-in operates on the whole booking via PNR (all passengers checked in with it); seat selection is per passenger (PNR + passenger name + seat); cancel frees the seats of all passengers on the booking, proving true state change (same seat/flight re-bookable).
- Concurrency: single-process demo; store access is sequential per tool call (same assumption as the existing greeting handlers).

## Data Access Patterns

- Server-side only: tool handlers read/write the in-memory store directly within the demo app process; agents never access the demo store except through MCP tool calls, and never touch the Parthenon database.
- No client-side data access: the agent client demo app holds no booking state — it only relays conversation turns to CH and polls session results; the Parthenon chat UI likewise only displays agent conversation.
- Parthenon platform data (skills, roles, agent type, script plan) is read by CC from the PostgreSQL database per existing patterns — CC remains the only DB-connected service; AR executes the scripted check-in plan in its sandbox and calls booking tools via the normal CH MCP path.
- Seed data access: deterministic loader constructs the store at startup; no runtime mutation of seed definitions (flights/seats) other than seat occupancy and derived ticket state.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `hello_world_tool` / `hello_agent_tool` / `hello_user_tool` | function | Existing greeting tools — unchanged, identity-propagation demo mode | `mcp-demo-app/app/tools.py` |
| `tool_registry` | dict | Name → handler dispatch map — gains the seven booking tool entries | `mcp-demo-app/app/tools.py` |
| `TOOL_MANIFEST` | list | MCP `tools/list` payload — gains seven booking tool entries (name, description, input schema) | `mcp-demo-app/app/tools.py` |
| `BookingStore` | class (new) | In-memory seed-backed store: flights/bookings/seat map/payment links, status lifecycle (booked → paid → checked-in → cancelled), seat availability | `mcp-demo-app/app/booking_store.py` (new) |
| `Flight` / `Booking` / `Passenger` | dataclasses (new) | Typed store records — a `Booking` is PNR-keyed and owns one or more `Passenger` records (name, type `adult`/`child`/`infant`, bags, seat) | `mcp-demo-app/app/booking_store.py` (new) |
| `BookingError` | exception (new) | Raised on invalid references or illegal transitions; tool handlers convert it to structured error results | `mcp-demo-app/app/booking_store.py` (new) |
| `BookingStore.reset` / `reset_booking_store` | methods/function (new) | Deterministic seed loader: fictional flights, seat map with seed holds, empty bookings; reseed on startup | `mcp-demo-app/app/booking_store.py` (new) |
| `booking_store` | singleton (new) | Module-level store instance; seeded in the app lifespan via `reset_booking_store()` | `mcp-demo-app/app/booking_store.py` (new) |
| `search_flights_tool` | function (new) | Tool: flights by origin/destination/date (read-only) | `mcp-demo-app/app/tools.py` |
| `BOOKING_TOOL_NAMES` | set (new) | Names of the seven booking tools — MCP route passes them an `arguments` dict in addition to the caller identity (greeting handlers keep the identity-only signature) | `mcp-demo-app/app/tools.py` |
| `book_ticket_tool` | function (new) | Tool: create a booking for one or more passengers (name, type, bags each); rejects a child/infant booking without an adult with a structured error (confirm-before-write gated platform-side); returns the PNR | `mcp-demo-app/app/tools.py` |
| `generate_payment_link_tool` | function (new) | Tool: fictional payment URL for a booked ticket; the demo simulates payment success (booked → paid) so the check-in step is reachable with exactly seven tools | `mcp-demo-app/app/tools.py` |
| `check_ticket_status_tool` | function (new) | Tool: current booking status by PNR plus flight and per-passenger seat/bag details (read-only) | `mcp-demo-app/app/tools.py` |
| `check_in_passenger_tool` | function (new) | Tool: paid → checked-in transition by PNR (all passengers on the booking checked in with it); target of the scripted plan | `mcp-demo-app/app/tools.py` |
| `select_seat_tool` | function (new) | Tool: per-passenger seat assignment (PNR + passenger name + seat) with availability validation | `mcp-demo-app/app/tools.py` |
| `cancel_booking_tool` | function (new) | Tool: destructive cancellation by PNR, frees the seats of all passengers on the booking (confirm-before-write gated) | `mcp-demo-app/app/tools.py` |
| `_error_result` / `_require_str` | functions (new) | Shared structured error shape (`{"error": True, "message": ...}`) and argument extraction helpers for booking tools | `mcp-demo-app/app/tools.py` |
| `mcp_endpoint` | function | JSON-RPC MCP endpoint (`initialize` / `tools/list` / `tools/call`) — unchanged logic, new tool names dispatch | `mcp-demo-app/app/routes/mcp.py` |
| `_SERVER_INFO` | constant | MCP server info metadata — updated for dual demo mode | `mcp-demo-app/app/routes/mcp.py` |
| `get_agent_identity` / `get_user_identity` | function | Identity extraction from forwarded JWT headers — unchanged; booking tools use agent identity | `mcp-demo-app/app/auth.py` |
| `lifespan` | function | App startup/shutdown — extended to seed the booking store | `mcp-demo-app/app/main.py` |
| `create_app` | function | FastAPI app factory — metadata updated for dual demo mode | `mcp-demo-app/app/main.py` |
| `register_with_hub` | function | Hub registration (create-or-lookup + sync) — unchanged; discovers all ten tools | `mcp-demo-app/app/registration.py` |
| `settings` | object | Demo app config (slug, hub URL, base URL) — unchanged | `mcp-demo-app/app/config.py` |
| MCP route tests | tests | Extended: booking tools in `tools/list` and `tools/call` dispatch (`tests/unit/test_mcp_router_booking.py`); greeting-tool tests updated only for the expanded tool counts | `mcp-demo-app/tests/` (unit/integration layout, see `mcp-demo-app/tests/conftest.py`) |
| Booking store/tools unit tests | tests (new) | Store lifecycle, seed determinism, per-tool happy/error paths (`tests/unit/test_booking_store.py`, `tests/unit/test_booking_tools.py`) | `mcp-demo-app/tests/unit/` |
| Demo client server | module | Unchanged client demo app: secret → CH gateway → conversation start/message/end, session poll | `agent-client-demo-app/demo_app/main.py` |
| Client demo UI | static page | Unchanged chat surface for the scenario's second demo surface | `agent-client-demo-app/static/index.html` |
