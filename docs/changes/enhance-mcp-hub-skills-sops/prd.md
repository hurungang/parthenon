# Epic Overview

Current MCP Hub, Skills, and SOPs management is too basic for enterprise needs. This epic delivers a robust, business-grade experience for managing MCP servers, skills, and SOPs, enabling organizations to control, audit, and automate AI tool usage with full visibility and compliance. These enhancements unlock the platform’s value for complex, regulated environments. The epic now also ensures that tool schemas and usage descriptions are automatically attached to agent instructions, and that default skills for `save_result` and `send_notification` are created during installation for immediate use.

# Business Goals

- Achieve parity with the master prototype for MCP Hub, Skills, and SOPs management
- Enable secure, auditable management of MCP servers, skills, and SOPs
- Provide clear mapping and visibility between tools, skills, roles, and SOPs
- Support advanced workflow automation through SOP step sequencing and instructions
- Improve operational transparency and compliance for enterprise customers
- Ensure agent instructions always include up-to-date tool schemas and usage descriptions
- Guarantee default skills (`save_result`, `send_notification`) are available after installation

# Users & Personas

- **Platform Administrators**: Configure, monitor, and audit MCP servers, skills, and SOPs
- **AI Engineers / Skill Designers**: Compose, edit, and assign skills and SOPs to roles; benefit from automatic tool schema attachment to agent instructions
- **Business Users / Operators**: Execute SOPs and understand workflows and required skills
- **Compliance Auditors**: View mappings and operational history for compliance
- **Platform Setup Engineers**: Ensure default skills are present and ready for use after installation

# User Stories

- As an admin, I want to manage MCP servers and credentials, so I can securely connect to external tool hubs
- As an engineer, I want to create and assign skills with multiple tool bindings, so I can control access and composition
- As an agent developer, I want to provide execution instructions for each skill, so that AI agents understand how to properly invoke the composed tools
- As a user, I want to see available tools, skills, and role access, so I understand capabilities and permissions
- As a designer, I want to create SOPs with ordered steps and instructions, so I can automate complex workflows
- As an auditor, I want to view mappings between tools, skills, roles, and SOPs, so I can verify compliance
- As an AI engineer, I want tool schemas and usage descriptions to be automatically appended to agent instructions based on tool selection, so that agents always have accurate, up-to-date tool information
- As a platform setup engineer, I want default skills for `save_result` and `send_notification` to be created automatically during installation, so that essential platform actions are always available

# Acceptance Criteria

## MCP Hub
- User can create, view, edit, and delete MCP servers with all required fields
- Created, updated, or deleted MCP servers are immediately visible in the list after saving
- User can manage multiple named sessions per server, each with identity/credential bindings
- Credentials are managed securely and never shown in plaintext
- Tool Repository view shows all tools from all servers, grouped by server
- User can see which skills use each tool (tool-to-skill mapping)
- User can trigger server sync and view sync status/history
- Validation and permission errors are clearly shown to the user

## Skills
- User can create, view, edit, and delete skills with multiple tool bindings
- Created, updated, or deleted skills are immediately visible in the list after saving
- User can assign roles to skills and see which roles have access
- Skills include multi-tool binding, role assignment, and an **instruction field** (agent-facing guidance on how to use the skill's tools)
- Skill editor includes an instruction field for agent-facing execution guidance
- Skill dependency visualization is available
- Tool namespace (server slug prefix) is displayed
- Validation and permission errors are clearly shown to the user
- **When a skill is assigned tools, the agent instruction automatically appends a read-only Tool Section containing the selected tools’ schemas and usage descriptions**
- **The Tool Section in agent instructions is always up-to-date and cannot be manually edited**

## SOPs
- User can create, view, edit, and delete SOPs
- Created, updated, or deleted SOPs are immediately visible in the list after saving
- SOP editor supports ordered step management and instructions
- User can assign roles to SOPs
- Validation and permission errors are clearly shown to the user

## Default Skills
- **After platform installation, default skills for `save_result` and `send_notification` exist and are visible in the skills list**
- **Default skills can be updated by users but are always created on install if missing**

# Out of Scope
- Implementation of new tool types or agent engines
- Changes to core authentication or OIDC flows
- Non-UI automation or backend-only features not visible to users

# Dependencies & Constraints
- Relies on existing OIDC/role infrastructure and permission models
- Requires secure credential storage and audit logging
- Must align with master prototype and data model
- No changes to core agent execution engine in this epic
- Tool schemas and usage descriptions must be sourced from the MCP tool registry
- Default skills must be created as part of the installation/initialization process