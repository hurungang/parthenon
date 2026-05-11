# User-Friendly Agent Logs — Technical Specification

## Technical Overview

This is a **frontend-only** change. The backend API, execution log storage schema, and API response contracts are untouched. The transformation from raw log entries to a user-friendly presentation happens entirely in the browser via a new `LogPresenter` service. A new `LogViewer` component family renders the structured output. The existing `AgentJobPage` is updated to host `LogViewer` in place of its current raw execution log section.

No new API endpoints, no database migrations, no backend code changes.

---

## Component Breakdown

### `LogPresenter`

**Type:** Pure TypeScript service (no React)  
**Responsibility:** Transforms the raw API response — an `ExecutionLogRead` (system instruction, user prompt) and an array of `ExecutionLogEntry` items (event type, message, data, timestamp) — into a `StructuredLog` containing a `LogSummary`, an ordered array of `WorkingStep` items, and a raw log string. All parsing and classification logic lives here. Components are kept free of transformation logic.

---

### `LogViewer`

**Type:** React component (container)  
**Responsibility:** Top-level log display component. Owns the `rawMode` boolean state. Calls `LogPresenter.presentLog()` once per render cycle and routes the output to its child panels. Renders `RawLogToggle` in the header. Conditionally renders either the user-friendly panel pair (`LogSummaryPanel` + `WorkingStepsPanel`) or a monospace raw log block based on `rawMode`.

---

### `LogSummaryPanel`

**Type:** React component (presentational)  
**Responsibility:** Renders the Execution Summary card. Displays identity, role, model, SOPs/skills (as MUI `Chip` elements), plan progress, and result status badge. Receives a `LogSummary` prop; performs no data fetching or transformation.

---

### `WorkingStepsPanel`

**Type:** React component (presentational)  
**Responsibility:** Renders the Execution Details card. Shows top-level steps (context loaded, task completed) as flat log rows. Wraps all LLM iterations and tool calls in a single collapsible section using MUI `Collapse`, collapsed by default. Each step inside the collapsible may contain an expandable detail block (plan text or tool input/output). Receives `WorkingStep[]` as prop.

---

### `RawLogToggle`

**Type:** React component (presentational)  
**Responsibility:** Renders the "Friendly / Raw Output" labelled toggle switch and a copy-to-clipboard button visible in raw mode. Receives `checked`, `onChange`, and `rawLogText` props. No internal state.

---

## API Changes

**None.** This change consumes two existing endpoints already called by `AgentJobPage`:

| Endpoint | Already Used By | Used By Log Viewer |
|---|---|---|
| `GET /agents/sessions/{id}/execution-logs` | `useExecutionLogs` hook → inline execution log section | `useExecutionLogs` hook → `LogViewer` |
| `GET /agents/sessions/{id}/logs` | `SessionExecutionLogsDialog` | `LogViewer` (replaces dialog) |

No new endpoints are added. No request or response schemas change.

---

## State Management

All state is local to `AgentJobPage` and the new components. No global state (Redux, Zustand, React Context) is introduced.

### Changes to `AgentJobPage` local state

| State variable | Before | After |
|---|---|---|
| `showLogs` | Controls `SessionExecutionLogsDialog` open/close | **Removed** — dialog no longer opened from this page |
| `execLogExpanded` | Controls the collapsible execution log section | **Removed** — replaced by `LogViewer` internal state |

### New state in `LogViewer`

| State variable | Type | Purpose |
|---|---|---|
| `rawMode` | `boolean` | Switches between friendly and raw log views |

### Existing state in `WorkingStepsPanel`

| State variable | Type | Purpose |
|---|---|---|
| `expanded` | `boolean` | Controls the collapsible "Agent Working Steps" section (collapsed by default) — owned by `WorkingStepsPanel` |
| `detailOpen` | `boolean` | Controls whether a step's detail block is expanded — owned per `StepRow` instance (local state, not centralised in the panel) |

---

## Data Access Patterns

### Existing data already fetched in `AgentJobPage`

1. **Session metadata** — fetched via `GET /agents/sessions/{id}` (polling until terminal status). Provides `AgentJob.status`, `AgentJob.output_data`, timestamps. No change.

2. **Execution log (system instruction + user prompt)** — fetched via `useExecutionLogs(id)` hook, which calls `GET /agents/sessions/{id}/execution-logs`. Returns `ExecutionLogRead[]`. No change to fetch behaviour; result is passed to `LogViewer`.

### New data fetch added to `AgentJobPage`

3. **Execution log entries** — currently fetched inside `SessionExecutionLogsDialog` on dialog open. After this change, this fetch is moved up into `AgentJobPage` itself (or a new hook), calling `GET /agents/sessions/{id}/logs` to retrieve `ExecutionLogEntry[]`. The entries are passed directly to `LogViewer` alongside the `ExecutionLogRead`.

### Transformation (LogPresenter)

`LogPresenter.presentLog(executionLog, entries)` is called by `LogViewer`. It reads:
- `executionLog.system_instruction` — parsed for identity, role, model name, and loaded SOPs/skills
- `executionLog.user_prompt` — used to derive plan summary if the agent emits a structured plan header
- `entries` — all entries are mapped to `WorkingStep` items in chronological order; `iconType` is derived from `event_type`: `llm_call`/`llm_start`/`llm_end` → `'llm'`; `tool_call`/`tool_start`/`tool_end` → `'tool'`; `agent_finish`/`task_complete`/`session_complete`/`chain_end` → `'success'`; `error` or `ERROR`/`CRITICAL` log level → `'error'`; all others → `'info'`; top-level steps (non-`llm`/`tool` icon types) are rendered as flat rows outside the collapsible; the final entry's `event_type`/`log_level` determines overall result status
- All entries serialised to timestamped lines for the raw log string

No network calls are made inside `LogPresenter`. It is a pure synchronous function.

---

## Code Reference Map

| Symbol | Type | Description | File |
|---|---|---|---|
| `StructuredLog` | interface | Container for all three presentation levels produced by `LogPresenter` | `frontend/src/types/index.ts` |
| `LogSummary` | interface | Summary data: identity, role, model, SOPs/skills, plan progress, result status, and `startedAt`/`completedAt` timestamps (derived from first/last entry) | `frontend/src/types/index.ts` |
| `WorkingStep` | interface | Single LLM iteration or tool call with message, timestamp, icon type, and optional detail payload | `frontend/src/types/index.ts` |
| `WorkingStepDetail` | interface | Collapsible detail block for a step: label + content string | `frontend/src/types/index.ts` |
| `WorkingStepIconType` | type | Union type for step icon variants: `'llm' \| 'tool' \| 'success' \| 'error' \| 'info'` | `frontend/src/types/index.ts` |
| `ExecutionLogRead` | interface | Existing type: system instruction and user prompt captured before first LLM call | `frontend/src/types/index.ts` |
| `ExecutionLogEntry` | interface | Individual log entry with event_type, message, data — moved from local `SessionExecutionLogsDialog` to shared types | `frontend/src/types/index.ts` |
| `presentLog` | function | Pure transformation: `presentLog(executionLog, entries): StructuredLog` | `frontend/src/services/LogPresenter.ts` |
| `LogViewer` | component | Root log display component; owns `rawMode` state; routes data to child panels | `frontend/src/components/logs/LogViewer.tsx` |
| `LogSummaryPanel` | component | Execution Summary card: identity, role, model, SOPs/skills, plan, result badge | `frontend/src/components/logs/LogSummaryPanel.tsx` |
| `WorkingStepsPanel` | component | Execution Details card: flat top-level steps + collapsible LLM/tool steps with detail blocks | `frontend/src/components/logs/WorkingStepsPanel.tsx` |
| `RawLogToggle` | component | Friendly/Raw Output toggle switch and copy-to-clipboard button | `frontend/src/components/logs/RawLogToggle.tsx` |
| `useExecutionLogs` | hook | Existing hook: fetches `ExecutionLogRead[]` from `GET /agents/sessions/{id}/execution-logs` | `frontend/src/hooks/useExecutionLogs.ts` |
| `AgentJobPage` | page | Updated: renders `LogViewer` in place of raw execution log section; fetches `ExecutionLogEntry[]` inline; `showLogs`/`execLogExpanded` state removed | `frontend/src/pages/agents/AgentJobPage.tsx` |
| `SessionExecutionLogsDialog` | component | Retained but no longer opened from `AgentJobPage`; "View Execution Logs" button removed | `frontend/src/pages/agents/SessionExecutionLogsDialog.tsx` |
| `en.json` | i18n | Translation strings for all new Log Viewer labels under `agents.sessions.logViewer.*` | `frontend/src/i18n/locales/en.json` |
