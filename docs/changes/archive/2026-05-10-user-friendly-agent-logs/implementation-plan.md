# User-Friendly Agent Logs — Implementation Plan

## Overview

This change replaces the raw technical log display in the Agent Job page with a structured, user-friendly Log Viewer. The work is purely frontend — a new `LogPresenter` transformation layer and `LogViewer` component are introduced, then wired into the existing `AgentJobPage`. No backend or API changes are required.

---

## Task Checklist

### Phase 1 — Types & Transformation Layer

- [x] 1.1 — Define `LogPresenter` structured output types
- [x] 1.2 — Implement `LogPresenter` transformation function

### Phase 2 — Log Viewer Component

- [x] 2.1 — Implement `LogSummaryPanel` sub-component
- [x] 2.2 — Implement `WorkingStepsPanel` sub-component (collapsible steps and tool call detail blocks)
- [x] 2.3 — Implement `RawLogToggle` control
- [x] 2.4 — Assemble `LogViewer` root component

### Phase 3 — Integration

- [x] 3.1 — Replace the existing execution log section in `AgentJobPage` with `LogViewer`
- [x] 3.2 — Retire `SessionExecutionLogsDialog` button from `AgentJobPage` (fold its data into Log Viewer)

### Phase 4 — i18n & Polish

- [x] 4.1 — Add all new translation keys to `en.json`
- [x] 4.2 — Verify responsive layout, accessibility, and MUI theme consistency

---

## Phase 1 — Types & Transformation Layer

### 1.1 — Define `LogPresenter` structured output types

Add new TypeScript interfaces to `frontend/src/types/index.ts` to represent the three presentation levels produced by the Log Presenter:

- **`LogSummary`** — identity, role, model, SOPs/skills loaded, plan progress, result status
- **`WorkingStep`** — a single LLM iteration or tool call, with a human-readable message, timestamp, icon type (llm/tool/success/error), and an optional collapsible detail payload (plan text or tool input/output)
- **`StructuredLog`** — container holding a `LogSummary`, an array of `WorkingStep`, and the raw log string

These types are derived entirely from the existing `ExecutionLogRead` (system instruction, user prompt) and `ExecutionLogEntry` (timestamp, event_type, message, data) shapes already in the codebase.

**Done when:** The new interfaces are exported from `frontend/src/types/index.ts` and TypeScript reports no errors.

---

### 1.2 — Implement `LogPresenter` transformation function

Create `frontend/src/services/LogPresenter.ts` containing a pure function `presentLog(executionLog: ExecutionLogRead, entries: ExecutionLogEntry[]): StructuredLog`.

The function must:
- Parse `system_instruction` to extract identity, role, model, SOPs/skills, and plan step count
- Group `entries` by `event_type` into `WorkingStep` items, preserving chronological order
- Derive the result status (success/failure) from the final entry's event type or log level
- Produce the raw log string by formatting all entries as timestamped lines
- Return a `StructuredLog` with all three levels populated

**Done when:** The function is importable, all input/output types are satisfied by TypeScript, and manual spot-checks against a real session's API response produce correct summary and step data.

---

## Phase 2 — Log Viewer Component

### 2.1 — Implement `LogSummaryPanel` sub-component

Create `frontend/src/components/logs/LogSummaryPanel.tsx`.

This component receives a `LogSummary` prop and renders the Execution Summary card from the prototype:
- A grid of summary items (identity, role, model, SOPs/skills as chips, plan progress as `N/N Steps Completed`)
- A status badge (green for success, red for failure) aligned to the card header
- All text routed through `t()` for i18n

**Done when:** The component renders correctly against a mock `LogSummary` and all labels use i18n keys.

---

### 2.2 — Implement `WorkingStepsPanel` sub-component

Create `frontend/src/components/logs/WorkingStepsPanel.tsx`.

This component receives `WorkingStep[]` and renders the Execution Details card from the prototype:
- Top-level steps (context loaded, task completed) shown inline as log rows
- All LLM iterations and tool calls wrapped in a single MUI `Collapse` controlled by a collapsible header, collapsed by default
- Each step inside the collapsible shows: icon (colour-coded by type), message, timestamp
- Expandable detail blocks within each step for plan text or tool input/output (collapsed by default)
- Uses MUI `Collapse` or `Accordion` — consistent with existing MUI usage in `AgentJobPage`

**Done when:** Expanding and collapsing the working steps section and individual detail blocks works correctly; the panel is collapsed by default on mount.

---

### 2.3 — Implement `RawLogToggle` control

Create `frontend/src/components/logs/RawLogToggle.tsx`.

A compact toggle control (matching the prototype's "Friendly / Raw Output" toggle) that:
- Accepts `checked` and `onChange` props
- Renders a labelled MUI Switch (or equivalent) with "Friendly" and "Raw Output" labels
- Includes a copy-to-clipboard button that copies the raw log string when in raw mode

**Done when:** The toggle fires `onChange` correctly and the copy button writes to the clipboard.

---

### 2.4 — Assemble `LogViewer` root component

Create `frontend/src/components/logs/LogViewer.tsx`.

This is the top-level component that:
- Accepts `executionLog: ExecutionLogRead` and `entries: ExecutionLogEntry[]` props
- Calls `presentLog()` from `LogPresenter.ts` to derive the `StructuredLog`
- Manages a single `rawMode: boolean` state
- Renders `RawLogToggle` in the header area
- When `rawMode` is false: renders `LogSummaryPanel` then `WorkingStepsPanel`
- When `rawMode` is true: renders a monospace preformatted block containing the raw log string

**Done when:** The component toggles cleanly between friendly and raw views, with no console errors, and the raw log is scrollable.

---

## Phase 3 — Integration

### 3.1 — Replace the existing execution log section in `AgentJobPage`

In `frontend/src/pages/agents/AgentJobPage.tsx`:
- Remove the collapsible "Execution Log" `Paper` section (system instruction + user prompt display)
- Add the `LogViewer` component in its place, fed with `execLogs[0]` from `useExecutionLogs` and the session's execution log entries fetched from `/agents/sessions/{id}/logs`
- The `LogViewer` sits below the session metadata and result sections, consistently with the current page layout
- Loading and empty states from `useExecutionLogs` must be handled (show a spinner while loading, show nothing if no logs available)

**Done when:** Opening an agent session page shows the `LogViewer` where the old execution log section was; the page has no TypeScript errors.

---

### 3.2 — Retire the "View Execution Logs" button from `AgentJobPage`

The `SessionExecutionLogsDialog` button (currently in the session metadata header) is removed from `AgentJobPage` because its functionality is now covered by the `LogViewer`. The `SessionExecutionLogsDialog` component itself is kept for now (it may be referenced elsewhere or useful for future use), but the button that opens it from `AgentJobPage` is removed.

**Done when:** The "View Execution Logs" button no longer appears on the `AgentJobPage`; `showLogs` state and `SessionExecutionLogsDialog` usage are removed from `AgentJobPage.tsx`.

---

## Phase 4 — i18n & Polish

### 4.1 — Add all new translation keys to `en.json`

In `frontend/src/i18n/locales/en.json`, add keys under `agents.sessions` (or a new `agents.sessions.logViewer` namespace) for:
- Summary panel labels: identity, role, model, sopsSkills, planProgress, resultSuccess, resultFailed
- Working steps panel: sectionTitle, iterationCount, viewPlanDetails, viewToolDetails
- Raw toggle: friendlyLabel, rawLabel, copyRaw
- Empty / loading states

**Done when:** All `t()` calls in the new components resolve to defined keys; no missing-key warnings in the console.

---

### 4.2 — Verify responsive layout, accessibility, and MUI theme consistency

- Confirm the summary grid reflows correctly on narrow viewports (matches `repeat(auto-fit, minmax(240px, 1fr))` breakpoint behaviour from the prototype)
- Confirm expand/collapse controls are keyboard-accessible (Enter/Space triggers toggle)
- Confirm all interactive elements have `aria-label` or `aria-expanded` attributes as appropriate
- Confirm colours and typography match the existing MUI theme tokens (no hardcoded hex values)

**Done when:** Visual review and keyboard navigation confirm full compliance; no new linting errors introduced.

---

## Completion Checklist

- [x] `LogPresenter.ts` is implemented and its output types are exported from `frontend/src/types/index.ts`
- [x] `LogSummaryPanel`, `WorkingStepsPanel`, `RawLogToggle`, and `LogViewer` components exist under `frontend/src/components/logs/`
- [x] `AgentJobPage` renders `LogViewer` in place of the old execution log section
- [x] "View Execution Logs" button is removed from `AgentJobPage`
- [x] All new UI strings are defined in `frontend/src/i18n/locales/en.json`
- [x] No TypeScript compiler errors in the frontend project
- [x] Working Steps panel is collapsed by default on page load
- [x] Raw log toggle switches cleanly between friendly and raw views
- [x] Copy-to-clipboard works for raw log output
- [x] Responsive and keyboard-accessible
