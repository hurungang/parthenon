import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockUseAgentTypes: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: (...args: unknown[]) => shared.mockGet(...args),
  },
}))

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => shared.mockUseAgentTypes(),
}))

vi.mock('../components/agents/AgentExecutionDetailsDialog', () => ({
  AgentExecutionDetailsDialog: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="execution-details-dialog">details:{sessionId}</div>
  ),
}))

function renderPage(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('AgentInstanceDashboardPage runtime-control scenarios', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    shared.mockUseAgentTypes.mockReturnValue({
      data: [
        { id: 'at-conv', name: 'Conversation Agent', input_type: 'conversation' },
        { id: 'at-task', name: 'Task Agent', input_type: 'typed' },
      ],
    })
  })

  it('shows loading progress before sessions request resolves', async () => {
    let resolveRequest: ((value: { data: unknown[] }) => void) | undefined
    shared.mockGet.mockImplementationOnce(
      () =>
        new Promise<{ data: unknown[] }>((resolve) => {
          resolveRequest = resolve
        }),
    )

    const { AgentInstanceDashboardPage } = await import('../pages/agents/AgentInstanceDashboardPage')
    renderPage(<AgentInstanceDashboardPage />)

    expect(screen.getByRole('progressbar')).toBeDefined()

    if (resolveRequest) {
      resolveRequest({ data: [] })
    }
    await waitFor(() => {
      expect(screen.getByText('agents.sessions.dashboardEmpty')).toBeDefined()
    })
  })

  it('shows permission error alert when sessions query fails', async () => {
    shared.mockGet.mockRejectedValueOnce(new Error('403 forbidden'))

    const { AgentInstanceDashboardPage } = await import('../pages/agents/AgentInstanceDashboardPage')
    renderPage(<AgentInstanceDashboardPage />)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeDefined()
    })
  })

  it('renders conversation title column and opens execution details dialog', async () => {
    shared.mockGet.mockImplementation((url: string) => {
      if (url.startsWith('/agents/sessions')) {
        return Promise.resolve({
          data: [
            {
              id: 'sess-conv-1',
              agent_type_id: 'at-conv',
              status: 'running',
              created_at: '2026-06-01T00:00:00Z',
              started_at: null,
              completed_at: null,
            },
          ],
        })
      }

      if (url.startsWith('/conversations?agent_type_id=at-conv')) {
        return Promise.resolve({
          data: [
            {
              id: 'conv-1',
              title: 'Live Delegation Thread',
              agent_job_id: 'sess-conv-1',
            },
          ],
        })
      }

      return Promise.resolve({ data: [] })
    })

    const { AgentInstanceDashboardPage } = await import('../pages/agents/AgentInstanceDashboardPage')
    renderPage(<AgentInstanceDashboardPage agentTypeId="at-conv" />)

    await waitFor(() => {
      expect(screen.getByText('conversations.sessions.dashboardColumn')).toBeDefined()
    })
    expect(screen.getByText('Live Delegation Thread')).toBeDefined()

    fireEvent.click(screen.getByRole('button', { name: 'agents.sessions.view' }))
    await waitFor(() => {
      expect(screen.getByTestId('execution-details-dialog')).toBeDefined()
    })
    expect(screen.getByText('details:sess-conv-1')).toBeDefined()
  })
})
