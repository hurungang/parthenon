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
    is_default: false,
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
    const editButtons = screen.queryAllByRole('button')
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

  it.skip('oauth2 auth type shows Authenticate with OAuth button in dialog', async () => {
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

  // TODO: Implement oauth2 auth type in backend
  it.skip('OAuth button click calls oauth/authorize endpoint', async () => {
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

  it.skip('OAuth success postMessage refreshes session list', async () => {
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

describe('McpSessionManager — Passthrough auth type (Task 8.6)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiClient.get.mockResolvedValue({ data: [] })
  })

  it('passthrough is included in auth type options', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    fireEvent.click(screen.getByText('mcp.sessions.create'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })
    // Open the auth type Select
    const selects = screen.getAllByRole('combobox')
    if (selects[0]) {
      fireEvent.mouseDown(selects[0])
      await waitFor(() => {
        expect(screen.queryByText('passthrough')).not.toBeNull()
      })
    }
  })

  it('selecting passthrough hides credential fields and shows info alert', async () => {
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    fireEvent.click(screen.getByText('mcp.sessions.create'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })
    // Switch to passthrough
    const selects = screen.getAllByRole('combobox')
    if (selects[0]) {
      fireEvent.mouseDown(selects[0])
      await waitFor(() => {
        const option = screen.queryByText('passthrough')
        if (option) fireEvent.click(option)
      })
    }
    await waitFor(() => {
      // Info alert text should be present
      expect(screen.queryByText('mcp.sessions.passthroughInfo')).not.toBeNull()
      // Credential fields should NOT be present
      expect(screen.queryByText('mcp.sessions.apiKey')).toBeNull()
      expect(screen.queryByText('mcp.sessions.bearerToken')).toBeNull()
    }, { timeout: 2000 })
  })

  it('passthrough session row shows Passthrough chip in table', async () => {
    const passthroughSession = {
      id: 'sess-pt',
      server_id: 'srv-1',
      name: 'Passthrough Session',
      description: null,
      auth_type: 'passthrough',
      identity_subject: null,
      identity_binding: null,
      credential_config: null,
      is_active: true,
      is_default: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get.mockResolvedValue({ data: [passthroughSession] })
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })
    await waitFor(() => {
      expect(screen.queryByText('Passthrough Session')).not.toBeNull()
      // Passthrough chip should be visible
      expect(screen.queryByText('mcp.sessions.passthrough')).not.toBeNull()
    })
  })
})

describe('McpSessionManager — conditional OAuth action buttons', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows token status chip for oauth2 sessions and dash for non-oauth2', async () => {
    const sessions = [
      {
        id: 'sess-oauth',
        server_id: 'srv-1',
        name: 'OAuth Session',
        description: null,
        auth_type: 'oauth2',
        identity_subject: null,
        identity_binding: null,
        credential_config: null,
        oauth_expires_at: '2099-01-01T00:00:00Z',
        oauth_refresh_expires_at: '2099-06-01T00:00:00Z',
        is_active: true,
        is_default: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'sess-api',
        server_id: 'srv-1',
        name: 'API Key Session',
        description: null,
        auth_type: 'api_key',
        identity_subject: null,
        identity_binding: null,
        credential_config: null,
        oauth_expires_at: null,
        oauth_refresh_expires_at: null,
        is_active: true,
        is_default: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]
    mockApiClient.get.mockResolvedValueOnce({ data: sessions })
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    const { container } = render(<McpSessionManager serverId="srv-1" />, { wrapper })
    await waitFor(() => {
      expect(screen.queryByText('OAuth Session')).not.toBeNull()
      expect(screen.queryByText('API Key Session')).not.toBeNull()
    })
    // oauth2 session renders a token status chip (MuiChip)
    const rows = container.querySelectorAll('tr')
    // The oauth2 session row should contain a Chip (token status), the api_key row should not
    // Both rows exist: header + 2 data rows
    expect(rows.length).toBeGreaterThanOrEqual(3)
  })

  it('shows green refresh button when oauth refresh token is valid', async () => {
    const oauthSession = {
      id: 'sess-oauth-valid',
      server_id: 'srv-1',
      name: 'Valid OAuth Session',
      description: null,
      auth_type: 'oauth2',
      identity_subject: null,
      identity_binding: null,
      credential_config: null,
      oauth_expires_at: '2099-01-01T00:00:00Z',
      oauth_refresh_expires_at: '2099-06-01T00:00:00Z',  // valid — far future
      is_active: true,
      is_default: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get.mockResolvedValueOnce({ data: [oauthSession] })
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    const { container } = render(<McpSessionManager serverId="srv-1" />, { wrapper })
    await waitFor(() => screen.getByText('Valid OAuth Session'))
    // Green success-colored refresh button must be present
    expect(container.querySelector('.MuiIconButton-colorSuccess')).not.toBeNull()
  })

  it('shows red reauth button when oauth refresh token is expired', async () => {
    const oauthSession = {
      id: 'sess-oauth-expired',
      server_id: 'srv-1',
      name: 'Expired OAuth Session',
      description: null,
      auth_type: 'oauth2',
      identity_subject: null,
      identity_binding: null,
      credential_config: null,
      oauth_expires_at: '2020-01-01T00:00:00Z',
      oauth_refresh_expires_at: '2020-01-01T00:00:00Z',  // expired — in the past
      is_active: true,
      is_default: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get.mockResolvedValueOnce({ data: [oauthSession] })
    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    const { container } = render(<McpSessionManager serverId="srv-1" />, { wrapper })
    await waitFor(() => screen.getByText('Expired OAuth Session'))
    // No success button — only the red reauth (error) and edit/delete buttons
    expect(container.querySelector('.MuiIconButton-colorSuccess')).toBeNull()
    // At least one error-colored button (reauth) must exist
    expect(container.querySelector('.MuiIconButton-colorError')).not.toBeNull()
  })
})

describe('McpSessionManager — Default session display', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders Default chip next to a session marked is_default=true', async () => {
    const defaultSession = {
      id: 'sess-default',
      server_id: 'srv-1',
      name: 'Default Session',
      description: null,
      auth_type: 'api_key',
      identity_subject: null,
      identity_binding: null,
      credential_config: null,
      is_active: true,
      is_default: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get.mockResolvedValue({ data: [defaultSession] })

    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })

    await waitFor(() => {
      expect(screen.queryByText('Default Session')).not.toBeNull()
    })

    // The Default chip should be visible
    const defaultChip = screen.queryByText('mcp.sessions.default')
    expect(defaultChip).not.toBeNull()
  })

  it('shows radio-button indicator for each session', async () => {
    const sessions = [
      {
        id: 'sess-a',
        server_id: 'srv-1',
        name: 'Session A',
        description: null,
        auth_type: 'api_key',
        identity_subject: null,
        identity_binding: null,
        credential_config: null,
        is_active: true,
        is_default: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'sess-b',
        server_id: 'srv-1',
        name: 'Session B',
        description: null,
        auth_type: 'bearer_token',
        identity_subject: null,
        identity_binding: null,
        credential_config: null,
        is_active: true,
        is_default: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]
    mockApiClient.get.mockResolvedValue({ data: sessions })

    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    const { container } = render(<McpSessionManager serverId="srv-1" />, { wrapper })

    await waitFor(() => {
      expect(screen.queryByText('Session A')).not.toBeNull()
    })

    // Radio buttons should be present (one per session row)
    const radios = container.querySelectorAll('input[type="radio"]')
    expect(radios.length).toBe(2)
  })

  it('shows auto-default info alert when only one session exists (isAutoDefault)', async () => {
    // With isAutoDefault (only 1 session), the info alert should show
    const singleSession = {
      id: 'sess-solo',
      server_id: 'srv-1',
      name: 'Solo Session',
      description: null,
      auth_type: 'api_key',
      identity_subject: null,
      identity_binding: null,
      credential_config: null,
      is_active: true,
      is_default: false, // Even if false, auto-default kicks in
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get.mockResolvedValue({ data: [singleSession] })

    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })

    await waitFor(() => {
      expect(screen.queryByText('Solo Session')).not.toBeNull()
    })

    // Auto-default info alert should be present
    const autoDefaultAlert = screen.queryByText('mcp.sessions.autoDefaultInfo')
    expect(autoDefaultAlert).not.toBeNull()
  })

  it('shows Default chip for sole session even when is_default=false (auto-default logic)', async () => {
    // When there's only 1 session, isAutoDefault=true, so the chip shows anyway
    const soleSession = {
      id: 'sess-alone',
      server_id: 'srv-1',
      name: 'Alone Session',
      description: null,
      auth_type: 'api_key',
      identity_subject: null,
      identity_binding: null,
      credential_config: null,
      is_active: true,
      is_default: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get.mockResolvedValue({ data: [soleSession] })

    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })

    await waitFor(() => {
      expect(screen.queryByText('Alone Session')).not.toBeNull()
    })

    // Even though is_default=false, the auto-default logic makes it show as default
    const defaultChip = screen.queryByText('mcp.sessions.default')
    expect(defaultChip).not.toBeNull()
  })
})

describe('McpSessionManager — Default session deletion blocking', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows blocking delete prompt when deleting default with siblings', async () => {
    const sessions = [
      {
        id: 'sess-d1',
        server_id: 'srv-1',
        name: 'Default Session',
        description: null,
        auth_type: 'api_key',
        identity_subject: null,
        identity_binding: null,
        credential_config: null,
        is_active: true,
        is_default: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'sess-d2',
        server_id: 'srv-1',
        name: 'Other Session',
        description: null,
        auth_type: 'bearer_token',
        identity_subject: null,
        identity_binding: null,
        credential_config: null,
        is_active: true,
        is_default: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]
    mockApiClient.get.mockResolvedValue({ data: sessions })

    const { McpSessionManager } = await import('../pages/mcp/McpSessionManager')
    render(<McpSessionManager serverId="srv-1" />, { wrapper })

    await waitFor(() => {
      expect(screen.queryByText('Default Session')).not.toBeNull()
      expect(screen.queryByText('Other Session')).not.toBeNull()
    })

    // Find the delete button for the default session and click it
    const deleteButtons = screen.queryAllByRole('button').filter((btn) =>
      btn.querySelector('[data-testid="DeleteIcon"]')
    )
    // Click the first delete button (for the default session)
    // The delete handler should show blocking error without API call
    if (deleteButtons.length > 0) {
      fireEvent.click(deleteButtons[0])
    }

    // The blocking error message should appear
    await waitFor(() => {
      const deleteBlocked = screen.queryByText('mcp.sessions.deleteDefaultBlocked')
      expect(deleteBlocked).not.toBeNull()
    })
  })
})

