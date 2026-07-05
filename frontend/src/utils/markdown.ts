/**
 * Escapes HTML special characters in a string for safe embedding.
 */
export function escapeHtml(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/**
 * Simple markdown-to-HTML converter.
 * Handles headings (h2-h4), strikethrough, bold, italic, inline code,
 * code blocks, unordered/ordered lists, blockquotes, horizontal rules,
 * and paragraphs.
 */
export function simpleMarkdownToHtml(md: string): string {
  let html = escapeHtml(md)

  // Headings (h2-h4)
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>')
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>')

  // Horizontal rules
  html = html.replace(/^---$/gm, '<hr>')

  // Blockquotes
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>')

  // Bold and italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')

  // Unordered lists
  html = html.replace(/^\s*[-*] (.+)$/gm, '<li>$1</li>')
  html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`)

  // Ordered lists
  html = html.replace(/^\s*\d+\. (.+)$/gm, '<li>$1</li>')
  html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => {
    if (match.includes('<ul>')) return match
    return `<ol>${match}</ol>`
  })

  // Code blocks (fenced)
  html = html.replace(/<pre><code>([\s\S]*?)<\/code><\/pre>/g, (_, code) => {
    return `<pre><code>${code}</code></pre>`
  })

  // Fix consecutive blockquotes
  html = html.replace(/<\/blockquote>\n<blockquote>/g, '<br>')

  // Paragraphs: wrap remaining text lines in <p>
  const blockTags = ['h2', 'h3', 'h4', 'ul', 'ol', 'li', 'pre', 'blockquote', 'hr', 'code']
  const parts = html.split('\n\n')
  html = parts
    .map((part) => {
      const trimmed = part.trim()
      if (!trimmed) return ''
      const startsWithBlock = blockTags.some((tag) => {
        const regex = new RegExp(`^<${tag}[ >]`)
        return regex.test(trimmed)
      })
      if (startsWithBlock) return trimmed
      return `<p>${trimmed.replace(/\n/g, '<br>')}</p>`
    })
    .join('\n\n')

  return html
}
