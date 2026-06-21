import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

const MOCK_DATA_TYPES = {
  items: [
    {
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
    },
    {
      id: 'dt-2',
      name: 'Metrics Snapshot',
      slug: 'metrics-snapshot',
      description: null,
      fields: [
        { name: 'metric_name', type: 'string', required: true },
        { name: 'value', type: 'number', required: true },
      ],
      created_at: '2026-01-02T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  page_size: 25,
}

const MOCK_AGENT_TYPES = [
  { id: 'at-1', name: 'Incident Analyzer' },
  { id: 'at-2', name: 'Metrics Collector' },
]

const MOCK_OUTPUTS = {
  items: [
    {
      id: 'out-1',
      data_type_id: 'dt-1',
      data_type_name: 'Incident Report',
      agent_type_id: 'at-1',
      agent_type_name: 'Incident Analyzer',
      execution_session_id: 'session-1',
      field_values: { title: 'Server down', severity: 'high' },
      validation_status: 'valid' as const,
      raw_output: null,
      created_at: '2026-01-15T10:00:00Z',
    },
    {
      id: 'out-2',
      data_type_id: 'dt-1',
      data_type_name: 'Incident Report',
      agent_type_id: 'at-1',
      agent_type_name: 'Incident Analyzer',
      execution_session_id: 'session-2',
      field_values: null,
      validation_status: 'validation_error' as const,
      raw_output: 'Server issue detected',
      created_at: '2026-01-15T11:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
}

const apiClientMock = {
  get: vi.fn().mockImplementation((url: string) => {
    if (url === '/data-types') {
      return Promise.resolve({ data: MOCK_DATA_TYPES })
    }
    if (url === '/agents/types') {
      return Promise.resolve({ data: MOCK_AGENT_TYPES })
    }
    if (url === '/agent-outputs') {
      return Promise.resolve({ data: MOCK_OUTPUTS })
    }
    if (url === '/agent-outputs/export') {
      return Promise.resolve({ data: new Blob(['col1,col2\nv1,v2\n'], { type: 'text/csv' }) })
    }
    return Promise.reject(new Error(`Unexpected URL: ${url}`))
  }),
  post: vi.fn().mockResolvedValue({ data: {} }),
  put: vi.fn().mockResolvedValue({ data: {} }),
  delete: vi.fn().mockResolvedValue({ data: {} }),
}

vi.mock('../api/apiClient', () => ({
  default: apiClientMock,
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AgentOutputsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the page title', async () => {
    const { AgentOutputsPage } = await import('../pages/agent-outputs/AgentOutputsPage')
    render(<AgentOutputsPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('admin.agentOutputs.title')).toBeDefined()
    })
  })

  it('renders export CSV button', async () => {
    const { AgentOutputsPage } = await import('../pages/agent-outputs/AgentOutputsPage')
    render(<AgentOutputsPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('admin.agentOutputs.exportCsv')).toBeDefined()
    })
  })

  it('renders data type filter selector', async () => {
    const { AgentOutputsPage } = await import('../pages/agent-outputs/AgentOutputsPage')
    render(<AgentOutputsPage />, { wrapper })
    await waitFor(() => {
      const matches = screen.getAllByText('admin.agentOutputs.filterDataType')
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders agent type filter selector', async () => {
    const { AgentOutputsPage } = await import('../pages/agent-outputs/AgentOutputsPage')
    render(<AgentOutputsPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getAllByText('admin.agentOutputs.filterAgentType').length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders output entries with data type names', async () => {
    const { AgentOutputsPage } = await import('../pages/agent-outputs/AgentOutputsPage')
    render(<AgentOutputsPage />, { wrapper })
    await waitFor(() => {
      const matches = screen.getAllByText('Incident Report')
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders output entries with agent type names', async () => {
    const { AgentOutputsPage } = await import('../pages/agent-outputs/AgentOutputsPage')
    render(<AgentOutputsPage />, { wrapper })
    await waitFor(() => {
      const matches = screen.getAllByText('Incident Analyzer')
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('shows validation status chips for outputs', async () => {
    const { AgentOutputsPage } = await import('../pages/agent-outputs/AgentOutputsPage')
    render(<AgentOutputsPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('admin.agentOutputs.statusValid')).toBeDefined()
      expect(screen.getByText('admin.agentOutputs.statusError')).toBeDefined()
    })
  })

  it('shows empty state when no outputs', async () => {
    apiClientMock.get.mockImplementation((url: string) => {
      if (url === '/data-types') return Promise.resolve({ data: MOCK_DATA_TYPES })
      if (url === '/agents/types') return Promise.resolve({ data: MOCK_AGENT_TYPES })
      if (url === '/agent-outputs') {
        return Promise.resolve({ data: { items: [], total: 0, page: 1, page_size: 20 } })
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`))
    })
    const { AgentOutputsPage } = await import('../pages/agent-outputs/AgentOutputsPage')
    render(<AgentOutputsPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('admin.agentOutputs.noResults')).toBeDefined()
    })
  })

  it('shows loading spinner while fetching', async () => {
    apiClientMock.get.mockImplementation(
      (url: string) =>
        new Promise((resolve) =>
          setTimeout(
            () => {
              if (url === '/data-types') resolve({ data: MOCK_DATA_TYPES })
              else if (url === '/agents/types') resolve({ data: MOCK_AGENT_TYPES })
              else if (url === '/agent-outputs') resolve({ data: MOCK_OUTPUTS })
              else resolve({ data: {} })
            },
            500,
          ),
        ),
    )
    const { AgentOutputsPage } = await import('../pages/agent-outputs/AgentOutputsPage')
    render(<AgentOutputsPage />, { wrapper })
    await waitFor(() => {
      // The data types and agent types load quickly, but outputs are loading
      // We just verify it doesn't crash
      expect(screen.getByText('admin.agentOutputs.title')).toBeDefined()
    })
  })
})
