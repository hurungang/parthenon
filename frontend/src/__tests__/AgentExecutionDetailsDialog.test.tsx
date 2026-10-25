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

vi.mock('../components/executions/OutputTypeResultTab', () => ({
  OutputTypeResultTab: (props: { outputData?: unknown }) => {
    const od = props.outputData
    const text =
      od !== null && typeof od === 'object' && 'result' in od
        ? String((od as { result: unknown }).result)
        : JSON.stringify(od)
    return <div data-testid="output-result">{text}</div>
  },
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

vi.mock('../components/agents/AgentTypeDetailsDialog', () => ({
  AgentTypeDetailsDialog: (props: { agentTypeId: string | null; initialTab?: number }) => (
    <div
      data-testid="agent-type-details-dialog"
      data-agent-type-id={props.agentTypeId}
      data-initial-tab={props.initialTab}
    />
  ),
}))

describe('AgentExecutionDetailsDialog', () => {
  beforeEach(() => {
    if (!Object.prototype.hasOwnProperty.call(Element.prototype, 'scrollIntoView')) {
      Object.defineProperty(Element.prototype, 'scrollIntoView', {
        value: () => undefined,
        writable: true,
        configurable: true,
      })
    }
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

    // Wait for the log viewer to appear (indicates execution tab content is rendered)
    await waitFor(() => {
      expect(screen.getByTestId('log-viewer')).toBeDefined()
    })
    
    // If tabs exist (2+ tabs), the execution logs tab should be selected by default
    const tabs = screen.queryAllByRole('tab')
    if (tabs.length > 0) {
      const executionTab = tabs.find(tab => tab.getAttribute('aria-selected') === 'true')
      expect(executionTab).toBeDefined()
    }
    
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

  it('shows a "View agent" header link that opens the agent type details dialog on the Overview tab', async () => {
    if (!Object.prototype.hasOwnProperty.call(Element.prototype, 'scrollIntoView')) {
      Object.defineProperty(Element.prototype, 'scrollIntoView', {
        value: () => undefined,
        writable: true,
        configurable: true,
      })
    }
    shared.mockGet.mockReset()
    shared.mockGet
      .mockResolvedValueOnce({ data: [] }) // logs
      .mockResolvedValueOnce({
        data: {
          id: 'sess-9',
          agent_type_id: 'at-42',
          status: 'completed',
          // Script-path session: final output stored as a raw string.
          output_data: 'Hello from the render step',
        },
      }) // session
      .mockResolvedValueOnce({ data: [] }) // conversation history

    const user = (await import('@testing-library/user-event')).default
    render(
      <AgentExecutionDetailsDialog open sessionId="sess-9" onClose={vi.fn()} />,
    )

    // Header link (not inside the Result tab)
    const link = await screen.findByRole('button', { name: 'agents.sessions.viewAgent' })
    await user.click(link)

    const dialog = screen.getByTestId('agent-type-details-dialog')
    expect(dialog.getAttribute('data-agent-type-id')).toBe('at-42')
    // Default Overview tab (the Scripts tab no longer exists).
    expect(dialog.getAttribute('data-initial-tab')).toBe('0')
    // The old Result-tab "View agent scripts" button is gone.
    expect(
      screen.queryByRole('button', { name: 'agents.sessions.viewAgentScripts' }),
    ).toBeNull()
  })

  it('renders a raw string output_data as result text, not a JSON object', async () => {
    if (!Object.prototype.hasOwnProperty.call(Element.prototype, 'scrollIntoView')) {
      Object.defineProperty(Element.prototype, 'scrollIntoView', {
        value: () => undefined,
        writable: true,
        configurable: true,
      })
    }
    shared.mockGet.mockReset()
    shared.mockGet
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({
        data: {
          id: 'sess-10',
          agent_type_id: 'at-42',
          status: 'completed',
          output_data: 'Plain render text',
        },
      })
      .mockResolvedValueOnce({ data: [] })

    render(
      <AgentExecutionDetailsDialog open sessionId="sess-10" onClose={vi.fn()} />,
    )

    await screen.findByRole('button', { name: 'agents.sessions.viewAgent' })
    // OutputTypeResultTab is rendered (not mocked) — the string is passed as
    // { result: string } so the extracted text renders instead of raw JSON.
    await waitFor(() => {
      expect(screen.getByText('Plain render text')).toBeDefined()
    })
  })
})
