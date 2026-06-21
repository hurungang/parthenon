import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { OutputTypeResultTab } from '../components/executions/OutputTypeResultTab'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, options?: Record<string, unknown>) => {
      const defaults: Record<string, string> = {
        'agents.agentType.outputMarkdown': 'Markdown',
        'agents.agentType.outputTyped': 'Typed',
        'agents.agentType.outputAuto': 'Auto',
        'executions.outputTypeResult.schemaLabel': 'Output Schema',
        'executions.outputTypeResult.showSchema': 'Show Schema',
        'executions.outputTypeResult.hideSchema': 'Hide Schema',
        'executions.outputTypeResult.noData': 'No output data available',
        'executions.resultTab.noData': 'No result data available.',
        'executions.resultTab.structuredOutput': 'Structured Output',
        'executions.resultTab.agentOutput': 'Agent Output',
        'executions.resultTab.showSchema': 'Show Output Schema',
        'executions.resultTab.hideSchema': 'Hide Output Schema',
        'executions.resultTab.validated': 'Validated ✓',
        'executionLog.result.validationError': 'Validation Error',
        'executionLog.result.validationErrorTitle': 'Output Validation Failed',
        'executionLog.result.validationErrorHint': 'The agent output did not match the expected schema.',
        'executionLog.result.rawFallback': 'Raw Output (Fallback)',
        'typedField.null': 'null',
        'typedField.empty': 'empty',
        'typedField.missing': 'Missing required value',
        'executions.resultTab.dataTypeBadge': '{{name}}',
      }
      if (options?.defaultValue && typeof options.defaultValue === 'string') {
        return options.defaultValue
      }
      return defaults[k] ?? k
    },
  }),
}))

// Mock useDataType hook
vi.mock('../hooks/useDataTypes', () => ({
  useDataType: () => ({
    data: null,
    isLoading: false,
    error: null,
  }),
}))

// Mock TypedOutputRenderer
vi.mock('../components/executions/TypedOutputRenderer', () => ({
  TypedOutputRenderer: ({ fields, values }: { fields: Array<{ name: string; type: string }>; values: Record<string, unknown> }) => (
    <div data-testid="typed-output-renderer">
      {fields.map((f) => (
        <div key={f.name} data-testid={`field-${f.name}`}>
          {f.name}: {String(values[f.name] ?? '')}
        </div>
      ))}
    </div>
  ),
}))

describe('OutputTypeResultTab', () => {
  // ── Existing backward-compatible tests ──

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

  // ── New typed output tests ──

  it('renders data type name badge when dataTypeName is provided', () => {
    render(
      <OutputTypeResultTab
        outputType="typed"
        outputData={{ field_values: { severity: 'high', title: 'Test' } }}
        dataTypeId="dt-1"
        dataTypeName="IncidentReport"
        dataTypeSchema={{
          id: 'dt-1',
          name: 'IncidentReport',
          slug: 'incident-report',
          description: null,
          fields: [
            { name: 'severity', type: 'string', required: true },
            { name: 'title', type: 'string', required: true },
          ],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
      />,
    )
    expect(screen.getByText('IncidentReport')).toBeDefined()
  })

  it('renders TypedOutputRenderer when dataTypeId and schema are provided', () => {
    render(
      <OutputTypeResultTab
        outputType="typed"
        outputData={{ field_values: { severity: 'high', title: 'Test Incident' } }}
        dataTypeId="dt-1"
        dataTypeName="IncidentReport"
        dataTypeSchema={{
          id: 'dt-1',
          name: 'IncidentReport',
          slug: 'incident-report',
          description: null,
          fields: [
            { name: 'severity', type: 'string', required: true },
            { name: 'title', type: 'string', required: true },
          ],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
      />,
    )
    expect(screen.getByTestId('typed-output-renderer')).toBeDefined()
    expect(screen.getByTestId('field-severity')).toBeDefined()
    expect(screen.getByTestId('field-title')).toBeDefined()
  })

  it('shows validation error alert when validationStatus is validation_error', () => {
    render(
      <OutputTypeResultTab
        outputType="typed"
        outputData={{
          field_values: null,
          validation_status: 'validation_error',
          raw_output: 'Some raw output text',
        }}
        dataTypeId="dt-1"
        validationStatus="validation_error"
        rawOutput="Some raw output text"
        dataTypeSchema={{
          id: 'dt-1',
          name: 'IncidentReport',
          slug: 'incident-report',
          description: null,
          fields: [
            { name: 'severity', type: 'string', required: true },
          ],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
      />,
    )
    // Validation error badge should be present
    expect(screen.getByText('Validation Error')).toBeDefined()
    // Validation error title
    expect(screen.getByText('Output Validation Failed')).toBeDefined()
    // Raw fallback
    expect(screen.getByText('Raw Output (Fallback)')).toBeDefined()
    expect(screen.getByText('Some raw output text')).toBeDefined()
  })

  it('shows validation error from outputData when no explicit validationStatus prop', () => {
    render(
      <OutputTypeResultTab
        outputType="typed"
        outputData={{
          validation_status: 'validation_error',
          raw_output: 'Fallback raw text',
        }}
        dataTypeId="dt-1"
        dataTypeSchema={{
          id: 'dt-1',
          name: 'IncidentReport',
          slug: 'incident-report',
          description: null,
          fields: [],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
      />,
    )
    expect(screen.getByText('Validation Error')).toBeDefined()
    expect(screen.getByText('Fallback raw text')).toBeDefined()
  })

  it('shows field-level validation errors in the alert', () => {
    render(
      <OutputTypeResultTab
        outputType="typed"
        outputData={{
          validation_status: 'validation_error',
          validation_errors: [
            { field: 'severity', message: 'Required field is missing' },
            { field: 'title', message: 'Must be a string' },
          ],
        }}
        dataTypeId="dt-1"
        validationStatus="validation_error"
        dataTypeSchema={{
          id: 'dt-1',
          name: 'IncidentReport',
          slug: 'incident-report',
          description: null,
          fields: [
            { name: 'severity', type: 'string', required: true },
            { name: 'title', type: 'string', required: true },
          ],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
      />,
    )
    // Field-level error messages should be visible
    expect(screen.getByText(/Required field is missing/)).toBeDefined()
    expect(screen.getByText(/Must be a string/)).toBeDefined()
  })

  it('falls back to JSON tree view when typed but no dataTypeId', () => {
    render(
      <OutputTypeResultTab
        outputType="typed"
        outputData={{ result: 'test-value', nested: { key: 'val' } }}
      />,
    )
    expect(screen.getByText('Typed')).toBeDefined()
    // Should still render without crashing
    expect(screen.getByText('Structured Output')).toBeDefined()
  })
})
