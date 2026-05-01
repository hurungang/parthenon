import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../hooks/usePermissions', () => ({
  useMyAccessRequests: vi.fn(() => ({ data: [], isLoading: false })),
  usePendingAccessRequests: vi.fn(() => ({ data: [], isLoading: false })),
  useSubmitAccessRequest: vi.fn(() => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })),
  useApproveAccessRequest: vi.fn(() => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })),
  useRejectAccessRequest: vi.fn(() => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })),
  useGroups: vi.fn(() => ({ data: [], isLoading: false })),
}))

import {
  useGroups,
  usePendingAccessRequests,
} from '../hooks/usePermissions'

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const MOCK_GROUP = {
  id: 'group-1',
  name: 'Ops Team',
  description: '',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  member_count: 3,
  role_count: 1,
}

const MOCK_PENDING_REQUEST = {
  id: 'req-1',
  batch_id: 'batch-1',
  user_id: 'user-1',
  group_id: undefined,
  status: 'pending',
  reviewer_id: undefined,
  reviewer_reason: undefined,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  requester_display_name: 'Test User',
}

beforeEach(() => {
  vi.mocked(useGroups).mockReturnValue({ data: [], isLoading: false } as unknown as ReturnType<typeof useGroups>)
  vi.mocked(usePendingAccessRequests).mockReturnValue({ data: [], isLoading: false } as unknown as ReturnType<typeof usePendingAccessRequests>)
})

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

// ---------------------------------------------------------------------------
// Task 4.3 — Group-optional access request UI tests
// ---------------------------------------------------------------------------

describe('MyRequestsTab — group-optional behaviour', () => {
  it('renders informational alert (not group list) when useGroups returns empty array', async () => {
    // useGroups default mock: { data: [], isLoading: false } → hasNoGroups = true
    const { AccessRequestsPage } = await import('../pages/permissions/AccessRequestsPage')
    render(<AccessRequestsPage />, { wrapper })

    // Navigate to My Requests tab (index 1)
    await waitFor(() => expect(screen.getAllByRole('tab').length).toBeGreaterThanOrEqual(2))
    fireEvent.click(screen.getAllByRole('tab')[1])

    // Open the Request Access dialog
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'permissions.accessRequests.requestAccess' })).toBeDefined()
    })
    fireEvent.click(screen.getByRole('button', { name: 'permissions.accessRequests.requestAccess' }))

    // Informational alert should be visible
    await waitFor(() => {
      expect(screen.getByText('permissions.accessRequests.noGroupInfoAlert')).toBeDefined()
    })

    // No group checkboxes should be rendered
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('renders group selection list when useGroups returns non-empty data', async () => {
    vi.mocked(useGroups).mockReturnValue({ data: [MOCK_GROUP], isLoading: false } as unknown as ReturnType<typeof useGroups>)

    const { AccessRequestsPage } = await import('../pages/permissions/AccessRequestsPage')
    render(<AccessRequestsPage />, { wrapper })

    // Navigate to My Requests tab
    await waitFor(() => expect(screen.getAllByRole('tab').length).toBeGreaterThanOrEqual(2))
    fireEvent.click(screen.getAllByRole('tab')[1])

    // Open the Request Access dialog
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'permissions.accessRequests.requestAccess' })).toBeDefined()
    })
    fireEvent.click(screen.getByRole('button', { name: 'permissions.accessRequests.requestAccess' }))

    // Group checkbox list should be visible
    await waitFor(() => {
      expect(screen.getByRole('checkbox')).toBeDefined()
    })

    // Informational alert should NOT be visible
    expect(screen.queryByText('permissions.accessRequests.noGroupInfoAlert')).toBeNull()
  })
})

describe('PendingRequestsTab — group-optional behaviour', () => {
  it('renders "Unassigned" chip for a request with no group_id', async () => {
    vi.mocked(usePendingAccessRequests).mockReturnValue({
      data: [MOCK_PENDING_REQUEST],
      isLoading: false,
    } as unknown as ReturnType<typeof usePendingAccessRequests>)

    const { AccessRequestsPage } = await import('../pages/permissions/AccessRequestsPage')
    render(<AccessRequestsPage />, { wrapper })

    // PendingRequestsTab is the default tab (index 0)
    await waitFor(() => {
      expect(screen.getByText('permissions.accessRequests.unassigned')).toBeDefined()
    })
  })

  it('approve dialog renders group dropdown when approveTarget.group_id is absent', async () => {
    vi.mocked(usePendingAccessRequests).mockReturnValue({
      data: [MOCK_PENDING_REQUEST],
      isLoading: false,
    } as unknown as ReturnType<typeof usePendingAccessRequests>)
    vi.mocked(useGroups).mockReturnValue({ data: [MOCK_GROUP], isLoading: false } as unknown as ReturnType<typeof useGroups>)

    const { AccessRequestsPage } = await import('../pages/permissions/AccessRequestsPage')
    render(<AccessRequestsPage />, { wrapper })

    // Click the Approve button in the table row
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'permissions.accessRequests.approve' })).toBeDefined()
    })
    fireEvent.click(screen.getByRole('button', { name: 'permissions.accessRequests.approve' }))

    // Dialog opens; group assignment dropdown should be visible
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
      expect(screen.getByText('permissions.accessRequests.assignGroup')).toBeDefined()
    })
  })
})

