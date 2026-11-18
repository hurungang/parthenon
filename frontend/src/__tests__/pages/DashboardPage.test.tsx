import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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

const { mockGetDashboardSummary, mockGetTokenHealth } = vi.hoisted(() => ({
  mockGetDashboardSummary: vi.fn(),
  mockGetTokenHealth: vi.fn(),
}))

vi.mock('../../api/dashboardApi', () => ({
  getDashboardSummary: mockGetDashboardSummary,
}))

vi.mock('../../api/tokenHealthApi', () => ({
  getTokenHealth: mockGetTokenHealth,
}))

// ── Payload builders ────────────────────────────────────────────────────────

const ALL_FALSE_FLAGS = {
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
}

/** All-zero dashboard summary — every card is severity "normal". */
function zeroSummary() {
  return {
    snapshot_counts: {
      agent_types: 0,
      agent_types_active: 0,
      agent_types_running: 0,
      pending_interventions: 0,
      model_configs: 0,
      model_counts: 0,
      active_schedules: 0,
      agent_identities: 0,
      agent_roles: 0,
      mcp_servers: 0,
      pending_access_requests: 0,
    },
    time_sensitive: {
      guardrail_breaches: 0,
      agent_executions: { completed: 0, failed: 0 },
      posture_breaches: 0,
      notification_delivered: 0,
      notification_failed: 0,
    },
    permission_flags: ALL_FALSE_FLAGS,
  }
}

function summaryWith(overrides: {
  snapshot?: Record<string, number>
  time?: Record<string, unknown>
  flags?: Record<string, boolean>
}) {
  const base = zeroSummary()
  return {
    ...base,
    snapshot_counts: { ...base.snapshot_counts, ...(overrides.snapshot ?? {}) },
    time_sensitive: { ...base.time_sensitive, ...(overrides.time ?? {}) },
    permission_flags: { ...base.permission_flags, ...(overrides.flags ?? {}) },
  }
}

function tokenHealth(identities: [number, number], sessions: [number, number]) {
  return {
    identities: {
      expired_count: identities[0],
      expiring_count: identities[1],
      healthy_count: 0,
      unknown_count: 0,
      items: [],
    },
    mcp_sessions: {
      expired_count: sessions[0],
      expiring_count: sessions[1],
      healthy_count: 0,
      unknown_count: 0,
      items: [],
    },
    permission_flags: { identities: false, mcp_sessions: false },
  }
}

const DEFAULT_SUMMARY = {
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
  permission_flags: ALL_FALSE_FLAGS,
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  mockNavigate.mockReset()
  mockGetDashboardSummary.mockReset()
  mockGetTokenHealth.mockReset()
  mockGetDashboardSummary.mockResolvedValue(DEFAULT_SUMMARY)
  mockGetTokenHealth.mockResolvedValue(tokenHealth([0, 0], [0, 0]))
})

describe('DashboardPage', () => {
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

/**
 * FIX-20261116-214714 — severity-ranked dashboard layout.
 *
 * Contract under test (from the approved expected behavior + implementation
 * plan):
 *  - Section wrappers: `dashboard-section-operational` / `-token` / `-time`.
 *  - Card wrappers: `dashboard-card-<key>` carrying `data-severity`
 *    (critical | warning | normal).
 *  - Token cards are green (`success` tone) when nothing is expired or
 *    expiring, `warning` when something is expiring, `error` when something
 *    is expired.
 *  - Actionable (critical/warning) cards sort above normal cards inside their
 *    section and show the `dashboard.actionRequired` badge.
 *  - Sections sort by their highest card severity; stable tie-break is
 *    operational → token → time.
 */
describe('DashboardPage — severity-ranked tiles (FIX-20261116-214714)', () => {
  /** Root MUI Card of a card wrapper (exposes the tone/action data attributes). */
  function rootCardOf(key: string): HTMLElement {
    const wrapperEl = screen.getByTestId(`dashboard-card-${key}`)
    const card = wrapperEl.matches('.MuiCard-root')
      ? wrapperEl
      : wrapperEl.querySelector('.MuiCard-root')
    if (!card) {
      throw new Error(`dashboard-card-${key} wrapper does not contain a root MuiCard element`)
    }
    return card as HTMLElement
  }

  function cardWrapper(key: string): HTMLElement {
    return screen.getByTestId(`dashboard-card-${key}`)
  }

  function testIdsInDomOrder(selector: string, scope: ParentNode = document): string[] {
    return Array.from(scope.querySelectorAll('[data-testid]'))
      .map((el) => el.getAttribute('data-testid') ?? '')
      .filter((id) => id.startsWith(selector))
  }

  function sectionOrder(): string[] {
    return testIdsInDomOrder('dashboard-section-').map((id) =>
      id.replace('dashboard-section-', ''),
    )
  }

  function sectionCardKeys(section: string): string[] {
    const sectionEl = screen.getByTestId(`dashboard-section-${section}`)
    return Array.from(sectionEl.querySelectorAll('[data-testid^="dashboard-card-"]')).map(
      (el) => (el.getAttribute('data-testid') ?? '').replace('dashboard-card-', ''),
    )
  }

  function isActionRequired(key: string): boolean {
    const card = rootCardOf(key)
    const attr = card.getAttribute('data-action-required')
    if (attr === null) {
      throw new Error(
        `dashboard-card-${key} root Card is missing data-action-required (expected "true"/"false")`,
      )
    }
    return attr === 'true'
  }

  function hasActionBadge(key: string): boolean {
    return within(cardWrapper(key)).queryByText('dashboard.actionRequired') !== null
  }

  async function renderWith(summary: unknown, tokens: unknown) {
    mockGetDashboardSummary.mockResolvedValue(summary)
    mockGetTokenHealth.mockResolvedValue(tokens)
    render(<DashboardPage />, { wrapper })
    // Wait for both endpoints to resolve and the token tone to be applied.
    await waitFor(() => {
      expect(screen.getByTestId('dashboard-card-token-identities')).toBeTruthy()
      expect(screen.getByTestId('dashboard-card-agent-types')).toBeTruthy()
    })
    await waitFor(() => {
      expect(rootCardOf('token-identities').getAttribute('data-status-tone')).not.toBeNull()
    })
  }

  it('renders all three section wrappers and every card wrapper with a severity', async () => {
    await renderWith(zeroSummary(), tokenHealth([0, 0], [0, 0]))

    expect(screen.getByTestId('dashboard-section-operational')).toBeTruthy()
    expect(screen.getByTestId('dashboard-section-token')).toBeTruthy()
    expect(screen.getByTestId('dashboard-section-time')).toBeTruthy()

    const expectedKeys = [
      'agent-types',
      'pending-interventions',
      'model-configs',
      'active-schedules',
      'agent-identities',
      'agent-roles',
      'mcp-servers',
      'permission-requests',
      'token-identities',
      'token-mcp-sessions',
      'guardrail-breaches',
      'agent-executions',
      'posture-breaches',
      'notification-delivery',
    ]
    for (const key of expectedKeys) {
      const severity = cardWrapper(key).getAttribute('data-severity')
      expect(severity, `dashboard-card-${key} is missing data-severity`).not.toBeNull()
      expect(['critical', 'warning', 'normal']).toContain(severity)
    }
  })

  it('healthy token payload (0 expired / 0 expiring) renders green token tiles with no action badge', async () => {
    await renderWith(zeroSummary(), tokenHealth([0, 0], [0, 0]))

    await waitFor(() => {
      expect(rootCardOf('token-identities').getAttribute('data-status-tone')).toBe('success')
      expect(rootCardOf('token-mcp-sessions').getAttribute('data-status-tone')).toBe('success')
    })

    expect(cardWrapper('token-identities').getAttribute('data-severity')).toBe('normal')
    expect(cardWrapper('token-mcp-sessions').getAttribute('data-severity')).toBe('normal')
    expect(hasActionBadge('token-identities')).toBe(false)
    expect(hasActionBadge('token-mcp-sessions')).toBe(false)
    // All-zero payload: nothing anywhere is actionable.
    expect(screen.queryByText('dashboard.actionRequired')).toBeNull()
  })

  it('expiring-only token payload renders warning tone + warning severity', async () => {
    await renderWith(zeroSummary(), tokenHealth([0, 2], [0, 0]))

    await waitFor(() => {
      expect(rootCardOf('token-identities').getAttribute('data-status-tone')).toBe('warning')
    })
    expect(cardWrapper('token-identities').getAttribute('data-severity')).toBe('warning')
    expect(hasActionBadge('token-identities')).toBe(true)

    // The untouched MCP tile stays green.
    expect(rootCardOf('token-mcp-sessions').getAttribute('data-status-tone')).toBe('success')
    expect(cardWrapper('token-mcp-sessions').getAttribute('data-severity')).toBe('normal')
  })

  it('expired token payload renders error tone + critical severity + action badge', async () => {
    await renderWith(zeroSummary(), tokenHealth([3, 1], [0, 0]))

    await waitFor(() => {
      expect(rootCardOf('token-identities').getAttribute('data-status-tone')).toBe('error')
    })
    expect(cardWrapper('token-identities').getAttribute('data-severity')).toBe('critical')
    expect(cardWrapper('token-identities').getAttribute('data-action-required')).toBe('true')
    expect(hasActionBadge('token-identities')).toBe(true)
  })

  it('sorts sections by highest card severity (critical token section first)', async () => {
    // Token section: critical (expired identity token).
    // Time section: warning (failed notifications only).
    // Operational section: all normal.
    await renderWith(
      summaryWith({ time: { notification_delivered: 10, notification_failed: 2 } }),
      tokenHealth([1, 0], [0, 0]),
    )

    await waitFor(() => {
      expect(screen.getByTestId('dashboard-section-token')).toBeTruthy()
      expect(rootCardOf('token-identities').getAttribute('data-status-tone')).toBe('error')
      expect(rootCardOf('notification-delivery').getAttribute('data-status-tone')).not.toBeNull()
    })

    const order = sectionOrder()
    expect(order.length).toBe(3)
    expect(order[0]).toBe('token')
    expect(order).toEqual(['token', 'time', 'operational'])
  })

  it('sorts critical/warning cards above normal cards inside their section', async () => {
    await renderWith(
      summaryWith({
        snapshot: { agent_types: 4, pending_interventions: 3, pending_access_requests: 2 },
        time: { notification_delivered: 10, notification_failed: 2 },
      }),
      tokenHealth([1, 0], [0, 0]),
    )

    await waitFor(() => {
      expect(cardWrapper('pending-interventions').getAttribute('data-severity')).toBe('critical')
      expect(cardWrapper('token-identities').getAttribute('data-severity')).toBe('critical')
      expect(cardWrapper('notification-delivery').getAttribute('data-severity')).toBe('warning')
    })

    // Token section: critical identities before normal MCP sessions.
    const tokenOrder = sectionCardKeys('token')
    expect(tokenOrder.indexOf('token-identities')).toBeGreaterThanOrEqual(0)
    expect(tokenOrder.indexOf('token-mcp-sessions')).toBeGreaterThanOrEqual(0)
    expect(tokenOrder.indexOf('token-identities')).toBeLessThan(
      tokenOrder.indexOf('token-mcp-sessions'),
    )

    // Operational section: critical pending interventions + permission requests
    // before the normal informational tiles.
    const operationalOrder = sectionCardKeys('operational')
    expect(operationalOrder.indexOf('pending-interventions')).toBeGreaterThanOrEqual(0)
    expect(operationalOrder.indexOf('agent-types')).toBeGreaterThanOrEqual(0)
    expect(operationalOrder.indexOf('pending-interventions')).toBeLessThan(
      operationalOrder.indexOf('agent-types'),
    )
    expect(operationalOrder.indexOf('permission-requests')).toBeLessThan(
      operationalOrder.indexOf('agent-types'),
    )

    // Time section: warning notification delivery before normal tiles.
    const timeOrder = sectionCardKeys('time')
    expect(timeOrder.indexOf('notification-delivery')).toBeLessThan(
      timeOrder.indexOf('guardrail-breaches'),
    )
  })

  it('places every action-required wrapper before normal wrappers within each section', async () => {
    await renderWith(
      summaryWith({
        snapshot: { agent_types: 4, pending_interventions: 3, pending_access_requests: 2 },
        time: { guardrail_breaches: 1, agent_executions: { completed: 2, failed: 1 } },
      }),
      tokenHealth([2, 0], [0, 1]),
    )

    await waitFor(() => {
      expect(cardWrapper('token-identities').getAttribute('data-severity')).toBe('critical')
    })

    for (const section of ['operational', 'token', 'time']) {
      const keys = sectionCardKeys(section)
      expect(keys.length, `section ${section} should render cards`).toBeGreaterThan(0)
      const flags = keys.map((key) => isActionRequired(key))
      const firstNormal = flags.indexOf(false)
      if (firstNormal === -1) continue
      expect(
        flags.slice(firstNormal).some((flag) => flag),
        `section ${section} renders an actionable card (${keys.join(
          ', ',
        )}) after a normal card — actionable wrappers must be sorted to the top`,
      ).toBe(false)
    }
  })

  it('does not render the action-required badge when the tile is permission-denied', async () => {
    await renderWith(
      summaryWith({
        snapshot: { pending_interventions: 5 },
        flags: { interventions: true },
      }),
      tokenHealth([0, 0], [0, 0]),
    )

    await waitFor(() => {
      expect(screen.getByTestId('dashboard-card-pending-interventions')).toBeTruthy()
      expect(rootCardOf('pending-interventions').getAttribute('data-action-required')).not.toBeNull()
    })

    // The placeholder replaces the counts, so no action affordance is offered.
    expect(within(cardWrapper('pending-interventions')).getByText('permissions.errors.accessDeniedTitle')).toBeTruthy()
    expect(hasActionBadge('pending-interventions')).toBe(false)
  })
})
