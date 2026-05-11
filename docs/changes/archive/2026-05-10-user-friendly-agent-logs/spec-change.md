# User-Friendly Agent Logs — Specification Delta

## Affected Spec Areas
- `docs/master/product/agent-session-logs.md`
- `docs/master/ux/agent-session-log-ui.html`
- `docs/master/qa/agent-session-logs.md`

## New Capabilities
- User-friendly agent session log summaries highlighting identity, role, SOP/skills, plan, model, and result
- Collapsible "Agent Working Steps" section grouping all LLM/model iterations
- Collapsible details for each major task/step (e.g., implementation plan, tool calls)
- "Raw Log Toggle" to switch between user-friendly and raw technical logs

## Modified Capabilities
- BEFORE: Agent logs displayed as raw, technical output with minimal grouping or explanation
- AFTER: Agent logs presented as high-level summaries with collapsible details, clear language, and a toggle for raw logs

## Removed Capabilities
- None

## Spec Update Instructions
- Update `docs/master/product/agent-session-logs.md` to describe new user-friendly log summary and collapsible UI requirements
- Update `docs/master/ux/agent-session-log-ui.html` to reflect new log grouping, collapsible sections, and raw log toggle
- Update `docs/master/qa/agent-session-logs.md` to include user comprehension and accessibility acceptance criteria