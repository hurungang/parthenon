import DOMPurify from 'dompurify'

/**
 * Tests whether a string contains HTML markup by checking for opening or
 * closing HTML tags. The regex requires an ASCII letter immediately after
 * `<` (for opening tags like `<p>`, `<div>`) or `</` (for closing tags
 * like `</div>`). Self-closing tags like `<br/>` also match.
 *
 * This avoids false positives on comparison operators (`x < 5`) or
 * template expressions.
 */
export function containsHtmlTags(content: string): boolean {
  return /<[a-zA-Z][^>]*>|<\/[a-zA-Z][^>]*>/m.test(content)
}

/**
 * Sanitizes an HTML string using DOMPurify, stripping disallowed tags and
 * attributes. Returns the sanitized HTML string safe for rendering via
 * `dangerouslySetInnerHTML`.
 */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html)
}
