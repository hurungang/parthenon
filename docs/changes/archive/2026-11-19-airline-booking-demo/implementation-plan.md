# Implementation Plan: airline-booking-demo

## Overview

Implement the scenario-based airline booking demo as a second demo mode layered onto the existing MCP demo app: seven fictional booking tools (search flights, book ticket, generate payment link, check ticket status, check in passenger, select seat, cancel booking) backed by a minimal in-memory seed-data store inside the demo app process. No Parthenon database changes — booking state lives entirely in the demo app's memory, and all platform behavior (MCP Hub registration, permission resolution, confirm-before-write, scripted plans, agent client gateway) is consumed as-is.

## Task Checklist

### Phase 1 — In-Memory Booking Domain (Demo App)

- [x] 1.1 — Design booking domain model and in-memory store
- [x] 1.2 — Build deterministic seed data loader
- [x] 1.3 — Add store reset/reseed behavior on startup

### Phase 2 — Booking MCP Tools

- [x] 2.1 — Implement flight search tool
- [x] 2.2 — Implement book ticket tool (confirm-before-write)
- [x] 2.3 — Implement generate payment link tool
- [x] 2.4 — Implement check ticket status tool
- [x] 2.5 — Implement check-in passenger tool
- [x] 2.6 — Implement seat selection tool
- [x] 2.7 — Implement cancel booking tool (confirm-before-write, destructive)
- [x] 2.8 — Wire tools into tool registry and MCP tool manifest

### Phase 3 — Demo App Integration

- [x] 3.1 — Wire booking store into app lifespan (seed on startup)
- [ ] 3.2 — Verify Hub registration and tool sync of all seven tools _DEFERRED: requires a running Parthenon stack (live-environment validation; registration code unchanged)._
- [x] 3.3 — Update app metadata/description for the dual demo mode

### Phase 4 — Parthenon Configuration (No DB Schema Changes)

- [ ] 4.1 — _DEFERRED to live-environment setup_ — Create demo booking skills for the seven tools
- [ ] 4.2 — _DEFERRED to live-environment setup_ — Create/extend demo agent role with booking skill grants
- [ ] 4.3 — _DEFERRED to live-environment setup_ — Configure demo conversational agent type (identity, role, model)
- [ ] 4.4 — _DEFERRED to live-environment setup_ — Author scripted/optimized plan for the check-in flow
- [ ] 4.5 — _DEFERRED to live-environment setup_ — Configure intentionally ungranted tool variant for access-denied demo

### Phase 5 — Unit Tests

- [x] 5.1 — Unit tests for booking store and seed data
- [x] 5.2 — Unit tests for each booking tool handler
- [x] 5.3 — MCP endpoint tests for booking tools (list + call)
- [x] 5.4 — Run full demo app test suite

### Phase 6 — End-to-End Scenario Validation & Docs

- [ ] 6.1 — _DEFERRED: requires running stack_ — Validate full journey via Parthenon chat UI
- [ ] 6.2 — _DEFERRED: requires running stack_ — Validate full journey via agent client demo app
- [ ] 6.3 — _DEFERRED: requires running stack_ — Validate confirm-before-write gating (reject/timeout → no write)
- [ ] 6.4 — _DEFERRED: requires running stack_ — Validate permission-denied path for ungranted tool
- [ ] 6.5 — _DEFERRED: requires running stack_ — Validate scripted check-in flow executes zero-LLM
- [ ] 6.6 — _DEFERRED: requires running stack_ — Verify restart resets booking state predictably
- [x] 6.7 — Write demo walkthrough reference doc

## Phase 1 — In-Memory Booking Domain (Demo App)

- [x] 1.1 — Design booking domain model and in-memory store —
  New module under `mcp-demo-app/app/` holding fictional flights, PNR-keyed bookings, a small seat map, and payment links in plain in-memory dictionaries/dataclasses. Support: flight lookup by origin/destination/date; booking creation for one or more passengers (name, type `adult`/`child`/`infant`, per-passenger bag count — a child/infant requires an adult on the same booking) with a deterministic PNR identifier; booking-level status transitions (booked → paid → checked-in → cancelled); per-passenger seat availability tracking; payment link records tied to a PNR. — _Done when: store module exists with typed structures and clear accessor functions; no persistence layer; no external service calls._

- [x] 1.2 — Build deterministic seed data loader —
  Minimal fictional seed: a handful of flights on a fixed route pair (no real airline names/fares), an initial seat map with a few occupied seats, no pre-existing bookings. Seed generation must be deterministic so every restart produces identical data. — _Done when: loading seed produces identical store state across runs; data is clearly fictional and minimal._

- [x] 1.3 — Add store reset/reseed behavior on startup —
  Store is rebuilt from seed data on demo app startup; no state survives restart. — _Done when: restarting the app resets all bookings/seat assignments to the seed state (covered by a unit test)._

## Phase 2 — Booking MCP Tools

All tool handlers live in `mcp-demo-app/app/tools.py` following the existing pattern: each handler receives the caller identity dict, returns a result dict, and `TOOL_MANIFEST` entries declare name, description, and JSON-schema input schema. Greeting tools remain unchanged.

- [x] 2.1 — Implement flight search tool —
  Input: origin, destination, date. Returns matching seed flights (flight number, times, fare, seats remaining). Read-only. — _Done when: search over seed data returns expected matches; empty result set is a clean response, not an error._

- [x] 2.2 — Implement book ticket tool (confirm-before-write) —
  Input: flight identifier, passengers list (name, type, optional bag count each). The agent must present the canonical confirmation preview and receive approval before this tool executes (platform-side gating — the tool itself just writes once called). Returns the booking PNR and status "booked"; rejects a child/infant booking without an adult with a structured error result. — _Done when: booking a seed flight creates a PNR-keyed booking in state "booked" with one reserved seat per passenger; the platform approval flow precedes every invocation in demo runs; rejection/timeout leaves the store untouched._

- [x] 2.3 — Implement generate payment link tool —
  Input: PNR. Returns a fictional payment URL and records a payment-link entry; the demo simulates immediate payment success, transitioning the booking from "booked" to "paid" (amount = fare × passenger count) so the check-in step is reachable with exactly seven tools (no separate pay tool). Calling it on an already-paid booking returns the existing link (idempotent); other non-booked states and unknown PNRs return a structured error result. — _Done when: link generated for a valid booked booking and status becomes "paid"; invalid/unknown PNR returns a structured error result._

- [x] 2.4 — Implement check ticket status tool —
  Input: PNR. Returns current booking status (booked / paid / checked-in / cancelled) plus flight and per-passenger seat/bag details. Read-only. — _Done when: status accurately reflects store state at each point of the journey._

- [x] 2.5 — Implement check-in passenger tool —
  Input: PNR. Allowed only for paid bookings; transitions the whole booking (all passengers with it) to "checked-in". This is the capability wrapped by the scripted/optimized plan (Phase 4.4). — _Done when: check-in succeeds for a paid booking and is rejected with a clear result for booked-only or cancelled bookings._

- [x] 2.6 — Implement seat selection tool —
  Input: PNR, passenger name, seat identifier. Allowed only after check-in; validates the passenger is on the booking, the seat exists and is free; marks the seat occupied and attaches it to that passenger. — _Done when: valid selection assigns the seat and updates availability; occupied/nonexistent seats or passengers not on the booking return structured error results._

- [x] 2.7 — Implement cancel booking tool (confirm-before-write, destructive) —
  Input: PNR. Cancels the whole booking and frees the seats of all its passengers; seats become re-bookable and the flight re-bookable, proving true state change. — _Done when: cancellation updates store state; freed seats can be selected by a new booking on the same flight._

- [x] 2.8 — Wire tools into tool registry and MCP tool manifest —
  Add all seven handlers to `tool_registry` and corresponding entries (name, description, input schema) to `TOOL_MANIFEST` in `mcp-demo-app/app/tools.py`. — _Done when: `tools/list` returns the seven booking tools plus the three greeting tools; each manifest entry matches its handler signature._

## Phase 3 — Demo App Integration

- [x] 3.1 — Wire booking store into app lifespan —
  Seed the booking store during startup in `mcp-demo-app/app/main.py` lifespan (before or alongside Hub registration; registration failure must remain non-fatal). — _Done when: app startup logs seed completion and tools operate against seeded data._

- [ ] 3.2 — Verify Hub registration and tool sync of all seven tools _DEFERRED: requires a running Parthenon stack (live-environment validation; registration code unchanged)._ —
  The existing flow in `mcp-demo-app/app/registration.py` (POST servers → 409 lookup → sync) must discover all seven tools under the app slug namespace. — _Done when: after startup, the Hub lists all seven booking tools; tool calls route through CH and reach the demo handlers._

- [x] 3.3 — Update app metadata/description for the dual demo mode —
  FastAPI title/description and server info in `mcp-demo-app/app/routes/mcp.py` reflect both greeting (identity) and airline-booking (scenario) demo modes. — _Done when: metadata text is accurate; no behavioral change to the MCP protocol surface._

## Phase 4 — Parthenon Configuration (No DB Schema Changes)

Platform configuration only — uses existing admin UI/seeding paths; no new tables, migrations, or platform code changes.

- [ ] 4.1 — _DEFERRED to live-environment setup_ — Create demo booking skills for the seven tools —
  One skill per tool (or small logical groups) referencing the synced tools under the demo app slug, following the existing skill-management flow. — _Done when: skills exist and resolve to the seven booking tools._

- [ ] 4.2 — _DEFERRED to live-environment setup_ — Create/extend demo agent role with booking skill grants —
  Demo agent role grants search/status/payment/check-in/seat/book/cancel skills as designed; a separate restricted variant omits at least one tool for the access-denied demo. — _Done when: an agent with the full role can invoke all seven tools; the restricted variant gets a clear access-denied result for the omitted tool._

- [ ] 4.3 — _DEFERRED to live-environment setup_ — Configure demo conversational agent type —
  Conversational agent type bound to the demo identity, booking role, a configured model, and a system instruction walking users through search → book → pay → check-in with confirm-before-write previews. — _Done when: the agent type executes end-to-end via CH and produces booking previews in the canonical confirm format._

- [ ] 4.4 — _DEFERRED to live-environment setup_ — Author scripted/optimized plan for the check-in flow —
  Wrap check_ticket_status → check_in → select_seat as a sandboxed script (draft → verified → compiled lifecycle), executed AR-only, demonstrating zero-LLM deterministic execution. — _Done when: the optimized plan executes the multi-tool check-in flow without intermediate LLM reasoning steps, visible in execution logs._

- [ ] 4.5 — _DEFERRED to live-environment setup_ — Configure intentionally ungranted tool variant for access-denied demo —
  Document/configure the restricted role variant and the specific tool (e.g. cancel) that will be denied on stage. — _Done when: the denial path is reproducible on demand and the agent relays the denial clearly to the user._

## Phase 5 — Unit Tests

Tests under `mcp-demo-app/tests/` (unit + integration layout per existing `conftest.py`), included in the configured test location `mcp-demo-app/tests/` from `docs/config.yaml`.

- [x] 5.1 — Unit tests for booking store and seed data —
  Cover seed determinism, reset-on-restart, seat availability transitions, and booking status lifecycle. — _Done when: all store-level tests pass._

- [x] 5.2 — Unit tests for each booking tool handler —
  Happy path plus invalid references, wrong-state transitions (check-in before payment, seat before check-in), cancel-and-rebook, and access-denied shape consistency with existing greeting tools. — _Done when: every handler has happy-path and error-path tests passing._

- [x] 5.3 — MCP endpoint tests for booking tools (list + call) —
  Extend existing MCP route tests: `tools/list` includes booking tools; `tools/call` dispatches correctly and returns structured results. — _Done when: endpoint tests pass against the FastAPI test client._

- [x] 5.4 — Run full demo app test suite —
  Full suite green, no regressions in greeting tool tests. — _Done when: `mcp-demo-app/tests/` passes in full._

## Phase 6 — End-to-End Scenario Validation & Docs

- [ ] 6.1 — _DEFERRED: requires running stack_ — Validate full journey via Parthenon chat UI —
  Search → book (with approval) → payment link → status → scripted check-in + seat → cancel (with approval) → re-book. — _Done when: the whole journey completes via chat UI with every tool call visible in execution logs / conversation history._

- [ ] 6.2 — _DEFERRED: requires running stack_ — Validate full journey via agent client demo app —
  Same scenario using `agent-client-demo-app` (client secret → CH integration gateway). — _Done when: journey completes from the client demo surface with no code changes to it._

- [ ] 6.3 — _DEFERRED: requires running stack_ — Validate confirm-before-write gating —
  Reject and let-approve-timeout the booking and cancellation previews. — _Done when: rejection or timeout leaves store state unchanged._

- [ ] 6.4 — _DEFERRED: requires running stack_ — Validate permission-denied path for ungranted tool —
  Restricted-role agent attempts cancel. — _Done when: clear access-denied result surfaces conversationally._

- [ ] 6.5 — _DEFERRED: requires running stack_ — Validate scripted check-in flow executes zero-LLM —
  Run the optimized check-in plan and inspect execution logs. — _Done when: logs show deterministic multi-tool execution without intermediate LLM steps._

- [ ] 6.6 — _DEFERRED: requires running stack_ — Verify restart resets booking state predictably —
  Restart the demo app mid-scenario and re-check state. — _Done when: store returns to identical seed state._

- [x] 6.7 — Write demo walkthrough reference doc —
  Add the scenario walkthrough (seed data summary, demo script, capability highlights per step, setup prerequisites) to `docs/master/reference/`. — _Done when: reference doc merged and a presenter can run the demo from it alone._

## Completion Checklist

- [ ] All seven booking tools registered, synced, and callable through the MCP Hub
- [ ] Greeting tools unchanged and still passing their tests
- [ ] In-memory seed data deterministic; restart resets state; no persistence, no external calls
- [ ] Confirm-before-write enforced on booking and cancellation; rejection/timeout = no write
- [ ] Access-denied path demonstrable for an ungranted tool
- [ ] Scripted/optimized check-in plan executes zero-LLM in Agent Runtime only
- [ ] Full journey validated from both Parthenon chat UI and agent client demo app
- [ ] All tool calls auditable in execution logs / conversation history
- [ ] Unit + integration tests in `mcp-demo-app/tests/` passing
- [ ] No Parthenon DB schema changes; `.change.yaml` `has_db_changes` stays false
- [ ] Demo walkthrough reference added to `docs/master/reference/`
