import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { SessionExecutionLogsDialog } from '../pages/agents/SessionExecutionLogsDialog'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockLogViewer: vi.fn(),
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

vi.mock('../components/executions/LogViewer', () => ({
  LogViewer: (props: unknown) => {
    shared.mockLogViewer(props)
    return <div data-testid="log-viewer" />
  },
}))

describe('SessionExecutionLogsDialog', () => {
  beforeEach(() => {
    shared.mockGet.mockReset()
    shared.mockLogViewer.mockReset()
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

  it('merges streamed entries with fetched logs and renders LogViewer', async () => {
    const { rerender } = render(<SessionExecutionLogsDialog open sessionId="sess-1" onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByTestId('log-viewer')).toBeDefined()
    })

    shared.streamedEntries = [
      {
        id: 'stream-1',
        timestamp: '2026-05-29T10:01:00Z',
        event_type: 'tool_call',
        log_level: 'INFO',
        message: 'streamed tool call',
        data: {},
      },
    ]
    rerender(<SessionExecutionLogsDialog open sessionId="sess-1" onClose={vi.fn()} />)

    await waitFor(() => {
      const lastCall = shared.mockLogViewer.mock.calls[shared.mockLogViewer.mock.calls.length - 1]
      const props = lastCall?.[0] as { entries: Array<{ id: string }> }
      expect(props.entries.map((e) => e.id).sort()).toEqual(['base-1', 'stream-1'])
    })
  })
})
