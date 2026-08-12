import { Box, Typography } from '@mui/material'
import { containsHtmlTags, sanitizeHtml } from '../utils/contentDetection'
import { simpleMarkdownToHtml } from '../utils/markdown'

/** Shared MUI styling for rendered HTML content (markdown and HTML paths). */
const resultMarkdownSx = {
  '& h2': { fontSize: 20, fontWeight: 700, color: 'text.primary', mb: 1.5, pb: 1, borderBottom: 2, borderColor: 'divider' },
  '& h3': { fontSize: 16, fontWeight: 600, color: 'text.primary', mt: 2.5, mb: 1 },
  '& h4': { fontSize: 14, fontWeight: 600, color: 'text.primary', mt: 2, mb: 1 },
  '& p': { fontSize: 14, lineHeight: 1.65, mb: 1.25, color: 'text.primary' },
  '& strong': { fontWeight: 700 },
  '& ul, & ol': { pl: 3, mb: 1.5 },
  '& li': { fontSize: 14, lineHeight: 1.65, mb: 0.5 },
  '& code': { bgcolor: '#F1F5F9', px: 0.75, borderRadius: 0.5, fontSize: 13, fontFamily: 'monospace', color: '#C2410C' },
  '& pre': { bgcolor: '#1E293B', color: '#E2E8F0', p: 2, borderRadius: 1, overflowX: 'auto', fontSize: 13, lineHeight: 1.5, mb: 1.5, '& code': { bgcolor: 'transparent', color: 'inherit', p: 0, fontSize: 13 } },
  '& em': { fontStyle: 'italic', color: 'text.secondary' },
  '& blockquote': { borderLeft: 4, borderColor: 'primary.main', pl: 2, py: 1, my: 1.5, bgcolor: '#EFF6FF', borderRadius: '0 4px 4px 0', fontStyle: 'italic', color: 'text.secondary' },
  '& hr': { border: 'none', borderTop: 1, borderColor: 'divider', my: 2.5 },
}

interface ContentRendererProps {
  /** The raw agent response content to render. */
  content: string | null | undefined
  /**
   * Rendering mode:
   * - `auto`: HTML renders as sanitized HTML; non-HTML goes through markdown conversion.
   * - `chat`: HTML renders as sanitized HTML; non-HTML renders as plain pre-formatted text.
   * @default 'auto'
   */
  mode?: 'auto' | 'chat'
}

/**
 * ContentRenderer inspects a content string and renders it through the
 * correct pipeline based on detected format and rendering context.
 *
 * - HTML content → sanitized with DOMPurify → rendered via `dangerouslySetInnerHTML`
 * - Non-HTML + `auto` mode → markdown conversion → rendered via `dangerouslySetInnerHTML`
 * - Non-HTML + `chat` mode → plain pre-formatted text with whitespace preservation
 * - Empty / null / undefined → nothing rendered
 */
export function ContentRenderer({ content, mode = 'auto' }: ContentRendererProps) {
  if (!content) return null

  const isHtml = containsHtmlTags(content)

  if (isHtml) {
    const sanitized = sanitizeHtml(content)
    return (
      <Box
        className="result-markdown"
        sx={resultMarkdownSx}
        dangerouslySetInnerHTML={{ __html: sanitized }}
      />
    )
  }

  if (mode === 'chat') {
    // Non-HTML content in chat mode: plain pre-formatted text
    return (
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
        {content}
      </Typography>
    )
  }

  // Non-HTML content in auto mode: markdown conversion
  const markdownHtml = simpleMarkdownToHtml(content)
  return (
    <Box
      className="result-markdown"
      sx={resultMarkdownSx}
      dangerouslySetInnerHTML={{ __html: markdownHtml }}
    />
  )
}
