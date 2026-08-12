# MCP Demo App — Product Requirements Document

## 1. Epic Overview

This change introduces a minimal Model Context Protocol (MCP) demo application that authenticates using the Keycloak ai_agent realm and exposes a single `helloWorld` tool. The primary goal is to validate the end-to-end flow of passing agent identity through the MCP ecosystem, ensuring that agent identities are recognized as first-class OIDC principals. This demo app will serve as a proof of concept for seamless integration with the Parthenon MCP Hub, enabling future expansion of agent-based capabilities across the enterprise AI framework.

## 2. Business Goals

- Demonstrate successful authentication of agent identities via Keycloak ai_agent realm in an MCP app
- Validate that agent identity is preserved and accessible throughout the MCP app flow
- Enable registration and integration of the demo MCP app with the Parthenon MCP Hub using a unique slug
- Provide a working example for partners and internal teams to reference when building MCP-compliant apps
- Reduce integration risk for future agent-based tools by proving the identity flow works as designed

## 3. Users & Personas

- **AI Platform Engineers**: Need to verify that agent identity flows are robust before onboarding new MCP apps
- **Solution Architects**: Require a reference implementation to guide integration of custom tools with the MCP Hub
- **Internal Product Teams**: Benefit from a working demo to accelerate development and reduce onboarding friction

## 4. User Stories

- As an AI platform engineer, I want to see a working MCP app that authenticates with the agent realm, so that I can confirm agent identity is handled correctly.
- As a solution architect, I want a simple demo app with a single tool, so that I can use it as a template for future MCP integrations.
- As a product team member, I want to register the demo app with the MCP Hub, so that I can validate the registration and tool sync process.

## 5. Acceptance Criteria

- User can launch the MCP demo app and authenticate using a Keycloak agent identity (ai_agent realm)
- The app exposes a single `helloWorld` tool, visible and callable after authentication
- Agent identity is passed and accessible throughout the app's flow (from login to tool execution)
- The demo app can be registered with the Parthenon MCP Hub using a unique slug, and the tool appears under the correct namespace
- Documentation is provided to guide registration and integration steps
- Out-of-scope features (see below) are not present in the demo app

## 6. Out of Scope

- No user realm authentication or support for non-agent identities
- No additional tools or business logic beyond the `helloWorld` demo
- No production-grade error handling, scalability, or security hardening
- No integration with external data sources or APIs
- No UI/UX enhancements beyond minimal demo requirements

## 7. Dependencies & Constraints

- Requires a functioning Keycloak instance with ai_agent realm configured
- Depends on the Parthenon MCP Hub's ability to register and sync MCP apps via unique slugs
- Must align with existing OIDC/OAuth2 authentication flows and agent identity conventions
- Demo app is for validation and reference only; not intended for production use
