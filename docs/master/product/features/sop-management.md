# SOP Management

## Overview
SOP Management enables the creation and orchestration of Standard Operating Procedures (SOPs) by composing multiple Skills into sequenced, auditable workflows. It now includes AI-assisted workflow authoring so users can generate a first draft from selected steps and a short business description, then review and refine the final workflow before publish.

## Who Uses It
- Enterprise Admins: Compose and manage SOPs, define workflow logic
- AI Workflow Authors: Draft SOP workflows with faster first-pass quality
- AI Agents: Execute SOPs and delegate steps to other agents
- Compliance Auditors: Review SOP definitions and execution history

## What It Does
- Allows composition of SOPs from multiple Skills with defined sequencing
- Supports AI-assisted workflow draft generation from selected steps and author-provided descriptions
- Provides preview of final formatted SOP workflow content prior to save or publish
- Supports branching and conditional logic within SOPs
- Enables agent-to-agent delegation for collaborative workflows
- Prevents direct and indirect cyclic delegation paths across SOP and agent delegation chains
- Applies delegation depth and delegated-step boundaries as part of bounded execution governance
- Provides auditability and management of all SOPs

## Key Concepts
- **SOP (Standard Operating Procedure)**: A multi-step, sequenced workflow composed of Skills
- **Workflow Authoring**: Defining business workflow content that guides SOP execution
- **AI-Assisted Drafting**: Generating a first workflow draft that users can edit
- **Workflow Preview**: Reviewing the final formatted SOP content before release
- **Step Sequencing**: Defining the order and logic of steps within an SOP
- **Agent Delegation**: Assigning SOP steps to different agents for execution. Delegation-based human intervention gates (via `human_intervene`) now work reliably inside conversational sessions — when a delegated sub-agent requests human input, the intervention is surfaced in the parent conversation UI
- **Delegation Cycle Prevention**: Blocking recursive delegation patterns that would create runaway execution loops
- **Delegation Boundaries**: Governing maximum delegation depth and delegated-step counts for predictable execution
- **SOP Auditability**: Tracking and reviewing SOP definitions and runs

## Acceptance Criteria
- Admins can create, edit, and manage SOPs from the UI
- SOP create and edit experiences use workflow terminology consistently
- Authors can generate SOP workflow drafts from selected steps and a short description
- Generated workflow text is editable before save
- Authors can preview the final formatted SOP workflow content before save or publish
- Preview clearly shows which configured generation model produced the draft
- If no generation model is configured, generation and preview show a clear user-facing error and authors can continue manual editing
- SOPs can sequence multiple Skills and include branching logic
- Agents can delegate SOP steps to other agents
- Cyclic delegation chains, including indirect recursion, are blocked with clear user-visible policy outcomes
- Delegation depth and delegated-step boundaries are enforced as part of execution governance
- All SOP executions are logged and auditable
- SOPs with delegated human intervention steps surface intervention requests in the parent conversation UI when executed conversationally
- Delegation-based intervention gates work reliably at any delegation depth within conversational agent sessions
- SOPs are discoverable and manageable from the UI
