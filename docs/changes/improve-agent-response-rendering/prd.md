# Improve Agent Response Rendering — PRD

## Epic Overview

Parthenon currently renders agent responses in two places — the chat window and execution detail views — with no awareness of the actual content format. In chat windows, every agent message is displayed as raw plain text, so HTML-rich responses from non-conversational agents appear as unreadable markup rather than rendered content. In execution detail views, all content is indiscriminately processed through markdown-to-HTML conversion, which can corrupt already-formatted HTML responses. This inconsistency degrades the operator experience and obscures the agent's intended output. This epic introduces content-type auto-detection so that HTML responses render as HTML and plain-text/markdown responses render correctly — in both chat and execution views — and adds a maximize button that lets operators expand any rendered output into a focused, full-content view.

## Business Goals

- **Eliminate raw markup display** — Operators never see unrendered HTML tags in agent responses; content renders as the agent intended in all views.
- **Ensure consistent rendering across views** — Chat windows and execution detail views apply the same content-type detection logic so agent output looks correct regardless of where it is viewed.
- **Give operators a focused review mode** — A maximize button on rendered content areas lets operators inspect large or complex agent outputs in a distraction-free, full-content view.
- **Preserve existing rendering quality** — Plain text, markdown, and typed output rendering continue to work exactly as they do today; only HTML responses—currently broken—change behaviour.

## Users & Personas

- **Platform Operators** — The primary beneficiaries. They review agent execution results in execution detail views and agent messages in conversation windows. They need rendered output that matches what the agent intended, not raw HTML source.
- **SOP Authors** — Test agent workflows and verify output formats. They need to see the final rendered output — whether HTML or markdown — to validate that agents produce correctly formatted results.
- **Business Users / Analysts** — Interact with agents via the chat window and review outputs; they expect rich, properly formatted agent responses without technical noise.

## User Stories

- As a platform operator reviewing a non-conversational agent execution, I want the execution result to auto-detect whether the content is HTML or markdown and render it appropriately, so that I always see the intended visual output instead of raw markup or corrupted rendering.
- As a platform operator chatting with an agent, I want HTML responses to render inline in the chat as formatted content, so that I can read tables, lists, and styled text without seeing raw HTML tags.
- As a platform operator examining a long or complex agent output, I want to click a maximize button to expand the content into a focused full-view, so that I can review the result in detail without surrounding UI distractions.
- As an SOP author testing an agent that produces HTML reports, I want the chat and execution views to render the HTML correctly, so that I can confirm the output format meets requirements before deploying to production.
- As a business user interacting with agents conversationally, I want rich agent responses to display as intended — with proper formatting — so that my workflow is not interrupted by having to interpret raw markup.

## Acceptance Criteria

### Content-Type Auto-Detection

- Agent responses in the **chat window** detect whether content contains HTML tags and render it as rich HTML instead of raw plain text
- Agent responses in the **execution detail view** (`auto` output type) detect whether content contains HTML tags and render it directly as HTML, bypassing markdown-to-HTML conversion
- Plain-text and markdown content (no HTML tags detected) renders exactly as it does today — through markdown conversion in execution views and as pre-formatted text in chat views
- Content-type detection applies to the `auto` output type where the agent may return any format
- Typed outputs (schema-validated results) are unaffected and continue to render with their existing structured field-by-field layout
- HTML content is sanitised before rendering to maintain security, consistent with existing platform rendering standards

### Maximize / Focus Mode

- A maximize button is visible on both agent chat messages and execution result content areas
- Clicking the maximize button opens the rendered output in a full-view focus mode, showing only the content without surrounding UI chrome
- The maximize view presents the same rendered output (HTML, markdown, or typed) that was visible in the inline view, just at full size
- The maximize view provides a clear way to close or restore back to the normal inline view (for example, a close button or click-outside behaviour)
- The maximize feature does not interfere with the existing full-screen toggle on the ConversationDialog (which expands the entire dialog, not an individual output)

### Regression Preservation

- All existing rendering behaviours continue unchanged for non-HTML content: markdown renders with standard markdown formatting, typed outputs render field-by-field, plain text renders with preserved whitespace and line breaks
- The maximize button does not alter how content is rendered — only the viewport size and surrounding UI
- Conversational agent messages continue to display correctly in the chat window; only the rendering of HTML content changes

## Out of Scope

- **Agent output generation** — This epic only changes how already-generated responses are rendered; it does not alter how agents produce content or what output types are possible.
- **Backend content-type metadata** — The system does not store or infer content type on the backend; detection is client-side at render time.
- **Real-time streaming format detection** — Content-type detection occurs when the final output is rendered, not mid-stream.
- **ConversationDialog fullscreen toggle changes** — The existing fullscreen toggle (which expands the entire dialog) is unchanged; the new maximize button targets individual rendered output areas.
- **Editing or modifying agent responses** — Operators cannot edit agent output content; they can only view it.
- **Print or export of maximized content** — The maximize view is a display-only feature; no new export or print capabilities are included.
- **New output types** — The existing output types (`auto`, `markdown`, `typed`, and conversational) remain the only supported types.

## Dependencies & Constraints

- **Client-side only** — All content-type detection and maximize functionality is implemented in the frontend; no backend, database, or API changes are required.
- **Existing rendering pipeline** — The current markdown-to-HTML conversion must be preserved and applied only when content is not detected as HTML; the HTML rendering path must maintain the platform's existing content sanitisation standards.
- **Existing UI framework** — Implementation must integrate with the current frontend technology stack without introducing new framework dependencies.
- **Fullscreen coexistence** — The new maximize button must not conflict with the existing fullscreen dialog toggle in the conversation interface.
- **Compatible output types** — The auto-detection logic is designed for the `auto` output type; typed outputs follow their existing schema-driven rendering path and are not subject to HTML detection.
- **Content security** — HTML rendering must maintain the platform's existing content sanitisation standards.
