# Spec Delta: Airline Booking Demo (Scenario-Based MCP Demo)

## Affected Spec Areas

- `docs/master/product/features/mcp-demo-app.md` — demo app gains a scenario-based airline-booking toolset alongside the existing greeting tools
- `docs/master/product/features/mcp-hub.md` — no behavioral change; new server/tool set registered and synced via the existing flow
- `docs/master/product/features/agent-types.md` — a demo conversational agent type configured with a booking role referencing the new skills
- `docs/master/product/features/skill-management.md` — new demo skills (flight search, booking, payment link, ticket status, check-in, seat, cancel) and a demo agent role binding them
- `docs/master/product/features/agent-execution.md` — confirm-before-write approval flow exercised by booking/cancellation tools
- `docs/master/product/features/sandboxed-scripting.md` — optimization showcase: at least one capability demonstrated via a scripted/optimized plan
- `docs/master/product/features/agent-gateway.md` — unchanged behavior; scenario exercised through the existing agent client integration path
- `docs/master/reference/` — new demo scenario walkthrough reference (airline booking journey)

## New Capabilities

- **Airline booking scenario toolset (demo)**
  - A minimal set of fictional MCP tools backed by in-memory seed data: flight search, ticket booking, payment-link generation, ticket status, passenger check-in, seat selection, and booking cancellation
  - All data is sample-only and resets predictably; no real airlines, fares, or personal data
- **Guided booking journey with confirmation gating**
  - The agent walks a user through search → book → pay → check-in conversationally
  - Booking and cancellation are write actions requiring the canonical confirm-before-write approval before anything changes; rejection or timeout leaves data untouched
- **Permission-demonstration path**
  - Booking tools are grouped into skills granted via a demo agent role; an ungranted tool returns a clear access-denied result the agent relays to the user — showcasing role/permission governance
- **Optimization showcase**
  - At least one multi-tool capability (e.g., check-in with seat selection) is executable via a scripted/optimized plan, demonstrating faster deterministic execution with fewer LLM steps
- **Dual-surface demo experience**
  - The same scenario is completable from the Parthenon chat UI and from the agent client demo app, showing both first-party and third-party integration surfaces
- **Scenario walkthrough reference**
  - A reference doc describing the demo script: seed data, sample dialogue flow, and the platform capabilities each step highlights

## Modified Capabilities

- **MCP Demo App**
  - Before: standalone demo exposing three greeting tools to validate dual-identity propagation and tool-level role gating.
  - After: additionally exposes the airline-booking scenario toolset and seed data, self-registering with the Hub under its own slug as today; greeting tools remain unchanged for identity-focused demos.
- **Demo tool catalog**
  - Before: hello-world tools only; no business workflow available.
  - After: a realistic business workflow demonstrates conversational agents, permission gating, confirm-before-write, and optimized plans in one narrative.

## Removed Capabilities

- None.

## Spec Update Instructions

- Update **MCP Demo App** spec: add the airline-booking scenario as a second demo mode; describe the fictional toolset (search, book, payment link, status, check-in, seat, cancel), in-memory seed data, and predictable reset behavior.
- Update **Skill Management** spec: list the new demo skills and the demo agent role that binds them; note the intentional access-denied demonstration path for ungranted tools.
- Update **Agent Execution** spec: note the airline demo as the canonical worked example of the confirm-before-write approval flow (booking preview table, approval, rejection → no write).
- Update **Sandboxed Scripting** spec: reference the demo's scripted/optimized-plan showcase capability as a reference implementation scenario.
- Update **Agent Types** spec: mention the demo conversational agent type configuration (identity, role, model, conversation input) used by the scenario.
- Add a reference doc in `docs/master/reference/`: the airline-booking demo walkthrough — seed data summary, step-by-step demo script, capability highlights per step, and setup prerequisites (backend stack, Keycloak realms, integration gateway, client secret).
- Explicitly do NOT modify the MCP Hub, Agent Gateway, Agent Identity, or tenant isolation specs — platform behavior is unchanged; the demo only consumes existing capabilities.
