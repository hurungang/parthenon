# Agent A2A Communication and Slug Enforcement

## Overview
This feature strengthens cross-agent collaboration by enabling reliable agent-to-agent communication through the Communication Hub while enforcing slug-based naming standards for routing-critical entities. It reduces failed handoffs, improves workflow continuity, and lowers naming-related operational risk.

## Who Uses It
- Platform Administrators: Define roles, agent scope, and governance boundaries
- SOP Authors and AI Operations Engineers: Design delegated multi-agent workflows
- Runtime Operators: Monitor dynamic receiver behavior and session outcomes
- Compliance Stakeholders: Validate controlled delegation and auditable interactions

## What It Does
- Enables agent-to-agent requests using agent type slug as the target identifier
- Automatically provisions a dynamic receiver instance when a target is unavailable
- Keeps requester and receiver in the same session until requester-driven completion
- Derives A2A target permissions from SOP delegation step definitions
- Shows allowed target agent type slugs during role editing
- Enforces slug-only values for agent type names, agent names, and MCP server names
- Includes agent-delegation visibility in plan list and topology preview surfaces

## Key Concepts
- **A2A Invocation**: Agent-to-agent collaboration routed through the Communication Hub
- **Dynamic Receiver**: On-demand target agent instance created to complete a delegation flow
- **Session Continuity**: Shared requester/receiver session maintained until explicit disconnect
- **Step-Derived Permissions**: Delegation rights derived from SOP step definitions
- **Slug Enforcement**: Stable, integration-safe naming for routing and identity surfaces

## Acceptance Criteria
- A2A requests can target agents by agent type slug through the Communication Hub
- If no active target exists, a dynamic receiver instance is created and connected to the active session
- Requester and receiver can exchange messages in the same session until requester completion
- Dynamic receiver instance is removed after completion and disconnect
- Role editing surfaces show allowed target agent type slugs before save
- Plan preview includes agent-delegation steps in both list and topology views
- Non-slug values are rejected for agent type names, agent names, and MCP server names in create and update flows
