# Improve Agent Response Rendering — Test Plan

## 1. Test Strategy

**Overall approach**: Frontend-only change. No backend, database, or API modifications. Testing is entirely component-level (Vitest + React Testing Library) with no E2E or integration tests required for this change.

**Test layers**:
- **Unit tests** (Vitest): Pure utility functions — `containsHtmlTags`, `sanitizeHtml`, `simpleMarkdownToHtml`
- **Component tests** (Vitest + React Testing Library): `ContentRenderer`, `MaximizableContent`, `OutputTypeResultTab`
- **Regression tests** (Vitest + React Testing Library): Existing test suites must continue to pass

**Test tools**: Vitest ^4.1.6, @testing-library/react, jsdom, DOMPurify (via import)

**What is NOT tested**: `ConversationDialog` and `AgentJobPage` integration points are verified manually during review. These components have heavy WebSocket and state management dependencies that make unit testing complex and unreliable; their rendering paths ultimately delegate to `ContentRenderer` and `MaximizableContent`, which are fully tested at the component level. The `OutputTypeResultTab` is tested at the component level since it's the primary rendering dispatcher for execution results.

---

## 2. Coverage Areas

### 2.1 HTML Detection Utility (`contentDetection.ts`)

**Why critical**: The detection logic is the single decision point that determines which rendering path every agent response takes. False positives (detecting HTML when it's markdown) would silently change rendering behavior for all markdown content. False negatives (missing HTML) would leave HTML unrendered.

**Coverage approach**: `containsHtmlTags` and `sanitizeHtml` are exercised through the `ContentRenderer` component tests (`ContentRenderer.test.tsx`). Scenarios covering detection of HTML tags, self-closing tags, angle bracket comparisons, and sanitization of script tags / event handlers are validated at the component render level.

### 2.2 Markdown Utility (`markdown.ts`)

**Why critical**: The `simpleMarkdownToHtml` function is extracted from `OutputTypeResultTab.tsx` into a shared utility. It must remain identical in behavior — any regression would affect every execution detail view displaying markdown output.

**Coverage approach**: `simpleMarkdownToHtml` is exercised through the `ContentRenderer` component tests (`ContentRenderer.test.tsx`). Scenarios covering markdown conversion in `auto` mode, plain-text preservation in `chat` mode, and empty/null handling are validated at the component render level.

### 2.3 ContentRenderer Component (`ContentRenderer.tsx`)

**Why critical**: This component is the rendering engine for all agent response content in every view. It must correctly dispatch to HTML, markdown, or plain-text rendering based on content detection and mode.

**What to test**:

| Scenario | Mode | Expected |
|----------|------|----------|
| HTML content | `auto` | Sanitized HTML rendered via `dangerouslySetInnerHTML` |
| HTML content | `chat` | Sanitized HTML rendered via `dangerouslySetInnerHTML` |
| Markdown content | `auto` | Converted to HTML via `simpleMarkdownToHtml`, then rendered |
| Markdown content | `chat` | Rendered as plain pre-formatted text (no conversion) |
| Plain text | `auto` | Converted to HTML via `simpleMarkdownToHtml` |
| Plain text | `chat` | Rendered as plain pre-formatted text |
| Empty string | either | Renders nothing (null/empty) |
| null content | either | Renders nothing (null/empty) |
| undefined content | either | Renders nothing (null/empty) |

**Additional component-level tests**:
- `<script>` tags in HTML content are sanitized away, not executed
- Event handler attributes in HTML content are stripped
- Mixed content (HTML fragments + markdown) routes via HTML path when HTML tags are detected
- Very long content (thousands of characters) renders without crashing
- Whitespace preservation in `chat` mode for plain text
- Component renders without throwing when DOMPurify encounters completely malformed input
- Prop type: content can be `string | null | undefined`, component handles all gracefully

### 2.4 MaximizableContent Component (`MaximizableContent.tsx`)

**Why critical**: This component provides the maximize/focus-mode affordance. It's a wrapper/decorator — it must not alter how content renders, only provide the maximize UI. Keyboard accessibility is essential.

**What to test**:
- Children rendered inline in normal (non-maximized) state
- Maximize button visible on content area
- Clicking maximize button opens MUI Dialog in full-view mode
- Dialog contains identical rendered content (children passed through unchanged)
- Optional `title` prop displayed in Dialog header when provided
- Optional `title` prop not displayed (or empty) when not provided
- Dialog closes on Escape key press
- Dialog closes on close button (X icon) click
- Dialog closes on backdrop click (if enabled)
- Maximize button accessible via keyboard (Tab, Enter/Space)
- Close button accessible via keyboard (Tab, Enter)
- Dialog has proper ARIA attributes (role, aria-label)
- Focus trap works within dialog (Tab cycles within dialog)
- Multiple MaximizableContent instances operate independently
- Maximize state is local — one instance maximizing does not affect others
- Component renders without children (empty/null children)
- Works with HTML content as children
- Works with plain text content as children
- Works with large content (does not crash with very large child trees)

### 2.5 Integration: OutputTypeResultTab (`OutputTypeResultTab.tsx`)

**Why critical**: This is the execution result renderer. For `auto` output type, HTML detection must bypass markdown processing. The maximize button must appear on result content areas. The existing markdown and typed rendering paths must be unchanged.

**Coverage notes**: Integration-level verification of the `OutputTypeResultTab` changes is covered by manual verification (see implementation plan tasks 3.3–3.5) and by the existing `OutputTypeResultTab.test.tsx` regression suite. Dedicated integration tests for `ContentRenderer`/`MaximizableContent` usage within `OutputTypeResultTab` were not added to the existing test file; the rendering paths for the new components are fully validated in their own component test suites.

### 2.6 Regression: Existing Tests Must Pass

**Why critical**: This change must not break any existing rendering behavior. All current tests must pass without modification to test logic.

**Covered by**:
- All existing tests in `frontend/src/__tests__/OutputTypeResultTab.test.tsx` continue to pass
- All existing tests in `frontend/src/__tests__/TypedOutputRenderer.test.tsx` continue to pass
- All existing tests in `frontend/src/__tests__/AgentExecutionDetailsDialog.test.tsx` continue to pass

### 2.7 Acceptance Criteria (PRD Mapping)

| PRD AC | Coverage | Test File |
|--------|----------|-----------|
| Chat window detects HTML and renders as rich HTML | `ContentRenderer.test.tsx` (mode: chat, HTML content) | Component |
| Execution detail view (auto) detects HTML, renders directly bypassing markdown | `ContentRenderer.test.tsx` (mode: auto), manual verification | Component |
| Plain-text/markdown content renders unchanged | `ContentRenderer.test.tsx` (auto + markdown, chat + plain text) | Component |
| Typed outputs unaffected | `OutputTypeResultTab.test.tsx` (existing typed output type tests unchanged) | Component (regression) |
| HTML sanitized before rendering | `ContentRenderer.test.tsx` (script tag / event handler stripping) | Component |
| Maximize button visible on chat messages and execution results | `MaximizableContent.test.tsx` | Component |
| Maximize opens full-view focus mode | `MaximizableContent.test.tsx` | Component |
| Maximize renders same output as inline | `MaximizableContent.test.tsx` | Component |
| Close/restore from maximize view | `MaximizableContent.test.tsx` | Component |

---

## 3. Critical Scenarios (WHEN/THEN)

### Content-Type Detection

- **WHEN** content starts with `<div>` or `<table>` or `<p>` tag **THEN** `containsHtmlTags` returns `true` and content routes through HTML rendering path
- **WHEN** content is `"<h1>Report</h1><p>Summary text.</p>"` **THEN** it renders as a heading and paragraph with rich formatting
- **WHEN** content is `"# Report\n\nSummary text."` **THEN** `containsHtmlTags` returns `false`, content routes through markdown path (or plain text in chat mode)
- **WHEN** content is `"The value x < 5 and y > 10."` **THEN** `containsHtmlTags` returns `false` — comparison operators are not mistaken for HTML
- **WHEN** content is a string containing `"< random non-tag text >"` **THEN** detection only matches valid-looking tag patterns, not arbitrary angle brackets
- **WHEN** content is `null` or empty **THEN** nothing renders, no error thrown

### ContentRenderer Rendering

- **WHEN** `ContentRenderer` receives HTML content with `mode="auto"` **THEN** the sanitized HTML is rendered via `dangerouslySetInnerHTML` and is visually correct in the DOM
- **WHEN** `ContentRenderer` receives HTML content with `mode="chat"` **THEN** the sanitized HTML is rendered via `dangerouslySetInnerHTML` (same behavior as auto for HTML)
- **WHEN** `ContentRenderer` receives markdown content with `mode="auto"` **THEN** the markdown is converted to HTML and rendered
- **WHEN** `ContentRenderer` receives markdown content with `mode="chat"` **THEN** the raw markdown text is rendered as pre-formatted plain text (whitespace preserved, no conversion)
- **WHEN** `ContentRenderer` receives plain text with `mode="chat"` **THEN** the text is rendered as pre-formatted plain text with newlines preserved
- **WHEN** content contains `<script>alert('xss')</script>` **THEN** the script tag is stripped by DOMPurify before rendering
- **WHEN** content contains `<div onclick="alert('xss')">` **THEN** the onclick attribute is stripped by DOMPurify

### MaximizableContent Flow

- **WHEN** maximize button is clicked **THEN** a full-view MUI Dialog opens containing the same rendered content as the inline view
- **WHEN** Escape key is pressed while dialog is open **THEN** the dialog closes and returns to inline view
- **WHEN** close button (X icon) is clicked **THEN** the dialog closes
- **WHEN** backdrop area is clicked (if enabled) **THEN** the dialog closes
- **WHEN** the maximize dialog is open **THEN** keyboard focus is trapped within the dialog
- **WHEN** `title` prop is provided **THEN** the title text appears in the dialog header
- **WHEN** `title` prop is omitted **THEN** the dialog header shows no title (or a default)

### Integration: OutputTypeResultTab

- **WHEN** output type is `auto` and content is HTML **THEN** `ContentRenderer(mode="auto")` is used and HTML renders directly
- **WHEN** output type is `auto` and content is markdown **THEN** `ContentRenderer(mode="auto")` converts to HTML via markdown
- **WHEN** output type is `markdown` **THEN** behavior is identical to before the change (markdown → HTML rendering)
- **WHEN** output type is `typed` **THEN** behavior is identical to before the change (structured field-by-field view)
- **WHEN** maximize button is visible on the rendered output **THEN** clicking it opens the content in a full-view dialog

---

## 4. Edge Cases & Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Mixed HTML + Markdown content**: Agent output contains both `<table>` tags and markdown syntax like `**bold**` inside the table cells | Medium | Medium — markdown inside HTML tags won't render as markdown | Detection routes to HTML path (HTML presence wins). Document in PRD that HTML-containing content is NOT processed for markdown. |
| **Very large HTML documents**: content string is 500KB+ of HTML table data | Low | Medium — rendering could be slow, DOMPurify could take noticeable time | Test with large content (renders without timeout). Consider lazy loading or virtualization if needed (out of scope for this change). |
| **Malformed HTML**: Unclosed tags, overlapping tags, invalid nesting | Medium | Medium — DOMPurify handles gracefully but layout may look broken | DOMPurify's built-in HTML normalization handles most malformed HTML. Browser renders best-effort. |
| **Comparison operators misidentified as HTML**: Text like `if (a < b && c > d) { ... }` | Low (regex pattern avoids) | High — would route plain text through HTML rendering, corrupting display. Detection regex requires `<` followed by ASCII letter for opening tags. | `containsHtmlTags` regex requires `<` immediately followed by an ASCII letter (`[a-zA-Z]`). Comparison operators like `< 5` have a space after `<`, so they won't match. Comprehensive unit tests for this edge case. |
| **Maximize with very small content**: Single word or sentence | Low | Low — dialog would be mostly empty space | Acceptable. The maximize button is still useful for scanning; operator can close immediately. |
| **Browser zoom/resize in maximize mode**: Content reflows but layout breaks at extreme zoom levels | Low | Low — MUI Dialog handles responsive sizing | Standard MUI Dialog behavior. Content area scrolls if needed. |
| **XSS via unsanitized HTML**: Agent produces `<img src=x onerror=alert(1)>` | High (security) | High — unsanitized HTML in `dangerouslySetInnerHTML` is dangerous | DOMPurify strips `onerror` and all event handlers. Sanitization path tested with known XSS vectors. `dangerouslySetInnerHTML` only used with DOMPurify-sanitized output, never with raw content. |
| **DOMPurify not available / import fails**: Missing dependency | Low | High — component would crash | DOMPurify listed as explicit dependency in package.json. Verified at install time. ContentRenderer should have defensive null-check on DOMPurify. |
| **Maximize button conflicts with existing fullscreen toggle**: Operator confused about which "full screen" to use | Low | Medium — two different expand buttons | PRD specifies these are distinct: fullscreen toggle expands the entire ConversationDialog, maximize expands a single content area. Visual differentiation (different icons, labels, tooltips) clarifies purpose. |
| **Tab order disrupted by maximize dialog**: Focus not trapped, operator tabs to background controls | Medium | Medium — accessibility regression | MUI Dialog provides built-in focus trapping. Verified with keyboard accessibility tests. |

---

## 5. Acceptance Criteria Checklist

### Content-Type Auto-Detection

- [ ] Chat window: HTML content renders as rich formatted HTML (not raw text)
- [ ] Chat window: Non-HTML content renders identically to before (plain text with whitespace)
- [ ] Execution detail view (auto): HTML content renders directly as HTML, bypassing markdown conversion
- [ ] Execution detail view (auto): Non-HTML content continues through markdown conversion
- [ ] Markdown output type: Behavior unchanged from before
- [ ] Typed output type: Behavior unchanged from before (structured field-by-field)
- [ ] HTML content is sanitized before rendering (script tags, event handlers stripped)
- [ ] `auto` output type is the only type subject to HTML detection

### Maximize / Focus Mode

- [ ] Maximize button visible on agent chat message content areas
- [ ] Maximize button visible on execution result content areas
- [ ] Clicking maximize opens full-view focus mode showing only the rendered content
- [ ] Maximize view renders the same output (HTML/markdown/typed) as inline view
- [ ] Maximize view has a clear close/restore mechanism (close button, Escape key)
- [ ] Maximize feature does not interfere with ConversationDialog fullscreen toggle

### Regression Preservation

- [ ] Markdown content renders with standard markdown formatting (unchanged)
- [ ] Typed outputs render field-by-field (unchanged)
- [ ] Plain text renders with preserved whitespace and line breaks (unchanged)
- [ ] All existing tests pass without modification to test logic (only tests may be added)

---

## 6. Test File References

All test files live under `frontend/src/__tests__/` (per `docs/config.yaml` `source.tests`).

### New Test Files Created

| Test File | Tests | Type |
|-----------|-------|------|
| `frontend/src/__tests__/ContentRenderer.test.tsx` | `ContentRenderer` component — all mode × content combinations (auto/chat × html/markdown/plain/null), sanitization, mixed content, self-closing tags, angle bracket comparisons; also exercises `containsHtmlTags`, `sanitizeHtml`, and `simpleMarkdownToHtml` through the component | Component |
| `frontend/src/__tests__/MaximizableContent.test.tsx` | `MaximizableContent` component — maximize/restore flow, keyboard accessibility, title prop, backdrop click close, independent instances, empty children | Component |

### Existing Test Files (regression — must not break)

| Test File | Reason |
|-----------|--------|
| `frontend/src/__tests__/OutputTypeResultTab.test.tsx` | Core output rendering — all existing test assertions must continue to pass |
| `frontend/src/__tests__/TypedOutputRenderer.test.tsx` | Typed output rendering must be unaffected |
| `frontend/src/__tests__/AgentExecutionDetailsDialog.test.tsx` | Execution detail dialog uses OutputTypeResultTab internally |
| `frontend/src/__tests__/AgentOutputDetailDrawer.test.tsx` | Output detail drawer may use OutputTypeResultTab |
