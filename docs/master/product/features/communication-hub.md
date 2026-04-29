# Communication Hub

## Overview
The Communication Hub provides centralized, reliable message routing between the Web UI, agents, and other platform components. It maintains session context and supports real-time, auditable communication for all agent interactions.

## Who Uses It
- Enterprise Admins: Monitor and troubleshoot message flows
- Business Users: Engage in real-time conversations with agents
- AI Agents: Exchange messages with users and other agents

## What It Does
- Routes messages between users, agents, and platform components
- Maintains session context for all communications
- Supports real-time messaging via WebSocket
- Enables agent-to-agent message routing

## Key Concepts
- **Message Broker**: Central component for routing all platform messages
- **Session Context**: Maintains state and context for each communication session
- **WebSocket**: Real-time, bidirectional communication channel
- **Agent-to-Agent Routing**: Direct messaging between agents

## Acceptance Criteria
- Messages are reliably routed between all platform components
- Session context is maintained for each conversation
- Real-time messaging is available via WebSocket
- Agent-to-agent communication is supported and auditable
- All message flows are accessible for monitoring and troubleshooting
