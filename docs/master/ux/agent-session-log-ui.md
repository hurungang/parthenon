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

## Conversation Activity (as shipped)

- A conversational turn always shows one activity indicator while it is live — `thinking`,
  `using a tool`, `delegating`, `waiting for a delegated response`, `waiting for your input` — and
  the same indicator becomes the terminal label (`finished`, `failed`, `timed out`) when the turn
  ends. It is never left spinning, and a reload or reconnect restores the persisted state.
- When a turn pauses for human input the indicator switches to `Waiting for your input` in place;
  there is no blank window between the agent's message and the intervention request.
- A paused turn that can no longer be resumed shows one reason-specific terminal card
  (`expired`, pause point lost, stopped unexpectedly) with what happened, what was not written, a
  next step and **Ask again** / **Dismiss** — never a generic timeout message.

## Out of Scope
- Backend log capture or storage changes
- Export formats (CSV, PDF, etc.)
- Changes to agent execution logic

## Constraints
- Must preserve access to full raw logs for technical users
- No changes to backend log structure or API responses
- Must comply with audit and traceability requirements
