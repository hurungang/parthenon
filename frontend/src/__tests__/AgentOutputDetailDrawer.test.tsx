import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Mock TypedOutputRenderer to avoid import complexity
vi.mock('../components/executions/TypedOutputRenderer', () => ({
  TypedOutputRenderer: ({ fields }: { fields: unknown[] }) => (
    <div data-testid="typed-output-renderer">TypedOutputRenderer ({fields.length} fields)</div>
  ),
}))

import { AgentOutputDetailDrawer } from '../pages/agent-outputs/AgentOutputDetailDrawer'
import type { AgentOutputResponse, AgentDataType } from '../types'

const DATA_TYPE: AgentDataType = {
  id: 'dt-1',
  name: 'Incident Report',
  slug: 'incident-report',
  description: null,
  fields: [
    { name: 'title', type: 'string', required: true },
    { name: 'severity', type: 'enum', enum_values: ['low', 'medium', 'high'], required: true },
  ],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

// Mock useDataType to return the test schema for dt-1
vi.mock('../hooks/useDataTypes', () => ({
  useDataType: (id: string) => {
    if (id === 'dt-1') {
      return { data: DATA_TYPE, isLoading: false, isError: false }
    }
    return { data: null, isLoading: false, isError: false }
  },
  useDataTypes: () => ({ data: null, isLoading: false }),
  useDataTypesWithUsage: () => ({ data: [], isLoading: false }),
  useCreateDataType: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateDataType: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDataType: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

const VALID_OUTPUT: AgentOutputResponse = {
  id: 'out-1',
  data_type_id: 'dt-1',
  data_type_name: 'Incident Report',
  agent_type_id: 'at-1',
  agent_type_name: 'Incident Analyzer',
  execution_session_id: 'session-1',
  field_values: { title: 'Server down', severity: 'high' },
  validation_status: 'valid',
  raw_output: null,
  created_at: '2026-01-15T10:00:00Z',
}

const ERROR_OUTPUT: AgentOutputResponse = {
  id: 'out-2',
  data_type_id: 'dt-1',
  data_type_name: 'Incident Report',
  agent_type_id: 'at-1',
  agent_type_name: 'Incident Analyzer',
  execution_session_id: 'session-2',
  field_values: null,
  validation_status: 'validation_error',
  raw_output: 'Server issue detected',
  created_at: '2026-01-15T11:00:00Z',
}

describe('AgentOutputDetailDrawer', () => {
  it('renders nothing when output is null', () => {
    const { container } = render(
      <AgentOutputDetailDrawer
        open={true}
        output={null}
        onClose={vi.fn()}
      />,
    )
    // Should not crash, render empty
    expect(container.textContent).toBe('')
  })

  it('renders output detail when open with valid output', () => {
    render(
      <AgentOutputDetailDrawer
        open={true}
        output={VALID_OUTPUT}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText('admin.agentOutputs.detailTitle')).toBeDefined()
    expect(screen.getByText('Incident Analyzer')).toBeDefined()
    expect(screen.getByText('Incident Report')).toBeDefined()
    expect(screen.getByText('admin.agentOutputs.statusValid')).toBeDefined()
    expect(screen.getByTestId('typed-output-renderer')).toBeDefined()
  })

  it('renders validation error status for error outputs', () => {
    render(
      <AgentOutputDetailDrawer
        open={true}
        output={ERROR_OUTPUT}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText('admin.agentOutputs.statusError')).toBeDefined()
    expect(screen.getByText('executionLog.result.validationErrorTitle')).toBeDefined()
  })

  it('shows raw output fallback for validation errors', () => {
    render(
      <AgentOutputDetailDrawer
        open={true}
        output={ERROR_OUTPUT}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText('executionLog.result.rawFallback')).toBeDefined()
    expect(screen.getByText('Server issue detected')).toBeDefined()
  })

  it('shows close button', () => {
    render(
      <AgentOutputDetailDrawer
        open={true}
        output={VALID_OUTPUT}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByTestId('CloseIcon')).toBeDefined()
  })
})
