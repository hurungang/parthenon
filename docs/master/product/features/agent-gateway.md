

# Agent Gateway (Unified AI Agent Navigation)

## Overview
The Agent Gateway provides a centralized, secure, and observable entry point for agent execution, session tracking, and asynchronous result delivery. With the unified "AI Agent" menu, all agent execution, monitoring, and log features are accessible from a single navigation structure. The gateway enforces permission logic, validates identity-role assignments, and routes results to users and systems. All references to old, disconnected navigation patterns have been removed.

## Who Uses It
- Platform Administrators: Configure agent exposure, monitor interactions, and manage gateway policies
- Business Users: Launch and interact with agents through supported protocols
- Developers/Integrators: Integrate with the gateway to trigger agent sessions and receive results
- Compliance & Audit Teams: Monitor agent activity, review session histories, and validate compliance

## What It Does
- Exposes agent types via a standard lifecycle protocol (init, request, question, answer, close)
- Supports both HTTP and MCP transports for agent communication
- Manages secure, auditable agent interactions and session tracking
- Validates identity and role authorization for all agent actions
- Provides real-time updates for conversational agents and asynchronous result delivery for task agents
- Ensures all lifecycle events, system instructions, and user prompts are tracked and accessible
- Filters available tools and actions based on agent role permissions

## Key Concepts
- **Agent Gateway**: Central entry point for agent execution and result routing
- **Lifecycle Protocol**: The standardized sequence of agent interaction events
- **Session Tracking**: Monitoring agent activity, status, and results
- **Identity-Role Validation**: Ensuring only authorized identities perform actions
- **Execution Logging**: Capturing system instructions and user prompts for audit

## Acceptance Criteria
- Agent types are accessible via both HTTP and MCP transports
- All lifecycle events (init, request, question, answer, close) are tracked
- Interactions are secure, permission-controlled, and validated against identity-role assignments
- Lifecycle protocol is enforced for all agent communications
- All interactions, system instructions, and user prompts are auditable and accessible from the UI
- Real-time updates are provided for conversational agents; asynchronous result delivery for task agents

## Out of Scope
- Direct database access or bypassing the gateway for agent execution
- Custom agent code or plugin upload

## Dependencies & Constraints
- Requires OIDC-compliant identity provider
- Relies on asynchronous session system for agent execution and result tracking
- All changes must comply with Parthenon’s security, audit, and observability conventions
