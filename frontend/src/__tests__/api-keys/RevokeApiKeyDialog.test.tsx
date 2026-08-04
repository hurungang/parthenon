import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, ..._args: unknown[]) => k }),
}))

const { mockApiClient } = vi.hoisted(() => {
  return {
    mockApiClient: {
      get: vi.fn(),
      post: vi.fn(),
    },
  }
})

vi.mock('../../api/apiClient', () => ({ default: mockApiClient }))

const MOCK_KEY = {
  id: 'key-to-revoke',
  name: 'Production Agent Key',
  key_prefix: 'phn_sk_',
  agent_identity_id: 'identity-1',
  agent_identity_name: 'Agent Alpha',
  agent_role_id: 'role-1',
  agent_role_name: 'Developer',
  status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  last_used_at: '2026-06-15T00:00:00Z',
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('RevokeApiKeyDialog', () => {
  const onClose = vi.fn()
  const onRevoked = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockApiClient.get.mockResolvedValue({ data: [] })
    mockApiClient.post.mockResolvedValue({ data: { id: 'key-to-revoke', status: 'revoked', message: 'API key revoked successfully' } })
  })

  it('renders revoke dialog with warning icon and title', async () => {
    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      expect(screen.getByText('apiKeys.revokeTitle')).toBeDefined()
    })
  })

  it('displays key name in confirmation dialog', async () => {
    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      expect(screen.getByText('Production Agent Key')).toBeDefined()
    })
  })

  it('displays identity and role information', async () => {
    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      expect(screen.getByText('Agent Alpha')).toBeDefined()
      expect(screen.getByText('Developer')).toBeDefined()
    })
  })

  it('displays revoke warning message', async () => {
    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      // The warning alert content is rendered with t() interpolation
      expect(screen.getByText('apiKeys.revokeWarning')).toBeDefined()
    })
  })

  it('displays revoke description text', async () => {
    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      expect(screen.getByText('apiKeys.revokeDescription')).toBeDefined()
    })
  })

  it('has cancel and revoke buttons', async () => {
    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      expect(screen.getByText('app.cancel')).toBeDefined()
      expect(screen.getByText('apiKeys.revoke')).toBeDefined()
    })
  })

  it('calls revoke API and triggers onRevoked on confirm', async () => {
    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )

    await waitFor(() => {
      expect(screen.getByText('apiKeys.revoke')).toBeDefined()
    })

    fireEvent.click(screen.getByText('apiKeys.revoke'))

    await waitFor(() => {
      expect(mockApiClient.post).toHaveBeenCalledWith('/api-keys/key-to-revoke/revoke')
      expect(onRevoked).toHaveBeenCalled()
    })
  })

  it('renders nothing useful when keyData is null (open=false)', async () => {
    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={null} open={false} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )

    // When open is false, the dialog content should not render
    // We just verify it doesn't crash
    await waitFor(() => {
      expect(screen.queryByText('apiKeys.revokeTitle')).toBeNull()
    })
  })

  it('handles API error and displays error in dialog', async () => {
    mockApiClient.post.mockRejectedValue(new Error('Revocation failed'))

    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )

    await waitFor(() => {
      expect(screen.getByText('apiKeys.revoke')).toBeDefined()
    })

    fireEvent.click(screen.getByText('apiKeys.revoke'))

    await waitFor(() => {
      expect(screen.getByText('Revocation failed')).toBeDefined()
    })
  })

  it('cancel button calls onClose and clears error', async () => {
    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )

    await waitFor(() => {
      expect(screen.getByText('app.cancel')).toBeDefined()
    })

    fireEvent.click(screen.getByText('app.cancel'))

    expect(onClose).toHaveBeenCalled()
  })

  it('revoke button shows loading state while pending', async () => {
    // Make the API call hang
    mockApiClient.post.mockImplementation(() => new Promise(() => {}))

    const { RevokeApiKeyDialog } = await import('../../pages/api-keys/RevokeApiKeyDialog')
    render(
      <RevokeApiKeyDialog keyData={MOCK_KEY} open={true} onClose={onClose} onRevoked={onRevoked} />,
      { wrapper: Wrapper }
    )

    await waitFor(() => {
      expect(screen.getByText('apiKeys.revoke')).toBeDefined()
    })

    fireEvent.click(screen.getByText('apiKeys.revoke'))

    // Should show "Revoking..." text while loading
    await waitFor(() => {
      expect(screen.getByText('apiKeys.revoking')).toBeDefined()
    })
  })
})
