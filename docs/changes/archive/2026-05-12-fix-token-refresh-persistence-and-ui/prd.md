# Epic PRD: Fix Agent Identity Token Refresh Persistence & Add Token Status UI

## Epic Overview

Agent reliability is compromised when refreshed identity tokens are not persisted to the database, causing agents to operate with expired credentials and misleading UI status. Additionally, the current UI does not clearly indicate token validity or provide context-appropriate actions for both agent identities and MCP server sessions. This epic addresses the persistence bug and introduces improved token status visibility and actionable controls, ensuring administrators and users can trust agent authentication and take corrective action when needed.

## Business Goals

- Ensure all agent token refreshes are reliably persisted to the database
- Provide clear, real-time visibility into token status for agent identities and MCP OAuth sessions
- Empower users and admins to resolve token issues quickly with context-aware UI actions
- Reduce agent job failures due to expired or invalid tokens
- Improve overall trust and transparency in agent authentication flows

## Users & Personas

- **System Administrators:** Need to monitor and maintain agent connectivity and resolve authentication issues
- **Developers/Operators:** Rely on agents for automated tasks and require reliable execution
- **End Users:** Indirectly benefit from uninterrupted agent-driven workflows

## User Stories

- As an admin, I want agent token refreshes to be saved immediately, so agents always use valid credentials
- As an admin, I want to see the current token status for each agent identity and MCP OAuth session, so I can quickly identify issues
- As an admin, I want action buttons that match the token state (refresh or reauthenticate), so I can resolve problems efficiently
- As a user, I want agents to run jobs without failing due to expired tokens

## Acceptance Criteria

### Token Persistence Fix
- When an agent identity or MCP session token is refreshed, the new token and expiry are saved to the database immediately
- No scenario exists where a refreshed token is lost due to missing commit
- Automated and manual token refreshes both persist changes

### Agent Identity Token Status UI
- Agent Identities page displays token status (active, expired, expiring soon)
- If refresh token is valid, show green refresh button; clicking it refreshes the token and updates status immediately
- If refresh token is invalid/expired, show red reauthenticate button; clicking it prompts for reauth flow
- UI updates in real time after token refresh or reauth (no manual reload required)
- Error messages are clear if refresh or reauth fails

### MCP Session Token Status UI (OAuth Sessions Only)
- MCP server sessions list displays token status for OAuth-based sessions
- Same action button logic as agent identities: green refresh if refresh token valid, red reauth if not
- UI updates in real time after token refresh or reauth
- Non-OAuth sessions do not display token status or action buttons

### General
- All token status indicators and actions are accessible and usable on desktop and mobile
- No regression in existing agent or session management features

## Out of Scope

- Changes to authentication provider integrations
- Non-OAuth session types for MCP servers
- Backend API design or implementation details

## Dependencies & Constraints

- Requires accurate detection of token and refresh token validity
- Relies on existing backend models for agent identities and MCP sessions
- UI changes must not disrupt other admin workflows

## Success Metrics

- 100% of token refreshes are persisted (verified by audit/logs)
- Token status in UI matches actual backend state in all scenarios
- Admins can resolve token issues without backend intervention
- Reduction in agent job failures due to expired tokens (tracked over time)
- Positive feedback from admin users on clarity and usability of new UI features
