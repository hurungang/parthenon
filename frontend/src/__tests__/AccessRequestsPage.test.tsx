import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../hooks/usePermissions', () => ({
  useMyAccessRequests: () => ({ data: [], isLoading: false }),
  usePendingAccessRequests: () => ({ data: [], isLoading: false }),
  useSubmitAccessRequest: () => ({ mutate: vi.fn(), isPending: false }),
  useApproveAccessRequest: () => ({ mutate: vi.fn(), isPending: false }),
  useRejectAccessRequest: () => ({ mutate: vi.fn(), isPending: false }),
  useGroups: () => ({ data: [], isLoading: false }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AccessRequestsPage', () => {
  it('renders without crashing', async () => {
    const { AccessRequestsPage } = await import('../pages/permissions/AccessRequestsPage')
    const { container } = render(<AccessRequestsPage />, { wrapper })
    expect(container).toBeDefined()
  })

  it('renders tabs for pending and my requests', async () => {
    const { AccessRequestsPage } = await import('../pages/permissions/AccessRequestsPage')
    render(<AccessRequestsPage />, { wrapper })
    await waitFor(() => {
      // Both tab areas should be in the DOM
      expect(screen.getAllByRole('tab').length).toBeGreaterThanOrEqual(2)
    })
  })
})
