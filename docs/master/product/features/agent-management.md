

# Agent Management (Unified AI Agent Navigation)

## Overview
Agent Management enables organizations to define, configure, and govern AI agent types, their roles, permissions, and operational lifecycles. With the unified "AI Agent" menu, all agent-related modules—including Agent Roles, Agent Identities, Agent Types, Agent Executions, and Agent Logs—are now grouped under a single, intuitive navigation structure. This consolidation improves discoverability, reduces user confusion, and streamlines access to all agent management capabilities. The system supports secure, role-based access control, explicit identity-role assignments, and centralized management of agent identities, model access, and permissions. All agent actions are fully auditable and observable, supporting compliance and operational transparency.

## Who Uses It
- Platform Administrators: Define agent types, roles, assign permissions, manage agent identities and model access
- Business Users: Launch agents, review results, and interact with agents
- Developers/Integrators: Integrate agents into workflows via the gateway
- Compliance & Audit Teams: Review agent definitions, assignments, and activity

## What It Does
- Provides a unified "AI Agent" menu with the following modules in order: Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs
- Supports creation and management of agent roles, with SOP/Skill permissions
- Enables explicit, many-to-many assignment of agent identities to roles, managed through the UI
- Provides guided forms for defining agent types, selecting identities, roles, models, and input/output options
- Manages agent identity authentication, token storage, refresh, and re-authentication flows
- Centralizes model provider configuration and selection for agent types
- Enforces max-instance limits for each agent type
- Manages agent execution lifecycle (creation, operation, termination)
- Provides real-time preview of allowed actions for each role
- Ensures all agent actions, assignments, and executions are logged and auditable
- Renames "Agent Instances" to "Agent Executions" throughout the platform for clarity
- Agent Executions view supports filtering by agent type, enabling users to focus on relevant runs
- Agent Types table includes columns for "Role" and "Identity", displaying the actual role and identity names for each agent type
- Clicking an agent type row opens a comprehensive dialog with:
	- Agent type details (basic info)
	- Plan preview tab (shows saved agent plan)
	- Execution logs tab (filtered by agent type)
	- Role and Identity names as clickable links, opening the corresponding view dialogs
- All dialogs (agent type details, role/identity view) are fully responsive and maximize content area
- Role and identity view dialogs include an "Edit" button for direct editing
- After closing any dialog, the parent table refreshes automatically to show updated data

## Key Concepts
- **AI Agent Menu**: A unified navigation entry grouping all agent-related modules for streamlined access
- **Agent Role**: A permission grouping for SOPs, Skills, and tools, assigned to agent identities
- **Identity-Role Assignment**: Explicit, many-to-many mapping between agent identities and roles, managed bidirectionally in the UI
- **Agent Type**: A defined class of agent with specific identity, role, and model configuration
- **Model Configuration**: Central management of model providers and enabled models for agent use
- **Execution Lifecycle**: The process of creating, running, and terminating agent executions (formerly instances)
- **Filtering**: Ability to filter agent executions by agent type for targeted review
- **Dialog-Based Details**: Agent type details, plan preview, and execution logs are accessible in a single, tabbed dialog
- **Column Visibility**: Role and identity columns are visible in the agent types table, with clickable names for direct navigation

## Acceptance Criteria
- The "AI Agent" top-level menu exists with the following five modules as child menus, in this order:
	1. Agent Roles
	2. Agent Identities
	3. Agent Types
	4. Agent Executions
	5. Agent Logs
- "Agent Instances" is renamed to "Agent Executions" everywhere in the UI and documentation
- Agent Executions view supports filtering by agent type (dropdown or similar)
- Agent Types table includes columns for "Role" and "Identity" displaying the actual role name and identity name for each agent type
- Clicking an agent type row opens a dialog with:
	- Agent type details (basic info)
	- Tab: Plan preview (shows saved agent plan)
	- Tab: Execution logs (list of executions for this agent type)
	- Role and Identity names displayed as clickable links; clicking opens the corresponding view dialog
- All dialogs (AgentTypeDetailsDialog, role/identity view dialogs) are fully responsive and match the width of PlanPreviewModal, maximizing content area
- Role and identity view dialogs include an "Edit" button to enable editing mode
- "Active instances" feature works: clicking agent type row shows current executions for that type
- After closing any dialog, parent table refreshes automatically to show updated data
- All changes are observable in the UI without requiring a page reload
- Error messages are clear and actionable if features fail

## Out of Scope
- Backend API or data model changes not required for navigation/UI improvements
- Major redesign of agent configuration or execution logic
- Changes to authentication or RBAC logic
- Non-agent-related navigation changes
- No new functionality or changes to Agent Roles or Agent Identities pages themselves (other than menu placement and view dialog edit button)

## Dependencies & Constraints
- Relies on existing agent type, execution, identity, and role data being available
- Must maintain compatibility with OIDC/OAuth2 and RBAC roles
- UI changes must not break existing agent workflows
- Requires OIDC-compliant identity provider (Keycloak, Azure EntraID)
- Agent identities must be managed in a separate, configurable realm within the identity provider
- Relies on existing MCP tool and Skill registration mechanisms
- Asynchronous session system must be available for agent execution and result tracking
- System must securely store and refresh agent OAuth tokens for runtime use
- Bootstrap process must initialize both user and agent realms in the identity provider
- All changes must comply with Parthenon’s security, audit, and observability conventions
