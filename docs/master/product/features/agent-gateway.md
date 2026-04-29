# Agent Gateway

## Overview
The Agent Gateway exposes agent types to external consumers and internal components via a standardized lifecycle protocol. It supports both HTTP and MCP transports, enabling secure, auditable interactions with agents throughout their operational lifecycle.

## Who Uses It
- Enterprise Admins: Configure agent exposure and monitor interactions
- Business Users: Interact with agents through supported protocols
- AI Agents: Participate in lifecycle-managed interactions

## What It Does
- Exposes agent types via a standard lifecycle protocol (init, request, question, answer, close)
- Supports both HTTP and MCP transports for agent communication
- Manages secure, auditable agent interactions
- Ensures lifecycle events are tracked and accessible

## Key Concepts
- **Lifecycle Protocol**: The standardized sequence of agent interaction events
- **HTTP Transport**: Communication with agents over HTTP
- **MCP Transport**: Communication with agents via the MCP protocol
- **Lifecycle Event Tracking**: Auditing all stages of agent interaction

## Acceptance Criteria
- Agent types are accessible via both HTTP and MCP transports
- All lifecycle events (init, request, question, answer, close) are tracked
- Interactions are secure and permission-controlled
- Lifecycle protocol is enforced for all agent communications
- All interactions are auditable and accessible from the UI
