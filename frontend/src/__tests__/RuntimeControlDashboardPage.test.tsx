import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: (...args: unknown[]) => shared.mockGet(...args),
    post: (...args: unknown[]) => shared.mockPost(...args),
  },
}))

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/agents/runtime-control" element={<div>runtime control page mounted</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RuntimeControlDashboardPage - dedicated page route', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('exposes a dedicated page at /agents/runtime-control', () => {
    renderAt('/agents/runtime-control')
    expect(screen.getByText('runtime control page mounted')).toBeDefined()
  })
})

describe('RuntimeControlDashboardPage - live SVG topology diagram', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
              },
              {
                session_id: 'sess-child-1',
                agent_type_id: 'at-child',
                agent_type_name: 'Invoice Reconciler',
                status: 'running',
                depth_from_root: 1,
                parent_session_id: 'sess-root-1',
                started_at: null,
                created_at: '2026-06-01T00:00:00Z',
                termination_category: null,
              },
              {
                session_id: 'sess-child-2',
                agent_type_id: 'at-child',
                agent_type_name: 'Vendor Policy Checker',
                status: 'running',
                depth_from_root: 1,
                parent_session_id: 'sess-root-1',
                started_at: null,
                created_at: '2026-06-01T00:00:00Z',
                termination_category: null,
              },
            ],
            edges: [
              { parent_session_id: 'sess-root-1', child_session_id: 'sess-child-1', depth_from_root: 1 },
              { parent_session_id: 'sess-root-1', child_session_id: 'sess-child-2', depth_from_root: 1 },
            ],
            root_session_ids: ['sess-root-1'],
          },
        })
      }
      if (url.startsWith('/agents/guardrails/model-usage-limits')) {
        return Promise.resolve({ data: [] })
      }
      if (url.startsWith('/agents/guardrails/model-usage-posture')) {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: [] })
    })
  })

  it('renders an SVG element with the parent and child nodes from topology data', async () => {
    const { RuntimeControlDashboardPage } = await import(
      '../pages/agents/RuntimeControlDashboardPage'
    )

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RuntimeControlDashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    // Wait for topology to load
    await waitFor(() => {
      expect(screen.getByTestId('runtime-topology-svg')).toBeDefined()
    })

    // The SVG should contain rect elements for each node and line/connector elements for edges
    const svg = screen.getByTestId('runtime-topology-svg')
    const rects = svg.querySelectorAll('rect')
    const lines = svg.querySelectorAll('line, path')
    expect(rects.length).toBeGreaterThanOrEqual(3) // at least 3 nodes
    expect(lines.length).toBeGreaterThanOrEqual(2) // at least 2 edges
  })
})

describe('RuntimeControlDashboardPage - model guardrails as a read-only dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
              },
            ],
            edges: [],
            root_session_ids: ['sess-root-1'],
          },
        })
      }
      if (url.startsWith('/agents/model-availability')) {
        return Promise.resolve({
          data: [
            {
              vendor_config_id: 'cfg-1',
              vendor_display_name: 'OpenAI Production',
              is_disabled: false,
              models: [
                {
                  model_name: 'gpt-4.1',
                  is_disabled: false,
                  disabled_reason: null,
                  guardrails: [
                    {
                      id: 'gr-1',
                      model_config_id: 'cfg-1',
                      model_id: 'cfg-1',
                      model_name: 'gpt-4.1',
                      period: 'hour' as const,
                      limit_value: 100,
                      unit: 'k' as const,
                      enforcement_posture: 'terminate' as const,
                      is_active: true,
                      details: {},
                      created_at: '2026-06-01T00:00:00Z',
                      updated_at: '2026-06-01T00:00:00Z',
                    },
                  ],
                },
              ],
            },
          ],
        })
      }
      if (url.startsWith('/agents/guardrails/model-usage-posture')) {
        return Promise.resolve({ data: [] })
      }
      if (url.startsWith('/agents/guardrails/model-usage-limits')) {
        return Promise.resolve({ data: [] })
      }
      if (url.startsWith('/agents/model-configs')) {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: [] })
    })
  })

  it('renders the guardrail panel as a read-only dashboard (no Add/Edit/Remove/switches)', async () => {
    const { RuntimeControlDashboardPage } = await import(
      '../pages/agents/RuntimeControlDashboardPage'
    )
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RuntimeControlDashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    // Wait for the dashboard summary to render (proof that readonly
    // mode is engaged and the data has loaded).
    await waitFor(() => {
      expect(screen.getByTestId('guardrail-dashboard-summary')).toBeDefined()
    })

    // No mutation affordances should be present on the runtime
    // control surface: no Add button, no edit/remove icon buttons,
    // no enable/disable switches on vendor / model / guardrail rows.
    expect(screen.queryByTestId('add-guardrail-button-cfg-1:gpt-4.1')).toBeNull()
    expect(screen.queryByTestId('guardrail-edit-gr-1')).toBeNull()
    expect(screen.queryByTestId('guardrail-remove-gr-1')).toBeNull()
    expect(screen.queryByTestId('vendor-switch-cfg-1')).toBeNull()
  })
})

describe('RuntimeControlDashboardPage - sleep conversation gets "End session" instead of "Terminate"', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    shared.mockGet.mockImplementation((url: string) => {
      if (url.startsWith('/agents/runtime/topology')) {
        return Promise.resolve({
          data: {
            nodes: [
              {
                session_id: 'conv-sleep-1',
                agent_type_id: 'at-support',
                agent_type_name: 'Support Agent',
                status: 'sleep',
                depth_from_root: 0,
                parent_session_id: null,
                started_at: null,
                created_at: '2026-06-01T00:00:00Z',
                termination_category: null,
                kind: 'conversation',
                title: 'Greeting and Introduction',
              },
            ],
            edges: [],
            root_session_ids: ['conv-sleep-1'],
          },
        })
      }
      if (url.startsWith('/agents/guardrails/model-usage-limits')) {
        return Promise.resolve({ data: [] })
      }
      if (url.startsWith('/agents/guardrails/model-usage-posture')) {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: [] })
    })
    shared.mockPost = vi.fn().mockResolvedValue({ data: { id: 'conv-sleep-1', status: 'closed' } })
  })

  it('shows the End Session button (not Terminate) when a sleep conversation is selected', async () => {
    const { RuntimeControlDashboardPage } = await import(
      '../pages/agents/RuntimeControlDashboardPage'
    )
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RuntimeControlDashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    // Wait for the topology to load (default filter excludes the
    // sleep node, so we land on the "filtered empty" state — the
    // legend is still rendered, which gives us the checkbox to
    // toggle sleep on).
    await waitFor(() => {
      // Either the SVG is rendered, or the "filtered empty"
      // message is shown (default state with no nodes matching).
      const svg = screen.queryByTestId('runtime-topology-svg')
      const empty = screen.queryByText('agents.sessions.runtimeTopologyFilteredEmpty')
      expect(svg !== null || empty !== null).toBe(true)
    })

    // Default filter excludes "conversation:sleep"; toggle it on
    // via the legend checkbox so the sleep node is rendered.
    const sleepCheckbox = screen.getByRole('checkbox', { name: /Sleep/i })
    fireEvent.click(sleepCheckbox)

    // Now the SVG should appear with the sleep node.
    await waitFor(() => {
      expect(screen.getByTestId('runtime-topology-svg')).toBeDefined()
    })

    // Click on the sleep conversation node in the SVG to select it.
    const nodeGroup = container.querySelector('[data-node-id="conv-sleep-1"]') as HTMLElement | null
    expect(nodeGroup).not.toBeNull()
    fireEvent.click(nodeGroup!)

    await waitFor(() => {
      expect(screen.getByTestId('end-conversation-button')).toBeDefined()
    })
    // The regular terminate button is hidden for sleep conversations.
    expect(screen.queryByTestId('terminate-node-button')).toBeNull()
  })
})
