# SOP Management

## Overview
SOP Management enables the creation and orchestration of Standard Operating Procedures (SOPs) by composing multiple Skills into sequenced, auditable workflows. It supports agent-to-agent delegation and branching, allowing complex business processes to be automated and governed.

## Who Uses It
- Enterprise Admins: Compose and manage SOPs, define workflow logic
- AI Agents: Execute SOPs and delegate steps to other agents
- Compliance Auditors: Review SOP definitions and execution history

## What It Does
- Allows composition of SOPs from multiple Skills with defined sequencing
- Supports branching and conditional logic within SOPs
- Enables agent-to-agent delegation for collaborative workflows
- Prevents direct and indirect cyclic delegation paths across SOP and agent delegation chains
- Applies delegation depth and delegated-step boundaries as part of bounded execution governance
- Provides auditability and management of all SOPs

## Key Concepts
- **SOP (Standard Operating Procedure)**: A multi-step, sequenced workflow composed of Skills
- **Step Sequencing**: Defining the order and logic of steps within an SOP
- **Agent Delegation**: Assigning SOP steps to different agents for execution
- **Delegation Cycle Prevention**: Blocking recursive delegation patterns that would create runaway execution loops
- **Delegation Boundaries**: Governing maximum delegation depth and delegated-step counts for predictable execution
- **SOP Auditability**: Tracking and reviewing SOP definitions and runs

## Acceptance Criteria
- Admins can create, edit, and manage SOPs from the UI
- SOPs can sequence multiple Skills and include branching logic
- Agents can delegate SOP steps to other agents
- Cyclic delegation chains, including indirect recursion, are blocked with clear user-visible policy outcomes
- Delegation depth and delegated-step boundaries are enforced as part of execution governance
- All SOP executions are logged and auditable
- SOPs are discoverable and manageable from the UI
