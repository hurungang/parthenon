# Demo Cases: improve-agent-response-rendering
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/improve-agent-response-rendering/demo-cases.md -->

> **Note:** This is a frontend-only rendering change with no backend, API, or database modifications. All tests are Vitest + React Testing Library component/unit tests. There are no E2E Playwright tests for this change. The Grep Patterns below reference Vitest test titles using the `describe > it` convention matching Playwright's format for compatibility with demo-app tooling.

## Grep Patterns
<!-- One Vitest test title per line (describe > it name format) -->
<!-- demo-app reads these lines for --grep regex matching -->
- ContentRenderer > renders complex nested HTML
- ContentRenderer > strips script tags via DOMPurify
- ContentRenderer > handles mixed HTML and markdown-like content by following HTML path
- ContentRenderer > does not treat angle bracket comparison as HTML
- MaximizableContent > opens dialog when maximize button is clicked
- MaximizableContent > closes dialog via Escape key
- OutputTypeResultTab > extracts text from Claude content blocks for auto output type

## Scenario Details
| # | Feature | What it Shows | Test File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Rich HTML Rendering | Tables, headings, and nested divs render as formatted content — not raw markup | ContentRenderer.test.tsx | renders complex nested HTML |
| 2 | XSS Sanitization | `\<script\>` tags are stripped before rendering via DOMPurify; safe content preserved | ContentRenderer.test.tsx | strips script tags via DOMPurify |
| 3 | HTML Detection Priority | When content contains both HTML tags and markdown syntax, HTML rendering path wins; markdown syntax appears as literal text, not converted | ContentRenderer.test.tsx | handles mixed HTML and markdown-like content by following HTML path |
| 4 | False-Positive Avoidance | Comparison operators like `x \< 5` are NOT misdetected as HTML tags; plain text passes through markdown conversion normally | ContentRenderer.test.tsx | does not treat angle bracket comparison as HTML |
| 5 | Maximize to Full-View | Clicking maximize button opens an MUI Dialog containing the same rendered content; title displayed in dialog header; content appears both inline and in dialog | MaximizableContent.test.tsx | opens dialog when maximize button is clicked |
| 6 | Keyboard Dismiss | Escape key closes the maximize dialog and returns to inline view | MaximizableContent.test.tsx | closes dialog via Escape key |
| 7 | Execution Integration | Auto output type with Claude content blocks flows through ContentRenderer for HTML detection and rendering; markdown content blocks are extracted and rendered correctly | OutputTypeResultTab.test.tsx | extracts text from Claude content blocks for auto output type |
