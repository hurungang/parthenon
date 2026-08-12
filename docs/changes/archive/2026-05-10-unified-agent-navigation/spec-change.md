# Unified Agent Navigation — Specification Change

## Affected Master Spec Areas
- Navigation & Layout (frontend/src/components/layout/)
- Agent Types (frontend/src/pages/agents/AgentTypesPage.tsx, related components)
- Agent Executions (formerly Agent Instances) (frontend/src/pages/agents/AgentJobPage.tsx)
- Agent Type Dialog/Details (new or updated component)
- Identity & Role Management (linked from agent type dialog)

## New Capabilities
- "AI Agent" top-level menu with the following five agent-related modules as children, in this order:
  - Agent Roles
  - Agent Identities
  - Agent Types
  - Agent Executions
  - Agent Logs
- Agent Executions view supports filtering by agent type
- Agent Types table includes columns for "Role" and "Identity" displaying the actual role name and identity name for each agent type
- Agent type row click opens dialog with:
  - Agent type details
  - Plan preview tab (shows saved plan)
  - Execution logs tab (filtered by agent type)
  - Role and Identity names displayed as clickable links; clicking opens the corresponding view dialog
- All dialogs (AgentTypeDetailsDialog, role/identity view dialogs) are fully responsive and match the width of PlanPreviewModal, maximizing content area
- Role and identity view dialogs include an "Edit" button to enable editing mode

## Modified Capabilities
- "Agent Instances" renamed to "Agent Executions" throughout UI and documentation
- "Active instances" feature fixed: clicking agent type row reliably shows executions for that type
- Parent tables auto-refresh after dialog actions (no manual reload)
- All dialogs use standardized width and are fully responsive
- Agent Types table now provides direct visibility of role and identity for each agent type
- Role and identity view dialogs now support editing via an "Edit" button
- Role and identity navigation from agent type details is via clickable names, not separate buttons

## Removed Capabilities
- Disconnected agent navigation (all agent modules now unified)
- Old "active instances" behavior (replaced by dialog-based view)

## Spec Update Instructions
- Update navigation spec to include "AI Agent" menu and all five child modules (Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs) in the correct order
- Update all references of "Agent Instances" to "Agent Executions" in master docs
- Add filtering requirements to Agent Executions spec
- Add dialog requirements to Agent Types spec: must show details, plan preview, execution logs, and clickable identity/role names that open view dialogs
- Add requirements for Agent Types table to include "Role" and "Identity" columns
- Specify that all dialogs (AgentTypeDetailsDialog, role/identity view dialogs) must match PlanPreviewModal width and be fully responsive
- Add requirement for "Edit" button in role and identity view dialogs
- Remove references to old, disconnected agent navigation patterns
- Ensure acceptance criteria for parent table refresh and error handling are included in relevant specs
