<!--
Agent Session Log UI Specification
This document describes the business requirements for the user-friendly agent session log UI in the Parthenon platform. No implementation or code details are included.
-->

# Agent Session Log UI

## Overview

The agent session log UI presents agent execution logs in a clear, accessible format for all user types. The interface highlights key information (identity, role, SOP/skills, plan, model, and results) and organizes execution steps into collapsible sections. A toggle allows users to switch between user-friendly summaries and raw technical logs.

## Business Requirements
- Display high-level agent session information: identity, role, SOP/skills, plan, model, and result summary
- Group all LLM/model iterations into a collapsible section labeled "Agent Working Steps" (collapsed by default)
- Show each major task/step as a simple log message with details folded by default; clicking expands to show full details (e.g., implementation plan, tool calls)
- Provide a "Raw Log Toggle" to switch between user-friendly and raw technical logs
- Ensure the UI is accessible and usable for non-technical users (clear language, no jargon)
- Validate usability and comprehension through user testing with business and compliance personas

## Out of Scope
- Backend log capture or storage changes
- Export formats (CSV, PDF, etc.)
- Changes to agent execution logic

## Constraints
- Must preserve access to full raw logs for technical users
- No changes to backend log structure or API responses
- Must comply with audit and traceability requirements
