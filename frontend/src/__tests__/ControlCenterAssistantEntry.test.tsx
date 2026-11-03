import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import enCatalog from '../i18n/locales/en.json'

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

vi.mock('../hooks/usePlatformAccess', () => ({
  usePlatformAccess: () => 'allowed',
}))

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useLocation: () => ({ pathname: '/dashboard' }),
    Outlet: () => <div data-testid="outlet-content" />,
  }
})

// Captured props of the ConversationDialog the assistant opens.
let capturedAgentTypeId: string | null = null
let capturedAgentTypeName: string | null = null

vi.mock('../components/agents/ConversationDialog', () => ({
  ConversationDialog: (props: { agentTypeId: string; agentTypeName: string }) => {
    capturedAgentTypeId = props.agentTypeId
    capturedAgentTypeName = props.agentTypeName
    return <div data-testid="assistant-conversation-dialog" />
  },
}))

// The seeded system assistant agent type surfaced by the agent-types query.
const SYSTEM_ASSISTANT = {
  id: 'at-assistant',
  name: 'control-center-assistant',
  is_system: true,
  is_active: true,
  input_type: 'conversation',
  output_type: 'auto',
}

let mockAgentTypes: Array<typeof SYSTEM_ASSISTANT> = []

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => ({ data: mockAgentTypes, isLoading: false, error: null }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Control Center Assistant entry point (AppShell)', () => {
  beforeEach(() => {
    mockAgentTypes = []
    capturedAgentTypeId = null
    capturedAgentTypeName = null
    vi.clearAllMocks()
  })

  it('does not render the assistant FAB when no system agent type is resolved', async () => {
    mockAgentTypes = [{ ...SYSTEM_ASSISTANT, is_system: false, id: 'at-1', name: 'Regular' }]
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    expect(screen.queryByLabelText('assistant.launch')).toBeNull()
  })

  it('resolves the seeded system agent type and renders the assistant FAB', async () => {
    mockAgentTypes = [SYSTEM_ASSISTANT]
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })

    // The FAB is labelled with the assistant.launch i18n key.
    await waitFor(() => {
      expect(screen.getByLabelText('assistant.launch')).toBeDefined()
    })
  })

  it('opens ConversationDialog with the resolved system agent type id on click', async () => {
    mockAgentTypes = [SYSTEM_ASSISTANT]
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })

    const fab = screen.getByLabelText('assistant.launch')
    fireEvent.click(fab)

    await waitFor(() => {
      expect(screen.getByTestId('assistant-conversation-dialog')).toBeDefined()
    })
    expect(capturedAgentTypeId).toBe(SYSTEM_ASSISTANT.id)
    expect(capturedAgentTypeName).toBe(SYSTEM_ASSISTANT.name)
  })
})

describe('Control Center Assistant — i18n catalog', () => {
  it('defines the assistant and is_system UI strings', () => {
    const catalog = enCatalog as any
    expect(catalog.assistant.launch).toBe('Control Center Assistant')
    expect(catalog.agents.types.systemBadge).toBe('System')
    expect(catalog.agents.types.systemProtected).toBe(
      'System agent types cannot be modified or deleted',
    )
  })
})
