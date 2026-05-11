
# Agent Plan Mode (Unified AI Agent Navigation)

## 1. Epic Overview

Agent Plan Mode provides a clear, actionable plan for each agent type, now accessible directly from the unified "AI Agent" menu. When configuring or reviewing agent types, users can open the Agent Type Details dialog, which includes a dedicated "Plan Preview" tab. This tab displays the LLM-generated implementation plan and a visual topology diagram, giving users confidence in agent setup, enabling better preview and validation before execution, and reducing errors in agent operation. The saved plan becomes part of the agent's execution context—during runtime, the agent follows the pre-approved plan to ensure compliant, predictable behavior. This dialog-based approach streamlines access to plan details and supports the new navigation structure.

## 2. Business Goals

- Increase successful agent deployments by 30% through improved plan transparency and validation
- Reduce agent misconfiguration support tickets by 40% within three months of launch
- Achieve 90% user satisfaction with the agent planning and preview experience (measured via in-app survey)
- Decrease average agent setup time by 25% for new users
- Ensure 100% of new Agent Types have an auto-generated, reviewable plan before execution

## 3. Users & Personas

- **AI Solution Architects**: Need to ensure agents are configured correctly and follow organizational SOPs
- **Business Analysts**: Want to understand and validate agent workflows before launch
- **Compliance Officers**: Require visibility into agent logic, SOPs, and tool usage for audit and approval
- **Developers/Integrators**: Need to preview agent plans to ensure correct integration with other systems

## 4. User Stories

- As an AI Solution Architect, I want to see a step-by-step plan for each agent, so that I can validate its workflow before saving or launching.
- As a Business Analyst, I want to preview the agent's SOPs, skills, and tools in a visual diagram, so that I can understand how the agent will operate.
- As a Compliance Officer, I want to review the agent's plan and associated SOPs/skills, so that I can approve agents for production use.
- As a Developer, I want to ensure the agent's plan aligns with integration requirements, so that downstream systems are not impacted by misconfiguration.

## 5. Acceptance Criteria

- When a user saves an Agent Type, the system automatically invokes an LLM to generate a clear, step-by-step implementation plan based on the agent's instruction, role SOPs, and skills.
- The LLM-generated plan is persisted with the agent type and displayed in a human-readable format, outlining each action the agent will take.
- A topology diagram visually shows the Agent Role, SOPs, Skills, and Tools that will be used, with clear relationships.
- Users can preview the full plan and diagram in the "Plan Preview" tab of the Agent Type Details dialog before finalizing the agent save.
- The saved plan is loaded into the agent's execution context during runtime, guiding the agent to follow the pre-approved workflow.
- The plan and diagram update automatically if the agent's configuration, role, SOPs, or skills change (triggers re-generation on save).
- All UI text is internationalized via i18next.
- The feature is accessible and usable on both desktop and tablet devices.
- Error handling: If plan generation fails, users receive a clear, actionable error message and the agent save is not blocked.
- No direct database access occurs from the frontend; all data flows through the backend API.

## 6. Out of Scope

- Editing or customizing the generated plan steps directly in the UI (plan is regenerated on config changes, not manually edited)
- Manual override of SOP/Skill/Tool selection within the plan preview
- Real-time plan adjustment during agent execution (the saved plan guides execution but doesn't adapt dynamically)
- Support for legacy agent types not using the new configuration model
- Exporting plans to external formats (e.g., PDF, CSV)
- Plan versioning or history (only the current plan is stored and used)

## 7. Dependencies & Constraints

- Relies on accurate mapping between Agent Roles, SOPs, Skills, and Tools in the master data
- Requires up-to-date SOP and Skill definitions for meaningful plan generation
- Requires access to an LLM (configured model in the platform) for plan generation
- LLM response time impacts user experience during agent save (plan generation must be reasonably fast)
- Must integrate with existing i18next localization framework
- Subject to current frontend/backend API contract and strong typing conventions
- Agent execution runtime must support loading and following the saved plan
- Plan must be stored in a format that's both human-readable (for preview) and machine-parseable (for execution guidance)
