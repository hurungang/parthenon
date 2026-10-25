import { Box } from '@mui/material'
import type { Theme } from '@mui/material/styles'
import type { SxProps } from '@mui/system'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownRendererProps {
  /** Raw markdown source to render (auto-detected markdown from agent output). */
  content: string
  /** Additional MUI sx overrides merged over the base typography styles. */
  sx?: SxProps<Theme>
}

/**
 * Shared markdown renderer for agent session results / outputs.
 *
 * Wraps react-markdown with remark-gfm so GitHub-Flavored Markdown —
 * tables, strikethrough, task lists, autolinks — renders correctly.
 * Used wherever rendered agent output text is displayed.
 */
export function MarkdownRenderer({ content, sx }: MarkdownRendererProps) {
  return (
    <Box
      className="result-markdown"
      sx={{
        '& p': { fontSize: 14, lineHeight: 1.65, my: 1.25 },
        '& h1, & h2': { fontSize: 20, fontWeight: 700, my: 1.5, pb: 1, borderBottom: 2, borderColor: 'divider' },
        '& h3': { fontSize: 16, fontWeight: 600, mt: 2.5, mb: 1 },
        '& h4': { fontSize: 14, fontWeight: 600, mt: 2, mb: 1 },
        '& strong': { fontWeight: 700 },
        '& ul, & ol': { pl: 3, my: 1.5 },
        '& li': { fontSize: 14, lineHeight: 1.65, my: 0.5 },
        '& code': { bgcolor: '#F1F5F9', px: 0.75, borderRadius: 0.5, fontSize: 13, fontFamily: 'monospace', color: '#C2410C' },
        '& pre': { bgcolor: '#1E293B', color: '#E2E8F0', p: 2, borderRadius: 1, overflowX: 'auto', fontSize: 13, lineHeight: 1.5, my: 1.5, '& code': { bgcolor: 'transparent', color: 'inherit', p: 0 } },
        '& em': { fontStyle: 'italic' },
        '& blockquote': { borderLeft: 4, borderColor: 'primary.main', pl: 2, py: 1, my: 1.5, bgcolor: '#EFF6FF', borderRadius: '0 4px 4px 0', fontStyle: 'italic' },
        '& hr': { border: 'none', borderTop: 1, borderColor: 'divider', my: 2.5 },
        // GFM tables
        '& table': { borderCollapse: 'collapse', my: 1.5, fontSize: 13, width: '100%' },
        '& th, & td': { border: 1, borderColor: 'divider', px: 1.5, py: 0.75, textAlign: 'left' },
        '& th': { bgcolor: '#F1F5F9', fontWeight: 700 },
        ...((typeof sx === 'object' ? sx : {}) as object),
      }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </Box>
  )
}
