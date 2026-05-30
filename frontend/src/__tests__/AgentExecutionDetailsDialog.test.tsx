import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { AgentExecutionDetailsDialog } from '../components/agents/AgentExecutionDetailsDialog'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  streamedEntries: [] as Array<{
    id: string
    timestamp: string
    event_type: string
    log_level: string
    message: string
    data: Record<string, unknown>
  }>,
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string) => k,
  }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: shared.mockGet,
  },
}))

vi.mock('../components/executions/LogViewer', () => ({
  LogViewer: () => <div data-testid="log-viewer" />,
}))

vi.mock('../pages/agents/AgentJobPage', () => ({
  AgentJobPage: () => <div data-testid="agent-job-page" />,
}))

vi.mock('../hooks/useExecutionLogs', () => ({
  useExecutionLogs: () => ({
    logs: [
      {
        id: 'exec-1',
        session_id: 'sess-1',
        system_instruction: 'system',
        user_prompt: 'prompt',
        logged_at: '2026-05-29T10:00:00Z',
      },
    ],
    loading: false,
  }),
}))

vi.mock('../hooks/useSessionExecutionLogStream', () => ({
  useSessionExecutionLogStream: () => ({
    entries: shared.streamedEntries,
    connectionState: 'connected',
    isFallback: false,
  }),
}))

describe('AgentExecutionDetailsDialog', () => {
  beforeEach(() => {
    shared.mockGet.mockReset()
    shared.streamedEntries = []
    shared.mockGet
      .mockResolvedValueOnce({
        data: [
          {
            id: 'base-1',
            timestamp: '2026-05-29T10:00:00Z',
            event_type: 'session_started',
            log_level: 'INFO',
            message: 'session started',
            data: {},
          },
        ],
      })
      .mockResolvedValueOnce({ data: { status: 'running' } })
  })

  it('focuses execution logs tab by default when dialog opens', async () => {
    render(
      <AgentExecutionDetailsDialog open sessionId="sess-1" onClose={vi.fn()} />,
    )

    const executionTab = screen.getByRole('tab', { name: 'agents.executionLogs.title' })
    const detailsTab = screen.getByRole('tab', { name: 'agents.sessions.detailsTitle' })

    expect(executionTab.getAttribute('aria-selected')).toBe('true')
    expect(detailsTab.getAttribute('aria-selected')).toBe('false')

    await waitFor(() => {
      expect(screen.getByTestId('log-viewer')).toBeDefined()
    })
    expect(screen.queryByTestId('agent-job-page')).toBeNull()
  })

  it('auto-scrolls to latest execution log entry when stream appends', async () => {
    if (!Object.prototype.hasOwnProperty.call(Element.prototype, 'scrollIntoView')) {
      Object.defineProperty(Element.prototype, 'scrollIntoView', {
        value: () => undefined,
        writable: true,
        configurable: true,
      })
    }

    const scrollIntoViewSpy = vi
      .spyOn(Element.prototype, 'scrollIntoView')
      .mockImplementation(() => undefined)

    const { rerender } = render(
      <AgentExecutionDetailsDialog open sessionId="sess-1" onClose={vi.fn()} />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('log-viewer')).toBeDefined()
    })

    shared.streamedEntries = [
      {
        id: 'stream-1',
        timestamp: '2026-05-29T10:01:00Z',
        event_type: 'tool_call',
        log_level: 'INFO',
        message: 'stream update',
        data: {},
      },
    ]

    rerender(<AgentExecutionDetailsDialog open sessionId="sess-1" onClose={vi.fn()} />)

    await waitFor(() => {
      expect(scrollIntoViewSpy).toHaveBeenCalled()
    })

    scrollIntoViewSpy.mockRestore()
  })
})
