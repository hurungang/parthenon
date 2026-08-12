# Skill Management

## Overview
Skill Management allows administrators to define, organize, and govern Skills as reusable business capabilities. The feature now supports AI-assisted workflow authoring so teams can generate a first draft from selected tools and a short business description, then review and refine the workflow before publishing. This improves authoring speed while preserving governance and auditability.

## Who Uses It
- Enterprise Admins: Define and assign Skills, manage permissions
- AI Workflow Authors: Draft and refine Skill workflows quickly
- System Administrators: Configure the generation model used for workflow drafting
- AI Agents: Execute Skills as part of workflows
- Business Users: Trigger Skills through the Web UI

## What It Does
- Enables creation of Skills with a business-facing workflow definition
- Supports AI-assisted workflow draft generation from selected tools and author-provided descriptions
- Provides preview of the final formatted workflow content before save or publish
- Organizes Skills for assignment to roles and agents
- Controls which users and agents can access each Skill
- Supports permission assignment and auditability for all Skills
- Skills can be bound directly to Agent Types (in addition to SOPs), giving agent designers the flexibility to reference skills at any granularity

## Key Concepts
- **Skill**: A reusable, permission-controlled action wrapping one or more tool calls. Each skill carries an `updated_at` timestamp that changes whenever the skill definition is modified.
- **Workflow Authoring**: Defining the business workflow text that guides how a Skill should be executed
- **AI-Assisted Drafting**: Generating an initial workflow draft that authors can edit before publication
- **Workflow Preview**: Reviewing the final formatted content that will be loaded at execution time
- **Skill Assignment**: Granting access to Skills for users, agents, or roles
- **MCP Tool Wrapping**: Encapsulating tool calls within Skills for governance
- **Permission Control**: Restricting Skill execution to authorized entities
- **Skill Version Tracking**: The `updated_at` timestamp enables external agents to cache skills locally and only re-download those that have changed since their last sync. The `load_skills` system tool supports an optional `since` parameter for incremental sync of only updated skills.

## Acceptance Criteria
- Admins can define new Skills and edit existing ones
- Skill create and edit experiences use workflow terminology consistently
- Authors can generate a workflow draft from selected tools and a short description
- Generated workflow text is editable before save
- Authors can preview the final formatted workflow content before save or publish
- Preview clearly shows which configured generation model produced the draft
- If no generation model is configured, generation and preview show a clear user-facing error and authors can continue manual editing
- Skills can be assigned to roles, users, or agents
- Only authorized entities can execute each Skill
- All Skill usage is logged and auditable
- Skills are discoverable and manageable from the UI
