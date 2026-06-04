# SOPs

## Overview
SOPs represent business workflows composed of orchestrated steps and delegated tasks. Guardrail policies ensure delegation remains bounded and free of recursive loops so SOP execution is predictable, controllable, and suitable for enterprise operations.

## Who Uses It
- Enterprise Administrators: Define and govern SOP workflows
- AI Operations Leads: Monitor SOP outcomes and policy-enforced stops
- Business Process Owners: Depend on reliable automated process execution

## What It Does
- Supports multi-step workflow orchestration for repeatable business processes
- Supports delegated execution across agents while enforcing bounded delegation behavior
- Detects and blocks direct and indirect cyclic delegation chains
- Produces clear policy-stop outcomes for governance and incident triage
- Supports a Default SOP fallback policy for agent execution when no explicit SOP is referenced in agent instruction
- Applies Default SOP behavior consistently across all supported agent input types
- Agent Types bind SOPs using the same ordered-list pattern that SOPs use to bind skills, allowing agent designers to curate which SOPs an agent type uses

## Acceptance Criteria
- SOP delegation supports business workflows without unbounded recursion
- Direct and indirect cyclic delegation paths are blocked with clear user-visible outcomes
- Delegation depth and delegated-step boundaries are enforced as part of execution policy
- SOP outcomes remain auditable and distinguish policy enforcement stops from functional failures
- Default SOP terminology is used consistently in governance and authoring contexts
- If an agent instruction explicitly references one or more SOP names, only those named SOPs are used for planning and execution context
- If an agent instruction does not reference any SOP name, the Default SOP is applied as fallback context
- Default SOP assignment and fallback policy are available across all supported agent input types

## Out of Scope
- Technical workflow engine design details
- Low-level execution runtime implementation mechanics

## Dependencies & Constraints
- Depends on Agent Type guardrail policy definitions and governance controls
- Must align with enterprise auditability and operational reliability requirements
- Must preserve established service-boundary expectations
