/**
 * Tests for the Dashboard token-health cards (token-expiry-alerting):
 * count display (expired vs expiring separately), permission-denied
 * placeholder, and click-through remediation routing targets.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }))

vi.mock('../api/apiClient', () => ({
  default: { get: mockGet },
}))

import { DashboardPage } from '../pages/DashboardPage'

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Mock BOTH dashboard endpoints the page fetches (summary + token-health). */
function mockApis(tokenHealth: unknown) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/dashboard/token-health') {
      return Promise.resolve({ data: tokenHealth })
    }
    // /dashboard/summary — minimal valid payload.
    return Promise.resolve({
      data: {
        snapshot_counts: {
          agent_types: 0, agent_types_active: 0, agent_types_running: 0,
          pending_interventions: 0, model_configs: 0, model_counts: 0,
          active_schedules: 0, agent_identities: 0, agent_roles: 0,
          mcp_servers: 0, pending_access_requests: 0,
        },
        time_sensitive: {
          guardrail_breaches: 0,
          agent_executions: { completed: 0, failed: 0 },
          posture_breaches: 0,
          notification_delivered: 0, notification_failed: 0,
        },
        permission_flags: {},
      },
    })
  })
}

const HEALTHY_SUMMARY = {
  identities: {
    expired_count: 2, expiring_count: 1, healthy_count: 5, unknown_count: 0,
    items: [],
  },
  mcp_sessions: {
    expired_count: 1, expiring_count: 3, healthy_count: 4, unknown_count: 0,
    items: [],
  },
  permission_flags: { identities: false, mcp_sessions: false },
}

beforeEach(() => {
  mockGet.mockReset()
})

describe('Dashboard token-health cards', () => {
  it('renders expired counts for identities and MCP sessions', async () => {
    mockApis(HEALTHY_SUMMARY)
    renderPage()
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith('/dashboard/token-health')
    })
    await waitFor(() => {
      const identitiesCard = screen.getByText('dashboard.tokenHealthIdentities').closest('[data-testid]')
        ?? screen.getByText('dashboard.tokenHealthIdentities').closest('.MuiCard-root')!
      expect(identitiesCard).toHaveTextContent('2')
    })
    const mcpCard = screen
      .getByText('dashboard.tokenHealthMcpSessions')
      .closest('.MuiCard-root')!
    expect(mcpCard).toHaveTextContent('1')
  })

  it('shows expiring-within-7-days breakdown separately', async () => {
    mockApis(HEALTHY_SUMMARY)
    renderPage()
    await waitFor(() => {
      expect(screen.getAllByText(/dashboard.expiringWithin7Days/).length).toBe(2)
    })
    const identitiesCard = screen
      .getByText('dashboard.tokenHealthIdentities')
      .closest('.MuiCard-root')!
    expect(identitiesCard).toHaveTextContent('1 dashboard.expiringWithin7Days')
    const mcpCard = screen
      .getByText('dashboard.tokenHealthMcpSessions')
      .closest('.MuiCard-root')!
    expect(mcpCard).toHaveTextContent('3 dashboard.expiringWithin7Days')
  })

  it('routes identity remediation to /agents/identities and sessions to /mcp', async () => {
    mockApis(HEALTHY_SUMMARY)
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('dashboard.tokenHealthIdentities')).toBeTruthy()
    })
    const identitiesLink = screen
      .getByText('dashboard.tokenHealthIdentities')
      .closest('.MuiCardActionArea-root') as HTMLAnchorElement | null
    expect(identitiesLink).not.toBeNull()
    expect(identitiesLink!.getAttribute('href')).toBe('/agents/identities')

    const mcpLink = screen
      .getByText('dashboard.tokenHealthMcpSessions')
      .closest('.MuiCardActionArea-root') as HTMLAnchorElement | null
    expect(mcpLink).not.toBeNull()
    expect(mcpLink!.getAttribute('href')).toBe('/mcp')
  })

  it('shows the permission-denied placeholder instead of counts', async () => {
    mockApis({
      identities: { expired_count: 0, expiring_count: 0, healthy_count: 0, unknown_count: 0, items: [] },
      mcp_sessions: { expired_count: 0, expiring_count: 0, healthy_count: 0, unknown_count: 0, items: [] },
      permission_flags: { identities: true, mcp_sessions: true },
    })
    renderPage()
    await waitFor(() => {
      // The access-denied placeholder text from StatCard.
      expect(screen.getAllByText('permissions.errors.accessDeniedTitle').length).toBe(2)
    })
  })

  it('clears warnings after remediation (data refetch shows refreshed state)', async () => {
    // First fetch: expired identity; after refetch: healthy.
    mockGet.mockImplementation((url: string) => {
      if (url === '/dashboard/token-health') {
        const payload =
          mockGet.mock.calls.filter((c) => c[0] === '/dashboard/token-health').length <= 1
            ? HEALTHY_SUMMARY
            : {
                identities: { expired_count: 0, expiring_count: 0, healthy_count: 8, unknown_count: 0, items: [] },
                mcp_sessions: { expired_count: 0, expiring_count: 0, healthy_count: 8, unknown_count: 0, items: [] },
                permission_flags: { identities: false, mcp_sessions: false },
              }
        return Promise.resolve({ data: payload })
      }
      return Promise.resolve({
        data: {
          snapshot_counts: {
            agent_types: 0, agent_types_active: 0, agent_types_running: 0,
            pending_interventions: 0, model_configs: 0, model_counts: 0,
            active_schedules: 0, agent_identities: 0, agent_roles: 0,
            mcp_servers: 0, pending_access_requests: 0,
          },
          time_sensitive: {
            guardrail_breaches: 0,
            agent_executions: { completed: 0, failed: 0 },
            posture_breaches: 0,
            notification_delivered: 0, notification_failed: 0,
          },
          permission_flags: {},
        },
      })
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => {
      const identitiesCard = screen
        .getByText('dashboard.tokenHealthIdentities')
        .closest('.MuiCard-root')!
      expect(identitiesCard).toHaveTextContent('2')
    })
    // Remediation happened server-side — refetch reflects zero warnings.
    await queryClient.refetchQueries({ queryKey: ['dashboard', 'token-health'] })
    await waitFor(() => {
      const identitiesCard = screen
        .getByText('dashboard.tokenHealthIdentities')
        .closest('.MuiCard-root')!
      expect(identitiesCard).toHaveTextContent('0')
    })
  })
})
