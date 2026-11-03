import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { ConversationSession } from '../types'

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    login: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    token: 'mock-token',
    claims: { sub: 'user1', exp: 9999999999, iat: 0, name: 'Admin' },
    setToken: vi.fn(),
    multiTenancyEnabled: false,
    activeTenant: null,
  }),
}))

// Capture the ConversationDialog props so we can assert which session the
// assistant entry point resolves and passes down.
const dialogPropsSpy = vi.hoisted(() => ({ last: null as Record<string, unknown> | null }))

vi.mock('../components/agents/ConversationDialog', () => ({
  ConversationDialog: (props: Record<string, unknown>) => {
    dialogPropsSpy.last = props
    return <div data-testid="assistant-dialog-stub" data-session-id={String(props.sessionId)} />
  },
}))

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => ({
    data: [
      { id: 'assistant-type-1', name: 'Control Center Assistant', is_system: true },
      { id: 'regular-type-1', name: 'Regular Agent', is_system: false },
    ],
    isLoading: false,
    error: null,
  }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

function makeSession(
  id: string,
  status: ConversationSession['status'],
  updatedAt: string,
): ConversationSession {
  return {
    id,
    agent_type_id: 'assistant-type-1',
    triggered_by_user_id: 'user1',
    agent_job_id: null,
    title: null,
    channel: 'web',
    status,
    turn_count: 2,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: updatedAt,
    closed_at: null,
    guardrail_usage: null,
  }
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

async function renderShell() {
  const { AppShell } = await import('../app/AppShell')
  render(<AppShell />, { wrapper })
}

beforeEach(() => {
  dialogPropsSpy.last = null
  vi.mocked(apiClient.get).mockReset()
  vi.mocked(apiClient.post).mockReset()
  // Default catch-all: any non-conversations GET returns an empty payload.
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (String(url).includes('/conversations')) {
      return { data: [] } as never
    }
    return { data: null } as never
  })
})

describe('AppShell — assistant session persistence', () => {
  it('resolves and passes the most recent ACTIVE session id to the dialog', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (String(url).includes('/conversations?agent_type_id=assistant-type-1')) {
        return {
          data: [
            makeSession('session-old-active', 'active', '2026-01-01T10:00:00Z'),
            makeSession('session-closed-newer', 'closed', '2026-01-03T10:00:00Z'),
            makeSession('session-latest-active', 'active', '2026-01-02T10:00:00Z'),
          ],
        } as never
      }
      return { data: null } as never
    })

    await renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'assistant.launch' }))

    await waitFor(() => {
      expect(screen.getByTestId('assistant-dialog-stub')).toBeDefined()
    })
    expect(apiClient.get).toHaveBeenCalledWith(
      '/conversations?agent_type_id=assistant-type-1',
    )
    expect(screen.getByTestId('assistant-dialog-stub').getAttribute('data-session-id')).toBe(
      'session-latest-active',
    )
  })

  it('falls back to a new session (null id) when no active session exists', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (String(url).includes('/conversations')) {
        return {
          data: [makeSession('session-closed', 'closed', '2026-01-05T10:00:00Z')],
        } as never
      }
      return { data: null } as never
    })

    await renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'assistant.launch' }))

    await waitFor(() => {
      expect(screen.getByTestId('assistant-dialog-stub')).toBeDefined()
    })
    expect(screen.getByTestId('assistant-dialog-stub').getAttribute('data-session-id')).toBe('null')
  })

  it('does not flash an empty dialog while the session is being resolved', async () => {
    const deferred: { resolve: () => void } = { resolve: () => {} }
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (String(url).includes('/conversations')) {
        await new Promise<void>((resolve) => {
          deferred.resolve = resolve
        })
        return {
          data: [makeSession('session-active', 'active', '2026-01-02T10:00:00Z')],
        } as never
      }
      return { data: null } as never
    })

    await renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'assistant.launch' }))

    // While resolving, no dialog is mounted at all (no empty conversation flash).
    expect(screen.queryByTestId('assistant-dialog-stub')).toBeNull()

    deferred.resolve()
    await waitFor(() => {
      expect(screen.getByTestId('assistant-dialog-stub')).toBeDefined()
    })
    expect(screen.getByTestId('assistant-dialog-stub').getAttribute('data-session-id')).toBe(
      'session-active',
    )
  })

  it('falls back to a new session when the sessions API fails', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (String(url).includes('/conversations')) {
        throw new Error('network down')
      }
      return { data: null } as never
    })

    await renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'assistant.launch' }))

    await waitFor(() => {
      expect(screen.getByTestId('assistant-dialog-stub')).toBeDefined()
    })
    expect(screen.getByTestId('assistant-dialog-stub').getAttribute('data-session-id')).toBe('null')
  })
})
