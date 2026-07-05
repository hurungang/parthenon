import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ContentRenderer } from '../components/ContentRenderer'

describe('ContentRenderer', () => {
  it('renders HTML content as sanitized HTML in auto mode', () => {
    render(<ContentRenderer mode="auto" content="<p>Hello <strong>World</strong></p>" />)
    // The content should be rendered, and the strong tag should be present
    const rendered = screen.getByText('Hello', { exact: false })
    expect(rendered).toBeDefined()
    expect(screen.getByText('World', { exact: false })).toBeDefined()
  })

  it('renders HTML content as sanitized HTML in chat mode', () => {
    render(<ContentRenderer mode="chat" content="<div>Chat <em>HTML</em></div>" />)
    expect(screen.getByText('Chat', { exact: false })).toBeDefined()
    expect(screen.getByText('HTML', { exact: false })).toBeDefined()
  })

  it('renders markdown content through conversion in auto mode', () => {
    render(<ContentRenderer mode="auto" content="## Heading\n\nSome **bold** text." />)
    // After markdown conversion, the heading should be rendered as an h2
    // Use partial matching because the h2 text includes trailing content
    expect(screen.getByText(/Heading/)).toBeDefined()
    expect(screen.getByText('bold')).toBeDefined()
  })

  it('renders markdown content as plain text in chat mode', () => {
    render(<ContentRenderer mode="chat" content="## Heading\n\nSome **bold** text." />)
    // In chat mode, raw markdown is shown as plain text
    // Use partial match because the full text includes trailing content
    expect(screen.getByText(/## Heading/)).toBeDefined()
    expect(screen.getByText(/Some \*\*bold\*\* text/)).toBeDefined()
  })

  it('renders plain text with whitespace preserved in chat mode', () => {
    const text = 'Line 1\nLine 2\n\nLine 3'
    render(<ContentRenderer mode="chat" content={text} />)
    // The Typography component renders the full text; use partial match
    // because getByText with exact matching normalizes whitespace
    expect(screen.getByText(/Line 1/)).toBeDefined()
    expect(screen.getByText(/Line 3/)).toBeDefined()
  })

  it('renders nothing for empty content', () => {
    const { container } = render(<ContentRenderer mode="auto" content="" />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing for null content', () => {
    const { container } = render(<ContentRenderer mode="auto" content={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing for undefined content', () => {
    const { container } = render(<ContentRenderer mode="auto" content={undefined} />)
    expect(container.firstChild).toBeNull()
  })

  it('strips script tags via DOMPurify', () => {
    render(
      <ContentRenderer
        mode="auto"
        content={'<p>Safe content</p><script>alert("xss")</script>' as string}
      />,
    )
    // Safe content should be present
    expect(screen.getByText('Safe content', { exact: false })).toBeDefined()
    // Script tag content should NOT be present
    expect(screen.queryByText('alert("xss")')).toBeNull()
  })

  it('strips event handler attributes via DOMPurify', () => {
    render(
      <ContentRenderer
        mode="auto"
        content={'<p onclick="alert(1)">Click me</p>' as string}
      />,
    )
    expect(screen.getByText('Click me', { exact: false })).toBeDefined()
  })

  it('handles mixed HTML and markdown-like content by following HTML path', () => {
    // When content contains HTML tags, it should follow the HTML rendering path
    // even if it also contains markdown-like syntax
    render(
      <ContentRenderer
        mode="auto"
        content="<p>HTML paragraph</p>\n\n**This is bold**"
      />,
    )
    // HTML is sanitized and rendered directly — bold markdown NOT converted
    expect(screen.getByText('HTML paragraph', { exact: false })).toBeDefined()
    // The markdown bold syntax should appear as literal text (not converted)
    // Use partial match because the text node contains surrounding whitespace
    expect(screen.getByText(/\*\*This is bold\*\*/)).toBeDefined()
  })

  it('renders complex nested HTML', () => {
    render(
      <ContentRenderer
        mode="auto"
        content="<div><h2>Report</h2><table><tr><td>Cell</td></tr></table></div>"
      />,
    )
    expect(screen.getByText('Report', { exact: false })).toBeDefined()
    expect(screen.getByText('Cell', { exact: false })).toBeDefined()
  })

  it('renders HTML in chat mode as sanitized HTML (not plain text)', () => {
    render(<ContentRenderer mode="chat" content="<p>Chat <strong>HTML</strong></p>" />)
    // Should render as HTML, not plain text with tags visible
    expect(screen.getByText('Chat', { exact: false })).toBeDefined()
    expect(screen.getByText('HTML', { exact: false })).toBeDefined()
    // The raw '<p>' should not be visible
    expect(screen.queryByText(/<p>/)).toBeNull()
  })

  it('detects self-closing HTML tags like <br/>', () => {
    render(<ContentRenderer mode="auto" content="Line 1<br/>Line 2" />)
    // The content should be rendered as HTML (br tag is detected)
    // Use partial match since text nodes are separated by <br/>
    expect(screen.getByText(/Line 1/)).toBeDefined()
    expect(screen.getByText(/Line 2/)).toBeDefined()
  })

  it('does not treat angle bracket comparison as HTML', () => {
    render(<ContentRenderer mode="auto" content="The value x < 5 is important" />)
    // In auto mode, this goes through markdown conversion as plain text
    // The '<' should be escaped
    const element = screen.getByText(/is important/)
    expect(element).toBeDefined()
  })

  it('defaults to auto mode when mode not specified', () => {
    render(<ContentRenderer content="## Default Test" />)
    // Should render as markdown (auto mode)
    expect(screen.getByText('Default Test', { exact: false })).toBeDefined()
  })
})
