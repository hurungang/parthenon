# Passthrough Sessions — Product Requirements Document (PRD)

## 1. Epic Overview
The current Parthenon MCP Hub workflow requires users to manually select an MCP session when configuring roles or testing tools, which adds unnecessary friction for MCP servers capable of accepting agent identity directly via JWT forwarding. Introducing a "passthrough" session type will streamline the experience by allowing direct agent identity propagation, reducing configuration steps, and enabling seamless integration with compatible MCP servers. This enhancement supports a more intuitive and efficient workflow for both administrators and end users, aligning with modern identity propagation patterns.

## 2. Business Goals
- Reduce friction and manual steps in configuring and testing MCP servers that support agent identity passthrough
- Enable faster onboarding and integration of new MCP servers leveraging JWT-based agent identity
- Improve user satisfaction by simplifying the tool testing and role configuration process
- Ensure secure and accurate propagation of agent identity to MCP servers

## 3. Users & Personas
- **AI Platform Administrators:** Need to register and configure MCP servers efficiently, minimizing manual session management
- **Tool Developers:** Want to test MCP tools quickly using agent identities without extra session selection steps
- **Enterprise End Users:** Benefit from seamless, secure access to MCP-powered tools with minimal configuration overhead

## 4. User Stories
- As an administrator, I want to associate an MCP server with a passthrough session so that agent identity is automatically forwarded without explicit session selection.
- As a tool developer, I want to test passthrough-type MCP servers by selecting an agent identity, so that I can validate identity propagation without managing sessions.
- As an end user, I want my agent identity to be securely and transparently propagated to compatible MCP servers, so that my access and permissions are enforced correctly.

## 5. Acceptance Criteria
- Administrators can configure an MCP server to use a passthrough session type (no explicit session selection required)
- When a passthrough session is configured, the Communication Hub automatically forwards the executing agent's identity to the MCP server
- Tool registry test feature allows selection of agent identity for passthrough-type MCP servers (no session selection shown)
- End-to-end flow: agent identity is correctly propagated and recognized by the MCP server (e.g., mcp-demo-app)
- UI clearly distinguishes passthrough session type from traditional session selection
- Error handling: system provides clear feedback if passthrough is misconfigured or unsupported by the MCP server
- No regression in existing session-based workflows

## 6. Out of Scope
- Changes to underlying authentication protocols or OIDC/OAuth2 flows
- Support for passthrough with legacy MCP servers that do not accept agent identity via JWT
- Backend implementation details, API specifications, or database schema changes

## 7. Dependencies & Constraints
- Requires MCP servers to support agent identity propagation via JWT (e.g., mcp-demo-app)
- Relies on existing OIDC/OAuth2 infrastructure and agent identity management
- UI/UX changes must maintain clarity for both passthrough and traditional session types
