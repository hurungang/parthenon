# Improve Agent Response Rendering — Technical Specification

## 1. Technical Overview

This is a frontend-only change that introduces HTML content auto-detection in agent response rendering and a maximize/focus-mode affordance for rendered output areas. Two new reusable React components are created: `ContentRenderer` inspects content strings to determine whether they contain HTML and routes rendering through the appropriate path (sanitized HTML, markdown conversion, or plain pre-formatted text). `MaximizableContent` wraps any content area with a maximize button that opens a full-view dialog. Both are integrated into the existing `OutputTypeResultTab` component (which renders execution results for all output types) and the two chat interfaces in `ConversationDialog` and `AgentJobPage`.

## 2. Component Breakdown

### 2.1 ContentRenderer

**File:** `frontend/src/components/ContentRenderer.tsx`

**Responsibility:** Inspects a content string and renders it through the correct pipeline based on detected format and rendering context.

**Props:**
- `content: string | null | undefined` — the raw agent response content
- `mode: 'auto' | 'chat'` — rendering context (default `'auto'`)

**Behavior matrix:**

| Content contains HTML? | Mode | Rendering path |
|------------------------|------|----------------|
| Yes | `auto` | Sanitize with DOMPurify → render via `dangerouslySetInnerHTML` |
| Yes | `chat` | Sanitize with DOMPurify → render via `dangerouslySetInnerHTML` |
| No | `auto` | Convert through `simpleMarkdownToHtml` → render via `dangerouslySetInnerHTML` |
| No | `chat` | Render as plain pre-formatted text with whitespace preservation |
| Empty / null / undefined | either | Render nothing (return null or empty fragment) |

### 2.2 MaximizableContent

**File:** `frontend/src/components/MaximizableContent.tsx`

**Responsibility:** Wraps any content area with a maximize button that opens the same content in a full-view MUI `Dialog`. Acts as a pure layout/decorator — does not alter how content is rendered.

**Props:**
- `children: React.ReactNode` — the rendered content to display inline and in the maximize dialog
- `title?: string` — optional title displayed in the maximize dialog header

**Behavior:**
- Renders `children` normally in the inline layout
- Displays a small maximize icon button (MUI icon) positioned absolutely in the top-right of the content container
- When maximize is clicked, opens a fullscreen/near-fullscreen MUI `Dialog` containing the same `children`
- Dialog closes via: close button (X icon), Escape key, or clicking outside (if enabled)
- Title prop is displayed in the dialog's `DialogTitle`

### 2.3 HTML Detection Utility

**File:** `frontend/src/utils/contentDetection.ts`

**Responsibility:** Provides stateless utility functions for content type detection and HTML sanitization.

**Exports:**
- `containsHtmlTags(content: string): boolean` — tests whether a string contains HTML markup via regex
- `sanitizeHtml(html: string): string` — sanitizes HTML string using DOMPurify, stripping disallowed tags and attributes

The detection regex pattern matches opening or closing HTML tags by looking for `<` followed immediately by an ASCII letter (for opening tags) or `</` followed by an ASCII letter (for closing tags). This avoids false positives on comparison operators (`< 5`) or template expressions.

### 2.4 Markdown Utility (Extracted)

**File:** `frontend/src/utils/markdown.ts` (new) or added to existing utility

**Responsibility:** The `simpleMarkdownToHtml` function currently defined at the bottom of `OutputTypeResultTab.tsx` is extracted to a shared utility file so it can be imported by both `OutputTypeResultTab` and `ContentRenderer` without circular dependencies. The function itself is unchanged in behavior.

### 2.5 Modified Components

#### OutputTypeResultTab
**File:** `frontend/src/components/executions/OutputTypeResultTab.tsx`

The `auto` output type branch replaces its direct `simpleMarkdownToHtml` call with `<ContentRenderer mode="auto" content={autoExtractedText} />`. The `markdown` output type and `typed` output type branches are unchanged in their rendering logic. Both are wrapped with `MaximizableContent` around their content containers.

The `simpleMarkdownToHtml` function definition at the bottom of the file is removed and re-imported from the shared utility.

#### ConversationDialog
**File:** `frontend/src/components/agents/ConversationDialog.tsx`

The agent message rendering (lines 693–711 in the timeline entries mapping) conditionally uses `ContentRenderer` with `mode="chat"` when `msg.role !== 'user'`. The rendered agent message content area is wrapped with `MaximizableContent`. User messages are unchanged.

#### AgentJobPage
**File:** `frontend/src/pages/agents/AgentJobPage.tsx`

Two integration points:
1. **Chat interface** (lines 530–563): Agent messages (`msg.role !== 'user'`) use `ContentRenderer` with `mode="chat"` and are wrapped with `MaximizableContent`. User messages unchanged. The conversation history view (lines 669–709) also uses `ContentRenderer`/`MaximizableContent` for agent messages.
2. **Result view** (lines 597–641): Already uses `OutputTypeResultTab` for typed outputs; the `auto` fallback rendering path now benefits from the changes in `OutputTypeResultTab`. The standalone markdown `dangerouslySetInnerHTML` path for `session.output_data.markdown` remains unchanged (not routed through `ContentRenderer`) since this data is already expected to be markdown-safe.

## 3. API Changes

None. This change is entirely client-side and does not modify any backend endpoints, request/response schemas, or data contracts.

## 4. State Management

### MaximizableContent internal state

The `MaximizableContent` component manages a single piece of local React state:
- `isMaximized: boolean` — tracks whether the full-view dialog is open

This state is internal to the component instance and does not affect any global or shared state. Each `MaximizableContent` instance is independent.

### No other state changes

The existing components (`OutputTypeResultTab`, `ConversationDialog`, `AgentJobPage`) do not gain new state for content rendering. The auto-detection is purely functional — it inspects the content string synchronously at render time without caching or persisting the detected type.

## 5. Data Access Patterns

### Content inspection (synchronous, client-side)

The `containsHtmlTags` function performs a regex test on the content string. This happens synchronously during React rendering and does not involve any network request, database query, or async operation.

### DOMPurify sanitization (synchronous, client-side)

The `sanitizeHtml` function calls DOMPurify's synchronous API. The sanitized output is passed to `dangerouslySetInnerHTML` in the React component's render output.

### Existing data flow (unchanged)

All content strings flow from the backend via existing REST API responses or WebSocket messages. The `ContentRenderer` receives the content string as a prop from the parent component, which obtained it from:
- `outputData` prop (in `OutputTypeResultTab`) — sourced from session output_data or typed output field_values
- `msg.content` (in chat interfaces) — sourced from WebSocket messages (`useChatSession`) or REST responses

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ContentRenderer` | Component | Renders agent response content with HTML/markdown/plain-text detection | `frontend/src/components/ContentRenderer.tsx` |
| `MaximizableContent` | Component | Wraps content area with maximize button and full-view dialog | `frontend/src/components/MaximizableContent.tsx` |
| `ContentRenderer.test.tsx` | Test | Unit tests for ContentRenderer component | `frontend/src/__tests__/ContentRenderer.test.tsx` |
| `MaximizableContent.test.tsx` | Test | Unit tests for MaximizableContent component | `frontend/src/__tests__/MaximizableContent.test.tsx` |
| `containsHtmlTags` | Function | Regex-based HTML tag detection in strings | `frontend/src/utils/contentDetection.ts` |
| `sanitizeHtml` | Function | Sanitizes HTML strings via DOMPurify | `frontend/src/utils/contentDetection.ts` |
| `simpleMarkdownToHtml` | Function | Converts markdown text to HTML (extracted from OutputTypeResultTab) | `frontend/src/utils/markdown.ts` |
| `escapeHtml` | Function | Escapes HTML special characters in a string for safe embedding | `frontend/src/utils/markdown.ts` |
| `OutputTypeResultTab` | Component | Central dispatcher for rendering execution results by output type | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `OutputTypeResultTabProps` | Interface | Props for OutputTypeResultTab (unchanged schema) | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `ConversationDialog` | Component | Dialog-based chat interface for conversational agents | `frontend/src/components/agents/ConversationDialog.tsx` |
| `AgentJobPage` | Component | Standalone agent session page with chat and result views | `frontend/src/pages/agents/AgentJobPage.tsx` |
| `AgentExecutionDetailsDialog` | Component | Tabbed execution detail dialog (uses OutputTypeResultTab for result tab) | `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` |
| `SessionExecutionLogsDialog` | Component | Session execution logs dialog with result tab | `frontend/src/pages/agents/SessionExecutionLogsDialog.tsx` |
| `extractResultText` | Function | Extracts plain text from content block arrays or strings | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `badgeForType` | Function | Returns badge style config for an output type | `frontend/src/components/executions/OutputTypeResultTab.tsx` |

## 7. Dependency Additions

| Package | Version | Purpose |
|---------|---------|---------|
| `dompurify` | ^3.x | Sanitize agent-generated HTML content before rendering |
| `@types/dompurify` | ^3.x | TypeScript type definitions for DOMPurify |

## 8. File Change Summary

| Action | File |
|--------|------|
| **Create** | `frontend/src/components/ContentRenderer.tsx` |
| **Create** | `frontend/src/components/MaximizableContent.tsx` |
| **Create** | `frontend/src/utils/contentDetection.ts` |
| **Create** | `frontend/src/utils/markdown.ts` |
| **Create** | `frontend/src/__tests__/ContentRenderer.test.tsx` |
| **Create** | `frontend/src/__tests__/MaximizableContent.test.tsx` |
| **Modify** | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| **Modify** | `frontend/src/components/agents/ConversationDialog.tsx` |
| **Modify** | `frontend/src/pages/agents/AgentJobPage.tsx` |
| **Modify** | `frontend/package.json` (add dompurify, @types/dompurify) |
