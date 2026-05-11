import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { AgentIdentity } from '../types'

// ── Hoisted mock refs ─────────────────────────────────────────────────────────

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

// ── Test fixtures ──────────────────────────────────────────────────────────────

const MOCK_IDENTITY: AgentIdentity = {
  id: 'identity-1',
  name: 'Research Bot',
  identity_type: 'realm_user',
  realm_name: 'ai_agents',
  realm_username: 'research-bot',
  status: 'active',
  token_expires_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

// ── API mock ──────────────────────────────────────────────────────────────────

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: null }),
  },
}))

// ── Wrapper ────────────────────────────────────────────────────────────────────

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('AgentIdentityViewDialog', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.resetAllMocks()
  })

  it('shows loading spinner while identity is fetching', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockReturnValue(new Promise(() => {}))

    const { AgentIdentityViewDialog } = await import(
      '../components/agents/AgentIdentityViewDialog'
    )
    render(<AgentIdentityViewDialog open identityId="identity-1" onClose={vi.fn()} />, { wrapper })

    expect(screen.getByRole('progressbar')).toBeDefined()
  })

  it('renders identity name and realm when loaded', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_IDENTITY })

    const { AgentIdentityViewDialog } = await import(
      '../components/agents/AgentIdentityViewDialog'
    )
    render(<AgentIdentityViewDialog open identityId="identity-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('Research Bot')).toBeDefined()
    })
    expect(screen.getByText('ai_agents')).toBeDefined()
    expect(screen.getByText('research-bot')).toBeDefined()
  })

  it('renders Edit button', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_IDENTITY })

    const { AgentIdentityViewDialog } = await import(
      '../components/agents/AgentIdentityViewDialog'
    )
    render(<AgentIdentityViewDialog open identityId="identity-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'app.edit' })).toBeDefined()
    })
  })

  it('clicking Edit closes dialog and navigates to /agents/identities', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_IDENTITY })
    const onClose = vi.fn()

    const { AgentIdentityViewDialog } = await import(
      '../components/agents/AgentIdentityViewDialog'
    )
    render(
      <AgentIdentityViewDialog open identityId="identity-1" onClose={onClose} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'app.edit' })).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'app.edit' }))
    })

    expect(onClose).toHaveBeenCalledOnce()
    expect(mockNavigate).toHaveBeenCalledWith('/agents/identities')
  })

  it('Close button calls onClose', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockResolvedValue({ data: MOCK_IDENTITY })
    const onClose = vi.fn()

    const { AgentIdentityViewDialog } = await import(
      '../components/agents/AgentIdentityViewDialog'
    )
    render(
      <AgentIdentityViewDialog open identityId="identity-1" onClose={onClose} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'app.close' })).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'app.close' }))
    })

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('shows PermissionDeniedAlert when identity fetch fails', async () => {
    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockRejectedValue(new Error('Forbidden'))

    const { AgentIdentityViewDialog } = await import(
      '../components/agents/AgentIdentityViewDialog'
    )
    render(<AgentIdentityViewDialog open identityId="identity-1" onClose={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('permission-denied-alert')).toBeDefined()
    })
  })

  it('does not fetch when identityId is null', async () => {
    const apiMock = await import('../api/apiClient')
    const getSpy = vi.mocked(apiMock.default.get)

    const { AgentIdentityViewDialog } = await import(
      '../components/agents/AgentIdentityViewDialog'
    )
    render(<AgentIdentityViewDialog open identityId={null} onClose={vi.fn()} />, { wrapper })

    expect(getSpy).not.toHaveBeenCalled()
  })
})
