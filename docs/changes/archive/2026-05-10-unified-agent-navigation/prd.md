# Unified Agent Navigation — Product Requirements Document (PRD)

## Epic Overview
The current agent-related modules in Parthenon are fragmented, making it difficult for users to manage and understand agent types, executions, and related features. This epic aims to unify and streamline the agent navigation experience by introducing a dedicated "AI Agent" menu, improving discoverability, renaming modules for clarity, adding filtering, and providing a comprehensive dialog for agent type details. The menu will now also include existing pages for Agent Roles and Agent Identities, consolidating all agent-related management under one menu. The goal is to make the UI more intuitive, efficient, and user-friendly for enterprise users managing AI agents at scale.

## Business Goals
- Increase user efficiency in managing agents and executions
- Reduce user confusion by consolidating agent-related features
- Improve discoverability of agent management and related actions
- Enable faster troubleshooting and monitoring of agent executions
- Support enterprise adoption by making the UI more intuitive

## Users & Personas
- **AI Platform Admins**: Need to configure, monitor, and troubleshoot agent types and executions
- **Data Scientists/Developers**: Want to quickly launch, review, and debug agent runs
- **Business Users/Operators**: Require clear access to agent status and outcomes

## User Stories
- As an admin, I want all agent-related modules under a single "AI Agent" menu, with Agent Roles and Agent Identities listed above Agent Types, so I can find and manage them easily
- As a user, I want to filter agent executions by agent type so I can focus on relevant runs
- As a user, I want to see agent type details and plan previews in a dialog for quick review
- As a user, I want the agent types table to show the role and identity for each agent type so I can quickly understand their configuration
- As an admin, I want to access identity and role management directly from agent type details by clicking the displayed identity or role name
- As a user, I want all dialogs (agent type details, role/identity view) to be fully responsive and as wide as possible for easier review
- As a user, I want to edit roles and identities directly from their view dialogs
- As a user, I want the "active instances" feature to work reliably when clicking agent type rows

## Acceptance Criteria
- "AI Agent" top-level menu exists with the following five modules as child menus, in this order:
  - Agent Roles
  - Agent Identities
  - Agent Types
  - Agent Executions
  - Agent Logs
- "Agent Instances" is renamed to "Agent Executions" everywhere in the UI
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
- Must align with enterprise UX standards and accessibility guidelines
