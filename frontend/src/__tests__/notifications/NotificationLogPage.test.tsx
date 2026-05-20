/**
 * Unit tests for NotificationLogPage component.
 *
 * Tests:
 * - Renders log entries with status chips
 * - Shows loading indicator during async data fetch
 * - Shows error alert when API call fails
 * - Opens detail drawer when a row is clicked
 * - Renders pagination controls
 * - Status filter chips are rendered
 * - Empty log list renders without crash
 */

import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ error }: { error: unknown }) => (
    <div data-testid="permission-denied-alert">{String(error)}</div>
  ),
}))

const MOCK_LOGS = [
  {
    id: 'log-1',
    group_id: 'grp-1',
    channel_id: 'ch-1',
    source_type: 'MANUAL' as const,
    source_id: null,
    subject: 'Alert: Server Down',
    body: 'The production server is unreachable.',
    recipient: 'ops@example.com',
    status: 'delivered' as const,
    error: null,
    metadata_: { status_code: 200 },
    created_at: '2026-05-10T12:00:00Z',
    delivered_at: '2026-05-10T12:00:05Z',
  },
  {
    id: 'log-2',
    group_id: null,
    channel_id: 'ch-2',
    source_type: 'AGENT' as const,
    source_id: 'agent-uuid',
    subject: 'Database backup failed',
    body: 'Backup job failed at 3AM.',
    recipient: 'dba@example.com',
    status: 'failed' as const,
    error: 'Connection timeout',
    metadata_: null,
    created_at: '2026-05-10T03:00:00Z',
    delivered_at: null,
  },
]

function wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

describe('NotificationLogPage — data loaded', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('renders log entries from API', async () => {
    vi.doMock('../../services/notificationService', () => ({
      listNotificationLogs: vi.fn().mockResolvedValue(MOCK_LOGS),
    }))
    const { NotificationLogPage } = await import('../../pages/notifications/NotificationLogPage')
    render(<NotificationLogPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('Alert: Server Down')).toBeDefined()
      expect(screen.getByText('Database backup failed')).toBeDefined()
    })
  })

  it('renders status filter chips for all status options', async () => {
    vi.doMock('../../services/notificationService', () => ({
      listNotificationLogs: vi.fn().mockResolvedValue([]),
    }))
    const { NotificationLogPage } = await import('../../pages/notifications/NotificationLogPage')
    render(<NotificationLogPage />, { wrapper })
    await waitFor(() => {
      // Status filter chips use i18n keys: notifications.status.pending, .delivered, .failed
      const pendingChip = screen.queryByText('notifications.status.pending')
      expect(pendingChip).not.toBeNull()
    })
  })

  it('opens detail drawer when a log row is clicked', async () => {
    vi.doMock('../../services/notificationService', () => ({
      listNotificationLogs: vi.fn().mockResolvedValue(MOCK_LOGS),
    }))
    const { NotificationLogPage } = await import('../../pages/notifications/NotificationLogPage')
    render(<NotificationLogPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('Alert: Server Down')).toBeDefined()
    })

    // Click the first log row
    const row = screen.getByText('Alert: Server Down').closest('tr')
    if (row) fireEvent.click(row)

    await waitFor(() => {
      // Body text appears in the drawer (not in the table)
      expect(screen.getByText('The production server is unreachable.')).toBeDefined()
    })
  })

  it('renders pagination controls', async () => {
    vi.doMock('../../services/notificationService', () => ({
      listNotificationLogs: vi.fn().mockResolvedValue(MOCK_LOGS),
    }))
    const { NotificationLogPage } = await import('../../pages/notifications/NotificationLogPage')
    const { container } = render(<NotificationLogPage />, { wrapper })

    await waitFor(() => {
      // TablePagination renders as a toolbar with rows-per-page controls
      const pagination = container.querySelector('[class*="TablePagination"]')
      expect(pagination).not.toBeNull()
    })
  })
})

describe('NotificationLogPage — loading state', () => {
  it('shows loading indicator while fetching logs', async () => {
    vi.resetModules()
    // Never resolves — keeps loading state
    vi.doMock('../../services/notificationService', () => ({
      listNotificationLogs: vi.fn().mockReturnValue(new Promise(() => {})),
    }))
    const { NotificationLogPage } = await import('../../pages/notifications/NotificationLogPage')
    const { container } = render(<NotificationLogPage />, { wrapper })

    await waitFor(() => {
      const progress = container.querySelector('[role="progressbar"]')
      expect(progress).not.toBeNull()
    })
  })
})

describe('NotificationLogPage — error state', () => {
  it('shows error alert when API call fails', async () => {
    vi.resetModules()
    vi.doMock('../../services/notificationService', () => ({
      listNotificationLogs: vi.fn().mockRejectedValue(new Error('403 Forbidden')),
    }))
    const { NotificationLogPage } = await import('../../pages/notifications/NotificationLogPage')
    render(<NotificationLogPage />, { wrapper })

    await waitFor(() => {
      const alerts = screen.queryAllByTestId('permission-denied-alert')
      expect(alerts.length).toBeGreaterThan(0)
    })
  })
})

describe('NotificationLogPage — empty state', () => {
  it('renders without crash when log list is empty', async () => {
    vi.resetModules()
    vi.doMock('../../services/notificationService', () => ({
      listNotificationLogs: vi.fn().mockResolvedValue([]),
    }))
    const { NotificationLogPage } = await import('../../pages/notifications/NotificationLogPage')
    const { container } = render(<NotificationLogPage />, { wrapper })
    await waitFor(() => {
      // No crash — table body exists
      const table = container.querySelector('table')
      expect(table).not.toBeNull()
    })
  })
})
