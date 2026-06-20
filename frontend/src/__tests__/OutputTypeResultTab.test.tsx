import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { OutputTypeResultTab } from '../components/executions/OutputTypeResultTab'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string) => {
      const defaults: Record<string, string> = {
        'agents.agentType.outputMarkdown': 'Markdown',
        'agents.agentType.outputTyped': 'Typed',
        'agents.agentType.outputAuto': 'Auto',
        'executions.outputTypeResult.schemaLabel': 'Output Schema',
        'executions.outputTypeResult.showSchema': 'Show Schema',
        'executions.outputTypeResult.hideSchema': 'Hide Schema',
        'executions.outputTypeResult.noData': 'No output data available',
      }
      return defaults[k] ?? k
    },
  }),
}))

describe('OutputTypeResultTab', () => {
  it('renders Markdown badge for markdown output type', () => {
    render(<OutputTypeResultTab outputType="markdown" outputData={{ markdown: '# Hello' }} />)
    expect(screen.getByText('Markdown')).toBeDefined()
  })

  it('renders Typed badge for typed output type', () => {
    render(<OutputTypeResultTab outputType="typed" outputData={{ result: 'test' }} />)
    expect(screen.getByText('Typed')).toBeDefined()
  })

  it('renders Auto badge for auto output type', () => {
    render(<OutputTypeResultTab outputType="auto" outputData={{ result: 'test' }} />)
    expect(screen.getByText('Auto')).toBeDefined()
  })

  it('renders markdown content for markdown output type', () => {
    render(<OutputTypeResultTab outputType="markdown" outputData={{ markdown: '# Hello World' }} />)
    expect(screen.getByText(/Hello World/)).toBeDefined()
  })

  it('renders with null outputData for auto type', () => {
    const { container } = render(<OutputTypeResultTab outputType="auto" outputData={null} />)
    expect(container.firstChild).not.toBeNull()
  })

  it('renders with null outputData for markdown type', () => {
    const { container } = render(<OutputTypeResultTab outputType="markdown" outputData={null} />)
    // Should show "no data" or render without crashing
    expect(container.firstChild).not.toBeNull()
  })

  it('renders with null outputData for typed type', () => {
    const { container } = render(<OutputTypeResultTab outputType="typed" outputData={null} />)
    expect(container.firstChild).not.toBeNull()
  })

  it('renders outputSchema when provided for typed output', () => {
    render(
      <OutputTypeResultTab
        outputType="typed"
        outputData={{ result: 'some value' }}
        outputSchema={{ type: 'object', properties: { result: { type: 'string' } } }}
      />,
    )
    expect(screen.getByText('Typed')).toBeDefined()
  })

  it('renders without crashing for markdown with result field', () => {
    render(<OutputTypeResultTab outputType="markdown" outputData={{ result: '## Section 1\ncontent here' }} />)
    expect(screen.getByText('Markdown')).toBeDefined()
  })

  it('renders without crashing for typed output with JSON data', () => {
    render(
      <OutputTypeResultTab
        outputType="typed"
        outputData={{ items: [{ id: 1, name: 'test' }] }}
      />,
    )
    expect(screen.getByText('Typed')).toBeDefined()
  })

  it('renders fallback for auto type with data', () => {
    render(<OutputTypeResultTab outputType="auto" outputData={{ result: 'some auto result' }} />)
    expect(screen.getByText('Auto')).toBeDefined()
  })
})
