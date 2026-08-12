# Agent Session Logs — QA Acceptance Criteria

## Overview
This document defines the business-level acceptance criteria for the user-friendly agent session log feature in the Parthenon platform. All criteria are observable and testable from a user perspective.

## Test Strategy

Agent session logs are validated through Vitest component tests that verify log rendering, collapsible section behaviour, and raw log toggle functionality in isolation. E2E Playwright tests validate the full log viewing flow from agent execution through log display. User testing with business and compliance personas validates accessibility and comprehension for non-technical users.

## Critical Scenarios

- **WHEN** an agent session completes and the user opens the execution log view, **THEN** high-level information (identity, role, SOP/skills, plan, model, result summary) is displayed in a human-readable summary panel.
- **WHEN** the user views the execution log, **THEN** all LLM/model iterations are grouped into a collapsible section labeled "Agent Working Steps" that is collapsed by default.
- **WHEN** the user clicks a working step, **THEN** the step expands to show full details including the implementation plan and tool calls used.
- **WHEN** the user toggles the "Raw Log" switch, **THEN** the view switches from the user-friendly summary to the raw technical log text, which is copyable.
- **WHEN** the user toggles back, **THEN** the view returns to the user-friendly summary.
- **WHEN** a non-technical user views the log, **THEN** all content is presented in clear language without technical jargon, and collapsible sections are keyboard-accessible.

## Acceptance Criteria
- Agent session logs display high-level information: identity, role, SOP/skills, plan, model, and result summary
- All LLM/model iterations are grouped into a collapsible section labeled "Agent Working Steps" (collapsed by default)
- Each major task/step is shown as a simple log message with details folded by default; clicking expands to show full details
- A "Raw Log Toggle" is available, allowing users to switch to and copy raw technical logs
- Log UI is accessible and usable for non-technical users (clear language, no jargon)
- All acceptance criteria validated via user testing with business and compliance personas

## Test File References
- Frontend component tests: `frontend/src/__tests__/LogViewer.test.tsx`, `frontend/src/__tests__/LogPresenter.test.tsx`
- E2E tests: `e2e/tests/agent-logs.spec.ts`

## Accessibility & Usability
- Agent session logs display high-level information: identity, role, SOP/skills, plan, model, and result summary
- All LLM/model iterations are grouped into a collapsible section labeled "Agent Working Steps" (collapsed by default)
- Each major task/step is shown as a simple log message with details folded by default; clicking expands to show full details (e.g., implementation plan, tool calls)
- A "Raw Log Toggle" is available, allowing users to switch to and copy raw technical logs
- Log UI is accessible and usable for non-technical users (clear language, no jargon)
- All acceptance criteria validated via user testing with business and compliance personas

## Accessibility & Usability
- All log content is presented in clear, non-technical language
- Collapsible sections are keyboard accessible and screen reader friendly
- Raw log toggle is clearly labeled and easy to use

## Out of Scope
- Backend log capture or storage changes
- Export formats (CSV, PDF, etc.)
- Changes to agent execution logic

## Validation
- User comprehension and accessibility validated through user testing with business and compliance personas
