# PRD: Airline Booking Demo (Scenario-Based MCP Demo)

## Epic Overview

The current MCP demo app proves identity propagation and tool-level access control with three trivial greeting tools, but it does not demonstrate what the Parthenon platform actually delivers to a business: an agent completing a realistic, multi-step workflow through governed tool calls. This epic adds a scenario-based airline travel-booking demo to the MCP demo app — searching flights, booking tickets, paying, checking in, selecting seats, and canceling — powered by minimal in-memory sample data and no real integrations. The scenario showcases the full platform story end-to-end: conversational agent flow, MCP tool calls through the Communication Hub, permissions/roles, the recent optimization work (scripted/optimized plans), and the agent client demo UI. It gives sales, demos, onboarding, and developers a single compelling narrative of "here is what an enterprise agent can safely do."

## Business Goals

- Reduce demo preparation time: a presenter can run the full booking scenario in under 10 minutes with the standard local setup
- Demonstrate platform value end-to-end: at least one complete user journey (search → book → pay → check in) executed purely by agent tool calls
- Showcase trust & governance: every booking (write) action visibly goes through the confirm-before-write approval flow
- Showcase the optimization work: at least one booking capability (e.g., check-in flow) demonstrated via a scripted/optimized plan for faster, deterministic execution
- Provide an onboarding reference: a new developer can understand agent + MCP Hub + client integration by following one runnable scenario

## Users & Personas

- **Sales / Pre-sales presenter** — needs an impressive, realistic demo of agent capabilities for prospects; wants zero setup friction and predictable outcomes
- **Prospective customer / evaluator** — wants to see how an agent handles a real workflow with permissions, confirmations, and auditability
- **New developer / integrator** — wants a worked example of registering an MCP server, exposing tools, granting roles/skills, and invoking the agent from the client demo app
- **Platform engineer (internal)** — wants a richer validation scenario for identity propagation, permission gating, and optimization behavior beyond hello-world tools

## User Stories

- As a presenter, I want to ask the agent to find flights between two cities on a date, so that I can show natural-language access to structured travel data.
- As a presenter, I want the agent to propose a booking and require my explicit confirmation before writing, so that I can demonstrate the platform's confirm-before-write governance.
- As a presenter, I want the agent to generate a payment link for a booked ticket, so that I can show an end-to-end commerce flow without real money movement.
- As a traveler (demo persona), I want to ask the agent for my ticket status, so that I can see read-only tool calls answered from the agent conversationally.
- As a traveler (demo persona), I want the agent to check me in and select a seat, so that I can see a multi-step task completed with several coordinated tool calls.
- As a traveler (demo persona), I want to cancel a booking with confirmation, so that I can see destructive actions are gated and auditable.
- As a platform engineer, I want at least one part of the flow executed via a scripted/optimized plan, so that I can demonstrate the optimization work reducing latency/LLM calls.
- As an evaluator, I want to run the same conversation through the agent client demo UI, so that I can see the agent is accessible both from the platform chat and third-party client surfaces.
- As an administrator, I want the booking tools permission-gated via roles/skills, so that I can show an agent being denied a tool it has not been granted.

## Acceptance Criteria

- The demo app registers with the MCP Hub under its own slug and all airline tools are discovered and listed by the Hub
- An agent with the appropriate role/skill grants can:
  - Search flights by origin, destination, and date and return matching sample flights
  - Book a ticket only after presenting a confirmation preview and receiving user approval; rejection or timeout results in no booking
  - Generate a payment link for an existing booked ticket
  - Report ticket status (booked / paid / checked-in / cancelled) accurately
  - Check in a paid ticket and select a seat, with seat availability reflected in results
  - Cancel a booking only after confirmation, and the cancelled booking can be re-booked on the same flight (proves true state change)
- All sample data is in-memory and resets predictably; no external systems are called
- Tools not granted to the agent's role return a clear access-denied result that the agent communicates to the user
- A scripted/optimized plan covers at least one multi-tool capability and demonstrably executes without intermediate LLM reasoning steps
- The full scenario is completable end-to-end from both the Parthenon chat UI and the agent client demo app
- Every tool call is visible in execution logs / conversation history for audit during the demo

## Out of Scope

- Real airline APIs, real payments, or any external integrations
- Persistent storage of bookings across restarts
- New platform features — this demo only consumes existing capabilities
- Production-grade security review of the sample data or tools
- UI changes to the Parthenon management UI
- Multi-tenant or multi-airline data modeling

## Dependencies & Constraints

- Requires a running Parthenon backend (Control Center, Communication Hub, Agent Runtime) with Keycloak identity realms configured
- Requires the MCP Hub registration/sync flow available (same as current demo app)
- Requires the Communication Hub integration gateway enabled for the agent client demo path
- Requires a configured model to drive the conversational agent
- Optimization (scripted plan) showcase depends on the existing script registry / optimized plan lifecycle being functional
- Sample seed data must stay minimal and fictional (no real airline names, fares, or personal data)
