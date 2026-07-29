import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DashboardPage } from '../../pages/DashboardPage'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('../../api/dashboardApi', () => ({
  getDashboardSummary: vi.fn().mockResolvedValue({
    snapshot_counts: {
      agent_types: 5,
      agent_types_active: 3,
      agent_types_running: 1,
      pending_interventions: 2,
      model_configs: 3,
      model_counts: 8,
      active_schedules: 4,
      agent_identities: 10,
      agent_roles: 2,
      mcp_servers: 3,
      pending_access_requests: 1,
    },
    time_sensitive: {
      guardrail_breaches: 1,
      agent_executions: { completed: 10, failed: 2 },
      posture_breaches: 0,
      notification_delivered: 45,
      notification_failed: 2,
    },
    permission_flags: {
      agent_types: false,
      interventions: false,
      model_configs: false,
      schedules: false,
      identities: false,
      roles: false,
      mcp_servers: false,
      permission_requests: false,
      guardrail_breaches: false,
      executions: false,
      posture_breaches: false,
      notifications: false,
    },
  }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('DashboardPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
  })

  it('renders the page title and tagline', async () => {
    render(<DashboardPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('nav.dashboard')).toBeTruthy()
      expect(screen.getByText('app.tagline')).toBeTruthy()
    })
  })

  it('renders operational metrics section title', async () => {
    render(<DashboardPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('dashboard.operationalMetrics')).toBeTruthy()
    })
  })

  it('renders time-sensitive metrics section title', async () => {
    render(<DashboardPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('dashboard.timeSensitiveMetrics')).toBeTruthy()
    })
  })

  it('renders all stat card labels', async () => {
    render(<DashboardPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('dashboard.agentTypes')).toBeTruthy()
      expect(screen.getByText('dashboard.pendingInterventions')).toBeTruthy()
      expect(screen.getByText('dashboard.modelConfigs')).toBeTruthy()
      expect(screen.getByText('dashboard.activeSchedules')).toBeTruthy()
      expect(screen.getByText('dashboard.agentIdentities')).toBeTruthy()
      expect(screen.getByText('dashboard.agentRoles')).toBeTruthy()
      expect(screen.getByText('dashboard.mcpServers')).toBeTruthy()
      expect(screen.getByText('dashboard.permissionRequests')).toBeTruthy()
    })
  })

  it('renders all 3 time-sensitive card labels', async () => {
    render(<DashboardPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('dashboard.guardrailBreachEvents')).toBeTruthy()
      expect(screen.getByText('dashboard.agentExecutions')).toBeTruthy()
      expect(screen.getByText('dashboard.modelUsagePostureBreaches')).toBeTruthy()
    })
  })

  it('renders date range picker presets', async () => {
    render(<DashboardPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('dashboard.presetHour')).toBeTruthy()
      expect(screen.getByText('dashboard.preset24h')).toBeTruthy()
      expect(screen.getByText('dashboard.preset7d')).toBeTruthy()
    })
  })
})
