import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ConversationSession } from '../types'
import * as ConversationSessionsHooks from '../hooks/useConversationSessions'
import { ConversationSessionsTab } from '../components/agents/ConversationSessionsTab'

// ── Hoisted mock refs ─────────────────────────────────────────────────────────
const { mockMutate, mockMutateAsync } = vi.hoisted(() => ({
  mockMutate: vi.fn(),
  mockMutateAsync: vi.fn().mockResolvedValue({}),
}))

const { mockNavigate } = vi.hoisted(() => ({ mockNavigate: vi.fn() }))

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ fallbackMessage }: { error: unknown; fallbackMessage?: string }) => (
    <div data-testid="permission-denied-alert">{fallbackMessage ?? 'error'}</div>
  ),
}))

// Mock the hooks used by ConversationSessionsTab
vi.mock('../hooks/useConversationSessions', () => ({
  useConversationSessions: vi.fn(),
  useCreateConversationSession: vi.fn(() => ({
    mutate: mockMutate,
    isPending: false,
  })),
  useEndConversationSession: vi.fn(() => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  })),
  useArchiveConversationSession: vi.fn(() => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  })),
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeSession(overrides: Partial<ConversationSession> = {}): ConversationSession {
  return {
    id: 'session-1',
    agent_type_id: 'agent-type-1',
    triggered_by_user_id: 'user-1',
    agent_job_id: null,
    title: 'My Test Conversation',
    channel: 'web',
    status: 'active',
    turn_count: 3,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    closed_at: null,
    ...overrides,
  }
}

function renderTab(sessions: ConversationSession[], loading = false) {
  vi.mocked(ConversationSessionsHooks.useConversationSessions).mockReturnValue({
    data: sessions,
    isLoading: loading,
    error: null,
  } as ReturnType<typeof ConversationSessionsHooks.useConversationSessions>)

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ConversationSessionsTab agentTypeId="agent-type-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('ConversationSessionsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders session titles and status chips', () => {
    renderTab([makeSession({ title: 'My Test Conversation', status: 'active' })])
    expect(screen.getByText('My Test Conversation')).toBeDefined()
    // Status chip label comes from t() which returns the key in tests
    expect(screen.getByText('conversations.sessions.status.active')).toBeDefined()
  })

  it('renders untitled placeholder when title is null', () => {
    renderTab([makeSession({ title: null })])
    // The em tag with untitled text should be present
    expect(screen.getByText('conversations.sessions.untitled')).toBeDefined()
  })

  it('does not render "Start New Conversation" button', () => {
    renderTab([])
    expect(screen.queryByText('conversations.sessions.startNew')).toBeNull()
  })

  it('Archive action shows confirmation dialog before mutating', async () => {
    renderTab([makeSession({ status: 'active' })])
    const archiveBtn = screen.getByLabelText('conversations.sessions.archive')
    fireEvent.click(archiveBtn)
    // Confirm dialog title should appear
    await waitFor(() => {
      expect(screen.getByText('conversations.sessions.archiveConfirmTitle')).toBeDefined()
    })
    // mutateAsync not called yet (user hasn't confirmed)
    expect(mockMutateAsync).not.toHaveBeenCalled()
  })

  it('renders empty state without crashing', () => {
    renderTab([])
    expect(screen.getByText('conversations.sessions.empty')).toBeDefined()
  })
})
