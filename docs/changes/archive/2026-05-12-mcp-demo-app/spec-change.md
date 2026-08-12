# MCP Demo App — Specification Delta

## 1. Affected Spec Areas

- MCP App Registration and Integration
- Agent Identity Authentication (OIDC/OAuth2, Keycloak ai_agent realm)
- Tool Discovery and Namespace Management in MCP Hub

## 2. New Capabilities

- Ability to register and integrate a minimal MCP app that authenticates as an agent
- Support for passing and validating agent identity across the full MCP app flow
- Exposure of a demo `helloWorld` tool under a unique MCP slug namespace

## 3. Modified Capabilities

- Clarifies that agent identities must be supported as first-class OIDC principals in all MCP app integrations
- Reinforces requirement for MCP Hub to recognize and namespace tools by registered slug

## 4. Removed Capabilities

- None; this change is additive and does not remove any existing capabilities

## 5. Spec Update Instructions

- Update master spec to include a reference to the MCP demo app as a validation artifact for agent identity flows
- Document the requirement for all MCP apps to support agent realm authentication and identity propagation
- Add example for registering a minimal MCP app and syncing its tools under a unique slug in the MCP Hub
- No changes to user realm, additional tools, or production features required
