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
- Skill creation is also available inline from the Agent Management Panel, which reuses the same create/edit dialogs — with no change to standalone Skill Management behaviour
- A Skill can only invoke the tools bound to it — there is no implicit tool access, so the binding is the skill's actual capability
- The Skills list shows each skill's bound tools (grouped by owning server), and a skill with no bound tools carries an explicit "No tools bound" indicator instead of appearing ready to use
- Adding tool bindings is additive: existing bindings are never silently removed when a skill is updated
- Skills can be created and updated conversationally through the [Control Center Assistant](control-center-assistant.md), which discovers a server's available tools and binds the needed ones at creation

## Key Concepts
- **Skill**: A reusable, permission-controlled action wrapping one or more tool calls. Each skill carries an `updated_at` timestamp that changes whenever the skill definition is modified.
- **Workflow Authoring**: Defining the business workflow text that guides how a Skill should be executed
- **AI-Assisted Drafting**: Generating an initial workflow draft that authors can edit before publication
- **Workflow Preview**: Reviewing the final formatted content that will be loaded at execution time
- **Skill Assignment**: Granting access to Skills for users, agents, or roles
- **MCP Tool Wrapping**: Encapsulating tool calls within Skills for governance. Binding is exclusive: a skill can only invoke the tools bound to it, and a skill with zero bindings is inert
- **Tool Binding Visibility**: Bound tools are shown as entries grouped by owning server (display name, owning server, canonical name); binding a tool the user cannot browse (e.g. a permission-gated integration tool already referenced by the skill) keeps it visible as a read-only pinned entry so a save never silently drops it
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
- Each skill displays its bound tools in the Skills list, or an explicit "No tools bound" indicator
- A skill with no bound tools cannot invoke anything and is flagged rather than presented as ready to use
- Updating a skill adds bindings without silently removing existing ones
- A bound tool the user cannot browse stays visible and pre-selected as read-only, so saving never drops it
- Skills can be created and updated conversationally through the Control Center Assistant, subject to the same permission enforcement

## Out of Scope
- SOP composition and sequencing (covered by SOP Management)
- MCP server registration and tool sync (covered by MCP Hub)
- Decision model vendor configuration and per-decision-tool model selection (covered by [Decision Model Providers](decision-model-providers.md))
- Low-level execution runtime implementation details

## Multi-Tenancy Note

When multi-tenancy is enabled (see [Multi-Tenancy](multi-tenancy.md) and [Strict Tenant Isolation](strict-tenant-isolation.md)), skills, skill bindings, and seeding are tenant-scoped: skills are tenant-owned, skill permissions are grantable only within the owning tenant, and seeded skills are planted into a target tenant (the root tenant for platform defaults) rather than a global slot. With multi-tenancy disabled (the default), behavior is unchanged — the deployment operates as the root tenant's workspace.
