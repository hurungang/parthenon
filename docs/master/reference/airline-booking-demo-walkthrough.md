# Airline Booking Demo — Presenter Walkthrough

Reference for running the scenario-based airline booking demo end-to-end. All booking data is **fictional**, held in an in-memory store inside the MCP demo app (`mcp-demo-app/`), and **resets deterministically on every demo-app restart**. No real payments, airlines, or external calls; no Parthenon database writes.

## 1. Setup Prerequisites

- Full Parthenon stack running: Control Center (CC), Communication Hub (CH), Agent Runtime (AR), Keycloak, PostgreSQL (`./scripts/restart-backend.sh` / `parthenon.ps1 restart`).
- MCP demo app running (`mcp-demo-app/`) — on startup it seeds the booking store and self-registers with the MCP Hub under slug `demo` (create-or-lookup + tool sync). Registration failure is non-fatal for the app itself.
- Agent client demo app (`agent-client-demo-app/`) for the second demo surface.
- Platform config (one-time, via admin UI / seeding): demo booking skills, demo agent role with skill grants (+ a restricted variant omitting at least one tool), a conversational agent type bound to a model and the booking role, and a scripted/optimized plan for the check-in flow.

## 2. Seed Data Summary

| Flight | Route | Date | Departure → Arrival | Fare | Seats |
|---|---|---|---|---|---|
| FL-101 | Aurora City → Meridian Falls | 2030-03-15 | 08:30 → 09:45 | 180 CRED | 24 (2 pre-held) |
| FL-102 | Aurora City → Meridian Falls | 2030-03-15 | 12:15 → 13:30 | 220 CRED | 24 (2 pre-held) |
| FL-103 | Aurora City → Meridian Falls | 2030-03-15 | 18:00 → 19:15 | 260 CRED | 24 (2 pre-held) |
| FL-201 | Meridian Falls → Aurora City | 2030-03-15 | 20:30 → 21:45 | 190 CRED | 24 (2 pre-held) |

- Seats per flight: rows 1–4 × A–F. Seats **1A** and **2C** are pre-occupied on every flight (deterministic seed holds) so availability demos are predictable.
- No pre-existing bookings; PNRs start at `PKT001` and reset on restart (deterministic counter — the same PNRs recur every run).
- A booking covers one or more passengers (name, type `adult`/`child`/`infant`, per-passenger bag count); one seat is reserved per passenger. A child or infant cannot travel without at least one adult on the same booking.
- Travel date to use in conversation: **2030-03-15**.

## 3. The Seven Tools (exposed as `demo____<tool>` via the MCP Hub)

| Tool | Read/Write | Notes |
|---|---|---|
| `searchFlights` | read | origin, destination, date |
| `bookTicket` | write | **confirm-before-write** (platform approval precedes invocation); passengers list (name, type, bags); returns the PNR |
| `generatePaymentLink` | write | fictional URL keyed by PNR; simulates payment success (booked → paid) regardless of passenger count |
| `checkTicketStatus` | read | booked / paid / checked-in / cancelled, by PNR |
| `checkInPassenger` | write | PNR-keyed; paid → checked-in only (all passengers on the booking); part of the scripted plan |
| `selectSeat` | write | checked-in only; PNR + passenger name + seat; validates existence & availability |
| `cancelBooking` | write (destructive) | **confirm-before-write**; cancels the whole booking and frees the seats of all its passengers |

Lifecycle (booking level): `booked → paid → checked-in`; `cancelled` from any state. Cancel frees the seats of all passengers on the booking, which new bookings on the same flight can then claim — proving true state change.

## 4. Demo Script (full journey, ~10 minutes)

1. **Search** — "Find flights from Aurora City to Meridian Falls on 2030-03-15." Agent calls `searchFlights`; three flights returned.
2. **Book (governance showcase)** — "Book the cheapest one for Jane Doe." Agent presents the canonical confirm-before-write preview (`**Book ticket: Jane Doe**` + field table) and waits for approval. **Show rejection first**: reject → no booking exists (state untouched). Then approve → booking `PKT001`, status `booked`, seat auto-assigned.
3. **Family booking + domain rule denial (extra beat)** — "Book it for Timmy (a kid) and his baby sister too, no adults." The call returns a structured error: *"A child or infant cannot travel without at least one adult on the same booking."* Then "add me as the adult" → booking succeeds with three passengers, each with a reserved seat and per-passenger bag counts. Great moment to show the agent enforcing a business rule conversationally.
4. **Pay** — "Generate the payment link." Agent calls `generatePaymentLink` with the PNR; fictional URL returned, the whole booking becomes `paid` (simulated — no real money; amount = fare × passenger count).
5. **Status** — "What's my ticket status?" Read-only `checkTicketStatus` by PNR answered conversationally, showing each passenger's seat and bags.
6. **Check-in (optimization showcase)** — "Check us in and pick a window seat for Jane." The scripted/optimized plan executes `checkTicketStatus → checkInPassenger → selectSeat` in Agent Runtime with **zero intermediate LLM steps** (visible in execution logs). Check-in covers the whole booking (all passengers). Seat `1A` is occupied (seed hold) — a good moment to show the structured "seat occupied" error, then pick e.g. `4A` for one passenger via PNR + passenger name + seat.
7. **Cancel (destructive showcase)** — "Cancel our booking." Confirmation preview again; approve → status `cancelled`, seats of all passengers freed. Re-book on the same flight and select a freed seat to prove true state change.
8. **Access-denied demo** — Using the restricted role variant, ask the agent to cancel (or whichever tool is ungranted): a clear access-denied result is relayed conversationally.
9. **Second surface** — Repeat (or abbreviate) the journey from `agent-client-demo-app` (client secret → CH integration gateway). No code changes needed there.

Capability highlights per step: identity propagation (every call carries the agent identity), tool-level permissions, confirm-before-write on book + cancel, scripted zero-LLM execution on check-in, structured error results, full audit trail in execution logs / conversation history.

## 5. Live Validation Script (Phases 6.1–6.6 — requires running stack)

- [ ] **6.1 Chat UI journey** — run §4 steps 1–6 from the Parthenon chat UI; verify every tool call appears in execution logs / conversation history.
- [ ] **6.2 Agent client journey** — same journey from `agent-client-demo-app`; no changes to that app.
- [ ] **6.3 Confirm-before-write gating** — reject a booking preview and let a cancellation preview time out; verify store state is unchanged (re-check status by PNR returns the structured "Unknown booking PNR" error).
- [ ] **6.4 Permission-denied path** — restricted-role agent attempts the ungranted tool (e.g. cancel); clear denial surfaced in conversation.
- [ ] **6.5 Scripted check-in zero-LLM** — run the optimized check-in plan; inspect AR execution logs for deterministic multi-tool execution without intermediate LLM reasoning steps.
- [ ] **6.6 Restart reset** — mid-scenario, restart `mcp-demo-app`; `checkTicketStatus` on the earlier PNR now returns the "Unknown booking PNR" error and flight search shows identical seed state.

Note on 6.6: booking state lives in the demo-app process only, so a restart always yields exactly the seed state in §2 — the same PNRs (`PKT001`, …) recur every run.

## 6. Reset Between Runs

Restart the demo app (or its container). Startup log line: `Booking store seeded: 4 flights, 0 bookings`.
