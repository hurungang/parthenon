# MCP Dual-Identity Tools — Product Requirements Document (PRD)

## 1. Epic Overview

The current MCP Demo App validates only a single agent identity via its `helloWorld` tool, but the Parthenon Communication Hub actually forwards **two** identities on every MCP tool call — the user identity (who made the request) and the agent identity (who executes). Without validating both identities end-to-end, the platform cannot prove that per-identity access control works correctly in production. This epic extends the MCP Demo App with two new tools (`helloAgent` and `helloUser`) that individually validate each identity and enforce `mcp_role`-based access control, providing a definitive reference proving the dual-identity passthrough and permission enforcement model functions correctly.

## 2. Business Goals

- Prove that **both** the user identity and agent identity are correctly forwarded to MCP servers by the Communication Hub
- Demonstrate that per-identity `mcp_role` claim-based tool access control works as designed
- Provide a complete reference implementation of dual-identity validation for teams building MCP-compliant apps
- Reduce enterprise onboarding risk by eliminating ambiguity about which identity drives tool authorization
- Enable platform engineers to self-validate the full identity propagation chain without manual log inspection

## 3. Users & Personas

- **AI Platform Engineers**: Need to verify the end-to-end dual-identity flow is correct before deploying MCP apps to production
- **Security Architects**: Require proof that per-identity `mcp_role` access control gates are enforced at the tool level
- **MCP Tool Developers**: Use the demo app as a template for implementing dual-identity-aware tools with claim-based authorization
- **Compliance Auditors**: Rely on the demo app's predictable access-control behavior as evidence of the platform's identity governance

## 4. User Stories

- As an AI platform engineer, I want a tool that greets the **agent** identity and is only callable when the agent has the `demo_agent` role, so that I can prove agent-identity passthrough and role enforcement work.
- As an AI platform engineer, I want a tool that greets the **user** identity and is only callable when the user has the `demo_user` role, so that I can prove user-identity passthrough and role enforcement work.
- As a security architect, I want attempting to call `helloAgent` without the `demo_agent` role to produce a clear access-denied result, so that I know per-identity gating is active.
- As an MCP tool developer, I want updated setup documentation that explains how to configure both realms and identities for dual-identity testing, so that I can replicate the setup in my own environment.

## 5. Acceptance Criteria

### New Tools

- **`helloAgent` tool is callable** when the agent identity JWT contains an `mcp_role` claim of `"demo_agent"`, and the response includes the agent's identity claims (sub, realm, mcp_role)
- **`helloAgent` tool returns an access-denied error** when the agent identity JWT does NOT contain `"demo_agent"` in the `mcp_role` claim
- **`helloAgent` tool returns an access-denied error** when no agent identity JWT is forwarded (missing or invalid)
- **`helloUser` tool is callable** when the user identity JWT contains an `mcp_role` claim of `"demo_user"`, and the response includes the user's identity claims (sub, realm, mcp_role)
- **`helloUser` tool returns an access-denied error** when the user identity JWT does NOT contain `"demo_user"` in the `mcp_role` claim
- **`helloUser` tool returns an access-denied error** when no user identity JWT is forwarded (missing or invalid)

### Existing Tool (No Regression)

- **`helloWorld` tool continues to work** as before — it surfaces the agent identity and is not gated by `mcp_role` claims
- **`tools/list` returns three tools**: `helloWorld`, `helloAgent`, and `helloUser` with their correct descriptions and input schemas

### Tool-Level Access Control

- Each tool independently validates only its required identity's claims — `helloAgent` does not inspect user claims, and `helloUser` does not inspect agent claims
- Identity JWTs are validated for signature, expiry, and issuer before claim inspection; invalid JWTs produce an auth error regardless of claim content

### Documentation

- Updated README includes step-by-step instructions for configuring both the user realm and agent realm with the required `mcp_role` claims
- Updated README explains how to set up test identities with `demo_agent` and `demo_user` roles
- Updated README describes how to verify each tool's access control behavior after setup

### General

- No changes required to the Parthenon Communication Hub or Control Center — this epic modifies only the MCP Demo App
- All three tools are available through the demo app's existing MCP interface
- Hub registration continues to use the existing `demo` slug and syncs all tools

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
- The demo app remains a validation and reference artifact — not intended for production use
