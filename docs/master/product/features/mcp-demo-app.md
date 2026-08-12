# MCP Demo App — Product Requirements Document


## 1. Epic Overview

The MCP Demo App introduces a minimal Model Context Protocol (MCP) application that authenticates using the Keycloak ai_agent realm and exposes three demo tools (`helloWorld`, `helloAgent`, `helloUser`). Its purpose is to validate the end-to-end flow of dual identity within the MCP ecosystem — agent identity (from `Authorization` header) and user identity (from `X-User-Identity` header) — including passthrough session type, per-identity `mcp_role` claim-based access control, and ensuring both agents and users are recognized as first-class OIDC principals. This proof of concept enables seamless integration with the Parthenon MCP Hub and provides a reference for future agent-based capabilities.

## 2. Business Goals

- Demonstrate successful authentication of agent identities via Keycloak ai_agent realm in an MCP app
- Demonstrate successful authentication of user identities via Keycloak user realm in an MCP app
- Validate that both agent and user identities are preserved and accessible throughout the MCP app flow
- Prove that per-identity `mcp_role` claim-based tool access control works as designed
- Enable registration and integration of the demo MCP app with the Parthenon MCP Hub using a unique slug
- Provide a working example for partners and internal teams to reference when building MCP-compliant apps with dual-identity support
- Reduce integration risk for future agent-based tools by proving the dual-identity flow works as designed

## 3. Users & Personas

- **AI Platform Engineers**: Need to verify the full end-to-end dual-identity flow is correct before deploying MCP apps to production
- **Security Architects**: Require proof that per-identity `mcp_role` access control gates are enforced at the tool level
- **Solution Architects**: Require a reference implementation to guide integration of custom tools with the MCP Hub
- **MCP Tool Developers**: Use the demo app as a template for implementing dual-identity-aware tools with claim-based authorization
- **Compliance Auditors**: Rely on the demo app's predictable access-control behavior as evidence of the platform's identity governance

## 4. User Stories

- As an AI platform engineer, I want a tool that greets the **agent** identity and is only callable when the agent has the `demo_agent` role, so that I can prove agent-identity passthrough and role enforcement work.
- As an AI platform engineer, I want a tool that greets the **user** identity and is only callable when the user has the `demo_user` role, so that I can prove user-identity passthrough and role enforcement work.
- As a security architect, I want attempting to call `helloAgent` without the `demo_agent` role to produce a clear access-denied result, so that I know per-identity gating is active.
- As a solution architect, I want a simple demo app with three tools demonstrating dual-identity validation, so that I can use it as a template for future MCP integrations.
- As a product team member, I want to register the demo app with the MCP Hub, so that I can validate the registration and tool sync process with all three tools.


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
- **`tools/list` returns three tools**: `helloWorld`, `helloAgent`, and `helloUser` with their correct descriptions and input schemas

### Tool-Level Access Control

- Each tool independently validates only its required identity's claims — `helloAgent` does not inspect user claims, and `helloUser` does not inspect agent claims
- Identity tokens are validated for authenticity before claim inspection; invalid tokens produce an auth error regardless of claim content

### MCP Hub Integration

- The demo app can be registered with the Parthenon MCP Hub using the existing `demo` slug, and all three tools sync and appear under the correct namespace
- Demo app supports passthrough session type, validating dual-identity propagation without explicit session selection

### Documentation

- README includes step-by-step instructions for configuring both the user realm and agent realm with the required `mcp_role` claims
- README explains how to set up test identities with `demo_agent` and `demo_user` roles
- README describes how to verify each tool's access control behavior after setup

## 6. Out of Scope

- Changes to the Communication Hub's identity forwarding logic or header construction
- Changes to the Control Center's permission resolution or token management
- Changes to Keycloak realm configuration (realms must be configured manually or via existing tooling)
- New database tables, migrations, or persistent storage in the demo app
- Frontend UI changes in the Parthenon Web UI
- Role assignment workflows or UI for demo identities
- Production-grade error handling, scalability, or security hardening beyond the existing demo app standard
- Support for non-JWT identity propagation methods

## 7. Dependencies & Constraints

- Requires a functioning Keycloak instance with both the user realm and `ai_agents` realm configured
- Requires the Parthenon Communication Hub to forward both user identity and agent identity as distinct JWT tokens in request headers
- Requires the existing MCP Demo App's authentication infrastructure
- All `mcp_role` claim values (`demo_agent`, `demo_user`) must be configured in Keycloak as client roles or realm roles on the respective identity principals
- Depends on the Parthenon MCP Hub's ability to register and sync MCP apps via unique slugs
- The demo app is a validation and reference artifact — not intended for production use
