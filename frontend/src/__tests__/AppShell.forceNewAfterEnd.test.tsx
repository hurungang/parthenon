import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

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

vi.mock('../components/agents/ConversationDialog', () => ({
  ConversationDialog: () => <div data-testid="assistant-dialog-stub" />,
}))

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => ({
    data: [{ id: 'assistant-type-1', name: 'Control Center Assistant', is_system: true }],
    isLoading: false,
    error: null,
  }),
}))

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
}))
vi.mock('../api/apiClient', () => ({
  default: {
    get: shared.mockGet,
    post: vi.fn(),
  },
}))

import { AppShell } from '../app/AppShell'
import {
  markAssistantSessionEnded,
} from '../utils/assistantSessionState'

function renderShell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppShell — force NEW assistant session after explicit end (FIX-20261031-091657)', () => {
  beforeEach(() => {
    shared.mockGet.mockReset()
    localStorage.clear()
  })

  it('skips the resume list fetch when the force-new flag is set', async () => {
    markAssistantSessionEnded('assistant-type-1')

    renderShell()
    const button = await screen.findByTestId('assistant-fab')
    fireEvent.click(button)

    await waitFor(() => {
      expect(screen.getByTestId('assistant-dialog-stub')).toBeDefined()
    })

    // Give any accidental fetch a chance to run
    await new Promise((r) => setTimeout(r, 20))
    const listCalls = shared.mockGet.mock.calls.filter(
      ([url]) => String(url).startsWith('/conversations?agent_type_id='),
    )
    expect(listCalls).toHaveLength(0)
  })

  it('still resumes latest active session normally (no flag)', async () => {
    shared.mockGet.mockResolvedValue({ data: [] })
    renderShell()
    const button = await screen.findByTestId('assistant-fab')
    fireEvent.click(button)

    await waitFor(() => {
      expect(shared.mockGet).toHaveBeenCalledWith('/conversations?agent_type_id=assistant-type-1')
    })
  })
})
