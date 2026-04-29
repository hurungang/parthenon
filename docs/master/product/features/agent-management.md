# Agent Management

## Overview
Agent Management provides the ability to define, configure, and govern AI agent types, their identities, and their operational lifecycles. It ensures that agents operate within assigned permissions, with clear identity and instance controls, supporting both SOP-bound and skillful agent models.

## Who Uses It
- Enterprise Admins: Define agent types, set permissions, and manage agent instances
- AI Agents: Operate under defined identities and permissions
- Compliance Auditors: Review agent definitions and activity

## What It Does
- Supports creation of agent types with OIDC identities and model bindings
- Enforces max-instance limits for each agent type
- Assigns skills and permissions to agent types
- Manages agent instance lifecycle (creation, operation, termination)

## Key Concepts
- **Agent Type**: A defined class of agent with specific identity and capabilities
- **SOP-Agent**: An agent bound to a single SOP for focused workflows
- **Skillful-Agent**: An agent with access to a set of Skills for flexible operation
- **Instance Lifecycle**: The process of creating, running, and terminating agent instances
- **Max-Instance Enforcement**: Limiting the number of concurrent agent instances

## Acceptance Criteria
- Admins can define and configure agent types with identities and permissions
- Max-instance limits are enforced for each agent type
- Agents operate only within their assigned permissions
- Agent instance creation and termination are auditable
- Agent types are discoverable and manageable from the UI
