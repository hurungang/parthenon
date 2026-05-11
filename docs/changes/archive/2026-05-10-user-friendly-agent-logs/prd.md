# User-Friendly Agent Logs — Product Requirements Document

## Epic Overview

Current agent execution logs in the Parthenon platform are overly technical, making it difficult for non-technical users to understand what happened during an agent run. This change aims to transform agent session logs into clear, user-friendly summaries that highlight key information (identity, role, SOP/skills, plan, model, and results) and present execution steps in a simple, collapsible format. The goal is to improve transparency, trust, and usability for all users, while still allowing access to raw technical logs for advanced troubleshooting.

## Business Goals
- Increase user comprehension of agent execution outcomes by 80% (measured via user feedback)
- Reduce support requests related to log interpretation by 50%
- Enable business users to self-serve basic troubleshooting without technical assistance
- Improve auditability and traceability of agent actions for compliance

## Users & Personas
- Business users: Need to understand agent actions and results without technical jargon
- Compliance/audit staff: Require clear, traceable records of agent activity
- Support staff: Need to quickly identify issues without deep technical analysis
- Technical users: Require access to raw logs for advanced troubleshooting

## User Stories
- As a business user, I want to see a simple summary of what the agent did, so that I can understand the outcome without technical details
- As a compliance officer, I want to verify which identity and role were used in each agent session, so that I can ensure proper access controls
- As a support staff member, I want to quickly identify why an agent run failed, so that I can assist users efficiently
- As a technical user, I want to toggle to raw logs, so that I can investigate complex issues when needed

## Acceptance Criteria
- Agent session logs display high-level information: identity, role, SOP/skills, plan, model, and result summary
- All LLM/model iterations are grouped into a collapsible section labeled "Agent Working Steps" (collapsed by default)
- Each major task/step is shown as a simple log message with details folded by default; clicking expands to show full details (e.g., implementation plan, tool calls)
- A "Raw Log Toggle" is available, allowing users to switch to and copy raw technical logs
- Log UI is accessible and usable for non-technical users (clear language, no jargon)
- All acceptance criteria validated via user testing with business and compliance personas

## Out of Scope
- Changes to backend log capture or storage format
- New log export formats (CSV, PDF, etc.)
- Changes to agent execution logic or error handling

## Dependencies & Constraints
- Requires updates to frontend log display components (React + MUI)
- Must preserve access to full raw logs for technical users
- No changes to backend log structure or API responses
- Must comply with existing audit and traceability requirements