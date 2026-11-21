# Demo Cases: airline-booking-demo
<!-- Curated representative scenarios for product demo -->

## Demo Scenarios
| # | Feature | What it Shows | Source | Steps Ref |
|---|---------|---------------|--------|-----------|
| 1 | Search (read) | Flight discovery by origin/destination/date with fare & seat availability | Walkthrough §4 step 1 | Walkthrough §4.1 |
| 2 | Book (confirm-before-write) | Governance showcase: canonical preview, reject-then-approve, store untouched on rejection | Walkthrough §4 step 2 | Walkthrough §4.2 |
| 3 | Family booking + domain rule denial | Business-rule enforcement: child/infant-without-adult booking rejected with a structured error; adding an adult yields a multi-passenger booking with per-passenger seats and bags | Walkthrough §4 step 3 | Walkthrough §4.3 |
| 4 | Payment link | Fictional payment URL tied to the PNR; booking → paid regardless of passenger count | Walkthrough §4 step 4 | Walkthrough §4.4 |
| 5 | Ticket status | Read-only lifecycle accuracy (booked / paid / checked-in / cancelled) answered conversationally, by PNR | Walkthrough §4 step 5 | Walkthrough §4.5 |
| 6 | Check-in + seat (scripted zero-LLM flow) | Optimization showcase: `checkTicketStatus → checkInPassenger → selectSeat` executed in AR with zero intermediate LLM steps; whole-booking check-in via PNR; per-passenger seat selection; structured "seat occupied" error on pre-held 1A | Walkthrough §4 step 6 | Walkthrough §4.6 |
| 7 | Cancel (destructive + confirm) | Second confirmation preview; cancel frees the seats of all passengers; re-book proves true state change (not hiding) | Walkthrough §4 step 7 | Walkthrough §4.7 |
| 8 | Permission denied | Restricted role variant invokes ungranted tool; clear access-denied result relayed conversationally, no state change | Walkthrough §4 step 8 | Walkthrough §4.8 |

## Scenario Details

- **1. Search** — Goal: demonstrate the natural-language entry point. Expected: `demo____searchFlights` called with Aurora City / Meridian Falls / 2030-03-15; three FL-101/102/103 flights returned with fares and seat counts; visible in execution logs.
- **2. Book** — Goal: showcase confirm-before-write trust. Expected: canonical preview (`**Book ticket: Jane Doe**` + field table) before any call; **reject first** → `checkTicketStatus` confirms no booking, store untouched; then approve → booking `PKT001`, status `booked`, seat auto-assigned.
- **3. Family booking + domain rule denial** — Goal: show the domain enforcing the child/infant-without-adult rule. Expected: booking only children/infants returns a structured error ("A child or infant cannot travel without at least one adult on the same booking"); retry with an adult included → one PNR, all passengers listed with reserved seats and per-passenger bag counts.
- **4. Payment link** — Goal: read→write transition without real money. Expected: fictional payment URL record keyed by the PNR; the whole booking flips `booked → paid` (amount = fare × passenger count); no external calls.
- **5. Status** — Goal: conversational read-only query. Expected: `demo____checkTicketStatus` by PNR returns accurate stage for the booking plus per-passenger seats/bags; no side effects.
- **6. Check-in + seat (scripted)** — Goal: showcase zero-LLM scripted plan execution. Expected: the optimized plan runs all three tools in AR sandbox without intermediate LLM reasoning (visible in AR execution logs); check-in covers all passengers on the booking; selecting pre-held `1A` returns a structured "seat occupied" error, then `4A` succeeds for the named passenger and the seat map shows it occupied. Fallback to base plan (if triggered) still completes and is visible in telemetry.
- **7. Cancel** — Goal: destructive-action governance + true state change. Expected: confirmation preview; approve → status `cancelled`, the seats of all passengers freed; re-book same flight and select a freed seat to prove genuine state change (re-book collision check: no stale seat/payment-link records).
- **8. Permission denied** — Goal: governance/access-control showcase. Expected: restricted-role agent's ungranted call (e.g. cancel) returns a clear access-denied result the agent relays to the user; store unchanged.

## Note on Grep Patterns (Playwright)

**N/A for this change** — no Playwright e2e tests exist for the airline booking demo; demos run live against the full Parthenon stack per the walkthrough script (`docs/master/reference/airline-booking-demo-walkthrough.md`, live validation phases 6.1–6.6), not as automated browser tests. Automated coverage lives in the Python suite (`mcp-demo-app/tests/`).
