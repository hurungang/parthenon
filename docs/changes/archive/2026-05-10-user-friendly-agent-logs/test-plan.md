# User-Friendly Agent Logs — Test Plan

## Test Strategy

This is a **frontend-only** change. No backend, database, or API contract changes are involved. The test strategy focuses on two layers:

- **Unit tests (Vitest)** — Validate the `LogPresenter` data transformation service and the individual presentational components in isolation. These tests are fast, deterministic, and cover all parsing/classification logic.
- **E2E tests (Playwright)** — Validate the integrated user flows on `AgentJobPage` end-to-end, including interaction sequences (expand/collapse, toggle raw mode, copy to clipboard) and visual correctness.

No backend integration tests are required. All existing backend API contracts are unchanged and are already covered by existing backend test suites.

---

## Coverage Areas

### 1. `LogPresenter` Service (Unit)

The most critical test target. All data classification and transformation logic lives here — components are intentionally logic-free. Bugs here affect every downstream component.

- Parsing identity, role, model, SOPs/skills from `system_instruction`
- Classifying entries by `event_type` into `WorkingStep` items (`llm_call`, `tool_call`, others)
- Deriving overall result status from the final entry
- Building the raw log string from timestamped entries
- Handling missing or malformed fields gracefully

### 2. `LogSummaryPanel` Component (Unit)

Verifies the summary card renders the correct fields from a `LogSummary` prop.

- Identity, role, model displayed
- SOPs/skills rendered as chips
- Plan progress displayed
- Result status badge present with correct visual state (success, failure, running)

### 3. `WorkingStepsPanel` Component (Unit)

Verifies collapsible behaviour and step rendering.

- "Agent Working Steps" section is collapsed by default
- Expanding the section reveals LLM iteration and tool call steps
- Expanding an individual step reveals its detail block
- Collapsing the section hides steps again
- Steps outside the collapsible section are always visible (flat rows)

### 4. `RawLogToggle` Component (Unit)

Verifies the toggle and clipboard button behave correctly as a controlled component.

- Toggle switch reflects the `checked` prop
- `onChange` callback fires on toggle interaction
- Copy button is only visible when `rawMode` is active
- Copy button triggers the clipboard write with `rawLogText`

### 5. `LogViewer` Component (Unit/Integration)

Verifies the container routes data correctly and manages `rawMode` state.

- Renders `LogSummaryPanel` and `WorkingStepsPanel` when `rawMode` is false
- Renders the raw log block when `rawMode` is true
- `RawLogToggle` is always present in the header
- Passes the correct props from `LogPresenter` output to child components

### 6. `AgentJobPage` Integration (E2E)

Verifies that the page-level integration works correctly with real component trees and API mocks.

- `LogViewer` renders in place of the old raw execution log section
- "View Execution Logs" button/dialog no longer appears on the page
- Log data loads and displays after session completes
- All interaction flows work end-to-end

---

## Critical Scenarios

### LogPresenter Transformation

**WHEN** a valid `ExecutionLogRead` with identity, role, model, and SOP/skill references in `system_instruction` is provided  
**THEN** `LogSummary` contains the correct identity, role, model, and an ordered list of SOPs/skills

**WHEN** `ExecutionLogEntry[]` contains a mix of `llm_call` and `tool_call` event types  
**THEN** `WorkingStep[]` classifies each entry into the correct type with appropriate icon and message

**WHEN** the final log entry has a success indicator  
**THEN** `LogSummary.resultStatus` is `"success"`

**WHEN** the final log entry has an error or failure indicator  
**THEN** `LogSummary.resultStatus` is `"failure"`

**WHEN** `ExecutionLogEntry[]` is empty  
**THEN** `WorkingStep[]` is an empty array and result status defaults to a neutral/unknown state

**WHEN** `system_instruction` is missing or empty  
**THEN** all summary fields default to empty/unknown without throwing an exception

**WHEN** an entry has `data` containing a structured tool input/output payload  
**THEN** the corresponding `WorkingStep` includes a `detail` payload for the expandable block

**WHEN** all entries are serialised into the raw log string  
**THEN** each line includes the entry's timestamp and message in the correct format

### LogSummaryPanel Display

**WHEN** `LogSummary` contains multiple SOPs/skills  
**THEN** each is rendered as a separate MUI Chip element

**WHEN** `resultStatus` is `"success"`  
**THEN** the result badge displays the success state (correct colour and label)

**WHEN** `resultStatus` is `"failure"`  
**THEN** the result badge displays the failure state (correct colour and label)

**WHEN** model or role is absent from the summary  
**THEN** the corresponding field renders a placeholder or is omitted without crashing

### WorkingStepsPanel Collapse Behaviour

**WHEN** `WorkingStepsPanel` first renders  
**THEN** the "Agent Working Steps" collapsible section is closed and LLM/tool step rows are not visible

**WHEN** the user clicks the "Agent Working Steps" section header  
**THEN** the collapsible expands and LLM iteration and tool call step rows become visible

**WHEN** the user clicks the section header again  
**THEN** the collapsible collapses and the step rows are hidden again

**WHEN** the user expands one step's detail block  
**THEN** only that step's detail is visible; other steps remain collapsed

**WHEN** top-level flat steps (e.g., "Context Loaded", "Task Completed") are present  
**THEN** they are always visible regardless of the collapsible state

### RawLogToggle Interaction

**WHEN** `rawMode` is false and the user activates the toggle  
**THEN** the `onChange` callback fires and `rawMode` transitions to true

**WHEN** `rawMode` is false  
**THEN** the copy-to-clipboard button is not visible

**WHEN** `rawMode` is true  
**THEN** the copy-to-clipboard button is visible

**WHEN** the user clicks the copy button  
**THEN** the full raw log text is written to the clipboard

### LogViewer Mode Switching (E2E)

**WHEN** `AgentJobPage` loads a completed session  
**THEN** the `LogViewer` renders in friendly mode showing the summary panel and working steps panel

**WHEN** the user toggles to raw mode  
**THEN** the summary panel and working steps panel are replaced by a monospace raw log block

**WHEN** the user toggles back to friendly mode  
**THEN** the summary panel and working steps panel are restored

**WHEN** the user is in raw mode and copies the log  
**THEN** the clipboard contains the full raw log text

### AgentJobPage Regression (E2E)

**WHEN** `AgentJobPage` renders for a completed session  
**THEN** the old "View Execution Logs" button or `SessionExecutionLogsDialog` trigger is absent from the page

**WHEN** `AgentJobPage` renders while a session is still running  
**THEN** the `LogViewer` renders with whatever log data is available (partial display, no crash)

---

## Edge Cases & Risks

### Empty and Partial Data

- **Empty `entries` array**: No working steps, summary still renders. Risk: `LogPresenter` crashes on empty array.
- **Missing `system_instruction`**: Summary fields silently default. Risk: Unguarded property access throws.
- **Single entry (no iterations)**: Only one step row; collapsible contains nothing. Risk: Empty collapsible UI looks broken.

### Very Large Logs

- **Hundreds of entries**: `WorkingStepsPanel` renders many rows. Risk: UI freeze or memory pressure on render.
- **Very long raw log string**: Copy-to-clipboard may exceed browser clipboard size limits.
- **Long `detail` payload per step**: Expandable detail blocks must handle arbitrary-length JSON without overflowing.

### Special Characters and Encoding

- **Special characters in messages or data**: Angle brackets, ampersands, quotes in tool payloads must not break HTML rendering.
- **Unicode in SOP/skill names**: Chips must render correctly with any unicode content.
- **Newlines in raw log**: Must appear as line breaks in the monospace block, not collapsed.

### Log Format Variations

- **Successful run with auto-refreshed OAuth token**: A `token_refresh` event type that doesn't fit `llm_call` or `tool_call` classification. Risk: Entry dropped or misclassified.
- **Run that fails before first LLM call**: `entries` may contain only error entries; no `llm_call` entries. Risk: Collapsible shows as empty with misleading label.
- **Multiple SOPs chained**: System instruction may reference multiple SOPs; all must be parsed and shown as chips.

### Regression Risks

- **`AgentJobPage` state cleanup**: Removal of `showLogs` and `execLogExpanded` state variables must not leave dead references.
- **`SessionExecutionLogsDialog` retained**: Dialog is not deleted; risk of it being accidentally triggered by other paths on the page.
- **`useExecutionLogs` hook reuse**: Hook continues to be used but its output is now passed to `LogViewer`; any breaking change to the hook's return shape will break log display silently.
- **i18n coverage**: Any hardcoded string that bypasses `t()` will fail the i18n convention check and show keys in non-English locales.

### Accessibility

- **Toggle switch**: Must be keyboard-navigable and have an accessible label.
- **Collapsible section**: Must announce expand/collapse state to screen readers via `aria-expanded`.
- **Copy button**: Must have an accessible label; success feedback must not be only visual.

---

## Acceptance Criteria Checklist

Maps each PRD acceptance criterion to its test coverage.

| # | Acceptance Criterion | Test Layer | Test Location |
|---|---|---|---|
| AC-1 | Agent session logs display: identity, role, SOP/skills, plan, model, and result summary | Unit (`LogPresenter`, `LogSummaryPanel`) + E2E | `frontend/src/__tests__/LogPresenter.test.ts`, `frontend/src/__tests__/LogSummaryPanel.test.tsx`, `e2e/tests/agent-logs.spec.ts` |
| AC-2 | All LLM/model iterations grouped in collapsible "Agent Working Steps" section, collapsed by default | Unit (`WorkingStepsPanel`) + E2E | `frontend/src/__tests__/WorkingStepsPanel.test.tsx`, `e2e/tests/agent-logs.spec.ts` |
| AC-3 | Each major task/step shown with details folded; clicking expands full details | Unit (`WorkingStepsPanel`) + E2E | `frontend/src/__tests__/WorkingStepsPanel.test.tsx`, `e2e/tests/agent-logs.spec.ts` |
| AC-4 | "Raw Log Toggle" allows switching to and copying raw technical logs | Unit (`RawLogToggle`, `LogViewer`) + E2E | `frontend/src/__tests__/RawLogToggle.test.tsx`, `frontend/src/__tests__/LogViewer.test.tsx`, `e2e/tests/agent-logs.spec.ts` |
| AC-5 | Log UI is accessible and usable for non-technical users (clear language, no jargon) | E2E (manual verification + automated label checks) | `e2e/tests/agent-logs.spec.ts`, `e2e/tests/accessibility.spec.ts` |

---

## Test File References

All new test files follow the conventions established by the existing test suite in each layer.

### Unit Tests (Vitest)

| File | Covers |
|---|---|
| `frontend/src/__tests__/LogPresenter.test.ts` | All `LogPresenter` transformation logic, classification rules, and edge cases |
| `frontend/src/__tests__/LogSummaryPanel.test.tsx` | Summary card rendering for all `LogSummary` prop states |
| `frontend/src/__tests__/WorkingStepsPanel.test.tsx` | Collapsible behaviour, step rendering, detail expansion |
| `frontend/src/__tests__/RawLogToggle.test.tsx` | Controlled toggle props, copy button visibility, clipboard callback |
| `frontend/src/__tests__/LogViewer.test.tsx` | Mode switching between friendly and raw, prop routing to child panels |

### E2E Tests (Playwright)

| File | Covers |
|---|---|
| `e2e/tests/agent-logs.spec.ts` | Full user flows on `AgentJobPage`: log display, expand/collapse, raw toggle, copy, regression checks |
| `e2e/tests/accessibility.spec.ts` | Keyboard navigation and screen reader label checks for the new log viewer controls (extend existing file) |
