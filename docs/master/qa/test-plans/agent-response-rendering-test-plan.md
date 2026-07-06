# Agent Response Rendering Test Plan

## Scope

Covers the content-type-aware rendering pipeline for agent responses: HTML/markdown/plain-text auto-detection, the `ContentRenderer` and `MaximizableContent` components, DOMPurify-based sanitization, and integration with the `OutputTypeResultTab` execution result renderer. Frontend-only change — no backend, database, or API modifications.

---

## Coverage Areas

### 1. Content-Type Detection (`contentDetection.ts`)

**What is tested:**
- `containsHtmlTags` regex detects HTML content and returns `true` for opening tags (`<div>`, `<table>`, `<p>`, `<h1>`, etc.) and self-closing tags (`<br/>`, `<img/>`)
- Returns `false` for markdown, plain text, and comparison operators (`x < 5`, `y > 10`) — angle brackets with space after `<` are not mistaken for HTML tags
- Pattern requires `<` immediately followed by an ASCII letter; arbitrary angle brackets (`< random >`) are excluded
- `sanitizeHtml` passes content through DOMPurify; script tags and event handler attributes are stripped
- Both utilities are exercised through `ContentRenderer` component tests, ensuring the full detection→sanitize→render pipeline is validated as a unit

**Acceptance criteria:**
- HTML content (any common tag pattern) detected and routed through HTML rendering path
- Markdown content (headings, bold, lists) NOT detected as HTML — routes through markdown conversion or plain-text path
- Comparison operators in code/log output NOT mistaken for HTML tags
- Sanitized HTML is free of script execution vectors and event handler attributes

**Test files:**
- [frontend/src/__tests__/ContentRenderer.test.tsx](../../../../frontend/src/__tests__/ContentRenderer.test.tsx) — exercises `containsHtmlTags`, `sanitizeHtml`, and `simpleMarkdownToHtml` through the component; covers detection of HTML tags, self-closing tags, angle bracket comparisons, and sanitization of XSS vectors

---

### 2. ContentRenderer Component

**What is tested:**
- `auto` mode + HTML content: sanitized HTML rendered via `dangerouslySetInnerHTML`
- `chat` mode + HTML content: sanitized HTML rendered (same as auto for HTML)
- `auto` mode + markdown content: converted to HTML via `simpleMarkdownToHtml`, then rendered
- `chat` mode + markdown content: rendered as pre-formatted plain text (no conversion, whitespace preserved)
- `auto` mode + plain text: converted to HTML via `simpleMarkdownToHtml`
- `chat` mode + plain text: rendered as pre-formatted plain text
- Empty string, `null`, `undefined` content: renders nothing, no errors thrown
- Long content (thousands of characters): renders without crashing
- Malformed HTML input: component renders without throwing (DOMPurify normalization absorbs)

**Acceptance criteria:**
- HTML content always renders as rich formatted HTML regardless of mode
- Markdown and plain-text content respect mode: converted in `auto`, verbatim in `chat`
- Empty/null/undefined content produces no rendering, no error
- `dangerouslySetInnerHTML` is ONLY used with DOMPurify-sanitized output, never with raw content

**Test files:**
- [frontend/src/__tests__/ContentRenderer.test.tsx](../../../../frontend/src/__tests__/ContentRenderer.test.tsx) — all mode × content-type combinations (auto/chat × html/markdown/plain/null), sanitization validation, mixed content, prop-type handling for `string | null | undefined`

---

### 3. MaximizableContent Component

**What is tested:**
- Normal (non-maximized) state: children rendered inline, maximize button visible on content area
- Maximize button click: opens MUI Dialog in full-view mode containing identical rendered content
- Escape key press: closes dialog, returns to inline view
- Close button (X icon) click: closes dialog
- Backdrop click (when enabled): closes dialog
- Optional `title` prop: displayed in dialog header when provided; omitted/hidden when not provided
- Keyboard accessibility: maximize button reachable via Tab + Enter/Space; close button reachable via Tab + Enter
- Dialog ARIA attributes: proper role, aria-label
- Focus trapping: Tab key cycles within dialog when open
- Independent instances: maximizing one instance does not affect others; maximize state is local
- Edge cases: renders without children (empty/null); works with HTML children, plain text children, large child trees

**Acceptance criteria:**
- Maximize/restore flow is complete: open, view, close via all supported mechanisms
- Inline and maximized content are visually and structurally identical
- Keyboard-accessible throughout the flow
- Multiple instances operate independently

**Test files:**
- [frontend/src/__tests__/MaximizableContent.test.tsx](../../../../frontend/src/__tests__/MaximizableContent.test.tsx) — maximize/restore flow, keyboard accessibility, title prop, backdrop click close, independent instances, empty children, large content

---

### 4. Markdown Utility (`markdown.ts`)

**What is tested:**
- `simpleMarkdownToHtml` converts standard markdown syntax (headings, bold, lists, code blocks) to equivalent HTML
- Preserves existing behavior extracted from `OutputTypeResultTab.tsx` — no regression in conversion output
- Called only in `auto` mode within `ContentRenderer`; bypassed in `chat` mode
- Empty/null input returns empty string without error

**Acceptance criteria:**
- Markdown → HTML conversion output is identical to pre-change behavior
- Bypassed in `chat` mode (raw markdown shown as plain text)
- Graceful handling of empty/null input

**Test files:**
- [frontend/src/__tests__/ContentRenderer.test.tsx](../../../../frontend/src/__tests__/ContentRenderer.test.tsx) — exercised through `ContentRenderer` component tests; covers markdown conversion in `auto` mode, plain-text preservation in `chat` mode, and empty/null handling

---

### 5. Integration: OutputTypeResultTab

**What is tested:**
- `auto` output type + HTML content: `ContentRenderer(mode="auto")` used, HTML renders directly bypassing markdown processing
- `auto` output type + markdown content: `ContentRenderer(mode="auto")` converts to HTML via markdown
- `markdown` output type: behavior identical to pre-change (markdown → HTML rendering)
- `typed` output type: behavior identical to pre-change (structured field-by-field view)
- Maximize button present on rendered output content areas

**Acceptance criteria:**
- Only `auto` output type is subject to HTML detection
- `markdown` and `typed` output types are unaffected
- Maximize button visible on execution result content

**Coverage notes:** Integration verification between `ContentRenderer`/`MaximizableContent` and `OutputTypeResultTab` is covered by existing regression tests. The rendering paths for `ContentRenderer` and `MaximizableContent` are independently validated at the component level.

**Test files:**
- [frontend/src/__tests__/OutputTypeResultTab.test.tsx](../../../../frontend/src/__tests__/OutputTypeResultTab.test.tsx) — existing test suite; all assertions must continue to pass without modification

---

### 6. Regression Preservation

**What is tested:**
- Existing markdown rendering is unchanged (standard formatting preserved)
- Typed output rendering is unchanged (field-by-field structure preserved)
- Plain text rendering is unchanged (whitespace and line breaks preserved)
- No modification to existing test logic — only new test files added

**Test files:**
- [frontend/src/__tests__/OutputTypeResultTab.test.tsx](../../../../frontend/src/__tests__/OutputTypeResultTab.test.tsx) — core output rendering regression guard
- [frontend/src/__tests__/TypedOutputRenderer.test.tsx](../../../../frontend/src/__tests__/TypedOutputRenderer.test.tsx) — typed output rendering regression guard
- [frontend/src/__tests__/AgentExecutionDetailsDialog.test.tsx](../../../../frontend/src/__tests__/AgentExecutionDetailsDialog.test.tsx) — execution detail dialog regression guard

---

## Key Scenarios (WHEN/THEN)

### Content-Type Detection

- **WHEN** content starts with `<div>`, `<table>`, or `<p>` tag **THEN** content routes through HTML rendering path
- **WHEN** content is `"<h1>Report</h1><p>Summary text.</p>"` **THEN** renders as a heading and paragraph with rich formatting
- **WHEN** content is `"# Report\n\nSummary text."` **THEN** routes through markdown path (or plain text in chat mode)
- **WHEN** content is `"The value x < 5 and y > 10."` **THEN** NOT detected as HTML — comparison operators preserved as text
- **WHEN** content contains `<script>alert('xss')</script>` **THEN** script tag is stripped by DOMPurify before rendering
- **WHEN** content contains `<div onclick="alert('xss')">` **THEN** onclick attribute is stripped by DOMPurify

### Rendering Dispatch

- **WHEN** `ContentRenderer` receives HTML content with `mode="auto"` **THEN** sanitized HTML is rendered
- **WHEN** `ContentRenderer` receives markdown content with `mode="auto"` **THEN** markdown is converted to HTML and rendered
- **WHEN** `ContentRenderer` receives markdown/plain text with `mode="chat"` **THEN** raw text is rendered as pre-formatted plain text (no markdown conversion)
- **WHEN** content is `null` or empty **THEN** nothing renders, no error thrown

### MaximizableContent Flow

- **WHEN** maximize button is clicked **THEN** full-view MUI Dialog opens with identical rendered content
- **WHEN** Escape key pressed while dialog is open **THEN** dialog closes, returns to inline view
- **WHEN** close button (X) is clicked **THEN** dialog closes
- **WHEN** dialog is open **THEN** keyboard focus is trapped within the dialog
- **WHEN** `title` prop is provided **THEN** title appears in dialog header; omitted **THEN** header shows no title

---

## Edge Cases & Risks

| Risk | Mitigation |
|------|------------|
| **Mixed HTML + Markdown**: Agent output contains both `<table>` tags and markdown syntax inside cells | Detection routes to HTML path (HTML presence wins). Markdown inside HTML tags is not processed. Documented as intended behavior. |
| **Comparison operators misidentified as HTML**: `if (a < b && c > d)` | Detection regex requires `<` immediately followed by ASCII letter. Space after `<` (as in comparison) prevents false match. Validated in ContentRenderer tests. |
| **XSS via unsanitized HTML**: Agent produces `<img src=x onerror=alert(1)>` | DOMPurify strips event handlers. `dangerouslySetInnerHTML` only used with DOMPurify-sanitized output. XSS vectors tested in ContentRenderer. |
| **DOMPurify not available**: Missing dependency causes component crash | DOMPurify listed as explicit dependency in `package.json`. Defensive null-check present in `ContentRenderer`. |
| **Very large HTML documents**: 500KB+ of HTML table data | Tested with large content — renders without timeout. Virtualization out of scope for this change. |
| **Malformed HTML**: Unclosed tags, invalid nesting | DOMPurify normalizes most malformed HTML. Browser renders best-effort. |
| **Maximize button vs. fullscreen toggle**: Operator confusion between two expand mechanisms | PRD distinguishes: fullscreen toggle expands entire ConversationDialog; maximize expands single content area. Different icons and labels clarify purpose. |
| **Focus trap in maximize dialog**: Tab key escapes to background controls | MUI Dialog provides built-in focus trapping. Verified via keyboard accessibility tests in MaximizableContent. |
| **ConversationDialog / AgentJobPage integration**: New components rendered in complex parent components with WebSocket/state dependencies | Rendering paths ultimately delegate to `ContentRenderer` and `MaximizableContent` which are fully tested at component level. Parent integration verified manually. |

---

## Manual Verification

| Scenario | Why Manual |
|---|---|
| ConversationDialog HTML rendering | Heavy WebSocket and state management dependencies make unit testing complex. Rendering path delegates to `ContentRenderer`, which is fully tested. Visual review confirms correct integration. |
| AgentJobPage maximize button placement | Complex parent component with execution session state. `MaximizableContent` component is independently tested; manual review verifies correct wiring and visual placement. |
| Browser zoom/resize in maximize mode | Pixel-level responsive behavior requires visual review; MUI Dialog handles responsive sizing automatically. |

---

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| improve-agent-response-rendering | Content-type-aware rendering pipeline: HTML auto-detection, `ContentRenderer`, `MaximizableContent`, DOMPurify sanitization, `OutputTypeResultTab` integration | 2026-07-05 |
