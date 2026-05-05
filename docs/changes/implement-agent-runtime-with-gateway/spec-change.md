# Specification Delta: Implement Agent Runtime with Gateway

## 1. Affected Spec Areas
- Product specification: Agent Management, Agent Runtime, Permission System, Communication Hub
- UX specification: Agent role/permission management UI, agent type configuration, session tracking interface (polling for task agents, chat UI for conversational agents)
- Architecture: Agent gateway, communication hub, session system powered by LangGraph
- Data model: Agent roles, agent types, session tracking entities

## 2. New Capabilities
- Ability to define and manage agent roles with SOP/Skill/MCP tool permissions
- Automatic permission inheritance: SOPs grant access to all underlying Skills and required MCP tools
- Real-time UI preview of allowed MCP tools for each role
- Agent type configuration supporting identity, role, system instruction, input/output options
- Agent identity creation via OAuth sign-in flow: Admins sign in to agent user accounts in a dedicated agent realm (e.g., `ai_agents`), and the system stores access and refresh tokens for runtime use
- System automatically refreshes agent tokens as needed for agent runtime operations
- Bootstrap process initializes the agent realm in the identity provider, mirroring user realm setup
- Launching agents as asynchronous sessions with input collection and result tracking (task agents with polling, conversational agents with chat UI powered by LangGraph)
- Centralized agent gateway for secure, auditable agent execution and result delivery (WebSocket support for conversational agents)
- Full auditability and observability of agent actions and session outcomes

## 3. Modified Capabilities
- Role management: Now includes SOP/Skill/MCP tool permission logic and preview
- Agent management: Now supports agent type definition, identity configuration (including OAuth-based agent user sign-in from a dedicated realm), and session-based execution with LangGraph
- Communication hub: Now acts as agent gateway, managing agent instance lifecycle and result routing
- Session system: Extended to support agent session tracking and asynchronous result updates (with LangGraph state management)

## 4. Removed Capabilities
- None. No existing user-facing capabilities are removed by this change.

## 5. Spec Update Instructions
- Update product spec in `docs/master/product/` to include agent runtime, gateway, and permission system enhancements
- Update UX spec in `docs/master/ux/` to cover new agent role management and agent type configuration screens
- Update architecture docs in `docs/master/architecture/` to reflect agent gateway, communication hub, and session system changes (LangGraph integration)
- Update data model in `docs/master/data-model/` to include agent roles, agent types, and session tracking entities
- Update QA/test plan in `docs/master/qa/` to cover new and modified user flows, permission logic, and auditability requirements
	- Update identity provider documentation to include agent realm initialization, OAuth-based agent user sign-in, and token management requirements
