# Epic Overview

The Agent Runtime with Gateway introduces a unified system for managing, executing, and governing AI agents within the Parthenon platform. This change enables organizations to define agent types, manage agent roles and permissions, and operate agents through a secure, observable gateway. Agent identities are managed using the same identity provider as human users, but within a separate, configurable realm (e.g., `ai_agents`). Agent identity creation leverages an OAuth-based sign-in flow, allowing administrators to sign in to agent user accounts in the agent realm and securely store tokens for runtime use. The solution addresses the need for scalable, auditable, and policy-driven agent orchestration, supporting both human and automated workflows while ensuring compliance and operational transparency.

# Business Goals

- Enable secure, role-based management of agent permissions for SOPs and Skills
- Allow organizations to define, configure, and launch agent types with flexible identity and input/output options
- Support agent identity management via OAuth sign-in to a dedicated agent realm, with secure token storage and refresh
- Provide a centralized gateway for agent execution, session tracking, and asynchronous result delivery
- Ensure all agent actions are auditable, observable, and compliant with enterprise requirements
- Improve operational efficiency by automating complex workflows through agent-driven SOPs and Skills

# Users & Personas

- **Platform Administrators**: Need to configure agent types, roles, and permissions to align with organizational policies
- **Platform Administrators**: Need to configure agent types, roles, and permissions to align with organizational policies, and manage agent identities using OAuth sign-in to a dedicated realm
- **Business Users**: Want to trigger agents to automate tasks, review results, and interact with agents as needed
- **Developers/Integrators**: Require a management interface and gateway to integrate agents into broader workflows
- **Compliance & Audit Teams**: Need visibility into agent actions, permissions, and session histories

# User Stories

- As a platform admin, I want to define agent roles and assign SOP/Skill permissions, so that agents operate within approved boundaries
- As a platform admin, I want to create agent identities by signing in to agent user accounts in a dedicated agent realm via OAuth, so that agent credentials are securely managed and separated from human users
- As a platform admin, I want the system to store and refresh agent OAuth tokens automatically, so that agents can operate without manual credential management
- As a business user, I want to launch an agent and provide input, so that the agent can execute a workflow and return results asynchronously
- As a platform admin, I want to preview which MCP tools a role can access, so that I can validate permissions before assigning them
- As a developer, I want to integrate with the agent gateway, so that I can trigger agent sessions and receive results programmatically
- As an auditor, I want to review agent session histories and permissions, so that I can ensure compliance and traceability

# Acceptance Criteria

- Users can create, edit, and delete agent roles, assigning SOP and Skill permissions
- When a role is granted access to an SOP, all underlying Skills and required MCP tools are automatically included in the role's permissions
- UI provides a real-time preview of allowed MCP tools for each role based on selected SOPs and Skills
- Users can define agent types with:
  - Identity configuration, including selection of an agent user from a dedicated agent realm via OAuth sign-in flow
  - Single agent role assignment
  - System instruction text
  - Input configuration (no input, typed arguments, or conversation)
  - Output configuration (typed output object or markdown text)
- Admins can create agent identities by signing in to agent user accounts in the agent realm using OAuth; system stores access and refresh tokens securely
- System automatically refreshes agent tokens as needed for agent runtime operations
- Bootstrap process initializes the agent realm in the identity provider, mirroring user realm setup
- Users can launch agents, provide required input, and track session status asynchronously
- For agents with conversation input type, the UI opens a chat interface (similar to VS Code chat sessions) for interactive back-and-forth communication
- Agent requests are routed through the communication hub/gateway, which manages agent instance lifecycle and result delivery
- Agents fetch and use only the SOPs, Skills, and MCP tools permitted by their assigned role
- All agent actions, session statuses, and results are auditable and observable via the management interface
- Error handling and permission enforcement are consistent and user-friendly across all dialogs and workflows
- Out-of-scope actions (e.g., direct database access, bypassing gateway) are not possible

# Out of Scope

- Direct database access or bypassing the agent gateway for agent execution
- Custom agent code or plugin upload (only configuration of agent types, not arbitrary code)
- Non-OIDC identity providers or unsupported authentication flows
- Use of agent identities as OIDC clients (agents are users in a dedicated realm, not clients)
- UI/UX design details (covered in separate UX documentation)
- Low-level technical implementation details, APIs, or schema definitions

# Dependencies & Constraints

- Requires OIDC-compliant identity provider (Keycloak, Azure EntraID)
- Agent identities must be managed in a separate, configurable realm (e.g., `ai_agents`) within the identity provider
- Relies on existing MCP tool and Skill registration mechanisms
- Asynchronous session system must be available for agent execution and result tracking
- System must securely store and refresh agent OAuth tokens for runtime use
- Bootstrap process must initialize both user and agent realms in the identity provider
- All changes must comply with Parthenon’s security, audit, and observability conventions
- Integration with OpenTelemetry for traceability and monitoring is mandatory
