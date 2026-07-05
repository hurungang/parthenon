## Overview

This change introduces content-type-aware rendering for agent responses across chat and execution views, plus a maximize button for focused output review. Two new reusable components are created — `ContentRenderer` and `MaximizableContent` — then integrated into `OutputTypeResultTab` and the two chat interfaces. No backend, database, or API changes are required; all detection and rendering is client-side.

## Task Checklist

### Phase 1 — HTML Detection & ContentRenderer Component
- [x] 1.1 — Create HTML detection utility
- [x] 1.2 — Add DOMPurify dependency
- [x] 1.3 — Create ContentRenderer component
- [x] 1.4 — Integrate ContentRenderer into OutputTypeResultTab for `auto` output type
- [x] 1.5 — Integrate ContentRenderer into ConversationDialog agent chat messages
- [x] 1.6 — Integrate ContentRenderer into AgentJobPage chat interface

### Phase 2 — MaximizableContent Component
- [x] 2.1 — Create MaximizableContent wrapper component
- [x] 2.2 — Integrate MaximizableContent into OutputTypeResultTab rendered result area
- [x] 2.3 — Integrate MaximizableContent into ConversationDialog agent chat messages
- [x] 2.4 — Integrate MaximizableContent into AgentJobPage chat messages

### Phase 3 — Testing & Validation
- [x] 3.1 — Write unit tests for ContentRenderer
- [x] 3.2 — Write unit tests for MaximizableContent
- [x] 3.3 — Verify all rendering paths (HTML, markdown, plain text, typed) render correctly
- [x] 3.4 — Verify maximize/close works in all integration points
- [x] 3.5 — Verify no regression for typed output, markdown output, or conversational agents

---

## Phase 1 — HTML Detection & ContentRenderer Component

### Task 1.1 — Create HTML detection utility
**Done when:** A `containsHtmlTags(content: string): boolean` function exists in `frontend/src/utils/contentDetection.ts`, detects `<p>`, `<div>`, `<table>`, `<h1>`–`<h6>`, `<ul>`, `<ol>`, `<li>`, `<br>`, `<hr>`, `<strong>`, `<em>`, `<span>`, `<pre>`, `<code>`, and any other well-formed HTML opening or closing tag via regex, and returns `true`/`false` accordingly.

Create a single utility function that inspects a string for the presence of HTML tags. The function uses a regex that matches any opening or closing HTML tag. It must avoid false positives on text containing angle brackets for comparisons (e.g., `< 5`) by requiring an ASCII letter immediately after `<` or `</`.

### Task 1.2 — Add DOMPurify dependency
**Done when:** `dompurify` and `@types/dompurify` are installed in the frontend project, the HTML content sanitization function is added to the new content detection utility file, and `npm run build` succeeds without errors.

Install the DOMPurify library to sanitize HTML content before rendering via `dangerouslySetInnerHTML`. Create an `sanitizeHtml(html: string): string` export in the utility file. This ensures agent-generated HTML responses are safe to render directly.

### Task 1.3 — Create ContentRenderer component
**Done when:** `ContentRenderer` component exists at `frontend/src/components/ContentRenderer.tsx`, accepts `content: string | null | undefined` and optional `mode: 'auto' | 'chat'` (default `'auto'`) props, detects HTML content via the utility from Task 1.1, and renders accordingly:
- For HTML content: sanitizes with DOMPurify then renders via `dangerouslySetInnerHTML` with standard container styling
- For non-HTML content in `auto` mode: runs markdown conversion via existing `simpleMarkdownToHtml` (extracted from OutputTypeResultTab) and renders the result
- For non-HTML content in `chat` mode: renders as plain pre-formatted text preserving whitespace and line breaks

The component must handle all edge cases: empty content, null/undefined content, and very long content. Extracting `simpleMarkdownToHtml` from `OutputTypeResultTab.tsx` into a shared utility avoids duplication.

### Task 1.4 — Integrate ContentRenderer into OutputTypeResultTab for `auto` output type
**Done when:** The `auto` output type branch in `OutputTypeResultTab.tsx` (lines 479–518) uses `ContentRenderer` with `mode="auto"` instead of directly calling `simpleMarkdownToHtml`. HTML content renders as rich HTML; non-HTML content continues through markdown conversion. The existing JSON fallback (when no text is extracted) remains unchanged — it only applies when text extraction fails entirely.

The `auto` output type experiences two behavioral changes:
- Text that contains HTML tags is now rendered directly as sanitized HTML (it no longer passes through `simpleMarkdownToHtml`)
- Text without HTML tags continues through `simpleMarkdownToHtml` as before

The `markdown` output type is unchanged — it continues to use `simpleMarkdownToHtml` unconditionally. The `typed` output type is unchanged. The validation error fallback is unchanged.

### Task 1.5 — Integrate ContentRenderer into ConversationDialog agent chat messages
**Done when:** The agent message rendering in `ConversationDialog.tsx` (lines 693–711) uses `ContentRenderer` with `mode="chat"` for agent role messages. HTML content from agents renders as rich formatted HTML; plain text messages continue to render as pre-formatted text. User messages are unchanged (they always render as plain text).

Only agent messages (`msg.role !== 'user'`) use `ContentRenderer`. User messages continue rendering as plain text wrapped in `<Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>`.

### Task 1.6 — Integrate ContentRenderer into AgentJobPage chat interface
**Done when:** The chat message rendering in `AgentJobPage.tsx` (lines 530–563) uses `ContentRenderer` with `mode="chat"` for agent role messages. HTML content from agents renders as rich formatted HTML in the chat interface; plain text messages continue to render as pre-formatted text.

Same approach as Task 1.5 — only agent role messages use `ContentRenderer`. User messages remain unchanged.

---

## Phase 2 — MaximizableContent Component

### Task 2.1 — Create MaximizableContent wrapper component
**Done when:** `MaximizableContent` component exists at `frontend/src/components/MaximizableContent.tsx`, accepts `children: React.ReactNode` and optional `title?: string` props, renders a maximize icon button (using MUI's `OpenInFullIcon` or equivalent) positioned in the top-right corner of the content area, and when clicked opens a full-view MUI `Dialog` containing the same children rendered at full available viewport size.

The maximize button must be:
- Subtle and unobtrusive in the inline view (small icon button)
- Clearly visible on hover or at all times
- Positioned absolutely in the top-right of the content container
- Labeled appropriately for accessibility

The maximize dialog must:
- Render the exact same `children` (not a copy) — the content renders identically to the inline view
- Open at maximum practical size (fullscreen or near-fullscreen dialog)
- Have a close button (X in the dialog title bar) to restore to inline view
- Support the Escape key to close
- Display the optional `title` in the dialog header

### Task 2.2 — Integrate MaximizableContent into OutputTypeResultTab rendered result area
**Done when:** The rendered output content area in `OutputTypeResultTab.tsx` is wrapped with `MaximizableContent` for the `auto` output type branch. The maximize button appears on the result content area and opens the full-content view. The markdown and typed output types also get the maximize button wrapping their respective content areas.

The maximize button integrates at the appropriate level: wrapping the content container (the `Box` that holds the rendered output), not the entire tab including meta row and badges. The title prop uses a relevant translated label like "Agent Output" or "Structured Output" depending on the output type.

### Task 2.3 — Integrate MaximizableContent into ConversationDialog agent chat messages
**Done when:** Each rendered agent message in `ConversationDialog.tsx` shows a maximize button. Clicking it opens the individual message's rendered content in a focused full-view dialog. The maximize button does not conflict with the existing fullscreen toggle on the ConversationDialog (which expands the entire dialog).

The maximize button appears on the rendered content paper of each agent message. It targets individual message content, not the entire chat window. The existing fullscreen dialog toggle (which expands the whole ConversationDialog) is completely unaffected.

### Task 2.4 — Integrate MaximizableContent into AgentJobPage chat messages
**Done when:** Each rendered agent message in `AgentJobPage.tsx` chat interface shows a maximize button with the same behavior as Task 2.3 — individual message content maximize to full-view dialog.

Same integration pattern as Task 2.3, applied to the chat interface within the standalone AgentJobPage.

---

## Phase 3 — Testing & Validation

### Task 3.1 — Write unit tests for ContentRenderer
**Done when:** Unit tests exist at `frontend/src/__tests__/ContentRenderer.test.tsx` covering:
- HTML content detects and renders as sanitized HTML (verify HTML tags are present in output)
- Markdown content in `auto` mode renders through markdown conversion (verify converted HTML)
- Plain text content in `chat` mode renders as pre-formatted text with whitespace preserved
- Empty content renders without error
- Null/undefined content renders without error
- HTML containing script tags is stripped by DOMPurify
- Mixed content (HTML with markdown-like syntax) correctly follows the HTML path

### Task 3.2 — Write unit tests for MaximizableContent
**Done when:** Unit tests exist at `frontend/src/__tests__/MaximizableContent.test.tsx` covering:
- Maximize button is rendered in the content area
- Clicking maximize opens the full-view dialog
- The dialog contains the same children as the inline view
- Close button in dialog closes it and returns to inline view
- Escape key closes the dialog
- Optional title prop is displayed in the dialog header

### Task 3.3 — Verify all rendering paths (HTML, markdown, plain text, typed) render correctly
**Done when:** Manual verification confirms:
- `auto` output type with HTML content renders as rich HTML in execution details
- `auto` output type with markdown content renders through markdown conversion in execution details
- `auto` output type with plain text renders correctly in execution details
- Agent chat messages with HTML render as rich formatted HTML in both ConversationDialog and AgentJobPage
- Agent chat messages with plain text render as pre-formatted text in both chat interfaces
- `markdown` output type renders unchanged
- `typed` output type renders unchanged (field-by-field structured view)

### Task 3.4 — Verify maximize/close works in all integration points
**Done when:** Manual verification confirms the maximize button appears and functions correctly in all four integration points:
- Execution result in OutputTypeResultTab (via AgentExecutionDetailsDialog)
- Execution result in standalone AgentJobPage
- Chat messages in ConversationDialog
- Chat messages in AgentJobPage chat interface

### Task 3.5 — Verify no regression for typed output, markdown output, or conversational agents
**Done when:** All existing unit tests pass (`npx vitest run`), and manual verification confirms:
- Typed output with schema renders the structured field-by-field view
- Typed output with validation errors shows the error banner and raw fallback
- Markdown output renders with standard markdown formatting (headings, lists, code blocks, bold, italic)
- Conversational agent messages continue to display correctly
- The ConversationDialog fullscreen toggle still works independently of the maximize button
- JSON fallback rendering (when `auto` text extraction fails) is unaffected

---

## Completion Checklist
- [x] All tasks in Phase 1 completed
- [x] All tasks in Phase 2 completed
- [x] All tasks in Phase 3 completed
- [x] All unit tests pass (frontend)
- [x] No TypeScript compilation errors (`npm run type-check`)
