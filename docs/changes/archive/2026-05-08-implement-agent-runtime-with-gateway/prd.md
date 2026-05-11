# Epic Overview

The Agent Runtime with Gateway introduces a unified system for managing, executing, and governing AI agents within the Parthenon platform. This change enables organizations to define agent types, manage agent roles and permissions, configure model access, and operate agents through a secure, observable gateway. Agent identities are managed using the same identity provider as human users, but within a separate, configurable realm (e.g., `ai_agents`). Agent identity creation leverages an OAuth-based sign-in flow, allowing administrators to sign in to agent user accounts in the agent realm and securely store tokens for runtime use. The solution addresses the need for scalable, auditable, and policy-driven agent orchestration, supporting both human and automated workflows while ensuring compliance and operational transparency. The agent runtime is powered by the LangChain deep agent framework, enabling advanced skill-based execution and improved support for SOPs and Skills. Execution logs now capture the full system instruction and user prompt for every agent run, providing complete visibility and traceability in the UI.

# Business Goals

- Enable secure, role-based management of agent permissions for SOPs and Skills
- Allow organizations to define, configure, and launch agent types with flexible identity, model, and input/output options
- Support agent identity management via OAuth sign-in to a dedicated agent realm, with secure token storage and refresh
- Provide a centralized gateway for agent execution, session tracking, and asynchronous result delivery
- Ensure all agent actions are auditable, observable, and compliant with enterprise requirements
- Improve operational efficiency by automating complex workflows through agent-driven SOPs and Skills
- Allow platform admins to manage model configurations and select models per agent type
- Provide visibility into agent instances, their statuses, and detailed execution history
- Ensure execution logs include the full system instruction and user prompt for every agent run, and that these are visible in the UI
- Leverage the LangChain deep agent framework to support skill-based agent execution and advanced SOP/Skill orchestration

# Users & Personas

- **Platform Administrators**: Need to configure agent types, roles, permissions, and model access to align with organizational policies; manage agent identities using OAuth sign-in to a dedicated realm; and manage model configurations and credentials
- **Business Users**: Want to trigger agents to automate tasks, review results, and interact with agents as needed; view and filter agent instances and drill into execution details
- **Developers/Integrators**: Require a management interface and gateway to integrate agents into broader workflows
- **Compliance & Audit Teams**: Need visibility into agent actions, permissions, session histories, and model usage

# User Stories



As a platform admin, I want to define agent roles and assign SOP/Skill permissions, so that agents operate only within approved boundaries and organizational policies.
As a platform admin, I want to explicitly assign agent identities to roles, so that I can control which specific identities are allowed to perform certain actions.
As a platform admin, I want to assign identities to a role from the role management UI, so that I can easily manage which agents belong to each role.
As a platform admin, I want to assign roles to an identity from the identity management UI, so that I can update permissions for each agent identity as needed.
As a platform admin, I want to refresh an expired agent identity token if the refresh token is still valid, so that agent access can be restored without requiring a new sign-in.
As a platform admin, I want to re-authenticate an agent identity when tokens are expired, so that I can quickly restore agent access and minimize downtime.
As a platform admin, I want agent identity authentication to use single sign-on, so that agent access is secure and consistent with organizational standards.
As a platform admin, I want the system to show only the tools and actions permitted for each agent's role, so that agents cannot access unauthorized capabilities.
As a platform admin, I want to create agent identities by signing in to agent user accounts in a dedicated agent realm, so that agent credentials are securely managed and separated from human users.
As a platform admin, I want the system to store and refresh agent authentication tokens automatically, so that agents can operate without manual credential management.
As a platform admin, I want to configure model providers and select which models are available, so that model access is controlled and only approved models are used by agents.
As a platform admin, I want to view and update the list of available models for each provider, so that I can keep the platform in sync with provider offerings.
As a platform admin, I want to choose a model for an agent type from all enabled models, so that agent types are flexible and not tied to a single provider.
As a business user, I want to launch an agent and provide input, so that the agent can execute a workflow and return results to me asynchronously.
As a platform admin, I want to preview which tools a role can access, so that I can validate permissions before assigning them.
As a developer, I want to integrate with the agent gateway, so that I can trigger agent sessions and receive results in my applications.
As an auditor, I want to review agent session histories and permissions, so that I can ensure compliance and traceability for all agent actions.
As a platform admin or user, I want to view a dashboard of agent instances, filter by status and time, so that I can monitor agent activity and performance.
As a user, I want to drill into an agent instance to see its input, output, and full conversation history, so that I can understand and audit agent behavior.
As a platform admin or auditor, I want to see the full system instruction and user prompt for every agent execution in the logs and UI, so that I have complete traceability of agent actions.
As a platform admin, I want the agent runtime to use a modern agent framework, so that skill-based execution and advanced workflow support are available.


# Acceptance Criteria

* Users can create, edit, and delete agent roles, and assign SOP and Skill permissions using a clear, unified format.
* Identity-role assignments are managed through the UI, allowing explicit control over which agent identities have which roles.
* When a role is granted access to an SOP, all related Skills and tools are automatically included in the role's permissions, and this is visible to the user.
* The UI provides a real-time preview of which tools and actions are available to each role, based on selected SOPs and Skills.
* Users can define agent types, including selecting an agent identity, assigning a role, entering system instructions, and configuring input/output options, all through guided forms.
* The system ensures that only agent identities assigned to a role can use that role for agent execution, and provides clear feedback if not.
* The identity management interface shows the status of each agent identity (valid, expired, expiring soon) and allows users to refresh or re-authenticate as needed.
* Agent authentication uses single sign-on, and the system automatically manages token storage and refresh, so agents remain operational without manual intervention.
* Platform admins can create, edit, and delete model configurations, select which models are enabled, and view available models for each provider, all from a central interface.
* Changes to enabled models are immediately reflected in the agent type configuration screens, so users always see up-to-date options.
* Users can launch agents, provide required input, and track session status asynchronously, with clear feedback and error messages.
* For conversational agents, the UI provides an interactive chat interface for back-and-forth communication.
* All agent actions, session statuses, and results are visible and auditable in the management interface, supporting compliance and traceability.
* The agent instance dashboard shows all agent instances, allows filtering by status and time, and displays key information for monitoring.
* Users can drill into any agent instance to view its full execution history, including input, output, and conversation details.
* Error handling and permission enforcement are consistent and user-friendly across all dialogs and workflows.
* Out-of-scope actions, such as direct database access or bypassing the gateway, are not possible through the UI.
* Execution logs for every agent run include the full system instruction and user prompt, and these are visible in the UI for each agent instance.
* The agent runtime uses a modern agent framework to support skill-based execution and advanced workflow orchestration.

# Out of Scope

- Direct database access or bypassing the agent gateway for agent execution
- Custom agent code or plugin upload (only configuration of agent types, not arbitrary code)
- Non-OIDC identity providers or unsupported authentication flows
- Use of agent identities as OIDC clients (agents are users in a dedicated realm, not clients)
- UI/UX design details (covered in separate UX documentation)
- Low-level technical implementation details, APIs, or schema definitions
- Use of LangGraph for agent runtime (superseded by LangChain deep agent framework)

# Dependencies & Constraints
---
**Architectural Correction Note:**
This update replaces the previous (incorrect) approach of constraining agent roles by allowed identity types. The new approach uses explicit, many-to-many identity-role assignments, with bidirectional UI for managing these relationships. Token refresh and re-authentication flows are now included for expired agent identity tokens.

- Requires OIDC-compliant identity provider (Keycloak, Azure EntraID)
- Agent identities must be managed in a separate, configurable realm (e.g., `ai_agents`) within the identity provider
- Relies on existing MCP tool and Skill registration mechanisms
- Asynchronous session system must be available for agent execution and result tracking
- System must securely store and refresh agent OAuth tokens for runtime use
- Bootstrap process must initialize both user and agent realms in the identity provider
- All changes must comply with Parthenon’s security, audit, and observability conventions
- Integration with OpenTelemetry for traceability and monitoring is mandatory
- Agent runtime must use LangChain deep agent framework (not LangGraph)
- Execution logs must capture and persist the full system instruction and user prompt for every agent run
