import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { AgentPlan } from '../types'

type MockAgentType = {
  id: string
  name: string
  description: string | null
  identity_id: string | null
  role_id: string | null
  llm_provider: string
  llm_model: string
  model_id: string | null
  system_instruction: string | null
  input_type: string
  input_schema: null
  output_type: string
  output_schema: null
  output_data_type_id: string | null
  output_data_type_name: string | null
  is_active: boolean
  is_system?: boolean
  created_at: string
  updated_at: string
  sop_bindings?: Array<unknown>
  skill_bindings?: Array<unknown>
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

// Mock TopologyDiagramRenderer to avoid SVG rendering complexity in these tests
vi.mock('../components/agents/TopologyDiagramRenderer', () => ({
  default: () => <div data-testid="topology-diagram" />,
}))

// Mock ConversationDialog to avoid WebSocket complexity in these tests
vi.mock('../components/agents/ConversationDialog', () => ({
  ConversationDialog: () => <div data-testid="conversation-dialog" />,
}))

// Override default form values so input_type starts as 'typed', not 'none'.
// This lets plan preview tests work without needing input schema fields.
vi.mock('../pages/agents/AgentTypeForm', async () => {
  const actual = await vi.importActual<typeof import('../pages/agents/AgentTypeForm')>(
    '../pages/agents/AgentTypeForm',
  )
  return {
    ...actual,
    defaultAgentTypeFormValues: { ...actual.defaultAgentTypeFormValues, input_type: 'typed', sop_bindings: [{ sop_id: 'sop-preset', order: 0 }] },
  }
})

let mockAgentTypes: MockAgentType[] = [
  {
    id: 'at-1',
    name: 'Research Agent',
    description: null,
    identity_id: null,
    role_id: null,
    llm_provider: 'openai',
    llm_model: 'gpt-4o',
    system_instruction: null,
    input_type: 'typed',
    input_schema: null,
    output_type: 'markdown',
    output_schema: null,
    model_id: null,
    output_data_type_id: null,
    output_data_type_name: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const MOCK_PLAN: AgentPlan = {
  id: 'plan-1',
  agent_type_id: 'at-new',
  plan_steps: [
    { order: 1, type: 'tool_call', name: 'Gather Info', description: 'Gather context' },
    { order: 2, type: 'sop_invocation', name: 'Execute SOP', description: null },
  ],
  topology_nodes: [{ id: 'role:r1', type: 'role', label: 'Role' }],
  topology_edges: [],
  generation_status: 'success',
  generation_error: null,
  agent_config_hash: 'hash123',
  generated_at: '2026-05-09T12:00:00Z',
}

// Mutable mock post/put — tests override these per scenario
let mockPostResult: { data: Record<string, unknown> } = { data: {} }
let mockPutResult: { data: Record<string, unknown> } = { data: {} }

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => ({
    data: mockAgentTypes,
    isLoading: false,
    error: null,
  }),
  // useAgentType is called by AgentTypeDetailsDialog when a row is clicked
  useAgentType: () => ({ data: undefined, isLoading: true, error: null }),
  useAgentInstances: () => ({ data: [], isLoading: false }),
  useTerminateInstance: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteAgentType: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    post: vi.fn(() => Promise.resolve(mockPostResult)),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    get: vi.fn().mockResolvedValue({ data: [] }),
    put: vi.fn(() => Promise.resolve(mockPutResult)),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AgentManagementPage', () => {
  beforeEach(() => {
    mockAgentTypes = [
      {
        id: 'at-1',
        name: 'Research Agent',
        description: null,
        identity_id: null,
        role_id: null,
        llm_provider: 'openai',
        llm_model: 'gpt-4o',
        model_id: null,
        system_instruction: null,
        input_type: 'typed',
        input_schema: null,
        output_type: 'markdown',
        output_schema: null,
        output_data_type_id: null,
        output_data_type_name: null,
        sop_bindings: [],
        skill_bindings: [],
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]
    vi.clearAllMocks()
  })

  it('renders the page heading', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByText('agents.title')).toBeDefined()
  })

  it('renders the agent type from mock data', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByText('Research Agent')).toBeDefined()
  })

  it('renders input_type chip for agent type', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    // input_type 'typed' shown as chip
    expect(screen.getByText('typed')).toBeDefined()
  })

  it('does not render old mode or max_instances fields', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.queryByText('agents.skillfulAgent')).toBeNull()
    expect(screen.queryByText('max_instances')).toBeNull()
  })

  it('renders Create Agent Type button', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByRole('button', { name: /agents\.createType/i })).toBeDefined()
  })

  it('opens dialog when Create Agent Type is clicked', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: /agents\.createType/i }))
    expect(screen.getByRole('dialog')).toBeDefined()
  })

  it('renders Launch (PlayArrow) button per agent type row', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    // Tooltip wraps icon button with aria-label agents.types.runAgent (since mock is typed)
    expect(screen.getByRole('button', { name: 'agents.types.runAgent' })).toBeDefined()
  })

  it('renders a separate Optimize action per row and gates it on a successful execution', async () => {
    const apiMock = await import('../api/apiClient')
    const getMock = vi.mocked(apiMock.default.get)
    const originalImpl = getMock.getMockImplementation()
    getMock.mockImplementation(((url: string) =>
      String(url).includes('optimization-gate')
        ? Promise.resolve({
            data: {
              can_optimize: true,
              can_generate_plan: true,
              workflow_model_configured: true,
              workflow_model_id: 'gpt-4o',
              is_conversational: false,
              successful_executions: 1,
              reason: null,
              reason_code: null,
            },
          })
        : Promise.resolve({ data: [] })) as never)

    try {
      const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
      render(<AgentManagementPage />, { wrapper })

      // Run stays available; Optimize is its own, separately rendered action.
      expect(screen.getByRole('button', { name: 'agents.types.runAgent' })).toBeDefined()

      const optimize = await screen.findByTestId('optimize-agent-action')
      await waitFor(() => {
        expect((optimize as HTMLButtonElement).disabled).toBe(false)
      })

      await act(async () => {
        fireEvent.click(optimize)
      })

      // No pre-start confirmation dialog: the run starts directly.
      expect(screen.queryByText('agents.optimize.intro')).toBeNull()
      await waitFor(() => {
        expect(apiMock.default.post).toHaveBeenCalledWith(
          '/agents/sessions/optimize',
          { agent_type_id: 'at-1' },
        )
      })
    } finally {
      if (originalImpl) getMock.mockImplementation(originalImpl)
    }
  })

  it('hides the Optimize action for conversational agent rows', async () => {
    mockAgentTypes = [
      {
        ...mockAgentTypes[0],
        id: 'at-conv',
        name: 'Chat Agent',
        input_type: 'conversation',
        model_id: null,
        sop_bindings: [],
        skill_bindings: [],
      },
    ]

    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('Chat Agent')).toBeDefined()
    })

    // Conversational agents have no plan or optimization — the action self-hides.
    expect(screen.queryByTestId('optimize-agent-action')).toBeNull()
    // Their Run/Start Chat surface is unchanged.
    expect(screen.getByRole('button', { name: 'agents.types.startChat' })).toBeDefined()
  })

  it('disables Optimize with the localized authoring-model reason when no model is configured', async () => {
    const apiMock = await import('../api/apiClient')
    const getMock = vi.mocked(apiMock.default.get)
    const originalImpl = getMock.getMockImplementation()
    getMock.mockImplementation(((url: string) =>
      String(url).includes('optimization-gate')
        ? Promise.resolve({
            data: {
              can_optimize: false,
              can_generate_plan: false,
              workflow_model_configured: false,
              workflow_model_id: null,
              is_conversational: false,
              successful_executions: 0,
              reason_code: 'authoring_model_not_configured',
              reason: 'No authoring model configured.',
            },
          })
        : Promise.resolve({ data: [] })) as never)

    try {
      const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
      render(<AgentManagementPage />, { wrapper })

      const optimize = await screen.findByTestId('optimize-agent-action')
      await waitFor(() => {
        expect((optimize as HTMLButtonElement).disabled).toBe(true)
      })

      // The reason_code copy is preferred over the raw backend reason.
      fireEvent.mouseOver(optimize.closest('span') as HTMLElement)
      expect(
        await screen.findByText('agents.optimize.gateReasons.authoring_model_not_configured'),
      ).toBeDefined()

      // A gated action never starts a run.
      fireEvent.click(optimize)
      expect(apiMock.default.post).not.toHaveBeenCalled()
    } finally {
      if (originalImpl) getMock.mockImplementation(originalImpl)
    }
  })

  it('asks the operator to re-select when the saved authoring model is no longer enabled', async () => {
    const apiMock = await import('../api/apiClient')
    const getMock = vi.mocked(apiMock.default.get)
    const originalImpl = getMock.getMockImplementation()
    getMock.mockImplementation(((url: string) =>
      String(url).includes('optimization-gate')
        ? Promise.resolve({
            data: {
              can_optimize: false,
              can_generate_plan: false,
              workflow_model_configured: false,
              workflow_model_id: 'retired-model',
              is_conversational: false,
              successful_executions: 2,
              reason_code: 'authoring_model_not_enabled',
              reason: 'The saved authoring model is gone.',
            },
          })
        : Promise.resolve({ data: [] })) as never)

    try {
      const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
      render(<AgentManagementPage />, { wrapper })

      const optimize = await screen.findByTestId('optimize-agent-action')
      await waitFor(() => {
        expect((optimize as HTMLButtonElement).disabled).toBe(true)
      })

      fireEvent.mouseOver(optimize.closest('span') as HTMLElement)
      expect(
        await screen.findByText('agents.optimize.gateReasons.authoring_model_not_enabled'),
      ).toBeDefined()
    } finally {
      if (originalImpl) getMock.mockImplementation(originalImpl)
    }
  })

  it('opens AgentJobLaunchDialog when Launch is clicked', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    // Find and click the launch button by its accessible name (mock agent is typed, so runAgent)
    const launchBtn = screen.getByRole('button', { name: 'agents.types.runAgent' })
    await act(async () => {
      fireEvent.click(launchBtn)
    })

    // Launch dialog should open
    await waitFor(() => {
      expect(screen.getByText('agents.sessions.launch')).toBeDefined()
    })
  })

  it('opens ConversationDialog when Launch is clicked for conversation agent', async () => {
    // Mock a conversation agent type
    const conversationAgent = {
      ...mockAgentTypes[0],
      id: 'at-conv',
      name: 'Chat Agent',
      input_type: 'conversation',
      model_id: null,
      output_data_type_id: null,
      output_data_type_name: null,
      sop_bindings: [],
      skill_bindings: [],
    }
    mockAgentTypes = [conversationAgent]

    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    // Wait for conversation launch action to appear
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'agents.types.startChat' })).toBeDefined()
    })

    // Find and click the launch button (should say 'Start Chat' for conversation agents)
    const launchBtn = screen.getByRole('button', { name: 'agents.types.startChat' })
    await act(async () => {
      fireEvent.click(launchBtn)
    })

    // Conversation dialog should open (mocked as div with testid)
    await waitFor(() => {
      expect(screen.getByTestId('conversation-dialog')).toBeDefined()
    })
  })

  it('renders Edit button per agent type row', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByRole('button', { name: 'app.edit' })).toBeDefined()
  })

  it('does not render a separate View action (row click already opens details)', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.queryByRole('button', { name: 'app.view' })).toBeNull()
  })
})

// ── Post-save navigation tests ─────────────────────────────────────────────────

describe('AgentManagementPage — post-save navigation', () => {
  beforeEach(() => {
    // Reset mock results before each test
    mockPostResult = { data: {} }
    mockPutResult = { data: {} }
    mockAgentTypes = [
      {
        id: 'at-1',
        name: 'Research Agent',
        description: null,
        identity_id: null,
        role_id: null,
        llm_provider: 'openai',
        llm_model: 'gpt-4o',
        model_id: null,
        system_instruction: null,
        input_type: 'typed',
        input_schema: null,
        output_type: 'markdown',
        output_schema: null,
        output_data_type_id: null,
        output_data_type_name: null,
        sop_bindings: [],
        skill_bindings: [],
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]
    vi.clearAllMocks()
  })

  it('opens AgentTypeDetailsDialog after successful create (agent has plan)', async () => {
    const savedAgentType = {
      id: 'at-new',
      name: 'New Agent',
      description: null,
      identity_id: null,
      role_id: null,
      model_id: null,
      system_instruction: null,
      input_type: 'typed',
      input_schema: null,
      output_type: 'markdown',
      output_schema: null,
      output_data_type_id: null,
      output_data_type_name: null,
      sop_bindings: [],
      skill_bindings: [],
      is_active: true,
      created_at: '2026-05-09T12:00:00Z',
      updated_at: '2026-05-09T12:00:00Z',
      plan: MOCK_PLAN,
    }
    mockPostResult = { data: savedAgentType }

    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    fireEvent.click(screen.getByRole('button', { name: /agents\.createType/i }))

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    const nameInputs = screen.getAllByRole('textbox')
    fireEvent.change(nameInputs[0], { target: { value: 'new-agent' } })

    const saveBtn = screen.getByRole('button', { name: /app\.save/i })
    await act(async () => {
      fireEvent.click(saveBtn)
    })

    // Create dialog closes; PlanPreviewModal is never shown
    await waitFor(() => {
      expect(screen.queryByText('agents.plan.previewTitle')).toBeNull()
    })
    // AgentTypeDetailsDialog opens (title shows the dialog heading i18n key while loading)
    await waitFor(() => {
      expect(screen.getByText('agents.types.dialogTitle')).toBeDefined()
    })
  })

  it('opens AgentTypeDetailsDialog after save even without a plan', async () => {
    const savedAgentTypeNoPlan = {
      id: 'at-noplan',
      name: 'No Plan Agent',
      description: null,
      identity_id: null,
      role_id: null,
      model_id: null,
      system_instruction: null,
      input_type: 'typed',
      input_schema: null,
      output_type: 'markdown',
      output_schema: null,
      output_data_type_id: null,
      output_data_type_name: null,
      sop_bindings: [],
      skill_bindings: [],
      is_active: true,
      created_at: '2026-05-09T12:00:00Z',
      updated_at: '2026-05-09T12:00:00Z',
    }
    mockPostResult = { data: savedAgentTypeNoPlan }

    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    fireEvent.click(screen.getByRole('button', { name: /agents\.createType/i }))

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    const nameInputs = screen.getAllByRole('textbox')
    fireEvent.change(nameInputs[0], { target: { value: 'no-plan-agent' } })

    const saveBtn = screen.getByRole('button', { name: /app\.save/i })
    await act(async () => {
      fireEvent.click(saveBtn)
    })

    // PlanPreviewModal never opens
    await waitFor(() => {
      expect(screen.queryByText('agents.plan.previewTitle')).toBeNull()
    })
    // AgentTypeDetailsDialog opens
    await waitFor(() => {
      expect(screen.getByText('agents.types.dialogTitle')).toBeDefined()
    })
  })
})

// ── Role and identity column tests ────────────────────────────────────────────

describe('AgentManagementPage — role and identity columns', () => {
  beforeEach(() => {
    mockAgentTypes = [
      {
        id: 'at-1',
        name: 'Research Agent',
        description: null,
        identity_id: null,
        role_id: null,
        llm_provider: 'openai',
        llm_model: 'gpt-4o',
        model_id: null,
        system_instruction: null,
        input_type: 'typed',
        input_schema: null,
        output_type: 'markdown',
        output_schema: null,
        output_data_type_id: null,
        output_data_type_name: null,
        sop_bindings: [],
        skill_bindings: [],
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]
    vi.clearAllMocks()
  })

  it('renders Role column header', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByRole('columnheader', { name: 'agents.types.role' })).toBeDefined()
  })

  it('renders Identity column header', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByRole('columnheader', { name: 'agents.types.identity' })).toBeDefined()
  })

  it('shows dash in Role column when role_id is null', async () => {
    // mockAgentTypes has role_id: null, apiClient.get returns [] for roles
    // so roleMap is empty and the cell falls back to '—'
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    // Multiple '—' may appear (model, role, identity) — verify at least one
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(1)
  })

  it('does not render a Data Type column (kept out of the list to reduce table width)', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.queryByRole('columnheader', { name: 'agents.types.outputDataType' })).toBeNull()
  })

  it('does not show the assigned data type name in the list table', async () => {
    mockAgentTypes = [
      {
        id: 'at-2',
        name: 'Report Agent',
        description: null,
        identity_id: null,
        role_id: null,
        llm_provider: 'openai',
        llm_model: 'gpt-4o',
        model_id: null,
        system_instruction: null,
        input_type: 'typed',
        input_schema: null,
        output_type: 'typed',
        output_schema: null,
        output_data_type_id: 'dt-1',
        output_data_type_name: 'Structured Report',
        sop_bindings: [],
        skill_bindings: [],
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]

    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    // Data type is intentionally not shown in the list table; it remains in the
    // agent type details dialog and edit form.
    expect(screen.queryByText('Structured Report')).toBeNull()
  })

  it('shows dash in the list when no data type is assigned', async () => {
    // mockAgentTypes[0] has output_data_type_name: null, so the cell shows '—'
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(1)
  })

  it('shows role name in Role column when resolved from API', async () => {
    // Temporarily add a role_id to the mock agent type and mock apiClient
    // to return role data so the role name resolves in the table
    const originalRoleId = mockAgentTypes[0].role_id
    mockAgentTypes[0].role_id = 'role-1'

    const apiMock = await import('../api/apiClient')
    vi.mocked(apiMock.default.get).mockImplementation((url: string) => {
      if ((url as string) === '/agents/roles')
        return Promise.resolve({
          data: [
            {
              id: 'role-1',
              name: 'Research Role',
              description: null,
              sop_ids: [],
              skill_ids: [],
              created_at: '',
              updated_at: '',
            },
          ],
        })
      return Promise.resolve({ data: [] })
    })

    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('Research Role')).toBeDefined()
    })

    // Restore original mock state
    mockAgentTypes[0].role_id = originalRoleId
  })
})

// ── Row-click → AgentTypeDetailsDialog tests ───────────────────────────────────

describe('AgentManagementPage — row click opens AgentTypeDetailsDialog', () => {
  beforeEach(() => {
    mockPostResult = { data: {} }
    mockPutResult = { data: {} }
    vi.clearAllMocks()
  })

  it('opens a dialog when an agent type row is clicked', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    // Find the agent type row by name and click it
    const agentRow = screen.getByText('Research Agent').closest('tr')
    expect(agentRow).not.toBeNull()

    await act(async () => {
      fireEvent.click(agentRow!)
    })

    // A dialog should be open (MUI Dialog renders with role="dialog")
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })
  })

  it('passes the correct agentTypeId to AgentTypeDetailsDialog on row click', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    const agentRow = screen.getByText('Research Agent').closest('tr')
    await act(async () => {
      fireEvent.click(agentRow!)
    })

    // Dialog title should show the i18n key (loading state from useAgentType mock)
    // The dialog title for a loading state uses the fallback key
    await waitFor(() => {
      expect(screen.getByText('agents.types.dialogTitle')).toBeDefined()
    })
  })

  it('action buttons (Launch, Edit) do not open details dialog due to stopPropagation', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    // Click the Edit button — it uses stopPropagation, so dialog should NOT open
    const editBtn = screen.getByRole('button', { name: 'app.edit' })
    await act(async () => {
      fireEvent.click(editBtn)
    })

    // The edit form dialog opens, but it's a different dialog (the Create/Edit form)
    // The AgentTypeDetailsDialog should NOT be open; the form dialog opens instead
    // We check that "agents.types.dialogTitle" is NOT in DOM (that's the details dialog key)
    // while the edit form dialog IS open (agents.types.editType would be in the dialog)
    const dialogs = screen.getAllByRole('dialog')
    // At most one dialog should be open (the edit dialog, not the details dialog)
    expect(dialogs.length).toBe(1)
  })
})

// ── Default SOP availability tests ────────────────────────────────────────────

describe('AgentManagementPage — Default SOP field available for all input types', () => {
  beforeEach(() => {
    mockAgentTypes = [
      {
        id: 'at-1',
        name: 'Research Agent',
        description: null,
        identity_id: null,
        role_id: null,
        llm_provider: 'openai',
        llm_model: 'gpt-4o',
        model_id: null,
        system_instruction: null,
        input_type: 'typed',
        input_schema: null,
        output_type: 'markdown',
        output_schema: null,
        output_data_type_id: null,
        output_data_type_name: null,
        sop_bindings: [],
        skill_bindings: [],
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]
    vi.clearAllMocks()
  })

  it('SOP/Skill Bindings section is visible in create dialog for typed-input agent', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    fireEvent.click(screen.getByRole('button', { name: /agents\.createType/i }))

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    // agents.types.bindings.title is the i18n key rendered by useTranslation mock as-is
    expect(screen.getByText('agents.types.bindings.title')).toBeDefined()
  })
})

// ── is_system surfacing (Control Center Assistant) ───────────────────────────

describe('AgentManagementPage — is_system agent types', () => {
  beforeEach(() => {
    mockAgentTypes = [
      {
        id: 'at-system',
        name: 'control-center-assistant',
        description: null,
        identity_id: null,
        role_id: null,
        llm_provider: 'openai',
        llm_model: 'gpt-4o',
        model_id: null,
        system_instruction: null,
        input_type: 'conversation',
        input_schema: null,
        output_type: 'auto',
        output_schema: null,
        output_data_type_id: null,
        output_data_type_name: null,
        sop_bindings: [],
        skill_bindings: [],
        is_active: true,
        is_system: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]
    vi.clearAllMocks()
  })

  it('marks the system agent type with the System badge', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    // The badge renders the agents.types.systemBadge i18n key (mocked t).
    expect(screen.getByText('agents.types.systemBadge')).toBeDefined()
  })

  it('disables the edit control for system agent types', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    const editBtn = screen.getByRole('button', { name: 'app.edit' })
    expect((editBtn as HTMLButtonElement).disabled).toBe(true)
  })

  it('disables the delete control for system agent types', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    const deleteBtn = screen.getByRole('button', { name: 'app.delete' })
    expect((deleteBtn as HTMLButtonElement).disabled).toBe(true)
  })

  it('does not mark a non-system agent type with the System badge', async () => {
    mockAgentTypes = [{ ...mockAgentTypes[0], is_system: false, id: 'at-normal', name: 'Normal Agent' }]
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.queryByText('agents.types.systemBadge')).toBeNull()
  })
})
