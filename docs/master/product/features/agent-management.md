

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
- Supports both traditional and passthrough session types for MCP servers; passthrough enables direct agent identity propagation without explicit session selection
- Provides a distinct guardrail profile view for every Agent Type, including iteration, delegation depth, delegated-step, timeout, and token-budget policies
- Allows authorized administrators to edit and save each Agent Type guardrail profile from the same governance workspace
- Presents token-budget values in k-token units with a default presentation value of 1000k for consistency across Agent Types
- Keeps guardrail editing compact by default so governance updates remain efficient in high-volume administration workflows
- Clicking an agent type row opens a comprehensive dialog with:
	- Agent type details (basic info)
	- Plan preview tab (shows saved agent plan)
	- Execution logs tab (filtered by agent type)
	- Sessions tab (visible only for conversation-type agents) — lists all conversation sessions with title, status, and last active time
	- Role and Identity names as clickable links, opening the corresponding view dialogs
- All dialogs (agent type details, role/identity view) are fully responsive and maximize content area
- Role and identity view dialogs include an "Edit" button for direct editing
- After closing any dialog, the parent table refreshes automatically to show updated data
- Conversation agent sessions:
	- Users can start new conversation sessions from the Sessions tab
	- Session titles are automatically generated from the first user prompt
	- Users can resume previous sessions with full conversation history
	- Users can end or archive sessions to manage their workspace
	- All sessions are user-scoped (users only see their own sessions)



## Key Concepts
- **AI Agent Menu**: A unified navigation entry grouping all agent-related modules for streamlined access
- **Agent Role**: A permission grouping for SOPs, Skills, and tools, assigned to agent identities
- **Identity-Role Assignment**: Explicit, many-to-many mapping between agent identities and roles, managed bidirectionally in the UI
- **Agent Type**: A defined class of agent with specific identity, role, and model configuration
- **Conversation Agent Session**: A persistent, user-named conversation with a conversation-type agent; includes automatic title generation, session management (start/resume/end/archive), and full turn history
- **Session Type**: Either traditional (named session) or passthrough (direct agent identity propagation to MCP server)
- **Model Configuration**: Central management of model providers and enabled models for agent use
- **Execution Lifecycle**: The process of creating, running, and terminating agent executions (formerly instances)
- **Filtering**: Ability to filter agent executions by agent type for targeted review
- **Dialog-Based Details**: Agent type details, plan preview, and execution logs are accessible in a single, tabbed dialog
- **Column Visibility**: Role and identity columns are visible in the agent types table, with clickable names for direct navigation
- **Agent Identity as OIDC Principal**: All agent identities must be supported as first-class OIDC principals. The MCP Demo App provides a reference implementation for this requirement.
- **Guardrail Profile**: A per-Agent-Type policy definition for cycle prevention, execution boundaries, delegation boundaries, timeout, and token-budget behavior


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
- Supports both traditional and passthrough session types for MCP servers; passthrough enables direct agent identity propagation without explicit session selection
- Clicking an agent type row opens a dialog with:
	- Agent type details (basic info)
	- Tab: Plan preview (shows saved agent plan)
	- Tab: Execution logs (list of executions for this agent type)
	- Tab: Sessions (visible only for conversation-type agents) — lists all user's conversation sessions with:
		- Session title (auto-generated from first user prompt)
		- Session status (active, closed, archived)
		- Last active timestamp
		- Actions: Resume, End, Archive
		- "Start New Conversation" entry point
	- Role and Identity names displayed as clickable links; clicking opens the corresponding view dialog
- All dialogs (AgentTypeDetailsDialog, role/identity view dialogs) are fully responsive and match the width of PlanPreviewModal, maximizing content area
- Role and identity view dialogs include an "Edit" button to enable editing mode
- "Active instances" feature works: clicking agent type row shows current executions for that type
- After closing any dialog, parent table refreshes automatically to show updated data
- Authorized administrators can open, edit, and save a distinct guardrail profile for each Agent Type
- Guardrail token budgets are shown in k-token units with 1000k as the default presentation value
- Guardrail editing remains compact by default and is easy to scan across large Agent Type portfolios
- After closing any create/edit/delete or guardrail dialog, parent tables refresh automatically to show updated policy values without manual page reload
- Conversation agent sessions work correctly:
	- Sessions tab appears only for agents with input_type = 'conversation'
	- Users can start new conversation sessions from the Sessions tab
	- Session titles are auto-generated from the first user prompt
	- Users can resume previous sessions with full turn history restored
	- Users can end sessions (status becomes 'closed', removed from active list)
	- Users can archive sessions (status becomes 'archived', excluded from default listing)
	- Sessions are user-scoped (users only see their own sessions)
	- Sessions list updates automatically after create/end/archive operations
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
