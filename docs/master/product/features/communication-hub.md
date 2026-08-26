# Communication Hub

## Overview
The Communication Hub provides centralized, reliable message routing between the Web UI, agents, and other platform components. It maintains session context and supports real-time, auditable communication for all agent interactions. It also hosts a full MCP protocol server for external third-party agents, accepting both certificate-based authentication (for internal Agent Runtime instances) and API key authentication (for external agents). External MCP clients — such as GitHub Copilot, Claude Desktop, or Cursor — connect over the standard MCP protocol (initialize / tools/list / tools/call) to discover and invoke the tools their bound role permits.

## Who Uses It
- Enterprise Admins: Monitor and troubleshoot message flows
- Business Users: Engage in real-time conversations with agents
- AI Agents: Exchange messages with users and other agents


## What It Does
- Routes messages between users, agents, and platform components
- Maintains session context for all communications, including passthrough session type where agent identity is forwarded directly to compatible MCP servers
- Supports real-time messaging via WebSocket
- Enables agent-to-agent message routing
- Surfaces guardrail-related session outcomes so operations teams can separate policy stops from functional failures during triage
- Exposes a full MCP protocol server (initialize / tools/list / tools/call) so external MCP clients can connect over the standard protocol, authenticate with an API key, and invoke permitted tools
- Authenticates external third-party agents via API keys (Bearer token or query parameter) for MCP protocol access
- Resolves API key authentication to the bound agent identity, role, and permissions via Control Center's internal API
- Provides the `load_skills` system tool for agents to discover all accessible skills and SOPs with full tool definitions, input/output schemas, and `updated_at` timestamps
- Retains the existing REST `/mcp/tools/load_skills` skill-discovery endpoint for backward compatibility


## Key Concepts
- **Message Broker**: Central component for routing all platform messages
- **Session Context**: Maintains state and context for each communication session, including passthrough session type
- **Passthrough Session**: Session type where agent identity is automatically propagated to the MCP server, eliminating manual session selection
- **WebSocket**: Real-time, bidirectional communication channel
- **Agent-to-Agent Routing**: Direct messaging between agents
- **API Key Authentication**: External agents authenticate to the Communication Hub's MCP endpoint using a Bearer token or query parameter. The Communication Hub validates the key against Control Center's internal API and resolves the bound agent identity role and permissions, then injects the identity token into proxied MCP requests without exposing it to the external agent.
- **MCP Protocol Server**: The Communication Hub's first-class MCP protocol interface. External MCP clients complete a standard handshake (initialize), list the tools they are permitted to use (tools/list), and invoke them (tools/call). Both system tools (such as `load_skills`) and MCP tools proxied from registered MCP servers are exposed through this single interface, governed by the same role-based permission resolution used for internal agents.
- **load_skills System Tool**: A built-in tool that returns all skills and SOPs the authenticated agent is permitted to access, with full tool definitions, input/output schemas, and `updated_at` timestamps. Supports an optional `since` parameter for incremental sync — only skills updated after the given timestamp are returned, enabling efficient local caching by external agents.


## Central Tool Router

The Communication Hub acts as the **central router for all tool calls** made by agents during execution. Every tool call — whether targeting a built-in platform tool or an external MCP server tool — is forwarded by the Agent Runtime to the Communication Hub, which resolves the appropriate handler using the unified `server____tool` naming convention.

- Built-in system tools (prefixed `system____`) are handled directly by the Communication Hub's internal system tool handlers. `system____human_intervene` tool calls are routed to Control Center for persistence and then relayed back to Agent Runtime as a suspend signal.
- MCP server tools (prefixed with the server name) are forwarded to the MCP Hub for proxying to the registered external server
- The Agent Runtime contains no routing logic — all routing decisions are made by the Communication Hub

This design centralizes routing, ensures consistent authorization, and allows new tool types to be added without changes to agent execution code.

## Acceptance Criteria
- Messages are reliably routed between all platform components
- Session context is maintained for each conversation, including passthrough session type
- When passthrough session is configured, agent identity is automatically forwarded to the MCP server
- UI clearly distinguishes passthrough session type from traditional session selection
- Real-time messaging is available via WebSocket
- The Communication Hub relays intervene response control messages from Web UI to Control Center and resume signals from Control Center to Agent Runtime
- Agent-to-agent communication is supported and auditable
- Guardrail stop outcomes are visible in communication-related operational views for fast incident classification
- All message flows are accessible for monitoring and troubleshooting
- External agents can authenticate via API key using Bearer token or query parameter
- External MCP clients can connect and complete a standard MCP handshake (initialize) using an existing API key
- After a successful handshake, external clients can list the tools they are permitted to use (tools/list), including system tools and MCP tools proxied from registered MCP servers
- External clients can invoke a permitted tool (tools/call) and receive the tool's result
- Unauthorized tool calls from external clients are rejected based on the bound role's permissions
- Invalid or revoked API keys receive a clear authentication error response
- External agents receive only the skills and tools granted by their bound role, enforced identically to internal agents
- External agents never receive the underlying identity token — only the Communication Hub holds it for proxying
- The `load_skills` system tool returns all permitted skills with `updated_at` timestamps
- The `load_skills` tool supports a `since` parameter for incremental sync of only updated skills
- The existing REST `/mcp/tools/load_skills` endpoint continues to work for current consumers
- Internal Agent Runtime mTLS certificate authentication is unchanged
- All API key authentication events (success and failure) are logged for security monitoring

## Out of Scope
- Direct database access from the Communication Hub (all data access is proxied through Control Center)
- Identity token issuance or storage (tokens are resolved by Control Center and injected per tool call)
- Agent execution logic (owned by Agent Runtime)
- Low-level transport and protocol implementation details
