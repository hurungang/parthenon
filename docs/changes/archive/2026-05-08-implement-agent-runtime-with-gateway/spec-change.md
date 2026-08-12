# Specification Delta: Implement Agent Runtime with Gateway

## 1. Affected Spec Areas

**Product specification:**
- Agent Management: Users can define and manage agent roles, assign permissions for SOPs, Skills, and tools, and manage agent identities and their assignments.
- Agent Runtime: Powered by a modern agent framework (LangChain), supporting skill-based execution and advanced workflow orchestration.
- Permission System: Role-based access control for agents, with clear assignment and preview of allowed actions.
- Communication Hub: Central gateway for agent execution, session tracking, and secure result delivery.
- Model Configuration: Platform admins can configure, enable, and manage model providers and available models.
- Agent Instance Dashboard: Users can view, filter, and monitor all agent instances and their statuses.
- Execution Logging: All agent actions, system instructions, and user prompts are captured and visible for audit and compliance.

**UX specification:**
- Agent role and permission management UI: Allows explicit assignment of agent identities to roles and preview of allowed actions.
- Agent type configuration: Guided forms for selecting identities, roles, models, and input/output options.
- Session tracking interface: Supports both polling for task agents and chat UI for conversational agents.
- Model configuration management: Central interface for managing providers, credentials, and enabled models.
- Agent instance dashboard and detail view: Full visibility into agent activity, including execution history and conversation details.

**Architecture:**
- Agent gateway and communication hub: Secure, auditable management of agent execution and result routing.
- Session system: Tracks agent sessions and supports asynchronous updates.
- Model configuration backend: Manages provider credentials and available models securely.
- Enhanced execution logging: Captures all relevant agent actions and instructions for traceability.

**Data model:**
- Agent roles and types: Business concepts for grouping permissions and defining agent capabilities.
- Identity-role assignment system: Explicit, many-to-many relationship between agent identities and roles, managed through the UI.
- Session tracking entities: Track agent activity, status, and results.
- Model configurations: Store provider details and enabled models for agent use.
- Execution log entries: Persist system instructions and user prompts for every agent run.

## 2. New Capabilities

**New Capabilities:**
- Users can define and manage agent roles, assign permissions for SOPs, Skills, and tools, and manage agent identities and their assignments through the UI.
- The identity-role assignment system allows explicit, many-to-many relationships, with bidirectional management (assign identities to roles and roles to identities).
- Agent identity authentication and token management are handled through the UI, including refresh and re-authentication flows.
- When a role is granted access to an SOP, all related Skills and tools are automatically included in the role's permissions, and this is visible to the user.
- The UI provides a real-time preview of allowed actions for each role.
- Agent type configuration supports selection of identity, role, system instruction, input/output options, and model selection from managed configurations.
- Platform admins can manage model providers, credentials, and enabled models, with secure storage and easy updates.
- Both direct LLM provider APIs and proxy solutions are supported for model backends.
- Admins can view and select available models for agent types from a unified list.
- Agent identity creation uses a secure sign-in flow, with credentials managed separately from human users.
- The system automatically manages agent authentication tokens for runtime operations.
- The platform initializes agent identity management in parallel with user management for consistency.
- Agents can be launched as asynchronous sessions, with input collection and result tracking for both task and conversational agents.
- The agent gateway provides secure, auditable execution and result delivery, including real-time updates for conversational agents.
- All agent actions and results are fully auditable and observable in the management interface.
- The agent instance dashboard allows users to view, filter, and monitor all agent instances and their statuses.
- Users can drill into agent instances to see input, output, and conversation history.
- Execution logs capture and display the full system instruction and user prompt for every agent run.
- The agent runtime uses a modern agent framework to support skill-based execution and advanced workflow orchestration.

## 3. Modified Capabilities


**Modified Capabilities:**
- Permission system now uses a unified, user-friendly format for referencing tools and actions.
- Role management includes clear permission logic and preview, with explicit identity-role assignment managed through the UI.
- Agent management supports agent type definition, identity configuration (including secure sign-in for agent users), model selection from managed configurations, and session-based execution using a modern agent framework.
- Agent runtime validates that only identities assigned to a role can use that role, ensuring secure and compliant execution.
- Agent identity management includes role assignment and token management, with refresh and re-authentication available from the UI.
- Communication hub acts as a secure gateway, managing agent instance lifecycle, result routing, and validating identity and role authorization.
- The system dynamically filters available tools based on agent role, exposing only permitted actions.
- Session system supports agent session tracking and asynchronous result updates, with full visibility for users.
- Model configuration is managed centrally, and all agent types reference managed model configurations.
- Agent instance dashboard provides status filtering and access to detailed instance information.
- Execution logging includes the full system instruction and user prompt for every agent run, visible in the UI and available for audit.

---
**Architectural Correction Note:**
This update replaces the previous (incorrect) approach of constraining agent roles by type-based identity constraints. The new approach uses explicit, many-to-many identity-role assignments, with bidirectional UI for managing these relationships. Token refresh and re-authentication flows are now included for expired agent identity tokens.

## 4. Removed Capabilities

- Use of previous agent runtime frameworks (such as LangGraph) is discontinued in favor of a modern agent framework (LangChain) for improved skill-based execution and workflow support.

## 5. Spec Update Instructions

**Spec Update Instructions:**
- Update product spec to include agent runtime (powered by a modern agent framework), gateway, permission system, model configuration, agent instance dashboard, and enhanced execution logging (system instruction and user prompt).
- Update UX spec to cover new agent role management, agent type configuration screens, model configuration management, agent instance dashboard, and agent instance detail view (showing system instruction and user prompt).
- Update architecture docs to reflect agent gateway, communication hub, session system changes (modern agent framework integration), model configuration backend, and execution logging.
- Update data model to include agent roles, agent types, session tracking entities, model configurations, and execution log entries (system instruction, user prompt).
- Update QA/test plan to cover new and modified user flows, permission logic, auditability requirements, model configuration management, agent instance dashboard, and execution log visibility.
- Update identity provider documentation to include agent realm initialization, secure agent user sign-in, and token management requirements.
