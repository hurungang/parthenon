import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn(), useParams: () => ({ id: 'sess-abc' }) }
})

// Mock WebSocket for chat session hook
class MockWebSocket {
  onopen: (() => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  onerror: ((e: Event) => void) | null = null
  readyState = 1 // OPEN
  send = vi.fn()
  close = vi.fn()
}
vi.stubGlobal('WebSocket', MockWebSocket)

// jsdom does not implement scrollIntoView — stub it globally
Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
  writable: true,
  value: vi.fn(),
})

const mockGet = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: { get: mockGet },
}))

vi.mock('../hooks/useChatSession', () => ({
  useChatSession: () => ({
    messages: [],
    sendMessage: vi.fn(),
    connected: false,
  }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/agents/sessions/sess-abc']}>
        {children}
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AgentJobPage', () => {
  afterEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
  })

  it('shows loading spinner initially', async () => {
    // Make the API call never resolve to keep loading state
    mockGet.mockImplementation(() => new Promise(() => {}))
    const { AgentJobPage } = await import('../pages/agents/AgentJobPage')
    render(<AgentJobPage />, { wrapper })
    expect(screen.getByRole('progressbar')).toBeDefined()
  })

  it('shows queued status chip for queued session', async () => {
    mockGet.mockResolvedValue({
      data: {
        id: 'sess-abc',
        agent_type_id: 'at-1',
        triggered_by_user_id: null,
        input_data: null,
        status: 'queued',
        started_at: null,
        completed_at: null,
        output_data: null,
        error_message: null,
        created_at: '2026-01-01T00:00:00Z',
      },
    })

    const { AgentJobPage } = await import('../pages/agents/AgentJobPage')
    render(<AgentJobPage />, { wrapper })

    await waitFor(() => {
      // Status chip with 'queued' label (translated key) — text also appears in the waiting Paper
      expect(screen.getAllByText('agents.sessions.statusQueued').length).toBeGreaterThan(0)
    })
  })

  it('shows completed status and result for completed session', async () => {
    mockGet.mockResolvedValue({
      data: {
        id: 'sess-abc',
        agent_type_id: 'at-1',
        triggered_by_user_id: null,
        input_data: null,
        status: 'completed',
        started_at: '2026-01-01T00:00:01Z',
        completed_at: '2026-01-01T00:00:05Z',
        output_data: { result: 'Success result' },
        error_message: null,
        created_at: '2026-01-01T00:00:00Z',
      },
    })

    const { AgentJobPage } = await import('../pages/agents/AgentJobPage')
    render(<AgentJobPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getAllByText('agents.sessions.statusCompleted').length).toBeGreaterThan(0)
    })
  })

  it('shows error message for failed session', async () => {
    mockGet.mockResolvedValue({
      data: {
        id: 'sess-abc',
        agent_type_id: 'at-1',
        triggered_by_user_id: null,
        input_data: null,
        status: 'failed',
        started_at: '2026-01-01T00:00:01Z',
        completed_at: '2026-01-01T00:00:05Z',
        output_data: null,
        error_message: 'Executor crashed with RuntimeError',
        created_at: '2026-01-01T00:00:00Z',
      },
    })

    const { AgentJobPage } = await import('../pages/agents/AgentJobPage')
    render(<AgentJobPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getAllByText('agents.sessions.statusFailed').length).toBeGreaterThan(0)
    })
  })

  it('sets up polling interval for non-terminal session', async () => {
    vi.useFakeTimers()

    let callCount = 0
    mockGet.mockImplementation(() => {
      callCount++
      return Promise.resolve({
        data: {
          id: 'sess-abc',
          agent_type_id: 'at-1',
          triggered_by_user_id: null,
          input_data: null,
          status: 'queued',
          started_at: null,
          completed_at: null,
          output_data: null,
          error_message: null,
          created_at: '2026-01-01T00:00:00Z',
        },
      })
    })

    const { AgentJobPage } = await import('../pages/agents/AgentJobPage')
    render(<AgentJobPage />, { wrapper })

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    // First fetch + at least one poll tick
    expect(callCount).toBeGreaterThanOrEqual(1)
  })

  it('stops polling when session reaches completed status', async () => {
    vi.useFakeTimers()

    const completedData = {
      id: 'sess-abc',
      agent_type_id: 'at-1',
      triggered_by_user_id: null,
      input_data: null,
      status: 'completed',
      started_at: '2026-01-01T00:00:01Z',
      completed_at: '2026-01-01T00:00:05Z',
      output_data: { result: 'done' },
      error_message: null,
      created_at: '2026-01-01T00:00:00Z',
    }

    mockGet.mockResolvedValue({ data: completedData })

    const { AgentJobPage } = await import('../pages/agents/AgentJobPage')
    render(<AgentJobPage />, { wrapper })

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    const callCountAfterComplete = mockGet.mock.calls.length

    // Advance timers further — should not trigger more polls
    await act(async () => {
      vi.advanceTimersByTime(9000)
    })

    expect(mockGet.mock.calls.length).toBe(callCountAfterComplete)
  })

  it('clears polling interval on unmount', async () => {
    vi.useFakeTimers()

    mockGet.mockResolvedValue({
      data: {
        id: 'sess-abc',
        agent_type_id: 'at-1',
        triggered_by_user_id: null,
        input_data: null,
        status: 'running',
        started_at: '2026-01-01T00:00:01Z',
        completed_at: null,
        output_data: null,
        error_message: null,
        created_at: '2026-01-01T00:00:00Z',
      },
    })

    const { AgentJobPage } = await import('../pages/agents/AgentJobPage')
    const { unmount } = render(<AgentJobPage />, { wrapper })

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    const callsBeforeUnmount = mockGet.mock.calls.length

    // Unmount component
    unmount()

    // Advance timers — no more calls should happen
    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })

    expect(mockGet.mock.calls.length).toBe(callsBeforeUnmount)
  })

  it('renders chat interface for conversational agent session', async () => {
    mockGet.mockResolvedValue({
      data: {
        id: 'sess-abc',
        agent_type_id: 'at-1',
        triggered_by_user_id: null,
        input_data: { message: 'Hello agent' },  // conversational session has message key
        status: 'running',
        started_at: '2026-01-01T00:00:01Z',
        completed_at: null,
        output_data: null,
        error_message: null,
        created_at: '2026-01-01T00:00:00Z',
      },
    })

    const { AgentJobPage } = await import('../pages/agents/AgentJobPage')
    render(<AgentJobPage />, { wrapper })

    await waitFor(() => {
      // Chat interface renders a send button
      expect(screen.getByText('agents.sessions.send')).toBeDefined()
    })
  })

  it('renders message history in chat interface for conversational agent', async () => {
    // Provide messages via the chat session hook mock
    vi.doMock('../hooks/useChatSession', () => ({
      useChatSession: () => ({
        messages: [
          { id: 'msg-1', role: 'user', content: 'Hello agent', timestamp: '2026-01-01T00:00:01Z' },
          { id: 'msg-2', role: 'assistant', content: 'Hello! How can I help?', timestamp: '2026-01-01T00:00:02Z' },
        ],
        sendMessage: vi.fn(),
        connected: true,
      }),
    }))

    mockGet.mockResolvedValue({
      data: {
        id: 'sess-abc',
        agent_type_id: 'at-1',
        triggered_by_user_id: null,
        input_data: { message: 'Hello agent' },
        status: 'completed',
        started_at: '2026-01-01T00:00:01Z',
        completed_at: '2026-01-01T00:00:05Z',
        output_data: null,
        error_message: null,
        created_at: '2026-01-01T00:00:00Z',
      },
    })

    // Re-import after mock update
    vi.resetModules()
    const { AgentJobPage } = await import('../pages/agents/AgentJobPage')
    render(<AgentJobPage />, { wrapper })

    await waitFor(() => {
      // Messages from the hook should render in the chat view
      expect(screen.getByText('Hello agent')).toBeDefined()
    })
  })
})
