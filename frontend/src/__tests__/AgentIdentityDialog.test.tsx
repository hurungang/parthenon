import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockGet = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    get: mockGet,
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

const onClose = vi.fn()
const onSaved = vi.fn().mockResolvedValue(undefined)

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AgentIdentityDialog', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  // ── OAuth-only creation mode ────────────────────────────────────────────────

  it('renders create dialog title', async () => {
    const { AgentIdentityDialog } = await import('../pages/agents/AgentIdentityDialog')
    render(<AgentIdentityDialog open={true} onClose={onClose} onSaved={onSaved} />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.createTitle')).toBeDefined()
    })
  })

  it('renders OAuth instructions and Sign In as Agent button', async () => {
    const { AgentIdentityDialog } = await import('../pages/agents/AgentIdentityDialog')
    render(<AgentIdentityDialog open={true} onClose={onClose} onSaved={onSaved} />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.oauthInstructions')).toBeDefined()
      expect(screen.getByText('agents.identities.signInAsAgent')).toBeDefined()
    })
  })

  it('renders OAuth note about bootstrap config', async () => {
    const { AgentIdentityDialog } = await import('../pages/agents/AgentIdentityDialog')
    render(<AgentIdentityDialog open={true} onClose={onClose} onSaved={onSaved} />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.oauthNote')).toBeDefined()
    })
  })

  it('calls GET authorize endpoint when Sign In as Agent button is clicked', async () => {
    const authUrl = 'http://keycloak/realms/ai_agents/auth?...'
    mockGet.mockResolvedValueOnce({ data: { authorization_url: authUrl } })

    const mockOpen = vi.fn()
    vi.stubGlobal('open', mockOpen)

    const { AgentIdentityDialog } = await import('../pages/agents/AgentIdentityDialog')
    render(<AgentIdentityDialog open={true} onClose={onClose} onSaved={onSaved} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('agents.identities.signInAsAgent')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('agents.identities.signInAsAgent'))
    })

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith('/agents/identities/oauth/authorize')
      expect(mockOpen).toHaveBeenCalledWith(
        authUrl,
        'agentOAuth',
        'width=600,height=700,menubar=no,toolbar=no,location=yes,status=no',
      )
    })

    vi.unstubAllGlobals()
  })

  it('calls onSaved and onClose when OAuth success message is received', async () => {
    const authUrl = 'http://keycloak/realms/ai_agents/auth?...'
    mockGet.mockResolvedValueOnce({ data: { authorization_url: authUrl } })

    const mockPopup = { closed: false, close: vi.fn() }
    const mockOpen = vi.fn(() => mockPopup)
    vi.stubGlobal('open', mockOpen)

    const { AgentIdentityDialog } = await import('../pages/agents/AgentIdentityDialog')
    render(<AgentIdentityDialog open={true} onClose={onClose} onSaved={onSaved} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('agents.identities.signInAsAgent')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('agents.identities.signInAsAgent'))
    })

    // Simulate successful OAuth callback
    await act(async () => {
      window.dispatchEvent(
        new MessageEvent('message', {
          origin: window.location.origin,
          data: {
            type: 'AGENT_OAUTH_SUCCESS',
            identity: { id: 'new-id', name: 'agent@ai_agents' },
          },
        }),
      )
    })

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled()
      expect(onClose).toHaveBeenCalled()
    })

    vi.unstubAllGlobals()
  })

  it('shows error when OAuth error message is received', async () => {
    const authUrl = 'http://keycloak/realms/ai_agents/auth?...'
    mockGet.mockResolvedValueOnce({ data: { authorization_url: authUrl } })

    const mockPopup = { closed: false, close: vi.fn() }
    const mockOpen = vi.fn(() => mockPopup)
    vi.stubGlobal('open', mockOpen)

    const { AgentIdentityDialog } = await import('../pages/agents/AgentIdentityDialog')
    render(<AgentIdentityDialog open={true} onClose={onClose} onSaved={onSaved} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('agents.identities.signInAsAgent')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('agents.identities.signInAsAgent'))
    })

    // Simulate OAuth error
    await act(async () => {
      window.dispatchEvent(
        new MessageEvent('message', {
          origin: window.location.origin,
          data: {
            type: 'AGENT_OAUTH_ERROR',
            error: 'access_denied',
            errorDescription: 'User cancelled',
          },
        }),
      )
    })

    await waitFor(() => {
      // PermissionDeniedAlert will be shown
      expect(screen.getByText(/User cancelled/)).toBeDefined()
    })

    vi.unstubAllGlobals()
  })
})
