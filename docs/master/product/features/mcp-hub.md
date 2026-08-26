# MCP Hub

## Overview
The MCP Hub enables Parthenon to connect with external tool servers, synchronize available tools, and manage secure, identity-bound sessions for tool execution. It centralizes tool integration and session management, ensuring that all tool usage is governed and auditable. The MCP Hub also accepts connections from third-party AI agents (such as Claude Code or Cursor) via API key authentication, granting external agents access to the same skills, SOPs, and tools under the same role-based permission model used for internal agents. Tools proxied from registered MCP servers are now reachable by external MCP clients over the standard MCP protocol (initialize / tools/list / tools/call), in addition to internal Agent Runtime tool calls.

## Who Uses It
- Enterprise Admins: Register and configure MCP servers, manage sessions and credentials
- AI Agents: Access tools via authorized sessions
- Compliance Auditors: Review tool usage and session mappings


## What It Does
- Registers external MCP servers with unique identifiers
- Synchronizes available tools from each server into a central repository
- Supports multiple named sessions per server, each with identity and credential binding
- **Supports "passthrough" session type:** Admins can designate an MCP server as passthrough, enabling direct agent identity propagation (no explicit session selection required)
- Supports designating a default session per server for predictable tool routing
- Automatically treats a server's sole session as the default, requiring no manual action
- Maps sessions or passthrough configuration to agent identities or roles for secure tool access
- Exposes proxied MCP server tools to external MCP clients over the standard MCP protocol (initialize / tools/list / tools/call), in addition to internal Agent Runtime tool calls — both governed by the same role-based permission resolution



## Key Concepts
- **MCP Server**: An external tool hub registered with Parthenon
- **Tool Sync**: Importing and updating available tools from MCP servers
- **Session Management**: Creating and managing named sessions with identity bindings, or configuring passthrough session type for compatible servers. Supports designating one session per server as the default for predictable tool routing and sync behavior.
- **Default Session**: The session used for sync and tool calls when no specific session is specified. Each MCP server has exactly one default session — explicitly set by the admin, or automatically assigned when only one session exists.
- **Passthrough Session**: A session type where agent identity is automatically forwarded to the MCP server, eliminating manual session selection
- **Credential Binding**: Associating credentials with sessions for secure access (not required for passthrough)
- **Session-to-Role Mapping**: Assigning sessions or passthrough configuration to specific agent roles or identities; performed inline within the Edit Agent Role dialog via dynamic dropdowns that appear based on selected SOPs/Skills — no separate popup dialog
- **Agent Identity Validation**: All MCP apps must support agent identities as first-class OIDC principals. The MCP Demo App serves as a reference implementation and validation artifact, now validating both dual-identity propagation (agent and user identities forwarded independently by the Communication Hub) and per-identity `mcp_role` claim-based tool access control.


## Acceptance Criteria
- Admins can register MCP servers and view their status
- The MCP server list shows exactly one System entry, visually distinct from user-registered servers
- Admins can configure an MCP server to use a passthrough session type (no explicit session selection required)
- All available tools are synchronized and listed in the platform
- Sync succeeds when tools/list works, even if the initialize handshake has warnings
- The sync action is only available when at least one session is configured for the server
- Sessions can be created, named, and bound to identities or roles, or passthrough can be enabled for compatible servers
- Admins can designate a default session; sole sessions are automatically the default
- The default session is visibly indicated and used for sync and tool calls
- Credentials are securely managed and auditable (where applicable)
- Tool usage is tracked per session or passthrough configuration and accessible for audit
- When passthrough is enabled, agent identity is automatically forwarded to the MCP server
- UI clearly distinguishes passthrough session type from traditional session selection
- No regression in existing session-based workflows
- MCP Demo App is available as a reference for validating dual-identity propagation (both agent and user identities), passthrough session type, per-identity `mcp_role` claim-based tool access control, and tool registration flows

## Out of Scope
- Changes to underlying authentication protocols or OIDC/OAuth2 flows
- Support for passthrough with legacy MCP servers that do not accept agent identity via JWT
- Backend implementation details, API specifications, or database schema changes

## Dependencies & Constraints
- Requires MCP servers to support agent identity propagation via JWT (e.g., mcp-demo-app)
- Relies on existing OIDC/OAuth2 infrastructure and agent identity management
- UI/UX changes must maintain clarity for both passthrough and traditional session types
