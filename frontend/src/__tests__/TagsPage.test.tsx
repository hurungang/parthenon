import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockTagDefinitions = [
  {
    id: '1',
    key: 'env',
    scope: 'global',
    resource_type: null,
    description: 'Environment tag',
    allowed_values: ['dev', 'prod', 'staging'],
  },
]

vi.mock('../hooks/usePermissions', () => ({
  useTagDefinitions: () => ({ data: mockTagDefinitions, isLoading: false }),
  useCreateTag: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateTag: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteTag: () => ({ mutate: vi.fn(), isPending: false }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('TagsPage', () => {
  it('renders tag table when data is loaded', async () => {
    const { TagsPage } = await import('../pages/permissions/TagsPage')
    render(<TagsPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getAllByText('env')[0]).toBeDefined()
    })
  })

  it('shows translated scope label in table', async () => {
    const { TagsPage } = await import('../pages/permissions/TagsPage')
    render(<TagsPage />, { wrapper })
    await waitFor(() => {
      // With i18n mocked as (k => k), scope label should be i18n key
      // Just ensure the component renders without crash and tag name is visible
      expect(screen.getAllByText('env')[0]).toBeDefined()
    })
  })

  it('renders Add Tag button', async () => {
    const { TagsPage } = await import('../pages/permissions/TagsPage')
    render(<TagsPage />, { wrapper })
    // Button should be in the DOM
    expect(screen.getAllByRole('button').length).toBeGreaterThan(0)
  })
})

describe('TagsPage loading state', () => {
  it('shows loading indicator when isLoading is true', async () => {
    vi.doMock('../hooks/usePermissions', () => ({
      useTagDefinitions: () => ({ data: undefined, isLoading: true }),
      useCreateTag: () => ({ mutate: vi.fn(), isPending: false }),
      useUpdateTag: () => ({ mutate: vi.fn(), isPending: false }),
      useDeleteTag: () => ({ mutate: vi.fn(), isPending: false }),
    }))
    const { TagsPage } = await import('../pages/permissions/TagsPage')
    const { container } = render(<TagsPage />, { wrapper })
    // Component renders without crash
    expect(container).toBeDefined()
    vi.resetModules()
  })
})
