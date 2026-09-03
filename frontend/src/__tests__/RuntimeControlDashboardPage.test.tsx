import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}))

// Resolve the two runtime-view title keys to their real English value so we can
// assert "no user-facing 'topology' label remains" (the keys are named
// runtimeTopologyTitle, but their *values* are "Agent Runtime Monitor").
const translations: Record<string, string> = {
  'agents.sessions.runtimeControlTitle': 'Agent Runtime Monitor',
  'agents.sessions.runtimeTopologyTitle': 'Agent Runtime Monitor',
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => translations[k] ?? k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: (...args: unknown[]) => shared.mockGet(...args),
    post: (...args: unknown[]) => shared.mockPost(...args),
  },
}))

// The map canvas is unit-tested in isolation; here we assert the page composes
// the canvas as its primary view (rather than the retired diagram/panel).
vi.mock('../components/agents/AgentRuntimeMapCanvas', () => ({
  AgentRuntimeMapCanvas: () => <div data-testid="agent-runtime-map-canvas-mock" />,
}))

import { RuntimeControlDashboardPage } from '../pages/agents/RuntimeControlDashboardPage'

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RuntimeControlDashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RuntimeControlDashboardPage - Agent Runtime Monitor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    shared.mockPost.mockResolvedValue({ data: {} })
    shared.mockGet.mockImplementation((url: string) => {
      if (url.startsWith('/agents/runtime/topology')) {
        return Promise.resolve({
          data: {
            nodes: [
              {
                session_id: 'sess-root-1',
                agent_type_id: 'at-root',
                agent_type_name: 'Procurement Orchestrator',
                status: 'running',
                depth_from_root: 0,
                parent_session_id: null,
                started_at: null,
                created_at: '2026-06-01T00:00:00Z',
                termination_category: null,
                kind: 'agent',
                needs_intervention: false,
              },
            ],
            edges: [],
            root_session_ids: ['sess-root-1'],
          },
        })
      }
      return Promise.resolve({ data: [] })
    })
  })

  it('presents the view as "Agent Runtime Monitor"', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getAllByText('Agent Runtime Monitor').length).toBeGreaterThan(0)
    })
  })

  it('renders the agent map canvas as the primary view', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('agent-runtime-map-canvas-mock')).toBeDefined()
    })
  })

  it('does not render the model guardrail panel', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('agent-runtime-map-canvas-mock')).toBeDefined()
    })
    expect(screen.queryByTestId('vendor-model-guardrail-panel')).toBeNull()
    expect(screen.queryByTestId('guardrail-dashboard-summary')).toBeNull()
  })

  it('leaves no user-facing "topology" label', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getAllByText('Agent Runtime Monitor').length).toBeGreaterThan(0)
    })
    expect(screen.queryByText(/topology/i)).toBeNull()
  })
})

describe('RuntimeControlDashboardPage - intervention alerting', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    shared.mockPost.mockResolvedValue({ data: {} })
    shared.mockGet.mockImplementation((url: string) => {
      if (url.startsWith('/agents/runtime/topology')) {
        return Promise.resolve({
          data: {
            nodes: [
              {
                session_id: 'sess-awaiting-intervention',
                agent_type_id: 'at-support',
                agent_type_name: 'Support Agent',
                status: 'sleep',
                depth_from_root: 0,
                parent_session_id: null,
                started_at: null,
                created_at: '2026-06-01T00:00:00Z',
                termination_category: null,
                kind: 'conversation',
                needs_intervention: true,
              },
            ],
            edges: [],
            root_session_ids: ['sess-awaiting-intervention'],
          },
        })
      }
      return Promise.resolve({ data: [] })
    })
  })

  it('shows the "awaiting intervention" indicator when a node needs intervention', async () => {
    renderPage()
    await waitFor(() => {
      expect(
        screen.getByText('agents.sessions.runtimeMonitorAwaitingIntervention'),
      ).toBeDefined()
    })
  })
})
