import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import { ConversationDialog } from '../components/agents/ConversationDialog'
import type { ChatMessage } from '../hooks/useChatSession'

/**
 * FIX-20261101-120618 Work Item 1 — "View All Sessions" upgrades to the
 * sessions-tab experience: active/ended toggle (default active-only),
 * date-range inputs defaulting to the configured window, pagination,
 * time-desc rows, and in-place resume/switch.
 */

let mockMessages: ChatMessage[] = []
let mockChatStatus: unknown = null

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string) => k,
  }),
}))

vi.mock('../hooks/useChatSession', () => ({
  useChatSession: vi.fn(() => ({
    messages: mockMessages,
    connected: true,
    pendingQuestion: null,
    sessionTitle: null,
    guardrailUsage: null,
    chatStatus: mockChatStatus,
    delegationCycles: [],
    activeDelegationCycleId: null,
    delegationSnippets: [],
    delegationSnippetsCollapsed: true,
    toggleDelegationSnippetsCollapsed: vi.fn(),
    hydrateDelegationFromHistory: vi.fn(),
    sendMessage: vi.fn(() => true),
    clearMessages: vi.fn(),
    recoveryEpoch: 0,
    chatError: null,
    interventionRequest: null,
    interventionQueueLength: 0,
    sendInterventionResponse: vi.fn(),
    cancelIntervention: vi.fn(),
  })),
}))

/** Captured params from every useConversationSessionsPage call. */
const pageParamsCalls: Array<Record<string, unknown>> = []
let mockPage = {
  items: [
    {
      id: 'session-1',
      title: 'Current session',
      status: 'active',
      updated_at: '2026-11-01T10:00:00Z',
    },
    {
      id: 'session-ended',
      title: 'Ended session',
      status: 'closed',
      updated_at: '2026-10-30T10:00:00Z',
    },
  ] as Array<Record<string, unknown>>,
  total: 2,
  page: 1,
  page_size: 10,
  default_window_days: 7,
}

vi.mock('../hooks/useConversationSessions', () => ({
  useEndConversationSession: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useArchiveConversationSession: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useConversationSessions: vi.fn(() => ({ data: [], isLoading: false, error: null })),
  useConversationSessionsPage: vi.fn((params: Record<string, unknown>) => {
    pageParamsCalls.push(params)
    return { data: mockPage, isLoading: false, error: null }
  }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(async () => ({ data: [] })),
    post: vi.fn(async () => ({ data: { id: 'brand-new-session' } })),
  },
}))

vi.mock('../hooks/useAssistantModelConfig', () => ({
  useAssistantModelConfig: vi.fn(() => ({ data: null })),
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: () => null,
}))

vi.mock('../components/conversations/InlineInterventionDialog', () => ({
  InlineInterventionDialog: () => null,
}))
vi.mock('../components/conversations/InterventionPendingIndicator', () => ({
  InterventionPendingIndicator: () => null,
}))
vi.mock('../hooks/useConversationIntervention', () => ({
  useConversationIntervention: () => ({
    dialogError: null,
    isSubmitting: false,
    respondToIntervention: vi.fn(),
    cancelIntervention: vi.fn(),
  }),
}))
vi.mock('../components/ContentRenderer', () => ({
  ContentRenderer: (props: { content: string }) => props.content,
}))
vi.mock('../components/MaximizableContent', () => ({
  MaximizableContent: (props: { children: React.ReactNode }) => props.children,
}))
vi.mock('../components/agents/AgentExecutionDetailsDialog', () => ({
  AgentExecutionDetailsDialog: () => null,
}))
vi.mock('../hooks/useSessionExecutionLogStream', () => ({
  useSessionExecutionLogStream: () => ({ entries: [] }),
}))

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ConversationDialog
        open
        sessionId="session-1"
        agentTypeId="agent-type-1"
        agentTypeName="Assistant"
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

async function openSessionsDialog() {
  // Resume session-1 first (mirrors a live chat in progress)
  vi.mocked(apiClient.post).mockImplementation(async (url: string) => {
    if (String(url) === '/conversations/session-1/resume') {
      return {
        data: {
          id: 'session-1',
          status: 'active',
          guardrail_usage: null,
          turns: [
            {
              id: 'turn-1',
              role: 'user',
              content: 'Hello there',
              created_at: '2026-11-01T10:00:00Z',
              tool_calls: [],
            },
          ],
        },
      } as never
    }
    return { data: { id: 'brand-new-session' } } as never
  })
  const utils = renderDialog()
  await waitFor(() => {
    expect(screen.getByText('Hello there')).toBeDefined()
  })
  fireEvent.click(screen.getByText('conversations.sessions.viewAllSessions'))
  await waitFor(() => {
    expect(screen.getByText('Current session')).toBeDefined()
  })
  return utils
}

beforeEach(() => {
  mockMessages = []
  mockChatStatus = null
  pageParamsCalls.length = 0
  mockPage = {
    items: [
      { id: 'session-1', title: 'Current session', status: 'active', updated_at: '2026-11-01T10:00:00Z' },
      { id: 'session-ended', title: 'Ended session', status: 'closed', updated_at: '2026-10-30T10:00:00Z' },
    ],
    total: 2,
    page: 1,
    page_size: 10,
    default_window_days: 7,
  }
  vi.mocked(apiClient.post).mockReset()
  localStorage.clear()
})

afterEach(() => {
  cleanup()
})

describe('ConversationDialog — View All Sessions upgrades (FIX-120618 WI1)', () => {
  it('defaults to active-only with a last-7-days window', async () => {
    await openSessionsDialog()

    const toggle = screen.getByLabelText('conversations.sessions.showEnded') as HTMLInputElement
    expect(toggle.checked).toBe(false)

    const last = pageParamsCalls[pageParamsCalls.length - 1]
    expect(last.status).toBe('active')
    expect(last.agentTypeId).toBe('agent-type-1')
    // default window = last 7 days (date-truncated, so allow < 24h slack)
    const dateFrom = new Date(String(last.dateFrom))
    const now = new Date()
    const expected = new Date(now.getTime() - 7 * 24 * 3600 * 1000)
    expect(Math.abs(dateFrom.getTime() - expected.getTime())).toBeLessThan(86_460_000)
    // Ended session is NOT resumable and marked ended
    expect(screen.getByTestId('conversation-dialog-session-session-ended-terminated')).toBeDefined()
    expect(screen.queryByTestId('conversation-dialog-switch-session-session-ended')).toBeNull()
  })

  it('toggling show-ended refetches with ended sessions included', async () => {
    await openSessionsDialog()
    pageParamsCalls.length = 0

    fireEvent.click(screen.getByLabelText('conversations.sessions.showEnded'))

    await waitFor(() => {
      expect(pageParamsCalls.some((p) => p.status === 'all')).toBe(true)
    })
  })

  it('pagination controls request subsequent pages', async () => {
    mockPage = {
      items: [{ id: 'session-1', title: 'Current session', status: 'active', updated_at: '2026-11-01T10:00:00Z' }],
      total: 25,
      page: 1,
      page_size: 10,
      default_window_days: 7,
    }
    await openSessionsDialog()
    pageParamsCalls.length = 0

    // 25 items / page size 10 → 3 pages; page 2 button exists
    const page2 = screen.getByRole('button', { name: 'Go to page 2' })
    fireEvent.click(page2)

    await waitFor(() => {
      expect(pageParamsCalls.some((p) => p.page === 2)).toBe(true)
    })
  })

  it('changing the date range refetches with explicit from/to', async () => {
    await openSessionsDialog()
    pageParamsCalls.length = 0

    const fromInput = screen.getByLabelText('conversations.sessions.dateFrom') as HTMLInputElement
    fireEvent.change(fromInput, { target: { value: '2026-10-01' } })

    await waitFor(() => {
      expect(pageParamsCalls.some((p) => p.dateFrom === '2026-10-01T00:00:00.000Z')).toBe(true)
    })

    const toInput = screen.getByLabelText('conversations.sessions.dateTo') as HTMLInputElement
    fireEvent.change(toInput, { target: { value: '2026-10-31' } })
    await waitFor(() => {
      expect(pageParamsCalls.some((p) => p.dateTo === '2026-10-31T23:59:59.999Z')).toBe(true)
    })
  })

  it('switching to an active session resumes it in place (FIX-111439 semantics)', async () => {
    mockPage = {
      items: [
        { id: 'session-1', title: 'Current session', status: 'active', updated_at: '2026-11-01T10:00:00Z' },
        { id: 'session-2', title: 'Other active', status: 'active', updated_at: '2026-10-31T10:00:00Z' },
      ],
      total: 2,
      page: 1,
      page_size: 10,
      default_window_days: 7,
    }
    await openSessionsDialog()

    fireEvent.click(screen.getByTestId('conversation-dialog-switch-session-session-2'))
    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/conversations/session-2/resume')
    })
    const postedUrls = vi.mocked(apiClient.post).mock.calls.map((c) => String(c[0]))
    expect(postedUrls).not.toContain('/conversations/session-1/end')
    expect(postedUrls).not.toContain('/conversations/session-1/archive')
  })

  it('renders i18n keys for the new controls (no hardcoded strings)', async () => {
    await openSessionsDialog()
    expect(screen.getByText('conversations.sessions.viewAllSessionsTitle')).toBeDefined()
    expect(screen.getByText('conversations.sessions.dateFrom')).toBeDefined()
    expect(screen.getByText('conversations.sessions.dateTo')).toBeDefined()
    expect(screen.getByLabelText('conversations.sessions.showEnded')).toBeDefined()
  })
})
