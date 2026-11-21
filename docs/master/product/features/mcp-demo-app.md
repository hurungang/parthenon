# MCP Demo App — Product Requirements Document


## 1. Epic Overview

The MCP Demo App introduces a minimal Model Context Protocol (MCP) application that authenticates using the Keycloak ai_agent realm and exposes three greeting demo tools (`helloWorld`, `helloAgent`, `helloUser`). Its purpose is to validate the end-to-end flow of dual identity within the MCP ecosystem — agent identity (from `Authorization` header) and user identity (from `X-User-Identity` header) — including passthrough session type, per-identity `mcp_role` claim-based access control, and ensuring both agents and users are recognized as first-class OIDC principals. This proof of concept enables seamless integration with the Parthenon MCP Hub and provides a reference for future agent-based capabilities.

The app also offers a **second demo mode**: a fictional airline travel-booking scenario — flight search, ticket booking, payment link, ticket status, check-in, seat selection, and cancellation — backed by minimal in-memory sample data and no external systems. Where the greeting tools prove identity plumbing, the booking scenario tells the business story: a conversational agent completing a realistic multi-step workflow through governed tool calls, with confirm-before-write governance on every state-changing step, a visible permission-denial path, and a scripted (zero-model) execution of the check-in capability. It is runnable end to end from both the platform chat UI and the agent client demo app. See the [Airline Booking Demo walkthrough](../../reference/airline-booking-demo-walkthrough.md).

## 2. Business Goals

- Demonstrate successful authentication of agent identities via Keycloak ai_agent realm in an MCP app
- Demonstrate successful authentication of user identities via Keycloak user realm in an MCP app
- Validate that both agent and user identities are preserved and accessible throughout the MCP app flow
- Prove that per-identity `mcp_role` claim-based tool access control works as designed
- Enable registration and integration of the demo MCP app with the Parthenon MCP Hub using a unique slug
- Provide a working example for partners and internal teams to reference when building MCP-compliant apps with dual-identity support
- Reduce integration risk for future agent-based tools by proving the dual-identity flow works as designed
- Give sales, onboarding, and evaluators one runnable business narrative — search, book, pay, check in — completed entirely by agent tool calls in a single short session
- Showcase governance in motion: every state-changing booking action passes the confirm-before-write approval, and an ungranted tool returns a clear denial the agent relays
- Keep the scenario frictionless and safe: fictional data only, held in memory, reset deterministically, with no external calls and no platform database writes

## 3. Users & Personas

- **AI Platform Engineers**: Need to verify the full end-to-end dual-identity flow is correct before deploying MCP apps to production
- **Security Architects**: Require proof that per-identity `mcp_role` access control gates are enforced at the tool level
- **Solution Architects**: Require a reference implementation to guide integration of custom tools with the MCP Hub
- **MCP Tool Developers**: Use the demo app as a template for implementing dual-identity-aware tools with claim-based authorization
- **Compliance Auditors**: Rely on the demo app's predictable access-control behavior as evidence of the platform's identity governance
- **Sales / Pre-sales Presenter**: Needs an impressive, realistic demonstration of agent capability with zero setup friction and predictable outcomes
- **Prospective Customer / Evaluator**: Wants to see an agent handle a real workflow with permissions, confirmations, and auditability
- **New Developer / Integrator**: Wants a worked example of registering an MCP server, exposing tools, granting roles and skills, and invoking the agent from a client application

## 4. User Stories

- As an AI platform engineer, I want a tool that greets the **agent** identity and is only callable when the agent has the `demo_agent` role, so that I can prove agent-identity passthrough and role enforcement work.
- As an AI platform engineer, I want a tool that greets the **user** identity and is only callable when the user has the `demo_user` role, so that I can prove user-identity passthrough and role enforcement work.
- As a security architect, I want attempting to call `helloAgent` without the `demo_agent` role to produce a clear access-denied result, so that I know per-identity gating is active.
- As a solution architect, I want a simple demo app with three greeting tools demonstrating dual-identity validation, so that I can use it as a template for future MCP integrations.
- As a product team member, I want to register the demo app with the MCP Hub, so that I can validate the registration and tool sync process across all ten tools (three greeting + seven booking).
- As a presenter, I want to ask the agent to find flights between two cities on a date, so that I can show natural-language access to structured travel data.
- As a presenter, I want the agent to propose a booking and require my explicit confirmation before anything is written, so that I can demonstrate confirm-before-write governance on a real business action.
- As a demo traveler, I want the agent to generate a payment link, report my ticket status, check me in with a selected seat, and cancel with confirmation, so that I can see a multi-step journey completed and every stage reflected accurately.
- As a platform engineer, I want at least one part of the journey executed by a scripted plan rather than step-by-step model reasoning, so that I can show the optimization work in a business context.
- As an evaluator, I want the same conversation to work from the agent client demo app, so that I can see the agent exposed through both first-party and third-party surfaces.
- As an administrator, I want the booking tools grouped into skills granted through an agent role, so that I can show an agent being refused a tool it was not granted.


## 5. Acceptance Criteria

### New Tools

- **`helloAgent` tool is callable** when the agent identity contains an `mcp_role` claim of `demo_agent`, and the response includes the agent's identity claims (subject, realm, mcp_role)
- **`helloAgent` tool returns an access-denied error** when the agent identity does NOT contain `demo_agent` in the `mcp_role` claim
- **`helloAgent` tool returns an access-denied error** when no agent identity is forwarded (missing or invalid)
- **`helloUser` tool is callable** when the user identity contains an `mcp_role` claim of `demo_user`, and the response includes the user's identity claims (subject, realm, mcp_role)
- **`helloUser` tool returns an access-denied error** when the user identity does NOT contain `demo_user` in the `mcp_role` claim
- **`helloUser` tool returns an access-denied error** when no user identity is forwarded (missing or invalid)

### Existing Tool (No Regression)

- **`helloWorld` tool continues to work** as before — it surfaces the agent identity and is not gated by `mcp_role` claims
- **The greeting set still lists exactly three tools** — `helloWorld`, `helloAgent`, and `helloUser` — with their correct descriptions and input schemas (the airline scenario's tools are a separate set; see below)

### Tool-Level Access Control

- Each tool independently validates only its required identity's claims — `helloAgent` does not inspect user claims, and `helloUser` does not inspect agent claims
- Identity tokens are validated for authenticity before claim inspection; invalid tokens produce an auth error regardless of claim content

### MCP Hub Integration

- The demo app can be registered with the Parthenon MCP Hub using the existing `demo` slug, and the greeting tools sync and appear under the correct namespace; the airline tools are synced through the same registration and sync flow
- Demo app supports passthrough session type, validating dual-identity propagation without explicit session selection

### Documentation

- README includes step-by-step instructions for configuring both the user realm and agent realm with the required `mcp_role` claims
- README explains how to set up test identities with `demo_agent` and `demo_user` roles
- README describes how to verify each tool's access control behavior after setup

### Airline Booking Scenario (Second Demo Mode)

- The demo app registers with the MCP Hub under its own slug and all airline tools are discovered and listed by the Hub alongside the existing greeting tools
- With the appropriate role and skill grants, an agent can search flights by origin, destination, and date and return matching sample flights with fares and seat availability
- A booking is written only after a confirmation preview is presented and approved; rejection or expiry of that confirmation leaves the store untouched and the agent reports nothing was booked
- The agent can generate a fictional payment link for a booked ticket, report ticket status accurately (booked / paid / checked in / cancelled), check in a paid booking, select a seat with availability reflected in the result, and cancel a booking after confirmation
- Cancelling frees the seats held by that booking, so the same seats can be booked again — proving a real state change rather than a hidden record
- A business-rule refusal (such as a booking containing only children or infants) returns a structured, readable error that the agent relays, and adding an adult produces a valid multi-passenger booking
- A tool not granted through the agent's role or skills returns a clear access-denied result that the agent communicates, with no state change
- One multi-tool capability (check-in with seat selection) is demonstrably completable through a scripted plan with no intermediate model reasoning steps
- All booking data is in-memory and fictional; restarting the demo app restores exactly the seed state, including the same repeatable booking references
- The full journey is completable end to end from both the Parthenon chat UI and the agent client demo app
- Every tool call in the journey is visible in execution logs and conversation history for audit during a demo

## 6. Out of Scope

- Changes to the Communication Hub's identity forwarding logic or header construction
- Changes to the Control Center's permission resolution or token management
- Changes to Keycloak realm configuration (realms must be configured manually or via existing tooling)
- New database tables, migrations, or persistent storage in the demo app
- Frontend UI changes in the Parthenon Web UI
- Role assignment workflows or UI for demo identities
- Production-grade error handling, scalability, or security hardening beyond the existing demo app standard
- Support for non-JWT identity propagation methods
- Real airline systems, real payments, or any external integration — the scenario is fictional throughout
- Persisting bookings across restarts, or modelling multiple airlines, tenants, or real fare/personal data
- New platform capabilities: the scenario consumes existing confirmation, permission, and scripted-execution behavior only
- Production-grade security review of the sample data or demo tools

## 7. Dependencies & Constraints

- Requires a functioning Keycloak instance with both the user realm and `ai_agents` realm configured
- Requires the Parthenon Communication Hub to forward both user identity and agent identity as distinct JWT tokens in request headers
- Requires the existing MCP Demo App's authentication infrastructure
- All `mcp_role` claim values (`demo_agent`, `demo_user`) must be configured in Keycloak as client roles or realm roles on the respective identity principals
- Depends on the Parthenon MCP Hub's ability to register and sync MCP apps via unique slugs
- The airline scenario additionally depends on a configured model for the conversational agent, a demo agent role granting the booking skills (plus a restricted variant omitting at least one tool), and a scripted plan for the check-in capability — all produced from existing platform features
- The demo app is a validation and reference artifact — not intended for production use
