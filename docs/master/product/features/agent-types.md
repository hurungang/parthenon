# Agent Types

## Overview
Agent Types define how organizations standardize agent behavior, governance, and accountability across different business use cases. Each Agent Type carries its own execution guardrail profile so teams can apply predictable limits, reduce runaway execution risk, and maintain cost-aware operations.

## Who Uses It
- Platform Administrators: Configure and govern Agent Type policies
- AI Operations Leads: Monitor policy outcomes and operational reliability
- Business Process Owners: Ensure automation behaves predictably for each use case

## What It Does
- Defines distinct execution policy boundaries per Agent Type
- Applies cycle prevention for delegated execution chains
- Applies bounded execution policy for iteration, delegation, and timeout controls
- Supports token-budget policy behavior for supported non-conversational and automated runs
- Supports clear visibility of guardrail usage and policy outcomes in execution summaries
- Validates SOP/delegation configuration for **recursive delegation risk** at create and update entry points, blocking recursion-prone submissions
- Validates **recursion/dead-loop risk** at run initiation and prevents execution when risk conditions are detected

## Recursion and Dead-Loop Prevention
- Agent Type create and update flows **validate recursive delegation risk** in SOP and delegation configuration
- Recursion-prone configurations are **blocked before submission** with a clear user-visible error
- Run initiation **validates recursion/dead-loop risk** and prevents execution when risk conditions are detected
- Validation outcomes are reflected in execution logs and configuration error messages

## Acceptance Criteria
- Each Agent Type has a distinct guardrail profile
- Delegation cycle prevention applies to direct and indirect recursion paths
- Iteration, delegation boundary, and timeout policies are enforced per Agent Type
- Conversational runs keep current-session token usage visible
- Conversational runs are not hard-stopped solely by token budget thresholds
- Non-conversational and automated runs enforce token budgets when supported, with transparent fallback when unsupported
- **Recursive delegation risk is validated during agent create and update, and invalid submissions are blocked**
- **Recursion/dead-loop risk is validated during run initiation, and execution is prevented when risk conditions are detected**

## Out of Scope
- Technical implementation design or service internals
- Provider-specific model optimization strategy

## Dependencies & Constraints
- Requires consistent policy governance in Control Center
- Depends on clear policy-outcome visibility in execution and monitoring views
- Must align with enterprise segregation and audit requirements
- Recursion validation depends on a stable SOP and delegation step graph; configuration changes that would create cycles must be rejected at create/update and again at run initiation
