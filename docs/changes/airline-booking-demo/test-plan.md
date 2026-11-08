# Test Plan: Airline Booking Demo (Scenario-Based MCP Demo)

Owner: tester
Change: `docs/changes/airline-booking-demo/` — seven MCP booking tools in `mcp-demo-app/`; in-memory seed data only; `has_db_changes: false`

## Test Strategy

The demo has three distinct surfaces that must each be validated, with different rigor:

1. **Unit tests** (`mcp-demo-app/tests/unit/`) — fast, deterministic coverage of the booking store module and each tool handler in isolation: seed determinism, status lifecycle transitions, seat availability, and per-tool happy/error paths. This is the primary safety net since all business logic is in the demo app's in-memory store.
2. **Integration tests** (`mcp-demo-app/tests/`) — exercise the MCP route (`POST /mcp`) end-to-end: `initialize`, `tools/list` returning all ten tools (three greeting + seven booking), and `tools/call` dispatching booking tool names with identity extraction. Verifies the greeting tools remain untouched alongside the new booking tools (dual demo mode).
3. **E2E / platform tests** — full scenario journey against a running Parthenon stack (CC + CH + AR + Keycloak + demo app): MCP Hub discovery/namespace, agent role/permission gating, confirm-before-write interventions, and scripted plan execution in AR. These validate the platform consumption story, not just the demo app.
4. **Manual demo rehearsal** — a timed walkthrough (<10 min) of the full booking journey from both the Parthenon chat UI and the agent client demo app, verifying auditability (every tool call visible in execution logs) and restart-reset predictability. This is the acceptance gate for the presenter persona.

Testing is read/write lifecycle focused (full CRUD-equivalent: book = create, status/search = read, seat/check-in = update, cancel = delete with re-book verification), mirroring the platform's CRUD flow standards.

## Coverage Areas

| Area | What & Why |
|---|---|
| Booking store seed determinism | Restart must produce identical flights, seat map, and empty bookings — a stated acceptance criterion; demos must be predictable |
| Ticket status lifecycle | `booked → paid → checked-in → cancelled` transitions must be enforced per tool (e.g., check-in requires paid); prevents demo-visible nonsensical states |
| Seat availability | Free ↔ occupied transitions, double-booking rejection, seat freed on cancel — proves true state change |
| Tool registry & manifest | All seven booking tools discoverable via `tools/list` and dispatchable via `tools/call`; Hub sync discovers all ten tools |
| Identity propagation | Booking tools resolve agent identity (Authorization header path) and never see tokens/credentials — top-priority rule |
| Permission gating | Ungranted tools return clear `access_denied`-style results the agent can relay — the governance showcase |
| Confirm-before-write gating | Book and cancel must be gated platform-side: rejection/timeout leaves store untouched — the trust showcase |
| Scripted check-in plan | Check-in flow executes via optimized plan in AR sandbox with zero intermediate LLM reasoning — the optimization showcase |
| Greeting tools regression | The three existing greeting tools must behave exactly as before (identity-propagation demo mode preserved) |
| Dual demo surfaces | Same journey completable from Parthenon chat UI and agent client demo app via CH integration gateway |
| Auditability | Every tool call appears in execution logs / conversation history |
| No external calls / no persistence | No external system calls; nothing survives restart; no Parthenon DB changes |

## Critical Scenarios

### Happy-path demo journey (full lifecycle)

- WHEN the agent searches flights by origin, destination, and date THEN matching fictional sample flights are returned with fare and seat availability information.
- WHEN the agent proposes a booking THEN a confirmation preview is presented and no booking exists until the user approves.
- WHEN the user approves the booking preview THEN a ticket is created with status `booked` and a booking reference; WHEN the user rejects it or the approval times out THEN no booking is created and the store is unchanged.
- WHEN a payment link is generated for a booked ticket THEN a fictional payment URL record tied to the booking reference is returned; WHEN the payment flow completes THEN the ticket status becomes `paid`.
- WHEN the ticket status is checked at each stage THEN it accurately reports `booked` / `paid` / `checked-in` / `cancelled`.
- WHEN the paid ticket is checked in THEN the status becomes `checked-in` and the passenger is eligible for seat selection.
- WHEN a seat is selected for a checked-in ticket THEN the seat is assigned and the seat map shows it occupied; other seats remain available.
- WHEN the booking is cancelled after confirmation THEN the status becomes `cancelled`, the seat is freed, and the same flight/seat can be re-booked (proves true state change, not hiding).

### Permission & governance paths

- WHEN an agent whose role lacks a booking tool grant invokes that tool THEN a clear access-denied result is returned and the agent communicates it to the user; no state changes.
- WHEN the restricted agent-role variant invokes a write tool (book/cancel) THEN the invocation is blocked by permission gating before any store mutation.
- WHEN confirm-before-write is rejected or times out for a booking or cancellation THEN the demo store is verifiably untouched (no partial writes).
- WHEN any booking tool is invoked THEN the agent identity is resolved from the forwarded JWT and no identity token or credential reaches the tool result or logs.

### Scripted plan execution

- WHEN the check-in flow is invoked through the scripted/optimized plan THEN it completes without intermediate LLM reasoning steps (zero-LLM execution in AR sandbox) and produces the same store state as the conversational path.
- WHEN the script falls back to the base plan (per existing script execution outcome semantics) THEN the check-in still completes correctly and the fallback is visible in telemetry/logs.
- WHEN the scripted plan calls booking tools THEN they traverse the normal CH MCP path with per-call permission resolution.

### Cross-surface & registration

- WHEN the demo app starts THEN it registers with the MCP Hub under its slug and the Hub sync lists all ten tools under the `server____tool` namespace.
- WHEN the same journey is run from the agent client demo app THEN results are equivalent to the Parthenon chat UI path (conversation start/message/poll via CH integration gateway).
- WHEN the demo app restarts mid-journey THEN the store resets to deterministic seed state and a fresh journey can be run predictably.
- WHEN greeting tools are invoked during or after booking scenarios THEN their behavior is unchanged from before this change.

## Edge Cases & Risks

- **Invalid inputs**: unknown origin/destination/date in search; booking a nonexistent flight; payment link or status check for an unknown booking reference → clean tool errors, not exceptions.
- **Lifecycle violations**: check-in on a `booked` (unpaid) ticket; seat selection before check-in; cancel on an already-cancelled booking; seat selection on a checked-in ticket that already holds a seat → rejected with meaningful messages.
- **Seat map exhaustion**: booking/check-in when a flight has no free seats; race between two demo runs on the same seat in a single process → deterministic, sequential handling (documented single-process assumption).
- **Re-book collision**: cancelling then re-booking must not leave stale seat-occupancy or payment-link records pointing at the old booking.
- **Hub registration failure at startup**: Hub unreachable or sync fails (non-fatal per existing pattern) → demo app must still boot, and the failure must be observable so the presenter can diagnose.
- **Confirm-before-write timeout window**: a slow presenter decision must be handled as documented (timeout ⇒ no write); ensure the timeout value is demo-appropriate.
- **Scripted plan brittleness**: tool-result shape changes inside the check-in script could yield semantic errors hidden in successful transport envelopes (`partial_failure` detection is deferred by product decision) — mitigations: verify result shapes in integration tests.
- **Identity/credential leakage risk**: booking results or logs must never embed raw JWTs or tokens — check in test assertions.
- **Greeting-tool regression**: registry/manifest extensions must not reorder or rename existing tools (external clients may depend on the contract).
- **Demo-time flakiness**: LLM-dependent conversational paths (search phrasing, confirmation flow) may vary run-to-run; scripted path provides determinism — rehearsal must cover both.

## Acceptance Criteria Checklist

Mapping to PRD acceptance criteria:

- [ ] Demo app registers with MCP Hub under its own slug; all airline tools discovered and listed by the Hub → registration scenarios (Cross-surface), integration tests
- [ ] Agent with appropriate grants can search flights by origin/destination/date returning matching sample flights → journey scenario 1; unit + E2E
- [ ] Booking only after confirmation preview + approval; rejection/timeout ⇒ no booking → journey scenarios 2–3; governance scenarios; E2E confirm-before-write
- [ ] Payment link generatable for an existing booked ticket → journey scenario 4; unit error path for unknown reference
- [ ] Ticket status (booked/paid/checked-in/cancelled) reported accurately → journey scenario 5; unit lifecycle tests
- [ ] Check-in of paid ticket + seat selection with availability reflected in results → journey scenarios 6–7; seat-map edge cases
- [ ] Cancel only after confirmation; cancelled booking re-bookable on same flight → journey scenario 8; governance scenarios
- [ ] Sample data in-memory, resets predictably, no external calls → seed determinism scenarios; restart scenario; no-external-calls coverage area
- [ ] Ungranted tools return clear access-denied result the agent communicates → permission scenarios
- [ ] Scripted/optimized plan covers at least one multi-tool capability, executing without intermediate LLM reasoning → scripted-plan scenarios
- [ ] Full scenario completable end-to-end from both Parthenon chat UI and agent client demo app → cross-surface scenarios; manual rehearsal
- [ ] Every tool call visible in execution logs / conversation history → auditability coverage area; manual rehearsal check

## Test File References

Per `docs/config.yaml` `source.tests`:

- `mcp-demo-app/tests/unit/test_booking_store.py` (new) — booking store lifecycle, seed determinism, reset-on-restart, seat availability transitions
- `mcp-demo-app/tests/unit/test_booking_tools.py` (new) — per-tool happy/error paths, lifecycle violations, cancel-and-rebook, access-denied shape consistency
- `mcp-demo-app/tests/unit/test_mcp_router_booking.py` (new) — MCP route: booking tools in `tools/list` and `tools/call` dispatch with identity extraction
- `mcp-demo-app/tests/unit/test_tools.py` (modified) — greeting/tool-registry tests updated for the expanded registry and manifest (ten tools)
- `mcp-demo-app/tests/unit/test_mcp_router.py` (modified) — greeting-tool route tests updated only for the expanded tool counts (regression preserved)
- Frontend layers — not applicable to this change: no frontend code is touched, so no Vitest tests; the Playwright E2E layer is likewise not exercised. Live-platform validation (Hub discovery, permission gating, confirm-before-write, scripted plan, dual-surface journey) is covered by the walkthrough's Live Validation Script and the manual demo rehearsal above.
