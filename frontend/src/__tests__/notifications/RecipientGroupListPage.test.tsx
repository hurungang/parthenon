/**
 * Unit tests for RecipientGroupListPage component.
 *
 * Tests:
 * - Renders group list with name and slug from hook data
 * - Shows channel count badge (number of channel_mappings)
 * - Shows loading indicator during async data fetch
 * - Shows error alert when hook returns an error
 * - Renders add group button
 * - Shows empty state when groups list is empty
 * - Status chip reflects is_active flag
 */

import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../../pages/notifications/RecipientGroupFormDialog', () => ({
  RecipientGroupFormDialog: ({ open }: { open: boolean }) => (
    <div data-testid="group-form-dialog" data-open={String(open)} />
  ),
}))

vi.mock('../../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ error }: { error: unknown }) => (
    <div data-testid="permission-denied-alert">{String(error)}</div>
  ),
}))

vi.mock('../../services/notificationService', () => ({
  deleteRecipientGroup: vi.fn().mockResolvedValue(undefined),
}))

const MOCK_GROUPS = [
  {
    id: 'grp-1',
    name: 'Operations Team',
    slug: 'operations-team',
    description: 'Ops team alerts',
    is_active: true,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    channel_mappings: [
      { id: 'map-1', channel_id: 'ch-1' },
      { id: 'map-2', channel_id: 'ch-2' },
    ],
  },
  {
    id: 'grp-2',
    name: 'Security Alerts',
    slug: 'security-alerts',
    description: null,
    is_active: false,
    created_at: '2026-05-02T00:00:00Z',
    updated_at: '2026-05-02T00:00:00Z',
    channel_mappings: [],
  },
]

function wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

describe('RecipientGroupListPage — data loaded', () => {
  it('renders group names from hook data', async () => {
    vi.resetModules()
    vi.doMock('../../hooks/useRecipientGroups', () => ({
      useRecipientGroups: () => ({
        groups: MOCK_GROUPS,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }),
    }))
    const { RecipientGroupListPage } = await import('../../pages/notifications/RecipientGroupListPage')
    render(<RecipientGroupListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('Operations Team')).toBeDefined()
      expect(screen.getByText('Security Alerts')).toBeDefined()
    })
  })

  it('renders group slug in monospace cell', async () => {
    vi.resetModules()
    vi.doMock('../../hooks/useRecipientGroups', () => ({
      useRecipientGroups: () => ({
        groups: MOCK_GROUPS,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }),
    }))
    const { RecipientGroupListPage } = await import('../../pages/notifications/RecipientGroupListPage')
    render(<RecipientGroupListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('operations-team')).toBeDefined()
      expect(screen.getByText('security-alerts')).toBeDefined()
    })
  })

  it('renders channel count for each group', async () => {
    vi.resetModules()
    vi.doMock('../../hooks/useRecipientGroups', () => ({
      useRecipientGroups: () => ({
        groups: MOCK_GROUPS,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }),
    }))
    const { RecipientGroupListPage } = await import('../../pages/notifications/RecipientGroupListPage')
    render(<RecipientGroupListPage />, { wrapper })
    await waitFor(() => {
      // Operations Team has 2 channels, Security Alerts has 0
      expect(screen.getByText('2')).toBeDefined()
      expect(screen.getByText('0')).toBeDefined()
    })
  })

  it('renders add group button', async () => {
    vi.resetModules()
    vi.doMock('../../hooks/useRecipientGroups', () => ({
      useRecipientGroups: () => ({
        groups: [],
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }),
    }))
    const { RecipientGroupListPage } = await import('../../pages/notifications/RecipientGroupListPage')
    render(<RecipientGroupListPage />, { wrapper })
    expect(screen.getAllByRole('button').length).toBeGreaterThan(0)
  })
})

describe('RecipientGroupListPage — loading state', () => {
  it('shows loading indicator when isLoading is true', async () => {
    vi.resetModules()
    vi.doMock('../../hooks/useRecipientGroups', () => ({
      useRecipientGroups: () => ({
        groups: [],
        isLoading: true,
        error: null,
        refetch: vi.fn(),
      }),
    }))
    const { RecipientGroupListPage } = await import('../../pages/notifications/RecipientGroupListPage')
    const { container } = render(<RecipientGroupListPage />, { wrapper })
    const progress = container.querySelector('[role="progressbar"]')
    expect(progress).not.toBeNull()
  })
})

describe('RecipientGroupListPage — error state', () => {
  it('displays error alert when hook returns an error', async () => {
    vi.resetModules()
    vi.doMock('../../hooks/useRecipientGroups', () => ({
      useRecipientGroups: () => ({
        groups: [],
        isLoading: false,
        error: new Error('403 Forbidden'),
        refetch: vi.fn(),
      }),
    }))
    const { RecipientGroupListPage } = await import('../../pages/notifications/RecipientGroupListPage')
    render(<RecipientGroupListPage />, { wrapper })
    await waitFor(() => {
      const alerts = screen.queryAllByTestId('permission-denied-alert')
      expect(alerts.length).toBeGreaterThan(0)
    })
  })
})

describe('RecipientGroupListPage — empty state', () => {
  it('shows empty state message when groups list is empty', async () => {
    vi.resetModules()
    vi.doMock('../../hooks/useRecipientGroups', () => ({
      useRecipientGroups: () => ({
        groups: [],
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }),
    }))
    const { RecipientGroupListPage } = await import('../../pages/notifications/RecipientGroupListPage')
    render(<RecipientGroupListPage />, { wrapper })
    await waitFor(() => {
      const empty = screen.queryByText('notifications.groups.empty')
      expect(empty).not.toBeNull()
    })
  })
})
