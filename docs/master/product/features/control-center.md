# Control Center

## Overview
Control Center is the governance center for policy-driven operation of Parthenon. It provides administrators with a consistent place to manage agent policy controls, including per-Agent-Type guardrail profiles that keep execution behavior predictable, auditable, and aligned with enterprise risk and cost expectations.

## Who Uses It
- Platform Administrators: Define and maintain governance policies for agent execution behavior
- AI Operations Leads: Review policy outcomes and tune limits for reliability and predictable operations
- Security and Compliance Owners: Verify that policy boundaries are enforced and auditable

## What It Does
- Presents a distinct guardrail profile for every Agent Type
- Allows authorized administrators to edit and save guardrail profiles by Agent Type
- Governs execution boundaries, including iteration ceilings, delegation boundaries, and timeout limits
- Governs token-budget policy behavior for supported non-conversational and automated runs
- Presents token-budget values in k-token units, with 1000k as the default presentation value
- Keeps the guardrail editor compact by default for efficient policy administration
- Reflects saved guardrail values in policy views used for governance and oversight

## Key Concepts
- **Per-Agent-Type Guardrail Profile**: A policy profile tied to one Agent Type for consistent execution governance
- **Execution Boundaries**: Policy limits that bound run behavior to approved operational ranges
- **Delegation Boundaries**: Policy limits that bound delegation depth and delegated-step volume
- **Conversational Policy Behavior**: Continuous token usage visibility while preserving conversation continuity unless other guardrails require a stop
- **Policy Outcome Transparency**: Clear representation of guardrail outcomes for triage and governance reporting

## Acceptance Criteria
- A distinct guardrail profile is visible for each Agent Type
- Authorized administrators can edit and save each Agent Type guardrail profile
- Saved guardrail values are reflected in subsequent policy views
- Token-budget values are displayed in k-token units with 1000k as the default presentation value
- Guardrail editing remains compact by default and supports efficient policy review across many Agent Types
- After closing create/edit/delete or guardrail dialogs, parent tables refresh automatically to show updated data without manual page reload
- Governance views clearly distinguish guardrail policy outcomes from functional execution failures

## Out of Scope
- Technical implementation details, architecture internals, or service-level configuration mechanics
- Provider-specific model tuning and optimization strategy
- Changes to non-governance UI areas unrelated to Control Center policy management

## Dependencies & Constraints
- Requires role-based authorization so only approved administrators can manage guardrail profiles
- Depends on policy outcome visibility from execution and session monitoring views
- Must preserve service-segregation expectations for execution responsibilities and governance responsibilities
- Must remain compatible with existing enterprise audit and compliance standards
