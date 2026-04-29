# Skill Management

## Overview
Skill Management allows admins to define, organize, and control access to Skills—reusable actions that wrap one or more MCP tool calls. This feature ensures that only authorized users and agents can execute specific business functions, supporting automation and compliance.

## Who Uses It
- Enterprise Admins: Define and assign Skills, manage permissions
- AI Agents: Execute Skills as part of workflows
- Business Users: Trigger Skills through the Web UI

## What It Does
- Enables creation of Skills that encapsulate MCP tool calls
- Organizes Skills for assignment to roles and agents
- Controls which users and agents can access each Skill
- Supports permission assignment and auditability for all Skills

## Key Concepts
- **Skill**: A reusable, permission-controlled action wrapping one or more tool calls
- **Skill Assignment**: Granting access to Skills for users, agents, or roles
- **MCP Tool Wrapping**: Encapsulating tool calls within Skills for governance
- **Permission Control**: Restricting Skill execution to authorized entities

## Acceptance Criteria
- Admins can define new Skills and edit existing ones
- Skills can be assigned to roles, users, or agents
- Only authorized entities can execute each Skill
- All Skill usage is logged and auditable
- Skills are discoverable and manageable from the UI
