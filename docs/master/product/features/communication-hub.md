# Communication Hub

## Overview
The Communication Hub provides centralized, reliable message routing between the Web UI, agents, and other platform components. It maintains session context and supports real-time, auditable communication for all agent interactions.

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


## Key Concepts
- **Message Broker**: Central component for routing all platform messages
- **Session Context**: Maintains state and context for each communication session, including passthrough session type
- **Passthrough Session**: Session type where agent identity is automatically propagated to the MCP server, eliminating manual session selection
- **WebSocket**: Real-time, bidirectional communication channel
- **Agent-to-Agent Routing**: Direct messaging between agents


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
