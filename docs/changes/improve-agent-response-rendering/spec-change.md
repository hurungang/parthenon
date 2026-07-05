# Specification Delta — Improve Agent Response Rendering

## Affected Spec Areas

| Spec Area | Master Doc | Nature of Change |
|-----------|-----------|------------------|
| Agent Execution & Output Rendering | `docs/master/product/features/agent-outputs.md`, `docs/master/product/features/agent-execution.md` | Content-type detection added to `auto` output rendering path; maximize button added to execution result view |
| Conversation Management | `docs/master/product/features/conversation-management.md` | Chat message rendering upgraded from plain-text-only to content-type-aware; maximize button added to chat messages |
| Agent Response Rendering UX | `docs/master/ux/prototype/index.html` (if exists and covers these views) | New maximize/focus-mode interaction pattern for rendered output areas |

## New Capabilities

### Content-Type Auto-Detection for Agent Responses

The platform now inspects agent response content at render time and detects whether it contains HTML markup. When HTML tags are present, the content is rendered directly as rich HTML — bypassing markdown processing in execution views and plain-text wrapping in chat windows. When no HTML tags are detected, the existing rendering behaviour (markdown conversion or plain-text display) is applied unchanged.

This detection applies to both rendering contexts:
- **Execution detail view**: For the `auto` output type, HTML content renders directly as rich HTML, bypassing markdown processing. Markdown and plain-text content continues through the existing conversion pipeline.
- **Chat window**: Agent messages that contain HTML are rendered as rich formatted content instead of raw pre-formatted text. Messages without HTML continue to display with the existing plain-text formatting that preserves whitespace and line breaks.

### Maximize / Focus Mode for Rendered Output

A maximize button is added to rendered agent output content areas in both chat messages and execution result views. Clicking the button expands the content into a full-view focus mode that shows only the rendered output without surrounding UI elements (chat headers, input controls, sidebar, execution metadata). The maximize view renders the exact same content — HTML, markdown, or typed output — that was visible inline, but at the full available viewport size. A close/restore action returns the user to the normal inline view.

This capability is distinct from the existing fullscreen dialog toggle in the conversation interface, which expands the entire dialog (including chat controls and session metadata). The maximize feature targets individual rendered content areas within those views.

## Modified Capabilities

### Chat Message Rendering (Before → After)

**Before**: All agent messages in chat windows render as plain text with whitespace preservation. No content-type detection is performed. If an agent returns HTML (which occurs for non-conversational agents with `output_type: 'auto'` when used conversationally), the raw HTML tags are displayed as unreadable text.

**After**: The chat message renderer inspects each agent message for HTML content. Messages containing HTML tags render as rich formatted content with sanitisation applied. Messages without HTML tags continue to render as plain pre-formatted text. A maximize button appears on each rendered agent message, allowing the operator to view the content in a focused full-view mode.

### Execution Detail Result Rendering (Before → After)

**Before**: For the `auto` output type, all content is unconditionally processed through markdown-to-HTML conversion. This treats all content as markdown — even if the agent already returned complete HTML — which can corrupt the intended formatting and produce garbled output.

**After**: The execution detail result renderer inspects the content before processing. If HTML tags are detected, the content renders directly as rich HTML (sanitised) without markdown conversion. If no HTML tags are detected, the content continues through standard markdown rendering. A maximize button appears on the rendered result area, allowing the operator to view the output in a focused full-view mode.

### Output Type Behaviour Matrix

| Output Type | Content | Before Rendering | After Rendering |
|-------------|---------|------------------|-----------------|
| `auto` | Plain text / Markdown | Standard markdown rendering | **Unchanged**: Standard markdown rendering |
| `auto` | HTML | Standard markdown rendering (corrupts formatting) | **Changed**: Rendered directly as HTML, bypassing markdown processing |
| `markdown` | Markdown | Standard markdown rendering | **Unchanged** |
| `typed` | Schema-validated JSON | Rendered as structured field-by-field view | **Unchanged** |
| Conversational (chat) | Plain text | Rendered as plain pre-formatted text | **Unchanged** |
| Conversational (chat) | HTML | Rendered as raw HTML text (broken) | **Changed**: Rendered as rich formatted HTML |

## Removed Capabilities

None. All existing rendering paths are preserved for content types that were already handled correctly. The change is purely additive — it adds detection logic where none existed and adds a maximize button that was not previously available.

## Spec Update Instructions

Update the following master documentation files after this change is implemented and verified:

### `docs/master/product/features/agent-outputs.md`
- In the "Execution Log Result Rendering" section, add a note that the `auto` output type now performs content-type detection: HTML content renders directly, non-HTML content goes through markdown conversion.
- Document the maximize button on execution result views as a new operator affordance for reviewing large outputs.

### `docs/master/product/features/conversation-management.md`
- In the "What It Does" section, update the description of agent message rendering to note that HTML content in agent messages now renders as rich formatted text instead of raw markup.
- Document the maximize button on chat messages as an operator affordance for focused output review.

### `docs/master/product/features/agent-execution.md`
- Under "Execution Log Result Rendering" or similar section, add a note about content-type-aware rendering for the `auto` output type.
- Mention the maximize button as part of the operator tools for reviewing execution results.

### `docs/master/ux/prototype/index.html` (if it covers execution detail or chat views)
- Add the maximize button pattern to any prototype mockup that shows rendered agent output content areas.
- Ensure the prototype reflects that HTML agent responses render as rich content, not raw text.
