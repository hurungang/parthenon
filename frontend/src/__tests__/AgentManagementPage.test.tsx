import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { AgentPlan } from '../types'

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

// Override default form values so input_type starts as 'typed', not 'none'.
// This bypasses the primarySop validation in handleSave and lets plan preview tests work.
vi.mock('../pages/agents/AgentTypeForm', async () => {
  const actual = await vi.importActual<typeof import('../pages/agents/AgentTypeForm')>(
    '../pages/agents/AgentTypeForm',
  )
  return {
    ...actual,
    defaultAgentTypeFormValues: { ...actual.defaultAgentTypeFormValues, input_type: 'typed' },
  }
})

const MOCK_AGENT_TYPES = [
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

const MOCK_FAILED_PLAN: AgentPlan = {
  id: 'plan-fail',
  agent_type_id: 'at-fail',
  plan_steps: [],
  topology_nodes: [],
  topology_edges: [],
  generation_status: 'failed',
  generation_error: 'LLM unavailable',
  agent_config_hash: null,
  generated_at: null,
}

// Mutable mock post/put — tests override these per scenario
let mockPostResult: { data: Record<string, unknown> } = { data: {} }
let mockPutResult: { data: Record<string, unknown> } = { data: {} }

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => ({
    data: MOCK_AGENT_TYPES,
    isLoading: false,
    error: null,
  }),
  // useAgentType is called by AgentTypeDetailsDialog when a row is clicked
  useAgentType: () => ({ data: undefined, isLoading: true, error: null }),
  useAgentInstances: () => ({ data: [], isLoading: false }),
  useTerminateInstance: () => ({ mutateAsync: vi.fn(), isPending: false }),
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
    // Tooltip wraps icon button with aria-label agents.types.launch
    expect(screen.getByRole('button', { name: 'agents.types.launch' })).toBeDefined()
  })

  it('opens AgentJobLaunchDialog when Launch is clicked', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    // Find and click the launch button by its accessible name
    const launchBtn = screen.getByRole('button', { name: 'agents.types.launch' })
    await act(async () => {
      fireEvent.click(launchBtn)
    })

    // Launch dialog should open
    await waitFor(() => {
      expect(screen.getByText('agents.sessions.launch')).toBeDefined()
    })
  })

  it('renders Edit button per agent type row', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByRole('button', { name: 'app.edit' })).toBeDefined()
  })
})

// ── Plan preview state management tests ───────────────────────────────────────

describe('AgentManagementPage — plan preview state', () => {
  beforeEach(() => {
    // Reset mock results before each test
    mockPostResult = { data: {} }
    mockPutResult = { data: {} }
    vi.clearAllMocks()
  })

  it('opens PlanPreviewModal after successful create when response includes plan', async () => {
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
      primary_sop_id: null,
      is_active: true,
      created_at: '2026-05-09T12:00:00Z',
      updated_at: '2026-05-09T12:00:00Z',
      plan: MOCK_PLAN,
    }
    mockPostResult = { data: savedAgentType }

    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    // Open create dialog
    fireEvent.click(screen.getByRole('button', { name: /agents\.createType/i }))

    // Fill in the required name field
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    // Find and fill the name input
    const nameInputs = screen.getAllByRole('textbox')
    const nameInput = nameInputs[0]
    fireEvent.change(nameInput, { target: { value: 'New Agent' } })

    // Click Save
    const saveBtn = screen.getByRole('button', { name: /app\.save/i })
    await act(async () => {
      fireEvent.click(saveBtn)
    })

    // PlanPreviewModal should open — look for plan step names
    await waitFor(() => {
      expect(screen.getByText('Gather Info')).toBeDefined()
    })
  })

  it('opens PlanPreviewModal with failed plan message when generation failed', async () => {
    const savedAgentTypeWithFailedPlan = {
      id: 'at-fail',
      name: 'Failed Plan Agent',
      description: null,
      identity_id: null,
      role_id: null,
      model_id: null,
      system_instruction: null,
      input_type: 'typed',
      input_schema: null,
      output_type: 'markdown',
      output_schema: null,
      primary_sop_id: null,
      is_active: true,
      created_at: '2026-05-09T12:00:00Z',
      updated_at: '2026-05-09T12:00:00Z',
      plan: MOCK_FAILED_PLAN,
    }
    mockPostResult = { data: savedAgentTypeWithFailedPlan }

    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    fireEvent.click(screen.getByRole('button', { name: /agents\.createType/i }))

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    const nameInputs = screen.getAllByRole('textbox')
    fireEvent.change(nameInputs[0], { target: { value: 'Failed Plan Agent' } })

    const saveBtn = screen.getByRole('button', { name: /app\.save/i })
    await act(async () => {
      fireEvent.click(saveBtn)
    })

    // Plan modal should open with the error message
    await waitFor(() => {
      expect(screen.getByText('agents.plan.generationFailed')).toBeDefined()
    })
    // The generation_error text should be visible
    await waitFor(() => {
      expect(screen.getByText('LLM unavailable')).toBeDefined()
    })
  })

  it('does not open PlanPreviewModal when save response has no plan field', async () => {
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
      primary_sop_id: null,
      is_active: true,
      created_at: '2026-05-09T12:00:00Z',
      updated_at: '2026-05-09T12:00:00Z',
      // no plan field
    }
    mockPostResult = { data: savedAgentTypeNoPlan }

    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    fireEvent.click(screen.getByRole('button', { name: /agents\.createType/i }))

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    const nameInputs = screen.getAllByRole('textbox')
    fireEvent.change(nameInputs[0], { target: { value: 'No Plan Agent' } })

    const saveBtn = screen.getByRole('button', { name: /app\.save/i })
    await act(async () => {
      fireEvent.click(saveBtn)
    })

    // Plan modal should NOT open — no previewTitle i18n key in the DOM
    await waitFor(() => {
      // The edit/create dialog should have closed
      expect(screen.queryByText('agents.plan.previewTitle')).toBeNull()
    })
  })
})

// ── Role and identity column tests ────────────────────────────────────────────

describe('AgentManagementPage — role and identity columns', () => {
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
    // MOCK_AGENT_TYPES has role_id: null, apiClient.get returns [] for roles
    // so roleMap is empty and the cell falls back to '—'
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    // Multiple '—' may appear (model, role, identity) — verify at least one
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(1)
  })

  it('shows role name in Role column when resolved from API', async () => {
    // Temporarily add a role_id to the mock agent type and mock apiClient
    // to return role data so the role name resolves in the table
    const originalRoleId = MOCK_AGENT_TYPES[0].role_id
    MOCK_AGENT_TYPES[0].role_id = 'role-1'

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
    MOCK_AGENT_TYPES[0].role_id = originalRoleId
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
