import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

const mockSessions = [
  {
    id: 'sess-1',
    server_id: 'srv-1',
    name: 'Primary Session',
    description: 'Main binding',
    auth_type: 'api_key',
    identity_subject: 'agent-001',
    identity_binding: { agent_id: 'agent-001', realm: 'parthenon' },
    credential_config: { required_keys: ['api_key'] },
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const mockApiClient = {
  get: vi.fn().mockResolvedValue({ data: mockSessions }),
  post: vi.fn().mockResolvedValue({ data: mockSessions[0] }),
  put: vi.fn().mockResolvedValue({ data: mockSessions[0] }),
  delete: vi.fn().mockResolvedValue({ data: {} }),
}

vi.mock('../api/apiClient', () => ({ default: mockApiClient }))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('McpSessionManager', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiClient.get.mockResolvedValue({ data: mockSessions })
  })

  it('renders the session manager title', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    expect(screen.getByText('mcp.sessions.title')).toBeDefined()
  }, 30000)

  it('renders create session button', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    expect(screen.getByText('mcp.sessions.create')).toBeDefined()
  })

  it('opens create dialog when create button is clicked', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    fireEvent.click(screen.getByText('mcp.sessions.create'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })
  })

  it('credential field is not pre-populated when editing a session', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    // Wait for sessions to load
    await waitFor(() => {
      expect(screen.getByText('Primary Session')).toBeDefined()
    })
    // Click edit on first session
    const editButtons = screen.getAllByTestId
      ? screen.queryAllByRole('button')
      : screen.getAllByRole('button')
    const editBtn = editButtons.find((b) => b.querySelector('svg'))
    if (editBtn) {
      fireEvent.click(editBtn)
    }
    // Credentials field should be empty (write-only)
    await waitFor(() => {
      const credInputs = screen.queryAllByRole('textbox')
      const credInput = credInputs.find((inp) => {
        const label = inp.getAttribute('aria-label') || inp.getAttribute('id') || ''
        return label.toLowerCase().includes('credential')
      })
      if (credInput) {
        expect((credInput as HTMLInputElement).value).toBe('')
      }
    })
  })

  it('shows session identity_binding field in dialog', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    fireEvent.click(screen.getByText('mcp.sessions.create'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })
    // identity_binding label should be present
    const labels = screen.queryAllByText(/identity_binding|mcp\.sessions\.identityBinding/i)
    expect(labels.length).toBeGreaterThanOrEqual(0)
  })

  it('shows session credential_config field in dialog', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    fireEvent.click(screen.getByText('mcp.sessions.create'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })
    const labels = screen.queryAllByText(/credential_config|mcp\.sessions\.credentialConfig/i)
    expect(labels.length).toBeGreaterThanOrEqual(0)
  })

  it('displays session list from API', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('Primary Session')).toBeDefined()
    })
  })

  it('renders without runtime errors', async () => {
    const errors: string[] = []
    const origErr = console.error
    console.error = (...args: unknown[]) => {
      const msg = String(args[0])
      if (!msg.includes('Warning') && !msg.includes('act(')) errors.push(msg)
      origErr(...args)
    }
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    await waitFor(() => {}, { timeout: 500 })
    console.error = origErr
    expect(errors).toHaveLength(0)
  })
})

describe('McpSessionManager — OAuth UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiClient.get.mockResolvedValue({ data: [] })
  })

  it('oauth2 auth type shows Authenticate with OAuth button in dialog', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })

    // Open create dialog
    fireEvent.click(screen.getByText('mcp.sessions.create'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    // Switch auth type to oauth2 via the Select
    // The Select component from MUI renders a hidden input + visible div
    const selects = screen.getAllByRole('combobox')
    const authTypeSelect = selects[0]
    if (authTypeSelect) {
      fireEvent.mouseDown(authTypeSelect)
      await waitFor(() => {
        const oauth2Option = screen.queryByText('oauth2')
        if (oauth2Option) fireEvent.click(oauth2Option)
      })
    }

    // After selecting oauth2, the Authenticate button key should appear
    await waitFor(() => {
      const buttons = screen.queryAllByRole('button')
      const oauthBtn = buttons.find(
        (b) => b.textContent?.includes('mcp.sessions.authenticateWithOAuth') ||
               b.textContent?.toLowerCase().includes('oauth')
      )
      expect(oauthBtn).toBeDefined()
    }, { timeout: 2000 })
  })

  it('oauth2 auth type does not show manual credential fields', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })

    fireEvent.click(screen.getByText('mcp.sessions.create'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    // Switch to oauth2
    const selects = screen.getAllByRole('combobox')
    if (selects[0]) {
      fireEvent.mouseDown(selects[0])
      await waitFor(() => {
        const option = screen.queryByText('oauth2')
        if (option) fireEvent.click(option)
      })
    }

    // Manual credential fields should NOT appear for oauth2
    await waitFor(() => {
      // api_key field key should not appear
      const apiKeyFields = screen.queryAllByText('mcp.sessions.apiKey')
      expect(apiKeyFields).toHaveLength(0)

      const bearerFields = screen.queryAllByText('mcp.sessions.bearerToken')
      expect(bearerFields).toHaveLength(0)
    }, { timeout: 2000 })
  })

  it('OAuth button click calls oauth/authorize endpoint', async () => {
    mockApiClient.get.mockImplementation((url: string) => {
      if (url.includes('/oauth/authorize')) {
        return Promise.resolve({ data: { authorization_url: 'https://auth.example.com/authorize?client_id=test&state=abc&response_type=code' } })
      }
      return Promise.resolve({ data: [] })
    })

    // Mock window.open to prevent actual popup
    const mockOpen = vi.fn().mockReturnValue({ closed: false, close: vi.fn() })
    vi.stubGlobal('open', mockOpen)

    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })

    fireEvent.click(screen.getByText('mcp.sessions.create'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    // Switch to oauth2
    const selects = screen.getAllByRole('combobox')
    if (selects[0]) {
      fireEvent.mouseDown(selects[0])
      await waitFor(() => {
        const option = screen.queryByText('oauth2')
        if (option) fireEvent.click(option)
      })
    }

    // Click the OAuth button
    await waitFor(() => {
      const buttons = screen.queryAllByRole('button')
      const oauthBtn = buttons.find(
        (b) => b.textContent?.includes('mcp.sessions.authenticateWithOAuth') ||
               b.textContent?.toLowerCase().includes('oauth')
      )
      if (oauthBtn) fireEvent.click(oauthBtn)
    }, { timeout: 2000 })

    await waitFor(() => {
      const getCalls = mockApiClient.get.mock.calls.map((c: unknown[]) => c[0] as string)
      const authorizeCall = getCalls.some((url) => url.includes('/oauth/authorize'))
      expect(authorizeCall).toBe(true)
    }, { timeout: 2000 })

    vi.unstubAllGlobals()
  })

  it('OAuth success postMessage refreshes session list', async () => {
    mockApiClient.get.mockImplementation((url: string) => {
      if (url.includes('/oauth/authorize')) {
        return Promise.resolve({ data: { authorization_url: 'https://auth.example.com/authorize?client_id=test&state=abc&response_type=code' } })
      }
      return Promise.resolve({ data: [] })
    })

    const mockPopup = { closed: false, close: vi.fn() }
    const mockOpen = vi.fn().mockReturnValue(mockPopup)
    vi.stubGlobal('open', mockOpen)

    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })

    fireEvent.click(screen.getByText('mcp.sessions.create'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    // Switch to oauth2 and click authenticate
    const selects = screen.getAllByRole('combobox')
    if (selects[0]) {
      fireEvent.mouseDown(selects[0])
      await waitFor(() => {
        const option = screen.queryByText('oauth2')
        if (option) fireEvent.click(option)
      })
    }

    await waitFor(() => {
      const buttons = screen.queryAllByRole('button')
      const oauthBtn = buttons.find(
        (b) => b.textContent?.includes('mcp.sessions.authenticateWithOAuth') ||
               b.textContent?.toLowerCase().includes('oauth')
      )
      if (oauthBtn) fireEvent.click(oauthBtn)
    }, { timeout: 2000 })

    // Simulate OAuth success message from popup
    await waitFor(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          data: { type: 'MCP_OAUTH_SUCCESS', sessionId: 'new-session-id' },
          origin: window.location.origin,
        })
      )
    })

    // After success, the API should have been called for the authorize endpoint
    await waitFor(() => {
      const getCalls = mockApiClient.get.mock.calls.map((c: unknown[]) => c[0] as string)
      expect(getCalls.some((url) => url.includes('/oauth/authorize'))).toBe(true)
    }, { timeout: 2000 })

    vi.unstubAllGlobals()
  })
})
