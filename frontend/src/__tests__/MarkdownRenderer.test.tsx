import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { MarkdownRenderer } from '../components/common/MarkdownRenderer'

/** Shared markdown renderer — GFM support (tables) via remark-gfm. */
describe('MarkdownRenderer', () => {
  it('renders basic markdown', () => {
    const { container } = render(<MarkdownRenderer content={'# Title\n\nHello **world**'} />)
    expect(container.querySelector('h1')?.textContent).toBe('Title')
    expect(container.querySelector('strong')?.textContent).toBe('world')
  })

  it('renders GFM tables via remark-gfm', () => {
    const md = [
      '| Name | Value |',
      '| ---- | ----- |',
      '| foo  | 1     |',
      '| bar  | 2     |',
    ].join('\n')
    const { container } = render(<MarkdownRenderer content={md} />)
    const table = container.querySelector('table')
    expect(table).not.toBeNull()
    expect(container.querySelectorAll('th')).toHaveLength(2)
    expect(container.querySelectorAll('td')).toHaveLength(4)
    expect(container.querySelector('td')?.textContent).toBe('foo')
  })

  it('renders empty content without crashing', () => {
    const { container } = render(<MarkdownRenderer content="" />)
    expect(container).toBeInTheDocument()
  })
})
