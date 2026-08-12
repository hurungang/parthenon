import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TypedOutputRenderer } from '../components/executions/TypedOutputRenderer'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, options?: Record<string, unknown>) => {
      const defaults: Record<string, string> = {
        'typedField.null': 'null',
        'typedField.empty': 'empty',
        'typedField.missing': 'Missing required value',
        'typedField.true': 'On',
        'typedField.false': 'Off',
      }
      if (options?.defaultValue && typeof options.defaultValue === 'string') {
        return options.defaultValue
      }
      return defaults[k] ?? k
    },
  }),
}))

describe('TypedOutputRenderer', () => {
  it('renders all fields in order with labels', () => {
    const fields = [
      { name: 'severity', type: 'string' as const, required: true },
      { name: 'score', type: 'number' as const, required: false },
    ]
    const values = { severity: 'high', score: 95 }

    render(<TypedOutputRenderer fields={fields} values={values} />)

    expect(screen.getByText('severity')).toBeDefined()
    expect(screen.getByText('score')).toBeDefined()
    expect(screen.getByText('high')).toBeDefined()
    expect(screen.getByText('95')).toBeDefined()
  })

  it('shows null placeholder for missing values', () => {
    const fields = [
      { name: 'description', type: 'string' as const, required: false },
    ]
    const values: Record<string, unknown> = {}

    render(<TypedOutputRenderer fields={fields} values={values} />)

    expect(screen.getByText('null')).toBeDefined()
  })

  it('shows missing required error for required fields with no value', () => {
    const fields = [
      { name: 'title', type: 'string' as const, required: true },
    ]
    const values: Record<string, unknown> = {}

    render(<TypedOutputRenderer fields={fields} values={values} />)

    expect(screen.getByText('Missing required value')).toBeDefined()
  })

  it('renders boolean field values', () => {
    const fields = [
      { name: 'is_active', type: 'boolean' as const, required: false },
    ]
    const values = { is_active: true }

    const { container } = render(<TypedOutputRenderer fields={fields} values={values} />)

    // Should render a disabled MUI Switch
    const switches = container.querySelectorAll('.MuiSwitch-root')
    expect(switches.length).toBe(1)
  })

  it('renders enum field as Chip', () => {
    const fields = [
      { name: 'status', type: 'enum' as const, required: false, enum_values: ['open', 'closed'] },
    ]
    const values = { status: 'open' }

    render(<TypedOutputRenderer fields={fields} values={values} />)

    expect(screen.getByText('open')).toBeDefined()
  })

  it('renders date field formatted', () => {
    const fields = [
      { name: 'created', type: 'date' as const, required: false },
    ]
    const values = { created: '2026-06-15T10:00:00Z' }

    render(<TypedOutputRenderer fields={fields} values={values} />)

    // Should render a formatted date
    expect(screen.getByText(/Jun/)).toBeDefined()
  })

  it('renders number field with formatting', () => {
    const fields = [
      { name: 'count', type: 'number' as const, required: false },
    ]
    const values = { count: 1000000 }

    render(<TypedOutputRenderer fields={fields} values={values} />)

    // Should render with locale formatting
    expect(screen.getByText('1,000,000')).toBeDefined()
  })

  it('renders string field as plain text', () => {
    const fields = [
      { name: 'name', type: 'string' as const, required: false },
    ]
    const values = { name: 'John Doe' }

    render(<TypedOutputRenderer fields={fields} values={values} />)

    expect(screen.getByText('John Doe')).toBeDefined()
  })

  it('renders long string field with monospace styling', () => {
    const longText = 'x'.repeat(150)
    const fields = [
      { name: 'content', type: 'string' as const, required: false },
    ]
    const values = { content: longText }

    render(<TypedOutputRenderer fields={fields} values={values} />)

    // The long text should be in the document
    expect(screen.getByText(longText)).toBeDefined()
  })

  it('uses default value when field value is missing', () => {
    const fields = [
      { name: 'priority', type: 'string' as const, required: false, default: 'low' },
    ]
    const values: Record<string, unknown> = {}

    render(<TypedOutputRenderer fields={fields} values={values} />)

    expect(screen.getByText('low')).toBeDefined()
  })

  it('renders field type label', () => {
    const fields = [
      { name: 'email', type: 'string' as const },
    ]
    const values = { email: 'test@example.com' }

    render(<TypedOutputRenderer fields={fields} values={values} />)

    expect(screen.getByText('string')).toBeDefined()
  })

  it('shows required asterisk for required fields', () => {
    const fields = [
      { name: 'name', type: 'string' as const, required: true },
    ]
    const values = { name: 'test' }

    render(<TypedOutputRenderer fields={fields} values={values} />)

    // The asterisk is rendered as text content
    expect(screen.getByText('*')).toBeDefined()
  })

  it('renders empty state when fields array is empty', () => {
    const fields: Array<{ name: string; type: 'string'; required?: boolean }> = []
    const values = {}

    render(<TypedOutputRenderer fields={fields} values={values} />)

    expect(screen.getByText('No fields defined.')).toBeDefined()
  })
})
