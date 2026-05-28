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

## Acceptance Criteria
- Each Agent Type has a distinct guardrail profile
- Delegation cycle prevention applies to direct and indirect recursion paths
- Iteration, delegation boundary, and timeout policies are enforced per Agent Type
- Conversational runs keep current-session token usage visible
- Conversational runs are not hard-stopped solely by token budget thresholds
- Non-conversational and automated runs enforce token budgets when supported, with transparent fallback when unsupported

## Out of Scope
- Technical implementation design or service internals
- Provider-specific model optimization strategy

## Dependencies & Constraints
- Requires consistent policy governance in Control Center
- Depends on clear policy-outcome visibility in execution and monitoring views
- Must align with enterprise segregation and audit requirements
