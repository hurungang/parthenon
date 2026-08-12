# SOPs

## Overview
SOPs represent business workflows composed of orchestrated steps and delegated tasks. Guardrail policies ensure delegation remains bounded and free of recursive loops so SOP execution is predictable, controllable, and suitable for enterprise operations.

## Business Goals
- Enable repeatable, governed business process automation across agent workflows
- Enforce bounded delegation behavior to prevent runaway agent execution chains
- Provide clear visibility into SOP outcomes for governance and incident triage
- Support a Default SOP fallback for agents without explicitly assigned SOPs

## User Stories
- As an **enterprise administrator**, I want to define SOP workflows that orchestrate multiple agent steps so that complex business processes can be automated reliably.
- As an **AI operations lead**, I want to see policy-enforced stop outcomes for SOP executions so that I can distinguish governance stops from functional failures.
- As a **business process owner**, I want SOP delegation to detect and block cyclic delegation chains so that execution never enters an infinite loop.
- As an **agent designer**, I want to bind specific SOPs to agent types so that each agent type has a curated set of approved workflows.

## What It Does
- Supports multi-step workflow orchestration for repeatable business processes
- Supports delegated execution across agents while enforcing bounded delegation behavior
- Detects and blocks direct and indirect cyclic delegation chains
- Produces clear policy-stop outcomes for governance and incident triage
- Supports a Default SOP fallback policy for agent execution when no explicit SOP is referenced
- Applies Default SOP behavior consistently across all supported agent input types
- Agent Types bind SOPs using an ordered-list pattern, allowing agent designers to curate which SOPs an agent type uses

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
